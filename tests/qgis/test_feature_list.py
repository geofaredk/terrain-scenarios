from qgis.core import QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import QEvent, QModelIndex, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QAbstractItemView, QStyleOptionViewItem

from qgis_helpers import UTM, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.feature_list import (FLAGGED_ROLE, ID_ROLE, SUBTITLE_ROLE, FeatureListModel,
                                             FeatureListView, FeatureRowDelegate)


def test_feature_list_edits_go_through_the_controller(tmp_path):
    c = start_session(tmp_path)
    a, b, d = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20, 30))
    model = FeatureListModel(c)
    assert model.rowCount() == 3 and model.data(model.index(0)) == a.name
    model.setData(model.index(1), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert not c.feature(b.id).enabled
    model.setData(model.index(2), "Barrier", Qt.ItemDataRole.EditRole)
    assert c.feature(d.id).name == "Barrier"
    model.dropMimeData(model.mimeData([model.index(0)]), Qt.DropAction.MoveAction, 3, 0, QModelIndex())
    assert [f.id for f in c.features] == [b.id, d.id, a.id]
    assert [model.data(model.index(r), ID_ROLE) for r in range(3)] == [b.id, d.id, a.id]


def test_flagged_features_show_a_warning(tmp_path):
    c = start_session(tmp_path)
    far = QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(10, 10)])
    c.add_drawn(Tool.ADD, Mode.PATH, far, UTM)
    model = FeatureListModel(c)
    assert "outside the DEM" in model.data(model.index(0), Qt.ItemDataRole.ToolTipRole)
    assert model.data(model.index(0), FLAGGED_ROLE) is True                    # the delegate paints the warning
    delegate = FeatureRowDelegate()
    size = delegate.sizeHint(QStyleOptionViewItem(), model.index(0))
    assert size.height() > 0 and size.width() >= 0                            # does not raise, gives a real size


def test_a_row_says_what_the_feature_is_and_what_it_moves(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    model = FeatureListModel(c)
    subtitle = model.index(0).data(SUBTITLE_ROLE)
    assert subtitle.startswith("Raise path") and "fill" in subtitle and "m³" in subtitle
    assert "cut" not in subtitle                      # a raise tool only fills
    c.set_enabled(dike.id, False)                     # a feature that changes nothing says only what it is
    assert model.index(0).data(SUBTITLE_ROLE) == "Raise path"


def test_the_view_installs_the_row_delegate_on_its_own(tmp_path):
    """main_dock.py builds a FeatureListView with no delegate of its own — the view must install
    FeatureRowDelegate itself, or the production panel paints with Qt's stock delegate (no picture,
    no subtitle, no warning, no chevron — and DecorationRole no longer carries the warning icon
    either, so it would show nothing at all) and hit-tests the checkbox in the wrong place."""
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))
    assert isinstance(view.itemDelegate(), FeatureRowDelegate)


def test_clicking_a_row_opens_it_but_clicking_its_checkbox_only_toggles_it(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))    # no setItemDelegate here — exercised as main_dock.py builds it
    view.resize(300, 120)
    opened = []
    view.rowOpened.connect(opened.append)
    rect = view.visualRect(view.model().index(0))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())      # the row body
    assert opened == [dike.id]
    box = FeatureRowDelegate.checkbox_rect(rect)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=box.center())       # the checkbox
    assert opened == [dike.id] and not c.feature(dike.id).enabled


def test_pressing_space_over_the_current_row_toggles_it(tmp_path):
    """The stock delegate's Key_Space/Key_Select checkbox toggle has nothing to do with the mouse
    hit-test our editorEvent override disables, and must keep working."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))
    view.resize(300, 120)
    view.setCurrentIndex(view.model().index(0))
    assert c.feature(dike.id).enabled
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert not c.feature(dike.id).enabled


def test_double_clicking_a_row_starts_editing_and_the_release_does_not_reopen_it(tmp_path):
    """A genuine double click is delivered as press, release, press, doubleclick, release. The
    first release is an ordinary click and opens the row, same as any single click; it is the
    *second* release — the one landing once the row has already entered rename — that must not
    also emit rowOpened (it used to, misfiring the moment a rename starts)."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))
    view.resize(300, 120)
    opened = []
    view.rowOpened.connect(opened.append)
    rect = view.visualRect(view.model().index(0))
    pos = rect.center()

    def send(kind):
        event = QMouseEvent(kind, QPointF(pos), QPointF(pos), Qt.MouseButton.LeftButton,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        {QEvent.Type.MouseButtonPress: view.mousePressEvent,
         QEvent.Type.MouseButtonRelease: view.mouseReleaseEvent,
         QEvent.Type.MouseButtonDblClick: view.mouseDoubleClickEvent}[kind](event)

    send(QEvent.Type.MouseButtonPress)
    send(QEvent.Type.MouseButtonRelease)
    assert opened == [dike.id]                                          # the first click's release opens it
    send(QEvent.Type.MouseButtonPress)
    send(QEvent.Type.MouseButtonDblClick)
    assert view.state() == QAbstractItemView.State.EditingState
    send(QEvent.Type.MouseButtonRelease)                                # the release that completes the double click
    assert opened == [dike.id]                                          # must not have opened it a second time


def test_selection_survives_edits_and_list_changes(tmp_path):
    c = start_session(tmp_path)
    a, b = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20))
    view = FeatureListView(FeatureListModel(c))
    view.select_id(b.id)
    c.update_feature(b.id, amount=2.0)
    assert view.selected_id() == b.id
    c.delete_feature(a.id)
    assert view.selected_id() == b.id


def test_a_row_index_from_before_the_list_shrank_is_ignored(tmp_path):
    """Qt checks only that a row is not negative before handing an index to the model, so an index
    kept across a reset can point past the end of the list — inside a Qt call that must not raise."""
    c = start_session(tmp_path)
    a, b = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20))
    model = FeatureListModel(c)
    stale = model.index(1)
    c.delete_feature(b.id)
    assert model.data(stale) is None
    assert model.setData(stale, "Barrier", Qt.ItemDataRole.EditRole) is False
    assert c.feature(a.id).name != "Barrier"
    assert bytes(model.mimeData([model.index(0), stale]).data("application/x-terrain-sketch-feature-ids")) \
        == a.id.encode()
