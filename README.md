# Course Template Repository

This repository serves as a template for creating new course repositories with automatic syllabus publishing capabilities.

## Quick Setup for New Courses

1. **Use this template** to create a new repository
2. **Configure course details** in `.course-config`:
   ```bash
   COURSE_CODE=CST123
   COURSE_NAME="Your Course Name"
   CALENDAR_URL="https://your-calendar-url" # Optional
   ```
3. **Update syllabus.md** with your course-specific content
4. **Syllabus publishing works automatically** (organization secret already configured)

## Repository Structure

- `syllabus.md` - Course syllabus (automatically published)
- `calendar.md` - Course calendar (optional, or use CALENDAR_URL)
- `.course-config` - Course configuration for GitHub Actions
- `.github/workflows/` - Automated syllabus publishing workflow
- `demos/` - In-class demonstration code
- `labs/` - Lab assignments and starter code
- `programming-assignments/` - Homework assignments
- `helpers/` - Grading and utility scripts
- `scripts/` - Course management scripts

## Features

- **Automatic Syllabus Publishing**: Changes to syllabus.md trigger automatic updates to a centralized syllabi repository
- **Structured Organization**: Consistent directory structure for demos, labs, and assignments
- **Template Placeholders**: Easy-to-replace placeholder content for new courses
- **Organization-Level Setup**: No additional secrets configuration needed for faculty

## Setup Instructions

### 1. Repository Setup
- Create new repository from this template
- Clone to your local machine
- Update `.course-config` with your course details

### 2. Content Customization
- Replace placeholder content in `syllabus.md`
- Add your assignments to `programming-assignments/`
- Add lab materials to `labs/`
- Add demonstration code to `demos/`

*Note: Syllabus publishing is automatically enabled via organization-level GitHub secrets.*

## GitHub Actions Workflow

The included workflow automatically:
- Syncs syllabus.md to a centralized syllabi repository
- Handles calendar embedding (from URL or local file)
- Maintains Jekyll-compatible formatting
- Updates course listings automatically

## Helpful Commands

- `make` - Build and run code (if Makefile present)
- `make grade` - Run grading scripts
- `git commit` - Commit changes (triggers syllabus sync if syllabus.md changed)

## Course Management

This template supports the following pedagogical structure:
- **Programming Assignments**: Major homework with automated grading
- **Labs**: In-class activities with starter code
- **Demos**: Lecture demonstration code
- **Continuous Assessment**: Through commits and progress tracking

## Getting Help

For issues with this template:
1. Check the GitHub Actions logs for sync issues
2. Verify `.course-config` is properly formatted
3. Contact repository maintainer

## Template Maintenance

To sync improvements from the template to existing courses:
```bash
git remote add template https://github.com/your-org/course-template
git fetch template
git cherry-pick <improvement-commits>
```