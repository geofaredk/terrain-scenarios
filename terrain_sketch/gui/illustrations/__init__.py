"""Theme-aware SVG illustrations: templates with colour tokens, rendered through QSvgRenderer.

The templates are plain SVG with `{terrain}`, `{line}`, `{fill}`, `{cut}` and `{text}` where a
colour belongs. The tokens are filled from the active QPalette — so the pictures follow QGIS's
light or dark theme — except fill and cut, which stay the map's orange and blue so a picture and
the canvas mean the same thing.
"""
from __future__ import annotations

import pathlib

from qgis.PyQt.QtCore import QByteArray, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer

from ..overlay import CUT, FILL

HERE = pathlib.Path(__file__).parent
HIGHLIGHT_OPACITY = "1"
DIMMED_OPACITY = "0.25"


def colours(palette: QPalette) -> dict:
    """The token values for a palette. Fill and cut are fixed so pictures match the map."""
    return {
        "terrain": palette.color(QPalette.ColorRole.Mid).name(),
        "line": palette.color(QPalette.ColorRole.Highlight).name(),
        "text": palette.color(QPalette.ColorRole.WindowText).name(),
        "fill": QColor(*FILL).name(),
        "cut": QColor(*CUT).name(),
    }


def svg_source(name: str, palette: QPalette, highlight: str | None = None) -> str:
    """The template with its colour tokens filled in, and one part optionally emphasised.

    A template tags a part by putting `{opacity-<key>}` where that part's `opacity` value goes.
    When `highlight` names one key, every other tagged part is dimmed, so the same drawing can
    point at width, height, slope or reach depending on which field has focus. A `highlight` this
    template does not tag emphasises nothing rather than dimming the whole picture: renaming a
    part key in an SVG must not silently turn the diagram grey.
    """
    text = (HERE / f"{name}.svg").read_text()
    for token, value in colours(palette).items():
        text = text.replace("{" + token + "}", value)
    keys = tagged_parts(text)
    if highlight not in keys:
        highlight = None
    for key in keys:
        opacity = HIGHLIGHT_OPACITY if highlight is None or key == highlight else DIMMED_OPACITY
        text = text.replace("{opacity-" + key + "}", opacity)
    return text


def tagged_parts(source: str) -> list[str]:
    """The part keys a template exposes, in the order they appear."""
    keys, rest = [], source
    while "{opacity-" in rest:
        start = rest.index("{opacity-") + len("{opacity-")
        end = rest.index("}", start)
        key = rest[start:end]
        if key not in keys:
            keys.append(key)
        rest = rest[end:]
    return keys


def pixmap(name: str, size, palette: QPalette, highlight: str | None = None) -> QPixmap:
    """Render an illustration at `size` (a QSize or an int for a square)."""
    if isinstance(size, int):
        from qgis.PyQt.QtCore import QSize
        size = QSize(size, size)
    renderer = QSvgRenderer(QByteArray(svg_source(name, palette, highlight).encode()))
    out = QPixmap(size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    try:
        renderer.render(painter, QRectF(0, 0, size.width(), size.height()))
    finally:
        painter.end()  # a QPainter still active when its paint device dies takes Qt down
    return out


def icon(name: str, size, palette: QPalette) -> QIcon:
    return QIcon(pixmap(name, size, palette))


def available() -> list[str]:
    """Every illustration name that ships with the plugin."""
    return sorted(p.stem for p in HERE.glob("*.svg"))
