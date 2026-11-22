"""The controller keeps each feature's style and the outline layer's per-feature renderer in step,
both ways: a style set through the controller reaches the map, and an edit made in QGIS's own
symbology (the Layers panel, Layer Properties) comes back to the feature as one undo step."""
from qgis.core import (Qgis, QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsLayerTreeModel, QgsProject,
                       QgsRendererCategory, QgsSingleSymbolRenderer, QgsSymbolLegendNode)
from qgis.PyQt.QtCore import Qt

import terrain_sketch.gui.controller as controller_module
from qgis_helpers import UTM, dem_layer, line_through, panel, spin_event_loop, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.help_texts import USE_FEATURE_STYLES
from terrain_sketch.qgis_io.symbols import from_xml, style_of, to_xml

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


def _legend_labels(model, c) -> list:
    """The labels of the outline layer's symbol entries as an already open Layers panel (`model`) shows them
    now — unlike `_legend_nodes`, which builds the legend afresh."""
    nodes = model.layerLegendNodes(model.rootGroup().findLayer(c.layers.outlines.id()))
    return [n.data(Qt.ItemDataRole.DisplayRole) for n in nodes if isinstance(n, QgsSymbolLegendNode)]


def _open_layers_panel():
    return QgsLayerTreeModel(QgsProject.instance().layerTreeRoot())


def _settle() -> None:
    """Let the controller read back an edit made in QGIS: it does so from the event loop."""
    spin_event_loop(10)


def _record_styles_changed(c) -> list:
    seen = []
    c.stylesChanged.connect(lambda: seen.append(True))
    return seen


def test_a_drawn_feature_is_in_the_open_layers_panel_at_once(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    model = _open_layers_panel()
    assert _legend_labels(model, c) == [dike.name]
    levee = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    assert _legend_labels(model, c) == [dike.name, levee.name]


def test_a_rename_shows_in_the_open_layers_panel_at_once(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    model = _open_layers_panel()
    c.update_feature(dike.id, name="North dike")
    assert _legend_labels(model, c) == ["North dike"]


def test_a_deleted_or_turned_off_feature_leaves_the_open_layers_panel_at_once(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    levee = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    model = _open_layers_panel()
    c.set_enabled(levee.id, False)
    assert _legend_labels(model, c) == [dike.name]
    c.delete_feature(dike.id)
    assert _legend_labels(model, c) == []


def test_an_undo_puts_the_feature_back_in_the_open_layers_panel_at_once(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.delete_feature(dike.id)
    model = _open_layers_panel()
    assert _legend_labels(model, c) == []
    c.undo_stack.undo()
    assert _legend_labels(model, c) == [dike.name]


def test_each_set_style_is_its_own_undo_step_and_marks_unsaved(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.save_scenario(str(tmp_path / "work.gpkg"))
    count = c.undo_stack.count()
    c.set_style(dike.id, RED)
    c.set_style(dike.id, BLUE)
    assert c.find(dike.id).style == BLUE and c.undo_stack.count() == count + 2 and c.is_dirty
    assert c.undo_stack.undoText() == "Change the style of " + dike.name
    c.undo_stack.undo()
    _settle()
    assert c.find(dike.id).style == RED and _symbols(c) == [RED]   # back to the red, not straight past it
    c.undo_stack.undo()
    _settle()
    # the undo's own layer writes must not be read back as a new edit of the old symbol
    assert c.find(dike.id).style is None and _symbols(c) == [None]
    assert c.undo_stack.count() == count + 2 and c.undo_stack.canRedo() and not c.is_dirty


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
    assert c.find(dike.id).style is None   # read back from the event loop, not inside the legend node
    _settle()
    assert c.find(dike.id).style == RED and c.undo_stack.count() == count + 1
    assert c.undo_stack.undoText() == "Change the style of " + dike.name and seen
    c.undo_stack.undo()
    _settle()
    assert c.find(dike.id).style is None and _symbols(c) == [None] and c.undo_stack.count() == count + 1


def test_layers_panel_label_edit_renames_the_feature(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    count = c.undo_stack.count()
    _model, nodes = _legend_nodes(c)
    nodes[0].setData("North dike", Qt.ItemDataRole.EditRole)
    _settle()
    assert c.find(dike.id).name == "North dike" and c.undo_stack.undoText() == "Rename " + dike.name
    assert c.undo_stack.count() == count + 1 and c.find(dike.id).style is None
    c.undo_stack.undo()
    _settle()
    cats = c.layers.outlines.renderer().categories()
    assert c.find(dike.id).name == dike.name and cats[0].label() == dike.name


def test_a_repaint_does_not_strip_a_name_with_spaces(tmp_path):
    c = start_session(tmp_path)
    # From layer takes the layer's name as is; older scenario files can hold such names, too
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, name="Dike ")
    c.save_scenario(str(tmp_path / "work.gpkg"))
    count = c.undo_stack.count()
    c.layers.outlines.triggerRepaint()
    _settle()
    assert c.find(dike.id).name == "Dike " and c.undo_stack.count() == count and not c.is_dirty


def test_unticking_a_category_changes_no_feature(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    seen = _record_styles_changed(c)
    count, before = c.undo_stack.count(), c.features
    _model, nodes = _legend_nodes(c)
    nodes[0].setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    _settle()
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
    _settle()
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
    _settle()
    assert c.undo_stack.count() == count and seen
    c.set_style(dike.id, RED)                     # stored, not drawn
    assert c.find(dike.id).style == RED
    assert isinstance(c.layers.outlines.renderer(), QgsSingleSymbolRenderer)
    assert not c.uses_feature_styles() and to_xml(c.display_symbol(dike.id)) == to_xml(green)
    seen.clear()
    c.use_feature_styles()
    _settle()
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


def test_open_puts_the_feature_styles_back_in_charge(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    c.set_style(dike.id, RED)
    path = str(tmp_path / "work.gpkg")
    c.save_scenario(path)
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "0,255,0,255"})))
    _settle()
    assert not c.uses_feature_styles()
    seen = _record_styles_changed(c)
    c.open_scenario(path)
    reopened = c.features[0]
    assert c.uses_feature_styles() and _symbols(c) == [RED] and seen
    assert [cat.value() for cat in c.layers.outlines.renderer().categories()] == [reopened.id]


def test_new_scenario_puts_the_feature_styles_back_in_charge(tmp_path):
    c = start_session(tmp_path)
    _dike(c)
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "0,255,0,255"})))
    _settle()
    seen = _record_styles_changed(c)
    c.new_scenario()
    assert c.features == () and c.uses_feature_styles() and _symbols(c) == [] and seen
    levee = _dike(c)
    assert [cat.value() for cat in c.layers.outlines.renderer().categories()] == [levee.id]


