# -*- coding: utf-8 -*-
"""成本栅格加载与基础校验模块（甲 · 数据与坐标层）。

本模块只负责“把成本栅格读进系统并整理成统一的内部结构”，不做路径搜索、
代价规则或图层可视化——那些分别由丙（引擎）、乙（成本规则）、丁（图层）负责。

内部栅格结构（RasterData）字段约定，供后续各层按同一接口取用：

    rows        栅格行数（南北向，自上而下编号）
    cols        栅格列数（东西向，自西向东编号）
    nodata      无数据值；遇到该值的格子视为不可通行
    values      二维列表 values[r][c]，数值为该格成本（如 5/7/8/4），
                NoData 格保留 nodata 原值，由调用方判断
    origin      左上角地理坐标 [xmin, ymax]（平面或经纬度，跟随源数据）
    pixel_size  单格边长 [sx, sy]；平面坐标通常为正，地理坐标 sy 为纬度步长
    crs         坐标系说明字符串（可选，缺省为 "unknown"）
    bounds      外包范围 [xmin, ymin, xmax, ymax]，由 origin / 尺寸 / 步长推算

坐标与行列号的换算（row / col 为 0 基下标）由 coord_transform.py 负责实现，
本模块只提供栅格内部几何所需的边界信息（origin / pixel_size / bounds）。
"""

import json
import math
from pathlib import Path

# 成本值允许的范围：课程样例为 5/7/8/4 这类正整数，这里放宽到非负有限数，
# 负值视为非法成本；NoData 单独由 nodata 字段标识。
MIN_COST = 0.0
MAX_COST = 1.0e12


class RasterError(ValueError):
    """栅格数据相关的校验错误，消息为中文，可直接提示给用户。"""


def _is_number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _read_matrix(source):
    """从 dict / 二维列表中取出成本矩阵，统一校验行列结构。

    支持两种输入形态：
      1. 二维列表 [[5, 7, 8, 4], ...]
      2. dict，含 "values"（二维列表）或 "matrix"（二维列表）
    """
    if isinstance(source, dict):
        matrix = source.get("values", source.get("matrix"))
    else:
        matrix = source
    if not isinstance(matrix, list) or not matrix:
        raise RasterError("成本栅格不能为空，至少需要一行数据")
    cols = None
    for r, row in enumerate(matrix):
        if not isinstance(row, list):
            raise RasterError("第 {} 行不是列表形式的栅格数据".format(r + 1))
        if cols is None:
            cols = len(row)
            if cols == 0:
                raise RasterError("栅格至少需要一列")
        elif len(row) != cols:
            raise RasterError("第 {} 行长度与首行（{} 列）不一致".format(r + 1, cols))
    return matrix


def _validate_cell(value, nodata, r, c):
    """校验单个成本格；返回归一化后的数值，NoData 原样保留。"""
    if not _is_number(value):
        raise RasterError("第 {} 行第 {} 列成本值不是有效数值".format(r + 1, c + 1))
    if nodata is not None and math.isclose(float(value), float(nodata), rel_tol=0.0, abs_tol=1e-9):
        return float(value)
    if value < MIN_COST or value > MAX_COST:
        raise RasterError("第 {} 行第 {} 列成本值超出允许范围 [{}, {}]".format(
            r + 1, c + 1, MIN_COST, MAX_COST))
    return float(value)


