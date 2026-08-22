#!/usr/bin/python

import dataclasses
import yaml
import argparse
import collections
import json
import logging
import os
import subprocess
from argparse import Namespace
import pprint
from typing import List
from collections import defaultdict
import re

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    from colorama import Fore, Style, init
    init()  # Initialize colorama
    HAS_COLORAMA = True
except ImportError:
    # Fallback if colorama not available
    class Fore:
        GREEN = ""
        RED = ""
        YELLOW = ""
    class Style:
        RESET_ALL = ""
    HAS_COLORAMA = False

logging.basicConfig()
log = logging.getLogger()
log.setLevel(logging.DEBUG)

@dataclasses.dataclass
class GradingResult:
  grade : float
  comments : str
  logs : str
  err: bool


class GradingFailException(Exception):
  """Exception raised when grading cannot proceed (build failure, test errors, etc)"""
  def __init__(self, grade=0.0, comments="", logs="", is_error=True):
    self.grade = grade
    self.comments = comments
    self.logs = logs
    self.is_error = is_error
    super().__init__(comments)


class ScoringItem(object):
  pass

class ScoringGroup(ScoringItem):
  def __init__(self, name, value):
    self.name = name
    self.value = value
    self.tests = []

class ScoringTest(ScoringItem):
  def __init__(self, suite, test_group, value, test_name=None):
    self.suite = suite
    self.test_group = test_group
    self.value = value
    self.test_name = test_name if test_name is not None else test_group

class Test(object):
  def __init__(self, name, num_assertions, status):
    self.name = name
    self.num_assertions = num_assertions
    self.status = status
    self.value = 0
  def __str__(self):
    return f"{self.name}:{self.status}"
  def set_value(self, value):
    self.value = value

  def get_score(self):
    return self.value if self.status == "PASSED" else 0.0

  @classmethod
  def create_from_dict(cls, json_dict):
    return cls(
      json_dict["name"],
      json_dict["assertions"],
      json_dict["status"]
    )

class Suite(object):
  def __init__(self, name, passed, failed, errored, skipped, tests=[]):
    self.name = name
    self.passed = passed
    self.failed = failed
    self.errored = errored
    self.skipped = skipped
    self.tests = dict()
    for test in tests:
      self.tests[test.name] = test
  def add_test(self, test):
    self.tests[test.name] = test

  def get_score(self):
    results = { "PASSED" : [], "FAILED" : [], "RESERVED" : [] }
    score = 0.0
    for t in self.tests.values():
      score += t.get_score()
      if t.status == "PASSED":
        results["PASSED"].append(t.name)
      else:
        results["FAILED"].append(t.name)
    return score, results

  def __str__(self):
    return f"{self.name} : ({self.passed}/{len(self.tests)}"
  @classmethod
  def create_from_dict(cls, json_dict):
    new_suite = cls(
      json_dict["name"],
      json_dict["passed"],
      json_dict["failed"],
      json_dict["errored"],
      json_dict["skipped"]
    )
    for test_dict in json_dict["tests"]:
      new_suite.add_test(Test.create_from_dict(test_dict))
    return new_suite

