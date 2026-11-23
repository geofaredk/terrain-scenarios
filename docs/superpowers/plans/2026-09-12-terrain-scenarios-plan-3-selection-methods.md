# Terrain Scenarios — Plan 3: Selection Methods Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the user every way of marking the area of a feature that the spec promises: click, freehand, brush painting, and features from a layer already in the project — plus reshaping a drawn feature by its vertices, a Line/Area toggle, and a highlight of the selected feature on the map.

**Architecture:** The map tools grow a shared base (`SketchTool`: styled rubber bands, project snapping, cleanup) with four tools on top: `DrawTool` (click), `FreehandTool` (trace), `BrushTool` (paint, Shift erases) and `VertexEditTool` (reshape). The panel's gallery gains a Line/Area toggle and one button per selection method; the layer form turns existing features into one multi-part feature. `SketchController` gains `add_from_layer()` and `set_geometry()`; every edit still goes through the controller.

**Tech Stack:** QGIS 4.2.2 Python API (PyQt6 via `qgis.PyQt`, Qt 6.11), GDAL 3.13, numpy; pytest (dev-only) with a headless `QgsApplication`.

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-scenarios-design.md` — §6.1 (map tools: freehand, brush, from layer, vertex edit), §6.2 (geometry handling), §7.2 (gallery, "Where?" buttons, Line/Area toggle, selecting a row selects the feature), §11 milestone 3. Plans 1 and 2 are merged on `main`.

## Global Constraints

- Target QGIS 4.x (Qt6) only. Import Qt through `qgis.PyQt` and always use fully scoped Qt6 enums (`Qt.MouseButton.LeftButton`, `Qgis.GeometryType.Polygon`, …).
- Native look (spec §7.1): only standard Qt/QGIS widgets, QGIS theme icons via `QgsApplication.getThemeIcon`, no stylesheets. Drawing keeps QGIS digitizing behaviour: project snapping, digitizing colours, right-click/Enter finishes, Backspace/Delete removes the last vertex, Esc cancels.
- `terrain_scenarios/core/` and `terrain_scenarios/model/` never import `qgis` or `PyQt`. Widgets never call the engine, files or layers directly — only `SketchController`.
- Errors never take QGIS down: user problems become message-bar messages; unexpected engine errors are caught in the controller and logged.
- User-facing names, summaries and messages live in `gui/help_texts.py` or `gui/selection.py`; widget captions use `self.tr()`. English only.
- Package modules start with a one-line docstring and use `from __future__ import annotations` where they have type hints; test modules need neither. 4-space indentation.
- Tests run only through `scripts/test.sh` (headless QGIS, `QT_QPA_PLATFORM=offscreen`). Never run `scripts/dev_install.sh`.
- **`QgsRubberBand` has no `geometryType()` in QGIS 4** — a tool must remember each band's geometry type itself. An exception raised inside a Qt callback (for example `QgsMapTool.deactivate`) aborts the interpreter, so this is not a detail.
- Out of scope here (later plans): the profile dock and live preview (Plan 4); illustrations, rich help and `QgsSettings` persistence (Plan 5); scenarios, volumes, undo/redo, 3D and packaging (Plan 6).

## Decisions made while prototyping (read before implementing)

- **Freehand follows the Line/Area toggle** instead of the spec's "ending near the start closes it": the shape is already chosen in the panel, so an area trace always closes its ring.
- **Vertex editing is an explicit "Edit shape" toggle** under the feature list rather than being permanently active while a feature is selected; otherwise panning and drawing would fight the editor. It switches off when the selection changes, the session ends or another map tool is chosen.
- **Brush is offered for areas only** (it paints polygons) and, when the selected feature uses the same tool and Area shape, it *extends that feature* instead of creating a new one — that is the spec's "with a brush feature selected, the brush adds to or erases from that feature".
- **From layer** creates one multi-part feature named after the layer (`_unique()` makes the name unique), so all parts share one set of values, as §4.1 requires.
- **The selected feature is outlined on the map** with a rubber band that follows edits and clears on deselect.

## File Structure

| File | Responsibility |
|---|---|
| `terrain_scenarios/gui/selection.py` | `Method` enum plus its labels, icons, tooltips and status hints |
| `terrain_scenarios/gui/map_tools/base.py` | `SketchTool` (bands, snapping, cleanup) and `DrawTool` (click drawing) |
| `terrain_scenarios/gui/map_tools/freehand.py` | `FreehandTool`: press, trace, release |
| `terrain_scenarios/gui/map_tools/brush.py` | `BrushTool`: paint and erase an area, radius control |
| `terrain_scenarios/gui/map_tools/vertex_edit.py` | `VertexEditTool`: move, add and remove vertices |
| `terrain_scenarios/gui/layer_source.py` | `LayerSource`: layer picker, "selected features only", "Use these features" |
| `terrain_scenarios/gui/tool_gallery.py` | Tool list, Line/Area toggle, method buttons, brush radius, layer form |
| `terrain_scenarios/gui/controller.py` | `add_from_layer()`, `set_geometry()`, feature names from a layer |
| `terrain_scenarios/gui/main_dock.py` | Routing per method, brush extension, Edit shape toggle, map highlight |
| `terrain_scenarios/plugin.py` | Stops drawing *and* editing when the panel is hidden or unloaded |

---

### Task 1: Freehand tracing (and the shared tool base)

**Files:**
- Create: `terrain_scenarios/gui/selection.py`, `terrain_scenarios/gui/map_tools/freehand.py`
- Modify: `terrain_scenarios/gui/map_tools/base.py` (extract `SketchTool` from `DrawTool`)
- Test: `tests/qgis/test_map_tools.py`

**Interfaces:**
- Consumes: the Plan 2 map tools and `fake_iface()` / `world()` from `tests/qgis/qgis_helpers.py`.
- Produces: `Method` (CLICK, FREEHAND, BRUSH, LAYER) with `METHOD_LABELS`, `METHOD_ICONS`, `METHOD_TIPS`, `METHOD_HINTS` and `EDIT_HINT`; `SketchTool(canvas)` with `finished(QgsGeometry)`, `cancelled()`, `geometry_type`, `add_band(geometry_type, stroke_only=False)`, `reset()`, `dispose()`, `snap(event)`, `tolerance(pixels=10.0)`; `DrawTool(SketchTool)` unchanged in behaviour; `FreehandTool(canvas, geometry_type=Qgis.GeometryType.Line)`.

- [ ] **Step 1: Replace the map-tool tests with the freehand ones added**

**File:** `tests/qgis/test_map_tools.py`
```python
from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QKeyEvent

import pytest
from qgis.core import Qgis, QgsGeometry, QgsPointXY

from qgis_helpers import fake_iface, world
from terrain_scenarios.gui.map_tools.draw_line import DrawLineTool
from terrain_scenarios.gui.map_tools.draw_polygon import DrawPolygonTool
from terrain_scenarios.gui.map_tools.freehand import FreehandTool


def click(tool, canvas, x, y, button=Qt.MouseButton.LeftButton):
    tool.canvasReleaseEvent(QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease, QPoint(x, y), button, button,
                                             Qt.KeyboardModifier.NoModifier))


def press(tool, key):
    tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_line_tool_emits_the_clicked_line_on_right_click():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 200, 10)
    click(tool, canvas, 0, 0, Qt.MouseButton.RightButton)
    assert len(drawn) == 1 and len(drawn[0].asPolyline()) == 2 and tool.points == []


def test_backspace_removes_the_last_point_and_escape_cancels():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    cancelled = []
    tool.cancelled.connect(lambda: cancelled.append(True))
    for x in (10, 50, 90):
        click(tool, canvas, x, 10)
    press(tool, Qt.Key.Key_Backspace)
    assert len(tool.points) == 2
    press(tool, Qt.Key.Key_Escape)
    assert tool.points == [] and cancelled == [True]


def test_a_polygon_needs_three_corners_and_enter_finishes_it():
    canvas = fake_iface().mapCanvas()
    tool = DrawPolygonTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 100, 10)
    press(tool, Qt.Key.Key_Return)
    assert drawn == []
    click(tool, canvas, 100, 100)
    press(tool, Qt.Key.Key_Return)
    assert len(drawn) == 1 and drawn[0].area() > 0


def event(canvas, x, y, kind, button=Qt.MouseButton.LeftButton, modifiers=Qt.KeyboardModifier.NoModifier):
    return QgsMapMouseEvent(canvas, kind, QPoint(x, y), button, button, modifiers)


def drag(tool, canvas, points, modifiers=Qt.KeyboardModifier.NoModifier):
    """Press, move along `points` and release, like a real mouse drag."""
    tool.canvasPressEvent(event(canvas, points[0][0], points[0][1], QEvent.Type.MouseButtonPress, modifiers=modifiers))
    for x, y in points[1:-1]:
        tool.canvasMoveEvent(event(canvas, x, y, QEvent.Type.MouseMove, modifiers=modifiers))
    last = points[-1]
    tool.canvasReleaseEvent(event(canvas, last[0], last[1], QEvent.Type.MouseButtonRelease, modifiers=modifiers))


def pixel(canvas, point):
    device = canvas.getCoordinateTransform().transform(point)
    return int(round(device.x())), int(round(device.y()))


def test_freehand_traces_a_line_while_the_button_is_held():
    canvas = fake_iface().mapCanvas()
    tool = FreehandTool(canvas, Qgis.GeometryType.Line)
    drawn = []
    tool.finished.connect(drawn.append)
    drag(tool, canvas, [(10, 10), (60, 30), (120, 60), (200, 90)])
    assert len(drawn) == 1 and len(drawn[0].asPolyline()) >= 3 and tool.points == []


def test_freehand_closes_the_ring_in_area_mode():
    canvas = fake_iface().mapCanvas()
    tool = FreehandTool(canvas, Qgis.GeometryType.Polygon)
    drawn = []
    tool.finished.connect(drawn.append)
    drag(tool, canvas, [(50, 50), (150, 50), (150, 150), (50, 150)])
    assert len(drawn) == 1 and drawn[0].area() > 0
```
- [ ] **Step 2: Run them to verify the new tests fail**

Run: `scripts/test.sh tests/qgis/test_map_tools.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_scenarios.gui.map_tools.freehand'`

- [ ] **Step 3: Add the selection methods and the shared tool base**

