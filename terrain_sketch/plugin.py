"""Plugin entry point: toolbar button, Raster menu entry and the Terrain Sketch panel."""
from __future__ import annotations

import os

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon

from .gui.controller import SketchController
from .gui.main_dock import MainDock
from .gui.profile_dock import ProfileDock
from .qgis_io.compat import gdal_problems

MENU = "&Terrain Sketch"


class TerrainSketchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.profiles = None
        self.controller = None

    def initGui(self):  # noqa: N802 — QGIS plugin API
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icons", "terrain_sketch.svg"))
        self.action = QAction(icon, "Terrain Sketch", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Sketch dikes, ditches, ponds and other features onto a DEM")
        self.action.toggled.connect(self._toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(MENU, self.action)

    def unload(self):
        if self.profiles is not None:
            self.profiles.shutdown()
            self.iface.removeDockWidget(self.profiles)
            self.profiles.deleteLater()
            self.profiles = None
        if self.dock is not None:
            self.dock.shutdown()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.controller is not None:
            self.controller.shutdown()
            self.controller = None
        if self.action is not None:
            self.iface.removePluginRasterMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def _toggle(self, checked: bool) -> None:
        if checked and self.dock is None and not self._create_dock():
            self.action.setChecked(False)
            return
        if self.dock is not None:
            if not checked:
                self.dock.stop_tools()
            self.dock.setUserVisible(checked)
        if self.profiles is not None:
            self.profiles.setUserVisible(checked)

    def _create_dock(self) -> bool:
        problems = gdal_problems()
        if problems:
            self.iface.messageBar().pushCritical("Terrain Sketch", " ".join(problems))
            return False
        self.controller = SketchController(QgsProject.instance())
        self.profiles = ProfileDock(self.controller, self.iface.mainWindow())
        self.dock = MainDock(self.iface, self.controller, self.profiles, self.iface.mainWindow())
        self.dock.closedStateChanged.connect(lambda closed: self.action.setChecked(not closed))
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.profiles)
        return True
