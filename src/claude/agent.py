"""Claude Code SDK integration for Slack."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from claude_code_sdk import query
from claude_code_sdk.types import (
    AssistantMessage,
    ClaudeCodeOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from ..config import Settings
from ..slack import blocks

if TYPE_CHECKING:
    from ..sessions.manager import Session, SessionManager
    from ..slack.message_updater import SlackMessageUpdater

logger = logging.getLogger(__name__)


async def make_prompt_stream(
    user_message: str,
    session_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Create an async iterable prompt for streaming mode."""
    yield {
        "type": "user",
        "message": {"role": "user", "content": user_message},
        "session_id": session_id,
    }

class ClaudeSlackAgent:
    """Manages Claude agent sessions for Slack integration."""

    def __init__(
        self,
        config: Settings,
        session_manager: SessionManager,
    ) -> None:
        self.config = config
        self.session_manager = session_manager

    async def process_message(
        self,
        session: Session,
        user_message: str,
        updater: SlackMessageUpdater,
    ) -> None:
        """Process a user message through Claude."""
        # Mark session as processing
        session.is_processing = True
        await self.session_manager.save(session)

        try:
            await self._run_query(session, user_message, updater)
        except asyncio.CancelledError:
            logger.info(f"Session {session.id} was cancelled")
            await updater.append("\n\n:stop_sign: _Operation cancelled_")
        except Exception as e:
            logger.exception(f"Claude error in session {session.id}: {e}")
            error_msg = str(e)
            # Detect resume/initialize failures (session likely still active in terminal)
            if "Control request timeout: initialize" in error_msg or (
                "exit code" in error_msg and session.claude_session_id
            ):
                await updater.append(
                    "\n\n:x: *Failed to resume session.*\n"
                    "This usually means the session is still running in a terminal. "
                    "Close the terminal session first, then try again.\n\n"
                    "_You can also use `clear session` and start fresh._"
                )
                # Clear the bad session ID so next message starts fresh
                session.claude_session_id = None
            else:
                await updater.append(f"\n\n:x: *Error:* {error_msg}")
        finally:
            # Mark session as not processing
            session.is_processing = False
            await self.session_manager.save(session)
            await updater.finalize(session.id)

    async def _run_query(
        self,
        session: Session,
        user_message: str,
        updater: SlackMessageUpdater,
    ) -> None:
        """Run the Claude query with streaming."""
        # Build options — use per-session cwd if set, otherwise config default
        effective_cwd = session.cwd or self.config.working_directory
        options = ClaudeCodeOptions(
            cwd=effective_cwd,
            max_turns=self.config.claude_max_turns,
        )

        # Permission modes. In headless mode, the CLI auto-approves all tools regardless
        # of --permission-mode, so we enforce restrictions via disallowed_tools instead.
        effective_mode = session.permission_mode or self.config.permission_mode
        options.permission_mode = "bypassPermissions"
        if effective_mode == "allowEdits":
            options.disallowed_tools = ["Bash"]
        elif effective_mode == "plan":
            options.disallowed_tools = ["Bash", "Write", "Edit", "NotebookEdit"]
        elif effective_mode == "default":
            # Use Claude's default permissions — don't bypass, don't disallow
            options.permission_mode = "default"
        # else: bypass — no restrictions
        logger.info(f"Permission mode: {effective_mode}, disallowed_tools: {options.disallowed_tools}")

        # Only set model if explicitly configured
        if self.config.claude_model:
            options.model = self.config.claude_model

        # Resume existing session if available
        if session.claude_session_id:
            options.resume = session.claude_session_id

        # Create streaming prompt
        prompt_stream = make_prompt_stream(user_message, session.claude_session_id)

        # Run the query with streaming prompt
        async for message in query(prompt=prompt_stream, options=options):
            # Check for cancellation
            if session.is_cancelled:
                raise asyncio.CancelledError("Session cancelled by user")

            await self._handle_message(message, session, updater)

    async def _handle_message(
        self,
        message: Any,
        session: Session,
        updater: SlackMessageUpdater,
    ) -> None:
        """Handle different message types from Claude."""
        if isinstance(message, AssistantMessage):
            # Process content blocks
            for block in message.content:
                if isinstance(block, TextBlock):
                    await updater.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    # Show tool usage in the message
                    tool_name = block.name
                    tool_input = block.input if hasattr(block, 'input') else {}
                    logger.info(f"Tool use: {tool_name}")

                    # Format tool usage for display
                    tool_display = self._format_tool_use(tool_name, tool_input)
                    await updater.append(f"\n\n{tool_display}\n")
                elif isinstance(block, ToolResultBlock):
                    # Optionally show tool results (can be verbose)
                    pass

        elif isinstance(message, ResultMessage):
            # Capture session ID for future resume
            if hasattr(message, "session_id") and message.session_id:
                is_new_session = session.claude_session_id is None
                session.claude_session_id = message.session_id

                if is_new_session:
                    cwd = session.cwd or self.config.working_directory
                    await updater.append(
                        f"\n\n---\n:id: *Session ID:* `{message.session_id}`\n"
                        f"_To continue from terminal:_\n"
                        f"```cd {cwd} && claude --resume {message.session_id}```"
                    )

            # Track cost and usage
            if hasattr(message, "total_cost_usd") and message.total_cost_usd is not None:
                session.total_cost_usd += message.total_cost_usd
            if hasattr(message, "num_turns"):
                session.num_turns += message.num_turns
            if hasattr(message, "duration_ms"):
                session.total_duration_ms += message.duration_ms
            await self.session_manager.save(session)

            # Handle result based on subtype
            if hasattr(message, "subtype"):
                if message.subtype == "success":
                    if hasattr(message, "result") and message.result:
                        await updater.append(f"\n\n{message.result}")
                elif message.subtype and message.subtype.startswith("error"):
                    await updater.append(f"\n\n:warning: _{message.subtype}_")

        elif isinstance(message, SystemMessage):
            # Log system messages
            logger.debug(f"System message: {message}")

    def _format_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        """Format tool usage for display in Slack."""
        if tool_name == "Read":
            file_path = tool_input.get("file_path", "unknown")
            return f":mag: *Reading* `{file_path}`"
        elif tool_name == "Write":
            file_path = tool_input.get("file_path", "unknown")
            return f":pencil2: *Writing* `{file_path}`"
        elif tool_name == "Edit":
            file_path = tool_input.get("file_path", "unknown")
            return f":pencil: *Editing* `{file_path}`"
        elif tool_name == "Bash":
            command = tool_input.get("command", "")
            desc = tool_input.get("description", "")
            if desc:
                return f":terminal: *Running:* {desc}\n```{command[:200]}```"
            return f":terminal: *Running:*\n```{command[:200]}```"
        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            return f":file_folder: *Searching for* `{pattern}`"
        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            return f":mag_right: *Searching for* `{pattern}`"
        elif tool_name == "WebSearch":
            query = tool_input.get("query", "")
            return f":globe_with_meridians: *Searching web:* {query}"
        elif tool_name == "WebFetch":
            url = tool_input.get("url", "")
            return f":link: *Fetching* `{url[:50]}...`" if len(url) > 50 else f":link: *Fetching* `{url}`"
        elif tool_name == "Task":
            desc = tool_input.get("description", "subtask")
            return f":robot_face: *Spawning agent:* {desc}"
        else:
            return f":wrench: *Using tool:* `{tool_name}`"

