"""Conway's Game of Life 演示脚本。

用法：
    python demo.py                       # 默认 blinker，迭代 30 代
    python demo.py --generations 50      # 自定义迭代代数
    python demo.py --pattern glider      # 切换图案（blinker / glider）

说明：
    --generations 为迭代上限（必须为正整数），保证程序必然终止、不会无限循环。
"""

from __future__ import annotations

import argparse
import sys

from game_of_life import GameOfLife

# 每个图案：名称 -> (活细胞坐标列表)
PATTERNS: dict[str, list[tuple[int, int]]] = {
    # 水平 blinker，置于 7x7 网格中央
    "blinker": [(2, 3), (3, 3), (4, 3)],
    # 经典 glider，置于 12x12 网格左上区域
    "glider": [(1, 1), (2, 2), (0, 3), (1, 3), (2, 3)],
}

PATTERN_DIMS: dict[str, tuple[int, int]] = {
    "blinker": (7, 7),
    "glider": (12, 12),
}


def build_grid(pattern: str) -> GameOfLife:
    """按指定图案构建初始网格。"""
    if pattern not in PATTERNS:
        raise ValueError(f"未知图案: {pattern!r}，可选: {sorted(PATTERNS)}")
    width, height = PATTERN_DIMS[pattern]
    grid = GameOfLife(width, height)
    for x, y in PATTERNS[pattern]:
        grid.set_alive(x, y)
    return grid


def render(grid: GameOfLife) -> str:
    """把网格渲染为文本：'O' 表示活细胞，'.' 表示死细胞。"""
    lines = []
    for y in range(grid.height):
        row = "".join("O" if grid.is_alive(x, y) else "." for x in range(grid.width))
        lines.append(row)
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Conway's Game of Life 演示（TDD 实现）",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=30,
        metavar="N",
        help="迭代代数上限（默认 30，必须为正整数）",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default="blinker",
        choices=sorted(PATTERNS),
        help="初始图案（默认 blinker）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.generations <= 0:
        print(f"错误: --generations 必须为正整数，收到 {args.generations}", file=sys.stderr)
        return 2

    grid = build_grid(args.pattern)
    print(f"Conway's Game of Life — 图案: {args.pattern}  "
          f"({grid.width}x{grid.height})，共 {args.generations} 代\n")

    for gen in range(args.generations + 1):  # +1：打印初始状态（第 0 代）
        print(f"--- 第 {gen} 代 ---")
        print(render(grid))
        print()
        if gen < args.generations:
            grid = grid.tick()  # 迭代上限由 --generations 保证，必然终止

    return 0


if __name__ == "__main__":
    sys.exit(main())
