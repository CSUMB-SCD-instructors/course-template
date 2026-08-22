#!/usr/bin/env python3
"""Publish the student-facing repository."""

from __future__ import annotations

import argparse
import datetime
import fnmatch
from collections import Counter
from pathlib import Path

from git import Repo

from .console import confirm, info, success, warn
from .course_config import (
  ConfigError,
  load_config,
  path_affects_publish,
  prune_tree,
  redact_tree,
  render_tree,
  resolve_target,
  resolve_target_choice,
)
from .git_helpers import GitHelper

STAGING_BRANCH = "redacted_for_students"
TARGET_BRANCH = "main"


def remove_template_sources(root: Path) -> list[Path]:
  removed: list[Path] = []
  for template_path in root.rglob("*.j2"):
    template_path.unlink()
    removed.append(template_path)
  return removed


def _matching_render_files(root: Path, render_patterns: list[str]) -> list[str]:
  matches: list[str] = []
  for path in root.rglob("*"):
    if not path.is_file():
      continue
    rel_path = path.relative_to(root).as_posix()
    if any(fnmatch.fnmatch(rel_path, pattern) for pattern in render_patterns):
      matches.append(rel_path)
  return sorted(matches)


def summarize_redactions(
  worktree_root: Path,
  redacted_paths: list[Path],
  previous_staging_ref: str | None,
) -> None:
  if not redacted_paths:
    info("No files were redacted.")
    return

  info("Redacted files:")
  for path in redacted_paths:
    print(f"  - {path.relative_to(worktree_root).as_posix()}")

  if previous_staging_ref:
    print("")
    info("Redaction diff summary versus previous redacted_for_students:")
    diff_stat = Repo(worktree_root).git.diff("--stat", previous_staging_ref, "--", *[
      path.relative_to(worktree_root).as_posix() for path in redacted_paths
    ])
    print(diff_stat or "  (no redaction changes versus previous redacted branch)")


def summarize_removed_templates(worktree_root: Path, removed_paths: list[Path]) -> None:
  if not removed_paths:
    return

  info("Removed template source files:")
  for path in removed_paths:
    print(f"  - {path.relative_to(worktree_root).as_posix()}")


def summarize_pruned_paths(worktree_root: Path, pruned_paths: list[Path]) -> None:
  if not pruned_paths:
    info("No files were removed by include/exclude rules.")
    return

  rel_paths = [path.relative_to(worktree_root).as_posix() for path in pruned_paths]
  grouped: Counter[str] = Counter()
  root_files: list[str] = []

  for rel_path in rel_paths:
    if "/" not in rel_path:
      root_files.append(rel_path)
      continue
    top_level = rel_path.split("/", maxsplit=1)[0]
    grouped[top_level] += 1

  info("Files removed by include/exclude rules:")
  for name, count in sorted(grouped.items()):
    suffix = "file" if count == 1 else "files"
    print(f"  - {name}/ ({count} {suffix})")

  if root_files:
    print("  - root files:")
    for rel_path in sorted(root_files):
      print(f"      {rel_path}")


def summarize_publication_tree(worktree_root: Path) -> None:
  top_level_entries = sorted(
    path.name for path in worktree_root.iterdir()
    if path.name != ".git"
  )
  info("Top-level contents of the publication tree:")
  for name in top_level_entries:
    suffix = "/" if (worktree_root / name).is_dir() else ""
    print(f"  - {name}{suffix}")

  file_count = sum(
    1 for path in worktree_root.rglob("*")
    if path.is_file() and ".git" not in path.parts
  )
  print(f"  Total published files: {file_count}")


def validate_dirty_state(
  git_helper: GitHelper,
  config: dict,
  target: str,
  source_branch: str,
  allow_dirty: bool,
) -> None:
  dirty_paths = git_helper.dirty_paths()
  if not dirty_paths:
    return

  relevant = [
    path for path in dirty_paths
    if path_affects_publish(config, target, path)
  ]
  ignored = [path for path in dirty_paths if path not in relevant]

  if ignored:
    warn("Ignoring dirty files outside the publish surface:")
    for path in ignored:
      print(f"  - {path}")

  if not relevant:
    return

  from .console import error
  error("Publish-relevant files have uncommitted changes:")
  for path in relevant:
    print(f"  - {path}")

  message = (
    f"Publish uses the committed state of '{source_branch}', so the files above "
    "will not be included until they are committed."
  )
  if allow_dirty:
    warn(message)
    return

  raise ConfigError(
    message + " Commit or stash them first, or re-run with --allow-dirty to publish anyway."
  )


