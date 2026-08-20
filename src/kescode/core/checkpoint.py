"""Workspace checkpoints for pausing and resuming KesCode runs."""

from __future__ import annotations

import dataclasses
import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)

from kescode.core.errors import KesCodeError
from kescode.core.state import (
    VALID_CHECKPOINT_MODES,
    RuntimeState,
    normalize_checkpoint_mode,
)

__all__ = [
    "CheckpointManager",
    "VALID_CHECKPOINT_MODES",
    "build_recovery_markdown",
    "normalize_checkpoint_mode",
    "resume_command",
    "snapshot_workspace_git",
]

CHECKPOINT_DIR = ".kescode/checkpoints"
CHECKPOINT_JSON = "checkpoint.json"
STATE_JSON = "state.json"
EVENTS_JSONL = "events.jsonl"
MANIFEST_JSON = "workspace_manifest.json"
RECOVERY_MD = "RECOVERY.md"

_IGNORED_DIRS = {
    ".git",
    ".kescode",
    ".venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "node_modules",
    "__pycache__",
}

_MESSAGE_CLASSES = {
    "HumanMessage": HumanMessage,
    "AIMessage": AIMessage,
    "SystemMessage": SystemMessage,
    "ToolMessage": ToolMessage,
    "RemoveMessage": RemoveMessage,
}


