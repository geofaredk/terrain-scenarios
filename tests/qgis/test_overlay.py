import numpy as np
import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsRectangle

from qgis_helpers import UTM, X0, Y0, fake_iface
from terrain_scenarios.gui.overlay import change_image, PreviewOverlay


def test_the_change_image_is_warm_for_fill_and_cool_for_cut():
    change = np.array([[0.0, 2.0], [-2.0, 0.0]], dtype=np.float32)
    image = change_image(change)
    assert image is not None and image.width() == 2 and image.height() == 2
    assert image.pixelColor(1, 0).red() > image.pixelColor(1, 0).blue()    # fill: warm
    assert image.pixelColor(0, 1).blue() > image.pixelColor(0, 1).red()    # cut: cool
    assert image.pixelColor(0, 0).alpha() == 0                            # unchanged: invisible


def test_an_unchanged_window_makes_no_image():
    assert change_image(np.zeros((4, 4), dtype=np.float32)) is None


def test_preview_overlay_paint_and_updatePosition_before_show_change_do_not_raise():
    canvas = fake_iface().mapCanvas()
    overlay = PreviewOverlay(canvas)
    # Should not raise even though image and bounds are None
    overlay.paint(None)
    overlay.updatePosition()


def test_preview_overlay_show_change_makes_it_visible_and_sets_image():
    canvas = fake_iface().mapCanvas()
    overlay = PreviewOverlay(canvas)
    change = np.array([[1.0, -1.0], [0.5, -0.5]], dtype=np.float32)
    bounds = (0.0, 0.0, 10.0, 10.0)
    overlay.show_change(bounds, change)
    assert overlay.isVisible()
    assert overlay.image is not None
    assert overlay.bounds is not None
    assert overlay.image.width() == 2 and overlay.image.height() == 2


def test_preview_overlay_clear_hides_and_drops_image():
    canvas = fake_iface().mapCanvas()
    overlay = PreviewOverlay(canvas)
    change = np.array([[1.0, -1.0]], dtype=np.float32)
    overlay.show_change((0.0, 0.0, 10.0, 10.0), change)
    assert overlay.isVisible()
    overlay.clear()
    assert not overlay.isVisible()
    assert overlay.image is None
    assert overlay.bounds is None
    # Should not raise even after clear
    overlay.paint(None)
    overlay.updatePosition()


def test_preview_overlay_dispose_removes_from_scene():
    canvas = fake_iface().mapCanvas()
    overlay = PreviewOverlay(canvas)
    # the baseline is taken AFTER construction, so "removed" cannot be confused with "never added"
    n_with = len(canvas.scene().items())
    change = np.array([[1.0, -1.0]], dtype=np.float32)
    overlay.show_change((0.0, 0.0, 10.0, 10.0), change)
    assert len(canvas.scene().items()) == n_with
    overlay.dispose()
    assert len(canvas.scene().items()) == n_with - 1  # the overlay itself went
    # Should not raise even after dispose
    overlay.paint(None)
    overlay.updatePosition()


def test_preview_overlay_dispose_twice_is_safe_and_silent(capfd):
    canvas = fake_iface().mapCanvas()
    overlay = PreviewOverlay(canvas)
    change = np.array([[1.0, -1.0]], dtype=np.float32)
    overlay.show_change((0.0, 0.0, 10.0, 10.0), change)
    overlay.dispose()
    capfd.readouterr()          # drop whatever the setup above wrote
    overlay.dispose()
    # And subsequent paint/updatePosition should still not raise
    overlay.paint(None)
    overlay.updatePosition()
    # A Qt qWarning goes from C++ straight to stderr, where pytest.warns cannot see it.
    assert capfd.readouterr().err == ""


def test_the_overlay_places_its_image_through_the_crs_transform():
    """The engine reports bounds in the DEM CRS; the canvas item is placed in the project CRS.
    Ignoring the transform drops the cut/fill image somewhere else on the map, silently."""
    canvas = fake_iface().mapCanvas()
    wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
    transform = QgsCoordinateTransform(UTM, wgs84, QgsProject.instance())
    overlay = PreviewOverlay(canvas, transform)
    dem_bounds = (X0, Y0 - 40.0, X0 + 40.0, Y0)
    overlay.show_change(dem_bounds, np.array([[1.0, -1.0]], dtype=np.float32))
    expected = transform.transformBoundingBox(QgsRectangle(*dem_bounds))
    assert expected.xMinimum() < 20.0                       # degrees, not UTM metres
    for got in (overlay.bounds, overlay.rect()):
        assert got.xMinimum() == pytest.approx(expected.xMinimum())
        assert got.yMinimum() == pytest.approx(expected.yMinimum())
        assert got.xMaximum() == pytest.approx(expected.xMaximum())
        assert got.yMaximum() == pytest.approx(expected.yMaximum())


def test_bounds_that_cannot_be_projected_leave_the_overlay_unshown():
    """`show_change` runs in a slot: a failing projection must not raise out of it."""
    canvas = fake_iface().mapCanvas()
    transform = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"),
                                       QgsCoordinateReferenceSystem("EPSG:3857"),
                                       QgsProject.instance())
    overlay = PreviewOverlay(canvas, transform)
    overlay.show_change((-1e12, -1e12, 1e12, 1e12), np.array([[1.0, -1.0]], dtype=np.float32))
    assert not overlay.isVisible() and overlay.bounds is None
