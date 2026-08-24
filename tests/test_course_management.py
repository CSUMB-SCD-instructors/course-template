from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo
from github.GithubException import GithubException

from scripts.management.course_config import (
  ConfigError,
  prune_tree,
  render_template,
  render_tree,
  resolve_target,
)
from scripts.management.git_helpers import GitHelper
from scripts.management.student_repositories import (
  StudentRepository,
  _initialize_student_repository,
  _invite_email_to_team,
  base_index_readme,
  student_token,
  student_token_secret,
  repository_settings,
  staff_members,
  student_repositories,
)
from scripts.management.syllabus_sync import sync_syllabi


def test_prune_tree_uses_include_and_exclude(tmp_path: Path) -> None:
  (tmp_path / "materials").mkdir()
  (tmp_path / "materials" / "starter.c").write_text("starter", encoding="utf-8")
  (tmp_path / "materials" / "solution").mkdir()
  (tmp_path / "materials" / "solution" / "answer.c").write_text("answer", encoding="utf-8")
  (tmp_path / ".envrc").write_text("secret", encoding="utf-8")
  (tmp_path / "course-config.yaml").write_text("config", encoding="utf-8")
  (tmp_path / "instructor-notes.md").write_text("notes", encoding="utf-8")

  config = {
    "defaults": {
      "publish": {
        "include": ["materials/**", ".envrc", "course-config.yaml"],
        "exclude": ["**/solution/**", ".env*", "course-config.yaml"],
      },
    },
    "targets": {"course": {}},
  }

  prune_tree(tmp_path, config, "course")

  assert (tmp_path / "materials" / "starter.c").exists()
  assert not (tmp_path / "materials" / "solution").exists()
  assert not (tmp_path / ".envrc").exists()
  assert not (tmp_path / "course-config.yaml").exists()
  assert not (tmp_path / "instructor-notes.md").exists()


def test_templates_use_explicit_student_repo_url(tmp_path: Path) -> None:
  (tmp_path / "README.md.j2").write_text(
    "git clone {{ student_repo_url }} {{ on_machine_repo_directory }}\n",
    encoding="utf-8",
  )
  config = {
    "defaults": {"on_machine_repo_directory": "CST334"},
    "targets": {"online": {"student_repo_url": "https://example.test/CST334-online.git"}},
  }

  rendered = render_template(tmp_path, "README.md.j2", resolve_target(config, "online"))

  assert rendered == "git clone https://example.test/CST334-online.git CST334\n"


def test_sync_syllabi_writes_commits_and_skips_unchanged(tmp_path: Path) -> None:
  source_root = tmp_path / "course"
  destination_root = tmp_path / "syllabi"
  source_root.mkdir()
  destination_root.mkdir()
  (source_root / "syllabus.md.j2").write_text(
    "# {{ course_name }}\n[Calendar](calendar.md)\n[Syllabus](syllabus.md)\n",
    encoding="utf-8",
  )
  (source_root / "calendar.md").write_text("# Calendar\n", encoding="utf-8")
  repo = Repo.init(destination_root)
  config = {
    "defaults": {},
    "targets": {
      "online": {
        "course_code": "CST334",
        "course_name": "Operating Systems Online",
        "published_course_code": "CST334-online",
      },
    },
  }

  changed = sync_syllabi(
    source_root,
    destination_root,
    config,
    ["online"],
    "Sync test",
    push=False,
  )

  syllabus_path = destination_root / "_active" / "CST334-online-syllabus.md"
  assert {path.as_posix() for path in changed} == {
    "_active/CST334-online-syllabus.md",
    "_active/CST334-online-calendar.md",
  }
  assert "CST334-online-calendar.html" in syllabus_path.read_text(encoding="utf-8")
  assert not (source_root / "syllabus.md").exists()
  first_commit = repo.head.commit.hexsha

  assert sync_syllabi(
    source_root,
    destination_root,
    config,
    ["online"],
    "Sync test",
    push=False,
  ) == []
  assert repo.head.commit.hexsha == first_commit


