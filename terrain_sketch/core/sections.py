"""Profile sampling for the editors: the cross-section template and the long section along a path.

Pure geometry and sampling — the widgets draw what these return and hand back edited points.
"""
from __future__ import annotations

import numpy as np

from .geometry import is_line, line_coords, split_parts
from .grid import DemGrid
from .operations import NoReferenceError, path_coords, rule_profile
from .profiles import side_dz, side_limit
from .stations import vertex_stations
from .tools import TOOL_INFO, Mode

SAMPLES = 200


def cross_section(feature, side: int = 1) -> tuple:
    """One side of the cross profile as ((distance from the centre line, dz), ...).

    Starts at the centre (0, 0), runs flat to the corridor edge, then through this side's
    break points, then down the terminal 1:n slope to its limit. `side` is +1 (right) or -1
    (left); for areas the corridor is zero-width, so the outline itself is the edge.
    """
    info = TOOL_INFO[feature.tool]
    edge = 0.5 * feature.width if feature.mode is Mode.PATH else 0.0
    breaks = feature.cross_right if side >= 0 else feature.cross_left
    points = [(0.0, 0.0), (edge, 0.0)]
    if not info.has_slopes:
        return tuple(points)
    limit = side_limit(breaks, feature.slope_n, feature.reach)
    for distance, dz in breaks:
        points.append((edge + float(distance), float(dz)))
    if limit > (breaks[-1][0] if breaks else 0.0):
        dz, _in_extent = side_dz(np.array([limit]), breaks, feature.slope_n, feature.reach,
                                 info.direction)
        points.append((edge + limit, float(dz[0])))
    return tuple(points)


def set_cross_section(feature, side: int, points) -> dict:
    """Turn edited cross-section points back into feature fields.

    `points` are ((distance from the centre line, dz), ...) as `cross_section` returns them.
    The first interior point sets the width; the rest become break points relative to the
    corridor edge; the last segment's run over rise sets the side slope.
    """
    pts = [(float(d), float(z)) for d, z in points if float(d) >= 0.0]
    if len(pts) < 2:
        raise ValueError("a cross section needs at least a centre and an edge point")
    edge = pts[1][0]
    changes: dict = {}
    if feature.mode is Mode.PATH:
        changes["width"] = max(2.0 * edge, 0.1)
    interior, last = pts[2:-1], pts[-1]
    changes["cross_right" if side >= 0 else "cross_left"] = tuple(
        (d - edge, z) for d, z in interior)
    run = last[0] - (interior[-1][0] if interior else edge)
    rise = abs(last[1] - (interior[-1][1] if interior else 0.0))
    changes["slope_n"] = round(run / rise, 4) if rise > 1e-9 else 0.0
    changes["reach"] = round(last[0] - edge, 4)
    return changes


def section_part(feature):
    """The part a long section runs along: for a multi-part path, the longest one."""
    geometry_parts = [p for p in split_parts(feature.geometry_wkb) if is_line(p)]
    if feature.mode is not Mode.PATH or not geometry_parts:
        return None
    return max(geometry_parts, key=lambda p: _length(line_coords(p)))


def long_section(feature, grid: DemGrid, terrain: DemGrid | None = None) -> dict:
    """Reference terrain and design line along the feature's centre line.

    Returns `{"stations", "terrain", "design", "custom"}`: stations in metres from the start,
    terrain sampled on `terrain` (the state just before this feature) and the design line
    either from the feature's custom long profile or regenerated from the tool rule.
    """
    part = section_part(feature)
    coords = None if part is None else line_coords(part)
    if coords is None or len(coords) < 2:
        return {"stations": (), "terrain": (), "design": (), "custom": False}
    reference = terrain if terrain is not None else grid
    length = float(vertex_stations(path_coords(part, grid.cell_size))[-1])
    stations = np.linspace(0.0, length, SAMPLES)
    xs, ys = _walk(coords, stations)
    heights = tuple(float(reference.sample(x, y)) for x, y in zip(xs, ys))
    if feature.long_profile is not None:
        design = tuple((float(s), float(z)) for s, z in feature.long_profile)
        return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": True}
    try:
        design = rule_profile(feature, part, reference)
    except NoReferenceError:
        design = ()
    return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": False}


def _length(coords: np.ndarray) -> float:
    return float(np.sum(np.hypot(np.diff(coords[:, 0]), np.diff(coords[:, 1]))))


def _walk(coords: np.ndarray, stations: np.ndarray):
    """Positions at `stations` metres along the polyline through `coords`."""
    segments = np.hypot(np.diff(coords[:, 0]), np.diff(coords[:, 1]))
    cumulative = np.concatenate([[0.0], np.cumsum(segments)])
    total = cumulative[-1]
    if total <= 0:
        return np.full(stations.shape, coords[0, 0]), np.full(stations.shape, coords[0, 1])
    clamped = np.clip(stations, 0.0, total)
    return (np.interp(clamped, cumulative, coords[:, 0]),
            np.interp(clamped, cumulative, coords[:, 1]))


def rescale_long_profile(feature, geometry_wkb: bytes, cell_size: float):
    """A custom long profile's stations after the path was reshaped.

    Stations are absolute metres along the path, so reshaping it would otherwise leave them
    pointing at the wrong places — or off the end. They are scaled by the change in length,
    which keeps a profile's shape where the user put it relative to the path. Returns the
    feature's existing profile unchanged when there is nothing to do.
    """
    if feature.long_profile is None:
        return feature.long_profile
    old = _path_length(feature.geometry_wkb, cell_size)
    new = _path_length(geometry_wkb, cell_size)
    if old is None or new is None or old <= 0.0 or abs(new - old) < 1e-9:
        return feature.long_profile
    factor = new / old
    return tuple((round(station * factor, 6), z) for station, z in feature.long_profile)


def _path_length(geometry_wkb: bytes, cell_size: float):
    line_parts = [p for p in split_parts(geometry_wkb) if is_line(p)]
    if not line_parts:
        return None
    part = max(line_parts, key=lambda p: _length(line_coords(p)))
    return float(vertex_stations(path_coords(part, cell_size))[-1])
