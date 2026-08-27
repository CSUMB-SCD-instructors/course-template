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
