"""全组公共接口契约 · 乙组提案 v0.1（待四人碰头确认后冻结）

用途：四个人按同一套签名并行开发，互不等待。
      cost_rules 的 step_cost / neighbor_steps 是乙组已实现的真实代码，直接给全组用；
      shortest_path 已由丙组接入真实搜索引擎与乙组邻格接口；
      load_cost_raster / path_to_layer 仍由甲 / 丁后续替换。

约定
----
    cost  : 甲组 RasterData dict（含 values / nodata），或裸二维矩阵 list / numpy 数组；
            乙组 cost_rules 两种都能直接接收，并自动采用 dict 里的 nodata
    cell  : (row, col)，整数，原点在左上角
    path  : [(r0,c0), (r1,c1), ...]，相邻格（含对角）组成的序列
    stats : {"total_cost": float, "length": float, "steps": int,
             "expanded": int, "elapsed_ms": float, "step_details": list[dict]}
    k     : 斜向距离系数，默认 sqrt(2)；老师给定其他值时统一改 CostConfig.diagonal_factor
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from cost_rules import (SQRT2, CostConfig, can_step, cell_value,
                        distance_factor, neighbor_steps, neighbors,
                        path_step_details, raster_shape, resolve_config, step_cost)
from cost_path import CostGrid, find_path
from golden_cases import GRID_4X4

CONTRACT_VERSION = "0.1"


@dataclass
class PathResult:
    """丙组 shortest_path 的返回结构。"""

    path: list[tuple[int, int]]
    stats: dict


# ---------------------------------------------------------------------------
# 甲组：数据读取。当前为桩，直接返回金标准 4x4 栅格。
# ---------------------------------------------------------------------------
def load_cost_raster(source: str | None = None) -> dict:
    """甲组接口：返回与 cost_raster.py 一致的 RasterData dict。

    STUB：当前返回乙组金标准 4x4 栅格。真实实现直接复用甲组模块：
        from cost_raster import load_raster_file
        return load_raster_file(source)
    """
    rows, cols = len(GRID_4X4), len(GRID_4X4[0])
    return {
        "rows": rows,
        "cols": cols,
        "nodata": -9999.0,
        "values": GRID_4X4,
        "origin": [0.0, float(rows)],
        "pixel_size": [1.0, 1.0],
        "crs": "unknown",
        "bounds": [0.0, 0.0, float(cols), float(rows)],
        "stub": True,
        "source": source or "STUB:golden_4x4",
    }


# step_cost(cost, a, b, k) —— 乙组真实实现，已在模块顶部 re-export。
# 丙组搜索层也可以直接用 neighbor_steps(cost, cell, cfg) 遍历可通行邻格。


# ---------------------------------------------------------------------------
# 丙组：真实最短路径搜索，直接消费乙组 neighbor_steps。
# ---------------------------------------------------------------------------
def shortest_path(
    cost: object,
    start: tuple[int, int],
    end: tuple[int, int],
    step_cost_fn=step_cost,
    config: CostConfig = None,
    algorithm: str = "dijkstra",
) -> PathResult:
    """按乙组 CostConfig 求最优路径，返回全组约定的 PathResult。"""
    cfg = resolve_config(cost, config)
    grid = CostGrid.from_raster(cost) if isinstance(cost, dict) else CostGrid(cost, nodata=cfg.nodata)
    if step_cost_fn is step_cost:
        provider = lambda cell: neighbor_steps(cost, cell, cfg)
    else:
        shape = raster_shape(cost)

        def provider(cell):
            out = []
            for nxt, factor, _diagonal in neighbors(cell, shape, cfg):
                if not can_step(cost, cell, nxt, cfg):
                    continue
                weight = step_cost_fn(cost, cell, nxt, cfg.diagonal_factor)
                if math.isfinite(weight):
                    out.append((nxt, weight, factor))
            return out

    result = find_path(
        grid, start, end, algorithm=algorithm,
        diagonal_multiplier=cfg.diagonal_factor,
        allow_corner_cutting=cfg.allow_corner_cut,
        cost_mode=cfg.cost_mode,
        include_start=cfg.include_start,
        nonpositive_blocked=cfg.nonpositive_blocked,
        blocked_values=cfg.blocked_values | frozenset({cfg.nodata}),
        neighbor_provider=provider,
        heuristic_min_cost=grid.min_cost if step_cost_fn is step_cost else None,
    )
    path = list(result.path_cells)
    if step_cost_fn is step_cost:
        details = path_step_details(cost, path, cfg)
    else:
        details = []
        cumulative = cell_value(cost, start) if cfg.include_start else 0.0
        for a, b, weight in zip(path, path[1:], result.step_costs):
            cumulative += weight
            details.append({
                "from": a, "to": b, "step_cost": weight,
                "factor": distance_factor(a, b, cfg), "cumulative": cumulative,
            })
    stats = {
        "total_cost": result.total_cost,
        "length": result.length_cells,
        "steps": len(path) - 1,
        "expanded": result.expanded_nodes,
        "elapsed_ms": result.elapsed_ms,
        "step_details": details,
        "algorithm": algorithm,
    }
    return PathResult(path=path, stats=stats)


# ---------------------------------------------------------------------------
# 丁组：矢量图层输出。当前为桩，只返回图层结构描述，不依赖 QGIS。
# ---------------------------------------------------------------------------
def path_to_layer(path: list[tuple[int, int]], stats: dict) -> dict:
    """STUB：生成路径 LineString 矢量图层。由丁组替换为 QgsVectorLayer。

    字段定义 fixed，丁组按此建字段即可：
        total_cost / length / steps / from_row / from_col / to_row / to_col / step_cost
    """
    segments = []
    for a, b in zip(path, path[1:]):
        diag = a[0] != b[0] and a[1] != b[1]
        segments.append(
            {
                "from_row": a[0],
                "from_col": a[1],
                "to_row": b[0],
                "to_col": b[1],
                "step_cost": None,
                "distance": SQRT2 if diag else 1.0,
            }
        )
    return {
        "geometry": "LineString",
        "fields": [
            "total_cost",
            "length",
            "steps",
            "from_row",
            "from_col",
            "to_row",
            "to_col",
            "step_cost",
        ],
        "segments": segments,
        "attributes": {
            "total_cost": stats.get("total_cost", math.inf),
            "length": stats.get("length", 0.0),
            "steps": stats.get("steps", len(segments)),
        },
        "stub": True,
    }


if __name__ == "__main__":
    data = load_cost_raster()
    result = shortest_path(data, (0, 0), (3, 3))
    layer = path_to_layer(result.path, result.stats)
    print("契约版本:", CONTRACT_VERSION)
    print("栅格:", data["rows"], "x", data["cols"])
    print("路径:", result.path)
    print("总成本:", round(result.stats["total_cost"], 6))
    print("图层字段:", layer["fields"])
    print("注意：输入与图层输出仍为 STUB，搜索为真实结果。")
