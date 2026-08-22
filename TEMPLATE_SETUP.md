# Maintaining the Course Copier Template

This repository is a Copier template, not merely a GitHub snapshot template.
New courses should be created with:

```bash
copier copy /path/to/course-template /path/to/new-course
```

Copier writes `.copier-answers.yml` to each generated course. That tracked file
records the template source and answers so the course can later run
`copier update` from a clean worktree.

## Template Boundaries

Keep reusable Python framework code in `scripts/management/`, the management
entry point, the grading starter contract, common workflows, and the generic
course skeleton here. Keep course-specific assignments, roster contents,
syllabus prose, and target-specific URLs in each generated course.

Files ending in `.jinja` are rendered by Copier. Runtime Jinja files such as
`syllabus.md.j2` deliberately do not use that suffix, so Copier copies them
unchanged for `scripts/manage_course.py` to render later.

## Adding the Framework to an Existing Course

Copier preserves an existing `pyproject.toml`, `uv.lock`, `.python-version`,
and `.envrc` instead of overwriting the course's runtime setup. When Copier asks whether it is adopting an existing course, answer yes. It
preserves the existing `pyproject.toml` and includes this one-time helper:

```bash
bash scripts/add_course_management_dependencies.sh
```

The helper delegates TOML edits and lockfile updates to `uv add`, adding only
the `course-management` optional dependency extra.
