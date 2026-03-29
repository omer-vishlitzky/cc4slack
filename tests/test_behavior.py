import json
from unittest.mock import AsyncMock, patch

import pytest

from router.slack_handler import (
    _build_prompt_with_thread_context,
    clean_mention,
    extract_full_text,
    handle_slack_event,
)


def make_slack_event(
    *,
    event_type: str,
    text: str = "hello",
    user: str = "U111",
    channel: str = "C111",
    ts: str = "1000.0",
    thread_ts: str = "",
    channel_type: str = "",
    bot_id: str = "",
    subtype: str = "",
) -> dict[str, str | dict[str, str]]:
    event: dict[str, str] = {
        "type": event_type,
        "text": text,
        "user": user,
        "channel": channel,
        "ts": ts,
    }
    if thread_ts:
        event["thread_ts"] = thread_ts
    if channel_type:
        event["channel_type"] = channel_type
    if bot_id:
        event["bot_id"] = bot_id
    if subtype:
        event["subtype"] = subtype
    return {"type": "event_callback", "event": event}


def make_request(
    *,
    data: dict[str, str | dict[str, str]],
) -> AsyncMock:
    request = AsyncMock()
    body = json.dumps(data).encode()
    request.body = AsyncMock(return_value=body)
    request.headers = {"X-Slack-Signature": "valid", "X-Slack-Request-Timestamp": "1234"}
    return request


def make_deps() -> tuple[AsyncMock, AsyncMock, dict[str, object]]:
    ws_manager = AsyncMock()
    ws_manager.get_connection = lambda *, slack_user_id: None
    ws_manager.get_thread_state = lambda *, slack_user_id, thread_key: None
    slack_client = AsyncMock()
    slack_client.chat_postMessage = AsyncMock(return_value={"ts": "M1"})
    slack_client.reactions_add = AsyncMock()
    updaters: dict[str, object] = {}
    return ws_manager, slack_client, updaters



