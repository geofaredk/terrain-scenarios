import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, read_tif, sample, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.qgis_io.layers import GROUP_NAME
from terrain_sketch.qgis_io.raster_io import DemError


def test_drawing_a_dike_updates_the_modified_dem(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dike.name == "Raise path 1" and c.features == (dike,)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)  # 1 m above the flat 10 m ground
    assert sample(c.layers.change, 20, 20) == pytest.approx(1.0)
    assert c.stats(dike.id).fill > 0 and c.layers.outlines.featureCount() == 1


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
