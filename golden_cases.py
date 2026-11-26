"""乙组 · 准确性金标准样例（交接给全组，尤其丙组验证搜索结果）
/////////
所有期望值都由手算解析式给出，不从本项目的算法代码推导，避免循环验证。
丙组可直接 import 这些常量，检查自己的 Dijkstra / A* 是否得到同样的路径与总成本。

样例一：4x4 主样例（含老师举例的 5 / 7 / 8 / 4，无 NoData）
    cost = [[5, 7, 8, 4],
            [7, 5, 8, 4],
            [8, 8, 5, 4],
            [4, 4, 4, 4]]
    start = (0, 0), end = (3, 3)

    target 口径、k=sqrt(2)、起点不计：
        (0,0)->(1,1): 5*k
        (1,1)->(2,2): 5*k
        (2,2)->(3,3): 4*k
        合计 = 14*k = 14*sqrt(2) = 19.79898987322333

    average 口径、k=sqrt(2)：
        (5+5)/2*k + (5+5)/2*k + (5+4)/2*k = 14.5*sqrt(2) = 20.50609665440988

    已用独立 Dijkstra 复核：默认 k 下该对角路径确为最优；
    k 放大到 4 时最优路径改走边缘，总成本 31（对角路径此时为 56）。
    该性质可用于验证「斜向系数确实生效」。

样例二：甲组通用样例 sample_data/cost_grid_4x4.json（含 1 个 NoData）
    cost = [[5, 7, 8, 4],
            [4, -9999, 7, 8],
            [7, 8, 4, 5],
            [8, 4, 5, 7]]
    (1,1) 为 NoData 不可通行；target 口径下最优路径为
        (0,0)->(1,0)->(2,0)->(3,1)->(3,2)->(3,3)
    逐步代价 4 + 7 + 4*k + 5 + 7 = 23 + 4*sqrt(2) = 28.65685424949238
"""

from __future__ import annotations

import math

if __package__:
    from .cost_rules import PIXEL_SIZE_48M, SQRT2, Cell
else:
    from cost_rules import PIXEL_SIZE_48M, SQRT2, Cell

NODATA = -9999.0

# ---- 甲组通用样例 ---------------------------------------------------------
GRID_TEAM_4X4: list[list[float]] = [
    [5, 7, 8, 4],
    [4, -9999, 7, 8],
    [7, 8, 4, 5],
    [8, 4, 5, 7],
]
RASTERDATA_TEAM_4X4: dict = {
    "rows": 4,
    "cols": 4,
    "nodata": NODATA,
    "values": GRID_TEAM_4X4,
    "origin": [0, 4],
    "pixel_size": [1, 1],
    "crs": "unknown",
    "bounds": [0, 0, 4, 4],
}
PATH_TEAM_4X4: list[Cell] = [
    (0, 0), (1, 0), (2, 0), (3, 1), (3, 2), (3, 3)
]
EXPECTED_TEAM_TARGET_SQRT2 = 23.0 + 4.0 * SQRT2

# ---- 主样例 ---------------------------------------------------------------
GRID_4X4: list[list[float]] = [
    [5, 7, 8, 4],
    [7, 5, 8, 4],
    [8, 8, 5, 4],
    [4, 4, 4, 4],
]
START_4X4: Cell = (0, 0)
END_4X4: Cell = (3, 3)
PATH_4X4: list[Cell] = [(0, 0), (1, 1), (2, 2), (3, 3)]
PATH_4X4_EDGE: list[Cell] = [
    (0, 0), (0, 1), (0, 2), (0, 3), (1, 3), (2, 3), (3, 3)
]

EXPECTED_TARGET_SQRT2 = 14.0 * SQRT2          # 19.79898987322333
EXPECTED_AVERAGE_SQRT2 = 14.5 * SQRT2         # 20.50609665440988
EXPECTED_DIAGONAL_AT_K4 = 14.0 * 4.0          # 56.0
EXPECTED_EDGE_AT_K4 = 31.0                    # 7+8+4+4+4+4

