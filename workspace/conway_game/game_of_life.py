"""Conway's Game of Life 核心实现。

接口（由 test_game_of_life.py 定义并约束）：
    grid = GameOfLife(width, height)
    grid.set_alive(x, y)          # 将 (x, y) 设为活细胞
    grid.is_alive(x, y) -> bool   # 越界返回 False
    grid.tick() -> GameOfLife     # 返回下一代（不可变：不改动原网格）
    grid.width / grid.height      # 网格尺寸

规则（每代同时应用）：
    1. 活细胞邻居数 < 2  -> 死亡（孤独）
    2. 活细胞邻居数为 2 或 3 -> 存活
    3. 活细胞邻居数 > 3  -> 死亡（过密）
    4. 死细胞邻居数恰好为 3 -> 繁殖
"""

from __future__ import annotations

from typing import Iterator, Tuple

Cell = Tuple[int, int]


class GameOfLife:
    """基于稀疏集合的 Game of Life 网格。"""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width 和 height 必须为正整数")
        self.width = width
        self.height = height
        self._alive: set[Cell] = set()

    def set_alive(self, x: int, y: int) -> None:
        """将 (x, y) 标记为活细胞；越界坐标被忽略。"""
        if 0 <= x < self.width and 0 <= y < self.height:
            self._alive.add((x, y))

    def is_alive(self, x: int, y: int) -> bool:
        """查询 (x, y) 是否为活细胞；越界返回 False。"""
        return (x, y) in self._alive

    def live_cells(self) -> Iterator[Cell]:
        """迭代当前所有活细胞的坐标。"""
        return iter(self._alive)

    def tick(self) -> "GameOfLife":
        """计算并返回下一代网格（不可变：不修改当前网格）。"""
        nxt = GameOfLife(self.width, self.height)
        for x in range(self.width):
            for y in range(self.height):
                neighbours = self._count_neighbours(x, y)
                if self.is_alive(x, y):
                    if neighbours in (2, 3):          # 规则 1/2/3
                        nxt.set_alive(x, y)
                elif neighbours == 3:                 # 规则 4
                    nxt.set_alive(x, y)
        return nxt

    def _count_neighbours(self, x: int, y: int) -> int:
        """统计 (x, y) 周围 8 个方向上的活细胞数量（边界外视为死）。"""
        count = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                if (x + dx, y + dy) in self._alive:
                    count += 1
        return count
