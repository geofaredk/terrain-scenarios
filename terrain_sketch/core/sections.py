"""Profile sampling for the editors: the cross-section template and the long section along a path.

Pure geometry and sampling — the widgets draw what these return and hand back edited points.
"""
from __future__ import annotations

import math

import numpy as np
from osgeo import ogr
from scipy.spatial import ConvexHull, QhullError

from .geometry import is_line, line_coords, line_wkb, polygon_rings, split_parts
from .grid import DemGrid
from .operations import NoReferenceError, path_coords, rule_profile
from .profiles import side_dz, side_limit
from .stations import vertex_stations
from .tools import TOOL_INFO, Mode

SAMPLES = 200
SAME = 1e-4   # values are written back at four decimals, so closer than this is the same value


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
    sorted_breaks = sorted(breaks, key=lambda b: b[0])
    for distance, dz in sorted_breaks:
        points.append((edge + float(distance), float(dz)))
    if limit > (sorted_breaks[-1][0] if sorted_breaks else 0.0):
        dz, _in_extent = side_dz(np.array([limit]), sorted_breaks, feature.slope_n, feature.reach,
                                 info.direction)
        points.append((edge + limit, float(dz[0])))
    return tuple(points)


def set_cross_section(feature, side: int, points) -> dict:
    """Turn edited cross-section points back into feature fields.

    `points` are ((distance from the centre line, dz), ...) as `cross_section` returns them.
    The first interior point sets the width; the rest become break points relative to the
    corridor edge; the last segment's run over rise sets the side slope.
    """
    pts = sorted([(float(d), float(z)) for d, z in points if float(d) >= 0.0], key=lambda p: p[0])
    if len(pts) < 2:
        raise ValueError("a cross section needs at least a centre and an edge point")
    edge = pts[1][0]
    changes: dict = {}
    # Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    # break list to `side_dz`, so writing them here would store a value the engine discards.
    breaks_key = ("cross_right" if side >= 0 else "cross_left") if feature.mode is Mode.PATH else None
    if feature.mode is Mode.PATH:
        changes["width"] = max(2.0 * edge, 0.1)

    # The final point is the slope's end only if the plot drew one: `cross_section` adds it when the
    # reach goes past the last break. With breaks beyond the reach there is none, and reading the last
    # break as the slope's end would rewrite the slope and the reach and drop that break.
    has_terminal_slope = feature.slope_n > 0.0
    last_break_distance = pts[-2][0] if len(pts) > 2 else edge
    stored = feature.cross_right if side >= 0 else feature.cross_left
    drew_terminus = side_limit(stored, feature.slope_n, feature.reach) > max([0.0] + [float(d) for d, _ in stored])
    last_point_is_terminus = has_terminal_slope and drew_terminus and pts[-1][0] > last_break_distance

    if has_terminal_slope and not drew_terminus:
        # every point after the edge is a break; the slope and its reach are not on the plot to change
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in pts[2:] if d > edge)
    elif last_point_is_terminus:
        interior, last = pts[2:-1], pts[-1]
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in interior)
        run = last[0] - (interior[-1][0] if interior else edge)
        rise = abs(last[1] - (interior[-1][1] if interior else 0.0))
        changes["slope_n"] = _slope_n(run, rise, feature.slope_n)
        changes["reach"] = _reach(last[0] - edge, feature.reach)
    else:
        # No terminal slope: all points after edge are breaks. Derive slope_n and reach.
        # Filter out breaks at distance 0 (at the edge itself) and collapse duplicates.
        interior = [(d, z) for d, z in pts[2:] if d > edge]

        # Collapse duplicate distances: keep the later (rightmost) value
        seen_distances = {}
        for d, z in interior:
            seen_distances[d] = z

        deduplicated = sorted(seen_distances.items())
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in deduplicated)
        changes["slope_n"] = 0.0
        changes["reach"] = 0.0 if not deduplicated else feature.reach

    return changes


