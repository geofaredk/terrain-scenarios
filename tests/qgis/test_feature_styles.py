"""The controller keeps each feature's style and the outline layer's per-feature renderer in step,
both ways: a style set through the controller reaches the map, and an edit made in QGIS's own
symbology (the Layers panel, Layer Properties) comes back to the feature as one undo step."""
from qgis.core import (Qgis, QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsLayerTreeModel, QgsProject,
                       QgsRendererCategory, QgsSingleSymbolRenderer, QgsSymbolLegendNode)
from qgis.gui import QgsSymbolSelectorWidget
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QLabel

import terrain_sketch.gui.controller as controller_module
from qgis_helpers import UTM, dem_layer, line_through, panel, spin_event_loop, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.help_texts import STYLE_LAYER_TIP, STYLE_TIP, USE_FEATURE_STYLES
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


def _settle() -> None:
    """Let the controller read back an edit made in QGIS: it does so from the event loop."""
    spin_event_loop(10)


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
    _settle()
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


def test_classify_takes_the_new_colours_and_keeps_the_names(tmp_path):
    c = start_session(tmp_path)
    dike = _dike(c)
    levee = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    count = c.undo_stack.count()
    # Layer Properties > Symbology > Classify labels each category with its value: here the feature id
    c.layers.outlines.setRenderer(QgsCategorizedSymbolRenderer("fid", [
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


def _feature_page(tmp_path, style=None):
    """The panel with a dike drawn (given `style` first) and its feature page open."""
    iface, c, dock = panel(tmp_path)
    dike = _dike(c)
    if style is not None:
        c.set_style(dike.id, style)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page
    return iface, c, dock, dike


def _menu_texts(dock, fid) -> list:
    return [a.text() for a in dock.feature_menu(dock.model.index(dock.model.row_of(fid))).actions()]


def test_style_button_shows_and_sets_the_feature_style(tmp_path):
    _iface, c, dock, dike = _feature_page(tmp_path, style=BLUE)
    page = dock.properties
    assert style_of(page.style_button.symbol()) == BLUE
    assert page.style_button.isEnabled() and page.style_button.toolTip() == STYLE_TIP
    page.style_button.setSymbol(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))
    assert c.find(dike.id).style == RED and _symbols(c) == [RED]
    page.style_button.setToNull()
    assert c.find(dike.id).style is None
    # shows the default look again after reload, not an empty button
    assert page.style_button.symbol() is not None and style_of(page.style_button.symbol()) is None
    c.undo_stack.clear()   # the edits above merged into one step with the BLUE before them
    page.style_button.setSymbol(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))
    c.undo_stack.undo()   # an undo moves the button back too
    assert c.find(dike.id).style is None and style_of(page.style_button.symbol()) is None
    c.undo_stack.redo()
    assert style_of(page.style_button.symbol()) == RED
    c.delete_feature(dike.id)                       # the button outlives the feature it showed
    count = c.undo_stack.count()
    page.style_button.setSymbol(QgsFillSymbol.createSimple({"color": "0,0,255,255"}))
    assert c.features == () and c.undo_stack.count() == count


def test_opening_the_page_records_nothing(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = _dike(c)
    c.set_style(dike.id, RED)
    levee = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    count, before = c.undo_stack.count(), c.features
    calls = []
    set_style = c.set_style
    c.set_style = lambda *args: (calls.append(args), set_style(*args))
    dock.feature_view.rowOpened.emit(dike.id)
    dock.close_page()
    dock.feature_view.rowOpened.emit(levee.id)   # a different style, and the default look
    c.stylesChanged.emit()                       # reloads nothing: the button shows levee's look already
    assert c.undo_stack.count() == count and c.features == before and calls == []
    _model, nodes = _legend_nodes(c)
    nodes[1].setSymbol(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))   # the levee, from the Layers panel
    _settle()                                    # read back, and loaded onto the button by stylesChanged
    assert c.find(levee.id).style == RED and style_of(dock.properties.style_button.symbol()) == RED
    assert c.undo_stack.count() == count + 1 and calls == []   # loading the button must not commit


def test_style_button_follows_a_layers_panel_edit(tmp_path):
    _iface, c, dock, dike = _feature_page(tmp_path)
    _model, nodes = _legend_nodes(c)
    nodes[0].setSymbol(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))
    _settle()
    assert c.find(dike.id).style == RED and style_of(dock.properties.style_button.symbol()) == RED


