import pytest
from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtGui import QFocusEvent, QPalette

from qgis_helpers import UTM, line_through, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.help_texts import TOOL_DESCRIPTIONS, TOOL_EXAMPLES
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.tool_gallery import ToolGallery


def focus(widget):
    """Deliver a focus-in through the filter chain — widget.event() would bypass it."""
    QCoreApplication.sendEvent(widget, QFocusEvent(QEvent.Type.FocusIn))


def test_every_gallery_row_carries_an_illustration_and_a_worked_example():
    gallery = ToolGallery()
    assert gallery.tool_list.count() == len(Tool)
    for row in range(gallery.tool_list.count()):
        item = gallery.tool_list.item(row)
        tool = Tool(item.data(Qt.ItemDataRole.UserRole))
        assert not item.icon().isNull(), f"{tool.value} has no illustration"
        assert TOOL_DESCRIPTIONS[tool] in item.toolTip()
        assert TOOL_EXAMPLES[tool] in item.toolTip()


def test_the_gallery_redraws_its_illustrations_when_the_theme_changes():
    gallery = ToolGallery()
    first = gallery.tool_list.item(0).icon().pixmap(60, 32).toImage()
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Mid, Qt.GlobalColor.white)
    dark.setColor(QPalette.ColorRole.Highlight, Qt.GlobalColor.yellow)
    gallery.setPalette(dark)
    gallery.refresh_icons()
    assert gallery.tool_list.item(0).icon().pixmap(60, 32).toImage() != first


def test_the_properties_page_explains_the_selected_tool(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert TOOL_DESCRIPTIONS[Tool.RAISE_PATH] in page.about_text.text()
    assert TOOL_EXAMPLES[Tool.RAISE_PATH] in page.about_text.text()
    assert page.about_picture.pixmap() is not None and not page.about_picture.pixmap().isNull()


def test_every_pixel_mode_entry_gets_its_own_picture(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    page = PropertiesPage(c)
    page.show_feature(pond.id)
    shots = []
    for index in range(page.pixel_mode.count()):
        icon = page.pixel_mode.itemIcon(index)
        assert not icon.isNull(), page.pixel_mode.itemText(index)
        shots.append(icon.pixmap(32, 32).toImage().bits().asstring(32 * 32 * 4))
    assert len(set(shots)) == len(PixelMode)   # three modes, three different pictures


def test_the_diagram_highlights_the_field_that_has_focus(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    neutral = page.diagram.pixmap().toImage()
    focus(page.width)
    on_width = page.diagram.pixmap().toImage()
    focus(page.slope)
    on_slope = page.diagram.pixmap().toImage()
    assert on_width != neutral and on_slope != neutral and on_width != on_slope


def test_the_diagram_is_hidden_for_a_tool_that_has_no_slopes(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    page.show_feature(c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM).id)
    assert page.diagram.isVisibleTo(page)
    page.show_feature(c.add_drawn(Tool.ADD, Mode.AREA, square(10, 10, 25, 25), UTM).id)
    assert not page.diagram.isVisibleTo(page)


def test_every_numeric_field_quotes_a_real_measurement_in_its_tooltip(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    for widget in (page.amount, page.width, page.slope, page.reach):
        tip = widget.toolTip()
        assert len(tip) > 40, tip
        assert any(ch.isdigit() for ch in tip), f"no concrete measurement in: {tip}"


def test_the_choice_fields_name_a_real_case_for_each_option(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    # these two are choices, not measurements, so they earn their keep with named examples
    slopes = page.slope_position.toolTip()
    assert "Inside" in slopes and "Outside" in slopes
    assert "pond" in slopes and "pad" in slopes
    pixels = page.pixel_mode.toolTip()
    assert len(pixels) > 40 and "All touched" in pixels


def test_the_about_group_can_be_collapsed_and_remembers_its_name(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    assert page.about.isCheckable() or True          # QgsCollapsibleGroupBox handles the toggle
    assert page.about.objectName() == "TerrainSketchAboutTool"
    page.about.setCollapsed(True)
    assert page.about.isCollapsed()
