import pytest

from qgis_helpers import UTM, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.tool_gallery import ToolGallery


def test_gallery_offers_only_the_modes_a_tool_supports():
    gallery = ToolGallery()
    assert not gallery.line_button.isEnabled() and not gallery.area_button.isEnabled()
    gallery.select_tool(Tool.RAISE_PATH)
    assert gallery.line_button.isEnabled() and not gallery.area_button.isEnabled()
    gallery.select_tool(Tool.LOWER_FLAT)
    requests = []
    gallery.drawRequested.connect(lambda tool, mode: requests.append((tool, mode)))
    gallery.area_button.click()
    assert requests == [(Tool.LOWER_FLAT, Mode.AREA)]


def test_properties_show_the_tool_fields_and_apply_changes(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount_label.text() == "Height"
    assert page.form.isRowVisible(page.width) and page.form.isRowVisible(page.slope)
    assert not page.form.isRowVisible(page.slope_position)
    page.amount.setValue(2.5)
    assert c.feature(dike.id).amount == 2.5 and sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    page.show_feature(pond.id)
    assert page.amount_label.text() == "Depth" and not page.form.isRowVisible(page.width)
    assert page.form.isRowVisible(page.slope_position) and page.slope_position.currentData() is True
    page.pixel_mode.setCurrentIndex(page.pixel_mode.findData(PixelMode.ALL_TOUCHED.value))
    assert c.feature(pond.id).pixel_mode is PixelMode.ALL_TOUCHED
