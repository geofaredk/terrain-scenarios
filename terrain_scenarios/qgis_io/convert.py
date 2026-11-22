"""QGIS geometries to engine WKB in the DEM CRS, and back."""
from __future__ import annotations

from qgis.core import Qgis, QgsCoordinateTransform, QgsGeometry, QgsProject

from ..core.tools import Mode


def to_dem_wkb(geometry: QgsGeometry, source_crs, dem_crs, mode: Mode) -> bytes:
    """Transform to the DEM CRS, repair, and keep only the parts that fit `mode` (lines for
    paths, polygons for areas). Raises ValueError with a user-facing message if none remain."""
    geom = QgsGeometry(geometry)
    if source_crs != dem_crs:
        geom.transform(QgsCoordinateTransform(source_crs, dem_crs, QgsProject.instance()))
    if not geom.isGeosValid():
        geom = geom.makeValid()
    wanted = Qgis.GeometryType.Line if mode is Mode.PATH else Qgis.GeometryType.Polygon
    parts = [p for p in geom.asGeometryCollection() if p.type() == wanted and not p.isEmpty()]
    if not parts:
        kind = "line" if mode is Mode.PATH else "area"
        raise ValueError(f"The drawn shape contains no {kind} that can be used.")
    combined = parts[0] if len(parts) == 1 else QgsGeometry.collectGeometry(parts)
    return bytes(combined.asWkb())


def from_wkb(wkb: bytes) -> QgsGeometry:
    geometry = QgsGeometry()
    geometry.fromWkb(bytes(wkb))
    return geometry
