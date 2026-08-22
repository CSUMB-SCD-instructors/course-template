# Course Copier Template

This is the reusable template for CSUMB course repositories. It provides the
Python course-management CLI, grading starter contract, safe student-repository
publication workflow, and syllabus synchronization.

Create a new course repository with Copier rather than GitHub's one-time
"Use this template" snapshot:

```bash
copier copy /path/to/course-template /path/to/new-course
```

Copier writes `.copier-answers.yml` into the generated course. Keep that file
committed; it lets the course apply future framework revisions with:

```bash
copier update
```

See [TEMPLATE_SETUP.md](TEMPLATE_SETUP.md) for template-maintenance guidance.
