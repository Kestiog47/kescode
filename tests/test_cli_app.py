"""Tests for the kescode CLI argument wiring."""

from __future__ import annotations

import sys
from pathlib import Path

from typer.testing import CliRunner

from kescode.cli import app as cli_app

runner = CliRunner()


def test_main_forwards_options(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    def fake_stream(
        task,
        *,
        workspace,
        max_attempts,
        approval_mode,
        checkpoint_mode,
        trace_mode,
        resume_workspace,
    ):
        captured.update(
            {
                "task": task,
                "workspace": workspace,
                "max_attempts": max_attempts,
                "approval_mode": approval_mode,
                "checkpoint_mode": checkpoint_mode,
                "trace_mode": trace_mode,
                "resume_workspace": resume_workspace,
            }
        )
        return iter([])

    monkeypatch.setattr(cli_app, "stream_agent_events", fake_stream)

    result = runner.invoke(
        cli_app.app,
        [
            "hello task",
            "--workspace",
            str(tmp_path),
            "--max-attempts",
            "2",
            "--approval-mode",
            "deny",
            "--checkpoint-mode",
            "strict",
            "--trace-mode",
            "off",
        ],
    )

    assert result.exit_code == 0
    assert captured["task"] == "hello task"
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["max_attempts"] == 2
    assert captured["approval_mode"] == "deny"
    assert captured["checkpoint_mode"] == "strict"
    assert captured["trace_mode"] == "off"
    assert captured["resume_workspace"] is None


def test_main_resume_does_not_require_task(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    def fake_stream(
        task,
        *,
        workspace,
        max_attempts,
        approval_mode,
        checkpoint_mode,
        trace_mode,
        resume_workspace,
    ):
        captured.update(
            {
                "task": task,
                "workspace": workspace,
                "resume_workspace": resume_workspace,
            }
        )
        return iter([])

    monkeypatch.setattr(cli_app, "stream_agent_events", fake_stream)

    result = runner.invoke(
        cli_app.app,
        ["--resume", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert captured["task"] == ""
    assert captured["resume_workspace"] == tmp_path


def test_main_requires_task_without_resume(tmp_path) -> None:
    result = runner.invoke(
        cli_app.app,
        ["--workspace", str(tmp_path)],
    )

    assert result.exit_code != 0
    assert "task is required" in result.output


def test_main_rejects_invalid_literal_options(tmp_path) -> None:
    result = runner.invoke(
        cli_app.app,
        [
            "hello task",
            "--workspace",
            str(tmp_path),
            "--approval-mode",
            "bogus",
        ],
    )

    assert result.exit_code != 0


def test_tui_command_launches_app(monkeypatch, tmp_path) -> None:
    captured: dict = {}

    class FakeTui:
        def __init__(
            self,
            workspace,
            *,
            session_workspace=None,
            max_attempts=3,
            approval_mode="inline",
            checkpoint_mode="light",
            trace_mode="on",
            model=None,
        ) -> None:
            captured.update(
                {
                    "workspace": workspace,
                    "session_workspace": session_workspace,
                    "max_attempts": max_attempts,
                    "approval_mode": approval_mode,
                    "checkpoint_mode": checkpoint_mode,
                    "trace_mode": trace_mode,
                    "model": model,
                }
            )

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(cli_app, "KesCodeTuiApp", FakeTui)

    result = runner.invoke(
        cli_app.tui_app,
        [
            "--workspace",
            str(tmp_path),
            "--session-workspace",
            str(tmp_path),
            "--max-attempts",
            "2",
            "--approval-mode",
            "deny",
            "--checkpoint-mode",
            "strict",
            "--trace-mode",
            "off",
            "--model",
            "test-model",
        ],
    )

    assert result.exit_code == 0
    assert captured["ran"] is True
    assert Path(captured["workspace"]) == tmp_path
    assert Path(captured["session_workspace"]) == tmp_path
    assert captured["max_attempts"] == 2
    assert captured["approval_mode"] == "deny"
    assert captured["checkpoint_mode"] == "strict"
    assert captured["trace_mode"] == "off"
    assert captured["model"] == "test-model"


def test_help_lists_tui_command() -> None:
    result = runner.invoke(cli_app.tui_app, ["--help"])

    assert result.exit_code == 0
    assert "tui" in result.output


def test_main_without_args_launches_tui(monkeypatch) -> None:
    captured: dict = {}

    class FakeTui:
        def __init__(self, workspace, **kwargs) -> None:
            captured["workspace"] = workspace

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(cli_app, "KesCodeTuiApp", FakeTui)
    monkeypatch.setattr(sys, "argv", ["kescode"])

    try:
        cli_app.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured["ran"] is True


def test_main_tui_subcommand_launches_tui(monkeypatch) -> None:
    captured: dict = {}

    class FakeTui:
        def __init__(self, workspace, **kwargs) -> None:
            captured["model"] = kwargs.get("model")

        def run(self) -> None:
            captured["ran"] = True

    monkeypatch.setattr(cli_app, "KesCodeTuiApp", FakeTui)
    monkeypatch.setattr(sys, "argv", ["kescode", "tui", "--model", "test-model"])

    try:
        cli_app.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured["ran"] is True
    assert captured["model"] == "test-model"
