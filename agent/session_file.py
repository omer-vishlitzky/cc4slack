import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SESSION_DIR = Path.home() / ".config" / "cc4slack"
SESSION_PATH = SESSION_DIR / "session.json"


def load_session() -> dict[str, Any] | None:
    if not SESSION_PATH.exists():
        return None
    raw = SESSION_PATH.read_text()
    return json.loads(raw)


def save_session(
    *,
    auth_token: str,
    owner_user_id: str,
    router_url: str,
    claude_sessions: dict[str, str],
    thread_configs: dict[str, dict[str, str]],
) -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "auth_token": auth_token,
        "owner_user_id": owner_user_id,
        "router_url": router_url,
        "claude_sessions": claude_sessions,
        "thread_configs": thread_configs,
    }
    SESSION_PATH.write_text(json.dumps(data, indent=2))
    logger.info(f"Session saved to {SESSION_PATH}")


def clear_session() -> None:
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()
        logger.info(f"Session cleared: {SESSION_PATH}")
