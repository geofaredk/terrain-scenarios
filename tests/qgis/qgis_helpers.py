"""Helpers for the QGIS integration tests: small GeoTIFF DEMs on a UTM grid (EPSG:25832)."""
from unittest import mock

import numpy as np
from osgeo import gdal
from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsRectangle, QgsVectorLayer)
from qgis.gui import QgisInterface, QgsMapCanvas, QgsMessageBarItem
from qgis.PyQt.QtCore import QEventLoop, QTimer
from qgis.PyQt.QtWidgets import QMainWindow, QVBoxLayout

gdal.UseExceptions()

X0, Y0, CELL = 612000.0, 6178040.0, 1.0  # top-left corner of the test DEMs
UTM = QgsCoordinateReferenceSystem("EPSG:25832")


def write_dem(path, array, crs="EPSG:25832", nodata=-9999.0, gt=None, bands=1) -> str:
    array = np.asarray(array, dtype=np.float32)
    rows, cols = array.shape
    ds = gdal.GetDriverByName("GTiff").Create(str(path), cols, rows, bands, gdal.GDT_Float32)
    ds.SetGeoTransform(gt or (X0, CELL, 0.0, Y0, 0.0, -CELL))
    ds.SetProjection(crs)
    for b in range(1, bands + 1):
        band = ds.GetRasterBand(b)
        band.WriteArray(array)
        if nodata is not None:
            band.SetNoDataValue(nodata)
    ds.FlushCache()
    ds = None
    return str(path)


def dem_layer(tmp_path, array=None, name="dem", **kw) -> QgsRasterLayer:
    """A 40 x 40 flat 10 m DEM (or `array`) added to the project."""
    if array is None:
        array = np.full((40, 40), 10.0, np.float32)
    layer = QgsRasterLayer(write_dem(tmp_path / f"{name}.tif", array, **kw), name)
    assert layer.isValid()
    QgsProject.instance().addMapLayer(layer)
    return layer


def world(col: float, row: float) -> tuple[float, float]:
    """Map coordinates of a cell centre on the test grid."""
    return X0 + (col + 0.5) * CELL, Y0 - (row + 0.5) * CELL


def line_through(c0, r0, c1, r1) -> QgsGeometry:
    return QgsGeometry.fromPolylineXY([QgsPointXY(*world(c0, r0)), QgsPointXY(*world(c1, r1))])


def square(c0, r0, c1, r1) -> QgsGeometry:
    corners = [world(c0, r0), world(c1, r0), world(c1, r1), world(c0, r1), world(c0, r0)]
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in corners]])


def sample(layer, col, row) -> float:
    return layer.dataProvider().sample(QgsPointXY(*world(col, row)), 1)[0]


def read_tif(path):
    ds = gdal.Open(str(path))
    band = ds.GetRasterBand(1)
    return band.ReadAsArray(), band.GetNoDataValue()


def fake_iface():
    """A QgisInterface mock with a real main window and a UTM map canvas over the test grid.

    The canvas has no parent so it lives as long as a test holds it, even after the mock is gone."""
    iface = mock.Mock(spec=QgisInterface)
    iface.mainWindow.return_value = QMainWindow()
    canvas = QgsMapCanvas()
    canvas.resize(400, 400)
    canvas.setDestinationCrs(UTM)
    canvas.setExtent(QgsRectangle(X0, Y0 - 40, X0 + 40, Y0))
    iface.mapCanvas.return_value = canvas
    # The bar stays a Mock so tests can assert pushMessage was called, but createMessage hands
    # back a REAL item: the panel builds a button onto it, and a Mock there would let a broken
    # widget path pass unnoticed — it aborted the interpreter instead.
    def create_message_item(title, text):
        item = QgsMessageBarItem(title, text)
        # Ensure the item has a layout for adding buttons
        if item.layout() is None:
            item.setLayout(QVBoxLayout(item))
        return item
    bar = mock.Mock()
    bar.createMessage.side_effect = create_message_item
    iface.messageBar.return_value = bar
    return iface


def start_session(tmp_path, array=None):
    """A SketchController with a session on a fresh test DEM."""
    from terrain_sketch.gui.controller import SketchController  # imported late: the GUI package comes in a later task

    controller = SketchController(QgsProject.instance())
    controller.set_dem(dem_layer(tmp_path, array))
    return controller


def spin_event_loop(ms: int) -> None:
    """Run the Qt event loop for `ms` milliseconds, so a queued QTimer (like the preview
    throttle) actually fires instead of just sitting there unexercised in a synchronous test."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def line_layer(name, geometries, add_to_project=True) -> QgsVectorLayer:
    """A memory line layer in the test CRS holding `geometries`."""
    layer = QgsVectorLayer("LineString?crs=EPSG:25832", name, "memory")
    features = []
    for geometry in geometries:
        feature = QgsFeature()
        feature.setGeometry(geometry)
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    if add_to_project:
        QgsProject.instance().addMapLayer(layer)
    return layer
