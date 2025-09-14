#!/bin/bash
# Script to publish redacted_for_students branch to student repository
# This creates a clean history without exposing solution commits

set -e  # Exit on any error

# Load course configuration
if [ ! -f ".course-config" ]; then
    echo -e "${RED}Error: .course-config file not found${NC}"
    echo -e "${RED}This file is required to determine course-specific settings${NC}"
    exit 1
fi

source .course-config

# Validate required configuration
if [ -z "$COURSE_CODE" ]; then
    echo -e "${RED}Error: COURSE_CODE not set in .course-config${NC}"
    exit 1
fi

if [ -z "$COURSE_NAME" ]; then
    echo -e "${RED}Error: COURSE_NAME not set in .course-config${NC}"
    exit 1
fi

# Check for default template values that shouldn't be used
if [ "$COURSE_CODE" = "CSTXXX" ] ; then
    echo -e "${RED}Error: COURSE_CODE appears to be a template default value: '$COURSE_CODE'${NC}"
    echo -e "${RED}Please update .course-config with your actual course code before publishing${NC}"
    exit 1
fi

if [ "$COURSE_NAME" = "Course Title" ] || [ "$COURSE_NAME" = "Your Course Name" ]; then
    echo -e "${RED}Error: COURSE_NAME appears to be a template default value: '$COURSE_NAME'${NC}"
    echo -e "${RED}Please update .course-config with your actual course name before publishing${NC}"
    exit 1
fi

# Check if STUDENT_REPO_URL is defined in .course-config, otherwise use course-based default
if [ -z "$STUDENT_REPO_URL" ]; then
    STUDENT_REPO_URL="https://github.com/CSUMB-SCD-instructors/${COURSE_CODE}.git"
fi

# Configuration
STUDENT_REMOTE_NAME="student-repo"
SOURCE_BRANCH="redacted_for_students"
TARGET_BRANCH="main"  # Branch name in student repository

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Publishing ${SOURCE_BRANCH} to student repository...${NC}"
echo -e "${YELLOW}Course Configuration:${NC}"
echo -e "  Course Code: ${GREEN}${COURSE_CODE}${NC}"
echo -e "  Course Name: ${GREEN}${COURSE_NAME}${NC}"
echo -e "  Student Repo: ${GREEN}${STUDENT_REPO_URL}${NC}"
echo ""

# Final safety check with course details
read -p "Confirm this is the correct course before publishing (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Publication cancelled - please verify your .course-config settings${NC}"
    exit 0
fi

# Verify we're in a git repository
if [ ! -d ".git" ]; then
    echo -e "${RED}Error: Not in a git repository${NC}"
    exit 1
fi

# Verify source branch exists
if ! git show-ref --verify --quiet refs/heads/${SOURCE_BRANCH}; then
    echo -e "${RED}Error: Branch ${SOURCE_BRANCH} does not exist${NC}"
    exit 1
fi

# Check if we're on the right branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "$SOURCE_BRANCH" ]; then
    echo -e "${YELLOW}Switching to ${SOURCE_BRANCH} branch...${NC}"
    git checkout ${SOURCE_BRANCH}
fi

# Verify branch is clean
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${RED}Error: Working directory is not clean. Please commit or stash changes.${NC}"
    git status
    exit 1
fi

# Add student repository as remote if it doesn't exist
if ! git remote get-url ${STUDENT_REMOTE_NAME} >/dev/null 2>&1; then
    echo -e "${YELLOW}Adding student repository as remote '${STUDENT_REMOTE_NAME}'...${NC}"
    git remote add ${STUDENT_REMOTE_NAME} ${STUDENT_REPO_URL}
else
    echo -e "${GREEN}Student repository remote already exists${NC}"
    # Update the remote URL in case it changed
    git remote set-url ${STUDENT_REMOTE_NAME} ${STUDENT_REPO_URL}
fi

# Fetch the student repository to check its current state
echo -e "${YELLOW}Fetching from student repository...${NC}"
git fetch ${STUDENT_REMOTE_NAME} || {
    echo -e "${RED}Warning: Could not fetch from student repository. This might be the first push.${NC}"
}

# Show what we're about to do
echo -e "${YELLOW}About to force-push the following commits to student repository:${NC}"
git log --oneline -10 ${SOURCE_BRANCH}

# Confirmation prompt
read -p "Are you sure you want to force-push to the student repository? This will overwrite the remote history. (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Publication cancelled.${NC}"
    exit 0
