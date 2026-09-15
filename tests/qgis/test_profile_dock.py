import pytest
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent

from qgis_helpers import UTM, line_layer, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.help_texts import (AREA_LONG_SECTION_HINT, AREA_LONG_SECTION_NOTE,
                                           MULTIPART_LONG_SECTION_NOTE)
from terrain_sketch.gui.profile_dock import ProfileDock


def test_the_profile_dock_loads_the_selected_feature(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.mirrored                                     # both sides of the path
    assert (-dike.width / 2.0, 0.0) in dock.cross.points and (dike.width / 2.0, 0.0) in dock.cross.points
    assert dock.cross.points[0][0] == -dock.cross.points[-1][0] < 0.0
    assert len(dock.long.terrain) == 200 and len(dock.long.points) >= 2
    assert dock.note.text() == ""


def test_editing_the_cross_profile_writes_width_and_slope_back(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, )
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((-15.0, -4.0), (-3.0, 0.0), (3.0, 0.0), (15.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.width == pytest.approx(6.0)
    assert updated.slope_n == pytest.approx(3.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)


def test_symmetric_mirrors_the_edit_to_the_other_side(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=10.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(True)
    # a berm added on the right; the left side is still as it was
    dock.cross.profileCommitted.emit(((-12.0, -10.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)))
    updated = c.feature(dike.id)
    assert updated.cross_left == updated.cross_right == ((4.0, -1.0),)
    dock.symmetric.setChecked(False)
    assert dock.cross.points == [(-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)]
    dock.cross.profileCommitted.emit(((-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (8.0, -2.0), (14.0, -4.0)))
    after = c.feature(dike.id)
    assert after.cross_right == ((6.0, -2.0),) and after.cross_left == ((4.0, -1.0),)


def test_the_side_slope_is_shared_between_the_sides_and_the_tip_says_so(tmp_path):
    """`slope_n` and `reach` are single per-feature fields (spec 5.4), so unticking Symmetric
    cannot stop them applying to both sides. The tooltip has to say that rather than promise
    that every edit is mirrored only while it is ticked."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=20.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(False)
    # only the right slope's end moves; the left side is still as it was
    dock.cross.profileCommitted.emit(((-22.0, -20.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (14.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.slope_n == pytest.approx(3.0) and updated.reach == pytest.approx(12.0)
    tip = dock.symmetric.toolTip()
    assert "break point" in tip.lower() and "both sides" in tip
    assert "every cross-profile edit" not in tip


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
    assert not dock.long.editable and not dock.symmetric.isEnabled()
    # there is no section through an area yet, so the panel says so instead of painting nothing
    assert dock.long.points == [] and dock.long.terrain == []
    assert dock.long.hint == AREA_LONG_SECTION_HINT
    assert dock.note.text() == AREA_LONG_SECTION_NOTE
    # and it never tells a user to select a feature they have already selected
    assert "Select or draw a feature" not in dock.long.hint
    assert "read-only section through the feature" not in dock.note.text()


def two_part_dike(controller):
    """One RAISE_PATH feature whose geometry has two separate line parts."""
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    return controller.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)


def test_a_multi_part_path_gets_a_read_only_long_panel_and_keeps_its_height_field(tmp_path):
    """The engine applies a custom long profile only to a single-part path, so offering one here
    would store the user's drags, disable Height, and change no terrain at all."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = two_part_dike(c)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert not dock.long.editable
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    assert not dock.reset_long.isEnabled()
    assert not c.long_section(dike.id)["custom"]

    # even with one already stored (an earlier version, or a path that was later extended)
    c.update_feature(dike.id, long_profile=((0.0, 20.0), (10.0, 20.0)))
    dock.show_feature(dike.id)
    assert not c.long_section(dike.id)["custom"]
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount.isEnabled()          # Height still drives the result, so it stays editable
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)   # the rule, not the 20 m profile


def test_an_area_cross_profile_refuses_break_points(tmp_path):
    """Break points are not supported for areas in v1 (spec 5.4): the engine discards them."""
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert dock.cross.editable and not dock.cross.allow_breaks
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 35, 34, 35), UTM)
    dock.show_feature(dike.id)
    assert dock.cross.allow_breaks


def test_editing_an_areas_cross_profile_stores_no_break_points(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)))
    updated = c.feature(pond.id)
    assert updated.cross_right == () and updated.cross_left == ()
    assert updated.reach == pytest.approx(8.0)      # the terminal slope still writes back


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


def mouse(widget, kind, point):
    event = QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent, QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent}[kind](event)


def test_undoing_the_shown_feature_during_a_drag_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    cross = dock.cross
    cross.resize(400, 200)
    handle = cross._to_screen(*cross.points[1])
    mouse(cross, QEvent.Type.MouseButtonPress, handle)
    assert cross._dragging == 1
    c.undo_stack.undo()                            # Ctrl+Z in the Profiles panel undoes the Add
    assert c.features == () and cross.points == []
    mouse(cross, QEvent.Type.MouseMove, handle + QPointF(20, -20))
    mouse(cross, QEvent.Type.MouseButtonRelease, handle + QPointF(20, -20))
    assert c.features == ()


def test_the_properties_page_follows_a_cross_profile_drag(tmp_path):
    """A drag moves the width, slope and reach. A page still showing the old values would write the
    old width back with the next arrow step on any of them."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((-7.0, -1.2), (-2.5, 0.0), (2.5, 0.0), (7.0, -1.2)))
    updated = c.feature(dike.id)
    assert (updated.width, updated.slope_n, updated.reach) == pytest.approx((5.0, 3.75, 4.5))
    assert page.width.value() == pytest.approx(5.0) and page.reach.value() == pytest.approx(4.5)
    assert page.slope.value() == pytest.approx(3.8)            # shown to its one decimal
    assert c.feature(dike.id).slope_n == pytest.approx(3.75)   # and not written back rounded


def test_the_left_side_of_a_path_can_be_given_its_own_berm(tmp_path):
    """Until the whole cross-section was shown, only the right side could be edited."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=10.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(False)
    right = [p for p in dock.cross.points if p[0] > 0.0]
    dock.cross.profileCommitted.emit(((-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), *right))
    updated = c.feature(dike.id)
    assert updated.cross_left == ((4.0, -1.0),) and updated.cross_right == ()
    assert (updated.width, updated.slope_n, updated.reach) == pytest.approx((4.0, 3.0, 10.0))
    assert sample(c.layers.working, 20, 16) > sample(c.layers.working, 20, 24)   # north is left of an eastward path


def test_the_symmetric_box_tells_the_plot_to_move_mirror_handles_together(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.symmetric
    dock.symmetric.setChecked(False)
    assert not dock.cross.symmetric


def test_the_cross_plot_explains_its_sides_only_for_a_path_it_can_edit(tmp_path):
    from terrain_sketch.gui.help_texts import CROSS_SIDES_TIP
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 25, 25, 35), UTM)
    band = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 5, 34, 5), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.toolTip() == CROSS_SIDES_TIP
    for other in (pond.id, band.id, None):
        dock.show_feature(other)
        assert dock.cross.toolTip() == "", other
