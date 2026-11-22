"""丙组准确性测试：手算、边界，以及独立 Bellman-Ford 小网格对照。"""

import math
import random
import unittest
from pathlib import Path

from cost_path import CostGrid, NoRouteError, find_path
from cost_raster import is_nodata, load_raster_file
from cost_rules import CostConfig, path_total_cost
from contract import shortest_path
from golden_cases import (EXPECTED_AVERAGE_SQRT2, EXPECTED_TARGET_SQRT2,
                          EXPECTED_TEAM_TARGET_SQRT2, GRID_4X4, PATH_4X4)


def bellman_ford_reference(rows, start, goal, diagonal_multiplier=math.sqrt(2)):
    """只用于小网格测试；刻意不用优先队列或搜索引擎的邻接实现。"""
    height, width = len(rows), len(rows[0])
    distance = {start: 0.0}
    for _ in range(height * width - 1):
        changed = False
        for row in range(height):
            for col in range(width):
                if (row, col) not in distance:
                    continue
                for next_row in range(max(0, row - 1), min(height, row + 2)):
                    for next_col in range(max(0, col - 1), min(width, col + 2)):
                        if (next_row, next_col) == (row, col) or rows[next_row][next_col] is None:
                            continue
                        diagonal = next_row != row and next_col != col
                        if diagonal and (rows[row][next_col] is None or rows[next_row][col] is None):
                            continue
                        factor = diagonal_multiplier if diagonal else 1.0
                        cost = distance[(row, col)] + (rows[row][col] + rows[next_row][next_col]) / 2 * factor
                        if cost < distance.get((next_row, next_col), math.inf):
                            distance[(next_row, next_col)] = cost
                            changed = True
        if not changed:
            break
    return distance.get(goal)


