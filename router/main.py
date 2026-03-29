import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from slack_sdk.web.async_client import AsyncWebClient

from shared.protocol import parse_agent_message

from .config import RouterSettings
from .message_updater import SlackMessageUpdater
from .slack_handler import handle_slack_action, handle_slack_event
from .thread_store import RedisThreadStore
from .ws_manager import WebSocketManager

logger = logging.getLogger(__name__)

settings = RouterSettings()
slack_client = AsyncWebClient(token=settings.slack_bot_token)
thread_store = RedisThreadStore(redis_url=settings.redis_url)
ws_manager = WebSocketManager(
    token_expiry_seconds=settings.token_expiry_seconds,
    thread_store=thread_store,
)
updaters: dict[str, SlackMessageUpdater] = {}


async def cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await ws_manager.cleanup_expired_tokens()
        except Exception:
            logger.exception("cleanup_expired_tokens failed, will retry next cycle")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("cc4slack router starting")
    cleanup_task = asyncio.create_task(cleanup_loop())
    yield
    cleanup_task.cancel()
    logger.info("cc4slack router stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/slack/events")
async def slack_events(request: Request) -> Response:
    return await handle_slack_event(
        request=request,
        signing_secret=settings.slack_signing_secret,
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )


@app.post("/slack/actions")
async def slack_actions(request: Request) -> Response:
    return await handle_slack_action(
        request=request,
        signing_secret=settings.slack_signing_secret,
        ws_manager=ws_manager,
        slack_client=slack_client,
        updaters=updaters,
    )


@app.websocket("/ws/agent")
async def ws_agent(ws: WebSocket) -> None:
    await ws.accept()
    logger.info("Agent WebSocket connected")

    try:
        while True:
            raw = await ws.receive_text()
            msg = parse_agent_message(raw=raw)
            msg_type = msg["type"]

            if msg_type == "register":
                await ws_manager.register_pending(ws=ws, token=msg["token"])

            elif msg_type == "reconnect":
                success = await ws_manager.reconnect_agent(
                    ws=ws, auth_token=msg["auth_token"], user_id=msg["user_id"]
                )
                if not success:
                    await ws.close(code=4001, reason="Invalid auth token")
                    return

            elif msg_type == "heartbeat":
                pass

            elif msg_type == "response_chunk":
                thread_key = msg["thread_key"]
                updater = updaters.get(thread_key)
                if updater:
                    await updater.append(text=msg["text"])

            elif msg_type == "response_done":
                thread_key = msg["thread_key"]
                user_id = ws_manager.find_user_by_ws(ws=ws)
                if user_id:
                    state = ws_manager.get_thread_state(
                        slack_user_id=user_id, thread_key=thread_key
                    )
                    if state:
                        state.session_id = msg["session_id"]
                        state.total_cost_usd += msg["cost"]
                        state.num_turns += msg["turns"]
                        state.total_duration_ms += msg["duration_ms"]
                        ws_manager.set_thread_state(
                            slack_user_id=user_id,
                            thread_key=thread_key,
                            state=state,
                        )

                updater = updaters.get(thread_key)
                if updater:
                    await updater.finalize(session_id=msg["session_id"])
                    updaters.pop(thread_key, None)

                await _remove_eyes_reaction(thread_key=thread_key, success=True)

            elif msg_type == "response_error":
                thread_key = msg["thread_key"]
                updater = updaters.get(thread_key)
                if updater:
                    await updater.show_error(error=msg["error"])
                    updaters.pop(thread_key, None)

                await _remove_eyes_reaction(thread_key=thread_key, success=False)

    except WebSocketDisconnect:
        logger.info("Agent WebSocket disconnected")
    except Exception:
        logger.exception("Agent WebSocket error")
    finally:
        await _cleanup_updaters_for_agent(ws=ws)
        await ws_manager.handle_agent_disconnect(ws=ws)


async def _cleanup_updaters_for_agent(*, ws: WebSocket) -> None:
    user_id = ws_manager.find_user_by_ws(ws=ws)
    if not user_id:
        return
    conn = ws_manager.get_connection(slack_user_id=user_id)
    if not conn:
        return
    for thread_key in list(conn.threads.keys()):
        updater = updaters.pop(thread_key, None)
        if updater:
            await updater.show_error(error="Agent disconnected")
            logger.info(f"Cleaned up stuck updater for {thread_key}")


async def _remove_eyes_reaction(*, thread_key: str, success: bool) -> None:
    parts = thread_key.split(":", 1)
    if len(parts) != 2:
        return
    channel, thread_ts = parts
    try:
        await slack_client.reactions_remove(channel=channel, name="eyes", timestamp=thread_ts)
    except Exception:
        pass
    try:
        reaction = "white_check_mark" if success else "x"
        await slack_client.reactions_add(channel=channel, name=reaction, timestamp=thread_ts)
    except Exception:
        pass
