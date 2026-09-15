"""Secondary text drawn in a colour derived from the palette, never hard-coded."""
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QWidget

from terrain_sketch.gui.muted import MutedLabel, muted_colour


def palette_of(text: str, window: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    palette.setColor(QPalette.ColorRole.Text, QColor(text))
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.Base, QColor(window))
    return palette


def test_muted_text_sits_between_the_text_and_the_background():
    light = muted_colour(palette_of("#000000", "#ffffff"))
    assert 100 < light.red() < 160 and light.red() == light.green() == light.blue()
    dark = muted_colour(palette_of("#ffffff", "#000000"))
    assert 100 < dark.red() < 160          # readable in both themes, never the background itself


def test_the_label_follows_a_theme_change():
    parent = QWidget()
    parent.setPalette(palette_of("#000000", "#ffffff"))
    label = MutedLabel("Raise path", parent)
    was = label.palette().color(QPalette.ColorRole.WindowText)
    parent.setPalette(palette_of("#ffffff", "#000000"))
    assert label.palette().color(QPalette.ColorRole.WindowText) != was
