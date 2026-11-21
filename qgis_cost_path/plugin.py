from pathlib import Path

from qgis.core import Qgis, QgsApplication, QgsMessageLog, QgsTask
from qgis.PyQt.QtWidgets import QAction, QStyle

from . import github_sync
from .dialog import CostPathDialog


class CostPathPlugin:
    MENU = "GIS 成本路径"

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.revision = None
        self.task = None
        self.cache = Path(QgsApplication.qgisSettingsDirPath()) / "gis-cost-path-cache"

    def initGui(self):
        window = self.iface.mainWindow()
        icon = window.style().standardIcon(QStyle.SP_ArrowRight)
        self.action = QAction(icon, "打开成本网格", window)
        self.action.setObjectName("gisCostPathOpen")
        self.action.triggered.connect(self.open_dialog)
        self.iface.addPluginToMenu(self.MENU, self.action)
        self.iface.addToolBarIcon(self.action)

    def open_dialog(self):
        if self.task is not None:
            return
        self.action.setEnabled(False)
        self.iface.messageBar().pushMessage(self.MENU, "正在检查 GitHub main 更新…", duration=3)
        self.task = QgsTask.fromFunction(
            "同步 GIS 成本路径", github_sync.fetch_revision,
            on_finished=self.sync_finished, cache=self.cache,
        )
        QgsApplication.taskManager().addTask(self.task)

    def sync_finished(self, error, sha=None):
        self.task = None
        if self.action is None:
            return
        self.action.setEnabled(True)
        if error is not None:
            self.report_fallback(error)
        cached = github_sync.last_working_revision(self.cache)
        revisions = dict.fromkeys(revision for revision in (sha, cached) if revision is not None)
        revisions[None] = None
        for revision in revisions:
            try:
                self.show_revision(revision)
            except Exception as load_error:
                self.report_fallback(load_error)
                continue
            if revision is not None:
                try:
                    github_sync.mark_working(self.cache, revision)
                except OSError as cache_error:
                    QgsMessageLog.logMessage(str(cache_error), self.MENU, Qgis.Warning)
            return

    def report_fallback(self, error):
        QgsMessageLog.logMessage(str(error), self.MENU, Qgis.Warning)
        self.iface.messageBar().pushWarning(self.MENU, "同步失败，打开上次可用的版本。")

    def show_revision(self, revision):
        if self.dialog is None or self.revision != revision:
            factory = github_sync.dialog_class(self.cache, revision) if revision else CostPathDialog
            candidate = factory(self.iface.mainWindow())
            if revision:
                candidate.setWindowTitle(f"{self.MENU} · GitHub {revision[:7]}")
            candidate.show()
            if self.dialog is not None:
                self.dialog.close()
                self.dialog.deleteLater()
            self.dialog = candidate
            self.revision = revision
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    def unload(self):
        if self.task is not None:
            self.task.cancel()
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.action is not None:
            self.iface.removePluginMenu(self.MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

