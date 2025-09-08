# Student Repository Publication Workflow

This directory contains scripts for managing the publication of course materials to student repositories.

## Overview

The workflow separates instructor solution code from student starter code:

- **`main` branch**: Complete solutions and course materials
- **`redacted_for_students` branch**: Student version with solutions replaced by `// todo` comments
- **Student repository**: Clean copy with no solution history

## Workflow Steps

### 1. Development Phase
Work on the `main` branch as normal:
```bash
git checkout main
# Make changes, add solutions, etc.
git add .
git commit -m "Add PA3 solutions"
```

### 2. Prepare Student Version
```bash
# Switch to student branch and merge latest changes
git checkout redacted_for_students
git merge main

# Manually redact solutions (replace implementations with // todo)
# Edit files like programming-assignments/*/src/student_code.c

# Commit redacted version
git add .
git commit -m "Redact solutions for student distribution"
```

### 3. Publish to Students
```bash
# Update student repository URL in the script first
# Edit scripts/publish_to_students.sh and set STUDENT_REPO_URL

# Run publication script
./scripts/publish_to_students.sh
```

The script will:
- Force-push `redacted_for_students` → student repo `main`
- Create a timestamped tag (e.g., `2025-w17`)
- Provide confirmation prompts for safety

## Configuration

Before first use, edit `scripts/publish_to_students.sh`:
```bash
STUDENT_REPO_URL="https://github.com/yourusername/CST334-assignments-base.git"
```

## Key Benefits

- **Security**: No solution history exposed to students
- **Updates**: Can push incremental updates during semester
- **Clean History**: Student repo has clean, linear history
- **Automation**: Scriptable for consistency

## Example Tag Timeline
- `2025-w01`: Initial course setup
- `2025-w03`: PA1 released
- `2025-w06`: PA2 released, PA1 updates
- `2025-w09`: Midterm materials

## Safety Features

- Branch verification before actions
- Working directory cleanliness checks
- Confirmation prompts before force-push
- Automatic tag generation with semester-appropriate naming