**File:** `terrain_scenarios/gui/selection.py`
```python
"""How the user marks the area of a feature: click, freehand, brush or an existing layer."""
from __future__ import annotations

from enum import Enum


class Method(str, Enum):
    CLICK = "click"
    FREEHAND = "freehand"
    BRUSH = "brush"
    LAYER = "layer"


METHOD_LABELS = {
    Method.CLICK: "Draw",
    Method.FREEHAND: "Freehand",
    Method.BRUSH: "Brush",
    Method.LAYER: "From layer",
}

METHOD_ICONS = {
    Method.CLICK: "/mActionCaptureLine.svg",
    Method.FREEHAND: "/mActionCaptureCurve.svg",
    Method.BRUSH: "/mActionCircle.svg",
    Method.LAYER: "/mActionAddOgrLayer.svg",
}

METHOD_TIPS = {
    Method.CLICK: "Click point by point; right-click or Enter finishes.",
    Method.FREEHAND: "Hold the mouse and trace the shape; release to finish.",
    Method.BRUSH: "Paint over the cells with a round brush; hold Shift to erase, [ and ] change the radius.",
    Method.LAYER: "Use lines or areas from a layer that is already in your project.",
}

METHOD_HINTS = {
    Method.CLICK: "Click to add points. Right-click or press Enter to finish, Backspace removes the last "
                  "point, Esc cancels.",
    Method.FREEHAND: "Hold the left mouse button and trace the shape. Release to finish, Esc cancels.",
    Method.BRUSH: "Paint with the left mouse button, hold Shift to erase. [ and ] or Ctrl+wheel change the "
                  "radius. Right-click or Enter finishes, Esc cancels.",
    Method.LAYER: "Pick a layer below and press 'Use these features'.",
}

EDIT_HINT = ("Drag a vertex to move it, double-click a segment to add one, press Delete to remove the vertex "
             "under the cursor. Esc stops editing.")
```
**File:** `terrain_scenarios/gui/map_tools/base.py`
```python
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
```
**File:** `terrain_scenarios/gui/map_tools/freehand.py`
```python
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
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_map_tools.py` → Expected: `5 passed`
Run: `scripts/test.sh` → Expected: `122 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/gui/selection.py terrain_scenarios/gui/map_tools tests/qgis/test_map_tools.py
git commit -m "feat(gui): freehand tracing and a shared map-tool base"
```

---

### Task 2: Brush painting

**Files:**
- Create: `terrain_scenarios/gui/map_tools/brush.py`
- Test: `tests/qgis/test_map_tools.py`

**Interfaces:**
- Consumes: `SketchTool` (Task 1).
- Produces: `BrushTool(canvas, radius, initial=None)` — signals `finished`, `cancelled`, `radiusChanged(float)`; attributes `radius`, `geometry` (the painted area), `cursor_band`; methods `set_radius(radius)`, `apply_stroke(points, erase=False)`, `finish()`, `reset()`. Shift while painting erases, `[` / `]` and Ctrl+wheel change the radius, right-click or Enter finishes.

- [ ] **Step 1: Replace the map-tool tests with the brush ones added**

**File:** `tests/qgis/test_map_tools.py`
```python
from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QKeyEvent

import pytest
from qgis.core import Qgis, QgsGeometry, QgsPointXY

from qgis_helpers import fake_iface, world
from terrain_scenarios.gui.map_tools.draw_line import DrawLineTool
from terrain_scenarios.gui.map_tools.draw_polygon import DrawPolygonTool
from terrain_scenarios.gui.map_tools.brush import BrushTool
from terrain_scenarios.gui.map_tools.freehand import FreehandTool


def click(tool, canvas, x, y, button=Qt.MouseButton.LeftButton):
    tool.canvasReleaseEvent(QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease, QPoint(x, y), button, button,
                                             Qt.KeyboardModifier.NoModifier))


def press(tool, key):
    tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_line_tool_emits_the_clicked_line_on_right_click():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 200, 10)
    click(tool, canvas, 0, 0, Qt.MouseButton.RightButton)
    assert len(drawn) == 1 and len(drawn[0].asPolyline()) == 2 and tool.points == []


def test_backspace_removes_the_last_point_and_escape_cancels():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    cancelled = []
    tool.cancelled.connect(lambda: cancelled.append(True))
    for x in (10, 50, 90):
        click(tool, canvas, x, 10)
    press(tool, Qt.Key.Key_Backspace)
    assert len(tool.points) == 2
    press(tool, Qt.Key.Key_Escape)
    assert tool.points == [] and cancelled == [True]


def test_a_polygon_needs_three_corners_and_enter_finishes_it():
    canvas = fake_iface().mapCanvas()
    tool = DrawPolygonTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 100, 10)
    press(tool, Qt.Key.Key_Return)
    assert drawn == []
    click(tool, canvas, 100, 100)
    press(tool, Qt.Key.Key_Return)
    assert len(drawn) == 1 and drawn[0].area() > 0


def event(canvas, x, y, kind, button=Qt.MouseButton.LeftButton, modifiers=Qt.KeyboardModifier.NoModifier):
    return QgsMapMouseEvent(canvas, kind, QPoint(x, y), button, button, modifiers)


def drag(tool, canvas, points, modifiers=Qt.KeyboardModifier.NoModifier):
    """Press, move along `points` and release, like a real mouse drag."""
    tool.canvasPressEvent(event(canvas, points[0][0], points[0][1], QEvent.Type.MouseButtonPress, modifiers=modifiers))
    for x, y in points[1:-1]:
        tool.canvasMoveEvent(event(canvas, x, y, QEvent.Type.MouseMove, modifiers=modifiers))
    last = points[-1]
    tool.canvasReleaseEvent(event(canvas, last[0], last[1], QEvent.Type.MouseButtonRelease, modifiers=modifiers))


def pixel(canvas, point):
    device = canvas.getCoordinateTransform().transform(point)
    return int(round(device.x())), int(round(device.y()))


def test_freehand_traces_a_line_while_the_button_is_held():
    canvas = fake_iface().mapCanvas()
    tool = FreehandTool(canvas, Qgis.GeometryType.Line)
    drawn = []
    tool.finished.connect(drawn.append)
    drag(tool, canvas, [(10, 10), (60, 30), (120, 60), (200, 90)])
    assert len(drawn) == 1 and len(drawn[0].asPolyline()) >= 3 and tool.points == []


def test_freehand_closes_the_ring_in_area_mode():
    canvas = fake_iface().mapCanvas()
    tool = FreehandTool(canvas, Qgis.GeometryType.Polygon)
    drawn = []
    tool.finished.connect(drawn.append)
    drag(tool, canvas, [(50, 50), (150, 50), (150, 150), (50, 150)])
    assert len(drawn) == 1 and drawn[0].area() > 0


def test_brush_paints_erases_and_changes_its_radius():
    canvas = fake_iface().mapCanvas()
    tool = BrushTool(canvas, radius=2.0)
    painted = []
    tool.finished.connect(painted.append)
    drag(tool, canvas, [(100, 100), (150, 100), (200, 100)])
    assert not tool.geometry.isEmpty()
    area = tool.geometry.area()
    drag(tool, canvas, [(190, 100), (210, 100)], modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert tool.geometry.area() < area  # Shift cut a bite out of the painted area
    press(tool, Qt.Key.Key_BracketRight)
    assert tool.radius == pytest.approx(2.5)
    press(tool, Qt.Key.Key_Return)
    assert len(painted) == 1 and painted[0].area() > 0 and tool.geometry.isEmpty()


def test_brush_starts_from_an_existing_area_when_extending():
    canvas = fake_iface().mapCanvas()
    start = QgsGeometry.fromPolygonXY([[QgsPointXY(*world(c, r)) for c, r in
                                        ((5, 5), (10, 5), (10, 10), (5, 10), (5, 5))]])
    tool = BrushTool(canvas, radius=2.0, initial=start)
    assert tool.geometry.area() == pytest.approx(start.area())
    tool.apply_stroke([QgsPointXY(*world(12, 7))])
    assert tool.geometry.area() > start.area()
```
- [ ] **Step 2: Run them to verify the new tests fail**

Run: `scripts/test.sh tests/qgis/test_map_tools.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_scenarios.gui.map_tools.brush'`

- [ ] **Step 3: Implement the brush**

**File:** `terrain_scenarios/gui/map_tools/brush.py`
```python
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
        self.radius = float(radius)
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
        """Emit the painted area; an empty area is dropped."""
        geometry = QgsGeometry(self.geometry)
        self.reset()
        if not geometry.isEmpty():
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
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_map_tools.py` → Expected: `7 passed`
Run: `scripts/test.sh` → Expected: `124 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/gui/map_tools/brush.py tests/qgis/test_map_tools.py
git commit -m "feat(gui): brush painting with erase and radius control"
```

---

### Task 3: Vertex editing

**Files:**
- Create: `terrain_scenarios/gui/map_tools/vertex_edit.py`
- Test: `tests/qgis/test_map_tools.py`

**Interfaces:**
- Consumes: `SketchTool` (Task 1).
- Produces: `VertexEditTool(canvas, geometry)` — signal `geometryChanged(QgsGeometry)` (canvas CRS) plus `cancelled`; attributes `geometry`, `vertex_band`; methods `vertex_near(point)`, `delete_vertex_near(point)`, `vertex_count()`. Dragging moves a vertex, double-clicking a segment inserts one, Delete removes the vertex under the cursor (never below 2 vertices for a line or 4 for a closed ring), Esc stops editing.

- [ ] **Step 1: Replace the map-tool tests with the vertex-editing one added**

