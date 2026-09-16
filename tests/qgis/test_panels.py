import pytest
from qgis.core import Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_layer, line_through, panel, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import UNSAVED_CHANGES
from terrain_sketch.gui.main_dock import VIEW_SESSION, VIEW_WELCOME, MainDock
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.selection import EDIT_ICON, METHOD_ICONS, Method
from terrain_sketch.gui.tool_gallery import ToolGallery


def test_the_panel_opens_on_a_welcome_view_and_switches_to_the_session(tmp_path):
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    assert dock.views.currentIndex() == VIEW_WELCOME
    layer = dem_layer(tmp_path)
    dock.dem_combo.setLayer(layer)
    dock.start_button.click()
    assert dock.views.currentIndex() == VIEW_SESSION
    assert layer.name() in dock.status_label.text()


def test_the_welcome_view_shows_the_raise_path_illustration(tmp_path):
    """spec §4: the raise_path illustration at 160×80, themed from the palette."""
    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    pixmap = dock.welcome_illustration.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert pixmap.size().width() == 160 and pixmap.size().height() == 80


def test_the_welcome_illustration_follows_a_theme_change(tmp_path):
    from qgis.PyQt.QtGui import QColor, QPalette

    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    before = dock.welcome_illustration.pixmap().toImage()
    palette = dock.welcome_illustration.palette()
    palette.setColor(QPalette.ColorRole.Mid, QColor("#ff00ff"))   # the terrain colour token
    dock.welcome_illustration.setPalette(palette)
    after = dock.welcome_illustration.pixmap().toImage()
    assert after != before


def test_the_dem_name_is_escaped_in_the_status_line(tmp_path):
    """The DEM name goes into a rich-text label alongside a real `<a href>` link; an unescaped
    ampersand (or `<`/`>`) in a layer name must not be read as markup."""
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    layer = dem_layer(tmp_path, name="A&B")
    dock.dem_combo.setLayer(layer)
    dock.start_button.click()
    assert "A&amp;B" in dock.status_label.text()


def test_the_status_line_follows_a_dem_rename(tmp_path):
    _iface, c, dock = panel(tmp_path)
    layer = c.project.mapLayer(c.dem_layer_id)
    layer.setName("Renamed DEM")
    assert "Renamed DEM" in dock.status_label.text()


def test_every_page_the_panel_opens_is_in_dock_mode(tmp_path):
    """A panel that is not in dock mode opens a modal dialog, which never returns offscreen."""
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    assert dock.main_panel.dockMode() and dock.stack.currentPanel().dockMode()


