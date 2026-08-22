#!/usr/bin/env python3
"""Sync rendered course syllabi to the shared syllabi repository."""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path
from typing import Any

import yaml
from git import Actor, InvalidGitRepositoryError, NoSuchPathError, PushInfo, Repo

from .console import info, success
from .course_config import (
  ConfigError,
  TemplateError,
  load_config,
  render_template,
  resolve_target,
  validate_rendered_content,
)


def _front_matter(values: dict[str, str]) -> str:
  body = yaml.safe_dump(
    values,
    allow_unicode=True,
    default_flow_style=False,
    sort_keys=False,
  )
  return f"---\n{body}---\n\n"


def _render_syllabus(
  source_root: Path,
  config: dict[str, Any],
  target: str,
) -> tuple[str, str | None]:
  resolved = resolve_target(config, target)
  published_course_code = str(resolved.get("published_course_code") or resolved.get("course_code", ""))
  course_name = str(resolved.get("course_name", ""))
  if not published_course_code or not course_name:
    raise ConfigError(f"Target '{target}' must define course_code and course_name")

  syllabus_template = source_root / "syllabus.md.j2"
  if not syllabus_template.exists():
    raise ConfigError(f"Syllabus template not found: {syllabus_template}")

  syllabus_content = render_template(source_root, "syllabus.md.j2", resolved)
  validate_rendered_content(
    "syllabus.md.j2",
    syllabus_content,
    list(resolved.get("forbidden_strings", [])),
  )

  calendar_path = source_root / "calendar.md"
  calendar_content = calendar_path.read_text(encoding="utf-8") if calendar_path.exists() else None
  calendar_url = str(resolved.get("calendar_url", ""))
  calendar_link = calendar_url or (
    f"/{published_course_code}-calendar.html" if calendar_content is not None else ""
  )

  today = datetime.date.today().isoformat()
  syllabus_metadata = {
    "layout": "default",
    "course_code": published_course_code,
    "course_name": course_name,
    "title": f"{published_course_code} - {course_name}",
    "last_updated": today,
  }
  if calendar_link:
    syllabus_metadata["course_calendar"] = calendar_link

  syllabus_content = syllabus_content.replace(
    "syllabus.md",
    f"{published_course_code}-syllabus.html",
  ).replace(
    "calendar.md",
    f"{published_course_code}-calendar.html",
  )

  syllabus_output = _front_matter(syllabus_metadata) + syllabus_content
  calendar_output: str | None = None
  if calendar_content is not None:
    calendar_metadata = {
      "layout": "default",
      "course_code": published_course_code,
      "course_name": course_name,
      "title": f"{published_course_code} Course Calendar",
      "last_updated": today,
    }
    calendar_output = _front_matter(calendar_metadata) + calendar_content

  return syllabus_output, calendar_output


def build_syllabus_assets(
  source_root: Path,
  config: dict[str, Any],
  targets: list[str],
) -> dict[Path, str]:
  assets: dict[Path, str] = {}
  for target in targets:
    resolved = resolve_target(config, target)
    published_course_code = str(resolved.get("published_course_code") or resolved.get("course_code", ""))
    syllabus_content, calendar_content = _render_syllabus(source_root, config, target)
    assets[Path("_active") / f"{published_course_code}-syllabus.md"] = syllabus_content
    if calendar_content is not None:
      assets[Path("_active") / f"{published_course_code}-calendar.md"] = calendar_content
  return assets


def _changed_assets(destination_root: Path, assets: dict[Path, str]) -> list[Path]:
  changed: list[Path] = []
  for relative_path, content in assets.items():
    output_path = destination_root / relative_path
    if not output_path.exists() or output_path.read_text(encoding="utf-8") != content:
      changed.append(relative_path)
  return changed


def _destination_repo(destination_root: Path) -> Repo:
  try:
    return Repo(destination_root)
  except (InvalidGitRepositoryError, NoSuchPathError) as exc:
    raise ConfigError(f"Destination is not a git repository: {destination_root}") from exc


def sync_syllabi(
  source_root: Path,
  destination_root: Path,
  config: dict[str, Any],
  targets: list[str],
  commit_message: str,
  *,
  dry_run: bool = False,
  push: bool = True,
) -> list[Path]:
  if not targets:
    raise ConfigError("At least one --target is required")

  source_root = source_root.resolve()
  destination_root = destination_root.resolve()
  destination_repo = _destination_repo(destination_root)
  if destination_repo.is_dirty(untracked_files=True):
    raise ConfigError("Destination repository is not clean; commit or stash changes first")

  assets = build_syllabus_assets(source_root, config, targets)
  changed = _changed_assets(destination_root, assets)
  if not changed:
    info("No syllabus changes to sync.")
    return []

  if dry_run:
    info("Dry run: the following syllabus assets would change:")
    for path in changed:
      print(f"  - {path.as_posix()}")
    return changed

  for relative_path, content in assets.items():
    output_path = destination_root / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")

  destination_repo.git.add("-A", "_active")
  if not destination_repo.is_dirty(index=True, working_tree=False, untracked_files=True):
    info("No syllabus changes to sync.")
    return []

  actor = Actor("Course syllabus sync", "action@github.com")
  destination_repo.index.commit(commit_message, author=actor, committer=actor)
  success(f"Committed {len(changed)} syllabus asset(s)")
  if push:
    try:
      push_results = destination_repo.remotes.origin.push()
    except AttributeError as exc:
      raise ConfigError("Destination repository has no origin remote to push") from exc
    failures = [result.summary for result in push_results if result.flags & PushInfo.ERROR]
    if failures:
      raise ConfigError("Failed to push syllabus updates: " + "; ".join(failures))
    success("Pushed syllabus updates")
  return changed


def run_sync_syllabus(args: argparse.Namespace) -> int:
  config = load_config(Path(args.config))
  source_root = Path(args.source_root).resolve()
  destination_root = Path(args.destination).resolve()
  commit_message = args.commit_message or "Update syllabi"

  sync_syllabi(
    source_root,
    destination_root,
    config,
    args.target,
    commit_message,
    dry_run=args.dry_run,
    push=not args.no_push,
  )
  return 0
