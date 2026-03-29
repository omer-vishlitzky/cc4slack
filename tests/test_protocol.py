import json

import pytest

from shared.protocol import (
    parse_agent_message,
    parse_router_message,
    serialize,
)


def test_parse_register_message() -> None:
    raw = json.dumps({"type": "register", "token": "abc123"})
    msg = parse_agent_message(raw=raw)
    assert msg["type"] == "register"
    assert msg["token"] == "abc123"


def test_parse_response_chunk() -> None:
    raw = json.dumps({"type": "response_chunk", "thread_key": "C1:T1", "text": "hello"})
    msg = parse_agent_message(raw=raw)
    assert msg["type"] == "response_chunk"
    assert msg["thread_key"] == "C1:T1"
    assert msg["text"] == "hello"


def test_parse_response_done() -> None:
    raw = json.dumps(
        {
            "type": "response_done",
            "thread_key": "C1:T1",
            "session_id": "sess-1",
            "cost": 0.05,
            "turns": 3,
            "duration_ms": 12000,
        }
    )
    msg = parse_agent_message(raw=raw)
    assert msg["type"] == "response_done"
    assert msg["session_id"] == "sess-1"
    assert msg["cost"] == 0.05


def test_parse_response_error() -> None:
    raw = json.dumps({"type": "response_error", "thread_key": "C1:T1", "error": "boom"})
    msg = parse_agent_message(raw=raw)
    assert msg["type"] == "response_error"
    assert msg["error"] == "boom"


def test_parse_heartbeat() -> None:
    raw = json.dumps({"type": "heartbeat"})
    msg = parse_agent_message(raw=raw)
    assert msg["type"] == "heartbeat"


def test_parse_reconnect_message() -> None:
    raw = json.dumps({"type": "reconnect", "auth_token": "durable-tok", "user_id": "U123"})
    msg = parse_agent_message(raw=raw)
    assert msg["type"] == "reconnect"
    assert msg["auth_token"] == "durable-tok"


def test_parse_verified_message() -> None:
    raw = json.dumps(
        {
            "type": "verified",
            "token": "tok",
            "slack_user_id": "U123",
            "auth_token": "durable-abc",
        }
    )
    msg = parse_router_message(raw=raw)
    assert msg["type"] == "verified"
    assert msg["token"] == "tok"
    assert msg["slack_user_id"] == "U123"
    assert msg["auth_token"] == "durable-abc"


def test_reconnect_roundtrip() -> None:
    msg = {"type": "reconnect", "auth_token": "durable-tok", "user_id": "U123"}
    raw = serialize(message=msg)
    parsed = parse_agent_message(raw=raw)
    assert parsed == msg


def test_parse_event_message() -> None:
    raw = json.dumps(
        {
            "type": "event",
            "thread_key": "C1:T1",
            "user_id": "U123",
            "text": "help me",
            "channel": "C1",
            "thread_ts": "T1",
        }
    )
    msg = parse_router_message(raw=raw)
    assert msg["type"] == "event"
    assert msg["text"] == "help me"


def test_parse_cancel_message() -> None:
    raw = json.dumps({"type": "cancel", "thread_key": "C1:T1"})
    msg = parse_router_message(raw=raw)
    assert msg["type"] == "cancel"


def test_parse_config_update_message() -> None:
    raw = json.dumps(
        {
            "type": "config_update",
            "thread_key": "C1:T1",
            "cwd": "/home/user",
            "permission_mode": "bypass",
        }
    )
    msg = parse_router_message(raw=raw)
    assert msg["type"] == "config_update"
    assert msg["cwd"] == "/home/user"


def test_parse_unknown_agent_type_raises() -> None:
    raw = json.dumps({"type": "banana"})
    with pytest.raises(ValueError, match="Unknown agent message type"):
        parse_agent_message(raw=raw)


def test_parse_unknown_router_type_raises() -> None:
    raw = json.dumps({"type": "banana"})
    with pytest.raises(ValueError, match="Unknown router message type"):
        parse_router_message(raw=raw)


def test_parse_invalid_json_raises() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_agent_message(raw="not json")


def test_parse_missing_type_raises() -> None:
    raw = json.dumps({"token": "abc"})
    with pytest.raises(KeyError):
        parse_agent_message(raw=raw)


def test_serialize_roundtrip() -> None:
    msg = {"type": "register", "token": "abc123"}
    raw = serialize(message=msg)
    parsed = parse_agent_message(raw=raw)
    assert parsed == msg


def test_serialize_event_roundtrip() -> None:
    msg = {
        "type": "event",
        "thread_key": "C1:T1",
        "user_id": "U123",
        "text": "hello",
        "channel": "C1",
        "thread_ts": "T1",
    }
    raw = serialize(message=msg)
    parsed = parse_router_message(raw=raw)
    assert parsed == msg
