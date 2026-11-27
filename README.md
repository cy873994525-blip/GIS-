# GIS 第二次作业 · 成本路径插件（栅格成本路径计算与可视化）

课程分组开发作业：在栅格成本表面上计算起点到终点的路径成本，并输出路径矢量图层与总成本。
不引入独立的完整程序或数据库管理，复用课程提供的数据读取与功能。

## 二次开发平台

**平台选型：QGIS 桌面端 + Python 插件（PyQGIS）。**

选择理由：四人都可免费安装、跨 Windows / macOS / Linux；插件用 Python 编写，不必按平台编译；
本仓库的数据层、成本规则层、搜索引擎层已全部用 Python 标准库实现，接入 QGIS 时只需补插件界面与
图层输出，算法代码不用重写。栅格读取、鼠标点选取点、坐标与像元换算、LineString 及点图层创建
在 PyQGIS 中均有现成接口。

分层与平台的对应关系：

| 层 | 落地方式 |
| --- | --- |
| 数据与坐标层（甲） | 纯 Python，`cost_raster.py` 读栅格，`coord_transform.py` 换算坐标与行列号；与 QGIS 的交接见下文「与 QGIS 的对接点」 |
| 成本规则层（乙） | 纯 Python，不依赖 QGIS |
| 搜索引擎层（丙） | 纯 Python，不依赖 QGIS |
| 插件与矢量图层（丁） | PyQGIS：`QgsMapToolEmitPoint` 取点、对话框用 PyQt、`QgsVectorLayer` 建 LineString 与端点图层 |

> 平台只影响丁的图层与界面部分，前三层保持与平台无关，便于在无 QGIS 环境（如 CI、纯 Python 测试）里跑通。

## 分组分工（四人）

| 成员 | 模块 | 职责 |
| --- | --- | --- |
| **甲（本人）** | 数据与坐标层 | 栅格加载封装、点选/键盘坐标 ↔ 行列号双向换算、越界与 NoData 校验、通用测试数据准备、输入链路联调 |
| 乙 | 成本规则层 | 8 邻域生成、正交系数 1 / 斜向系数 k、单步代价公式、障碍与切角规则、手算金标准 |
| 丙 | 搜索引擎层 | Dijkstra / A* 路径求解、接口约定、速度测试（节点数、耗时、规模对比） |
| 丁 | 插件与矢量图层 | 插件骨架与对话框、LineString 路径图层、起终点图层、样式标注、端到端串联与交付汇总 |

> 集成联调不单设角色：丙牵头接口约定，甲接通输入、乙对齐代价口径、丁端到端串联。

## 甲（数据与坐标层）进度拆分（约 4 次）

| 进度 | 目标 | 主要内容 | 状态 |
| --- | --- | --- | --- |
| **第 1 次** | 项目骨架 + 栅格加载封装与基础校验 | 仓库结构、`cost_raster.py` 栅格读取/元数据/基础校验、4×4 与 5×5 通用测试样例、单元测试、README 分工与进度记录 | ✅ 已完成（2026-11-16） |
| **第 2 次** | 坐标 ↔ 行列号双向换算 | `coord_transform.py`：格心/左上角换算、反算与边界语义、键盘输入解析、起终点落点校验、GeoTransform 与 PyQGIS 适配；30 项单元测试 | ✅ 已完成（2026-11-21） |
| 第 3 次 | 越界 / NoData 输入校验闭环 | 非法落点、NoData 格、超范围坐标的拦截与中文提示；与丙约定栅格数组与起终点行列号接口；输入侧测试用例归档 | ⬜ 待做 |
| 第 4 次 | 输入链路联调与测试材料 | 配合丙把真实点选/键盘输入接到引擎；整理输入侧测试用例、截图与说明，纳入提交材料 | ⬜ 待做 |

## 目录结构