def whole_cross_section(feature) -> tuple:
    """A path's cross profile across both sides, as a surveyor draws it: ((offset, dz), ...) from the
    end of the left slope to the end of the right one, left of the centre line at negative offsets.
    Left and right are as seen looking along the path in the direction it was drawn."""
    left = cross_section(feature, side=-1)[1:]
    right = cross_section(feature, side=1)[1:]
    return tuple((-x, z) for x, z in reversed(left)) + right


def set_whole_cross_section(feature, points, symmetric: bool = False) -> dict:
    """Turn an edited whole cross profile back into feature fields.

    Each side is read the way `set_cross_section` reads one, but a side whose points are still the ones
    the plot was given is left as the feature has it: reading it back could only add rounding. Width,
    side slope and reach are single values shared by both sides, so each is taken from the side where it
    changed (the right when both did). With `symmetric`, the break points of a side whose breaks changed
    are copied to the other side (the right's when both did); an edit that moves no break point, such as
    a slope's end, leaves both sides' breaks as they are."""
    pts = [(float(x), float(z)) for x, z in points]
    sides = {}
    for side, key, own in ((1, "cross_right", sorted(p for p in pts if p[0] > 0.0)),
                           (-1, "cross_left", sorted((-x, z) for x, z in pts if x < 0.0))):
        if _same_points(own, cross_section(feature, side=side)[1:]):
            sides[key] = {}
        else:
            sides[key] = set_cross_section(feature, side, [(0.0, 0.0)] + own)
    changes = {key: read.get(key, getattr(feature, key)) for key, read in sides.items()}
    for key in ("width", "slope_n", "reach"):
        current = getattr(feature, key)
        left, right = sides["cross_left"].get(key, current), sides["cross_right"].get(key, current)
        changes[key] = left if abs(left - current) > SAME and abs(right - current) <= SAME else right
    if symmetric:
        right_same = _same_points(changes["cross_right"], feature.cross_right)
        left_same = _same_points(changes["cross_left"], feature.cross_left)
        if right_same and not left_same:
            changes["cross_right"] = changes["cross_left"]
        elif not right_same:
            changes["cross_left"] = changes["cross_right"]
    return changes


def _same_points(a, b) -> bool:
    """Whether two break lists are equal to within the rounding a round trip through the plot adds."""
    return len(a) == len(b) and all(abs(ax - bx) <= SAME and abs(az - bz) <= SAME
                                    for (ax, az), (bx, bz) in zip(a, b))


def _slope_n(run: float, rise: float, current: float) -> float:
    """The terminal slope 1:n from a run over a rise, rounded to the stored four decimals.

    0.0 is the "no terminal slope" sentinel, so a run too small to round to a non-zero n — a
    terminus dragged hard against its neighbour — keeps the slope the feature already has
    rather than silently losing it. There is no undo.
    """
    if rise <= 1e-9:
        return 0.0
    rounded = round(run / rise, 4)
    return rounded if rounded > 0.0 else current


def _reach(distance: float, current: float) -> float:
    """The slope's reach from the terminus's distance beyond the edge, rounded like the slope.

    A reach of 0.0 stops the slope at the edge, so a terminus dragged hard against the edge rounds to
    nothing only by accident — the same drag `_slope_n` guards against — and keeps the reach it had."""
    rounded = round(distance, 4)
    return rounded if rounded > 0.0 else current


def section_part(feature):
    """The part a long section runs along: for a multi-part path, the longest one."""
    geometry_parts = [p for p in split_parts(feature.geometry_wkb) if is_line(p)]
    if feature.mode is not Mode.PATH or not geometry_parts:
        return None
    return max(geometry_parts, key=lambda p: _length(line_coords(p)))


