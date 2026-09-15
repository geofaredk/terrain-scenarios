"""The "Terrain Sketch" layer group: modified DEM, change, hillshade and sketch outlines."""
from __future__ import annotations

from qgis.core import (Qgis, QgsColorRampShader, QgsDataProvider, QgsFeature, QgsFillSymbol, QgsHillshadeRenderer,
                       QgsPalLayerSettings, QgsRasterLayer, QgsRasterShader, QgsSingleBandPseudoColorRenderer,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)
from qgis.PyQt import sip
from qgis.PyQt.QtGui import QColor

GROUP_NAME = "Terrain Sketch"
CHANGE_LIMIT = 2.0  # metres of cut or fill shown at full colour


class SketchLayers:
    """Creates the session's layers in a group at the top of the layer tree."""

    def __init__(self, project, dem_layer, working_path: str, change_path: str):
        self.project = project
        self.outlines = QgsVectorLayer("Polygon?field=name:string&field=tool:string", "Sketch outlines", "memory")
        self.outlines.setCrs(dem_layer.crs())
        self.change = QgsRasterLayer(change_path, "Change (new − original)")
        self.hillshade = QgsRasterLayer(working_path, "Hillshade")
        self.working = QgsRasterLayer(working_path, "Modified DEM")
        self.working.setRenderer(dem_layer.renderer().clone())
        self.change.setRenderer(_change_renderer(self.change))
        hillshade = QgsHillshadeRenderer(self.hillshade.dataProvider(), 1, 315.0, 45.0)
        hillshade.setOpacity(0.5)
        self.hillshade.setRenderer(hillshade)
        _style_outlines(self.outlines)
        self.layer_ids = [layer.id() for layer in (self.outlines, self.change, self.hillshade, self.working)]
        self.group = project.layerTreeRoot().insertGroup(0, GROUP_NAME)
        try:
            for layer in (self.outlines, self.change, self.hillshade, self.working):
                project.addMapLayer(layer, False)
                self.group.addLayer(layer)
            self.group.findLayer(self.hillshade.id()).setItemVisibilityChecked(False)
        except Exception:
            self.remove()  # a half-built group would stay in the user's layer tree for good
            raise
        self.outlines_id, self.change_id, self.hillshade_id, self.working_id = self.layer_ids

    def refresh(self) -> None:
        """Re-read the working and change files after they were written (skips removed layers)."""
        for layer_id in (self.change_id, self.hillshade_id, self.working_id):
            layer = self.project.mapLayer(layer_id)
            if layer is not None:
                layer.dataProvider().reloadData()
                layer.triggerRepaint()

    def repoint(self, working_path: str, change_path: str) -> None:
        """Read the working and change rasters from the files they were moved to, keeping each layer's style
        (and so a 3D terrain on the Modified DEM layer). Layers the user removed are skipped."""
        options = QgsDataProvider.ProviderOptions()
        for layer_id, path in ((self.change_id, change_path), (self.hillshade_id, working_path),
                               (self.working_id, working_path)):
            layer = self.project.mapLayer(layer_id)
            if layer is not None:
                layer.setDataSource(path, layer.name(), "gdal", options)

    def set_outlines(self, items) -> None:
        """Replace the outlines with `items`: (name, tool label, QgsGeometry in the DEM CRS).
        Does nothing once the user removed the outline layer."""
        layer = self.project.mapLayer(self.outlines_id)
        if layer is None:
            return
        provider = layer.dataProvider()
        provider.truncate()
        features = []
        for name, tool, geometry in items:
            feature = QgsFeature(layer.fields())
            feature.setAttributes([name, tool])
            feature.setGeometry(geometry)
            features.append(feature)
        provider.addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()

    def set_hillshade_visible(self, visible: bool) -> None:
        node = None if sip.isdeleted(self.group) else self.group.findLayer(self.hillshade_id)
        if node is not None:
            node.setItemVisibilityChecked(visible)

    def remove(self) -> None:
        """Remove the group and whatever of its layers is still in the project."""
        self.project.removeMapLayers([i for i in self.layer_ids if self.project.mapLayer(i) is not None])
        if not sip.isdeleted(self.group) and self.group.parent() is not None:
            self.group.parent().removeChildNode(self.group)


def _change_renderer(layer: QgsRasterLayer) -> QgsSingleBandPseudoColorRenderer:
    ramp = QgsColorRampShader(-CHANGE_LIMIT, CHANGE_LIMIT, None, Qgis.ShaderInterpolationMethod.Linear,
                              Qgis.ShaderClassificationMethod.Continuous)
    ramp.setColorRampItemList([
        QgsColorRampShader.ColorRampItem(-CHANGE_LIMIT, QColor(33, 102, 172), f"−{CHANGE_LIMIT:g} m (cut)"),
        QgsColorRampShader.ColorRampItem(-0.01, QColor(146, 197, 222, 160), ""),
        QgsColorRampShader.ColorRampItem(0.0, QColor(255, 255, 255, 0), "no change"),
        QgsColorRampShader.ColorRampItem(0.01, QColor(253, 174, 97, 160), ""),
        QgsColorRampShader.ColorRampItem(CHANGE_LIMIT, QColor(215, 48, 39), f"+{CHANGE_LIMIT:g} m (fill)"),
    ])
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(ramp)
    return QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)


def _style_outlines(layer: QgsVectorLayer) -> None:
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"color": "0,0,0,0", "outline_color": "35,35,35,255", "outline_width": "0.5", "outline_style": "dash"}))
    labels = QgsPalLayerSettings()
    labels.fieldName = "name"
    layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
    layer.setLabelsEnabled(True)
    layer.setReadOnly(True)