```text
GIS第二次作业/
├── README.md                   # 平台选型、分工、进度、运行与测试
├── cost_raster.py              # 甲：栅格加载、元数据、基础校验与成本取值
├── coord_transform.py          # 甲：坐标与行列号换算、输入解析、QGIS 对接
├── cost_rules.py               # 乙：成本规则与单步代价
├── golden_cases.py             # 乙：手算金标准样例
├── contract.py                 # 乙：全组接口契约草案
├── cost_path/                  # 丙：Dijkstra / A* 搜索引擎
├── benchmarks/                 # 丙：固定种子的规模测速与记录
├── qgis_cost_path/             # 丁：QGIS 插件与成本路径可视化
│   ├── __init__.py             # QGIS 插件加载入口
│   ├── metadata.txt            # 插件名称、版本与 QGIS 版本要求
│   ├── plugin.py               # 注册工具栏按钮与菜单入口
│   ├── dialog.py               # 成本网格、起终点选择与路径结果展示
│   └── github_sync.py          # 检查 GitHub main 更新与缓存版本回退
├── build_qgis_plugin.py        # 丁：生成可安装的 QGIS 插件 ZIP
├── docs/                       # 接口草案与第一周测试报告
├── sample_data/
│   ├── cost_grid_4x4.json       # 4×4 通用测试样例
│   ├── cost_grid_5x5.json       # 5×5 通用测试样例
│   └── cost_grid_10x10.json     # 丁：10×10 障碍绕行演示样例
└── tests/
    ├── test_cost_raster.py      # 甲：栅格读取与校验测试
    ├── test_coord_transform.py  # 甲：坐标换算测试
    ├── test_cost_rules.py       # 乙：成本规则测试
    └── test_engine.py           # 丙：搜索准确性与数据对接测试
```

## 运行与测试

后端核心只使用 Python 标准库，Python 3.8+ 可直接运行。

```powershell
# 运行全部测试（当前 81 项）
python -m unittest discover -s tests -v

# 只跑甲的两个模块
python -m unittest discover -s tests -p "test_cost_raster.py" -v
python -m unittest discover -s tests -p "test_coord_transform.py" -v

# 语法检查
python -m py_compile cost_raster.py coord_transform.py
```

坐标换算的最小示例（键盘输入 → 行列号）：

```python
from cost_raster import load_raster_file
from coord_transform import resolve_point, require_passable, cell_to_map

raster = load_raster_file("sample_data/cost_grid_4x4.json")
p = require_passable(resolve_point(raster, "0.5, 3.5", role="起点"))
print(p["row"], p["col"], p["cost"], p["message"])
x, y = cell_to_map(raster, p["row"], p["col"])   # 反向取格心坐标
```

## 成本栅格 JSON 格式

```json
{
  "crs": "unknown",
  "nodata": -9999,
  "origin": [0, 4],
  "pixel_size": [1, 1],
  "values": [
    [5, 7, 8, 4],
    [4, -9999, 7, 8],
    [7, 8, 4, 5],
    [8, 4, 5, 7]
  ]
}
```

- `values[r][c]`：第 r 行第 c 列成本（0 基下标）；NoData 格记为 `nodata` 值，视为不可通行。
- `origin`：左上角坐标 `[xmin, ymax]`；`pixel_size`：单格步长 `[sx, sy]`。
- 当前样例为平面网格坐标；接入真实底图前需确认坐标系（CRS）与投影，由后续进度处理。

## 第 1 次进度记录（甲）

**完成时间**：2026-11-16

**本次完成内容**

1. 搭建仓库基础结构，明确四人分工与甲的四次进度规划。
2. 新增 `cost_raster.py`：
   - 封装成本栅格加载（矩阵 / JSON 文件两种入口）；
   - 统一内部 `RasterData` 结构（行列数、NoData、成本矩阵、原点、步长、坐标系、bounds）；
   - 基础校验：空栅格、行列不齐、非数值成本、负成本、非法原点/步长；
   - 提供越界判断、NoData 判断、成本取值与元数据摘要接口，供乙/丙/丁按同一结构取用。
3. 准备两份通用测试样例：4×4 与 5×5 成本栅格（成本值 5/7/8/4，含 NoData 障碍格）。
4. 新增 `tests/test_cost_raster.py`：覆盖矩阵结构、NoData 标记、越界拦截、行列不齐/非数值/负成本拒绝、摘要统计、文件读取与坏数据用例。

**验证**：单元测试通过；`py_compile` 语法检查通过。

**本次未做（留给后续进度）**：坐标 ↔ 行列号双向换算、键盘/点选输入解析、与丙引擎的接口联调、前端对话框与图层（丁负责）。

## 第 2 次进度记录（甲）

**完成时间**：2026-11-21
**提交**：`1ffb1c6`
**上传时间**：2026-11-21 23:12（UTC+8），已推送至 `origin/main`
**本次对应任务**：坐标 ↔ 行列号双向换算 + 与 QGIS 平台的坐标对接准备（第 2 次进度）

**本次完成内容**

