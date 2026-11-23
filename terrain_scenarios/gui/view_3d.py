"""3D views of the Modified DEM (spec §8.5): every open 3D view whose terrain is a DEM terrain on the
session's Modified DEM is shown at a detail that resolves single cells, and is rebuilt after each change.

QGIS seeds a new view's DEM terrain at 16 samples per tile edge, which steps over a dike a few cells
wide, and never rebuilds a view's terrain when the raster under it is rewritten. Views on any other
terrain are never touched. Without QGIS's 3D module (a QGIS built without 3D) all of this does nothing."""
from __future__ import annotations

import importlib
import traceback

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject, QTimer

from .controller import LOG_TAG

# Samples per tile edge are capped here: a tile holds resolution² vertices, and a view keeps several
# tiles loaded, so 512 (262 144 vertices a tile) is about the most a laptop GPU draws smoothly. It
# matches QGIS's own default map texture per tile (512 px), so heights are then as fine as the
# draped map; QGIS's 3D configuration allows up to 4096. Deeper tiles of a bigger DEM still reach
# single cells as the camera comes closer.
MAX_RESOLUTION = 512
REBUILD_DELAY = 300   # ms after the last write before the views rebuild: a drag or nudges rebuild once
_SEEN = "terrain_scenarios_detail"   # a view's dynamic property: its detail was set once, the rest is the user's


def _module_3d():
    """QGIS's 3D Python module, or None in a QGIS built without it. Loading it first also keeps
    `mapCanvases3D()` from converting its results with a null type, which crashes QGIS."""
    try:
        return importlib.import_module("qgis._3d")
    except ImportError:
        return None


def wanted_resolution(layer) -> int:
    """Samples per tile edge that let the root tile resolve every cell of `layer`, within the cap."""
    return max(1, min(max(layer.width(), layer.height()), MAX_RESOLUTION))


class TerrainViews(QObject):
    """Watches the open 3D views. `check_soon` gives new views on the Modified DEM their detail;
    `schedule_rebuild` (on each terrain write) rebuilds every such view once a burst of writes is over.
    `working_layer_id` returns the session's Modified DEM layer id, or None without a session."""

    def __init__(self, iface, project, working_layer_id, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.project = project
        self.working_layer_id = working_layer_id
        self._check = QTimer(self)
        self._check.setSingleShot(True)
        self._check.setInterval(0)    # after QGIS has finished setting up the view that was just added
        self._check.timeout.connect(self._check_views)
        self._rebuild = QTimer(self)
        self._rebuild.setSingleShot(True)
        self._rebuild.setInterval(REBUILD_DELAY)
        self._rebuild.timeout.connect(self._rebuild_views)
        # New views: a docked one is added to the main window; an undocked one is a window without a
        # parent, but QGIS registers every new view with the project's views manager (QgisInterface
        # has no signal for it in 4.2.3).
        self._window = iface.mainWindow()
        self._window.installEventFilter(self)
        project.viewsManager().views3DListChanged.connect(self.check_soon)

    def shutdown(self) -> None:
        self._check.stop()
        self._rebuild.stop()
        try:
            self.project.viewsManager().views3DListChanged.disconnect(self.check_soon)
        except TypeError:
            pass
        if self._window is not None and not sip.isdeleted(self._window):
            self._window.removeEventFilter(self)
        self._window = None

    def eventFilter(self, watched, event):  # noqa: N802 — Qt override
        """Guarded: a Qt virtual override. Only schedules a check; never consumes the event."""
        try:
            if event.type() == QEvent.Type.ChildAdded:
                self._check.start()
        except Exception:  # noqa: BLE001 — an exception here aborts QGIS
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        return False

    def check_soon(self) -> None:
        """Look at the open views once control is back in the event loop. Guarded: a slot."""
        try:
            self._check.start()
        except Exception:  # noqa: BLE001
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def schedule_rebuild(self) -> None:
        """The Modified DEM file was written: rebuild the views on it after the burst. Guarded: a slot."""
        try:
            self._rebuild.start()     # restarted per write, so a burst rebuilds once
        except Exception:  # noqa: BLE001
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _check_views(self) -> None:
        try:
            for view, settings, terrain in self._our_views():
                resolution = self._resolution(view, terrain)
                if resolution != terrain.resolution():
                    detailed = terrain.clone()
                    detailed.setResolution(resolution)
                    settings.setTerrainSettings(detailed)   # a different setting: the view rebuilds itself
        except Exception:  # noqa: BLE001 — a timer slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _rebuild_views(self) -> None:
        try:
            for view, settings, terrain in self._our_views():
                final = terrain.clone()
                final.setResolution(self._resolution(view, terrain))
                # Settings equal to the current ones are ignored, so the view would keep the old
                # terrain. A skirt 1 m taller and then the real settings are two changes; QGIS builds
                # the terrain once, deferred, from the last of them. The terrain stays a DEM terrain
                # on the Modified DEM throughout, unlike a detour through a flat one.
                nudged = final.clone()
                nudged.setSkirtHeight(final.skirtHeight() + 1.0)
                settings.setTerrainSettings(nudged)
                settings.setTerrainSettings(final)
        except Exception:  # noqa: BLE001 — a timer slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _resolution(self, view, terrain) -> int:
        """The detail a view gets: once, the larger of its own and the one that resolves every cell —
        never lower than the user's. After that its resolution is the user's to change."""
        if view.property(_SEEN):
            return terrain.resolution()
        view.setProperty(_SEEN, True)
        return max(terrain.resolution(), wanted_resolution(terrain.layer()))

    def _our_views(self) -> list:
        """(view, its Qgs3DMapSettings, its DEM terrain settings) for each open view whose terrain is a
        DEM terrain on the Modified DEM. Views closed meanwhile, and each view that fails, are skipped."""
        module = _module_3d()
        layer_id = self.working_layer_id()
        if module is None or layer_id is None:
            return []
        found = []
        for view in self.iface.mapCanvases3D() or []:
            try:
                if view is None or sip.isdeleted(view):
                    continue
                settings = view.mapSettings()
                terrain = settings.terrainSettings() if settings is not None else None
                if not isinstance(terrain, module.QgsDemTerrainSettings):
                    continue
                layer = terrain.layer()
                if layer is not None and layer.id() == layer_id:
                    found.append((view, settings, terrain))
            except Exception:  # noqa: BLE001 — one odd view must not keep the others from updating
                QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
        return found
