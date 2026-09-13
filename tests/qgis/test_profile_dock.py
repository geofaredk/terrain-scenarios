import pytest

from qgis_helpers import UTM, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.profile_dock import ProfileDock


def test_the_profile_dock_loads_the_selected_feature(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.points[0] == (0.0, 0.0)
    assert dock.cross.points[1][0] == pytest.approx(dike.width / 2.0)
    assert len(dock.long.terrain) == 200 and len(dock.long.points) >= 2
    assert dock.note.text() == ""


def test_editing_the_cross_profile_writes_width_and_slope_back(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, )
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (3.0, 0.0), (15.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.width == pytest.approx(6.0)
    assert updated.slope_n == pytest.approx(3.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)


def test_symmetric_mirrors_the_edit_to_the_other_side(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(True)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)))
    updated = c.feature(dike.id)
    assert updated.cross_left == updated.cross_right == ((4.0, -1.0),)
    dock.symmetric.setChecked(False)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (2.0, 0.0), (8.0, -2.0), (14.0, -4.0)))
    after = c.feature(dike.id)
    assert after.cross_right == ((6.0, -2.0),) and after.cross_left == ((4.0, -1.0),)


def test_editing_the_long_profile_makes_it_custom_and_reset_restores_the_rule(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, )
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.long.profileCommitted.emit(((0.0, 14.0), (29.0, 14.0)))
    assert c.feature(dike.id).long_profile == ((0.0, 14.0), (29.0, 14.0))
    assert dock.note.text() and dock.reset_long.isEnabled()
    assert sample(c.layers.working, 20, 20) == pytest.approx(14.0)
    dock.reset_long.click()
    assert c.feature(dike.id).long_profile is None
    assert dock.note.text() == ""


def test_an_area_feature_gets_a_read_only_long_panel(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert not dock.long.editable and dock.note.text()
    assert not dock.symmetric.isEnabled()


def test_the_dock_clears_when_the_selection_or_the_session_goes(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.points
    dock.show_feature(None)
    assert dock.cross.points == [] and dock.long.points == []
    dock.show_feature(dike.id)
    c.close()
    assert dock.cross.points == []


def test_deleting_the_shown_feature_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    c.delete_feature(dike.id)  # the Delete button, still showing this feature's profiles
    assert dock.cross.points == [] and dock.long.points == []


def test_a_custom_long_profile_disables_the_height_field(tmp_path):
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount.isEnabled()
    c.update_feature(dike.id, long_profile=((0.0, 14.0), (29.0, 14.0)))
    page.show_feature(dike.id)
    assert not page.amount.isEnabled() and "fixed" in page.amount.toolTip()
