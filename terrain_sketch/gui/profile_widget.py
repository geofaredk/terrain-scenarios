"""A profile plot with draggable handles, in cross-section or long-section mode."""
from __future__ import annotations

import math
from enum import Enum

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

from .help_texts import PROFILE_EMPTY_HINT
from .overlay import CUT, FILL

MARGIN_LEFT, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_RIGHT = 46, 26, 10, 12
SHADE_ALPHA = 70        # the plot shades the same change as the map overlay, but behind the lines
GRAB_PIXELS = 8
HANDLE_RADIUS = 4
NUDGE, NUDGE_FINE = 0.1, 0.01
NUDGE_KEYS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right)
MIN_HALF_WIDTH = 0.05   # the narrowest corridor a path takes is 0.1 m


class Kind(Enum):
    CROSS = "cross"
    LONG = "long"


class ProfileWidget(QWidget):
    """Draws the reference terrain, the design line and draggable handles.

    Dragging emits `profileChanged` continuously and `profileCommitted` on release, both with
    the full point list. The arrow keys work the same way: each press (and each auto-repeat while a
    key is held) emits `profileChanged`, and letting go of the key commits once. The widget owns no
    feature state: whoever drives it sets points and applies the edits.

    A `mirrored` cross profile shows both sides of a path around a centre line at 0: no handle crosses
    it, the two crest edges move together (a path's width is one value), and while `symmetric` is set
    every handle that has a mirror image on the other side takes it along.
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
        self.allow_breaks = True
        self.mirrored = False
        self.symmetric = False
        self.hint = PROFILE_EMPTY_HINT
        self.selected = -1
        self._dragging = -1
        self._before: list | None = None
        self._nudge_before: list | None = None   # the points before the arrow key now held
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- contents -------------------------------------------------------------------

    def set_profile(self, points, terrain=(), editable=True, allow_breaks=True,
                    hint: str = PROFILE_EMPTY_HINT, mirrored: bool = False) -> None:
        """Show `points` over `terrain`.

        `allow_breaks` is False when the engine does not use break points for this feature, so
        the plot must refuse to add or remove them; `hint` is what an empty plot says instead of
        the default "select a feature". The widget knows nothing about features: the dock, which
        does, sets both.

        The selected handle stays selected when the new profile has as many points: every drag and
        nudge commits, and the commit reloads the plot, so the next arrow key must still find it.
        """
        points = [(float(x), float(z)) for x, z in points]
        if len(points) != len(self.points):
            self.selected = -1
        self.points = points
        self.terrain = [(float(x), float(z)) for x, z in terrain]
        self.editable = editable
        self.allow_breaks = allow_breaks
        self.mirrored = mirrored
        self.hint = hint
        self._dragging = -1
        self._nudge_before = None
        self.update()

    def clear(self, hint: str = PROFILE_EMPTY_HINT) -> None:
        self.points, self.terrain, self.hint, self.selected = [], [], hint, -1
        self._dragging, self._before = -1, None   # an undo can clear the plot under a drag
        self._nudge_before = None
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
        if self.mirrored:
            self._draw_sides(painter, palette)

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
        """Fill above the reference in warm, cut below it in cool — the drag preview's colours.

        These are the overlay's FILL and CUT, so the plot and the map agree while a handle is
        dragged. The committed change layer has a ramp of its own (`qgis_io/layers.py`).
        """
        reference = self._resampled_terrain()
        if reference is None:
            return
        for colour, above in ((QColor(*FILL, SHADE_ALPHA), True), (QColor(*CUT, SHADE_ALPHA), False)):
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

    def _draw_sides(self, painter, palette) -> None:
        """Say which side is which, and mark the centre line the two sides are measured from."""
        plot = self._plot_rect()
        centre = self._to_screen(0.0, self._z_range()[0]).x()
        painter.setPen(QPen(palette.mid().color(), 1, Qt.PenStyle.DashDotLine))
        painter.drawLine(QPointF(centre, plot.top()), QPointF(centre, plot.bottom()))
        painter.setPen(palette.windowText().color())
        label = plot.adjusted(4, 2, -4, 0)
        painter.drawText(label, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.tr("Left"))
        painter.drawText(label, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, self.tr("Right"))

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
            if self.allow_breaks and 0 < index < len(self.points) - 1 and index not in self._edges():
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
        if not 0 <= self._dragging < len(self.points):
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
        if not self.editable or not self.allow_breaks or event.button() != Qt.MouseButton.LeftButton:
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
        if not 0 <= self.selected < len(self.points) or not self.editable or event.key() not in deltas:
            event.ignore()
            return
        if self._nudge_before is None:
            self._nudge_before = list(self.points)
        dx, dz = deltas[event.key()]
        x, z = self.points[self.selected]
        self._move_handle(self.selected, (x + dx, z + dz))
        self.profileChanged.emit(tuple(self.points))
        event.accept()

    def keyReleaseEvent(self, event):  # noqa: N802 — Qt override
        """Commit a nudge when its key is let go. A held key sends a release with every auto-repeat
        too, so those are skipped: a second of holding Up is one change, not thirty."""
        if event.key() not in NUDGE_KEYS or event.isAutoRepeat():
            event.ignore()
            return
        self._commit_nudge()
        event.accept()

    def focusOutEvent(self, event):  # noqa: N802 — Qt override
        self._commit_nudge()   # the release never comes to a plot that lost focus while a key was held
        super().focusOutEvent(event)

    def _commit_nudge(self) -> None:
        before, self._nudge_before = self._nudge_before, None
        if before is not None and before != self.points:
            self.profileCommitted.emit(tuple(self.points))

    def _move_handle(self, index: int, position) -> None:
        x, z = position
        partner = self._partner(index)
        if not self._can_move_x(index):
            x = self.points[index][0]
        else:
            x = self._clamp_x(index, x)
            if partner is not None:
                x = -self._clamp_x(partner, -x)   # the mirror image must fit between its own neighbours too
            if self.mirrored:
                x = min(x, -MIN_HALF_WIDTH) if self.points[index][0] < 0.0 else max(x, MIN_HALF_WIDTH)
            elif self.kind is Kind.CROSS:
                x = max(x, 0.0)
        if index in self._edges():
            z = self.points[index][1]           # the crest stays level: its edges only move sideways
        if partner is not None:
            self.points[partner] = (-x, z)
        self.points[index] = (x, z)
        self.update()

    def _clamp_x(self, index: int, x: float) -> float:
        if index > 0:
            x = max(x, self.points[index - 1][0] + 1e-6)
        if index < len(self.points) - 1:
            x = min(x, self.points[index + 1][0] - 1e-6)
        return x

    def _edges(self) -> tuple:
        """Indexes of the two crest edges of a mirrored profile: the handles either side of the centre."""
        if not self.mirrored:
            return ()
        right = next((i for i, (x, _z) in enumerate(self.points) if x > 0.0), None)
        return (right - 1, right) if right else ()

    def _partner(self, index: int):
        """The handle that moves with `index`: the other crest edge, or — while `symmetric` — the
        mirror image of any handle that has one."""
        edges = self._edges()
        if index in edges:
            return edges[1] if index == edges[0] else edges[0]
        mirror = len(self.points) - 1 - index
        if self.symmetric and edges and mirror != index and _mirrors(self.points[index], self.points[mirror]):
            return mirror
        return None

    def _can_move_x(self, index: int) -> bool:
        """The first point is pinned (the centre of a one-sided cross profile, the start of a long
        section); in a long section the last one is too (it is the end). A mirrored profile has no
        pinned point: its outer handles are the ends of the slopes."""
        if self.mirrored:
            return True
        if index == 0:
            return False
        return not (self.kind is Kind.LONG and index == len(self.points) - 1)

    def _insertion_index(self, x: float):
        edges = self._edges()
        for index in range(1, len(self.points)):
            if self.points[index - 1][0] < x < self.points[index][0]:
                return None if edges and index == edges[1] else index   # never on the crest itself
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


def _mirrors(a, b) -> bool:
    return abs(a[0] + b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


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
