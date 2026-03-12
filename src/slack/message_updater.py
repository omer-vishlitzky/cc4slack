"""Streaming message updater for Slack."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from . import blocks

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


class SlackMessageUpdater:
    """Updates a Slack message with streaming content.

    Rate-limits updates to avoid hitting Slack API limits while
    providing responsive feedback to users. For long responses,
    posts continuation messages instead of truncating.
    """

    def __init__(
        self,
        client: AsyncWebClient,
        channel: str,
        message_ts: str,
        thread_ts: str,
        update_interval: float = 0.5,
        max_length: int = 2900,  # Leave some margin for safety
    ) -> None:
        """
        Initialize the message updater.

        Args:
            client: Slack AsyncWebClient
            channel: Channel ID
            message_ts: Timestamp of message to update
            thread_ts: Thread timestamp
            update_interval: Minimum seconds between updates
            max_length: Maximum text length per message (Slack limit is ~3000)
        """
        self.client = client
        self.channel = channel
        self.message_ts = message_ts
        self.thread_ts = thread_ts
        self.update_interval = update_interval
        self.max_length = max_length

        self._buffer = ""
        self._last_update = 0.0
        self._lock = asyncio.Lock()
        self._pending_update = False
        self._finalized = False
        self._continuation_messages: list[str] = []  # Track continuation message timestamps

    async def append(self, text: str) -> None:
        """Append text to the buffer and update if needed."""
        async with self._lock:
            self._buffer += text
            if not self._finalized:
                await self._maybe_flush()

    async def set_text(self, text: str) -> None:
        """Set the entire buffer text and update."""
        async with self._lock:
            self._buffer = text
            await self._maybe_flush()

    async def _maybe_flush(self) -> None:
        """Flush buffer to Slack if enough time has passed."""
        now = time.time()
        if now - self._last_update >= self.update_interval:
            await self._flush()
        else:
            # Schedule a delayed flush if not already pending
            if not self._pending_update:
                self._pending_update = True
                delay = self.update_interval - (now - self._last_update)
                asyncio.create_task(self._delayed_flush(delay))

    async def _delayed_flush(self, delay: float) -> None:
        """Flush after a delay."""
        await asyncio.sleep(delay)
        async with self._lock:
            self._pending_update = False
            if not self._finalized:
                await self._flush()

    async def _flush(self) -> None:
        """Send buffered content to Slack."""
        if not self._buffer:
            return

        try:
            # For streaming updates, just show the tail of long content
            # Full content will be posted in finalize()
            if len(self._buffer) > self.max_length:
                display_text = "..." + self._buffer[-(self.max_length - 100):]
            else:
                display_text = self._buffer

            await self.client.chat_update(
                channel=self.channel,
                ts=self.message_ts,
                text=display_text,  # Fallback text
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": display_text,
                        },
                    }
                ],
            )
            self._last_update = time.time()
        except Exception as e:
            # Log but don't fail - message updates are best effort
            logger.warning(f"Failed to update message: {e}")

    async def finalize(self, session_id: str) -> None:
        """Send final message(s) with action buttons.

        For long responses, splits into multiple messages to avoid truncation.
        """
        async with self._lock:
            self._finalized = True

            try:
                if not self._buffer:
                    self._buffer = "_No response_"

                # Split long content into chunks
                chunks = self._split_into_chunks(self._buffer)

                if len(chunks) == 1:
                    # Single message - update the original
                    await self.client.chat_update(
                        channel=self.channel,
                        ts=self.message_ts,
                        text=chunks[0],
                        blocks=blocks.response_message(chunks[0], session_id),
                    )
                else:
                    # Multiple messages needed
                    # Update the first message
                    await self.client.chat_update(
                        channel=self.channel,
                        ts=self.message_ts,
                        text=chunks[0],
                        blocks=[
                            {
                                "type": "section",
                                "text": {"type": "mrkdwn", "text": chunks[0]},
                            }
                        ],
                    )

                    # Post continuation messages
                    for i, chunk in enumerate(chunks[1:], start=2):
                        is_last = (i == len(chunks))

                        if is_last:
                            # Last chunk gets the action buttons
                            result = await self.client.chat_postMessage(
                                channel=self.channel,
                                thread_ts=self.thread_ts,
                                text=chunk,
                                blocks=blocks.response_message(chunk, session_id),
                            )
                        else:
                            # Middle chunks are plain
                            result = await self.client.chat_postMessage(
                                channel=self.channel,
                                thread_ts=self.thread_ts,
                                text=chunk,
                                blocks=[
                                    {
                                        "type": "section",
                                        "text": {"type": "mrkdwn", "text": chunk},
                                    }
                                ],
                            )
                        self._continuation_messages.append(result["ts"])

            except Exception as e:
                logger.warning(f"Failed to finalize message: {e}")

    def _split_into_chunks(self, text: str) -> list[str]:
        """Split text into chunks that fit within Slack's limit."""
        if len(text) <= self.max_length:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            if len(remaining) <= self.max_length:
                chunks.append(remaining)
                break

            # Find a good break point (newline or space)
            break_point = self.max_length

            # Try to break at a newline
            newline_pos = remaining.rfind('\n', 0, self.max_length)
            if newline_pos > self.max_length // 2:
                break_point = newline_pos + 1
            else:
                # Try to break at a space
                space_pos = remaining.rfind(' ', 0, self.max_length)
                if space_pos > self.max_length // 2:
                    break_point = space_pos + 1

            chunks.append(remaining[:break_point])
            remaining = remaining[break_point:]

        return chunks

    async def show_error(self, error: str) -> None:
        """Update message to show an error."""
        async with self._lock:
            try:
                await self.client.chat_update(
                    channel=self.channel,
                    ts=self.message_ts,
                    text=f"Error: {error}",
                    blocks=blocks.error_message(error),
                )
            except Exception as e:
                logger.warning(f"Failed to show error: {e}")

    @property
    def current_text(self) -> str:
        """Get the current buffer text."""
        return self._buffer