1. 平台确定：经四人讨论，二次开发平台选定 **QGIS + Python 插件（PyQGIS）**，理由与分层对应关系见文首「二次开发平台」一节。
2. 新增 `coord_transform.py`（坐标层核心换算）：
   - `cell_to_map`：行列号 → 地图坐标，支持格心（`anchor="center"`，路径节点与属性挂接使用）与格左上角（`anchor="corner"`，边界核对使用）；
   - `map_to_cell`：地图坐标 → 行列号，0 基、行向下增大，与 `cost_raster.values` 行序及丙组引擎的 `(row, col)` 约定一致；
   - 边界语义：外接矩形右边界 `x=xmax`、下边界 `y=ymin` 归入最后一列 / 最后一行（GDAL 闭区间约定）；超出图幅即报错，不静默夹紧到边缘格；
   - `parse_coord_text`：键盘坐标录入解析，容忍半角/全角逗号、分号、空格、制表符、中英文括号、全角数字、正负号、小数与科学计数法；必须恰好两个数值，多一个少一个都报错，避免静默截断；
   - `resolve_point` / `describe_cell` / `require_passable`：把键盘输入一次走完「解析 → 换算 → 越界 → NoData」四道校验，输出含中文提示的结构，引擎只会收到合法行列号；
   - `from_geotransform` / `to_geotransform`：与 GDAL、QGIS 的 6 参数地理变换互相转换；含旋转分量的栅格明确报错，不给出看似正常实则错位的结果；
   - `from_qgis_layer`：从 `QgsRasterLayer` 取地理变换与尺寸并转成本项目栅格结构；PyQGIS 采用延迟导入，纯 Python 环境不会因缺少 qgis 包而失败。
3. 新增 `tests/test_coord_transform.py`：**30 项单元测试**，覆盖格心/角点换算、全格往返一致、非正方像元、经纬度负坐标方向、右/下边界归属、越界与浮点容差、NoData 落点拦截、多种键盘输入格式与非法输入、GeoTransform 往返及旋转拒绝。
4. 更新 `cost_raster.py` 模块说明，明确坐标换算职责已移交 `coord_transform.py`。

**验证**：`test_coord_transform.py` 30 项全部通过；仓库全量 `python -m unittest discover -s tests` 共 **81 项**全部通过；`py_compile` 语法检查通过。

**本次未做（留给后续进度）**：与丙引擎的输入链路联调（第 4 次）、QGIS 地图画布点击取点的实际联调（需在装有 QGIS 的机器上由丁配合验证）、真实课程栅格的 CRS / 投影确认。

### 与 QGIS 的对接点

| 环节 | 甲提供的接口 | 丁在 QGIS 中的用法 |
| --- | --- | --- |
| 栅格读入 | `load_raster_file(path)` 或 `from_qgis_layer(layer, values=...)` | 打开课程栅格图层后取地理变换与尺寸，成本矩阵由课程数据读出 |
| 鼠标点选 | `map_to_cell(raster, x, y)` | `QgsMapToolEmitPoint` 拿到画布坐标，先 `mapToLayer` 转图层坐标再调用 |
| 键盘输入 | `resolve_point(raster, text, role="起点")` | 对话框输入框直接调用，返回 `row/col/cost/blocked` 与中文提示 |
| 路径节点出图 | `cell_to_map(raster, row, col)` | 路径格点逐个转格心坐标，串成 LineString 顶点 |
| 图层坐标参考 | `raster["crs"]`、`to_geotransform(raster)` | 输出图层沿用源栅格 CRS，核对像元对齐 |

> 换算层只做定位，不判断是否可通行；是否 NoData 由 `require_passable` 与引擎判定，避免同一规则在两个模块里重复实现。

## 丙（搜索引擎层）第 1 次进度记录 · 2026-11-16

1. 新增 `cost_path/`：标准库实现的 8 邻域最小堆 Dijkstra 与可切换 A*，返回路径格点、逐段成本、总成本、格网长度、扩展节点数和搜索耗时。
2. 引擎可直接接收甲组 `cost_raster.py` 的 `RasterData` 字典；数值 NoData 标记自动视为不可通行，原始矩阵和 CRS 元数据不被修改。接口说明见 [丙组接口约定](docs/integration-contract.md)。
3. 默认逐步成本为两格成本均值乘正交/斜向系数（斜向默认 `√2`），可接入乙组正式代价函数；默认禁止穿越障碍拐角。乙组/老师确认前，此默认规则只作第一周基线。
4. 测试包含甲组 4×4、5×5 样例，手算 5/7/8/4、障碍/切角/无路径/非法值，以及 30 组随机小格 × 3 种斜向系数与独立算法对照。运行全部测试：

   ```powershell
   python -m unittest discover -s tests -v
   ```

5. `benchmarks/run.py` 用固定种子对 100²、500²、1000² 两类格网比较准确性、扩展节点和耗时；首轮数据与限制见 [第一周测试记录](docs/week1-report.md)。

简单调用：