**File:** `tests/qgis/test_map_tools.py`
```python
from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QKeyEvent

import pytest
from qgis.core import Qgis, QgsGeometry, QgsPointXY

from qgis_helpers import fake_iface, world
from terrain_scenarios.gui.map_tools.draw_line import DrawLineTool
from terrain_scenarios.gui.map_tools.draw_polygon import DrawPolygonTool
from terrain_scenarios.gui.map_tools.brush import BrushTool
from terrain_scenarios.gui.map_tools.freehand import FreehandTool
from terrain_scenarios.gui.map_tools.vertex_edit import VertexEditTool


def click(tool, canvas, x, y, button=Qt.MouseButton.LeftButton):
    tool.canvasReleaseEvent(QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease, QPoint(x, y), button, button,
                                             Qt.KeyboardModifier.NoModifier))


def press(tool, key):
    tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_line_tool_emits_the_clicked_line_on_right_click():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 200, 10)
    click(tool, canvas, 0, 0, Qt.MouseButton.RightButton)
    assert len(drawn) == 1 and len(drawn[0].asPolyline()) == 2 and tool.points == []


def test_backspace_removes_the_last_point_and_escape_cancels():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    cancelled = []
    tool.cancelled.connect(lambda: cancelled.append(True))
    for x in (10, 50, 90):
        click(tool, canvas, x, 10)
    press(tool, Qt.Key.Key_Backspace)
    assert len(tool.points) == 2
    press(tool, Qt.Key.Key_Escape)
    assert tool.points == [] and cancelled == [True]


def test_a_polygon_needs_three_corners_and_enter_finishes_it():
    canvas = fake_iface().mapCanvas()
    tool = DrawPolygonTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 100, 10)
    press(tool, Qt.Key.Key_Return)
    assert drawn == []
    click(tool, canvas, 100, 100)
    press(tool, Qt.Key.Key_Return)
    assert len(drawn) == 1 and drawn[0].area() > 0


def event(canvas, x, y, kind, button=Qt.MouseButton.LeftButton, modifiers=Qt.KeyboardModifier.NoModifier):
    return QgsMapMouseEvent(canvas, kind, QPoint(x, y), button, button, modifiers)


def drag(tool, canvas, points, modifiers=Qt.KeyboardModifier.NoModifier):
    """Press, move along `points` and release, like a real mouse drag."""
    tool.canvasPressEvent(event(canvas, points[0][0], points[0][1], QEvent.Type.MouseButtonPress, modifiers=modifiers))
    for x, y in points[1:-1]:
        tool.canvasMoveEvent(event(canvas, x, y, QEvent.Type.MouseMove, modifiers=modifiers))
    last = points[-1]
    tool.canvasReleaseEvent(event(canvas, last[0], last[1], QEvent.Type.MouseButtonRelease, modifiers=modifiers))


def pixel(canvas, point):
    device = canvas.getCoordinateTransform().transform(point)
    return int(round(device.x())), int(round(device.y()))


def test_freehand_traces_a_line_while_the_button_is_held():
    canvas = fake_iface().mapCanvas()
    tool = FreehandTool(canvas, Qgis.GeometryType.Line)
    drawn = []
    tool.finished.connect(drawn.append)
    drag(tool, canvas, [(10, 10), (60, 30), (120, 60), (200, 90)])
    assert len(drawn) == 1 and len(drawn[0].asPolyline()) >= 3 and tool.points == []


def test_freehand_closes_the_ring_in_area_mode():
    canvas = fake_iface().mapCanvas()
    tool = FreehandTool(canvas, Qgis.GeometryType.Polygon)
    drawn = []
    tool.finished.connect(drawn.append)
    drag(tool, canvas, [(50, 50), (150, 50), (150, 150), (50, 150)])
    assert len(drawn) == 1 and drawn[0].area() > 0


def test_brush_paints_erases_and_changes_its_radius():
    canvas = fake_iface().mapCanvas()
    tool = BrushTool(canvas, radius=2.0)
    painted = []
    tool.finished.connect(painted.append)
    drag(tool, canvas, [(100, 100), (150, 100), (200, 100)])
    assert not tool.geometry.isEmpty()
    area = tool.geometry.area()
    drag(tool, canvas, [(190, 100), (210, 100)], modifiers=Qt.KeyboardModifier.ShiftModifier)
    assert tool.geometry.area() < area  # Shift cut a bite out of the painted area
    press(tool, Qt.Key.Key_BracketRight)
    assert tool.radius == pytest.approx(2.5)
    press(tool, Qt.Key.Key_Return)
    assert len(painted) == 1 and painted[0].area() > 0 and tool.geometry.isEmpty()


def test_brush_starts_from_an_existing_area_when_extending():
    canvas = fake_iface().mapCanvas()
    start = QgsGeometry.fromPolygonXY([[QgsPointXY(*world(c, r)) for c, r in
                                        ((5, 5), (10, 5), (10, 10), (5, 10), (5, 5))]])
    tool = BrushTool(canvas, radius=2.0, initial=start)
    assert tool.geometry.area() == pytest.approx(start.area())
    tool.apply_stroke([QgsPointXY(*world(12, 7))])
    assert tool.geometry.area() > start.area()


def test_vertex_editing_moves_adds_and_removes_points():
    canvas = fake_iface().mapCanvas()
    a, b, c = QgsPointXY(*world(5, 20)), QgsPointXY(*world(20, 20)), QgsPointXY(*world(30, 20))
    tool = VertexEditTool(canvas, QgsGeometry.fromPolylineXY([a, b, c]))
    changes = []
    tool.geometryChanged.connect(changes.append)
    x, y = pixel(canvas, a)
    drag(tool, canvas, [(x, y), (x, y - 20), (x, y - 20)])
    assert changes and changes[-1].vertexAt(0).y() > a.y()  # the first vertex moved north
    mid_x, mid_y = pixel(canvas, QgsPointXY((b.x() + c.x()) / 2, b.y()))
    tool.canvasDoubleClickEvent(event(canvas, mid_x, mid_y, QEvent.Type.MouseButtonDblClick))
    assert tool.vertex_count() == 4 and len(changes) == 2
    tool.canvasMoveEvent(event(canvas, mid_x, mid_y, QEvent.Type.MouseMove))
    press(tool, Qt.Key.Key_Delete)
    assert tool.vertex_count() == 3 and len(changes) == 3
```
- [ ] **Step 2: Run them to verify the new test fails**

Run: `scripts/test.sh tests/qgis/test_map_tools.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_scenarios.gui.map_tools.vertex_edit'`

- [ ] **Step 3: Implement vertex editing**

**File:** `terrain_scenarios/gui/map_tools/vertex_edit.py`
```python
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
        _distance, _closest, after, _left = self.geometry.closestSegmentWithContext(point)
        if after < 0:
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
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_map_tools.py` → Expected: `8 passed`
Run: `scripts/test.sh` → Expected: `125 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/gui/map_tools/vertex_edit.py tests/qgis/test_map_tools.py
git commit -m "feat(gui): reshape a feature by moving, adding and removing vertices"
```

---

### Task 4: Features from a layer, and replacing a shape

**Files:**
- Modify: `terrain_scenarios/gui/controller.py`, `terrain_scenarios/gui/help_texts.py`, `tests/qgis/qgis_helpers.py`
- Test: `tests/qgis/test_controller.py`

**Interfaces:**
- Consumes: `to_dem_wkb`, `new_feature`, the existing controller.
- Produces: `SketchController.add_drawn(tool, mode, geometry, crs, name=None)`; `add_from_layer(tool, mode, layer, selected_only=False) -> TerrainFeature | None` (one multi-part feature named after the layer; a message and None when nothing usable); `set_geometry(fid, geometry, crs) -> bool` (replaces a feature's shape; False with a message when the shape does not fit the feature's mode or cannot be transformed); `_unique(name)`; `help_texts.NO_FEATURES_IN_LAYER`. Test helper `line_layer(name, geometries, add_to_project=True)`.

- [ ] **Step 1: Extend the test helpers and write the failing tests**

**File:** `tests/qgis/qgis_helpers.py`
```python
"""Helpers for the QGIS integration tests: small GeoTIFF DEMs on a UTM grid (EPSG:25832)."""
from unittest import mock

import numpy as np
from osgeo import gdal
from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsRectangle, QgsVectorLayer)
from qgis.gui import QgisInterface, QgsMapCanvas
from qgis.PyQt.QtWidgets import QMainWindow

gdal.UseExceptions()

X0, Y0, CELL = 612000.0, 6178040.0, 1.0  # top-left corner of the test DEMs
UTM = QgsCoordinateReferenceSystem("EPSG:25832")


def write_dem(path, array, crs="EPSG:25832", nodata=-9999.0, gt=None, bands=1) -> str:
    array = np.asarray(array, dtype=np.float32)
    rows, cols = array.shape
    ds = gdal.GetDriverByName("GTiff").Create(str(path), cols, rows, bands, gdal.GDT_Float32)
    ds.SetGeoTransform(gt or (X0, CELL, 0.0, Y0, 0.0, -CELL))
    ds.SetProjection(crs)
    for b in range(1, bands + 1):
        band = ds.GetRasterBand(b)
        band.WriteArray(array)
        if nodata is not None:
            band.SetNoDataValue(nodata)
    ds.FlushCache()
    ds = None
    return str(path)


def dem_layer(tmp_path, array=None, name="dem", **kw) -> QgsRasterLayer:
    """A 40 x 40 flat 10 m DEM (or `array`) added to the project."""
    if array is None:
        array = np.full((40, 40), 10.0, np.float32)
    layer = QgsRasterLayer(write_dem(tmp_path / f"{name}.tif", array, **kw), name)
    assert layer.isValid()
    QgsProject.instance().addMapLayer(layer)
    return layer


def world(col: float, row: float) -> tuple[float, float]:
    """Map coordinates of a cell centre on the test grid."""
    return X0 + (col + 0.5) * CELL, Y0 - (row + 0.5) * CELL


def line_through(c0, r0, c1, r1) -> QgsGeometry:
    return QgsGeometry.fromPolylineXY([QgsPointXY(*world(c0, r0)), QgsPointXY(*world(c1, r1))])


def square(c0, r0, c1, r1) -> QgsGeometry:
    corners = [world(c0, r0), world(c1, r0), world(c1, r1), world(c0, r1), world(c0, r0)]
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in corners]])


def sample(layer, col, row) -> float:
    return layer.dataProvider().sample(QgsPointXY(*world(col, row)), 1)[0]


def read_tif(path):
    ds = gdal.Open(str(path))
    band = ds.GetRasterBand(1)
    return band.ReadAsArray(), band.GetNoDataValue()


def fake_iface():
    """A QgisInterface mock with a real main window and a UTM map canvas over the test grid.

    The canvas has no parent so it lives as long as a test holds it, even after the mock is gone."""
    iface = mock.Mock(spec=QgisInterface)
    iface.mainWindow.return_value = QMainWindow()
    canvas = QgsMapCanvas()
    canvas.resize(400, 400)
    canvas.setDestinationCrs(UTM)
    canvas.setExtent(QgsRectangle(X0, Y0 - 40, X0 + 40, Y0))
    iface.mapCanvas.return_value = canvas
    return iface


def start_session(tmp_path, array=None):
    """A SketchController with a session on a fresh test DEM."""
    from terrain_scenarios.gui.controller import SketchController  # imported late: the GUI package comes in a later task

    controller = SketchController(QgsProject.instance())
    controller.set_dem(dem_layer(tmp_path, array))
    return controller


def line_layer(name, geometries, add_to_project=True) -> QgsVectorLayer:
    """A memory line layer in the test CRS holding `geometries`."""
    layer = QgsVectorLayer("LineString?crs=EPSG:25832", name, "memory")
    features = []
    for geometry in geometries:
        feature = QgsFeature()
        feature.setGeometry(geometry)
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    if add_to_project:
        QgsProject.instance().addMapLayer(layer)
    return layer
```
**File:** `tests/qgis/test_controller.py`
```python
import pytest
from qgis.core import Qgis, QgsProject

import terrain_scenarios.gui.controller as controller_module
from qgis_helpers import UTM, dem_layer, line_layer, line_through, read_tif, sample, square, start_session
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.qgis_io.layers import GROUP_NAME
from terrain_scenarios.qgis_io.raster_io import DemError


def test_drawing_a_dike_updates_the_modified_dem(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dike.name == "Raise path 1" and c.features == (dike,)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)  # 1 m above the flat 10 m ground
    assert sample(c.layers.change, 20, 20) == pytest.approx(1.0)
    assert c.stats(dike.id).fill > 0 and c.layers.outlines.featureCount() == 1


def test_editing_toggling_and_deleting_recompute(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=2.5)
    assert sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    c.set_enabled(dike.id, False)
    assert sample(c.layers.working, 20, 20) == pytest.approx(10.0)
    assert c.layers.outlines.featureCount() == 0
    c.delete_feature(dike.id)
    assert c.features == ()


def test_names_are_unique_and_reorder_changes_the_order(tmp_path):
    c = start_session(tmp_path)
    a = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 10, 30, 10), UTM)
    b = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 30, 30, 30), UTM)
    assert (a.name, b.name) == ("Add to terrain 1", "Add to terrain 2")
    c.reorder([b.id, a.id])
    assert [f.id for f in c.features] == [b.id, a.id]
    with pytest.raises(ValueError):
        c.reorder([a.id])


def test_an_unusable_drawing_is_reported_and_not_added(tmp_path):
    c = start_session(tmp_path)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_drawn(Tool.RAISE_FLAT, Mode.AREA, line_through(5, 5, 10, 10), UTM) is None
    assert c.features == () and messages


def test_export_writes_the_modified_dem(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.export_dem(str(tmp_path / "out.tif"))
    exported, _ = read_tif(tmp_path / "out.tif")
    assert exported[20, 20] == pytest.approx(11.0) and exported[0, 0] == pytest.approx(10.0)


def test_removing_the_dem_layer_ends_the_session(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    QgsProject.instance().removeMapLayer(c.dem_layer_id)
    assert not c.has_dem and c.features == () and messages
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None


def test_export_refuses_to_overwrite_the_source_dem(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    with pytest.raises(RuntimeError):
        c.export_dem(c.info.path)
    with pytest.raises(RuntimeError):
        c.export_dem(c.files.working_path)
    source, _ = read_tif(c.info.path)
    assert source[20, 20] == pytest.approx(10.0)


def test_failing_working_files_keep_the_previous_session(tmp_path, monkeypatch):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(controller_module, "WorkingFiles", boom)
    with pytest.raises(DemError):
        c.set_dem(dem_layer(tmp_path, name="other"))
    assert c.has_dem
    assert c.features == (dike,)
    assert c.files is not None and c.layers is not None


def test_removing_a_result_layer_keeps_the_session(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    messages = []
    c.message.connect(lambda level, text: messages.append((level, text)))
    QgsProject.instance().removeMapLayer(c.layers.hillshade_id)
    assert c.has_dem and c.features == (dike,)
    assert messages and messages[-1][0] == Qgis.MessageLevel.Info
    c.update_feature(dike.id, amount=2.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(12.0)


def test_a_new_project_drops_the_session_without_a_message(tmp_path):
    c = start_session(tmp_path)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    QgsProject.instance().clear()
    assert not c.has_dem and not messages


def test_an_engine_error_keeps_the_previous_feature_list(tmp_path, monkeypatch):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dike.amount == pytest.approx(1.0)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(c.stack, "update", boom)
    c.update_feature(dike.id, amount=5.0)
    assert messages
    assert c.feature(dike.id).amount == pytest.approx(1.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)


def test_a_geographic_dem_is_refused_without_side_effects(tmp_path):
    c = SketchController(QgsProject.instance())
    with pytest.raises(DemError):
        c.set_dem(dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001)))
    assert not c.has_dem
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None


def test_drawing_or_exporting_without_a_session_is_reported_not_raised(tmp_path):
    c = start_session(tmp_path)
    c.close()  # e.g. the DEM layer was removed while the user was still drawing
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM) is None
    assert messages and not c.dem_crs.isValid()
    with pytest.raises(RuntimeError, match="Start"):
        c.export_dem(str(tmp_path / "out.tif"))


def test_features_from_a_layer_become_one_multi_part_feature(tmp_path):
    c = start_session(tmp_path)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    feature = c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)
    assert feature.name == "Planned dikes" and len(c.features) == 1
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)
    assert sample(c.layers.working, 20, 30) == pytest.approx(11.0)


def test_only_the_selected_features_are_used(tmp_path):
    c = start_session(tmp_path)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    layer.selectByIds([next(layer.getFeatures()).id()])
    c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer, selected_only=True)
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)
    assert sample(c.layers.working, 20, 30) == pytest.approx(10.0)


def test_an_empty_layer_selection_is_reported(tmp_path):
    c = start_session(tmp_path)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer, selected_only=True) is None
    assert c.features == () and messages


def test_set_geometry_replaces_the_shape(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.set_geometry(dike.id, line_through(5, 30, 34, 30), UTM)
    assert sample(c.layers.working, 20, 20) == pytest.approx(10.0)
    assert sample(c.layers.working, 20, 30) == pytest.approx(11.0)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.set_geometry(dike.id, square(10, 10, 20, 20), UTM) is False  # an area cannot replace a path
    assert messages
```
- [ ] **Step 2: Run them to verify the new tests fail**

