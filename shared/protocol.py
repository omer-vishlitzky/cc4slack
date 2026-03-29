import json
from typing import Literal, TypedDict


class RegisterMessage(TypedDict):
    type: Literal["register"]
    token: str


class ResponseChunkMessage(TypedDict):
    type: Literal["response_chunk"]
    thread_key: str
    text: str


class ResponseDoneMessage(TypedDict):
    type: Literal["response_done"]
    thread_key: str
    session_id: str
    cost: float
    turns: int
    duration_ms: int


class ResponseErrorMessage(TypedDict):
    type: Literal["response_error"]
    thread_key: str
    error: str


class HeartbeatMessage(TypedDict):
    type: Literal["heartbeat"]


class ReconnectMessage(TypedDict):
    type: Literal["reconnect"]
    auth_token: str
    user_id: str


class VerifiedMessage(TypedDict):
    type: Literal["verified"]
    token: str
    slack_user_id: str
    auth_token: str


class EventMessage(TypedDict):
    type: Literal["event"]
    thread_key: str
    user_id: str
    text: str
    channel: str
    thread_ts: str


class CancelMessage(TypedDict):
    type: Literal["cancel"]
    thread_key: str


class ConfigUpdateMessage(TypedDict):
    type: Literal["config_update"]
    thread_key: str
    cwd: str
    permission_mode: str
    model: str


AgentToRouter = (
    RegisterMessage
    | ReconnectMessage
    | ResponseChunkMessage
    | ResponseDoneMessage
    | ResponseErrorMessage
    | HeartbeatMessage
)

RouterToAgent = VerifiedMessage | EventMessage | CancelMessage | ConfigUpdateMessage

AGENT_MESSAGE_TYPES = {
    "register",
    "reconnect",
    "response_chunk",
    "response_done",
    "response_error",
    "heartbeat",
}
ROUTER_MESSAGE_TYPES = {"verified", "event", "cancel", "config_update"}


def parse_agent_message(*, raw: str) -> AgentToRouter:
    data = json.loads(raw)
    msg_type = data["type"]
    if msg_type not in AGENT_MESSAGE_TYPES:
        raise ValueError(f"Unknown agent message type: {msg_type}")
    return data


def parse_router_message(*, raw: str) -> RouterToAgent:
    data = json.loads(raw)
    msg_type = data["type"]
    if msg_type not in ROUTER_MESSAGE_TYPES:
        raise ValueError(f"Unknown router message type: {msg_type}")
    return data


def serialize(*, message: AgentToRouter | RouterToAgent) -> str:
    return json.dumps(message)
