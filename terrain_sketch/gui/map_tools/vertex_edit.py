"""Reshape a drawn feature by moving, adding and removing its vertices."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import Qt, pyqtSignal

from .base import SketchTool


class VertexEditTool(SketchTool):
    """Drag a vertex to move it, double-click a segment to add one, Delete removes the vertex
    under the cursor. Every change is emitted as `geometryChanged`; Esc stops editing."""

    geometryChanged = pyqtSignal(object)  # QgsGeometry in the canvas CRS

    def __init__(self, canvas, geometry: QgsGeometry):
        self.geometry_type = geometry.type()
        super().__init__(canvas)
        self.geometry = QgsGeometry(geometry)
        self.vertex_band = self.add_band(Qgis.GeometryType.Point)
        self.vertex_band.setIcon(self.vertex_band.ICON_BOX)
        self.vertex_band.setIconSize(8)
        self._dragging = None
        self._cursor = QgsPointXY()
        self._redraw()

    def canvasPressEvent(self, event):  # noqa: N802 — Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self.vertex_near(event.mapPoint())
        self._dragging = index

    def canvasMoveEvent(self, event):  # noqa: N802 — Qt override
        self._cursor = event.mapPoint()
        if self._dragging is None:
            return
        point = self.snap(event)
        self.geometry.moveVertex(point.x(), point.y(), self._dragging)
        self._redraw()

    def canvasReleaseEvent(self, event):  # noqa: N802 — Qt override
        if self._dragging is None:
            return
        self._dragging = None
        self.geometryChanged.emit(QgsGeometry(self.geometry))

    def canvasDoubleClickEvent(self, event):  # noqa: N802 — Qt override
        point = event.mapPoint()
        distance_squared, _closest, after, _left = self.geometry.closestSegmentWithContext(point)
        if after < 0 or distance_squared > self.tolerance() ** 2:
            return
        self.geometry.insertVertex(point.x(), point.y(), after)
        self._redraw()
        self.geometryChanged.emit(QgsGeometry(self.geometry))

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            event.accept()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_vertex_near(self._cursor)
            event.accept()
        else:
            event.ignore()

    def vertex_near(self, point: QgsPointXY) -> int | None:
        """Index of the vertex within grab distance of `point`, or None."""
        _closest, index, _prev, _next, distance_squared = self.geometry.closestVertex(point)
        if index < 0 or distance_squared > self.tolerance() ** 2:
            return None
        return index

    def delete_vertex_near(self, point: QgsPointXY) -> None:
        """Remove the vertex under `point` unless the shape would become unusable."""
        index = self.vertex_near(point)
        if index is None or self.vertex_count() <= self._minimum_vertices():
            return
        self.geometry.deleteVertex(index)
        self._redraw()
        self.geometryChanged.emit(QgsGeometry(self.geometry))

    def vertex_count(self) -> int:
        return sum(1 for _ in self.geometry.vertices())

    def _minimum_vertices(self) -> int:
        # a closed ring repeats its first vertex, so a triangle counts four
        return 4 if self.geometry.type() == Qgis.GeometryType.Polygon else 2

    def _redraw(self) -> None:
        self.band.setToGeometry(self.geometry, None)
        self.vertex_band.reset(Qgis.GeometryType.Point)
        for vertex in self.geometry.vertices():
            self.vertex_band.addPoint(QgsPointXY(vertex.x(), vertex.y()), False)
        self.vertex_band.updatePosition()
        self.vertex_band.update()
