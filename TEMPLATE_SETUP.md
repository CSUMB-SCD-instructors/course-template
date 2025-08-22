# Template Setup Guide

## For Template Maintainers

### Updating the Template
When making improvements to course structure or workflows:

1. **Make changes in the template repository**
2. **Test changes** with a sample course
3. **Update version/changelog** if significant changes
4. **Notify faculty** of available updates

### Syncing Changes to Existing Courses
Faculty can pull template improvements:

```bash
# Add template as remote (one-time setup)
git remote add template https://github.com/your-org/course-template

# Sync specific improvements
git fetch template
git cherry-pick <commit-hash>

# Or merge all changes (use carefully)
git merge template/main --allow-unrelated-histories
```

## For Faculty Using Template

### Initial Setup
1. **Create repository from template**
2. **Update `.course-config`**:
   ```bash
   COURSE_CODE=CST123
   COURSE_NAME="Your Course Name"  
   CALENDAR_URL="https://your-calendar-url"  # Optional
   ```
3. **Customize `syllabus.md`** with course details
4. **Commit changes** to trigger first syllabus sync

### Adding Content
- **Programming Assignments**: Add to `programming-assignments/PAX/`
- **Labs**: Add to `labs/labX-name/`
- **Demos**: Add to `demos/demoX-topic/`

### Calendar Options
- **Google Sheets**: Set `CALENDAR_URL` in `.course-config`
- **Local file**: Create `calendar.md` in repository root
- **No calendar**: Leave `CALENDAR_URL` empty and don't create `calendar.md`

## Organization Setup

### Required Secrets
Set up once at organization level:
- `SYLLABI_SYNC_TOKEN`: Personal access token with repo permissions to syllabi repository

### Repository Structure
```
organization/
├── course-template/          # This template
├── syllabi/                 # Centralized syllabi publishing
├── CST334-golden/           # Individual course repos
├── CST201-algorithms/
└── CST237-intro-cs/
```

## Troubleshooting

### Syllabus Not Syncing
1. Check GitHub Actions logs
2. Verify `.course-config` format
3. Ensure organization secrets are properly configured
4. Check syllabi repository permissions

### Template Updates Not Working
1. Verify template remote is configured
2. Check for merge conflicts
3. Consider manual file updates for complex changes