Run: `scripts/test.sh tests/qgis/test_controller.py`
Expected: `4 failed, 13 passed` — `AttributeError: 'SketchController' object has no attribute 'add_from_layer'` (three times) and `… no attribute 'set_geometry'`

- [ ] **Step 3: Implement the controller additions**

**File:** `terrain_scenarios/gui/help_texts.py`
```python
"""User-facing names, descriptions and messages in one place (extended in Plan 5)."""
from __future__ import annotations

from ..core.operations import FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS, FLAG_NODATA_REFERENCE, FLAG_OUTSIDE
from ..core.tools import PixelMode, Tool

TOOL_LABELS = {
    Tool.INTERPOLATE: "Interpolate",
    Tool.RAISE_PATH: "Raise path",
    Tool.LOWER_PATH: "Lower path",
    Tool.RAISE_FLAT: "Raise flat",
    Tool.LOWER_FLAT: "Lower flat",
    Tool.ADD: "Add to terrain",
    Tool.SUBTRACT: "Subtract from terrain",
}

TOOL_SUMMARIES = {
    Tool.INTERPOLATE: "A straight grade between the terrain at the start and end of the path, or a smooth "
                      "surface between the corners of an area. Example: cut through an embankment that "
                      "blocks a flow path, or fill an old ditch.",
    Tool.RAISE_PATH: "Adds material along the path, following the terrain uphill or downhill; it never "
                     "removes material. Example: a wall or emergency dike along a river bank.",
    Tool.LOWER_PATH: "Removes material along the path, following the terrain; it never adds material. "
                     "Example: a ditch or swale that drains a road towards a pond.",
    Tool.RAISE_FLAT: "A level top at the highest point of the path or outline plus the height. "
                     "Example: a flat dam, or building footprints.",
    Tool.LOWER_FLAT: "A level bottom at the lowest point of the path or outline minus the depth. "
                     "Example: a flat culvert, or a retention basin.",
    Tool.ADD: "Raises every selected cell by the height, keeping the relief. "
              "Example: an inflatable flood barrier on a street.",
    Tool.SUBTRACT: "Lowers every selected cell by the depth, keeping the slope changes. "
                   "Example: a pipe trench in a road, or deepening a canal to its bed.",
}

PIXEL_MODE_LABELS = {
    PixelMode.ALL_TOUCHED: "All touched",
    PixelMode.CENTRE: "Centre inside",
    PixelMode.FULLY_INSIDE: "Fully inside",
}

PIXEL_MODE_TIPS = {
    PixelMode.ALL_TOUCHED: "Every pixel the shape touches (generous).",
    PixelMode.CENTRE: "Pixels whose centre lies inside the shape (closest to the true area).",
    PixelMode.FULLY_INSIDE: "Only pixels completely inside the shape (strict).",
}

FLAG_TEXTS = {
    FLAG_OUTSIDE: "This feature lies outside the DEM.",
    FLAG_NO_PIXELS: "No pixels are selected — try 'All touched' or a larger width.",
    FLAG_NODATA_REFERENCE: "The start, end or edge of this feature lies outside the DEM or on nodata.",
    FLAG_BAD_GEOMETRY: "The shape of this feature cannot be used.",
}

DRAW_HINT = ("Click to add points. Right-click or press Enter to finish, Backspace removes the last "
             "point, Esc cancels.")

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Scenarios never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Scenarios session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Scenarios layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."

NO_FEATURES_IN_LAYER = "That layer has no features of the right kind to use here."


def amount_label(tool: Tool) -> str | None:
    """Label of the amount field, or None when the tool has no amount."""
    if tool is Tool.INTERPOLATE:
        return None
    if tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT):
        return "Depth"
    return "Height"
```
**File:** `terrain_scenarios/gui/controller.py`
```python
"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import os
import tempfile
import traceback
from dataclasses import replace

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core.engine import FeatureStack
from ..core.operations import FeatureStats
from ..core.tools import Mode, Tool
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from .help_texts import (DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, NO_FEATURES_IN_LAYER, NO_SESSION,
                         RESULT_LAYER_REMOVED, SESSION_ENDED_DEM_REMOVED, TOOL_LABELS)

LOG_TAG = "Terrain Scenarios"


class SketchController(QObject):
    """Owns the session: the DEM, the ordered feature list, the engine, the files and the layers."""

    featuresChanged = pyqtSignal()
    sessionChanged = pyqtSignal()
    message = pyqtSignal(object, str)  # (Qgis.MessageLevel, text for the message bar)

    def __init__(self, project: QgsProject, parent=None):
        super().__init__(parent)
        self.project = project
        self.stack = None
        self.info = None
        self.files = None
        self.layers = None
        self.dem_layer_id = None
        self.dem_crs = QgsCoordinateReferenceSystem()
        self._features: list[TerrainFeature] = []
        self._closing = False
        project.layersRemoved.connect(self._on_layers_removed)
        project.cleared.connect(self._drop_session)
        project.aboutToBeCleared.connect(self._drop_session)

    @property
    def has_dem(self) -> bool:
        return self.stack is not None

    @property
    def features(self) -> tuple:
        return tuple(self._features)

    def feature(self, fid: str) -> TerrainFeature:
        return next(f for f in self._features if f.id == fid)

    def stats(self, fid: str) -> FeatureStats:
        return self.stack.stats.get(fid, FeatureStats()) if self.stack else FeatureStats()

    def feature_geometry(self, fid: str) -> QgsGeometry:
        """The feature's drawn geometry in the DEM CRS."""
        return from_wkb(self.feature(fid).geometry_wkb)

    def set_dem(self, layer) -> None:
        """Start a new session on `layer`. Raises DemError (user-facing message) before changing anything;
        if it fails after the previous session was already closed, the session is dropped cleanly."""
        grid, info = read_dem(layer)
        try:
            files = WorkingFiles(tempfile.mkdtemp(prefix="terrain_scenarios_"), grid, info)
        except (OSError, RuntimeError, MemoryError) as error:
            raise DemError(f"Terrain Scenarios could not create its working files: {error}") from error
        self.close()
        self.stack = FeatureStack(grid)
        self.info = info
        self.files = files
        try:
            self.layers = SketchLayers(self.project, layer, self.files.working_path, self.files.change_path)
        except Exception as error:  # noqa: BLE001 — never leave a half-built session behind
            self._drop_session()
            raise DemError(f"Terrain Scenarios could not create its layers: {error}") from error
        self.dem_layer_id = layer.id()
        self.dem_crs = QgsCoordinateReferenceSystem(layer.crs())
        for warning in info.warnings:
            self.message.emit(Qgis.MessageLevel.Warning, warning)
        self.sessionChanged.emit()
        self.featuresChanged.emit()

    def close(self) -> None:
        """End the session and remove its layers from the project."""
        self._closing = True
        try:
            if self.layers is not None:
                self.layers.remove()
        finally:
            self._closing = False
        self._drop_session()

    def shutdown(self) -> None:
        """Close the session and stop listening to the project (plugin unload)."""
        self.close()
        self.project.layersRemoved.disconnect(self._on_layers_removed)
        self.project.cleared.disconnect(self._drop_session)
        self.project.aboutToBeCleared.disconnect(self._drop_session)

    def add_drawn(self, tool: Tool, mode: Mode, geometry: QgsGeometry, crs, name: str | None = None) -> TerrainFeature | None:
        """Turn a drawn geometry (in `crs`) into a new feature with default values. Returns None,
        with a message, when the drawing cannot be used or no session is active."""
        if not self.has_dem:
            self.message.emit(Qgis.MessageLevel.Warning, NO_SESSION)
            return None
        try:
            wkb = to_dem_wkb(geometry, crs, self.dem_crs, mode)
        except ValueError as error:
            self.message.emit(Qgis.MessageLevel.Warning, str(error))
            return None
        except QgsCsException:
            self.message.emit(Qgis.MessageLevel.Warning, DRAWING_NOT_TRANSFORMED)
            return None
        feature = new_feature(tool, mode, wkb, self.stack.original.cell_size,
                              name=self._unique(name) if name else self._unique_name(tool))
        self._set([*self._features, feature])
        return feature

    def add_from_layer(self, tool: Tool, mode: Mode, layer, selected_only: bool = False) -> TerrainFeature | None:
        """One multi-part feature from a vector layer's features; each part keeps its own reference levels."""
        if not self.has_dem:
            self.message.emit(Qgis.MessageLevel.Warning, NO_SESSION)
            return None
        source = layer.getSelectedFeatures() if selected_only else layer.getFeatures()
        geometries = [QgsGeometry(f.geometry()) for f in source if not f.geometry().isEmpty()]
        if not geometries:
            self.message.emit(Qgis.MessageLevel.Warning, NO_FEATURES_IN_LAYER)
            return None
        combined = geometries[0] if len(geometries) == 1 else QgsGeometry.collectGeometry(geometries)
        return self.add_drawn(tool, mode, combined, layer.crs(), name=layer.name())

    def set_geometry(self, fid: str, geometry: QgsGeometry, crs) -> bool:
        """Replace a feature's shape (brush and vertex editing); False, with a message, if unusable."""
        feature = self.feature(fid)
        try:
            wkb = to_dem_wkb(geometry, crs, self.dem_crs, feature.mode)
        except ValueError as error:
            self.message.emit(Qgis.MessageLevel.Warning, str(error))
            return False
        except QgsCsException:
            self.message.emit(Qgis.MessageLevel.Warning, DRAWING_NOT_TRANSFORMED)
            return False
        self.update_feature(fid, geometry_wkb=wkb)
        return True

    def update_feature(self, fid: str, **changes) -> None:
        self._set([replace(f, **changes) if f.id == fid else f for f in self._features])

    def set_enabled(self, fid: str, enabled: bool) -> None:
        self.update_feature(fid, enabled=bool(enabled))

    def delete_feature(self, fid: str) -> None:
        self._set([f for f in self._features if f.id != fid])

    def reorder(self, ids) -> None:
        by_id = {f.id: f for f in self._features}
        if sorted(ids) != sorted(by_id):
            raise ValueError("reorder() needs every feature id exactly once")
        self._set([by_id[i] for i in ids])

    def export_dem(self, path: str) -> None:
        """Write the modified DEM to `path`; raises RuntimeError without a session, or if `path`
        would overwrite the source DEM or one of this session's working files."""
        if not self.has_dem:
            raise RuntimeError(NO_SESSION)
        target = os.path.realpath(path)
        protected = {os.path.realpath(self.info.path), os.path.realpath(self.files.working_path),
                    os.path.realpath(self.files.change_path)}
        if target in protected:
            raise RuntimeError(EXPORT_OVER_SOURCE)
        export_dem(path, self.stack.working, self.info)

    def set_hillshade_visible(self, visible: bool) -> None:
        if self.layers is not None:
            self.layers.set_hillshade_visible(visible)

    def _set(self, features) -> None:
        features = list(features)
        try:
            window = self.stack.update(features)
        except Exception:  # noqa: BLE001 — never let an engine error take QGIS down or desync the feature list
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Scenarios could not update the terrain; "
                                                          "see the 'Terrain Scenarios' log tab for details.")
            self.featuresChanged.emit()
            return
        self._features = features
        try:
            if window is not None:
                self.files.write(window, self.stack.working)
                self.layers.refresh()
            self.layers.set_outlines(self._outline_items())
        except Exception:  # noqa: BLE001 — never let a file/layer error take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Scenarios could not update the terrain; "
                                                          "see the 'Terrain Scenarios' log tab for details.")
        self.featuresChanged.emit()

    def _outline_items(self) -> list:
        items = []
        for f in self._features:
            if not f.enabled:
                continue
            geometry = from_wkb(f.geometry_wkb)
            if f.mode is Mode.PATH:
                width = max(f.width, self.stack.original.cell_size)
                geometry = geometry.buffer(width / 2.0, 8, Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Miter, 2.0)
            items.append((f.name, TOOL_LABELS[f.tool], geometry))
        return items

    def _unique_name(self, tool: Tool) -> str:
        names = {f.name for f in self._features}
        n = 1
        while f"{TOOL_LABELS[tool]} {n}" in names:
            n += 1
        return f"{TOOL_LABELS[tool]} {n}"

    def _unique(self, name: str) -> str:
        names = {f.name for f in self._features}
        if name not in names:
            return name
        n = 2
        while f"{name} {n}" in names:
            n += 1
        return f"{name} {n}"

    def _drop_session(self) -> None:
        had_session = self.stack is not None
        self.stack = self.info = self.files = self.layers = None
        self.dem_layer_id = None
        self.dem_crs = QgsCoordinateReferenceSystem()
        self._features = []
        if had_session:
            self.sessionChanged.emit()
            self.featuresChanged.emit()

    def _on_layers_removed(self, items) -> None:
        if self._closing or self.stack is None:
            return
        ids = {item if isinstance(item, str) else item.id() for item in items}
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_controller.py` → Expected: `17 passed`
Run: `scripts/test.sh` → Expected: `129 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/gui/controller.py terrain_scenarios/gui/help_texts.py tests/qgis/qgis_helpers.py tests/qgis/test_controller.py
git commit -m "feat(gui): features from a layer and replacing a feature's shape"
```

