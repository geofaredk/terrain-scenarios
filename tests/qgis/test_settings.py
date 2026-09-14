from qgis.core import QgsSettings
from qgis.PyQt.QtWidgets import QPushButton, QSplitter

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


def test_splitter_state_is_stored_and_handed_back_to_the_widget():
    first = QSplitter()
    first.addWidget(QPushButton())
    first.addWidget(QPushButton())
    settings.save_state("probe_splitter", first)
    # what was stored is exactly what the widget produced — every QWidget also has saveGeometry,
    # so a module that probed for a method would quietly store the wrong one for a splitter
    assert bytes(settings.load("probe_splitter/state")) == bytes(first.saveState())
    second = QSplitter()
    second.addWidget(QPushButton())
    second.addWidget(QPushButton())
    assert settings.restore_state("probe_splitter", second)


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
