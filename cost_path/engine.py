"""C 组搜索引擎：Dijkstra 与 A*，不依赖 GIS 软件或栅格文件格式。

可直接接收甲组的 RasterData 字典，也可接收 rows[row][col] 成本数组。
乙组可传入 step_cost(from_cost, to_cost, movement_factor) 覆盖默认边权。
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
              diagonal_multiplier=SQRT2, allow_corner_cutting=False,
              step_cost=None):
    """计算包含起终点的最小成本路径。

    默认边权 = (出发格成本 + 到达格成本)/2 × 移动系数；正交系数 1，
    斜向系数 diagonal_multiplier。乙组可提供同签名的 step_cost 回调。
    自定义边权时 A* 自动使用零启发式，以确保在非负边权下仍得到最优解。
    禁止切角时，斜移要求相邻的两个正交格均可通行。

    elapsed_ms 仅统计搜索与路径回溯；CostGrid 构造耗时不计入。
    """
    if isinstance(grid, dict):
        grid = CostGrid.from_raster(grid)
    elif not isinstance(grid, CostGrid):
        grid = CostGrid(grid)
    if algorithm not in ("dijkstra", "astar"):
        raise ValueError("algorithm 只能是 dijkstra 或 astar")
    try:
        diagonal_multiplier = float(diagonal_multiplier)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("斜向系数必须是大于等于 1 的有限数") from exc
    if not math.isfinite(diagonal_multiplier) or diagonal_multiplier < 1:
        raise ValueError("斜向系数必须是大于等于 1 的有限数")
    if step_cost is not None and not callable(step_cost):
        raise ValueError("step_cost 必须是可调用的三参数函数")

    source = _cell_index(grid, start, "起点")
    target = _cell_index(grid, goal, "终点")
    width = grid.width
    goal_row, goal_col = divmod(target, width)
    heuristic_scale = grid.min_cost if algorithm == "astar" and step_cost is None else 0.0
    size = grid.height * width
    distances = array("d", [math.inf]) * size
    parents = array("i", [-1]) * size
    parent_edges = array("d", [0.0]) * size
    visited = bytearray(size)
    distances[source] = 0.0
    initial_h = _heuristic(start[0], start[1], goal_row, goal_col,
                           heuristic_scale, diagonal_multiplier)
    frontier = [(initial_h, 0.0, source)]
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
        for row_step, col_step in NEIGHBORS:
            next_row, next_col = row + row_step, col + col_step
            if not (0 <= next_row < grid.height and 0 <= next_col < width):
                continue
            next_index = next_row * width + next_col
            to_cost = grid.values[next_index]
            if to_cost < 0 or visited[next_index]:
                continue
            diagonal = row_step != 0 and col_step != 0
            if diagonal and not allow_corner_cutting:
                if grid.values[row * width + next_col] < 0 or grid.values[next_row * width + col] < 0:
                    continue
            factor = diagonal_multiplier if diagonal else 1.0
            edge = ((from_cost + to_cost) * 0.5 * factor if step_cost is None
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
