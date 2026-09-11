import numpy as np
import pytest

import terrain_sketch.core.operations as operations_module
from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.geometry import line_wkb, multi_wkb, polygon_wkb
from terrain_sketch.core.operations import (FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS,
                                            FLAG_NODATA_REFERENCE, FLAG_OUTSIDE, apply_feature)
from terrain_sketch.core.tools import Mode, PixelMode, Tool

# On the default 40 x 40 grid (1 m cells) cell (r, c) has its centre at x = c + 0.5, y = 39.5 - r.
EAST_WEST = line_wkb([(5.25, 20.25), (34.75, 20.25)])  # runs through row 19 (y 20..21)
ROW = 19


def square(x0, y0, x1, y1):
    return polygon_wkb([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def bump(X, Y):
    return 3.0 * np.exp(-((X - 20.0) ** 2 + (Y - 20.5) ** 2) / 8.0)


def run(grid, f):
    before = grid.data.astype(float).copy()
    stats = apply_feature(f, grid)
    return before, grid.data.astype(float), stats


def test_add_path_raises_corridor_by_exact_amount():
    _, after, stats = run(g := make_grid(flat(5)), feature(Tool.ADD, Mode.PATH, EAST_WEST, amount=1.5, width=3.0))
    changed = after != 5.0
    assert changed.sum() == 3 * 30  # rows 18..20, cols 5..34
    np.testing.assert_allclose(after[changed], 6.5)
    assert stats.fill == pytest.approx(90 * 1.5) and stats.cut == 0 and stats.storage is None
    assert g.valid.all()


def test_subtract_area_keeps_the_relief():
    before, after, stats = run(make_grid(tilted), feature(Tool.SUBTRACT, Mode.AREA, square(10.3, 10.3, 20.3, 20.3), amount=2.0))
    changed = after != before
    assert changed.sum() == 100
    np.testing.assert_allclose((before - after)[changed], 2.0, atol=1e-5)
    assert stats.cut == pytest.approx(200.0, rel=1e-5)


def test_interpolate_path_grades_straight_through_a_bump():
    _, after, _ = run(make_grid(lambda X, Y: tilted(X, Y) + bump(X, Y)),
                      feature(Tool.INTERPOLATE, Mode.PATH, EAST_WEST, width=1.0))
    xs = np.arange(5, 34) + 0.5
    np.testing.assert_allclose(after[ROW, 5:34], 10 + 0.1 * xs, atol=1e-3)


def test_raise_path_never_lowers_and_builds_a_crest():
    before, after, stats = run(make_grid(lambda X, Y: tilted(X, Y) + bump(X, Y)),
                               feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, amount=1.0, width=2.0, slope_n=2.0))
    assert (after >= before - 1e-5).all()
    assert after[ROW, 8] == pytest.approx(10 + 0.1 * 8.5 + 1.0, abs=1e-3)  # 1 m above the grade
    assert after[ROW, 20] == pytest.approx(before[ROW, 20])  # the 3 m bump is already higher
    assert stats.cut == 0 and stats.fill > 0


def test_lower_path_never_raises_and_cuts_a_ditch():
    before, after, stats = run(make_grid(lambda X, Y: tilted(X, Y) - bump(X, Y)),
                               feature(Tool.LOWER_PATH, Mode.PATH, EAST_WEST, amount=1.0, width=2.0, slope_n=2.0))
    assert (after <= before + 1e-5).all()
    assert after[ROW, 8] == pytest.approx(10 + 0.1 * 8.5 - 1.0, abs=1e-3)
    assert after[ROW, 20] == pytest.approx(before[ROW, 20])  # the pit is already deeper
    assert stats.fill == 0 and stats.cut > 0


def test_path_side_slopes_fall_one_in_n_including_the_ends():
    _, after, _ = run(make_grid(flat(0)),
                      feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, amount=2.0, width=2.0, slope_n=4.0))
    assert after[ROW, 20] == pytest.approx(2.0)
    np.testing.assert_allclose(np.diff(after[18:12:-1, 20]), -0.25, atol=1e-6)  # northwards
    assert after[ROW, 35] > after[ROW, 36] > 0.0  # the dike end slopes down, no hole
    assert after[0, 20] == 0.0  # beyond 8 m the slope has met the ground


