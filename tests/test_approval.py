"""Tests for command risk classification and BashTool approval integration."""

from __future__ import annotations

import pytest
from langchain_core.tools import ToolException

from kescode.core.approval import (
    ApprovalDecision,
    ApprovalRequest,
    classify_command_risk,
    normalize_approval_mode,
)
from kescode.core.state import RuntimeState
from kescode.tools.bash_tool import BashTool


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        ("pip install requests", "Python package installation"),
        ("python -m pip install requests", "Python package installation"),
        ("python3.13 -m pip install requests", "Python package installation"),
        ("echo ok && pip install requests", "Python package installation"),
        ("ls; pip install requests", "Python package installation"),
        ("uv add pytest", "Project dependency change with uv add"),
        ("uv sync", "Dependency synchronization with uv sync"),
        ("uv pip install pytest", "Python package installation with uv pip"),
        ("npm install lodash", "Node package installation"),
        ("pnpm install lodash", "Node package installation"),
        ("yarn add lodash", "Node package installation"),
        ("yarn install", "Node package installation"),
        ("curl -O https://example.com/file", "Network download command"),
        ("wget https://example.com/file", "Network download command"),
        ("uvicorn app.main:app", "Long-running development server"),
        ("python -m uvicorn app.main:app", "Long-running development server"),
        ("python -m http.server 8000", "Long-running development server"),
        ("cd src && uv sync", "Dependency synchronization with uv sync"),
    ],
)
def test_classify_command_risk_known_commands(
    command: str,
    reason: str,
) -> None:
    assert classify_command_risk(command) == reason


@pytest.mark.parametrize(
    "command",
    [
        "",
        "echo hello",
        "git status",
        "ls -la",
        "uv run pytest",
        "yarn run build",
        "python -m py_compile run.py",
        "npm run test",
    ],
)
def test_classify_command_risk_safe_commands(command: str) -> None:
    assert classify_command_risk(command) is None


def test_approval_request_uses_default_tool_name() -> None:
    request = ApprovalRequest(
        id="approval-12345678",
        command="pip install requests",
        risk_reason="Python package installation",
    )
    assert request.tool_name == "BashTool"


def test_approval_decision_defaults_reason_to_empty() -> None:
    assert ApprovalDecision(approved=False).reason == ""


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, "inline"),
        ("inline", "inline"),
        ("auto", "auto"),
        ("deny", "deny"),
        ("ask", "inline"),
        ("", "inline"),
    ],
)
def test_normalize_approval_mode(mode: str | None, expected: str) -> None:
    assert normalize_approval_mode(mode) == expected


def _make_tool(
    tmp_path,
    *,
    approval_mode: str | None = None,
    approval_handler=None,
) -> BashTool:
    return BashTool(
        RuntimeState(workspace=tmp_path),
        approval_mode=approval_mode,
        approval_handler=approval_handler,
    )


def _fake_execute_result(command: str) -> dict:
    return {
        "command": command,
        "ok": True,
        "exit_code": 0,
        "stdout": "ok",
        "stderr": "",
        "approved": True,
        "requires_approval": False,
    }


def test_deny_mode_rejects_without_execution(monkeypatch, tmp_path) -> None:
    tool = _make_tool(tmp_path, approval_mode="deny")

    def fail_execute(*_args, **_kwargs):
        raise AssertionError("denied command must not execute")

    monkeypatch.setattr(tool, "_execute", fail_execute)
    result = tool.run_bash("pip install requests")

    assert result["ok"] is False
    assert result["approved"] is False
    assert "Python package installation" in result["reason"]


def test_auto_mode_marks_requires_approval(monkeypatch, tmp_path) -> None:
    tool = _make_tool(tmp_path, approval_mode="auto")
    monkeypatch.setattr(
        tool,
        "_execute",
        lambda command, timeout: _fake_execute_result(command),
    )

    result = tool.run_bash("pip install requests")

    assert result["ok"] is True
    assert result["approved"] is True
    assert result["requires_approval"] is True


def test_inline_mode_approved_executes(monkeypatch, tmp_path) -> None:
    tool = _make_tool(tmp_path, approval_mode="inline")
    seen_requests = []

    def handler(request):
        seen_requests.append(request)
        return ApprovalDecision(approved=True, reason="allowed")

    monkeypatch.setattr(
        tool,
        "_execute",
        lambda command, timeout: _fake_execute_result(command),
    )
    result = tool.run_bash("npm install lodash", approval_handler=handler)

    assert result["ok"] is True
    assert result["requires_approval"] is False
    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request.id.startswith("approval-")
    assert request.command == "npm install lodash"
    assert request.risk_reason == "Node package installation"
    assert request.tool_name == "BashTool"


def test_inline_mode_rejected_returns_failure(monkeypatch, tmp_path) -> None:
    tool = _make_tool(tmp_path, approval_mode="inline")

    def fail_execute(*_args, **_kwargs):
        raise AssertionError("rejected command must not execute")

    monkeypatch.setattr(tool, "_execute", fail_execute)
    result = tool.run_bash(
        "curl -O https://example.com/file",
        approval_handler=lambda request: ApprovalDecision(
            approved=False,
            reason="not now",
        ),
    )

    assert result["ok"] is False
    assert result["approved"] is False
    assert result["reason"] == "not now"


def test_inline_mode_without_handler_raises(tmp_path) -> None:
    tool = _make_tool(tmp_path, approval_mode="inline")

    with pytest.raises(ToolException, match="requires approval"):
        tool.run_bash("pip install requests")


def test_safe_command_skips_approval(monkeypatch, tmp_path) -> None:
    tool = _make_tool(tmp_path, approval_mode="deny")
    executed = []

    def execute(command, timeout):
        executed.append(command)
        return _fake_execute_result(command)

    monkeypatch.setattr(tool, "_execute", execute)
    result = tool.run_bash("echo hello")

    assert result["ok"] is True
    assert executed == ["echo hello"]


def test_run_delegates_to_run_bash(tmp_path) -> None:
    tool = _make_tool(tmp_path, approval_mode="deny")

    result = tool.run("pip install requests")

    assert result["ok"] is False
    assert result["requires_approval"] is True
