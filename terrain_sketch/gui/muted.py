"""Secondary text: the palette's own text colour, toned down so it reads as supporting information."""
from __future__ import annotations

import functools

from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QLabel

BLEND = 0.45          # how far the text colour moves towards the background
MIN_CONTRAST = 3.0    # WCAG contrast the muted colour keeps against its background, where the text itself has it
_STEP = 0.01


def _luminance(colour: QColor) -> float:
    """WCAG relative luminance of `colour`."""
    def channel(value: int) -> float:
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(colour.red()) + 0.7152 * channel(colour.green()) + 0.0722 * channel(colour.blue())


def _contrast(a: QColor, b: QColor) -> float:
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _mix(text: QColor, background: QColor, amount: float) -> QColor:
    return QColor(*(round(t + (b - t) * amount) for t, b in (
        (text.red(), background.red()), (text.green(), background.green()), (text.blue(), background.blue()))))


@functools.lru_cache(maxsize=64)
def _muted_rgb(text: int, background: int) -> int:
    text_colour, background_colour = QColor.fromRgb(text), QColor.fromRgb(background)
    floor = min(MIN_CONTRAST, _contrast(text_colour, background_colour))
    amount = BLEND
    while amount > 0:
        colour = _mix(text_colour, background_colour, amount)
        if _contrast(colour, background_colour) >= floor:
            return colour.rgb()
        amount -= _STEP
    return text_colour.rgb()


def muted_between(text: QColor, background: QColor) -> QColor:
    """`text` blended towards `background`, for secondary text drawn on that background. The blend
    stops short where going the full way would leave less than `MIN_CONTRAST` against the
    background: a selection highlight is often much closer to its text colour than a window is
    (Qt's light highlight has 3.7:1 against white), and a full blend there cannot be read."""
    return QColor.fromRgb(_muted_rgb(text.rgb(), background.rgb()))


def muted_colour(palette: QPalette) -> QColor:
    """The palette's window text colour muted against the window colour, for labels on a panel."""
    return muted_between(palette.color(QPalette.ColorRole.WindowText), palette.color(QPalette.ColorRole.Window))


class MutedLabel(QLabel):
    """A label in the muted colour that repaints itself when QGIS switches theme."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._applying = False
        self._apply()

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange and not self._applying:
            self._apply()
        super().changeEvent(event)

    def _apply(self) -> None:
        """Set the muted colour on this label's own palette.

        `QWidget.setPalette` sends `PaletteChange` straight back to this label, synchronously, so
        `changeEvent` re-enters here while the call is still running. Two things keep that from
        blending the colour a second time: the source colour always comes from the inherited
        palette (the parent's, or the application's with no parent yet), never from
        `self.palette()`, which already holds the muted colour; and `_applying` returns early from
        the re-entrant call. Blending the label's own colour again on every re-entry converges on
        the background within about nine passes, leaving the text invisible."""
        if self._applying:
            return
        self._applying = True
        try:
            parent = self.parentWidget()
            source = parent.palette() if parent is not None else QApplication.palette()
            colour = muted_colour(source)
            palette = self.palette()
            if palette.color(QPalette.ColorRole.WindowText) == colour:
                return   # already applied — nothing to change, and nothing to re-blend
            palette.setColor(QPalette.ColorRole.WindowText, colour)
            super().setPalette(palette)
        finally:
            self._applying = False
