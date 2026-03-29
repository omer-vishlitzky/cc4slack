# cc4slack Architecture

## Overview

cc4slack connects Slack users to personal Claude Code instances running on beaker machines. A single Slack app (assisted-bot) acts as a router, dispatching messages to each developer's agent over WebSocket.

```
Developer A (Slack)                    Developer B (Slack)
       │                                      │
       ▼                                      ▼
┌─────────────────────────────────────────────────┐
│              assisted-bot (router)               │
│           MPP OpenShift (runtime-ext)            │
│                                                  │
│  Slack events ──→ lookup user ──→ forward via WS │
│  active_registrations:                           │
│    U12345 → ws_connection_A                      │
│    U67890 → ws_connection_B                      │
└──────────┬──────────────────────┬────────────────┘
           │ WebSocket            │ WebSocket
           ▼                      ▼
   ┌──────────────┐       ┌──────────────┐
   │  Beaker A    │       │  Beaker B    │
   │  Claude Code │       │  Claude Code │
   │  (Dev A)     │       │  (Dev B)     │
   └──────────────┘       └──────────────┘
```

## Components

### Router (assisted-bot on MPP)

FastAPI app deployed on OpenShift. Receives Slack events via HTTP webhook, maintains WebSocket connections from beaker agents, and forwards events to the correct agent.

- Receives all Slack events at `/slack/events`
- Maintains a registry of verified user → WebSocket connection mappings
- Forwards events to the correct beaker agent
- Posts Claude's responses back to Slack using the bot token

### Agent (beaker machine)

Lightweight process that connects outbound to the router via WebSocket. Runs Claude Code SDK to process messages. No open ports needed on the beaker machine.

- Connects outbound to the router's `/ws/agent` endpoint
- Receives forwarded Slack events over the WebSocket
- Processes messages through Claude Code SDK
- Sends responses back over the WebSocket (router posts them to Slack)

## Connection Flow (WebSocket)

The beaker agent connects outbound to the router. No inbound ports need to be open on the beaker machine.

```
Beaker agent starts
       │
       ▼
  WebSocket connect to router
  wss://assisted-bot.apps.ext.spoke.prod.us-east-1.aws.paas.redhat.com/ws/agent
       │
       ▼
  Connection established
  Agent sends: {"type": "register", "token": "<one-time-token>"}
       │
       ▼
  Router stores pending registration:
    token → ws_connection (no user yet)
       │
       ▼
  Agent displays verification code in terminal
  Waiting for Slack verification...
```

## Security: Registration and Verification

### Threat Model

A Claude Code instance on a developer's beaker machine holds sensitive credentials (SSH keys, API tokens, Jira/GitHub access). If an attacker can route their Slack messages to a victim's beaker machine, they achieve remote code execution with the victim's credentials.

### Verification Flow

Registration requires proving you control BOTH the beaker terminal AND the Slack account. Neither alone is sufficient.

```
Step 1: Dev starts agent on beaker
$ ./start-agent.sh

  Agent generates a random 32-char token locally.
  Agent connects to router via WebSocket.
  Agent sends token to router as a pending registration.
  Agent displays: "Verification code: K7x9mP2q..."

  STATE:
    Router: pending_registrations["K7x9mP2q..."] = {ws: <connection>, verified: false}
    Agent:  my_token = "K7x9mP2q...", owner = None, state = LOCKED

Step 2: Dev types the code in Slack
@assisted-bot verify K7x9mP2q...

  Slack sends event to router. Slack's signing secret guarantees
  the event came from user U12345 — this cannot be forged.

  Router looks up "K7x9mP2q..." in pending_registrations — found.
  Router checks expiry (< 5 minutes) — ok.
  Router moves to active:
    active_registrations["U12345"] = {ws: <connection>}
  Router deletes pending registration (token consumed).
  Router sends over WebSocket: {"type": "verified", "token": "K7x9mP2q...", "slack_user_id": "U12345"}

  Agent receives "verified" message.
  Agent checks: does "K7x9mP2q..." match my_token? YES.
  Agent sets: owner = "U12345", state = ACTIVE.

  STATE:
    Router: active_registrations["U12345"] → ws_connection
    Agent:  owner = "U12345", state = ACTIVE, processes events only from U12345

Step 3: Dev uses the bot
@assisted-bot help me fix this bug

  Slack event → router → lookup U12345 → forward over WebSocket → agent.
  Agent checks: event user U12345 == owner U12345? YES → process with Claude.
  Claude response → WebSocket → router → Slack API → thread reply.
```

