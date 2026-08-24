# Course Management

Run all course-management commands from the course repository root:

```bash
python scripts/manage_course.py --help
```

## Core Workflow

```bash
# Build and publish safe, rendered materials to the cohort base repository.
python scripts/manage_course.py publish-base --target <cohort>

# Create missing private student repositories and access teams.
python scripts/manage_course.py provision-student-repos --target <cohort>

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

The legacy shared-repository flow remains available when a target defines
`student_repo_url`:

```bash
python scripts/manage_course.py publish-repo --target <cohort>
```

Use `--dry-run` where a command provides it before operating on a new cohort.

## Per-student repository URLs in templates

In files rendered by `publish-base`, a plain `{{ student_repo_url }}` is
intentionally deferred. It remains a placeholder in the shared base, then
`provision-student-repos` replaces it with the URL of each student's private
repository before its first commit. Do not apply filters or other Jinja
expressions to this deferred value.

## Student usage tokens

`provision-student-repos` creates a root `.env` file in each newly initialized
private student repository containing `STUDENT_TOKEN`. Before provisioning, set
`student_repositories.token_secret` in `course-config.yaml` to a private,
non-placeholder value (for example, generate one with `openssl rand -hex 32`).
The configuration file is not part of the student publication surface.

Tokens are stable HMAC-SHA-256 values scoped to the course, cohort, and
normalized student email. A checking server can use the same secret and roster
to reproduce expected values. Do not print the secret or tokens in logs, and do
not use a short or public salt such as `42`.
