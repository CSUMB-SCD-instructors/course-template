#!/usr/bin/env python3
"""Shared git helpers for course-management scripts."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

from .course_config import ConfigError


class GitHelper:
  def __init__(self, repo_root: Path):
    try:
      self.repo = Repo(repo_root)
    except (InvalidGitRepositoryError, NoSuchPathError) as exc:
      raise ConfigError(f"Not a git repository: {repo_root}") from exc

    self.repo_root = Path(self.repo.working_tree_dir or repo_root).resolve()

  def branch_exists(self, branch_name: str) -> bool:
    return any(head.name == branch_name for head in self.repo.heads)

  def ensure_branch(self, branch_name: str) -> None:
    if not self.branch_exists(branch_name):
      raise ConfigError(f"Branch does not exist: {branch_name}")

  def dirty_paths(self) -> list[str]:
    status_lines = self.repo.git.status("--short", "--untracked-files=all").splitlines()
    dirty: list[str] = []
    for line in status_lines:
      if not line:
        continue
      rel_path = line[3:]
      if " -> " in rel_path:
        rel_path = rel_path.split(" -> ", maxsplit=1)[1]
      dirty.append(rel_path)
    return dirty

  @contextmanager
  def temporary_clone(self, *, keep: bool = False) -> Iterator[tuple[Repo, Path]]:
    tempdir = Path(tempfile.mkdtemp(prefix="course-publish-", dir=tempfile.gettempdir()))
    try:
      clone_repo = Repo.clone_from(self.repo_root.as_posix(), tempdir.as_posix())
      yield clone_repo, tempdir
    finally:
      if not keep:
        shutil.rmtree(tempdir, ignore_errors=True)

  def prepare_staging_branch(self, clone_repo: Repo, branch_name: str, source_branch: str) -> str | None:
    source_ref = f"origin/{source_branch}"
    staging_ref = f"origin/{branch_name}"
    remote_refs = {ref.name for ref in clone_repo.remotes.origin.refs}

    if source_ref not in remote_refs:
      raise ConfigError(f"Source branch does not exist in clone: {source_branch}")

    if any(head.name == branch_name for head in clone_repo.heads):
      clone_repo.git.checkout(source_ref)
      clone_repo.delete_head(branch_name, force=True)

    # Build every publication on an orphan branch. The resulting commit has no
    # parents, so forcing it to the student repository cannot expose source or
    # prior publication history through the student-facing branch.
    clone_repo.git.checkout("--orphan", branch_name, source_ref)
    return staging_ref if staging_ref in remote_refs else None

  def repo_has_changes(self, repo: Repo) -> bool:
    return repo.is_dirty(untracked_files=True)

  def sync_branch_back(self, clone_repo: Repo, branch_name: str) -> None:
    try:
      clone_repo.git.push("--force", self.repo_root.as_posix(), f"{branch_name}:{branch_name}")
    except GitCommandError:
      pass
