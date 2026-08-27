#!/usr/bin/env python3
"""Course management CLI."""

from __future__ import annotations

import argparse
import sys

from .console import error
from .course_config import DEFAULT_CONFIG_PATH, ConfigError, RedactionError, TemplateError
from .student_repositories import run_publish_base
from .syllabus_sync import run_sync_syllabus


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Manage course publication, student repositories, teams, and syllabi.",
    epilog="""Common workflows:
  Publish one shared cohort repository:
    python scripts/manage_course.py publish-base --target <cohort>

  Publish and provision a per-student cohort:
    python scripts/manage_course.py publish-base --target <cohort> --per-student-repos

  Render and sync one or more syllabi:
    python scripts/manage_course.py sync-syllabus --destination ../syllabi \\
      --target <cohort>

Run `python scripts/manage_course.py <command> --help` for command-specific options.""",
    formatter_class=argparse.RawDescriptionHelpFormatter,
  )
  subparsers = parser.add_subparsers(dest="command", required=True)

  base = subparsers.add_parser("publish-base", help="Publish a redacted cohort repository and grant access")
  base.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Use custom YAML configuration file")
  base.add_argument("--target", required=True, help="Cohort target name")
  base.add_argument("--source-root", default=".", help="Course repository root")
  base.add_argument("--source-branch", help="Override the configured source branch")
  base.add_argument(
    "--allow-dirty",
    action="store_true",
    help="Allow publication to continue when publish-relevant files have uncommitted changes",
  )
  base.add_argument("--blank-slate", action="store_true", help="Replace the publication branch with new orphan history")
  base.add_argument(
    "--per-student-repos",
    action="store_true",
    help="Also create private student repositories; materials use base and main becomes their index",
  )
  base.add_argument(
    "--skip-add-students",
    action="store_true",
    help="Publish without reading the roster or granting student access",
  )
  base.add_argument("--dry-run", action="store_true", help="Build and review without pushing")
  base.add_argument("--keep-temp", action="store_true", help="Keep the generated temporary clone")

  syllabus = subparsers.add_parser("sync-syllabus", help="Render and sync syllabi to a syllabi repository")
  syllabus.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Use custom YAML configuration file")
  syllabus.add_argument(
    "--target",
    action="append",
    required=True,
    help="Target to sync; specify once for each target",
  )
  syllabus.add_argument(
    "--destination",
    required=True,
    help="Path to a checked-out syllabi repository",
  )
  syllabus.add_argument(
    "--source-root",
    default=".",
    help="Course repository root containing syllabus.md.j2",
  )
  syllabus.add_argument("--commit-message", help="Commit message for the syllabus update")
  syllabus.add_argument(
    "--dry-run",
    action="store_true",
    help="Report generated syllabus changes without writing, committing, or pushing",
  )
  syllabus.add_argument(
    "--no-push",
    action="store_true",
    help="Commit changes locally without pushing the destination repository",
  )

  return parser


def main() -> int:
  parser = build_parser()
  args = parser.parse_args()

  try:
    if args.command == "publish-base":
      return run_publish_base(args)
    if args.command == "sync-syllabus":
      return run_sync_syllabus(args)
    raise ConfigError(f"Unknown command: {args.command}")
  except (ConfigError, TemplateError, RedactionError) as exc:
    error(f"Error: {exc}")
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
