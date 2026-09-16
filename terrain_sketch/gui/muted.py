"""Secondary text: the palette's own text colour, toned down so it reads as supporting information."""
from __future__ import annotations

from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QApplication, QLabel

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
        self._applying = False
        self._apply()

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange and not self._applying:
            self._apply()
        super().changeEvent(event)

    def _apply(self) -> None:
        """CRITICAL 1 fix: `setPalette` below always sends `QEvent.Type.PaletteChange` straight
        back to this same label (`QWidget.setPalette` does this synchronously, unconditionally),
        which `changeEvent` catches and used to call `_apply` again — reading the colour back from
        `self.palette()`, which by then already held the *muted* colour from the call just made,
        and blending that another `BLEND` fraction towards the background. Repeated, that
        converges the text within a shade of the background inside a handful of re-entries
        (verified by probe: about 9 passes) — invisible in both themes.

        Two independent fixes, either alone would do it, kept together for safety: the source
        colour always comes from the INHERITED palette — this label's parent, or the application's
        with no parent yet — never `self.palette()`, so re-entering this can only ever recompute
        the same exact colour, never blend further; and `_applying` blocks the re-entrant call
        outright, so `changeEvent` never even calls back into this while it is still running."""
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
