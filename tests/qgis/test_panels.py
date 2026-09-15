import pytest
from qgis.core import Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_layer, line_through, panel, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.controller import SketchController
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


def test_a_page_survives_being_closed_and_reopened(tmp_path):
    """QgsPanelWidgetStack deletes a closed panel by default (verified by probe): the gallery and
    properties pages are built once and reopened many times, so they must opt out of that, or the
    second open is a use of a deleted C++ object."""
    from qgis.PyQt.QtWidgets import QApplication

    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)          # opens the properties page
    dock.feature_view.clearSelection()            # closes it
    QApplication.processEvents()
    dock.feature_view.select_id(dike.id)          # reopening it must not touch a deleted panel
    assert dock.stack.currentPanel() is dock.properties_page


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
