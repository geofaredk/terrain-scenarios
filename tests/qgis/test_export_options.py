"""Export DEM's options (spec §8.5): add the result to the project, and say when an integer DEM is
exported with decimals."""
import numpy as np
from osgeo import gdal
from qgis.core import QgsProject, QgsRasterLayer

from qgis_helpers import CELL, UTM, X0, Y0, fake_iface, line_through
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED
from terrain_sketch.gui.main_dock import MainDock


def integer_dem(tmp_path) -> QgsRasterLayer:
    path = str(tmp_path / "whole_metres.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, 40, 40, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((X0, CELL, 0.0, Y0, 0.0, -CELL))
    ds.SetProjection(UTM.toWkt())
    ds.GetRasterBand(1).WriteArray(np.full((40, 40), 10, np.int16))
    ds = None
    layer = QgsRasterLayer(path, "whole metres")
    QgsProject.instance().addMapLayer(layer)
    return layer


def panel(tmp_path, dem=None):
    from qgis_helpers import dem_layer
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem or dem_layer(tmp_path))
    dock.start_button.click()
    assert controller.has_dem
    return iface, controller, dock


def pushed(iface):
    """(text, widget) of the last message pushed as a widget."""
    widget = iface.messageBar().pushWidget.call_args[0][0]
    return widget.text(), widget


def export(dock, tmp_path, name="exported.tif"):
    path = str(tmp_path / name)
    dock.ask_export_path = lambda: path
    dock.export_button.click()
    return path


def test_the_export_message_offers_to_add_the_result_to_the_project(tmp_path):
    from qgis.PyQt.QtWidgets import QPushButton
    iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = export(dock, tmp_path)
    text, widget = pushed(iface)
    assert text == EXPORT_DONE.format(path)
    button = next(b for b in widget.findChildren(QPushButton) if b.text() == "Add to project")
    assert widget.layout().indexOf(button) >= 0   # laid out in the message, not floating at its corner
    button.click()
    added = [layer for layer in QgsProject.instance().mapLayers().values() if layer.source() == path]
    assert len(added) == 1 and added[0].isValid()
    assert not button.isEnabled()                 # a second click would add a duplicate
    button.click()
    assert len([l for l in QgsProject.instance().mapLayers().values() if l.source() == path]) == 1


def test_an_export_that_has_gone_is_reported_instead_of_added(tmp_path):
    import os
    iface, _c, dock = panel(tmp_path)
    path = export(dock, tmp_path)
    os.remove(path)
    heard = []
    dock._show_message = lambda level, text: heard.append(text)
    dock._add_export(path)
    assert heard == [EXPORT_NOT_ADDED.format(path)]
    assert not [l for l in QgsProject.instance().mapLayers().values() if l.source() == path]


def test_an_integer_dem_is_exported_with_decimals_and_the_user_is_told(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    iface, c, dock = panel(tmp_path, integer_dem(tmp_path))
    assert c.dem_is_integer
    titles = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda _parent, title, *a, **k: titles.append(title) or ("", "")))
    dock._export_dialog()
    assert "32-bit float" in titles[0]

    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = export(dock, tmp_path)
    text, _widget = pushed(iface)
    assert text == f"{EXPORT_DONE.format(path)}. {EXPORT_INTEGER_NOTE}"
    assert gdal.Open(path).GetRasterBand(1).DataType == gdal.GDT_Float32


def test_a_float_dem_gets_no_integer_note(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    iface, c, dock = panel(tmp_path)
    assert not c.dem_is_integer
    titles = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda _parent, title, *a, **k: titles.append(title) or ("", "")))
    dock._export_dialog()
    assert "32-bit" not in titles[0]
    path = export(dock, tmp_path)
    text, _widget = pushed(iface)
    assert EXPORT_INTEGER_NOTE not in text


def test_two_messages_about_the_same_file_add_it_once(tmp_path):
    """Exporting twice to one file leaves two messages, each with its own button."""
    from qgis.PyQt.QtWidgets import QPushButton
    iface, _c, dock = panel(tmp_path)
    path = export(dock, tmp_path)
    _text, first = pushed(iface)
    export(dock, tmp_path)
    _text, second = pushed(iface)
    for widget in (first, second):
        next(b for b in widget.findChildren(QPushButton) if b.text() == "Add to project").click()
    assert len([l for l in QgsProject.instance().mapLayers().values() if l.source() == path]) == 1


def test_an_unexpected_failure_adding_the_export_points_to_the_log(tmp_path):
    from unittest import mock
    _iface, _c, dock = panel(tmp_path)
    path = export(dock, tmp_path)
    heard = []
    dock._show_message = lambda level, text: heard.append(text)
    with mock.patch.object(QgsProject, "addMapLayer", side_effect=RuntimeError("layer registry refused")):
        dock._add_export(path)
    assert heard == [EXPORT_ADD_FAILED.format(path)]


def test_export_is_an_icon_button_like_the_other_file_actions(tmp_path):
    from qgis.PyQt.QtCore import Qt
    _iface, _c, dock = panel(tmp_path)
    assert dock.export_button.toolButtonStyle() == dock.save_scenario_button.toolButtonStyle() \
        == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert dock.export_button.toolTip().startswith("Export DEM…\n")
