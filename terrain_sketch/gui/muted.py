"""Secondary text: the palette's own text colour, toned down so it reads as supporting information."""
from __future__ import annotations

from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QLabel

BLEND = 0.45   # how far the text colour moves towards the background


def muted_colour(palette: QPalette) -> QColor:
    """The palette's text colour blended towards its background, so it follows light and dark themes."""
    text = palette.color(QPalette.ColorRole.WindowText)
    back = palette.color(QPalette.ColorRole.Window)
    mix = lambda a, b: round(a + (b - a) * BLEND)   # noqa: E731 — one expression, used three times
    return QColor(mix(text.red(), back.red()), mix(text.green(), back.green()), mix(text.blue(), back.blue()))


class MutedLabel(QLabel):
    """A label in the muted colour that repaints itself when QGIS switches theme."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._apply()

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._apply()
        super().changeEvent(event)

    def _apply(self) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, muted_colour(self.palette()))
        super().setPalette(palette)
