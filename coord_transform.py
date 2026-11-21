# -*- coding: utf-8 -*-
"""坐标与行列号双向换算模块（甲 · 数据与坐标层，第二次进度）。

作用范围：把"用户给的坐标"和"搜索层要的 (行, 列)"互相翻译，并把非法输入
挡在进入引擎之前。不做路径搜索、不算代价、不画图层。

坐标约定（与 QGIS / GDAL 的栅格地理变换一致）
--------------------------------------------
栅格左上角 origin = [xmin, ymax]，像元步长 pixel_size = [sx, sy]，y 轴自北向南递减：

    列方向：x 从 xmin 起，向右每格递加 sx
    行方向：y 从 ymax 起，向下每格递减 sy

行 row、列 col 均为 0 基，且 row 向下增大（第 0 行在最北），与 cost_raster.values
的行序、丙组引擎的 (row, col) 约定完全一致。

换算公式（格心）：

    x = xmin + (col + 0.5) * sx
    y = ymax - (row + 0.5) * sy

反算：

    col = floor((x - xmin) / sx)
    row = floor((ymax - y) / sy)

边界语义：外接矩形右边界 x=xmax、下边界 y=ymin 属于图幅，归入最后一列 / 最后一行
（与 GDAL 的闭区间约定一致）；超出图幅一个像元以外报错，不再静默夹紧。

旋转栅格（GeoTransform 含非零 rot）本进度不支持，遇到即明确报错，避免给出
看似正常、实则错位的换算结果。
"""

from __future__ import annotations

import math
import re

# 浮点容差：坐标往返换算与边界判定都用它，避免 x=0.1+0.2 这类误差误判越界。
EPS = 1e-9

# 全角数字与全角符号归一化，键盘中文输入法下常见
_FULLWIDTH_MAP = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９"}
_FULLWIDTH_MAP.update({ord("，"): ",", ord("；"): ",", ord("（"): "(", ord("）"): ")"})
_FULLWIDTH_MAP.update({ord("　"): " "})

# 键盘输入的允许字符：数字、正负号、小数点、指数、分隔符与括号
_ALLOWED_INPUT = re.compile(r"^[0-9eE+\-.(),; \t]*$")


class CoordError(ValueError):
    """坐标 / 输入相关的校验错误，消息为中文，可直接显示在对话框里。"""


