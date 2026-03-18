"""Slack Bolt app setup and initialization."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from slack_bolt.async_app import AsyncApp

from .actions import register_action_handlers
from .events import register_event_handlers

if TYPE_CHECKING:
    from ..claude.agent import ClaudeSlackAgent
    from ..config import Settings
    from ..sessions.manager import SessionManager

logger = logging.getLogger(__name__)


def create_slack_app(
    config: Settings,
    session_manager: SessionManager,
    claude_agent: ClaudeSlackAgent,
) -> AsyncApp:
    """Create and configure the Slack Bolt app."""
    # Create the Slack Bolt app
    app = AsyncApp(
        token=config.slack_bot_token,
        signing_secret=config.slack_signing_secret or None,
    )

    # Register event handlers (mentions, messages)
    register_event_handlers(app, session_manager, claude_agent, config)

    # Register action handlers (button clicks)
    register_action_handlers(app, session_manager, config)

    logger.info("Slack app configured successfully")

    return app
