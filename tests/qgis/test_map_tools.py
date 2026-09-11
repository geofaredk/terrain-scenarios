from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QKeyEvent

from qgis_helpers import fake_iface
from terrain_sketch.gui.map_tools.draw_line import DrawLineTool
from terrain_sketch.gui.map_tools.draw_polygon import DrawPolygonTool


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
