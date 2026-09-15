"""The line an area's section runs along (spec §5.4): drawn on the map, shown there, undone, reset."""
import numpy as np
import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import SECTION_LINE_HINT, UNDO_SECTION_LINE
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.gui.map_tools.draw_line import DrawLineTool
from terrain_sketch.gui.profile_dock import ProfileDock
from terrain_sketch.qgis_io.convert import from_wkb


def pond_and_dike(c):
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 35, 34, 35), UTM)
    return pond, dike


def panels(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    profiles = ProfileDock(controller)
    dock = MainDock(iface, controller, profiles)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, profiles, dock


def test_a_drawn_section_line_is_stored_in_the_dem_crs_as_one_undo_step(tmp_path):
    c = start_session(tmp_path)
    pond, _dike = pond_and_dike(c)
    terrain = c.stack.working.data.copy()
    web = QgsCoordinateReferenceSystem("EPSG:3857")
    drawn = QgsGeometry(line_through(20, 5, 20, 35))
    drawn.transform(QgsCoordinateTransform(UTM, web, QgsProject.instance()))
    steps = c.undo_stack.count()
    assert c.set_section_line(pond.id, drawn, web)
    stored = from_wkb(c.find(pond.id).section_line)
    assert stored.asPolyline()[0].x() == pytest.approx(line_through(20, 5, 20, 35).asPolyline()[0].x(), abs=0.01)
    assert c.undo_stack.count() == steps + 1 and c.undo_stack.undoText() == UNDO_SECTION_LINE.format(pond.name)
    assert np.array_equal(c.stack.working.data, terrain)          # the terrain does not change
    assert c.is_dirty                                             # but the scenario file holds the line
    c.undo_stack.undo()
    assert c.find(pond.id).section_line is None


def test_resetting_the_line_goes_back_to_the_default_through_the_middle(tmp_path):
    c = start_session(tmp_path)
    pond, _dike = pond_and_dike(c)
    default = c.section_line(pond.id)
    c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert c.section_line(pond.id) != default
    assert c.set_section_line(pond.id, None)
    assert c.find(pond.id).section_line is None and c.section_line(pond.id) == default


def test_only_an_area_that_still_exists_takes_a_section_line(tmp_path):
    c = start_session(tmp_path)
    pond, dike = pond_and_dike(c)
    steps = c.undo_stack.count()
    assert not c.set_section_line(dike.id, line_through(20, 5, 20, 35), UTM)
    assert c.section_line(dike.id) is None
    c.delete_feature(pond.id)
    assert not c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert c.undo_stack.count() == steps + 1                     # only the delete


def test_a_drawing_that_is_not_a_line_is_a_message(tmp_path):
    c = start_session(tmp_path)
    pond, _dike = pond_and_dike(c)
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    assert not c.set_section_line(pond.id, square(1, 1, 5, 5), UTM)
    assert heard and c.find(pond.id).section_line is None


def test_the_profiles_panel_offers_the_section_buttons_for_an_area_only(tmp_path):
    c = start_session(tmp_path)
    pond, dike = pond_and_dike(c)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert not dock.draw_section.isHidden() and not dock.reset_section.isHidden() and dock.reset_long.isHidden()
    assert dock.draw_section.isEnabled() and not dock.reset_section.isEnabled()   # nothing to reset yet
    asked = []
    dock.drawSectionRequested.connect(asked.append)
    dock.draw_section.click()
    assert asked == [pond.id]
    c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert dock.reset_section.isEnabled()
    dock.reset_section.click()
    assert c.find(pond.id).section_line is None
    dock.show_feature(dike.id)
    assert dock.draw_section.isHidden() and dock.reset_section.isHidden() and not dock.reset_long.isHidden()


def test_draw_section_line_puts_a_line_tool_on_the_map_and_stores_what_is_drawn(tmp_path):
    iface, c, profiles, dock = panels(tmp_path)
    pond, _dike = pond_and_dike(c)
    dock.feature_view.select_id(pond.id)
    profiles.draw_section.click()
    canvas = iface.mapCanvas()
    assert isinstance(dock.draw_tool, DrawLineTool) and canvas.mapTool() is dock.draw_tool
    assert dock.hint.text() == SECTION_LINE_HINT
    dock.draw_tool.finished.emit(line_through(20, 5, 20, 35))
    assert dock.draw_tool is None and c.find(pond.id).section_line is not None
    assert len(c.features) == 2                                  # a section line, not a new feature
    assert profiles.long.points[-1][0] == pytest.approx(30.0)    # the section now runs along it


def test_the_map_shows_the_section_line_of_the_selected_area(tmp_path):
    _iface, c, _profiles, dock = panels(tmp_path)
    pond, dike = pond_and_dike(c)
    dock.feature_view.select_id(pond.id)
    shown = dock.section_band.asGeometry()
    assert not shown.isEmpty() and shown.asWkt(3) == from_wkb(c.section_line(pond.id)).asWkt(3)
    c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert dock.section_band.asGeometry().asWkt(3) == from_wkb(c.find(pond.id).section_line).asWkt(3)
    dock.feature_view.select_id(dike.id)
    assert dock.section_band.asGeometry().isEmpty()


def test_finishing_a_section_line_for_an_area_that_was_undone_adds_nothing(tmp_path):
    _iface, c, profiles, dock = panels(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.select_id(pond.id)
    profiles.draw_section.click()
    tool = dock.draw_tool
    c.undo_stack.undo()                                          # the pond goes while the line is drawn
    tool.finished.emit(line_through(20, 5, 20, 35))
    assert c.features == () and dock.draw_tool is None