```python
from cost_raster import load_raster_file
from cost_path import find_path

raster = load_raster_file("sample_data/cost_grid_4x4.json")
result = find_path(raster, (0, 0), (3, 3), algorithm="dijkstra")
print(result.to_dict())
```

**第一周时的下一步**：丙与乙对齐逐步成本和切角规则，把甲组样例的期望结果定为手算金标准；与甲继续对接坐标转行列接口。这些工作中的规则与金标准已在下方第二次进度完成。第一周使用的均值成本及禁切角默认值仅作历史基线。

## 丙（搜索引擎层）第 2 次进度记录 · 2026-11-22

1. 核对了甲组的 `cost_raster.py` / `coord_transform.py`、乙组的 `cost_rules.py` / `golden_cases.py`、丁组的 QGIS 插件入口和内置 10×10 演示。搜索引擎默认规则现与乙组 `CostConfig` 对齐：进入格计费、斜向系数 `√2`、起点不计费、允许切角、非正值和 NoData 不可通行。`average`、禁切角、起点计费等可由参数切换。**这是当前团队联调口径，尚待老师最终确认。**
2. `contract.shortest_path` 从占位实现改为真实 Dijkstra / A*，直接消费乙组 `neighbor_steps`，返回路径、总成本、长度、步数、扩展节点、耗时和乙组逐段明细。独立 `find_path` 仍供丁组已有插件调用，调用默认值已经对齐。修复乙组类型别名在项目使用的 Python 3.8 上无法导入的问题。
3. 接入乙组手算金标准：4×4 默认路径成本 `14√2 ≈ 19.799`；甲组含 NoData 的 4×4 样例为 `23+4√2 ≈ 28.657`。Dijkstra、A* 和统一接口均通过核验；全量自动化测试见下文命令。
4. 用新口径重新测试 100² / 500² / 1000² 均一和随机栅格，记录准确性、扩展节点及速度。详见 [第二次联调与测试记录](docs/week2-report.md) 和 [机器可读结果](benchmarks/week2-2026-11-22.json)。第一周的均值口径报告保留，不能直接拿其成本数字比较。

```powershell
python -m unittest discover -s tests -q
python benchmarks/run.py --output benchmarks/week2-2026-11-22.json
```

```python
from cost_raster import load_raster_file
from contract import shortest_path

raster = load_raster_file("sample_data/cost_grid_4x4.json")
route = shortest_path(raster, (0, 0), (3, 3), algorithm="astar")
print(route.path, route.stats["total_cost"])
```

丁组 QGIS 网格窗口会随新引擎采用本次统一默认规则；先前 10×10 演示的 `55.60` 是旧口径记录，需在 QGIS 中按本次提交重新核对。地图坐标输入、真实底图上的 LineString 与端点矢量层仍是丁组后续集成任务。

## 乙（成本规则层）第 1 次进度记录 · 2026-11-16

1. 新增 `cost_rules.py`：只回答一个问题——从格 a 走到相邻格 b 要付多少代价；不负责读文件、不搜索路径、不画图。对外提供 `step_cost(cost, a, b, k)`（全组契约签名，已实现，非桩）、供丙组遍历的 `neighbor_steps(cost, cell, cfg)`、供丁组逐段字段与总成本回写的 `path_step_details(...)` 和 `path_total_cost(...)`。
2. 成本规则全部参数化（见 `CostConfig`），四人碰头后改配置即可冻结口径，不必改算法：8 邻域、正交系数 1 / 斜向系数 k（默认 `√2`）；单步代价两种口径可切换——`target`（进入格成本 × 距离系数，乙组默认）与 `average`（两格成本均值 × 距离系数）；起点格是否计入、是否允许穿越障碍拐角（切角）、NoData / 非正值 / 自定义值视为障碍。不可通行的一步返回 `math.inf` 而非抛异常，搜索层可直接跳过。
3. 兼容甲组数据结构：`cost_rules` 直接接收 `cost_raster.py` 返回的 `RasterData` 字典（含 `values` / `nodata`），自动采用其中的 nodata 值，调用方无需手工拆出 `values`；同时也接受裸二维矩阵（list / numpy 数组）。
4. 新增 `golden_cases.py`：所有期望值由解析式手算给出，不从本项目算法反推，避免循环验证，供丙组校验 Dijkstra / A*。含自建 4×4 样例（默认口径对角路径 `14√2 ≈ 19.799`，average 口径 `14.5√2 ≈ 20.506`）、甲组通用 4×4 样例（含 NoData，最优路径 `(0,0)→(1,0)→(2,0)→(3,1)→(3,2)→(3,3)`，总成本 `23+4√2 ≈ 28.657`）、2×2 斜向系数生效样例（k=`√2` 时对角 1.414 < 正交 3；k=4 时对角 4 > 正交 3）及障碍 / 切角样例。
5. 新增 `contract.py`：全组接口契约草案（v0.1），已对齐甲组 `RasterData` 结构；`step_cost` / `neighbor_steps` 为乙组真实实现。本段为第一周原始记录；`shortest_path` 已在丙组第二次进度接入真实搜索，`load_cost_raster` 与 `path_to_layer` 示例接口仍为桩。
6. 新增 `tests/test_cost_rules.py`：31 项单元测试，覆盖邻域生成、斜向系数、两种代价口径、逐格累加、NoData / 障碍 / 切角、起点计入开关、越界与不相邻异常，并含 5 项与甲组 `RasterData` 结构的对接用例。运行：

   ```powershell
   python -m unittest discover -s tests -p "test_cost_rules.py" -v
   ```

