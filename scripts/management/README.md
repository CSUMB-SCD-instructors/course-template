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