def _finite(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CoordError("{} 必须是数值，当前为 {!r}".format(name, value))
    if not math.isfinite(float(value)):
        raise CoordError("{} 必须是有限数值，当前为 {!r}".format(name, value))
    return float(value)


def check_raster(raster):
    """校验栅格结构里换算所需字段是否齐全且自洽。"""
    for key in ("rows", "cols", "origin", "pixel_size", "bounds"):
        if key not in raster:
            raise CoordError("栅格结构缺少字段 {}，无法做坐标换算".format(key))
    rows, cols = raster["rows"], raster["cols"]
    if not isinstance(rows, int) or not isinstance(cols, int) or rows <= 0 or cols <= 0:
        raise CoordError("栅格行列数必须是正整数，当前为 {} × {}".format(rows, cols))
    origin = raster["origin"]
    pixel = raster["pixel_size"]
    if len(origin) < 2 or len(pixel) < 2:
        raise CoordError("origin 与 pixel_size 都必须是长度为 2 的数值对")
    sx, sy = _finite(pixel[0], "像元宽 sx"), _finite(pixel[1], "像元高 sy")
    if sx <= 0 or sy <= 0:
        raise CoordError("像元步长必须为正数，当前 sx={}, sy={}".format(sx, sy))
    return float(origin[0]), float(origin[1]), sx, sy


def raster_extent(raster):
    """返回图幅四至 (xmin, ymin, xmax, ymax)。"""
    xmin, ymax, sx, sy = check_raster(raster)
    return xmin, ymax - raster["rows"] * sy, xmin + raster["cols"] * sx, ymax


def cell_to_map(raster, row, col, anchor="center"):
    """行列号 → 地图坐标。

    anchor="center" 取格心（路径节点、属性挂接都用格心，避免落在外框线上）；
    anchor="corner" 取格左上角，用于检查边界与像元对齐。
    """
    xmin, ymax, sx, sy = check_raster(raster)
    if not isinstance(row, int) or not isinstance(col, int):
        raise CoordError("行列号必须是整数，当前为 ({!r}, {!r})".format(row, col))
    if not (0 <= row < raster["rows"] and 0 <= col < raster["cols"]):
        raise CoordError("行列号 ({}, {}) 越界：图幅为 {} 行 × {} 列".format(
            row, col, raster["rows"], raster["cols"]))
    offset = 0.5 if anchor == "center" else 0.0
    if anchor not in ("center", "corner"):
        raise CoordError("anchor 只能是 'center' 或 'corner'，当前为 {!r}".format(anchor))
    return xmin + (col + offset) * sx, ymax - (row + offset) * sy


def map_to_cell(raster, x, y):
    """地图坐标 → (row, col)，并做图幅边界判定。

    返回 (row, col)；坐标落在图幅外时抛 CoordError，不静默夹紧到边缘格，
    否则用户会以为点在了图上，实际却偏出去很远。
    """
    x = _finite(x, "x 坐标")
    y = _finite(y, "y 坐标")
    xmin, ymax, sx, sy = check_raster(raster)
    xmax = xmin + raster["cols"] * sx
    ymin = ymax - raster["rows"] * sy

    if x < xmin - EPS or x > xmax + EPS:
        raise CoordError("x={:.6f} 超出图幅东西范围 [{:.6f}, {:.6f}]".format(x, xmin, xmax))
    if y < ymin - EPS or y > ymax + EPS:
        raise CoordError("y={:.6f} 超出图幅南北范围 [{:.6f}, {:.6f}]".format(y, ymin, ymax))

    # x==xmax、y==ymin 恰好落在图幅右 / 下边界，归入最后一列 / 最后一行
    raw_col = (x - xmin) / sx
    raw_row = (ymax - y) / sy
    col = min(int(math.floor(raw_col)), raster["cols"] - 1)
    row = min(int(math.floor(raw_row)), raster["rows"] - 1)
    col = max(col, 0)
    row = max(row, 0)
    return row, col


def parse_coord_text(text):
    """解析键盘输入的坐标字符串，返回 (x, y)。

    容错范围（课堂演示时手打坐标很容易带格式）：
      半角 / 全角逗号、分号、空格、制表符分隔；
      中文括号或英文括号包裹；全角数字；正负号与小数；科学计数法。
    只接受恰好两个数值，多一个少一个都报错，避免把 "100 200 300" 静默截成两点。
    """
    if text is None:
        raise CoordError("坐标输入为空，请输入形如 100,200 的两个数值")
    if not isinstance(text, str):
        text = str(text)
    norm = text.translate(_FULLWIDTH_MAP).strip()
    if not norm:
        raise CoordError("坐标输入为空，请输入形如 100,200 的两个数值")
    if not _ALLOWED_INPUT.match(norm):
        raise CoordError("坐标输入含非法字符：{!r}".format(text))

    # 去括号后按任意分隔符切分
    body = norm.replace("(", " ").replace(")", " ").replace(",", " ").replace(";", " ")
    tokens = [t for t in re.split(r"\s+", body) if t]
    if len(tokens) != 2:
        raise CoordError("坐标需要恰好两个数值（x 和 y），当前解析出 {} 个：{}".format(
            len(tokens), text))
    try:
        x = float(tokens[0])
        y = float(tokens[1])
    except ValueError:
        raise CoordError("坐标不是有效数字：{!r}".format(text))
    if not math.isfinite(x) or not math.isfinite(y):
        raise CoordError("坐标必须是有限数值：{!r}".format(text))
    return x, y


def format_coord(x, y, precision=3):
    """把坐标格式化成对话框可复制的文本。"""
    return "{:.{p}f}, {:.{p}f}".format(float(x), float(y), p=precision)


def resolve_point(raster, text, role="起点"):
    """键盘输入 → 校验通过的 (row, col)，并返回可直接展示的信息。

    这是对话框"起点 / 终点"输入框该调用的入口：解析、换算、越界、NoData
    全部在这里拦完，引擎只会收到合法的行列号。
    """
    x, y = parse_coord_text(text)
    row, col = map_to_cell(raster, x, y)
    return describe_cell(raster, row, col, role=role, x=x, y=y)


def describe_cell(raster, row, col, role="起点", x=None, y=None):
    """组装单点的完整信息：行列号、格心坐标、成本值、是否可通行。"""
    from cost_raster import get_cost, is_nodata  # 延迟导入，避免模块循环依赖

    if x is None or y is None:
        x, y = cell_to_map(raster, row, col, anchor="center")
    else:
        x = float(x)
        y = float(y)

    blocked = is_nodata(raster, row, col)
    try:
        cost = get_cost(raster, row, col)
    except Exception:
        cost = None

    return {
        "role": role,
        "x": x,
        "y": y,
        "row": row,
        "col": col,
        "cost": cost,
        "blocked": blocked,
        "cell_center": list(cell_to_map(raster, row, col, anchor="center")),
        "coord_text": format_coord(x, y),
        "message": "{}：({}) → 第 {} 行第 {} 列，成本 {}{}".format(
            role,
            format_coord(x, y),
            row + 1,
            col + 1,
            "无数据" if cost is None else ("{:g}".format(cost)),
            "，该格不可通行" if blocked else "",
        ),
    }


def require_passable(point):
    """起终点落在 NoData 时抛错，避免把不可通行格交给引擎。"""
    if point.get("blocked"):
        raise CoordError("{}落在无数据格（第 {} 行第 {} 列），不可作为路径端点".format(
            point.get("role", "端点"), point["row"] + 1, point["col"] + 1))
    return point


def from_geotransform(geotransform, rows, cols, values, nodata=None, crs="unknown"):
    """把 GDAL / QGIS 的 6 参数地理变换转成本项目的 origin + pixel_size。

    geotransform = (x0, sx, rot_x, y0, rot_y, sy)，其中 sy 通常为负值（自北向南）。
    本进度不支持带旋转的栅格：rot_x / rot_y 非零时直接报错，不猜测近似。
    """
    from cost_raster import build_raster  # 延迟导入，避免模块循环依赖

    if geotransform is None or len(geotransform) != 6:
        raise CoordError("geotransform 必须是 6 个数值，当前为 {!r}".format(geotransform))
    gt = [_finite(v, "geotransform 分量") for v in geotransform]
    x0, sx, rot_x, y0, rot_y, sy = gt
    if abs(rot_x) > EPS or abs(rot_y) > EPS:
        raise CoordError("该栅格含旋转分量（rot_x={}, rot_y={}），本进度不支持".format(rot_x, rot_y))
    if sx <= 0:
        raise CoordError("geotransform 的像元宽 sx 必须为正，当前为 {}".format(sx))
    if sy >= 0:
        raise CoordError("geotransform 的像元高 sy 应为负值（自北向南），当前为 {}".format(sy))
    if len(values) != rows or any(len(r) != cols for r in values):
        raise CoordError("成本矩阵尺寸与 rows/cols 不一致：{} 行 × {} 列".format(rows, cols))
    return build_raster(
        matrix=values,
        origin=[x0, y0],
        pixel_size=[sx, -sy],
        nodata=nodata,
        crs=crs,
    )


def to_geotransform(raster):
    """反向输出 6 参数地理变换，交给 QGIS 写图层或核对像元对齐。"""
    xmin, ymax, sx, sy = check_raster(raster)
    return (xmin, sx, 0.0, ymax, 0.0, -sy)


def from_qgis_layer(layer, cost_field=None, values=None, nodata=None):
    """从 QGIS 栅格图层取地理变换与尺寸，转成本项目的 RasterData。

    只在 QGIS 环境里可用：PyQGIS 不在标准库内，故做延迟导入，纯 Python 测试
    环境不会因为缺少 qgis 包而导入失败。成本矩阵由调用方传入 values，或由本函数
    按 cost_field 指定的波段读出；本周先支持 values 传入，避免依赖 numpy。
    """
    try:
        from qgis.core import QgsRasterLayer  # noqa: F401  仅用于确认运行环境
    except Exception as exc:  # pragma: no cover - 非 QGIS 环境
        raise CoordError("当前环境没有 PyQGIS，无法直接读取 QGIS 图层：{}".format(exc))

    if not layer.isValid():
        raise CoordError("QGIS 栅格图层无效，请检查数据源路径")
    extent = layer.extent()
    rows, cols = layer.height(), layer.width()
    gt = (extent.xMinimum(), layer.rasterUnitsPerPixelX(), 0.0,
          extent.yMaximum(), 0.0, -layer.rasterUnitsPerPixelY())
    if values is None:
        raise CoordError("请传入成本矩阵 values（本周不直接按波段读取）")
    return from_geotransform(gt, rows, cols, values, nodata=nodata,
                             crs=layer.crs().authid() or "unknown")
