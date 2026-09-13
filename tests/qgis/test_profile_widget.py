from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent

from terrain_sketch.gui.profile_widget import Kind, ProfileWidget


def press(widget, x, y, button=Qt.MouseButton.LeftButton, kind=QEvent.Type.MouseButtonPress):
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent,
     QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent,
     QEvent.Type.MouseButtonDblClick: widget.mouseDoubleClickEvent}[kind](event)


def widget_with(points, kind=Kind.CROSS, size=(400, 200)):
    w = ProfileWidget(kind)
    w.resize(*size)
    w.set_profile(points)
    return w


def test_a_widget_with_no_feature_shows_the_hint_and_no_handles():
    w = ProfileWidget(Kind.CROSS)
    w.resize(400, 200)
    assert w.points == [] and w.handle_at(QPointF(10, 10)) == -1


def test_dragging_a_handle_emits_while_moving_and_once_on_release():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)
    start = w._to_screen(12.0, -3.0)
    press(w, start.x(), start.y())
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseMove)
    assert len(during) == 1 and during[-1][-1][1] > -3.0   # the handle moved up
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert len(committed) == 1 and committed[-1] == during[-1]


def test_a_drag_that_does_not_move_commits_nothing():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    point = w._to_screen(2.0, 0.0)
    press(w, point.x(), point.y())
    press(w, point.x(), point.y(), kind=QEvent.Type.MouseButtonRelease)
    assert committed == []


def test_the_first_handle_cannot_move_sideways():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    start = w._to_screen(0.0, 0.0)
    press(w, start.x(), start.y())
    press(w, start.x() + 40, start.y(), kind=QEvent.Type.MouseMove)
    assert w.points[0][0] == 0.0


def test_handles_cannot_be_dragged_past_their_neighbours():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    middle = w._to_screen(2.0, 0.0)
    press(w, middle.x(), middle.y())
    press(w, w._to_screen(20.0, 0.0).x(), middle.y(), kind=QEvent.Type.MouseMove)
    assert w.points[1][0] < w.points[2][0]


def test_double_click_adds_a_point_and_right_click_removes_it():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    target = w._to_screen(7.0, -1.0)
    press(w, target.x(), target.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 4 and len(committed) == 1
    added = w._to_screen(*w.points[2])
    press(w, added.x(), added.y(), button=Qt.MouseButton.RightButton)
    assert len(w.points) == 3 and len(committed) == 2


def test_a_read_only_widget_ignores_edits():
    w = ProfileWidget(Kind.LONG)
    w.resize(400, 200)
    w.set_profile([(0.0, 10.0), (30.0, 12.0)], editable=False)
    committed = []
    w.profileCommitted.connect(committed.append)
    point = w._to_screen(30.0, 12.0)
    press(w, point.x(), point.y())
    press(w, point.x(), point.y() - 30, kind=QEvent.Type.MouseMove)
    assert w.points[-1] == (30.0, 12.0) and committed == []


def test_the_long_profile_keeps_its_end_stations_fixed():
    w = widget_with([(0.0, 10.0), (15.0, 11.0), (30.0, 12.0)], kind=Kind.LONG)
    end = w._to_screen(30.0, 12.0)
    press(w, end.x(), end.y())
    press(w, end.x() - 60, end.y() - 10, kind=QEvent.Type.MouseMove)
    assert w.points[-1][0] == 30.0 and w.points[-1][1] > 12.0   # height moved, station did not
