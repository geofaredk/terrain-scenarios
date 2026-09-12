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
        self._before = None
        self._cursor = QgsPointXY()
        self._redraw()

    def canvasPressEvent(self, event):  # noqa: N802 — Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = self.vertex_near(event.mapPoint())
        self._before = QgsGeometry(self.geometry) if self._dragging is not None else None

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
        before, self._dragging, self._before = self._before, None, None
        if before is not None and self.geometry.isExactlyEqual(before):
            return  # a bare click on a vertex must not cost a recompute
        self._changed()

    def canvasDoubleClickEvent(self, event):  # noqa: N802 — Qt override
        point = event.mapPoint()
        distance_squared, _closest, after, _left = self.geometry.closestSegmentWithContext(point)
        if after < 0 or distance_squared > self.tolerance() ** 2:
            return
        snapped = self.snap(event)  # the proximity check uses the raw point, the vertex snaps like a drag
        self.geometry.insertVertex(snapped.x(), snapped.y(), after)
        self._changed()

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
        if index is None or not self._can_delete(index):
            return
        self.geometry.deleteVertex(index)
        self._changed()

    def vertex_count(self) -> int:
        return sum(1 for _ in self.geometry.vertices())

    def ring_vertex_count(self, index: int) -> int:
        """Vertices in the ring or part that vertex `index` belongs to; 0 when there is no such vertex."""
        found, target = self.geometry.vertexIdFromVertexNr(index)
        if not found:
            return 0
        count = 0
        for number in range(self.vertex_count()):
            ok, vertex_id = self.geometry.vertexIdFromVertexNr(number)
            if ok and vertex_id.part == target.part and vertex_id.ring == target.ring:
                count += 1
        return count

    def _can_delete(self, index: int) -> bool:
        """The ring or part holding the vertex must survive on its own: a polygon with a hole can have
        plenty of vertices overall while its exterior ring is already down to a triangle."""
        minimum = self._minimum_vertices()
        return self.vertex_count() > minimum and self.ring_vertex_count(index) > minimum

    def _minimum_vertices(self) -> int:
        # a closed ring repeats its first vertex, so a triangle counts four
        return 4 if self.geometry.type() == Qgis.GeometryType.Polygon else 2

    def _changed(self) -> None:
        self._redraw()
        self.geometryChanged.emit(QgsGeometry(self.geometry))

    def _redraw(self) -> None:
        self.band.setToGeometry(self.geometry, None)
        self.vertex_band.reset(Qgis.GeometryType.Point)
        for vertex in self.geometry.vertices():
            self.vertex_band.addPoint(QgsPointXY(vertex.x(), vertex.y()), False)
        self.vertex_band.updatePosition()
        self.vertex_band.update()
