"""Slack Block Kit UI components."""

from __future__ import annotations

import json
from typing import Any


def thinking_indicator() -> list[dict[str, Any]]:
    """Create a thinking/processing indicator."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":hourglass_flowing_sand: *Claude is thinking...*",
            },
        }
    ]


def processing_with_status(status: str) -> list[dict[str, Any]]:
    """Create a processing indicator with status text."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":hourglass_flowing_sand: *Processing...*\n{status}",
            },
        }
    ]


def tool_approval_request(
    tool_name: str,
    tool_input: dict[str, Any],
    pending_id: str,
    session_id: str,
) -> list[dict[str, Any]]:
    """Create a tool approval request with approve/reject buttons."""
    # Format tool details based on type
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        description = tool_input.get("description", "Execute command")
        detail_text = f"*Description:* {description}\n```\n{command[:1000]}\n```"
    elif tool_name == "Write":
        file_path = tool_input.get("file_path", "unknown")
        content = tool_input.get("content", "")
        preview = content[:500] + "..." if len(content) > 500 else content
        detail_text = f"*File:* `{file_path}`\n*Content preview:*\n```\n{preview}\n```"
    elif tool_name == "Edit":
        file_path = tool_input.get("file_path", "unknown")
        old_str = tool_input.get("old_string", "")[:200]
        new_str = tool_input.get("new_string", "")[:200]
        detail_text = (
            f"*File:* `{file_path}`\n"
            f"*Replace:*\n```\n{old_str}\n```\n"
            f"*With:*\n```\n{new_str}\n```"
        )
    else:
        # Generic tool display
        input_str = json.dumps(tool_input, indent=2)[:500]
        detail_text = f"*Input:*\n```\n{input_str}\n```"

    approval_value = json.dumps({
        "pending_id": pending_id,
        "session_id": session_id,
        "tool_name": tool_name,
    })

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":warning: *Claude wants to use `{tool_name}`*",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": detail_text[:3000],  # Slack limit
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve", "emoji": True},
                    "style": "primary",
                    "action_id": "approve_tool",
                    "value": approval_value,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reject", "emoji": True},
                    "style": "danger",
                    "action_id": "reject_tool",
                    "value": approval_value,
                },
            ],
        },
    ]


def tool_approved(tool_name: str, pending_id: str) -> list[dict[str, Any]]:
    """Show that a tool was approved."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":white_check_mark: *`{tool_name}` approved*",
            },
        },
    ]


def tool_rejected(tool_name: str, pending_id: str, reason: str = "") -> list[dict[str, Any]]:
    """Show that a tool was rejected."""
    text = f":x: *`{tool_name}` rejected*"
    if reason:
        text += f"\n_{reason}_"
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text,
            },
        },
    ]


def response_message(text: str, session_id: str) -> list[dict[str, Any]]:
    """Format Claude's response with action buttons."""
    # Truncate text to Slack's limit
    display_text = text[:3000] if text else "_No response_"

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": display_text,
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Clear Session", "emoji": True},
                    "action_id": "clear_session",
                    "value": json.dumps({"session_id": session_id}),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Status", "emoji": True},
                    "action_id": "show_status",
                    "value": json.dumps({"session_id": session_id}),
                },
            ],
        },
    ]


def response_with_cancel(text: str, session_id: str) -> list[dict[str, Any]]:
    """Format in-progress response with cancel button."""
    display_text = text[:3000] if text else ":hourglass_flowing_sand: _Processing..._"

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": display_text,
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel", "emoji": True},
                    "style": "danger",
                    "action_id": "cancel_operation",
                    "value": json.dumps({"session_id": session_id}),
                },
            ],
        },
    ]


def session_status(
    session_id: str,
    created_at: str,
    message_count: int | None = None,
    is_processing: bool = False,
    cwd: str = "",
    claude_session_id: str | None = None,
    total_cost_usd: float = 0.0,
    num_turns: int = 0,
    permission_mode: str = "",
) -> list[dict[str, Any]]:
    """Show session status information."""
    status_emoji = ":gear:" if is_processing else ":white_check_mark:"
    status_text = "Processing" if is_processing else "Ready"

    fields = [
        f"*Status:* {status_emoji} {status_text}",
        f"*Session ID:* `{session_id[:8]}...`",
        f"*Created:* {created_at}",
    ]
    if claude_session_id:
        fields.append(f"*Claude Session:* `{claude_session_id[:12]}...`")
    if cwd:
        fields.append(f"*Working Directory:* `{cwd}`")
    if num_turns > 0:
        fields.append(f"*Turns:* {num_turns}")
    if total_cost_usd > 0:
        fields.append(f"*Total Cost:* ${total_cost_usd:.4f}")
    if permission_mode:
        fields.append(f"*Permission Mode:* `{permission_mode}`")
    if message_count is not None:
        fields.append(f"*Messages:* {message_count}")

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Session Status*\n" + "\n".join(fields),
            },
        },
    ]


def error_message(error: str) -> list[dict[str, Any]]:
    """Format an error message."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":x: *Error*\n{error[:2000]}",
            },
        },
    ]


def session_cleared(
    total_cost_usd: float = 0.0,
    num_turns: int = 0,
    total_duration_ms: int = 0,
) -> list[dict[str, Any]]:
    """Show session cleared message with usage summary."""
    text = ":broom: *Session cleared.* Starting fresh!"

    if num_turns > 0 or total_cost_usd > 0:
        stats = []
        if num_turns > 0:
            stats.append(f"*Turns:* {num_turns}")
        if total_cost_usd > 0:
            stats.append(f"*Total Cost:* ${total_cost_usd:.4f}")
        if total_duration_ms > 0:
            duration_s = total_duration_ms / 1000
            if duration_s >= 60:
                mins = int(duration_s // 60)
                secs = int(duration_s % 60)
                stats.append(f"*Duration:* {mins}m {secs}s")
            else:
                stats.append(f"*Duration:* {duration_s:.1f}s")
        text += "\n\n_Session summary:_\n" + "\n".join(stats)

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": text,
            },
        },
    ]


def operation_cancelled() -> list[dict[str, Any]]:
    """Show operation cancelled message."""
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":stop_sign: *Operation cancelled.*",
            },
        },
    ]
