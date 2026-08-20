"""Rich-rendered ASCII art logo for the KesCode TUI."""

from __future__ import annotations

import time
from collections.abc import Iterator

from rich.console import Console
from rich.live import Live
from rich.text import Text

LOGO_ART = """ 🐾 KesCode
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Stage 6 · MultiAgent + Context/Harness
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

_PALETTE = (
    "bold cyan",
    "bold magenta",
    "bold yellow",
    "bold green",
)
_RULE_STYLE = "bold bright_black"
_TAGLINE_STYLE = "dim italic"


def build_logo(step: int = 0) -> Text:
    """Return the KesCode logo as a colored rich Text."""

    lines = LOGO_ART.splitlines()
    title_style = _PALETTE[step % len(_PALETTE)]
    text = Text()
    text.append(f"{lines[0]}\n", style=title_style)
    text.append(f"{lines[1]}\n", style=_RULE_STYLE)
    text.append(f"{lines[2]}\n", style=_TAGLINE_STYLE)
    text.append(lines[3], style=_RULE_STYLE)
    return text


def logo_frames(
    cycles: int = 3,
    *,
    palette: tuple[str, ...] | None = None,
) -> Iterator[Text]:
    """Yield one Text frame per palette color for the requested cycles."""

    colors = palette or _PALETTE
    for cycle in range(cycles):
        for step in range(len(colors)):
            yield build_logo(step + cycle * len(colors))


def render_logo(
    console: Console | None = None,
    *,
    animate: bool = True,
    cycles: int = 2,
    interval: float = 0.12,
) -> None:
    """Render the logo to a rich console, optionally cycling colors."""

    console = console or Console()
    if not animate:
        console.print(build_logo())
        return

    with Live(
        console=console,
        refresh_per_second=max(1.0, 1 / interval),
        transient=False,
    ) as live:
        for frame in logo_frames(cycles):
            live.update(frame)
            time.sleep(interval)


__all__ = [
    "LOGO_ART",
    "build_logo",
    "logo_frames",
    "render_logo",
]
