"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject, QgsSettings

from terrain_sketch.gui import settings as plugin_settings

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()


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
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))


@pytest.fixture(autouse=True)
def clean_project(no_modal_dialogs):
    QgsProject.instance().clear()
    _clear_plugin_settings()
    yield
    QgsProject.instance().clear()
    _clear_plugin_settings()


def _clear_plugin_settings() -> None:
    """Drop everything under the plugin's settings group so tests cannot inherit each other's."""
    settings = QgsSettings()
    settings.beginGroup(plugin_settings.GROUP)
    settings.remove("")
    settings.endGroup()
