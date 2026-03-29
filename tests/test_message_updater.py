from unittest.mock import AsyncMock

import pytest

from router.message_updater import SlackMessageUpdater, _split_into_chunks


def make_updater() -> tuple[SlackMessageUpdater, AsyncMock]:
    client = AsyncMock()
    client.chat_update = AsyncMock()
    client.chat_postMessage = AsyncMock(return_value={"ts": "M2"})
    updater = SlackMessageUpdater(
        client=client,
        channel="C1",
        message_ts="M1",
        thread_ts="T1",
    )
    return updater, client


def test_split_short_text() -> None:
    chunks = _split_into_chunks(text="hello world")
    assert chunks == ["hello world"]


def test_split_long_text() -> None:
    text = "a" * 6000
    chunks = _split_into_chunks(text=text)
    assert len(chunks) >= 2
    assert "".join(chunks) == text
    for chunk in chunks:
        assert len(chunk) <= 2900


def test_split_prefers_newline_break() -> None:
    line = "x" * 1500
    text = f"{line}\n{line}\n{line}"
    chunks = _split_into_chunks(text=text)
    assert len(chunks) >= 2
    assert chunks[0].endswith("\n") or len(chunks[0]) <= 2900


@pytest.mark.asyncio
async def test_append_accumulates() -> None:
    updater, client = make_updater()
    updater._last_update = float("inf")
    await updater.append(text="hello ")
    await updater.append(text="world")
    assert updater._buffer == "hello world"


@pytest.mark.asyncio
async def test_finalize_single_message() -> None:
    updater, client = make_updater()
    updater._buffer = "short response"
    await updater.finalize(session_id="sess-1")

    client.chat_update.assert_called_once()
    call_kwargs = client.chat_update.call_args.kwargs
    assert call_kwargs["text"] == "short response"
    assert call_kwargs["ts"] == "M1"


@pytest.mark.asyncio
async def test_finalize_empty_buffer() -> None:
    updater, client = make_updater()
    await updater.finalize(session_id="sess-1")

    client.chat_update.assert_called_once()
    assert client.chat_update.call_args.kwargs["text"] == "_No response_"


@pytest.mark.asyncio
async def test_finalize_long_splits() -> None:
    updater, client = make_updater()
    updater._buffer = "x" * 6000
    await updater.finalize(session_id="sess-1")

    assert client.chat_update.call_count == 1
    assert client.chat_postMessage.call_count >= 1


@pytest.mark.asyncio
async def test_show_error() -> None:
    updater, client = make_updater()
    await updater.show_error(error="something broke")

    client.chat_update.assert_called_once()
    call_kwargs = client.chat_update.call_args.kwargs
    assert "something broke" in call_kwargs["text"]
    assert updater._finalized is True
