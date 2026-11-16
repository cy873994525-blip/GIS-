"""乙组 · 成本规则层（GIS 算法课程作业 2）

本模块只回答一个问题：从格 a 走到相邻格 b，这一步要付多少代价。
它不负责搜索路径、不负责读文件、不负责画图。

对全组暴露的接口
-----------------
    step_cost(cost, a, b, k)              -> float          单步代价（契约签名）
    neighbor_steps(cost, cell, cfg)       -> [(next, w, f)] 供丙组 Dijkstra / A* 遍历
    path_total_cost(cost, path, cfg)      -> float          沿给定路径累加总成本
    path_step_details(cost, path, cfg)    -> list[dict]     逐段明细，供丁组写矢量图层字段

成本口径（全部可配置，见 CostConfig）
-----------------------------------
    * 8 邻域；正交距离系数 1.0，斜向距离系数 k（默认 sqrt(2)）
    * 单步代价 w = 进入格成本 * 距离系数                     cost_mode="target"（默认）
               w = (出发格成本 + 进入格成本)/2 * 距离系数    cost_mode="average"
    * 起点格默认不计入总成本（include_start=False）
    * NoData / 非有限值 / 非正值 / blocked_values 均视为障碍
    * 被阻挡或不可通行的一步返回 math.inf（不抛异常，便于搜索层直接跳过）
    * allow_corner_cut=False 时，对角穿越的任一侧角格被阻挡即禁止该步

零第三方依赖，且兼容两种输入：
    * 甲组 cost_raster.build_raster() 返回的 RasterData dict（含 values / nodata）
    * 裸二维矩阵：list[list[float]]、tuple 或 numpy 二维数组
传入 RasterData 时会自动采用其中的 nodata 值，无需手工拆 values。

待四人碰头确认后冻结：斜向系数 k 的具体取值、target 还是 average。
在此之前两种口径都已实现并各有金标准，切换只需改 CostConfig。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Iterable

SQRT2 = math.sqrt(2.0)

Cell = tuple[int, int]
Raster = Any  # list[list[float]] | tuple | numpy.ndarray，统一用 cost[r][c] 访问


@dataclass(frozen=True)
class CostConfig:
    """成本规则的全部开关。改这里就能切换口径，不必改算法代码。"""

    diagonal_factor: float = SQRT2
    cost_mode: str = "target"  # "target" | "average"
    include_start: bool = False
    allow_corner_cut: bool = True
    nodata: float = -9999.0
    blocked_values: frozenset[float] = frozenset()
    nonpositive_blocked: bool = True

    def __post_init__(self) -> None:
        if self.diagonal_factor <= 0:
            raise ValueError("diagonal_factor 必须为正数")
        if self.cost_mode not in ("target", "average"):
            raise ValueError("cost_mode 只能是 'target' 或 'average'")


DEFAULT_CONFIG = CostConfig()


def as_matrix(cost: Raster):
    """统一取到二维成本矩阵。

    兼容甲组 RasterData dict（含 values）与裸二维矩阵；
    后者可以是 list / tuple / numpy 数组，只要支持 cost[r][c]。
    """
    if isinstance(cost, dict) and "values" in cost:
        return cost["values"]
    return cost


def resolve_config(cost: Raster, config: CostConfig | None = None) -> CostConfig:
    """解析规则配置。

    未显式传 config 时，自动采用甲组 RasterData 里的 nodata 值，
    避免两组 NoData 口径不一致；显式传入的 config 始终优先。
    """
    if config is not None:
        return config
    if isinstance(cost, dict) and cost.get("nodata") is not None:
        return replace(DEFAULT_CONFIG, nodata=float(cost["nodata"]))
    return DEFAULT_CONFIG


def raster_shape(cost: Raster) -> tuple[int, int]:
    """返回 (行数, 列数)。"""
    m = as_matrix(cost)
    rows = len(m)
    if rows == 0:
        return (0, 0)
    return (rows, len(m[0]))


def in_bounds(shape: tuple[int, int], cell: Cell) -> bool:
    return 0 <= cell[0] < shape[0] and 0 <= cell[1] < shape[1]


def cell_value(cost: Raster, cell: Cell) -> float | None:
    """读取格值并规范化为 float；NoData / None / nan / inf 返回 None。"""
    r, c = cell
    v = as_matrix(cost)[r][c]
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def is_blocked(cost: Raster, cell: Cell, config: CostConfig | None = None) -> bool:
    """该格是否为障碍（不可进入）。"""
    cfg = resolve_config(cost, config)
    v = cell_value(cost, cell)
    if v is None or v == cfg.nodata or v in cfg.blocked_values:
        return True
    return bool(cfg.nonpositive_blocked and v <= 0)


def is_adjacent(a: Cell, b: Cell) -> bool:
    """a、b 是否为 8 邻域内的不同格。"""
    dr, dc = abs(a[0] - b[0]), abs(a[1] - b[1])
    return dr <= 1 and dc <= 1 and (dr, dc) != (0, 0)


def is_diagonal(a: Cell, b: Cell) -> bool:
    return a[0] != b[0] and a[1] != b[1]


def distance_factor(a: Cell, b: Cell, config: CostConfig = DEFAULT_CONFIG) -> float:
    """正交返回 1.0，斜向返回 k。"""
    return config.diagonal_factor if is_diagonal(a, b) else 1.0


def neighbors(
    cell: Cell, shape: tuple[int, int], config: CostConfig = DEFAULT_CONFIG
) -> list[tuple[Cell, float, bool]]:
    """返回 8 邻域 [(邻格, 距离系数, 是否斜向)]，顺序固定为从左上到右下。

    只做几何过滤（越界），不判断障碍；障碍判断在 can_step / neighbor_steps。
    """
    out: list[tuple[Cell, float, bool]] = []
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nxt: Cell = (cell[0] + dr, cell[1] + dc)
            if not in_bounds(shape, nxt):
                continue
            diag = dr != 0 and dc != 0
            out.append((nxt, config.diagonal_factor if diag else 1.0, diag))
    return out


def can_step(
    cost: Raster, a: Cell, b: Cell, config: CostConfig | None = None
) -> bool:
    """从 a 能否走到 b：边界、相邻、目标格障碍、切角规则。"""
    cfg = resolve_config(cost, config)
    shape = raster_shape(cost)
    if not in_bounds(shape, a) or not in_bounds(shape, b):
        return False
    if not is_adjacent(a, b):
        return False
    if is_blocked(cost, b, cfg):
        return False
    if is_diagonal(a, b) and not cfg.allow_corner_cut:
        side_a = (a[0], b[1])  # 与 a 同行、与 b 同列
        side_b = (b[0], a[1])  # 与 b 同行、与 a 同列
        if is_blocked(cost, side_a, cfg) or is_blocked(cost, side_b, cfg):
            return False
    return True


def step_cost(
    cost: Raster,
    a: Cell,
    b: Cell,
    k: float | None = None,
    *,
    config: CostConfig | None = None,
) -> float:
    """单步代价 —— 全组契约签名 step_cost(cost, a, b, k)。

    k        : 斜向系数；传入时覆盖 config.diagonal_factor（兼容契约第 4 个位置参数）
    config   : 完整规则配置；不传则用 DEFAULT_CONFIG
    返回值    : 可通行时为该步代价；被阻挡/不可通行时为 math.inf
    异常      : a 或 b 越界、a 与 b 不相邻时抛 ValueError（属于调用方错误）
    """
    cfg = resolve_config(cost, config)
    if k is not None:
        cfg = replace(cfg, diagonal_factor=float(k))

    shape = raster_shape(cost)
    if not in_bounds(shape, a) or not in_bounds(shape, b):
        raise ValueError(f"格子越界: {a} -> {b}, shape={shape}")
    if not is_adjacent(a, b):
        raise ValueError(f"两格不相邻: {a} -> {b}")

    if not can_step(cost, a, b, cfg):
        return math.inf

    va = cell_value(cost, a)
    vb = cell_value(cost, b)
    if va is None or vb is None:
        return math.inf

    f = distance_factor(a, b, cfg)
    if cfg.cost_mode == "target":
        return vb * f
    return (va + vb) / 2.0 * f


def neighbor_steps(
    cost: Raster, cell: Cell, config: CostConfig | None = None
) -> list[tuple[Cell, float, float]]:
    """丙组搜索层直接消费的接口。

    返回 [(邻格, 该步代价, 距离系数)]，已过滤障碍与禁止的切角。
    """
    cfg = resolve_config(cost, config)
    out: list[tuple[Cell, float, float]] = []
    for nxt, f, _diag in neighbors(cell, raster_shape(cost), cfg):
        w = step_cost(cost, cell, nxt, config=cfg)
        if math.isfinite(w):
            out.append((nxt, w, f))
    return out


def path_total_cost(
    cost: Raster, path: Iterable[Cell], config: CostConfig | None = None
) -> float:
    """沿给定路径累加总成本；任一步不可通行则返回 math.inf。

    include_start=True 时额外加上起点格成本（不加距离系数）。
    """
    cfg = resolve_config(cost, config)
    cells = list(path)
    if not cells:
        return 0.0

    total = 0.0
    if cfg.include_start:
        v0 = cell_value(cost, cells[0])
        if v0 is None:
            return math.inf
        total += v0

    for a, b in zip(cells, cells[1:]):
        w = step_cost(cost, a, b, config=cfg)
        if not math.isfinite(w):
            return math.inf
        total += w
    return total


def path_step_details(
    cost: Raster, path: Iterable[Cell], config: CostConfig | None = None
) -> list[dict]:
    """逐段明细，可直接映射为矢量图层的 step_cost 字段。

    每段返回 from / to / enter_cost / average_cost / factor / step_cost / cumulative。
    """
    cfg = resolve_config(cost, config)
    cells = list(path)
    out: list[dict] = []
    cumulative = 0.0
    if cfg.include_start and cells:
        v0 = cell_value(cost, cells[0])
        cumulative = v0 if v0 is not None else math.inf

    for a, b in zip(cells, cells[1:]):
        w = step_cost(cost, a, b, config=cfg)
        cumulative += w
        va, vb = cell_value(cost, a), cell_value(cost, b)
        out.append(
            {
                "from": a,
                "to": b,
                "enter_cost": vb,
                "average_cost": None if va is None or vb is None else (va + vb) / 2.0,
                "factor": distance_factor(a, b, cfg),
                "step_cost": w,
                "cumulative": cumulative,
            }
        )
    return out


if __name__ == "__main__":
    demo = [
        [5, 7, 8, 4],
        [7, 5, 8, 4],
        [8, 8, 5, 4],
        [4, 4, 4, 4],
    ]
    path = [(0, 0), (1, 1), (2, 2), (3, 3)]
    print("默认口径 target, k=sqrt(2)")
    print(f"  总成本 = {path_total_cost(demo, path):.6f}  (= 14*sqrt(2))")
    for row in path_step_details(demo, path):
        print(
            f"  {row['from']} -> {row['to']}: "
            f"{row['enter_cost']:g} x {row['factor']:.6f} = {row['step_cost']:.6f}"
        )
    print("\n从 (0,0) 出发可走的邻格：")
    for nxt, w, f in neighbor_steps(demo, (0, 0)):
        print(f"  {nxt}: 代价 {w:.6f}")
