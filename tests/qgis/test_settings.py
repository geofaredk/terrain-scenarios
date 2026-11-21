from qgis.core import QgsSettings
from qgis.PyQt.QtWidgets import QApplication, QPushButton, QSplitter

from terrain_sketch.gui import settings


def test_settings_round_trip_under_the_plugin_group():
    settings.save("probe/value", "kept")
    assert settings.load("probe/value") == "kept"
    stored = QgsSettings()
    stored.beginGroup(settings.GROUP)
    assert stored.value("probe/value") == "kept"     # written where the spec says, not at the root
    stored.endGroup()


def test_a_missing_setting_falls_back_to_the_default():
    assert settings.load("never/written", "fallback") == "fallback"


def test_a_stale_list_splitter_setting_is_left_alone():
    """spec §10: list_splitter is retired along with the splitter it described. A value left over
    in an existing profile from before the redesign is simply ignored — nothing reads it any more,
    and the panel does not even have a splitter to restore it into."""
    from qgis.core import QgsProject

    from qgis_helpers import fake_iface
    from terrain_sketch.gui.controller import SketchController
    from terrain_sketch.gui.main_dock import MainDock

    settings.save("list_splitter/state", b"an old value from before the redesign")
    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    assert not hasattr(dock, "list_splitter")
    assert settings.load("list_splitter/state") == b"an old value from before the redesign"


def test_splitter_state_is_stored_and_handed_back_to_the_widget():
    first = QSplitter()
    first.addWidget(QPushButton())
    first.addWidget(QPushButton())
    first.setSizes([300, 100])       # a split the user could have dragged, so there is something
                                     # to recognise at the other end besides a True return value
    settings.save_state("probe_splitter", first)
    # what was stored is exactly what the widget produced — every QWidget also has saveGeometry,
    # so a module that probed for a method would quietly store the wrong one for a splitter
    assert bytes(settings.load("probe_splitter/state")) == bytes(first.saveState())
    second = QSplitter()
    second.addWidget(QPushButton())
    second.addWidget(QPushButton())
    assert settings.restore_state("probe_splitter", second)
    assert second.sizes() == first.sizes()   # restored, not merely reported as restored


def test_a_splitter_is_stored_by_state_not_by_geometry():
    splitter = QSplitter()
    splitter.addWidget(QPushButton())
    splitter.addWidget(QPushButton())
    settings.save_state("probe_kind", splitter)
    assert settings.load("probe_kind/state") is not None
    assert settings.load("probe_kind/geometry") is None


def test_restoring_something_never_saved_reports_failure_rather_than_raising():
    assert not settings.restore_state("probe_absent", QSplitter())


def test_a_deleted_widget_does_not_raise():
    """These run from Qt callbacks: a PyQt wrapper whose C++ object is gone raises RuntimeError,
    and an exception in a callback aborts the interpreter."""
    from qgis.PyQt import sip
    splitter = QSplitter()
    splitter.addWidget(QPushButton())
    splitter.addWidget(QPushButton())
    settings.save_state("probe_dead", splitter)
    sip.delete(splitter)
    settings.save_state("probe_dead", splitter)              # must not raise
    assert not settings.restore_state("probe_dead", splitter)


def test_a_corrupt_stored_value_does_not_raise():
    settings.save("probe_bad/state", "not a byte array")
    assert not settings.restore_state("probe_bad", QSplitter())


def test_a_collapsed_group_is_remembered_under_the_plugin_group(tmp_path):
    """QgsCollapsibleGroupBox saves under its own key otherwise, which the plugin cannot clear and
    which leaked a collapsed About box from one test into the next."""
    from qgis_helpers import start_session
    from terrain_sketch.gui.properties_page import PropertiesPage
    stored = QgsSettings()
    for key in stored.allKeys():
        if key.startswith("QgsCollapsibleGroupBox/") and "TerrainSketch" in key:
            stored.remove(key)                     # left in the shared test profile by earlier versions
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    page.show()                                    # a box that is not shown does not report a collapse
    assert page.about.isCollapsed()                # collapsed by default now (the summary is in the header)
    page.about.setCollapsed(False)
    assert settings.load("about_group/collapsed", True, bool) is False
    assert not [key for key in QgsSettings().allKeys() if key.startswith("QgsCollapsibleGroupBox/")
                and "TerrainSketch" in key]
    again = PropertiesPage(c)
    again.show()                                   # a box that saved its own state would load it here
    assert not again.about.isCollapsed() and again.volumes.isCollapsed()    # About remembers being opened