def test_sync_syllabi_dry_run_does_not_write(tmp_path: Path) -> None:
  source_root = tmp_path / "course"
  destination_root = tmp_path / "syllabi"
  source_root.mkdir()
  destination_root.mkdir()
  (source_root / "syllabus.md.j2").write_text("# {{ course_name }}\n", encoding="utf-8")
  Repo.init(destination_root)
  config = {
    "defaults": {},
    "targets": {"in-person": {"course_code": "CST334", "course_name": "Operating Systems"}},
  }

  changed = sync_syllabi(
    source_root,
    destination_root,
    config,
    ["in-person"],
    "Sync test",
    dry_run=True,
    push=False,
  )

  assert changed == [Path("_active/CST334-syllabus.md")]
  assert not (destination_root / "_active").exists()


def test_publish_staging_branch_is_an_orphan_commit(tmp_path: Path) -> None:
  source_root = tmp_path / "source"
  student_remote = tmp_path / "student.git"
  source_root.mkdir()
  source_repo = Repo.init(source_root)
  (source_root / "student_code.c").write_text("int answer(void) { return 42; }\n", encoding="utf-8")
  source_repo.git.add(A=True)
  source_repo.index.commit("Source solution")
  source_repo.git.branch("-M", "main")
  source_repo.git.branch("redacted_for_students")
  Repo.init(student_remote, bare=True)

  helper = GitHelper(source_root)
  with helper.temporary_clone() as (publish_repo, _):
    previous_ref = helper.prepare_staging_branch(
      publish_repo,
      "redacted_for_students",
      "main",
    )
    assert previous_ref == "origin/redacted_for_students"

    worktree_root = Path(publish_repo.working_tree_dir or ".")
    (worktree_root / "student_code.c").write_text(
      "int answer(void) { return 0; }\n",
      encoding="utf-8",
    )
    publish_repo.git.add(A=True)
    publish_repo.index.commit("Redacted publication")
    assert publish_repo.git.log("-1", "--format=%P") == ""

    publish_repo.git.push("--force", student_remote.as_posix(), "redacted_for_students:main")

  clone_root = tmp_path / "student-clone"
  student_repo = Repo.clone_from(student_remote.as_posix(), clone_root, branch="main")
  assert len(list(student_repo.iter_commits("main"))) == 1
  assert (clone_root / "student_code.c").read_text(encoding="utf-8") == (
    "int answer(void) { return 0; }\n"
  )


def test_cohort_target_inherits_mode_and_derives_base_repository() -> None:
  config = {
    "defaults": {
      "github_org": "example-org",
      "student_repositories": {"base_branch": "base", "base_index_branch": "main"},
    },
    "modes": {
      "online": {
        "course_code": "CST334",
        "course_name": "Operating Systems Online",
        "staff": ["ta-one", "ta.two@example.edu"],
      },
    },
    "targets": {
      "fall2026online": {
        "mode": "online",
        "cohort_slug": "fall2026online",
        "student_list": "students.txt",
      },
    },
  }

  resolved = resolve_target(config, "fall2026online")

  assert resolved["mode"] == "online"
  assert resolved["base_repo_name"] == "CST334-fall2026online-base"
  assert resolved["base_repo_url"] == "https://github.com/example-org/CST334-fall2026online-base.git"
  assert repository_settings(resolved)["base_branch"] == "base"
  assert staff_members(resolved) == ["ta-one", "ta.two@example.edu"]


def test_student_repositories_use_normalized_email_local_parts() -> None:
  resolved = {
    "course_code": "CST334",
    "cohort_slug": "spring2026",
    "github_org": "example-org",
    "base_repo_name": "CST334-spring2026-base",
    "base_repo_url": "https://github.com/example-org/CST334-spring2026-base.git",
    "student_repositories": {"base_branch": "base", "base_index_branch": "main"},
  }

  students = student_repositories(resolved, ["Sogden@csumb.edu", "jane.doe+lab@csumb.edu"])

  assert [(student.slug, student.repository_name) for student in students] == [
    ("sogden", "CST334-spring2026-sogden"),
    ("jane-doe-lab", "CST334-spring2026-jane-doe-lab"),
  ]