def test_raise_flat_path_is_level_at_highest_vertex_plus_height():
    wkb = line_wkb([(5.25, 20.25), (20.25, 20.25), (34.75, 20.25)])
    _, after, _ = run(make_grid(tilted), feature(Tool.RAISE_FLAT, Mode.PATH, wkb, amount=0.5, width=1.0, slope_n=0.0))
    np.testing.assert_allclose(after[ROW, 5:35], 10 + 0.1 * 34.75 + 0.5, atol=1e-4)


def test_lower_flat_area_basin_and_storage():
    _, after, stats = run(make_grid(flat(10)),
                          feature(Tool.LOWER_FLAT, Mode.AREA, square(10.3, 10.3, 20.3, 20.3), amount=1.0, slope_n=0.0))
    assert (after == 9).sum() == 100
    assert stats.cut == pytest.approx(100.0)
    assert stats.storage == pytest.approx(100.0)


def test_area_slopes_outside_fall_one_in_n_and_stop_at_reach():
    poly = square(15.3, 15.3, 25.3, 25.3)  # cells 15..24
    _, after, _ = run(make_grid(flat(0)), feature(Tool.RAISE_FLAT, Mode.AREA, poly, amount=2.0, slope_n=4.0))
    assert after[20, 20] == pytest.approx(2.0)
    np.testing.assert_allclose(np.diff(after[20, 25:31]), -0.25, atol=1e-6)
    _, capped, _ = run(make_grid(flat(0)),
                       feature(Tool.RAISE_FLAT, Mode.AREA, poly, amount=2.0, slope_n=40.0, reach=3.0))
    assert capped[20, 26] > 0.0 and capped[20, 29] == 0.0


def test_pond_slopes_inside_meet_the_terrain_at_the_outline():
    poly = square(10.3, 10.3, 30.3, 30.3)  # cells 10..29
    _, after, stats = run(make_grid(flat(10)), feature(Tool.LOWER_FLAT, Mode.AREA, poly, amount=2.0,
                                                       slope_n=2.0, slopes_inside=True))
    assert after[20, 10] == pytest.approx(9.75)  # first cell inside the outline
    np.testing.assert_allclose(np.diff(after[20, 10:14]), -0.5, atol=1e-6)
    assert after[20, 20] == pytest.approx(8.0)  # flat floor
    assert (after[:, :10] == 10).all()  # nothing outside the outline changes
    assert stats.storage == pytest.approx(stats.cut)


def test_interpolate_area_reproduces_a_plane_and_fills_a_ditch():
    ditch = lambda X, Y: tilted(X, Y) - np.where(np.abs(X - 20.5) < 1.0, 2.0, 0.0)  # noqa: E731
    grid = make_grid(ditch)
    poly = polygon_wkb([(12.3, 12.3), (28.7, 12.1), (29.2, 27.9), (24.7, 31.3), (11.8, 27.7)])
    before, after, _ = run(grid, feature(Tool.INTERPOLATE, Mode.AREA, poly))
    X, _ = grid.cell_centers()
    changed = after != before
    np.testing.assert_allclose(after[changed], (10 + 0.1 * X)[changed], atol=1e-3)
    assert after[20, 20] == pytest.approx(10 + 0.1 * 20.5, abs=1e-3)  # ditch cell filled


def test_nodata_cells_are_never_modified():
    grid = make_grid(flat(10), nodata_cells=[(15, 15), (16, 16)])
    _, after, _ = run(grid, feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 30.3, 30.3), amount=1.0))
    assert after[15, 15] == -9999 and after[16, 16] == -9999 and not grid.valid[15, 15]
    assert after[20, 20] == 11


