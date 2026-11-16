"""全组公共接口契约 · 乙组提案 v0.1（待四人碰头确认后冻结）

用途：四个人按同一套签名并行开发，互不等待。
      cost_rules 的 step_cost / neighbor_steps 是乙组已实现的真实代码，直接给全组用；
      load_cost_raster / shortest_path / path_to_layer 暂为桩实现，仅返回结构正确的假数据，
      由甲 / 丙 / 丁各自替换，联调时只换函数体，不动调用方。

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

from cost_rules import DEFAULT_CONFIG, SQRT2, CostConfig, neighbor_steps, step_cost
from golden_cases import GRID_4X4, PATH_4X4, EXPECTED_TARGET_SQRT2

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
# 丙组：最短路径搜索。当前为桩，返回金标准路径与结构完整的假统计。
# ---------------------------------------------------------------------------
def shortest_path(
    cost: object,
    start: tuple[int, int],
    end: tuple[int, int],
    step_cost_fn=step_cost,
    config: CostConfig = DEFAULT_CONFIG,
) -> PathResult:
    """STUB：Dijkstra / A*，返回 PathResult。由丙组实现。

    桩实现仅用于丁组提前做出图界面，不保证路径正确。
    """
    path = list(PATH_4X4)
    stats = {
        "total_cost": EXPECTED_TARGET_SQRT2,
        "length": 3 * SQRT2,
        "steps": len(path) - 1,
        "expanded": 0,
        "elapsed_ms": 0.0,
        "step_details": [],
        "stub": True,
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
    print("注意：除 step_cost 外均为 STUB，联调时替换。")
