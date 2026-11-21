import pytest
from qgis.core import Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsProject
from qgis.PyQt.QtWidgets import QListView

from qgis_helpers import UTM, dem_layer, fake_iface, line_layer, line_through, panel, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import UNSAVED_CHANGES
from terrain_sketch.gui.main_dock import VIEW_SESSION, VIEW_WELCOME, MainDock
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.selection import EDIT_HINT, EDIT_ICON, METHOD_ICONS, ZOOM_ICON, Method
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
    """A panel that is not in dock mode opens a modal dialog, which never returns offscreen. The
    panel opens two pages (spec §11): New feature, and a feature's own page."""
    _iface, c, dock = panel(tmp_path)
    assert dock.main_panel.dockMode()
    dock.new_button.click()
    assert dock.stack.currentPanel() is dock.gallery_page and dock.gallery_page.dockMode()
    dock.close_page()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page and dock.properties_page.dockMode()


def test_the_status_line_keeps_the_styles_normal_margin_from_the_panel_edge(tmp_path):
    from qgis.PyQt.QtCore import QPoint

    _iface, _c, dock = panel(tmp_path)
    dock.resize(360, 650)
    dock.show()
    status = dock.status_label
    left = status.mapTo(dock.views, QPoint(0, 0)).x()
    right = dock.views.width() - (left + status.width())
    assert left > 0 and right > 0, (left, right)