@pytest.mark.asyncio
@patch("router.slack_handler.SignatureVerifier")
async def test_app_mention_is_processed(mock_verifier: AsyncMock) -> None:
    mock_verifier.return_value.is_valid_request.return_value = True
    ws_manager, slack_client, updaters = make_deps()

    data = make_slack_event(event_type="app_mention", text="<@BOT> hello")
    request = make_request(data=data)

    response = await handle_slack_event(
        request=request,
        signing_secret="test",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("router.slack_handler.SignatureVerifier")
async def test_im_message_is_processed(mock_verifier: AsyncMock) -> None:
    mock_verifier.return_value.is_valid_request.return_value = True
    ws_manager, slack_client, updaters = make_deps()

    data = make_slack_event(event_type="message", channel_type="im")
    request = make_request(data=data)

    response = await handle_slack_event(
        request=request,
        signing_secret="test",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("router.slack_handler.SignatureVerifier")
async def test_mpim_message_is_ignored(mock_verifier: AsyncMock) -> None:
    mock_verifier.return_value.is_valid_request.return_value = True
    ws_manager, slack_client, updaters = make_deps()

    data = make_slack_event(event_type="message", channel_type="mpim", text="just chatting")
    request = make_request(data=data)

    response = await handle_slack_event(
        request=request,
        signing_secret="test",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )
    assert response.status_code == 200
    slack_client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
@patch("router.slack_handler.SignatureVerifier")
async def test_bot_message_in_dm_is_ignored(mock_verifier: AsyncMock) -> None:
    mock_verifier.return_value.is_valid_request.return_value = True
    ws_manager, slack_client, updaters = make_deps()

    data = make_slack_event(event_type="message", channel_type="im", bot_id="B123")
    request = make_request(data=data)

    response = await handle_slack_event(
        request=request,
        signing_secret="test",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )
    assert response.status_code == 200
    slack_client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
@patch("router.slack_handler.SignatureVerifier")
async def test_message_edit_in_dm_is_ignored(mock_verifier: AsyncMock) -> None:
    mock_verifier.return_value.is_valid_request.return_value = True
    ws_manager, slack_client, updaters = make_deps()

    data = make_slack_event(event_type="message", channel_type="im", subtype="message_changed")
    request = make_request(data=data)

    response = await handle_slack_event(
        request=request,
        signing_secret="test",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )
    assert response.status_code == 200
    slack_client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
@patch("router.slack_handler.SignatureVerifier")
async def test_slack_retry_is_ignored(mock_verifier: AsyncMock) -> None:
    ws_manager, slack_client, updaters = make_deps()

    data = make_slack_event(event_type="app_mention", text="<@BOT> hello")
    request = make_request(data=data)
    request.headers = {
        "X-Slack-Signature": "valid",
        "X-Slack-Request-Timestamp": "1234",
        "X-Slack-Retry-Num": "1",
    }

    response = await handle_slack_event(
        request=request,
        signing_secret="test",
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )
    assert response.status_code == 200
    mock_verifier.assert_not_called()



def test_clean_mention_removes_bot_id() -> None:
    assert clean_mention(text="<@U123ABC> hello world") == "hello world"


def test_clean_mention_multiple() -> None:
    assert clean_mention(text="<@U123ABC> <@U456DEF> hello") == "hello"


def test_clean_mention_no_mention() -> None:
    assert clean_mention(text="hello world") == "hello world"


def test_clean_mention_only_mention() -> None:
    assert clean_mention(text="<@U123ABC>") == ""



def test_extract_full_text_plain_message() -> None:
    event = {"text": "hello world"}
    assert extract_full_text(event=event) == "hello world"


def test_extract_full_text_no_text() -> None:
    event = {"text": ""}
    assert extract_full_text(event=event) == ""


def test_extract_full_text_with_attachment() -> None:
    event = {
        "text": "pls help",
        "attachments": [{"text": "forwarded content here", "title": "Help Desk"}],
    }
    result = extract_full_text(event=event)
    assert "pls help" in result
    assert "forwarded content here" in result
    assert "Help Desk" in result
    assert "[Forwarded message]" in result


def test_extract_full_text_attachment_only_fallback() -> None:
    event = {
        "text": "check this",
        "attachments": [{"fallback": "fallback text only"}],
    }
    result = extract_full_text(event=event)
    assert "check this" in result
    assert "fallback text only" in result


def test_extract_full_text_no_text_with_attachment() -> None:
    event = {
        "text": "",
        "attachments": [{"text": "just the attachment"}],
    }
    result = extract_full_text(event=event)
    assert result == "just the attachment"



@pytest.mark.asyncio
async def test_thread_context_top_level_message_no_fetch() -> None:
    slack_client = AsyncMock()
    result = await _build_prompt_with_thread_context(
        text="hello",
        channel="C1",
        thread_ts="1000.0",
        current_ts="1000.0",
        last_processed_ts="",
        slack_client=slack_client,
    )
    assert result == "hello"
    slack_client.conversations_replies.assert_not_called()


@pytest.mark.asyncio
async def test_thread_context_first_mention_fetches_full_thread() -> None:
    slack_client = AsyncMock()
    slack_client.conversations_replies = AsyncMock(
        return_value={
            "messages": [
                {"ts": "1000.0", "user": "U111", "text": "hey let's discuss"},
                {"ts": "1001.0", "user": "U222", "text": "sure, what about k8s?"},
            ]
        }
    )

    result = await _build_prompt_with_thread_context(
        text="what do you think?",
        channel="C1",
        thread_ts="1000.0",
        current_ts="1002.0",
        last_processed_ts="",
        slack_client=slack_client,
    )

    assert "[Thread context from Slack thread]" in result
    assert "hey let's discuss" in result
    assert "what about k8s?" in result
    assert "[Your message]" in result
    assert "what do you think?" in result
    slack_client.conversations_replies.assert_called_once()
    call_kwargs = slack_client.conversations_replies.call_args.kwargs
    assert call_kwargs["inclusive"] is True


@pytest.mark.asyncio
async def test_thread_context_second_mention_fetches_delta() -> None:
    slack_client = AsyncMock()
    slack_client.conversations_replies = AsyncMock(
        return_value={
            "messages": [
                {"ts": "1003.0", "user": "U222", "text": "also consider scaling"},
            ]
        }
    )

    result = await _build_prompt_with_thread_context(
        text="answer that",
        channel="C1",
        thread_ts="1000.0",
        current_ts="1004.0",
        last_processed_ts="1002.0",
        slack_client=slack_client,
    )

    assert "[New messages from Slack thread]" in result
    assert "also consider scaling" in result
    assert "answer that" in result

    call_kwargs = slack_client.conversations_replies.call_args.kwargs
    assert call_kwargs["oldest"] == "1002.0"
    assert call_kwargs["latest"] == "1004.0"
    assert call_kwargs["inclusive"] is False


@pytest.mark.asyncio
async def test_thread_context_excludes_bot_messages() -> None:
    slack_client = AsyncMock()
    slack_client.conversations_replies = AsyncMock(
        return_value={
            "messages": [
                {"ts": "1000.0", "user": "U111", "text": "question"},
                {"ts": "1001.0", "bot_id": "B123", "text": "bot response"},
                {"ts": "1002.0", "user": "U222", "text": "follow up"},
            ]
        }
    )

    result = await _build_prompt_with_thread_context(
        text="summarize",
        channel="C1",
        thread_ts="1000.0",
        current_ts="1003.0",
        last_processed_ts="",
        slack_client=slack_client,
    )

    assert "question" in result
    assert "follow up" in result
    assert "bot response" not in result


@pytest.mark.asyncio
async def test_thread_context_excludes_current_message() -> None:
    slack_client = AsyncMock()
    slack_client.conversations_replies = AsyncMock(
        return_value={
            "messages": [
                {"ts": "1000.0", "user": "U111", "text": "question"},
                {"ts": "1001.0", "user": "U111", "text": "my @mention message"},
            ]
        }
    )

    result = await _build_prompt_with_thread_context(
        text="my mention message",
        channel="C1",
        thread_ts="1000.0",
        current_ts="1001.0",
        last_processed_ts="",
        slack_client=slack_client,
    )

    assert "question" in result
    assert result.count("my mention message") == 1


@pytest.mark.asyncio
async def test_thread_context_no_messages_returns_text_only() -> None:
    slack_client = AsyncMock()
    slack_client.conversations_replies = AsyncMock(
        return_value={"messages": []}
    )

    result = await _build_prompt_with_thread_context(
        text="hello",
        channel="C1",
        thread_ts="1000.0",
        current_ts="1001.0",
        last_processed_ts="",
        slack_client=slack_client,
    )

    assert result == "hello"
