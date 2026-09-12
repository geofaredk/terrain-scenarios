"""Trace a shape with the mouse held down."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import Qt

from .base import SketchTool


class FreehandTool(SketchTool):
    """Press, trace, release. Area mode closes the traced ring; Esc cancels."""

    min_vertices = 2

    def __init__(self, canvas, geometry_type=Qgis.GeometryType.Line):
        self.geometry_type = geometry_type
        super().__init__(canvas)
        self.points: list[QgsPointXY] = []
        self._tracing = False

    def canvasPressEvent(self, event):  # noqa: N802 — Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._tracing = True
        self.points = [event.mapPoint()]
        self._redraw()

    def canvasMoveEvent(self, event):  # noqa: N802 — Qt override
        if not self._tracing:
            return
        point = event.mapPoint()
        if not self.points or point.distance(self.points[-1]) >= self.tolerance(2.0):
            self.points.append(point)
            self._redraw()

    def canvasReleaseEvent(self, event):  # noqa: N802 — Qt override
        if event.button() != Qt.MouseButton.LeftButton or not self._tracing:
            return
        self._tracing = False
        self.points.append(event.mapPoint())
        self.finish()

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.reset()
            self.cancelled.emit()
            event.accept()
        else:
            event.ignore()

    def finish(self) -> None:
        """Emit the traced geometry; a trace with too few points is dropped."""
        points = self.points
        needed = 3 if self.geometry_type == Qgis.GeometryType.Polygon else 2
        self.reset()
        if len(points) < needed:
            return
        if self.geometry_type == Qgis.GeometryType.Polygon:
            geometry = QgsGeometry.fromPolygonXY([points + [points[0]]])
        else:
            geometry = QgsGeometry.fromPolylineXY(points)
        self.finished.emit(geometry)

    def reset(self) -> None:
        self.points = []
        self._tracing = False
        super().reset()

    def _redraw(self) -> None:
        self.band.reset(self.geometry_type)
        for i, point in enumerate(self.points):
            self.band.addPoint(point, i == len(self.points) - 1)
