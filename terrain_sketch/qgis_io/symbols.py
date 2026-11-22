"""A feature's outline symbol as text: the plugin's default look, and symbol XML that compares equal
for equal symbols (QGIS gives every symbol layer a fresh random id when it saves one)."""
from __future__ import annotations

import re

from qgis.core import QgsFillSymbol, QgsReadWriteContext, QgsSymbol, QgsSymbolLayerUtils
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtXml import QDomDocument

_ID_ATTRIBUTE = re.compile(r' id="[^"]*"')


def default_symbol() -> QgsFillSymbol:
    """The outline look of a feature with no style of its own: a dashed dark outline, no fill."""
    return QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "35,35,35,255", "outline_width": "0.5", "outline_style": "dash"})


def to_xml(symbol: QgsSymbol) -> str:
    """The symbol as XML text, without the symbol-layer ids, so equal symbols give equal text."""
    doc = QDomDocument()
    doc.appendChild(QgsSymbolLayerUtils.saveSymbol("symbol", symbol, doc, QgsReadWriteContext()))
    return _ID_ATTRIBUTE.sub("", doc.toString())


def from_xml(text: str | None) -> QgsFillSymbol | None:
    """The fill symbol saved in `text`; None for no text, text that is not a symbol, or a non-fill symbol."""
    if not text:
        return None
    doc = QDomDocument()
    doc.setContent(text)  # its result's type differs between PyQt versions; an empty document tells instead
    if doc.documentElement().isNull():
        return None
    symbol = QgsSymbolLayerUtils.loadSymbol(doc.documentElement(), QgsReadWriteContext())
    return symbol if isinstance(symbol, QgsFillSymbol) else None


def style_of(symbol: QgsSymbol | None) -> str | None:
    """What a feature stores for `symbol`: None for no symbol or the default look, else its XML."""
    if symbol is None:
        return None
    text = to_xml(symbol)
    return None if text == to_xml(default_symbol()) else text


def preview_pixmap(symbol: QgsSymbol, size: QSize) -> QPixmap:
    """A small picture of the symbol, as QGIS shows one in its symbol lists."""
    return QgsSymbolLayerUtils.symbolPreviewPixmap(symbol, size, 0)
