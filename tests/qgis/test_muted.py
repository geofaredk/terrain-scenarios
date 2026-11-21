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
    """The exact expected colour, not merely one that differs from before: a label that re-blends
    its already-muted colour off its own `setPalette` converges on the background, a colour that
    also differs from before while being invisible."""
    light = palette_of("#000000", "#ffffff")
    dark = palette_of("#ffffff", "#000000")
    parent = QWidget()
    parent.setPalette(light)
    label = MutedLabel("Raise path", parent)
    assert label.palette().color(QPalette.ColorRole.WindowText) == muted_colour(light)
    parent.setPalette(dark)
    assert label.palette().color(QPalette.ColorRole.WindowText) == muted_colour(dark)


def test_the_muted_colour_is_computed_from_the_inherited_palette_not_its_own():
    """`MutedLabel._apply` calls `setPalette`, which — because `QWidget.setPalette` always sends
    `QEvent.Type.PaletteChange` synchronously back to the same widget — re-enters `changeEvent` ->
    `_apply` immediately. Computing the muted colour from the label's own palette on that
    re-entrant call would blend the *already-muted* colour again; repeated (~9 times, verified by
    probe) that converges the text within a shade of the background — invisible in both themes.
    The colour must come from the label's PARENT's palette (or the application's, with no parent),
    never `self.palette()`, so the result is exact and stable however often this re-enters."""
    from qgis.PyQt.QtWidgets import QApplication

    light = palette_of("#000000", "#ffffff")
    parent = QWidget()
    parent.setPalette(light)
    label = MutedLabel("Sketching on: dem", parent)
    QApplication.processEvents()
    expected = muted_colour(parent.palette())
    actual = label.palette().color(QPalette.ColorRole.WindowText)
    assert actual == expected, f"expected {expected.getRgb()}, got {actual.getRgb()} (blended towards the background)"
    # nowhere near the background itself, which a runaway self-blend converges towards
    background = parent.palette().color(QPalette.ColorRole.Window)
    assert actual != background
