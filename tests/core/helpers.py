"""Shared helpers for core tests: synthetic DEMs and features."""
import numpy as np

from terrain_scenarios.core.grid import DemGrid
from terrain_scenarios.model.feature import TerrainFeature

NODATA = -9999.0


def make_grid(func, rows=40, cols=40, cell=1.0, nodata_cells=()):
    """North-up grid covering x 0..cols*cell and y 0..rows*cell with z = func(X, Y) at cell centres."""
    gt = (0.0, cell, 0.0, rows * cell, 0.0, -cell)
    xs = (np.arange(cols) + 0.5) * cell
    ys = rows * cell - (np.arange(rows) + 0.5) * cell
    X, Y = np.meshgrid(xs, ys)
    data = np.broadcast_to(np.asarray(func(X, Y), dtype=np.float32), X.shape).copy()
    for r, c in nodata_cells:
        data[r, c] = NODATA
    return DemGrid.from_array(data, gt, nodata=NODATA)


def flat(z):
    return lambda X, Y: np.full(X.shape, float(z))


def tilted(X, Y):
    """Rises 0.1 m per metre towards the east."""
    return 10.0 + 0.1 * X


def feature(tool, mode, wkb, **kw):
    kw.setdefault("id", "f1")
    kw.setdefault("name", "test")
    return TerrainFeature(tool=tool, mode=mode, geometry_wkb=wkb, **kw)
