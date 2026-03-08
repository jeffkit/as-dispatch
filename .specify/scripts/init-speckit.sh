#!/usr/bin/env bash
# Speckit Driver initialization script
#
# This script sets up the .specify directory with the necessary scripts and templates
# for the speckit-driver skill to work properly.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[SPECKIT-INIT]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SPECKIT-INIT]${NC} ✓ $1"
}

print_warning() {
    echo -e "${YELLOW}[SPECKIT-INIT]${NC} ⚠ $1"
}

print_error() {
    echo -e "${RED}[SPECKIT-INIT]${NC} ✗ $1"
}

# Get the skill directory path
# For development testing, allow override
SKILL_DIR="${SPECKIT_SKILL_DIR:-$HOME/.claude/skills/speckit-driver}"
SPECIFY_DIR=".specify"

print_status "Initializing Speckit Driver environment..."

# Check if skill directory exists
if [ ! -d "$SKILL_DIR" ]; then
    print_error "Speckit-driver skill not found at $SKILL_DIR"
    print_error "Please install the speckit-driver skill first using:"
    print_error "  /plugin install speckit-driver@jeff-choices"
    exit 1
fi

# Check if .specify directory already exists
if [ -d "$SPECIFY_DIR" ]; then
    print_success ".specify directory already exists - skipping initialization"
    print_status "To reinitialize, remove the .specify directory first:"
    print_status "  rm -rf .specify"
    exit 0
fi

# Create .specify directory structure
print_status "Creating .specify directory structure..."
mkdir -p "$SPECIFY_DIR/scripts"
mkdir -p "$SPECIFY_DIR/templates"
mkdir -p "$SPECIFY_DIR/memory"

# Function to setup directory with copy (more reliable)
setup_directory() {
    local source_dir="$1"
    local target_dir="$2"
    local dir_name="$3"

    print_status "Setting up $dir_name..."

    # Copy files from source to target
    if cp -r "$source_dir"/* "$target_dir/" 2>/dev/null; then
        print_success "Copied files for $dir_name"
        return 0
    fi

    # If copy fails
    print_error "Failed to set up $dir_name"
    return 1
}

# Setup scripts directory
SCRIPTS_SOURCE="$SKILL_DIR/scripts"
SCRIPTS_TARGET="$SPECIFY_DIR/scripts"

if [ -d "$SCRIPTS_SOURCE" ]; then
    if setup_directory "$SCRIPTS_SOURCE" "$SCRIPTS_TARGET" "scripts"; then
        # Make bash scripts executable
        find "$SCRIPTS_TARGET" -name "*.sh" -type f -exec chmod +x {} \;
        print_success "Made scripts executable"
    else
        print_error "Failed to setup scripts directory"
        exit 1
    fi
else
    print_error "Scripts directory not found at $SCRIPTS_SOURCE"
    exit 1
fi

# Setup templates directory
TEMPLATES_SOURCE="$SKILL_DIR/templates"
TEMPLATES_TARGET="$SPECIFY_DIR/templates"

if [ -d "$TEMPLATES_SOURCE" ]; then
    if setup_directory "$TEMPLATES_SOURCE" "$TEMPLATES_TARGET" "templates"; then
        print_success "Templates directory setup complete"
    else
        print_error "Failed to setup templates directory"
        exit 1
    fi
else
    print_error "Templates directory not found at $TEMPLATES_SOURCE"
    exit 1
fi

# Create memory directory structure
print_status "Creating memory directory structure..."
mkdir -p "$SPECIFY_DIR/memory"

# Test the setup by checking if key files exist
print_status "Verifying installation..."

REQUIRED_TEMPLATES=(
    "spec-template.md"
    "plan-template.md"
    "tasks-template.md"
    "checklist-template.md"
    "agent-file-template.md"
)

REQUIRED_SCRIPTS=(
    "bash/check-prerequisites.sh"
    "bash/create-new-feature.sh"
    "bash/setup-plan.sh"
    "bash/update-agent-context.sh"
)

# Check templates
for template in "${REQUIRED_TEMPLATES[@]}"; do
    if [ -f "$SPECIFY_DIR/templates/$template" ]; then
        print_success "Found template: $template"
    else
        print_warning "Missing template: $template"
    fi
done

# Check scripts
for script in "${REQUIRED_SCRIPTS[@]}"; do
    if [ -f "$SPECIFY_DIR/scripts/$script" ]; then
        print_success "Found script: $script"
    else
        print_warning "Missing script: $script"
    fi
done

# Create a marker file to track successful initialization
echo "{\"initialized_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"skill_version\":\"1.1.1\",\"method\":\"copy\"}" > "$SPECIFY_DIR/.init-info.json"

print_success "Speckit Driver initialization completed successfully!"
print_status ""
print_status "You can now use speckit commands like:"
print_status "  '用speckit开发一个用户登录功能'"
print_status "  '使用speckit构建API服务'"
print_status ""
print_status "The .specify directory contains:"
print_status "  - scripts/: Speckit utility scripts"
print_status "  - templates/: Document templates"
print_status "  - memory/: Project constitution and memory"
print_status ""
print_status "To remove this setup: rm -rf .specify"