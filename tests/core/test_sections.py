from dataclasses import replace

import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, multi_wkb, polygon_wkb
from terrain_sketch.core.sections import (cross_section, default_section_line, long_section, section_along,
                                          set_cross_section, set_whole_cross_section, supports_long_profile,
                                          whole_cross_section)
from terrain_sketch.core.tools import Mode, Tool


def dike(**kw):
    return feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(5, 20), (35, 20)]), **kw)


def test_cross_section_runs_from_the_centre_over_the_crest_and_down_the_slope():
    points = cross_section(dike(width=4.0, slope_n=3.0, reach=20.0, amount=2.0))
    assert points[0] == (0.0, 0.0)
    assert points[1] == (2.0, 0.0)          # half the width: the crest edge
    assert points[-1][0] == pytest.approx(22.0)   # edge + reach
    assert points[-1][1] == pytest.approx(-20.0 / 3.0)  # a raise tool slopes down


def test_a_break_point_becomes_a_berm_in_the_section():
    points = cross_section(dike(width=4.0, slope_n=2.0, reach=10.0, cross_right=((3.0, -1.0),)))
    assert (5.0, -1.0) in points           # 2.0 edge + 3.0 beyond it
    assert points[-1][0] == pytest.approx(12.0)


def test_the_two_sides_can_differ():
    f = dike(width=4.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5),))
    assert cross_section(f, side=-1)[2] == (4.0, -0.5)
    assert cross_section(f, side=1)[2] == (6.0, -1.5)


def test_editing_the_section_writes_back_width_slope_and_breaks():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (3.0, 0.0), (8.0, -1.0), (14.0, -3.0)])
    assert changes["width"] == pytest.approx(6.0)          # the edge moved to 3.0
    assert changes["cross_right"] == ((5.0, -1.0),)        # stored relative to the edge
    assert changes["slope_n"] == pytest.approx(3.0)        # 6 m run over 2 m rise
    assert changes["reach"] == pytest.approx(11.0)


def test_an_area_section_starts_at_the_outline_itself():
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]),
                   slope_n=2.0, reach=6.0, amount=1.0)
    points = cross_section(pond)
    assert points[0] == (0.0, 0.0) and points[1] == (0.0, 0.0)
    assert points[-1][0] == pytest.approx(6.0)
    assert points[-1][1] == pytest.approx(3.0)   # a lower tool slopes up away from the outline


def test_long_section_samples_the_terrain_and_the_rule_design_line():
    grid = make_grid(tilted)
    section = long_section(dike(amount=2.0), grid)
    assert len(section["stations"]) == len(section["terrain"]) == 200
    assert section["stations"][0] == 0.0 and section["stations"][-1] == pytest.approx(30.0)
    assert section["terrain"][0] == pytest.approx(10.5, abs=0.1)    # tilted: 10 + 0.1x at x=5
    assert section["terrain"][-1] == pytest.approx(13.5, abs=0.1)
    assert not section["custom"]
    assert section["design"][0][1] == pytest.approx(section["terrain"][0] + 2.0, abs=0.1)


def test_a_custom_long_profile_is_reported_as_custom_and_used_as_given():
    section = long_section(dike(long_profile=((0.0, 20.0), (30.0, 25.0))), make_grid(tilted))
    assert section["custom"] and section["design"] == ((0.0, 20.0), (30.0, 25.0))


def test_the_long_section_reference_is_the_terrain_before_the_feature():
    grid = make_grid(flat(10))
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, polygon_wkb([(0, 0), (40, 0), (40, 40), (0, 40)]),
                  id="pad", amount=5.0)
    d = dike(id="dike", amount=2.0)
    stack = FeatureStack(grid)
    stack.update([pad, d])
    _window, before = stack.terrain_before("dike")
    on_top = long_section(d, stack.working, terrain=before)
    assert on_top["terrain"][10] == pytest.approx(15.0)          # the pad is already there
    assert on_top["design"][0][1] == pytest.approx(17.0)         # the dike rises from the pad
    plain = long_section(d, grid)
    assert plain["terrain"][10] == pytest.approx(10.0)


def test_terrain_before_is_the_original_for_the_first_feature():
    grid = make_grid(flat(10))
    d = dike(id="dike", amount=2.0)
    stack = FeatureStack(grid)
    stack.update([d])
    _window, before = stack.terrain_before("dike")
    assert np.allclose(before.data, 10.0)


