"""乙组 · 自带测试（零第三方依赖）

运行：python test_cost_rules.py
或：  python -m unittest -v test_cost_rules

金标准来自 golden_cases.py 的手算解析式，不依赖被测代码推导。
"""

from __future__ import annotations

import math
import unittest

from cost_rules import (
    DEFAULT_CONFIG,
    SQRT2,
    CostConfig,
    can_step,
    distance_factor,
    is_blocked,
    neighbor_steps,
    neighbors,
    path_step_details,
    path_total_cost,
    raster_shape,
    step_cost,
)
from golden_cases import (
    EXPECTED_AVERAGE_SQRT2,
    EXPECTED_DIAGONAL_2X2,
    EXPECTED_DIAGONAL_2X2_K4,
    EXPECTED_DIAGONAL_AT_K4,
    EXPECTED_EDGE_AT_K4,
    EXPECTED_ORTHOGONAL_2X2,
    EXPECTED_TARGET_SQRT2,
    GRID_2X2,
    GRID_4X4,
    GRID_CORNER_BOTH_BLOCKED,
    GRID_CORNER_ONE_BLOCKED,
    PATH_4X4,
    PATH_4X4_EDGE,
    PATH_DIAGONAL_2X2,
    PATH_ORTHOGONAL_2X2,
)


class TestNeighbors(unittest.TestCase):
    def test_center_cell_has_eight_neighbors(self):
        nbs = neighbors((1, 1), raster_shape(GRID_4X4))
        self.assertEqual(len(nbs), 8)
        self.assertEqual([f for _c, f, d in nbs if not d], [1.0] * 4)
        self.assertEqual([f for _c, f, d in nbs if d], [SQRT2] * 4)

    def test_corner_cell_has_three_neighbors(self):
        self.assertEqual(len(neighbors((0, 0), raster_shape(GRID_4X4))), 3)

    def test_custom_diagonal_factor(self):
        cfg = CostConfig(diagonal_factor=4.0)
        nbs = neighbors((1, 1), raster_shape(GRID_4X4), cfg)
        self.assertEqual([f for _c, f, d in nbs if d], [4.0] * 4)

    def test_distance_factor(self):
        self.assertEqual(distance_factor((1, 1), (1, 2)), 1.0)
        self.assertAlmostEqual(distance_factor((1, 1), (2, 2)), SQRT2)


class TestStepCost(unittest.TestCase):
    def test_target_mode_hand_calculation(self):
        self.assertAlmostEqual(step_cost(GRID_4X4, (0, 0), (1, 1)), 5 * SQRT2)
        self.assertAlmostEqual(step_cost(GRID_4X4, (0, 0), (0, 1)), 7.0)

    def test_average_mode_hand_calculation(self):
        cfg = CostConfig(cost_mode="average")
        self.assertAlmostEqual(
            step_cost(GRID_4X4, (2, 2), (3, 3), config=cfg), 4.5 * SQRT2
        )

    def test_explicit_k_positional_argument(self):
        self.assertAlmostEqual(step_cost(GRID_4X4, (0, 0), (1, 1), 4.0), 20.0)

    def test_blocked_target_returns_inf(self):
        self.assertTrue(
            math.isinf(step_cost(GRID_CORNER_BOTH_BLOCKED, (0, 0), (0, 1)))
        )

    def test_invalid_arguments_raise(self):
        with self.assertRaises(ValueError):
            step_cost(GRID_4X4, (0, 0), (9, 9))
        with self.assertRaises(ValueError):
            step_cost(GRID_4X4, (0, 0), (0, 2))

    def test_invalid_config_raises(self):
        with self.assertRaises(ValueError):
            CostConfig(diagonal_factor=0)
        with self.assertRaises(ValueError):
            CostConfig(cost_mode="unknown")


