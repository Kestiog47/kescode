"""Runtime state shared by KesCode tools."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from kescode.core.approval import ApprovalHandler, normalize_approval_mode

VALID_CHECKPOINT_MODES = {"light", "strict", "off"}
VALID_TRACE_MODES = {"off", "summary", "full"}


def normalize_checkpoint_mode(mode: str | None) -> str:
    """Return a valid checkpoint mode, defaulting unknown values to light."""

    if mode in VALID_CHECKPOINT_MODES:
        return mode
    return "light"


def normalize_trace_mode(mode: str | None) -> str:
    """Return a valid trace mode; on and unknown values become full."""

    if mode == "on":
        return "full"
    if mode in VALID_TRACE_MODES:
        return mode
    return "full"


@dataclass(frozen=True)
class RuntimeState:
    """State carried through a single KesCode run."""

    workspace: Path
    checkpoint_mode: str = "light"
    trace_mode: str = "full"
    trace_id: str | None = None
    approval_mode: str = "inline"
    approval_handler: ApprovalHandler | None = None

    def __post_init__(self) -> None:
        workspace = self.workspace.expanduser().resolve()
        checkpoint_mode = normalize_checkpoint_mode(self.checkpoint_mode)
        trace_mode = normalize_trace_mode(self.trace_mode)
        approval_mode = normalize_approval_mode(self.approval_mode)
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "checkpoint_mode", checkpoint_mode)
        object.__setattr__(self, "trace_mode", trace_mode)
        object.__setattr__(self, "approval_mode", approval_mode)
