"""Feature symbols as text: what is saved in the scenario file and compared with the layer's symbology."""
from qgis.core import QgsFillSymbol, QgsLineSymbol
from qgis.PyQt.QtCore import QSize

from terrain_sketch.qgis_io.symbols import default_symbol, from_xml, preview_pixmap, style_of, to_xml


def _red():
    return QgsFillSymbol.createSimple({"color": "255,0,0,255"})


def test_equal_symbols_give_equal_xml():
    assert to_xml(default_symbol()) == to_xml(default_symbol())
    assert to_xml(default_symbol()) != to_xml(_red())


def test_xml_round_trips_a_symbol():
    red = _red()
    assert to_xml(from_xml(to_xml(red))) == to_xml(red)


def test_the_default_symbol_is_no_style():
    assert style_of(default_symbol()) is None and style_of(None) is None
    assert style_of(_red()) == to_xml(_red())


def test_from_xml_rejects_what_is_not_a_fill_symbol():
    line = QgsLineSymbol.createSimple({})
    assert from_xml(None) is None and from_xml("") is None and from_xml("not xml") is None
    assert from_xml(to_xml(line)) is None


def test_preview_pixmap_has_the_asked_size():
    pixmap = preview_pixmap(_red(), QSize(24, 16))
    assert not pixmap.isNull() and (pixmap.width(), pixmap.height()) == (24, 16)
