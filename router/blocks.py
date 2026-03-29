import json
from typing import Any

SLACK_TEXT_LIMIT = 3000


def thinking_indicator() -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":hourglass_flowing_sand: *Claude is thinking...*"},
        }
    ]


def response_message(*, text: str, session_id: str) -> list[dict[str, Any]]:
    display_text = text[:SLACK_TEXT_LIMIT] if text else "_No response_"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": display_text}},
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


def response_with_cancel(*, text: str, session_id: str) -> list[dict[str, Any]]:
    display_text = text[:SLACK_TEXT_LIMIT] if text else ":hourglass_flowing_sand: _Processing..._"
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": display_text}},
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
    *,
    session_id: str,
    created_at: str,
    is_processing: bool,
    cwd: str,
    total_cost_usd: float,
    num_turns: int,
    permission_mode: str,
    agent_connected: bool,
) -> list[dict[str, Any]]:
    status_emoji = ":gear:" if is_processing else ":white_check_mark:"
    status_text = "Processing" if is_processing else "Ready"

    fields = [
        f"*Status:* {status_emoji} {status_text}",
        f"*Agent:* {'Connected' if agent_connected else 'Disconnected'}",
        f"*Working Directory:* `{cwd}`",
        f"*Permission Mode:* `{permission_mode}`",
    ]
    if num_turns > 0:
        fields.append(f"*Turns:* {num_turns}")
    if total_cost_usd > 0:
        fields.append(f"*Total Cost:* ${total_cost_usd:.4f}")

    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Session Status*\n" + "\n".join(fields)},
        },
    ]


def session_cleared(
    *,
    total_cost_usd: float,
    num_turns: int,
    total_duration_ms: int,
) -> list[dict[str, Any]]:
    text = ":broom: *Session cleared.* Starting fresh!"

    if num_turns > 0 or total_cost_usd > 0:
        stats: list[str] = []
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

    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def operation_cancelled() -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":stop_sign: *Operation cancelled.*"},
        }
    ]


def error_message(*, error: str) -> list[dict[str, Any]]:
    return [{"type": "section", "text": {"type": "mrkdwn", "text": f":x: *Error*\n{error[:2000]}"}}]


def agent_connected(*, slack_user_id: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":white_check_mark: *Agent connected for <@{slack_user_id}>.*\n"
                    "You can now mention me to start working."
                ),
            },
        }
    ]


def agent_disconnected() -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":warning: *Your agent disconnected.*"
                    " Start it again on your beaker machine and re-verify."
                ),
            },
        }
    ]


def agent_not_connected() -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    ":x: *No agent connected.*\n\n"
                    "Start your agent on your beaker machine:\n"
                    "```./scripts/start-agent.sh```\n"
                    "Then verify with the code shown in your terminal:\n"
                    "```@assisted-bot verify <code>```"
                ),
            },
        }
    ]