def run_publish_repo(args: argparse.Namespace) -> int:
  config_path = Path(args.config)
  config = load_config(config_path)
  target = resolve_target_choice(args)
  resolved = resolve_target(config, target)

  source_branch = args.source_branch or str(resolved.get("source_branch", "main"))
  course_code = str(resolved.get("course_code", ""))
  course_name = str(resolved.get("course_name", ""))
  student_repo_url = str(resolved.get("student_repo_url", ""))

  if not course_code:
    raise ConfigError("course_code is not configured")
  if not course_name:
    raise ConfigError("course_name is not configured")

  git_helper = GitHelper(Path(__file__).resolve().parents[2])
  git_helper.ensure_branch(source_branch)
  validate_dirty_state(git_helper, config, target, source_branch, args.allow_dirty)
  current_branch = git_helper.repo.active_branch.name

  info(f"Publishing {source_branch} to student repository")
  print(f"  Target: {target}")
  print(f"  Course Code: {course_code}")
  print(f"  Course Name: {course_name}")
  print(f"  Student Repo: {student_repo_url}")
  print(f"  Staging Branch: {STAGING_BRANCH}")
  print(f"  Dry Run: {'yes' if args.dry_run else 'no'}")
  print(f"  Keep Temp: {'yes' if args.keep_temp else 'no'}")
  print("")

  if not confirm("Continue with publication? (y/N): "):
    info("Publication cancelled.")
    return 0

  default_commit_msg = f"Published to students: {datetime.datetime.now().isoformat(sep=' ', timespec='seconds')}"

  with git_helper.temporary_clone(keep=args.keep_temp) as (worktree_repo, tempdir):
    previous_staging_ref = git_helper.prepare_staging_branch(
      worktree_repo,
      STAGING_BRANCH,
      source_branch,
    )
    worktree_root = Path(worktree_repo.working_tree_dir or ".")

    info("Rendering templates...")
    try:
      render_tree(worktree_root, config, target)
    except Exception as exc:
      render_patterns = list(resolved.get("render_paths", []))
      current_branch_matches = _matching_render_files(git_helper.repo_root, render_patterns)
      source_branch_matches = _matching_render_files(worktree_root, render_patterns)
      if (
        current_branch != source_branch and
        current_branch_matches and
        not source_branch_matches
      ):
        raise ConfigError(
          f"{exc}\nHint: the configured source branch is '{source_branch}', but the current "
          f"branch '{current_branch}' has the template files. Re-run with "
          f"--source-branch {current_branch} or commit/merge those template files into {source_branch}."
        ) from exc
      raise

    info("Dropping template source files...")
    removed_template_paths = remove_template_sources(worktree_root)
    summarize_removed_templates(worktree_root, removed_template_paths)

    info("Applying include/exclude rules...")
    pruned_paths = prune_tree(worktree_root, config, target)
    summarize_pruned_paths(worktree_root, pruned_paths)
    print("")
    summarize_publication_tree(worktree_root)

    # Stage the rendered and pruned baseline. Redactions remain unstaged so
    # they have a focused diff for human review without entering git history.
    worktree_repo.git.add(A=True)

    info("Applying explicit redactions...")
    redacted_paths = redact_tree(worktree_root, config, target)
    summarize_redactions(worktree_root, redacted_paths, previous_staging_ref)

    print("")
    info(f"Review the generated publication tree here: {tempdir}")
    info("Suggested checks:")
    print("  - run `git diff --cached --stat` for rendered, included, and removed files")
    print("  - run `git diff -- <redacted-path>` to inspect each automatic redaction")
    print("  - run `git diff HEAD --stat` to review the complete final publication")

    print("")
    if not confirm("Review the staged publication tree and continue? (y/N): "):
      info("Publication cancelled.")
      return 0

    # Add the reviewed redactions to the staged baseline before committing the
    # single student-visible publication commit.
    worktree_repo.git.add(A=True)
    if git_helper.repo_has_changes(worktree_repo):
      commit_msg = input(f"Commit message [{default_commit_msg}]: ").strip() or default_commit_msg
      worktree_repo.index.commit(commit_msg)
      if args.dry_run:
        info("Dry run enabled: not syncing commit back to local redacted_for_students.")
      else:
        git_helper.sync_branch_back(worktree_repo, STAGING_BRANCH)
        success(f"Created commit on {STAGING_BRANCH}")
    else:
      info("No content changes detected; reusing existing redacted_for_students HEAD.")

    if args.dry_run:
      info("Dry run enabled: skipping push.")
      if args.keep_temp:
        info(f"Temporary publication tree preserved at: {tempdir}")
      success("Dry run complete.")
      return 0

    if not confirm(f"Force-push {STAGING_BRANCH} to {student_repo_url}:{TARGET_BRANCH}? (y/N): "):
      info("Publication cancelled before push.")
      return 0

    worktree_repo.git.push("--force", student_repo_url, f"{STAGING_BRANCH}:{TARGET_BRANCH}")

  success("Publication complete.")
  success(f"Pushed {STAGING_BRANCH} to {student_repo_url}")
  if args.keep_temp:
    info(f"Temporary publication tree preserved at: {tempdir}")
  return 0
