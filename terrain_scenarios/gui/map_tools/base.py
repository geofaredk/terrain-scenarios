"""Shared behaviour of the sketch map tools: snapping, rubber bands and QGIS digitizing keys."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointLocator, QgsPointXY
from qgis.gui import QgsMapTool, QgsMapToolEdit, QgsRubberBand, QgsSnapIndicator
from qgis.PyQt.QtCore import Qt, pyqtSignal


class SketchTool(QgsMapTool):
    """Base for every Terrain Scenarios map tool: styled rubber bands, project snapping, cleanup."""

    finished = pyqtSignal(object)  # QgsGeometry in the canvas CRS
    cancelled = pyqtSignal()

    geometry_type = Qgis.GeometryType.Line

    def __init__(self, canvas):
        super().__init__(canvas)
        self._bands: list[tuple[QgsRubberBand, Qgis.GeometryType]] = []
        self.band = self.add_band(self.geometry_type)
        self.snap_indicator = QgsSnapIndicator(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def add_band(self, geometry_type, stroke_only: bool = False) -> QgsRubberBand:
        """A rubber band styled like QGIS digitizing, released again by `dispose()`."""
        band = QgsRubberBand(self.canvas(), geometry_type)
        band.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        band.setFillColor(Qt.GlobalColor.transparent if stroke_only else QgsMapToolEdit.digitizingFillColor())
        band.setWidth(QgsMapToolEdit.digitizingStrokeWidth())
        self._bands.append((band, geometry_type))
        return band

    def reset(self) -> None:
        for band, geometry_type in self._bands:
            band.reset(geometry_type)
        if self.snap_indicator is not None:
            self.snap_indicator.setMatch(QgsPointLocator.Match())

    def dispose(self) -> None:
        """Release this tool's canvas scene items; call before `deleteLater()`."""
        self.reset()
        scene = self.canvas().scene()
        for band, _geometry_type in self._bands:
            scene.removeItem(band)
        self._bands = []  # the snap indicator's marker goes with the tool itself

    def deactivate(self):
        self.reset()
        super().deactivate()

    def snap(self, event) -> QgsPointXY:
        match = self.canvas().snappingUtils().snapToMap(event.mapPoint())
        if self.snap_indicator is not None:
            self.snap_indicator.setMatch(match)
        return match.point() if match.isValid() else event.mapPoint()

    def tolerance(self, pixels: float = 10.0) -> float:
        """`pixels` screen pixels expressed in map units."""
        return self.canvas().mapUnitsPerPixel() * pixels


class DrawTool(SketchTool):
    """Click vertices like in QGIS digitizing: right-click or Enter finishes, Backspace or
    Delete removes the last vertex, Esc cancels. Snaps with the project's snapping settings."""

    min_vertices = 2

    def __init__(self, canvas):
        super().__init__(canvas)
        self.points: list[QgsPointXY] = []

    def build_geometry(self, points: list[QgsPointXY]) -> QgsGeometry:
        return QgsGeometry.fromPolylineXY(points)

    def canvasMoveEvent(self, event):  # noqa: N802 — Qt override
        self._redraw(self.snap(event))

    def canvasReleaseEvent(self, event):  # noqa: N802 — Qt override
        if event.button() == Qt.MouseButton.RightButton:
            self.finish()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.points.append(self.snap(event))
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
        super().reset()

    def _redraw(self, hover: QgsPointXY | None = None) -> None:
        points = self.points + ([hover] if hover is not None and self.points else [])
        self.band.reset(self.geometry_type)
        for i, point in enumerate(points):
            self.band.addPoint(point, i == len(points) - 1)
