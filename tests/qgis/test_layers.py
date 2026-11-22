from qgis.core import (QgsCategorizedSymbolRenderer, QgsCoordinateTransformContext, QgsFillSymbol, QgsGeometry,
                       QgsPointXY, QgsProject, QgsRendererCategory, QgsSingleSymbolRenderer, QgsVectorFileWriter,
                       QgsVectorLayer)

from qgis_helpers import dem_layer, world
from terrain_sketch.core.grid import Window
from terrain_sketch.qgis_io.layers import GROUP_NAME, SketchLayers
from terrain_sketch.qgis_io.raster_io import WorkingFiles, read_dem
from terrain_sketch.qgis_io.symbols import default_symbol, style_of, to_xml


def _layers(tmp_path):
    dem = dem_layer(tmp_path)
    grid, info = read_dem(dem)
    files = WorkingFiles(str(tmp_path / "s"), grid, info)
    return grid, files, SketchLayers(QgsProject.instance(), dem, files.working_path, files.change_path)


def test_group_holds_the_three_layers_in_order(tmp_path):
    _, _, layers = _layers(tmp_path)
    group = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME)
    assert [n.layer().name() for n in group.findLayers()] == [
        "Sketch outlines", "Change (new − original)", "Modified DEM"]
    assert type(layers.change.renderer()).__name__ == "QgsSingleBandPseudoColorRenderer"


def test_refresh_shows_new_values_and_outlines_update(tmp_path):
    grid, files, layers = _layers(tmp_path)
    working = grid.copy()
    working.data[2, 3] = 15.0
    files.write(Window(2, 3, 1, 1), working)
    layers.refresh()
    x, y = world(3, 2)
    assert layers.working.dataProvider().sample(QgsPointXY(x, y), 1)[0] == 15.0
    triangle = QgsGeometry.fromWkt(f"POLYGON(({x} {y}, {x + 5} {y}, {x + 5} {y - 5}, {x} {y}))")
    layers.set_outlines([("f1", "Pond", "Lower flat", triangle)])
    assert layers.outlines.featureCount() == 1


def test_remove_takes_the_group_and_its_layers_away(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.remove()
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None
    assert all(QgsProject.instance().mapLayer(i) is None for i in layers.layer_ids)


def test_refresh_and_cleanup_tolerate_layers_the_user_removed(tmp_path):
    _, _, layers = _layers(tmp_path)
    QgsProject.instance().removeMapLayers([layers.change_id, layers.outlines_id])  # the user deletes two layers
    layers.refresh()
    layers.set_outlines([])
    layers.remove()
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None
    assert all(QgsProject.instance().mapLayer(i) is None for i in layers.layer_ids)


def _red():
    return to_xml(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))


def _blue():
    return to_xml(QgsFillSymbol.createSimple({"color": "0,0,255,255"}))


def test_a_new_outline_layer_draws_features_by_feature_id(tmp_path):
    _, _, layers = _layers(tmp_path)
    renderer = layers.outlines.renderer()
    assert isinstance(renderer, QgsCategorizedSymbolRenderer) and renderer.classAttribute() == "feature_id"
    assert renderer.categories() == [] and layers.is_managed()
    assert [f.name() for f in layers.outlines.fields()] == ["feature_id", "name", "tool"]


def test_the_outline_layer_exports_to_geopackage(tmp_path):
    """Save Features As and Make Permanent write a GeoPackage by default, whose own `fid` is its integer key."""
    _, _, layers = _layers(tmp_path)
    triangle = QgsGeometry.fromWkt("POLYGON((0 0, 5 0, 5 5, 0 0))")
    layers.set_outlines([("a1", "Pond", "Lower flat", triangle), ("b2", "Dike", "Raise path", triangle)])
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    path = str(tmp_path / "outlines.gpkg")
    error, message, _path, _layer = QgsVectorFileWriter.writeAsVectorFormatV3(
        layers.outlines, path, QgsCoordinateTransformContext(), options)
    assert error == QgsVectorFileWriter.WriterError.NoError, message
    written = QgsVectorLayer(path, "written", "ogr")
    assert sorted((f["feature_id"], f["name"], f["tool"]) for f in written.getFeatures()) == [
        ("a1", "Pond", "Lower flat"), ("b2", "Dike", "Raise path")]


