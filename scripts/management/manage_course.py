#!/usr/bin/env python3
"""Course management CLI."""

from __future__ import annotations

import argparse
import sys

from .console import error
from .course_config import DEFAULT_CONFIG_PATH, ConfigError, RedactionError, TemplateError
from .publish_repo import run_publish_repo
from .student_repositories import run_provision_student_repositories, run_publish_base
from .student_team_management import run_student_team_management
from .syllabus_sync import run_sync_syllabus


def build_parser() -> argparse.ArgumentParser:
  parser = argparse.ArgumentParser(
    description="Manage course publication, student repositories, teams, and syllabi.",
    epilog="""Common workflows:
  Publish a legacy shared repository:
    python scripts/manage_course.py publish-repo --target <cohort>

  Publish and provision a per-student cohort:
    python scripts/manage_course.py publish-base --target <cohort>
    python scripts/manage_course.py provision-student-repos --target <cohort>

  Render and sync one or more syllabi:
    python scripts/manage_course.py sync-syllabus --destination ../syllabi \\
      --target <cohort>

Run `python scripts/manage_course.py <command> --help` for command-specific options.""",
    formatter_class=argparse.RawDescriptionHelpFormatter,
  )
  subparsers = parser.add_subparsers(dest="command", required=True)

  publish = subparsers.add_parser("publish-repo", help="Publish the student-facing repository")
  publish.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Use custom YAML configuration file")
  publish.add_argument("--target", required=True, help="Publish cohort target name")
  publish.add_argument("--source-branch", help="Override the configured source branch")
  publish.add_argument(
    "--allow-dirty",
    action="store_true",
    help="Allow publish to continue even if publish-relevant files have uncommitted changes",
  )
  publish.add_argument(
    "--dry-run",
    action="store_true",
    help="Build and validate the student-facing tree without updating redacted_for_students or pushing",
  )
  publish.add_argument(
    "--keep-temp",
    action="store_true",
    help="Keep the temporary publication clone on disk for inspection after the command exits",
  )

  base = subparsers.add_parser("publish-base", help="Publish a redacted cohort base repository")
  base.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Use custom YAML configuration file")
  base.add_argument("--target", required=True, help="Cohort target name")
  base.add_argument("--source-root", default=".", help="Course repository root")
  base.add_argument("--source-branch", help="Override the configured source branch")
  base.add_argument(
    "--allow-dirty",
    action="store_true",
    help="Allow publication to continue when publish-relevant files have uncommitted changes",
  )
  base.add_argument("--blank-slate", action="store_true", help="Replace the base branch with new orphan history")
  base.add_argument("--dry-run", action="store_true", help="Build and review without pushing")
  base.add_argument("--keep-temp", action="store_true", help="Keep the generated temporary clone")

  provision = subparsers.add_parser(
    "provision-student-repos",
    help="Create private student repositories and email-invited access teams",
  )
  provision.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Use custom YAML configuration file")
  provision.add_argument("--target", required=True, help="Cohort target name")
  provision.add_argument("--dry-run", action="store_true", help="Report planned repositories without creating them")

  teams = subparsers.add_parser("student-team", help="Manage GitHub teams for student repo access")
  teams.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Use custom YAML configuration file")
  teams.add_argument("--target", required=True, help="Course cohort target name")
  teams.add_argument("--students", help="File containing student emails, one per line")
  teams.add_argument("--term", help="Academic term, e.g. fall2026")
  teams.add_argument(
    "--action",
    default="create",
    choices=["create", "add", "remove", "delete"],
    help="GitHub team action",
  )

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
    if args.command == "publish-repo":
      return run_publish_repo(args)
    if args.command == "publish-base":
      return run_publish_base(args)
    if args.command == "provision-student-repos":
      return run_provision_student_repositories(args)
    if args.command == "student-team":
      return run_student_team_management(args)
    if args.command == "sync-syllabus":
      return run_sync_syllabus(args)
    raise ConfigError(f"Unknown command: {args.command}")
  except (ConfigError, TemplateError, RedactionError) as exc:
    error(f"Error: {exc}")
    return 1


if __name__ == "__main__":
  raise SystemExit(main())
