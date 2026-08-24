#!/usr/bin/env python3
"""Resolve course publish targets and render template files."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

DEFAULT_CONFIG_PATH = "course-config.yaml"


class ConfigError(Exception):
  pass


class TemplateError(Exception):
  pass


class RedactionError(Exception):
  pass


def merge_values(base: Any, override: Any) -> Any:
  if isinstance(base, dict) and isinstance(override, dict):
    merged = dict(base)
    for key, value in override.items():
      if key in merged:
        merged[key] = merge_values(merged[key], value)
      else:
        merged[key] = value
    return merged
  if isinstance(base, list) and isinstance(override, list):
    return list(base) + list(override)
  return override


def load_config(path: Path) -> dict[str, Any]:
  if not path.exists():
    raise ConfigError(f"Configuration file not found: {path}")

  with path.open("r", encoding="utf-8") as fh:
    data = yaml.safe_load(fh)

  if data is None:
    raise ConfigError(f"Configuration file is empty: {path}")
  if not isinstance(data, dict):
    raise ConfigError("Configuration file must contain a YAML mapping at the top level")
  if "targets" not in data or not isinstance(data["targets"], dict):
    raise ConfigError("Config must contain a 'targets' mapping")
  return data


def resolve_target(config: dict[str, Any], target: str) -> dict[str, Any]:
  defaults = config.get("defaults", {})
  modes = config.get("modes", {})
  targets = config["targets"]
  if target not in targets:
    raise ConfigError(
      f"Unknown target '{target}'. Available targets: {', '.join(sorted(targets))}"
    )

  resolved: dict[str, Any] = {}
  if isinstance(defaults, dict):
    resolved = merge_values(resolved, defaults)
  mode = targets[target].get("mode")
  if mode is not None:
    if not isinstance(mode, str) or mode not in modes:
      raise ConfigError(f"Target '{target}' references unknown mode '{mode}'")
    if not isinstance(modes[mode], dict):
      raise ConfigError(f"Mode '{mode}' must be a mapping")
    resolved = merge_values(resolved, modes[mode])
  resolved = merge_values(resolved, targets[target])
  resolved["target"] = target
  if mode is not None:
    resolved["mode"] = mode

  student_repositories = resolved.get("student_repositories", {})
  cohort_slug = resolved.get("cohort_slug")
  course_code = resolved.get("course_code")
  github_org = resolved.get("github_org")
  if (
    isinstance(student_repositories, dict)
    and isinstance(cohort_slug, str)
    and isinstance(course_code, str)
    and isinstance(github_org, str)
  ):
    # Course repository names are intentionally derived only here so rendered
    # templates and management commands share one documented naming rule.
    base_repo_name = f"{course_code}-{cohort_slug}-base"
    resolved["base_repo_name"] = base_repo_name
    resolved["base_repo_url"] = f"https://github.com/{github_org}/{base_repo_name}.git"

  return resolved


def resolve_target_choice(args: Any) -> str:
  if getattr(args, "target", None):
    return args.target
  raise ConfigError("--target is required")


def should_render(rel_path: str, patterns: list[str], exclude_dirs: list[str]) -> bool:
  """Return whether a selected render path is outside excluded directories.

  ``render_tree`` selects files with ``Path.glob`` so it can support recursive
  glob patterns correctly; ``patterns`` is retained for this helper's public
  signature.
  """
  normalized = rel_path.replace(os.sep, "/")
  for excluded in exclude_dirs:
    excluded_normalized = _normalize_pattern(excluded).rstrip("/")
    prefix = excluded_normalized + "/"
    if normalized == excluded_normalized or normalized.startswith(prefix):
      return False
  return True


def includes_all_paths(include_patterns: list[str]) -> bool:
  """An empty include list or ["*"] means keep everything before exclusions."""
  return not include_patterns or include_patterns == ["*"]


def load_publish_cfg(config: dict[str, Any], target: str) -> tuple[dict[str, Any], dict[str, Any]]:
  resolved = resolve_target(config, target)
  publish_cfg = resolved.get("publish", {})
  if not isinstance(publish_cfg, dict):
    raise ConfigError("'publish' must be a mapping")
  return resolved, publish_cfg


def _normalize_path(path: str) -> str:
  normalized = path.replace(os.sep, "/")
  while normalized.startswith("./"):
    normalized = normalized[2:]
  return normalized


def _normalize_pattern(pattern: str) -> str:
  normalized = pattern.replace(os.sep, "/")
  while normalized.startswith("./"):
    normalized = normalized[2:]
  return normalized


def _is_git_internal(rel_path: str) -> bool:
  normalized = _normalize_path(rel_path)
  return normalized == ".git" or normalized.startswith(".git/")


def path_in_publish_surface(
  include_patterns: list[str],
  exclude_patterns: list[str],
  rel_path: str,
) -> bool:
  normalized = _normalize_path(rel_path)
  included = includes_all_paths(include_patterns) or any(
    fnmatch.fnmatch(normalized, _normalize_pattern(pattern)) for pattern in include_patterns
  )
  if not included:
    return False
  return not any(fnmatch.fnmatch(normalized, _normalize_pattern(pattern)) for pattern in exclude_patterns)


def path_affects_publish(
  config: dict[str, Any],
  target: str,
  rel_path: str,
) -> bool:
  normalized = _normalize_path(rel_path)
  resolved, publish_cfg = load_publish_cfg(config, target)
  include_patterns = list(publish_cfg.get("include", []))
  exclude_patterns = list(publish_cfg.get("exclude", []))
  render_patterns = list(resolved.get("render_paths", []))

  if any(fnmatch.fnmatch(normalized, _normalize_pattern(pattern)) for pattern in render_patterns):
    return True

  for entry in publish_cfg.get("redact", []):
    if not isinstance(entry, dict):
      continue

    patterns: list[str] = []
    if isinstance(entry.get("path"), str):
      patterns.append(entry["path"])
    if isinstance(entry.get("paths"), list):
      patterns.extend([
        value for value in entry["paths"]
        if isinstance(value, str)
      ])

    if any(fnmatch.fnmatch(normalized, _normalize_pattern(pattern)) for pattern in patterns):
      return True

  return path_in_publish_surface(
    include_patterns,
    exclude_patterns,
    normalized,
  )


def _remove_empty_directories(root: Path) -> list[Path]:
  removed: list[Path] = []
  for path in sorted(root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
    if not path.is_dir() or path.is_symlink():
      continue
    rel_path = path.relative_to(root).as_posix()
    if _is_git_internal(rel_path):
      continue
    try:
      path.rmdir()
      removed.append(path)
    except OSError:
      continue
  return removed


def prune_tree(root: Path, config: dict[str, Any], target: str) -> list[Path]:
  _, publish_cfg = load_publish_cfg(config, target)
  include_patterns = list(publish_cfg.get("include", []))
  exclude_patterns = list(publish_cfg.get("exclude", []))

  pruned: list[Path] = []
  for path in root.rglob("*"):
    if path.is_dir() and not path.is_symlink():
      continue

    rel_path = path.relative_to(root).as_posix()
    if _is_git_internal(rel_path):
      continue
    if not path_in_publish_surface(
      include_patterns,
      exclude_patterns,
      rel_path,
    ):
      path.unlink()
      pruned.append(path)

  pruned.extend(_remove_empty_directories(root))
  return pruned


def _parse_ctags_functions(path: Path) -> list[dict[str, Any]]:
  try:
    result = subprocess.run(
      [
        "ctags",
        "--output-format=json",
        "--kinds-C=f",
        "--fields=+ne",
        "-o",
        "-",
        str(path),
      ],
      check=True,
      capture_output=True,
      text=True,
    )
  except FileNotFoundError as exc:  # pragma: no cover - environment issue
    raise RedactionError(
      "ctags is not available. Install universal ctags to enable automated redaction."
    ) from exc
  except subprocess.CalledProcessError as exc:
    raise RedactionError(f"ctags failed for {path}: {exc.stderr.strip() or exc}") from exc

  functions: list[dict[str, Any]] = []
  for line in result.stdout.splitlines():
    if not line.strip():
      continue
    try:
      entry = json.loads(line)
    except json.JSONDecodeError as exc:
      raise RedactionError(f"ctags produced invalid JSON for {path}: {line}") from exc
    if entry.get("_type") != "tag" or entry.get("kind") != "function":
      continue
    if not isinstance(entry.get("line"), int) or not isinstance(entry.get("end"), int):
      raise RedactionError(f"ctags did not provide line bounds for {path}: {entry}")
    functions.append(entry)
  return functions


def _stub_return_expr(typeref: str) -> str | None:
  if not typeref.startswith("typename:"):
    return None

  type_name = typeref.removeprefix("typename:").strip()
  if not type_name or type_name == "void":
    return None
  if "*" in type_name:
    return "NULL"
  if type_name in {"bool", "_Bool"}:
    return "(bool){0}"
  return f"({type_name}){{0}}"


def redact_c_functions(path: Path) -> None:
  lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
  replacements: list[tuple[int, int, list[str]]] = []

  for entry in _parse_ctags_functions(path):
    start = int(entry["line"]) - 1
    end = int(entry["end"]) - 1
    name = str(entry.get("name", path.name))
    typeref = str(entry.get("typeref", ""))

    if start < 0 or end >= len(lines) or start > end:
      raise RedactionError(f"ctags returned invalid bounds for {name} in {path}")

    signature_line = lines[start]
    signature_indent = re.match(r"[ \t]*", signature_line).group(0)
    body_indent = signature_indent + "  "

    stub_lines = [f"{body_indent}// todo\n"]
    return_expr = _stub_return_expr(typeref)
    if return_expr is not None:
      stub_lines.append(f"{body_indent}return {return_expr};\n")

    replacements.append((start + 1, end, stub_lines))

  for start, end, replacement_lines in sorted(replacements, reverse=True):
    lines[start:end] = replacement_lines

  path.write_text("".join(lines), encoding="utf-8")


def redact_tree(root: Path, config: dict[str, Any], target: str) -> list[Path]:
  _, publish_cfg = load_publish_cfg(config, target)
  redactions = list(publish_cfg.get("redact", []))
  if not redactions:
    return []

  normalized_redactions: list[dict[str, Any]] = []
  for entry in redactions:
    if not isinstance(entry, dict):
      raise ConfigError("Each publish.redact entry must be a mapping")
    mode = entry.get("mode")
    if not isinstance(mode, str) or not mode:
      raise ConfigError("Each publish.redact entry must include a non-empty 'mode'")

    patterns: list[str] = []
    path_value = entry.get("path")
    if isinstance(path_value, str) and path_value:
      patterns.append(path_value)

    paths_value = entry.get("paths")
    if isinstance(paths_value, list):
      patterns.extend([
        value for value in paths_value
        if isinstance(value, str) and value
      ])

    if not patterns:
      raise ConfigError(
        "Each publish.redact entry must include a non-empty 'path' or 'paths'"
      )

    normalized_redactions.append({
      "mode": mode,
      "patterns": [_normalize_pattern(pattern) for pattern in patterns],
    })

  redacted: list[Path] = []
  redacted_seen: set[str] = set()

  for entry in normalized_redactions:
    matches: list[Path] = []
    for path in root.rglob("*"):
      if not path.is_file():
        continue
      rel_path = path.relative_to(root).as_posix()
      if _is_git_internal(rel_path):
        continue
      if any(fnmatch.fnmatch(rel_path, pattern) for pattern in entry["patterns"]):
        matches.append(path)

    mode = entry["mode"]
    for path in matches:
      rel_path = path.relative_to(root).as_posix()
      if mode == "empty":
        path.write_text("", encoding="utf-8")
      elif mode == "c-function-stubs":
        redact_c_functions(path)
      else:
        raise ConfigError(f"Unknown publish.redact mode '{mode}' for {rel_path}")

      if rel_path not in redacted_seen:
        redacted.append(path)
        redacted_seen.add(rel_path)

  return redacted


def list_redaction_matches(root: Path, config: dict[str, Any], target: str) -> list[str]:
  _, publish_cfg = load_publish_cfg(config, target)
  redactions = list(publish_cfg.get("redact", []))
  if not redactions:
    return []

  matches: set[str] = set()
  for entry in redactions:
    if not isinstance(entry, dict):
      raise ConfigError("Each publish.redact entry must be a mapping")

    patterns: list[str] = []
    path_value = entry.get("path")
    if isinstance(path_value, str) and path_value:
      patterns.append(path_value)

    paths_value = entry.get("paths")
    if isinstance(paths_value, list):
      patterns.extend([
        value for value in paths_value
        if isinstance(value, str) and value
      ])

    if not patterns:
      raise ConfigError(
        "Each publish.redact entry must include a non-empty 'path' or 'paths'"
      )

    normalized_patterns = [_normalize_pattern(pattern) for pattern in patterns]
    for path in root.rglob("*"):
      if not path.is_file():
        continue
      rel_path = path.relative_to(root).as_posix()
      if _is_git_internal(rel_path):
        continue
      if any(fnmatch.fnmatch(rel_path, pattern) for pattern in normalized_patterns):
        matches.add(rel_path)

  return sorted(matches)


def render_template(
  root: Path,
  rel_path: str,
  context: dict[str, Any],
  env: Environment | None = None,
) -> str:
  if env is None:
    env = Environment(
      loader=FileSystemLoader(str(root)),
      undefined=StrictUndefined,
      autoescape=False,
      trim_blocks=False,
      lstrip_blocks=False,
      keep_trailing_newline=True,
    )

  try:
    return env.get_template(rel_path).render(**context)
  except UnicodeDecodeError as exc:
    raise TemplateError(f"Template file is not valid UTF-8: {rel_path}") from exc
  except Exception as exc:
    raise TemplateError(f"Failed to render template {rel_path}: {exc}") from exc


def validate_rendered_content(
  rel_path: str,
  content: str,
  forbidden_strings: list[str],
  *,
  allow_deferred_student_repo_url: bool = False,
) -> None:
  unresolved = re.findall(r"({{.*?}}|{%.+?%})", content, re.S)
  allowed_deferred_expression = re.compile(r"{{\s*student_repo_url\s*}}")
  if unresolved and not (
    allow_deferred_student_repo_url
    and all(allowed_deferred_expression.fullmatch(expression) for expression in unresolved)
  ):
    raise TemplateError(f"Unresolved template syntax remains in {rel_path}")
  for forbidden in forbidden_strings:
    if forbidden and forbidden in content:
      raise TemplateError(
        f"Forbidden string '{forbidden}' found in rendered file {rel_path}"
      )


def render_tree(
  root: Path,
  config: dict[str, Any],
  target: str,
  *,
  defer_student_repo_url: bool = False,
) -> list[Path]:
  resolved = resolve_target(config, target)
  if defer_student_repo_url:
    # The cohort base is shared by all students. Keep this one expression for
    # the per-student provisioning pass, when the repository URL is known.
    resolved["student_repo_url"] = "{{ student_repo_url }}"
  patterns = list(resolved.get("render_paths", []))
  exclude_dirs = list(resolved.get("render_exclude_dirs", []))
  forbidden_strings = list(resolved.get("forbidden_strings", []))

  if not patterns:
    raise ConfigError("No render_paths configured")

  rendered_files: list[Path] = []
  matched_patterns: set[str] = set()
  matched_files: dict[Path, set[str]] = {}
  env = Environment(
    loader=FileSystemLoader(str(root)),
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
  )

  # Path.glob provides normal glob semantics, including recursive ** patterns.
  # In particular, **/README.md.j2 matches README templates at any depth.
  for pattern in patterns:
    normalized_pattern = _normalize_pattern(pattern)
    for path in root.glob(normalized_pattern):
      if not path.is_file():
        continue
      rel_path = path.relative_to(root).as_posix()
      if _is_git_internal(rel_path):
        continue
      matched_files.setdefault(path, set()).add(pattern)

  for path in sorted(matched_files, key=lambda candidate: candidate.as_posix()):
    rel_path = path.relative_to(root).as_posix()
    if not should_render(rel_path, patterns, exclude_dirs):
      continue
    matched_patterns.update(matched_files[path])

    rendered = render_template(root, rel_path, resolved, env)

    output_path = path.with_suffix("") if path.name.endswith(".j2") else path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    output_path.chmod(stat.S_IMODE(path.stat().st_mode))
    rendered_files.append(output_path)

  for path in rendered_files:
    rel_path = path.relative_to(root).as_posix()
    content = path.read_text(encoding="utf-8")
    validate_rendered_content(
      rel_path,
      content,
      forbidden_strings,
      allow_deferred_student_repo_url=defer_student_repo_url,
    )

  missing_patterns = sorted(set(patterns) - matched_patterns)
  if missing_patterns:
    raise TemplateError(
      "No files matched the configured render paths: " + ", ".join(missing_patterns)
    )
  return rendered_files


def render_student_repository_tree(
  root: Path,
  config: dict[str, Any],
  target: str,
  student_repo_url: str,
) -> list[Path]:
  """Resolve deferred student repository URLs in a private repository copy."""
  resolved = resolve_target(config, target)
  resolved["student_repo_url"] = student_repo_url
  forbidden_strings = list(resolved.get("forbidden_strings", []))
  env = Environment(
    loader=FileSystemLoader(str(root)),
    undefined=StrictUndefined,
    autoescape=False,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
  )
  rendered_files: list[Path] = []

  for path in root.rglob("*"):
    if not path.is_file():
      continue
    rel_path = path.relative_to(root).as_posix()
    if _is_git_internal(rel_path):
      continue
    content = path.read_text(encoding="utf-8")
    if "{{ student_repo_url" not in content:
      continue
    rendered = render_template(root, rel_path, resolved, env)
    path.write_text(rendered, encoding="utf-8")
    path.chmod(stat.S_IMODE(path.stat().st_mode))
    validate_rendered_content(rel_path, rendered, forbidden_strings)
    rendered_files.append(path)

  return rendered_files