class TestGoldenCases(unittest.TestCase):
    def test_4x4_target_total(self):
        self.assertAlmostEqual(
            path_total_cost(GRID_4X4, PATH_4X4), EXPECTED_TARGET_SQRT2
        )

    def test_4x4_average_total(self):
        self.assertAlmostEqual(
            path_total_cost(GRID_4X4, PATH_4X4, CostConfig(cost_mode="average")),
            EXPECTED_AVERAGE_SQRT2,
        )

    def test_4x4_step_by_step_matches_hand_calculation(self):
        details = path_step_details(GRID_4X4, PATH_4X4)
        self.assertEqual(len(details), 3)
        for row, want in zip(details, [5 * SQRT2, 5 * SQRT2, 4 * SQRT2]):
            self.assertAlmostEqual(row["step_cost"], want)
        self.assertAlmostEqual(details[-1]["cumulative"], EXPECTED_TARGET_SQRT2)

    def test_diagonal_factor_changes_the_best_route(self):
        self.assertAlmostEqual(path_total_cost(GRID_4X4, PATH_4X4), 14 * SQRT2)
        self.assertLess(14 * SQRT2, EXPECTED_EDGE_AT_K4)
        cfg = CostConfig(diagonal_factor=4.0)
        self.assertAlmostEqual(
            path_total_cost(GRID_4X4, PATH_4X4, cfg), EXPECTED_DIAGONAL_AT_K4
        )
        self.assertAlmostEqual(
            path_total_cost(GRID_4X4, PATH_4X4_EDGE, cfg), EXPECTED_EDGE_AT_K4
        )
        self.assertGreater(EXPECTED_DIAGONAL_AT_K4, EXPECTED_EDGE_AT_K4)

    def test_2x2_diagonal_vs_orthogonal(self):
        self.assertAlmostEqual(
            path_total_cost(GRID_2X2, PATH_DIAGONAL_2X2), EXPECTED_DIAGONAL_2X2
        )
        self.assertAlmostEqual(
            path_total_cost(GRID_2X2, PATH_ORTHOGONAL_2X2),
            EXPECTED_ORTHOGONAL_2X2,
        )
        self.assertLess(EXPECTED_DIAGONAL_2X2, EXPECTED_ORTHOGONAL_2X2)
        self.assertAlmostEqual(
            path_total_cost(
                GRID_2X2, PATH_DIAGONAL_2X2, CostConfig(diagonal_factor=4.0)
            ),
            EXPECTED_DIAGONAL_2X2_K4,
        )
        self.assertGreater(EXPECTED_DIAGONAL_2X2_K4, EXPECTED_ORTHOGONAL_2X2)

    def test_include_start(self):
        self.assertAlmostEqual(
            path_total_cost(GRID_4X4, PATH_4X4, CostConfig(include_start=True)),
            EXPECTED_TARGET_SQRT2 + 5.0,
        )

    def test_empty_path_costs_zero(self):
        self.assertEqual(path_total_cost(GRID_4X4, []), 0.0)


class TestObstaclesAndCornerCut(unittest.TestCase):
    def test_nodata_is_blocked(self):
        self.assertTrue(is_blocked(GRID_CORNER_BOTH_BLOCKED, (0, 1)))
        self.assertFalse(is_blocked(GRID_CORNER_BOTH_BLOCKED, (0, 0)))

    def test_both_sides_blocked(self):
        strict = CostConfig(allow_corner_cut=False)
        self.assertTrue(can_step(GRID_CORNER_BOTH_BLOCKED, (0, 0), (1, 1)))
        self.assertFalse(can_step(GRID_CORNER_BOTH_BLOCKED, (0, 0), (1, 1), strict))

    def test_one_side_blocked(self):
        strict = CostConfig(allow_corner_cut=False)
        self.assertTrue(can_step(GRID_CORNER_ONE_BLOCKED, (0, 0), (1, 1)))
        self.assertFalse(can_step(GRID_CORNER_ONE_BLOCKED, (0, 0), (1, 1), strict))

    def test_neighbor_steps_filters_blocked_and_corners(self):
        strict = CostConfig(allow_corner_cut=False)
        self.assertEqual(neighbor_steps(GRID_CORNER_BOTH_BLOCKED, (0, 0), strict), [])
        loose = neighbor_steps(GRID_CORNER_BOTH_BLOCKED, (0, 0))
        self.assertEqual([cell for cell, _w, _f in loose], [(1, 1)])
        self.assertAlmostEqual(loose[0][1], SQRT2)

    def test_neighbor_steps_on_4x4(self):
        steps = neighbor_steps(GRID_4X4, (0, 0))
        self.assertEqual(len(steps), 3)
        costs = {cell: w for cell, w, _f in steps}
        self.assertAlmostEqual(costs[(0, 1)], 7.0)
        self.assertAlmostEqual(costs[(1, 0)], 7.0)
        self.assertAlmostEqual(costs[(1, 1)], 5 * SQRT2)


