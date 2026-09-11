"""Terrain Sketch QGIS plugin."""


def classFactory(iface):  # noqa: N802 — name required by QGIS
    from .plugin import TerrainSketchPlugin

    return TerrainSketchPlugin(iface)