def test_the_scenario_actions_live_behind_one_menu_button(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    assert [a.text() for a in dock.scenario_button.menu().actions()] == [
        "New scenario", "Open scenario…", "Save scenario", "Save scenario as…"]


def test_changing_the_dem_goes_back_to_the_welcome_view(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dock.status_label.linkActivated.emit("change")
    assert dock.views.currentIndex() == VIEW_WELCOME and c.has_dem     # the session keeps running until Start


def test_changing_the_dem_stops_a_drawing_in_progress(tmp_path):
    """Change… used to leave a drawing running on the map behind a view that no longer shows it; a
    finished drawing would then have opened the new feature's page on top of the welcome view."""
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert dock.draw_tool is not None
    dock.status_label.linkActivated.emit("change")
    assert dock.draw_tool is None and dock.views.currentIndex() == VIEW_WELCOME


def test_keep_sketching_returns_to_the_session_without_touching_it(tmp_path):
    """Change… used to be the only way back to a live session, and the only route from the welcome
    view was Start — which discards every feature just to return to the same session."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.status_label.linkActivated.emit("change")
    assert dock.views.currentIndex() == VIEW_WELCOME and not dock.keep_sketching_button.isHidden()
    dock.keep_sketching_button.click()
    assert dock.views.currentIndex() == VIEW_SESSION
    assert c.has_dem and [f.id for f in c.features] == [dike.id]      # untouched


def test_keep_sketching_is_hidden_without_a_session(tmp_path):
    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    assert dock.keep_sketching_button.isHidden()


def test_changing_the_dem_with_unsaved_work_asks_first_and_can_be_cancelled(tmp_path):
    """The dirty branch of Change…: `_keep_unsaved_work` backing out must leave the session view
    showing, exactly as it does when Start is refused the same way."""
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or None     # cancel
    dock.status_label.linkActivated.emit("change")
    assert asked == [UNSAVED_CHANGES]
    assert dock.views.currentIndex() == VIEW_SESSION and len(c.features) == 1


def test_ending_the_session_closes_any_open_page(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page
    c.close()
    assert dock.stack.currentPanel() is dock.main_panel and dock.views.currentIndex() == VIEW_WELCOME


def test_a_scenario_action_in_the_same_session_does_not_close_the_open_page(tmp_path):
    """`sessionChanged` also fires from new_scenario/save_scenario/open_scenario with `has_dem`
    still true; only a real transition (a session starting or ending) should close the open page."""
    _iface, c, dock = panel(tmp_path)
    dock.new_button.click()
    assert dock.stack.currentPanel() is dock.gallery_page
    dock.new_scenario_action.trigger()
    assert c.has_dem and dock.stack.currentPanel() is dock.gallery_page
    assert dock.views.currentIndex() == VIEW_SESSION


def test_a_page_survives_being_closed_and_reopened(tmp_path):
    """QgsPanelWidgetStack deletes a closed panel by default (verified by probe), and `addWidget`
    reparented `dock.properties` into it — so unless the content is taken out before the wrapper
    dies, closing a page destroys `properties` right along with it once a real event loop (not
    merely `processEvents`, which does not flush a deferred delete) runs. `spin_event_loop` gives
    the deferred delete an actual chance to fire, which is what a real user's session does between
    two clicks."""
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)          # opens the properties page
    dock.feature_view.clearSelection()            # closes it
    spin_event_loop(50)                            # let the closed page's deferred delete actually run
    dock.feature_view.select_id(dike.id)          # reopening must not touch a deleted `properties` widget
    assert dock.stack.currentPanel() is dock.properties_page
    assert dock.properties.amount.value() == pytest.approx(dike.amount)   # still a live, working widget
    assert dock.properties.isVisible()             # not left invisible by release_content's old hide()


def test_undo_keys_on_the_properties_fields_survive_a_close_and_reopen(tmp_path):
    """The per-spin `UndoKeys` filters (`spin_undo_keys`) are installed once, directly on the spin
    boxes inside `dock.properties` — they must keep working after the page they sit on has been
    closed and reopened, exactly like the widget itself."""
    from qgis.PyQt.QtGui import QKeySequence
    from qgis.PyQt.QtTest import QTest
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    dock.feature_view.clearSelection()
    spin_event_loop(50)                            # let the first close's deferred delete run
    dock.feature_view.select_id(dike.id)
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    spin.selectAll()
    QTest.keyClicks(spin, "2")                     # typed, not yet committed
    assert spin.lineEdit().text() == "2 m"
    QTest.keySequence(spin, QKeySequence(QKeySequence.StandardKey.Undo))
    spin_event_loop(10)
    assert spin.lineEdit().text() == "1.00 m"      # the field's own undo still claims Ctrl+Z


def test_the_gallery_survives_new_feature_draw_and_new_feature_again(tmp_path):
    """The exact sequence the reviewer's repro used: New feature (opens the gallery page), draw a
    feature (closes it, opens the feature's properties page), New feature again (closes the
    properties page, reopens the gallery page) — `dock.gallery` must still be a live widget, not one
    whose wrapper's deleteLater already took it down."""
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    dock.draw_tool.finished.emit(line_through(5, 20, 34, 20))
    assert dock.stack.currentPanel() is dock.properties_page
    spin_event_loop(50)                            # let the New feature page's deferred delete run
    dock.new_button.click()                        # must not touch the deleted-by-then gallery page
    assert dock.stack.currentPanel() is dock.gallery_page
    assert dock.gallery.tool_list.count() == len(Tool)             # still a live, working widget
    assert dock.gallery.isVisible()                # not left invisible by release_content's old hide()


def test_the_stacks_own_back_button_releases_the_page_before_reopening(tmp_path):
    """`QgsPanelWidgetStack` owns a visible "Go back" button (`mBackButton`) that calls
    `acceptPanel()` directly — never through `MainDock.close_page()`. `_PagePanel` must release its
    content from `panelAccepted` itself, or this exit path (the one a real user actually clicks)
    destroys `gallery` right along with its wrapper."""
    from qgis.PyQt.QtWidgets import QApplication, QToolButton
    from qgis_helpers import spin_event_loop

    _iface, _c, dock = panel(tmp_path)
    dock.show()
    dock.new_button.click()
    QApplication.processEvents()
    back = dock.stack.findChild(QToolButton, "mBackButton")
    assert back is not None and back.isVisible()
    back.click()
    assert dock.stack.currentPanel() is dock.main_panel     # the button really did close the page
    spin_event_loop(50)                                       # let the deferred delete actually run
    dock.new_button.click()                                   # must not touch a deleted `gallery`
    assert dock.stack.currentPanel() is dock.gallery_page
    assert dock.gallery.isVisible()                # not left invisible by release_content's old hide()
    assert dock.gallery.tool_list.count() == len(Tool)         # still a live, working widget


def test_escape_releases_the_page_before_reopening(tmp_path):
    """Escape is `QgsPanelWidgetStack`'s own shortcut for `acceptPanel()`, bypassing `close_page()`
    exactly like the back button."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    QApplication.processEvents()
    assert dock.stack.currentPanel() is dock.properties_page
    dock.stack.setFocus()
    QApplication.processEvents()
    QTest.keyClick(dock.stack, Qt.Key.Key_Escape)
    assert dock.stack.currentPanel() is dock.main_panel     # Escape really did close the page
    spin_event_loop(50)                                       # let the deferred delete actually run
    # select_id on the already-selected row is a no-op (Qt does not re-emit selectionChanged for a
    # selection that does not change): clear first, so reselecting genuinely reopens the page.
    dock.feature_view.clearSelection()
    dock.feature_view.select_id(dike.id)                      # must not touch a deleted `properties`
    assert dock.stack.currentPanel() is dock.properties_page
    assert dock.properties.isVisible()             # not left invisible by release_content's old hide()
    assert dock.properties.amount.value() == pytest.approx(dike.amount)   # still a live, working widget


def test_gallery_offers_only_the_shapes_and_methods_a_tool_supports():
    gallery = ToolGallery()
    gallery.select_tool(Tool.RAISE_PATH)
    assert gallery.line_mode.isEnabled() and not gallery.area_mode.isEnabled()
    assert gallery.selected_mode() is Mode.PATH
    assert gallery.method_buttons[Method.FREEHAND].isEnabled()
    assert not gallery.method_buttons[Method.BRUSH].isEnabled() and not gallery.brush_spin.isEnabled()
    gallery.select_tool(Tool.LOWER_FLAT)
    gallery.select_mode(Mode.AREA)
    assert gallery.method_buttons[Method.BRUSH].isEnabled() and gallery.brush_spin.isEnabled()
    requests = []
    gallery.drawRequested.connect(lambda tool, mode, method: requests.append((tool, mode, method)))
    gallery.method_buttons[Method.FREEHAND].click()
    assert requests == [(Tool.LOWER_FLAT, Mode.AREA, Method.FREEHAND)]
    gallery.method_buttons[Method.LAYER].click()
    assert not gallery.layer_source.isHidden() and len(requests) == 1  # the layer form asks first


def test_layer_form_reports_the_chosen_layer(tmp_path):
    gallery = ToolGallery()
    gallery.select_tool(Tool.RAISE_PATH)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    gallery.layer_source.layer_combo.setLayer(layer)
    gallery.layer_source.selected_only.setChecked(True)
    asked = []
    gallery.layerRequested.connect(lambda tool, mode, lyr, only: asked.append((tool, mode, lyr.name(), only)))
    gallery.layer_source.use_button.click()
    assert asked == [(Tool.RAISE_PATH, Mode.PATH, "Planned dikes", True)]


def test_properties_show_the_tool_fields_and_apply_changes(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert all(w.toolTip() for w in (page.amount, page.width, page.slope, page.reach, page.slope_position))
    assert page.amount_label.text() == "Height above the path"
    assert page.form.isRowVisible(page.width) and page.form.isRowVisible(page.slope)
    assert not page.form.isRowVisible(page.slope_position)
    page.amount.setValue(2.5)
    assert c.feature(dike.id).amount == 2.5 and sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    page.show_feature(pond.id)
    assert page.amount_label.text() == "Depth below the lowest point" and not page.form.isRowVisible(page.width)
    assert page.form.isRowVisible(page.slope_position) and page.slope_position.currentData() is True
    page.pixel_mode.setCurrentIndex(page.pixel_mode.findData(PixelMode.ALL_TOUCHED.value))
    assert c.feature(pond.id).pixel_mode is PixelMode.ALL_TOUCHED


def test_every_panel_icon_exists_in_the_qgis_theme():
    """getThemeIcon returns a null icon for an unknown name, and the button then renders blank."""
    from terrain_sketch.gui.main_dock import PROFILES_ICON
    for name in (*METHOD_ICONS.values(), EDIT_ICON, PROFILES_ICON):
        assert not QgsApplication.getThemeIcon(name).isNull(), name


def test_the_brush_radius_is_labelled_with_the_units_it_is_really_in():
    gallery = ToolGallery()
    gallery.set_radius_units(QgsCoordinateReferenceSystem("EPSG:25832").mapUnits())
    assert gallery.brush_spin.suffix() == " m"
    gallery.set_radius_units(QgsCoordinateReferenceSystem("EPSG:4326").mapUnits())
    assert gallery.brush_spin.suffix() == " degrees"
    gallery.set_radius_units(Qgis.DistanceUnit.Unknown)
    assert gallery.brush_spin.suffix() == " map units"
