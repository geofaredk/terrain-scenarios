"""Plugin entry point: toolbar button, Raster menu entry and the Terrain Scenarios panel."""
from __future__ import annotations

import os

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon

from .gui import settings
from .gui.controller import SketchController
from .gui.main_dock import MainDock
from .gui.profile_dock import ProfileDock
from .qgis_io.compat import gdal_problems

MENU = "&Terrain Scenarios"


class TerrainScenariosPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.profiles = None
        self.controller = None

    def initGui(self):  # noqa: N802 — QGIS plugin API
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icons", "terrain_scenarios.svg"))
        self.action = QAction(icon, "Terrain Scenarios", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Sketch dikes, ditches, ponds and other features onto a DEM")
        self.action.toggled.connect(self._toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(MENU, self.action)

    def unload(self):
        self._remember_docks()
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
                self.dock.profiles_button.setChecked(False)   # hides the Profiles panel; it opens only from there
            self.dock.setUserVisible(checked)

    def _create_dock(self) -> bool:
        problems = gdal_problems()
        if problems:
            self.iface.messageBar().pushCritical("Terrain Scenarios", " ".join(problems))
            return False
        self.controller = SketchController(QgsProject.instance())
        self.profiles = ProfileDock(self.controller, self.iface.mainWindow())
        self.dock = MainDock(self.iface, self.controller, self.profiles, self.iface.mainWindow())
        self.dock.closedStateChanged.connect(lambda closed: self.action.setChecked(not closed))
        window = self.iface.mainWindow()
        # Both panels go back where the user last had them (spec §7.1); QGIS does not do this for a
        # plugin's panels, which are created long after it restored its own window layout.
        for name, dock, default in (("main_dock", self.dock, Qt.DockWidgetArea.RightDockWidgetArea),
                                    ("profile_dock", self.profiles, Qt.DockWidgetArea.BottomDockWidgetArea)):
            self.iface.addDockWidget(settings.dock_area(name, default), dock)
            settings.restore_dock(name, dock, window)
            dock.dockLocationChanged.connect(lambda _area, n=name, d=dock: settings.save_dock(n, d, window))
            dock.topLevelChanged.connect(lambda _floating, n=name, d=dock: settings.save_dock(n, d, window))
        # hidden until the Profiles button in the panel shows it; hide(), not setUserVisible(False), which does
        # nothing to a panel the window has not shown yet
        self.profiles.hide()
        return True

    def _remember_docks(self) -> None:
        window = self.iface.mainWindow()
        for name, dock in (("main_dock", self.dock), ("profile_dock", self.profiles)):
            if dock is not None:
                settings.save_dock(name, dock, window)
