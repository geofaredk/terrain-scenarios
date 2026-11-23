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


def test_polygon_vertex_editing_respects_minimum_ring_size():
    canvas = fake_iface().mapCanvas()
    # Create a simple triangle polygon (4 vertices: 3 corners + 1 to close the ring)
    a, b, c = QgsPointXY(*world(5, 5)), QgsPointXY(*world(15, 5)), QgsPointXY(*world(10, 15))
    tool = VertexEditTool(canvas, QgsGeometry.fromPolygonXY([[a, b, c, a]]))
    changes = []
    tool.geometryChanged.connect(changes.append)
    assert tool.vertex_count() == 4  # triangle with closing point
    # Move a vertex
    x, y = pixel(canvas, a)
    drag(tool, canvas, [(x, y), (x - 10, y + 10), (x - 10, y + 10)])
    assert len(changes) == 1 and changes[-1].vertexAt(0).x() < a.x()
    # Try to delete a vertex: should fail (would drop below 4 vertices for a ring)
    tool.canvasMoveEvent(event(canvas, x, y, QEvent.Type.MouseMove))
    press(tool, Qt.Key.Key_Delete)
    assert tool.vertex_count() == 4  # still 4 vertices, no deletion
    # Add a vertex to make it a quad (5 vertices)
    mid_x, mid_y = pixel(canvas, QgsPointXY((b.x() + c.x()) / 2, (b.y() + c.y()) / 2))
    tool.canvasDoubleClickEvent(event(canvas, mid_x, mid_y, QEvent.Type.MouseButtonDblClick))
    assert tool.vertex_count() == 5 and len(changes) == 2
    # Now delete should work
    tool.canvasMoveEvent(event(canvas, mid_x, mid_y, QEvent.Type.MouseMove))
    press(tool, Qt.Key.Key_Delete)
    assert tool.vertex_count() == 4 and len(changes) == 3


def test_the_brush_clamps_the_radius_it_is_constructed_with():
    canvas = fake_iface().mapCanvas()
    assert BrushTool(canvas, radius=0.0).radius == pytest.approx(0.01)


def test_erasing_the_whole_painted_area_cancels_instead_of_finishing():
    canvas = fake_iface().mapCanvas()
    tool = BrushTool(canvas, radius=2.0)
    painted, cancelled = [], []
    tool.finished.connect(painted.append)
    tool.cancelled.connect(lambda: cancelled.append(True))
    tool.apply_stroke([QgsPointXY(*world(10, 10))])
    tool.set_radius(6.0)
    tool.apply_stroke([QgsPointXY(*world(10, 10))], erase=True)
    assert tool.geometry.isEmpty()
    press(tool, Qt.Key.Key_Return)
    assert painted == [] and cancelled == [True]


def test_clicking_a_vertex_without_moving_it_emits_nothing():
    canvas = fake_iface().mapCanvas()
    a, b, c = QgsPointXY(*world(5, 20)), QgsPointXY(*world(20, 20)), QgsPointXY(*world(30, 20))
    tool = VertexEditTool(canvas, QgsGeometry.fromPolylineXY([a, b, c]))
    changes = []
    tool.geometryChanged.connect(changes.append)
    x, y = pixel(canvas, a)
    drag(tool, canvas, [(x, y), (x, y)])  # press and release on the vertex without moving it
    assert changes == []
    drag(tool, canvas, [(x, y), (x, y - 20), (x, y - 20)])
    assert len(changes) == 1


def test_an_inserted_vertex_snaps_like_a_dragged_one():
    canvas = fake_iface().mapCanvas()
    a, b = QgsPointXY(*world(5, 20)), QgsPointXY(*world(25, 20))
    tool = VertexEditTool(canvas, QgsGeometry.fromPolylineXY([a, b]))
    target = QgsPointXY(*world(15, 12))
    tool.snap = lambda _event: target  # as if the project's snapping caught a nearby feature
    mid_x, mid_y = pixel(canvas, QgsPointXY((a.x() + b.x()) / 2, a.y()))
    tool.canvasDoubleClickEvent(event(canvas, mid_x, mid_y, QEvent.Type.MouseButtonDblClick))
    assert tool.vertex_count() == 3
    assert tool.geometry.vertexAt(1).x() == pytest.approx(target.x())
    assert tool.geometry.vertexAt(1).y() == pytest.approx(target.y())


