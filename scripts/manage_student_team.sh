#!/bin/bash
# Script to manage GitHub teams for student repository access
# Creates a team with read-only access and adds students by email

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse command line arguments
CONFIG_FILE=".course-config"
STUDENT_FILE=""
TERM=""
ACTION="create"

show_help() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Manage GitHub teams for student repository access"
    echo ""
    echo "Options:"
    echo "  --config FILE          Use custom configuration file (default: .course-config)"
    echo "  --online               Use online course configuration (.course-config-online)"
    echo "  --students FILE        File containing student emails (one per line)"
    echo "  --term TERM            Academic term (e.g., fall2025, spring2026)"
    echo "  --action ACTION        Action to perform: create, add, remove, delete (default: create)"
    echo "  -h, --help             Show this help message"
    echo ""
    echo "Actions:"
    echo "  create    Create team and add students (default)"
    echo "  add       Add students to existing team"
    echo "  remove    Remove students from team"
    echo "  delete    Delete the team entirely"
    echo ""
    echo "Examples:"
    echo "  # Create team for fall 2025 with students from file"
    echo "  $0 --students students.txt --term fall2025"
    echo ""
    echo "  # Add more students to existing team"
    echo "  $0 --students new_students.txt --term fall2025 --action add"
    echo ""
    echo "  # Create team for online course"
    echo "  $0 --online --students students.txt --term fall2025"
    echo ""
    echo "Student file format (one email per line):"
    echo "  student1@example.edu"
    echo "  student2@example.edu"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --online)
            CONFIG_FILE=".course-config-online"
            shift
            ;;
        --students)
            STUDENT_FILE="$2"
            shift 2
            ;;
        --term)
            TERM="$2"
            shift 2
            ;;
        --action)
            ACTION="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo -e "${RED}Error: Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Validate required arguments for create/add/remove actions
if [ "$ACTION" != "delete" ]; then
    if [ -z "$STUDENT_FILE" ]; then
        echo -e "${RED}Error: --students FILE is required for action: ${ACTION}${NC}"
        echo "Use --help for usage information"
        exit 1
    fi

    if [ ! -f "$STUDENT_FILE" ]; then
        echo -e "${RED}Error: Student file not found: ${STUDENT_FILE}${NC}"
        exit 1
    fi
fi

if [ -z "$TERM" ]; then
    echo -e "${RED}Error: --term TERM is required${NC}"
    echo "Use --help for usage information"
    exit 1
fi

# Validate action
if [[ ! "$ACTION" =~ ^(create|add|remove|delete)$ ]]; then
    echo -e "${RED}Error: Invalid action: ${ACTION}${NC}"
    echo "Valid actions: create, add, remove, delete"
    exit 1
fi

# Load course configuration
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}Error: Configuration file not found: $CONFIG_FILE${NC}"
    exit 1
fi

source "$CONFIG_FILE"

# Validate required configuration
if [ -z "$COURSE_CODE" ]; then
    echo -e "${RED}Error: COURSE_CODE not set in $CONFIG_FILE${NC}"
    exit 1
fi

# Set default student repo URL if not specified
if [ -z "$STUDENT_REPO_URL" ]; then
    STUDENT_REPO_URL="https://github.com/CSUMB-SCD-instructors/${COURSE_CODE}.git"
fi

# Extract org and repo name from URL
# Handle both HTTPS and SSH URLs
if [[ "$STUDENT_REPO_URL" =~ github\.com[:/]([^/]+)/([^/.]+) ]]; then
    ORG="${BASH_REMATCH[1]}"
    REPO="${BASH_REMATCH[2]}"
else
    echo -e "${RED}Error: Could not parse GitHub org/repo from URL: ${STUDENT_REPO_URL}${NC}"
    exit 1
fi

# Construct team name: REPO:students:TERM
TEAM_NAME="${REPO}:students:${TERM}"
TEAM_SLUG=$(echo "$TEAM_NAME" | tr '[:upper:]' '[:lower:]' | tr ':' '-')

echo -e "${YELLOW}GitHub Team Management${NC}"
echo -e "  Organization: ${GREEN}${ORG}${NC}"
echo -e "  Repository: ${GREEN}${REPO}${NC}"
echo -e "  Team Name: ${GREEN}${TEAM_NAME}${NC}"
echo -e "  Team Slug: ${GREEN}${TEAM_SLUG}${NC}"
echo -e "  Term: ${GREEN}${TERM}${NC}"
echo -e "  Action: ${GREEN}${ACTION}${NC}"
if [ -n "$STUDENT_FILE" ]; then
    STUDENT_COUNT=$(grep -c -v '^[[:space:]]*$' "$STUDENT_FILE" 2>/dev/null || echo "0")
    echo -e "  Students: ${GREEN}${STUDENT_COUNT} from ${STUDENT_FILE}${NC}"
fi
echo ""

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo -e "${RED}Error: GitHub CLI (gh) is not installed${NC}"
    echo "Install it with: brew install gh"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo -e "${RED}Error: Not authenticated with GitHub CLI${NC}"
    echo "Run: gh auth login"
    exit 1
fi

