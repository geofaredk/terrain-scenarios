"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject, QgsSettings

from terrain_sketch.gui import settings as plugin_settings

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()


@pytest.fixture(autouse=True)
def clean_project():
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
