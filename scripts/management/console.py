#!/usr/bin/env python3
"""Shared console helpers."""

from __future__ import annotations

import sys

from colorama import Fore, Style, init as colorama_init

colorama_init()


def info(message: str) -> None:
  print(f"{Fore.YELLOW}{message}{Style.RESET_ALL}")


def success(message: str) -> None:
  print(f"{Fore.GREEN}{message}{Style.RESET_ALL}")


def warn(message: str) -> None:
  print(f"{Fore.MAGENTA}{message}{Style.RESET_ALL}")


def error(message: str) -> None:
  print(f"{Fore.RED}{message}{Style.RESET_ALL}", file=sys.stderr)


def confirm(prompt: str) -> bool:
  return input(prompt).strip().lower().startswith("y")


def green(text: str) -> str:
  return f"{Fore.GREEN}{text}{Style.RESET_ALL}"


def red(text: str) -> str:
  return f"{Fore.RED}{text}{Style.RESET_ALL}"