# Function to check if team exists
team_exists() {
    gh api "/orgs/${ORG}/teams/${TEAM_SLUG}" &> /dev/null
    return $?
}

# Function to create team
create_team() {
    echo -e "${YELLOW}Creating team: ${TEAM_NAME}${NC}"

    gh api \
        --method POST \
        -H "Accept: application/vnd.github+json" \
        "/orgs/${ORG}/teams" \
        -f name="${TEAM_NAME}" \
        -f description="Students for ${REPO} (${TERM})" \
        -f privacy="closed" \
        > /dev/null

    echo -e "${GREEN}✓ Team created${NC}"

    # Add repository with read permission
    echo -e "${YELLOW}Adding repository with read permission...${NC}"
    gh api \
        --method PUT \
        -H "Accept: application/vnd.github+json" \
        "/orgs/${ORG}/teams/${TEAM_SLUG}/repos/${ORG}/${REPO}" \
        -f permission="pull" \
        > /dev/null

    echo -e "${GREEN}✓ Repository access configured (read-only)${NC}"
}

# Function to add students to team
add_students() {
    local count=0
    local failed=0

    echo -e "${YELLOW}Adding students to team...${NC}"

    while IFS= read -r email || [ -n "$email" ]; do
        # Skip empty lines and comments
        if [[ -z "$email" || "$email" =~ ^[[:space:]]*# ]]; then
            continue
        fi

        # Remove leading/trailing whitespace
        email=$(echo "$email" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

        if [ -n "$email" ]; then
            echo -n "  Adding ${email}... "

            # Add member by email (they'll get an invitation)
            if gh api \
                --method POST \
                -H "Accept: application/vnd.github+json" \
                "/orgs/${ORG}/teams/${TEAM_SLUG}/memberships/${email}" \
                -f role="member" \
                &> /dev/null; then
                echo -e "${GREEN}✓${NC}"
                ((count++))
            else
                echo -e "${RED}✗${NC}"
                ((failed++))
            fi
        fi
    done < "$STUDENT_FILE"

    echo ""
    echo -e "${GREEN}Added ${count} student(s)${NC}"
    if [ $failed -gt 0 ]; then
        echo -e "${YELLOW}Failed to add ${failed} student(s)${NC}"
    fi
}

# Function to remove students from team
remove_students() {
    local count=0
    local failed=0

    echo -e "${YELLOW}Removing students from team...${NC}"

    while IFS= read -r email || [ -n "$email" ]; do
        # Skip empty lines and comments
        if [[ -z "$email" || "$email" =~ ^[[:space:]]*# ]]; then
            continue
        fi

        # Remove leading/trailing whitespace
        email=$(echo "$email" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

        if [ -n "$email" ]; then
            echo -n "  Removing ${email}... "

            if gh api \
                --method DELETE \
                -H "Accept: application/vnd.github+json" \
                "/orgs/${ORG}/teams/${TEAM_SLUG}/memberships/${email}" \
                &> /dev/null; then
                echo -e "${GREEN}✓${NC}"
                ((count++))
            else
                echo -e "${RED}✗${NC}"
                ((failed++))
            fi
        fi
    done < "$STUDENT_FILE"

    echo ""
    echo -e "${GREEN}Removed ${count} student(s)${NC}"
    if [ $failed -gt 0 ]; then
        echo -e "${YELLOW}Failed to remove ${failed} student(s)${NC}"
    fi
}

# Function to delete team
delete_team() {
    echo -e "${YELLOW}WARNING: This will delete the entire team!${NC}"
    read -p "Are you sure you want to delete team '${TEAM_NAME}'? (y/N): " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Deletion cancelled.${NC}"
        exit 0
    fi

    echo -e "${YELLOW}Deleting team: ${TEAM_NAME}${NC}"

    gh api \
        --method DELETE \
        -H "Accept: application/vnd.github+json" \
        "/orgs/${ORG}/teams/${TEAM_SLUG}" \
        > /dev/null

    echo -e "${GREEN}✓ Team deleted${NC}"
}

# Main execution based on action
case $ACTION in
    create)
        if team_exists; then
            echo -e "${YELLOW}Team already exists: ${TEAM_NAME}${NC}"
            echo -e "${YELLOW}Use --action add to add more students${NC}"
            exit 1
        fi

        create_team
        add_students
        ;;

    add)
        if ! team_exists; then
            echo -e "${RED}Error: Team does not exist: ${TEAM_NAME}${NC}"
            echo -e "${RED}Use --action create to create it first${NC}"
            exit 1
        fi

        add_students
        ;;

    remove)
        if ! team_exists; then
            echo -e "${RED}Error: Team does not exist: ${TEAM_NAME}${NC}"
            exit 1
        fi

        remove_students
        ;;

    delete)
        if ! team_exists; then
            echo -e "${RED}Error: Team does not exist: ${TEAM_NAME}${NC}"
            exit 1
        fi

        delete_team
        ;;
esac

echo ""
echo -e "${GREEN}Operation complete!${NC}"
echo ""
echo "View team at: https://github.com/orgs/${ORG}/teams/${TEAM_SLUG}"