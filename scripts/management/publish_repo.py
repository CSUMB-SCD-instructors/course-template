"""Helpers shared by cohort publication workflows."""

from __future__ import annotations

from pathlib import Path

from .console import error, warn
from .course_config import ConfigError, path_affects_publish
from .git_helpers import GitHelper


def remove_template_sources(root: Path) -> list[Path]:
  removed: list[Path] = []
  for template_path in root.rglob("*.j2"):
    template_path.unlink()
    removed.append(template_path)
  return removed


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