**验证**：31 项单元测试全部通过；`py_compile` 语法检查通过；甲组 `RasterData` 直算结果与金标准 `28.656854` 一致。

**待四人冻结的口径（重要）**：乙组默认 `target`（进入格成本 × 系数），丙组第一周默认 `average`（两格均值 × 系数），两者总成本不同；斜向系数、起点是否计入、是否允许切角也需一并定死。切换只需改 `CostConfig`，调用方无需改动。

**下周重点**：与丙组确认正式单步代价与切角规则，把甲组样例期望值定为全组金标准；把 `neighbor_steps` 接入丙组 Dijkstra / A*；按冻结口径为丁组提供 `path_step_details` 逐段字段，用于矢量图层属性表。

## 乙（成本规则层）第 2 次进度记录 · 2026-11-22

1. 与丙组对齐并冻结当前联调口径：`target`（进入格成本 × 距离系数）、斜向系数 `√2`、起点不计、默认允许切角；`CostConfig` 保留 `average` / 自定义 k / 禁切角开关，老师最终确认后只改配置，不改算法代码。
2. 补齐分工表第 3、4 条（三角公式与 48m×48m 像元）：`cost_rules.py` 新增 `diagonal_factor_from_pixels()`、`step_length_m()`、`path_length_m()` 与 `PIXEL_SIZE_48M`。48m 正方形像元斜向一步 48√2≈67.88 米，样例路径总长 144√2≈203.65 米；长度只写入丁组矢量图层字段，不乘进成本，避免与金标准冲突。
3. `golden_cases.py` 增补 48m 长度金标准与结构化样例；`tests/test_cost_rules.py` 由 31 项增至 **37 项**，覆盖三角公式、非正方形像元、长度累加、48 米不影响成本及非法像元。
4. 以乙组手算解析式复核 `contract.shortest_path`：4×4 默认 `14√2≈19.79899`、含 NoData 样例 `23+4√2≈28.65685`、k=4 时最优路线切换，Dijkstra / A* / 统一接口结果一致。完整手算与对照记录见 [乙组第二次准确性对照](docs/week2-cost-rules-report.md)。
5. 验证：全仓库 `python -m unittest discover -s tests -q` **89 项全部通过**，`py_compile` 语法检查通过。

**待确认**：对角穿越障碍是否禁切角、最终计费口径（`target` / `average`）；变更只需改 `CostConfig` 并同步丙组与丁组界面。




## 第 1 次进度记录（丁成员 · 插件与可视化）

**完成时间**：2026-11-21 至 2026-11-22  
**本次任务**：搭建 QGIS 插件运行环境，打通成本栅格加载、起终点选择、路径求解和结果可视化流程。

### 本次完成内容

1. **搭建并验证 QGIS 二次开发环境**  
   在 macOS 上安装 QGIS 3.44.15，完成 PyQGIS 插件的打包、安装和加载验证。新增 `build_qgis_plugin.py`，将插件代码、路径搜索引擎和内置样例统一打包为可安装的 ZIP。

2. **实现 QGIS 插件入口与交互式路径分析窗口**  
   在 `qgis_cost_path/plugin.py` 注册工具栏绿色箭头和菜单入口，在 `qgis_cost_path/dialog.py` 实现成本分析窗口。用户可选择内置样例或导入 JSON，在网格上点选起终点并切换 Dijkstra 和 A*。窗口调用项目现有的搜索引擎，绘制最低成本路径，并展示总成本、路径长度、扩展节点数、搜索耗时及逐段成本。

3. **接入 GitHub 主分支更新流程**  
   在 `qgis_cost_path/github_sync.py` 实现打开插件时检查 GitHub `main` 分支的机制。插件窗口标题显示当前加载的提交号，便于演示时核对版本。界面、算法和样例更新提交到 `main` 后，可通过重新打开插件来加载。网络不可用或新版加载失败时，插件可回退到上次可用版本。

