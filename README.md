# cc4slack — Claude Code for Slack

Use Claude Code from Slack. Each developer runs their own Claude agent on a beaker machine, connected to Slack through a shared router.

## For Developers: Connect Your Agent

### 1. Clone and start

```bash
curl -fsSL https://raw.githubusercontent.com/eranco74/cc4slack/main/scripts/install-agent.sh | bash
```

This clones the repo, installs dependencies, prompts for config, and runs the agent for initial verification. After verification, it installs a systemd service that runs in the background and auto-restarts.

### 2. Verify in Slack

The installer runs the agent and prints a verification code. Type it in Slack:

```
@assisted-bot verify K7x9mP2q...
```

### 3. Use it

Mention the bot in any channel or DM:

```
@assisted-bot help me debug this failing test
```

Each thread is a separate conversation. Claude can read files, write code, run commands — everything you can do in the terminal.

## Commands

| Command | Description |
|---------|-------------|
| `verify <code>` | Connect your beaker agent |
| `unregister` | Disconnect your agent |
| `status` | Show connection and session info |
| `mode` | Show current permission mode |
| `mode <mode>` | Change permission mode |
| `cwd` | Show working directory |
| `cwd <path>` | Change working directory |
| `help` | Show available commands |

## Permission Modes

| Mode | Description |
|------|-------------|
| `default` | Use Claude's settings from `.claude/settings.json` |
| `bypass` | All tools run without checks (use in sandboxed environments only) |
| `allowEdits` | File edits auto-approved, bash commands blocked |
| `plan` | Read-only — no file writes or bash commands |

Change per thread: `@assisted-bot mode allowEdits`

## Agent Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ROUTER_URL` | (required) | WebSocket URL of the router |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (optional if using default auth) |
| `CLAUDE_MODEL` | claude-sonnet-4-20250514 | Model to use |
| `CLAUDE_MAX_TURNS` | 50 | Max conversation turns per request |
| `WORKING_DIRECTORY` | . | Default working directory for Claude |
| `PERMISSION_MODE` | default | Default permission mode |
| `RECONNECT_DELAY_SECONDS` | 5 | Seconds to wait before reconnecting |
| `LOG_LEVEL` | INFO | Logging level |

## For Admins: Deploy the Router

### Router Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SLACK_BOT_TOKEN` | (required) | Bot token (xoxb-...) |
| `SLACK_SIGNING_SECRET` | (required) | Slack signing secret |
| `TOKEN_EXPIRY_SECONDS` | 300 | Verification token TTL |
| `REDIS_URL` | (required) | Redis URL for state persistence |
| `LOG_LEVEL` | INFO | Logging level |

### Persistence

The router requires Redis for state persistence:
- Auth tokens (7-day TTL) — agents reconnect without re-verification after restarts
- Thread state (24h TTL) — cost, turns, config survive router restarts
- Agent saves session locally to `~/.config/cc4slack/session.json`

### Deploy to OpenShift

```bash
export SLACK_BOT_TOKEN=xoxb-YOUR_TOKEN
export SLACK_SIGNING_SECRET=YOUR_SECRET
./scripts/deploy-router.sh
```

The script builds the image, pushes to Quay, deploys Redis with a PVC, creates secrets (including Redis URL), and deploys the router. Run it again to redeploy after code changes.

### Slack App Setup

The router requires a Slack app with these bot scopes:

| Scope | Purpose |
|-------|---------|
| `app_mentions:read` | Receive @mentions |
| `chat:write` | Send responses |
| `im:history` | Read DM history |
| `im:read` | Access DMs |
| `im:write` | Send DMs |
| `files:read` | Read uploaded files |
| `channels:read` | Read channel info |

Event subscriptions:
- `app_mention` — mentions in channels
- `message.im` — direct messages

Request URL: `https://<route-hostname>/slack/events`

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full architecture, security model, and protocol documentation.

## Troubleshooting

**"No agent connected"** — Start your agent on your beaker machine and verify with the code.

**"Verification failed"** — Token expired (5 min TTL). Restart the agent to get a new code.

**Agent keeps disconnecting** — Check network connectivity between beaker and the router. The agent auto-reconnects, but you'll need to re-verify.

**"Still processing previous request"** — Claude is working on a previous message in the same thread. Wait for it to finish or use a different thread.