def test_terrain_before_is_none_for_a_feature_that_is_not_there():
    stack = FeatureStack(make_grid(flat(10)))
    assert stack.terrain_before("missing") is None


def test_a_custom_long_profile_follows_a_reshaped_path():
    from terrain_sketch.core.sections import rescale_long_profile
    f = dike(long_profile=((0.0, 10.0), (15.0, 12.0), (30.0, 11.0)))
    longer = line_wkb([(5, 20), (65, 20)])          # the path doubles in length
    assert rescale_long_profile(f, longer, 1.0) == ((0.0, 10.0), (30.0, 12.0), (60.0, 11.0))


def test_rescaling_leaves_a_rule_profile_and_an_unchanged_path_alone():
    from terrain_sketch.core.sections import rescale_long_profile
    rule = dike()
    assert rescale_long_profile(rule, line_wkb([(5, 20), (65, 20)]), 1.0) is None
    same = dike(long_profile=((0.0, 10.0), (30.0, 11.0)))
    assert rescale_long_profile(same, same.geometry_wkb, 1.0) is same.long_profile


def test_a_feature_with_no_terminal_slope_and_multiple_breaks_survives_a_round_trip():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0), (6.0, -2.0))
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(10.0)


def test_an_unsorted_break_list_produces_a_non_decreasing_distance_sequence():
    f = dike(width=4.0, slope_n=2.0, reach=20.0, cross_right=((6.0, -2.0), (3.0, -1.0)))
    points = cross_section(f)
    distances = [d for d, z in points]
    assert distances == sorted(distances)


def test_an_ordinary_round_trip_with_one_break_and_a_slope_remains_unchanged():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0),)
    assert changes["slope_n"] == pytest.approx(3.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_deleting_the_terminal_slope_yields_zero_slope_and_reach():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0)])
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)
    assert changes["cross_right"] == ()


def test_a_terminus_dragged_onto_the_edge_produces_no_break_at_distance_zero():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.0, -0.5)])
    assert changes["cross_right"] == ()
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)


def test_a_terminus_dragged_onto_the_last_break_produces_one_break_not_two():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (5.0, -1.0), (5.0, -1.5)])
    assert changes["cross_right"] == ((3.0, -1.5),)
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_an_identity_round_trip_through_the_no_terminus_branch_changes_nothing():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(f.width)
    assert changes["cross_right"] == f.cross_right
    assert changes["slope_n"] == pytest.approx(f.slope_n)
    assert changes["reach"] == pytest.approx(f.reach)


def two_part_dike(**kw):
    """A RAISE_PATH whose geometry has two separate line parts."""
    return feature(Tool.RAISE_PATH, Mode.PATH,
                   multi_wkb([line_wkb([(5, 20), (15, 20)]), line_wkb([(25, 20), (35, 20)])]), **kw)


def test_a_multi_part_path_does_not_support_a_custom_long_profile():
    assert supports_long_profile(dike())
    assert not supports_long_profile(two_part_dike())
    pond = feature(Tool.LOWER_FLAT, Mode.AREA,
                   polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]))
    assert not supports_long_profile(pond)


def test_a_multi_part_path_reports_the_rule_line_not_the_stored_custom_profile():
    """The engine applies a long profile only to a single-part path, so reporting one here
    would show the user a design line their terrain does not follow."""
    stored = ((0.0, 20.0), (10.0, 20.0))
    section = long_section(two_part_dike(amount=2.0, long_profile=stored), make_grid(tilted))
    assert not section["custom"]
    assert section["design"] != stored
    # the rule line: the terrain under the longest part plus the height
    assert section["design"][0][1] == pytest.approx(section["terrain"][0] + 2.0, abs=0.1)


def test_an_areas_cross_section_edit_writes_no_break_points():
    """Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    break list to `side_dz`, so storing them would keep a value the engine silently discards."""
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]),
                   slope_n=2.0, reach=6.0, amount=1.0)
    changes = set_cross_section(pond, 1, [(0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)])
    assert "cross_right" not in changes and "cross_left" not in changes
    assert "width" not in changes                       # an area has no corridor either
    assert changes["slope_n"] == pytest.approx(3.3333)  # 5 m run over 1.5 m rise
    assert changes["reach"] == pytest.approx(8.0)


