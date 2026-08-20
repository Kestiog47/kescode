"""Tests for workspace-backed session management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kescode.core.errors import KesCodeError
from kescode.core.session import (
    MAX_SESSION_CONTEXT,
    MAX_TURN_CONTENT,
    SESSION_FILE,
    SESSION_ROOT,
    SESSION_SUMMARY_FILE,
    append_assistant_turn,
    append_user_turn,
    build_session_context,
    load_or_create_session,
    save_session,
)


def test_load_or_create_session_creates_session_file(tmp_path) -> None:
    session = load_or_create_session(tmp_path)

    assert session["session_id"]
    assert session["turn_index"] == 0
    assert session["recent_turns"] == []
    assert session["created_at"]
    assert session["updated_at"]
    assert (tmp_path / SESSION_ROOT / SESSION_FILE).exists()


def test_load_or_create_session_loads_existing_session(tmp_path) -> None:
    first = load_or_create_session(tmp_path)
    append_user_turn(first, "hello")
    save_session(tmp_path, first)

    second = load_or_create_session(tmp_path)

    assert second["session_id"] == first["session_id"]
    assert second["turn_index"] == 1
    assert second["recent_turns"][0]["content"] == "hello"


def test_append_turns_records_user_and_assistant_turns(tmp_path) -> None:
    session = load_or_create_session(tmp_path)

    first_turn = append_user_turn(session, "hello")
    append_assistant_turn(
        session,
        turn=first_turn,
        route="chat",
        content="hi there",
        summary="greeting",
    )
    second_turn = append_user_turn(session, "continue")

    assert first_turn == 1
    assert second_turn == 2
    assert session["turn_index"] == 2
    assert session["recent_turns"][0] == {
        "turn": 1,
        "role": "user",
        "content": "hello",
        "timestamp": session["recent_turns"][0]["timestamp"],
    }
    assert session["recent_turns"][1]["role"] == "assistant"
    assert session["recent_turns"][1]["route"] == "chat"
    assert session["recent_turns"][1]["summary"] == "greeting"
    assert session["recent_turns"][2]["turn"] == 2


def test_append_user_turn_truncates_long_content(tmp_path) -> None:
    session = load_or_create_session(tmp_path)

    append_user_turn(session, "x" * (MAX_TURN_CONTENT * 2))

    stored = session["recent_turns"][0]["content"]
    assert len(stored) == MAX_TURN_CONTENT
    assert stored.endswith("...")


def test_save_session_writes_json_and_summary(tmp_path) -> None:
    session = load_or_create_session(tmp_path)
    append_user_turn(session, "build it")
    append_assistant_turn(
        session,
        turn=1,
        route="workflow",
        content="completed",
        summary="implementation done",
    )

    saved = save_session(tmp_path, session)

    session_path = tmp_path / SESSION_ROOT / SESSION_FILE
    summary_path = tmp_path / SESSION_ROOT / SESSION_SUMMARY_FILE
    assert session_path.exists()
    assert summary_path.exists()
    assert saved["updated_at"]
    assert saved["recent_turns"][-1]["route"] == "workflow"
    assert json.loads(session_path.read_text(encoding="utf-8")) == saved
    summary = summary_path.read_text(encoding="utf-8")
    assert "Session ID" in summary
    assert "implementation done" in summary


def test_build_session_context_includes_session_files_and_turns(
    tmp_path,
) -> None:
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "README.md").write_text("readme", encoding="utf-8")
    ignored = tmp_path / ".venv" / "ignored.py"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("ignored", encoding="utf-8")
    session = load_or_create_session(tmp_path)
    append_user_turn(session, "hello")
    append_assistant_turn(
        session,
        turn=1,
        route="chat",
        content="hi there",
        summary="greeted the user",
    )

    context = build_session_context(tmp_path, session)

    assert session["session_id"] in context
    assert "Turn index: 1" in context
    assert "main.py" in context
    assert "README.md" in context
    assert "ignored.py" not in context
    assert "greeted the user" in context


def test_build_session_context_respects_max_length(tmp_path) -> None:
    session = load_or_create_session(tmp_path)
    for index in range(1, 11):
        append_user_turn(session, "user " + ("x" * MAX_TURN_CONTENT))
        append_assistant_turn(
            session,
            turn=index,
            route="workflow",
            content="assistant " + ("y" * MAX_TURN_CONTENT),
            summary="summary " + ("z" * MAX_TURN_CONTENT),
        )

    context = build_session_context(tmp_path, session)

    assert len(context) <= MAX_SESSION_CONTEXT
    assert "Recent turns (last 10)" in context


def test_load_corrupt_session_raises(tmp_path) -> None:
    path = tmp_path / SESSION_ROOT / SESSION_FILE
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(KesCodeError, match="Unable to read session file"):
        load_or_create_session(tmp_path)
