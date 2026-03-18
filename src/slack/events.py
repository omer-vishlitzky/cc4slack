"""Slack event handlers for mentions and direct messages."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import TYPE_CHECKING, Any


from . import blocks
from .message_updater import SlackMessageUpdater

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp
    from slack_sdk.web.async_client import AsyncWebClient

    from ..claude.agent import ClaudeSlackAgent
    from ..config import Settings
    from ..sessions.manager import SessionManager

logger = logging.getLogger(__name__)

# Regex to clean bot mention from message text
MENTION_PATTERN = re.compile(r"<@[A-Z0-9]+>\s*")

# Regex to match connect command with optional session ID
CONNECT_PATTERN = re.compile(r"^connect\s*(.*)$", re.IGNORECASE)

# Regex to match sessions command
SESSIONS_PATTERN = re.compile(r"^sessions?\s*$", re.IGNORECASE)

# Regex to match cwd command with optional path
CWD_PATTERN = re.compile(r"^cwd\s*(.*)$", re.IGNORECASE)

# Regex to match mode command
MODE_PATTERN = re.compile(r"^mode\s*(default|bypass|allowEdits|plan)?\s*$", re.IGNORECASE)

# Regex to match help command
HELP_PATTERN = re.compile(r"^help\s*$", re.IGNORECASE)

HELP_TEXT = """:robot_face: *Available commands:*

• *`connect`* — Connect to the most recent Claude session
• *`connect <number>`* — Connect by index from the sessions list
• *`connect <session-id>`* — Connect by full session ID
• *`sessions`* — List available Claude sessions
• *`cwd`* — Show current working directory
• *`cwd <path>`* — Change working directory for this thread
• *`mode`* — Show current permission mode
• *`mode default`* — Use Claude's settings (.claude/settings.json)
• *`mode bypass`* — All tools run without checks (use in sandbox)
• *`mode allowEdits`* — Auto-approve edits, block bash
• *`mode plan`* — Read-only, no writes or bash
• *`help`* — Show this help message

