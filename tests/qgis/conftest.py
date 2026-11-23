"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject, QgsSettings

from terrain_scenarios.gui import settings as plugin_settings
from terrain_scenarios.gui.controller import SketchController

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()

# Every controller listens to the one QgsProject. Without letting go after each test, the controllers of
# every earlier test would still answer the next test's project signals.
_controllers = []
_controller_init = SketchController.__init__


def _tracked_init(self, *args, **kwargs):
    _controller_init(self, *args, **kwargs)
    _controllers.append(self)


SketchController.__init__ = _tracked_init


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A real modal dialog in an offscreen run waits forever and hangs the whole suite. Every
    project clear below can legitimately ask to save a panel's unsaved work, so the defaults
    answer the way closing without saving would. A test that is about a prompt replaces the
    panel's own hook (`confirm_save`, `confirm`, `ask_save_path`…) and asserts on that."""
    from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

    def question(_parent, _title, _text, buttons=QMessageBox.StandardButton.Yes, *_rest):
        for answer in (QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.No,
                       QMessageBox.StandardButton.Cancel):
            if buttons & answer:
                return answer
        return QMessageBox.StandardButton.NoButton

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Cancel)   # no button clicked
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))


@pytest.fixture(autouse=True)
def clean_project(no_modal_dialogs):
    QgsProject.instance().clear()
    _clear_plugin_settings()
    yield
    QgsProject.instance().clear()
    while _controllers:
        _controllers.pop().shutdown()
    _clear_plugin_settings()


def _clear_plugin_settings() -> None:
    """Drop everything under the plugin's settings group so tests cannot inherit each other's."""
    settings = QgsSettings()
    settings.beginGroup(plugin_settings.GROUP)
    settings.remove("")
    settings.endGroup()
