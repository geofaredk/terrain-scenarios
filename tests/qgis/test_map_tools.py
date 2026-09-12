from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QKeyEvent

import pytest
from qgis.core import Qgis, QgsGeometry, QgsPointXY

from qgis_helpers import fake_iface, world
from terrain_sketch.gui.map_tools.draw_line import DrawLineTool
from terrain_sketch.gui.map_tools.draw_polygon import DrawPolygonTool
from terrain_sketch.gui.map_tools.brush import BrushTool
from terrain_sketch.gui.map_tools.freehand import FreehandTool


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
