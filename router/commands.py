import re
from typing import TYPE_CHECKING

from . import blocks

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from .ws_manager import WebSocketManager

COMMAND_PATTERNS: dict[str, re.Pattern[str]] = {
    "help": re.compile(r"^help\s*$", re.IGNORECASE),
    "verify": re.compile(r"^verify\s+(\S+)\s*$", re.IGNORECASE),
    "unregister": re.compile(r"^unregister\s*$", re.IGNORECASE),
    "mode": re.compile(r"^mode\s*(default|bypass|allowEdits|plan)?\s*$", re.IGNORECASE),
    "model": re.compile(r"^model\s*(.*)?$", re.IGNORECASE),
    "cwd": re.compile(r"^cwd\s*(.*)$", re.IGNORECASE),
    "status": re.compile(r"^status\s*$", re.IGNORECASE),
}

HELP_TEXT = """:robot_face: *cc4slack — Claude Code for Slack*

*Setup:*
1. Start your agent on your beaker machine
2. Type `@assisted-bot verify <code>` with the code shown in your terminal

*Commands:*
- `verify <code>` — Connect your beaker agent
- `unregister` — Disconnect your agent
- `status` — Show connection and session info
- `mode` — Show current permission mode
- `mode <default|bypass|allowEdits|plan>` — Change permission mode
- `model` — Show current model
- `model <model-id>` — Change model (e.g. claude-opus-4-6)
- `cwd` — Show working directory
- `cwd <path>` — Change working directory
- `help` — Show this message

*Permission Modes:*
- `default` — Use Claude's settings from .claude/settings.json
- `bypass` — All tools run without checks (sandbox only)
- `allowEdits` — File edits auto-approved, bash blocked
- `plan` — Read-only, no writes or bash"""

MODE_DESCRIPTIONS: dict[str, str] = {
    "default": "Using Claude's default permissions from settings files",
    "bypass": "All tools run without permission checks",
    "allowEdits": "File edits auto-approved, bash commands blocked",
    "plan": "Read-only mode, no writes or bash",
}


def try_parse_command(*, text: str) -> tuple[str, re.Match[str]] | None:
    for name, pattern in COMMAND_PATTERNS.items():
        match = pattern.match(text)
        if match:
            return name, match
    return None


async def handle_help(
    *,
    channel: str,
    thread_ts: str,
    client: "AsyncWebClient",
) -> None:
    await client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=HELP_TEXT)


async def handle_verify(
    *,
    token: str,
    slack_user_id: str,
    channel: str,
    thread_ts: str,
    client: "AsyncWebClient",
    ws_manager: "WebSocketManager",
) -> None:
    verified = await ws_manager.verify_token(token=token, slack_user_id=slack_user_id)
    if verified:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Agent connected",
            blocks=blocks.agent_connected(slack_user_id=slack_user_id),
        )
    else:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                ":x: *Verification failed.* Token is invalid or expired."
                " Start your agent again to get a new code."
            ),
        )


async def handle_unregister(
    *,
    slack_user_id: str,
    channel: str,
    thread_ts: str,
    client: "AsyncWebClient",
    ws_manager: "WebSocketManager",
) -> None:
    conn = ws_manager.get_connection(slack_user_id=slack_user_id)
    if conn:
        await ws_manager.remove_connection(slack_user_id=slack_user_id)
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                ":white_check_mark: *Agent disconnected.*"
                " You can reconnect by starting your agent and verifying again."
            ),
        )
    else:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=":information_source: No agent is currently connected.",
        )