4. **新增 10×10 成本网格与障碍绕行样例**  
   新增 `sample_data/cost_grid_10x10.json`，将其接入内置样例下拉菜单和 ZIP 打包清单，保留原有 4×4、5×5 样例。10×10 网格在第 5 列设置 NoData 障碍，并在第 8 行留出通道，用于观察搜索算法如何避开障碍并选择最低成本路线。

### 验证结果

在 QGIS 中通过绿色箭头打开插件，确认窗口可以加载 GitHub 版本并运行 10×10 样例。使用 Dijkstra 从第 3 行第 1 列搜索到第 5 行第 9 列，路线经过第 8 行第 5 列的通道，**总成本为 55.60，路径长度约为 12.49 格**。

## 丁成员第 2 次进度记录 · 2026-11-26

### 本次目标

完成甲、乙、丙三个模块与 QGIS 插件的统一对接，使组员已经完成的数据读取、坐标转换、成本规则和最短路径算法能够通过 QGIS 图形界面完整运行。

### 本次完成内容

1. **完成四人模块的统一调用链**
   将 QGIS 插件调整为以下调用流程：
   ```text
   甲组 cost_raster.py
   成本栅格读取与 NoData 校验
   ↓
   甲组 coord_transform.py
   地图坐标与栅格行列号转换
   ↓
   乙组 cost_rules.py
   障碍判断、邻格生成和单步成本计算
   ↓
   丙组 contract.shortest_path()
   Dijkstra / A* 最低成本路径搜索
   ↓
   丁组 QGIS 插件
   参数输入、路径显示和矢量图层输出
   ```
2. **接入统一路径搜索接口**
   插件由原先直接调用独立搜索引擎，改为调用：
   ```python
   contract.shortest_path()
   ```
   该接口能够直接接收甲组生成的 `RasterData`，并在搜索过程中调用乙组的 `neighbor_steps()` 和成本配置。
   返回结果包括：
   ```text
   路径格点
   总成本
   路径长度
   移动步数
   扩展节点
   搜索耗时
   逐段成本
   累计成本
   ```
3. **接入坐标与行列号转换**
   插件接入甲组的以下接口：
   ```python
   resolve_point()
   map_to_cell()
   cell_to_map()
   require_passable()
   ```
   对带有真实 CRS 的数据，输入框按照 `X,Y` 地图坐标解析。
   对 `CRS=unknown` 的内置样例，输入框按照用户看到的“行号,列号”解析，并从 1 开始计数。
   修复了内置 5×5 样例中输入 `1,1` 后错误定位到第 5 行第 2 列的问题。修复后：
   ```text
   输入 1,1 → 第1行第1列
   输入 5,5 → 第5行第5列
   输入 3,2 → 命中 NoData，拒绝作为端点
   ```
4. **统一障碍与 NoData 规则**
   插件界面与路径搜索统一调用乙组的障碍判断规则。
   以下格子均不可通行：
   ```text
   NoData
   非有限数值
   非正成本
   CostConfig 中指定的障碍值
   ```
   起点或终点落在障碍格时，插件会显示错误提示，并保留上一次有效选择。
5. **生成路径线和起终点图层**
   新增：
   ```text
   qgis_cost_path/qgis_layers.py
   ```
   该模块负责把路径中的 `(row, col)` 转换为像元中心坐标，并生成：
   ```text
   最小成本路径 LineString 图层
   成本路径端点 Point 图层
   ```
   路径属性包括：
   ```text
   段序号
   起始行列号
   目标行列号
   单步成本
   累计成本
   总成本
   路径长度
   实际距离
   算法名称
   ```
6. **完善插件打包与 GitHub 同步**
   更新以下文件：
   ```text
   build_qgis_plugin.py
   qgis_cost_path/github_sync.py
   qgis_cost_path/plugin.py
   ```
   将甲、乙、丙的模块统一加入插件安装包和 GitHub 在线同步范围。
   插件打开时会检查 GitHub `main` 分支，并在窗口标题中显示当前提交号。同步失败时可以回退到上一次可用版本。
