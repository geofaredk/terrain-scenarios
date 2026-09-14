"""The seven terrain tools. `apply_feature` edits a DemGrid in place, part by part."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import QhullError

from .geometry import (corridor, densify, envelope, is_line, line_coords, polygon_rings,
                       simplify_line, split_parts)
from .grid import DemGrid, Window
from .mask import polygon_mask
from .profiles import side_dz, side_limit
from .stations import stations_offsets, vertex_stations
from .tools import TOOL_INFO, Combine, Mode, Tool, reports_storage
from .volumes import cut_fill, pond_storage

MARGIN_CELLS = 4  # >= nearest-valid search radius (3) + 1 for bilinear sampling

FLAG_OUTSIDE = "outside"
FLAG_NO_PIXELS = "no_pixels"
FLAG_NODATA_REFERENCE = "nodata_reference"
FLAG_BAD_GEOMETRY = "bad_geometry"


@dataclass(frozen=True)
class FeatureStats:
    cut: float = 0.0
    fill: float = 0.0
    storage: float | None = None
    changed_cells: int = 0
    flags: tuple = ()


class NoReferenceError(Exception):
    """A reference elevation could not be sampled because the terrain there is nodata."""


def path_coords(part, cell_size: float) -> np.ndarray:
    """Vertices of a path part as used by the engine (simplified to half a cell)."""
    return line_coords(simplify_line(part, 0.5 * cell_size))


def rule_profile(feature, part, grid: DemGrid) -> tuple:
    """Design line ((station, z), ...) of a path part from the tool rule, sampled on the
    current terrain. Stations follow the engine's simplified path; the flat tools read the
    drawn (unsimplified) vertices."""
    vertices = line_coords(part)
    length = float(vertex_stations(path_coords(part, grid.cell_size))[-1])
    tool, amount = feature.tool, feature.amount
    if tool in (Tool.RAISE_FLAT, Tool.LOWER_FLAT):
        z = np.array([grid.sample(x, y) for x, y in vertices])
        if np.isnan(z).all():
            raise NoReferenceError
        level = np.nanmax(z) + amount if tool is Tool.RAISE_FLAT else np.nanmin(z) - amount
        return ((0.0, float(level)), (length, float(level)))
    z0, z1 = grid.sample(*vertices[0]), grid.sample(*vertices[-1])
    if math.isnan(z0) or math.isnan(z1):
        raise NoReferenceError
    offset = {Tool.RAISE_PATH: amount, Tool.LOWER_PATH: -amount}.get(tool, 0.0)
    return ((0.0, z0 + offset), (length, z1 + offset))


def part_window(feature, part, grid: DemGrid) -> Window | None:
    info = TOOL_INFO[feature.tool]
    if is_line(part):
        width = max(feature.width, grid.cell_size)
        band = corridor(simplify_line(part, 0.5 * grid.cell_size), width)
        r = _path_side_limit(feature) if info.has_slopes else 0.0
        if band is None or band.IsEmpty():
            xmin, ymin, xmax, ymax = envelope(part)
            r = width / 2.0
        else:
            xmin, ymin, xmax, ymax = envelope(band)
        return grid.window_for_bbox(xmin - r, ymin - r, xmax + r, ymax + r, MARGIN_CELLS)
    xmin, ymin, xmax, ymax = envelope(part)
    r = feature.reach if (info.has_slopes and feature.slope_n > 0.0 and not feature.slopes_inside) else 0.0
    return grid.window_for_bbox(xmin - r, ymin - r, xmax + r, ymax + r, MARGIN_CELLS)


def feature_window(feature, grid: DemGrid) -> Window | None:
    """Every cell the feature may read or change, or None if it misses the grid."""
    try:
        parts = split_parts(feature.geometry_wkb)
    except ValueError:
        return None
    window = None
    for part in parts:
        w = part_window(feature, part, grid)
        if w is not None:
            window = w.union(window)
    return window


def footprint_flags(feature) -> tuple:
    """Flags for a feature that has no window on the grid."""
    try:
        split_parts(feature.geometry_wkb)
    except ValueError:
        return (FLAG_BAD_GEOMETRY,)
    return (FLAG_OUTSIDE,)


def apply_feature(feature, grid: DemGrid) -> FeatureStats:
    """Apply one feature to `grid` in place and report its volumes and problems."""
    info = TOOL_INFO[feature.tool]
    try:
        parts = split_parts(feature.geometry_wkb)
    except ValueError:
        return FeatureStats(flags=(FLAG_BAD_GEOMETRY,))
    want_line = feature.mode is Mode.PATH
    long_profile = feature.long_profile if len(parts) == 1 else None
    flags: set = set()
    cut = fill = 0.0
    storage = None
    changed = 0
    on_grid = selected_any = False
    for part in parts:
        if is_line(part) != want_line:
            flags.add(FLAG_BAD_GEOMETRY)
            continue
        window = part_window(feature, part, grid)
        if window is None:
            continue
        on_grid = True
        view = grid.view(window)
        before = view.data.astype(np.float64)
        try:
            if want_line:
                new, selected = _path_values(feature, info, part, view, long_profile)
            else:
                new, selected = _area_values(feature, info, part, view)
        except NoReferenceError:
            flags.add(FLAG_NODATA_REFERENCE)
            continue
        selected &= view.valid
        if not selected.any():
            continue
        selected_any = True
        view.data[selected] = new[selected].astype(view.data.dtype)
        after = view.data.astype(np.float64)
        c, f = cut_fill(before, after, view.valid, grid.cell_area)
        cut, fill = cut + c, fill + f
        changed += int(((after != before) & view.valid).sum())
        if reports_storage(feature.tool, feature.mode):
            s = pond_storage(after, (after < before) & view.valid, view.valid, grid.cell_area)
            if s is not None:
                storage = (storage or 0.0) + s
    if not on_grid and not flags:
        flags.add(FLAG_OUTSIDE)
    elif on_grid and not selected_any and not flags:
        flags.add(FLAG_NO_PIXELS)
    return FeatureStats(cut, fill, storage, changed, tuple(sorted(flags)))


def _combine(combine: Combine, old: np.ndarray, design: np.ndarray) -> np.ndarray:
    if combine is Combine.MAX:
        return np.maximum(old, design)
    if combine is Combine.MIN:
        return np.minimum(old, design)
    return design


def _path_values(feature, info, drawn, view: DemGrid, long_profile):
    part = simplify_line(drawn, 0.5 * view.cell_size)
    coords = line_coords(part)
    old = view.data.astype(np.float64)
    if len(coords) < 2:
        return old, np.zeros(old.shape, bool)
    width = max(feature.width, view.cell_size)
    band_geom = corridor(part, width)
    core = polygon_mask(band_geom, view, feature.pixel_mode)
    if feature.tool is Tool.ADD:
        return old + feature.amount, core
    if feature.tool is Tool.SUBTRACT:
        return old - feature.amount, core
    profile = sorted(long_profile) if long_profile else rule_profile(feature, drawn, view)
    if feature.tool is Tool.INTERPOLATE:
        station, _ = _stations(coords, view, core)
        return np.interp(station, [p[0] for p in profile], [p[1] for p in profile]), core
    if not core.any():
        return old, core
    # distance beyond the crest (the outline lies half a cell from core centres)
    dist = ndimage.distance_transform_edt(~core, sampling=(view.cell_height, view.cell_width))
    beyond = np.maximum(dist - 0.5 * view.cell_size, 0.0)
    # stations only where a cell can change: the crest and the cells within slope reach
    station, offset = _stations(coords, view, core | (beyond <= _path_side_limit(feature)))
    zline = np.interp(station, [p[0] for p in profile], [p[1] for p in profile])
    dz_l, ext_l = side_dz(beyond, feature.cross_left, feature.slope_n, feature.reach, info.direction)
    dz_r, ext_r = side_dz(beyond, feature.cross_right, feature.slope_n, feature.reach, info.direction)
    left = offset < 0.0
    in_extent = np.where(left, ext_l, ext_r)
    dz = np.where(core, 0.0, np.where(left, dz_l, dz_r))
    slope_cells = ~core & in_extent
    return _combine(info.combine, old, zline + dz), core | slope_cells


def _path_side_limit(feature) -> float:
    return max(side_limit(feature.cross_left, feature.slope_n, feature.reach),
               side_limit(feature.cross_right, feature.slope_n, feature.reach))


def _stations(coords: np.ndarray, view: DemGrid, cells: np.ndarray):
    """Station and signed offset for the selected cells (zero elsewhere)."""
    X, Y = view.cell_centers()
    station = np.zeros(cells.shape)
    offset = np.zeros(cells.shape)
    station[cells], offset[cells] = stations_offsets(coords, X[cells], Y[cells])
    return station, offset


def _area_values(feature, info, part, view: DemGrid):
    core = polygon_mask(part, view, feature.pixel_mode)
    old = view.data.astype(np.float64)
    tool = feature.tool
    if tool is Tool.ADD:
        return old + feature.amount, core
    if tool is Tool.SUBTRACT:
        return old - feature.amount, core
    if tool is Tool.INTERPOLATE:
        return _vertex_surface(part, view), core
    ring = densify(polygon_rings(part)[0], view.cell_size)
    z = np.array([view.sample(x, y) for x, y in ring])
    if np.isnan(z).all():
        raise NoReferenceError
    level = np.nanmax(z) + feature.amount if tool is Tool.RAISE_FLAT else np.nanmin(z) - feature.amount
    design, selected = _area_design(feature, info, core, view, float(level))
    return _combine(info.combine, old, design), selected


def _area_design(feature, info, core: np.ndarray, view: DemGrid, level: float):
    design = np.full(core.shape, level)
    if feature.slope_n <= 0.0 or not core.any() or core.all():
        return design, core
    sampling = (view.cell_height, view.cell_width)
    half_cell = 0.5 * view.cell_size
    if not feature.slopes_inside:
        dist = ndimage.distance_transform_edt(~core, sampling=sampling)
        beyond = np.maximum(dist - half_cell, 0.0)
        dz, in_extent = side_dz(beyond, (), feature.slope_n, feature.reach, info.direction)
        return level + np.where(core, 0.0, dz), core | in_extent
    dist, (ri, ci) = ndimage.distance_transform_edt(core, sampling=sampling, return_indices=True)
    inward = np.maximum(dist - half_cell, 0.0)
    edge = view.data[ri, ci].astype(np.float64)  # terrain just outside the outline
    if info.direction > 0:
        slope = np.maximum(level, edge - inward / feature.slope_n)
    else:
        slope = np.minimum(level, edge + inward / feature.slope_n)
    return np.where(view.valid[ri, ci], slope, level), core


def _vertex_surface(part, view: DemGrid) -> np.ndarray:
    pts = np.vstack([ring[:-1] for ring in polygon_rings(part)])
    z = np.array([view.sample(x, y) for x, y in pts])
    ok = ~np.isnan(z)
    if not ok.any():
        raise NoReferenceError
    pts, z = pts[ok], z[ok]
    X, Y = view.cell_centers()
    nearest = NearestNDInterpolator(pts, z)(X, Y)
    try:
        surface = LinearNDInterpolator(pts, z)(X, Y)
    except (QhullError, ValueError):
        return nearest
    return np.where(np.isnan(surface), nearest, surface)