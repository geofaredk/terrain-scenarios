"""Station (distance along a path) and signed offset of points relative to a polyline."""
from __future__ import annotations

import numpy as np


def vertex_stations(coords: np.ndarray) -> np.ndarray:
    """Cumulative distance along the polyline at each vertex (first = 0)."""
    seg = np.hypot(*np.diff(coords, axis=0).T)
    return np.concatenate([[0.0], np.cumsum(seg)])


def stations_offsets(coords: np.ndarray, X: np.ndarray, Y: np.ndarray):
    """For every point: station of the nearest point on the polyline and the signed
    distance to it (positive right of the direction of travel, negative left)."""
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    best = np.full(X.shape, np.inf)
    station = np.zeros(X.shape)
    side = np.ones(X.shape)
    cum = 0.0
    for (ax, ay), (bx, by) in zip(coords[:-1], coords[1:]):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        length = float(np.sqrt(length2))
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / length2, 0.0, 1.0)
        d2 = (X - (ax + t * dx)) ** 2 + (Y - (ay + t * dy)) ** 2
        better = d2 < best
        best = np.where(better, d2, best)
        station = np.where(better, cum + t * length, station)
        cross = dx * (Y - ay) - dy * (X - ax)  # > 0: left of travel (y axis up)
        side = np.where(better, np.where(cross > 0.0, -1.0, 1.0), side)
        cum += length
    return station, side * np.sqrt(best)