### 验证结果
原项目 89 项自动化测试全部通过。
甲组 4×4 样例从第 1 行第 1 列到第 4 行第 4 列的结果为：
```text
总成本：28.656854
路径长度：5.414214 格
移动步数：5
```
Dijkstra 与 A* 均得到相同最低成本。
第一周 10×10 演示起终点按照当前统一成本规则重新计算后为：
```text
总成本：51.840620
路径长度：11.899495 格
移动步数：9
```
路径仍经过第 8 行第 5 列的障碍通道。此前记录的 `55.60` 属于第一周旧成本口径。
---
## 丁成员第 3 次进度记录 · 2026-12-01
### 本次目标
接入真实成本栅格数据，使插件可以直接读取 GeoTIFF，并在插件窗口内完成真实栅格显示、起终点选择、最短路径计算和路线绘制。
### 真实数据说明
本次使用北京香山真实道路选线成本数据：
```text
文件：cost.tif
格式：单波段 Float32 GeoTIFF
坐标系：EPSG:32650
栅格尺寸：334 × 334
像元尺寸：30 × 30 米
NoData：-9999
有效成本范围：1–96
有效像元：106529
NoData 像元：5027
```
栅格成本已经由土地覆盖成本与坡度系数计算完成：
```text
最终格子成本 = 土地覆盖成本 × 坡度系数
```
高程数据用于计算坡度，插件直接读取最终生成的成本栅格。
### 本次完成内容
1. **增加 GeoTIFF 文件入口**
   插件顶部新增：
   ```text
   导入 GeoTIFF…
   ```
   用户可以直接选择 `.tif` 或 `.tiff` 文件。
   插件自动读取：
   ```text
   第1波段成本值
   栅格行列数
   CRS
   GeoTransform
   像元尺寸
   NoData 掩膜
   ```
2. **支持真实大栅格**
   原插件表格适合 4×4、5×5 和 10×10 小样例。真实数据包含：
   ```text
   334 × 334 = 111556 个像元
   ```
   为避免创建十多万个表格单元造成界面卡顿，插件为大栅格增加专用图像视图。
   该视图将成本矩阵绘制成彩色栅格图，并直接显示在插件窗口中。
3. **实现窗口内点击选点**
   用户选择“起点”或“终点”后，可以直接点击插件中的栅格图。
   插件会把点击位置转换为对应格子，并自动执行
   ```text
   坐标范围校验
   NoData 校验
   障碍校验
   路径重新计算
   路线重新绘制
   ```
4. **建立统一栅格坐标约定**
   真实栅格在插件窗口中使用以下坐标规则：
   ```text
   左上角为 X=0,Y=0
   X 方向向下增加
   Y 方向向右增加
   一个像元代表一个坐标单位
   ```
   334×334 栅格的合法输入范围为：
   ```text
   X：0–333
   Y：0–333
   ```
   数据包 `cases.json` 中的：
   ```text
   start_cell = [250, 283]
   ```
   在插件中显示为：
   ```text
   X=250, Y=283
   ```
5. **在栅格图上叠加路径**
   计算完成后，插件直接在成本栅格图上绘制：
   ```text
   青绿色最低成本路径
   绿色起点
   棕红色终点
   白色路线描边
   ```
   鼠标悬停在栅格上时，会显示：
   ```text
   X
   Y
   当前格子成本
   ```
6. **支持真实地图画布**
   GeoTIFF 导入后同时加入 QGIS 图层面板，并自动缩放到栅格范围。
   用户既可以在插件窗口内点击选点，也可以使用“地图点选”功能在 QGIS 画布上选点。
   QGIS 画布坐标会先转换到成本栅格 CRS，再转换为栅格行列号。
7. **使用真实成本运行最短路径算法**
   路径搜索继续支持：
   ```text
   Dijkstra
   A*
   ```
   单步成本采用当前团队统一规则：
   ```text
   正交移动成本 = 进入目标格的成本 × 1
   斜向移动成本 = 进入目标格的成本 × √2
   ```
   起点格默认不计费，NoData 和障碍格不可进入。
### 验证结果
使用真实 `cost.tif` 完成以下验证：
```text
GeoTIFF 文件选择
第1波段读取
EPSG:32650 识别
30米像元识别
NoData 读取
334×334 大栅格显示
窗口点击到格子坐标转换
键盘 X,Y 输入
Dijkstra 路径计算
A* 路径计算
窗口内路线叠加
QGIS 图层输出
```
真实数据可以在插件窗口中完成从成本栅格读取到最低成本路径显示的完整流程。
---
## 丁成员第 4 次进度记录 · 2026-12-08
### 本次目标
在真实路径计算基础上增加算法实验、实际距离、成本分析、颜色图例和结果导出，使插件能够直接用于课程演示、实验对比和最终报告。
### 本次完成内容
1. **增加 Dijkstra 与 A* 对比**
   新增按钮：
   ```text
   对比 Dijkstra / A*
   ```
   设置起点和终点后，插件会使用相同的成本栅格和成本规则分别运行两种算法。
   对比表显示：
   | 算法 | 总成本 | 路径长度/格 | 实际距离/米 | 扩展节点 | 耗时/ms |
   |---|---:|---:|---:|---:|---:|
   | Dijkstra | 自动计算 | 自动计算 | 自动计算 | 自动统计 | 自动统计 |
   | A* | 自动计算 | 自动计算 | 自动计算 | 自动统计 | 自动统计 |
   该功能可以验证两种算法是否得到相同最低成本，并比较扩展节点数与搜索效率。
