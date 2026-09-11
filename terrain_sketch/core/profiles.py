"""Cross-profile evaluation beyond a corridor edge or outline."""
from __future__ import annotations

import numpy as np


def side_limit(breaks, slope_n: float, reach: float) -> float:
    """Farthest distance beyond the edge that a side (break points + slope) can change."""
    last = max([0.0] + [float(x) for x, _ in breaks])
    return max(reach, last) if slope_n > 0.0 else last


def side_dz(x, breaks, slope_n: float, reach: float, direction: int):
    """Height change and in-extent mask at distance `x` (>= 0) beyond the edge.

    `breaks` are (distance, dz) points beyond the edge (the edge itself is (0, 0)).
    After the last point the side slope continues at 1:`slope_n` (`direction` -1 = down,
    +1 = up) until `reach` from the edge; `slope_n` <= 0 means no terminal slope."""
    x = np.asarray(x, dtype=float)
    pts = [(0.0, 0.0)] + sorted((float(a), float(b)) for a, b in breaks if a > 0.0)
    xs = np.array([p[0] for p in pts])
    zs = np.array([p[1] for p in pts])
    dz = np.interp(x, xs, zs)
    if slope_n > 0.0:
        dz = np.where(x > xs[-1], zs[-1] + direction * (x - xs[-1]) / slope_n, dz)
    return dz, x <= side_limit(breaks, slope_n, reach)