# ---- 48m × 48m 像元的三角公式与地面长度（手算） -----------------------------
# 斜边 = sqrt(48² + 48²) = 48*sqrt(2) ≈ 67.88225099 米
EXPECTED_STEP_ORTHOGONAL_M = 48.0
EXPECTED_STEP_DIAGONAL_M = 48.0 * SQRT2
EXPECTED_PATH_4X4_LENGTH_M = 3.0 * 48.0 * SQRT2  # 三段对角，≈ 203.64675298 米

# ---- 斜向系数是否生效的最小样例 -------------------------------------------
GRID_2X2: list[list[float]] = [[1.0, 2.0], [2.0, 1.0]]
PATH_DIAGONAL_2X2: list[Cell] = [(0, 0), (1, 1)]
PATH_ORTHOGONAL_2X2: list[Cell] = [(0, 0), (0, 1), (1, 1)]
EXPECTED_DIAGONAL_2X2 = SQRT2                 # 1 * sqrt(2)
EXPECTED_ORTHOGONAL_2X2 = 3.0                 # 2 + 1
EXPECTED_DIAGONAL_2X2_K4 = 4.0                # 1 * 4，此时比正交的 3 更贵

# ---- 障碍 / NoData / 切角 --------------------------------------------------
GRID_CORNER_BOTH_BLOCKED: list[list[float]] = [[1.0, NODATA], [NODATA, 1.0]]
GRID_CORNER_ONE_BLOCKED: list[list[float]] = [
    [1.0, 2.0, 1.0],
    [NODATA, 1.0, 1.0],
    [1.0, 1.0, 1.0],
]


def golden_cases() -> dict:
    """返回全部金标准的结构化描述，便于测试脚本批量消费。"""
    return {
        "hw2_4x4": {
            "grid": GRID_4X4,
            "start": START_4X4,
            "end": END_4X4,
            "path": PATH_4X4,
            "expected_target": EXPECTED_TARGET_SQRT2,
            "expected_average": EXPECTED_AVERAGE_SQRT2,
        },
        "diagonal_k4": {
            "grid": GRID_4X4,
            "path_diagonal": PATH_4X4,
            "path_edge": PATH_4X4_EDGE,
            "expected_diagonal": EXPECTED_DIAGONAL_AT_K4,
            "expected_edge": EXPECTED_EDGE_AT_K4,
        },
        "diagonal_2x2": {
            "grid": GRID_2X2,
            "path_diagonal": PATH_DIAGONAL_2X2,
            "path_orthogonal": PATH_ORTHOGONAL_2X2,
            "expected_diagonal": EXPECTED_DIAGONAL_2X2,
            "expected_orthogonal": EXPECTED_ORTHOGONAL_2X2,
            "expected_diagonal_k4": EXPECTED_DIAGONAL_2X2_K4,
        },
        "corner_cut": {
            "grid_both": GRID_CORNER_BOTH_BLOCKED,
            "grid_one": GRID_CORNER_ONE_BLOCKED,
        },
        "team_4x4": {
            "rasterdata": RASTERDATA_TEAM_4X4,
            "grid": GRID_TEAM_4X4,
            "path": PATH_TEAM_4X4,
            "expected_target": EXPECTED_TEAM_TARGET_SQRT2,
            "nodata_cell": (1, 1),
        },
        "pixel_48m": {
            "pixel_size": PIXEL_SIZE_48M,
            "path": PATH_4X4,
            "expected_diagonal_factor": SQRT2,
            "expected_step_orthogonal_m": EXPECTED_STEP_ORTHOGONAL_M,
            "expected_step_diagonal_m": EXPECTED_STEP_DIAGONAL_M,
            "expected_path_length_m": EXPECTED_PATH_4X4_LENGTH_M,
        },
    }


if __name__ == "__main__":
    for name, case in golden_cases().items():
        print(name, "->", sorted(case.keys()))
    print("14*sqrt(2) =", 14 * math.sqrt(2))
    print("14.5*sqrt(2) =", 14.5 * math.sqrt(2))
    print("23+4*sqrt(2) =", 23 + 4 * math.sqrt(2))
    print("48m*sqrt(2) =", 48 * math.sqrt(2), "米")
    print("3*48*sqrt(2) =", 3 * 48 * math.sqrt(2), "米")