---

### Task 5: The panel — methods, layer form, editing and highlight

**Files:**
- Create: `terrain_scenarios/gui/layer_source.py`
- Modify: `terrain_scenarios/gui/tool_gallery.py`, `terrain_scenarios/gui/main_dock.py`, `terrain_scenarios/plugin.py`
- Test: `tests/qgis/test_panels.py`, `tests/qgis/test_dock_plugin.py`

**Interfaces:**
- Consumes: every tool from Tasks 1–3 and the controller from Task 4.
- Produces: `LayerSource` with `useRequested(layer, selected_only)` and `set_mode(mode)`; `ToolGallery` with `drawRequested(Tool, Mode, Method)`, `layerRequested(Tool, Mode, layer, selected_only)`, `line_mode`/`area_mode`, `method_buttons` (dict by `Method`), `brush_spin`, `layer_source`, `selected_mode()`, `select_mode(mode)`, `brush_radius()`, `set_brush_radius(radius)`; `MainDock` with `edit_button`, `edit_tool`, `highlight`, `stop_editing()`, `stop_tools()`, `shutdown()`; `TerrainScenariosPlugin` stops both tools when the panel is hidden and calls `dock.shutdown()` on unload.

- [ ] **Step 1: Write the failing panel and dock tests**

**File:** `tests/qgis/test_panels.py`
```python
import pytest

from qgis_helpers import UTM, line_layer, line_through, sample, square, start_session
from terrain_scenarios.core.tools import Mode, PixelMode, Tool
from terrain_scenarios.gui.properties_page import PropertiesPage
from terrain_scenarios.gui.selection import Method
from terrain_scenarios.gui.tool_gallery import ToolGallery


def test_gallery_offers_only_the_shapes_and_methods_a_tool_supports():
    gallery = ToolGallery()
    gallery.select_tool(Tool.RAISE_PATH)
    assert gallery.line_mode.isEnabled() and not gallery.area_mode.isEnabled()
    assert gallery.selected_mode() is Mode.PATH
    assert gallery.method_buttons[Method.FREEHAND].isEnabled()
    assert not gallery.method_buttons[Method.BRUSH].isEnabled() and not gallery.brush_spin.isEnabled()
    gallery.select_tool(Tool.LOWER_FLAT)
    gallery.select_mode(Mode.AREA)
    assert gallery.method_buttons[Method.BRUSH].isEnabled() and gallery.brush_spin.isEnabled()
    requests = []
    gallery.drawRequested.connect(lambda tool, mode, method: requests.append((tool, mode, method)))
    gallery.method_buttons[Method.FREEHAND].click()
    assert requests == [(Tool.LOWER_FLAT, Mode.AREA, Method.FREEHAND)]
    gallery.method_buttons[Method.LAYER].click()
    assert not gallery.layer_source.isHidden() and len(requests) == 1  # the layer form asks first


def test_layer_form_reports_the_chosen_layer(tmp_path):
    gallery = ToolGallery()
    gallery.select_tool(Tool.RAISE_PATH)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    gallery.layer_source.layer_combo.setLayer(layer)
    gallery.layer_source.selected_only.setChecked(True)
    asked = []
    gallery.layerRequested.connect(lambda tool, mode, lyr, only: asked.append((tool, mode, lyr.name(), only)))
    gallery.layer_source.use_button.click()
    assert asked == [(Tool.RAISE_PATH, Mode.PATH, "Planned dikes", True)]


def test_properties_show_the_tool_fields_and_apply_changes(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert all(w.toolTip() for w in (page.amount, page.width, page.slope, page.reach, page.slope_position))
    assert page.amount_label.text() == "Height"
    assert page.form.isRowVisible(page.width) and page.form.isRowVisible(page.slope)
    assert not page.form.isRowVisible(page.slope_position)
    page.amount.setValue(2.5)
    assert c.feature(dike.id).amount == 2.5 and sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    page.show_feature(pond.id)
    assert page.amount_label.text() == "Depth" and not page.form.isRowVisible(page.width)
    assert page.form.isRowVisible(page.slope_position) and page.slope_position.currentData() is True
    page.pixel_mode.setCurrentIndex(page.pixel_mode.findData(PixelMode.ALL_TOUCHED.value))
    assert c.feature(pond.id).pixel_mode is PixelMode.ALL_TOUCHED
```
**File:** `tests/qgis/test_dock_plugin.py`
```python
import pytest
from qgis.core import QgsProject

from qgis.core import QgsPointXY

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, sample, square, world
from terrain_scenarios import classFactory
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.selection import Method
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.gui.main_dock import PAGE_GALLERY, PAGE_PROPERTIES, PAGE_START, MainDock
from terrain_scenarios.qgis_io.layers import GROUP_NAME


def test_drawing_a_dike_from_the_panel(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    assert dock.pages.currentIndex() == PAGE_START and not dock.new_button.isEnabled()
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert controller.has_dem and dock.pages.currentIndex() == PAGE_GALLERY
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert iface.mapCanvas().mapTool() is dock.draw_tool and not dock.hint.isHidden()
    dock.draw_tool.finished.emit(line_through(5, 20, 34, 20))
    assert len(controller.features) == 1
    assert dock.feature_view.selected_id() == controller.features[0].id
    assert dock.pages.currentIndex() == PAGE_PROPERTIES and dock.hint.isHidden() and dock.draw_tool is None
    assert sample(controller.layers.working, 20, 20) == pytest.approx(11.0)
    dock.ask_export_path = lambda: str(tmp_path / "exported.tif")
    dock.export_button.click()
    assert (tmp_path / "exported.tif").exists()


def test_a_geographic_dem_is_reported_in_the_message_bar(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert not dock.controller.has_dem
    iface.messageBar().pushMessage.assert_called()


def test_ending_the_session_stops_a_drawing_in_progress(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert dock.draw_tool is not None
    QgsProject.instance().removeMapLayer(dem.id())  # the user removes the DEM while still drawing
    assert not controller.has_dem and dock.draw_tool is None and dock.hint.isHidden()
    assert iface.mapCanvas().mapTool() is None


def test_hiding_the_panel_stops_a_drawing_and_leaves_no_rubber_band(tmp_path):
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    plugin.dock.dem_combo.setLayer(dem_layer(tmp_path))
    plugin.dock.start_button.click()
    n0 = len(iface.mapCanvas().scene().items())
    plugin.dock.gallery.select_tool(Tool.RAISE_PATH)
    plugin.dock.gallery.select_mode(Mode.PATH)
    plugin.dock.gallery.method_buttons[Method.CLICK].click()
    plugin.action.setChecked(False)
    assert plugin.dock.draw_tool is None
    assert len(iface.mapCanvas().scene().items()) == n0


def test_a_new_session_applies_the_hillshade_checkbox(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    dock.hillshade_box.setChecked(True)
    dock.confirm = lambda text: True
    dock.start_button.click()
    node = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME).findLayer(controller.layers.hillshade_id)
    assert node.itemVisibilityChecked()


def test_plugin_adds_and_removes_its_button_menu_and_panel():
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    iface.addToolBarIcon.assert_called_once_with(plugin.action)
    iface.addPluginToRasterMenu.assert_called_once()
    plugin.action.setChecked(True)
    assert plugin.dock is not None
    iface.addDockWidget.assert_called_once()
    plugin.unload()
    iface.removeToolBarIcon.assert_called_once()
    iface.removeDockWidget.assert_called_once()
    assert plugin.dock is None and plugin.controller is None and plugin.action is None


def _session_dock(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def test_the_brush_extends_the_selected_area_feature(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    pond = controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock._brush_fid == pond.id and not dock.draw_tool.geometry.isEmpty()
    dock.draw_tool.apply_stroke([QgsPointXY(*world(25, 15))])  # paint next to the pond
    dock.draw_tool.finish()
    assert len(controller.features) == 1  # the pond grew, no second feature
    assert sample(controller.layers.working, 25, 15) < 10.0


def test_vertex_editing_reshapes_the_selected_feature(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.edit_tool.geometryChanged.emit(line_through(5, 10, 34, 10))
    assert sample(controller.layers.working, 20, 10) == pytest.approx(11.0)
    assert sample(controller.layers.working, 20, 20) == pytest.approx(10.0)
    dock.edit_button.setChecked(False)
    assert dock.edit_tool is None


def test_selecting_a_feature_highlights_it_on_the_map(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.highlight.numberOfVertices() > 0
    dock.feature_view.clearSelection()
    assert dock.highlight.numberOfVertices() == 0
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_panels.py tests/qgis/test_dock_plugin.py`
Expected: errors — `AttributeError: 'ToolGallery' object has no attribute 'line_mode'`, `… 'layer_source'`, `… 'select_mode'` and `AttributeError: 'MainDock' object has no attribute 'edit_button'`

