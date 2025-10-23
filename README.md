# Course Template Repository

This repository serves as a template for creating new course repositories with automatic syllabus publishing and student content distribution capabilities.

## Quick Setup for New Courses

1. **Use this template** to create a new repository
2. **Configure course details** in `.course-config` (see `.course-config.example`):
   ```bash
   COURSE_CODE=CST334
   COURSE_NAME="Introduction to Operating Systems"
   CALENDAR_URL="https://your-calendar-url" # Optional
   ```
3. **Update syllabus.md** with your course-specific content
4. **Syllabus publishing works automatically** (organization secret already configured)

## Repository Structure

- `syllabus.md` - Course syllabus (automatically published to centralized syllabi site)
- `syllabus-online.md` - Optional online course syllabus variant
- `calendar.md` - Course calendar (optional, or use CALENDAR_URL in .course-config)
- `students.txt` - Student email addresses for team management (see `students.txt.example`)
- `.course-config` - Course configuration variables (see `.course-config.example`)
- `.course-config.example` - Template showing required configuration format
- `.course-config-online` - Optional online course configuration
- `.course-config-online.example` - Template for online course variant
- `.studentignore` - Files/directories to exclude when publishing to student repositories
- `.studentignore-online.example` - Template for online course exclusions
- `.github/workflows/` - Automated syllabus publishing workflow
- `demos/` - In-class demonstration code
- `labs/` - Lab assignments and starter code
- `programming-assignments/` - Homework assignments
- `scripts/` - Course management and grading scripts (publish script excluded from student repos)

## Key Features

### 1. Automatic Syllabus Publishing
Changes to `syllabus.md`, `calendar.md`, or `.course-config` automatically trigger updates to the centralized syllabi repository at https://github.com/CSUMB-SCD-instructors/syllabi

**How it works:**
- GitHub Actions workflow (`.github/workflows/sync-syllabus.yml`) monitors these files
- On commit to `main` branch, files are copied to the syllabi repository's `_active/` directory
- Each course gets its own namespaced files: `${COURSE_CODE}-syllabus.md`, `${COURSE_CODE}-calendar.md`
- Jekyll front matter is automatically added with course metadata
- No risk of clobbering other courses' syllabi - each course manages only its own files

### 2. Student Repository Publishing
The `scripts/publish_to_students.sh` script enables controlled distribution of course materials to student-facing repositories.

**Workflow:**
1. **Development**: Work on `main` branch with complete solutions
2. **Redaction**: Merge to `redacted_for_students` branch and remove solutions
3. **Publication**: Run `./scripts/publish_to_students.sh` to publish to student repository

**Key capabilities:**
- Uses `.studentignore` to exclude instructor-only content (scripts, solutions, etc.)
- Creates clean, squashed commits for student repositories
- Supports tagging releases (defaults to `YYYY-wWW` format)
- Includes safety checks and confirmation prompts
- Force-pushes to maintain clean student history without exposing solution commits

**Example student publication:**
```bash
git checkout redacted_for_students
git merge main
# Manually redact solutions (replace with // todo comments)
git add .
git commit -m "Redact solutions for student distribution"
./scripts/publish_to_students.sh
```

See `scripts/README.md` for detailed workflow documentation.

### 3. Instructor-Only Content Management
Use `.studentignore` to control what gets published to student repositories. This file works like `.gitignore` but for the student publication workflow.

**Already excluded by default:**
- `/scripts/publish_to_students.sh` - Student publication script
- `/scripts/README.md` - Publication workflow documentation
- `*reserved*`, `*hidden*` - Reserved/hidden test files
- `/docker/` - Infrastructure configuration
- `*.pub`, `*deploy-key*` - Deployment keys
- `.studentignore`, `.course-config` - Template configuration files
- `CLAUDE.md` - AI assistant instructions

**Common additions:**
```bash
# Add to .studentignore for instructor-only content
solutions/
grades/
instructor-notes/
*/solution.c
*_solution.py
```

