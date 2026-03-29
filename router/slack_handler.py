import asyncio
import json
import logging
import re
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from slack_sdk.signature import SignatureVerifier

from shared.protocol import EventMessage

from . import blocks
from .commands import (
    handle_cwd,
    handle_help,
    handle_mode,
    handle_model,
    handle_status,
    handle_unregister,
    handle_verify,
    try_parse_command,
)
from .message_updater import SlackMessageUpdater
from .thread_store import ThreadState

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from .ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

MENTION_PATTERN = re.compile(r"<@[A-Z0-9]+>\s*")


def clean_mention(*, text: str) -> str:
    return MENTION_PATTERN.sub("", text).strip()


def extract_full_text(*, event: dict[str, Any]) -> str:
    text = event.get("text", "").strip()
    attachments = event.get("attachments", [])
    if not attachments:
        return text

    attachment_parts: list[str] = []
    for att in attachments:
        parts: list[str] = []
        if att.get("pretext"):
            parts.append(att["pretext"])
        if att.get("title"):
            parts.append(f"*{att['title']}*")
        if att.get("text"):
            parts.append(att["text"])
        if att.get("fallback") and not att.get("text"):
            parts.append(att["fallback"])
        if parts:
            attachment_parts.append("\n".join(parts))

    if not attachment_parts:
        return text

    attachments_block = "\n---\n".join(attachment_parts)
    if text:
        return f"{text}\n\n[Forwarded message]\n{attachments_block}"
    return attachments_block


async def handle_slack_event(
    *,
    request: Request,
    signing_secret: str,
    ws_manager: "WebSocketManager",
    slack_client: "AsyncWebClient",
    updaters: dict[str, SlackMessageUpdater],
) -> Response:
    body = await request.body()
    headers = request.headers

    if headers.get("X-Slack-Retry-Num"):
        return Response(status_code=200)

    verifier = SignatureVerifier(signing_secret)
    if not verifier.is_valid_request(body, headers):
        return Response(status_code=400, content="Invalid signature")

    data = json.loads(body)

    if data["type"] == "url_verification":
        return JSONResponse({"challenge": data["challenge"]})

    if data["type"] != "event_callback":
        return Response(status_code=200)

    event = data["event"]
    event_type = event["type"]
    channel_type = event.get("channel_type", "")
    logger.info(
        f"Slack event: type={event_type} channel_type={channel_type} "
        f"user={event.get('user', '?')} channel={event.get('channel', '?')} "
        f"text={event.get('text', '')!r} "
        f"attachments={'attachments' in event} files={'files' in event}"
    )
    if "attachments" in event:
        for att in event["attachments"]:
            fallback = att.get("fallback", "")
            att_text = att.get("text", "")
            logger.info(f"  attachment: fallback={fallback!r} text={att_text!r}")

    if event_type == "app_mention":
        asyncio.create_task(
            _handle_mention(
                event=event,
                ws_manager=ws_manager,
                slack_client=slack_client,
                updaters=updaters,
            )
        )
    elif event_type == "message" and channel_type == "im":
        if not event.get("bot_id") and not event.get("subtype"):
            asyncio.create_task(
                _handle_dm(
                    event=event,
                    ws_manager=ws_manager,
                    slack_client=slack_client,
                    updaters=updaters,
                )
            )
        else:
            logger.info(f"Ignored DM: bot_id={event.get('bot_id')} subtype={event.get('subtype')}")
    else:
        logger.info(f"Unhandled event type: {event_type} channel_type={channel_type}")

    return Response(status_code=200)