- [ ] **Step 3: Implement the layer form, the gallery and the panel wiring**

**File:** `terrain_scenarios/gui/layer_source.py`
```python
"""Use lines or areas from a vector layer that is already in the project."""
from __future__ import annotations

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..core.tools import Mode


class LayerSource(QWidget):
    """Layer picker, "selected features only" and the button that turns them into a feature."""

    useRequested = pyqtSignal(object, bool)  # QgsVectorLayer, selected_only

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Layer")))
        self.layer_combo = QgsMapLayerComboBox()
        row.addWidget(self.layer_combo, 1)
        layout.addLayout(row)
        self.selected_only = QCheckBox(self.tr("Selected features only"))
        layout.addWidget(self.selected_only)
        self.use_button = QPushButton(self.tr("Use these features"))
        self.use_button.setToolTip(self.tr("Every feature becomes one part of a single Terrain Scenarios feature; "
                                           "they share the same values."))
        layout.addWidget(self.use_button)
        self.use_button.clicked.connect(self._use)
        self.set_mode(Mode.PATH)

    def set_mode(self, mode: Mode) -> None:
        """Show line layers for paths and polygon layers for areas."""
        self.layer_combo.setFilters(Qgis.LayerFilter.LineLayer if mode is Mode.PATH else Qgis.LayerFilter.PolygonLayer)

    def _use(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is not None:
            self.useRequested.emit(layer, self.selected_only.isChecked())
```
**File:** `terrain_scenarios/gui/tool_gallery.py`
```python
"""'What do you want to build?' — the tool list, the Line/Area toggle and the 'Where?' methods."""
from __future__ import annotations

from qgis.core import QgsApplication
from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QRadioButton,
                                 QToolButton, QVBoxLayout, QWidget)

from ..core.tools import TOOL_INFO, Mode, Tool
from .help_texts import TOOL_LABELS, TOOL_SUMMARIES
from .layer_source import LayerSource
from .selection import METHOD_ICONS, METHOD_LABELS, METHOD_TIPS, Method

DEFAULT_BRUSH_RADIUS = 5.0


class ToolGallery(QWidget):
    drawRequested = pyqtSignal(object, object, object)  # Tool, Mode, Method
    layerRequested = pyqtSignal(object, object, object, bool)  # Tool, Mode, QgsVectorLayer, selected_only

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(self.tr("What do you want to build?")))
        self.tool_list = QListWidget()
        for tool in Tool:
            item = QListWidgetItem(TOOL_LABELS[tool])
            item.setData(Qt.ItemDataRole.UserRole, tool.value)
            item.setToolTip(TOOL_SUMMARIES[tool])
            self.tool_list.addItem(item)
        layout.addWidget(self.tool_list)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(self.tr("Shape")))
        self.line_mode = QRadioButton(self.tr("Line"))
        self.area_mode = QRadioButton(self.tr("Area"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.line_mode)
        self.mode_group.addButton(self.area_mode)
        mode_row.addWidget(self.line_mode)
        mode_row.addWidget(self.area_mode)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        layout.addWidget(QLabel(self.tr("Where?")))
        method_row = QHBoxLayout()
        self.method_buttons = {method: self._method_button(method) for method in Method}
        for button in self.method_buttons.values():
            method_row.addWidget(button)
        method_row.addStretch(1)
        layout.addLayout(method_row)

        brush_row = QHBoxLayout()
        self.brush_label = QLabel(self.tr("Brush radius"))
        brush_row.addWidget(self.brush_label)
        self.brush_spin = QgsDoubleSpinBox()
        self.brush_spin.setRange(0.1, 1000.0)
        self.brush_spin.setDecimals(1)
        self.brush_spin.setSuffix(" m")
        self.brush_spin.setValue(DEFAULT_BRUSH_RADIUS)
        self.brush_spin.setToolTip(self.tr("Radius of the round brush; [ and ] or Ctrl+wheel change it while painting."))
        brush_row.addWidget(self.brush_spin)
        brush_row.addStretch(1)
        layout.addLayout(brush_row)

        self.layer_source = LayerSource()
        self.layer_source.hide()
        layout.addWidget(self.layer_source)

        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self.line_mode.toggled.connect(self._mode_changed)
        self.area_mode.toggled.connect(self._mode_changed)
        self.layer_source.useRequested.connect(self._use_layer)
        self._tool_changed()

    def selected_tool(self) -> Tool | None:
        item = self.tool_list.currentItem()
        return Tool(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def selected_mode(self) -> Mode | None:
        if self.area_mode.isChecked():
            return Mode.AREA
        return Mode.PATH if self.line_mode.isChecked() else None

    def select_tool(self, tool: Tool) -> None:
        for row in range(self.tool_list.count()):
            if self.tool_list.item(row).data(Qt.ItemDataRole.UserRole) == tool.value:
                self.tool_list.setCurrentRow(row)

    def select_mode(self, mode: Mode) -> None:
        (self.area_mode if mode is Mode.AREA else self.line_mode).setChecked(True)

    def brush_radius(self) -> float:
        return self.brush_spin.value()

    def set_brush_radius(self, radius: float) -> None:
        self.brush_spin.setValue(radius)

    def _method_button(self, method: Method) -> QToolButton:
        button = QToolButton()
        button.setIcon(QgsApplication.getThemeIcon(METHOD_ICONS[method]))
        button.setText(METHOD_LABELS[method])
        button.setToolTip(METHOD_TIPS[method])
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.clicked.connect(lambda _checked=False, m=method: self._pick(m))
        return button

    def _tool_changed(self, *_args) -> None:
        tool = self.selected_tool()
        self.summary.setText(TOOL_SUMMARIES[tool] if tool else self.tr("Pick a tool, then choose where to draw it."))
        modes = TOOL_INFO[tool].modes if tool else ()
        self.line_mode.setEnabled(Mode.PATH in modes)
        self.area_mode.setEnabled(Mode.AREA in modes)
        if self.selected_mode() not in modes:
            self.mode_group.setExclusive(False)
            self.line_mode.setChecked(False)
            self.area_mode.setChecked(False)
            self.mode_group.setExclusive(True)
            if modes:
                self.select_mode(modes[0])
        self._mode_changed()

    def _mode_changed(self, *_args) -> None:
        mode = self.selected_mode()
        for method, button in self.method_buttons.items():
            button.setEnabled(mode is not None and (mode is Mode.AREA or method is not Method.BRUSH))
        brush_usable = self.method_buttons[Method.BRUSH].isEnabled()
        self.brush_label.setEnabled(brush_usable)
        self.brush_spin.setEnabled(brush_usable)
        if mode is not None:
            self.layer_source.set_mode(mode)
        else:
            self.layer_source.hide()

    def _pick(self, method: Method) -> None:
        tool, mode = self.selected_tool(), self.selected_mode()
        if tool is None or mode is None:
            return
        self.layer_source.setVisible(method is Method.LAYER)
        if method is not Method.LAYER:
            self.drawRequested.emit(tool, mode, method)

    def _use_layer(self, layer, selected_only: bool) -> None:
        tool, mode = self.selected_tool(), self.selected_mode()
        if tool is not None and mode is not None:
            self.layerRequested.emit(tool, mode, layer, selected_only)
```
**File:** `terrain_scenarios/gui/main_dock.py`
```python
"""The Terrain Scenarios panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

from qgis.core import Qgis, QgsApplication, QgsCoordinateTransform, QgsGeometry, QgsProject
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError
from .feature_list import FeatureListModel, FeatureListView
from .map_tools.brush import BrushTool
from .map_tools.draw_line import DrawLineTool
from .map_tools.draw_polygon import DrawPolygonTool
from .map_tools.freehand import FreehandTool
from .map_tools.vertex_edit import VertexEditTool
from .properties_page import PropertiesPage
from .selection import EDIT_HINT, METHOD_HINTS, Method
from .tool_gallery import ToolGallery

PAGE_START, PAGE_GALLERY, PAGE_PROPERTIES = range(3)


class MainDock(QgsDockWidget):
    def __init__(self, iface, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Terrain Scenarios"))
        self.setObjectName("TerrainScenariosDock")
        self.iface = iface
        self.controller = controller
        self.draw_tool = None
        self._previous_tool = None
        self.confirm = self._confirm_dialog  # replaceable in tests
        self.ask_export_path = self._export_dialog  # replaceable in tests
        self.edit_tool = None
        self._brush_fid = None
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)

        body = QWidget()
        layout = QVBoxLayout(body)
        dem_row = QHBoxLayout()
        dem_row.addWidget(QLabel(self.tr("DEM")))
        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(Qgis.LayerFilter.RasterLayer)
        dem_row.addWidget(self.dem_combo, 1)
        self.start_button = QPushButton(self.tr("Start"))
        self.start_button.setToolTip(self.tr("Start sketching on this DEM. The DEM itself is never changed."))
        dem_row.addWidget(self.start_button)
        layout.addLayout(dem_row)

        tools_row = QHBoxLayout()
        self.export_button = QToolButton()
        self.export_button.setIcon(QgsApplication.getThemeIcon("/mActionFileSaveAs.svg"))
        self.export_button.setText(self.tr("Export DEM…"))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setToolTip(self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
        self.hillshade_box = QCheckBox(self.tr("Hillshade"))
        tools_row.addWidget(self.export_button)
        tools_row.addWidget(self.hillshade_box)
        tools_row.addStretch(1)
        layout.addLayout(tools_row)

        self.model = FeatureListModel(controller, self)
        self.feature_view = FeatureListView(self.model)
        layout.addWidget(self.feature_view, 1)
        list_row = QHBoxLayout()
        self.new_button = QPushButton(QgsApplication.getThemeIcon("/mActionAdd.svg"), self.tr("New feature"))
        self.delete_button = QPushButton(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"))
        self.edit_button = QPushButton(QgsApplication.getThemeIcon("/mActionNodeTool.svg"), self.tr("Edit shape"))
        self.edit_button.setCheckable(True)
        self.edit_button.setToolTip(self.tr("Move, add or remove the points of the selected feature."))
        list_row.addWidget(self.new_button)
        list_row.addWidget(self.delete_button)
        list_row.addWidget(self.edit_button)
        list_row.addStretch(1)
        layout.addLayout(list_row)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.hide()
        layout.addWidget(self.hint)

        self.pages = QStackedWidget()
        start_label = QLabel(self.tr("Pick a DEM above and press Start. Terrain Scenarios works on a copy; your DEM "
                                     "is never changed."))
        start_label.setWordWrap(True)
        self.gallery = ToolGallery()
        self.properties = PropertiesPage(controller)
        for page in (start_label, self.gallery, self.properties):
            self.pages.addWidget(page)
        layout.addWidget(self.pages, 2)
        self.setWidget(body)

        self.start_button.clicked.connect(self._start)
        self.export_button.clicked.connect(self._export)
        self.hillshade_box.toggled.connect(controller.set_hillshade_visible)
        self.new_button.clicked.connect(self._new_feature)
        self.delete_button.clicked.connect(self._delete_selected)
        self.feature_view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.feature_view.customContextMenuRequested.connect(self._context_menu)
        self.gallery.drawRequested.connect(self._begin_drawing)
        self.gallery.layerRequested.connect(self._use_layer)
        self.edit_button.toggled.connect(self._toggle_edit)
        self.iface.mapCanvas().mapToolSet.connect(self._map_tool_set)
        controller.featuresChanged.connect(self._refresh_highlight)
        controller.sessionChanged.connect(self._session_changed)
        controller.message.connect(self._show_message)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        tool, self.draw_tool, self._brush_fid = self.draw_tool, None, None
        self._release_tool(tool)

    def stop_editing(self) -> None:
        """Leave vertex editing and give the canvas its previous map tool back."""
        tool, self.edit_tool = self.edit_tool, None
        self._release_tool(tool)
        if self.edit_button.isChecked():
            self.edit_button.setChecked(False)

    def stop_tools(self) -> None:
        """Stop drawing and editing — the panel is hidden, the session ended or the tool changed."""
        self.end_drawing()
        self.stop_editing()

    def shutdown(self) -> None:
        """Stop the tools and release the highlight; called when the plugin unloads."""
        self.stop_tools()
        self.highlight.reset(Qgis.GeometryType.Line)
        self.iface.mapCanvas().scene().removeItem(self.highlight)

    def _release_tool(self, tool) -> None:
        if tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is tool:
                if self._previous_tool is not None and not sip.isdeleted(self._previous_tool):
                    canvas.setMapTool(self._previous_tool)
                else:
                    canvas.unsetMapTool(tool)
            tool.dispose()
            tool.deleteLater()
        self.hint.hide()

    def closeEvent(self, event):  # noqa: N802 — Qt override
        self.end_drawing()
        super().closeEvent(event)

    def _session_changed(self) -> None:
        has_dem = self.controller.has_dem
        if not has_dem:
            self.stop_tools()  # a drawing or edit cannot outlive its session
            self._update_highlight(None)
        for widget in (self.export_button, self.hillshade_box, self.new_button, self.delete_button,
                       self.edit_button, self.feature_view):
            widget.setEnabled(has_dem)
        if self.controller.layers is not None:
            project = self.controller.project
            self.dem_combo.setExceptedLayerList([project.mapLayer(i) for i in self.controller.layers.layer_ids])
            self.controller.set_hillshade_visible(self.hillshade_box.isChecked())
        else:
            self.dem_combo.setExceptedLayerList([])
        self.pages.setCurrentIndex(PAGE_GALLERY if has_dem else PAGE_START)

    def _start(self) -> None:
        layer = self.dem_combo.currentLayer()
        if layer is None:
            return
        if self.controller.features and not self.confirm(
                self.tr("Start again on this DEM? The current features will be discarded.")):
            return
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))

    def _new_feature(self) -> None:
        self.feature_view.clearSelection()
        self.pages.setCurrentIndex(PAGE_GALLERY)

    def _delete_selected(self) -> None:
        fid = self.feature_view.selected_id()
        if fid is not None:
            self.controller.delete_feature(fid)

    def _selection_changed(self, *_args) -> None:
        fid = self.feature_view.selected_id()
        self.stop_editing()
        self.edit_button.setEnabled(fid is not None)
        self._update_highlight(fid)
        if fid is not None:
            self.properties.show_feature(fid)
            self.pages.setCurrentIndex(PAGE_PROPERTIES)
        elif self.controller.has_dem:
            self.pages.setCurrentIndex(PAGE_GALLERY)

    def _begin_drawing(self, tool, mode, method) -> None:
        self.stop_tools()
        canvas = self.iface.mapCanvas()
        if method is Method.BRUSH:
            self._brush_fid = self._brush_target(tool, mode)
            initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
            self.draw_tool = BrushTool(canvas, self.gallery.brush_radius(), initial)
            self.draw_tool.radiusChanged.connect(self.gallery.set_brush_radius)
        elif method is Method.FREEHAND:
            shape = Qgis.GeometryType.Line if mode is Mode.PATH else Qgis.GeometryType.Polygon
            self.draw_tool = FreehandTool(canvas, shape)
        else:
            self.draw_tool = (DrawLineTool if mode is Mode.PATH else DrawPolygonTool)(canvas)
        self.draw_tool.finished.connect(lambda geometry, t=tool, m=mode: self._drawn(t, m, geometry))
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.setText(self.tr(METHOD_HINTS[method]))
        self.hint.show()

    def _brush_target(self, tool, mode) -> str | None:
        """The selected feature the brush should extend, if it fits the chosen tool and shape."""
        fid = self.feature_view.selected_id()
        if fid is None or mode is not Mode.AREA:
            return None
        feature = self.controller.feature(fid)
        return fid if feature.tool is tool and feature.mode is Mode.AREA else None

    def _drawn(self, tool, mode, geometry) -> None:
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        fid = self._brush_fid
        self.end_drawing()
        if fid is not None:
            self.controller.set_geometry(fid, geometry, crs)
            self.feature_view.select_id(fid)
            return
        feature = self.controller.add_drawn(tool, mode, geometry, crs)
        if feature is not None:
            self.feature_view.select_id(feature.id)

    def _use_layer(self, tool, mode, layer, selected_only) -> None:
        feature = self.controller.add_from_layer(tool, mode, layer, selected_only)
        if feature is not None:
            self.feature_view.select_id(feature.id)

    def _toggle_edit(self, checked: bool) -> None:
        if not checked:
            self.stop_editing()
            return
        fid = self.feature_view.selected_id()
        if fid is None:
            self.edit_button.setChecked(False)
            return
        self.end_drawing()
        canvas = self.iface.mapCanvas()
        self.edit_tool = VertexEditTool(canvas, self._to_canvas(self.controller.feature_geometry(fid)))
        self.edit_tool.geometryChanged.connect(lambda geometry, f=fid: self._edited(f, geometry))
        self.edit_tool.cancelled.connect(self.stop_editing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.edit_tool)
        self.hint.setText(self.tr(EDIT_HINT))
        self.hint.show()

    def _edited(self, fid, geometry) -> None:
        self.controller.set_geometry(fid, geometry, self.iface.mapCanvas().mapSettings().destinationCrs())

    def _map_tool_set(self, new_tool, _old_tool=None) -> None:
        """The user picked another map tool: stop our drawing or editing."""
        if self.draw_tool is not None and new_tool is not self.draw_tool:
            self.end_drawing()
        if self.edit_tool is not None and new_tool is not self.edit_tool:
            self.stop_editing()

    def _to_canvas(self, geometry: QgsGeometry) -> QgsGeometry:
        """A geometry in the DEM CRS, expressed in the canvas CRS."""
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        result = QgsGeometry(geometry)
        if canvas_crs != self.controller.dem_crs:
            result.transform(QgsCoordinateTransform(self.controller.dem_crs, canvas_crs, QgsProject.instance()))
        return result

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map."""
        if fid is None or not self.controller.has_dem or fid not in {f.id for f in self.controller.features}:
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        geometry = self._to_canvas(self.controller.feature_geometry(fid))
        self.highlight.reset(geometry.type())
        self.highlight.setToGeometry(geometry, None)

    def _export(self) -> None:
        path = self.ask_export_path()
        if not path:
            return
        try:
            self.controller.export_dem(path)
        except (OSError, RuntimeError) as error:
            self._show_message(Qgis.MessageLevel.Critical, self.tr("Export failed: {}").format(error))
            return
        self._show_message(Qgis.MessageLevel.Success, self.tr("Exported the modified DEM to {}").format(path))

    def _context_menu(self, position) -> None:
        index = self.feature_view.indexAt(position)
        if not index.isValid():
            return
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(QgsApplication.getThemeIcon("/mActionZoomToLayer.svg"), self.tr("Zoom to feature"),
                       lambda: self._zoom_to(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"),
                       lambda: self.controller.delete_feature(fid))
        menu.exec(self.feature_view.viewport().mapToGlobal(position))

    def _zoom_to(self, fid: str) -> None:
        canvas = self.iface.mapCanvas()
        transform = QgsCoordinateTransform(self.controller.dem_crs, canvas.mapSettings().destinationCrs(),
                                           QgsProject.instance())
        extent = transform.transformBoundingBox(self.controller.feature_geometry(fid).boundingBox())
        canvas.setExtent(extent.buffered(max(extent.width(), extent.height()) * 0.25 + 1.0))
        canvas.refresh()

    def _show_message(self, level, text: str) -> None:
        self.iface.messageBar().pushMessage(self.tr("Terrain Scenarios"), text, level, 8)

    def _confirm_dialog(self, text: str) -> bool:
        return QMessageBox.question(self, self.tr("Terrain Scenarios"), text) == QMessageBox.StandardButton.Yes

    def _export_dialog(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export modified DEM"), "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
        return path
```
**File:** `terrain_scenarios/plugin.py`
```python
"""Plugin entry point: toolbar button, Raster menu entry and the Terrain Scenarios panel."""
from __future__ import annotations

import os

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon

from .gui.controller import SketchController
from .gui.main_dock import MainDock
from .qgis_io.compat import gdal_problems

MENU = "&Terrain Scenarios"


class TerrainScenariosPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.controller = None

    def initGui(self):  # noqa: N802 — QGIS plugin API
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icons", "terrain_scenarios.svg"))
        self.action = QAction(icon, "Terrain Scenarios", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Sketch dikes, ditches, ponds and other features onto a DEM")
        self.action.toggled.connect(self._toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(MENU, self.action)

    def unload(self):
        if self.dock is not None:
            self.dock.shutdown()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.controller is not None:
            self.controller.shutdown()
            self.controller = None
        if self.action is not None:
            self.iface.removePluginRasterMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def _toggle(self, checked: bool) -> None:
        if checked and self.dock is None and not self._create_dock():
            self.action.setChecked(False)
            return
        if self.dock is not None:
            if not checked:
                self.dock.stop_tools()
            self.dock.setUserVisible(checked)

    def _create_dock(self) -> bool:
        problems = gdal_problems()
        if problems:
            self.iface.messageBar().pushCritical("Terrain Scenarios", " ".join(problems))
            return False
        self.controller = SketchController(QgsProject.instance())
        self.dock = MainDock(self.iface, self.controller, self.iface.mainWindow())
        self.dock.closedStateChanged.connect(lambda closed: self.action.setChecked(not closed))
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        return True
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_panels.py tests/qgis/test_dock_plugin.py` → Expected: `12 passed`
Run: `scripts/test.sh` → Expected: `133 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/gui/layer_source.py terrain_scenarios/gui/tool_gallery.py terrain_scenarios/gui/main_dock.py terrain_scenarios/plugin.py tests/qgis/test_panels.py tests/qgis/test_dock_plugin.py
git commit -m "feat(gui): selection methods, layer form, shape editing and map highlight"
```

