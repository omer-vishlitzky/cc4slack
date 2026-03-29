from unittest.mock import AsyncMock

import pytest

from router.commands import (
    handle_cwd,
    handle_help,
    handle_mode,
    handle_model,
    handle_unregister,
    handle_verify,
    try_parse_command,
)
from router.slack_handler import _dispatch
from router.thread_store import RedisThreadStore
from router.ws_manager import WebSocketManager


def make_ws_manager() -> WebSocketManager:
    import fakeredis.aioredis

    store = RedisThreadStore(redis_url="redis://fake")
    store._redis = fakeredis.aioredis.FakeRedis()
    return WebSocketManager(token_expiry_seconds=300, thread_store=store)


def test_parse_help() -> None:
    result = try_parse_command(text="help")
    assert result is not None
    assert result[0] == "help"


def test_parse_help_case_insensitive() -> None:
    result = try_parse_command(text="HELP")
    assert result is not None
    assert result[0] == "help"


def test_parse_verify() -> None:
    result = try_parse_command(text="verify abc123xyz")
    assert result is not None
    assert result[0] == "verify"
    assert result[1].group(1) == "abc123xyz"


def test_parse_mode_no_arg() -> None:
    result = try_parse_command(text="mode")
    assert result is not None
    assert result[0] == "mode"
    assert result[1].group(1) is None


def test_parse_mode_with_arg() -> None:
    result = try_parse_command(text="mode bypass")
    assert result is not None
    assert result[0] == "mode"
    assert result[1].group(1) == "bypass"


def test_parse_cwd_no_arg() -> None:
    result = try_parse_command(text="cwd")
    assert result is not None
    assert result[0] == "cwd"


def test_parse_cwd_with_path() -> None:
    result = try_parse_command(text="cwd /home/user/project")
    assert result is not None
    assert result[0] == "cwd"
    assert result[1].group(1) == "/home/user/project"


def test_parse_unregister() -> None:
    result = try_parse_command(text="unregister")
    assert result is not None
    assert result[0] == "unregister"


def test_parse_status() -> None:
    result = try_parse_command(text="status")
    assert result is not None
    assert result[0] == "status"


def test_parse_regular_text_returns_none() -> None:
    assert try_parse_command(text="help me fix this bug") is None
    assert try_parse_command(text="please verify my code") is None
    assert try_parse_command(text="what is the status of this?") is None


@pytest.mark.asyncio
async def test_handle_help() -> None:
    client = AsyncMock()
    await handle_help(channel="C1", thread_ts="T1", client=client)
    client.chat_postMessage.assert_called_once()
    call_kwargs = client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "C1"
    assert "cc4slack" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_handle_verify_success() -> None:
    client = AsyncMock()
    ws_manager = make_ws_manager()
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    await ws_manager.register_pending(ws=ws, token="tok123")

    await handle_verify(
        token="tok123",
        slack_user_id="U111",
        channel="C1",
        thread_ts="T1",
        client=client,
        ws_manager=ws_manager,
    )

    client.chat_postMessage.assert_called_once()
    call_kwargs = client.chat_postMessage.call_args.kwargs
    assert "connected" in call_kwargs["text"].lower()


@pytest.mark.asyncio
async def test_handle_verify_failure() -> None:
    client = AsyncMock()
    ws_manager = make_ws_manager()

    await handle_verify(
        token="wrong_token",
        slack_user_id="U111",
        channel="C1",
        thread_ts="T1",
        client=client,
        ws_manager=ws_manager,
    )

    client.chat_postMessage.assert_called_once()
    call_kwargs = client.chat_postMessage.call_args.kwargs
    assert "failed" in call_kwargs["text"].lower()


@pytest.mark.asyncio
async def test_handle_unregister_connected() -> None:
    client = AsyncMock()
    ws_manager = make_ws_manager()
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    ws.close = AsyncMock()
    await ws_manager.register_pending(ws=ws, token="tok")
    await ws_manager.verify_token(token="tok", slack_user_id="U111")

    await handle_unregister(
        slack_user_id="U111",
        channel="C1",
        thread_ts="T1",
        client=client,
        ws_manager=ws_manager,
    )

    assert ws_manager.get_connection(slack_user_id="U111") is None
    client.chat_postMessage.assert_called_once()
    assert "disconnected" in client.chat_postMessage.call_args.kwargs["text"].lower()


@pytest.mark.asyncio
async def test_handle_unregister_not_connected() -> None:
    client = AsyncMock()
    ws_manager = make_ws_manager()

    await handle_unregister(
        slack_user_id="U111",
        channel="C1",
        thread_ts="T1",
        client=client,
        ws_manager=ws_manager,
    )

    client.chat_postMessage.assert_called_once()
    assert "no agent" in client.chat_postMessage.call_args.kwargs["text"].lower()


# --- Auth gateway tests ---


