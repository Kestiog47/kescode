"""Shell execution tool."""

from __future__ import annotations

import locale
import os
import subprocess
from typing import Any
from uuid import uuid4

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

from kescode.core.approval import (
    ApprovalDecision,
    ApprovalHandler,
    ApprovalRequest,
    classify_command_risk,
    normalize_approval_mode,
)
from kescode.core.state import RuntimeState


class BashArgs(BaseModel):
    command: str = Field(description="Shell command to run inside the workspace.")
    timeout_seconds: float = Field(
        default=120.0,
        gt=0,
        le=3600,
        description="Maximum time in seconds before the command is killed.",
    )


class BashTool:
    """Run a shell command with the workspace as its working directory."""

    name = "bash"
    description = (
        "Run a shell command with the workspace as the working directory. "
        "Returns a structured result with ok, stdout, stderr, and exit_code; "
        "risky commands may require approval."
    )
    args_schema = BashArgs

    def __init__(
        self,
        state: RuntimeState,
        *,
        approval_mode: str | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> None:
        self.state = state
        self.approval_mode = normalize_approval_mode(approval_mode)
        self.approval_handler = approval_handler

    def run(self, command: str, timeout_seconds: float = 120.0) -> dict[str, Any]:
        return self.run_bash(command, timeout_seconds=timeout_seconds)

    def run_bash(
        self,
        command: str,
        timeout_seconds: float = 120.0,
        approval_mode: str | None = None,
        approval_handler: ApprovalHandler | None = None,
    ) -> dict[str, Any]:
        """Run a command after classifying and, when needed, approving its risk."""

        mode = normalize_approval_mode(
            approval_mode if approval_mode is not None else self.approval_mode
        )
        handler = (
            approval_handler if approval_handler is not None else self.approval_handler
        )
        risk_reason = classify_command_risk(command)

        if risk_reason is None:
            return self._execute(command, timeout_seconds)

        if mode == "deny":
            return _denied_result(command, risk_reason)

        if mode == "inline":
            if handler is None:
                raise ToolException(
                    f"Command requires approval ({risk_reason}), but no approval "
                    "handler is configured."
                )
            request = ApprovalRequest(
                id=f"approval-{uuid4().hex[:8]}",
                command=command,
                risk_reason=risk_reason,
            )
            decision = _as_decision(handler(request))
            if not decision.approved:
                reason = decision.reason or f"Command rejected: {risk_reason}"
                return _denied_result(command, risk_reason, reason=reason)
            result = self._execute(command, timeout_seconds)
            result["approved"] = True
            result["requires_approval"] = False
            return result

        # auto mode: allow the command but record that approval was not requested.
        result = self._execute(command, timeout_seconds)
        result["approved"] = True
        result["requires_approval"] = True
        return result

    def _execute(self, command: str, timeout_seconds: float) -> dict[str, Any]:
        env = os.environ.copy()
        env["KESCODE_WORKSPACE"] = str(self.state.workspace)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=self.state.workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                creationflags=creationflags,
            )
        except OSError as exc:
            return _result(
                command,
                ok=False,
                reason=f"Unable to run command: {exc}",
            )

        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            stderr_text = _decode_output(stderr)
            if stderr_text:
                stderr_text += "\n"
            stderr_text += f"[timed out after {timeout_seconds:g} seconds]"
            return _result(
                command,
                ok=False,
                exit_code=None,
                stdout=_decode_output(stdout),
                stderr=stderr_text,
                reason=f"Command timed out after {timeout_seconds:g} seconds",
            )

        return _result(
            command,
            ok=process.returncode == 0,
            exit_code=process.returncode,
            stdout=_decode_output(stdout),
            stderr=_decode_output(stderr),
        )

    def to_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            func=self.run,
            name=self.name,
            description=self.description,
            args_schema=self.args_schema,
        )


def _decode_output(data: bytes) -> str:
    """Decode command output, preferring UTF-8 and falling back to locale encoding."""

    if not data:
        return ""

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        encoding = locale.getpreferredencoding(False)
        return data.decode(encoding, errors="replace")


def _as_decision(decision: ApprovalDecision | bool) -> ApprovalDecision:
    if isinstance(decision, ApprovalDecision):
        return decision
    return ApprovalDecision(approved=bool(decision))


def _denied_result(
    command: str,
    risk_reason: str,
    *,
    reason: str = "",
) -> dict[str, Any]:
    message = reason or f"Command denied: {risk_reason}"
    return _result(
        command,
        ok=False,
        exit_code=None,
        approved=False,
        requires_approval=True,
        reason=message,
    )


def _result(
    command: str,
    *,
    ok: bool,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    approved: bool = True,
    requires_approval: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "command": command,
        "ok": ok,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "approved": approved,
        "requires_approval": requires_approval,
    }
    if reason:
        result["reason"] = reason
    return result
