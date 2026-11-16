# 丙组搜索引擎接口约定 · 第一周草案

## 输入

```python
CostGrid(rows, nodata=None)
CostGrid.from_raster(raster_data)
find_path(grid, start, goal, *, algorithm="dijkstra",
          diagonal_multiplier=2**0.5, allow_corner_cutting=False,
          step_cost=None)
```

| 参数 | 约定 |
| --- | --- |
| `rows` / `raster_data` | 可直接传甲组 `cost_raster.load_raster_file()` 返回的 `RasterData` 字典；也可传矩形二维数组。有效成本为有限非负数，`None` 为障碍。`CostGrid(rows, nodata=-9999)` 支持甲组样例的数值 NoData 标记。 |
| `start`、`goal` | 零起始 `(row, col)` 整数；必须在栅格内且可通行。甲/丁组负责鼠标坐标或手输地图坐标到格号的转换。 |
| `algorithm` | `"dijkstra"` 或 `"astar"`；两者在同一非负边权下应得到同一最小总成本，路线形状可能因等价路径而不同。 |
| `diagonal_multiplier` | 斜向移动系数，有限且不小于 1；默认 `√2`。正交移动系数恒为 1。 |
| `allow_corner_cutting` | 默认 `False`；斜向移动时要求两侧正交邻格均可通行。乙组确认课程规则后可调整。 |
| `step_cost` | 乙组可传 `step_cost(from_cost, to_cost, movement_factor) -> 非负有限数`。`movement_factor` 正交为 1、斜向为设置的系数。默认规则是 `(from_cost + to_cost)/2 × movement_factor`。 |

自定义 `step_cost` 下 A* 暂时使用零启发式，保持最优性；乙组给出可证明的成本下界后可增加有效启发式以加速。成本为 0 的格子允许通行。负成本、无穷大与 NaN 拒绝输入。

## 输出与错误

`find_path` 返回 `RouteResult`，可用 `.to_dict()` 变成普通字典：

```json
{
  "path_cells": [[0, 0], [1, 1]],
  "step_costs": [6.363961030678928],
  "total_cost": 6.363961030678928,
  "length_cells": 1.4142135623730951,
  "expanded_nodes": 2,
  "elapsed_ms": 0.1,
  "algorithm": "dijkstra"
}
```

示例 `elapsed_ms` 仅示意，运行值随机器变化。`step_costs[i]` 对应 `path_cells[i] -> path_cells[i+1]`；数组长度比路径节点数少 1。`total_cost` 是逐段边权累积；`length_cells` 是格子尺度下的几何长度（正交 1、斜向 `√2`），不代表米。`elapsed_ms` 只计搜索与回溯，不计 `CostGrid` 构造、读取文件或渲染。

起终点无效、代价值无效时抛 `ValueError`；合法输入但无法连通时抛 `NoRouteError`。插件应把错误提示给用户，不创建空矢量图层。

## 交接到真实地图

甲组目前提供 `origin=[xmin, ymax]`、`pixel_size=[sx, sy]` 和 `crs`，保证其 `values` 的行列顺序与地图一致。丁组把每个 `(row, col)` 的**格心**转换成路径坐标：

```text
x = origin[0] + (col + 0.5) * pixel_size[0]
y = origin[1] - (row + 0.5) * pixel_size[1]
```

丁组用转换后的点创建 LineString，并将源栅格 CRS 赋给路径图层和端点图层；`crs="unknown"` 的甲组样例不能直接当作经纬度或投影地图叠加。路径的 `total_cost` 字段来自引擎；实际距离需根据 CRS 和地图单位另行计算。若需要逐段成本矢量属性，可按 `step_costs` 分段建线，或在完整路径上保存序列化明细。若后续真实栅格含旋转项，应由甲组扩展空间变换，丁组不能沿用上述无旋转公式。

## 待乙组和老师确认

- 穿越栅格的成本究竟按进入格、离开格，还是相邻格均值计；当前均值只是可替换的默认约定。
- 斜向系数 `k` 是否固定 `√2`，以及拐角处是否禁止斜穿。
- 甲组已提交 4×4 / 5×5 通用样例，丙组已纳入自动化测试；仍需乙组确认起终点与期望总成本，形成正式手算金标准。
