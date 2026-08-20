"""Tests for the rich-rendered KesCode TUI logo."""

from __future__ import annotations

import io

from rich.console import Console

from kescode.cli.tui.logo import build_logo, logo_frames, render_logo


def test_build_logo_contains_expected_lines() -> None:
    logo = build_logo()

    assert "🐾 KesCode" in logo.plain
    assert "Stage 6 · MultiAgent + Context/Harness" in logo.plain
    assert len(logo.plain.splitlines()) == 4


def test_build_logo_cycles_colors() -> None:
    first = build_logo(0)
    second = build_logo(1)

    assert first.plain == second.plain
    assert str(first.spans[0].style) != str(second.spans[0].style)


def test_logo_frames_cover_each_palette_color() -> None:
    frames = list(logo_frames(cycles=2))

    assert len(frames) == 8
    assert len({str(frame.spans[0].style) for frame in frames}) == 4


def test_render_logo_without_animation_prints_art() -> None:
    console = Console(
        file=io.StringIO(),
        width=80,
        force_terminal=False,
        record=True,
    )

    render_logo(console, animate=False)

    output = console.export_text()
    assert "KesCode" in output
    assert "Stage 6 · MultiAgent + Context/Harness" in output


def test_render_logo_animation_leaves_final_art() -> None:
    console = Console(
        file=io.StringIO(),
        width=80,
        force_terminal=False,
        record=True,
    )

    render_logo(console, animate=True, cycles=1, interval=0.001)

    assert "KesCode" in console.export_text()