class Results(object):
  def __init__(self, passed, failed, errored, skipped, suites=[]):
    self.passed = passed
    self.failed = failed
    self.errored = errored
    self.skipped = skipped
    self.suites = dict()
    for suite in suites:
      self.suites[suite.name] = suite
  def add_suite(self, suite):
    self.suites[suite.name] = suite
  def __str__(self):
    return f"Results: {self.passed} / {sum([len(suite.tests.keys()) for (name, suite) in self.suites.items()])}"

  def get_score(self, scoring_tests=None):
    results = {}
    score = 0.0
    for s in self.suites.values():
      suite_score, suite_results = s.get_score()
      score += suite_score
      results[s.name] = suite_results

      # Add only MISSING configured reserve tests to RESERVED array
      if scoring_tests:
        configured_reserve_tests = [st.test_name for st in scoring_tests
                                   if st.suite == s.name and st.test_name.startswith("RESERVE_")]
        # Find tests that ran (in PASSED or FAILED)
        ran_tests = set(suite_results["PASSED"] + suite_results["FAILED"])
        # Only include configured reserve tests that didn't run
        missing_reserve_tests = [test_name for test_name in configured_reserve_tests
                                if test_name not in ran_tests]
        results[s.name]["RESERVED"] = missing_reserve_tests

    return score, results

  def score(self, scoring_tests: List[ScoringTest]):
    # First pass: filter out missing reserve tests and group by test group
    available_scoring_tests = []
    reserve_tests_found = 0
    reserve_tests_missing = 0
    test_groups = {}  # test_group -> (total_value, [available_tests])

    for score in scoring_tests:
      suite = self.suites.get(score.suite)
      if suite is None:
        if score.test_name.startswith("RESERVE_"):
          log.debug(f"Skipping missing reserve test suite: {score.suite}")
          reserve_tests_missing += 1
          continue
        else:
          log.error(f"Missing required test suite: {score.suite}")
          continue

      test = suite.tests.get(score.test_name)
      if test is None:
        if score.test_name.startswith("RESERVE_"):
          log.debug(f"Skipping missing reserve test: {score.test_name}")
          reserve_tests_missing += 1
          continue
        else:
          log.error(f"Missing required test: {score.test_name}")
          continue

      available_scoring_tests.append(score)
      if score.test_name.startswith("RESERVE_"):
        reserve_tests_found += 1

      # Group tests by test group for recalculating points
      group_key = f"{score.suite}.{score.test_group}"
      if group_key not in test_groups:
        test_groups[group_key] = (score.value, [])
      test_groups[group_key][1].append(score)

    # Recalculate points per test for each group
    adjusted_scoring_tests = []
    for group_key, (total_value, tests) in test_groups.items():
      # Find the original group total value by looking at the scoring config
      # All tests in a group should have the same total when multiplied by count
      original_tests_in_group = [s for s in scoring_tests if f"{s.suite}.{s.test_group}" == group_key]
      if original_tests_in_group:
        # Calculate original total: first test's individual value * total test count in group
        original_total_value = original_tests_in_group[0].value * len(original_tests_in_group)
      else:
        original_total_value = total_value

      # Recalculate points per available test to maintain group total
      points_per_test = original_total_value / len(tests) if tests else 0

      for test_score in tests:
        # Create new scoring test with adjusted value
        adjusted_test = ScoringTest(
          test_score.suite,
          test_score.test_group,
          points_per_test,
          test_score.test_name
        )
        adjusted_scoring_tests.append(adjusted_test)

    # Apply adjusted scores
    for score in adjusted_scoring_tests:
      suite = self.suites[score.suite]
      test = suite.tests[score.test_name]
      test.set_value(score.value)

    if reserve_tests_found > 0:
      log.info(f"Found {reserve_tests_found} reserve tests for enhanced grading")
    if reserve_tests_missing > 0:
      log.debug(f"Skipped {reserve_tests_missing} missing reserve tests")

  @classmethod
  def create_from_dict(cls, json_dict):
    new_result = cls(
      json_dict["passed"],
      json_dict["failed"],
      json_dict["errored"],
      json_dict["skipped"]
    )
    for suite_dict in json_dict["test_suites"]:
      new_result.add_suite(Suite.create_from_dict(suite_dict))
    return new_result


def parse_flags():
  parser = argparse.ArgumentParser()

  parser.add_argument(
    "--PA", "--pa",
    required=True,
    help="Name of the PA (e.g. \"PA1\") to grade.  If it matches Canvas or your LMS it can be easier."
  )
  parser.add_argument(
    "--output-path",
    dest="output_path",
    default="/tmp/feedback.yaml",
    help="Override for where to output the feedback.yaml file."
  )

  return parser.parse_args()


