import pytest
from qgis.core import Qgis, QgsGeometry, QgsPointXY, QgsProject

import terrain_scenarios.gui.controller as controller_module
from qgis_helpers import (UTM, dem_layer, line_layer, line_through, read_tif, sample, square,
                          start_session, world)
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.qgis_io.layers import GROUP_NAME
from terrain_scenarios.qgis_io.raster_io import DemError


def test_drawing_a_dike_updates_the_modified_dem(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dike.name == "Raise path 1" and c.features == (dike,)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)  # 1 m above the flat 10 m ground
    assert sample(c.layers.change, 20, 20) == pytest.approx(1.0)
    assert c.layers.outlines.featureCount() == 1


def test_editing_toggling_and_deleting_recompute(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=2.5)
    assert sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    c.set_enabled(dike.id, False)
    assert sample(c.layers.working, 20, 20) == pytest.approx(10.0)
    assert c.layers.outlines.featureCount() == 0
    c.delete_feature(dike.id)
    assert c.features == ()


def test_names_are_unique_and_reorder_changes_the_order(tmp_path):
    c = start_session(tmp_path)
    a = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 10, 30, 10), UTM)
    b = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 30, 30, 30), UTM)
    assert (a.name, b.name) == ("Add to terrain 1", "Add to terrain 2")
    c.reorder([b.id, a.id])
    assert [f.id for f in c.features] == [b.id, a.id]
    with pytest.raises(ValueError):
        c.reorder([a.id])


def test_an_unusable_drawing_is_reported_and_not_added(tmp_path):
    c = start_session(tmp_path)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_drawn(Tool.RAISE_FLAT, Mode.AREA, line_through(5, 5, 10, 10), UTM) is None
    assert c.features == () and messages


def test_export_writes_the_modified_dem(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.export_dem(str(tmp_path / "out.tif"))
    exported, _ = read_tif(tmp_path / "out.tif")
    assert exported[20, 20] == pytest.approx(11.0) and exported[0, 0] == pytest.approx(10.0)


def test_removing_the_dem_layer_ends_the_session(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    QgsProject.instance().removeMapLayer(c.dem_layer_id)
    assert not c.has_dem and c.features == () and messages
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None


def test_export_refuses_to_overwrite_the_source_dem(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    with pytest.raises(RuntimeError):
        c.export_dem(c.info.path)
    with pytest.raises(RuntimeError):
        c.export_dem(c.files.working_path)
    source, _ = read_tif(c.info.path)
    assert source[20, 20] == pytest.approx(10.0)


def test_failing_working_files_keep_the_previous_session(tmp_path, monkeypatch):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(controller_module, "WorkingFiles", boom)
    with pytest.raises(DemError):
        c.set_dem(dem_layer(tmp_path, name="other"))
    assert c.has_dem
    assert c.features == (dike,)
    assert c.files is not None and c.layers is not None


def test_removing_a_result_layer_keeps_the_session(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    messages = []
    c.message.connect(lambda level, text: messages.append((level, text)))
    QgsProject.instance().removeMapLayer(c.layers.change_id)
    assert c.has_dem and c.features == (dike,)
    assert messages and messages[-1][0] == Qgis.MessageLevel.Info
    c.update_feature(dike.id, amount=2.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(12.0)


def test_a_new_project_drops_the_session_without_a_message(tmp_path):
    c = start_session(tmp_path)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    QgsProject.instance().clear()
    assert not c.has_dem and not messages


def test_an_engine_error_keeps_the_previous_feature_list(tmp_path, monkeypatch):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dike.amount == pytest.approx(1.0)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(c.stack, "update", boom)
    c.update_feature(dike.id, amount=5.0)
    assert messages
    assert c.feature(dike.id).amount == pytest.approx(1.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)


def test_a_geographic_dem_is_refused_without_side_effects(tmp_path):
    c = SketchController(QgsProject.instance())
    with pytest.raises(DemError):
        c.set_dem(dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001)))
    assert not c.has_dem
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None


def test_drawing_or_exporting_without_a_session_is_reported_not_raised(tmp_path):
    c = start_session(tmp_path)
    c.close()  # e.g. the DEM layer was removed while the user was still drawing
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM) is None
    assert messages and not c.dem_crs.isValid()
    with pytest.raises(RuntimeError, match="Start"):
        c.export_dem(str(tmp_path / "out.tif"))


def test_features_from_a_layer_become_one_multi_part_feature(tmp_path):
    c = start_session(tmp_path)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    feature = c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)
    assert feature.name == "Planned dikes" and len(c.features) == 1
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)
    assert sample(c.layers.working, 20, 30) == pytest.approx(11.0)


def test_only_the_selected_features_are_used(tmp_path):
    c = start_session(tmp_path)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    layer.selectByIds([next(layer.getFeatures()).id()])
    c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer, selected_only=True)
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)
    assert sample(c.layers.working, 20, 30) == pytest.approx(10.0)


def test_an_empty_layer_selection_is_reported(tmp_path):
    c = start_session(tmp_path)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer, selected_only=True) is None
    assert c.features == () and messages


def test_set_geometry_replaces_the_shape(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.set_geometry(dike.id, line_through(5, 30, 34, 30), UTM)
    assert sample(c.layers.working, 20, 20) == pytest.approx(10.0)
    assert sample(c.layers.working, 20, 30) == pytest.approx(11.0)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.set_geometry(dike.id, square(10, 10, 20, 20), UTM) is False  # an area cannot replace a path
    assert messages


def test_reshaping_a_feature_that_was_deleted_is_reported_not_raised(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.delete_feature(dike.id)  # e.g. the Delete button while a brush stroke was still running
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.set_geometry(dike.id, line_through(5, 30, 34, 30), UTM) is False
    assert messages and c.features == ()


def test_importing_the_same_layer_twice_numbers_the_second_feature(tmp_path):
    c = start_session(tmp_path)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    first = c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)
    second = c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)
    assert (first.name, second.name) == ("Planned dikes", "Planned dikes 2")


def test_a_long_section_that_raises_is_logged_and_reported_empty(tmp_path, monkeypatch):
    """`ProfileDock._refresh` calls this from a slot, and its chain reaches `split_parts`, which
    raises for a geometry it cannot use. An exception in a Qt callback takes QGIS down."""
    from terrain_scenarios.gui.profile_dock import ProfileDock
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    log = []
    monkeypatch.setattr(controller_module.QgsMessageLog, "logMessage",
                        staticmethod(lambda text, *a, **kw: log.append(text)))

    # a point where a line is expected: what Plan 6 can load from a scenario GeoPackage
    point = QgsGeometry.fromPointXY(QgsPointXY(*world(20, 20))).asWkb().data()
    c.update_feature(dike.id, geometry_wkb=point)
    assert c.feature(dike.id).geometry_wkb == point

    section = c.long_section(dike.id)
    assert section == {"stations": (), "terrain": (), "design": (), "custom": False}
    assert log and "ValueError" in log[-1]
    dock.show_feature(dike.id)          # the panel that runs in the slot survives it
    assert dock.long.points == []


def test_a_long_section_for_a_missing_feature_is_empty_without_logging(tmp_path, monkeypatch):
    c = start_session(tmp_path)
    log = []
    monkeypatch.setattr(controller_module.QgsMessageLog, "logMessage",
                        staticmethod(lambda text, *a, **kw: log.append(text)))
    assert c.long_section("nope") == {"stations": (), "terrain": (), "design": (), "custom": False}
    assert not log
