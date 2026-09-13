import numpy as np

from terrain_sketch.gui.overlay import change_image


def test_the_change_image_is_warm_for_fill_and_cool_for_cut():
    change = np.array([[0.0, 2.0], [-2.0, 0.0]], dtype=np.float32)
    image = change_image(change)
    assert image is not None and image.width() == 2 and image.height() == 2
    assert image.pixelColor(1, 0).red() > image.pixelColor(1, 0).blue()    # fill: warm
    assert image.pixelColor(0, 1).blue() > image.pixelColor(0, 1).red()    # cut: cool
    assert image.pixelColor(0, 0).alpha() == 0                            # unchanged: invisible


def test_an_unchanged_window_makes_no_image():
    assert change_image(np.zeros((4, 4), dtype=np.float32)) is None