def test_apply_styles_gives_each_feature_a_category(tmp_path):
    _, _, layers = _layers(tmp_path)
    red = _red()
    layers.apply_styles([("a", "North dike", red), ("b", "Pond", None)])
    cats = layers.outlines.renderer().categories()
    assert [(c.value(), c.label()) for c in cats] == [("a", "North dike"), ("b", "Pond")]
    assert to_xml(cats[0].symbol()) == red and style_of(cats[1].symbol()) is None


def test_apply_styles_updates_in_place_and_keeps_render_state(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.apply_styles([("a", "North dike", None), ("b", "Pond", None)])
    renderer = layers.outlines.renderer()
    renderer.updateCategoryRenderState(1, False)  # the user unticks Pond in the Layers panel
    layers.apply_styles([("a", "South dike", _blue()), ("b", "Pond", None)])
    assert layers.outlines.renderer() is renderer
    cats = renderer.categories()
    assert [(c.value(), c.label(), c.renderState()) for c in cats] == [
        ("a", "South dike", True), ("b", "Pond", False)]
    assert to_xml(cats[0].symbol()) == _blue()


def test_apply_styles_follows_the_list_order(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.apply_styles([("a", "A", None), ("b", "B", None)])
    layers.apply_styles([("c", "C", None), ("b", "B", None), ("a", "A", None)])
    assert [c.value() for c in layers.outlines.renderer().categories()] == ["c", "b", "a"]


def test_apply_styles_drops_features_no_longer_listed_but_keeps_an_all_other_values_category(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.apply_styles([("a", "A", None), ("b", "B", None)])
    layers.outlines.renderer().addCategory(QgsRendererCategory("", default_symbol(), "other"))
    layers.apply_styles([("a", "A", None)])
    assert [c.value() for c in layers.outlines.renderer().categories()] == ["a", ""]


def test_read_styles_reports_labels_and_styles(tmp_path):
    _, _, layers = _layers(tmp_path)
    red = _red()
    layers.apply_styles([("a", "North dike", red), ("b", "Pond", None)])
    layers.outlines.renderer().addCategory(QgsRendererCategory("", QgsFillSymbol.createSimple({}), "other"))
    assert layers.read_styles() == {"a": ("North dike", red), "b": ("Pond", None)}


def test_a_merged_category_is_no_ones_style_and_gives_way_to_one_category_per_feature(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.apply_styles([("c", "C", None)])
    layers.outlines.renderer().addCategory(QgsRendererCategory(["a", "b"], default_symbol(), "a, b"))  # Merge
    assert layers.read_styles() == {"c": ("C", None)}
    layers.apply_styles([("a", "A", _red()), ("b", "B", None), ("c", "C", None)])
    cats = layers.outlines.renderer().categories()
    assert [c.value() for c in cats] == ["a", "b", "c"]
    assert layers.read_styles() == {"a": ("A", _red()), "b": ("B", None), "c": ("C", None)}


def test_a_replaced_renderer_is_left_alone(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.outlines.setRenderer(QgsSingleSymbolRenderer(default_symbol()))
    assert not layers.is_managed()
    layers.apply_styles([("a", "A", None)])
    assert isinstance(layers.outlines.renderer(), QgsSingleSymbolRenderer) and layers.read_styles() == {}
    layers.use_feature_styles([("a", "A", _red())])
    assert layers.is_managed()
    assert layers.read_styles() == {"a": ("A", _red())}


def test_drawn_symbol_is_what_the_map_draws(tmp_path):
    _, _, layers = _layers(tmp_path)
    triangle = QgsGeometry.fromWkt("POLYGON((0 0, 5 0, 5 5, 0 0))")
    layers.set_outlines([("a", "Pond", "Lower flat", triangle)])
    layers.apply_styles([("a", "Pond", _blue())])
    assert to_xml(layers.drawn_symbol("a")) == _blue()
    layers.outlines.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "255,0,0,255"})))
    assert to_xml(layers.drawn_symbol("a")) == _red()
    assert layers.drawn_symbol("missing") is None
