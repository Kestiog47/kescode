"""Tests for execution tracing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kescode.core.state import RuntimeState, normalize_trace_mode
from kescode.core.trace import TraceRecorder, build_timeline_markdown


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (None, "full"),
        ("full", "full"),
        ("summary", "summary"),
        ("off", "off"),
        ("unknown", "full"),
        ("", "full"),
    ],
)
def test_normalize_trace_mode(mode: str | None, expected: str) -> None:
    assert normalize_trace_mode(mode) == expected


def test_runtime_state_trace_defaults_and_normalization(tmp_path) -> None:
    runtime = RuntimeState(workspace=tmp_path)
    assert runtime.trace_mode == "full"
    assert runtime.trace_id is None

    normalized = RuntimeState(workspace=tmp_path, trace_mode="unknown")
    assert normalized.trace_mode == "full"


def _runtime(tmp_path: Path, mode: str = "full", trace_id: str | None = None):
    return RuntimeState(
        workspace=tmp_path,
        trace_mode=mode,
        trace_id=trace_id,
    )


def test_recorder_initializes_counters_and_generates_trace_id(tmp_path) -> None:
    recorder = TraceRecorder(_runtime(tmp_path), task="trace task")

    assert recorder.mode == "full"
    assert recorder.trace_id.startswith("trace-")
    assert recorder.root == tmp_path / ".kescode" / "traces" / recorder.trace_id
    assert recorder.node_visits == {}
    assert recorder.tool_calls == 0
    assert recorder.failed_tool_calls == 0
    assert recorder.approval_count == 0
    assert recorder.checkpoint_count == 0
    assert recorder.handoff_count == 0


def test_recorder_uses_runtime_trace_id(tmp_path) -> None:
    recorder = TraceRecorder(_runtime(tmp_path, trace_id="trace-fixed"))

    assert recorder.trace_id == "trace-fixed"
    assert recorder.root == tmp_path / ".kescode" / "traces" / "trace-fixed"


def test_off_mode_records_nothing(tmp_path) -> None:
    recorder = TraceRecorder(_runtime(tmp_path, mode="off"))

    assert recorder.start({"task": "x"}) is None
    assert recorder.record_custom_event({"type": "tool_call"}) is None
    assert (
        recorder.end(
            status="completed",
            latest_node="final",
            final_state={},
        )
        is None
    )
    assert not (tmp_path / ".kescode").exists()


def test_full_mode_records_events_and_statistics(tmp_path) -> None:
    recorder = TraceRecorder(_runtime(tmp_path), task="full task")
    recorder.start(
        {"task": "full task", "attempts": 1, "max_attempts": 3},
        resumed=True,
        resume_event={"checkpoint_id": "checkpoint-abc"},
    )
    recorder.record_custom_event({"type": "tool_call", "name": "bash"})
    recorder.record_custom_event({"type": "tool_result", "ok": False})
    recorder.record_custom_event(
        {"type": "tool_result", "ok": True, "requires_approval": True}
    )
    recorder.record_custom_event(
        {"type": "tool_result", "ok": False, "requires_approval": True}
    )
    recorder.record_custom_event({"type": "handoff"})
    recorder.record_custom_event({"type": "checkpoint_saved"})
    recorder.record_graph_update({"planner": {"plan_summary": "plan"}})
    recorder.record_graph_update({"node": "verifier", "data": {"passed": True}})

    payload = recorder.end(
        status="completed",
        latest_node="final",
        final_state={"task": "full task"},
    )

    root = tmp_path / ".kescode" / "traces" / recorder.trace_id
    assert payload is not None
    assert payload["task"] == "full task"
    assert payload["status"] == "completed"
    assert payload["latest_node"] == "final"
    assert payload["tool_calls"] == 1
    assert payload["failed_tool_calls"] == 2
    assert payload["approval_count"] == 2
    assert payload["checkpoint_count"] == 1
    assert payload["handoff_count"] == 1
    assert payload["node_visits"] == {"planner": 1, "verifier": 1}
    assert payload["duration_ms"] >= 0
    assert len(payload["timeline_head"]) == 9
    assert (root / "trace.json").exists()
    assert (root / "timeline.md").exists()

    lines = (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 9
    first = json.loads(lines[0])
    assert first["type"] == "run_start"
    assert first["resumed"] is True
    assert first["resume_event"]["checkpoint_id"] == "checkpoint-abc"


def test_summary_mode_skips_events_file(tmp_path) -> None:
    recorder = TraceRecorder(_runtime(tmp_path, mode="summary"), task="summary")
    recorder.start({"task": "summary"})
    recorder.record_custom_event({"type": "tool_call", "name": "bash"})

    payload = recorder.end(
        status="running",
        latest_node="planner",
        final_state={},
    )

    root = tmp_path / ".kescode" / "traces" / recorder.trace_id
    assert payload is not None
    assert payload["tool_calls"] == 1
    assert (root / "trace.json").exists()
    assert (root / "timeline.md").exists()
    assert not (root / "events.jsonl").exists()


def test_end_splits_timeline_head_and_tail(tmp_path) -> None:
    recorder = TraceRecorder(_runtime(tmp_path), task="long run")
    recorder.start({"task": "long run"})
    for index in range(120):
        recorder.record_custom_event(
            {"type": "tool_call", "name": f"tool-{index}"}
        )

    payload = recorder.end(
        status="completed",
        latest_node="final",
        final_state={},
    )

    assert payload is not None
    assert len(payload["timeline_head"]) == 20
    assert len(payload["timeline_tail"]) == 80
    assert payload["timeline_omitted"] == 21


def test_build_timeline_markdown_contains_summary(tmp_path) -> None:
    recorder = TraceRecorder(_runtime(tmp_path), task="markdown")
    recorder.start({"task": "markdown"})
    recorder.record_custom_event({"type": "tool_call", "name": "bash"})
    payload = recorder.end(
        status="completed",
        latest_node="final",
        final_state={},
    )

    markdown = build_timeline_markdown(payload)

    assert "# Trace Timeline" in markdown
    assert "markdown" in markdown
    assert "completed" in markdown
    assert "tool_call" in markdown
    assert "run_start" in markdown
    assert markdown.count("run_start") == 1
