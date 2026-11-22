"""Terrain Scenarios QGIS plugin."""


def classFactory(iface):  # noqa: N802 — name required by QGIS
    from .plugin import TerrainScenariosPlugin

    return TerrainScenariosPlugin(iface)
