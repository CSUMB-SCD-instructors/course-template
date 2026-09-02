#!/usr/bin/env python3
"""Publish safe cohort bases and provision private student repositories."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import hmac
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from git import Actor, GitCommandError, Repo
from github.GithubException import GithubException, UnknownObjectException

from .console import confirm, info, success
from .course_config import (
  ConfigError,
  load_config,
  prune_tree,
  redact_tree,
  render_tree,
  resolve_target,
)
from .git_helpers import GitHelper
from .publish_repo import remove_template_sources, validate_dirty_state
from .student_team_management import github_client, invite_by_email, read_student_emails


@dataclass(frozen=True)
class StudentRepository:
  email: str
  slug: str
  repository_name: str


TOKEN_SECRET_PLACEHOLDERS = {
  "",
  "change-me",
  "change_me",
  "changeme",
  "replace-me",
  "replace_me",
}


def normalized_student_email(email: str) -> str:
  """Return the canonical email form used for repository tokens."""
  normalized = email.strip().casefold()
  if not normalized or "@" not in normalized:
    raise ConfigError(f"Invalid student email for token generation: {email!r}")
  return normalized


def student_token_secret(resolved: dict[str, Any]) -> str:
  per_student_cfg = resolved.get("per_student_repositories")
  if not isinstance(per_student_cfg, dict):
    raise ConfigError("per_student_repositories must be configured")

  secret = per_student_cfg.get("token_secret")
  if not isinstance(secret, str) or secret.strip().casefold() in TOKEN_SECRET_PLACEHOLDERS:
    raise ConfigError(
      "per_student_repositories.token_secret must be a non-empty private course secret"
    )
  return secret


def student_token(resolved: dict[str, Any], email: str) -> str:
  """Derive a stable token that the course server can reproduce from its roster."""
  secret = student_token_secret(resolved)
  settings = repository_settings(resolved)
  message = "\x1f".join((
    "course-student-token-v1",
    settings["course_code"],
    settings["cohort_slug"],
    normalized_student_email(email),
  ))
  return hmac.new(
    secret.encode("utf-8"),
    message.encode("utf-8"),
    hashlib.sha256,
  ).hexdigest()


def student_slug(email: str) -> str:
  local_part = email.split("@", maxsplit=1)[0].lower()
  slug = re.sub(r"[^a-z0-9]+", "-", local_part).strip("-")
  if not slug:
    raise ConfigError(f"Could not derive a repository slug from email: {email}")
  return slug


def repository_settings(resolved: dict[str, Any]) -> dict[str, str]:
  """Return the derived cohort repository settings."""
  required = ("course_code", "cohort_slug", "github_org", "base_repo_name", "base_repo_url")
  missing = [key for key in required if not isinstance(resolved.get(key), str) or not resolved[key]]
  if missing:
    raise ConfigError("Missing student repository settings: " + ", ".join(missing))

  return {
    "course_code": str(resolved["course_code"]),
    "cohort_slug": str(resolved["cohort_slug"]),
    "github_org": str(resolved["github_org"]),
    "base_repo_name": str(resolved["base_repo_name"]),
    "base_repo_url": str(resolved["base_repo_url"]),
    "base_branch": "base",
    "index_branch": "main",
  }


def student_repositories(resolved: dict[str, Any], emails: list[str]) -> list[StudentRepository]:
  settings = repository_settings(resolved)
  seen: set[str] = set()
  students: list[StudentRepository] = []
  for email in emails:
    slug = student_slug(email)
    if slug in seen:
      raise ConfigError(f"Multiple student emails resolve to repository slug '{slug}'")
    seen.add(slug)
    students.append(StudentRepository(
      email=email,
      slug=slug,
      repository_name=f"{settings['course_code']}-{settings['cohort_slug']}-{slug}",
    ))
  return students


def staff_members(resolved: dict[str, Any]) -> list[str]:
  """Return configured staff GitHub usernames or email addresses."""
  staff = resolved.get("staff", [])
  if not isinstance(staff, list) or not all(isinstance(member, str) and member for member in staff):
    raise ConfigError("staff must be a list of non-empty GitHub usernames or email addresses")
  return list(dict.fromkeys(staff))


def _get_or_create_repo(org: Any, name: str, description: str) -> tuple[Any, bool]:
  try:
    return org.get_repo(name), False
  except UnknownObjectException:
    return org.create_repo(name, private=True, auto_init=False, description=description), True


def _get_or_create_team(org: Any, name: str, description: str) -> tuple[Any, bool]:
  slug = name.lower().replace(":", "-")
  try:
    return org.get_team_by_slug(slug), False
  except UnknownObjectException:
    return org.create_team(name=name, privacy="closed", description=description), True


def _invite_email_to_team(org: Any, team: Any, email: str) -> bool:
  """Invite an email address, returning whether GitHub created an invitation.

  GitHub does not distinguish an existing member from an outstanding invitation
  in this endpoint's 422 response, so callers can only report those together.
  """
  try:
    invite_by_email(org, email, team.id)
    return True
  except GithubException as exc:
    # GitHub returns an error when the student is already invited or a member.
    # Those states are both acceptable for repeatable provisioning.
    status = getattr(exc, "status", None)
    if status == 422:  # pragma: no cover - GitHub response
      return False
    if status == 403:
      org_name = getattr(org, "login", "the organization")
      raise ConfigError(
        f"Could not invite {email} to {org_name}. GitHub requires the authenticated "
        "account to be an organization owner and authorized to create organization "
        "invitations. Check `gh auth status`; GitHub CLI tokens typically need "
        "`gh auth refresh -h github.com -s admin:org`."
      ) from exc
    raise


def _add_staff_member(gh: Any, org: Any, team: Any, member: str) -> None:
  """Add a username directly or send an organization invitation by email."""
  if "@" in member:
    _invite_email_to_team(org, team, member)
    return

  try:
    team.add_membership(gh.get_user(member), role="member")
  except GithubException as exc:
    # GitHub returns 422 when this username is already a team member.
    if getattr(exc, "status", None) not in {422}:  # pragma: no cover - GitHub response
      raise


def _build_publication_tree(
  root: Path,
  config: dict[str, Any],
  target: str,
  *,
  per_student_repos: bool,
) -> list[Path]:
  render_tree(root, config, target)
  remove_template_sources(root)
  prune_tree(root, config, target)
  if not per_student_repos:
    update_script = root / "scripts" / "update_from_base.sh"
    if update_script.exists():
      update_script.unlink()
  redacted = redact_tree(root, config, target)
  return redacted


def _require_student_emails(resolved: dict[str, Any], target: str) -> list[str]:
  student_list = resolved.get("student_list")
  if not isinstance(student_list, str) or not student_list:
    raise ConfigError(f"Target '{target}' must define student_list before adding students")
  return read_student_emails(Path(student_list))


def _ensure_base_access(
  gh: Any,
  org: Any,
  base_repo: Any,
  settings: dict[str, str],
  staff: list[str],
  emails: list[str],
) -> Any:
  """Ensure staff and enrolled students have their cohort-level access."""
  staff_team, _ = _get_or_create_team(
    org,
    f"{settings['course_code']}:{settings['cohort_slug']}:staff",
    f"Staff access to {settings['cohort_slug']} course repositories",
  )
  staff_team.set_repo_permission(base_repo, "maintain")
  for member in staff:
    _add_staff_member(gh, org, staff_team, member)

  cohort_team, _ = _get_or_create_team(
    org,
    f"{settings['course_code']}:{settings['cohort_slug']}:base-readers",
    f"Read access to the {settings['cohort_slug']} course base",
  )
  cohort_team.set_repo_permission(base_repo, "pull")
  for email in emails:
    _invite_email_to_team(org, cohort_team, email)

  return staff_team


def _checkout_orphan_branch(repo: Repo, branch_name: str, source_ref: str) -> None:
  if any(head.name == branch_name for head in repo.heads):
    repo.git.checkout(source_ref)
    repo.delete_head(branch_name, force=True)
  repo.git.checkout("--orphan", branch_name, source_ref)


def _fetch_base_commit(repo: Repo, base_url: str, base_branch: str) -> Any | None:
  remote_name = "student-base"
  if remote_name in [remote.name for remote in repo.remotes]:
    remote = repo.remotes[remote_name]
    remote.set_url(base_url)
  else:
    remote = repo.create_remote(remote_name, base_url)
  try:
    remote.fetch(base_branch)
  except GitCommandError:
    return None
  try:
    return repo.commit(f"{remote_name}/{base_branch}")
  except Exception:
    return None


def publish_base(
  source_root: Path,
  config: dict[str, Any],
  target: str,
  *,
  source_branch: str,
  blank_slate: bool,
  allow_dirty: bool,
  dry_run: bool,
  keep_temp: bool,
  per_student_repos: bool = False,
  skip_add_students: bool = False,
) -> int:
  if per_student_repos and skip_add_students:
    raise ConfigError("--per-student-repos cannot be used with --skip-add-students")

  resolved = resolve_target(config, target)
  settings = repository_settings(resolved)
  staff = staff_members(resolved)
  emails = [] if skip_add_students else _require_student_emails(resolved, target)
  if per_student_repos:
    student_token_secret(resolved)
    student_repositories(resolved, emails)
  helper = GitHelper(source_root)
  helper.ensure_branch(source_branch)
  validate_dirty_state(helper, config, target, source_branch, allow_dirty)
  current_branch = helper.repo.active_branch.name

  info(f"Publishing cohort base for {target}")
  print(f"  Base repository: {settings['base_repo_name']}")
  publication_branch = settings["base_branch"] if per_student_repos else settings["index_branch"]
  print(f"  Publication branch: {publication_branch}")
  print(f"  Per-student repositories: {'yes' if per_student_repos else 'no'}")
  print(f"  Add students: {'no' if skip_add_students else 'yes'}")
  print(f"  Blank slate: {'yes' if blank_slate else 'no'}")
  if not confirm("Continue with base publication? (y/N): "):
    info("Base publication cancelled.")
    return 0

  base_url = settings["base_repo_url"]
  gh = None
  org = None
  base_repo = None
  if not dry_run:
    gh = github_client()
    org = gh.get_organization(settings["github_org"])
    base_repo, _ = _get_or_create_repo(
      org,
      settings["base_repo_name"],
      f"Student materials for {settings['course_code']} {settings['cohort_slug']}",
    )
    base_url = base_repo.clone_url
  with helper.temporary_clone(keep=keep_temp) as (worktree_repo, tempdir):
    previous_base = None
    if not blank_slate and not dry_run:
      previous_base = _fetch_base_commit(worktree_repo, base_url, publication_branch)
    _checkout_orphan_branch(worktree_repo, publication_branch, f"origin/{source_branch}")
    worktree_root = Path(worktree_repo.working_tree_dir or ".")
    try:
      redacted = _build_publication_tree(
        worktree_root,
        config,
        target,
        per_student_repos=per_student_repos,
      )
    except Exception as exc:
      if current_branch != source_branch:
        raise ConfigError(
          f"{exc}\nHint: the configured source branch is '{source_branch}', but the current "
          f"branch '{current_branch}' may contain the required templates. Re-run with "
          f"--source-branch {current_branch} or commit/merge those templates into {source_branch}."
        ) from exc
      raise
    worktree_repo.git.add(A=True)

    info(f"Prepared {len(redacted)} redacted file(s) in {tempdir}")
    if not confirm("Review the generated base tree and continue? (y/N): "):
      info("Base publication cancelled.")
      return 0

    has_content_changes = True
    if previous_base is not None:
      try:
        worktree_repo.git.diff("--cached", "--quiet", previous_base.hexsha)
      except GitCommandError:
        pass
      else:
        info("No base content changes detected.")
        if dry_run:
          return 0
        # Access management still runs below so newly enrolled students are
        # invited even when the published course files have not changed.
        has_content_changes = False

    if has_content_changes:
      message = f"Publish {settings['cohort_slug']} materials: {datetime.date.today().isoformat()}"
      parents = [previous_base] if previous_base is not None else []
      worktree_repo.index.commit(message, parent_commits=parents)
      if dry_run:
        info("Dry run enabled: skipping base push.")
        return 0

      push_args = [base_url, f"{publication_branch}:{publication_branch}"]
      if blank_slate or previous_base is None:
        push_args.insert(0, "--force")
      worktree_repo.git.push(*push_args)

  if dry_run:
    return 0

  assert gh is not None and org is not None and base_repo is not None
  if per_student_repos:
    provision_student_repositories(
      config,
      target,
      dry_run=False,
      confirm_changes=False,
    )
  elif not skip_add_students:
    _ensure_base_access(gh, org, base_repo, settings, staff, emails)
    base_repo.edit(default_branch=settings["index_branch"])
  else:
    staff_team, _ = _get_or_create_team(
      org,
      f"{settings['course_code']}:{settings['cohort_slug']}:staff",
      f"Staff access to {settings['cohort_slug']} course repositories",
    )
    staff_team.set_repo_permission(base_repo, "maintain")
    for member in staff:
      _add_staff_member(gh, org, staff_team, member)
    base_repo.edit(default_branch=settings["index_branch"])

  success(f"Published {settings['base_repo_name']}:{publication_branch}")
  return 0


def base_index_readme(
  settings: dict[str, str],
  students: list[StudentRepository],
) -> str:
  """Render the default-branch directory without exposing course material."""
  lines = [
    f"# {settings['course_code']} {settings['cohort_slug']} Student Repositories",
    "",
    "Course materials are on the `base` branch. This branch is a directory of student repositories.",
    "",
    "| Student | Repository |",
    "| --- | --- |",
  ]
  for student in sorted(students, key=lambda candidate: candidate.slug.casefold()):
    repository_url = (
      f"https://github.com/{settings['github_org']}/{student.repository_name}"
    )
    lines.append(f"| {student.slug} | [GitHub repository]({repository_url}) |")
  lines.append("")
  return "\n".join(lines)


def _write_base_index(
  base_url: str,
  settings: dict[str, str],
  students: list[StudentRepository],
) -> None:
  with tempfile.TemporaryDirectory(prefix="course-base-index-") as raw_tempdir:
    root = Path(raw_tempdir)
    repo = Repo.clone_from(base_url, root, branch=settings["base_branch"])
    _checkout_orphan_branch(repo, settings["index_branch"], settings["base_branch"])
    repo.git.rm("-rf", ".", ignore_unmatch=True)
    repo.git.clean("-fdx")
    (root / "README.md").write_text(
      base_index_readme(settings, students),
      encoding="utf-8",
    )
    repo.git.add(A=True)
    actor = Actor("Course management", "course-management@example.invalid")
    repo.index.commit("Update student repository index", author=actor, committer=actor)
    repo.git.push("--force", base_url, f"{settings['index_branch']}:{settings['index_branch']}")


def _initialize_student_repository(
  base_url: str,
  base_branch: str,
  student_repository_remote: str,
  token: str,
  config: dict[str, Any],
  target: str,
  *,
  force: bool = False,
) -> None:
  """Create a student's ``base`` and ``main`` branches from the course base.

  ``base`` deliberately has no student-specific token.  It is a copy of the
  shared course base that lives in the student's own remote, so students can
  fetch ``origin/base`` without having to configure a second remote.
  """
  with tempfile.TemporaryDirectory(prefix="course-student-repo-") as raw_tempdir:
    base_clone = Repo.clone_from(base_url, raw_tempdir, branch=base_branch)
    root = Path(base_clone.working_tree_dir or raw_tempdir)
    (root / ".env").write_text(f"STUDENT_TOKEN={token}\n", encoding="utf-8")
    base_clone.git.add(".env")
    actor = Actor("Course management", "course-management@example.invalid")
    base_clone.index.commit(
      "Add student usage token",
      author=actor,
      committer=actor,
    )
    # Publish the unmodified course commit first.  main then receives the
    # student-only .env commit below it.
    base_push_args = [student_repository_remote, f"{base_branch}:{base_branch}"]
    if force:
      base_push_args.insert(0, "--force")
    base_clone.git.push(*base_push_args)
    push_args = [student_repository_remote, f"{base_branch}:main"]
    if force:
      push_args.insert(0, "--force")
    base_clone.git.push(*push_args)


def _sync_student_base_branch(
  base_url: str,
  base_branch: str,
  student_repository_remote: str,
) -> None:
  """Make a student's base branch exactly match the latest course base.

  The course publisher owns this branch.  Force-pushing is intentional: a
  release can have orphan history after ``--blank-slate``, and student work
  belongs on main rather than on the update source.
  """
  with tempfile.TemporaryDirectory(prefix="course-student-base-") as raw_tempdir:
    base_clone = Repo.clone_from(base_url, raw_tempdir, branch=base_branch)
    base_clone.git.push(
      "--force",
      student_repository_remote,
      f"{base_branch}:{base_branch}",
    )


def provision_student_repositories(
  config: dict[str, Any],
  target: str,
  *,
  dry_run: bool,
  overwrite_existing: bool = False,
  confirm_changes: bool = True,
) -> int:
  resolved = resolve_target(config, target)
  settings = repository_settings(resolved)
  emails = _require_student_emails(resolved, target)
  students = student_repositories(resolved, emails)
  # Validate the shared secret before prompting or creating GitHub resources.
  student_token_secret(resolved)
  staff = staff_members(resolved)

  info(f"Provisioning {len(students)} student repositories for {target}")
  for student in students:
    print(f"  - {student.repository_name}")
  print(f"  Staff members: {len(staff)} configured (Maintain access)")
  if overwrite_existing:
    print("  Existing student main branches: WILL BE REPLACED from the current base")
  if dry_run:
    info("Dry run enabled: no teams or repositories will be created.")
    return 0

  gh = github_client()
  org = gh.get_organization(settings["github_org"])
  try:
    base_repo = org.get_repo(settings["base_repo_name"])
    base_repo.get_branch(settings["base_branch"])
  except UnknownObjectException as exc:
    raise ConfigError(
      f"Publish {settings['base_repo_name']}:{settings['base_branch']} before provisioning students"
    ) from exc
  base_url = base_repo.clone_url

  if confirm_changes:
    confirmation = (
      "Overwrite existing student main branches from the current base? (y/N): "
      if overwrite_existing
      else "Create missing teams and repositories? (y/N): "
    )
    if not confirm(confirmation):
      info("Student provisioning cancelled.")
      return 0

  staff_team = _ensure_base_access(gh, org, base_repo, settings, staff, emails)

  for student in students:
    info(f"Provisioning {student.repository_name}")
    student_repo, _ = _get_or_create_repo(
      org,
      student.repository_name,
      f"Private {settings['course_code']} repository for {student.slug}",
    )
    student_team, _ = _get_or_create_team(
      org,
      f"{student.repository_name}:student",
      f"Write access to {student.repository_name}",
    )
    repository_invitation_created = _invite_email_to_team(org, student_team, student.email)
    if repository_invitation_created:
      info(f"Invited {student.email} to {student.repository_name}")
    student_team.set_repo_permission(student_repo, "push")
    staff_team.set_repo_permission(student_repo, "maintain")

    try:
      student_repo.get_branch("main")
      initialized = True
    except UnknownObjectException:
      initialized = False

    if not initialized or overwrite_existing:
      _initialize_student_repository(
        base_url,
        settings["base_branch"],
        student_repo.clone_url,
        student_token(resolved, student.email),
        config,
        target,
        force=overwrite_existing,
      )
      student_repo.edit(default_branch="main")
    else:
      _sync_student_base_branch(
        base_url,
        settings["base_branch"],
        student_repo.clone_url,
      )

  _write_base_index(base_url, settings, students)
  base_repo.edit(default_branch=settings["index_branch"])
  success("Student repository provisioning complete.")
  return 0


def run_publish_base(args: argparse.Namespace) -> int:
  config = load_config(Path(args.config))
  return publish_base(
    Path(args.source_root),
    config,
    args.target,
    source_branch=args.source_branch or str(resolve_target(config, args.target).get("source_branch", "main")),
    blank_slate=args.blank_slate,
    allow_dirty=args.allow_dirty,
    dry_run=args.dry_run,
    keep_temp=args.keep_temp,
    per_student_repos=args.per_student_repos,
    skip_add_students=args.skip_add_students,
  )