def test_a_terminus_dragged_hard_against_its_neighbour_keeps_the_side_slope():
    """`_move_handle` clamps a dragged handle to neighbour + 1e-6, and a run that small rounds
    to 0.0 — the "no terminal slope" sentinel. There is no undo, so the slope is kept."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.000001, -3.0)])
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_terminus_dragged_hard_against_the_edge_keeps_its_reach():
    """A reach that rounds to 0.0 stops the slope at the edge — the slope kept by the test above
    would then change nothing."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.00001, -3.0)])
    assert changes["reach"] == pytest.approx(20.0)
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_real_but_very_flat_slope_is_still_written():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (22.0, -0.5)])
    assert changes["slope_n"] == pytest.approx(40.0)


def test_the_whole_cross_section_runs_from_the_left_slope_to_the_right_one():
    f = dike(width=4.0, slope_n=2.0, reach=10.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5),))
    points = whole_cross_section(f)
    assert points[0][0] == pytest.approx(-12.0) and points[-1][0] == pytest.approx(12.0)
    assert (-4.0, -0.5) in points and (-2.0, 0.0) in points and (2.0, 0.0) in points and (6.0, -1.5) in points
    assert [x for x, _z in points] == sorted(x for x, _z in points)
    assert not any(x == 0.0 for x, _z in points)                # no centre handle: the crest runs across it


def test_an_untouched_whole_section_writes_back_what_the_feature_has():
    f = dike(width=4.5, slope_n=2.5, reach=12.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5), (6.0, -1.6)))
    changes = set_whole_cross_section(f, whole_cross_section(f))
    assert changes["width"] == pytest.approx(4.5)
    assert changes["slope_n"] == pytest.approx(2.5) and changes["reach"] == pytest.approx(12.0)
    for side in ("cross_left", "cross_right"):
        assert len(changes[side]) == len(getattr(f, side))
        for written, stored in zip(changes[side], getattr(f, side)):
            assert written == pytest.approx(stored)


def test_a_left_side_edit_changes_the_left_side_and_the_shared_slope():
    f = dike(width=4.0, slope_n=3.0, reach=10.0)
    points = list(whole_cross_section(f))
    points[0] = (-14.0, -4.0)                                   # the left slope's end: 12 m out, 4 m down
    changes = set_whole_cross_section(f, points)
    assert changes["reach"] == pytest.approx(12.0) and changes["slope_n"] == pytest.approx(3.0)
    assert changes["cross_left"] == () and changes["cross_right"] == ()


def test_symmetric_copies_the_edited_side_whichever_side_it_is():
    f = dike(width=4.0, slope_n=3.0, reach=10.0)
    left_berm = [(-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (12.0, -10.0 / 3.0)]
    assert set_whole_cross_section(f, left_berm, symmetric=True)["cross_right"] == ((4.0, -1.0),)
    right_berm = [(-12.0, -10.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)]
    assert set_whole_cross_section(f, right_berm, symmetric=True)["cross_left"] == ((4.0, -1.0),)
    unticked = set_whole_cross_section(f, left_berm, symmetric=False)
    assert unticked["cross_left"] == ((4.0, -1.0),) and unticked["cross_right"] == ()


def test_editing_one_side_leaves_a_side_with_breaks_past_its_reach_as_it_was():
    """A berm beyond the reach leaves that side without a slope-end handle. Reading its last berm as the
    slope's end rewrote the slope and the reach and dropped the berm while the user edited the other side."""
    f = dike(width=4.0, slope_n=3.0, reach=5.0, cross_right=((2.0, -0.5), (8.0, -1.0)))
    points = list(whole_cross_section(f))
    assert points[-1] == (10.0, -1.0)                               # the berm is the last handle
    points[0] = (-10.0, -8.0 / 3.0)                                 # the left slope's end, 3 m further out
    changes = set_whole_cross_section(f, points)
    assert changes["cross_right"] == f.cross_right and changes["cross_left"] == ()
    assert changes["slope_n"] == pytest.approx(3.0) and changes["reach"] == pytest.approx(8.0)


def test_a_side_whose_breaks_run_past_its_reach_keeps_its_slope_when_edited():
    f = dike(width=4.0, slope_n=3.0, reach=5.0, cross_right=((2.0, -0.5), (8.0, -1.0)))
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (4.0, -0.5), (10.0, -1.4)])
    assert changes["cross_right"] == ((2.0, -0.5), (8.0, -1.4))
    assert "slope_n" not in changes and "reach" not in changes


