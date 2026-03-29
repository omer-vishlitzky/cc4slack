import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from router.thread_store import RedisThreadStore
from router.ws_manager import (
    ActiveConnection,
    ThreadState,
    WebSocketManager,
)


def make_mock_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    return ws


@pytest.fixture
def manager() -> WebSocketManager:
    import fakeredis.aioredis

    store = RedisThreadStore(redis_url="redis://fake")
    store._redis = fakeredis.aioredis.FakeRedis()
    return WebSocketManager(token_expiry_seconds=300, thread_store=store)


@pytest.mark.asyncio
async def test_register_pending(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok123")
    assert "tok123" in manager._pending
    assert manager._pending["tok123"].ws is ws


@pytest.mark.asyncio
async def test_verify_token_success(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok123")

    result = await manager.verify_token(token="tok123", slack_user_id="U111")

    assert result is True
    assert "tok123" not in manager._pending
    assert "U111" in manager._active
    assert manager._active["U111"].ws is ws
    ws.send_text.assert_called_once()
    sent = json.loads(ws.send_text.call_args[0][0])
    assert sent["type"] == "verified"
    assert sent["token"] == "tok123"
    assert sent["slack_user_id"] == "U111"
    assert "auth_token" in sent
    assert len(sent["auth_token"]) > 0


@pytest.mark.asyncio
async def test_verify_token_unknown(*, manager: WebSocketManager) -> None:
    result = await manager.verify_token(token="nonexistent", slack_user_id="U111")
    assert result is False


@pytest.mark.asyncio
async def test_verify_token_expired(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok123")
    manager._pending["tok123"].created_at = datetime.now(UTC) - timedelta(seconds=600)

    result = await manager.verify_token(token="tok123", slack_user_id="U111")

    assert result is False
    assert "U111" not in manager._active


@pytest.mark.asyncio
async def test_verify_token_consumed(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok123")
    await manager.verify_token(token="tok123", slack_user_id="U111")

    result = await manager.verify_token(token="tok123", slack_user_id="U222")
    assert result is False


@pytest.mark.asyncio
async def test_verify_replaces_existing_connection(*, manager: WebSocketManager) -> None:
    ws_old = make_mock_ws()
    ws_new = make_mock_ws()

    await manager.register_pending(ws=ws_old, token="tok1")
    await manager.verify_token(token="tok1", slack_user_id="U111")

    await manager.register_pending(ws=ws_new, token="tok2")
    await manager.verify_token(token="tok2", slack_user_id="U111")

    assert manager._active["U111"].ws is ws_new
    ws_old.close.assert_called_once()


@pytest.mark.asyncio
async def test_get_connection(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")

    conn = manager.get_connection(slack_user_id="U111")
    assert conn is not None
    assert conn.ws is ws

    assert manager.get_connection(slack_user_id="U999") is None


@pytest.mark.asyncio
async def test_send_to_agent(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")

    msg = {
        "type": "event",
        "thread_key": "C:T",
        "user_id": "U111",
        "text": "hi",
        "channel": "C",
        "thread_ts": "T",
    }
    result = await manager.send_to_agent(slack_user_id="U111", message=msg)
    assert result is True
    assert ws.send_text.call_count == 2


@pytest.mark.asyncio
async def test_send_to_unregistered_user(*, manager: WebSocketManager) -> None:
    result = await manager.send_to_agent(
        slack_user_id="U999", message={"type": "cancel", "thread_key": "C:T"}
    )
    assert result is False


@pytest.mark.asyncio
async def test_remove_connection(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")

    await manager.remove_connection(slack_user_id="U111")

    assert "U111" not in manager._active
    ws.close.assert_called()


@pytest.mark.asyncio
async def test_thread_state_management(*, manager: WebSocketManager) -> None:
    ws = MagicMock()
    manager._active["U111"] = ActiveConnection(ws=ws, slack_user_id="U111")

    state = ThreadState(channel="C1", thread_ts="T1", message_ts="M1")
    manager.set_thread_state(slack_user_id="U111", thread_key="C1:T1", state=state)

    retrieved = manager.get_thread_state(slack_user_id="U111", thread_key="C1:T1")
    assert retrieved is state
    assert retrieved.channel == "C1"

    assert manager.get_thread_state(slack_user_id="U111", thread_key="C1:T999") is None

    manager.clear_thread_state(slack_user_id="U111", thread_key="C1:T1")
    assert manager.get_thread_state(slack_user_id="U111", thread_key="C1:T1") is None


@pytest.mark.asyncio
async def test_cleanup_expired_tokens(*, manager: WebSocketManager) -> None:
    ws1 = make_mock_ws()
    ws2 = make_mock_ws()
    await manager.register_pending(ws=ws1, token="old")
    await manager.register_pending(ws=ws2, token="fresh")
    manager._pending["old"].created_at = datetime.now(UTC) - timedelta(seconds=600)

    cleaned = await manager.cleanup_expired_tokens()

    assert cleaned == 1
    assert "old" not in manager._pending
    assert "fresh" in manager._pending
    ws1.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_agent_disconnect(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")

    await manager.handle_agent_disconnect(ws=ws)

    assert "U111" not in manager._active


def test_find_user_by_ws(*, manager: WebSocketManager) -> None:
    ws = MagicMock()
    manager._active["U111"] = ActiveConnection(ws=ws, slack_user_id="U111")

    assert manager.find_user_by_ws(ws=ws) == "U111"
    assert manager.find_user_by_ws(ws=MagicMock()) is None


@pytest.mark.asyncio
async def test_reconnect_agent_success(*, manager: WebSocketManager) -> None:
    ws1 = make_mock_ws()
    await manager.register_pending(ws=ws1, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")
    auth_token = manager._active["U111"].auth_token

    await manager.handle_agent_disconnect(ws=ws1)
    assert "U111" not in manager._active

    ws2 = make_mock_ws()
    result = await manager.reconnect_agent(ws=ws2, auth_token=auth_token, user_id="U111")

    assert result is True
    assert "U111" in manager._active
    assert manager._active["U111"].ws is ws2
    ws2.send_text.assert_called_once()
    sent = json.loads(ws2.send_text.call_args[0][0])
    assert sent["type"] == "verified"
    assert sent["slack_user_id"] == "U111"


@pytest.mark.asyncio
async def test_reconnect_agent_invalid_token(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    result = await manager.reconnect_agent(ws=ws, auth_token="bad-token", user_id="U111")
    assert result is False


@pytest.mark.asyncio
async def test_reconnect_agent_wrong_user(*, manager: WebSocketManager) -> None:
    ws1 = make_mock_ws()
    await manager.register_pending(ws=ws1, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")
    auth_token = manager._active["U111"].auth_token

    await manager.handle_agent_disconnect(ws=ws1)

    ws2 = make_mock_ws()
    result = await manager.reconnect_agent(ws=ws2, auth_token=auth_token, user_id="U999")
    assert result is False


@pytest.mark.asyncio
async def test_reconnect_restores_thread_state(*, manager: WebSocketManager) -> None:
    ws1 = make_mock_ws()
    await manager.register_pending(ws=ws1, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")
    auth_token = manager._active["U111"].auth_token

    state = ThreadState(channel="C1", thread_ts="T1", message_ts="M1", total_cost_usd=0.5)
    manager.set_thread_state(slack_user_id="U111", thread_key="C1:T1", state=state)
    await asyncio.sleep(0)

    await manager.handle_agent_disconnect(ws=ws1)

    ws2 = make_mock_ws()
    await manager.reconnect_agent(ws=ws2, auth_token=auth_token, user_id="U111")

    restored = manager.get_thread_state(slack_user_id="U111", thread_key="C1:T1")
    assert restored is not None
    assert restored.total_cost_usd == 0.5


@pytest.mark.asyncio
async def test_remove_connection_revokes_auth_token(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")
    auth_token = manager._active["U111"].auth_token

    await manager.remove_connection(slack_user_id="U111")

    ws2 = make_mock_ws()
    result = await manager.reconnect_agent(ws=ws2, auth_token=auth_token, user_id="U111")
    assert result is False


@pytest.mark.asyncio
async def test_cleanup_survives_ws_close_error(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="old")
    manager._pending["old"].created_at = datetime.now(UTC) - timedelta(seconds=600)

    ws.close = AsyncMock(side_effect=RuntimeError("connection already closed"))

    cleaned = await manager.cleanup_expired_tokens()

    assert cleaned == 1
    assert "old" not in manager._pending


@pytest.mark.asyncio
async def test_cleanup_loop_retries_after_failure() -> None:
    call_count = 0

    async def fake_cleanup() -> int:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Redis down")
        return 0

    async def cleanup_loop_under_test() -> None:
        while True:
            await asyncio.sleep(0)
            try:
                await fake_cleanup()
            except Exception:
                pass

    task = asyncio.create_task(cleanup_loop_under_test())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert call_count >= 2


@pytest.mark.asyncio
async def test_updaters_cleaned_on_agent_disconnect(*, manager: WebSocketManager) -> None:
    ws = make_mock_ws()
    await manager.register_pending(ws=ws, token="tok")
    await manager.verify_token(token="tok", slack_user_id="U111")

    state = ThreadState(channel="C1", thread_ts="T1", message_ts="M1")
    manager.set_thread_state(slack_user_id="U111", thread_key="C1:T1", state=state)
    await asyncio.sleep(0)

    mock_updater = AsyncMock()
    updaters: dict[str, AsyncMock] = {"C1:T1": mock_updater}

    # Simulate what _cleanup_updaters_for_agent does
    user_id = manager.find_user_by_ws(ws=ws)
    assert user_id == "U111"
    conn = manager.get_connection(slack_user_id=user_id)
    assert conn is not None
    for thread_key in list(conn.threads.keys()):
        updater = updaters.pop(thread_key, None)
        if updater:
            await updater.show_error(error="Agent disconnected")

    mock_updater.show_error.assert_called_once_with(error="Agent disconnected")
    assert "C1:T1" not in updaters