def test_student_token_is_stable_scoped_and_normalizes_email() -> None:
  resolved = {
    "course_code": "CST334",
    "cohort_slug": "spring2026",
    "github_org": "example-org",
    "base_repo_name": "CST334-spring2026-base",
    "base_repo_url": "https://github.com/example-org/CST334-spring2026-base.git",
    "student_repositories": {"token_secret": "private course secret"},
  }

  token = student_token(resolved, " Sogden@CSUMB.edu ")

  assert token == student_token(resolved, "sogden@csumb.edu")
  assert token != student_token(resolved, "other@csumb.edu")
  assert len(token) == 64
  assert all(character in "0123456789abcdef" for character in token)

  other_cohort = dict(resolved, cohort_slug="fall2026")
  assert token != student_token(other_cohort, "sogden@csumb.edu")


@pytest.mark.parametrize("secret", [None, "", "CHANGE_ME", "replace-me"])
def test_student_token_requires_a_configured_secret(secret: object) -> None:
  resolved = {"student_repositories": {"token_secret": secret}}

  with pytest.raises(ConfigError, match="token_secret"):
    student_token_secret(resolved)


def test_student_repository_initialization_commits_root_env_file(tmp_path: Path) -> None:
  base_remote = tmp_path / "base.git"
  student_remote = tmp_path / "student.git"
  base_worktree = tmp_path / "base-worktree"
  Repo.init(base_remote, bare=True)
  Repo.init(student_remote, bare=True)

  base_repo = Repo.init(base_worktree)
  (base_worktree / "starter.txt").write_text("starter\n", encoding="utf-8")
  base_repo.git.add(A=True)
  base_repo.index.commit("Initial base")
  base_repo.git.branch("-M", "base")
  base_repo.git.push(base_remote.as_posix(), "base:base")

  _initialize_student_repository(
    base_remote.as_posix(),
    "base",
    student_remote.as_posix(),
    "test-token",
  )

  clone_root = tmp_path / "student-clone"
  student_repo = Repo.clone_from(student_remote.as_posix(), clone_root, branch="main")
  assert (clone_root / ".env").read_text(encoding="utf-8") == "STUDENT_TOKEN=test-token\n"
  assert student_repo.git.log("-1", "--format=%s") == "Add student usage token"


def test_student_invitation_permission_error_includes_auth_guidance(monkeypatch: pytest.MonkeyPatch) -> None:
  class Organization:
    login = "example-org"

  class Team:
    id = 123

  def fail_invitation(*args: object) -> None:
    raise GithubException(403, {"message": "You must be an admin"})

  monkeypatch.setattr(
    "scripts.management.student_repositories.invite_by_email",
    fail_invitation,
  )

  with pytest.raises(ConfigError, match="gh auth refresh.*admin:org"):
    _invite_email_to_team(Organization(), Team(), "student@example.edu")


def test_student_invitation_reports_when_invitation_already_exists(
  monkeypatch: pytest.MonkeyPatch,
) -> None:
  class Organization:
    pass

  class Team:
    id = 123

  def existing_invitation(*args: object) -> None:
    raise GithubException(422, {"message": "Invitee is already a member"})

  monkeypatch.setattr(
    "scripts.management.student_repositories.invite_by_email",
    existing_invitation,
  )

  assert not _invite_email_to_team(Organization(), Team(), "student@example.edu")


def test_base_index_readme_links_to_sorted_student_repositories() -> None:
  settings = {
    "course_code": "CST334",
    "cohort_slug": "per_student_test",
    "github_org": "CSUMB-SCD-assignments",
  }
  students = [
    StudentRepository("zoe@example.edu", "zoe", "CST334-per_student_test-zoe"),
    StudentRepository("amy@example.edu", "amy", "CST334-per_student_test-amy"),
  ]

  readme = base_index_readme(settings, students)

  assert "| Student | Repository |" in readme
  assert readme.index("| amy |") < readme.index("| zoe |")
  assert (
    "[GitHub repository](https://github.com/CSUMB-SCD-assignments/"
    "CST334-per_student_test-amy)"
  ) in readme


