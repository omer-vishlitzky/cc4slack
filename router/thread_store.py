import json
import logging
from dataclasses import asdict, dataclass

import redis.asyncio as redis_lib

logger = logging.getLogger(__name__)

AUTH_TTL_SECONDS = 604800
THREAD_TTL_SECONDS = 86400


@dataclass
class ThreadState:
    channel: str
    thread_ts: str
    message_ts: str
    session_id: str = ""
    cwd: str = "."
    permission_mode: str = "default"
    model: str = ""
    last_processed_ts: str = ""
    total_cost_usd: float = 0.0
    num_turns: int = 0
    total_duration_ms: int = 0


class RedisThreadStore:
    def __init__(self, *, redis_url: str) -> None:
        self._redis = redis_lib.from_url(redis_url)

    async def save_auth_token(self, *, auth_token: str, slack_user_id: str) -> None:
        await self._redis.set(
            f"cc4slack:auth:{auth_token}", slack_user_id, ex=AUTH_TTL_SECONDS
        )

    async def lookup_auth_token(self, *, auth_token: str) -> str | None:
        val = await self._redis.get(f"cc4slack:auth:{auth_token}")
        if val is None:
            return None
        return val.decode() if isinstance(val, bytes) else val

    async def revoke_auth_token(self, *, auth_token: str) -> None:
        await self._redis.delete(f"cc4slack:auth:{auth_token}")

    async def save_thread_state(
        self, *, slack_user_id: str, thread_key: str, state: ThreadState
    ) -> None:
        key = f"cc4slack:threads:{slack_user_id}"
        await self._redis.hset(key, thread_key, json.dumps(asdict(state)))
        await self._redis.expire(key, THREAD_TTL_SECONDS)

    async def load_thread_state(
        self, *, slack_user_id: str, thread_key: str
    ) -> ThreadState | None:
        raw = await self._redis.hget(
            f"cc4slack:threads:{slack_user_id}", thread_key
        )
        if raw is None:
            return None
        raw_str = raw.decode() if isinstance(raw, bytes) else raw
        return ThreadState(**json.loads(raw_str))

    async def delete_thread_state(
        self, *, slack_user_id: str, thread_key: str
    ) -> None:
        await self._redis.hdel(
            f"cc4slack:threads:{slack_user_id}", thread_key
        )

    async def load_all_thread_states(
        self, *, slack_user_id: str
    ) -> dict[str, ThreadState]:
        raw_map = await self._redis.hgetall(
            f"cc4slack:threads:{slack_user_id}"
        )
        result: dict[str, ThreadState] = {}
        for tk, raw in raw_map.items():
            tk_str = tk.decode() if isinstance(tk, bytes) else tk
            raw_str = raw.decode() if isinstance(raw, bytes) else raw
            result[tk_str] = ThreadState(**json.loads(raw_str))
        return result
