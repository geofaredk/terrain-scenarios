"""3D views of the Modified DEM (spec §8.5, 2026-11-23): shown at full detail, and rebuilt after every
change. A real Qgs3DMapCanvas cannot be made offscreen (it segfaults without an OpenGL context), so the
views here are stand-ins around a real Qgs3DMapSettings — the object whose behaviour matters."""
import sys

import numpy as np
from qgis._3d import Qgs3DMapSettings, QgsDemTerrainSettings, QgsFlatTerrainSettings
from qgis.core import QgsProject
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QDockWidget

from qgis_helpers import UTM, fake_iface, line_through, panel, spin_event_loop, start_session
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.view_3d import MAX_RESOLUTION, REBUILD_DELAY, TerrainViews

AFTER_REBUILD = REBUILD_DELAY + 200


class View(QObject):
    """Stands in for a Qgs3DMapCanvas: a QObject whose mapSettings() is a real Qgs3DMapSettings."""

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.rebuilds = []
        settings.terrainGeneratorChanged.connect(lambda: self.rebuilds.append(True))

    def mapSettings(self):  # noqa: N802 — Qgs3DMapCanvas API
        return self.settings

    def terrain(self):
        return self.settings.terrainSettings()


def dem_view(layer, resolution=None) -> View:
    settings = Qgs3DMapSettings()
    terrain = QgsDemTerrainSettings()
    terrain.setLayer(layer)
    if resolution is not None:
        terrain.setResolution(resolution)
    settings.setTerrainSettings(terrain)
    return View(settings)


def flat_view() -> View:
    settings = Qgs3DMapSettings()
    settings.setTerrainSettings(QgsFlatTerrainSettings())
    return View(settings)


def working_layer(c):
    return QgsProject.instance().mapLayer(c.layers.working_id)


def views_for(c, iface, views):
    iface.mapCanvases3D.return_value = views
    return TerrainViews(iface, QgsProject.instance(), lambda: c.layers.working_id if c.layers else None)


def draw(c, row=20):
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, row, 34, row), UTM)


def test_the_view_the_button_opens_resolves_every_cell_of_the_modified_dem(tmp_path):
    iface, c, dock = panel(tmp_path)
    c.show_in_3d()
    view = dem_view(working_layer(c))                       # what QGIS seeds: resolution 16
    iface.createNewMapCanvas3D.side_effect = lambda *_args: iface.mapCanvases3D.return_value.append(view) or view
    iface.mapCanvases3D.return_value = []
    dock.view_3d_button.click()
    spin_event_loop(50)
    assert view.terrain().resolution() == 40               # the 40 x 40 test DEM's larger side


def test_a_big_dem_is_capped(tmp_path):
    c = start_session(tmp_path, np.full((10, MAX_RESOLUTION + 300), 10.0, np.float32))
    c.show_in_3d()
    view = dem_view(working_layer(c))
    views = views_for(c, fake_iface(), [view])
    views.check_soon()
    spin_event_loop(50)
    assert view.terrain().resolution() == MAX_RESOLUTION
    assert MAX_RESOLUTION <= 4096                            # QGIS's own 3D configuration allows up to 4096


def test_a_higher_resolution_the_user_set_is_kept(tmp_path):
    c = start_session(tmp_path)
    view = dem_view(working_layer(c), resolution=2048)
    views = views_for(c, fake_iface(), [view])
    views.check_soon()
    spin_event_loop(50)
    assert view.terrain().resolution() == 2048 and view.rebuilds == []


def test_views_on_other_terrains_are_never_touched(tmp_path):
    c = start_session(tmp_path)
    flat = flat_view()
    on_the_dem = dem_view(QgsProject.instance().mapLayer(c.dem_layer_id))
    views = views_for(c, fake_iface(), [flat, on_the_dem])
    views.check_soon()
    draw(c)
    spin_event_loop(AFTER_REBUILD)
    assert flat.rebuilds == [] and on_the_dem.rebuilds == []
    assert on_the_dem.terrain().resolution() == 16


def test_a_view_opened_through_qgis_own_menu_is_noticed_as_a_dock(tmp_path):
    c = start_session(tmp_path)
    iface = fake_iface()
    views = views_for(c, iface, [])
    view = dem_view(working_layer(c))
    iface.mapCanvases3D.return_value.append(view)
    QDockWidget("3D Map 1", iface.mainWindow())              # QGIS docks a new view in its main window
    spin_event_loop(50)
    assert view.terrain().resolution() == 40
    views.shutdown()


