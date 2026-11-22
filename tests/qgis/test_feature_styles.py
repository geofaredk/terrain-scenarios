"""The controller keeps each feature's style and the outline layer's per-feature renderer in step,
both ways: a style set through the controller reaches the map, and an edit made in QGIS's own
symbology (the Layers panel, Layer Properties) comes back to the feature as one undo step."""
from qgis.core import (QgsFillSymbol, QgsLayerTreeModel, QgsProject, QgsRendererCategory, QgsSingleSymbolRenderer,
                       QgsSymbolLegendNode)
from qgis.PyQt.QtCore import Qt

from qgis_helpers import UTM, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.qgis_io.symbols import style_of, to_xml

RED = to_xml(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))
BLUE = to_xml(QgsFillSymbol.createSimple({"color": "0,0,255,255"}))


def _dike(c):
    return c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)


def _symbols(c) -> list:
    cats = c.layers.outlines.renderer().categories()  # kept alive while its symbols are read
    return [style_of(cat.symbol()) for cat in cats]


def _legend_nodes(c):
    """The outline layer's symbol legend nodes, as the Layers panel shows them; the model is returned
    too, as the nodes live only as long as it does."""
    root = QgsProject.instance().layerTreeRoot()
    model = QgsLayerTreeModel(root)
    nodes = model.layerLegendNodes(root.findLayer(c.layers.outlines.id()))
    return model, [n for n in nodes if isinstance(n, QgsSymbolLegendNode)]


def _record_styles_changed(c) -> list:
    seen = []
    c.stylesChanged.connect(lambda: seen.append(True))
    return seen


def test_set_style_is_one_undoable_step_and_marks_unsaved(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.save_scenario(str(tmp_path / "work.gpkg"))
    count = c.undo_stack.count()
    c.set_style(dike.id, RED)
    c.set_style(dike.id, BLUE)
    assert c.find(dike.id).style == BLUE and c.undo_stack.count() == count + 1 and c.is_dirty
    assert c.undo_stack.undoText() == "Change the style of " + dike.name
    c.undo_stack.undo()
    # the undo's own layer writes must not be read back as a new edit of the old symbol
    assert c.find(dike.id).style is None and _symbols(c) == [None]
    assert c.undo_stack.count() == count + 1 and c.undo_stack.canRedo() and not c.is_dirty


def test_set_style_does_not_touch_the_terrain(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    writes = []
    write = c.files.write
    c.files.write = lambda *args: (writes.append(args), write(*args))[1]
    c.set_style(dike.id, RED)
    assert c.find(dike.id).style == RED and writes == []


def test_set_style_reaches_the_map(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.set_style(dike.id, RED)
    cats = c.layers.outlines.renderer().categories()
    assert [cat.value() for cat in cats] == [dike.id]
    assert to_xml(cats[0].symbol()) == RED and cats[0].label() == dike.name


def test_layers_panel_symbol_edit_is_one_undo_step(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    seen = _record_styles_changed(c)
    count = c.undo_stack.count()
    _model, nodes = _legend_nodes(c)
    nodes[0].setSymbol(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))  # takes ownership: a fresh one
    assert c.find(dike.id).style == RED and c.undo_stack.count() == count + 1
    assert c.undo_stack.undoText() == "Change the style of " + dike.name and seen
    c.undo_stack.undo()
    assert c.find(dike.id).style is None and _symbols(c) == [None] and c.undo_stack.count() == count + 1


def test_layers_panel_label_edit_renames_the_feature(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    count = c.undo_stack.count()
    _model, nodes = _legend_nodes(c)
    nodes[0].setData("North dike", Qt.ItemDataRole.EditRole)
    assert c.find(dike.id).name == "North dike" and c.undo_stack.undoText() == "Rename " + dike.name
    assert c.undo_stack.count() == count + 1 and c.find(dike.id).style is None
    c.undo_stack.undo()
    cats = c.layers.outlines.renderer().categories()
    assert c.find(dike.id).name == dike.name and cats[0].label() == dike.name


def test_unticking_a_category_changes_no_feature(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    seen = _record_styles_changed(c)
    count, before = c.undo_stack.count(), c.features
    _model, nodes = _legend_nodes(c)
    nodes[0].setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert c.find(dike.id).enabled and c.features == before and c.undo_stack.count() == count and seen
    assert [cat.renderState() for cat in c.layers.outlines.renderer().categories()] == [False]


def test_categories_that_are_not_features_are_ignored(tmp_path):
    c = start_session(tmp_path)
    _dike(c)
    seen = _record_styles_changed(c)
    count, before = c.undo_stack.count(), c.features
    renderer = c.layers.outlines.renderer()
    renderer.addCategory(QgsRendererCategory("", QgsFillSymbol.createSimple({"color": "0,255,0,255"}), "Other"))
    renderer.addCategory(QgsRendererCategory("deadbeef", QgsFillSymbol.createSimple({"color": "0,0,255,255"}),
                                             "Ghost"))
    c.layers.outlines.emitStyleChanged()
    assert c.features == before and c.undo_stack.count() == count and seen


def test_turned_off_feature_keeps_its_style(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.set_style(dike.id, RED)
    c.set_enabled(dike.id, False)
    assert [cat.value() for cat in c.layers.outlines.renderer().categories()] == []
    assert c.find(dike.id).style == RED
    c.set_enabled(dike.id, True)
    cats = c.layers.outlines.renderer().categories()
    assert to_xml(cats[0].symbol()) == RED


def test_duplicate_copies_the_style(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.set_style(dike.id, RED)
    copy = c.duplicate_feature(dike.id)
    assert copy.style == RED and c.find(copy.id).style == RED
    assert to_xml(c.display_symbol(copy.id)) == RED   # turned off, so its own stored style


def test_a_replaced_renderer_is_kept_and_shown(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    seen = _record_styles_changed(c)
    green = QgsFillSymbol.createSimple({"color": "0,255,0,255"})
    count = c.undo_stack.count()
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(green.clone()))
    assert c.undo_stack.count() == count and seen
    c.set_style(dike.id, RED)                     # stored, not drawn
    assert c.find(dike.id).style == RED
    assert isinstance(c.layers.outlines.renderer(), QgsSingleSymbolRenderer)
    assert not c.uses_feature_styles() and to_xml(c.display_symbol(dike.id)) == to_xml(green)
    seen.clear()
    c.use_feature_styles()
    assert c.uses_feature_styles() and to_xml(c.display_symbol(dike.id)) == RED and seen
    assert _symbols(c) == [RED] and c.find(dike.id).style == RED


def test_styles_work_without_the_outline_layer(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    QgsProject.instance().removeMapLayer(c.layers.outlines_id)
    c.set_style(dike.id, RED)
    assert c.find(dike.id).style == RED
    assert c.uses_feature_styles() and to_xml(c.display_symbol(dike.id)) == RED
    c.use_feature_styles()   # nothing to put a renderer on: does nothing, and does not raise
    assert c.display_symbol("no such feature") is None


def test_styles_come_back_after_save_and_open(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.set_style(dike.id, RED)
    path = str(tmp_path / "work.gpkg")
    c.save_scenario(path)
    c.set_style(dike.id, None)
    assert c.display_symbol(dike.id) is None and _symbols(c) == [None]
    c.open_scenario(path)
    reopened = next(f for f in c.features if f.name == dike.name)   # opened features get fresh ids
    assert reopened.style == RED and to_xml(c.display_symbol(reopened.id)) == RED
    cats = c.layers.outlines.renderer().categories()
    assert [cat.value() for cat in cats] == [reopened.id] and to_xml(cats[0].symbol()) == RED
