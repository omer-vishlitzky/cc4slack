# Message Handling Behavior

## When does the bot respond?

| Context | @mention required? | Responds to threads? |
|---------|-------------------|---------------------|
| 1:1 DM | No — every message is for the bot | Yes |
| Group DM | Yes — only @mentions | Yes (if @mentioned in the thread) |
| Channel | Yes — only @mentions | Yes (if @mentioned in the thread) |

## Slack event mapping

| Slack event | channel_type | Our action |
|-------------|-------------|------------|
| `app_mention` | any | Process — user explicitly invoked the bot |
| `message` | `im` | Process — 1:1 DM, every message is for the bot |
| `message` | `mpim` | **Ignore** — `app_mention` already covers @mentions |
| `message` | `channel` | Never received — not subscribed |

## Why ignore `message.mpim`?

When someone @mentions the bot in a group DM, Slack sends TWO events:
1. `app_mention` — we handle this
2. `message` with `channel_type: "mpim"` — if we also handle this, the message is processed twice

By ignoring `message.mpim`, we get exactly one processing per @mention.

## Thread behavior

- In 1:1 DMs: every thread reply is processed (no @mention needed)
- In group DMs/channels: only thread replies that @mention the bot are processed
- Each thread maintains its own Claude session (session ID tracked per thread_key)

## Thread context (incremental)

The bot fetches Slack thread history so Claude understands the full conversation, not just @mentioned messages.

```
First @mention in thread:
  → Fetch all messages from thread start to this message
  → Send to Claude as "[Thread context]\n...\n[Your message]\n..."
  → New Claude session created

Second @mention in same thread:
  → Fetch only messages SINCE the last @mention (the delta)
  → Send to Claude as "[New messages]\n...\n[Your message]\n..."
  → Resume existing Claude session (has history from first turn)
```

This way Claude sees everything — messages from other people between @mentions, links shared, decisions made — without re-sending context it already has.