def supports_long_profile(feature) -> bool:
    """Whether a custom long profile would actually drive this feature's terrain.

    `operations.apply_feature` uses one only for a single-part path (spec 5.4), so for anything
    else the editor must not offer one: it would be stored, shown as custom and then discarded,
    while the Height/Depth that does drive the result sits disabled.
    """
    if feature.mode is not Mode.PATH:
        return False
    try:
        return len(split_parts(feature.geometry_wkb)) == 1
    except ValueError:
        return False


def long_section(feature, grid: DemGrid, terrain: DemGrid | None = None) -> dict:
    """Reference terrain and design line along the feature's centre line.

    Returns `{"stations", "terrain", "design", "custom"}`: stations in metres from the start,
    terrain sampled on `terrain` (the state just before this feature) and the design line
    either from the feature's custom long profile or regenerated from the tool rule.

    `custom` is False whenever the engine would ignore the stored profile — a multi-part path —
    so the editor never presents a line the terrain does not follow.
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
    if feature.long_profile is not None and supports_long_profile(feature):
        design = tuple((float(s), float(z)) for s, z in feature.long_profile)
        return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": True}
    try:
        design = rule_profile(feature, part, reference)
    except NoReferenceError:
        design = ()
    return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": False}


def default_section_line(feature, cell_size: float) -> bytes | None:
    """The line an area's section runs along until the user draws one (spec §5.4): through the
    centroid, along the longer side of the smallest rotated rectangle around the outline, and on past
    the outline — beyond the reach of outside slopes — so the section shows the ground around it.
    Runs west to east (or south to north). None for a path, or an outline too thin to have a longer side."""
    parts = [p for p in split_parts(feature.geometry_wkb) if not is_line(p)] if feature.mode is Mode.AREA else []
    if not parts:
        return None
    points = np.vstack([polygon_rings(p)[0] for p in parts])
    try:
        hull = points[ConvexHull(points).vertices]
    except (QhullError, ValueError):
        return None
    along, best = None, None
    for a, b in zip(hull, np.roll(hull, -1, axis=0)):
        edge = b - a
        size = float(np.hypot(*edge))
        if size == 0.0:
            continue
        u = edge / size
        v = np.array([-u[1], u[0]])
        span_u, span_v = np.ptp(hull @ u), np.ptp(hull @ v)
        if best is None or span_u * span_v < best:
            best, along = span_u * span_v, (u if span_u >= span_v else v)
    if along[0] < 0.0 or (along[0] == 0.0 and along[1] < 0.0):
        along = -along
    outline = ogr.CreateGeometryFromWkb(bytes(feature.geometry_wkb))
    centre = np.array(outline.Centroid().GetPoints()[0][:2])
    t = (points - centre) @ along
    outside = TOOL_INFO[feature.tool].has_slopes and feature.slope_n > 0.0 and not feature.slopes_inside
    margin = (feature.reach if outside else 0.0) + max(5.0 * cell_size, 0.1 * float(np.ptp(t)))
    return line_wkb([centre + (t.min() - margin) * along, centre + (t.max() + margin) * along])


def section_along(line: bytes, before: DemGrid, after: DemGrid) -> dict:
    """Terrain before and after a feature along `line`: `{"stations", "before", "after"}`, stations in
    metres from the line's start. Stations where either terrain is nodata or off the grid are left out."""
    empty = {"stations": (), "before": (), "after": ()}
    lines = [line_coords(p) for p in split_parts(line) if is_line(p)]
    coords = max(lines, key=_length, default=np.zeros((0, 2)))
    if len(coords) < 2 or _length(coords) <= 0.0:
        return empty
    stations = np.linspace(0.0, _length(coords), SAMPLES)
    xs, ys = _walk(coords, stations)
    rows = [(float(s), before.sample(x, y), after.sample(x, y)) for s, x, y in zip(stations, xs, ys)]
    rows = [row for row in rows if not (math.isnan(row[1]) or math.isnan(row[2]))]
    if not rows:
        return empty
    out = tuple(zip(*rows))
    return {"stations": out[0], "before": out[1], "after": out[2]}


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
