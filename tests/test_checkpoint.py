"""Tests for checkpoint save/resume and recovery guides."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from kescode.core.checkpoint import (
    CheckpointManager,
    build_recovery_markdown,
    resume_command,
)
from kescode.core.errors import KesCodeError
from kescode.core.state import RuntimeState, normalize_checkpoint_mode


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, "light"),
        ("light", "light"),
        ("strict", "strict"),
        ("off", "off"),
        ("unknown", "light"),
        ("", "light"),
    ],
)
def test_normalize_checkpoint_mode(mode: str | None, expected: str) -> None:
    assert normalize_checkpoint_mode(mode) == expected


def test_runtime_state_normalizes_checkpoint_mode(tmp_path) -> None:
    runtime = RuntimeState(workspace=tmp_path, checkpoint_mode="unknown")
    assert runtime.checkpoint_mode == "light"


def test_resume_command() -> None:
    plain = str(Path("C:/work"))
    spaced = str(Path("C:/my work"))
    assert resume_command(Path("C:/work")) == f"kescode --resume {plain}"
    assert resume_command(Path("C:/my work")) == f'kescode --resume "{spaced}"'


def test_build_recovery_markdown_contains_required_sections() -> None:
    payload = {
        "checkpoint_id": "checkpoint-abc12345",
        "timestamp": "2026-08-20T00:00:00+00:00",
        "mode": "light",
        "status": "running",
        "latest_node": "planner",
        "task": "Implement hello.py",
        "workspace": "C:/work",
        "git_commit": "abc123",
        "workspace_manifest": {
            "file_count": 1,
            "files": [{"path": "notes.txt", "size": 5}],
        },
        "resume_command": "kescode --resume C:/work",
    }

    markdown = build_recovery_markdown(payload)

    assert "## Task" in markdown
    assert "Implement hello.py" in markdown
    assert "## Files" in markdown
    assert "notes.txt" in markdown
    assert "abc123" in markdown
    assert "kescode --resume C:/work" in markdown


def _runtime(tmp_path: Path, mode: str = "light") -> RuntimeState:
    return RuntimeState(workspace=tmp_path, checkpoint_mode=mode)


def test_off_mode_does_not_save(tmp_path) -> None:
    manager = CheckpointManager(_runtime(tmp_path, mode="off"), task="off task")

    assert manager.enabled is False
    assert manager.save({}) is None
    assert not (tmp_path / ".kescode").exists()


def test_light_mode_writes_lightweight_files(tmp_path) -> None:
    (tmp_path / "hello.py").write_text("print('hi')", encoding="utf-8")
    manager = CheckpointManager(_runtime(tmp_path), task="light task")
    state = {"task": "light task", "attempts": 1, "max_attempts": 3}

    event = manager.save(state, status="running", latest_node="planner")

    root = tmp_path / ".kescode" / "checkpoints"
    assert event is not None
    assert event["type"] == "checkpoint_saved"
    assert event["git_commit"] is None
    assert (root / "checkpoint.json").exists()
    assert (root / "workspace_manifest.json").exists()
    assert (root / "RECOVERY.md").exists()
    assert not (root / "state.json").exists()
    assert not (root / "events.jsonl").exists()

    manifest = json.loads(
        (root / "workspace_manifest.json").read_text(encoding="utf-8")
    )
    assert {"path": "hello.py", "size": 11} in manifest["files"]


def test_strict_mode_appends_events_and_saves_state(tmp_path) -> None:
    manager = CheckpointManager(_runtime(tmp_path, mode="strict"), task="strict")
    state = {"task": "strict", "attempts": 2, "max_attempts": 5}

    manager.save(
        state,
        status="running",
        latest_node="planner",
        event={"type": "tool_call", "name": "bash"},
    )
    manager.save(
        state,
        status="running",
        latest_node="verifier",
        event={"type": "tool_result"},
    )

    root = tmp_path / ".kescode" / "checkpoints"
    assert (root / "state.json").exists()
    events = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 2
    assert json.loads(events[0])["name"] == "bash"
    assert json.loads(events[1])["latest_node"] == "verifier"


def test_light_resume_rebuilds_inputs(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    manager = CheckpointManager(runtime, task="resume me")
    manager.save(
        {"task": "resume me", "attempts": 1, "max_attempts": 4},
        status="running",
        latest_node="planner",
    )

    inputs, resume_event = CheckpointManager.load_resume_inputs(runtime)

    assert inputs["task"] == "resume me"
    assert inputs["attempts"] == 1
    assert inputs["max_attempts"] == 4
    assert inputs["messages"] == []
    assert resume_event["type"] == "checkpoint_resumed"
    assert resume_event["latest_node"] == "planner"


def test_strict_resume_restores_messages(tmp_path) -> None:
    runtime = _runtime(tmp_path, mode="strict")
    manager = CheckpointManager(runtime, task="with messages")
    manager.save(
        {
            "task": "with messages",
            "attempts": 2,
            "max_attempts": 3,
            "messages": [
                SystemMessage(content="system prompt"),
                HumanMessage(content="hello human"),
            ],
        }
    )

    inputs, _resume_event = CheckpointManager.load_resume_inputs(runtime)

    assert len(inputs["messages"]) == 2
    assert isinstance(inputs["messages"][0], SystemMessage)
    assert inputs["messages"][1].content == "hello human"


def test_load_without_checkpoint_raises(tmp_path) -> None:
    with pytest.raises(KesCodeError, match="No checkpoint found"):
        CheckpointManager.load_resume_inputs(_runtime(tmp_path))


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_git_snapshot_and_restore(tmp_path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    (tmp_path / "notes.txt").write_text("original", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-A"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    runtime = _runtime(tmp_path)
    manager = CheckpointManager(runtime, task="git task")
    event = manager.save(
        {"task": "git task", "attempts": 1, "max_attempts": 3},
        status="running",
        latest_node="planner",
    )
    assert event is not None
    assert event["git_commit"]

    (tmp_path / "notes.txt").write_text("changed", encoding="utf-8")
    inputs, resume_event = CheckpointManager.load_resume_inputs(runtime)

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "original"
    assert inputs["task"] == "git task"
    assert inputs["attempts"] == 1
    assert resume_event["git_commit"] == event["git_commit"]
