import sys
import types

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QPushButton

from qgis_helpers import dem_layer, fake_iface, line_layer, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import (EMPTY_LAYER, NO_FEATURES_SELECTED, PICK_A_LAYER,
                                           REPROJECT_UNAVAILABLE)
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.gui.tool_gallery import ToolGallery


def offer_reproject(iface, dock, tmp_path):
    """Refuse a geographic DEM and hand back that layer and the Reproject… button offered with it."""
    dem = dem_layer(tmp_path, name="geographic", crs="EPSG:4326",
                    gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    widget = iface.messageBar().pushWidget.call_args[0][0]
    button, = [b for b in widget.findChildren(QPushButton) if "Reproject" in b.text()]
    return dem, button


def fake_processing(dialog):
    """A stand-in for the Processing plugin whose execAlgorithmDialog is `dialog`."""
    module = types.ModuleType("processing")
    module.execAlgorithmDialog = dialog
    return module


def messages(iface):
    return [call[0][1] for call in iface.messageBar().pushMessage.call_args_list]


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


def test_the_reproject_button_explains_itself_when_processing_is_disabled(tmp_path, monkeypatch):
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    _dem, button = offer_reproject(iface, dock, tmp_path)
    monkeypatch.setitem(sys.modules, "processing", None)   # `import processing` now fails
    button.click()
    assert REPROJECT_UNAVAILABLE in messages(iface)


def test_a_warp_tool_that_fails_to_open_becomes_a_message(tmp_path, monkeypatch):
    """This button's slot runs inside a Qt callback, where an exception aborts the interpreter
    rather than failing anything — so nothing it calls may be left to raise."""
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    _dem, button = offer_reproject(iface, dock, tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("the warp dialog could not be opened")

    monkeypatch.setitem(sys.modules, "processing", fake_processing(explode))
    button.click()
    assert REPROJECT_UNAVAILABLE in messages(iface)


def test_the_warp_tool_gets_the_dem_the_message_was_about(tmp_path, monkeypatch):
    """The offer belongs to the DEM that was refused. Reading the combo at click time instead
    would warp whichever layer the user had picked since — silently, and with no undo."""
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    geographic, button = offer_reproject(iface, dock, tmp_path)
    dock.dem_combo.setLayer(dem_layer(tmp_path, name="projected"))   # the user moves on
    asked = []
    monkeypatch.setitem(sys.modules, "processing",
                        fake_processing(lambda name, params: asked.append((name, params))))
    button.click()
    assert len(asked) == 1 and asked[0][0] == "gdal:warpreproject"
    assert asked[0][1]["INPUT"].id() == geographic.id()


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
