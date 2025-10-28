#!/bin/bash
# Script to publish redacted_for_students branch to student repository
# This creates a clean history without exposing solution commits

set -e  # Exit on any error

# Colors for output (defined early for usage messages)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse command line arguments
CONFIG_FILE=".course-config"
PUBLISHING_MODE="default"

while [[ $# -gt 0 ]]; do
    case $1 in
        --online)
            CONFIG_FILE=".course-config-online"
            PUBLISHING_MODE="online"
            shift
            ;;
        --config)
            CONFIG_FILE="$2"
            PUBLISHING_MODE="custom"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --online           Use online course configuration (.course-config-online)"
            echo "  --config FILE      Use custom configuration file"
            echo "  -h, --help         Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                 # Publish in-person course (default)"
            echo "  $0 --online        # Publish online course variant"
            echo "  $0 --config .course-config-custom  # Use custom config"
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Load course configuration
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}Error: Configuration file not found: $CONFIG_FILE${NC}"
    echo -e "${RED}This file is required to determine course-specific settings${NC}"
    exit 1
fi

source "$CONFIG_FILE"

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

# Set defaults for optional configuration variables
if [ -z "$STUDENT_REPO_URL" ]; then
    STUDENT_REPO_URL="https://github.com/CSUMB-SCD-instructors/${COURSE_CODE}.git"
fi

if [ -z "$SYLLABUS_SOURCE" ]; then
    SYLLABUS_SOURCE="syllabus.md"
fi

if [ -z "$SYLLABUS_DEST" ]; then
    SYLLABUS_DEST="syllabus.md"
fi

if [ -z "$STUDENTIGNORE_FILE" ]; then
    STUDENTIGNORE_FILE=".studentignore"
fi

# ASSIGNMENT_REMAP should be an array, default to empty if not set
if [ -z "${ASSIGNMENT_REMAP+x}" ]; then
    ASSIGNMENT_REMAP=()
fi

# Configuration
STUDENT_REMOTE_NAME="student-repo"
SOURCE_BRANCH="redacted_for_students"
TARGET_BRANCH="main"  # Branch name in student repository

# Display publishing configuration
echo -e "${YELLOW}Publishing ${SOURCE_BRANCH} to student repository...${NC}"
if [ "$PUBLISHING_MODE" = "online" ]; then
    echo -e "${YELLOW}Mode: ${GREEN}ONLINE${NC}"
elif [ "$PUBLISHING_MODE" = "custom" ]; then
    echo -e "${YELLOW}Mode: ${GREEN}CUSTOM (${CONFIG_FILE})${NC}"
fi
echo -e "${YELLOW}Course Configuration:${NC}"
echo -e "  Course Code: ${GREEN}${COURSE_CODE}${NC}"
echo -e "  Course Name: ${GREEN}${COURSE_NAME}${NC}"
echo -e "  Student Repo: ${GREEN}${STUDENT_REPO_URL}${NC}"

# Show syllabus mapping if non-default
if [ "$SYLLABUS_SOURCE" != "syllabus.md" ] || [ "$SYLLABUS_DEST" != "syllabus.md" ]; then
    echo -e "  Syllabus: ${GREEN}${SYLLABUS_SOURCE}${NC} → ${GREEN}${SYLLABUS_DEST}${NC}"
fi

# Show assignment remapping if configured
if [ ${#ASSIGNMENT_REMAP[@]} -gt 0 ]; then
    echo -e "  ${YELLOW}Assignment Remapping:${NC}"
    for remap in "${ASSIGNMENT_REMAP[@]}"; do
        IFS=':' read -r source dest <<< "$remap"
        echo -e "    ${GREEN}${source}${NC} → ${GREEN}${dest}${NC}"
    done
fi

# Show studentignore file if non-default
if [ "$STUDENTIGNORE_FILE" != ".studentignore" ]; then
    echo -e "  Exclusions file: ${GREEN}${STUDENTIGNORE_FILE}${NC}"
fi

echo ""

# Final safety check with course details
read -p "Confirm this is the correct course configuration before publishing (y/N): " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Publication cancelled - please verify your configuration settings${NC}"
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

# Check if repository exists and offer to create it if not
echo -e "${YELLOW}Checking if student repository exists...${NC}"
if ! gh repo view ${STUDENT_REPO_URL} >/dev/null 2>&1; then
    echo -e "${YELLOW}Repository does not exist: ${STUDENT_REPO_URL}${NC}"
    read -p "Would you like to create this repository now? (y/N): " -r
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Creating private repository...${NC}"

        # Extract org/repo from URL
        REPO_PATH=$(echo ${STUDENT_REPO_URL} | sed -E 's|https://github.com/([^/]+/[^/]+)(\.git)?|\1|')

        # Create the repository with gh CLI
        if gh repo create ${REPO_PATH} --private --description "${COURSE_NAME} - Student Repository"; then
            echo -e "${GREEN}Repository created successfully!${NC}"
        else
            echo -e "${RED}Error: Failed to create repository${NC}"
            echo -e "${RED}Please create the repository manually and try again${NC}"
            exit 1
        fi
    else
        echo -e "${RED}Error: Repository does not exist and creation was declined${NC}"
        echo -e "${RED}Please create the repository manually at: ${STUDENT_REPO_URL}${NC}"
        exit 1
    fi
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

# Copy current state from redacted branch
# First, remove all tracked files to ensure deletions are reflected
git rm -rf . 2>/dev/null || true
# Then copy everything fresh from source branch
git checkout ${SOURCE_BRANCH} -- .

# Apply syllabus mapping if configured
if [ "$SYLLABUS_SOURCE" != "syllabus.md" ] && [ -f "$SYLLABUS_SOURCE" ]; then
    echo -e "${YELLOW}Mapping syllabus: ${SYLLABUS_SOURCE} → ${SYLLABUS_DEST}${NC}"
    if [ "$SYLLABUS_SOURCE" != "$SYLLABUS_DEST" ]; then
        mv "$SYLLABUS_SOURCE" "$SYLLABUS_DEST" 2>/dev/null || cp "$SYLLABUS_SOURCE" "$SYLLABUS_DEST"
    fi
elif [ "$SYLLABUS_SOURCE" != "syllabus.md" ]; then
    echo -e "${RED}Warning: Syllabus source file not found: ${SYLLABUS_SOURCE}${NC}"
fi

# Apply assignment remapping if configured
if [ ${#ASSIGNMENT_REMAP[@]} -gt 0 ]; then
    echo -e "${YELLOW}Applying assignment remapping...${NC}"
    for remap in "${ASSIGNMENT_REMAP[@]}"; do
        IFS=':' read -r source dest <<< "$remap"

        # Determine base directory (assume programming-assignments/ if not absolute path)
        if [[ "$source" != /* ]]; then
            source_path="programming-assignments/${source}"
            dest_path="programming-assignments/${dest}"
        else
            source_path="$source"
            dest_path="$dest"
        fi

        if [ -d "$source_path" ]; then
            echo -e "  Renaming: ${source_path} → ${dest_path}"
            # Create parent directory if needed
            mkdir -p "$(dirname "$dest_path")"
            mv "$source_path" "$dest_path"
        else
            echo -e "  ${RED}Warning: Source directory not found: ${source_path}${NC}"
        fi
    done
fi

# Remove files/directories specified in studentignore file
if [ -f "$STUDENTIGNORE_FILE" ]; then
    echo -e "${YELLOW}Applying ${STUDENTIGNORE_FILE} filters...${NC}"
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
    done < "$STUDENTIGNORE_FILE"
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