def test_the_scenario_actions_live_behind_one_menu_button(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    assert [a.text() for a in dock.scenario_button.menu().actions()] == [
        "New scenario", "Open scenario…", "Save scenario", "Save scenario as…"]


def test_changing_the_dem_goes_back_to_the_welcome_view(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dock.status_label.linkActivated.emit("change")
    assert dock.views.currentIndex() == VIEW_WELCOME and c.has_dem     # the session keeps running until Start


def test_changing_the_dem_stops_a_drawing_in_progress(tmp_path):
    """A drawing left running behind the welcome view runs on the map behind a view that does not
    show it, and finishing it would open the new feature's page on top of the welcome view."""
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert dock.draw_tool is not None
    dock.status_label.linkActivated.emit("change")
    assert dock.draw_tool is None and dock.views.currentIndex() == VIEW_WELCOME


def test_keep_sketching_returns_to_the_session_without_touching_it(tmp_path):
    """Keep sketching is the way back to a live session from Change…: Start would replace the
    session, discarding every feature just to return to the same one."""
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


def test_changing_the_dem_with_unsaved_work_asks_nothing_and_keeps_the_session(tmp_path):
    """spec §5.3: Change… only shows the welcome view. Nothing is discarded there, so there is
    nothing to ask; Keep sketching returns to the same session and its unsaved work."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or None     # cancel, if asked
    dock.status_label.linkActivated.emit("change")
    assert asked == []
    assert dock.views.currentIndex() == VIEW_WELCOME and c.has_dem and c.is_dirty
    dock.keep_sketching_button.click()
    assert dock.views.currentIndex() == VIEW_SESSION and [f.id for f in c.features] == [dike.id]
    assert asked == []


def test_change_then_start_asks_about_unsaved_work_exactly_once(tmp_path):
    """The unsaved-work question belongs to Start, which is what replaces the session (spec §5.3)."""
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or False     # Discard
    dock.status_label.linkActivated.emit("change")
    dock.start_button.click()
    assert asked == [UNSAVED_CHANGES]
    assert c.has_dem and c.features == () and dock.views.currentIndex() == VIEW_SESSION


def test_a_section_line_started_behind_the_welcome_view_brings_the_session_back(tmp_path):
    """The Profiles dock stays usable while the welcome view shows (the session keeps running);
    the line being drawn, and its hint under the toolbar, must be on screen."""
    from terrain_sketch.gui.help_texts import SECTION_LINE_HINT
    from terrain_sketch.gui.profile_dock import ProfileDock

    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.show()
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.select_id(pond.id)
    dock.status_label.linkActivated.emit("change")
    assert dock.views.currentIndex() == VIEW_WELCOME

    profiles.draw_section.click()
    assert dock.draw_tool is not None
    assert dock.views.currentIndex() == VIEW_SESSION
    assert dock.session_hint.isVisible() and dock.session_hint.text() == SECTION_LINE_HINT


def test_ending_the_session_closes_any_open_page(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page
    c.close()
    assert dock.stack.currentPanel() is dock.main_panel and dock.views.currentIndex() == VIEW_WELCOME


def test_the_page_closes_when_its_feature_is_deleted_elsewhere(tmp_path):
    """spec §9: a feature deleted from outside its own page (here, straight through the controller
    — e.g. the layer panel's own delete, or anything else that is not the page's own Delete button)
    still closes the page it is shown on."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page
    c.delete_feature(dike.id)
    assert dock.stack.currentPanel() is dock.main_panel


def test_undo_that_removes_the_open_feature_closes_its_page(tmp_path):
    """spec §9: a feature that disappears through undo (here, undoing the add that created it)
    closes its own open page exactly as an outright delete does."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page
    c.undo_stack.undo()                       # undoes the add
    assert dock.stack.currentPanel() is dock.main_panel


def test_going_back_keeps_the_feature_selected_and_highlighted(tmp_path):
    """spec §9: Back from any page returns to the list with the feature still selected and still
    highlighted on the map — `properties.acceptPanel()` reaches `close_page` the same way the
    stack's own Back button and Escape do (see `PropertiesPage`'s own Escape handling)."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.highlight.numberOfVertices() > 0
    dock.properties.acceptPanel()
    assert dock.stack.currentPanel() is dock.main_panel
    assert dock.feature_view.selected_id() == dike.id
    assert dock.highlight.numberOfVertices() > 0


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
    dock.feature_view.rowOpened.emit(dike.id)     # opens the properties page
    dock.feature_view.clearSelection()            # closes it
    spin_event_loop(50)                            # let the closed page's deferred delete actually run
    dock.feature_view.rowOpened.emit(dike.id)     # reopening must not touch a deleted `properties` widget
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
    dock.feature_view.rowOpened.emit(dike.id)
    dock.feature_view.clearSelection()
    spin_event_loop(50)                            # let the first close's deferred delete run
    dock.feature_view.rowOpened.emit(dike.id)
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
    """New feature (opens the gallery page), draw a
    feature (closes it, opens the feature's properties page), New feature again (closes the
    properties page, reopens the gallery page) — `dock.gallery` is one persistent instance for the
    dock's whole life (a fresh `_PagePanel` wraps it on every open), so it must still be the SAME
    live widget, not a new one and not one a wrapper's deleteLater took down."""
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    gallery = dock.gallery
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    dock.draw_tool.finished.emit(line_through(5, 20, 34, 20))
    assert dock.stack.currentPanel() is dock.properties_page
    spin_event_loop(50)                            # let the New feature page's deferred delete run
    dock.new_button.click()                        # must not touch the deleted-by-then gallery page
    assert dock.stack.currentPanel() is dock.gallery_page
    assert dock.gallery is gallery                 # the same instance, not a new one
    assert dock.gallery.tool_list.count() == len(Tool)             # still a live, working widget
    assert dock.gallery.isVisible()                # not left invisible by release_content's old hide()


def test_the_stacks_own_back_button_releases_the_page_before_reopening(tmp_path):
    """`QgsPanelWidgetStack` owns a visible "Go back" button (`mBackButton`) that calls
    `acceptPanel()` directly — never through `MainDock.close_page()`. `_PagePanel` must release its
    content from `panelAccepted` itself, or this exit path (the one a real user actually clicks)
    destroys `gallery` right along with its wrapper — and since `gallery` is one persistent instance
    reused across every open, reopening it afterwards must find that very same object, still live."""
    from qgis.PyQt.QtWidgets import QApplication, QToolButton
    from qgis_helpers import spin_event_loop

    _iface, _c, dock = panel(tmp_path)
    dock.show()
    gallery = dock.gallery
    dock.new_button.click()
    QApplication.processEvents()
    back = dock.stack.findChild(QToolButton, "mBackButton")
    assert back is not None and back.isVisible()
    back.click()
    assert dock.stack.currentPanel() is dock.main_panel     # the button really did close the page
    spin_event_loop(50)                                       # let the deferred delete actually run
    dock.new_button.click()                                   # must not touch a deleted `gallery`
    assert dock.stack.currentPanel() is dock.gallery_page
    assert dock.gallery is gallery                 # the same instance, not a new one
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
    dock.feature_view.rowOpened.emit(dike.id)
    QApplication.processEvents()
    assert dock.stack.currentPanel() is dock.properties_page
    dock.stack.setFocus()
    QApplication.processEvents()
    QTest.keyClick(dock.stack, Qt.Key.Key_Escape)
    assert dock.stack.currentPanel() is dock.main_panel     # Escape really did close the page
    spin_event_loop(50)                                       # let the deferred delete actually run
    # The row stays selected after Escape closes the page (spec §9); rowOpened must still reopen
    # it even though reselecting it fires no selectionChanged at all (see
    # test_reopening_an_already_selected_row_reaches_its_page below for the Back-button/click version).
    dock.feature_view.rowOpened.emit(dike.id)                 # must not touch a deleted `properties`
    assert dock.stack.currentPanel() is dock.properties_page
    assert dock.properties.isVisible()             # not left invisible by release_content's old hide()
    assert dock.properties.amount.value() == pytest.approx(dike.amount)   # still a live, working widget


def test_escape_inside_the_gallery_closes_the_new_feature_page(tmp_path):
    """`ToolGallery` is itself a `QgsPanelWidget` (`dockMode` True): its own inherited
    `keyPressEvent` answers Escape by calling its own `acceptPanel()` — emitting `gallery`'s own
    `panelAccepted`, not the `_PagePanel` wrapper's — before the key press ever reaches the wrapper
    that is actually on the stack. Unlike `test_escape_releases_the_page_before_reopening` (which
    sends Escape to the stack itself, where focus is not inside either page's own widgets), this
    sends Escape to a widget *inside* the gallery — the tool tiles — to reproduce that exact path,
    and only passes because `gallery.panelAccepted` is forwarded to `close_page`
    (`MainDock.__init__`); removing that connection makes it fail. `properties` has the identical
    hazard — see `test_escape_inside_the_feature_page_closes_it` — fixed the same way."""
    from qgis.PyQt import sip
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication
    from qgis_helpers import spin_event_loop

    _iface, _c, dock = panel(tmp_path)
    dock.show()
    gallery = dock.gallery
    dock.new_button.click()
    assert dock.stack.currentPanel() is dock.gallery_page
    dock.gallery.tool_list.setFocus()
    QApplication.processEvents()
    QTest.keyClick(dock.gallery.tool_list, Qt.Key.Key_Escape)
    assert dock.stack.currentPanel() is dock.main_panel     # Escape really did close the page
    spin_event_loop(50)                                       # let the deferred delete actually run
    assert dock.gallery is gallery and not sip.isdeleted(gallery)   # still the same, live instance
    dock.new_button.click()                                   # must not touch a deleted `gallery`
    assert dock.stack.currentPanel() is dock.gallery_page
    assert dock.gallery.isVisible()


def test_the_tools_are_shown_as_tiles(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    gallery = dock.gallery
    assert gallery.tool_list.viewMode() == QListView.ViewMode.IconMode
    assert gallery.tool_list.count() == len(Tool)
    assert not gallery.tool_list.item(0).icon().isNull()


def test_the_brush_radius_is_only_there_when_the_brush_is(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.ADD)   # a tool that reaches both shapes, unlike RAISE_PATH
    dock.gallery.select_mode(Mode.PATH)
    assert not dock.gallery.brush_spin.isVisibleTo(dock.gallery)     # no brush on a line
    dock.gallery.select_mode(Mode.AREA)
    assert dock.gallery.brush_spin.isVisibleTo(dock.gallery)


def test_shape_is_a_segmented_pair_that_disables_what_the_tool_cannot_do(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)   # a tool that supports only one shape
    assert dock.gallery.line_mode.isCheckable() and dock.gallery.area_mode.isCheckable()
    assert dock.gallery.line_mode.isEnabled() and not dock.gallery.area_mode.isEnabled()
    assert dock.gallery.mode_group.checkedButton() is dock.gallery.line_mode


def test_the_shape_buttons_look_like_buttons_in_either_state(tmp_path):
    """With `autoRaise` on, the unchecked one of the pair has no visible border at all — reading as
    plain text next to the checked one's highlight, rather than as a pair of buttons."""
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    assert not dock.gallery.line_mode.autoRaise() and not dock.gallery.area_mode.autoRaise()


def test_the_tile_grid_is_sized_to_its_content_not_stretched(tmp_path):
    """With a `QListWidget`'s default vertical size policy, `Expanding`, the tile view stretches to
    fill the whole New feature page, crowding the summary, Shape and Where controls into whatever
    space is left at the bottom of a tall dock. Sized to content
    (`_ToolTileList.heightForWidth`) instead: all seven tiles show without a scrollbar, and the
    Where buttons sit well up the page rather than pushed to its bottom."""
    from qgis.PyQt.QtWidgets import QApplication
    from qgis_helpers import spin_event_loop

    _iface, _c, dock = panel(tmp_path)
    dock.resize(360, 900)
    dock.show()
    dock.new_button.click()
    QApplication.processEvents()
    spin_event_loop(20)

    gallery = dock.gallery
    assert gallery.tool_list.count() == len(Tool) == 7
    where_button = gallery.method_buttons[Method.CLICK]
    top = where_button.mapTo(dock, where_button.rect().topLeft()).y()
    assert 0 < top < dock.height() * 2 / 3   # well up the page, not crammed at the bottom


def test_the_tile_grid_reports_a_height_that_keeps_every_tile_reachable(tmp_path):
    """`heightForWidth` must count columns from the viewport the icon grid actually wraps inside,
    not the outer WIDGET width, and must not treat an exact multiple of the grid width as enough
    to fit another column — either mistake undercounts the rows some widths need (232-234,
    348-350 and 464-466 px reproduce it for seven tiles at this grid size — the sweep starts at
    200, not 240, specifically to also cover the first of those). The list then gets too little
    height from the page's layout, the last tile falls below the viewport, and
    `ScrollBarAlwaysOff` leaves it permanently unreachable — silently, since nothing
    about the list looks wrong until you count the tiles.

    `verticalScrollBar().isVisible()` cannot catch this: with the scrollbar forced off, it is
    always `False`. This instead checks the view's own layout of the last tile directly — at every
    width from 200 to 520 px, resizing the list itself to `heightForWidth`'s own answer (exactly
    what `QVBoxLayout` would give it in the page) and asserting the tile the view actually lays out
    stays fully inside the viewport."""
    from qgis.PyQt.QtWidgets import QApplication

    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    tiles = dock.gallery.tool_list
    tiles.setParent(None)   # freed from the page's own layout, which would otherwise re-assert its geometry
    tiles.show()

    failures = []
    for width in range(200, 521):
        tiles.resize(width, tiles.heightForWidth(width))
        QApplication.processEvents()
        last = tiles.visualRect(tiles.model().index(tiles.count() - 1, 0))
        if last.isNull() or not tiles.viewport().rect().contains(last):
            failures.append(width)
    assert not failures, f"the last tile is clipped at width(s) {failures}"


def test_the_new_feature_pages_hint_is_on_screen_while_drawing_on_a_short_dock(tmp_path):
    """The hint sits at the top of the page, above the tiles, so a dock too short for the whole
    page still shows what to do while a drawing runs."""
    from qgis.PyQt.QtCore import QPoint, QRect
    from qgis.PyQt.QtWidgets import QApplication

    _iface, _c, dock = panel(tmp_path)
    dock.resize(360, 650)
    dock.show()
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    QApplication.processEvents()
    assert dock.draw_tool is not None

    hint, page = dock.gallery.hint, dock.gallery_page
    assert hint.isVisible()
    visible = QRect(page.mapTo(dock, QPoint(0, 0)), page.size()).intersected(dock.rect())
    shown = QRect(hint.mapTo(dock, QPoint(0, 0)), hint.size())
    assert visible.contains(shown), (shown, visible)
    assert shown.bottom() < dock.gallery.tool_list.mapTo(dock, QPoint(0, 0)).y()     # above the tiles


def test_the_new_feature_page_keeps_the_styles_normal_margin_from_the_panel_edge(tmp_path):
    """With zero content margins the page's content would touch the panel edge, unlike QGIS's own
    panels."""
    _iface, _c, dock = panel(tmp_path)
    dock.show()
    dock.new_button.click()
    left = dock.gallery.tool_list.mapTo(dock, dock.gallery.tool_list.rect().topLeft()).x()
    assert left > 0


def test_drawing_a_feature_closes_the_new_feature_page(tmp_path):
    """Drawing goes through the ordinary path — `select_id` selects the new feature, which opens
    its properties page, which `open_page` replaces the New feature page with — so nothing New-
    feature-specific has to close it (a close on every added feature would also fire, wrongly, on
    an unrelated scenario reset or an undo)."""
    _iface, c, dock = panel(tmp_path)
    dock.new_button.click()
    assert dock.stack.currentPanel() is dock.gallery_page   # the page really was open first
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    dock.draw_tool.finished.emit(line_through(5, 20, 34, 20))
    assert dock.stack.currentPanel() is dock.properties_page


def test_reopening_new_feature_does_not_build_a_new_gallery(tmp_path):
    """dock.gallery is one persistent instance for the dock's whole life (a fresh `_PagePanel`
    wraps it on every open) — repeated opens must not construct a fresh `ToolGallery` each time,
    which would leak one gallery per click and reset every choice on reopen."""
    _iface, _c, dock = panel(tmp_path)
    gallery = dock.gallery
    for _ in range(3):
        dock.new_button.click()
        assert dock.gallery is gallery
        dock.close_page()
    assert dock.gallery is gallery


def test_the_gallery_keeps_its_state_across_close_and_reopen(tmp_path):
    """Closing and reopening the New feature page must not reset the tool, shape or brush radius
    the user picked — only meaningful because `dock.gallery` is the same instance every time
    (see `test_reopening_new_feature_does_not_build_a_new_gallery`)."""
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.set_brush_radius(17.0)
    dock.close_page()
    dock.new_button.click()
    assert dock.gallery.selected_tool() is Tool.LOWER_FLAT
    assert dock.gallery.selected_mode() is Mode.AREA
    assert dock.gallery.brush_radius() == pytest.approx(17.0)


def test_a_brush_strokes_radius_change_updates_the_one_gallery(tmp_path):
    """[ and ] (or Ctrl+wheel) change the brush radius while painting; `BrushTool.radiusChanged` is
    wired to `dock.gallery.set_brush_radius` — with one persistent gallery this always lands on the
    spin box the user can see, not on a spin box belonging to some other, already-replaced page."""
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    dock.draw_tool.radiusChanged.emit(9.0)
    assert dock.gallery.brush_radius() == pytest.approx(9.0)


def test_pressing_back_while_drawing_stops_the_map_tool(tmp_path):
    """Spec §6.6: "Pressing back (or Escape on the page) stops a drawing that is still running and
    returns to the list." (Esc-cancelling a drawing on the map itself is a different case — it keeps
    the New feature page open so the user can try again — and is unaffected here: nothing in this
    test presses Escape on the map or the canvas.) Closing the New feature page via the stack's own
    Back button while its drawing is still running must stop that drawing, not leave it running on
    the map behind a page that no longer shows its hint or has a Finish/Cancel control for it."""
    from qgis.PyQt.QtWidgets import QApplication, QToolButton
    from qgis_helpers import spin_event_loop

    _iface, _c, dock = panel(tmp_path)
    dock.show()
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert dock.draw_tool is not None
    QApplication.processEvents()
    back = dock.stack.findChild(QToolButton, "mBackButton")
    back.click()
    spin_event_loop(50)                              # let the deferred delete actually run
    assert dock.draw_tool is None
    assert dock.stack.currentPanel() is dock.main_panel


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
    for name in (*METHOD_ICONS.values(), EDIT_ICON, ZOOM_ICON, PROFILES_ICON):
        assert not QgsApplication.getThemeIcon(name).isNull(), name


def test_the_brush_radius_is_labelled_with_the_units_it_is_really_in():
    gallery = ToolGallery()
    gallery.set_radius_units(QgsCoordinateReferenceSystem("EPSG:25832").mapUnits())
    assert gallery.brush_spin.suffix() == " m"
    gallery.set_radius_units(QgsCoordinateReferenceSystem("EPSG:4326").mapUnits())
    assert gallery.brush_spin.suffix() == " degrees"
    gallery.set_radius_units(Qgis.DistanceUnit.Unknown)
    assert gallery.brush_spin.suffix() == " map units"


# --- The feature page -----------------------------------------------------------------------


def test_opening_a_feature_shows_its_page_with_name_and_volume(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    page = dock.properties
    # `page` (dock.properties) is the single, persistent feature-page instance (like dock.gallery);
    # it is never pushed onto the stack directly (see `_PagePanel` in main_dock.py — pushing the same
    # `QgsPanelWidget` instance twice over the dock's life corrupts the stack, verified by probe), so
    # what the stack actually shows is `dock.properties_page`, the fresh wrapper `open_page` built
    # for this open — the same pattern every other test in this file uses for `dock.gallery_page`.
    assert dock.stack.currentPanel() is dock.properties_page and page.panelTitle() == dike.name
    assert page.name_edit.text() == dike.name and "Raise path" in page.header_summary.text()
    assert "m³" in page.header_summary.text()


def test_the_feature_page_keeps_the_styles_normal_margin_from_the_panel_edge(tmp_path):
    """With zero content margins the page's fields would touch the panel edge, unlike QGIS's own
    panels."""
    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    label = dock.properties.amount_label
    assert label.mapTo(dock, label.rect().topLeft()).x() > 0


def test_renaming_in_the_header_is_undoable(tmp_path):
    """Real typing (`QTest.keyClicks` + Return), not `setText` + a bare `editingFinished.emit()`:
    only real typing sets `isModified()`, which is what the "still typing" guards elsewhere on this
    page (and `_commit_rename` itself) actually react to."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.name_edit.setFocus()
    spin_event_loop(10)
    dock.properties.name_edit.selectAll()
    QTest.keyClicks(dock.properties.name_edit, "Dike north")
    assert dock.properties.name_edit.isModified()
    QTest.keyClick(dock.properties.name_edit, Qt.Key.Key_Return)
    assert c.feature(dike.id).name == "Dike north"
    c.undo_stack.undo()
    assert c.feature(dike.id).name == dike.name and dock.properties.name_edit.text() == dike.name


def test_deleting_from_the_page_goes_back_to_the_list(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.delete_button.click()
    assert dock.stack.currentPanel() is dock.main_panel and c.features == ()


def test_pixels_to_change_sits_under_advanced_and_starts_collapsed(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    page = dock.properties
    assert page.advanced.isCollapsed() and page.pixel_mode.parent() is page.advanced
    assert page.volumes.isCollapsed() and page.about.isCollapsed()


def test_undo_that_restores_a_deleted_feature_does_not_open_a_page(tmp_path):
    """spec §5.2, §9: selection alone never opens a *closed* page. `dike` stays selected the whole
    time (its own page was closed with Back) while `pond` is deleted and the delete undone — the
    list resets twice, which reselects `dike` through `FeatureListView`'s own remember/restore (a
    real `selectionChanged` fires, confirmed by probe) even though nothing about `dike` changed.
    `_selection_changed` only ever retargets or closes a page that is *already* open."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.close_page()                                     # the row stays selected, the page does not
    assert dock.stack.currentPanel() is dock.main_panel
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    c.delete_feature(pond.id)
    dock.undo_button.click()                               # restores pond; the list resets, reselecting dike
    assert c.find(pond.id) is not None
    assert dock.stack.currentPanel() is dock.main_panel     # restoring it must not reopen dike's page


def test_renaming_in_the_list_does_not_reach_a_closed_page(tmp_path):
    """A plain rename never fires `selectionChanged` at all — `FeatureListModel._sync` only emits
    `dataChanged` when the id list itself is unchanged — so on its own it can never open a closed
    page, whatever `_selection_changed`'s guard does or does not check (a version of this test that
    only renamed `dike` and then asserted the page stayed closed could not fail no matter how that
    guard was written). What genuinely drives a *selected, unchanged* row through
    `selectionChanged` again is a model reset somewhere else in the list: `pond`'s deletion and its
    undo (spec §9's "a model reset, undo") each reset the model while `dike` — renamed here through
    the list in between, exactly as a user would — stays selected throughout, and is reselected by
    `FeatureListView`'s own remember/restore every time (confirmed by probe to fire a genuine
    `selectionChanged`, even though `dike` itself never left the list). Its page must stay closed
    regardless."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.close_page()                                      # the row stays selected, the page does not
    dock.model.setData(dock.model.index(dock.model.row_of(dike.id)), "Dike north")
    assert c.feature(dike.id).name == "Dike north"
    assert dock.stack.currentPanel() is dock.main_panel
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    c.delete_feature(pond.id)
    dock.undo_button.click()                               # restores pond; the model resets, reselecting dike
    assert c.find(pond.id) is not None
    assert dock.stack.currentPanel() is dock.main_panel


def test_reopening_an_already_selected_row_reaches_its_page(tmp_path):
    """After Back closes the feature page, the row stays selected (spec §9) — and a click on an
    already-selected row fires no `selectionChanged` at all (Qt does not re-emit for a selection
    that does not change). Pages open from `FeatureListView.rowOpened`, not `selectionChanged`, so
    the row can still be reopened; this reproduces the real path, a click on the view's own
    viewport, not a direct signal emit."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication, QToolButton
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    QApplication.processEvents()
    assert dock.stack.currentPanel() is dock.properties_page
    back = dock.stack.findChild(QToolButton, "mBackButton")
    back.click()
    assert dock.stack.currentPanel() is dock.main_panel
    spin_event_loop(50)                                      # let the deferred delete actually run
    assert dock.feature_view.selected_id() == dike.id         # the row really did stay selected
    position = dock.feature_view.visualRect(dock.model.index(0)).center()
    QTest.mouseClick(dock.feature_view.viewport(), Qt.MouseButton.LeftButton, pos=position)
    assert dock.stack.currentPanel() is dock.properties_page   # the same click reopens the page
    assert dock.properties.isVisible()


def test_the_edit_hint_shows_on_the_feature_page_while_it_is_open(tmp_path):
    """spec §6 item 6: EDIT_HINT belongs to the feature page, not the New feature page — `dock.hint`
    (used by every existing hint test) must follow whichever page is actually open."""
    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.properties.hint.isVisible() and dock.properties.hint.text() == EDIT_HINT
    assert dock.hint is dock.properties.hint and dock.hint.text() == EDIT_HINT
    dock.edit_button.setChecked(False)
    assert not dock.properties.hint.isVisible()


def test_the_zoom_button_zooms_to_the_feature(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    before = dock.iface.mapCanvas().extent()
    dock.properties.zoom_button.click()
    assert dock.iface.mapCanvas().extent() != before


# --- Escape, the title bar, hint placement, tools for a vanished feature ------------------------


def test_escape_inside_the_feature_page_closes_it(tmp_path):
    """CRITICAL regression: `PropertiesPage` is a `QgsPanelWidget` (dockMode True) exactly like
    `ToolGallery` — its own inherited `keyPressEvent` answers Escape by calling its own
    `acceptPanel()`, emitting `properties.panelAccepted` rather than the `_PagePanel` wrapper's,
    before the key press ever reaches the wrapper actually on the stack. Without forwarding that to
    `close_page` (`MainDock.__init__`, the same fix `gallery` already had), Escape anywhere inside
    the feature page — the name field, a spin box — did nothing at all. Sent to two different
    widgets inside the page, with a real event loop, on the genuinely shown dock."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)

    dock.feature_view.rowOpened.emit(dike.id)
    QApplication.processEvents()
    assert dock.stack.currentPanel() is dock.properties_page
    dock.properties.name_edit.setFocus()
    QApplication.processEvents()
    QTest.keyClick(dock.properties.name_edit, Qt.Key.Key_Escape)
    assert dock.stack.currentPanel() is dock.main_panel     # Escape in the name field closed the page
    spin_event_loop(50)                                       # let the deferred delete actually run

    dock.feature_view.rowOpened.emit(dike.id)
    QApplication.processEvents()
    assert dock.stack.currentPanel() is dock.properties_page
    assert dock.properties.isVisible()                        # reopens a live, visible page
    dock.properties.amount.setFocus()
    QApplication.processEvents()
    QTest.keyClick(dock.properties.amount, Qt.Key.Key_Escape)
    assert dock.stack.currentPanel() is dock.main_panel     # Escape in a spin box closed it too
    spin_event_loop(50)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page and dock.properties.isVisible()


def test_escape_in_the_name_field_cancels_instead_of_committing(tmp_path):
    """Escape cancels. `editingFinished` fires on focus-out as well as Return — and the page
    closing (Escape's other effect there) takes focus away from `name_edit` — so without
    discarding the typed text first, Escape would commit it as a rename anyway, the moment the
    page closed underneath it. Return still commits (`test_renaming_in_the_header_is_undoable`)."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.name_edit.setFocus()
    QApplication.processEvents()
    dock.properties.name_edit.selectAll()
    QTest.keyClicks(dock.properties.name_edit, "Typed but not committed")
    steps = c.undo_stack.count()

    QTest.keyClick(dock.properties.name_edit, Qt.Key.Key_Escape)
    QApplication.processEvents()
    spin_event_loop(20)
    assert dock.stack.currentPanel() is dock.main_panel      # Escape still closed the page
    assert c.feature(dike.id).name == dike.name               # …but the typed text was discarded
    assert c.undo_stack.count() == steps                      # and no rename was ever committed


def test_escape_in_a_spin_box_cancels_instead_of_committing(tmp_path):
    """Escape cancels in every field, not just the name field. `amount`'s
    `setKeyboardTracking(False)` means typing does not commit as it goes, but the spin's own
    `interpretText()` still commits whatever is displayed on focus-out — which the page closing
    (Escape's other effect) would otherwise trigger, same hazard `_discard_name_edit` fixes for the
    name field. Return still commits (`test_properties_show_the_tool_fields_and_apply_changes`)."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    before = c.feature(dike.id).amount
    dock.properties.amount.setFocus()
    QApplication.processEvents()
    dock.properties.amount.selectAll()
    QTest.keyClicks(dock.properties.amount, "77")
    steps = c.undo_stack.count()

    QTest.keyClick(dock.properties.amount, Qt.Key.Key_Escape)
    QApplication.processEvents()
    spin_event_loop(20)
    assert dock.stack.currentPanel() is dock.main_panel      # Escape still closed the page
    assert c.feature(dike.id).amount == before                # …but the typed value was discarded
    assert c.undo_stack.count() == steps                       # and no change was ever committed


def test_return_commits_a_spin_boxs_typed_value(tmp_path):
    """The other half of the Escape-cancels rule above: typing into `amount` and pressing Return —
    not just `setValue` — must commit it, through the real keyboard path (`interpretText` on
    `editingFinished`/Return), as one undo step. There was no keyboard-driven test of this; every
    existing coverage of a committed change (`test_properties_show_the_tool_fields_and_apply_changes`)
    calls `setValue` directly, which bypasses typing and `keyboardTracking(False)` entirely."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis.PyQt.QtWidgets import QApplication

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.amount.setFocus()
    QApplication.processEvents()
    dock.properties.amount.selectAll()
    QTest.keyClicks(dock.properties.amount, "7.5")
    steps = c.undo_stack.count()

    QTest.keyClick(dock.properties.amount, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert c.feature(dike.id).amount == pytest.approx(7.5)
    assert c.undo_stack.count() == steps + 1


def test_the_title_bar_follows_a_rename(tmp_path):
    """spec §7: "The panel's title bar follows a rename" — through the header field, through the
    list, and through undo. `QgsPanelWidgetStack` writes its title `QLabel` (`mTitleText`) once,
    when the panel is pushed, with no live-update signal of its own (verified by probe): without
    `_sync_feature_page_title`, every assertion below would still see the name the page had when it
    was opened."""
    from qgis.PyQt.QtWidgets import QLabel

    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    label = dock.stack.findChild(QLabel, "mTitleText")
    assert label.text() == f" {dike.name} "

    dock.properties.name_edit.setText("Dike north")
    dock.properties.name_edit.editingFinished.emit()
    assert label.text() == " Dike north "
    assert dock.properties_page.panelTitle() == "Dike north"

    dock.model.setData(dock.model.index(dock.model.row_of(dike.id)), "Sea wall")
    assert label.text() == " Sea wall "

    dock.undo_button.click()                # undoes the rename through the list
    assert label.text() == " Dike north "


def test_the_hint_sits_under_the_action_row_within_the_viewport(tmp_path):
    """spec §6 item 6: the hint must sit directly under the action row so it is never
    scrolled out of sight — checked on a small dock with Volumes and About both expanded, which
    push the page's total content height well past what a 320×420 dock can show at once."""
    from qgis.PyQt.QtWidgets import QApplication

    _iface, c, dock = panel(tmp_path)
    dock.resize(320, 420)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    page = dock.properties
    page.volumes.setCollapsed(False)
    page.about.setCollapsed(False)
    dock.edit_button.setChecked(True)
    QApplication.processEvents()
    # Expanding a group can itself scroll the area to keep the newly-revealed content in view; a
    # fresh page (nothing yet manually scrolled) always starts at the top, so that is what is
    # checked — whether the hint needs scrolling to reach is exactly what this test is about.
    page.scroll_area.verticalScrollBar().setValue(0)
    QApplication.processEvents()

    assert page.hint.isVisible()
    viewport = page.scroll_area.viewport()
    top = page.hint.mapTo(viewport, page.hint.rect().topLeft()).y()
    bottom = top + page.hint.height()
    assert 0 <= top and bottom <= viewport.height(), (top, bottom, viewport.height())


def test_a_hint_with_no_page_open_shows_under_the_toolbar(tmp_path):
    """spec §6 item 6: a section line drawn from the Profiles dock after going back to
    the list has no page open to show its hint on — it shows under the toolbar in the session view
    instead."""
    from terrain_sketch.gui.help_texts import SECTION_LINE_HINT
    from terrain_sketch.gui.profile_dock import ProfileDock

    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.show()
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.rowOpened.emit(pond.id)
    dock.close_page()                                        # back to the list: no page open
    assert dock.stack.currentPanel() is dock.main_panel

    profiles.draw_section.click()
    assert dock.draw_tool is not None
    assert dock.session_hint.isVisible() and dock.session_hint.text() == SECTION_LINE_HINT
    assert dock.hint is dock.session_hint


def test_a_running_section_lines_hint_moves_to_the_session_view_on_back(tmp_path):
    """spec §6 item 6: a hint whose label is picked only once, when the activity starts, stays on
    the now-hidden page's own label when the feature page closes with a section line still running
    (spec §9: it keeps going), and is visible nowhere. `MainDock` must move
    it to `session_hint` the moment the page closes, whichever way that happens — here, the stack's
    own Back button, with a real event loop so the deferred reroute (`_schedule_reroute_hint` waits
    for the stack's own pop, posted with `QTimer.singleShot(0, …)`) has a chance to run."""
    from qgis.PyQt.QtWidgets import QApplication, QToolButton
    from qgis_helpers import spin_event_loop
    from terrain_sketch.gui.help_texts import SECTION_LINE_HINT
    from terrain_sketch.gui.profile_dock import ProfileDock

    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.show()
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.rowOpened.emit(pond.id)
    profiles.draw_section.click()
    assert dock.properties.hint.isVisible() and dock.properties.hint.text() == SECTION_LINE_HINT

    back = dock.stack.findChild(QToolButton, "mBackButton")
    back.click()
    QApplication.processEvents()
    spin_event_loop(20)                                        # let the deferred reroute actually run
    assert dock.stack.currentPanel() is dock.main_panel
    assert dock.draw_tool is not None                          # the line keeps running (spec §9)
    assert dock.session_hint.isVisible() and dock.session_hint.text() == SECTION_LINE_HINT
    # `isVisible()` is already False here regardless of routing — the feature page's own ancestor
    # is hidden once it is no longer the current panel — so only `isHidden()` (the widget's own
    # explicit hidden state) can actually catch a hint left showing on the closed page.
    assert dock.properties.hint.isHidden() and dock.gallery.hint.isHidden()


def test_a_running_section_lines_hint_moves_onto_its_feature_page_on_open(tmp_path):
    """The reverse of the test above: a section line started from the list — its hint on
    `session_hint` — must move onto the feature page the moment that page opens (spec §6 item 6),
    not stay stranded under the toolbar behind it."""
    from qgis.PyQt.QtWidgets import QApplication
    from qgis_helpers import spin_event_loop
    from terrain_sketch.gui.help_texts import SECTION_LINE_HINT
    from terrain_sketch.gui.profile_dock import ProfileDock

    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.show()
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.rowOpened.emit(pond.id)
    dock.close_page()
    QApplication.processEvents()
    spin_event_loop(20)   # flush this close's own deferred reroute before it can mask the one below
    profiles.draw_section.click()
    assert dock.session_hint.isVisible() and dock.session_hint.text() == SECTION_LINE_HINT

    dock.feature_view.rowOpened.emit(pond.id)
    QApplication.processEvents()
    spin_event_loop(20)
    assert dock.stack.currentPanel() is dock.properties_page
    assert dock.properties.hint.isVisible() and dock.properties.hint.text() == SECTION_LINE_HINT
    # As above: `session_hint`'s own ancestor is hidden once a page is open, which would make
    # `isVisible()` false whether or not the reroute actually ran — `isHidden()` checks the label's
    # own explicit state instead.
    assert dock.session_hint.isHidden()


def test_edit_shape_stops_when_the_feature_page_closes(tmp_path):
    """spec §9: Edit shape's own button lives on the feature page — closing it (Back here; Escape
    goes through the same `panelAccepted`) leaves no way to switch editing off from there, so
    closing the page must stop it itself."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.close_page()
    assert dock.edit_tool is None and not dock.edit_button.isChecked()


def test_a_section_line_keeps_running_after_the_feature_page_closes(tmp_path):
    """Unlike Edit shape, a section line started from the Profiles dock keeps running when
    the feature page closes — its own controls live on the Profiles dock, not the feature page."""
    from terrain_sketch.gui.profile_dock import ProfileDock

    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.rowOpened.emit(pond.id)
    profiles.draw_section.click()
    tool = dock.draw_tool
    assert tool is not None and dock._section_fid == pond.id
    dock.close_page()
    assert dock.draw_tool is tool and dock._section_fid == pond.id   # still running


def test_a_section_line_stops_when_its_feature_disappears_with_the_page_closed(tmp_path):
    """spec §9: a feature that disappears (delete, undo) must not leave a tool still working on it,
    whether or not its page happens to be open right now. Checking only while the feature page is
    the current panel would leave a section line's `_section_fid` still set — and the map tool
    still running — whenever the page had already been closed (a
    section line is the one tool that genuinely reaches that state at all: unlike Edit shape, spec
    §9 has it keep running when the feature page closes, see
    `test_a_section_line_keeps_running_after_the_feature_page_closes` above — Edit shape's own
    button lives on that page, so it always stops the moment the page does, and this specific "tool
    still running with the page already closed" state can never arise for it)."""
    from terrain_sketch.gui.profile_dock import ProfileDock

    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()

    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.rowOpened.emit(pond.id)
    profiles.draw_section.click()
    assert dock.draw_tool is not None and dock._section_fid == pond.id
    dock.close_page()
    assert dock.draw_tool is not None and dock._section_fid == pond.id   # still running, page closed

    c.delete_feature(pond.id)
    assert dock.draw_tool is None and dock._section_fid is None          # now it stops


def test_edit_shape_stops_when_its_feature_disappears_with_no_page_ever_open(tmp_path):
    """The other reachable form of the same bug: Edit shape's button also works with no page open
    at all — nothing about `_toggle_edit` requires the page to be showing — so a feature can be
    edited without its page ever having been opened (selecting it is enough); deleting it through
    the list's context menu (`controller.delete_feature`, exactly what `Delete` on the menu calls)
    at that point must not leave `edit_tool` running on a feature that no longer exists, whether
    or not the feature page happens to be the open panel."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.stack.currentPanel() is dock.main_panel      # selection alone never opens the page
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None

    c.delete_feature(dike.id)
    assert dock.edit_tool is None and not dock.edit_button.isChecked()


def test_an_empty_header_name_restores_the_current_name(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.name_edit.setText("")
    dock.properties.name_edit.editingFinished.emit()
    assert c.feature(dike.id).name == dike.name
    assert dock.properties.name_edit.text() == dike.name


def test_a_padded_header_name_commits_and_shows_the_stripped_name(tmp_path):
    """Real typing (`QTest.keyClicks` + Return), not `setText` + a bare `editingFinished.emit()`:
    `setText` never sets `isModified()`, so `_refresh_problems`'s own "still typing" guard
    (`if not self.name_edit.isModified(): self.name_edit.setText(feature.name)`) — an ordinary side
    effect of the `featuresChanged` the commit itself triggers — would repair the field on its own
    and mask `_commit_rename`'s own final `setText` being removed entirely. Real typing sets
    `isModified()`, so that guard is skipped and only `_commit_rename`'s own line can be doing it."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtTest import QTest
    from qgis_helpers import spin_event_loop

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.name_edit.setFocus()
    spin_event_loop(10)
    dock.properties.name_edit.selectAll()
    QTest.keyClicks(dock.properties.name_edit, "  Padded  ")
    assert dock.properties.name_edit.isModified()
    QTest.keyClick(dock.properties.name_edit, Qt.Key.Key_Return)
    assert c.feature(dike.id).name == "Padded"
    assert dock.properties.name_edit.text() == "Padded"


def test_show_feature_keeps_a_name_the_user_is_still_typing_when_retargeting(tmp_path):
    """`_selection_changed` retargets the open page by calling `show_feature` again for the same
    feature (e.g. an unrelated `featuresChanged`) — that must follow `_load_values`' rule for the
    numeric fields and never overwrite a name the user has not finished typing yet. Retargeting a
    *different* feature must still replace it unconditionally."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.name_edit.setText("Still typing")
    dock.properties.name_edit.setModified(True)
    dock.properties.show_feature(dike.id)                # retargeting the SAME feature
    assert dock.properties.name_edit.text() == "Still typing"
    dock.properties.show_feature(pond.id)                 # a DIFFERENT feature always replaces it
    assert dock.properties.name_edit.text() == pond.name


def test_delete_uses_the_id_the_page_sends_not_just_the_selection(tmp_path):
    """`deleteRequested(str)` carries the feature the page is actually showing; `_delete_selected`
    must delete that one, not whatever the list's own selection happens to be (only falling back to
    the selection when called with none, e.g. a future caller with no id of its own)."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock._delete_selected(dike.id)
    assert c.find(dike.id) is None and c.find(pond.id) is not None
    dock._delete_selected()                               # no id given: falls back to the selection
    assert c.find(pond.id) is None


def test_delete_selected_logs_an_exception_instead_of_raising_it(tmp_path, monkeypatch):
    """An exception escaping a Qt callback aborts QGIS, so every `MainDock` slot reachable from a
    signal, event filter or timer wraps its body in try/except and logs to `QgsMessageLog`. This
    checks that pattern on one slot, `_delete_selected`, with the controller made to raise."""
    import terrain_sketch.gui.main_dock as main_dock_module

    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)

    log = []
    monkeypatch.setattr(main_dock_module.QgsMessageLog, "logMessage",
                        staticmethod(lambda text, *a, **kw: log.append(text)))

    def boom(_fid):
        raise RuntimeError("boom")

    monkeypatch.setattr(c, "delete_feature", boom)
    dock._delete_selected(dike.id)          # must not raise

    assert log and "RuntimeError" in log[-1]


def test_deleting_from_the_page_stops_a_running_edit(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.properties.delete_button.click()
    assert dock.edit_tool is None and c.features == ()


def test_from_layer_opens_the_new_features_page(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    dock.gallery.layer_source.layer_combo.setLayer(layer)
    dock.gallery.layer_source.use_button.click()
    assert len(c.features) == 1
    assert dock.stack.currentPanel() is dock.properties_page
    assert dock.properties.name_edit.text() == c.features[0].name


def test_gallery_and_properties_are_invisible_while_both_pages_are_closed(tmp_path):
    """Neither `gallery` nor `properties` may paint anywhere while neither page is open — not as an
    unplaced child of the dock at (0, 0) (the state `gallery` was in from construction, before ever
    being opened once, verified by probe) and not after being opened and released either."""
    _iface, c, dock = panel(tmp_path)
    dock.show()
    assert not dock.gallery.isVisible() and not dock.properties.isVisible()   # never yet opened

    dock.new_button.click()
    assert dock.gallery.isVisible()
    dock.close_page()
    assert not dock.gallery.isVisible()

    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.properties.isVisible()
    dock.close_page()
    assert not dock.properties.isVisible() and not dock.gallery.isVisible()

    dock.new_button.click()
    assert dock.gallery.isVisible() and not dock.properties.isVisible()
    dock.close_page()
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.properties.isVisible() and not dock.gallery.isVisible()
