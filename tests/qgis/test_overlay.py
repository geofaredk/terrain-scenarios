import numpy as np

from qgis_helpers import fake_iface
from terrain_sketch.gui.overlay import change_image, PreviewOverlay


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
    n0 = len(canvas.scene().items())
    overlay = PreviewOverlay(canvas)
    # Showing the overlay adds it to the scene
    change = np.array([[1.0, -1.0]], dtype=np.float32)
    overlay.show_change((0.0, 0.0, 10.0, 10.0), change)
    n_with = len(canvas.scene().items())
    assert n_with > n0  # overlay was added to the scene
    overlay.dispose()
    n_after = len(canvas.scene().items())
    assert n_after == n0  # overlay was removed from the scene
    # Should not raise even after dispose
    overlay.paint(None)
    overlay.updatePosition()


def test_preview_overlay_dispose_twice_is_safe_and_silent():
    canvas = fake_iface().mapCanvas()
    overlay = PreviewOverlay(canvas)
    change = np.array([[1.0, -1.0]], dtype=np.float32)
    overlay.show_change((0.0, 0.0, 10.0, 10.0), change)
    overlay.dispose()
    # Second dispose should not emit a warning or raise
    overlay.dispose()
    # And subsequent paint/updatePosition should still not raise
    overlay.paint(None)
    overlay.updatePosition()
