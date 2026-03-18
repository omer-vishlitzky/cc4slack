"""Session management for Slack threads."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .storage import SessionStorage


@dataclass
class Session:
    """Represents a Claude session tied to a Slack thread."""

    id: str
    channel_id: str
    thread_ts: str
    claude_session_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_notification: str = ""
    is_cancelled: bool = False
    is_processing: bool = False
    total_cost_usd: float = 0.0
    num_turns: int = 0
    total_duration_ms: int = 0
    cwd: str | None = None  # Per-thread working directory override
    permission_mode: str | None = None  # Per-thread override: None = use global default

    @property
    def thread_key(self) -> str:
        """Unique key for this thread (channel_id:thread_ts)."""
        return f"{self.channel_id}:{self.thread_ts}"

    def update_activity(self) -> None:
        """Update the last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)


class SessionManager:
    """Manages Claude sessions mapped to Slack threads."""

    def __init__(self, storage: SessionStorage, ttl_seconds: int = 86400) -> None:
        self.storage = storage
        self.ttl_seconds = ttl_seconds

    async def get_or_create(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Session:
        """Get existing session or create new one for thread."""
        thread_key = f"{channel_id}:{thread_ts}"

        session = await self.storage.get(thread_key)
        if session:
            session.update_activity()
            await self.storage.save(session)
            return session

        # Create new session
        session = Session(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        await self.storage.save(session)
        return session

    async def get(self, channel_id: str, thread_ts: str) -> Session | None:
        """Get session for a thread if it exists."""
        thread_key = f"{channel_id}:{thread_ts}"
        return await self.storage.get(thread_key)

    async def get_by_id(self, session_id: str) -> Session | None:
        """Get session by its ID."""
        return await self.storage.get_by_id(session_id)

    async def save(self, session: Session) -> None:
        """Save session state."""
        session.update_activity()
        await self.storage.save(session)

    async def clear(self, channel_id: str, thread_ts: str) -> bool:
        """Clear/delete session for a thread. Returns True if session existed."""
        thread_key = f"{channel_id}:{thread_ts}"
        existing = await self.storage.get(thread_key)
        if existing:
            await self.storage.delete(thread_key)
            return True
        return False

    async def cancel(self, session_id: str) -> bool:
        """Mark a session as cancelled. Returns True if session found."""
        session = await self.storage.get_by_id(session_id)
        if session:
            session.is_cancelled = True
            await self.storage.save(session)
            return True
        return False

    async def set_processing(self, session_id: str, processing: bool) -> bool:
        """Set the processing state of a session."""
        session = await self.storage.get_by_id(session_id)
        if session:
            session.is_processing = processing
            await self.storage.save(session)
            return True
        return False

    async def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        return await self.storage.cleanup_older_than(self.ttl_seconds)