def test_the_side_that_was_not_edited_does_not_change_the_shared_values():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0),))
    points = list(whole_cross_section(f))
    points[-1] = (6.0, -1.5)                                        # drag the right berm
    changes = set_whole_cross_section(f, points)
    assert changes["cross_right"] == ((4.0, -1.5),) and changes["reach"] == pytest.approx(10.0)
    # a stored value halfway between two four-decimal numbers still counts as unchanged on the other side
    odd = dike(width=4.0, slope_n=3.0, reach=40.34765)
    moved = list(whole_cross_section(odd))
    moved[0] = (moved[0][0] - 3.0, moved[0][1] - 1.0)
    assert set_whole_cross_section(odd, moved)["reach"] == pytest.approx(43.34765, abs=1e-4)


def rotated_rectangle(length, breadth, degrees, centre=(20.0, 20.0)):
    c, s = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
    corners = [(-length / 2, -breadth / 2), (length / 2, -breadth / 2), (length / 2, breadth / 2),
               (-length / 2, breadth / 2)]
    return polygon_wkb([(centre[0] + x * c - y * s, centre[1] + x * s + y * c) for x, y in corners])


def line_points(wkb):
    from osgeo import ogr
    return np.array(ogr.CreateGeometryFromWkb(wkb).GetPoints())[:, :2]


def test_the_default_section_runs_through_the_middle_along_the_longer_side():
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, rotated_rectangle(20.0, 6.0, 30.0), slopes_inside=True)
    start, end = line_points(default_section_line(pond, cell_size=1.0))
    direction = (end - start) / np.hypot(*(end - start))
    assert direction == pytest.approx([np.cos(np.radians(30.0)), np.sin(np.radians(30.0))])
    assert (start + end) / 2 == pytest.approx([20.0, 20.0])                 # through the centroid
    assert np.hypot(*(end - start)) == pytest.approx(20.0 + 2 * 5.0)         # past the outline by five cells


def test_the_default_section_reaches_past_outside_slopes_and_runs_west_to_east():
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, rotated_rectangle(20.0, 6.0, 180.0), slope_n=2.0, reach=8.0)
    start, end = line_points(default_section_line(pad, cell_size=1.0))
    assert start[0] < end[0]
    assert np.hypot(*(end - start)) == pytest.approx(20.0 + 2 * (8.0 + 5.0))


def test_a_path_has_no_default_section_line():
    assert default_section_line(dike(), cell_size=1.0) is None


def test_a_section_samples_before_and_after_and_leaves_out_what_is_off_the_grid():
    grid = make_grid(flat(10.0))
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 15), (30, 15), (30, 25), (10, 25)]),
                   amount=2.0, slopes_inside=False, slope_n=0.0, id="pond")
    stack = FeatureStack(grid)
    stack.update([pond])
    line = line_wkb([(-10.0, 20.0), (35.0, 20.0)])                          # starts 10 m off the west edge
    _window, before, after = stack.terrain_around("pond", grid.window_for_bbox(0, 19, 35, 21))
    section = section_along(line, before, after)
    assert section["stations"][0] > 6.0                                      # the first metres are off the grid
    assert set(np.round(section["before"], 6)) == {10.0}
    assert min(section["after"]) == pytest.approx(8.0) and section["after"][-1] == pytest.approx(10.0)


def test_terrain_around_a_feature_is_before_and_after_it_alone():
    grid = make_grid(flat(10.0))
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, polygon_wkb([(5, 5), (35, 5), (35, 35), (5, 35)]),
                  amount=1.0, slope_n=0.0, id="pad")
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(15, 15), (25, 15), (25, 25), (15, 25)]),
                   amount=3.0, slope_n=0.0, id="pond")
    stack = FeatureStack(grid)
    stack.update([pad, pond])
    window, before, after = stack.terrain_around("pond")
    assert np.array_equal(before.data, stack.terrain_before("pond")[1].data)
    assert before.sample(20.0, 20.0) == pytest.approx(11.0) and after.sample(20.0, 20.0) == pytest.approx(8.0)
    _w, before_off, after_off = stack.terrain_around("pond", features=[pad, replace(pond, enabled=False)])
    assert np.array_equal(before_off.data, after_off.data)                   # a feature turned off changes nothing