---

## Manual check in QGIS (for the human, after merge)

1. Rebuild and reinstall the plugin ZIP (or `scripts/dev_install.sh` once), restart QGIS.
2. Start a session on a projected DEM. For **Raise path**: Shape = Line, then **Freehand** — hold the mouse and trace a dike; check the rubber band follows and snapping still works.
3. For **Lower flat**: Shape = Area, then **Brush** — paint a pond, hold Shift to erase, use `[` / `]` and Ctrl+wheel for the radius; right-click to finish.
4. Select the pond, press **Brush** again and paint next to it: the pond should grow instead of a second feature appearing.
5. Select a drawn dike, press **Edit shape**, drag a vertex, double-click a segment, hover a vertex and press Delete; the terrain follows each change.
6. **From layer**: pick a line layer from your project, tick "Selected features only", press "Use these features".
7. Check that selecting a row in the list outlines that feature on the map, and that switching to QGIS's pan tool stops drawing/editing.

## Roadmap: Plans 4–6

| Plan | Milestone | Builds on Plan 3 via |
|---|---|---|
| 4 | Profile dock (cross + long), live preview while dragging, `FeatureStack.terrain_before` | `SketchController.set_geometry/update_feature`, `Preview`, `PropertiesPage` |
| 5 | Illustrated gallery, help texts, tooltips, pixel-mode pictures, "Reproject…" button, `QgsSettings` persistence | `selection.py` labels/tips, `ToolGallery`, `help_texts.py` |
| 6 | Scenario GeoPackage, volumes panel, undo/redo, 3D view, duplicate/rename, ZIP packaging | `SketchController`, `TerrainFeature.to_dict/from_dict`, `FeatureStats` |