fi

# Create clean squashed commit for publication
echo -e "${YELLOW}Creating clean publication commit...${NC}"

# Get a meaningful commit message
read -p "Enter commit message for this publication [Published to students: $(date)]: " COMMIT_MSG
if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="Published to students: $(date)"
fi

TEMP_BRANCH="temp-clean-$(date +%s)"

# Create new branch from last published commit (if it exists)
if git ls-remote --exit-code ${STUDENT_REMOTE_NAME} ${TARGET_BRANCH} >/dev/null 2>&1; then
    echo -e "${YELLOW}Creating branch from last published commit...${NC}"
    git fetch ${STUDENT_REMOTE_NAME} ${TARGET_BRANCH}
    git checkout -b ${TEMP_BRANCH} ${STUDENT_REMOTE_NAME}/${TARGET_BRANCH}
else
    echo -e "${YELLOW}Creating new publication branch (first publication)...${NC}"
    git checkout --orphan ${TEMP_BRANCH}
    git rm -rf . 2>/dev/null || true
fi

# Copy current state from redacted branch, respecting .studentignore
git checkout ${SOURCE_BRANCH} -- .

# Remove files/directories specified in .studentignore
if [ -f ".studentignore" ]; then
    echo -e "${YELLOW}Applying .studentignore filters...${NC}"
    while IFS= read -r pattern || [ -n "$pattern" ]; do
        # Skip empty lines and comments
        if [[ -z "$pattern" || "$pattern" =~ ^[[:space:]]*# ]]; then
            continue
        fi
        
        # Remove leading/trailing whitespace
        pattern=$(echo "$pattern" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        
        if [ -n "$pattern" ]; then
            echo -e "  Excluding: ${pattern}"
            # Handle absolute paths (starting with /)
            if [[ "$pattern" == /* ]]; then
                # Remove leading slash for relative path
                pattern="${pattern#/}"
                if [ -d "$pattern" ]; then
                    rm -rf "$pattern" 2>/dev/null || true
                elif [ -f "$pattern" ]; then
                    rm -f "$pattern" 2>/dev/null || true
                fi
            # Handle directory patterns (ending with /)
            elif [[ "$pattern" == */ ]]; then
                rm -rf "${pattern%/}" 2>/dev/null || true
            else
                # Handle file patterns (use find for glob support)
                find . -name "$pattern" -delete 2>/dev/null || true
                # Also try exact match for files
                if [ -f "$pattern" ]; then
                    rm -f "$pattern" 2>/dev/null || true
                fi
            fi
        fi
    done < ".studentignore"
fi

git add .

# Create the squashed commit
git commit -m "$COMMIT_MSG"

# Push the clean branch
echo -e "${YELLOW}Force-pushing clean commit to student repository...${NC}"
git push --force ${STUDENT_REMOTE_NAME} ${TEMP_BRANCH}:${TARGET_BRANCH}

# Clean up
git checkout ${SOURCE_BRANCH}
git branch -D ${TEMP_BRANCH}

echo -e "${GREEN}Successfully published to student repository!${NC}"
echo -e "${GREEN}Student repository URL: ${STUDENT_REPO_URL}${NC}"

# Generate default tag name (YYYY-wWW format)
YEAR=$(date +%Y)
WEEK=$(date +%U)
DEFAULT_TAG="${YEAR}-w${WEEK}"

# Optional: Create a tag for this publication
read -p "Create a tag for this publication? [${DEFAULT_TAG}]: " TAG_NAME
if [ -z "$TAG_NAME" ]; then
    TAG_NAME="$DEFAULT_TAG"
fi

if [ -n "$TAG_NAME" ]; then
    echo -e "${YELLOW}Creating and pushing tag: ${TAG_NAME}${NC}"
    git tag -a ${TAG_NAME} -m "Published to students: $(date)"
    git push --force ${STUDENT_REMOTE_NAME} ${TAG_NAME}
    echo -e "${GREEN}Tag ${TAG_NAME} created and pushed${NC}"
fi

echo -e "${GREEN}Publication complete!${NC}"
echo ""
echo "Next steps for students:"
echo "  git clone ${STUDENT_REPO_URL}"
echo ""
echo "To publish updates later:"
echo "  1. Make changes on main branch"
echo "  2. Merge main -> ${SOURCE_BRANCH}"
echo "  3. Manually redact solutions"
echo "  4. Run this script again"