"""Undo and redo from the panel: the buttons, Ctrl+Z where it belongs, and what the panel does after."""
import pytest
from qgis.core import QgsProject
from qgis.gui import QgsMapToolPan
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QKeySequence
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, spin_event_loop
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.gui.help_texts import UNDO_ADD
from terrain_scenarios.gui.main_dock import MainDock
from terrain_scenarios.gui.profile_dock import ProfileDock
from terrain_scenarios.gui.selection import Method


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def in_a_window(iface, dock):
    """The dock inside an active main window that, like QGIS, binds Ctrl+Z to its own undo."""
    window = iface.mainWindow()
    window.setCentralWidget(iface.mapCanvas())
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    qgis_undo = []
    action = QAction("QGIS undo", window)
    action.setShortcuts([QKeySequence(QKeySequence.StandardKey.Undo), QKeySequence(QKeySequence.StandardKey.Redo)])
    action.triggered.connect(lambda: qgis_undo.append(True))
    window.addAction(action)
    window.show()
    window.activateWindow()
    spin_event_loop(50)
    return window, qgis_undo


def press(widget, standard_key):
    widget.setFocus()
    spin_event_loop(10)
    QTest.keySequence(QApplication.focusWidget() or widget, QKeySequence(standard_key))
    spin_event_loop(10)


def test_the_undo_buttons_follow_the_history_and_say_what_they_will_do(tmp_path):
    _iface, c, dock = panel(tmp_path)
    assert not dock.undo_button.icon().isNull() and not dock.redo_button.icon().isNull()
    assert not dock.undo_button.isEnabled() and not dock.redo_button.isEnabled()
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dock.undo_button.isEnabled() and not dock.redo_button.isEnabled()
    assert UNDO_ADD.format("Raise path 1") in dock.undo_button.toolTip()
    dock.undo_button.click()
    assert c.features == ()
    assert dock.redo_button.isEnabled() and UNDO_ADD.format("Raise path 1") in dock.redo_button.toolTip()
    dock.redo_button.click()
    assert len(c.features) == 1


def test_ctrl_z_in_the_panel_undoes_terrain_scenarios_not_qgis(tmp_path):
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    press(dock.feature_view, QKeySequence.StandardKey.Undo)
    assert c.features == () and qgis_undo == []
    press(dock.feature_view, QKeySequence.StandardKey.Redo)
    assert len(c.features) == 1 and qgis_undo == []


def test_ctrl_z_in_the_profiles_panel_undoes_terrain_scenarios_too(tmp_path):
    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    window, qgis_undo = in_a_window(iface, dock)
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, profiles)
    spin_event_loop(20)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    press(profiles.widget(), QKeySequence.StandardKey.Undo)
    assert c.features == () and qgis_undo == []


def test_ctrl_z_on_the_map_undoes_terrain_scenarios_while_one_of_its_tools_is_active(tmp_path):
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert iface.mapCanvas().mapTool() is dock.draw_tool
    press(iface.mapCanvas(), QKeySequence.StandardKey.Undo)
    assert c.features == () and qgis_undo == []
    assert dock.draw_tool is not None                 # drawing a new feature carries on


def test_ctrl_z_on_the_map_is_left_to_qgis_with_any_other_tool(tmp_path):
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pan = QgsMapToolPan(iface.mapCanvas())
    iface.mapCanvas().setMapTool(pan)
    press(iface.mapCanvas(), QKeySequence.StandardKey.Undo)
    assert len(c.features) == 1 and qgis_undo == [True]


