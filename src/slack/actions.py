"""Slack action handlers for button clicks and interactions."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from . import blocks

if TYPE_CHECKING:
    from slack_bolt.async_app import AsyncApp
    from slack_sdk.web.async_client import AsyncWebClient

    from ..claude.tool_approval import ApprovalManager
    from ..sessions.manager import SessionManager

logger = logging.getLogger(__name__)


def register_action_handlers(
    app: AsyncApp,
    session_manager: SessionManager,
    approval_manager: ApprovalManager,
    config: Any = None,
) -> None:
    """Register Slack action handlers on the app."""

    @app.action("approve_tool")
    async def handle_approve_tool(
        ack: Any,
        body: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle tool approval button click."""
        await ack()

        try:
            action_value = body["actions"][0]["value"]
            approval_data = json.loads(action_value)
            pending_id = approval_data["pending_id"]
            tool_name = approval_data.get("tool_name", "Unknown")

            logger.info(f"Tool approved: {tool_name} (pending_id={pending_id})")

            # Signal approval
            approved = await approval_manager.approve(pending_id)

            if approved:
                # Update the message to show approved status
                await client.chat_update(
                    channel=body["channel"]["id"],
                    ts=body["message"]["ts"],
                    text=f"{tool_name} approved",
                    blocks=blocks.tool_approved(tool_name, pending_id),
                )
            else:
                # Already decided or not found
                await client.chat_postMessage(
                    channel=body["channel"]["id"],
                    thread_ts=body["message"].get("thread_ts") or body["message"]["ts"],
                    text="This approval request has already been processed.",
                )

        except Exception as e:
            logger.exception(f"Error handling approve action: {e}")

    @app.action("reject_tool")
    async def handle_reject_tool(
        ack: Any,
        body: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle tool rejection button click."""
        await ack()

        try:
            action_value = body["actions"][0]["value"]
            approval_data = json.loads(action_value)
            pending_id = approval_data["pending_id"]
            tool_name = approval_data.get("tool_name", "Unknown")

            logger.info(f"Tool rejected: {tool_name} (pending_id={pending_id})")

            # Signal rejection
            rejected = await approval_manager.reject(
                pending_id, reason="User rejected this action"
            )

            if rejected:
                # Update the message to show rejected status
                await client.chat_update(
                    channel=body["channel"]["id"],
                    ts=body["message"]["ts"],
                    text=f"{tool_name} rejected",
                    blocks=blocks.tool_rejected(
                        tool_name, pending_id, "User rejected this action"
                    ),
                )
            else:
                await client.chat_postMessage(
                    channel=body["channel"]["id"],
                    thread_ts=body["message"].get("thread_ts") or body["message"]["ts"],
                    text="This approval request has already been processed.",
                )

        except Exception as e:
            logger.exception(f"Error handling reject action: {e}")

    @app.action("cancel_operation")
    async def handle_cancel_operation(
        ack: Any,
        body: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle cancel operation button click."""
        await ack()

        try:
            action_value = body["actions"][0]["value"]
            data = json.loads(action_value)
            session_id = data["session_id"]

            logger.info(f"Cancelling session: {session_id}")

            # Mark session as cancelled
            cancelled = await session_manager.cancel(session_id)

            # Also cancel any pending approvals for this session
            await approval_manager.cancel_session_approvals(session_id)

            if cancelled:
                await client.chat_postMessage(
                    channel=body["channel"]["id"],
                    thread_ts=body["message"].get("thread_ts") or body["message"]["ts"],
                    text="Operation cancelled",
                    blocks=blocks.operation_cancelled(),
                )

        except Exception as e:
            logger.exception(f"Error handling cancel action: {e}")

    @app.action("clear_session")
    async def handle_clear_session(
        ack: Any,
        body: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle clear session button click."""
        await ack()

        try:
            channel = body["channel"]["id"]
            thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

            logger.info(f"Clearing session for {channel}:{thread_ts}")

            # Get session first to cancel any pending approvals and capture stats
            session = await session_manager.get(channel, thread_ts)
            cost = 0.0
            turns = 0
            duration = 0
            if session:
                await approval_manager.cancel_session_approvals(session.id)
                cost = session.total_cost_usd
                turns = session.num_turns
                duration = session.total_duration_ms

            # Clear the session
            cleared = await session_manager.clear(channel, thread_ts)

            if cleared:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="Session cleared",
                    blocks=blocks.session_cleared(
                        total_cost_usd=cost,
                        num_turns=turns,
                        total_duration_ms=duration,
                    ),
                )
            else:
                await client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts,
                    text="No active session to clear.",
                )

        except Exception as e:
            logger.exception(f"Error handling clear session action: {e}")

    @app.action("show_status")
    async def handle_show_status(
        ack: Any,
        body: dict[str, Any],
        client: AsyncWebClient,
        logger: logging.Logger,
    ) -> None:
        """Handle show status button click."""
        await ack()

        try:
            action_value = body["actions"][0]["value"]
            data = json.loads(action_value)
            session_id = data["session_id"]

            # Get session info
            session = await session_manager.get_by_id(session_id)

            if session:
                from ..config import get_settings
                default_cwd = config.working_directory if config else get_settings().working_directory
                cwd = session.cwd or default_cwd
                await client.chat_postMessage(
                    channel=body["channel"]["id"],
                    thread_ts=body["message"].get("thread_ts") or body["message"]["ts"],
                    text="Session status",
                    blocks=blocks.session_status(
                        session_id=session.id,
                        created_at=session.created_at.strftime("%Y-%m-%d %H:%M UTC"),
                        is_processing=session.is_processing,
                        cwd=cwd,
                        claude_session_id=session.claude_session_id,
                        total_cost_usd=session.total_cost_usd,
                        num_turns=session.num_turns,
                    ),
                )
            else:
                await client.chat_postMessage(
                    channel=body["channel"]["id"],
                    thread_ts=body["message"].get("thread_ts") or body["message"]["ts"],
                    text="Session not found. It may have expired.",
                )

        except Exception as e:
            logger.exception(f"Error handling status action: {e}")
