import numpy as np
import pytest

from helpers import make_grid
from terrain_scenarios.core.geometry import polygon_wkb, split_parts
from terrain_scenarios.core.mask import polygon_mask
from terrain_scenarios.core.tools import PixelMode

# Square from 0.7 to 4.6 on a 1 m grid: touches cells 0..4, centres 1..4 inside, cells 1..3 fully inside.
SQUARE = polygon_wkb([(0.7, 0.7), (4.6, 0.7), (4.6, 4.6), (0.7, 4.6)])


@pytest.mark.parametrize("mode, count", [
    (PixelMode.ALL_TOUCHED, 25),
    (PixelMode.CENTRE, 16),
    (PixelMode.FULLY_INSIDE, 9),
])
def test_square_cell_counts(mode, count):
    grid = make_grid(lambda X, Y: 0 * X, rows=6, cols=6)
    assert polygon_mask(split_parts(SQUARE)[0], grid, mode).sum() == count


def test_modes_are_nested_for_random_polygons():
    rng = np.random.default_rng(1)
    grid = make_grid(lambda X, Y: 0 * X, rows=30, cols=30)
    for _ in range(20):
        cx, cy = rng.uniform(8, 22, 2)
        radius = rng.uniform(2, 8)
        angles = np.sort(rng.uniform(0, 2 * np.pi, 7))
        ring = [(cx + radius * rng.uniform(0.6, 1) * np.cos(a), cy + radius * rng.uniform(0.6, 1) * np.sin(a))
                for a in angles]
        poly = split_parts(polygon_wkb(ring))[0]
        touched, centre, inside = (polygon_mask(poly, grid, m) for m in
                                   (PixelMode.ALL_TOUCHED, PixelMode.CENTRE, PixelMode.FULLY_INSIDE))
        assert (inside <= centre).all() and (centre <= touched).all()
