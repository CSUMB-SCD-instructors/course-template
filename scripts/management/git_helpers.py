#!/usr/bin/env python3
"""Shared git helpers for course-management scripts."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from git import InvalidGitRepositoryError, NoSuchPathError, Repo

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
