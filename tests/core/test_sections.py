import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, polygon_wkb
from terrain_sketch.core.sections import cross_section, long_section, set_cross_section
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