def test_undo_stops_a_vertex_edit_that_would_put_the_old_outline_back(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.set_geometry(dike.id, line_through(5, 24, 34, 28), UTM)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.undo_button.click()
    assert dock.edit_tool is None and not dock.edit_button.isChecked()


def test_undo_reloads_the_properties_page(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page
    dock.properties.amount.setValue(2.5)                   # through the page, as a user would
    assert c.find(dike.id).amount == 2.5
    dock.undo_button.click()
    assert c.find(dike.id).amount == 1.0
    assert dock.properties.amount.value() == 1.0           # not still showing the undone 2.5


def test_the_panel_header_does_not_make_the_panel_wider(tmp_path):
    """Seven buttons in a row forced a right-hand panel past 400 px; in a toolbar the ones that do
    not fit go behind », so the header is no longer what sets the panel's minimum width. New feature
    and Scenario ▾ now carry their own text (spec §5.1), so the floor is one such button wide rather
    than icon-only — still nowhere near 400 px."""
    _iface, _c, dock = panel(tmp_path)
    dock.show()
    assert dock.toolbar.minimumSizeHint().width() < 200
    assert dock.widget().minimumSizeHint().width() < 360


def test_ctrl_z_in_a_text_field_of_the_panel_is_left_to_that_field(tmp_path):
    """A spin box or line edit keeps Ctrl+Z for its own text, as everywhere in Qt: while there is
    typed text to undo, pressing it there must neither undo a Terrain Scenarios change nor reach
    QGIS's own undo."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    assert dock.stack.currentPanel() is dock.properties_page
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    spin.selectAll()
    QTest.keyClicks(spin, "2")                             # typed, not yet committed
    assert spin.lineEdit().text() == "2 m"
    press(spin, QKeySequence.StandardKey.Undo)
    assert len(c.features) == 1 and c.find(dike.id).amount == 1.0 and qgis_undo == []
    assert spin.lineEdit().text() == "1.00 m"              # the field undid its own text


def test_ctrl_z_after_stepping_a_setting_undoes_the_change(tmp_path):
    """The arrows commit each step, so the field has no text of its own to undo: Ctrl+Z there
    undoes the whole adjustment, as one step, like it does anywhere else in the panel. The page
    must actually be open: a real window is active here (`in_a_window`), and a widget outside it
    cannot genuinely take Qt's application focus, which these key events rely on."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    for _ in range(3):
        QTest.keyClick(spin, Qt.Key.Key_Up)
        spin_event_loop(5)
    assert c.find(dike.id).amount == pytest.approx(1.3)
    press(spin, QKeySequence.StandardKey.Undo)
    assert c.find(dike.id).amount == 1.0 and spin.value() == 1.0 and qgis_undo == []
    press(spin, QKeySequence.StandardKey.Redo)
    assert c.find(dike.id).amount == pytest.approx(1.3) and qgis_undo == []


def test_ctrl_z_after_a_field_undid_its_own_text_undoes_the_last_change(tmp_path):
    """Once the typed text is undone the field has only a redo left, so the next Ctrl+Z goes on to
    the feature change instead of doing nothing. The page must be open for the same reason as
    above: a widget outside the active window cannot take real application focus."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    QTest.keyClick(spin, Qt.Key.Key_Up)
    spin_event_loop(5)
    spin.selectAll()
    QTest.keyClicks(spin, "2")                             # typed, not yet committed
    press(spin, QKeySequence.StandardKey.Undo)             # the field undoes its own text
    assert c.find(dike.id).amount == pytest.approx(1.1)
    press(spin, QKeySequence.StandardKey.Undo)
    assert c.find(dike.id).amount == 1.0 and qgis_undo == []


def test_the_undo_button_leaves_a_value_the_user_is_still_typing(tmp_path):
    """The button takes no focus, so the field keeps it and its typed text. Undo changes the feature;
    the typed value is still there to confirm with Enter, not silently thrown away. The page must be
    open for the typed text to reach a genuinely focused field (see the two tests above)."""
    iface, c, dock = panel(tmp_path)
    _window, _qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    c.update_feature(dike.id, width=dike.width + 1.0)
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    spin.selectAll()
    QTest.keyClicks(spin, "2")                             # typed, not yet committed
    dock.undo_button.click()
    assert c.find(dike.id).width == dike.width                   # the width change was undone
    assert dock.properties.width.value() == pytest.approx(dike.width)
    assert spin.lineEdit().text() == "2 m"
    QTest.keyClick(spin, Qt.Key.Key_Return)
    assert c.find(dike.id).amount == 2.0


def test_ctrl_z_in_the_header_name_field_is_left_to_that_field_while_it_has_typed_text(tmp_path):
    """The header's `name_edit` gets the same `UndoKeys` filter as the spins (`spin_undo_keys`):
    while it has typed text of its own to undo, Ctrl+Z there is its own, not a rename commit of
    whatever the field held before — and, critically, not the app's undo stack either, or a stale
    Ctrl+Z here would silently undo the *previous* feature change instead of the field's own text.

    A plain `QLineEdit` already undoes its own typed text on Ctrl+Z with no filter installed at
    all, so the behavioural assertions below hold either way and cannot alone prove the filter is
    doing anything — `name_keys.applies(False)` is checked directly: that boolean is the one thing
    genuinely only the filter's own `_has_text_history` check decides (`spin_undo_keys[-1]` is
    `name_edit`'s, installed last, right after the four spins, in `MainDock.__init__`)."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    name = dock.properties.name_edit
    name_keys = dock.spin_undo_keys[-1]
    name.setFocus()
    spin_event_loop(10)
    name.selectAll()
    QTest.keyClicks(name, "Typed but not committed")
    assert name.text() == "Typed but not committed"
    assert name_keys.applies(False) is False    # the filter itself declines: not its shortcut to take
    steps = c.undo_stack.count()
    press(name, QKeySequence.StandardKey.Undo)
    assert name.text() == dike.name                       # the field undid its own text
    assert c.undo_stack.count() == steps and qgis_undo == []   # neither the app's undo stack …
    assert c.find(dike.id).name == dike.name                   # … nor a rename ever happened
    assert name_keys.applies(False) is True     # nothing left to undo natively: now it is the filter's


def test_ctrl_z_in_the_header_name_field_reaches_the_app_once_committed(tmp_path):
    """Once a rename is committed the field has no text of its own left to undo, so Ctrl+Z there
    goes on to undo the rename itself, through the app's own undo stack — exactly the spins'
    "after stepping a setting" behaviour, now also true for the name field."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    name = dock.properties.name_edit
    name.setFocus()
    spin_event_loop(10)
    name.selectAll()
    QTest.keyClicks(name, "Renamed")
    QTest.keyClick(name, Qt.Key.Key_Return)
    spin_event_loop(10)
    assert c.find(dike.id).name == "Renamed" and not name.isModified()
    press(name, QKeySequence.StandardKey.Undo)
    assert c.find(dike.id).name == dike.name and qgis_undo == []
