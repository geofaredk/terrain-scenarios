"""Shared behaviour of the drawing tools: snapping, rubber band and QGIS digitizing keys."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointLocator, QgsPointXY
from qgis.gui import QgsMapTool, QgsMapToolEdit, QgsRubberBand, QgsSnapIndicator
from qgis.PyQt.QtCore import Qt, pyqtSignal


class DrawTool(QgsMapTool):
    """Click vertices like in QGIS digitizing: right-click or Enter finishes, Backspace or
    Delete removes the last vertex, Esc cancels. Snaps with the project's snapping settings."""

    finished = pyqtSignal(object)  # QgsGeometry in the canvas CRS
    cancelled = pyqtSignal()

    geometry_type = Qgis.GeometryType.Line
    min_vertices = 2

    def __init__(self, canvas):
        super().__init__(canvas)
        self.points: list[QgsPointXY] = []
        self.band = QgsRubberBand(canvas, self.geometry_type)
        self.band.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.band.setFillColor(QgsMapToolEdit.digitizingFillColor())
        self.band.setWidth(QgsMapToolEdit.digitizingStrokeWidth())
        self.snap_indicator = QgsSnapIndicator(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def build_geometry(self, points: list[QgsPointXY]) -> QgsGeometry:
        return QgsGeometry.fromPolylineXY(points)

    def canvasMoveEvent(self, event):  # noqa: N802 — Qt override
        self._redraw(self._snap(event))

    def canvasReleaseEvent(self, event):  # noqa: N802 — Qt override
        if event.button() == Qt.MouseButton.RightButton:
            self.finish()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.points.append(self._snap(event))
            self._redraw()

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        key = event.key()
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and self.points:
            self.points.pop()
            self._redraw()
            event.accept()
        elif key == Qt.Key.Key_Escape:
            self.reset()
            self.cancelled.emit()
            event.accept()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish()
            event.accept()
        else:
            event.ignore()

    def finish(self) -> None:
        """Emit the drawn geometry; does nothing until there are enough vertices."""
        if len(self.points) < self.min_vertices:
            return
        geometry = self.build_geometry(self.points)
        self.reset()
        self.finished.emit(geometry)

    def reset(self) -> None:
        self.points = []
        self.band.reset(self.geometry_type)
        self.snap_indicator.setMatch(QgsPointLocator.Match())

    def deactivate(self):
        self.reset()
        super().deactivate()

    def _snap(self, event) -> QgsPointXY:
        match = self.canvas().snappingUtils().snapToMap(event.mapPoint())
        self.snap_indicator.setMatch(match)
        return match.point() if match.isValid() else event.mapPoint()

    def _redraw(self, hover: QgsPointXY | None = None) -> None:
        points = self.points + ([hover] if hover is not None and self.points else [])
        self.band.reset(self.geometry_type)
        for i, point in enumerate(points):
            self.band.addPoint(point, i == len(points) - 1)