def donut() -> QgsGeometry:
    """A square with a triangular hole — what the brush makes when a stroke erases a bite out of a blob."""
    shell = [QgsPointXY(*world(c, r)) for c, r in ((5, 5), (25, 5), (25, 25), (5, 25), (5, 5))]
    hole = [QgsPointXY(*world(c, r)) for c, r in ((8, 14), (14, 20), (8, 20), (8, 14))]
    return QgsGeometry.fromPolygonXY([shell, hole])


def test_vertex_deletion_guards_each_ring_not_the_whole_geometry():
    canvas = fake_iface().mapCanvas()
    tool = VertexEditTool(canvas, donut())
    changes = []
    tool.geometryChanged.connect(changes.append)
    assert tool.vertex_count() == 9 and tool.geometry.constGet().numInteriorRings() == 1

    # The hole is already a triangle, even though the geometry as a whole has nine vertices.
    tool.delete_vertex_near(QgsPointXY(*world(14, 20)))
    assert tool.vertex_count() == 9 and changes == []

    # The exterior ring is a square and can spare a corner.
    tool.delete_vertex_near(QgsPointXY(*world(25, 5)))
    assert tool.vertex_count() == 8 and len(changes) == 1

    # It is a triangle now: dropping another corner would discard the shell and promote the hole.
    tool.delete_vertex_near(QgsPointXY(*world(25, 25)))
    assert tool.vertex_count() == 8 and len(changes) == 1
    assert tool.geometry.constGet().numInteriorRings() == 1 and tool.geometry.isGeosValid()


def test_deleting_a_corner_that_would_put_the_hole_outside_the_shell_is_refused():
    canvas = fake_iface().mapCanvas()
    tool = VertexEditTool(canvas, donut())
    changes = []
    tool.geometryChanged.connect(changes.append)
    before = tool.geometry.asWkt()

    # The shell is a square and has vertices to spare, but losing this corner leaves a triangle
    # that no longer contains the hole — makeValid() would rewrite the feature and there is no undo.
    tool.delete_vertex_near(QgsPointXY(*world(5, 5)))
    assert tool.geometry.asWkt() == before and tool.geometry.isGeosValid() and changes == []


def test_dragging_a_corner_into_the_hole_is_refused_on_release():
    canvas = fake_iface().mapCanvas()
    tool = VertexEditTool(canvas, donut())
    changes = []
    tool.geometryChanged.connect(changes.append)
    before = tool.geometry.asWkt()

    corner = pixel(canvas, QgsPointXY(*world(5, 25)))
    inside_the_hole = pixel(canvas, QgsPointXY(*world(10, 18)))
    drag(tool, canvas, [corner, inside_the_hole, inside_the_hole])
    assert tool.geometry.asWkt() == before and tool.geometry.isGeosValid() and changes == []


def test_ordinary_deletes_and_drags_on_a_simple_area_still_go_through():
    canvas = fake_iface().mapCanvas()
    corners = [QgsPointXY(*world(c, r)) for c, r in ((5, 5), (25, 5), (25, 25), (5, 25), (5, 5))]
    tool = VertexEditTool(canvas, QgsGeometry.fromPolygonXY([corners]))
    changes = []
    tool.geometryChanged.connect(changes.append)

    x, y = pixel(canvas, corners[0])
    drag(tool, canvas, [(x, y), (x + 30, y + 30), (x + 30, y + 30)])
    assert len(changes) == 1 and changes[-1].vertexAt(0).x() > corners[0].x()

    tool.delete_vertex_near(corners[1])
    assert tool.vertex_count() == 4 and len(changes) == 2 and tool.geometry.isGeosValid()
