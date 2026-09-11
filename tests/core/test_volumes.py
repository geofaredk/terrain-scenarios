import numpy as np
import pytest

from helpers import flat, make_grid
from terrain_sketch.core.volumes import cut_fill, pond_storage, total_cut_fill


def test_cut_fill_and_storage_on_small_arrays():
    before = np.full((5, 5), 10.0)
    after = before.copy()
    after[1:4, 1:4] = 8.0
    after[0, 0] = 11.0
    valid = np.ones((5, 5), bool)
    cut, fill = cut_fill(before, after, valid, 2.0)
    assert cut == pytest.approx(36.0) and fill == pytest.approx(2.0)
    assert pond_storage(after, after < before, valid, 1.0) == pytest.approx(18.0)  # spill at 10
    assert pond_storage(after, np.zeros_like(valid), valid, 1.0) is None


def test_pond_storage_ignores_nodata_cells_inside_the_pond():
    after = np.full((5, 5), 10.0)
    after[1:4, 1:4] = 8.0
    after[2, 2] = -9999.0  # nodata sentinel inside the lowered region
    valid = np.ones((5, 5), bool)
    valid[2, 2] = False
    assert pond_storage(after, after < 10.0, valid, 1.0) == pytest.approx(16.0)  # 8 valid cells x 2 m


def test_total_cut_fill_compares_working_with_original():
    original = make_grid(flat(10))
    working = original.copy()
    working.data[0, 0] = 12
    working.data[1, 1] = 9
    cut, fill = total_cut_fill(original, working)
    assert cut == pytest.approx(1.0) and fill == pytest.approx(2.0)
