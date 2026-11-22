# 丙组搜索引擎接口约定 · 2026-11-22 联调版

## 输入

```python
CostGrid(rows, nodata=None)
CostGrid.from_raster(raster_data)
find_path(grid, start, goal, *, algorithm="dijkstra",
          diagonal_multiplier=2**0.5, allow_corner_cutting=True,
          cost_mode="target", include_start=False,
          nonpositive_blocked=True, blocked_values=(),
          step_cost=None, neighbor_provider=None)

# 按乙组 CostConfig 直接计算，返回 PathResult(path, stats)
from contract import shortest_path
shortest_path(raster_data, (0, 0), (3, 3), algorithm="astar")
```

| 参数 | 约定 |
| --- | --- |
| `rows` / `raster_data` | 可直接传甲组 `cost_raster.load_raster_file()` 返回的 `RasterData` 字典；也可传矩形二维数组。有效成本为有限非负数，`None` 为障碍；裸数组的 `-9999` 默认作为 NoData。`CostGrid(rows, nodata=-9999)` 可显式指定数值 NoData。 |
| `start`、`goal` | 零起始 `(row, col)` 整数；必须在栅格内且可通行。甲/丁组负责鼠标坐标或手输地图坐标到格号的转换。 |
| `algorithm` | `"dijkstra"` 或 `"astar"`；两者在同一非负边权下应得到同一最小总成本，路线形状可能因等价路径而不同。 |
| `diagonal_multiplier` | 斜向移动系数，有限且大于 0；默认 `√2`。正交系数恒为 1。系数小于 1 时 A* 使用零启发式保证最优性。 |
| `cost_mode` / `include_start` | 默认 `target`，即进入格成本 × 移动系数；`average` 为两格均值 × 系数。起点默认不计费。 |
| `allow_corner_cutting` | 默认 `True`，与乙组 `CostConfig` 对齐；设为 `False` 时斜向移动须保证两侧正交邻格均可通行。 |
| `nonpositive_blocked` / `blocked_values` | 默认非正值不可通行；可以另设障碍值集合。`None` 与 NoData 始终是障碍。 |
| `step_cost` | 独立引擎兼容第一周的三参数回调 `step_cost(from_cost, to_cost, movement_factor) -> 非负有限数`。 |
| `neighbor_provider` | 跨组接口接收乙组 `neighbor_steps(cost, cell, cfg)` 输出的 `(邻格, 边权, 系数)`。`contract.shortest_path` 已实际接通该接口，并返回 `path` 和含逐段明细的 `stats`。 |

自定义 `step_cost` 下 A* 使用零启发式，保持最优性；标准乙组规则使用栅格最小成本作为安全下界。`neighbor_provider` 默认使用零启发式；只有提供经证明的 `heuristic_min_cost` 下界才会启用。成本为 0 的格子需显式设 `nonpositive_blocked=False` 才能通行。负成本、无穷大与 NaN 拒绝输入。

## 输出与错误

`find_path` 返回 `RouteResult`，可用 `.to_dict()` 变成普通字典：

```json
{
  "path_cells": [[0, 0], [1, 1]],
  "step_costs": [5.656854249492381],
  "total_cost": 5.656854249492381,
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

## 当前联调结果与待确认规则

- 乙组手算金标准 `14√2 ≈ 19.799` 与甲组含 NoData 4×4 样例 `23+4√2 ≈ 28.657` 已由 Dijkstra、A* 和统一接口通过测试。
- 现在统一采用乙组的 `target`、`allow_corner_cut=True`、`include_start=False` 默认值；这是团队当前联调口径，老师尚未最终确认。规则变化时传 `CostConfig`，不改搜索核心。
- 第一周报告中的均值口径及丁组此前 10×10 演示数值属于历史记录，不能与当前默认口径混用。丁组需要以新版本重新演示并核对图层字段。