def test_a_view_opened_as_its_own_window_is_noticed_through_the_views_manager(tmp_path):
    """QGIS gives an undocked view a window without a parent; it registers every new view with the
    project's views manager, though."""
    c = start_session(tmp_path)
    iface = fake_iface()
    views = views_for(c, iface, [])
    view = dem_view(working_layer(c))
    iface.mapCanvases3D.return_value.append(view)
    QgsProject.instance().viewsManager().views3DListChanged.emit()
    spin_event_loop(50)
    assert view.terrain().resolution() == 40
    views.shutdown()


def test_a_resolution_the_user_lowers_afterwards_is_theirs(tmp_path):
    c = start_session(tmp_path)
    view = dem_view(working_layer(c))
    views = views_for(c, fake_iface(), [view])
    views.check_soon()
    spin_event_loop(50)
    lower = view.terrain().clone()
    lower.setResolution(24)
    view.settings.setTerrainSettings(lower)
    views.check_soon()
    c.terrainWritten.connect(views.schedule_rebuild)
    draw(c)
    spin_event_loop(AFTER_REBUILD)
    assert view.terrain().resolution() == 24


def test_after_an_edit_an_open_view_is_rebuilt_from_the_file_once(tmp_path):
    c = start_session(tmp_path)
    c.show_in_3d()
    view = dem_view(working_layer(c))
    views = views_for(c, fake_iface(), [view])
    c.terrainWritten.connect(views.schedule_rebuild)
    draw(c)
    assert view.rebuilds == []                              # coalesced: not at once
    spin_event_loop(AFTER_REBUILD)
    assert view.rebuilds                                    # setTerrainSettings with equal settings would be a no-op
    terrain = view.terrain()
    assert isinstance(terrain, QgsDemTerrainSettings)
    assert terrain.layer().id() == c.layers.working_id and terrain.resolution() == 40
    expected = QgsDemTerrainSettings()
    expected.setLayer(working_layer(c))
    expected.setResolution(40)
    assert terrain.equals(expected)                         # nothing else changed on the way


def test_a_burst_of_edits_rebuilds_once(tmp_path):
    c = start_session(tmp_path)
    one, burst = dem_view(working_layer(c)), dem_view(working_layer(c))
    views = views_for(c, fake_iface(), [one])
    c.terrainWritten.connect(views.schedule_rebuild)
    draw(c, 10)
    spin_event_loop(AFTER_REBUILD)
    once = len(one.rebuilds)
    views.shutdown()
    views = views_for(c, fake_iface(), [burst])
    c.terrainWritten.connect(views.schedule_rebuild)
    for row in (12, 14, 16, 18):
        draw(c, row)
        spin_event_loop(REBUILD_DELAY // 4)
    spin_event_loop(AFTER_REBUILD)
    assert once > 0 and len(burst.rebuilds) == once


def test_a_view_closed_meanwhile_is_skipped(tmp_path):
    c = start_session(tmp_path)
    closed, open_ = dem_view(working_layer(c)), dem_view(working_layer(c))
    views = views_for(c, fake_iface(), [closed, open_])
    c.terrainWritten.connect(views.schedule_rebuild)
    draw(c)
    sip.delete(closed)
    spin_event_loop(AFTER_REBUILD)                          # a slot: an error here would abort the run
    assert open_.rebuilds and open_.terrain().resolution() == 40


def test_the_controller_says_when_it_wrote_the_terrain(tmp_path):
    c = start_session(tmp_path)
    heard = []
    c.terrainWritten.connect(lambda: heard.append(True))
    draw(c)
    assert len(heard) == 1
    c.undo_stack.undo()
    assert len(heard) == 2
    c.undo_stack.redo()
    assert len(heard) == 3
    c.save_scenario(str(tmp_path / "s.gpkg"))               # the rasters move beside the scenario: repointed
    assert len(heard) == 4


def test_an_edit_in_the_panel_rebuilds_the_open_view(tmp_path):
    iface, c, dock = panel(tmp_path)
    c.show_in_3d()
    view = dem_view(working_layer(c))
    iface.mapCanvases3D.return_value = [view]
    draw(c)
    spin_event_loop(AFTER_REBUILD)
    assert view.rebuilds and view.terrain().resolution() == 40
    dock.shutdown()


def test_without_the_3d_module_nothing_happens(tmp_path, monkeypatch):
    c = start_session(tmp_path)
    view = dem_view(working_layer(c))
    monkeypatch.setitem(sys.modules, "qgis._3d", None)          # importing it fails
    iface = fake_iface()
    views = views_for(c, iface, [view])
    c.terrainWritten.connect(views.schedule_rebuild)
    views.check_soon()
    draw(c)
    spin_event_loop(AFTER_REBUILD)
    assert view.rebuilds == [] and view.terrain().resolution() == 16
    iface.mapCanvases3D.assert_not_called()                 # it would crash QGIS without the 3D types
