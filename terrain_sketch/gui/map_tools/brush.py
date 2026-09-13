"""Paint the area of a feature with a round brush."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import Qt, pyqtSignal

from .base import SketchTool

BUFFER_SEGMENTS = 12
RADIUS_STEP = 1.25


class BrushTool(SketchTool):
    """Paint with the left button, hold Shift to erase. `[` and `]` or Ctrl+wheel change the
    radius; right-click or Enter finishes, Esc cancels. Starts from `initial` when extending
    an existing feature."""

    radiusChanged = pyqtSignal(float)

    geometry_type = Qgis.GeometryType.Polygon

    def __init__(self, canvas, radius: float, initial: QgsGeometry | None = None):
        super().__init__(canvas)
        self.set_radius(radius)
        self.geometry = QgsGeometry(initial) if initial is not None and not initial.isEmpty() else QgsGeometry()
        self.cursor_band = self.add_band(Qgis.GeometryType.Polygon, stroke_only=True)
        self._points: list[QgsPointXY] = []
        self._erasing = False
        self._redraw()

    def set_radius(self, radius: float) -> None:
        self.radius = max(float(radius), 0.01)
        self.radiusChanged.emit(self.radius)

    def canvasPressEvent(self, event):  # noqa: N802 — Qt override
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._erasing = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        self._points = [event.mapPoint()]

    def canvasMoveEvent(self, event):  # noqa: N802 — Qt override
        point = event.mapPoint()
        if self._points:
            self._points.append(point)
        self._draw_cursor(point)

    def canvasReleaseEvent(self, event):  # noqa: N802 — Qt override
        if event.button() == Qt.MouseButton.RightButton:
            self.finish()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self._points:
            return
        self._points.append(event.mapPoint())
        self.apply_stroke(self._points, erase=self._erasing)
        self._points = []

    def apply_stroke(self, points: list[QgsPointXY], erase: bool = False) -> None:
        """Add the painted stroke to the feature's area, or cut it away when erasing."""
        stroke = self._stroke(points)
        if self.geometry.isEmpty():
            self.geometry = QgsGeometry() if erase else stroke
        else:
            self.geometry = self.geometry.difference(stroke) if erase else self.geometry.combine(stroke)
        self._redraw()

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reset()
            self.cancelled.emit()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish()
        elif key == Qt.Key.Key_BracketLeft:
            self.set_radius(self.radius / RADIUS_STEP)
        elif key == Qt.Key.Key_BracketRight:
            self.set_radius(self.radius * RADIUS_STEP)
        else:
            event.ignore()
            return
        event.accept()

    def wheelEvent(self, event):  # noqa: N802 — Qt override
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(event)
            return
        step = RADIUS_STEP if event.angleDelta().y() > 0 else 1 / RADIUS_STEP
        self.set_radius(self.radius * step)
        event.accept()

    def finish(self) -> None:
        """Emit the painted area; an area erased to nothing ends the stroke as a cancellation."""
        geometry = QgsGeometry(self.geometry)
        self.reset()
        if geometry.isEmpty():
            self.cancelled.emit()
            return
        self.finished.emit(geometry)

    def reset(self) -> None:
        self.geometry = QgsGeometry()
        self._points = []
        super().reset()

    def _stroke(self, points: list[QgsPointXY]) -> QgsGeometry:
        line = QgsGeometry.fromPointXY(points[0]) if len(points) == 1 else QgsGeometry.fromPolylineXY(points)
        return line.buffer(self.radius, BUFFER_SEGMENTS)

    def _draw_cursor(self, point: QgsPointXY) -> None:
        self.cursor_band.setToGeometry(QgsGeometry.fromPointXY(point).buffer(self.radius, BUFFER_SEGMENTS), None)

    def _redraw(self) -> None:
        self.band.reset(Qgis.GeometryType.Polygon)
        if not self.geometry.isEmpty():
            self.band.setToGeometry(self.geometry, None)
