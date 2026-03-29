import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket

from shared.protocol import RouterToAgent, serialize

from .thread_store import RedisThreadStore, ThreadState

logger = logging.getLogger(__name__)


@dataclass
class PendingRegistration:
    ws: WebSocket
    token: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ActiveConnection:
    ws: WebSocket
    slack_user_id: str
    auth_token: str = ""
    threads: dict[str, ThreadState] = field(default_factory=dict)


class WebSocketManager:
    def __init__(
        self,
        *,
        token_expiry_seconds: int,
        thread_store: RedisThreadStore,
    ) -> None:
        self._token_expiry_seconds = token_expiry_seconds
        self._thread_store = thread_store
        self._pending: dict[str, PendingRegistration] = {}
        self._active: dict[str, ActiveConnection] = {}

    async def register_pending(self, *, ws: WebSocket, token: str) -> None:
        self._pending[token] = PendingRegistration(ws=ws, token=token)
        logger.info(f"Pending registration: token={token[:8]}...")

    async def verify_token(self, *, token: str, slack_user_id: str) -> bool:
        pending = self._pending.pop(token, None)
        if not pending:
            return False

        age = (datetime.now(timezone.utc) - pending.created_at).total_seconds()
        if age > self._token_expiry_seconds:
            logger.warning(f"Token expired: {token[:8]}... (age={age:.0f}s)")
            return False

        if slack_user_id in self._active:
            old = self._active[slack_user_id]
            logger.info(f"Replacing existing connection for {slack_user_id}")
            try:
                await old.ws.close()
            except Exception:
                pass

        auth_token = secrets.token_urlsafe(32)
        await self._thread_store.save_auth_token(auth_token=auth_token, slack_user_id=slack_user_id)

        persisted_threads = await self._thread_store.load_all_thread_states(
            slack_user_id=slack_user_id
        )

        self._active[slack_user_id] = ActiveConnection(
            ws=pending.ws,
            slack_user_id=slack_user_id,
            auth_token=auth_token,
            threads=persisted_threads,
        )

        verified_msg: RouterToAgent = {
            "type": "verified",
            "token": token,
            "slack_user_id": slack_user_id,
            "auth_token": auth_token,
        }
        await pending.ws.send_text(serialize(message=verified_msg))
        logger.info(f"Verified: {slack_user_id} → agent (auth_token={auth_token[:8]}...)")
        return True

    async def reconnect_agent(self, *, ws: WebSocket, auth_token: str) -> bool:
        slack_user_id = await self._thread_store.lookup_auth_token(auth_token=auth_token)
        if not slack_user_id:
            return False

        if slack_user_id in self._active:
            old = self._active[slack_user_id]
            try:
                await old.ws.close()
            except Exception:
                pass

        persisted_threads = await self._thread_store.load_all_thread_states(
            slack_user_id=slack_user_id
        )

        self._active[slack_user_id] = ActiveConnection(
            ws=ws,
            slack_user_id=slack_user_id,
            auth_token=auth_token,
            threads=persisted_threads,
        )

        verified_msg: RouterToAgent = {
            "type": "verified",
            "token": "",
            "slack_user_id": slack_user_id,
            "auth_token": auth_token,
        }
        await ws.send_text(serialize(message=verified_msg))
        logger.info(f"Reconnected: {slack_user_id} via auth_token")
        return True

    def get_connection(self, *, slack_user_id: str) -> ActiveConnection | None:
        return self._active.get(slack_user_id)

    async def send_to_agent(self, *, slack_user_id: str, message: RouterToAgent) -> bool:
        conn = self._active.get(slack_user_id)
        if not conn:
            return False
        await conn.ws.send_text(serialize(message=message))
        return True

    async def remove_connection(self, *, slack_user_id: str) -> None:
        conn = self._active.pop(slack_user_id, None)
        if conn:
            if conn.auth_token:
                await self._thread_store.revoke_auth_token(auth_token=conn.auth_token)
            logger.info(f"Removed connection for {slack_user_id}")
            try:
                await conn.ws.close()
            except Exception:
                pass

    def get_thread_state(self, *, slack_user_id: str, thread_key: str) -> ThreadState | None:
        conn = self._active.get(slack_user_id)
        if not conn:
            return None
        return conn.threads.get(thread_key)

    def set_thread_state(self, *, slack_user_id: str, thread_key: str, state: ThreadState) -> None:
        conn = self._active.get(slack_user_id)
        if conn:
            conn.threads[thread_key] = state
            asyncio.create_task(
                self._thread_store.save_thread_state(
                    slack_user_id=slack_user_id, thread_key=thread_key, state=state
                )
            )

    def clear_thread_state(self, *, slack_user_id: str, thread_key: str) -> None:
        conn = self._active.get(slack_user_id)
        if conn:
            conn.threads.pop(thread_key, None)
            asyncio.create_task(
                self._thread_store.delete_thread_state(
                    slack_user_id=slack_user_id, thread_key=thread_key
                )
            )

    async def cleanup_expired_tokens(self) -> int:
        now = datetime.now(timezone.utc)
        expired = [
            token
            for token, reg in self._pending.items()
            if (now - reg.created_at).total_seconds() > self._token_expiry_seconds
        ]
        for token in expired:
            pending = self._pending.pop(token)
            try:
                await pending.ws.close()
            except Exception:
                pass
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired pending registrations")
        return len(expired)

    def find_user_by_ws(self, *, ws: WebSocket) -> str | None:
        for user_id, conn in self._active.items():
            if conn.ws is ws:
                return user_id
        return None

    async def handle_agent_disconnect(self, *, ws: WebSocket) -> None:
        user_id = self.find_user_by_ws(ws=ws)
        if user_id:
            self._active.pop(user_id, None)
            logger.info(f"Agent disconnected: {user_id}")

        expired_tokens = [token for token, reg in self._pending.items() if reg.ws is ws]
        for token in expired_tokens:
            self._pending.pop(token)