def test_student_update_script_renders_cohort_base_details(tmp_path: Path) -> None:
  (tmp_path / "update_from_base.sh.j2").write_text(
    "git fetch {{ base_repo_url }} {{ student_repositories.base_branch }}\n",
    encoding="utf-8",
  )
  config = {
    "defaults": {
      "github_org": "example-org",
      "student_repositories": {"base_branch": "base"},
    },
    "modes": {"in-person": {"course_code": "CST334"}},
    "targets": {"spring2026": {"mode": "in-person", "cohort_slug": "spring2026"}},
  }

  rendered = render_template(
    tmp_path,
    "update_from_base.sh.j2",
    resolve_target(config, "spring2026"),
  )

  assert rendered == "git fetch https://github.com/example-org/CST334-spring2026-base.git base\n"


def test_render_tree_preserves_executable_template_mode(tmp_path: Path) -> None:
  scripts_dir = tmp_path / "scripts"
  scripts_dir.mkdir()
  template_path = scripts_dir / "update_from_base.sh.j2"
  template_path.write_text("#!/usr/bin/env bash\necho {{ cohort_slug }}\n", encoding="utf-8")
  template_path.chmod(0o755)
  config = {
    "defaults": {"render_paths": ["scripts/update_from_base.sh.j2"]},
    "targets": {"spring2026": {"cohort_slug": "spring2026"}},
  }

  render_tree(tmp_path, config, "spring2026")

  output_path = scripts_dir / "update_from_base.sh"
  assert output_path.read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho spring2026\n"
  assert output_path.stat().st_mode & 0o111


def test_render_tree_supports_recursive_render_path_globs(tmp_path: Path) -> None:
  (tmp_path / "README.md.j2").write_text("# {{ course_name }}\n", encoding="utf-8")
  lab_dir = tmp_path / "labs" / "lab1"
  lab_dir.mkdir(parents=True)
  (lab_dir / "README.md.j2").write_text("# Lab: {{ course_name }}\n", encoding="utf-8")
  config = {
    "defaults": {"render_paths": ["**/README.md.j2"]},
    "targets": {"spring2026": {"course_name": "Operating Systems"}},
  }

  rendered = render_tree(tmp_path, config, "spring2026")

  assert sorted(path.relative_to(tmp_path).as_posix() for path in rendered) == [
    "README.md",
    "labs/lab1/README.md",
  ]
  assert (lab_dir / "README.md").read_text(encoding="utf-8") == "# Lab: Operating Systems\n"


def test_student_can_merge_a_new_base_release_without_rewriting_work(tmp_path: Path) -> None:
  base_remote = tmp_path / "base.git"
  base_worktree = tmp_path / "base-worktree"
  student_worktree = tmp_path / "student-worktree"
  Repo.init(base_remote, bare=True)

  base_repo = Repo.init(base_worktree)
  (base_worktree / "assignment.txt").write_text("starter\n", encoding="utf-8")
  base_repo.git.add(A=True)
  base_repo.index.commit("Initial safe base")
  base_repo.git.branch("-M", "base")
  base_repo.git.push(base_remote.as_posix(), "base:base")

  student_repo = Repo.clone_from(base_remote.as_posix(), student_worktree, branch="base")
  student_repo.git.branch("-M", "main")
  (student_worktree / "student.txt").write_text("student work\n", encoding="utf-8")
  student_repo.git.add(A=True)
  student_repo.index.commit("Student work")
  student_commit = student_repo.head.commit.hexsha

  base_repo.git.checkout("base")
  (base_worktree / "assignment.txt").write_text("updated starter\n", encoding="utf-8")
  base_repo.git.add(A=True)
  base_repo.index.commit("Safe base update")
  base_repo.git.push(base_remote.as_posix(), "base:base")
  base_commit = base_repo.head.commit.hexsha

  student_repo.create_remote("course-base", base_remote.as_posix())
  student_repo.remotes["course-base"].fetch("base")
  student_repo.git.merge("--no-edit", "course-base/base")

  assert student_repo.git.merge_base("--is-ancestor", student_commit, "HEAD") == ""
  assert student_repo.git.merge_base("--is-ancestor", base_commit, "HEAD") == ""
  assert (student_worktree / "student.txt").read_text(encoding="utf-8") == "student work\n"
  assert (student_worktree / "assignment.txt").read_text(encoding="utf-8") == "updated starter\n"