def test_multi_part_areas_use_their_own_reference_levels():
    west, east = square(5.3, 15.3, 10.3, 20.3), square(25.3, 15.3, 30.3, 20.3)
    _, after, _ = run(make_grid(tilted), feature(Tool.RAISE_FLAT, Mode.AREA, multi_wkb([west, east]),
                                                 amount=1.0, slope_n=0.0))
    assert after[22, 7] == pytest.approx(10 + 0.1 * 10.3 + 1.0, abs=1e-3)
    assert after[22, 27] == pytest.approx(10 + 0.1 * 30.3 + 1.0, abs=1e-3)


def test_dragged_long_profile_still_never_cuts():
    low = ((0.0, 5.0), (29.5, 5.0))
    before, after, stats = run(make_grid(flat(10)), feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, long_profile=low))
    assert (after == before).all() and stats.fill == 0 and stats.flags == ()
    high = ((0.0, 12.0), (29.5, 14.0))
    _, after2, _ = run(make_grid(flat(10)), feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, long_profile=high, slope_n=0.0))
    assert after2[ROW, 20] == pytest.approx(12.0 + 2.0 * (20.5 - 5.25) / 29.5, abs=1e-3)


@pytest.mark.parametrize("mode", list(PixelMode))
@pytest.mark.parametrize("tool, sign", [(Tool.RAISE_PATH, 1.0), (Tool.LOWER_PATH, -1.0)])
def test_path_cross_section_has_no_gap_in_any_pixel_mode(tool, sign, mode):
    """Slope distance must be measured from the pixel-mode's own crest (`core`), not always
    from the centre-mode band: otherwise the ring between the crest and the band is neither
    crest nor slope and stays untouched, leaving a gap in the cross-section (I1)."""
    _, after, _ = run(make_grid(flat(10)),
                      feature(tool, Mode.PATH, EAST_WEST, amount=2.0, width=4.0, slope_n=2.0, pixel_mode=mode))
    col = sign * (after[:, 20] - 10.0)
    top = int(np.argmax(col))
    assert col[top] == pytest.approx(2.0)
    assert (np.diff(col[top::-1]) <= 1e-6).all()
    assert (np.diff(col[top:]) <= 1e-6).all()


def test_wide_path_with_a_sharp_bend_is_not_cut_off(monkeypatch):
    """A sharp mitred bend's corridor can extend up to the full width beyond the vertex; the
    footprint window must cover the whole mitre spike, not just the line's own bbox padded by
    width/2 + slope limit (I2). A too-small window truncates the slope, so a much larger
    MARGIN_CELLS must produce the identical result once the footprint is correct."""
    wkb = line_wkb([(30.0, 20.0), (40.0, 60.0), (50.0, 20.0)])
    f = feature(Tool.RAISE_PATH, Mode.PATH, wkb, amount=3.0, width=12.0, slope_n=2.0, reach=5.0)
    default = make_grid(flat(0), rows=100, cols=80)
    apply_feature(f, default)
    monkeypatch.setattr(operations_module, "MARGIN_CELLS", 30)
    wide_margin = make_grid(flat(0), rows=100, cols=80)
    apply_feature(f, wide_margin)
    np.testing.assert_array_equal(default.data, wide_margin.data)


def test_problem_flags():
    grid = make_grid(flat(10))
    far = feature(Tool.ADD, Mode.PATH, line_wkb([(500, 500), (600, 600)]))
    assert apply_feature(far, grid).flags == (FLAG_OUTSIDE,)
    thin = feature(Tool.ADD, Mode.PATH, EAST_WEST, width=1.0, pixel_mode=PixelMode.FULLY_INSIDE)
    assert apply_feature(thin, grid).flags == (FLAG_NO_PIXELS,)
    wrong = feature(Tool.ADD, Mode.PATH, square(1.3, 1.3, 5.3, 5.3))
    assert apply_feature(wrong, grid).flags == (FLAG_BAD_GEOMETRY,)
    holes = [(r, c) for r in range(12, 29) for c in range(0, 14)]
    start_on_nodata = feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST)
    assert FLAG_NODATA_REFERENCE in apply_feature(start_on_nodata, make_grid(flat(10), nodata_cells=holes)).flags
