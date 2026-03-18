"""Main entry point for cc4slack."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import NoReturn

import structlog
from dotenv import load_dotenv
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from .claude.agent import ClaudeSlackAgent
from .config import Settings, get_settings
from .sessions.manager import SessionManager
from .sessions.storage import MemorySessionStorage
from .slack.app import create_slack_app


def setup_logging(level: str = "INFO", log_file: str = "cc4slack.log") -> None:
    """Configure structured logging to both console and file."""
    log_level = getattr(logging, level.upper())

    # Create formatters
    console_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    file_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(console_format, datefmt="%H:%M:%S"))

    # File handler
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(file_format, datefmt="%Y-%m-%d %H:%M:%S"))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


async def cleanup_loop(
    session_manager: SessionManager,
    interval: int = 60,
) -> NoReturn:
    """Periodic cleanup of expired sessions."""
    logger = logging.getLogger(__name__)

    while True:
        try:
            await asyncio.sleep(interval)

            # Cleanup expired sessions
            sessions_cleaned = await session_manager.cleanup_expired()
            if sessions_cleaned:
                logger.debug(f"Cleaned up {sessions_cleaned} expired sessions")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"Error in cleanup loop: {e}")


async def run_app() -> None:
    """Run the Slack app with Socket Mode."""
    logger = logging.getLogger(__name__)

    # Load environment variables
    load_dotenv()

    # Get configuration
    config = get_settings()

    # Setup logging
    setup_logging(config.log_level)

    logger.info("Starting cc4slack...")
    logger.info(f"Working directory: {config.working_directory}")
    logger.info(f"Claude model: {config.claude_model}")
    logger.info(f"Session storage: {config.session_storage}")

    # Initialize storage
    if config.session_storage == "redis":
        # TODO: Implement Redis storage
        logger.warning("Redis storage not yet implemented, using memory storage")
        storage = MemorySessionStorage()
    else:
        storage = MemorySessionStorage()

    # Initialize managers
    session_manager = SessionManager(storage, config.session_ttl_seconds)

    # Initialize Claude agent
    claude_agent = ClaudeSlackAgent(
        config=config,
        session_manager=session_manager,
    )

    # Create Slack app
    app = create_slack_app(
        config=config,
        session_manager=session_manager,
        claude_agent=claude_agent,
    )

    # Start cleanup task
    cleanup_task = asyncio.create_task(
        cleanup_loop(session_manager)
    )

    # Create Socket Mode handler
    handler = AsyncSocketModeHandler(app, config.slack_app_token)

    # Setup graceful shutdown
    shutdown_event = asyncio.Event()

    def handle_shutdown(sig: signal.Signals) -> None:
        logger.info(f"Received {sig.name}, shutting down...")
        shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig: handle_shutdown(s))

    try:
        # Start the Socket Mode connection
        logger.info("Connecting to Slack via Socket Mode...")
        await handler.connect_async()
        logger.info("Connected! Bot is ready to receive messages.")

        # Wait for shutdown signal
        await shutdown_event.wait()

    except Exception as e:
        logger.exception(f"Error running app: {e}")
        raise
    finally:
        # Cleanup
        logger.info("Shutting down...")
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass

        await handler.close_async()
        logger.info("Shutdown complete.")


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(run_app())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
