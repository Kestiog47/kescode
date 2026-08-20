"""Textual TUI for KesCode multi-turn sessions."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.message import Message
from textual.widgets import Footer, Header, Input, RichLog, Static

from kescode.cli.tui.approval import (
    ApprovalGate,
    ApprovalModal,
    ApprovalRequestedMessage,
)
from kescode.cli.tui.logo import build_logo
from kescode.core.agent import stream_session_events
from kescode.core.approval import ApprovalDecision, ApprovalRequest
from kescode.core.paths import ensure_workspace
from kescode.core.session import load_or_create_session

_TOOL_LABELS = {
    "bash": "BashTool",
    "file_edit": "FileEditTool",
    "file_read": "FileReadTool",
    "file_write": "FileWriteTool",
    "grep": "GrepTool",
    "notepad_append": "NotepadAppendTool",
    "notepad_read": "NotepadReadTool",
    "todo_update": "TodoUpdateTool",
    "todo_write": "Plan",
    "web_search": "WebSearchTool",
}

class AgentEventMessage(Message):
    """Carry one streamed agent event from the worker thread to the UI."""

    def __init__(self, event: dict[str, Any]) -> None:
        super().__init__()
        self.event = event


class KesCodeTuiApp(App[None]):
    """Textual interface for KesCode multi-turn sessions."""

    TITLE = "KesCode"
    SUB_TITLE = "workspace agent"
    CSS = """
    Screen {
        layout: vertical;
    }
    Header {
        dock: top;
    }
    Footer {
        dock: bottom;
    }
    #session-status {
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 2;
        content-align: left middle;
    }
    #logo {
        height: 3;
        background: $surface;
        padding: 0 2;
        content-align: center middle;
    }
    #event-log {
        width: 1fr;
        height: 1fr;
        border: round $accent;
        padding: 0 1;
    }
    #prompt {
        height: 3;
        margin: 0 1;
    }
    """

    def __init__(
        self,
        workspace: Path | str,
        *,
        session_workspace: Path | str | None = None,
        max_attempts: int = 3,
        approval_mode: str = "inline",
        checkpoint_mode: str = "light",
        trace_mode: str = "on",
        model: str | None = None,
    ) -> None:
        super().__init__()
        self.workspace = ensure_workspace(Path(workspace))
        self.session_workspace = ensure_workspace(
            Path(session_workspace)
            if session_workspace is not None
            else self.workspace
        )
        self.max_attempts = max_attempts
        self.approval_mode = approval_mode
        self.checkpoint_mode = checkpoint_mode
        self.trace_mode = trace_mode
        if model:
            os.environ["MODEL"] = model

        self._session_id = ""
        self._turn_running = False
        self._last_reply_content = ""
        self._seen_event_keys: set[str] = set()
        self._thread: threading.Thread | None = None
        self._logo_step = 0
        self._logo_frames_left = 8
        self._logo_timer = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="session-status")
        yield Static(build_logo(), id="logo")
        yield RichLog(
            highlight=True,
            markup=False,
            wrap=True,
            id="event-log",
        )
        yield Input(placeholder="💬 Input: ...", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        try:
            session = load_or_create_session(self.session_workspace)
            self._session_id = str(session.get("session_id") or "")
        except Exception:
            pass
        self._update_status("Ready")
        self.query_one("#prompt", Input).focus()
        self._logo_timer = self.set_interval(0.3, self._animate_logo)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        task = event.value.strip()
        event.input.value = ""
        if not task:
            return
        if self._turn_running:
            self.notify("Agent is still running.", severity="warning")
            return

        self._turn_running = True
        self._last_reply_content = ""
        self._seen_event_keys.clear()
        self.query_one(Input).disabled = True
        self._update_status("Running...")
        self._thread = threading.Thread(
            target=self._run_session_turn,
            args=(task,),
            daemon=True,
        )
        self._thread.start()

    def on_agent_event_message(self, message: AgentEventMessage) -> None:
        self._handle_event(message.event)

    def on_approval_requested_message(
        self,
        message: ApprovalRequestedMessage,
    ) -> None:
        self._log(f"⚠️ Approval requested: {message.request.tool_name}")
        self.push_screen(
            ApprovalModal(message.request, self.workspace),
            callback=lambda approved: message.gate.resolve(bool(approved)),
        )

    def _run_session_turn(self, task: str) -> None:
        try:
            for event in stream_session_events(
                task,
                session_workspace=self.session_workspace,
                workspace=self.workspace,
                max_attempts=self.max_attempts,
                approval_mode=self.approval_mode,
                approval_handler=self._approval_handler,
                checkpoint_mode=self.checkpoint_mode,
                trace_mode=self.trace_mode,
            ):
                self._post_event(event)
        except Exception as exc:
            self._post_event({"type": "error", "message": str(exc)})
        finally:
            self._post_event({"type": "turn_finished"})

    def _approval_handler(
        self,
        request: ApprovalRequest,
    ) -> ApprovalDecision:
        gate = ApprovalGate(notifier=self._notify_approval)
        return gate(request)

    def _notify_approval(
        self,
        request: ApprovalRequest,
        gate: ApprovalGate,
    ) -> None:
        self._post_ui_message(ApprovalRequestedMessage(request, gate))

    def _post_event(self, event: dict[str, Any]) -> None:
        self._post_ui_message(AgentEventMessage(event))

    def _post_ui_message(self, message: Message) -> None:
        try:
            self.post_message(message)
        except Exception:
            pass

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "session_event":
            self._handle_session_event(event.get("event") or {})
        elif event_type == "graph_event":
            self._handle_graph_event(event.get("event") or {})
        elif event_type == "custom_event":
            self._handle_custom_event(event.get("event") or {})
        elif event_type == "intent_route":
            reason = str(event.get("reason") or "")
            suffix = f" ({reason})" if reason else ""
            self._log_once(
                _event_key("intent", (event.get("route"), reason)),
                f"🧭 Intent: {event.get('route')}{suffix}",
            )
        elif event_type == "final_answer":
            self._log_reply(event.get("content"), "✅")
        elif event_type == "error":
            self._log(f"❌ {event.get('message') or 'Unknown error'}")
        elif event_type == "turn_finished":
            self._finish_turn()
        else:
            self._log(f"• {event_type}")

    def _handle_session_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "session_loaded":
            self._session_id = str(event.get("session_id") or self._session_id)
            self._update_status()
        elif event_type == "user_turn":
            self._log(f"💬 {event.get('content') or ''}")
            self._update_status(f"turn {event.get('turn')}")
        elif event_type == "session_context":
            self._log(f"🧾 Session context ready (turn {event.get('turn')})")
        elif event_type == "assistant_turn":
            self._log_reply(event.get("content"), "🤖")
            self._update_status(f"turn {event.get('turn')} complete")
        elif event_type == "session_saved":
            self._update_status("Session saved")
        else:
            self._log(f"• session: {event_type}")

    def _handle_graph_event(self, graph_event: dict[str, Any]) -> None:
        for node, update in graph_event.items():
            if not isinstance(update, dict):
                continue
            if node == "planner":
                plan_summary = update.get("plan_summary")
                if plan_summary:
                    self._log_once(
                        _event_key("plan", plan_summary),
                        f"📋 {plan_summary}",
                    )
            elif node == "intent_router":
                route = update.get("intent_route")
                reason = str(update.get("intent_reason") or "")
                suffix = f" ({reason})" if reason else ""
                self._log_once(
                    _event_key("intent", (route, reason)),
                    f"🧭 Intent: {route}{suffix}",
                )
            elif node == "chat_responder":
                content = update.get("final_answer") or update.get(
                    "chat_response"
                )
                if content:
                    self._log_reply(content, "🤖")
            elif node == "final":
                content = update.get("final_answer")
                if content:
                    self._log_reply(content, "✅")
            elif node == "verifier":
                passed = update.get("passed")
                if passed is True:
                    self._log("✅ Verifier passed")
                elif passed is False:
                    self._log("❌ Verifier failed")
            elif node == "context_monitor":
                self._log("📦 Context monitor checked")
            elif node == "context_compressor":
                self._log("📦 Context compressed")
            else:
                self._log(f"📦 {node}")

    def _handle_custom_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "tool_call":
            self._log_once(
                _event_key("tool_call", (event.get("name"), event.get("args"))),
                self._tool_call_text(event),
            )
        elif event_type == "tool_result":
            self._log_once(
                _event_key("tool_result", (event.get("name"), event.get("result"))),
                self._tool_result_text(event),
            )
        elif event_type == "handoff":
            self._log_once(
                _event_key(
                    "handoff",
                    (
                        event.get("from"),
                        event.get("to"),
                        event.get("instruction"),
                    ),
                ),
                "🔄 Handoff: "
                f"{event.get('from')} → {event.get('to')}: "
                f"{event.get('instruction') or ''}",
            )
        elif event_type == "checkpoint_saved":
            self._log(f"💾 Checkpoint saved: {event.get('checkpoint_id')}")
        elif event_type == "ai_message":
            content = str(event.get("content") or "").strip()
            if content:
                self._log_once(
                    _event_key("ai_message", content),
                    f"💭 {content}",
                )
        elif event_type == "search_results":
            self._log_once(
                _event_key("search_results", event.get("query")),
                f"🔍 WebSearchTool: {event.get('query') or ''} "
                f"({len(event.get('results') or [])} results)",
            )
        elif event_type == "final_answer":
            self._log_reply(event.get("content"), "✅")
        elif event_type == "plan_snapshot":
            plan_summary = str(event.get("plan_summary") or "")
            if plan_summary:
                self._log_once(
                    _event_key("plan", plan_summary),
                    f"📋 {plan_summary}",
                )
        elif event_type == "memory":
            pass
        else:
            self._log(f"• {event_type}")

    def _finish_turn(self) -> None:
        self._turn_running = False
        prompt = self.query_one("#prompt", Input)
        prompt.disabled = False
        prompt.focus()
        self._update_status("Ready")

    def _log_reply(self, content: Any, prefix: str) -> None:
        text = str(content or "").strip()
        if not text or text == self._last_reply_content:
            return
        self._last_reply_content = text
        self._log(f"{prefix} {text}")

    def _log_once(self, key: str, content: str) -> None:
        if key in self._seen_event_keys:
            return
        self._seen_event_keys.add(key)
        self._log(content)

    def _animate_logo(self) -> None:
        self._logo_step += 1
        self._logo_frames_left -= 1
        self.query_one("#logo", Static).update(build_logo(self._logo_step))
        if self._logo_frames_left <= 0:
            if self._logo_timer is not None:
                self._logo_timer.stop()

    def _update_status(self, extra: str = "") -> None:
        session = self._session_id[:8] or "..."
        parts = [f"🐾 KesCode", f"session: {session}"]
        if extra:
            parts.append(extra)
        self.query_one("#session-status", Static).update(" | ".join(parts))

    def _log(self, content: str) -> None:
        self.query_one("#event-log", RichLog).write(content)

    def _tool_call_text(self, event: dict[str, Any]) -> str:
        name = str(event.get("name") or "tool")
        label = _TOOL_LABELS.get(name, name)
        args = event.get("args")
        if not isinstance(args, dict):
            args = {"value": str(args)}

        file_path = args.get("file_path")
        if file_path:
            return f"🔧 {label} → {file_path}"
        query = args.get("query")
        if query:
            return f"🔍 {label}: \"{query}\""
        command = args.get("command")
        if command:
            return f"🔧 {label}: {_one_line(command, 140)}"
        content = args.get("content")
        if content is not None:
            return f"📝 {label}: \"{_one_line(content, 120)}\""
        return f"🔧 {label}: {_one_line(json.dumps(args, ensure_ascii=False), 140)}"

    def _tool_result_text(self, event: dict[str, Any]) -> str:
        name = str(event.get("name") or "tool")
        label = _TOOL_LABELS.get(name, name)
        result = event.get("result")
        if not isinstance(result, dict):
            return f"ℹ️ {label}: {_one_line(result, 180)}"

        ok = result.get("ok")
        icon = "✅" if ok is True else ("❌" if ok is False else "ℹ️")
        detail = (
            result.get("summary")
            or result.get("stdout")
            or result.get("stderr")
            or result.get("reason")
            or result.get("answer")
            or json.dumps(result, ensure_ascii=False)
        )
        return f"{icon} {label}: {_one_line(detail, 180)}"


def _one_line(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _event_key(prefix: str, value: Any) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
    except (TypeError, ValueError):
        payload = str(value)
    return f"{prefix}:{payload}"


__all__ = [
    "AgentEventMessage",
    "KesCodeTuiApp",
]
