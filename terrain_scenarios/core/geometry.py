"""OGR geometry helpers: WKB in/out, single-part LineStrings/Polygons in the DEM CRS."""
from __future__ import annotations

import math

import numpy as np
from osgeo import ogr

ogr.UseExceptions()

_SINGLE = (ogr.wkbLineString, ogr.wkbPolygon)
_MULTI = (ogr.wkbMultiLineString, ogr.wkbMultiPolygon, ogr.wkbGeometryCollection)


def split_parts(wkb: bytes) -> list:
    """Single-part 2D LineStrings/Polygons contained in `wkb`. Raises ValueError for other types."""
    geom = ogr.CreateGeometryFromWkb(bytes(wkb))
    parts: list = []
    _collect(geom, parts)
    return parts


def _collect(geom, parts: list) -> None:
    if geom is None or geom.IsEmpty():
        return
    gtype = ogr.GT_Flatten(geom.GetGeometryType())
    if ogr.GT_IsNonLinear(gtype):
        geom = geom.GetLinearGeometry()
        gtype = ogr.GT_Flatten(geom.GetGeometryType())
    if gtype in _SINGLE:
        part = geom.Clone()
        part.FlattenTo2D()
        parts.append(part)
    elif gtype in _MULTI:
        for i in range(geom.GetGeometryCount()):
            _collect(geom.GetGeometryRef(i), parts)
    else:
        raise ValueError(f"Unsupported geometry type: {ogr.GeometryTypeToName(gtype)}")


def is_line(part) -> bool:
    return ogr.GT_Flatten(part.GetGeometryType()) == ogr.wkbLineString


def line_coords(part) -> np.ndarray:
    """(N, 2) vertices with consecutive duplicates removed."""
    pts = np.array(part.GetPoints(), dtype=float)[:, :2]
    keep = np.ones(len(pts), dtype=bool)
    keep[1:] = np.any(np.diff(pts, axis=0) != 0.0, axis=1)
    return pts[keep]


def polygon_rings(part) -> list[np.ndarray]:
    """Closed rings as (N, 2) arrays, exterior first."""
    return [np.array(part.GetGeometryRef(i).GetPoints(), dtype=float)[:, :2]
            for i in range(part.GetGeometryCount())]


def envelope(part) -> tuple[float, float, float, float]:
    xmin, xmax, ymin, ymax = part.GetEnvelope()
    return xmin, ymin, xmax, ymax


def simplify_line(part, tolerance: float):
    simple = part.Simplify(tolerance)
    return simple if simple is not None and not simple.IsEmpty() else part


def corridor(line_part, width: float):
    """The line buffered by width/2 with flat end caps and mitre joins."""
    return line_part.Buffer(width / 2.0, ["ENDCAP_STYLE=FLAT", "JOIN_STYLE=MITRE", "MITRE_LIMIT=2.0"])


def densify(coords: np.ndarray, step: float) -> np.ndarray:
    """Points along a polyline/ring at most `step` apart, including every vertex."""
    out = [coords[:1]]
    for a, b in zip(coords[:-1], coords[1:]):
        n = max(1, math.ceil(float(np.hypot(*(b - a))) / step))
        t = np.arange(1, n + 1)[:, None] / n
        out.append(a + t * (b - a))
    return np.vstack(out)


def line_wkb(coords) -> bytes:
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in coords:
        g.AddPoint_2D(float(x), float(y))
    return bytes(g.ExportToWkb())


def polygon_wkb(exterior, holes=()) -> bytes:
    g = ogr.Geometry(ogr.wkbPolygon)
    for ring_coords in (exterior, *holes):
        ring = ogr.Geometry(ogr.wkbLinearRing)
        for x, y in ring_coords:
            ring.AddPoint_2D(float(x), float(y))
        ring.CloseRings()
        g.AddGeometry(ring)
    return bytes(g.ExportToWkb())


def multi_wkb(wkbs) -> bytes:
    """Combine single-part WKBs of the same kind into a Multi* WKB."""
    parts = [ogr.CreateGeometryFromWkb(bytes(w)) for w in wkbs]
    kind = ogr.wkbMultiLineString if is_line(parts[0]) else ogr.wkbMultiPolygon
    g = ogr.Geometry(kind)
    for p in parts:
        g.AddGeometry(p)
    return bytes(g.ExportToWkb())
