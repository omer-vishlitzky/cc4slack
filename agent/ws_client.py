import asyncio
import logging

import websockets
from websockets.asyncio.client import ClientConnection

from shared.protocol import AgentToRouter, RouterToAgent, parse_router_message, serialize

logger = logging.getLogger(__name__)


class AgentWebSocket:
    def __init__(self, *, url: str) -> None:
        self._url = url
        self._ws: ClientConnection | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(self._url)
        logger.info(f"Connected to router: {self._url}")

    async def send(self, *, message: AgentToRouter) -> None:
        if not self._ws:
            logger.warning("Cannot send — WebSocket is closed")
            return
        await self._ws.send(serialize(message=message))

    async def receive(self) -> RouterToAgent:
        assert self._ws is not None
        raw = await self._ws.recv()
        assert isinstance(raw, str)
        return parse_router_message(raw=raw)

    async def close(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    def start_heartbeat(self, *, interval_seconds: int = 30) -> None:
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(interval_seconds=interval_seconds)
        )

    async def _heartbeat_loop(self, *, interval_seconds: int) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            await self.send(message={"type": "heartbeat"})
