from qgis.core import QgsGeometry, QgsPointXY, QgsProject

from qgis_helpers import dem_layer, world
from terrain_sketch.core.grid import Window
from terrain_sketch.qgis_io.layers import GROUP_NAME, SketchLayers
from terrain_sketch.qgis_io.raster_io import WorkingFiles, read_dem


def _layers(tmp_path):
    dem = dem_layer(tmp_path)
    grid, info = read_dem(dem)
    files = WorkingFiles(str(tmp_path / "s"), grid, info)
    return grid, files, SketchLayers(QgsProject.instance(), dem, files.working_path, files.change_path)


def test_group_holds_the_four_layers_in_order(tmp_path):
    _, _, layers = _layers(tmp_path)
    group = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME)
    assert [n.layer().name() for n in group.findLayers()] == [
        "Sketch outlines", "Change (new − original)", "Hillshade", "Modified DEM"]
    assert not group.findLayer(layers.hillshade.id()).itemVisibilityChecked()
    assert type(layers.change.renderer()).__name__ == "QgsSingleBandPseudoColorRenderer"
    assert type(layers.hillshade.renderer()).__name__ == "QgsHillshadeRenderer"


def test_refresh_shows_new_values_and_outlines_update(tmp_path):
    grid, files, layers = _layers(tmp_path)
    working = grid.copy()
    working.data[2, 3] = 15.0
    files.write(Window(2, 3, 1, 1), working)
    layers.refresh()
    x, y = world(3, 2)
    assert layers.working.dataProvider().sample(QgsPointXY(x, y), 1)[0] == 15.0
    triangle = QgsGeometry.fromWkt(f"POLYGON(({x} {y}, {x + 5} {y}, {x + 5} {y - 5}, {x} {y}))")
    layers.set_outlines([("Pond", "Lower flat", triangle)])
    assert layers.outlines.featureCount() == 1


def test_remove_takes_the_group_and_its_layers_away(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.remove()
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None
    assert all(QgsProject.instance().mapLayer(i) is None for i in layers.layer_ids)
