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
- `calendar.md` - Course calendar (optional, or use CALENDAR_URL in .course-config)
- `.course-config` - Course configuration variables (see `.course-config.example`)
- `.course-config.example` - Template showing required configuration format
- `.studentignore` - Files/directories to exclude when publishing to student repositories
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
- For PPTX files you want students to access, consider keeping them in a separate repository or using a PPTX-to-PDF conversion workflow
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
3. Run `./scripts/publish_to_students.sh`
4. Script applies `.studentignore` filters and publishes to student repository

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
  └── publish_to_students.sh     # Excluded from student repos
  ```
- For course-specific grading documentation, see individual course repositories

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