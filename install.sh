#!/usr/bin/env bash
set -euo pipefail

# cc4slack installer
# Usage: curl -fsSL https://raw.githubusercontent.com/eranco74/cc4slack/master/install.sh | bash

REPO="https://github.com/eranco74/cc4slack.git"
INSTALL_DIR="${CC4SLACK_DIR:-$HOME/cc4slack}"
PYTHON="${PYTHON:-python3}"
MIN_PYTHON="3.11"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}▸${NC} $*"; }
warn()  { echo -e "${YELLOW}▸${NC} $*"; }
error() { echo -e "${RED}✘${NC} $*" >&2; }
bold()  { echo -e "${BOLD}$*${NC}"; }

# --- Pre-flight checks ---

# Python version
if ! command -v "$PYTHON" &>/dev/null; then
    error "Python 3 not found. Install Python >= $MIN_PYTHON and try again."
    exit 1
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if "$PYTHON" -c "import sys; exit(0 if sys.version_info >= (3,11) else 1)"; then
    info "Python $PY_VERSION ✓"
else
    error "Python >= $MIN_PYTHON required (found $PY_VERSION)"
    exit 1
fi

# Claude CLI
if ! command -v claude &>/dev/null; then
    error "Claude Code CLI not found. Install it first:"
    echo "  npm install -g @anthropic-ai/claude-code"
    echo "  or visit https://docs.anthropic.com/en/docs/claude-code"
    exit 1
fi
info "Claude CLI $(claude --version 2>/dev/null || echo 'found') ✓"

# Git
if ! command -v git &>/dev/null; then
    error "git not found. Please install git and try again."
    exit 1
fi

# --- Install ---

if [ -d "$INSTALL_DIR" ]; then
    info "Updating existing installation in $INSTALL_DIR"
    cd "$INSTALL_DIR"
    git pull --ff-only origin master
else
    info "Cloning cc4slack to $INSTALL_DIR"
    git clone "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Virtual environment
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv .venv
fi

info "Installing dependencies..."
if ! .venv/bin/pip install -q -e . 2>&1 | tail -3; then
    error "Failed to install dependencies. Run manually:"
    echo "  cd $INSTALL_DIR && .venv/bin/pip install -e ."
    exit 1
fi

# --- Configure ---

if [ ! -f .env ]; then
    bold ""
    bold "═══════════════════════════════════════════"
    bold "  cc4slack setup"
    bold "═══════════════════════════════════════════"
    echo ""
    echo "You need Slack app tokens. If you haven't created a Slack app yet,"
    echo "follow the instructions in the README:"
    echo "  https://github.com/eranco74/cc4slack#2-configure-the-slack-app"
    echo ""

    read -rp "Slack Bot Token (xoxb-...): " SLACK_BOT_TOKEN </dev/tty
    read -rp "Slack App Token (xapp-...): " SLACK_APP_TOKEN </dev/tty
    read -rp "Working directory for Claude [$(pwd)]: " WORKING_DIR </dev/tty
    WORKING_DIR="${WORKING_DIR:-$(pwd)}"
    read -rp "Permission mode (default/bypass/allowEdits/plan) [default]: " PERM_MODE </dev/tty
    PERM_MODE="${PERM_MODE:-default}"

    cat > .env <<ENVEOF
# Slack Configuration
SLACK_BOT_TOKEN=${SLACK_BOT_TOKEN}
SLACK_APP_TOKEN=${SLACK_APP_TOKEN}

# Claude Configuration
CLAUDE_MODEL=
CLAUDE_MAX_TURNS=50

# Permission mode: default (use Claude settings), bypass (all tools), allowEdits (edits ok, bash blocked), plan (read-only)
PERMISSION_MODE=${PERM_MODE}

# Working Directory
WORKING_DIRECTORY=${WORKING_DIR}

# Session Configuration
SESSION_STORAGE=memory
SESSION_TTL_SECONDS=86400
LOG_LEVEL=INFO
ENVEOF

    info "Configuration saved to .env"
else
    info "Using existing .env configuration"
fi

# --- Done ---

echo ""
bold "═══════════════════════════════════════════"
bold "  cc4slack installed successfully! 🎉"
bold "═══════════════════════════════════════════"
echo ""
echo "  Start the app:"
echo ""
echo "    cd $INSTALL_DIR && .venv/bin/cc4slack"
echo ""
echo "  Or activate the venv first:"
echo ""
echo "    cd $INSTALL_DIR"
echo "    source .venv/bin/activate"
echo "    cc4slack"
echo ""
echo "  Edit configuration:  $INSTALL_DIR/.env"
echo "  View README:         https://github.com/eranco74/cc4slack"
echo ""
