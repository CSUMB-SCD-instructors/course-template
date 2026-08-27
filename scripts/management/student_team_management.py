#!/usr/bin/env python3
"""Shared GitHub and roster helpers for cohort access management."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from github import Github

from .course_config import ConfigError


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
