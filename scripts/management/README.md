# Course Management

Run all course-management commands from the course repository root:

```bash
python scripts/manage_course.py --help
```

## Core Workflow

```bash
# Build and publish the safe shared cohort repository, including student Read access.
python scripts/manage_course.py publish-base --target <cohort>

# Optionally also create private repositories and teams for each student.
python scripts/manage_course.py publish-base --target <cohort> --per-student-repos

# Render and sync a syllabus to the central syllabi repository.
python scripts/manage_course.py sync-syllabus \
  --destination ../syllabi \
  --target <cohort>
```

`course-config.yaml` is the single source of course configuration. It resolves
settings as `defaults`, then the selected `mode`, then the concrete `target`.
Use explicit `publish.include` and `publish.exclude` lists to define the
student-facing surface. Add only explicit `publish.redact` rules for protected
files.

For Python files, omitting `mode` automatically redacts function bodies to
`raise NotImplementedError` while preserving function signatures, decorators, and leading
docstrings. Use
`mode: python-function-stubs` when you want to be explicit. Other redaction
modes, such as `c-function-stubs`, must still be named explicitly.

To keep a particular Python function, add `# redaction: keep` immediately
before its definition. The marker may also appear immediately before the
function's decorators.

Set `defaults.instructor_slug` to the instructor's GitHub username to make that
account a maintainer of the staff, cohort-reader, and per-student teams. It
also creates and synchronizes `<course>-<cohort>-<instructor_slug>` even when
the instructor is not on the roster. Leave it empty to disable the instructor
repository. `instructor_github_username` remains an optional override when the
repository suffix and GitHub username differ.

Existing per-student configurations should rename `student_repositories` to
`per_student_repositories`; `student_repo_url` is no longer configured.

Use `--dry-run` where a command provides it before operating on a new cohort.

## Shared repository access

`publish-base` derives the repository name as
`<course_code>-<cohort_slug>-base`, creates or reuses one cohort reader team,
and grants it Pull access. It also grants configured staff Maintain access.
Repeat runs are safe: existing teams, members, and invitations are left in
place. Use `--skip-add-students` to publish before a roster exists.

`{{ student_repo_url }}` remains available in course templates as a
compatibility alias for the derived common cohort repository URL.

## Student usage tokens

`publish-base --per-student-repos` creates a root `.env` file in each newly initialized
private student repository containing `STUDENT_TOKEN`. Before provisioning, set
`per_student_repositories.token_secret` in `course-config.yaml` to a private,
non-placeholder value (for example, generate one with `openssl rand -hex 32`).
The configuration file is not part of the student publication surface.

Tokens are stable HMAC-SHA-256 values scoped to the course, cohort, and
normalized student email. A checking server can use the same secret and roster
to reproduce expected values. Do not print the secret or tokens in logs, and do
not use a short or public salt such as `42`.

## Updating private student repositories

Each private student (and optional instructor) repository has a
publisher-managed `base` branch. On every `publish-base --per-student-repos`
run, that branch is updated to exactly match the shared cohort base; work on
`main` is not changed. Students can inspect it on GitHub or update their work
with:

```bash
git fetch origin base
git merge origin/base
```

The generated `scripts/update_from_base.sh` performs those commands after
checking for uncommitted changes. Treat `base` as instructor-owned: students
should not commit or push to it.
