# cc4slack - Claude Code for Slack

Interact with Claude Code directly from Slack. This app brings the full power of Claude Code's agentic coding assistant capabilities to your Slack workspace.

## Features

- **Full Agent Mode**: Claude can read files, write code, run commands, and help with any coding task
- **Thread-Based Sessions**: Each Slack thread maintains its own conversation context
- **Session Continuity**: Connect Slack threads to existing Claude Code terminal sessions, or resume Slack sessions from the terminal
- **Permission Modes**: Control what tools Claude can use — from read-only to full access
- **Per-Thread Overrides**: Change working directory or permission mode per thread
- **File Uploads**: Upload files to Slack and they're saved to the working directory for Claude to use
- **Cost Tracking**: See API cost, turns, and duration when clearing a session
- **Streaming Responses**: See Claude's responses as they're generated
- **Socket Mode**: No public URL required — easy local development and deployment

## Quick Start

### One-Line Install

```bash
curl -fsSL https://raw.githubusercontent.com/eranco74/cc4slack/master/install.sh | bash
```

This clones the repo, creates a virtual environment, installs dependencies, and prompts for your Slack tokens. Requires Python 3.11+ and the [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code).

### Manual Setup

### 1. Create a Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) and click "Create New App"
2. Choose "From scratch" and give it a name (e.g., "Claude Code")
3. Select your workspace

### 2. Configure the Slack App

#### Enable Socket Mode
1. Go to **Settings > Socket Mode**
2. Enable Socket Mode
3. Create an App-Level Token with `connections:write` scope
4. Save the token (starts with `xapp-`)

#### Add Bot Scopes
1. Go to **OAuth & Permissions**
2. Under "Bot Token Scopes", add:
   - `app_mentions:read` - Read mentions of the bot
   - `chat:write` - Send messages
   - `files:read` - Read uploaded files
   - `im:history` - Read direct message history
   - `im:read` - Access direct messages
   - `im:write` - Send direct messages
   - `reactions:write` - Add emoji reactions

#### Subscribe to Events
1. Go to **Event Subscriptions**
2. Enable Events
3. Under "Subscribe to bot events", add:
   - `app_mention` - When someone mentions the bot
   - `message.im` - Direct messages to the bot

#### Enable Interactivity
1. Go to **Interactivity & Shortcuts**
2. Turn on Interactivity (no URL needed for Socket Mode)

#### Install to Workspace
1. Go to **OAuth & Permissions**
2. Click "Install to Workspace"
3. Copy the "Bot User OAuth Token" (starts with `xoxb-`)

### 3. Set Up the App

```bash
# Clone or navigate to the project
cd cc4slack

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# For development dependencies (testing, linting)
pip install -e ".[dev]"
```

### 4. Configure Environment Variables

Create a `.env` file with your tokens:

```env
# Required - Slack tokens
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token

# Optional - Anthropic API key (if not using default auth)
ANTHROPIC_API_KEY=sk-ant-your-api-key

# Optional - Working directory for Claude
WORKING_DIRECTORY=/path/to/your/project

# Permission mode (default, bypass, allowEdits, plan)
PERMISSION_MODE=default
```

### 5. Run the App

```bash
python -m src.main
```

Or if installed:

```bash
cc4slack
```

## Usage

### In Channels
Mention the bot with your request:
```
@Claude Code Help me write a function to parse JSON
```

### In Direct Messages
Just send a message directly to the bot:
```
Can you review this code for security issues?
```

### In Threads
Continue conversations in threads — each thread maintains its own session context.

### Commands

| Command | Description |
|---------|-------------|
| `connect` | Connect to the most recent Claude terminal session |
| `connect <number>` | Connect by index from the sessions list |
| `connect <session-id>` | Connect by full session ID |
| `sessions` | List available Claude sessions |
| `cwd` | Show current working directory |
| `cwd <path>` | Change working directory for this thread |
| `mode` | Show current permission mode |
| `mode <mode>` | Change permission mode for this thread |
| `help` | Show available commands |

### File Uploads
Upload files in a thread — they'll be saved to the working directory and passed to Claude as context.

### Interactive Buttons

- **Cancel**: Stop the current operation while Claude is processing
- **Clear Session**: End the session and see a cost/usage summary
- **Status**: Show session details (cwd, permission mode, cost, turns, session ID)

## Permission Modes

Control what tools Claude can use via the `PERMISSION_MODE` env var or the `mode` command per thread:

| Mode | Description |
|------|-------------|
| `default` | Use Claude's built-in permissions from `~/.claude/settings.json` and `.claude/settings.local.json`. Allowed tools run, others are blocked. |
| `bypass` | All tools run without permission checks. **Only use in sandboxed environments.** |
| `allowEdits` | File edits (Write, Edit) are auto-approved. Bash commands are blocked unless explicitly allowed in settings. |
| `plan` | Read-only mode. No file writes or bash commands allowed. |

Example — set mode per thread in Slack:
```
mode allowEdits
```

> **Note**: The Claude Code SDK's `can_use_tool` callback does not currently work in headless mode, so interactive per-tool approval buttons are not available. Permission control is handled via the CLI's built-in permission modes instead.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_BOT_TOKEN` | Required | Slack bot token (xoxb-...) |
| `SLACK_APP_TOKEN` | Required | Slack app token (xapp-...) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (optional if using default auth) |
| `CLAUDE_MODEL` | claude-sonnet-4-20250514 | Claude model to use |
| `CLAUDE_MAX_TURNS` | 50 | Maximum conversation turns |
| `PERMISSION_MODE` | default | Permission mode (default, bypass, allowEdits, plan) |
| `WORKING_DIRECTORY` | . | Working directory for Claude |
| `SESSION_STORAGE` | memory | Storage backend (memory/redis) |
| `SESSION_TTL_SECONDS` | 86400 | Session lifetime in seconds (24 hours) |
| `LOG_LEVEL` | INFO | Logging level |

## Architecture

```
src/
├── __init__.py
├── main.py                 # Entry point, app lifecycle
├── config.py               # Pydantic settings from env
├── slack/
│   ├── app.py              # Slack Bolt app setup
│   ├── events.py           # Event handlers, command routing
│   ├── actions.py          # Button click handlers (cancel/clear/status)
│   ├── blocks.py           # Block Kit UI components
│   └── message_updater.py  # Streaming message updates
├── claude/
│   ├── agent.py            # Claude Code SDK integration
│   └── tool_approval.py    # Approval types (unused — SDK limitation)
└── sessions/
    ├── manager.py           # Session dataclass and lifecycle
    └── storage.py           # Storage backend (memory)
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src

# Linting
ruff check src
```

## License

MIT