@pytest.mark.asyncio
async def test_auth_gateway_blocks_help_without_agent() -> None:
    ws_manager = make_ws_manager()
    slack_client = AsyncMock()
    slack_client.chat_postMessage = AsyncMock(return_value={"ts": "M1"})
    updaters: dict[str, object] = {}

    await _dispatch(
        user_id="U_NO_AGENT",
        channel="C1",
        thread_ts="T1",
        text="help",
        user_message_ts="T1",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )

    call_kwargs = slack_client.chat_postMessage.call_args.kwargs
    assert "no agent connected" in call_kwargs["text"].lower()


@pytest.mark.asyncio
async def test_auth_gateway_blocks_mode_without_agent() -> None:
    ws_manager = make_ws_manager()
    slack_client = AsyncMock()
    slack_client.chat_postMessage = AsyncMock(return_value={"ts": "M1"})

    await _dispatch(
        user_id="U_NO_AGENT",
        channel="C1",
        thread_ts="T1",
        text="mode bypass",
        user_message_ts="T1",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters={},
    )

    call_kwargs = slack_client.chat_postMessage.call_args.kwargs
    assert "no agent connected" in call_kwargs["text"].lower()


@pytest.mark.asyncio
async def test_auth_gateway_blocks_regular_message_without_agent() -> None:
    ws_manager = make_ws_manager()
    slack_client = AsyncMock()
    slack_client.chat_postMessage = AsyncMock(return_value={"ts": "M1"})

    await _dispatch(
        user_id="U_NO_AGENT",
        channel="C1",
        thread_ts="T1",
        text="hello Claude",
        user_message_ts="T1",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters={},
    )

    call_kwargs = slack_client.chat_postMessage.call_args.kwargs
    assert "no agent connected" in call_kwargs["text"].lower()


@pytest.mark.asyncio
async def test_auth_gateway_allows_verify_without_agent() -> None:
    ws_manager = make_ws_manager()
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    await ws_manager.register_pending(ws=ws, token="tok999")

    slack_client = AsyncMock()
    slack_client.chat_postMessage = AsyncMock(return_value={"ts": "M1"})

    await _dispatch(
        user_id="U_NEW",
        channel="C1",
        thread_ts="T1",
        text="verify tok999",
        user_message_ts="T1",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters={},
    )

    call_kwargs = slack_client.chat_postMessage.call_args.kwargs
    assert "connected" in call_kwargs["text"].lower()


# --- Persistence tests ---


@pytest.mark.asyncio
async def test_mode_change_persists_to_store() -> None:
    ws_manager = make_ws_manager()
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    await ws_manager.register_pending(ws=ws, token="tok")
    await ws_manager.verify_token(token="tok", slack_user_id="U111")

    client = AsyncMock()
    await handle_mode(
        mode_arg="bypass",
        channel="C1",
        thread_ts="T1",
        slack_user_id="U111",
        client=client,
        ws_manager=ws_manager,
    )

    import asyncio

    await asyncio.sleep(0)

    loaded = await ws_manager._thread_store.load_thread_state(
        slack_user_id="U111", thread_key="C1:T1"
    )
    assert loaded is not None
    assert loaded.permission_mode == "bypass"


@pytest.mark.asyncio
async def test_cwd_change_persists_to_store() -> None:
    ws_manager = make_ws_manager()
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    await ws_manager.register_pending(ws=ws, token="tok")
    await ws_manager.verify_token(token="tok", slack_user_id="U111")

    client = AsyncMock()
    await handle_cwd(
        path_arg="/home/user/project",
        channel="C1",
        thread_ts="T1",
        slack_user_id="U111",
        client=client,
        ws_manager=ws_manager,
    )

    import asyncio

    await asyncio.sleep(0)

    loaded = await ws_manager._thread_store.load_thread_state(
        slack_user_id="U111", thread_key="C1:T1"
    )
    assert loaded is not None
    assert loaded.cwd == "/home/user/project"


@pytest.mark.asyncio
async def test_model_change_persists_to_store() -> None:
    ws_manager = make_ws_manager()
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    await ws_manager.register_pending(ws=ws, token="tok")
    await ws_manager.verify_token(token="tok", slack_user_id="U111")

    client = AsyncMock()
    await handle_model(
        model_arg="claude-opus-4-6",
        channel="C1",
        thread_ts="T1",
        slack_user_id="U111",
        client=client,
        ws_manager=ws_manager,
    )

    import asyncio

    await asyncio.sleep(0)

    loaded = await ws_manager._thread_store.load_thread_state(
        slack_user_id="U111", thread_key="C1:T1"
    )
    assert loaded is not None
    assert loaded.model == "claude-opus-4-6"


@pytest.mark.asyncio
async def test_mode_creates_state_if_missing() -> None:
    ws_manager = make_ws_manager()
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    await ws_manager.register_pending(ws=ws, token="tok")
    await ws_manager.verify_token(token="tok", slack_user_id="U111")

    assert ws_manager.get_thread_state(slack_user_id="U111", thread_key="C1:T1") is None

    client = AsyncMock()
    await handle_mode(
        mode_arg="plan",
        channel="C1",
        thread_ts="T1",
        slack_user_id="U111",
        client=client,
        ws_manager=ws_manager,
    )

    state = ws_manager.get_thread_state(slack_user_id="U111", thread_key="C1:T1")
    assert state is not None
    assert state.permission_mode == "plan"
