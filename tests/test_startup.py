import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_SIGNING_SECRET", "test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


def test_router_starts_and_healthz_works() -> None:
    from router.main import app

    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_router_websocket_accepts_connection() -> None:
    from router.main import app

    client = TestClient(app)
    with client.websocket_connect("/ws/agent") as ws:
        ws.send_text(json.dumps({"type": "register", "token": "test-token-123"}))


def test_router_rejects_unverified_slack_event() -> None:
    from router.main import app

    client = TestClient(app)
    response = client.post(
        "/slack/events",
        content=json.dumps(
            {"type": "event_callback", "event": {"type": "app_mention"}}
        ),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


def test_agent_fails_without_router_url() -> None:
    env = {k: v for k, v in os.environ.items() if k != "ROUTER_URL"}
    result = subprocess.run(
        [sys.executable, "-m", "agent.main"],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 1
    assert "ROUTER_URL" in result.stderr


def test_agent_settings_valid_with_router_url() -> None:
    os.environ["ROUTER_URL"] = "ws://localhost:9999/ws/agent"
    from agent.config import AgentSettings

    settings = AgentSettings(_env_file=None)
    assert settings.router_url == "ws://localhost:9999/ws/agent"
    assert settings.claude_model == ""
    assert settings.permission_mode == "default"


def test_uvicorn_has_websocket_support() -> None:
    import websockets

    assert websockets is not None


def test_router_fails_without_required_config() -> None:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "REDIS_URL")
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from router.config import RouterSettings; RouterSettings()",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )
    assert result.returncode == 1
