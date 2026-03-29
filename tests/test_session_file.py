from pathlib import Path
from unittest.mock import patch

import pytest

from agent.session_file import clear_session, load_session, save_session


@pytest.fixture
def tmp_session(tmp_path: Path) -> Path:
    session_path = tmp_path / "session.json"
    with patch("agent.session_file.SESSION_PATH", session_path):
        with patch("agent.session_file.SESSION_DIR", tmp_path):
            yield session_path


def test_save_and_load_roundtrip(*, tmp_session: Path) -> None:
    with patch("agent.session_file.SESSION_PATH", tmp_session):
        with patch("agent.session_file.SESSION_DIR", tmp_session.parent):
            save_session(
                auth_token="tok-abc",
                owner_user_id="U123",
                router_url="wss://example.com/ws",
                claude_sessions={"C1:T1": "sess-1"},
                thread_configs={
                    "C1:T1": {"cwd": "/home", "permission_mode": "default", "model": ""}
                },
            )

            loaded = load_session()
            assert loaded is not None
            assert loaded["auth_token"] == "tok-abc"
            assert loaded["owner_user_id"] == "U123"
            assert loaded["router_url"] == "wss://example.com/ws"
            assert loaded["claude_sessions"]["C1:T1"] == "sess-1"
            assert loaded["thread_configs"]["C1:T1"]["cwd"] == "/home"


def test_load_nonexistent_returns_none(*, tmp_session: Path) -> None:
    with patch("agent.session_file.SESSION_PATH", tmp_session):
        result = load_session()
        assert result is None


def test_clear_session_removes_file(*, tmp_session: Path) -> None:
    with patch("agent.session_file.SESSION_PATH", tmp_session):
        with patch("agent.session_file.SESSION_DIR", tmp_session.parent):
            save_session(
                auth_token="tok",
                owner_user_id="U1",
                router_url="wss://x",
                claude_sessions={},
                thread_configs={},
            )
            assert tmp_session.exists()

            clear_session()
            assert not tmp_session.exists()


def test_clear_nonexistent_is_noop(*, tmp_session: Path) -> None:
    with patch("agent.session_file.SESSION_PATH", tmp_session):
        clear_session()