class CostPathTests(unittest.TestCase):
    def test_b_group_golden_cases_and_contract(self):
        for algorithm in ("dijkstra", "astar"):
            with self.subTest(algorithm=algorithm):
                direct = find_path(GRID_4X4, (0, 0), (3, 3), algorithm=algorithm)
                joined = shortest_path(GRID_4X4, (0, 0), (3, 3), algorithm=algorithm)
                self.assertEqual(list(direct.path_cells), PATH_4X4)
                self.assertEqual(joined.path, PATH_4X4)
                self.assertAlmostEqual(direct.total_cost, EXPECTED_TARGET_SQRT2)
                self.assertAlmostEqual(joined.stats["total_cost"], EXPECTED_TARGET_SQRT2)
                self.assertEqual(joined.stats["steps"], 3)
                self.assertEqual(len(joined.stats["step_details"]), 3)
                self.assertAlmostEqual(joined.stats["step_details"][-1]["cumulative"],
                                       EXPECTED_TARGET_SQRT2)
                average = shortest_path(
                    GRID_4X4, (0, 0), (3, 3),
                    config=CostConfig(cost_mode="average"), algorithm=algorithm)
                self.assertAlmostEqual(average.stats["total_cost"], EXPECTED_AVERAGE_SQRT2)

    def test_contract_config_and_input_errors(self):
        grid = [[1, 2], [2, 1]]
        for algorithm in ("dijkstra", "astar"):
            result = shortest_path(grid, (0, 0), (1, 1),
                                   config=CostConfig(diagonal_factor=4), algorithm=algorithm)
            self.assertEqual(result.stats["total_cost"], 3)
            self.assertEqual(result.stats["steps"], 2)
        with self.assertRaises(ValueError):
            shortest_path(grid, (-1, 0), (1, 1))
        with self.assertRaises(ValueError):
            shortest_path(grid, (0, 0), (2, 0))
        with self.assertRaises(NoRouteError):
            shortest_path([[1, -9999, 1]], (0, 0), (0, 2))

    def test_a_group_rasterdata_and_common_samples(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("cost_grid_4x4.json", "cost_grid_5x5.json"):
            with self.subTest(sample=name):
                raster = load_raster_file(root / "sample_data" / name)
                rows = [[None if is_nodata(raster, row, col) else raster["values"][row][col]
                         for col in range(raster["cols"])] for row in range(raster["rows"])]
                start, goal = (0, 0), (raster["rows"] - 1, raster["cols"] - 1)
                original_values = [row[:] for row in raster["values"]]
                for algorithm in ("dijkstra", "astar"):
                    result = find_path(raster, start, goal, algorithm=algorithm)
                    if name == "cost_grid_4x4.json":
                        self.assertAlmostEqual(result.total_cost, EXPECTED_TEAM_TARGET_SQRT2)
                    self.assertAlmostEqual(result.total_cost,
                                           path_total_cost(raster, result.path_cells))
                    self.assertTrue(all(not is_nodata(raster, *cell) for cell in result.path_cells))
                self.assertEqual(raster["values"], original_values)

    def test_hand_calculated_diagonal(self):
        grid = [[5, 7], [8, 4]]
        expected = (5 + 4) / 2 * math.sqrt(2)
        for algorithm in ("dijkstra", "astar"):
            with self.subTest(algorithm=algorithm):
                result = find_path(grid, (0, 0), (1, 1), algorithm=algorithm,
                                   cost_mode="average")
                self.assertEqual(result.path_cells, ((0, 0), (1, 1)))
                self.assertAlmostEqual(result.total_cost, expected)
                self.assertEqual(len(result.step_costs), 1)
                self.assertAlmostEqual(result.length_cells, math.sqrt(2))
                self.assertEqual(result.to_dict()["path_cells"], [[0, 0], [1, 1]])

    def test_corner_cutting_is_configurable(self):
        grid = [[1, None], [1, 1]]
        result = find_path(grid, (0, 0), (1, 1), allow_corner_cutting=False)
        self.assertEqual(result.path_cells, ((0, 0), (1, 0), (1, 1)))
        self.assertEqual(result.total_cost, 2.0)
        allowed = find_path(grid, (0, 0), (1, 1))
        self.assertEqual(allowed.path_cells, ((0, 0), (1, 1)))
        self.assertAlmostEqual(allowed.total_cost, math.sqrt(2))

    def test_custom_rule_keeps_astar_exact(self):
        grid = [[5, 7], [8, 4]]
        rule = lambda _from, to, factor: to * factor
        dijkstra = find_path(grid, (0, 0), (1, 1), step_cost=rule)
        astar = find_path(grid, (0, 0), (1, 1), algorithm="astar", step_cost=rule)
        self.assertAlmostEqual(dijkstra.total_cost, 4 * math.sqrt(2))
        self.assertAlmostEqual(astar.total_cost, dijkstra.total_cost)

    def test_zero_cost_and_same_cell(self):
        grid = CostGrid([[0, 0], [0, 0]])
        for algorithm in ("dijkstra", "astar"):
            result = find_path(grid, (0, 0), (1, 1), algorithm=algorithm,
                               nonpositive_blocked=False)
            self.assertEqual(result.total_cost, 0)
            self.assertEqual(sum(result.step_costs), 0)
        same = find_path(grid, (1, 1), (1, 1), nonpositive_blocked=False)
        self.assertEqual(same.path_cells, ((1, 1),))
        self.assertEqual(same.step_costs, ())
        self.assertEqual(same.length_cells, 0)

    def test_no_path_and_invalid_inputs(self):
        with self.assertRaises(NoRouteError):
            find_path([[1, None, 1], [None, None, None]], (0, 0), (0, 2))
        for rows in ([[1], [1, 2]], [[-1]], [[math.nan]], [[True]]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                CostGrid(rows)
        with self.assertRaises(ValueError):
            find_path([[1, None]], (0, 0), (0, 1))
        with self.assertRaises(ValueError):
            find_path([[1]], (0, 0), (0, 0), diagonal_multiplier=0)
        with self.assertRaises(ValueError):
            find_path([[1]], (0, 0), (0, 0), algorithm="unknown")
        with self.assertRaises(ValueError):
            find_path([[1, 1]], (0, 0), (0, 1), step_cost=lambda *_: -1)

    def test_random_small_grids_match_independent_reference(self):
        rng = random.Random(20261116)
        for case in range(30):
            rows = [[None if rng.random() < 0.22 else rng.randint(0, 9)
                     for _ in range(4)] for _ in range(4)]
            rows[0][0] = 1
            rows[3][3] = 1
            for multiplier in (1.0, math.sqrt(2), 2.5):
                expected = bellman_ford_reference(rows, (0, 0), (3, 3), multiplier)
                for algorithm in ("dijkstra", "astar"):
                    with self.subTest(case=case, multiplier=multiplier, algorithm=algorithm):
                        if expected is None:
                            with self.assertRaises(NoRouteError):
                                find_path(rows, (0, 0), (3, 3), algorithm=algorithm,
                                          diagonal_multiplier=multiplier,
                                          cost_mode="average", allow_corner_cutting=False,
                                          nonpositive_blocked=False)
                            continue
                        result = find_path(rows, (0, 0), (3, 3), algorithm=algorithm,
                                           diagonal_multiplier=multiplier,
                                           cost_mode="average", allow_corner_cutting=False,
                                           nonpositive_blocked=False)
                        self.assertTrue(math.isclose(result.total_cost, expected, rel_tol=1e-10))
                        self.assertTrue(math.isclose(sum(result.step_costs), expected, rel_tol=1e-10))
                        self.assertEqual(result.path_cells[0], (0, 0))
                        self.assertEqual(result.path_cells[-1], (3, 3))
                        for (row, col), (next_row, next_col), edge in zip(
                                result.path_cells, result.path_cells[1:], result.step_costs):
                            row_step, col_step = abs(next_row - row), abs(next_col - col)
                            self.assertEqual(max(row_step, col_step), 1)
                            self.assertIsNotNone(rows[next_row][next_col])
                            if row_step and col_step:
                                self.assertIsNotNone(rows[row][next_col])
                                self.assertIsNotNone(rows[next_row][col])
                            factor = multiplier if row_step and col_step else 1.0
                            self.assertAlmostEqual(
                                edge, (rows[row][col] + rows[next_row][next_col]) / 2 * factor)


if __name__ == "__main__":
    unittest.main()