def run_unittests(path_to_assignment_directory):
  os.chdir(path_to_assignment_directory)

  # Run tests with JSON output and capture stderr for log messages
  json_file = "/tmp/unittest_results.json"
  proc = subprocess.Popen([
    "./unit_tests", "-j1", f"--json={json_file}"
  ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  proc.wait()

  stdout = proc.stdout.read().decode('latin-1')
  stderr = proc.stderr.read().decode('latin-1')

  # Log stderr which contains the log_info messages from tests
  log.info(f"Test stderr output: {stderr}")

  # Read the JSON results with error-resilient encoding
  try:
    with open(json_file, 'r', encoding='utf-8', errors='replace') as f:
      json_content = f.read()
  except FileNotFoundError:
    # Fallback to stdout if file wasn't created
    json_content = stdout

  results = parse_unit_tests_json(json_content)
  return results, stderr

def parse_unit_tests_json(in_lines) -> Results:
  json_lines = fix_json(in_lines)
  json_dict = json.loads(json_lines)

  results = Results.create_from_dict(json_dict)
  return results

def fix_json(json_str):
  in_lines = json_str.split('\n')
  out_lines = []
  curr_line_i = 0
  while curr_line_i < len(in_lines):
    if "messages" in in_lines[curr_line_i]:
      out_lines[-1] = out_lines[-1][:-1]
      # Then we suspect we'll be starting to messages field
      # for right now we'll just skip it -- going forward we may actually fix it
      #while in_lines[curr_line_i].strip() != ']':
      while not in_lines[curr_line_i].strip().endswith(']'):
        curr_line_i += 1
      else:
        curr_line_i += 1

    out_lines.append(in_lines[curr_line_i])
    curr_line_i += 1
  return '\n'.join(out_lines)

def get_scoring_tests_new_format(config_dict):
  """Parse new hierarchical YAML format: Suite -> TestGroup -> Tests"""
  scoring_tests = []

  for suite_name, suite_content in config_dict.items():
    if isinstance(suite_content, dict):
      # Handle nested test groups within suites
      for test_group_name, test_group_config in suite_content.items():
        if isinstance(test_group_config, dict) and "tests" in test_group_config:
          tests_data = test_group_config["tests"]
          total_value = test_group_config.get("value", 0)

          if isinstance(tests_data, dict):
            # Tests with individual point values
            for test_name, point_value in tests_data.items():
              scoring_tests.append(
                ScoringTest(
                  suite_name,
                  test_group_name,
                  point_value,
                  test_name
                )
              )
          elif isinstance(tests_data, list):
            # Tests with evenly distributed points
            points_per_test = total_value / len(tests_data) if tests_data else 0
            for test_name in tests_data:
              scoring_tests.append(
                ScoringTest(
                  suite_name,
                  test_group_name,
                  points_per_test,
                  test_name
                )
              )
    elif isinstance(suite_content, list):
      # Legacy fallback: suite contains direct test group configs
      for test_group_config in suite_content:
        if isinstance(test_group_config, dict) and "tests" in test_group_config:
          test_group_name = test_group_config.get("test_group", suite_name.lower())
          tests_data = test_group_config["tests"]
          total_value = test_group_config.get("value", 0)

          if isinstance(tests_data, dict):
            for test_name, point_value in tests_data.items():
              scoring_tests.append(
                ScoringTest(
                  suite_name,
                  test_group_name,
                  point_value,
                  test_name
                )
              )
          elif isinstance(tests_data, list):
            points_per_test = total_value / len(tests_data) if tests_data else 0
            for test_name in tests_data:
              scoring_tests.append(
                ScoringTest(
                  suite_name,
                  test_group_name,
                  points_per_test,
                  test_name
                )
              )

  return scoring_tests

def get_scoring_tests(tests):
  scoring_tests = []
  for test_group in tests:
    if "tests" in test_group.keys():
      tests_data = test_group["tests"]
      if isinstance(tests_data, dict):
        # New format: tests is a dict with test names as keys and point values as values
        for test_name, point_value in tests_data.items():
          scoring_tests.append(
            ScoringTest(
              test_group["suite"],
              test_group["test_group"],
              point_value,
              test_name
            )
          )
      elif isinstance(tests_data, list):
        # Old format: tests is a list, divide points evenly
        for test in tests_data:
          scoring_tests.append(
            ScoringTest(
              test_group["suite"],
              test_group["test_group"],
              test_group["value"] / len(tests_data),
              test
            )
          )
    else:
      scoring_tests.append(
        ScoringTest(
          test_group["suite"],
          test_group["test_group"],
          test_group["value"]
        )
      )
  return scoring_tests

def load_scoring_config(assignment_dir):
  """Load scoring config - now supports RESERVE_ tests mixed in main file"""
  yaml_path = os.path.join(assignment_dir, "scoring.yaml")
  json_path = os.path.join(assignment_dir, "scoring.json")

  # Load main config
  main_config = None
  if os.path.exists(yaml_path):
    with open(yaml_path) as fid:
      if HAS_YAML:
        main_config = yaml.safe_load(fid)
      else:
        log.warning(f"YAML file found ({yaml_path}) but PyYAML not available.")
        return []
  elif os.path.exists(json_path):
    with open(json_path) as fid:
      main_config = json.load(fid)

  if main_config is None:
    return []

  return get_scoring_tests_new_format(main_config) if ("tests" not in main_config and "groups" not in main_config) else parse_scoring_legacy(main_config)

def parse_scoring_legacy(config_dict):
  """Handle legacy format parsing"""
  if "groups" in config_dict.keys():
    groups = []
    for group in config_dict["groups"]:
      scoring_group = ScoringGroup(group["name"], group["value"])
      scoring_group.tests = get_scoring_tests(config_dict["tests"])
      groups.append(group)
    return groups
  if "tests" in config_dict.keys():
    return get_scoring_tests(config_dict["tests"])
  return []

def make_test(path_to_assignment_directory):
  os.chdir(path_to_assignment_directory)
  proc = subprocess.Popen(["make", "unit_tests"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
  proc.wait()

  stdout = proc.stdout.read().decode()
  stderr = proc.stderr.read().decode()

  if proc.returncode == 0:
    return True, stderr
  else:
    return False, stderr

def make_lint(path_to_assignment_directory):
  os.chdir(path_to_assignment_directory)
  proc = subprocess.Popen(["make check"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
  proc.wait()

  stdout = proc.stdout.read().decode()
  stderr = proc.stderr.read().decode()

  log.debug(f"stdout: {stdout}")
  log.debug(f"stderr: {stderr}")

  if proc.returncode == 0:
    return True, stdout + "\n\n" + stderr
  else:
    return False, stdout + "\n\n" + stderr


def _do_grade(PA, assignment_dir, scoring_tests):
  """Core grading logic - raises GradingFailException on failure"""
  # Initialize results storage
  all_logs = []
  comments_parts = []

  # Build tests
  build_success, build_log = make_test(assignment_dir)
  all_logs.append(f"Build Log:\n{build_log}")

  if not build_success:
    raise GradingFailException(
      grade=0.0,
      comments="Build failed - cannot run tests.\n\n***Note, if you are debugging code using `make grade` please use `make` for debugging instead!***",
      logs="\n\n".join(all_logs),
      is_error=False  # Build failure is expected, not an error
    )

  comments_parts.append("Build: SUCCESS")

  # Run lint check
  lint_success, lint_log = make_lint(assignment_dir)
  all_logs.append(f"Lint Log:\n{lint_log}")

  if lint_success:
    comments_parts.append("Lint: PASSED")
  else:
    comments_parts.append("Lint: FAILED")

  # Run unit tests and capture raw results
  # Use enhanced test runner that captures stderr output
  test_results, test_stderr = run_unittests(assignment_dir)

  # Create a serializable version of the test results
  raw_test_results = {
    'passed': test_results.passed,
    'failed': test_results.failed,
    'errored': test_results.errored,
    'skipped': test_results.skipped,
    'test_suites': []
  }

  for suite_name, suite in test_results.suites.items():
    suite_data = {
      'name': suite_name,
      'passed': suite.passed,
      'failed': suite.failed,
      'errored': suite.errored,
      'skipped': suite.skipped,
      'tests': []
    }
    for test_name, test in suite.tests.items():
      suite_data['tests'].append({
        'name': test_name,
        'status': test.status,
        'assertions': test.num_assertions
      })
    raw_test_results['test_suites'].append(suite_data)
  test_results.score(scoring_tests)
  score, results = test_results.get_score(scoring_tests)

  # Create comments based on test results
  for suite_name, suite_results in results.items():
    passed_count = len(suite_results.get("PASSED", []))
    failed_count = len(suite_results.get("FAILED", []))
    total_count = passed_count + failed_count

    comments_parts.append(f"{suite_name}: {passed_count}/{total_count} tests passed")

    if suite_results.get("FAILED"):
      failed_tests = suite_results["FAILED"][:3]  # Show first 3 failed tests
      failed_str = ", ".join(failed_tests)
      if len(suite_results["FAILED"]) > 3:
        failed_str += "..."
      comments_parts.append(f"  Failed tests: {failed_str}")

  if len(scoring_tests) == 0:
    comments_parts.append("No scoring configuration found - raw score used.")

  all_logs.append(f"Test Results: {test_results}")

  # Add test stderr to logs for tripwire detection
  if test_stderr.strip():
    all_logs.append(f"Test stderr output:\n{test_stderr}")

  # Prepare final result
  final_comments = "\n".join(comments_parts)
  final_logs = "\n\n".join(all_logs)

  if isinstance(score, (int, float)):
    grade = float(score)
  else:
    grade = 0.0

  return {
    'grade': grade + (1.0 if lint_success else 0.0),
    'comments': final_comments,
    'logs': final_logs,
    'raw_test_results': raw_test_results,
    'scoring_tests': scoring_tests,
    'error': False
  }


def grade(PA, output_path, **kwargs):
  """Main grading wrapper with exception handling"""
  try:
    # Find assignment directory based on PA name
    assignment_dir = None
    potential_dirs = [
      f"programming-assignments/{PA}",
      f"labs/{PA}",
      PA  # Direct path
    ]

    for dir_path in potential_dirs:
      if os.path.exists(dir_path) and os.path.isdir(dir_path):
        assignment_dir = os.path.abspath(dir_path)
        break

    if not assignment_dir:
      raise GradingFailException(
        grade=0.0,
        comments=f"Assignment directory not found for {PA}. Searched: {', '.join(potential_dirs)}",
        logs="Assignment directory search failed.",
        is_error=True
      )

    log.info(f"Grading assignment in: {assignment_dir}")

    # Load scoring configuration
    scoring_tests = load_scoring_config(assignment_dir)

    # Do the actual grading
    return _do_grade(PA, assignment_dir, scoring_tests)

  except GradingFailException as e:
    # Expected grading failure
    log.error(f"Grading failed: {e.comments}")
    return {
      'grade': e.grade,
      'comments': e.comments,
      'logs': e.logs,
      'raw_test_results': None,
      'scoring_tests': scoring_tests if 'scoring_tests' in locals() else [],
      'error': e.is_error
    }
  except Exception as e:
    # Unexpected error
    log.error(f"Unexpected error during grading: {e}", exc_info=True)
    return {
      'grade': 0.0,
      'comments': f"Unexpected error during grading: {str(e)}",
      'logs': f"Exception: {str(e)}",
      'raw_test_results': None,
      'scoring_tests': [],
      'error': True
    }

def main():
  flags = parse_flags()
  result = grade(**vars(flags))

  # Extract failing tests and reserved tests using the rich data we now have
  failing_tests = []
  reserved_tests = []
  passing_tests = []

  if result['raw_test_results'] and result['scoring_tests']:
    # Extract tests from raw test results
    ran_tests = set()
    for test_suite in result['raw_test_results'].get('test_suites', []):
      suite_name = test_suite['name']
      for test in test_suite.get('tests', []):
        test_full_name = f"{suite_name}::{test['name']}"
        ran_tests.add(test['name'])  # Track which tests actually ran

        if test['status'] == 'PASSED':
          passing_tests.append(test_full_name)
        else:
          failing_tests.append(test_full_name)

    # Extract reserved tests from scoring configuration (only if they didn't run)
    for scoring_test in result['scoring_tests']:
      if scoring_test.test_name.startswith("RESERVE_"):
        if scoring_test.test_name not in ran_tests:
          # Only add to reserved list if the test didn't actually run
          reserved_tests.append(f"{scoring_test.suite}::{scoring_test.test_name}")

  # Add detailed test breakdown to comments
  enhanced_comments = result['comments']
  if passing_tests:
    enhanced_comments += f"\n\nPassing Tests:\n" + "\n".join([f"  - {test}" for test in passing_tests])
  if failing_tests:
    enhanced_comments += f"\n\nFailing Tests:\n" + "\n".join([f"  - {test}" for test in failing_tests])
  if reserved_tests:
    enhanced_comments += f"\n\nReserved Tests (will be used for final grading):\n" + "\n".join([f"  - {test}" for test in reserved_tests])

  # Create GradingResult for YAML output
  grading_result = GradingResult(
    grade=result['grade'],
    comments=enhanced_comments,
    logs=result['logs'],
    err=result.get('error', False)
  )

  with open(flags.output_path, 'w') as yaml_fid:
    yaml.safe_dump(
      dataclasses.asdict(grading_result),
      yaml_fid,
      sort_keys=False
    )

  print(f"Grading complete. Results written to {flags.output_path}")
  print(f"Grade: {result['grade']}")
  print(f"Comments: {result['comments']}")

  # Print detailed test breakdown with colors
  if passing_tests:
    print(f"\n{Fore.GREEN}Passing Tests:{Style.RESET_ALL}")
    for test in passing_tests:
      print(f"  {Fore.GREEN}- {test}{Style.RESET_ALL}")

  if failing_tests:
    print(f"\n{Fore.RED}Failing Tests:{Style.RESET_ALL}")
    for test in failing_tests:
      print(f"  {Fore.RED}- {test}{Style.RESET_ALL}")

  if reserved_tests:
    print(f"\n{Fore.YELLOW}Reserved Tests (will be used for final grading):{Style.RESET_ALL}")
    for test in reserved_tests:
      print(f"  {Fore.YELLOW}- {test}{Style.RESET_ALL}")

  if not failing_tests and not reserved_tests:
    if "Build failed" not in result['comments'] and "Error running tests:" not in result['comments']:
      print(f"\n{Fore.GREEN}All visible tests are passing!{Style.RESET_ALL}")


if __name__ == "__main__":
  main()
