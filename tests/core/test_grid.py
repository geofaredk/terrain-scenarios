import math

import numpy as np
import pytest

from helpers import make_grid
from terrain_sketch.core.grid import DemGrid, Window


def test_window_for_bbox_adds_margin_and_clips():
    g = make_grid(lambda X, Y: 0 * X, rows=10, cols=10)
    assert g.window_for_bbox(2.5, 2.5, 4.5, 4.5, margin_cells=1) == Window(4, 1, 5, 5)
    assert g.window_for_bbox(-5, -5, 3, 3) == Window(7, 0, 3, 3)
    assert g.window_for_bbox(-5, -5, -1, -1) is None


def test_window_union_intersects_contains():
    a, b = Window(0, 0, 2, 2), Window(1, 1, 3, 3)
    assert a.union(b) == Window(0, 0, 4, 4)
    assert a.intersects(b) and not a.intersects(Window(2, 2, 1, 1))
    assert a.union(b).contains(b) and not a.contains(b)


def test_subgrid_is_a_copy_and_view_shares_memory():
    g = make_grid(lambda X, Y: X + 100 * Y, rows=10, cols=10)
    w = Window(2, 3, 4, 5)
    sub = g.subgrid(w)
    X, Y = sub.cell_centers()
    np.testing.assert_allclose(sub.data, X + 100 * Y)
    sub.data[:] = 5
    assert g.data[2, 3] != 5
    g.view(w).data[:] = 0
    assert g.data[2:6, 3:8].sum() == 0


def test_rejects_rotated_and_south_up_rasters():
    with pytest.raises(ValueError):
        DemGrid.from_array(np.zeros((2, 2)), (0, 1, 0.1, 2, 0, -1))
    with pytest.raises(ValueError):
        DemGrid.from_array(np.zeros((2, 2)), (0, 1, 0, 0, 0, 1))


def test_sample_is_exact_on_a_plane():
    g = make_grid(lambda X, Y: 2 * X + 3 * Y, rows=10, cols=10)
    assert g.sample(4.3, 6.7) == pytest.approx(2 * 4.3 + 3 * 6.7, abs=1e-4)


def test_sample_uses_nearest_valid_cell_next_to_nodata():
    g = make_grid(lambda X, Y: X, rows=10, cols=10, nodata_cells=[(5, 5)])
    assert g.sample(5.5, 4.5) in (4.5, 5.5, 6.5)
    assert math.isnan(g.sample(50.0, 50.0))


def test_nested_windows_share_bit_identical_geotransforms():
    """On a realistic (non-integer, sub-metre) geotransform, a window taken through a
    subgrid must land on exactly the same geotransform as a direct window on the root grid —
    otherwise rasterization of boundaries on cell edges can flip by a ULP-level offset."""
    g = DemGrid.from_array(np.zeros((60, 60), np.float32), (612345.6, 0.4, 0.0, 6178925.2, 0.0, -0.4))
    a, b, c, d = 0, 1, 0, 2
    nested = g.subgrid(Window(a, b, 30, 30)).view(Window(c, d, 10, 10))
    direct = g.view(Window(a + c, b + d, 10, 10))
    assert nested.geotransform == direct.geotransform
    X1, Y1 = nested.cell_centers()
    X2, Y2 = direct.cell_centers()
    assert (X1 == X2).all() and (Y1 == Y2).all()


def test_from_array_rejects_non_2d_input():
    with pytest.raises(ValueError):
        DemGrid.from_array(np.zeros(5), (0, 1, 0, 1, 0, -1))