**Note on slides/binary files:**
- Use `scripts/strip_pptx_notes.py` to remove speaker notes from PPTX files before sharing with students
- For large binary files (>50MB), consider Git LFS: `git lfs track "*.pptx"`
- Files in `.studentignore` are version-controlled in instructor repo but NOT published to students

## Setup Instructions

### 1. Repository Setup
```bash
# Create new repository from this template on GitHub
# Clone to your local machine
git clone https://github.com/CSUMB-SCD-instructors/CST###-your-course.git
cd CST###-your-course

# Update course configuration
cp .course-config.example .course-config
# Edit .course-config with your course details (see .course-config.example)
```

### 2. Configure Course Details
Edit `.course-config` with your course information:
```bash
COURSE_CODE=CST334                    # Your course code
COURSE_NAME="Introduction to Operating Systems"
CALENDAR_URL="https://..."            # Optional: external calendar URL
STUDENT_REPO_URL="https://github.com/CSUMB-SCD-instructors/CST334.git"  # Optional: defaults to ${COURSE_CODE}
```

### 3. Content Customization
- Replace placeholder content in `syllabus.md`
- Add your assignments to `programming-assignments/`
- Add lab materials to `labs/`
- Add demonstration code to `demos/`
- Update `.studentignore` if you have additional instructor-only content

### 4. Student Repository Setup (Optional)
If you plan to publish to a student-facing repository:
```bash
# Create redacted_for_students branch
git checkout -b redacted_for_students
git push -u origin redacted_for_students

# Configure student repository URL in .course-config
# STUDENT_REPO_URL defaults to https://github.com/CSUMB-SCD-instructors/${COURSE_CODE}.git
```

### 5. Online Course Setup (Optional)
If you teach both in-person and online sections:
```bash
# Create online configuration
cp .course-config-online.example .course-config-online
# Edit with online course details

# Create online syllabus
cp syllabus.md syllabus-online.md
# Customize for online students

# Create online studentignore (optional)
cp .studentignore-online.example .studentignore-online
# Customize exclusions for online vs in-person

# Configure assignment remapping in .course-config-online if needed
# See .course-config-online.example for ASSIGNMENT_REMAP syntax
```

## Workflows and Automation

### Syllabus Publishing Workflow
**Trigger:** Commits to `main` branch that modify:
- `syllabus.md`
- `calendar.md`
- `.course-config`

**Behavior:**
- Automatically syncs to centralized syllabi repository
- Requires `SYLLABI_SYNC_TOKEN` organization secret (already configured)
- Creates Jekyll-compatible pages with course metadata
- Updates `last_updated` timestamp

**Calendar options:**
- **External URL**: Set `CALENDAR_URL` in `.course-config` (e.g., Google Sheets published URL)
- **Local file**: Create `calendar.md` in repository root
- **No calendar**: Leave `CALENDAR_URL` empty and don't create `calendar.md`

### Student Publishing Workflow
See `scripts/README.md` for complete documentation.

**Two-branch system:**
- `main` - Instructor branch with complete solutions
- `redacted_for_students` - Redacted version for student distribution

**Publishing process:**
1. Merge `main` → `redacted_for_students`
2. Redact solutions (manual step - replace with `// todo` comments)
3. Run `./scripts/publish_to_students.sh` (or `--online` for online variant)
4. Script applies `.studentignore` filters and publishes to student repository

**Online course support:**
```bash
# Publish in-person version
./scripts/publish_to_students.sh

# Publish online version with different syllabus and assignment ordering
./scripts/publish_to_students.sh --online
```

The `--online` flag uses `.course-config-online` to:
- Use a different student repository
- Map `syllabus-online.md` → `syllabus.md`
- Remap assignment directories (e.g., swap PA1 and PA2)
- Apply different `.studentignore` rules

## Course Management