def test_style_button_is_disabled_under_a_layer_style(tmp_path):
    _iface, c, dock, _dike_feature = _feature_page(tmp_path)
    page = dock.properties
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "0,255,0,255"})))
    _settle()
    assert not page.style_button.isEnabled() and page.style_button.toolTip() == STYLE_LAYER_TIP
    c.use_feature_styles()
    _settle()
    assert page.style_button.isEnabled() and page.style_button.toolTip() == STYLE_TIP


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


def _record_criticals(monkeypatch) -> list:
    """Every Critical log entry from here on: what a guarded slot that failed leaves behind."""
    logged = []
    monkeypatch.setattr(controller_module.QgsMessageLog, "logMessage",
                        lambda text, tag="", level=None, *a: logged.append(text)
                        if level == Qgis.MessageLevel.Critical else None)
    return logged


def _open_selector(dock):
    """Click the page's Style button: QGIS's symbol selector, which must open on the panel's own stack."""
    dock.properties.style_button.click()
    top = dock.stack.currentPanel()
    assert top.metaObject().className() == "QgsSymbolSelectorWidget" and top.dockMode()
    return sip.cast(top, QgsSymbolSelectorWidget)


def _live_edit(selector, colour) -> None:
    """What the selector does while the user edits: change its working symbol and say so."""
    selector.symbol().setColor(QColor(*colour))
    selector.widgetChanged.emit()


def test_style_button_opens_the_symbol_selector_on_the_panel(tmp_path, monkeypatch):
    logged = _record_criticals(monkeypatch)
    _iface, c, dock, dike = _feature_page(tmp_path)
    c.save_scenario(str(tmp_path / "work.gpkg"))
    count = c.undo_stack.count()
    selector = _open_selector(dock)
    _live_edit(selector, (255, 0, 0))
    _live_edit(selector, (0, 0, 255))
    style = c.find(dike.id).style
    assert style is not None and style == style_of(dock.properties.style_button.symbol())
    assert to_xml(from_xml(style)) == style and from_xml(style).color() == QColor(0, 0, 255)
    assert c.undo_stack.count() == count + 1 and c.is_dirty    # one undo step, and unsaved
    selector.acceptPanel()                                    # the stack's Back button
    _settle()
    assert dock.stack.currentPanel() is dock.properties_page
    assert c.find(dike.id).style == style and c.undo_stack.count() == count + 1
    assert dock.stack.findChild(QLabel, "mTitleText").text().strip() == dike.name
    assert logged == []


def test_closing_the_page_with_the_selector_open_returns_to_the_list(tmp_path, monkeypatch):
    logged = _record_criticals(monkeypatch)
    _iface, c, dock, dike = _feature_page(tmp_path)
    _open_selector(dock)
    dock.close_page()
    _settle()
    assert dock.stack.currentPanel() is dock.main_panel
    dock.feature_view.rowOpened.emit(dike.id)   # the page and its selector open again on a sound stack
    _open_selector(dock).acceptPanel()
    _settle()
    assert dock.stack.currentPanel() is dock.properties_page
    assert logged == []


def test_the_shown_feature_going_away_with_the_selector_open_returns_to_the_list(tmp_path, monkeypatch):
    logged = _record_criticals(monkeypatch)
    _iface, c, dock, dike = _feature_page(tmp_path)
    selector = _open_selector(dock)
    _live_edit(selector, (255, 0, 0))
    c.undo_stack.undo()                         # the style edit
    c.undo_stack.undo()                         # the drawing: the feature is gone
    _settle()
    assert c.features == () and dock.stack.currentPanel() is dock.main_panel
    assert logged == []


def test_ending_the_session_with_the_selector_open_returns_to_the_list(tmp_path, monkeypatch):
    logged = _record_criticals(monkeypatch)
    _iface, c, dock, _dike_feature = _feature_page(tmp_path)
    _open_selector(dock)
    c.close()
    _settle()
    assert dock.stack.currentPanel() is dock.main_panel and dock.views.currentIndex() == 0
    assert logged == []


def test_selecting_another_feature_closes_the_selector_first(tmp_path, monkeypatch):
    logged = _record_criticals(monkeypatch)
    _iface, c, dock, dike = _feature_page(tmp_path)
    levee = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    _open_selector(dock)
    dock.feature_view.select_id(levee.id)       # the page follows the selection
    _settle()
    assert dock.stack.currentPanel() is dock.properties_page and dock.properties.fid == levee.id
    assert c.find(dike.id).style is None and c.find(levee.id).style is None
    assert logged == []
