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
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolPermissionContext,
    ToolResultBlock,
    ToolUseBlock,
)

from ..config import Settings
from ..slack import blocks
from .tool_approval import ApprovalManager

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

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

# Tools that are read-only and safe to auto-approve
READ_ONLY_TOOLS = {"Read", "Glob", "Grep", "WebSearch", "WebFetch"}

# Tools that modify the system
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}

# The bash tool
BASH_TOOLS = {"Bash"}


class ClaudeSlackAgent:
    """Manages Claude agent sessions for Slack integration."""

    def __init__(
        self,
        config: Settings,
        session_manager: SessionManager,
        approval_manager: ApprovalManager,
    ) -> None:
        self.config = config
        self.session_manager = session_manager
        self.approval_manager = approval_manager

    async def process_message(
        self,
        session: Session,
        user_message: str,
        updater: SlackMessageUpdater,
        slack_client: AsyncWebClient,
    ) -> None:
        """Process a user message through Claude."""
        # Mark session as processing
        session.is_processing = True
        await self.session_manager.save(session)

        try:
            await self._run_query(session, user_message, updater, slack_client)
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
        slack_client: AsyncWebClient,
    ) -> None:
        """Run the Claude query with streaming."""
        # Create the permission callback
        can_use_tool = self._create_permission_callback(session, updater, slack_client)

        # Build options
        options = ClaudeCodeOptions(
            cwd=self.config.working_directory,
            max_turns=self.config.claude_max_turns,
        )

        # Set permission mode or custom callback
        if self.config.dangerously_skip_permissions:
            logger.info("Using bypassPermissions mode (DANGEROUSLY_SKIP_PERMISSIONS=true)")
            options.permission_mode = "bypassPermissions"
        else:
            logger.info("Using can_use_tool callback for permission checks")
            options.can_use_tool = can_use_tool

        # Only set model if explicitly configured
        if self.config.claude_model:
            options.model = self.config.claude_model

        # Resume existing session if available
        if session.claude_session_id:
            options.resume = session.claude_session_id

        # Create streaming prompt (required for can_use_tool callback)
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
                await self.session_manager.save(session)

                if is_new_session:
                    cwd = self.config.working_directory
                    await updater.append(
                        f"\n\n---\n:id: *Session ID:* `{message.session_id}`\n"
                        f"_To continue from terminal:_\n"
                        f"```cd {cwd} && claude --resume {message.session_id}```"
                    )

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

    def _create_permission_callback(
        self,
        session: Session,
        updater: SlackMessageUpdater,
        slack_client: AsyncWebClient,
    ):
        """Create the tool permission callback."""

        async def can_use_tool(
            tool_name: str,
            tool_input: dict[str, Any],
            context: ToolPermissionContext,
        ) -> PermissionResultAllow | PermissionResultDeny:
            """
            Callback to determine if a tool can be used.

            Returns:
                PermissionResultAllow to allow the tool
                PermissionResultDeny to deny the tool with a message
            """
            logger.info(f"Permission check for tool: {tool_name}")

            # Auto-approve read-only tools
            if self.config.auto_approve_read_only and tool_name in READ_ONLY_TOOLS:
                logger.info(f"Auto-approving read-only tool: {tool_name}")
                return PermissionResultAllow()

            # Check if tool requires approval
            needs_approval = False
            if tool_name in BASH_TOOLS and self.config.require_approval_for_bash:
                needs_approval = True
            elif tool_name in WRITE_TOOLS and self.config.require_approval_for_write:
                needs_approval = True

            if not needs_approval:
                logger.info(f"Auto-approving tool (no approval required): {tool_name}")
                return PermissionResultAllow()

            # Request approval via Slack
            logger.info(f"Requesting Slack approval for tool: {tool_name}")
            return await self._request_approval(
                session, tool_name, tool_input, slack_client
            )

        return can_use_tool

    async def _request_approval(
        self,
        session: Session,
        tool_name: str,
        tool_input: dict[str, Any],
        slack_client: AsyncWebClient,
    ) -> PermissionResultAllow | PermissionResultDeny:
        """Request user approval for a tool via Slack."""
        # Create pending approval
        pending = await self.approval_manager.create_pending(
            session_id=session.id,
            tool_name=tool_name,
            tool_input=tool_input,
        )

        try:
            # Post approval request to Slack
            await slack_client.chat_postMessage(
                channel=session.channel_id,
                thread_ts=session.thread_ts,
                blocks=blocks.tool_approval_request(
                    tool_name=tool_name,
                    tool_input=tool_input,
                    pending_id=pending.id,
                    session_id=session.id,
                ),
                text=f"Claude wants to use {tool_name}",  # Fallback text
            )

            # Wait for user decision (with timeout)
            try:
                result = await asyncio.wait_for(
                    pending.wait_for_decision(),
                    timeout=self.approval_manager.default_timeout,
                )

                if result.approved:
                    return PermissionResultAllow()
                else:
                    return PermissionResultDeny(message=result.reason)

            except asyncio.TimeoutError:
                return PermissionResultDeny(
                    message=f"Approval request timed out after {self.approval_manager.default_timeout}s"
                )

        finally:
            # Clean up the pending approval
            await self.approval_manager.remove(pending.id)
