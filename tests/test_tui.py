"""Tests for the Textual TUI approval gate and event rendering."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from textual.widgets import Input, RichLog

from kescode.cli.tui.app import KesCodeTuiApp, _one_line
from kescode.cli.tui.approval import ApprovalGate
from kescode.core.approval import ApprovalRequest


def _request(**overrides: str) -> ApprovalRequest:
    values = {
        "id": "approval-test",
        "command": "pip install requests",
        "risk_reason": "Python package installation",
        "tool_name": "BashTool",
    }
    values.update(overrides)
    return ApprovalRequest(**values)


def test_approval_gate_notifies_and_resolves() -> None:
    seen: list[tuple[ApprovalRequest, ApprovalGate]] = []

    def notifier(request: ApprovalRequest, gate: ApprovalGate) -> None:
        seen.append((request, gate))
        threading.Thread(target=gate.resolve, args=(True,), daemon=True).start()

    gate = ApprovalGate(notifier=notifier)
    decision = gate(_request())

    assert decision.approved is True
    assert len(seen) == 1
    assert seen[0][0].command == "pip install requests"


def test_approval_gate_times_out_with_denial() -> None:
    gate = ApprovalGate()
    gate.request = _request()

    decision = gate.wait(timeout=0)

    assert decision.approved is False
    assert decision.reason == "Approval timed out."


def test_one_line_collapses_whitespace_and_truncates() -> None:
    assert _one_line("a\n\n  b", 20) == "a b"
    assert _one_line("abcdefghij", 7) == "abcd..."


def test_tool_call_text_formats_common_arguments(tmp_path: Path) -> None:
    app = KesCodeTuiApp(
        tmp_path,
        approval_mode="deny",
        checkpoint_mode="off",
        trace_mode="off",
    )

    file_text = app._tool_call_text(
        {"type": "tool_call", "name": "file_write", "args": {"file_path": "app.py"}}
    )
    assert file_text == "🔧 FileWriteTool → app.py"

    search_text = app._tool_call_text(
        {"type": "tool_call", "name": "web_search", "args": {"query": "flask tutorial"}}
    )
    assert search_text == '🔍 WebSearchTool: "flask tutorial"'

    command_text = app._tool_call_text(
        {"type": "tool_call", "name": "bash", "args": {"command": "uv run pytest"}}
    )
    assert command_text == "🔧 BashTool: uv run pytest"


def test_tui_logs_plan_and_dedupes_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = KesCodeTuiApp(
        tmp_path,
        approval_mode="deny",
        checkpoint_mode="off",
        trace_mode="off",
    )
    log_text: list[str] = []

    class FakeRichLog:
        def write(self, text: str) -> None:
            log_text.append(text)

    monkeypatch.setattr(
        app,
        "query_one",
        lambda selector, _widget_type: FakeRichLog(),
    )

    app._handle_event(
        {
            "type": "custom_event",
            "event": {
                "type": "plan_snapshot",
                "plan_summary": "Build demo",
                "todos": [
                    {
                        "id": "todo-1",
                        "status": "in_progress",
                        "content": "create app",
                    }
                ],
            },
        }
    )
    app._handle_event(
        {
            "type": "custom_event",
            "event": {
                "type": "plan_snapshot",
                "plan_summary": "Build demo",
                "todos": [],
            },
        }
    )
    app._handle_event(
        {
            "type": "graph_event",
            "event": {
                "intent_router": {
                    "intent_route": "workflow",
                    "intent_reason": "coding task",
                }
            },
        }
    )
    app._handle_event(
        {
            "type": "intent_route",
            "route": "workflow",
            "reason": "coding task",
        }
    )
    app._handle_event(
        {
            "type": "custom_event",
            "event": {
                "type": "tool_call",
                "name": "file_write",
                "args": {"file_path": "app.py"},
            },
        }
    )
    app._handle_event(
        {
            "type": "custom_event",
            "event": {
                "type": "tool_call",
                "name": "file_write",
                "args": {"file_path": "app.py"},
            },
        }
    )
    app._handle_event(
        {
            "type": "custom_event",
            "event": {
                "type": "tool_result",
                "name": "file_write",
                "result": {"ok": True, "summary": "ok"},
            },
        }
    )
    app._handle_event(
        {
            "type": "custom_event",
            "event": {
                "type": "tool_result",
                "name": "file_write",
                "result": {"ok": True, "summary": "ok"},
            },
        }
    )

    assert sum("Build demo" in line for line in log_text) == 1
    assert sum("🧭 Intent: workflow" in line for line in log_text) == 1
    assert sum("FileWriteTool → app.py" in line for line in log_text) == 1
    assert sum("FileWriteTool: ok" in line for line in log_text) == 1


def test_tui_input_is_focused_and_accepts_keys(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = KesCodeTuiApp(
            tmp_path,
            approval_mode="deny",
            checkpoint_mode="off",
            trace_mode="off",
        )
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)

            assert app.focused is prompt
            await pilot.press("h", "i")
            assert prompt.value == "hi"

    asyncio.run(scenario())


def test_tui_submit_renders_streamed_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_stream(task, **kwargs):
        return iter(
            [
                {
                    "type": "session_event",
                    "event": {"type": "user_turn", "turn": 1, "content": task},
                },
                {"type": "intent_route", "route": "workflow", "reason": "test"},
                {"type": "final_answer", "content": "done"},
            ]
        )

    monkeypatch.setattr(
        "kescode.cli.tui.app.stream_session_events",
        fake_stream,
    )

    async def scenario() -> None:
        app = KesCodeTuiApp(
            tmp_path,
            approval_mode="deny",
            checkpoint_mode="off",
            trace_mode="off",
        )
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            await pilot.press("h", "e", "l", "l", "o")
            await pilot.press("enter")

            log = app.query_one("#event-log", RichLog)
            for _ in range(50):
                if any("done" in line.text for line in log.lines):
                    break
                await asyncio.sleep(0.05)

            texts = [line.text for line in log.lines]
            assert any("hello" in text for text in texts)
            assert any("done" in text for text in texts)
            assert prompt.disabled is False

    asyncio.run(scenario())


def test_tui_dedupes_repeated_chat_reply(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reply = "你好，我是 KesCode"

    def fake_stream(task, **kwargs):
        return iter(
            [
                {
                    "type": "graph_event",
                    "event": {
                        "chat_responder": {
                            "final_answer": reply,
                            "chat_response": reply,
                        }
                    },
                },
                {"type": "final_answer", "content": reply},
                {
                    "type": "session_event",
                    "event": {
                        "type": "assistant_turn",
                        "turn": 1,
                        "route": "chat",
                        "content": reply,
                    },
                },
            ]
        )

    monkeypatch.setattr(
        "kescode.cli.tui.app.stream_session_events",
        fake_stream,
    )

    async def scenario() -> None:
        app = KesCodeTuiApp(
            tmp_path,
            approval_mode="deny",
            checkpoint_mode="off",
            trace_mode="off",
        )
        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "你好"
            await pilot.press("enter")

            log = app.query_one("#event-log", RichLog)
            for _ in range(50):
                if not prompt.disabled:
                    break
                await asyncio.sleep(0.05)

            texts = [line.text for line in log.lines]
            replies = [text for text in texts if reply in text]
            assert len(replies) == 1

    asyncio.run(scenario())