### Directory Structure
```
CST334-operating-systems/
├── .course-config              # Course configuration
├── .studentignore              # Student publication exclusions
├── syllabus.md                # Auto-synced to syllabi repo
├── calendar.md                # Optional course calendar
├── demos/                     # In-class demonstrations
│   ├── demo01-processes/
│   └── demo02-threads/
├── labs/                      # Lab assignments
│   ├── lab01-git-intro/
│   └── lab02-shell-scripting/
├── programming-assignments/   # Major assignments
│   ├── PA1-shell/
│   └── PA2-scheduler/
└── scripts/                   # Grading and course management
    ├── grade.py               # Students can access
    ├── tests-public/         # Students can access
    ├── tests-reserved/       # Excluded (*reserved* pattern)
    ├── publish_to_students.sh # Excluded (instructor-only)
    └── README.md             # Excluded (instructor-only)
```

### Grading and Helper Scripts
- Grading scripts can be added to `scripts/` directory
- Students can access grading scripts to test their work locally
- Use filename patterns `*reserved*` or `*hidden*` for instructor-only test files
- Example structure:
  ```
  scripts/
  ├── grade.py                    # Students can access
  ├── tests-public/              # Students can access
  ├── tests-reserved/            # Excluded from student repos
  ├── strip_pptx_notes.py        # Utility to remove speaker notes from slides
  └── publish_to_students.sh     # Excluded from student repos
  ```
- For course-specific grading documentation, see individual course repositories

### Managing Student Repository Access

Use `scripts/manage_student_team.sh` to create GitHub teams and grant students read-only access:

```bash
# Create team and add students for fall 2025
./scripts/manage_student_team.sh --students students.txt --term fall2025

# For online course
./scripts/manage_student_team.sh --online --students students.txt --term fall2025

# Add more students to existing team
./scripts/manage_student_team.sh --students new_students.txt --term fall2025 --action add

# Remove students from team
./scripts/manage_student_team.sh --students removed_students.txt --term fall2025 --action remove
```

**Student file format** (`students.txt`):
```
student1@csumb.edu
student2@csumb.edu
student3@csumb.edu
```

**Team naming:** Creates teams like `CST334-students-fall2025` with read-only access to the student repository.

**Requirements:** GitHub CLI (`gh`) must be installed and authenticated: `gh auth login`

### Sharing Slides with Students
Use `scripts/strip_pptx_notes.py` to remove instructor notes from PowerPoint files:

```bash
# Strip notes and create new file
python scripts/strip_pptx_notes.py lecture01.pptx
# Creates: lecture01_no_notes.pptx

# Process multiple files
python scripts/strip_pptx_notes.py slides/*.pptx

# Specify custom output name
python scripts/strip_pptx_notes.py lecture01.pptx -o lecture01_student.pptx
```

**Requirements:** `pip install python-pptx` (or `uv sync` if using the project dependencies)

**Note:** This only works with `.pptx` files (modern PowerPoint format). Old `.ppt` files must be converted first.

## Getting Help

### Common Issues

**Syllabus not syncing:**
1. Check GitHub Actions logs in "Actions" tab
2. Verify `.course-config` format matches `.course-config.example`
3. Ensure `COURSE_CODE` and `COURSE_NAME` are not template defaults
4. Check syllabi repository permissions

**Student publication failing:**
1. Verify `.course-config` has correct `STUDENT_REPO_URL`
2. Ensure `redacted_for_students` branch exists
3. Check for uncommitted changes (working directory must be clean)
4. Review `.studentignore` patterns

**Template values not updated:**
The scripts check for template defaults and will error if you try to publish with:
- `COURSE_CODE=CSTXXX`
- `COURSE_NAME="Course Title"` or `"Your Course Name"`

### Support
For issues with this template:
1. Check the GitHub Actions logs for sync issues
2. Verify `.course-config` is properly formatted
3. Review `scripts/README.md` for student publishing workflow
4. Contact repository maintainer

## Template Maintenance

### Pulling Template Updates
To sync improvements from the template to existing courses:
```bash
# Add template as remote (one-time setup)
git remote add template https://github.com/CSUMB-SCD-instructors/course-template
git fetch template

# Cherry-pick specific improvements
git cherry-pick <commit-hash>

# Or merge all changes (use carefully, may cause conflicts)
git merge template/main --allow-unrelated-histories
```

See `TEMPLATE_SETUP.md` for maintainer documentation.