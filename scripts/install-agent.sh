#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.local/share/cc4slack"
CONFIG_DIR="$HOME/.config/cc4slack"
REPO_URL="https://github.com/omer-vishlitzky/cc4slack.git"
DEFAULT_ROUTER_URL="wss://assisted-bot.apps.ext.spoke.prod.us-east-1.aws.paas.redhat.com/ws/agent"
SERVICE_DIR="$HOME/.config/systemd/user"

echo "=== cc4slack agent installer ==="
echo ""

systemctl --user stop cc4slack-agent 2>/dev/null || true

if [ -d "$INSTALL_DIR" ]; then
    echo "Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --quiet
else
    echo "Cloning cc4slack..."
    git clone --quiet "$REPO_URL" "$INSTALL_DIR" --branch main
fi

cd "$INSTALL_DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install --quiet -r requirements-agent.txt

mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/.env" ]; then
    echo ""
    read -rp "Working directory [$HOME]: " working_dir < /dev/tty
    working_dir="${working_dir:-$HOME}"

    cat > "$CONFIG_DIR/.env" << EOF
ROUTER_URL=$DEFAULT_ROUTER_URL
WORKING_DIRECTORY=$working_dir
PERMISSION_MODE=default
EOF
    echo "Config saved to $CONFIG_DIR/.env"
fi

mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_DIR/cc4slack-agent.service" << EOF
[Unit]
Description=cc4slack agent — Claude Code for Slack
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$CONFIG_DIR/.env
ExecStart=$(getent passwd $USER | cut -d: -f7) -lc 'exec $INSTALL_DIR/.venv/bin/python -m agent.main'
Restart=always
RestartSec=10
Environment=PYTHONPATH=$INSTALL_DIR

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload

echo ""
echo "=== Verifying agent ==="
echo ""
echo "Paste the verification code in Slack when prompted."
echo ""

cd "$INSTALL_DIR"
set -a; source "$CONFIG_DIR/.env"; set +a
PYTHONPATH="$INSTALL_DIR" .venv/bin/python -m agent.main --verify-only

echo ""
echo "Starting systemd service..."
systemctl --user enable cc4slack-agent
systemctl --user start cc4slack-agent
echo ""
echo "Agent is running as a systemd service."
echo ""
echo "Useful commands:"
echo "  journalctl --user -u cc4slack-agent -f     # view logs"
echo "  systemctl --user restart cc4slack-agent     # restart"
echo "  systemctl --user stop cc4slack-agent        # stop"
echo "  systemctl --user status cc4slack-agent      # status"
echo ""
echo "Config: $CONFIG_DIR/.env"
echo "Code:   $INSTALL_DIR"
