import pytest
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QKeyEvent, QMouseEvent

from terrain_scenarios.gui.profile_widget import NUDGE, NUDGE_FINE, Kind, ProfileWidget


def press(widget, x, y, button=Qt.MouseButton.LeftButton, kind=QEvent.Type.MouseButtonPress):
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent,
     QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent,
     QEvent.Type.MouseButtonDblClick: widget.mouseDoubleClickEvent}[kind](event)


def widget_with(points, kind=Kind.CROSS, size=(400, 200), **kw):
    w = ProfileWidget(kind)
    w.resize(*size)
    w.set_profile(points, **kw)
    return w


def key(widget, which, modifiers=Qt.KeyboardModifier.NoModifier, release=True):
    """Press and let go of a key, as a tap does; the press event is returned."""
    event = QKeyEvent(QEvent.Type.KeyPress, which, modifiers)
    widget.keyPressEvent(event)
    if release:
        widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, modifiers))
    return event


def hold(widget, which, repeats):
    """Hold a key down: one press, then auto-repeated press and release pairs, then the real release."""
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, which, Qt.KeyboardModifier.NoModifier))
    for _ in range(repeats):
        widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, Qt.KeyboardModifier.NoModifier, "", True))
        widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, which, Qt.KeyboardModifier.NoModifier, "", True))
    widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, Qt.KeyboardModifier.NoModifier))


def select(widget, x, z):
    """Click a handle without moving it, as the user does before nudging with the arrow keys."""
    point = widget._to_screen(x, z)
    press(widget, point.x(), point.y())
    press(widget, point.x(), point.y(), kind=QEvent.Type.MouseButtonRelease)


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


def test_the_arrow_keys_nudge_the_selected_handle_and_commit_when_let_go():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)

    ignored = key(w, Qt.Key.Key_Up)                     # nothing selected yet
    assert not ignored.isAccepted() and committed == []

    select(w, 12.0, -3.0)
    assert committed == []                              # a click that moves nothing commits nothing
    accepted = key(w, Qt.Key.Key_Up, release=False)
    assert accepted.isAccepted()
    assert w.points[2][1] == pytest.approx(-3.0 + NUDGE)
    assert len(during) == 1 and committed == []         # shown while the key is down…
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    assert len(committed) == 1 and committed[-1] == tuple(w.points)   # …committed when it is let go

    key(w, Qt.Key.Key_Down)
    assert w.points[2][1] == pytest.approx(-3.0)
    key(w, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert w.points[2][0] == pytest.approx(12.0 + NUDGE_FINE)   # Shift nudges finely
    key(w, Qt.Key.Key_Left)
    assert w.points[2][0] == pytest.approx(12.0 + NUDGE_FINE - NUDGE)
    assert len(committed) == 4


def test_holding_an_arrow_key_is_one_change_not_one_per_repeat():
    """Auto-repeat sends about thirty presses a second, and each commit is a recompute, a file write
    and an undo step."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    hold(w, Qt.Key.Key_Up, repeats=9)
    assert w.points[2][1] == pytest.approx(-3.0 + 10 * NUDGE)
    assert len(during) == 10 and len(committed) == 1 and committed[0] == tuple(w.points)


def test_a_nudge_is_committed_when_the_plot_loses_focus_before_the_key_is_let_go():
    from qgis.PyQt.QtGui import QFocusEvent
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    key(w, Qt.Key.Key_Down, release=False)
    w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert len(committed) == 1
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    assert len(committed) == 1                          # the late release commits nothing more


def test_a_nudge_the_plot_was_reloaded_under_is_not_committed():
    """An undo can reload or clear the plot while a key is held; the release must not commit points
    that belonged to the profile before."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    key(w, Qt.Key.Key_Up, release=False)
    w.set_profile([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    assert committed == []


def test_the_arrow_keys_are_ignored_in_a_read_only_plot_and_for_other_keys():
    w = widget_with([(0.0, 10.0), (15.0, 11.0), (30.0, 12.0)], kind=Kind.LONG)
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 15.0, 11.0)
    assert key(w, Qt.Key.Key_Delete).isAccepted() is False   # not a nudge key
    w.editable = False
    assert key(w, Qt.Key.Key_Up).isAccepted() is False
    assert w.points[1] == (15.0, 11.0) and committed == []


def test_a_nudge_cannot_push_a_handle_past_its_neighbour():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (2.05, -1.0)])
    select(w, 2.05, -1.0)
    key(w, Qt.Key.Key_Left)                         # NUDGE is 0.1: further left than the neighbour
    assert w.points[1][0] < w.points[2][0]


def test_a_plot_without_break_points_refuses_to_add_or_remove_them():
    """An area's break points are discarded by the engine (spec 5.4), so the plot must not
    pretend to take them."""
    points = [(0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)]
    w = widget_with(points, allow_breaks=False)
    committed = []
    w.profileCommitted.connect(committed.append)
    target = w._to_screen(5.0, 1.0)
    press(w, target.x(), target.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 4 and committed == []           # nothing added
    handle = w._to_screen(3.0, 0.5)
    press(w, handle.x(), handle.y(), button=Qt.MouseButton.RightButton)
    assert len(w.points) == 4 and committed == []           # nothing removed
    # the terminal slope is still draggable: only the break points are off limits
    start = w._to_screen(8.0, 2.0)
    press(w, start.x(), start.y())
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseMove)
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert len(committed) == 1 and w.points[3][1] > 2.0


