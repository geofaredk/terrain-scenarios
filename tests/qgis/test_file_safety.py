"""Paths that used to crash QGIS or leave files behind: projection failures, replaced exports,
temporary working files and a half-built layer group."""
import os
from unittest import mock

import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui import controller as controller_module
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import EXPORT_REPLACE, SHAPE_NOT_TRANSFORMED
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.gui.selection import Method
from terrain_sketch.qgis_io.layers import GROUP_NAME
from terrain_sketch.qgis_io.raster_io import DemError


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def messages(iface) -> list[str]:
    return [call[0][1] for call in iface.messageBar().pushMessage.call_args_list]


def test_zooming_to_a_feature_whose_outline_cannot_be_projected_is_a_message(tmp_path):
    iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    with mock.patch.object(QgsCoordinateTransform, "transformBoundingBox", side_effect=QgsCsException("forced")):
        dock._zoom_to(dike.id)                      # the context-menu action's slot
    assert SHAPE_NOT_TRANSFORMED in messages(iface)


def test_zooming_to_a_feature_that_has_gone_does_nothing(tmp_path):
    iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    extent = iface.mapCanvas().extent()
    c.delete_feature(dike.id)
    dock._zoom_to(dike.id)
    assert iface.mapCanvas().extent() == extent


def test_editing_a_shape_that_cannot_be_projected_is_a_message_not_a_crash(tmp_path):
    iface, c, dock = panel(tmp_path)
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    with mock.patch.object(QgsGeometry, "transform", side_effect=QgsCsException("forced")):
        dock.edit_button.setChecked(True)          # toggled -> slot; an exception there aborts QGIS
    assert dock.edit_tool is None and not dock.edit_button.isChecked()
    assert SHAPE_NOT_TRANSFORMED in messages(iface)


def test_brushing_onto_a_shape_that_cannot_be_projected_is_a_message_not_a_crash(tmp_path):
    iface, c, dock = panel(tmp_path)
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    with mock.patch.object(QgsGeometry, "transform", side_effect=QgsCsException("forced")):
        dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock.draw_tool is None and dock._brush_fid is None
    assert SHAPE_NOT_TRANSFORMED in messages(iface)


@pytest.mark.parametrize("typed, replaced", [("flood", True), ("flood.tif", False)])
def test_an_export_name_typed_without_tif_asks_before_replacing_that_file(tmp_path, monkeypatch, typed, replaced):
    """The dialog checks for overwriting before `.tif` is added, so an existing flood.tif would be
    replaced silently when the user types just `flood`."""
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, _c, dock = panel(tmp_path)
    (tmp_path / "flood.tif").write_bytes(b"an earlier export")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / typed), "")))
    questions = []
    dock.confirm = lambda text: questions.append(text) or False
    assert dock._export_dialog() == ("" if replaced else str(tmp_path / "flood.tif"))
    assert questions == ([EXPORT_REPLACE.format("flood.tif")] if replaced else [])
    dock.confirm = lambda text: True
    assert dock._export_dialog() == str(tmp_path / "flood.tif")


def test_closing_a_session_removes_its_working_files(tmp_path):
    c = start_session(tmp_path)
    folder = c.files.folder
    assert os.path.isfile(os.path.join(folder, "working_dem.tif"))
    c.close()
    assert not os.path.exists(folder)


def test_clearing_the_project_removes_the_working_files(tmp_path):
    c = start_session(tmp_path)
    folder = c.files.folder
    QgsProject.instance().clear()
    assert not c.has_dem and not os.path.exists(folder)


def test_starting_on_another_dem_removes_only_the_old_working_files(tmp_path):
    c = start_session(tmp_path)
    old = c.files.folder
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    assert not os.path.exists(old) and os.path.isdir(c.files.folder)


def test_working_files_that_cannot_be_written_leave_no_folder_behind(tmp_path, monkeypatch):
    import tempfile
    made = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(real(**kw)) or made[-1])
    c = SketchController(QgsProject.instance())
    dem = dem_layer(tmp_path)
    with mock.patch.object(controller_module, "WorkingFiles", side_effect=OSError("disk full")):
        with pytest.raises(DemError):
            c.set_dem(dem)
    assert made and not os.path.exists(made[0])


def test_a_layer_group_that_fails_half_way_is_removed_again(tmp_path):
    """The group is in the layer tree before its layers are wired up; a failure there (here the
    hillshade node cannot be found, so hiding it raises) must not leave a half-built group."""
    from qgis.core import QgsLayerTreeGroup
    c = SketchController(QgsProject.instance())
    dem = dem_layer(tmp_path)
    with mock.patch.object(QgsLayerTreeGroup, "findLayer", return_value=None) as find:
        with pytest.raises(DemError):
            c.set_dem(dem)
    project = QgsProject.instance()
    assert find.called                                  # it really failed after the group existed
    assert project.layerTreeRoot().findGroup(GROUP_NAME) is None
    assert not project.mapLayersByName("Sketch outlines") and not project.mapLayersByName("Modified DEM")
    assert project.mapLayer(dem.id()) is not None       # the user's DEM is untouched
    assert not c.has_dem


def test_working_files_failing_in_an_unexpected_way_leave_no_folder_behind(tmp_path, monkeypatch):
    import tempfile
    made = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(real(**kw)) or made[-1])
    c = SketchController(QgsProject.instance())
    dem = dem_layer(tmp_path)
    with mock.patch.object(controller_module, "WorkingFiles", side_effect=ValueError("a GDAL surprise")):
        with pytest.raises(DemError):
            c.set_dem(dem)
    assert made and not os.path.exists(made[0])


def test_a_start_that_fails_leaves_the_running_session_as_it_was(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    folder, working = c.files.folder, c.layers.working_id
    (tmp_path / "geographic").mkdir()
    with pytest.raises(DemError):
        c.set_dem(dem_layer(tmp_path / "geographic", name="lat_lon", crs="EPSG:4326",
                            gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001)))
    assert c.has_dem and [f.id for f in c.features] == [dike.id]
    assert os.path.isdir(folder) and QgsProject.instance().mapLayer(working) is not None


def test_shutting_a_controller_down_twice_is_safe(tmp_path):
    c = start_session(tmp_path)
    c.shutdown()
    c.shutdown()
    QgsProject.instance().clear()          # no longer listening, so nothing of it runs
    assert not c.has_dem
