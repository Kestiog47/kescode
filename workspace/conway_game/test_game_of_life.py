"""TDD 测试套件：Conway's Game of Life。

红阶段：本文件先于实现编写，运行时应失败（game_of_life 尚未实现）。
绿阶段：实现 game_of_life.GameOfLife 后，所有测试应全部通过。

接口约定（由本测试套件定义）：
    grid = GameOfLife(width, height)
    grid.set_alive(x, y)          # 将 (x, y) 设为活细胞
    grid.is_alive(x, y) -> bool   # 越界返回 False
    grid.tick() -> GameOfLife     # 返回下一代（不可变：不改动原网格）
    grid.width / grid.height      # 网格尺寸
"""

import unittest

from game_of_life import GameOfLife


def alive_set(grid):
    """返回网格中所有活细胞的 {(x, y)} 集合。"""
    return {
        (x, y)
        for x in range(grid.width)
        for y in range(grid.height)
        if grid.is_alive(x, y)
    }


def build(alive_cells, width=5, height=5):
    grid = GameOfLife(width, height)
    for x, y in alive_cells:
        grid.set_alive(x, y)
    return grid


class UnderpopulationTests(unittest.TestCase):
    """规则 1：活细胞邻居数 < 2 时死亡（孤独）。"""

    def test_live_cell_with_zero_neighbours_dies(self):
        grid = build([(2, 2)])
        nxt = grid.tick()
        self.assertFalse(nxt.is_alive(2, 2))

    def test_live_cell_with_one_neighbour_dies(self):
        grid = build([(2, 2), (2, 3)])
        nxt = grid.tick()
        self.assertFalse(nxt.is_alive(2, 2))
        self.assertFalse(nxt.is_alive(2, 3))

    def test_isolated_corner_cell_dies(self):
        # 位于角落的孤立细胞同样死亡（边界邻居计数正确）
        grid = build([(0, 0)])
        nxt = grid.tick()
        self.assertFalse(nxt.is_alive(0, 0))


class SurvivalTests(unittest.TestCase):
    """规则 2：活细胞邻居数为 2 或 3 时存活。"""

    def test_live_cell_with_two_neighbours_survives(self):
        grid = build([(2, 1), (2, 2), (2, 3)])
        nxt = grid.tick()
        self.assertTrue(nxt.is_alive(2, 2))

    def test_live_cell_with_three_neighbours_survives(self):
        # (1,1) 为活细胞，邻居 (1,2),(2,1),(2,2) 恰好 3 个
        grid = build([(1, 1), (1, 2), (2, 1), (2, 2)])
        nxt = grid.tick()
        self.assertTrue(nxt.is_alive(1, 1))


class OverpopulationTests(unittest.TestCase):
    """规则 3：活细胞邻居数 > 3 时死亡（过密）。"""

    def test_live_cell_with_four_neighbours_dies(self):
        # 十字形：中心 (2,2) 有 4 个邻居 -> 死亡
        grid = build([(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)])
        nxt = grid.tick()
        self.assertFalse(nxt.is_alive(2, 2))

    def test_live_cell_with_eight_neighbours_dies(self):
        # 3x3 全活：中心有 8 个邻居 -> 死亡
        cells = [(x, y) for x in (1, 2, 3) for y in (1, 2, 3)]
        grid = build(cells)
        nxt = grid.tick()
        self.assertFalse(nxt.is_alive(2, 2))


class ReproductionTests(unittest.TestCase):
    """规则 4：死细胞邻居数恰好为 3 时繁殖。"""

    def test_dead_cell_with_three_neighbours_is_born(self):
        # 左上角 L 形：(1,1) 为死细胞，邻居 (0,0),(0,1),(1,0) 恰好 3 个 -> 复活
        grid = build([(0, 0), (0, 1), (1, 0)], width=3, height=3)
        nxt = grid.tick()
        self.assertTrue(nxt.is_alive(1, 1))

    def test_dead_cell_with_two_neighbours_stays_dead(self):
        # 双细胞：死细胞 (1,2) 有 2 个邻居 -> 不复活
        grid = build([(2, 2), (2, 3)])
        nxt = grid.tick()
        self.assertFalse(nxt.is_alive(1, 2))

    def test_dead_cell_with_four_neighbours_stays_dead(self):
        # 四角形：(2,1) 死细胞有 4 个邻居 -> 不复活
        grid = build([(1, 1), (3, 1), (1, 2), (3, 2)])
        nxt = grid.tick()
        self.assertFalse(nxt.is_alive(2, 1))
        self.assertFalse(nxt.is_alive(2, 2))


class BoundaryAndPatternTests(unittest.TestCase):
    """边界情况与经典图案。"""

    def test_empty_grid_stays_empty(self):
        grid = GameOfLife(4, 4)
        nxt = grid.tick()
        self.assertEqual(alive_set(nxt), set())

    def test_all_dead_grid_stays_all_dead(self):
        grid = GameOfLife(3, 3)
        nxt = grid.tick()
        self.assertEqual(alive_set(nxt), set())

    def test_block_still_life_is_unchanged(self):
        block = {(1, 1), (2, 1), (1, 2), (2, 2)}
        grid = build(block, width=4, height=4)
        nxt = grid.tick()
        self.assertEqual(alive_set(nxt), block)

    def test_blinker_oscillates_with_period_two(self):
        # 水平 blinker -> 垂直 -> 水平
        grid = build([(1, 2), (2, 2), (3, 2)], width=5, height=5)
        nxt = grid.tick()
        self.assertEqual(alive_set(nxt), {(2, 1), (2, 2), (2, 3)})
        nxt2 = nxt.tick()
        self.assertEqual(alive_set(nxt2), {(1, 2), (2, 2), (3, 2)})

    def test_glider_moves_diagonally(self):
        # glider 每 4 代平移一个对角单位
        grid = build([(1, 0), (2, 1), (0, 2), (1, 2), (2, 2)], width=6, height=6)
        gen1 = grid.tick()
        self.assertEqual(alive_set(gen1), {(0, 1), (1, 2), (1, 3), (2, 1), (2, 2)})
        gen4 = gen1.tick().tick().tick()
        self.assertEqual(
            alive_set(gen4),
            {(2, 1), (3, 2), (1, 3), (2, 3), (3, 3)},
        )

    def test_corner_adjacency_reproduction(self):
        # 左上角 L 形 -> 2x2 block（验证边界相邻计数）
        grid = build([(0, 0), (0, 1), (1, 0)], width=3, height=3)
        nxt = grid.tick()
        self.assertEqual(alive_set(nxt), {(0, 0), (0, 1), (1, 0), (1, 1)})


class ImmutabilityTests(unittest.TestCase):
    """tick 必须不可变：不修改原始网格。"""

    def test_tick_does_not_modify_original_grid(self):
        block = {(1, 1), (2, 1), (1, 2), (2, 2)}
        grid = build(block, width=4, height=4)
        before = alive_set(grid)
        grid.tick()
        self.assertEqual(alive_set(grid), before)

    def test_tick_returns_new_instance(self):
        grid = build([(2, 2)])
        nxt = grid.tick()
        self.assertIsNot(grid, nxt)

    def test_is_alive_out_of_bounds_returns_false(self):
        grid = build([(0, 0)], width=2, height=2)
        self.assertFalse(grid.is_alive(-1, 0))
        self.assertFalse(grid.is_alive(0, 2))
        self.assertFalse(grid.is_alive(5, 5))


if __name__ == "__main__":
    unittest.main()