class TestRasterCompatibility(unittest.TestCase):
    def test_tuple_of_tuples(self):
        grid = tuple(tuple(row) for row in GRID_4X4)
        self.assertAlmostEqual(path_total_cost(grid, PATH_4X4), EXPECTED_TARGET_SQRT2)

    def test_custom_blocked_value(self):
        cfg = CostConfig(blocked_values=frozenset({8.0}))
        self.assertTrue(is_blocked(GRID_4X4, (0, 2), cfg))
        self.assertTrue(math.isinf(step_cost(GRID_4X4, (0, 1), (0, 2), config=cfg)))

    def test_zero_cost_can_be_allowed(self):
        grid = [[1.0, 0.0], [1.0, 1.0]]
        self.assertTrue(is_blocked(grid, (0, 1)))
        self.assertFalse(
            is_blocked(grid, (0, 1), CostConfig(nonpositive_blocked=False))
        )

    def test_default_config_is_immutable(self):
        self.assertEqual(DEFAULT_CONFIG.cost_mode, "target")
        self.assertAlmostEqual(DEFAULT_CONFIG.diagonal_factor, SQRT2)
        self.assertAlmostEqual(DEFAULT_CONFIG.diagonal_factor, math.sqrt(2.0))


class TestTeamRasterData(unittest.TestCase):
    """与甲组 cost_raster.RasterData dict 结构的联调用例。"""

    def setUp(self):
        import cost_rules as cr
        import golden_cases as gc
        self.cr = cr
        self.gc = gc

    def test_rasterdata_dict_matches_bare_matrix(self):
        gc, cr = self.gc, self.cr
        self.assertAlmostEqual(
            cr.path_total_cost(gc.RASTERDATA_TEAM_4X4, gc.PATH_TEAM_4X4),
            gc.EXPECTED_TEAM_TARGET_SQRT2,
        )
        self.assertAlmostEqual(
            cr.path_total_cost(gc.GRID_TEAM_4X4, gc.PATH_TEAM_4X4),
            gc.EXPECTED_TEAM_TARGET_SQRT2,
        )

    def test_rasterdata_shape_and_nodata_config(self):
        self.assertEqual(self.cr.raster_shape(self.gc.RASTERDATA_TEAM_4X4), (4, 4))
        self.assertEqual(
            self.cr.resolve_config(self.gc.RASTERDATA_TEAM_4X4).nodata, -9999.0
        )

    def test_rasterdata_nodata_blocks_center_cell(self):
        gc, cr = self.gc, self.cr
        self.assertTrue(cr.is_blocked(gc.RASTERDATA_TEAM_4X4, (1, 1)))
        self.assertTrue(
            math.isinf(cr.step_cost(gc.RASTERDATA_TEAM_4X4, (0, 0), (1, 1)))
        )

    def test_rasterdata_neighbor_steps_skip_nodata(self):
        steps = self.cr.neighbor_steps(self.gc.RASTERDATA_TEAM_4X4, (0, 0))
        cells = {cell: w for cell, w, _f in steps}
        self.assertNotIn((1, 1), cells)
        self.assertAlmostEqual(cells[(0, 1)], 7.0)
        self.assertAlmostEqual(cells[(1, 0)], 4.0)

    def test_explicit_config_overrides_rasterdata(self):
        cfg = CostConfig(diagonal_factor=4.0)
        self.assertAlmostEqual(
            self.cr.path_total_cost(
                self.gc.RASTERDATA_TEAM_4X4, self.gc.PATH_TEAM_4X4, cfg
            ),
            23.0 + 4.0 * 4.0,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
