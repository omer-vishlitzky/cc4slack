from claude_code_sdk.types import AssistantMessage, SystemMessage

from agent.claude_runner import _build_options, _format_tool_use, _parse_message_safe


def test_build_options_default_mode() -> None:
    options = _build_options(
        cwd="/home/user",
        permission_mode="default",
        max_turns=50,
        model="claude-sonnet-4-20250514",
        session_id=None,
    )
    assert options.cwd == "/home/user"
    assert options.max_turns == 50
    assert options.permission_mode == "default"


def test_build_options_bypass_mode() -> None:
    options = _build_options(
        cwd=".",
        permission_mode="bypass",
        max_turns=50,
        model="claude-sonnet-4-20250514",
        session_id=None,
    )
    assert options.permission_mode == "bypassPermissions"


def test_build_options_allow_edits_mode() -> None:
    options = _build_options(
        cwd=".",
        permission_mode="allowEdits",
        max_turns=50,
        model="claude-sonnet-4-20250514",
        session_id=None,
    )
    assert options.permission_mode == "bypassPermissions"
    assert options.disallowed_tools == ["Bash"]


def test_build_options_plan_mode() -> None:
    options = _build_options(
        cwd=".",
        permission_mode="plan",
        max_turns=50,
        model="claude-sonnet-4-20250514",
        session_id=None,
    )
    assert options.disallowed_tools == ["Bash", "Write", "Edit", "NotebookEdit"]


def test_build_options_with_resume() -> None:
    options = _build_options(
        cwd=".",
        permission_mode="default",
        max_turns=50,
        model="claude-sonnet-4-20250514",
        session_id="sess-123",
    )
    assert options.resume == "sess-123"


def test_build_options_with_model() -> None:
    options = _build_options(
        cwd=".",
        permission_mode="default",
        max_turns=50,
        model="claude-opus-4-6",
        session_id=None,
    )
    assert options.model == "claude-opus-4-6"


def test_format_tool_use_bash_with_desc() -> None:
    result = _format_tool_use(
        tool_name="Bash", tool_input={"command": "ls -la", "description": "List files"}
    )
    assert "List files" in result
    assert "ls -la" in result


def test_format_tool_use_bash_no_desc() -> None:
    result = _format_tool_use(tool_name="Bash", tool_input={"command": "git status"})
    assert "git status" in result
    assert ":terminal:" in result


def test_format_tool_use_read() -> None:
    result = _format_tool_use(tool_name="Read", tool_input={"file_path": "/tmp/test.py"})
    assert "/tmp/test.py" in result
    assert ":mag:" in result


def test_format_tool_use_write() -> None:
    result = _format_tool_use(tool_name="Write", tool_input={"file_path": "/tmp/out.py"})
    assert "/tmp/out.py" in result


def test_format_tool_use_web_fetch_full_url() -> None:
    long_url = "https://example.com/" + "a" * 100
    result = _format_tool_use(tool_name="WebFetch", tool_input={"url": long_url})
    assert long_url in result


def test_format_tool_use_agent() -> None:
    result = _format_tool_use(tool_name="Agent", tool_input={"description": "research"})
    assert "research" in result
    assert ":robot_face:" in result


def test_format_tool_use_unknown() -> None:
    result = _format_tool_use(tool_name="CustomTool", tool_input={})
    assert "CustomTool" in result
    assert ":wrench:" in result


def test_format_tool_use_missing_key_does_not_crash() -> None:
    result = _format_tool_use(tool_name="Read", tool_input={})
    assert "?" in result
    assert ":mag:" in result


def test_format_tool_use_partial_keys() -> None:
    result = _format_tool_use(tool_name="Glob", tool_input={"other_field": "value"})
    assert "?" in result


def test_parse_message_safe_handles_rate_limit_event() -> None:
    data = {"type": "rate_limit_event", "retry_after_ms": 5000}
    result = _parse_message_safe(data)
    assert isinstance(result, SystemMessage)
    assert result.subtype == "rate_limit_event"
    assert result.data == data


def test_parse_message_safe_handles_unknown_type() -> None:
    data = {"type": "some_future_type", "payload": "whatever"}
    result = _parse_message_safe(data)
    assert isinstance(result, SystemMessage)
    assert result.subtype == "some_future_type"


def test_parse_message_safe_passes_known_types() -> None:
    data = {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": "hello"}],
            "model": "claude-sonnet-4-6",
        },
    }
    result = _parse_message_safe(data)
    assert isinstance(result, AssistantMessage)
