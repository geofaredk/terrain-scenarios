"""DEM held in memory: values, validity mask, north-up geotransform and cell windows."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Window:
    """Block of cells: rows row0..row0+rows-1 and cols col0..col0+cols-1."""

    row0: int
    col0: int
    rows: int
    cols: int

    @property
    def row1(self) -> int:
        return self.row0 + self.rows

    @property
    def col1(self) -> int:
        return self.col0 + self.cols

    @property
    def slices(self) -> tuple[slice, slice]:
        return slice(self.row0, self.row1), slice(self.col0, self.col1)

    def union(self, other: Window | None) -> Window:
        if other is None:
            return self
        r0, c0 = min(self.row0, other.row0), min(self.col0, other.col0)
        r1, c1 = max(self.row1, other.row1), max(self.col1, other.col1)
        return Window(r0, c0, r1 - r0, c1 - c0)

    def intersects(self, other: Window) -> bool:
        return (self.row0 < other.row1 and other.row0 < self.row1
                and self.col0 < other.col1 and other.col0 < self.col1)

    def contains(self, other: Window) -> bool:
        return (self.row0 <= other.row0 and self.col0 <= other.col0
                and other.row1 <= self.row1 and other.col1 <= self.col1)


class DemGrid:
    """A north-up raster block. `data` is float32; cells where `valid` is False are nodata."""

    def __init__(self, data: np.ndarray, valid: np.ndarray, geotransform, offset=(0, 0)):
        gt = tuple(float(v) for v in geotransform)
        if gt[2] != 0.0 or gt[4] != 0.0:
            raise ValueError("Rotated rasters are not supported")
        if gt[5] >= 0.0:
            raise ValueError("Raster must be north-up (negative pixel height)")
        self.data = data
        self.valid = valid
        self.root = gt
        self.offset = (int(offset[0]), int(offset[1]))

    @property
    def geotransform(self) -> tuple:
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        return (rx0 + col_off * px, px, 0.0, ry0 + row_off * py, 0.0, py)

    @classmethod
    def from_array(cls, array, geotransform, nodata=None) -> DemGrid:
        data = np.array(array, dtype=np.float32)
        if data.ndim != 2:
            raise ValueError("DEM data must be a 2-D array")
        valid = np.isfinite(data)
        if nodata is not None:
            valid &= data != np.float32(nodata)
        return cls(data, valid, geotransform)

    @property
    def rows(self) -> int:
        return self.data.shape[0]

    @property
    def cols(self) -> int:
        return self.data.shape[1]

    @property
    def cell_width(self) -> float:
        return self.geotransform[1]

    @property
    def cell_height(self) -> float:
        return -self.geotransform[5]

    @property
    def cell_size(self) -> float:
        return 0.5 * (self.cell_width + self.cell_height)

    @property
    def cell_area(self) -> float:
        return self.cell_width * self.cell_height

    @property
    def full_window(self) -> Window:
        return Window(0, 0, self.rows, self.cols)

    def copy(self) -> DemGrid:
        return DemGrid(self.data.copy(), self.valid.copy(), self.root, self.offset)

    def window_geotransform(self, window: Window) -> tuple:
        """Root-based geotransform of `window` (in this grid's local coordinates): every path
        to the same absolute cells produces a bit-identical tuple."""
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        return (rx0 + (col_off + window.col0) * px, px, 0.0, ry0 + (row_off + window.row0) * py, 0.0, py)

    def subgrid(self, window: Window) -> DemGrid:
        """Independent copy of a window."""
        rs, cs = window.slices
        row_off, col_off = self.offset
        offset = (row_off + window.row0, col_off + window.col0)
        return DemGrid(self.data[rs, cs].copy(), self.valid[rs, cs].copy(), self.root, offset)

    def view(self, window: Window) -> DemGrid:
        """Window sharing memory with this grid: writes to the view change this grid."""
        rs, cs = window.slices
        row_off, col_off = self.offset
        offset = (row_off + window.row0, col_off + window.col0)
        return DemGrid(self.data[rs, cs], self.valid[rs, cs], self.root, offset)

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """Continuous (col, row); cell (r, c) covers [c, c+1) x [r, r+1)."""
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        return (x - rx0) / px - col_off, (y - ry0) / py - row_off

    def cell_centers(self) -> tuple[np.ndarray, np.ndarray]:
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        xs = rx0 + (col_off + np.arange(self.cols) + 0.5) * px
        ys = ry0 + (row_off + np.arange(self.rows) + 0.5) * py
        return np.meshgrid(xs, ys)

    def window_for_bbox(self, xmin, ymin, xmax, ymax, margin_cells: int = 0) -> Window | None:
        """Cells touching the bbox plus a margin, clipped to the grid; None if outside."""
        c_lo, r_lo = self.world_to_pixel(xmin, ymax)
        c_hi, r_hi = self.world_to_pixel(xmax, ymin)
        c0 = max(math.floor(c_lo) - margin_cells, 0)
        r0 = max(math.floor(r_lo) - margin_cells, 0)
        c1 = min(math.ceil(c_hi) + margin_cells, self.cols)
        r1 = min(math.ceil(r_hi) + margin_cells, self.rows)
        if c1 <= c0 or r1 <= r0:
            return None
        return Window(r0, c0, r1 - r0, c1 - c0)

    def sample(self, x: float, y: float, search_cells: int = 3) -> float:
        """Bilinear elevation at (x, y). If a needed cell is nodata or the point lies off the
        grid, the nearest valid cell within `search_cells` is used; NaN if there is none."""
        cf, rf = self.world_to_pixel(x, y)
        inside = 0.0 <= cf < self.cols and 0.0 <= rf < self.rows
        if inside:
            u, v = cf - 0.5, rf - 0.5
            c0, r0 = math.floor(u), math.floor(v)
            fu, fv = u - c0, v - r0
            total = 0.0
            ok = True
            for r, c, w in ((r0, c0, (1 - fu) * (1 - fv)), (r0, c0 + 1, fu * (1 - fv)),
                            (r0 + 1, c0, (1 - fu) * fv), (r0 + 1, c0 + 1, fu * fv)):
                r = min(max(r, 0), self.rows - 1)
                c = min(max(c, 0), self.cols - 1)
                if not self.valid[r, c]:
                    ok = False
                    break
                total += w * float(self.data[r, c])
            if ok:
                return total
        return self._nearest_valid(cf, rf, search_cells)

    def _nearest_valid(self, cf: float, rf: float, search_cells: int) -> float:
        rc, cc = math.floor(rf), math.floor(cf)
        r0, r1 = max(rc - search_cells, 0), min(rc + search_cells + 1, self.rows)
        c0, c1 = max(cc - search_cells, 0), min(cc + search_cells + 1, self.cols)
        if r1 <= r0 or c1 <= c0:
            return math.nan
        block = self.valid[r0:r1, c0:c1]
        if not block.any():
            return math.nan
        rr, cc_ = np.nonzero(block)
        d2 = (rr + r0 + 0.5 - rf) ** 2 + (cc_ + c0 + 0.5 - cf) ** 2
        k = int(np.argmin(d2))
        return float(self.data[rr[k] + r0, cc_[k] + c0])
