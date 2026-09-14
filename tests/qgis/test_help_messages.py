from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QPushButton

from qgis_helpers import dem_layer, fake_iface, line_layer, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import EMPTY_LAYER, NO_FEATURES_SELECTED, PICK_A_LAYER
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.gui.tool_gallery import ToolGallery


def test_a_geographic_dem_is_refused_with_a_button_that_opens_the_warp_tool(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert not dock.controller.has_dem
    iface.messageBar().pushWidget.assert_called()          # a widget, not a plain message
    widget = iface.messageBar().pushWidget.call_args[0][0]
    buttons = widget.findChildren(QPushButton)
    assert [b for b in buttons if "Reproject" in b.text()], [b.text() for b in buttons]


def test_a_projected_dem_is_accepted_without_any_reproject_offer(tmp_path):
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    assert dock.controller.has_dem
    iface.messageBar().pushWidget.assert_not_called()


def test_the_use_button_is_dead_only_when_no_layer_is_on_offer():
    QgsProject.instance().removeAllMapLayers()
    gallery = ToolGallery()
    form = gallery.layer_source
    assert not form.use_button.isEnabled()
    assert form.use_button.toolTip() == PICK_A_LAYER
    line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    assert form.use_button.isEnabled()
    assert form.use_button.toolTip() != PICK_A_LAYER


def test_an_empty_selection_and_an_empty_layer_are_reported_differently(tmp_path):
    c = start_session(tmp_path)
    said = []
    c.message.connect(lambda level, text: said.append(text))
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer, selected_only=True)
    assert said[-1] == NO_FEATURES_SELECTED and "select" in said[-1].lower()
    empty = line_layer("Nothing here", [])
    c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, empty)
    assert said[-1] == EMPTY_LAYER
    assert NO_FEATURES_SELECTED != EMPTY_LAYER