class CheckpointManager:
    """Save and restore workspace checkpoints for a KesCode run."""

    def __init__(self, runtime: RuntimeState, task: str = "") -> None:
        self.workspace = runtime.workspace
        self.mode = normalize_checkpoint_mode(runtime.checkpoint_mode)
        self.task = task
        self.root = self.workspace / CHECKPOINT_DIR

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    def save(
        self,
        state: dict[str, Any],
        *,
        status: str = "running",
        latest_node: str | None = None,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Persist one checkpoint and return a checkpoint_saved event."""

        if not self.enabled:
            return None

        self.root.mkdir(parents=True, exist_ok=True)
        _ensure_checkpoint_ignore(self.root)

        checkpoint_id = f"checkpoint-{uuid4().hex[:8]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        if self.mode == "strict":
            event_record = dict(event or {})
            event_record.setdefault("timestamp", timestamp)
            event_record.setdefault("checkpoint_id", checkpoint_id)
            event_record.setdefault("status", status)
            event_record.setdefault("latest_node", latest_node)
            _append_event(self.root / EVENTS_JSONL, event_record)
            _write_json(
                self.root / STATE_JSON,
                _serialize_state(state),
            )

        manifest = _build_workspace_manifest(self.workspace)
        _write_json(self.root / MANIFEST_JSON, manifest)

        git_commit = snapshot_workspace_git(
            self.workspace,
            message=f"kescode checkpoint {checkpoint_id}",
        )

        payload: dict[str, Any] = {
            "checkpoint_id": checkpoint_id,
            "timestamp": timestamp,
            "mode": self.mode,
            "status": status,
            "latest_node": latest_node,
            "task": self.task or state.get("task", ""),
            "workspace": str(self.workspace),
            "git_commit": git_commit,
            "workspace_manifest": manifest,
            "resume_command": resume_command(self.workspace),
            "attempts": state.get("attempts", 0),
            "max_attempts": state.get("max_attempts", 3),
            "state": _state_summary(state),
        }
        _write_json(self.root / CHECKPOINT_JSON, payload)
        _write_text(self.root / RECOVERY_MD, build_recovery_markdown(payload))

        return {
            "type": "checkpoint_saved",
            "checkpoint_id": checkpoint_id,
            "workspace": str(self.workspace),
            "mode": self.mode,
            "status": status,
            "latest_node": latest_node,
            "git_commit": git_commit,
            "timestamp": timestamp,
        }

    @classmethod
    def load_resume_inputs(
        cls,
        runtime: RuntimeState,
        task: str | None = None,
        max_attempts: int = 3,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Restore checkpoint inputs and return (inputs, resume_event)."""

        manager = cls(runtime, task=task or "")
        checkpoint_path = manager.root / CHECKPOINT_JSON
        if not checkpoint_path.exists():
            raise KesCodeError(f"No checkpoint found at {checkpoint_path}")

        checkpoint = _read_json(checkpoint_path)
        git_commit = checkpoint.get("git_commit")
        if git_commit:
            _restore_git_commit(manager.workspace, git_commit)

        state_path = manager.root / STATE_JSON
        if state_path.exists():
            inputs = _deserialize_state(_read_json(state_path))
        else:
            inputs = _inputs_from_checkpoint(
                checkpoint,
                runtime=runtime,
                task=task,
                max_attempts=max_attempts,
            )

        inputs["runtime"] = runtime
        if task:
            inputs["task"] = task
        inputs.setdefault("task", checkpoint.get("task") or "")
        inputs.setdefault("attempts", checkpoint.get("attempts") or 0)
        inputs.setdefault("max_attempts", max_attempts)
        inputs.setdefault("messages", [])

        resume_event: dict[str, Any] = {
            "type": "checkpoint_resumed",
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "workspace": str(manager.workspace),
            "mode": checkpoint.get("mode"),
            "status": checkpoint.get("status"),
            "latest_node": checkpoint.get("latest_node"),
            "git_commit": git_commit,
            "task": inputs.get("task", ""),
            "attempts": inputs.get("attempts", 0),
            "max_attempts": inputs.get("max_attempts", max_attempts),
        }
        return inputs, resume_event


def resume_command(workspace: Path) -> str:
    """Return the shell command used to resume a workspace checkpoint."""

    path = str(workspace)
    if os.name == "nt":
        if " " in path or '"' in path:
            escaped = path.replace('"', '\\"')
            return f'kescode --resume "{escaped}"'
        return f"kescode --resume {path}"
    return f"kescode --resume {shlex.quote(path)}"


def build_recovery_markdown(payload: dict[str, Any]) -> str:
    """Render a human-readable recovery guide from a checkpoint payload."""

    manifest = payload.get("workspace_manifest") or {}
    files = sorted(
        str(item["path"]) for item in manifest.get("files") or [] if isinstance(item, dict)
    )
    lines = [
        "# Recovery Guide",
        "",
        f"- Checkpoint: {payload.get('checkpoint_id') or 'unknown'}",
        f"- Created: {payload.get('timestamp') or 'unknown'}",
        f"- Mode: {payload.get('mode') or 'unknown'}",
        f"- Status: {payload.get('status') or 'running'}",
        f"- Latest node: {payload.get('latest_node') or 'unknown'}",
        "",
        "## Task",
        "",
        str(payload.get("task") or "No task recorded."),
        "",
        "## Workspace",
        "",
        f"Path: `{payload.get('workspace') or 'unknown'}`",
        f"Git commit: `{payload.get('git_commit') or 'none'}`",
        "",
        "## Files",
        "",
        f"{len(files)} files tracked at checkpoint time.",
        "",
    ]
    if files:
        lines.append("```")
        lines.extend(files)
        lines.append("```")
    else:
        lines.append("No workspace files recorded.")
    lines.extend(
        [
            "",
            "## Resume",
            "",
            "```bash",
            str(payload.get("resume_command") or resume_command(Path("."))),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def snapshot_workspace_git(
    workspace: Path,
    message: str = "kescode checkpoint",
) -> str | None:
    """Commit the workspace snapshot and return the commit sha, if available."""

    if not _is_git_repo(workspace):
        return None

    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "KesCode")
    env.setdefault("GIT_AUTHOR_EMAIL", "kescode@local")
    env.setdefault("GIT_COMMITTER_NAME", "KesCode")
    env.setdefault("GIT_COMMITTER_EMAIL", "kescode@local")

    _git(workspace, ["add", "-A"], env=env)
    commit = _git(workspace, ["commit", "-m", message], env=env)
    head = _git(workspace, ["rev-parse", "HEAD"], env=env)
    if commit.returncode == 0 and head.returncode == 0:
        return head.stdout.strip()
    if commit.returncode != 0 and head.returncode == 0:
        return head.stdout.strip()
    return None


def _restore_git_commit(workspace: Path, commit: str) -> bool:
    if not commit or not _is_git_repo(workspace):
        return False

    verify = _git(workspace, ["rev-parse", "--verify", f"{commit}^{{commit}}"])
    if verify.returncode != 0:
        return False

    restore = _git(workspace, ["restore", "--source", commit, "--", "."])
    if restore.returncode == 0:
        return True
    checkout = _git(workspace, ["checkout", commit, "--", "."])
    return checkout.returncode == 0


def _is_git_repo(workspace: Path) -> bool:
    result = _git(workspace, ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git(
    workspace: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        env=env,
        creationflags=creationflags,
    )


def _ensure_checkpoint_ignore(root: Path) -> None:
    ignore = root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n!.gitignore\n", encoding="utf-8")


def _build_workspace_manifest(workspace: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or _is_ignored(path, workspace):
            continue
        relative = path.relative_to(workspace)
        files.append(
            {
                "path": relative.as_posix(),
                "size": path.stat().st_size,
            }
        )
    return {
        "workspace": str(workspace),
        "file_count": len(files),
        "files": files,
    }


def _is_ignored(path: Path, workspace: Path) -> bool:
    try:
        parts = path.relative_to(workspace).parts
    except ValueError:
        return True
    return bool(parts) and parts[0] in _IGNORED_DIRS


def _state_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": state.get("task", ""),
        "attempts": state.get("attempts", 0),
        "max_attempts": state.get("max_attempts", 3),
        "plan_summary": state.get("plan_summary", ""),
        "todos": state.get("todos", []),
        "acceptance_criteria": state.get("acceptance_criteria", []),
        "verification_commands": state.get("verification_commands", []),
        "research_notes": state.get("research_notes", ""),
        "code_agent_summary": state.get("code_agent_summary", ""),
        "last_error": state.get("last_error"),
        "passed": state.get("passed", False),
        "context_next_node": state.get("context_next_node", ""),
    }


def _inputs_from_checkpoint(
    checkpoint: dict[str, Any],
    *,
    runtime: RuntimeState,
    task: str | None,
    max_attempts: int,
) -> dict[str, Any]:
    summary = checkpoint.get("state") or {}
    inputs: dict[str, Any] = {
        "task": task or checkpoint.get("task") or "",
        "runtime": runtime,
        "messages": [],
        "attempts": int(summary.get("attempts", checkpoint.get("attempts") or 0)),
        "max_attempts": int(
            summary.get(
                "max_attempts",
                checkpoint.get("max_attempts") or max_attempts,
            )
        ),
    }
    for key in (
        "plan_summary",
        "todos",
        "acceptance_criteria",
        "verification_commands",
        "research_notes",
        "sources",
        "agent_handoffs",
        "code_agent_summary",
        "verification_results",
        "verification_checks",
        "passed",
        "last_error",
        "context_summary",
        "context_token_count",
        "context_token_limit",
        "context_should_compress",
        "context_next_node",
        "compression_events",
        "memory_snapshot",
        "history_summary",
    ):
        if key in summary:
            inputs[key] = summary[key]
    return inputs


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key, value in state.items():
        if isinstance(value, RuntimeState):
            serialized[key] = {
                "workspace": str(value.workspace),
                "checkpoint_mode": value.checkpoint_mode,
                "trace_mode": value.trace_mode,
                "trace_id": value.trace_id,
                "approval_mode": value.approval_mode,
            }
        else:
            serialized[key] = value
    return serialized


def _deserialize_state(data: dict[str, Any]) -> dict[str, Any]:
    state = dict(data)
    messages = state.get("messages")
    if isinstance(messages, list):
        state["messages"] = [_message_from_dict(item) for item in messages]
    runtime = state.get("runtime")
    if isinstance(runtime, dict):
        state["runtime"] = RuntimeState(
            workspace=Path(runtime.get("workspace", ".")),
            checkpoint_mode=runtime.get("checkpoint_mode"),
            trace_mode=runtime.get("trace_mode"),
            trace_id=runtime.get("trace_id"),
            approval_mode=runtime.get("approval_mode"),
        )
    return state


def _message_from_dict(data: Any) -> Any:
    if not isinstance(data, dict):
        return str(data)
    message_class = _MESSAGE_CLASSES.get(data.get("type"))
    if message_class is None:
        return str(data)
    kwargs = {key: value for key, value in data.items() if key != "type"}
    try:
        return message_class(**kwargs)
    except Exception:
        content = kwargs.get("content", "")
        try:
            return message_class(content=content)
        except Exception:
            return HumanMessage(content=content)


def _json_default(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        return _serialize_message(value)
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return str(value)


def _serialize_message(message: BaseMessage) -> dict[str, Any]:
    data: dict[str, Any] = {
        "type": message.__class__.__name__,
        "content": message.content,
    }
    for attribute in ("tool_call_id", "name", "id"):
        value = getattr(message, attribute, None)
        if value is not None:
            data[attribute] = value
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        data["tool_calls"] = tool_calls
    return data


def _append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(event, ensure_ascii=False, default=_json_default) + "\n"
        )


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
        newline="\n",
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
