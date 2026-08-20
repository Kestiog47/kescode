"""Tests for the Textual TUI approval gate and event rendering."""

from __future__ import annotations

import threading
from pathlib import Path

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


def test_tui_renders_plan_snapshot_and_event_log(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = KesCodeTuiApp(
        tmp_path,
        approval_mode="deny",
        checkpoint_mode="off",
        trace_mode="off",
    )
    plan_text: list[str] = []
    log_text: list[str] = []

    class FakeStatic:
        def update(self, text: str) -> None:
            plan_text.append(text)

    class FakeRichLog:
        def write(self, text: str) -> None:
            log_text.append(text)

    monkeypatch.setattr(
        app,
        "query_one",
        lambda selector, _widget_type: (
            FakeStatic() if selector == "#plan-panel" else FakeRichLog()
        ),
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
                "type": "tool_call",
                "name": "file_write",
                "args": {"file_path": "app.py"},
            },
        }
    )

    assert "Build demo" in plan_text[0]
    assert "todo-1" in plan_text[0]
    assert "create app" in plan_text[0]
    assert "🔄" in plan_text[0]
    assert any("FileWriteTool → app.py" in line for line in log_text)