---

## Addendum: final-review fixes

The task blocks above are the plan as written. Five tasks landed on `feat/selection-methods`, each reviewed as it
landed, followed by a whole-branch review and one fix wave. **Where this addendum and the task blocks disagree, the
code is authoritative** — the blocks were generated from a prototype that the reviews then improved.

### Changed after the task blocks

| # | What changed | Why |
|---|---|---|
| C1 | `SketchController.set_geometry` looks the feature up with a `None` default and guards on `has_dem` | Deleting a feature mid-brush-stroke raised `StopIteration` inside a Qt callback — an interpreter abort that took QGIS down with unsaved work. `main_dock` also clears `_brush_fid` when its target disappears. |
| I2 | `VertexEditTool` guards the ring/part containing the vertex (`vertexIdFromVertexNr`), not the whole geometry | The whole-geometry count let an exterior ring be reduced while a hole existed, producing invalid geometry that `makeValid()` silently rewrote. The Brush makes donuts by design (`difference` → one interior ring), so the path is reachable. **See the known residual below.** |
| I3 | Icons: `/mActionSelectFreehand.svg`, `/mActionAddBasicCircle.svg`, `EDIT_ICON = /mActionVertexTool.svg` | `/mActionCaptureCurve.svg`, `/mActionCircle.svg` and `/mActionNodeTool.svg` are null in QGIS 4.2.2, so three buttons rendered blank. `getThemeIcon` fails silently; a test now asserts every panel icon resolves. |
| I4 | Added `test_vertex_deletion_guards_each_ring_not_the_whole_geometry` | The original polygon test used a single-ring triangle, where per-ring and whole-geometry guards are indistinguishable — it pinned nothing. |
| I5 | Brush radius suffix derives from the canvas CRS's map units | It was hardcoded `" m"` while the brush buffers in the canvas CRS. A UTM DEM in an EPSG:4326 project made "5.0 m" buffer 5 degrees. |
| I6 | `BRUSH_EXTEND_HINT` names the feature being extended | Extend-vs-create was decided on a conjunction the user could not see. The behaviour stands; only its visibility changed. |
| — | Smaller: `hint.hide()` moved inside its guard; `closeEvent` → `stop_tools()`; brush `finish()` emits `cancelled` on an empty geometry; dead `freehand.min_vertices` and `help_texts.DRAW_HINT` removed; `BrushTool.__init__` routes through `set_radius`; vertex insert snaps; release emits only when the geometry actually changed; `_unique`'s collision branch covered | Each confirmed by review. |

### Ring editing refuses edits that would leave the shape invalid

The per-ring guard alone was not enough: it blocked a *second* exterior deletion but not the first. An exterior ring
going 5 → 4 vertices left a triangle with the hole outside it (`isGeosValid() == False`), and `to_dem_wkb`'s
`makeValid()` rewrote the feature into a shape the user never drew — with no undo to recover it. A probe then showed
the **drag** path had the same hazard: dragging a shell corner into the hole produced an invalid geometry too.

`VertexEditTool` now snapshots the geometry before a delete and reuses the press-time snapshot on a drag release; if
the result is not `isGeosValid()`, it restores the snapshot and emits nothing. Insertion is deliberately excluded —
adding a point on an existing segment cannot make a valid ring invalid. The check is free (`isGeosValid()` measured
0.00 ms on a 500-vertex polygon).

Two things worth knowing about the guard. It refuses on the *result* being invalid without asking whether the
geometry was already invalid on entry; that is safe because everything reaching the tool has been through
`makeValid()`, and the only gap — reprojection in `_to_canvas` distorting a valid shape — would make that one feature
refuse edits until redrawn rather than corrupt it. And a refusal is **silent**, matching the existing ring-guard
behaviour: the drag visibly snaps back, but a refused Delete simply does nothing.

### Deferred to later plans

| Plan | Items |
|---|---|
| 4 | Watch `main_dock.py` (336 lines, coordinating session state, drawing, editing, brush-extend, highlight, export and context menus) before it grows further. |
| 5 | `tr()` is called on non-literals (`METHOD_HINTS[method]`, `EDIT_HINT`) so `pylupdate` cannot extract them — harmless while English-only, but it defeats the point of the `tr()` calls; `NO_FEATURES_IN_LAYER` misdiagnoses its most likely trigger ("Selected features only" with nothing selected); "Use these features" is a dead button on an empty combo; a refused vertex edit gives no feedback at all (see above) — a status hint would stop users reading a refusal as an unresponsive tool. |
| 6 | `add_from_layer` has no size ceiling and `_set` is synchronous — importing a large road network freezes QGIS with no progress or warning; undo/redo would also defuse the ring residual above. |
| — | Ship-as-is, recorded for completeness: `brush.py` hardcodes `Polygon` in one `reset`; no brush move-distance throttle; Esc skips `reset()` in `VertexEditTool` (the wired path covers it); `_unique_name`/`_unique` near-duplication; no distinct "layer with zero features" test; no direct `featuresChanged → _refresh_highlight` test; vestigial `snap_indicator is not None` checks. |
