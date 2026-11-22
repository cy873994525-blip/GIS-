"""C 组搜索引擎：Dijkstra 与 A*，不依赖 GIS 软件或栅格文件格式。

可直接接收甲组的 RasterData 字典，也可接收 rows[row][col] 成本数组。
默认规则与乙组 CostConfig 对齐；团队接口可直接使用乙组 neighbor_steps。
丁组将返回的 path_cells 映射到栅格中心坐标，制作矢量图层。
"""

from array import array
from dataclasses import dataclass
import heapq
import math
from time import perf_counter


SQRT2 = math.sqrt(2.0)
NEIGHBORS = ((-1, 0), (0, -1), (0, 1), (1, 0),
             (-1, -1), (-1, 1), (1, -1), (1, 1))


class NoRouteError(Exception):
    """起点和终点有效，但在当前障碍与切角规则下没有路径。"""


@dataclass(frozen=True)
class RouteResult:
    path_cells: tuple
    step_costs: tuple
    total_cost: float
    length_cells: float
    expanded_nodes: int
    elapsed_ms: float
    algorithm: str

    def to_dict(self):
        """给插件对话框/JSON 接口使用的普通 Python 值。"""
        return {
            "path_cells": [list(cell) for cell in self.path_cells],
            "step_costs": list(self.step_costs),
            "total_cost": self.total_cost,
            "length_cells": self.length_cells,
            "expanded_nodes": self.expanded_nodes,
            "elapsed_ms": self.elapsed_ms,
            "algorithm": self.algorithm,
        }


class CostGrid:
    """一次校验并压平输入，供多次搜索/公平测速复用。"""

    __slots__ = ("height", "width", "values", "min_cost")

    def __init__(self, rows, nodata=None):
        try:
            height = len(rows)
            width = len(rows[0]) if height else 0
        except (TypeError, IndexError) as exc:
            raise ValueError("栅格必须是非空的二维数组") from exc
        if height == 0 or width == 0:
            raise ValueError("栅格必须至少有一行一列")
        if nodata is not None:
            try:
                nodata = float(nodata)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("NoData 标记必须是有限数值或 None") from exc
            if not math.isfinite(nodata):
                raise ValueError("NoData 标记必须是有限数值或 None")
        values = array("d")
        min_cost = math.inf
        for row_index, row in enumerate(rows):
            try:
                row_width = len(row)
            except TypeError as exc:
                raise ValueError("第 {} 行不是数组".format(row_index)) from exc
            if row_width != width:
                raise ValueError("第 {} 行长度不一致；栅格必须是矩形".format(row_index))
            for col_index, raw in enumerate(row):
                if raw is None:
                    values.append(-1.0)
                    continue
                if isinstance(raw, bool):
                    raise ValueError("第 {} 行第 {} 列成本不能是布尔值".format(row_index, col_index))
                try:
                    value = float(raw)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("第 {} 行第 {} 列成本不是数值".format(row_index, col_index)) from exc
                if nodata is not None and math.isclose(value, nodata, rel_tol=0.0, abs_tol=1e-9):
                    values.append(-1.0)
                    continue
                if not math.isfinite(value) or value < 0:
                    raise ValueError("第 {} 行第 {} 列成本必须是有限非负数；NoData 请用 None".format(
                        row_index, col_index))
                values.append(value)
                if value < min_cost:
                    min_cost = value
        self.height = height
        self.width = width
        self.values = values
        self.min_cost = min_cost

    @classmethod
    def from_raster(cls, raster):
        """读取甲组 cost_raster.py 的 RasterData，不改变原始矩阵或空间元数据。"""
        if not isinstance(raster, dict) or not all(
                key in raster for key in ("rows", "cols", "values", "nodata")):
            raise ValueError("甲组 RasterData 缺少 rows/cols/values/nodata 字段")
        grid = cls(raster["values"], nodata=raster["nodata"])
        if grid.height != raster["rows"] or grid.width != raster["cols"]:
            raise ValueError("RasterData 行列数与 values 不一致")
        return grid


def _cell_index(grid, cell, label):
    if (not isinstance(cell, (tuple, list)) or len(cell) != 2
            or any(isinstance(value, bool) or not isinstance(value, int) for value in cell)):
        raise ValueError("{}必须是 (行, 列) 整数坐标".format(label))
    row, col = cell
    if not (0 <= row < grid.height and 0 <= col < grid.width):
        raise ValueError("{}超出栅格边界".format(label))
    index = row * grid.width + col
    if grid.values[index] < 0:
        raise ValueError("{}位于 NoData 障碍格".format(label))
    return index