### Attack Scenarios

**Attack: Register pointing to victim's beaker**
Attacker can't. The registration happens from the beaker agent process itself (it connects outbound). The attacker would need to run code on the victim's machine.

**Attack: Verify someone else's token**
Attacker doesn't know the token — it's displayed only on the victim's terminal. 32-char token = 256 bits of entropy. Tokens expire after 5 minutes.

**Attack: Attacker registers their own token, then router sends /verified to victim's agent**
The victim's agent checks: does the token in the /verified message match MY token? No → rejected. Each agent only accepts verification with the token it generated.

**Attack: Forge a Slack event to claim to be someone else**
Slack's signing secret prevents this. The router verifies the signature on every event. Cannot be forged without the signing secret.

**Attack: Intercept the WebSocket connection**
The WebSocket uses TLS (wss://). The OpenShift route has edge TLS termination.

**Attack: Send events to the agent before verification**
Agent is in LOCKED state until verified. All events are rejected.

### Defense in Depth

Both sides independently verify:

| Layer | What it verifies | How |
|-------|-----------------|-----|
| Slack signing secret | Event came from real Slack user | HMAC signature verification |
| One-time token | Person in Slack = person at beaker terminal | Token visible only on terminal, typed in Slack |
| Agent owner check | Incoming event is from verified owner | Agent compares event user_id to stored owner |
| Token on /verified | Verification targets the right agent | Agent compares received token to its own |
| TLS | Traffic not intercepted | wss:// + HTTPS |
| Locked state | No processing before verification | Agent rejects all events until verified |

## Message Flow (After Verification)

```
1. User @mentions bot in Slack
2. Slack POSTs event to router's /slack/events
3. Router verifies Slack signature
4. Router extracts user ID from event
5. Router looks up user in active_registrations
   - Not found → reply "Your agent isn't running"
   - Found → continue
6. Router sends event over WebSocket to beaker agent
7. Agent verifies user ID matches owner
8. Agent passes message to Claude Code SDK
9. Claude streams response chunks
10. Agent sends chunks over WebSocket to router
11. Router posts/updates Slack message via chat.write API
12. Claude finishes → agent sends "done" message
13. Router adds action buttons (Clear Session, Status)
```

## Failure Modes

| Failure | Detection | User experience |
|---------|-----------|----------------|
| Beaker agent crashes | WebSocket close event | Router replies: "Your agent disconnected" |
| Beaker machine reboots | WebSocket close event | Same — user must restart agent and re-verify |
| Router restarts | All WebSocket connections drop | All agents reconnect automatically, re-verify |
| Network interruption | WebSocket ping/pong timeout | Agent auto-reconnects, re-registers |
| Claude API error | Agent catches exception | Router posts error message in thread |

## Configuration

### Router (environment variables)

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_BOT_TOKEN` | Yes | Bot token (xoxb-...) |
| `SLACK_SIGNING_SECRET` | Yes | For verifying Slack events |
| `TOKEN_EXPIRY_SECONDS` | No | Pending token TTL (default: 300) |

### Agent (environment variables)

| Variable | Required | Description |
|----------|----------|-------------|
| `ROUTER_URL` | Yes | WebSocket URL of the router |
| `ANTHROPIC_API_KEY` | No | If not using default Claude auth |
| `CLAUDE_MODEL` | No | Model override (default: claude-sonnet-4-20250514) |
| `WORKING_DIRECTORY` | No | Working directory for Claude (default: .) |
| `PERMISSION_MODE` | No | default/bypass/allowEdits/plan |
