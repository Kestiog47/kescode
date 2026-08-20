"""Typer entry point for the kescode command."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from kescode.core.agent import NODE_TITLES, stream_agent_events
from kescode.core.paths import ensure_workspace

DEFAULT_MAX_ATTEMPTS = 3
console = Console()
app = typer.Typer()


@app.command()
def run(
    ctx: typer.Context,
    task: Annotated[
        str | None,
        typer.Argument(help="Task description for the agent."),
    ] = None,
    workspace: Annotated[
        Path | None,
        typer.Option(
            "--workspace",
            "-w",
            help="Workspace directory; created automatically when missing.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help="Model name. Defaults to MODEL env or deepseek-v4-flash.",
        ),
    ] = None,
    max_attempts: Annotated[
        int,
        typer.Option(
            "--max-attempts",
            min=1,
            help="Maximum number of planner/verifier attempts before finalizing.",
        ),
    ] = DEFAULT_MAX_ATTEMPTS,
    approval_mode: Annotated[
        Literal["inline", "auto", "deny"],
        typer.Option("--approval-mode", help="Command approval policy."),
    ] = "inline",
    checkpoint_mode: Annotated[
        Literal["light", "strict", "off"],
        typer.Option("--checkpoint-mode", help="Checkpoint persistence policy."),
    ] = "light",
    trace_mode: Annotated[
        Literal["on", "off"],
        typer.Option("--trace-mode", help="Execution tracing policy."),
    ] = "on",
    resume: Annotated[
        Path | None,
        typer.Option("--resume", help="Resume from a workspace checkpoint."),
    ] = None,
) -> None:
    """Run KesCode against a task in a workspace."""

    if task is None and resume is None:
        raise typer.BadParameter(
            "task is required unless --resume is provided."
        )

    workspace = ensure_workspace(workspace or Path.cwd())
    if model:
        os.environ["MODEL"] = model

    try:
        for event in stream_agent_events(
            task or "",
            workspace=workspace,
            max_attempts=max_attempts,
            approval_mode=approval_mode,
            checkpoint_mode=checkpoint_mode,
            trace_mode=trace_mode,
            resume_workspace=resume,
        ):
            _render_event(event)
    except RuntimeError as exc:
        console.print(f"Error: {exc}", style="bold red", markup=False)
        raise typer.Exit(1) from exc


def _render_event(event: dict) -> None:
    """Render one agent event through rich."""

    event_type = event.get("type")
    if event_type == "graph_event":
        _render_graph_event(event.get("event") or {})
        return
    if event_type == "custom_event":
        event = event.get("event") or {}
        event_type = event.get("type", "custom_event")
    node = str(event.get("node") or "")
    if event_type == "node_output":
        data = event.get("data") or {}
        content = Syntax(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            "json",
            word_wrap=True,
        )
        _print_panel(content, title=node, border_style=_node_style(node))
    elif event_type == "ai_message":
        content = Text(str(event.get("content") or ""), style="grey35", overflow="fold")
        title = node or "Agent"
        _print_panel(content, title=title, border_style="grey35")
    elif event_type == "tool_call":
        args_json = json.dumps(
            event.get("args") or {},
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        content = Syntax(args_json, "json", word_wrap=True)
        _print_panel(
            content,
            title=f"{node} / Tool: {event.get('name')}",
            border_style="bold cyan",
        )
    elif event_type == "tool_result":
        result = event.get("result")
        if isinstance(result, dict):
            result_json = json.dumps(result, ensure_ascii=False, indent=2, default=str)
            content = Syntax(result_json, "json", word_wrap=True)
        else:
            content = Text(str(result), style="magenta", overflow="fold")
        _print_panel(
            content,
            title=f"{node} / Tool result: {event.get('name')}",
            border_style="magenta",
        )
    elif event_type == "handoff":
        content = Text(
            f"{event.get('from')} -> {event.get('to')}: "
            f"{event.get('instruction')}",
            style="bold blue",
            overflow="fold",
        )
        _print_panel(content, title="Handoff", border_style="bold blue")
    elif event_type == "final_answer":
        content = Text(
            str(event.get("content") or ""),
            style="bold green",
            overflow="fold",
        )
        _print_panel(content, title="Final", border_style="bold green")


def _render_graph_event(event: dict) -> None:
    """Render a raw graph update as one or more node panels."""

    for node, update in event.items():
        if node == "final":
            content = Text(
                str(update.get("final_answer") or ""),
                style="bold green",
                overflow="fold",
            )
            _print_panel(content, title="Final", border_style="bold green")
            continue

        data = dict(update)
        if node == "planner":
            data.pop("messages", None)
        content = Syntax(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            "json",
            word_wrap=True,
        )
        _print_panel(
            content,
            title=NODE_TITLES.get(node, node),
            border_style=_node_style(node),
        )


def _node_style(node: str) -> str:
    return {
        "Planner": "bold cyan",
        "searchAgent": "bold cyan",
        "codeAgent": "bold yellow",
        "Verifier": "bold magenta",
        "Final": "bold green",
    }.get(node, "grey35")


def _print_panel(
    renderable: object,
    *,
    title: str,
    border_style: str,
) -> None:
    """Print a compact rounded panel for one agent event."""

    console.print(
        Panel(
            renderable,
            title=title,
            border_style=border_style,
            box=box.ROUNDED,
            title_align="left",
            padding=(0, 1),
            expand=False,
        )
    )


def main() -> None:
    """Console entry point."""

    app()