def _heuristic(row, col, goal_row, goal_col, min_cost, diagonal_multiplier):
    row_delta = abs(goal_row - row)
    col_delta = abs(goal_col - col)
    diagonal = min(row_delta, col_delta)
    # k > 2 时两次正交移动不会比一次斜移更贵。
    return min_cost * (row_delta + col_delta + (min(diagonal_multiplier, 2.0) - 2.0) * diagonal)


def find_path(grid, start, goal, *, algorithm="dijkstra",
              diagonal_multiplier=SQRT2, allow_corner_cutting=True,
              cost_mode="target", include_start=False,
              nonpositive_blocked=True, blocked_values=(),
              step_cost=None, neighbor_provider=None, heuristic_min_cost=None):
    """计算包含起终点的最小成本路径。

    默认边权 = 进入格成本 × 移动系数，与乙组默认 CostConfig 一致。
    cost_mode="average" 时为相邻两格均值 × 移动系数。
    乙组可通过 neighbor_provider(cell) 提供 [(邻格, 边权, 系数)]；
    此时使用乙组过滤后的邻格，A* 默认零启发式以保证最优性。
    heuristic_min_cost 只供已证明边权下界的邻格提供方使用。
    step_cost 为兼容第一周的三参数回调 (from_cost, to_cost, factor)。

    elapsed_ms 仅统计搜索与路径回溯；CostGrid 构造耗时不计入。
    """
    if isinstance(grid, dict):
        grid = CostGrid.from_raster(grid)
    elif not isinstance(grid, CostGrid):
        grid = CostGrid(grid, nodata=-9999.0)
    if algorithm not in ("dijkstra", "astar"):
        raise ValueError("algorithm 只能是 dijkstra 或 astar")
    try:
        diagonal_multiplier = float(diagonal_multiplier)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("斜向系数必须是大于 0 的有限数") from exc
    if not math.isfinite(diagonal_multiplier) or diagonal_multiplier <= 0:
        raise ValueError("斜向系数必须是大于 0 的有限数")
    if cost_mode not in ("target", "average"):
        raise ValueError("cost_mode 只能是 target 或 average")
    if step_cost is not None and not callable(step_cost):
        raise ValueError("step_cost 必须是可调用的三参数函数")
    if neighbor_provider is not None and not callable(neighbor_provider):
        raise ValueError("neighbor_provider 必须是可调用的邻格函数")
    if step_cost is not None and neighbor_provider is not None:
        raise ValueError("step_cost 和 neighbor_provider 不能同时提供")
    try:
        blocked_values = frozenset(float(value) for value in blocked_values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("blocked_values 必须是有限数值集合") from exc
    if any(not math.isfinite(value) for value in blocked_values):
        raise ValueError("blocked_values 必须是有限数值集合")
    if heuristic_min_cost is not None:
        try:
            heuristic_min_cost = float(heuristic_min_cost)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("heuristic_min_cost 必须是有限非负数") from exc
        if not math.isfinite(heuristic_min_cost) or heuristic_min_cost < 0:
            raise ValueError("heuristic_min_cost 必须是有限非负数")

    size = grid.height * grid.width
    blocked = bytearray(size)
    min_passable_cost = math.inf
    for index, value in enumerate(grid.values):
        if value < 0 or value in blocked_values or nonpositive_blocked and value <= 0:
            blocked[index] = 1
        elif value < min_passable_cost:
            min_passable_cost = value

    source = _cell_index(grid, start, "起点")
    target = _cell_index(grid, goal, "终点")
    if blocked[source] or blocked[target]:
        raise ValueError("起点或终点位于不可通行的格子")
    width = grid.width
    goal_row, goal_col = divmod(target, width)
    heuristic_scale = 0.0
    if algorithm == "astar" and diagonal_multiplier >= 1:
        if neighbor_provider is not None:
            heuristic_scale = heuristic_min_cost or 0.0
        elif step_cost is None:
            heuristic_scale = min_passable_cost
    distances = array("d", [math.inf]) * size
    parents = array("i", [-1]) * size
    parent_edges = array("d", [0.0]) * size
    visited = bytearray(size)
    distances[source] = grid.values[source] if include_start else 0.0
    initial_h = _heuristic(start[0], start[1], goal_row, goal_col,
                           heuristic_scale, diagonal_multiplier)
    frontier = [(distances[source] + initial_h, distances[source], source)]
    expanded_nodes = 0
    started = perf_counter()

    while frontier:
        _, current_cost, current = heapq.heappop(frontier)
        if visited[current] or current_cost > distances[current]:
            continue
        visited[current] = 1
        expanded_nodes += 1
        if current == target:
            break
        row, col = divmod(current, width)
        from_cost = grid.values[current]
        if neighbor_provider is not None:
            for next_cell, edge, _factor in neighbor_provider((row, col)):
                if (not isinstance(next_cell, (tuple, list)) or len(next_cell) != 2
                        or any(isinstance(value, bool) or not isinstance(value, int)
                               for value in next_cell)):
                    raise ValueError("neighbor_provider 返回了非法邻格")
                next_row, next_col = next_cell
                if (not (0 <= next_row < grid.height and 0 <= next_col < width)
                        or max(abs(next_row - row), abs(next_col - col)) != 1):
                    raise ValueError("neighbor_provider 返回了越界或不相邻的格子")
                next_index = next_row * width + next_col
                if blocked[next_index] or visited[next_index]:
                    continue
                try:
                    edge = float(edge)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("neighbor_provider 必须返回有限非负边权") from exc
                if not math.isfinite(edge) or edge < 0:
                    raise ValueError("neighbor_provider 必须返回有限非负边权")
                candidate = current_cost + edge
                if not math.isfinite(candidate):
                    raise ValueError("累计成本溢出；请检查输入成本")
                if candidate < distances[next_index]:
                    distances[next_index] = candidate
                    parents[next_index] = current
                    parent_edges[next_index] = edge
                    estimate = _heuristic(next_row, next_col, goal_row, goal_col,
                                          heuristic_scale, diagonal_multiplier)
                    heapq.heappush(frontier, (candidate + estimate, candidate, next_index))
            continue
        for row_step, col_step in NEIGHBORS:
            next_row, next_col = row + row_step, col + col_step
            if not (0 <= next_row < grid.height and 0 <= next_col < width):
                continue
            next_index = next_row * width + next_col
            to_cost = grid.values[next_index]
            if blocked[next_index] or visited[next_index]:
                continue
            diagonal = row_step != 0 and col_step != 0
            if diagonal and not allow_corner_cutting:
                if blocked[row * width + next_col] or blocked[next_row * width + col]:
                    continue
            factor = diagonal_multiplier if diagonal else 1.0
            edge = ((to_cost if cost_mode == "target" else (from_cost + to_cost) * 0.5) * factor
                    if step_cost is None
                    else step_cost(from_cost, to_cost, factor))
            if isinstance(edge, bool):
                raise ValueError("step_cost 必须返回有限非负数")
            try:
                edge = float(edge)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("step_cost 必须返回有限非负数") from exc
            if not math.isfinite(edge) or edge < 0:
                raise ValueError("step_cost 必须返回有限非负数")
            candidate = current_cost + edge
            if not math.isfinite(candidate):
                raise ValueError("累计成本溢出；请检查输入成本")
            if candidate < distances[next_index]:
                distances[next_index] = candidate
                parents[next_index] = current
                parent_edges[next_index] = edge
                estimate = _heuristic(next_row, next_col, goal_row, goal_col,
                                      heuristic_scale, diagonal_multiplier)
                heapq.heappush(frontier, (candidate + estimate, candidate, next_index))

    if not visited[target]:
        raise NoRouteError("起点到终点没有可通行的路径")
    reversed_cells = []
    reversed_edges = []
    length_cells = 0.0
    current = target
    while current != -1:
        reversed_cells.append(divmod(current, width))
        parent = parents[current]
        if parent != -1:
            reversed_edges.append(parent_edges[current])
            row, col = divmod(current, width)
            parent_row, parent_col = divmod(parent, width)
            length_cells += SQRT2 if row != parent_row and col != parent_col else 1.0
        current = parent
    return RouteResult(tuple(reversed(reversed_cells)),
                       tuple(reversed(reversed_edges)), distances[target],
                       length_cells, expanded_nodes,
                       (perf_counter() - started) * 1000.0, algorithm)
