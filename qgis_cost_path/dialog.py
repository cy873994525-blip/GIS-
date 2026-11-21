from pathlib import Path

from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFileDialog,
    QFormLayout, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QRadioButton, QSplitter, QStyle, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .core.cost_path import CostGrid, NoRouteError, find_path
from .core.cost_raster import RasterError, is_nodata, load_raster_file


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
            QPointF(self.columnViewportPosition(col) + self.columnWidth(col) / 2,
                    self.rowViewportPosition(row) + self.rowHeight(row) * 0.75)
            for row, col in self.path_cells
        ]
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            for color, width in (("#ffffff", 6), (START_COLOR, 3)):
                painter.setPen(QPen(QColor(color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                painter.drawPolyline(QPolygonF(points))
        finally:
            painter.end()


class CostPathDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("GIS 成本路径")
        self.resize(830, 475)
        self.raster = None
        self.grid = None
        self.start = self.goal = None
        self.result = None
        self.marked_cells = set()
        self.imported_grid = None

        self.sample = QComboBox()
        self.sample.addItem("内置 4 × 4", "cost_grid_4x4.json")
        self.sample.addItem("内置 5 × 5", "cost_grid_5x5.json")
        self.algorithm = QComboBox()
        self.algorithm.addItem("Dijkstra", "dijkstra")
        self.algorithm.addItem("A*", "astar")
        self.load_button = QPushButton("导入 JSON…")
        self.load_button.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
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
            ("起点", self.start_label), ("终点", self.goal_label),
            ("总成本", self.cost_label), ("路径长度", self.length_label),
            ("扩展节点", self.expanded_label), ("搜索耗时", self.time_label),
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
        split.setSizes([455, 350])
        layout = QVBoxLayout(self)
        layout.addLayout(options)
        layout.addWidget(split, 1)

        self.sample.currentIndexChanged.connect(self.load_sample)
        self.load_button.clicked.connect(self.import_json)
        self.algorithm.currentIndexChanged.connect(self.calculate)
        self.table.cellClicked.connect(self.pick_cell)
        self.table.cellActivated.connect(self.pick_cell)
        self.load_sample()

    def read_grid(self, path):
        raster = load_raster_file(path)
        if raster["rows"] * raster["cols"] > MAX_CELLS:
            raise RasterError("当前窗口最多显示 {:,} 格".format(MAX_CELLS))
        return raster, CostGrid.from_raster(raster)

    def load_sample(self):
        filename = self.sample.currentData()
        if filename is None:
            if self.imported_grid is not None:
                self.show_grid(*self.imported_grid)
            return
        path = SAMPLES / filename
        try:
            raster, grid = self.read_grid(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法读取样例", str(error))
            return
        self.show_grid(raster, grid, path.name)

    def import_json(self):
        filename, _ = QFileDialog.getOpenFileName(self, "打开成本栅格", "", "JSON (*.json)")
        if not filename:
            return
        path = Path(filename)
        try:
            raster, grid = self.read_grid(path)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "无法导入成本栅格", str(error))
            return
        self.imported_grid = raster, grid, path.name
        imported = self.sample.findText("导入的栅格")
        if imported < 0:
            self.sample.addItem("导入的栅格")
            imported = self.sample.count() - 1
        if self.sample.currentIndex() == imported:
            self.load_sample()
        else:
            self.sample.setCurrentIndex(imported)

    def show_grid(self, raster, grid, source_name):
        self.raster, self.grid = raster, grid
        self.start = self.goal = None
        self.marked_cells.clear()
        self.table.path_cells = ()
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clear()
            self.table.setRowCount(raster["rows"])
            self.table.setColumnCount(raster["cols"])
            for row, values in enumerate(raster["values"]):
                for col, value in enumerate(values):
                    blocked = is_nodata(raster, row, col)
                    item = QTableWidgetItem("×" if blocked else "{:.6g}".format(value))
                    item.setTextAlignment(Qt.AlignCenter)
                    item.setToolTip("{} {}".format(cell_label((row, col)), "NoData" if blocked else value))
                    self.table.setItem(row, col, item)
                    self.paint_cell((row, col))
                    if not blocked:
                        if self.start is None:
                            self.start = (row, col)
                        self.goal = (row, col)
        finally:
            self.table.setUpdatesEnabled(True)
        self.source.setText("{}  ·  {} × {}  ·  × NoData".format(
            source_name, raster["rows"], raster["cols"]))
        self.calculate()

    def paint_cell(self, cell):
        row, col = cell
        item = self.table.item(row, col)
        if is_nodata(self.raster, row, col):
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
        if is_nodata(self.raster, row, col):
            self.status.setText("格子 {} 为 NoData，不可通行。".format(cell_label((row, col))))
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
                self.result = find_path(self.grid, self.start, self.goal,
                                        algorithm=self.algorithm.currentData())
            except (NoRouteError, ValueError) as error:
                status = str(error)
        old_marks = self.marked_cells
        path = self.result.path_cells if self.result is not None else ()
        self.marked_cells = set(path)
        self.marked_cells.update(cell for cell in (self.start, self.goal) if cell is not None)
        for cell in old_marks | self.marked_cells:
            self.paint_cell(cell)
        self.table.path_cells = path
        self.table.viewport().update()
        self.show_result(status)

    def show_result(self, status):
        self.start_label.setText(cell_label(self.start) if self.start is not None else "—")
        self.goal_label.setText(cell_label(self.goal) if self.goal is not None else "—")
        self.status.setText(status)
        self.status.setVisible(bool(status))
        result = self.result
        if result is None:
            for label in (self.cost_label, self.length_label, self.expanded_label, self.time_label):
                label.setText("—")
            self.route_text.clear()
            return
        self.cost_label.setText("{:.2f}".format(result.total_cost))
        self.length_label.setText("{:.2f} 格".format(result.length_cells))
        self.expanded_label.setText(str(result.expanded_nodes))
        self.time_label.setText("{:.3f} ms".format(result.elapsed_ms))
        lines = [cell_label(self.start) + " 起点"]
        for cell, cost in zip(result.path_cells[1:], result.step_costs):
            lines.append("→ {}  +{:.2f}".format(cell_label(cell), cost))
        self.route_text.setPlainText("\n".join(lines))

