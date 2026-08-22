#!/usr/bin/env python3
"""GitHub student team management."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from github import Github
from github.GithubException import GithubException, UnknownObjectException

from .console import confirm, green, info, red, success
from .course_config import ConfigError, load_config, resolve_target, resolve_target_choice


def parse_repo_name(student_repo_url: str) -> tuple[str, str]:
  match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", student_repo_url)
  if not match:
    raise ConfigError(f"Could not parse GitHub org/repo from URL: {student_repo_url}")
  return match.group(1), match.group(2)


def github_client() -> Github:
  token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
  if not token:
    try:
      result = subprocess.run(
        ["gh", "auth", "token"],
        check=True,
        capture_output=True,
        text=True,
      )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
      raise ConfigError(
        "Set GH_TOKEN or GITHUB_TOKEN, or authenticate with `gh auth login`."
      ) from exc
    token = result.stdout.strip()

  if not token:
    raise ConfigError("GitHub token is empty.")
  return Github(token)


def read_student_emails(path: Path) -> list[str]:
  emails: list[str] = []
  with path.open("r", encoding="utf-8") as fh:
    for line in fh:
      email = line.strip()
      if not email or email.startswith("#"):
        continue
      emails.append(email)
  return emails


def invite_by_email(org, email: str, team_id: int) -> None:
  org._requester.requestJsonAndCheck(
    "POST",
    f"{org.url}/invitations",
    input={
      "email": email,
      "role": "direct_member",
      "team_ids": [team_id],
    },
  )


def resolve_team(org, team_slug: str):
  try:
    return org.get_team_by_slug(team_slug)
  except UnknownObjectException as exc:
    raise ConfigError(f"Team does not exist: {team_slug}") from exc


def create_team(org, repo_name: str, team_name: str, team_slug: str, term: str):
  if team_slug in {team.slug for team in org.get_teams()}:
    raise ConfigError(f"Team already exists: {team_name}")

  repo = org.get_repo(repo_name)
  team = org.create_team(
    name=team_name,
    repo_names=[repo],
    permission="pull",
    privacy="closed",
    description=f"Students for {repo_name} ({term})",
  )
  team.set_repo_permission(repo, "pull")
  return team


def add_students(team, student_file: Path) -> None:
  team_id = team.id
  org = team.organization
  invited = 0
  failed = 0

  for email in read_student_emails(student_file):
    print(f"  Inviting {email:<40}", end=" ")
    try:
      invite_by_email(org, email, team_id)
      print(green("✓"))
      invited += 1
    except GithubException:
      print(red("✗"))
      failed += 1

  success(f"Invited {invited} student(s)")
  if failed:
    info(f"Failed on {failed} student(s)")


def remove_students(team, student_file: Path) -> None:
  removed = 0
  failed = 0

  for identifier in read_student_emails(student_file):
    print(f"  Removing {identifier:<40}", end=" ")
    try:
      team._requester.requestJsonAndCheck(
        "DELETE",
        f"{team.url}/memberships/{identifier}",
      )
      print(green("✓"))
      removed += 1
    except GithubException:
      print(red("✗"))
      failed += 1

  success(f"Removed {removed} student(s)")
  if failed:
    info(f"Failed to remove {failed} student(s)")


def delete_team(team, team_name: str) -> None:
  info("WARNING: this deletes the entire GitHub team.")
  if not confirm(f"Delete '{team_name}'? (y/N): "):
    info("Deletion cancelled.")
    return
  team.delete()
  success("Team deleted.")


def run_student_team_management(args: argparse.Namespace) -> int:
  config = load_config(Path(args.config))
  target = resolve_target_choice(args)
  resolved = resolve_target(config, target)
  student_repo_url = str(resolved.get("student_repo_url", ""))

  if not args.term:
    raise ConfigError("--term is required")

  student_file: Path | None = None
  if args.action != "delete":
    if not args.students:
      raise ConfigError(f"--students is required for action {args.action}")
    student_file = Path(args.students)
    if not student_file.exists():
      raise ConfigError(f"Student file not found: {student_file}")

  org_name, repo_name = parse_repo_name(student_repo_url)
  team_name = f"{repo_name}:students:{args.term}"
  team_slug = team_name.lower().replace(":", "-")

  gh = github_client()
  org = gh.get_organization(org_name)

  info("GitHub Team Management")
  print(f"  Target: {target}")
  print(f"  Organization: {org_name}")
  print(f"  Repository: {repo_name}")
  print(f"  Team Name: {team_name}")
  print(f"  Team Slug: {team_slug}")
  print(f"  Action: {args.action}")
  print("")

  if args.action == "create":
    team = create_team(org, repo_name, team_name, team_slug, args.term)
    if student_file is not None:
      add_students(team, student_file)
  elif args.action == "add":
    if student_file is None:
      raise ConfigError("--students is required for action add")
    add_students(resolve_team(org, team_slug), student_file)
  elif args.action == "remove":
    if student_file is None:
      raise ConfigError("--students is required for action remove")
    remove_students(resolve_team(org, team_slug), student_file)
  elif args.action == "delete":
    delete_team(resolve_team(org, team_slug), team_name)
  else:
    raise ConfigError(f"Unsupported action: {args.action}")

  success("Operation complete.")
  print(f"View team at: https://github.com/orgs/{org_name}/teams/{team_slug}")
  return 0
