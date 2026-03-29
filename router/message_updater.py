import asyncio
import logging
import time
from typing import TYPE_CHECKING

from . import blocks

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

UPDATE_INTERVAL = 30
MAX_MESSAGE_LENGTH = 2900


class SlackMessageUpdater:
    def __init__(
        self,
        *,
        client: "AsyncWebClient",
        channel: str,
        message_ts: str,
        thread_ts: str,
    ) -> None:
        self._client = client
        self._channel = channel
        self._message_ts = message_ts
        self._thread_ts = thread_ts
        self._buffer = ""
        self._last_update = 0.0
        self._lock = asyncio.Lock()
        self._pending_update = False
        self._finalized = False

    async def append(self, *, text: str) -> None:
        async with self._lock:
            self._buffer += text
            if not self._finalized:
                await self._maybe_flush()

    async def _maybe_flush(self) -> None:
        now = time.time()
        if now - self._last_update >= UPDATE_INTERVAL:
            await self._flush()
            return
        if not self._pending_update:
            self._pending_update = True
            delay = UPDATE_INTERVAL - (now - self._last_update)
            asyncio.create_task(self._delayed_flush(delay=delay))

    async def _delayed_flush(self, *, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._lock:
            self._pending_update = False
            if not self._finalized:
                await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return
        display_text = self._buffer
        if len(display_text) > MAX_MESSAGE_LENGTH:
            display_text = "..." + display_text[-(MAX_MESSAGE_LENGTH - 100) :]
        await self._client.chat_update(
            channel=self._channel,
            ts=self._message_ts,
            text=display_text,
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": display_text}}],
        )
        self._last_update = time.time()

    async def finalize(self, *, session_id: str) -> None:
        async with self._lock:
            self._finalized = True
            if not self._buffer:
                self._buffer = "_No response_"

            chunks = _split_into_chunks(text=self._buffer)

            if len(chunks) == 1:
                await self._client.chat_update(
                    channel=self._channel,
                    ts=self._message_ts,
                    text=chunks[0],
                    blocks=blocks.response_message(text=chunks[0], session_id=session_id),
                )
                return

            await self._client.chat_update(
                channel=self._channel,
                ts=self._message_ts,
                text=chunks[0],
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": chunks[0]}}],
            )

            for i, chunk in enumerate(chunks[1:], start=2):
                is_last = i == len(chunks)
                if is_last:
                    await self._client.chat_postMessage(
                        channel=self._channel,
                        thread_ts=self._thread_ts,
                        text=chunk,
                        blocks=blocks.response_message(text=chunk, session_id=session_id),
                    )
                else:
                    await self._client.chat_postMessage(
                        channel=self._channel,
                        thread_ts=self._thread_ts,
                        text=chunk,
                        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": chunk}}],
                    )

    async def show_error(self, *, error: str) -> None:
        async with self._lock:
            self._finalized = True
            await self._client.chat_update(
                channel=self._channel,
                ts=self._message_ts,
                text=f"Error: {error}",
                blocks=blocks.error_message(error=error),
            )


def _split_into_chunks(*, text: str) -> list[str]:
    if len(text) <= MAX_MESSAGE_LENGTH:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= MAX_MESSAGE_LENGTH:
            chunks.append(remaining)
            break

        break_point = MAX_MESSAGE_LENGTH

        newline_pos = remaining.rfind("\n", 0, MAX_MESSAGE_LENGTH)
        if newline_pos > MAX_MESSAGE_LENGTH // 2:
            break_point = newline_pos + 1
        else:
            space_pos = remaining.rfind(" ", 0, MAX_MESSAGE_LENGTH)
            if space_pos > MAX_MESSAGE_LENGTH // 2:
                break_point = space_pos + 1

        chunks.append(remaining[:break_point])
        remaining = remaining[break_point:]

    return chunks
