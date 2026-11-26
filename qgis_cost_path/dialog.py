from pathlib import Path

from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSplitter, QStyle, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)
from qgis.core import (
    QgsCoordinateTransform, QgsCsException, QgsProject, QgsRectangle,
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
MAX_CELLS = 10_000
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
        self.pick_start = QRadioButton("起点")
        self.pick_goal = QRadioButton("终点")
        self.pick_start.setStyleSheet("color: " + START_COLOR)
        self.pick_goal.setStyleSheet("color: " + GOAL_COLOR)
        self.pick_goal.setChecked(True)
        self.pick_group = QButtonGroup(self)
        self.pick_group.addButton(self.pick_start)
        self.pick_group.addButton(self.pick_goal)

        self.table = GridView()
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

        options = QHBoxLayout()
        options.addWidget(QLabel("数据"))
        options.addWidget(self.sample)
        options.addWidget(self.load_button)
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
        grid_layout.addWidget(self.table)
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
        self.algorithm.currentIndexChanged.connect(self.calculate)
        self.table.cellClicked.connect(self.pick_cell)
        self.table.cellActivated.connect(self.pick_cell)
        self.apply_xy.clicked.connect(self.apply_coordinates)
        self.xy.returnPressed.connect(self.apply_coordinates)
        self.map_pick.clicked.connect(self.start_map_pick)
        self.publish.clicked.connect(self.publish_result)
        self.use_raster.clicked.connect(self.import_active_raster)
        self.load_sample()

    def read_grid(self, path):
        raster = load_raster_file(path)
        if raster["rows"] * raster["cols"] > MAX_CELLS:
            raise RasterError("当前窗口最多显示 {:,} 格".format(MAX_CELLS))
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
            raster = read_qgis_raster(layer, MAX_CELLS)
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(self, "无法读取当前栅格", str(error))
            return
        self.set_imported_grid(raster, layer.name())

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
        self.map_pick.setEnabled(crs.isValid())
        if crs.isValid():
            self.xy.setPlaceholderText(
                "X, Y（{}）".format(crs.authid() or "栅格坐标")
            )
        else:
            self.xy.setPlaceholderText("行, 列（从 1 开始，例如 1,1）")

        self.table.setUpdatesEnabled(False)
        try:
            self.table.clear()
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
                "格子 {} 不可通行。".format(cell_label((row, col)))
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
        if self.start is None:
            status = "栅格中没有可通行的格子。"
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
        self.show_result(status)

    def show_result(self, status):
        self.start_label.setText(
            cell_label(self.start) if self.start is not None else "—"
        )
        self.goal_label.setText(
            cell_label(self.goal) if self.goal is not None else "—"
        )
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
        lines = [cell_label(self.start) + " 起点"]
        for step in stats["step_details"]:
            lines.append(
                "→ {}  +{:.2f}".format(
                    cell_label(step["to"]), step["step_cost"]
                )
            )
        self.route_text.setPlainText("\n".join(lines))

    def selected_role(self):
        return "起点" if self.pick_start.isChecked() else "终点"

    def set_endpoint(self, cell, role):
        if self.is_blocked_cell(*cell):
            raise ValueError(
                "{}落在不可通行格 {}。".format(role, cell_label(cell))
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
            if raster_crs(self.raster).isValid():
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