def test_clearing_the_plot_mid_drag_ends_the_drag():
    """Ctrl+Z during a drag can remove the shown feature, which clears the plot under the mouse.
    The next mouse move and release happen inside Qt, where an IndexError would abort QGIS."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    start = w._to_screen(2.0, 0.0)
    press(w, start.x(), start.y())
    assert w._dragging == 1
    w.clear()
    assert w._dragging == -1 and w._before is None
    press(w, start.x() + 20, start.y() - 20, kind=QEvent.Type.MouseMove)
    press(w, start.x() + 20, start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert w.points == [] and committed == []


def whole(width=4.0, left=(), right=((12.0, -3.0),)):
    """A mirrored plot: left-side points (negative), the two crest edges, right-side points."""
    edge = width / 2.0
    points = [*left, (-edge, 0.0), (edge, 0.0), *right]
    return widget_with(points, mirrored=True)


def drag(widget, x, z, to_x, to_z):
    start, end = widget._to_screen(x, z), widget._to_screen(to_x, to_z)
    press(widget, start.x(), start.y())
    press(widget, end.x(), end.y(), kind=QEvent.Type.MouseMove)
    press(widget, end.x(), end.y(), kind=QEvent.Type.MouseButtonRelease)


def test_the_two_crest_edges_move_together():
    w = whole(left=((-12.0, -3.0),))
    drag(w, 2.0, 0.0, 3.0, 0.0)
    assert w.points[1][0] == pytest.approx(-w.points[2][0]) and w.points[2][0] == pytest.approx(3.0, abs=0.1)
    assert w.points[1][1] == w.points[2][1] == 0.0                # the crest stays level


def test_the_crest_stays_level_while_an_edge_is_dragged_or_nudged():
    w = whole(left=((-12.0, -3.0),))
    drag(w, 2.0, 0.0, 3.0, 1.5)                                   # dragged up and out
    assert w.points[1][1] == w.points[2][1] == 0.0
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, *w.points[2])
    key(w, Qt.Key.Key_Up)
    assert w.points[2][1] == 0.0 and committed == []               # nothing to commit


def test_no_handle_crosses_the_centre_line():
    w = whole(left=((-12.0, -3.0),))
    drag(w, -2.0, 0.0, 5.0, 0.0)                                  # the left edge dragged far to the right
    assert w.points[1][0] < 0.0 < w.points[2][0]
    assert w.points[2][0] <= 12.0


def test_with_symmetric_on_a_handle_takes_its_mirror_image_along():
    w = whole(left=((-12.0, -3.0),))
    w.symmetric = True
    drag(w, 12.0, -3.0, 14.0, -4.0)
    assert w.points[0][0] == pytest.approx(-w.points[3][0]) and w.points[0][1] == pytest.approx(w.points[3][1])
    w.symmetric = False
    drag(w, 14.0, w.points[3][1], 10.0, -2.0)
    assert w.points[0][0] != pytest.approx(-w.points[3][0])       # off: only the dragged side moves


def test_a_handle_without_a_mirror_image_moves_alone_even_when_symmetric():
    w = whole(left=((-12.0, -3.0),), right=((6.0, -1.0), (12.0, -3.0)))
    w.symmetric = True
    before = list(w.points)
    drag(w, 6.0, -1.0, 7.0, -1.5)
    assert w.points[:3] == before[:3]


def test_the_arrow_keys_move_both_crest_edges():
    w = whole(left=((-12.0, -3.0),))
    select(w, 2.0, 0.0)
    key(w, Qt.Key.Key_Right)
    assert w.points[2][0] == pytest.approx(2.0 + NUDGE) and w.points[1][0] == pytest.approx(-2.0 - NUDGE)


def test_the_crest_edges_cannot_be_removed_and_nothing_is_added_on_the_crest():
    w = whole(left=((-12.0, -3.0),))
    committed = []
    w.profileCommitted.connect(committed.append)
    edge = w._to_screen(2.0, 0.0)
    press(w, edge.x(), edge.y(), button=Qt.MouseButton.RightButton)
    crest = w._to_screen(0.5, 0.0)
    press(w, crest.x(), crest.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 4 and committed == []
    slope = w._to_screen(7.0, -1.5)
    press(w, slope.x(), slope.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 5 and len(committed) == 1              # a berm on a slope is fine


def test_a_reload_keeps_the_selected_handle_only_where_it_still_is():
    """A commit reloads the plot with the handle where the user left it, and the next arrow key must find
    it. An undo can reload a profile with as many points but another shape, where the same index is
    another handle."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)])
    select(w, 6.0, -1.0)
    key(w, Qt.Key.Key_Right)
    w.set_profile([(0.0, 0.0), (2.0, 0.0), (6.1, -1.0), (12.0, -3.0)])     # the commit's reload
    assert w.selected == 2
    w.set_profile([(0.0, 0.0), (2.0, 0.0), (3.0, -0.2), (12.0, -3.0)])     # an undo to another shape
    assert w.selected == -1