def build_raster(matrix, origin=None, pixel_size=None, nodata=None, crs="unknown"):
    """把成本矩阵整理为统一的 RasterData 结构并做基础校验。

    参数
    ----
    matrix : list[list] | dict
        成本矩阵，或含 values/matrix 的 dict。
    origin : [x, y] | None
        左上角坐标；缺省使用平面网格坐标 (0, rows)，便于先用样例数据自测。
    pixel_size : [sx, sy] | None
        单格步长；缺省为 [1.0, 1.0]。平面坐标系下 y 自上而下递减，内部按
        标准 GIS 约定记录 ymax=origin[1]、ymin=origin[1]-rows*|sy|。
    nodata : number | None
        无数据值；None 表示不设 NoData。
    crs : str
        坐标系说明。

    返回
    ----
    dict : RasterData
    """
    values = _read_matrix(matrix)
    rows = len(values)
    cols = len(values[0])

    if nodata is not None and not _is_number(nodata):
        raise RasterError("NoData 值必须是数值或留空")

    cleaned = []
    for r, row in enumerate(values):
        cleaned_row = [_validate_cell(v, nodata, r, c) for c, v in enumerate(row)]
        cleaned.append(cleaned_row)

    if origin is None:
        origin = [0.0, float(rows)]
    else:
        if not isinstance(origin, list) or len(origin) < 2 or not all(_is_number(v) for v in origin[:2]):
            raise RasterError("起点原点坐标必须是 [x, y] 数值对")
        origin = [float(origin[0]), float(origin[1])]

    if pixel_size is None:
        pixel_size = [1.0, 1.0]
    else:
        if not isinstance(pixel_size, list) or len(pixel_size) < 2 or not all(_is_number(v) and v > 0 for v in pixel_size[:2]):
            raise RasterError("栅格步长 pixel_size 必须是两个正数值 [sx, sy]")
        pixel_size = [float(pixel_size[0]), float(pixel_size[1])]

    sx, sy = pixel_size
    xmin, ymax = origin
    xmax = xmin + cols * sx
    ymin = ymax - rows * sy

    return {
        "rows": rows,
        "cols": cols,
        "nodata": None if nodata is None else float(nodata),
        "values": cleaned,
        "origin": origin,
        "pixel_size": pixel_size,
        "crs": str(crs),
        "bounds": [xmin, ymin, xmax, ymax],
    }


def load_raster_file(path):
    """从 JSON 文件加载成本栅格。

    文件格式（UTF-8 JSON）示例：

        {
          "crs": "unknown",
          "nodata": -9999,
          "origin": [0, 4],
          "pixel_size": [1, 1],
          "values": [
            [5, 7, 8, 4],
            [4, 5, 7, 8],
            [7, 8, 4, 5],
            [8, 4, 5, 7]
          ]
        }

    只读取课程提供 / 本组准备的栅格 JSON，不独立实现完整数据管理系统。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise RasterError("栅格文件不存在：{}".format(file_path))
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RasterError("栅格文件不是合法 JSON：{}".format(exc))

    if not isinstance(payload, dict):
        raise RasterError("栅格文件顶层必须是对象，含 values 成本矩阵")

    return build_raster(
        matrix=payload,
        origin=payload.get("origin"),
        pixel_size=payload.get("pixel_size"),
        nodata=payload.get("nodata"),
        crs=payload.get("crs", "unknown"),
    )


def in_bounds(raster, row, col):
    """判断行列号是否落在栅格范围内（0 基）。"""
    return isinstance(row, int) and isinstance(col, int) and 0 <= row < raster["rows"] and 0 <= col < raster["cols"]


def is_nodata(raster, row, col):
    """判断指定格是否为 NoData；越界由调用方先用 in_bounds 判断。"""
    nodata = raster["nodata"]
    if nodata is None:
        return False
    return math.isclose(raster["values"][row][col], nodata, rel_tol=0.0, abs_tol=1e-9)


def get_cost(raster, row, col):
    """取某格成本；越界或 NoData 时抛出 RasterError，供上层拦截。"""
    if not in_bounds(raster, row, col):
        raise RasterError("行列号 ({}, {}) 越界：栅格为 {} 行 × {} 列".format(
            row, col, raster["rows"], raster["cols"]))
    if is_nodata(raster, row, col):
        raise RasterError("第 {} 行第 {} 列为 NoData，不可通行".format(row + 1, col + 1))
    return raster["values"][row][col]


def raster_summary(raster):
    """返回栅格元数据摘要，供对话框 / 测试记录展示。"""
    flat = [v for row in raster["values"] for v in row]
    nodata = raster["nodata"]
    nodata_count = sum(1 for v in flat if nodata is not None and math.isclose(v, nodata, rel_tol=0.0, abs_tol=1e-9))
    valid = [v for v in flat if not (nodata is not None and math.isclose(v, nodata, rel_tol=0.0, abs_tol=1e-9))]
    return {
        "rows": raster["rows"],
        "cols": raster["cols"],
        "cell_count": raster["rows"] * raster["cols"],
        "nodata_count": nodata_count,
        "cost_min": min(valid) if valid else None,
        "cost_max": max(valid) if valid else None,
        "crs": raster["crs"],
        "bounds": raster["bounds"],
    }
