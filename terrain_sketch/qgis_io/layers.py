"""The "Terrain Sketch" layer group: modified DEM, change and sketch outlines."""
from __future__ import annotations

from qgis.core import (Qgis, QgsCategorizedSymbolRenderer, QgsColorRampShader, QgsDataProvider, QgsExpression,
                       QgsFeature, QgsFeatureRequest, QgsPalLayerSettings, QgsRasterLayer, QgsRasterShader,
                       QgsRenderContext, QgsRendererCategory, QgsSingleBandPseudoColorRenderer, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling)
from qgis.PyQt import sip
from qgis.PyQt.QtGui import QColor

from .symbols import default_symbol, from_xml, style_of, to_xml

GROUP_NAME = "Terrain Sketch"
FID_FIELD = "fid"
CHANGE_LIMIT = 2.0  # metres of cut or fill shown at full colour


class SketchLayers:
    """Creates the session's layers in a group at the top of the layer tree."""

    def __init__(self, project, dem_layer, working_path: str, change_path: str):
        self.project = project
        self.outlines = QgsVectorLayer(f"Polygon?field={FID_FIELD}:string&field=name:string&field=tool:string",
                                       "Sketch outlines", "memory")
        self.outlines.setCrs(dem_layer.crs())
        self.change = QgsRasterLayer(change_path, "Change (new − original)")
        self.working = QgsRasterLayer(working_path, "Modified DEM")
        self.working.setRenderer(dem_layer.renderer().clone())
        self.change.setRenderer(_change_renderer(self.change))
        self.outlines.setRenderer(_feature_renderer([]))
        _style_outlines(self.outlines)
        self.layer_ids = [layer.id() for layer in (self.outlines, self.change, self.working)]
        self.group = project.layerTreeRoot().insertGroup(0, GROUP_NAME)
        try:
            for layer in (self.outlines, self.change, self.working):
                project.addMapLayer(layer, False)
                self.group.addLayer(layer)
        except Exception:
            self.remove()  # a half-built group would stay in the user's layer tree for good
            raise
        self.outlines_id, self.change_id, self.working_id = self.layer_ids

    def refresh(self) -> None:
        """Re-read the working and change files after they were written (skips removed layers)."""
        for layer_id in (self.change_id, self.working_id):
            layer = self.project.mapLayer(layer_id)
            if layer is not None:
                layer.dataProvider().reloadData()
                layer.triggerRepaint()

    def repoint(self, working_path: str, change_path: str) -> None:
        """Read the working and change rasters from the files they were moved to, keeping each layer's style
        (and so a 3D terrain on the Modified DEM layer). Layers the user removed are skipped."""
        options = QgsDataProvider.ProviderOptions()
        for layer_id, path in ((self.change_id, change_path), (self.working_id, working_path)):
            layer = self.project.mapLayer(layer_id)
            if layer is not None:
                layer.setDataSource(path, layer.name(), "gdal", options)

    def set_outlines(self, items) -> None:
        """Replace the outlines with `items`: (feature id, name, tool label, QgsGeometry in the DEM CRS).
        Does nothing once the user removed the outline layer."""
        layer = self.project.mapLayer(self.outlines_id)
        if layer is None:
            return
        provider = layer.dataProvider()
        provider.truncate()
        features = []
        for fid, name, tool, geometry in items:
            feature = QgsFeature(layer.fields())
            feature.setAttributes([fid, name, tool])
            feature.setGeometry(geometry)
            features.append(feature)
        provider.addFeatures(features)
        layer.updateExtents()
        layer.triggerRepaint()

    def is_managed(self) -> bool:
        """Whether the outline layer still draws with the plugin's per-feature renderer. Once the user picks
        another renderer, the plugin leaves it alone."""
        layer = self.project.mapLayer(self.outlines_id)
        if layer is None:
            return False
        renderer = layer.renderer()
        return isinstance(renderer, QgsCategorizedSymbolRenderer) and renderer.classAttribute() == FID_FIELD

    def apply_styles(self, entries) -> None:
        """Bring the per-feature renderer in line with `entries`: (feature id, name, style) for the enabled
        features, in list order. The renderer is edited in place, touching only categories that differ, so
        renderer settings and each category's checkbox last. A category for empty or no value (the user's
        "all other values") is kept. Does nothing unless the layer is managed."""
        if not self.is_managed():
            return
        layer = self.project.mapLayer(self.outlines_id)
        renderer = layer.renderer()
        fids = [fid for fid, _name, _style in entries]
        cats = renderer.categories()  # kept alive while its symbols are used
        for index in reversed(range(len(cats))):
            value = cats[index].value()
            if value not in fids and value not in ("", None):
                renderer.deleteCategory(index)
        for position, (fid, name, style) in enumerate(entries):
            symbol = from_xml(style) or default_symbol()
            index = renderer.categoryIndexForValue(fid)
            if index < 0:
                renderer.addCategory(QgsRendererCategory(fid, symbol, name))
                index = len(renderer.categories()) - 1
            else:
                cats = renderer.categories()
                if cats[index].label() != name:
                    renderer.updateCategoryLabel(index, name)
                if to_xml(cats[index].symbol()) != to_xml(symbol):
                    renderer.updateCategorySymbol(index, symbol)
            if index != position:
                renderer.moveCategory(index, position)
        layer.triggerRepaint()
        layer.emitStyleChanged()  # the in-place edits above tell the legend nothing on their own

    def read_styles(self) -> dict:
        """{feature id: (category label, style)} for every category with a value; {} unless managed."""
        if not self.is_managed():
            return {}
        cats = self.project.mapLayer(self.outlines_id).renderer().categories()
        return {c.value(): (c.label(), style_of(c.symbol())) for c in cats if c.value() not in ("", None)}

    def use_feature_styles(self, entries) -> None:
        """Put a new per-feature renderer on the outline layer, built from `entries` as in `apply_styles`."""
        layer = self.project.mapLayer(self.outlines_id)
        if layer is None:
            return
        layer.setRenderer(_feature_renderer(entries))
        layer.triggerRepaint()

    def drawn_symbol(self, fid: str):
        """The symbol the outline layer's current renderer draws for feature `fid`, whatever the renderer;
        None when the layer is gone, the feature is not on it, or nothing is drawn for it."""
        layer = self.project.mapLayer(self.outlines_id)
        if layer is None:
            return None
        request = QgsFeatureRequest().setFilterExpression(
            f"{QgsExpression.quotedColumnRef(FID_FIELD)} = {QgsExpression.quotedValue(fid)}")
        feature = next(layer.getFeatures(request), None)
        if feature is None:
            return None
        renderer = layer.renderer().clone()  # started on its own: the layer's renderer may be drawing
        context = QgsRenderContext()
        renderer.startRender(context, layer.fields())  # originalSymbolForFeature crashes on an unstarted one
        try:
            symbol = renderer.originalSymbolForFeature(feature, context)
            return symbol.clone() if symbol is not None else None
        finally:
            renderer.stopRender(context)

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


def _feature_renderer(entries) -> QgsCategorizedSymbolRenderer:
    """A Categorized renderer on the feature id with one category per (feature id, name, style)."""
    renderer = QgsCategorizedSymbolRenderer(FID_FIELD, [
        QgsRendererCategory(fid, from_xml(style) or default_symbol(), name) for fid, name, style in entries])
    renderer.setSourceSymbol(default_symbol())
    return renderer


def _style_outlines(layer: QgsVectorLayer) -> None:
    labels = QgsPalLayerSettings()
    labels.fieldName = "name"
    layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
    layer.setLabelsEnabled(True)
    layer.setReadOnly(True)