async def handle_slack_action(
    *,
    request: Request,
    signing_secret: str,
    ws_manager: "WebSocketManager",
    slack_client: "AsyncWebClient",
    updaters: dict[str, SlackMessageUpdater],
) -> Response:
    body = await request.body()
    headers = request.headers

    verifier = SignatureVerifier(signing_secret)
    if not verifier.is_valid_request(body, headers):
        return Response(status_code=400, content="Invalid signature")

    form = await request.form()
    payload = json.loads(form["payload"])
    action_id = payload["actions"][0]["action_id"]
    channel = payload["channel"]["id"]
    thread_ts = payload["message"].get("thread_ts", payload["message"]["ts"])
    user_id = payload["user"]["id"]

    if action_id == "cancel_operation":
        thread_key = f"{channel}:{thread_ts}"
        await ws_manager.send_to_agent(
            slack_user_id=user_id,
            message={"type": "cancel", "thread_key": thread_key},
        )
        await slack_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Operation cancelled",
            blocks=blocks.operation_cancelled(),
        )

    elif action_id == "clear_session":
        thread_key = f"{channel}:{thread_ts}"
        state = ws_manager.get_thread_state(slack_user_id=user_id, thread_key=thread_key)
        cost = state.total_cost_usd if state else 0.0
        turns = state.num_turns if state else 0
        duration = state.total_duration_ms if state else 0
        ws_manager.clear_thread_state(slack_user_id=user_id, thread_key=thread_key)
        updaters.pop(thread_key, None)
        await slack_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Session cleared",
            blocks=blocks.session_cleared(
                total_cost_usd=cost, num_turns=turns, total_duration_ms=duration
            ),
        )

    elif action_id == "show_status":
        await handle_status(
            slack_user_id=user_id,
            channel=channel,
            thread_ts=thread_ts,
            client=slack_client,
            ws_manager=ws_manager,
        )

    return Response(status_code=200)


async def _handle_mention(
    *,
    event: dict[str, Any],
    ws_manager: "WebSocketManager",
    slack_client: "AsyncWebClient",
    updaters: dict[str, SlackMessageUpdater],
) -> None:
    user_id = event["user"]
    channel = event["channel"]
    full_text = extract_full_text(event=event)
    text = clean_mention(text=full_text)
    thread_ts = event.get("thread_ts", event["ts"])

    if not text:
        await slack_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="How can I help? Mention me with your question.",
        )
        return

    await _dispatch(
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
        text=text,
        user_message_ts=event["ts"],
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )


async def _handle_dm(
    *,
    event: dict[str, Any],
    ws_manager: "WebSocketManager",
    slack_client: "AsyncWebClient",
    updaters: dict[str, SlackMessageUpdater],
) -> None:
    user_id = event["user"]
    channel = event["channel"]
    text = extract_full_text(event=event)
    thread_ts = event.get("thread_ts", event["ts"])

    if not text:
        return

    await _dispatch(
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
        text=text,
        user_message_ts=event["ts"],
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )


async def _dispatch(
    *,
    user_id: str,
    channel: str,
    thread_ts: str,
    text: str,
    user_message_ts: str,
    ws_manager: "WebSocketManager",
    slack_client: "AsyncWebClient",
    updaters: dict[str, SlackMessageUpdater],
) -> None:
    text = clean_mention(text=text)
    command = try_parse_command(text=text)
    logger.info(f"Dispatch: user={user_id} text={text!r} command={command[0] if command else None}")
    if command and command[0] == "verify":
        _, match = command
        await handle_verify(
            token=match.group(1),
            slack_user_id=user_id,
            channel=channel,
            thread_ts=thread_ts,
            client=slack_client,
            ws_manager=ws_manager,
        )
        return

    conn = ws_manager.get_connection(slack_user_id=user_id)
    if not conn:
        await slack_client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="No agent connected",
            blocks=blocks.agent_not_connected(),
        )
        return

    if command:
        cmd_name, match = command
        if cmd_name == "help":
            await handle_help(channel=channel, thread_ts=thread_ts, client=slack_client)
        elif cmd_name == "unregister":
            await handle_unregister(
                slack_user_id=user_id,
                channel=channel,
                thread_ts=thread_ts,
                client=slack_client,
                ws_manager=ws_manager,
            )
        elif cmd_name == "mode":
            await handle_mode(
                mode_arg=match.group(1),
                channel=channel,
                thread_ts=thread_ts,
                slack_user_id=user_id,
                client=slack_client,
                ws_manager=ws_manager,
            )
        elif cmd_name == "model":
            await handle_model(
                model_arg=match.group(1) or "",
                channel=channel,
                thread_ts=thread_ts,
                slack_user_id=user_id,
                client=slack_client,
                ws_manager=ws_manager,
            )
        elif cmd_name == "cwd":
            await handle_cwd(
                path_arg=match.group(1).strip(),
                channel=channel,
                thread_ts=thread_ts,
                slack_user_id=user_id,
                client=slack_client,
                ws_manager=ws_manager,
            )
        elif cmd_name == "status":
            await handle_status(
                slack_user_id=user_id,
                channel=channel,
                thread_ts=thread_ts,
                client=slack_client,
                ws_manager=ws_manager,
            )
        return

    await _forward_to_agent(
        user_id=user_id,
        channel=channel,
        thread_ts=thread_ts,
        text=text,
        user_message_ts=user_message_ts,
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )


async def _forward_to_agent(
    *,
    user_id: str,
    channel: str,
    thread_ts: str,
    text: str,
    user_message_ts: str,
    ws_manager: "WebSocketManager",
    slack_client: "AsyncWebClient",
    updaters: dict[str, SlackMessageUpdater],
) -> None:
    thread_key = f"{channel}:{thread_ts}"

    try:
        await slack_client.reactions_add(channel=channel, name="eyes", timestamp=user_message_ts)
    except Exception:
        pass

    result = await slack_client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Claude is thinking...",
        blocks=blocks.thinking_indicator(),
    )
    message_ts = result["ts"]

    state = ws_manager.get_thread_state(slack_user_id=user_id, thread_key=thread_key)
    if not state:
        state = ThreadState(channel=channel, thread_ts=thread_ts, message_ts=message_ts)
        ws_manager.set_thread_state(slack_user_id=user_id, thread_key=thread_key, state=state)
    else:
        state.message_ts = message_ts

    prompt = await _build_prompt_with_thread_context(
        text=text,
        channel=channel,
        thread_ts=thread_ts,
        current_ts=user_message_ts,
        last_processed_ts=state.last_processed_ts,
        slack_client=slack_client,
    )

    state.last_processed_ts = user_message_ts
    ws_manager.set_thread_state(slack_user_id=user_id, thread_key=thread_key, state=state)

    updater = SlackMessageUpdater(
        client=slack_client,
        channel=channel,
        message_ts=message_ts,
        thread_ts=thread_ts,
    )
    updaters[thread_key] = updater

    event_msg: EventMessage = {
        "type": "event",
        "thread_key": thread_key,
        "user_id": user_id,
        "text": prompt,
        "channel": channel,
        "thread_ts": thread_ts,
    }
    await ws_manager.send_to_agent(slack_user_id=user_id, message=event_msg)


async def _build_prompt_with_thread_context(
    *,
    text: str,
    channel: str,
    thread_ts: str,
    current_ts: str,
    last_processed_ts: str,
    slack_client: "AsyncWebClient",
) -> str:
    is_thread_reply = thread_ts != current_ts
    if not is_thread_reply:
        return text

    is_first_fetch = not last_processed_ts
    oldest = thread_ts if is_first_fetch else last_processed_ts
    result = await slack_client.conversations_replies(
        channel=channel,
        ts=thread_ts,
        oldest=oldest,
        latest=current_ts,
        inclusive=is_first_fetch,
    )
    messages = result["messages"]

    context_messages = [
        msg for msg in messages
        if msg["ts"] != current_ts and not msg.get("bot_id")
    ]

    if not context_messages:
        return text

    context_lines = []
    for msg in context_messages:
        context_lines.append(f"<@{msg['user']}>: {msg['text']}")

    context_block = "\n".join(context_lines)
    prefix = "New messages" if last_processed_ts else "Thread context"
    return f"[{prefix} from Slack thread]\n{context_block}\n\n[Your message]\n{text}"