_You can also upload files — they'll be saved to the working directory and passed to Claude._
_Use the *Clear Session* button to end a session (shows cost summary)._
_Use the *Status* button to see session details._"""


def clean_mention(text: str) -> str:
    """Remove bot mention from message text."""
    return MENTION_PATTERN.sub("", text).strip()


def register_event_handlers(
    app: AsyncApp,
    session_manager: SessionManager,
    claude_agent: ClaudeSlackAgent,
    config: Settings | None = None,
) -> None:
    """Register Slack event handlers on the app."""

    @app.event("app_mention")
    async def handle_mention(
        event: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle when the bot is mentioned in a channel."""
        user = event.get("user", "unknown")
        channel = event["channel"]
        text = event.get("text", "")
        # Use thread_ts if in a thread, otherwise start new thread with this message
        thread_ts = event.get("thread_ts") or event["ts"]

        logger.info(f"Mention from {user} in {channel}: {text[:50]}...")

        # Clean the mention from the text
        user_message = clean_mention(text)
        if not user_message:
            await client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="Hi! How can I help you? Just mention me with your question.",
            )
            return

        # Check for connect command
        connect_match = CONNECT_PATTERN.match(user_message)
        if connect_match:
            await handle_connect(
                channel=channel,
                thread_ts=thread_ts,
                session_id_arg=connect_match.group(1).strip(),
                client=client,
                session_manager=session_manager,
                config=config,
            )
            return

        # Check for sessions command
        if SESSIONS_PATTERN.match(user_message):
            await handle_list_sessions(
                channel=channel,
                thread_ts=thread_ts,
                client=client,
                config=config,
            )
            return

        # Check for cwd command
        cwd_match = CWD_PATTERN.match(user_message)
        if cwd_match:
            await handle_cwd(
                channel=channel,
                thread_ts=thread_ts,
                path_arg=cwd_match.group(1).strip(),
                client=client,
                session_manager=session_manager,
                config=config,
            )
            return

        # Check for mode command
        mode_match = MODE_PATTERN.match(user_message)
        if mode_match:
            await handle_mode_command(
                channel=channel,
                thread_ts=thread_ts,
                mode_arg=mode_match.group(1),
                client=client,
                session_manager=session_manager,
                config=config,
            )
            return

        # Check for help command
        if HELP_PATTERN.match(user_message):
            await client.chat_postMessage(
                channel=channel, thread_ts=thread_ts, text=HELP_TEXT,
            )
            return

        # Handle file uploads — download and mention in the prompt
        files = event.get("files", [])
        if files:
            session = await session_manager.get_or_create(
                channel_id=channel, thread_ts=thread_ts,
            )
            effective_cwd = session.cwd or config.working_directory if config else "."
            saved = await download_slack_files(files, effective_cwd, config.slack_bot_token if config else "")
            if saved:
                file_list = ", ".join(f"`{f}`" for f in saved)
                user_message = (
                    f"{user_message}\n\n"
                    f"[The user uploaded the following files to the working directory: {file_list}]"
                ) if user_message else f"The user uploaded files: {file_list}. Please review them."

        await process_request(
            channel=channel,
            thread_ts=thread_ts,
            user_message=user_message,
            client=client,
            session_manager=session_manager,
            claude_agent=claude_agent,
            user_message_ts=event["ts"],
        )

    @app.event("message")
    async def handle_message(
        event: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle direct messages to the bot."""
        # Only handle direct messages
        if event.get("channel_type") != "im":
            return

        # Ignore bot messages and message edits
        if event.get("bot_id") or event.get("subtype"):
            return

        user = event.get("user", "unknown")
        channel = event["channel"]
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event["ts"]

        logger.info(f"DM from {user}: {text[:50]}...")

        files = event.get("files", [])
        stripped = text.strip()

        if not stripped and not files:
            return

        # Check for commands (only when there are no files)
        if stripped and not files:
            # Check for connect command
            connect_match = CONNECT_PATTERN.match(stripped)
            if connect_match:
                await handle_connect(
                    channel=channel,
                    thread_ts=thread_ts,
                    session_id_arg=connect_match.group(1).strip(),
                    client=client,
                    session_manager=session_manager,
                    config=config,
                )
                return

            # Check for sessions command
            if SESSIONS_PATTERN.match(stripped):
                await handle_list_sessions(
                    channel=channel,
                    thread_ts=thread_ts,
                    client=client,
                    config=config,
                )
                return

            # Check for cwd command
            cwd_match = CWD_PATTERN.match(stripped)
            if cwd_match:
                await handle_cwd(
                    channel=channel,
                    thread_ts=thread_ts,
                    path_arg=cwd_match.group(1).strip(),
                    client=client,
                    session_manager=session_manager,
                    config=config,
                )
                return

            # Check for mode command
            mode_match = MODE_PATTERN.match(stripped)
            if mode_match:
                await handle_mode_command(
                    channel=channel,
                    thread_ts=thread_ts,
                    mode_arg=mode_match.group(1),
                    client=client,
                    session_manager=session_manager,
                    config=config,
                )
                return

            # Check for help command
            if HELP_PATTERN.match(stripped):
                await client.chat_postMessage(
                    channel=channel, thread_ts=thread_ts, text=HELP_TEXT,
                )
                return

        # Handle file uploads
        user_message = stripped
        if files:
            session = await session_manager.get_or_create(
                channel_id=channel, thread_ts=thread_ts,
            )
            effective_cwd = session.cwd or (config.working_directory if config else ".")
            saved = await download_slack_files(files, effective_cwd, config.slack_bot_token if config else "")
            if saved:
                file_list = ", ".join(f"`{f}`" for f in saved)
                user_message = (
                    f"{user_message}\n\n"
                    f"[The user uploaded the following files to the working directory: {file_list}]"
                ) if user_message else f"The user uploaded files: {file_list}. Please review them."

        await process_request(
            channel=channel,
            thread_ts=thread_ts,
            user_message=user_message or "Please review the uploaded files.",
            client=client,
            session_manager=session_manager,
            claude_agent=claude_agent,
            user_message_ts=event["ts"],
        )


def read_session_id_from_file(file_path: str) -> str | None:
    """Read a Claude session ID from a file on disk."""
    try:
        if os.path.exists(file_path):
            content = open(file_path).read().strip()
            if content:
                return content
    except Exception as e:
        logger.warning(f"Failed to read session file {file_path}: {e}")
    return None


def _clean_title(raw: str) -> str:
    """Clean raw message content into a short readable title."""
    # Strip XML/HTML-like tags
    text = re.sub(r"<[^>]+>", "", raw)
    # Strip URLs
    text = re.sub(r"https?://\S+", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Take the first meaningful line
    for line in text.split("\n"):
        line = line.strip()
        if line and len(line) > 5:
            text = line
            break
    # Strip trailing punctuation/whitespace left after URL removal
    text = text.strip(": \t\n")
    # Truncate
    if len(text) > 100:
        text = text[:97] + "..."
    return text if len(text) > 3 else "(no title)"


def get_session_title(file_path: str) -> str:
    """Extract the first user message from a session transcript as a title."""
    import json

    try:
        with open(file_path) as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    data.get("type") == "user"
                    and data.get("message", {}).get("role") == "user"
                    and not data.get("isMeta")
                ):
                    content = data["message"].get("content", "")
                    if isinstance(content, str) and content.strip():
                        return _clean_title(content)
    except Exception as e:
        logger.debug(f"Failed to read session title from {file_path}: {e}")
    return "(no title)"


def list_available_sessions(
    claude_dir: str = os.path.expanduser("~/.claude/projects"),
    project_dir: str | None = None,
) -> list[tuple[str, str, str, float]]:
    """List available session IDs from Claude's project directories.

    Args:
        claude_dir: Base Claude projects directory.
        project_dir: If set, only list sessions from this project's directory.

    Returns list of (session_id, file_path, title, mtime) tuples, sorted by most recent first.
    """
    sessions: list[tuple[str, str, str, float]] = []
    try:
        if project_dir:
            # Encode the project path the same way Claude does
            encoded = project_dir.replace("/", "-")
            if encoded.startswith("-"):
                encoded = encoded  # Claude keeps the leading dash
            search_dir = os.path.join(claude_dir, encoded)
            if not os.path.isdir(search_dir):
                search_dir = claude_dir  # fallback to all
        else:
            search_dir = claude_dir

        if not os.path.isdir(search_dir):
            return sessions

        for root, _dirs, files in os.walk(search_dir):
            for f in files:
                if f.endswith(".jsonl") and not f.startswith("agent-"):
                    full_path = os.path.join(root, f)
                    session_id = f.removesuffix(".jsonl")
                    mtime = os.path.getmtime(full_path)
                    sessions.append((session_id, full_path, "", mtime))

        sessions.sort(key=lambda x: x[3], reverse=True)

        # Only fetch titles for top results (avoid reading too many files)
        result = []
        for sid, path, _, mtime in sessions[:10]:
            title = get_session_title(path)
            result.append((sid, path, title, mtime))

        return result
    except Exception as e:
        logger.warning(f"Failed to list sessions from {claude_dir}: {e}")
        return []


async def handle_connect(
    channel: str,
    thread_ts: str,
    session_id_arg: str,
    client: AsyncWebClient,
    session_manager: SessionManager,
    config: Settings | None = None,
) -> None:
    """Handle the 'connect' command to attach to an existing Claude session.

    Supports:
        connect          - connect to most recent session
        connect 1        - connect by index (from `sessions` list)
        connect <uuid>   - connect by full session ID
    """
    from ..config import get_settings

    if config is None:
        config = get_settings()

    claude_session_id: str | None = None

    if session_id_arg:
        # Check if it's a numeric index
        if session_id_arg.isdigit():
            index = int(session_id_arg) - 1  # 1-based to 0-based
            available = list_available_sessions(project_dir=config.working_directory)
            if 0 <= index < len(available):
                claude_session_id = available[index][0]
            else:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text=f":warning: Invalid session index `{session_id_arg}`. Use `sessions` to see available sessions.",
                )
                return
        else:
            # Full session ID provided
            claude_session_id = session_id_arg
    else:
        # No argument — auto-connect to the most recent session
        # First try the session file (from SessionStart hook)
        claude_session_id = read_session_id_from_file(config.claude_session_file)

        if not claude_session_id:
            # Fall back to the most recent session on disk
            available = list_available_sessions(project_dir=config.working_directory)
            if available:
                claude_session_id = available[0][0]

    if not claude_session_id:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                ":warning: No sessions found.\n\n"
                "*To connect:*\n"
                "1. Run `/status` in your Claude terminal to get the session ID\n"
                "2. Then use `connect <session-id>` here"
            ),
        )
        return

    # Get or create the Slack session for this thread
    session = await session_manager.get_or_create(
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Set the Claude session ID to connect to the existing session
    session.claude_session_id = claude_session_id
    await session_manager.save(session)

    # Try to get a summary of the session being connected to
    summary = _get_session_summary(claude_session_id, config.working_directory)

    connect_text = (
        f":link: *Connected to Claude session*\n"
        f"Session ID: `{claude_session_id[:12]}...`\n\n"
    )
    if summary:
        connect_text += f"*Session context:*\n{summary}\n\n"
    connect_text += (
        "Messages in this thread will resume that session's conversation history.\n"
        "_Note: The terminal session must not be actively running. "
        "Close it first if it's still open._"
    )

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=connect_text,
    )
    logger.info(f"Connected Slack thread {channel}:{thread_ts} to Claude session {claude_session_id}")


async def handle_list_sessions(
    channel: str,
    thread_ts: str,
    client: AsyncWebClient,
    config: Settings | None = None,
) -> None:
    """Handle the 'sessions' command to list available Claude sessions."""
    import time
    from ..config import get_settings

    if config is None:
        config = get_settings()

    available = list_available_sessions(project_dir=config.working_directory)

    if not available:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=":file_folder: No sessions found.",
        )
        return

    now = time.time()
    lines = []
    for i, (_sid, _path, title, mtime) in enumerate(available[:10], start=1):
        age_s = now - mtime
        if age_s < 3600:
            age = f"{int(age_s / 60)}m ago"
        elif age_s < 86400:
            age = f"{int(age_s / 3600)}h ago"
        else:
            age = f"{int(age_s / 86400)}d ago"
        lines.append(f"*{i}.* {title}  _({age})_")

    session_list = "\n".join(lines)
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            f":file_folder: *Recent sessions*\n\n"
            f"{session_list}\n\n"
            f"_`connect` = most recent · `connect 3` = by number_"
        ),
    )


def _get_session_summary(session_id: str, working_directory: str) -> str:
    """Get a summary of a session by reading its transcript.

    Returns a short summary with the first user message and the last few exchanges.
    """
    import json

    claude_dir = os.path.expanduser("~/.claude/projects")
    encoded = working_directory.replace("/", "-")
    session_file = os.path.join(claude_dir, encoded, f"{session_id}.jsonl")

    if not os.path.exists(session_file):
        # Search all project dirs
        for root, _dirs, files in os.walk(claude_dir):
            if f"{session_id}.jsonl" in files:
                session_file = os.path.join(root, f"{session_id}.jsonl")
                break
        else:
            return ""

    try:
        first_user_msg = ""
        user_messages: list[str] = []

        with open(session_file) as f:
            for line in f:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    data.get("type") == "user"
                    and data.get("message", {}).get("role") == "user"
                    and not data.get("isMeta")
                ):
                    content = data["message"].get("content", "")
                    if isinstance(content, str) and content.strip():
                        msg = content.strip()[:100]
                        if len(content.strip()) > 100:
                            msg += "..."
                        if not first_user_msg:
                            first_user_msg = msg
                        user_messages.append(msg)

        if not first_user_msg:
            return ""

        parts = [f"> *First message:* {first_user_msg}"]
        if len(user_messages) > 1:
            parts.append(f"> *Total messages:* {len(user_messages)}")
            last_msg = user_messages[-1]
            if last_msg != first_user_msg:
                parts.append(f"> *Last message:* {last_msg}")

        return "\n".join(parts)
    except Exception as e:
        logger.debug(f"Failed to read session summary: {e}")
        return ""


async def download_slack_files(
    files: list[dict[str, Any]],
    cwd: str,
    bot_token: str,
) -> list[str]:
    """Download files shared in Slack to the working directory.

    Returns list of saved file paths (relative to cwd).
    """
    import httpx

    saved_files = []
    async with httpx.AsyncClient() as http:
        for file_info in files:
            url = file_info.get("url_private_download") or file_info.get("url_private")
            name = file_info.get("name", "uploaded_file")
            if not url:
                continue

            try:
                resp = await http.get(
                    url,
                    headers={"Authorization": f"Bearer {bot_token}"},
                    follow_redirects=True,
                )
                resp.raise_for_status()

                dest = os.path.join(cwd, name)
                with open(dest, "wb") as f:
                    f.write(resp.content)
                saved_files.append(name)
                logger.info(f"Downloaded file: {name} -> {dest}")
            except Exception as e:
                logger.warning(f"Failed to download file {name}: {e}")

    return saved_files


async def handle_cwd(
    channel: str,
    thread_ts: str,
    path_arg: str,
    client: AsyncWebClient,
    session_manager: SessionManager,
    config: Settings | None = None,
) -> None:
    """Handle the 'cwd' command to show or change the working directory for this thread."""
    from ..config import get_settings

    if config is None:
        config = get_settings()

    session = await session_manager.get_or_create(
        channel_id=channel,
        thread_ts=thread_ts,
    )

    if not path_arg:
        # Show current working directory
        effective_cwd = session.cwd or config.working_directory
        source = "thread override" if session.cwd else "default"
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f":file_folder: *Working directory* ({source}): `{effective_cwd}`",
        )
        return

    # Validate the path exists
    new_path = os.path.expanduser(path_arg)
    new_path = os.path.abspath(new_path)

    if not os.path.isdir(new_path):
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f":warning: Directory not found: `{new_path}`",
        )
        return

    # Set the cwd on the session
    old_cwd = session.cwd or config.working_directory
    session.cwd = new_path
    # Clear the Claude session ID since it's tied to the old project directory
    session.claude_session_id = None
    await session_manager.save(session)

    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            f":file_folder: *Working directory changed*\n"
            f"From: `{old_cwd}`\n"
            f"To: `{new_path}`\n\n"
            f"_Session reset — next message starts a fresh Claude session in the new directory._"
        ),
    )
    logger.info(f"Changed cwd for {channel}:{thread_ts} to {new_path}")


async def handle_mode_command(
    channel: str,
    thread_ts: str,
    mode_arg: str | None,
    client: AsyncWebClient,
    session_manager: SessionManager,
    config: Settings | None = None,
) -> None:
    """Handle the 'mode' command to show or change permission mode."""
    from ..config import get_settings
    config = config or get_settings()

    session = await session_manager.get_or_create(
        channel_id=channel,
        thread_ts=thread_ts,
    )

    if not mode_arg:
        # Show current mode
        effective = session.permission_mode or config.permission_mode
        override = f" (thread override: `{session.permission_mode}`)" if session.permission_mode else ""
        mode_descriptions = {
            "default": "Using Claude's default permissions from settings files",
            "bypass": "All tools run without permission checks",
            "allowEdits": "File edits auto-approved, bash commands blocked",
            "plan": "Read-only mode, no writes or bash",
        }
        desc = mode_descriptions.get(effective, "Unknown")
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=(
                f":shield: *Permission mode:* `{effective}`\n"
                f"{desc}{override}\n"
                f"_Default: `{config.permission_mode}` — change with `mode bypass`, `mode allowEdits`, or `mode plan`_"
            ),
        )
        return

    mode = mode_arg if mode_arg in ("default", "bypass", "allowEdits", "plan") else None
    if not mode:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=":x: Unknown mode. Use `mode default`, `mode bypass`, `mode allowEdits`, or `mode plan`.",
        )
        return

    session.permission_mode = mode
    await session_manager.save(session)

    mode_emoji = {"default": ":shield:", "bypass": ":warning:", "allowEdits": ":pencil:", "plan": ":book:"}
    mode_descriptions = {
        "default": "Using Claude's default permissions from settings files (.claude/settings.json).",
        "bypass": "All tools run without permission checks. Use in sandboxed environments.",
        "allowEdits": "File edits are auto-approved. Bash commands will be blocked.",
        "plan": "Read-only mode. No file writes or bash commands allowed.",
    }
    await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=(
            f"{mode_emoji[mode]} *Permission mode set to `{mode}`*\n"
            f"{mode_descriptions[mode]}"
        ),
    )
    logger.info(f"Set permission_mode={mode} for {channel}:{thread_ts}")


async def process_request(
    channel: str,
    thread_ts: str,
    user_message: str,
    client: AsyncWebClient,
    session_manager: SessionManager,
    claude_agent: ClaudeSlackAgent,
    user_message_ts: str | None = None,
) -> None:
    """Process a user request through Claude."""
    # Get or create session for this thread
    session = await session_manager.get_or_create(
        channel_id=channel,
        thread_ts=thread_ts,
    )

    # Check if session is already processing
    if session.is_processing:
        await client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=":hourglass: I'm still working on the previous request. Please wait...",
        )
        return

    # Add "eyes" reaction to user's message to show we're processing
    if user_message_ts:
        try:
            await client.reactions_add(channel=channel, name="eyes", timestamp=user_message_ts)
        except Exception:
            pass  # Best effort

    # Send initial "thinking" message
    result = await client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text="Claude is thinking...",
        blocks=blocks.thinking_indicator(),
    )

    message_ts = result["ts"]

    # Create message updater for streaming responses
    updater = SlackMessageUpdater(
        client=client,
        channel=channel,
        message_ts=message_ts,
        thread_ts=thread_ts,
    )

    # Process with Claude in background task
    # This allows the event handler to return quickly
    asyncio.create_task(
        _run_claude_task(
            session=session,
            user_message=user_message,
            updater=updater,
            client=client,
            claude_agent=claude_agent,
            session_manager=session_manager,
            user_message_ts=user_message_ts,
        )
    )


async def _run_claude_task(
    session: Any,
    user_message: str,
    updater: SlackMessageUpdater,
    client: AsyncWebClient,
    claude_agent: ClaudeSlackAgent,
    session_manager: SessionManager,
    user_message_ts: str | None = None,
) -> None:
    """Run Claude agent task with error handling."""
    success = False
    try:
        await claude_agent.process_message(
            session=session,
            user_message=user_message,
            updater=updater,
        )
        success = True
    except Exception as e:
        logger.exception(f"Error processing message: {e}")
        await updater.show_error(str(e))
    finally:
        # Ensure session is marked as not processing
        session.is_processing = False
        await session_manager.save(session)

        # Update reaction on user's message
        if user_message_ts:
            try:
                await client.reactions_remove(
                    channel=session.channel_id, name="eyes", timestamp=user_message_ts,
                )
            except Exception:
                pass
            try:
                reaction = "white_check_mark" if success else "x"
                await client.reactions_add(
                    channel=session.channel_id, name=reaction, timestamp=user_message_ts,
                )
            except Exception:
                pass