def test_volumes_start_collapsed_and_an_opened_group_stays_open(tmp_path):
    from qgis_helpers import start_session
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    page.show()
    assert page.volumes.isCollapsed() and page.about.isCollapsed()   # both start collapsed (spec §7 items 5-7)
    page.volumes.setCollapsed(False)
    again = PropertiesPage(c)
    again.show()
    assert not again.volumes.isCollapsed()


def test_advanced_starts_collapsed_and_remembers_being_opened(tmp_path):
    from qgis_helpers import start_session
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    page.show()
    assert page.advanced.isCollapsed()              # collapsed by default (spec §7 item 5)
    page.advanced.setCollapsed(False)
    assert settings.load("advanced_group/collapsed", True, bool) is False
    again = PropertiesPage(c)
    again.show()
    assert not again.advanced.isCollapsed()


def window_with(dock, area):
    from qgis.PyQt.QtWidgets import QMainWindow, QTextEdit
    window = QMainWindow()
    window.setCentralWidget(QTextEdit())
    window.resize(1000, 700)
    window.addDockWidget(area, dock)
    window.show()
    return window


def test_a_docked_panel_comes_back_in_its_area_at_its_width():
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QDockWidget, QTextEdit
    first = QDockWidget("Terrain Sketch")
    first.setWidget(QTextEdit())
    window = window_with(first, Qt.DockWidgetArea.LeftDockWidgetArea)
    window.resizeDocks([first], [340], Qt.Orientation.Horizontal)
    QApplication.processEvents()
    settings.save_dock("probe_dock", first, window)

    second = QDockWidget("Terrain Sketch")
    second.setWidget(QTextEdit())
    area = settings.dock_area("probe_dock", Qt.DockWidgetArea.RightDockWidgetArea)
    assert area == Qt.DockWidgetArea.LeftDockWidgetArea
    other = window_with(second, area)
    settings.restore_dock("probe_dock", second, other)
    QApplication.processEvents()
    assert abs(second.width() - first.width()) <= 2


def test_a_floating_panel_comes_back_floating_where_it_was():
    from qgis.PyQt.QtCore import QRect, Qt
    from qgis.PyQt.QtWidgets import QDockWidget, QTextEdit
    first = QDockWidget("Profiles")
    first.setWidget(QTextEdit())
    window = window_with(first, Qt.DockWidgetArea.BottomDockWidgetArea)
    first.setFloating(True)
    first.setGeometry(QRect(120, 140, 500, 260))
    QApplication.processEvents()
    settings.save_dock("probe_float", first, window)

    second = QDockWidget("Profiles")
    second.setWidget(QTextEdit())
    other = window_with(second, settings.dock_area("probe_float", Qt.DockWidgetArea.BottomDockWidgetArea))
    settings.restore_dock("probe_float", second, other)
    QApplication.processEvents()
    assert second.isFloating() and second.size() == first.size()


def test_a_panel_being_removed_or_never_placed_keeps_what_was_stored():
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QDockWidget, QMainWindow
    area = Qt.DockWidgetArea
    settings.save("probe_kept/area", int(area.TopDockWidgetArea.value))
    settings.save_dock("probe_kept", QDockWidget(), QMainWindow())      # in no area of that window
    assert settings.dock_area("probe_kept", area.RightDockWidgetArea) == area.TopDockWidgetArea
    settings.save("probe_junk/area", "somewhere")
    assert settings.dock_area("probe_junk", area.RightDockWidgetArea) == area.RightDockWidgetArea
    settings.save("probe_none/area", 0)                                 # NoDockWidgetArea
    assert settings.dock_area("probe_none", area.BottomDockWidgetArea) == area.BottomDockWidgetArea
