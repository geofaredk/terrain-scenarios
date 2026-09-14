import pytest
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QPalette

from terrain_sketch.core.tools import PixelMode, Tool
from terrain_sketch.gui import illustrations
from terrain_sketch.gui.overlay import CUT, FILL


def light() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Mid, QColor(140, 140, 140))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(20, 80, 200))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(10, 10, 10))
    return palette


def dark() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Mid, QColor(90, 90, 90))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(120, 180, 255))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 240))
    return palette


def test_every_tool_and_pixel_mode_has_an_illustration():
    names = illustrations.available()
    for tool in Tool:
        assert f"tool_{tool.value}" in names, f"no illustration for {tool.value}"
    for mode in PixelMode:
        assert f"pixels_{mode.value}" in names, f"no illustration for {mode.value}"
    assert "parameters" in names


def test_no_colour_token_survives_rendering():
    for name in illustrations.available():
        source = illustrations.svg_source(name, light())
        assert "{" not in source and "}" not in source, f"{name} kept an unfilled token"


def test_the_palette_drives_the_colours_so_the_theme_is_followed():
    light_source = illustrations.svg_source("tool_raise_path", light())
    dark_source = illustrations.svg_source("tool_raise_path", dark())
    assert "#8c8c8c" in light_source and "#5a5a5a" in dark_source
    assert light_source != dark_source


def test_fill_and_cut_stay_the_map_colours_in_both_themes():
    fill, cut = QColor(*FILL).name(), QColor(*CUT).name()
    for palette in (light(), dark()):
        assert fill in illustrations.svg_source("tool_raise_path", palette)
        assert cut in illustrations.svg_source("tool_lower_path", palette)


def test_the_parameter_diagram_exposes_the_parts_the_fields_control():
    assert illustrations.tagged_parts(open(
        illustrations.HERE / "parameters.svg").read()) == ["width", "amount", "slope", "reach"]


def test_highlighting_one_part_dims_the_others():
    source = illustrations.svg_source("parameters", light(), highlight="slope")
    assert source.count('opacity="0.25"') == 3 and source.count('opacity="1"') == 1
    every = illustrations.svg_source("parameters", light())
    assert every.count('opacity="1"') == 4 and '0.25' not in every


def test_an_unknown_highlight_leaves_every_part_visible():
    source = illustrations.svg_source("parameters", light(), highlight="nope")
    assert source.count('opacity="0.25"') == 4


def test_every_illustration_renders_to_a_non_blank_pixmap():
    palette = light()
    for name in illustrations.available():
        image = illustrations.pixmap(name, QSize(64, 64), palette).toImage()
        assert image.size() == QSize(64, 64), name
        painted = sum(1 for y in range(0, 64, 2) for x in range(0, 64, 2)
                      if image.pixelColor(x, y).alpha() > 0)
        assert painted > 20, f"{name} rendered almost nothing ({painted} samples painted)"


def test_a_square_size_may_be_given_as_a_plain_int():
    assert illustrations.pixmap("tool_add", 48, light()).size() == QSize(48, 48)


def test_the_three_pixel_modes_really_do_look_different():
    palette = light()
    shots = [illustrations.pixmap(f"pixels_{m.value}", 64, palette).toImage() for m in PixelMode]
    def signature(image):
        return tuple(image.pixelColor(x, y).alpha() > 0
                     for y in range(8, 56, 4) for x in range(8, 56, 4))
    assert len(set(signature(s) for s in shots)) == 3