2. **增加实际距离**
   原插件只显示以格为单位的路径长度。本次加入米和千米单位。
   对 30×30 米像元：
   ```text
   正交移动一步 = 30 米
   斜向移动一步 = 30√2 米
   ```
   结果区同时显示：
   ```text
   路径长度：352.71 格
   实际距离：10581.30 米（10.581 千米）
   ```
   实际距离只在栅格 CRS 为米制投影坐标系时计算。
3. **增加路径成本分析**
   结果区新增“成本分析”标签页，显示：
   ```text
   经过格数
   移动步数
   正交移动步数
   斜向移动步数
   最低格子成本
   最高格子成本
   平均格子成本
   NoData / 障碍格数量
   ```
   路径不会进入 NoData，因此合法路径中的障碍格数量始终为 0。
4. **增加颜色图例**
   栅格图下方增加颜色说明：
   ```text
   绿色：低成本
   黄色：中成本
   红色：高成本
   深色：NoData / 不可通行
   青绿色线：最低成本路径
   ```
   成本颜色按照当前栅格的有效最小值和最大值进行归一化显示。
5. **明确显示 X/Y 栅格范围**
   导入 GeoTIFF 后，界面显示：
   ```text
   X方向格数
   X合法坐标范围
   Y方向格数
   Y合法坐标范围
   总像元数
   坐标增长方向
   ```
   对当前真实数据：
   ```text
   X方向：334格，0–333，向下增加
   Y方向：334格，0–333，向右增加
   总像元：111556
   左上角：X=0,Y=0
   ```
   用户可以据此输入合法的起终点坐标。
6. **增加完整结果导出**
   新增按钮：
   ```text
   导出完整结果…
   ```
   用户可以选择保存目录和 GeoPackage 文件名。
   假设保存为：
   ```text
   xiangshan_path.gpkg
   ```
   插件会生成：
   ```text
   xiangshan_path.gpkg
   xiangshan_path_summary.csv
   xiangshan_path_segments.csv
   ```
   GeoPackage 包含两个图层：
   ```text
   route_segments
   endpoints
   ```
   `route_segments` 保存每一段路径及其成本属性，`endpoints` 保存起点和终点。
   摘要 CSV 包含：
   ```text
   算法
   起终点
   X/Y格数
   总成本
   栅格长度
   米制距离
   千米距离
   正交与斜向步数
   最低、最高和平均格子成本
   扩展节点
   搜索耗时
   CRS
   Dijkstra/A* 对比结果
   ```
   逐段 CSV 包含：
   ```text
   段序号
   起点X/Y
   终点X/Y
   进入格成本
   移动系数
   单步成本
   累计成本
   ```
7. **重新组织结果界面**
   右侧结果区域划分为三个标签页：
   ```text
   逐段明细
   成本分析
   算法对比
   ```
   可以在同一个窗口中分别查看路径细节、统计信息和算法实验结果。
### 验证结果
完成以下自动化和 QGIS 环境验证：
```text
89 项原有 Python 测试全部通过
插件文件语法检查通过
Dijkstra/A* 对比表生成成功
米制距离与千米距离计算正确
路径成本分析生成成功
334×334 X/Y 范围显示正确
GeoPackage 路径图层导出成功
GeoPackage 端点图层导出成功
摘要 CSV 导出成功
逐段成本 CSV 导出成功
插件 ZIP 完整性检查通过
```
使用 48 米投影样例验证得到：
```text
总成本：28.656854
路径长度：5.414214 格
实际距离：259.882251 米
路径分段：5
端点要素：2
```
### 当前成果
经过三次开发，插件已经形成以下完整流程：
```text
真实 GeoTIFF 成本栅格
↓
窗口内可视化
↓
键盘或鼠标选择起终点
↓
NoData 和障碍校验
↓
Dijkstra / A* 最低成本搜索
↓
路径、成本和实际距离显示
↓
算法效率对比
↓
路径成本统计
↓
QGIS 矢量图层生成
↓
GeoPackage 和 CSV 成果导出
```
当前插件已经能够支持课程演示、算法实验、真实数据分析和结果交付。
