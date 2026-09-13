"""A profile plot with draggable handles, in cross-section or long-section mode."""
from __future__ import annotations

import math
from enum import Enum

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

from .help_texts import PROFILE_EMPTY_HINT

MARGIN_LEFT, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_RIGHT = 46, 26, 10, 12
GRAB_PIXELS = 8
HANDLE_RADIUS = 4
NUDGE, NUDGE_FINE = 0.1, 0.01


class Kind(Enum):
    CROSS = "cross"
    LONG = "long"


class ProfileWidget(QWidget):
    """Draws the reference terrain, the design line and draggable handles.

    Dragging emits `profileChanged` continuously and `profileCommitted` on release, both with
    the full point list. The widget owns no feature state: whoever drives it sets points and
    applies the edits.
    """

    profileChanged = pyqtSignal(object)     # ((x, z), ...) while dragging
    profileCommitted = pyqtSignal(object)   # ((x, z), ...) on release
    selectionChanged = pyqtSignal(int)      # index of the highlighted handle, -1 for none

    def __init__(self, kind: Kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.points: list[tuple[float, float]] = []
        self.terrain: list[tuple[float, float]] = []
        self.editable = True
        self.hint = PROFILE_EMPTY_HINT
        self.selected = -1
        self._dragging = -1
        self._before: list | None = None
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- contents -------------------------------------------------------------------

    def set_profile(self, points, terrain=(), editable=True) -> None:
        self.points = [(float(x), float(z)) for x, z in points]
        self.terrain = [(float(x), float(z)) for x, z in terrain]
        self.editable = editable
        self.selected = -1
        self._dragging = -1
        self.update()

    def clear(self, hint: str = PROFILE_EMPTY_HINT) -> None:
        self.points, self.terrain, self.hint, self.selected = [], [], hint, -1
        self.update()

    def handle_at(self, position) -> int:
        """Index of the handle within grab distance of a widget position, or -1."""
        for index, (x, z) in enumerate(self.points):
            if (self._to_screen(x, z) - QPointF(position.x(), position.y())).manhattanLength() \
                    <= GRAB_PIXELS * 2:
                return index
        return -1

    # ---- painting -------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802 — Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        if not self.points and not self.terrain:
            painter.setPen(palette.mid().color())
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self.hint)
            return
        self._draw_grid(painter, palette)
        if self.terrain:
            self._draw_terrain(painter, palette)
        self._draw_design(painter, palette)
        if self.editable:
            self._draw_handles(painter, palette)

    def _draw_grid(self, painter, palette) -> None:
        plot = self._plot_rect()
        painter.setPen(QPen(palette.mid().color(), 1))
        painter.drawRect(plot)
        grid = QColor(palette.mid().color())
        grid.setAlpha(60)
        for value in self._ticks(*self._z_range()):
            y = self._to_screen(self._x_range()[0], value).y()
            painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(palette.windowText().color())
            painter.drawText(QRectF(0, y - 8, MARGIN_LEFT - 4, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{value:g}")
        for value in self._ticks(*self._x_range()):
            x = self._to_screen(value, self._z_range()[0]).x()
            painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(palette.windowText().color())
            painter.drawText(QRectF(x - 30, plot.bottom() + 2, 60, MARGIN_BOTTOM - 4),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             f"{value:g}")
        painter.setPen(palette.windowText().color())
        painter.drawText(QRectF(0, 0, MARGIN_LEFT + 40, MARGIN_TOP + 8),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.tr("m"))

    def _draw_terrain(self, painter, palette) -> None:
        pen = QPen(palette.windowText().color(), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([self._to_screen(x, z) for x, z in self.terrain]))

    def _draw_design(self, painter, palette) -> None:
        if len(self.points) < 2:
            return
        design = [self._to_screen(x, z) for x, z in self.points]
        if self.terrain:
            self._shade_between(painter)
        painter.setPen(QPen(palette.highlight().color(), 2))
        painter.drawPolyline(QPolygonF(design))

    def _shade_between(self, painter) -> None:
        """Fill above the reference in warm, cut below it in cool — the map's change colours."""
        reference = self._resampled_terrain()
        if reference is None:
            return
        for colour, above in ((QColor(230, 140, 60, 70), True), (QColor(60, 120, 200, 70), False)):
            path = QPainterPath()
            started = False
            for (x, z), (_rx, rz) in zip(self.points, reference):
                if (z > rz) == above and abs(z - rz) > 1e-9:
                    if not started:
                        path.moveTo(self._to_screen(x, rz))
                        started = True
                    path.lineTo(self._to_screen(x, z))
                elif started:
                    path.lineTo(self._to_screen(x, rz))
                    path.closeSubpath()
                    started = False
            if started:
                path.lineTo(self._to_screen(self.points[-1][0], reference[-1][1]))
                path.closeSubpath()
            painter.fillPath(path, colour)

    def _resampled_terrain(self):
        if not self.terrain:
            return None
        xs = [x for x, _ in self.terrain]
        zs = [z for _, z in self.terrain]
        out = []
        for x, _z in self.points:
            out.append((x, _interpolate(x, xs, zs)))
        return out

    def _draw_handles(self, painter, palette) -> None:
        for index, (x, z) in enumerate(self.points):
            centre = self._to_screen(x, z)
            painter.setPen(QPen(palette.highlight().color(), 1))
            painter.setBrush(palette.highlight() if index == self.selected else palette.base())
            painter.drawEllipse(centre, HANDLE_RADIUS, HANDLE_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # ---- interaction ----------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802 — Qt override
        if not self.editable:
            return
        index = self.handle_at(event.position())
        if event.button() == Qt.MouseButton.RightButton:
            if index > 0 and index < len(self.points) - 1:
                self.points.pop(index)
                self.selected = -1
                self.update()
                self.profileCommitted.emit(tuple(self.points))
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.selected = index
        self._dragging = index
        self._before = list(self.points)
        self.selectionChanged.emit(index)
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802 — Qt override
        if self._dragging < 0:
            return
        self._move_handle(self._dragging, self._to_data(event.position()))
        self.profileChanged.emit(tuple(self.points))

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt override
        if self._dragging < 0:
            return
        self._dragging = -1
        if self._before != self.points:
            self.profileCommitted.emit(tuple(self.points))
        self._before = None

    def mouseDoubleClickEvent(self, event):  # noqa: N802 — Qt override
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        x, z = self._to_data(event.position())
        index = self._insertion_index(x)
        if index is None:
            return
        self.points.insert(index, (x, z))
        self.selected = index
        self._dragging = -1
        self.update()
        self.profileCommitted.emit(tuple(self.points))

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        step = NUDGE_FINE if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else NUDGE
        deltas = {Qt.Key.Key_Up: (0.0, step), Qt.Key.Key_Down: (0.0, -step),
                  Qt.Key.Key_Left: (-step, 0.0), Qt.Key.Key_Right: (step, 0.0)}
        if self.selected < 0 or not self.editable or event.key() not in deltas:
            event.ignore()
            return
        dx, dz = deltas[event.key()]
        x, z = self.points[self.selected]
        self._move_handle(self.selected, (x + dx, z + dz))
        self.profileCommitted.emit(tuple(self.points))
        event.accept()

    def _move_handle(self, index: int, position) -> None:
        x, z = position
        if not self._can_move_x(index):
            x = self.points[index][0]
        else:
            low = self.points[index - 1][0] if index > 0 else None
            high = self.points[index + 1][0] if index < len(self.points) - 1 else None
            if low is not None:
                x = max(x, low + 1e-6)
            if high is not None:
                x = min(x, high - 1e-6)
            x = max(x, 0.0) if self.kind is Kind.CROSS else x
        self.points[index] = (x, z)
        self.update()

    def _can_move_x(self, index: int) -> bool:
        """The first point is pinned; in a long section the last one is too (it is the end)."""
        if index == 0:
            return False
        return not (self.kind is Kind.LONG and index == len(self.points) - 1)

    def _insertion_index(self, x: float):
        for index in range(1, len(self.points)):
            if self.points[index - 1][0] < x < self.points[index][0]:
                return index
        return None

    # ---- coordinate transforms ------------------------------------------------------

    def _plot_rect(self) -> QRectF:
        return QRectF(MARGIN_LEFT, MARGIN_TOP,
                      max(self.width() - MARGIN_LEFT - MARGIN_RIGHT, 1.0),
                      max(self.height() - MARGIN_TOP - MARGIN_BOTTOM, 1.0))

    def _x_range(self) -> tuple[float, float]:
        xs = [x for x, _ in self.points] + [x for x, _ in self.terrain]
        return (min(xs), max(xs)) if xs else (0.0, 1.0)

    def _z_range(self) -> tuple[float, float]:
        zs = [z for _, z in self.points] + [z for _, z in self.terrain]
        if not zs:
            return (0.0, 1.0)
        low, high = min(zs), max(zs)
        if high - low < 1e-6:
            low, high = low - 0.5, high + 0.5
        pad = (high - low) * 0.12
        return low - pad, high + pad

    def _to_screen(self, x: float, z: float) -> QPointF:
        plot = self._plot_rect()
        x0, x1 = self._x_range()
        z0, z1 = self._z_range()
        sx = plot.left() + (x - x0) / (x1 - x0 or 1.0) * plot.width()
        sy = plot.bottom() - (z - z0) / (z1 - z0 or 1.0) * plot.height()
        return QPointF(sx, sy)

    def _to_data(self, position) -> tuple[float, float]:
        plot = self._plot_rect()
        x0, x1 = self._x_range()
        z0, z1 = self._z_range()
        x = x0 + (position.x() - plot.left()) / (plot.width() or 1.0) * (x1 - x0)
        z = z0 + (plot.bottom() - position.y()) / (plot.height() or 1.0) * (z1 - z0)
        return float(x), float(z)

    @staticmethod
    def _ticks(low: float, high: float, count: int = 5) -> list:
        if high <= low:
            return [low]
        raw = (high - low) / count
        magnitude = 10 ** _floor_log10(raw)
        step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw),
                   default=magnitude)
        first = step * round(low / step + 0.5)
        out, value = [], first
        while value <= high:
            out.append(round(value, 6))
            value += step
        return out


def _floor_log10(value: float) -> int:
    return int(math.floor(math.log10(value))) if value > 0 else 0


def _interpolate(x: float, xs, zs) -> float:
    if not xs:
        return 0.0
    if x <= xs[0]:
        return zs[0]
    if x >= xs[-1]:
        return zs[-1]
    for i in range(1, len(xs)):
        if xs[i] >= x:
            span = xs[i] - xs[i - 1]
            t = 0.0 if span <= 0 else (x - xs[i - 1]) / span
            return zs[i - 1] + t * (zs[i] - zs[i - 1])
    return zs[-1]
