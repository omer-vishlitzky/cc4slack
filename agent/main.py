import asyncio
import logging
import secrets

from dotenv import load_dotenv

from .claude_runner import ClaudeRunner
from .config import AgentSettings
from .session_file import load_session, save_session
from .ws_client import AgentWebSocket

logger = logging.getLogger(__name__)


async def run_agent() -> None:
    load_dotenv()
    settings = AgentSettings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    runner = ClaudeRunner(settings=settings)
    thread_configs: dict[str, dict[str, str]] = {}
    last_auth_token = ""
    last_owner = ""

    while True:
        ws = AgentWebSocket(url=settings.router_url)

        try:
            await ws.connect()

            last_owner, last_auth_token = await _authenticate(
                ws=ws,
                settings=settings,
                runner=runner,
                thread_configs=thread_configs,
            )

            logger.info(f"Authenticated as {last_owner}")
            print(f"Connected as {last_owner}. Listening for messages...")

            ws.start_heartbeat(interval_seconds=30)
            await _event_loop(
                ws=ws,
                runner=runner,
                owner=last_owner,
                settings=settings,
                thread_configs=thread_configs,
                auth_token=last_auth_token,
            )

        except (ConnectionError, OSError) as e:
            logger.warning(f"Connection lost: {e}")
        except Exception:
            logger.exception("Agent error")
        finally:
            runner.cancel_all()
            await ws.close()

        _save_state(
            auth_token=last_auth_token,
            owner=last_owner,
            settings=settings,
            runner=runner,
            thread_configs=thread_configs,
        )

        logger.info(f"Reconnecting in {settings.reconnect_delay_seconds}s...")
        await asyncio.sleep(settings.reconnect_delay_seconds)


async def _authenticate(
    *,
    ws: AgentWebSocket,
    settings: AgentSettings,
    runner: ClaudeRunner,
    thread_configs: dict[str, dict[str, str]],
) -> tuple[str, str]:
    saved = load_session()
    if saved and saved["auth_token"] and saved["router_url"] == settings.router_url:
        auth_token = str(saved["auth_token"])
        await ws.send(message={"type": "reconnect", "auth_token": auth_token})

        verified_msg = await asyncio.wait_for(ws.receive(), timeout=5.0)
        if verified_msg["type"] == "verified":
            owner = verified_msg["slack_user_id"]
            for tk, sid in saved["claude_sessions"].items():
                runner.set_session(thread_key=str(tk), session_id=str(sid))
            for tk, cfg in saved["thread_configs"].items():
                thread_configs[str(tk)] = {str(k): str(v) for k, v in cfg.items()}
            print("Reconnected using saved session.")
            return owner, auth_token

    token = secrets.token_urlsafe(24)
    await ws.send(message={"type": "register", "token": token})

    print(f"\n{'=' * 50}")
    print(f"  Verification code: {token}")
    print(f"  Type in Slack: @assisted-bot verify {token}")
    print(f"{'=' * 50}\n")

    verified_msg = await ws.receive()
    assert verified_msg["type"] == "verified"
    assert verified_msg["token"] == token

    owner = verified_msg["slack_user_id"]
    auth_token = verified_msg["auth_token"]

    save_session(
        auth_token=auth_token,
        owner_user_id=owner,
        router_url=settings.router_url,
        claude_sessions={},
        thread_configs={},
    )

    return owner, auth_token


async def _event_loop(
    *,
    ws: AgentWebSocket,
    runner: ClaudeRunner,
    owner: str,
    settings: AgentSettings,
    thread_configs: dict[str, dict[str, str]],
    auth_token: str,
) -> None:
    while True:
        msg = await ws.receive()
        msg_type = msg["type"]

        if msg_type == "event":
            thread_key = msg["thread_key"]
            if thread_key in thread_configs:
                tc = thread_configs[thread_key]
                cwd = tc["cwd"]
                mode = tc["permission_mode"]
                model = tc["model"]
            else:
                cwd = settings.working_directory
                mode = settings.permission_mode
                model = settings.claude_model

            if msg["user_id"] != owner:
                await ws.send(
                    message={
                        "type": "response_error",
                        "thread_key": thread_key,
                        "error": "Unauthorized: event user does not match agent owner",
                    }
                )
                continue

            await runner.run(
                thread_key=thread_key,
                text=msg["text"],
                ws=ws,
                cwd=cwd,
                permission_mode=mode,
                model=model,
            )

        elif msg_type == "cancel":
            runner.cancel(thread_key=msg["thread_key"])

        elif msg_type == "config_update":
            thread_key = msg["thread_key"]
            thread_configs[thread_key] = {
                "cwd": msg["cwd"],
                "permission_mode": msg["permission_mode"],
                "model": msg["model"],
            }
            cwd_val = msg["cwd"]
            mode_val = msg["permission_mode"]
            logger.info(f"Config updated for {thread_key}: cwd={cwd_val} mode={mode_val}")

            _save_state(
                auth_token=auth_token,
                owner=owner,
                settings=settings,
                runner=runner,
                thread_configs=thread_configs,
            )


def _save_state(
    *,
    auth_token: str,
    owner: str,
    settings: AgentSettings,
    runner: ClaudeRunner,
    thread_configs: dict[str, dict[str, str]],
) -> None:
    if not auth_token:
        return
    save_session(
        auth_token=auth_token,
        owner_user_id=owner,
        router_url=settings.router_url,
        claude_sessions=runner.get_all_sessions(),
        thread_configs=thread_configs,
    )


def main() -> None:
    import sys

    load_dotenv()
    try:
        AgentSettings()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            "\nRequired environment variables:\n"
            "  ROUTER_URL=wss://assisted-bot.apps.ext.spoke.prod.us-east-1.aws.paas.redhat.com/ws/agent\n"
            "\nOptional:\n"
            "  WORKING_DIRECTORY=/path/to/project\n"
            "  PERMISSION_MODE=default|bypass|allowEdits|plan\n"
            "  CLAUDE_MODEL=claude-sonnet-4-6 (default: uses CLI default)\n"
            "  ANTHROPIC_API_KEY=sk-ant-...\n",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\nAgent stopped.")


if __name__ == "__main__":
    main()
