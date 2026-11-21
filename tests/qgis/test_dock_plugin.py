from unittest import mock

import pytest
from qgis.core import QgsFlatTerrainProvider, QgsProject, QgsSettings
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtWidgets import QApplication

from qgis.core import QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsPointXY

from qgis.core import QgsRectangle

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, sample, square, world
from terrain_sketch import classFactory
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.selection import Method
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import SCENARIO_TOTALS, cubic_metres
from terrain_sketch.gui.main_dock import VIEW_SESSION, VIEW_WELCOME, MainDock
from terrain_sketch.gui.map_tools.draw_line import DrawLineTool
from terrain_sketch.qgis_io.layers import GROUP_NAME


def test_drawing_a_dike_from_the_panel(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.show()   # isVisible() below needs the dock actually shown, not just not explicitly hidden
    assert dock.views.currentIndex() == VIEW_WELCOME and not dock.new_button.isEnabled()
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert controller.has_dem and dock.views.currentIndex() == VIEW_SESSION
    dock.new_button.click()                             # drills into the New feature page
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert iface.mapCanvas().mapTool() is dock.draw_tool and dock.hint.isVisible()
    dock.draw_tool.finished.emit(line_through(5, 20, 34, 20))
    assert len(controller.features) == 1
    assert dock.feature_view.selected_id() == controller.features[0].id
    assert dock.stack.currentPanel() is dock.properties_page and not dock.hint.isVisible() and dock.draw_tool is None
    assert sample(controller.layers.working, 20, 20) == pytest.approx(11.0)
    dock.ask_export_path = lambda: str(tmp_path / "exported.tif")
    dock.export_button.click()
    assert (tmp_path / "exported.tif").exists()


def test_a_geographic_dem_is_reported_in_the_message_bar(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert not dock.controller.has_dem
    # it is pushed as a WIDGET now, because it carries a Reproject… button
    iface.messageBar().pushWidget.assert_called()


def test_ending_the_session_stops_a_drawing_in_progress(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert dock.draw_tool is not None
    QgsProject.instance().removeMapLayer(dem.id())  # the user removes the DEM while still drawing
    assert not controller.has_dem and dock.draw_tool is None and dock.hint.isHidden()
    assert iface.mapCanvas().mapTool() is None


def test_hiding_the_panel_stops_a_drawing_and_leaves_no_rubber_band(tmp_path):
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    plugin.dock.dem_combo.setLayer(dem_layer(tmp_path))
    plugin.dock.start_button.click()
    n0 = len(iface.mapCanvas().scene().items())
    plugin.dock.gallery.select_tool(Tool.RAISE_PATH)
    plugin.dock.gallery.select_mode(Mode.PATH)
    plugin.dock.gallery.method_buttons[Method.CLICK].click()
    plugin.action.setChecked(False)
    assert plugin.dock.draw_tool is None
    assert len(iface.mapCanvas().scene().items()) == n0


def test_the_open_page_stays_while_the_panel_is_toggled_off(tmp_path):
    """spec §9: toggling the plugin's own panel off (`plugin.action`, not `MainDock.closeEvent` —
    `_toggle` calls `stop_tools()` directly, never `close_page()`) stops tools, as it already did,
    but must not close whatever page is open — it is there again for when the panel returns."""
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    plugin.dock.dem_combo.setLayer(dem_layer(tmp_path))
    plugin.dock.start_button.click()
    dike = plugin.controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    plugin.dock.feature_view.rowOpened.emit(dike.id)
    assert plugin.dock.stack.currentPanel() is plugin.dock.properties_page
    plugin.action.setChecked(False)
    assert plugin.dock.stack.currentPanel() is plugin.dock.properties_page


def test_plugin_adds_and_removes_its_button_menu_and_panel(tmp_path):
    flat = QgsFlatTerrainProvider()
    flat.setOffset(5.0)
    QgsProject.instance().elevationProperties().setTerrainProvider(flat)
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    iface.addToolBarIcon.assert_called_once_with(plugin.action)
    iface.addPluginToRasterMenu.assert_called_once()
    plugin.action.setChecked(True)
    assert plugin.dock is not None and plugin.profiles is not None
    assert iface.addDockWidget.call_count == 2  # the panel on the right, the profiles below
    plugin.dock.dem_combo.setLayer(dem_layer(tmp_path))
    plugin.dock.start_button.click()
    controller = plugin.controller              # kept alive, so its undo stack can be watched after unload
    assert controller.show_in_3d()
    plugin.unload()
    iface.removeToolBarIcon.assert_called_once()
    assert iface.removeDockWidget.call_count == 2
    assert plugin.dock is None and plugin.profiles is None
    assert plugin.controller is None and plugin.action is None
    terrain = QgsProject.instance().elevationProperties().terrainProvider()
    assert isinstance(terrain, QgsFlatTerrainProvider) and terrain.offset() == 5.0   # the project's terrain is back
    # The canvas outlives the plugin: its Ctrl+Z filter must go at once, not whenever the dock is deleted
    canvas = iface.mapCanvas()
    canvas.setMapTool(DrawLineTool(canvas))     # a Terrain Sketch tool, as far as that filter could tell
    controller.undo_stack.undo = mock.Mock()
    for kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
        QApplication.sendEvent(canvas, QKeyEvent(kind, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier))
    controller.undo_stack.undo.assert_not_called()


def _session_dock(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def test_the_brush_extends_the_selected_area_feature(tmp_path):
    """Drives the gallery directly, with a feature selected: the panel itself cannot reach an
    extending brush, because New feature clears the selection before its page opens. The code is
    kept as the hook for a future "paint more" action."""
    _iface, controller, dock = _session_dock(tmp_path)
    pond = controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock._brush_fid == pond.id and not dock.draw_tool.geometry.isEmpty()
    dock.draw_tool.apply_stroke([QgsPointXY(*world(25, 15))])  # paint next to the pond
    dock.draw_tool.finish()
    assert len(controller.features) == 1  # the pond grew, no second feature
    assert sample(controller.layers.working, 25, 15) < 10.0


def test_vertex_editing_reshapes_the_selected_feature(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.edit_tool.geometryChanged.emit(line_through(5, 10, 34, 10))
    assert sample(controller.layers.working, 20, 10) == pytest.approx(11.0)
    assert sample(controller.layers.working, 20, 20) == pytest.approx(10.0)
    dock.edit_button.setChecked(False)
    assert dock.edit_tool is None


def test_selecting_a_feature_highlights_it_on_the_map(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.highlight.numberOfVertices() > 0
    dock.feature_view.clearSelection()
    assert dock.highlight.numberOfVertices() == 0


def test_an_outline_that_cannot_be_projected_leaves_the_highlight_empty(tmp_path):
    """Selecting and changing a feature redraw the highlight from Qt signals, so a failed
    projection into the map's CRS must not raise there; Edit shape and Zoom say so when used."""
    iface, controller, dock = _session_dock(tmp_path)
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    with mock.patch.object(QgsGeometry, "transform", side_effect=QgsCsException("forced")):
        dock.feature_view.select_id(dike.id)
        assert dock.highlight.numberOfVertices() == 0
        controller.update_feature(dike.id, amount=2.0)
        assert dock.highlight.numberOfVertices() == 0
    iface.messageBar().pushMessage.assert_not_called()


def test_deleting_the_shown_feature_leaves_the_properties_page(tmp_path):
    """`featuresChanged` resets the list model, which can clear the Qt selection without
    emitting `selectionChanged` — so the dock must check for itself that Properties is not left
    showing a feature that Delete just removed."""
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page

    dock.delete_button.click()

    if dock.stack.currentPanel() is dock.properties_page:
        fid = dock.feature_view.selected_id()
        assert fid is not None and fid in {f.id for f in controller.features}
        cut, fill = controller.totals()
        assert dock.properties.totals_value.text() == SCENARIO_TOTALS.format(fill=cubic_metres(fill),
                                                                              cut=cubic_metres(cut))
    else:
        assert dock.stack.currentPanel() is not dock.properties_page


def test_deleting_the_brushed_feature_mid_stroke_does_not_take_qgis_down(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    pond = controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    brush = dock.draw_tool
    assert dock._brush_fid == pond.id
    controller.delete_feature(pond.id)  # the Delete button or the row context menu, still painting
    assert dock._brush_fid is None
    brush.apply_stroke([QgsPointXY(*world(25, 15))])
    brush.finish()  # a stale target used to raise StopIteration out of this Qt callback
    assert len(controller.features) == 1 and controller.features[0].id != pond.id


def test_the_brush_hint_names_the_feature_it_extends(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    pond = controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock._brush_fid == pond.id and pond.name in dock.hint.text()
    dock.end_drawing()
    dock.feature_view.clearSelection()
    dock.gallery.method_buttons[Method.BRUSH].click()  # nothing selected: this paints a new feature
    assert dock._brush_fid is None and pond.name not in dock.hint.text()


def test_opening_a_row_takes_the_new_feature_page_and_its_hint_off_screen(tmp_path):
    """`isHidden()` is False for a widget that was never put on screen at all, so the original form
    of this test (no `dock.show()`, no `dock.new_button.click()`) could not tell a visible hint from
    one that was never shown in the first place — it passed regardless of what really happened on
    screen. With the page genuinely opened and the dock genuinely shown: opening a row (not
    reachable through the real UI while the New feature page covers the feature list — this fires
    `rowOpened` directly, as the original test drove the selection model directly) opens that row's
    properties page in the New feature page's place (`open_page` never drills more than one level
    deep — see its docstring), which — since the page the drawing's hint was on is now gone — stops
    the drawing too (`_stop_drawing_on_gallery_close`), the same as pressing Back or Escape would."""
    _iface, controller, dock = _session_dock(tmp_path)
    dock.show()
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.FREEHAND].click()
    assert dock.hint.isVisible()
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.draw_tool is None          # the page it was drawing on is gone, so the drawing stopped
    assert not dock.hint.isVisible()       # … and so did its hint
    assert dock.stack.currentPanel() is dock.properties_page


def test_closing_the_panel_stops_the_edit_tool_too(tmp_path):
    iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.close()
    assert dock.edit_tool is None and iface.mapCanvas().mapTool() is None


def test_the_brush_radius_follows_the_canvas_crs(tmp_path):
    iface, _controller, dock = _session_dock(tmp_path)
    assert dock.gallery.brush_spin.suffix() == " m"  # the test canvas is UTM
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert dock.gallery.brush_spin.suffix() == " degrees"


def _dock_on(tmp_path, canvas_crs=None):
    iface = fake_iface()
    if canvas_crs is not None:
        iface.mapCanvas().setDestinationCrs(canvas_crs)
    dem = dem_layer(tmp_path)                       # EPSG:25832
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    return iface, controller, dock


def test_the_drag_preview_is_placed_with_a_dem_to_canvas_transform(tmp_path):
    """The engine reports preview bounds in the DEM CRS. Without a transform the cut/fill image
    lands somewhere else on the map — or off-screen — for any project whose CRS differs."""
    web = QgsCoordinateReferenceSystem("EPSG:3857")
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=web)
    transform = dock.overlay.crs_transform
    assert transform is not None and transform.isValid()
    assert transform.sourceCrs() == controller.dem_crs
    assert transform.destinationCrs() == web

    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    previews = []
    controller.previewUpdated.connect(lambda _fid, preview: previews.append(preview))
    controller.preview(dike.id, amount=5.0)
    assert previews and dock.overlay.bounds is not None
    expected = transform.transformBoundingBox(QgsRectangle(*previews[0].bounds))
    assert dock.overlay.bounds.xMinimum() == pytest.approx(expected.xMinimum())
    assert dock.overlay.bounds.yMinimum() == pytest.approx(expected.yMinimum())
    # and that is nowhere near the untransformed DEM-CRS bounds
    assert abs(dock.overlay.bounds.xMinimum() - previews[0].bounds[0]) > 1000.0


def test_the_overlay_transform_follows_a_change_of_project_crs(tmp_path):
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=QgsCoordinateReferenceSystem("EPSG:3857"))
    assert dock.overlay.crs_transform is not None
    iface.mapCanvas().setDestinationCrs(UTM)          # the user switches the project to the DEM CRS
    assert dock.overlay.crs_transform is None         # same CRS: the bounds need no transform
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert dock.overlay.crs_transform is not None
    assert dock.overlay.crs_transform.destinationCrs().authid() == "EPSG:4326"


def test_a_dem_crs_that_cannot_be_projected_leaves_the_preview_unshown(tmp_path):
    """`_update_overlay_transform` runs in a slot, so it must not raise — and it must not let the
    overlay paint bounds it cannot place."""
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=QgsCoordinateReferenceSystem("EPSG:3857"))
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    previews = []
    controller.previewUpdated.connect(lambda _fid, preview: previews.append(preview))
    controller.preview(dike.id, amount=5.0)
    assert dock.overlay.isVisible()

    controller.dem_crs = QgsCoordinateReferenceSystem()   # a DEM whose CRS is unknown
    dock._update_overlay_transform()
    assert dock.overlay.crs_transform is None and not dock.overlay.isVisible()
    controller.previewUpdated.emit(dike.id, previews[0])  # the next frame of the drag arrives
    assert not dock.overlay.isVisible() and dock.overlay.bounds is None


def test_without_a_session_the_overlay_has_no_transform(tmp_path):
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=QgsCoordinateReferenceSystem("EPSG:3857"))
    assert dock.overlay.crs_transform is not None
    controller.close()
    assert dock.overlay.crs_transform is None


def test_the_panels_open_where_they_were_left_and_unloading_remembers_it(tmp_path):
    from terrain_sketch.gui import settings
    iface = fake_iface()
    window = iface.mainWindow()
    iface.addDockWidget.side_effect = window.addDockWidget          # a real window, as in QGIS
    settings.save("main_dock/area", int(Qt.DockWidgetArea.LeftDockWidgetArea.value))
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    assert iface.addDockWidget.call_args_list[0][0] == (Qt.DockWidgetArea.LeftDockWidgetArea, plugin.dock)
    assert window.dockWidgetArea(plugin.profiles) == Qt.DockWidgetArea.BottomDockWidgetArea   # the default
    window.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, plugin.profiles)   # the user moves it
    QgsSettings().remove(f"{settings.GROUP}/main_dock/area")         # only unloading can write it back now
    plugin.unload()
    area = Qt.DockWidgetArea
    assert settings.dock_area("profile_dock", area.BottomDockWidgetArea) == area.TopDockWidgetArea
    assert settings.dock_area("main_dock", area.RightDockWidgetArea) == area.LeftDockWidgetArea


def plugin_in_a_window():
    """The plugin with its panels in a real, shown main window, as QGIS puts them."""
    iface = fake_iface()
    window = iface.mainWindow()
    iface.addDockWidget.side_effect = window.addDockWidget
    window.show()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    QApplication.processEvents()
    return iface, plugin


def test_the_profiles_panel_starts_hidden_and_the_panel_button_shows_and_hides_it():
    _iface, plugin = plugin_in_a_window()
    button = plugin.dock.profiles_button
    assert plugin.dock.isUserVisible() and not plugin.profiles.isUserVisible()
    assert button.isCheckable() and not button.isChecked() and button.isEnabled()
    button.click()
    assert plugin.profiles.isUserVisible() and button.isChecked()
    button.click()
    assert not plugin.profiles.isUserVisible() and not button.isChecked()
    plugin.unload()


def test_closing_the_profiles_panel_itself_releases_the_button():
    _iface, plugin = plugin_in_a_window()
    plugin.dock.profiles_button.click()
    plugin.profiles.close()                                   # the panel's own close button
    QApplication.processEvents()
    assert not plugin.dock.profiles_button.isChecked()
    plugin.unload()


def test_hiding_terrain_sketch_hides_the_profiles_and_opening_it_again_does_not_show_them():
    _iface, plugin = plugin_in_a_window()
    plugin.dock.profiles_button.click()
    plugin.action.setChecked(False)
    assert not plugin.profiles.isUserVisible()
    plugin.action.setChecked(True)
    assert plugin.dock.isUserVisible() and not plugin.profiles.isUserVisible()
    assert not plugin.dock.profiles_button.isChecked()
    plugin.unload()


def test_a_panel_without_a_profiles_panel_has_no_profiles_button():
    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    assert not dock.profiles_action.isVisible()


def test_the_new_feature_button_sits_above_the_feature_list(tmp_path):
    """The primary action lives in the toolbar, above the list, in the session view now (spec §5).
    `delete_button` and `edit_button` are the feature page's own buttons (spec §12) and are laid
    out there, not in the toolbar, so their position is not asserted here."""
    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    dock.resize(360, 700)
    dock.show()
    QApplication.processEvents()
    list_top = dock.feature_view.mapTo(dock, dock.feature_view.rect().topLeft()).y()
    assert dock.new_button.mapTo(dock, dock.new_button.rect().bottomLeft()).y() < list_top


def test_the_feature_list_fills_the_session_view_without_a_splitter(tmp_path):
    """The list_splitter is retired along with its settings key (spec §10): there is no splitter any
    more, and the feature list alone fills the session view's height below the toolbar."""
    from qgis.PyQt.QtWidgets import QSplitter
    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    assert not hasattr(dock, "list_splitter")
    assert dock.findChild(QSplitter, "TerrainSketchListSplitter") is None
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    dock.resize(360, 900)
    dock.show()
    QApplication.processEvents()
    # no lower pages sharing the session view's height any more: only the toolbar and the status line
    assert dock.feature_view.height() > dock.views.height() - 120
