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
  student_repositories_cfg = resolved.get("student_repositories")
  if not isinstance(student_repositories_cfg, dict):
    raise ConfigError("student_repositories must be configured")

  secret = student_repositories_cfg.get("token_secret")
  if not isinstance(secret, str) or secret.strip().casefold() in TOKEN_SECRET_PLACEHOLDERS:
    raise ConfigError(
      "student_repositories.token_secret must be a non-empty private course secret"
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
  student_repositories = resolved.get("student_repositories")
  if not isinstance(student_repositories, dict):
    raise ConfigError("student_repositories must be configured")

  required = ("course_code", "cohort_slug", "github_org", "base_repo_name", "base_repo_url")
  missing = [key for key in required if not isinstance(resolved.get(key), str) or not resolved[key]]
  if missing:
    raise ConfigError("Missing student repository settings: " + ", ".join(missing))

  base_branch = str(student_repositories.get("base_branch", "base"))
  index_branch = str(student_repositories.get("base_index_branch", "main"))
  return {
    "course_code": str(resolved["course_code"]),
    "cohort_slug": str(resolved["cohort_slug"]),
    "github_org": str(resolved["github_org"]),
    "base_repo_name": str(resolved["base_repo_name"]),
    "base_repo_url": str(resolved["base_repo_url"]),
    "base_branch": base_branch,
    "index_branch": index_branch,
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


def _build_publication_tree(root: Path, config: dict[str, Any], target: str) -> list[Path]:
  render_tree(root, config, target)
  remove_template_sources(root)
  prune_tree(root, config, target)
  redacted = redact_tree(root, config, target)
  return redacted


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
) -> int:
  resolved = resolve_target(config, target)
  settings = repository_settings(resolved)
  helper = GitHelper(source_root)
  helper.ensure_branch(source_branch)
  validate_dirty_state(helper, config, target, source_branch, allow_dirty)
  current_branch = helper.repo.active_branch.name

  info(f"Publishing cohort base for {target}")
  print(f"  Base repository: {settings['base_repo_name']}")
  print(f"  Base branch: {settings['base_branch']}")
  print(f"  Blank slate: {'yes' if blank_slate else 'no'}")
  if not confirm("Continue with base publication? (y/N): "):
    info("Base publication cancelled.")
    return 0

  base_url = settings["base_repo_url"]
  if not dry_run:
    gh = github_client()
    org = gh.get_organization(settings["github_org"])
    base_repo, _ = _get_or_create_repo(
      org,
      settings["base_repo_name"],
      f"Redacted course base for {settings['course_code']} {settings['cohort_slug']}",
    )
    base_url = base_repo.clone_url
  with helper.temporary_clone(keep=keep_temp) as (worktree_repo, tempdir):
    previous_base = None
    if not blank_slate and not dry_run:
      previous_base = _fetch_base_commit(worktree_repo, base_url, settings["base_branch"])
    _checkout_orphan_branch(worktree_repo, settings["base_branch"], f"origin/{source_branch}")
    worktree_root = Path(worktree_repo.working_tree_dir or ".")
    try:
      redacted = _build_publication_tree(worktree_root, config, target)
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

    if previous_base is not None:
      try:
        worktree_repo.git.diff("--cached", "--quiet", previous_base.hexsha)
      except GitCommandError:
        pass
      else:
        info("No base content changes detected.")
        return 0

    message = f"Publish {settings['cohort_slug']} base: {datetime.date.today().isoformat()}"
    parents = [previous_base] if previous_base is not None else []
    worktree_repo.index.commit(message, parent_commits=parents)
    if dry_run:
      info("Dry run enabled: skipping base push.")
      return 0

    push_args = [base_url, f"{settings['base_branch']}:{settings['base_branch']}"]
    if blank_slate or previous_base is None:
      push_args.insert(0, "--force")
    worktree_repo.git.push(*push_args)

  success(f"Published {settings['base_repo_name']}:{settings['base_branch']}")
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
  student_repo_url: str,
  token: str,
) -> None:
  """Create a student's main branch from the base and add its private token."""
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
    base_clone.git.push(student_repo_url, f"{base_branch}:main")


def provision_student_repositories(
  config: dict[str, Any],
  target: str,
  *,
  dry_run: bool,
) -> int:
  resolved = resolve_target(config, target)
  settings = repository_settings(resolved)
  student_list = resolved.get("student_list")
  if not isinstance(student_list, str) or not student_list:
    raise ConfigError(f"Target '{target}' must define student_list before provisioning")
  emails = read_student_emails(Path(student_list))
  students = student_repositories(resolved, emails)
  # Validate the shared secret before prompting or creating GitHub resources.
  student_token_secret(resolved)
  staff = staff_members(resolved)
  staff_team_name = f"{settings['course_code']}:{settings['cohort_slug']}:staff"

  info(f"Provisioning {len(students)} student repositories for {target}")
  for student in students:
    print(f"  - {student.repository_name}")
  print(f"  Staff team: {staff_team_name} ({len(staff)} configured member(s), Maintain access)")
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

  if not confirm("Create missing teams and repositories? (y/N): "):
    info("Student provisioning cancelled.")
    return 0

  cohort_team, _ = _get_or_create_team(
    org,
    f"{settings['course_code']}:{settings['cohort_slug']}:base-readers",
    f"Read access to the {settings['cohort_slug']} course base",
  )
  cohort_team.set_repo_permission(base_repo, "pull")
  staff_team, _ = _get_or_create_team(
    org,
    staff_team_name,
    f"Staff access to {settings['cohort_slug']} student repositories",
  )
  for member in staff:
    _add_staff_member(gh, org, staff_team, member)

  newly_invited: list[str] = []
  already_invited_or_members: list[str] = []
  for student in students:
    info(f"Provisioning {student.repository_name}")
    base_invitation_created = _invite_email_to_team(org, cohort_team, student.email)
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
    if base_invitation_created or repository_invitation_created:
      newly_invited.append(student.email)
    else:
      already_invited_or_members.append(student.email)
    student_team.set_repo_permission(student_repo, "push")
    staff_team.set_repo_permission(student_repo, "maintain")

    try:
      student_repo.get_branch("main")
      initialized = True
    except UnknownObjectException:
      initialized = False

    if not initialized:
      _initialize_student_repository(
        base_url,
        settings["base_branch"],
        student_repo.clone_url,
        student_token(resolved, student.email),
      )
      student_repo.edit(default_branch="main")

  _write_base_index(base_url, settings, students)
  base_repo.edit(default_branch=settings["index_branch"])
  print("Invitation update:")
  if newly_invited:
    print("  New organization invitation sent:")
    for email in newly_invited:
      print(f"    - {email}")
  else:
    print("  No new organization invitations sent.")
  if already_invited_or_members:
    print("  No new invitation (already a member or invitation pending):")
    for email in already_invited_or_members:
      print(f"    - {email}")
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
  )


def run_provision_student_repositories(args: argparse.Namespace) -> int:
  config = load_config(Path(args.config))
  return provision_student_repositories(config, args.target, dry_run=args.dry_run)