def test_classify_takes_the_new_colours_and_keeps_the_names(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    levee = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    count = c.undo_stack.count()
    # Layer Properties > Symbology > Classify labels each category with its value: here the feature id
    c.layers.outlines.setRenderer(QgsCategorizedSymbolRenderer("feature_id", [
        QgsRendererCategory(dike.id, QgsFillSymbol.createSimple({"color": "255,0,0,255"}), dike.id),
        QgsRendererCategory(levee.id, QgsFillSymbol.createSimple({"color": "0,0,255,255"}), levee.id)]))
    _settle()
    assert [f.name for f in c.features] == [dike.name, levee.name]
    assert [f.style for f in c.features] == [RED, BLUE]
    assert c.undo_stack.count() == count + 1 and c.undo_stack.undoText() == "Change feature styles"


def test_ending_the_session_before_the_read_back_commits_nothing(tmp_path, monkeypatch):
    c = start_session(tmp_path)
    _dike(c)
    logged = []
    monkeypatch.setattr(controller_module.QgsMessageLog, "logMessage",
                        lambda text, tag="", level=None, *a: logged.append((text, level)))
    seen = _record_styles_changed(c)
    model, nodes = _legend_nodes(c)
    nodes[0].setSymbol(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))
    del model, nodes   # the legend goes with the layers below
    c.close()
    _settle()
    assert c.features == () and c.undo_stack.count() == 0 and not seen
    assert [text for text, level in logged if level == Qgis.MessageLevel.Critical] == []


def _menu_texts(dock, fid) -> list:
    return [a.text() for a in dock.feature_menu(dock.model.index(dock.model.row_of(fid))).actions()]


def test_use_feature_styles_again_is_offered_only_when_needed(tmp_path):
    iface, c, dock = panel(tmp_path)
    dike = _dike(c)
    c.set_style(dike.id, RED)
    iface.addCustomActionForLayerType.assert_called_with(dock.use_styles_action, "", Qgis.LayerType.Vector, False)
    iface.addCustomActionForLayer.assert_called_with(dock.use_styles_action, c.layers.outlines)
    assert dock.use_styles_action.text() == USE_FEATURE_STYLES
    assert not dock.use_styles_action.isEnabled()
    assert USE_FEATURE_STYLES not in _menu_texts(dock, dike.id)
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "0,255,0,255"})))
    _settle()
    assert dock.use_styles_action.isEnabled()
    texts = _menu_texts(dock, dike.id)
    assert texts.index(USE_FEATURE_STYLES) < texts.index("")   # above the separator
    menu = dock.feature_menu(dock.model.index(dock.model.row_of(dike.id)))
    menu_action = next(a for a in menu.actions() if a.text() == USE_FEATURE_STYLES)
    menu_action.trigger()
    _settle()
    assert c.uses_feature_styles() and _symbols(c) == [RED]
    assert not dock.use_styles_action.isEnabled()
    first = c.layers.outlines
    dock.dem_combo.setLayer(dem_layer(tmp_path, name="other"))   # Start on another DEM: a new outline layer
    dock.start_button.click()
    assert c.layers.outlines is not first
    iface.addCustomActionForLayer.assert_called_with(dock.use_styles_action, c.layers.outlines)


def test_shutdown_removes_the_layer_action(tmp_path):
    iface, _c, dock = panel(tmp_path)
    iface.removeCustomActionForLayerType.assert_not_called()
    dock.shutdown()
    iface.removeCustomActionForLayerType.assert_called_with(dock.use_styles_action)


def test_a_layer_write_after_a_nested_one_is_still_the_controllers_own(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    count = c.undo_stack.count()
    with c._outline_writes():
        with c._outline_writes():
            pass
        cats = c.layers.outlines.renderer().categories()  # kept alive while its symbols are used
        c.layers.outlines.renderer().updateCategorySymbol(0, from_xml(RED))
        c.layers.outlines.triggerRepaint()
        del cats
    _settle()
    assert c.find(dike.id).style is None and c.undo_stack.count() == count

