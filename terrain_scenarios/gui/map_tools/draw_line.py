"""Draw a line by clicking its vertices."""
from __future__ import annotations

from qgis.core import Qgis

from .base import DrawTool


class DrawLineTool(DrawTool):
    geometry_type = Qgis.GeometryType.Line
    min_vertices = 2
