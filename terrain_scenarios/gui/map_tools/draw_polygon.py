"""Draw an area by clicking its corners."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointXY

from .base import DrawTool


class DrawPolygonTool(DrawTool):
    geometry_type = Qgis.GeometryType.Polygon
    min_vertices = 3

    def build_geometry(self, points: list[QgsPointXY]) -> QgsGeometry:
        return QgsGeometry.fromPolygonXY([points + [points[0]]])
