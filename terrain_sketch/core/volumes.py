"""Cut/fill and pond storage volumes."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from .grid import DemGrid


def cut_fill(before: np.ndarray, after: np.ndarray, valid: np.ndarray, cell_area: float):
    """(cut, fill) in cubic metres between two elevation arrays over valid cells."""
    diff = np.where(valid, after.astype(np.float64) - before.astype(np.float64), 0.0)
    return float(-diff[diff < 0.0].sum() * cell_area), float(diff[diff > 0.0].sum() * cell_area)


def pond_storage(after: np.ndarray, lowered: np.ndarray, valid: np.ndarray, cell_area: float):
    """Static storage below the lowest rim cell around the lowered region, or None.

    The rim is the ring of valid cells bordering the lowered region (8-connected);
    nodata cells never count as pond or rim."""
    lowered = lowered & valid
    if not lowered.any():
        return None
    rim = ndimage.binary_dilation(lowered, structure=np.ones((3, 3), bool)) & ~lowered & valid
    if not rim.any():
        return None
    spill = float(after[rim].min())
    depth = np.where(lowered, spill - after.astype(np.float64), 0.0)
    return float(np.clip(depth, 0.0, None).sum() * cell_area)


def total_cut_fill(original: DemGrid, working: DemGrid):
    """(cut, fill) of the whole scenario."""
    return cut_fill(original.data, working.data, original.valid, original.cell_area)