async def handle_mode(
    *,
    mode_arg: str | None,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    client: "AsyncWebClient",
    ws_manager: "WebSocketManager",
) -> None:
    if not mode_arg:
        thread_key = f"{channel}:{thread_ts}"
        state = ws_manager.get_thread_state(slack_user_id=slack_user_id, thread_key=thread_key)
        current_mode = state.permission_mode if state else "default"
        desc = MODE_DESCRIPTIONS[current_mode]
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f":shield: *Permission mode:* `{current_mode}`\n{desc}",
        )
        return

    thread_key = f"{channel}:{thread_ts}"
    state = ws_manager.get_thread_state(slack_user_id=slack_user_id, thread_key=thread_key)
    if state:
        state.permission_mode = mode_arg

    await ws_manager.send_to_agent(
        slack_user_id=slack_user_id,
        message={
            "type": "config_update",
            "thread_key": thread_key,
            "cwd": state.cwd if state else ".",
            "permission_mode": mode_arg,
            "model": state.model if state else "",
        },
    )

    mode_emoji = {
        "default": ":shield:",
        "bypass": ":warning:",
        "allowEdits": ":pencil:",
        "plan": ":book:",
    }
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            f"{mode_emoji[mode_arg]} *Permission mode set to `{mode_arg}`*\n"
            f"{MODE_DESCRIPTIONS[mode_arg]}"
        ),
    )


async def handle_cwd(
    *,
    path_arg: str,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    client: "AsyncWebClient",
    ws_manager: "WebSocketManager",
) -> None:
    thread_key = f"{channel}:{thread_ts}"

    if not path_arg:
        state = ws_manager.get_thread_state(slack_user_id=slack_user_id, thread_key=thread_key)
        current_cwd = state.cwd if state else "."
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f":file_folder: *Working directory:* `{current_cwd}`",
        )
        return

    state = ws_manager.get_thread_state(slack_user_id=slack_user_id, thread_key=thread_key)
    if state:
        state.cwd = path_arg

    await ws_manager.send_to_agent(
        slack_user_id=slack_user_id,
        message={
            "type": "config_update",
            "thread_key": thread_key,
            "cwd": path_arg,
            "permission_mode": state.permission_mode if state else "default",
            "model": state.model if state else "",
        },
    )

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f":file_folder: *Working directory set to* `{path_arg}`",
    )


async def handle_model(
    *,
    model_arg: str,
    channel: str,
    thread_ts: str,
    slack_user_id: str,
    client: "AsyncWebClient",
    ws_manager: "WebSocketManager",
) -> None:
    thread_key = f"{channel}:{thread_ts}"

    if not model_arg.strip():
        state = ws_manager.get_thread_state(slack_user_id=slack_user_id, thread_key=thread_key)
        current_model = state.model if state and state.model else "default (CLI)"
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f":brain: *Model:* `{current_model}`",
        )
        return

    model = model_arg.strip()
    state = ws_manager.get_thread_state(slack_user_id=slack_user_id, thread_key=thread_key)
    if state:
        state.model = model

    await ws_manager.send_to_agent(
        slack_user_id=slack_user_id,
        message={
            "type": "config_update",
            "thread_key": thread_key,
            "cwd": state.cwd if state else ".",
            "permission_mode": state.permission_mode if state else "default",
            "model": model,
        },
    )

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f":brain: *Model set to* `{model}`",
    )


async def handle_status(
    *,
    slack_user_id: str,
    channel: str,
    thread_ts: str,
    client: "AsyncWebClient",
    ws_manager: "WebSocketManager",
) -> None:
    conn = ws_manager.get_connection(slack_user_id=slack_user_id)
    agent_connected = conn is not None

    thread_key = f"{channel}:{thread_ts}"
    state = ws_manager.get_thread_state(slack_user_id=slack_user_id, thread_key=thread_key)

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Session status",
        blocks=blocks.session_status(
            session_id=thread_key,
            created_at="N/A",
            is_processing=False,
            cwd=state.cwd if state else ".",
            total_cost_usd=state.total_cost_usd if state else 0.0,
            num_turns=state.num_turns if state else 0,
            permission_mode=state.permission_mode if state else "default",
            agent_connected=agent_connected,
        ),
    )
