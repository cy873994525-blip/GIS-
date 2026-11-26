from pathlib import Path

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSplitter, QStyle, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsCoordinateTransform, QgsCsException, QgsProject, QgsRasterLayer,
    QgsRectangle,
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.utils import iface

from .core.contract import shortest_path
from .core.coord_transform import (
    map_to_cell, parse_coord_text, require_passable, resolve_point,
)
from .core.cost_path import NoRouteError
from .core.cost_raster import RasterError, is_nodata, load_raster_file
from .core.cost_rules import is_blocked, resolve_config
from .qgis_layers import make_result_layers, raster_crs, read_qgis_raster


SAMPLES = Path(__file__).resolve().parent / "sample_data"
MAX_TABLE_CELLS = 10_000
MAX_ANALYSIS_CELLS = 1_000_000
START_COLOR = "#006c60"
GOAL_COLOR = "#994523"


def cell_label(cell):
    return "（{}, {}）".format(cell[0] + 1, cell[1] + 1)


class GridView(QTableWidget):
    def __init__(self):
        super().__init__()
        self.path_cells = ()
        self.setAccessibleName("成本网格")
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.horizontalHeader().setDefaultSectionSize(75)
        self.verticalHeader().setDefaultSectionSize(55)
        self.setMinimumSize(240, 230)

    def paintEvent(self, event):
        super().paintEvent(event)
        if len(self.path_cells) < 2:
            return
        points = [
            QPointF(
                self.columnViewportPosition(col) + self.columnWidth(col) / 2,
                self.rowViewportPosition(row) + self.rowHeight(row) * 0.75,
            )
            for row, col in self.path_cells
        ]
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            for color, width in (("#ffffff", 6), (START_COLOR, 3)):
                painter.setPen(
                    QPen(
                        QColor(color), width, Qt.SolidLine,
                        Qt.RoundCap, Qt.RoundJoin,
                    )
                )
                painter.drawPolyline(QPolygonF(points))
        finally:
            painter.end()


class RasterGridView(QWidget):
    cellClicked = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.raster = None
        self.image = None
        self.path_cells = ()
        self.start = None
        self.goal = None
        self.setMinimumSize(420, 420)
        self.setMouseTracking(True)

    def set_raster(self, raster):
        self.raster = raster
        self.path_cells = ()
        self.start = None
        self.goal = None

        rows = raster["rows"]
        cols = raster["cols"]
        valid_values = [
            float(value)
            for row, values in enumerate(raster["values"])
            for col, value in enumerate(values)
            if not is_nodata(raster, row, col) and float(value) > 0
        ]
        minimum = min(valid_values)
        maximum = max(valid_values)
        span = maximum - minimum

        image = QImage(cols, rows, QImage.Format_RGB32)
        for row, values in enumerate(raster["values"]):
            for col, value in enumerate(values):
                if is_nodata(raster, row, col) or float(value) <= 0:
                    color = QColor("#39413f")
                else:
                    ratio = 0.0 if span == 0 else (float(value) - minimum) / span
                    hue = 0.35 * (1.0 - ratio)
                    color = QColor.fromHsvF(hue, 0.72, 0.92)
                image.setPixelColor(col, row, color)

        self.image = image
        self.update()

    def set_path(self, path, start, goal):
        self.path_cells = tuple(path)
        self.start = start
        self.goal = goal
        self.update()

    def image_rect(self):
        if self.raster is None:
            return QRectF()
        available_width = max(1, self.width() - 20)
        available_height = max(1, self.height() - 20)
        ratio = min(
            available_width / self.raster["cols"],
            available_height / self.raster["rows"],
        )
        width = self.raster["cols"] * ratio
        height = self.raster["rows"] * ratio
        return QRectF(
            (self.width() - width) / 2,
            (self.height() - height) / 2,
            width,
            height,
        )

    def cell_center(self, cell, rect):
        row, col = cell
        return QPointF(
            rect.left() + (col + 0.5) * rect.width() / self.raster["cols"],
            rect.top() + (row + 0.5) * rect.height() / self.raster["rows"],
        )

    def event_cell(self, position):
        rect = self.image_rect()
        if self.raster is None or not rect.contains(position):
            return None
        col = min(
            int((position.x() - rect.left()) * self.raster["cols"] / rect.width()),
            self.raster["cols"] - 1,
        )
        row = min(
            int((position.y() - rect.top()) * self.raster["rows"] / rect.height()),
            self.raster["rows"] - 1,
        )
        return row, col

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            cell = self.event_cell(event.localPos())
            if cell is not None:
                self.cellClicked.emit(*cell)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        cell = self.event_cell(event.localPos())
        if cell is None:
            self.setToolTip("")
        else:
            row, col = cell
            if is_nodata(self.raster, row, col):
                value = "NoData"
            else:
                value = "{:g}".format(self.raster["values"][row][col])
            self.setToolTip("X={}, Y={}，成本 {}".format(row, col, value))
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.image is None:
            return

        rect = self.image_rect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
        painter.drawImage(rect, self.image)
        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.drawRect(rect)

        if len(self.path_cells) > 1:
            points = [
                self.cell_center(cell, rect)
                for cell in self.path_cells
            ]
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(
                QPen(
                    QColor("#ffffff"), 6, Qt.SolidLine,
                    Qt.RoundCap, Qt.RoundJoin,
                )
            )
            painter.drawPolyline(QPolygonF(points))
            painter.setPen(
                QPen(
                    QColor("#087f8c"), 3, Qt.SolidLine,
                    Qt.RoundCap, Qt.RoundJoin,
                )
            )
            painter.drawPolyline(QPolygonF(points))

        for cell, color in (
            (self.start, START_COLOR),
            (self.goal, GOAL_COLOR),
        ):
            if cell is None:
                continue
            point = self.cell_center(cell, rect)
            painter.setPen(QPen(QColor("#ffffff"), 2))
            painter.setBrush(QBrush(QColor(color)))
            painter.drawEllipse(point, 6, 6)

        painter.end()


class CostPathDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("GIS 成本路径")
        self.resize(900, 530)

        self.raster = None
        self.config = None
        self.start = None
        self.goal = None
        self.result = None
        self.marked_cells = set()
        self.imported_grid = None
        self.output_ids = []
        self.source_raster_id = None
        self.large_grid = False

        self.canvas = iface.mapCanvas()
        self.map_tool = QgsMapToolEmitPoint(self.canvas)
        self.previous_tool = None
        self.map_tool.canvasClicked.connect(self.map_clicked)

        self.sample = QComboBox()
        self.sample.addItem("内置 4 × 4", "cost_grid_4x4.json")
        self.sample.addItem("内置 5 × 5", "cost_grid_5x5.json")
        self.sample.addItem("内置 10 × 10", "cost_grid_10x10.json")
        self.sample.addItem(
            "地图联调 4 × 4（48 米）", "cost_grid_4x4_map.json"
        )

        self.algorithm = QComboBox()
        self.algorithm.addItem("Dijkstra", "dijkstra")
        self.algorithm.addItem("A*", "astar")

        self.load_button = QPushButton("导入 JSON…")
        self.load_button.setIcon(
            self.style().standardIcon(QStyle.SP_DialogOpenButton)
        )
        self.load_tiff_button = QPushButton("导入 GeoTIFF…")
        self.load_tiff_button.setIcon(
            self.style().standardIcon(QStyle.SP_DialogOpenButton)
        )
        self.pick_start = QRadioButton("起点")
        self.pick_goal = QRadioButton("终点")
        self.pick_start.setStyleSheet("color: " + START_COLOR)
        self.pick_goal.setStyleSheet("color: " + GOAL_COLOR)
        self.pick_goal.setChecked(True)
        self.pick_group = QButtonGroup(self)
        self.pick_group.addButton(self.pick_start)
        self.pick_group.addButton(self.pick_goal)

        self.table = GridView()
        self.raster_view = RasterGridView()
        self.raster_view.hide()
        self.start_label = QLabel()
        self.goal_label = QLabel()
        self.cost_label = QLabel()
        self.length_label = QLabel()
        self.expanded_label = QLabel()
        self.time_label = QLabel()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.route_text = QPlainTextEdit()
        self.route_text.setReadOnly(True)
        self.route_text.setAccessibleName("路径格点与逐段成本")
        self.route_text.setMinimumHeight(95)
        self.source = QLabel()
        self.source.setTextFormat(Qt.PlainText)
        self.source.setWordWrap(True)
        self.grid_hint = QLabel()
        self.grid_hint.setWordWrap(True)
        self.grid_hint.setStyleSheet(
            "padding: 12px; color: #43504d; background: #eef3f1;"
        )
        self.grid_hint.hide()

        options = QHBoxLayout()
        options.addWidget(QLabel("数据"))
        options.addWidget(self.sample)
        options.addWidget(self.load_button)
        options.addWidget(self.load_tiff_button)
        options.addStretch()
        options.addWidget(QLabel("算法"))
        options.addWidget(self.algorithm)

        points = QHBoxLayout()
        points.addWidget(QLabel("选择格子作为"))
        points.addWidget(self.pick_start)
        points.addWidget(self.pick_goal)
        points.addStretch()

        grid_panel = QWidget()
        grid_layout = QVBoxLayout(grid_panel)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addLayout(points)
        grid_layout.addWidget(self.grid_hint)
        grid_layout.addWidget(self.table)
        grid_layout.addWidget(self.raster_view, 1)
        grid_layout.addWidget(self.source)

        metrics = QFormLayout()
        for label, value in (
            ("起点", self.start_label),
            ("终点", self.goal_label),
            ("总成本", self.cost_label),
            ("路径长度", self.length_label),
            ("扩展节点", self.expanded_label),
            ("搜索耗时", self.time_label),
        ):
            metrics.addRow(label, value)

        result_panel = QWidget()
        results = QVBoxLayout(result_panel)
        results.addWidget(QLabel("路径结果"))
        results.addLayout(metrics)
        results.addWidget(self.status)
        results.addWidget(QLabel("路径格点（行、列）与逐段成本"))
        results.addWidget(self.route_text, 1)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(grid_panel)
        split.addWidget(result_panel)
        split.setSizes([480, 380])

        self.xy = QLineEdit()
        self.xy.setPlaceholderText("成本栅格坐标系中的 X, Y")
        self.apply_xy = QPushButton("应用坐标")
        self.map_pick = QPushButton("地图点选")
        self.publish = QPushButton("添加结果到地图")
        self.use_raster = QPushButton("使用当前栅格")

        coordinate_row = QHBoxLayout()
        coordinate_row.addWidget(self.xy, 1)
        coordinate_row.addWidget(self.apply_xy)
        coordinate_row.addWidget(self.map_pick)
        coordinate_row.addWidget(self.publish)
        coordinate_row.addWidget(self.use_raster)

        layout = QVBoxLayout(self)
        layout.addLayout(options)
        layout.addLayout(coordinate_row)
        layout.addWidget(split, 1)

        self.sample.currentIndexChanged.connect(self.load_sample)
        self.load_button.clicked.connect(self.import_json)
        self.load_tiff_button.clicked.connect(self.import_geotiff)
        self.algorithm.currentIndexChanged.connect(self.calculate)
        self.table.cellClicked.connect(self.pick_cell)
        self.table.cellActivated.connect(self.pick_cell)
        self.raster_view.cellClicked.connect(self.pick_cell)
        self.apply_xy.clicked.connect(self.apply_coordinates)
        self.xy.returnPressed.connect(self.apply_coordinates)
        self.map_pick.clicked.connect(self.start_map_pick)
        self.publish.clicked.connect(self.publish_result)
        self.use_raster.clicked.connect(self.import_active_raster)
        self.load_sample()

    def read_grid(self, path):
        raster = load_raster_file(path)
        if raster["rows"] * raster["cols"] > MAX_ANALYSIS_CELLS:
            raise RasterError(
                "当前插件最多分析 {:,} 格".format(MAX_ANALYSIS_CELLS)
            )
        return raster

    def load_sample(self):
        filename = self.sample.currentData()
        if filename is None:
            if self.imported_grid is not None:
                self.show_grid(*self.imported_grid)
            return
        path = SAMPLES / filename
        try:
            raster = self.read_grid(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法读取样例", str(error))
            return
        self.show_grid(raster, path.name)

    def import_json(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "打开成本栅格", "", "JSON (*.json)"
        )
        if not filename:
            return
        path = Path(filename)
        try:
            raster = self.read_grid(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法导入成本栅格", str(error))
            return
        self.set_imported_grid(raster, path.name)

    def import_active_raster(self):
        layer = iface.activeLayer()
        try:
            raster = read_qgis_raster(layer, MAX_ANALYSIS_CELLS)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "无法读取当前栅格", str(error))
            return
        self.set_imported_grid(raster, layer.name())

    def import_geotiff(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择成本 GeoTIFF",
            "",
            "GeoTIFF (*.tif *.tiff)",
        )
        if not filename:
            return

        layer = QgsRasterLayer(filename, Path(filename).stem, "gdal")
        if not layer.isValid():
            QMessageBox.warning(
                self, "无法导入 GeoTIFF", "QGIS 无法打开所选栅格文件。"
            )
            return

        try:
            raster = read_qgis_raster(layer, MAX_ANALYSIS_CELLS)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "无法导入 GeoTIFF", str(error))
            return

        project = QgsProject.instance()
        project.addMapLayer(layer)
        self.source_raster_id = layer.id()
        self.set_imported_grid(raster, layer.name())

        try:
            extent = self.coordinate_transform(
                layer.crs(), self.canvas.mapSettings().destinationCrs()
            ).transformBoundingBox(layer.extent())
            self.canvas.setExtent(extent)
            self.canvas.refresh()
        except QgsCsException:
            pass

    def set_imported_grid(self, raster, name):
        self.imported_grid = (raster, name)
        imported = self.sample.findText("导入的栅格")
        if imported < 0:
            self.sample.addItem("导入的栅格")
            imported = self.sample.count() - 1
        if self.sample.currentIndex() == imported:
            self.load_sample()
        else:
            self.sample.setCurrentIndex(imported)

    def show_grid(self, raster, source_name):
        self.stop_map_pick()
        self.raster = raster
        self.config = resolve_config(raster)
        self.start = None
        self.goal = None
        self.xy.clear()
        self.marked_cells.clear()
        self.table.path_cells = ()

        crs = raster_crs(raster)
        cell_count = raster["rows"] * raster["cols"]
        self.large_grid = cell_count > MAX_TABLE_CELLS
        self.map_pick.setEnabled(crs.isValid())
        if crs.isValid():
            self.xy.setPlaceholderText(
                "X, Y（{}）".format(crs.authid() or "栅格坐标")
            )
        else:
            self.xy.setPlaceholderText("行, 列（从 1 开始，例如 1,1）")

        self.table.setEnabled(not self.large_grid)
        self.table.setVisible(not self.large_grid)
        self.raster_view.setVisible(self.large_grid)
        self.grid_hint.setVisible(self.large_grid)
        if self.large_grid:
            self.grid_hint.setText(
                "已加载 {:,} 个像元。左上角为 X=0,Y=0，"
                "向下 X 增加，向右 Y 增加；请选择起点或终点后点击栅格图。".format(
                    cell_count
                )
            )
            self.xy.setPlaceholderText(
                "X, Y（左上角 0,0；X 向下，Y 向右）"
            )
            self.raster_view.set_raster(raster)

        self.table.setUpdatesEnabled(False)
        try:
            self.table.clear()
            if self.large_grid:
                self.table.setRowCount(0)
                self.table.setColumnCount(0)
            else:
                self.table.setRowCount(raster["rows"])
                self.table.setColumnCount(raster["cols"])
                for row, values in enumerate(raster["values"]):
                    for col, value in enumerate(values):
                        blocked = self.is_blocked_cell(row, col)
                        item = QTableWidgetItem(
                            "×" if blocked else "{:.6g}".format(value)
                        )
                        item.setTextAlignment(Qt.AlignCenter)
                        item.setToolTip(
                            "{} {}".format(
                                cell_label((row, col)),
                                "不可通行" if blocked else value,
                            )
                        )
                        self.table.setItem(row, col, item)
                        self.paint_cell((row, col))
                        if not blocked:
                            if self.start is None:
                                self.start = (row, col)
                            self.goal = (row, col)
        finally:
            self.table.setUpdatesEnabled(True)

        self.source.setText(
            "{}  ·  {} × {}  ·  {}  ·  × 不可通行".format(
                source_name,
                raster["rows"],
                raster["cols"],
                raster.get("crs", "unknown"),
            )
        )
        self.calculate()

    def is_blocked_cell(self, row, col):
        return (
            is_nodata(self.raster, row, col)
            or is_blocked(self.raster, (row, col), self.config)
        )

    def paint_cell(self, cell):
        row, col = cell
        item = self.table.item(row, col)
        if item is None:
            return
        if self.is_blocked_cell(row, col):
            background, foreground = "#4c5b57", "#ffffff"
        elif cell == self.start:
            background, foreground = START_COLOR, "#ffffff"
        elif cell == self.goal:
            background, foreground = GOAL_COLOR, "#ffffff"
        elif cell in self.marked_cells:
            background, foreground = "#c6eadf", "#183531"
        else:
            background, foreground = "#eff4f2", "#243631"
        item.setBackground(QBrush(QColor(background)))
        item.setForeground(QBrush(QColor(foreground)))

    def pick_cell(self, row, col):
        if self.raster is None:
            return
        if self.is_blocked_cell(row, col):
            self.status.setText(
                "格子 {} 不可通行。".format(
                    self.coordinate_label((row, col))
                )
            )
            self.status.show()
            return
        if self.pick_start.isChecked():
            self.start = (row, col)
        else:
            self.goal = (row, col)
        self.calculate()

    def calculate(self):
        if self.raster is None:
            return
        status = ""
        self.result = None
        if self.start is None or self.goal is None:
            status = "请设置起点和终点。"
        else:
            try:
                self.result = shortest_path(
                    self.raster,
                    self.start,
                    self.goal,
                    config=self.config,
                    algorithm=self.algorithm.currentData(),
                )
            except (NoRouteError, ValueError) as error:
                status = str(error)

        old_marks = self.marked_cells
        path = tuple(self.result.path) if self.result is not None else ()
        self.marked_cells = set(path)
        self.marked_cells.update(
            cell for cell in (self.start, self.goal) if cell is not None
        )
        for cell in old_marks | self.marked_cells:
            self.paint_cell(cell)
        self.table.path_cells = path
        self.table.viewport().update()
        self.raster_view.set_path(path, self.start, self.goal)
        self.show_result(status)

    def coordinate_label(self, cell):
        if cell is None:
            return "—"
        if self.large_grid:
            return "X={}, Y={}".format(cell[0], cell[1])
        return cell_label(cell)

    def show_result(self, status):
        self.start_label.setText(self.coordinate_label(self.start))
        self.goal_label.setText(self.coordinate_label(self.goal))
        self.status.setText(status)
        self.status.setVisible(bool(status))
        result = self.result
        self.publish.setEnabled(
            result is not None and raster_crs(self.raster).isValid()
        )
        if result is None:
            for label in (
                self.cost_label, self.length_label,
                self.expanded_label, self.time_label,
            ):
                label.setText("—")
            self.route_text.clear()
            return

        stats = result.stats
        self.cost_label.setText("{:.2f}".format(stats["total_cost"]))
        self.length_label.setText("{:.2f} 格".format(stats["length"]))
        self.expanded_label.setText(str(stats["expanded"]))
        self.time_label.setText("{:.3f} ms".format(stats["elapsed_ms"]))
        lines = [self.coordinate_label(self.start) + " 起点"]
        for step in stats["step_details"]:
            lines.append(
                "→ {}  +{:.2f}".format(
                    self.coordinate_label(step["to"]), step["step_cost"]
                )
            )
        self.route_text.setPlainText("\n".join(lines))

    def selected_role(self):
        return "起点" if self.pick_start.isChecked() else "终点"

    def set_endpoint(self, cell, role):
        if self.is_blocked_cell(*cell):
            raise ValueError(
                "{}落在不可通行格 {}。".format(
                    role, self.coordinate_label(cell)
                )
            )
        if role == "起点":
            self.start = cell
        else:
            self.goal = cell
        self.calculate()

    def apply_coordinates(self):
        if self.raster is None:
            return
        role = self.selected_role()
        try:
            if self.large_grid:
                x_number, y_number = parse_coord_text(self.xy.text())
                if not x_number.is_integer() or not y_number.is_integer():
                    raise ValueError("X 和 Y 必须是整数，例如 250,283。")
                row = int(x_number)
                col = int(y_number)
                if not (
                    0 <= row < self.raster["rows"]
                    and 0 <= col < self.raster["cols"]
                ):
                    raise ValueError(
                        "坐标超出范围：X 应为 0 到 {}，Y 应为 0 到 {}。".format(
                            self.raster["rows"] - 1,
                            self.raster["cols"] - 1,
                        )
                    )
                cell = (row, col)
            elif raster_crs(self.raster).isValid():
                point = require_passable(
                    resolve_point(self.raster, self.xy.text(), role=role)
                )
                cell = (point["row"], point["col"])
            else:
                row_number, col_number = parse_coord_text(self.xy.text())
                if not row_number.is_integer() or not col_number.is_integer():
                    raise ValueError("行号和列号必须是整数，例如 1,1。")
                row = int(row_number) - 1
                col = int(col_number) - 1
                if not (
                    0 <= row < self.raster["rows"]
                    and 0 <= col < self.raster["cols"]
                ):
                    raise ValueError(
                        "行列号超出范围：请输入 1 到 {} 行、1 到 {} 列。".format(
                            self.raster["rows"], self.raster["cols"]
                        )
                    )
                cell = (row, col)
            self.set_endpoint(cell, role)
        except ValueError as error:
            QMessageBox.warning(self, "坐标无效", str(error))

    def start_map_pick(self):
        if self.raster is None:
            return
        if not raster_crs(self.raster).isValid():
            QMessageBox.warning(
                self, "无法地图点选", "当前成本栅格没有有效 CRS。"
            )
            return
        if self.canvas.mapTool() is not self.map_tool:
            self.previous_tool = self.canvas.mapTool()
            self.canvas.setMapTool(self.map_tool)

    def stop_map_pick(self):
        previous = self.previous_tool
        self.previous_tool = None
        if self.canvas.mapTool() is self.map_tool:
            if previous is None:
                self.canvas.unsetMapTool(self.map_tool)
            else:
                self.canvas.setMapTool(previous)

    def coordinate_transform(self, source_crs, destination_crs):
        return QgsCoordinateTransform(
            source_crs, destination_crs, QgsProject.instance()
        )

    def map_clicked(self, point, button):
        self.stop_map_pick()
        if button != Qt.LeftButton or self.raster is None:
            return
        try:
            source_crs = self.canvas.mapSettings().destinationCrs()
            target_crs = raster_crs(self.raster)
            transformed = self.coordinate_transform(
                source_crs, target_crs
            ).transform(point)
            cell = map_to_cell(
                self.raster, transformed.x(), transformed.y()
            )
            self.set_endpoint(cell, self.selected_role())
        except (QgsCsException, ValueError) as error:
            QMessageBox.warning(self, "地图点选失败", str(error))

    def publish_result(self):
        if self.result is None:
            return
        project = QgsProject.instance()
        try:
            layers = make_result_layers(self.raster, self.result)
            source_extent = QgsRectangle(*self.raster["bounds"])
            destination_extent = self.coordinate_transform(
                raster_crs(self.raster),
                self.canvas.mapSettings().destinationCrs(),
            ).transformBoundingBox(source_extent)
            destination_extent.scale(1.15)
        except (QgsCsException, ValueError) as error:
            QMessageBox.warning(self, "无法添加图层", str(error))
            return

        project.addMapLayers(layers)
        project.removeMapLayers(self.output_ids)
        self.output_ids = [layer.id() for layer in layers]
        self.canvas.setExtent(destination_extent)
        self.canvas.refresh()

    def closeEvent(self, event):
        self.stop_map_pick()
        super().closeEvent(event)
