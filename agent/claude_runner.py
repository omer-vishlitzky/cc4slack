import asyncio
import logging
from collections import defaultdict
from typing import Any

import claude_code_sdk._internal.client as _sdk_client
from claude_code_sdk import query
from claude_code_sdk._errors import MessageParseError
from claude_code_sdk._internal.message_parser import parse_message as _original_parse
from claude_code_sdk.types import (
    AssistantMessage,
    ClaudeCodeOptions,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolUseBlock,
)

from .config import AgentSettings
from .ws_client import AgentWebSocket

logger = logging.getLogger(__name__)


# SDK 0.0.25 crashes on unrecognized message types (e.g. rate_limit_event)
# instead of skipping them. Patch to return a harmless SystemMessage so the
# async-for iteration survives transient informational messages from the CLI.
def _parse_message_safe(data: dict[str, Any]) -> AssistantMessage | ResultMessage | SystemMessage:
    try:
        return _original_parse(data)
    except MessageParseError:
        msg_type = data.get("type", "unknown")
        logger.info(f"Skipping unrecognized SDK message type: {msg_type}")
        return SystemMessage(subtype=msg_type, data=data)


_sdk_client.parse_message = _parse_message_safe


class ClaudeRunner:
    def __init__(self, *, settings: AgentSettings) -> None:
        self._settings = settings
        self._sessions: dict[str, str] = {}
        self._active_tasks: dict[str, asyncio.Task[None]] = {}

    def get_session_id(self, *, thread_key: str) -> str | None:
        return self._sessions.get(thread_key)

    def get_all_sessions(self) -> dict[str, str]:
        return dict(self._sessions)

    def set_session(self, *, thread_key: str, session_id: str) -> None:
        self._sessions[thread_key] = session_id

    async def run(
        self,
        *,
        thread_key: str,
        text: str,
        ws: AgentWebSocket,
        cwd: str,
        permission_mode: str,
        model: str,
    ) -> None:
        if thread_key in self._active_tasks and not self._active_tasks[thread_key].done():
            logger.warning(
                f"Rejected {thread_key}: active task exists. "
                f"Active tasks: {list(self._active_tasks.keys())}"
            )
            await ws.send(
                message={
                    "type": "response_error",
                    "thread_key": thread_key,
                    "error": "Still processing previous request in this thread. Please wait.",
                }
            )
            return

        active = list(self._active_tasks.keys())
        logger.info(f"Starting Claude for {thread_key}. Active tasks: {active}")

        task = asyncio.create_task(
            self._run_query(
                thread_key=thread_key,
                text=text,
                ws=ws,
                cwd=cwd,
                permission_mode=permission_mode,
                model=model,
            )
        )
        self._active_tasks[thread_key] = task

    def cancel(self, *, thread_key: str) -> None:
        task = self._active_tasks.get(thread_key)
        if task and not task.done():
            task.cancel()
            logger.info(f"Cancelled task for {thread_key}")

    def cancel_all(self) -> None:
        for tk, task in list(self._active_tasks.items()):
            if not task.done():
                task.cancel()
                logger.info(f"Cancelled task for {tk} (disconnect)")
        self._active_tasks.clear()

    async def _run_query(
        self,
        *,
        thread_key: str,
        text: str,
        ws: AgentWebSocket,
        cwd: str,
        permission_mode: str,
        model: str,
    ) -> None:
        options = _build_options(
            cwd=cwd,
            permission_mode=permission_mode,
            max_turns=self._settings.claude_max_turns,
            model=model,
            session_id=self._sessions.get(thread_key),
        )

        try:
            async for message in query(prompt=text, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            await ws.send(
                                message={
                                    "type": "response_chunk",
                                    "thread_key": thread_key,
                                    "text": block.text,
                                }
                            )
                        elif isinstance(block, ToolUseBlock):
                            tool_display = _format_tool_use(
                                tool_name=block.name,
                                tool_input=block.input,
                            )
                            await ws.send(
                                message={
                                    "type": "response_chunk",
                                    "thread_key": thread_key,
                                    "text": f"\n\n{tool_display}\n",
                                }
                            )

                elif isinstance(message, ResultMessage):
                    session_id = message.session_id or ""
                    if session_id:
                        self._sessions[thread_key] = session_id

                    await ws.send(
                        message={
                            "type": "response_done",
                            "thread_key": thread_key,
                            "session_id": session_id,
                            "cost": message.total_cost_usd or 0.0,
                            "turns": message.num_turns or 0,
                            "duration_ms": message.duration_ms or 0,
                        }
                    )

        except asyncio.CancelledError:
            await ws.send(
                message={
                    "type": "response_chunk",
                    "thread_key": thread_key,
                    "text": "\n\n:stop_sign: _Operation cancelled_",
                }
            )
            await ws.send(
                message={
                    "type": "response_done",
                    "thread_key": thread_key,
                    "session_id": self._sessions.get(thread_key, ""),
                    "cost": 0.0,
                    "turns": 0,
                    "duration_ms": 0,
                }
            )
        except Exception as e:
            logger.exception(f"Claude error for {thread_key}")
            await ws.send(
                message={
                    "type": "response_error",
                    "thread_key": thread_key,
                    "error": str(e),
                }
            )
        finally:
            self._active_tasks.pop(thread_key, None)


def _build_options(
    *,
    cwd: str,
    permission_mode: str,
    max_turns: int,
    model: str,
    session_id: str | None,
) -> ClaudeCodeOptions:
    options = ClaudeCodeOptions(cwd=cwd, max_turns=max_turns)

    options.permission_mode = "bypassPermissions"
    if permission_mode == "allowEdits":
        options.disallowed_tools = ["Bash"]
    elif permission_mode == "plan":
        options.disallowed_tools = ["Bash", "Write", "Edit", "NotebookEdit"]
    elif permission_mode == "default":
        options.permission_mode = "default"

    if model:
        options.model = model
    if session_id:
        options.resume = session_id

    return options


TOOL_FORMATTERS: dict[str, str] = {
    "Read": ":mag: *Reading* `{file_path}`",
    "Write": ":pencil2: *Writing* `{file_path}`",
    "Edit": ":pencil: *Editing* `{file_path}`",
    "Glob": ":file_folder: *Searching for* `{pattern}`",
    "Grep": ":mag_right: *Searching for* `{pattern}`",
    "WebSearch": ":globe_with_meridians: *Searching web:* {query}",
}


def _format_tool_use(*, tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        desc = tool_input.get("description", "")
        if desc:
            return f":terminal: *Running:* {desc}\n```{command}```"
        return f":terminal: *Running:*\n```{command}```"

    if tool_name == "WebFetch":
        url = tool_input.get("url", "")
        return f":link: *Fetching* `{url}`"

    if tool_name == "Agent":
        desc = tool_input.get("description", "subtask")
        return f":robot_face: *Spawning agent:* {desc}"

    template = TOOL_FORMATTERS.get(tool_name)
    if template:
        safe_input = defaultdict(lambda: "?", tool_input)
        return template.format_map(safe_input)

    return f":wrench: *Using tool:* `{tool_name}`"
