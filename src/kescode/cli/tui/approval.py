"""TUI approval modal and worker-thread synchronization."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

from kescode.core.approval import ApprovalDecision, ApprovalRequest


class ApprovalRequestedMessage(Message):
    """Carry an approval request from a worker thread to the TUI."""

    def __init__(self, request: ApprovalRequest, gate: ApprovalGate) -> None:
        super().__init__()
        self.request = request
        self.gate = gate


class ApprovalGate:
    """Block a worker thread until the user resolves an approval request."""

    def __init__(
        self,
        notifier: (
            Callable[[ApprovalRequest, ApprovalGate], None] | None
        ) = None,
    ) -> None:
        self.notifier = notifier
        self.request: ApprovalRequest | None = None
        self._decision: ApprovalDecision | None = None
        self._event = threading.Event()

    def __call__(self, request: ApprovalRequest) -> ApprovalDecision:
        self.request = request
        self._decision = None
        self._event.clear()
        if self.notifier is not None:
            self.notifier(request, self)
        return self.wait()

    def wait(self, timeout: float | None = None) -> ApprovalDecision:
        if not self._event.wait(timeout):
            return ApprovalDecision(
                approved=False,
                reason="Approval timed out.",
            )
        return self._decision or ApprovalDecision(approved=False)

    def resolve(self, approved: bool, *, reason: str = "") -> None:
        self._decision = ApprovalDecision(approved=approved, reason=reason)
        self._event.set()


class ApprovalModal(ModalScreen[bool]):
    """Show a risky command and ask the user to approve or deny it."""

    BINDINGS = [
        ("y", "approve", "Approve"),
        ("enter", "approve", "Approve"),
        ("n", "deny", "Deny"),
        ("escape", "deny", "Deny"),
    ]

    CSS = """
    ApprovalModal {
        align: center middle;
        background: $surface;
    }
    #approval-dialog {
        width: 72;
        height: auto;
        max-height: 80%;
        border: round $warning;
        background: $panel;
        padding: 1 2;
    }
    #approval-title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    .approval-row {
        margin-bottom: 1;
    }
    #approval-command {
        border: tall $primary;
        background: $surface;
        padding: 1;
        margin: 1 0;
    }
    #approval-actions {
        height: 3;
        align-horizontal: right;
    }
    #approval-actions Button {
        width: 16;
        margin-left: 1;
    }
    """

    def __init__(
        self,
        request: ApprovalRequest,
        workspace: Path | str = "",
    ) -> None:
        super().__init__()
        self.request = request
        self.workspace = Path(workspace) if workspace else Path.cwd()

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-dialog"):
            yield Label("Command Approval Required", id="approval-title")
            yield Label(f"Tool: {self.request.tool_name}", classes="approval-row")
            yield Label(f"Risk: {self.request.risk_reason}", classes="approval-row")
            yield Label(f"Workspace: {self.workspace}", classes="approval-row")
            yield Static(f"Command:\n{self.request.command}", id="approval-command")
            with Horizontal(id="approval-actions"):
                yield Button("Y Approve", id="approve", variant="success")
                yield Button("N Deny", id="deny", variant="error")

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "approve")


__all__ = [
    "ApprovalGate",
    "ApprovalModal",
    "ApprovalRequestedMessage",
]
