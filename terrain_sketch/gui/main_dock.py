"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

import os
import traceback

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsMessageLog,
                       QgsProject, QgsRasterLayer)
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.convert import from_wkb
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .controller import LOG_TAG
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (DEM_NOT_READABLE, EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED,
                         EXPORT_REPLACE, REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_NOT_APPLIED,
                         SCENARIO_NOT_APPLIED_ON_ITS_DEM, SCENARIO_OPENED, SCENARIO_OTHER_DEM, SCENARIO_REPLACE,
                         SCENARIO_SAVED, SECTION_LINE_HINT, SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING,
                         UNSAVED_CHANGES, VIEW_3D_NOT_OPENED, VIEW_3D_TIP)
from .map_tools.base import SketchTool
from .map_tools.brush import BrushTool
from .map_tools.draw_line import DrawLineTool
from .map_tools.draw_polygon import DrawPolygonTool
from .map_tools.freehand import FreehandTool
from .map_tools.vertex_edit import VertexEditTool
from .overlay import PreviewOverlay
from .properties_page import PropertiesPage
from .selection import BRUSH_EXTEND_HINT, EDIT_HINT, EDIT_ICON, METHOD_HINTS, Method
from .tool_gallery import ToolGallery
from .undo import UndoKeys

PAGE_START, PAGE_GALLERY, PAGE_PROPERTIES = range(3)


def _file_button(icon: str, text: str, tip: str) -> QToolButton:
    """An icon-only, auto-raised button like those in QGIS's own dock toolbars. The text is kept
    for screen readers and heads the tooltip, so the icon is never the only way to tell them apart."""
    button = QToolButton()
    button.setIcon(QgsApplication.getThemeIcon(icon))
    button.setText(text)
    button.setToolTip(f"{text}\n{tip}")
    button.setAutoRaise(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    return button


def _action_button(action) -> QToolButton:
    """An icon-only, auto-raised button for `action`: it follows the action's enabled state and
    text, so its tooltip always says what will happen ("Undo Add Raise path 1")."""
    button = QToolButton()
    button.setDefaultAction(action)
    button.setAutoRaise(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    return button


def _has_text_history(spin, redo: bool) -> bool:
    edit = spin.lineEdit()
    return edit.isRedoAvailable() if redo else edit.isUndoAvailable()


def _same_source(source: str, path: str) -> bool:
    """Whether a layer reads the file at `path` (a raster layer's source is its file path)."""
    return os.path.normcase(os.path.realpath(source)) == os.path.normcase(os.path.realpath(path))


class MainDock(QgsDockWidget):
    def __init__(self, iface, controller, profiles=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Terrain Sketch"))
        self.setObjectName("TerrainSketchDock")
        self.iface = iface
        self.controller = controller
        self.profiles = profiles          # the bottom profile dock, if the plugin made one
        self.overlay = PreviewOverlay(iface.mapCanvas())
        self._overlay_transform_failed = False
        self.draw_tool = None
        self._previous_tool = None
        self.confirm = self._confirm_dialog  # replaceable in tests
        self.ask_export_path = self._export_dialog  # replaceable in tests
        self.ask_save_path = self._save_dialog
        self.ask_open_path = self._open_dialog
        self.confirm_save = self._save_question
        self.choose_dem = self._dem_choice_dialog
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self._brush_extends = False       # set with _brush_fid, but kept when that feature goes
        self._section_fid = None          # the area whose section line is being drawn
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)
        self.section_band = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)   # an area's section line
        self.section_band.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.section_band.setWidth(QgsMapToolEdit.digitizingStrokeWidth())
        self.section_band.setLineStyle(Qt.PenStyle.DashLine)

        body = QWidget()
        layout = QVBoxLayout(body)
        dem_row = QHBoxLayout()
        dem_row.addWidget(QLabel(self.tr("DEM")))
        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(Qgis.LayerFilter.RasterLayer)
        dem_row.addWidget(self.dem_combo, 1)
        self.start_button = QPushButton(self.tr("Start"))
        self.start_button.setToolTip(self.tr("Start sketching on this DEM. The DEM itself is never changed."))
        dem_row.addWidget(self.start_button)
        self.hillshade_box = QCheckBox(self.tr("Hillshade"))
        dem_row.addWidget(self.hillshade_box)
        layout.addLayout(dem_row)

        # A toolbar, like QGIS's own panels: when the panel is narrower than its buttons, the ones
        # that do not fit move behind the » button instead of forcing the whole panel wider.
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(iface.iconSize(True))
        self.new_scenario_button = _file_button(
            "/mActionFileNew.svg", self.tr("New scenario"),
            self.tr("Start again with no features. The DEM stays as it is."))
        self.open_scenario_button = _file_button(
            "/mActionFileOpen.svg", self.tr("Open scenario…"),
            self.tr("Open a saved scenario (.gpkg) onto the DEM you started on."))
        self.save_scenario_button = _file_button(
            "/mActionFileSave.svg", self.tr("Save scenario"),
            self.tr("Save the features to a scenario file you can open again later."))
        self.save_as_scenario_button = _file_button(
            "/mActionFileSaveAs.svg", self.tr("Save scenario as…"),
            self.tr("Save the features to a new scenario file, leaving the current one as it is."))
        self.scenario_buttons = (self.new_scenario_button, self.open_scenario_button,
                                 self.save_scenario_button, self.save_as_scenario_button)
        for button in self.scenario_buttons:
            self.toolbar.addWidget(button)
        self.undo_action = controller.undo_stack.createUndoAction(self, self.tr("Undo"))
        self.undo_action.setIcon(QgsApplication.getThemeIcon("/mActionUndo.svg"))
        self.redo_action = controller.undo_stack.createRedoAction(self, self.tr("Redo"))
        self.redo_action.setIcon(QgsApplication.getThemeIcon("/mActionRedo.svg"))
        self.undo_button = _action_button(self.undo_action)
        self.redo_button = _action_button(self.redo_action)
        self.toolbar.addSeparator()
        self.toolbar.addWidget(self.undo_button)
        self.toolbar.addWidget(self.redo_button)
        self.toolbar.addSeparator()
        self.export_button = _file_button(
            "/mActionSharingExport.svg", self.tr("Export DEM…"),
            self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
        self.toolbar.addWidget(self.export_button)
        self.view_3d_button = _file_button("/3d.svg", self.tr("3D view"), VIEW_3D_TIP)
        self.toolbar.addWidget(self.view_3d_button)
        layout.addWidget(self.toolbar)

        self.model = FeatureListModel(controller, self)
        self.feature_view = FeatureListView(self.model)
        layout.addWidget(self.feature_view, 1)
        list_row = QHBoxLayout()
        self.new_button = QPushButton(QgsApplication.getThemeIcon("/mActionAdd.svg"), self.tr("New feature"))
        self.delete_button = QPushButton(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"))
        self.edit_button = QPushButton(QgsApplication.getThemeIcon(EDIT_ICON), self.tr("Edit shape"))
        self.edit_button.setCheckable(True)
        self.edit_button.setToolTip(self.tr("Move, add or remove the points of the selected feature."))
        list_row.addWidget(self.new_button)
        list_row.addWidget(self.delete_button)
        list_row.addWidget(self.edit_button)
        list_row.addStretch(1)
        layout.addLayout(list_row)

        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.hide()
        layout.addWidget(self.hint)

        self.pages = QStackedWidget()
        start_label = QLabel(self.tr("Pick a DEM above and press Start. Terrain Sketch works on a copy; your DEM "
                                     "is never changed."))
        start_label.setWordWrap(True)
        self.gallery = ToolGallery()
        self.properties = PropertiesPage(controller)
        for page in (start_label, self.gallery, self.properties):
            self.pages.addWidget(page)
        layout.addWidget(self.pages, 2)
        self.setWidget(body)

        self.start_button.clicked.connect(self._start)
        self.export_button.clicked.connect(self._export)
        self.view_3d_button.clicked.connect(self._open_3d_view)
        self.new_scenario_button.clicked.connect(self._new_scenario)
        self.open_scenario_button.clicked.connect(self._open_scenario)
        self.save_scenario_button.clicked.connect(lambda: self._save_scenario())
        self.save_as_scenario_button.clicked.connect(lambda: self._save_scenario(save_as=True))
        self.hillshade_box.toggled.connect(controller.set_hillshade_visible)
        self.new_button.clicked.connect(self._new_feature)
        self.delete_button.clicked.connect(self._delete_selected)
        self.feature_view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.feature_view.customContextMenuRequested.connect(self._context_menu)
        self.gallery.drawRequested.connect(self._begin_drawing)
        self.gallery.layerRequested.connect(self._use_layer)
        self.edit_button.toggled.connect(self._toggle_edit)
        self.iface.mapCanvas().mapToolSet.connect(self._map_tool_set)
        self.iface.mapCanvas().destinationCrsChanged.connect(self._update_radius_units)
        self.iface.mapCanvas().destinationCrsChanged.connect(self._update_overlay_transform)
        self.iface.mapCanvas().destinationCrsChanged.connect(self._refresh_highlight)   # drawn in the map's CRS
        controller.featuresChanged.connect(self._refresh_highlight)
        controller.featuresChanged.connect(self._drop_missing_brush_target)
        controller.featuresChanged.connect(self._sync_selection_page)
        controller.sessionChanged.connect(self._session_changed)
        controller.message.connect(self._show_message)
        controller.previewUpdated.connect(self._preview_updated)
        controller.previewCleared.connect(lambda: self.overlay.clear())
        controller.featuresRestored.connect(self._history_restored)
        # Ctrl+Z / Ctrl+Shift+Z: in the panel always, on the map only while a Terrain Sketch tool is active
        self.undo_keys = UndoKeys(controller.undo_stack, parent=self)
        self.installEventFilter(self.undo_keys)
        if profiles is not None:
            profiles.installEventFilter(self.undo_keys)   # the Profiles panel is Terrain Sketch too
            profiles.drawSectionRequested.connect(self._draw_section_line)
        # A spin box claims Ctrl+Z for its own text even when it has none to undo, as after its arrows
        # committed each step; only while it has typed text to undo (or redo) is that key its own
        self.spin_undo_keys = []
        page = self.properties
        for spin in (page.amount, page.width, page.slope, page.reach):
            keys = UndoKeys(controller.undo_stack, applies=lambda redo, s=spin: not _has_text_history(s, redo),
                            parent=self)
            spin.installEventFilter(keys)
            self.spin_undo_keys.append(keys)
        self.canvas_undo_keys = UndoKeys(controller.undo_stack, applies=lambda _redo: self._sketch_tool_active(),
                                       parent=self)
        iface.mapCanvas().installEventFilter(self.canvas_undo_keys)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        tool, self.draw_tool, self._brush_fid, self._brush_extends = self.draw_tool, None, None, False
        self._section_fid = None
        self._release_tool(tool)

    def stop_editing(self) -> None:
        """Leave vertex editing and give the canvas its previous map tool back."""
        tool, self.edit_tool = self.edit_tool, None
        self._release_tool(tool)
        if self.edit_button.isChecked():
            self.edit_button.setChecked(False)

    def stop_tools(self) -> None:
        """Stop drawing and editing — the panel is hidden, the session ended or the tool changed."""
        self.end_drawing()
        self.stop_editing()
        self.controller.cancel_preview()

    def shutdown(self) -> None:
        """Stop the tools and release the highlight and overlay; called when the plugin unloads."""
        self.stop_tools()
        self.controller.cancel_preview()
        self.overlay.dispose()
        self.highlight.reset(Qgis.GeometryType.Line)
        self.section_band.reset(Qgis.GeometryType.Line)
        self.iface.mapCanvas().scene().removeItem(self.highlight)
        self.iface.mapCanvas().scene().removeItem(self.section_band)
        # The filters on the panels are this dock's children and go with it; the canvas outlives the plugin
        self.iface.mapCanvas().removeEventFilter(self.canvas_undo_keys)

    def _release_tool(self, tool) -> None:
        if tool is not None:
            canvas = self.iface.mapCanvas()
            if canvas.mapTool() is tool:
                if self._previous_tool is not None and not sip.isdeleted(self._previous_tool):
                    canvas.setMapTool(self._previous_tool)
                else:
                    canvas.unsetMapTool(tool)
            tool.dispose()
            tool.deleteLater()
            self.hint.hide()

    def closeEvent(self, event):  # noqa: N802 — Qt override
        self.stop_tools()
        super().closeEvent(event)

    def _session_changed(self) -> None:
        has_dem = self.controller.has_dem
        if not has_dem:
            self.stop_tools()  # a drawing or edit cannot outlive its session
            self._update_highlight(None)
        for widget in (self.export_button, self.hillshade_box, self.new_button, self.delete_button,
                       self.edit_button, self.feature_view, self.view_3d_button, *self.scenario_buttons):
            widget.setEnabled(has_dem)
        if self.controller.layers is not None:
            project = self.controller.project
            self.dem_combo.setExceptedLayerList([project.mapLayer(i) for i in self.controller.layers.layer_ids])
            self.controller.set_hillshade_visible(self.hillshade_box.isChecked())
        else:
            self.dem_combo.setExceptedLayerList([])
        self.pages.setCurrentIndex(PAGE_GALLERY if has_dem else PAGE_START)
        self._update_radius_units()
        self._update_overlay_transform()

    def _update_overlay_transform(self) -> None:
        """Keep the drag preview georeferenced.

        Its bounds come from the engine in the DEM's CRS, while the canvas item is placed in the
        project CRS: without this the cut/fill image lands somewhere else on the map, silently,
        whenever the two differ. Runs from `sessionChanged` and `destinationCrsChanged` — both
        slots, so a CRS that cannot be projected leaves the preview unshown instead of raising."""
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        dem_crs = self.controller.dem_crs
        transform, failed = None, False
        if not self.controller.has_dem:
            pass                                   # no session, so no preview to place
        elif not (dem_crs.isValid() and canvas_crs.isValid()):
            failed = True                          # nothing to project between
        elif dem_crs != canvas_crs:
            try:
                transform = QgsCoordinateTransform(dem_crs, canvas_crs, QgsProject.instance())
                failed = not transform.isValid()
            except Exception:                      # noqa: BLE001 — this runs in a slot
                failed = True
            if failed:
                transform = None
        self._overlay_transform_failed = failed
        self.overlay.crs_transform = transform
        if failed:
            self.overlay.clear()

    def _update_radius_units(self) -> None:
        """Label the brush radius with the canvas's own map units — the brush buffers in them."""
        self.gallery.set_radius_units(self.iface.mapCanvas().mapUnits())

    def _drop_missing_brush_target(self) -> None:
        """The feature a brush stroke extends can be deleted while the stroke is still running."""
        if self._brush_fid is not None and self._brush_fid not in {f.id for f in self.controller.features}:
            self._brush_fid = None

    def _start(self) -> None:
        layer = self.dem_combo.currentLayer()
        if layer is None:
            return
        if self._keep_unsaved_work():
            return
        self._start_session(layer)

    def _start_session(self, layer) -> bool:
        """Start on `layer` once any unsaved work has been dealt with. True when the session started."""
        self._asked_about_unsaved = True   # the user has just answered; closing the old session must not ask again
        try:
            self.controller.set_dem(layer)
            return True
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
            return False
        finally:
            self._asked_about_unsaved = False

    def _start_on_file(self, source: str) -> bool:
        """Start on the DEM at `source`: the layer already in the project that reads it, or a new one."""
        project = QgsProject.instance()
        layer = next((layer for layer in project.mapLayers().values()
                      if isinstance(layer, QgsRasterLayer) and _same_source(layer.source(), source)), None)
        added = layer is None
        if added:
            layer = QgsRasterLayer(source, os.path.splitext(os.path.basename(source))[0])
            if not layer.isValid():
                self._show_message(Qgis.MessageLevel.Warning, DEM_NOT_READABLE.format(source))
                return False
            project.addMapLayer(layer)
        self.dem_combo.setLayer(layer)
        if self._start_session(layer):
            return True
        if added:
            project.removeMapLayer(layer.id())    # a layer the user never added does not stay behind
        return False

    def _new_feature(self) -> None:
        self.feature_view.clearSelection()
        self.pages.setCurrentIndex(PAGE_GALLERY)

    def _delete_selected(self) -> None:
        fid = self.feature_view.selected_id()
        if fid is not None:
            self.controller.delete_feature(fid)

    def _preview_updated(self, _fid, preview) -> None:
        if self._overlay_transform_failed:
            return  # the bounds cannot be placed on this canvas; showing them would mislead
        self.overlay.show_change(preview.bounds, preview.change)

    def _selection_changed(self, *_args) -> None:
        fid = self.feature_view.selected_id()
        self.stop_editing()
        if self._section_fid is not None and fid != self._section_fid:
            self.end_drawing()          # the line being drawn is the other area's, which the panel no longer shows
        if self.profiles is not None:
            self.profiles.show_feature(fid)
        self.edit_button.setEnabled(fid is not None)
        self._update_highlight(fid)
        if fid is not None:
            self.properties.show_feature(fid)
            self.pages.setCurrentIndex(PAGE_PROPERTIES)
        elif self.controller.has_dem:
            self.pages.setCurrentIndex(PAGE_GALLERY)

    def _begin_drawing(self, tool, mode, method) -> None:
        self.stop_tools()
        canvas = self.iface.mapCanvas()
        if method is Method.BRUSH:
            self._brush_fid = self._brush_target(tool, mode)
            self._brush_extends = self._brush_fid is not None
            try:
                initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
            except QgsCsException:
                self._brush_fid, self._brush_extends = None, False
                self._show_message(Qgis.MessageLevel.Warning, SHAPE_NOT_TRANSFORMED)
                return
            self.draw_tool = BrushTool(canvas, self.gallery.brush_radius(), initial)
            self.draw_tool.radiusChanged.connect(self.gallery.set_brush_radius)
        elif method is Method.FREEHAND:
            shape = Qgis.GeometryType.Line if mode is Mode.PATH else Qgis.GeometryType.Polygon
            self.draw_tool = FreehandTool(canvas, shape)
        else:
            self.draw_tool = (DrawLineTool if mode is Mode.PATH else DrawPolygonTool)(canvas)
        self.draw_tool.finished.connect(lambda geometry, t=tool, m=mode: self._drawn(t, m, geometry))
        self._activate_drawing(self._drawing_hint(method))

    def _activate_drawing(self, hint: str) -> None:
        """Put `draw_tool` on the map, remembering the tool it replaces, and show what to do."""
        canvas = self.iface.mapCanvas()
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.setText(hint)
        self.hint.show()

    def _draw_section_line(self, fid: str) -> None:
        """Draw the line an area's section runs along (spec §5.4), asked for by the Profiles panel."""
        if self.controller.find(fid) is None:
            return
        self.stop_tools()
        self._section_fid = fid
        self.draw_tool = DrawLineTool(self.iface.mapCanvas())
        self.draw_tool.finished.connect(lambda geometry, f=fid: self._section_drawn(f, geometry))
        self._activate_drawing(SECTION_LINE_HINT)

    def _section_drawn(self, fid: str, geometry) -> None:
        if fid != self._section_fid:
            return                      # the drawing already ended: the selection moved to another feature
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.end_drawing()
        self.controller.set_section_line(fid, geometry, crs)

    def _drawing_hint(self, method) -> str:
        """The instruction text for `method`, naming the feature when the brush extends one."""
        if self._brush_fid is not None:
            return BRUSH_EXTEND_HINT.format(self.controller.feature(self._brush_fid).name)
        return METHOD_HINTS[method]

    def _brush_target(self, tool, mode) -> str | None:
        """The selected feature the brush should extend, if it fits the chosen tool and shape."""
        fid = self.feature_view.selected_id()
        if fid is None or mode is not Mode.AREA:
            return None
        feature = self.controller.feature(fid)
        return fid if feature.tool is tool and feature.mode is Mode.AREA else None

    def _drawn(self, tool, mode, geometry) -> None:
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        fid = self._brush_fid
        self.end_drawing()
        if fid is not None:
            self.controller.set_geometry(fid, geometry, crs)
            self.feature_view.select_id(fid)
            return
        feature = self.controller.add_drawn(tool, mode, geometry, crs)
        if feature is not None:
            self.feature_view.select_id(feature.id)

    def _use_layer(self, tool, mode, layer, selected_only) -> None:
        feature = self.controller.add_from_layer(tool, mode, layer, selected_only)
        if feature is not None:
            self.feature_view.select_id(feature.id)

    def _toggle_edit(self, checked: bool) -> None:
        if not checked:
            self.stop_editing()
            return
        fid = self.feature_view.selected_id()
        if fid is None:
            self.edit_button.setChecked(False)
            return
        self.end_drawing()
        canvas = self.iface.mapCanvas()
        try:
            shape = self._to_canvas(self.controller.feature_geometry(fid))
        except QgsCsException:
            self.edit_button.setChecked(False)
            self._show_message(Qgis.MessageLevel.Warning, SHAPE_NOT_TRANSFORMED)
            return
        self.edit_tool = VertexEditTool(canvas, shape)
        self.edit_tool.geometryChanged.connect(lambda geometry, f=fid: self._edited(f, geometry))
        self.edit_tool.cancelled.connect(self.stop_editing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.edit_tool)
        self.hint.setText(EDIT_HINT)
        self.hint.show()

    def _edited(self, fid, geometry) -> None:
        self.controller.set_geometry(fid, geometry, self.iface.mapCanvas().mapSettings().destinationCrs())

    def _map_tool_set(self, new_tool, _old_tool=None) -> None:
        """The user picked another map tool: stop our drawing or editing."""
        if self.draw_tool is not None and new_tool is not self.draw_tool:
            self.end_drawing()
        if self.edit_tool is not None and new_tool is not self.edit_tool:
            self.stop_editing()

    def _to_canvas(self, geometry: QgsGeometry) -> QgsGeometry:
        """A geometry in the DEM CRS, expressed in the canvas CRS."""
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        result = QgsGeometry(geometry)
        if canvas_crs != self.controller.dem_crs:
            result.transform(QgsCoordinateTransform(self.controller.dem_crs, canvas_crs, QgsProject.instance()))
        return result

    def _sync_selection_page(self) -> None:
        """The list model resets on every change, which can clear the Qt selection without
        emitting `selectionChanged` (a clear that leaves nothing selected is a no-op) — so a
        deleted feature can be left showing on the Properties page with stale figures. Make the
        dock behave as if the user had deselected whenever that happens."""
        if self.pages.currentIndex() != PAGE_PROPERTIES:
            return
        fid = self.feature_view.selected_id()
        if fid is None or fid not in {f.id for f in self.controller.features}:
            self._selection_changed()

    def _sketch_tool_active(self) -> bool:
        return isinstance(self.iface.mapCanvas().mapTool(), SketchTool)

    def _history_restored(self) -> None:
        """Undo or redo replaced the feature list underneath whatever the panel shows. A vertex
        edit or a brush stroke that extends a feature holds that feature's old outline and would
        put it straight back, so both stop; drawing a new feature does not depend on the list and
        carries on. (The Properties page follows every change on its own.)
        `_brush_extends`, not `_brush_fid`: an undo that removes the feature itself has already cleared
        the id (featuresChanged comes first), and the brush would then add the old outline as a new feature."""
        self.stop_editing()
        if self._brush_extends:
            self.end_drawing()

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map, with the line its section runs along if it is an area."""
        self._update_section_band(fid)
        if fid is None or not self.controller.has_dem or fid not in {f.id for f in self.controller.features}:
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        try:
            geometry = self._to_canvas(self.controller.feature_geometry(fid))
        except QgsCsException:
            # runs from selection and change signals, on every change: no message here, Edit shape
            # and Zoom to feature give one when the user acts on the outline
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        self.highlight.reset(geometry.type())
        self.highlight.setToGeometry(geometry, None)

    def _update_section_band(self, fid) -> None:
        line = self.controller.section_line(fid) if fid is not None else None
        try:
            geometry = self._to_canvas(from_wkb(line)) if line is not None else None
        except QgsCsException:
            geometry = None                    # as for the outline: no line rather than an abort
        self.section_band.reset(Qgis.GeometryType.Line)
        if geometry is not None:
            self.section_band.setToGeometry(geometry, None)

    def _new_scenario(self) -> None:
        if self._keep_unsaved_work():
            return
        self.stop_tools()               # an edit in progress belongs to a feature that is about to go
        self.controller.new_scenario()

    def _open_scenario(self) -> None:
        """Ask about unsaved work first, then for the file — the order QGIS's own Open Project uses.
        A scenario made on a different DEM is only opened once the user has agreed to it."""
        if self._keep_unsaved_work():
            return
        path = self.ask_open_path()
        if not path:
            return
        started = False
        try:
            differences = ", ".join(self.controller.scenario_differences(path))
            if differences:
                source = self.controller.scenario_dem_source(path)
                if source is None:        # its DEM is gone or unknown: this one or nothing
                    choice = "current" if self.confirm(SCENARIO_DEM_DIFFERS.format(differences)) else None
                else:
                    choice = self.choose_dem(SCENARIO_OTHER_DEM.format(dem=os.path.basename(source),
                                                                       differences=differences))
                if choice is None or (choice == "scenario" and not self._start_on_file(source)):
                    return
                started = choice == "scenario"
            self.stop_tools()
            self.controller.open_scenario(path)
        except ScenarioError as error:
            text = str(error)
            if started and text == SCENARIO_NOT_APPLIED:
                text = SCENARIO_NOT_APPLIED_ON_ITS_DEM   # starting on its DEM already closed the features' session
            self._show_message(Qgis.MessageLevel.Warning, text)
            return
        self._show_message(Qgis.MessageLevel.Success, SCENARIO_OPENED.format(path))

    def _save_scenario(self, save_as: bool = False) -> bool:
        """Save, asking for a path when there is not one yet. True when it was written."""
        path = self.controller.scenario_path
        if save_as or not path:
            path = self.ask_save_path()
        if not path:
            return False
        try:
            self.controller.save_scenario(path)
        except ScenarioError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))
            return False
        self._show_message(Qgis.MessageLevel.Success, SCENARIO_SAVED.format(path))
        return True

    def _offer_save_before_discard(self) -> None:
        """The controller is about to drop a session with unsaved changes — the project is closing,
        the DEM was removed or the plugin is unloading. None of those can be cancelled from here,
        so the question is only Save or Discard — but choosing Save and then cancelling the file
        dialog, or a save that fails, must not drop the session silently: the question repeats
        until a save succeeds or the user chooses Discard."""
        if self._asked_about_unsaved:
            return
        while self.confirm_save(UNSAVED_BEFORE_CLOSING, can_cancel=False) and not self._save_scenario():
            pass

    def _keep_unsaved_work(self) -> bool:
        """Ask before discarding unsaved features. True means the user backed out."""
        if not self.controller.has_dem or not self.controller.is_dirty:
            return False
        answer = self.confirm_save(UNSAVED_CHANGES)
        if answer is None:
            return True                       # cancelled: keep everything as it is
        if answer and not self._save_scenario():
            return True                       # wanted to save but did not; do not discard
        return False

    def _export(self) -> None:
        path = self.ask_export_path()
        if not path:
            return
        try:
            self.controller.export_dem(path)
        except (OSError, RuntimeError) as error:
            self._show_message(Qgis.MessageLevel.Critical, self.tr("Export failed: {}").format(error))
            return
        text = EXPORT_DONE.format(path)
        if self.controller.dem_is_integer:
            text = f"{text}. {EXPORT_INTEGER_NOTE}"
        self._offer_to_add_export(path, text)

    def _offer_to_add_export(self, path: str, text: str) -> None:
        """Spec §8.5's "adds the result to the project", offered after the export rather than as a
        dialog option: the file dialog is the platform's own and cannot carry one."""
        try:
            bar = self.iface.messageBar()
            widget = bar.createMessage(self.tr("Terrain Sketch"), text)
            button = QPushButton(self.tr("Add to project"), widget)
            button.clicked.connect(lambda _checked=False: self._add_export(path, button))
            widget.layout().addWidget(button)
            bar.pushWidget(widget, Qgis.MessageLevel.Success, 0)
        except Exception:  # noqa: BLE001 — this runs in a click handler; a plain message will do
            self._show_message(Qgis.MessageLevel.Success, text)

    def _add_export(self, path: str, button=None) -> None:
        """Add the exported GeoTIFF as a layer. Runs from the message's button, so a file that has
        since been moved or deleted becomes a message. A file already in the project — added from an
        earlier message about the same path — is not added a second time."""
        try:
            project = QgsProject.instance()
            if not any(_same_source(layer.source(), path) for layer in project.mapLayers().values()):
                layer = QgsRasterLayer(path, os.path.splitext(os.path.basename(path))[0])
                if not layer.isValid():
                    self._show_message(Qgis.MessageLevel.Warning, EXPORT_NOT_ADDED.format(path))
                    return
                project.addMapLayer(layer)
            if button is not None and not sip.isdeleted(button):
                button.setEnabled(False)       # once is enough
        except Exception:  # noqa: BLE001
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self._show_message(Qgis.MessageLevel.Warning, EXPORT_ADD_FAILED.format(path))

    def _open_3d_view(self) -> None:
        """The modified DEM as the project's terrain, then a new 3D view (spec §8.5): through the
        interface when this QGIS offers it, otherwise through QGIS's own New 3D Map View action,
        otherwise a message saying how to open one by hand."""
        try:
            if not self.controller.show_in_3d():
                return
            try:
                if self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
                    return
            except Exception:  # noqa: BLE001 — a QGIS built without 3D; the menu action may still work
                QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
            action = self.iface.mainWindow().findChild(QAction, "mActionNew3DMapCanvas")
            if action is not None and action.isEnabled():
                action.trigger()
                return
        except Exception:  # noqa: BLE001 — this runs in a click slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        self._show_message(Qgis.MessageLevel.Warning, VIEW_3D_NOT_OPENED)

    def _context_menu(self, position) -> None:
        menu = self.feature_menu(self.feature_view.indexAt(position))
        if menu is not None:
            menu.exec(self.feature_view.viewport().mapToGlobal(position))
            menu.deleteLater()   # parented to the dock, it and its actions would otherwise stay for good

    def feature_menu(self, index) -> QMenu | None:
        """The list's context menu for the row at `index` (spec §7.2), or None off the rows."""
        if not index.isValid():
            return None
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(self.tr("Rename"), lambda: self._rename(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDuplicateFeature.svg"), self.tr("Duplicate"),
                       lambda: self._duplicate(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionZoomToLayer.svg"), self.tr("Zoom to feature"),
                       lambda: self._zoom_to(fid))
        menu.addSeparator()
        menu.addAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"),
                       lambda: self.controller.delete_feature(fid))
        return menu

    def _rename(self, fid: str) -> None:
        """Runs from the context menu, whose own event loop lets the list change before the action
        fires, so the row is looked up now rather than kept from when the menu was built."""
        row = self.model.row_of(fid)
        if row >= 0:
            self.feature_view.edit(self.model.index(row))

    def _duplicate(self, fid: str) -> None:
        copy = self.controller.duplicate_feature(fid)
        if copy is not None:
            self.feature_view.select_id(copy.id)

    def _zoom_to(self, fid: str) -> None:
        """Runs from the context menu, so a feature that has gone or an outline that cannot be
        projected into the map's CRS becomes a message rather than an exception in a slot."""
        if self.controller.find(fid) is None:
            return
        canvas = self.iface.mapCanvas()
        transform = QgsCoordinateTransform(self.controller.dem_crs, canvas.mapSettings().destinationCrs(),
                                           QgsProject.instance())
        try:
            extent = transform.transformBoundingBox(self.controller.feature_geometry(fid).boundingBox())
        except QgsCsException:
            self._show_message(Qgis.MessageLevel.Warning, SHAPE_NOT_TRANSFORMED)
            return
        canvas.setExtent(extent.buffered(max(extent.width(), extent.height()) * 0.25 + 1.0))
        canvas.refresh()

    def _offer_reproject(self, text: str) -> None:
        """A geographic DEM is refused with a button that opens Processing's warp tool, so the
        user is not left to find it themselves."""
        try:
            # the DEM this message is about, captured now: the combo can hold something else by
            # the time the button is pressed, and warping a layer the user never saw refused
            # would be worse than warping nothing
            layer = self.dem_combo.currentLayer()
            bar = self.iface.messageBar()
            widget = bar.createMessage(self.tr("Terrain Sketch"), text)
            button = QPushButton(self.tr("Reproject…"), widget)
            button.clicked.connect(lambda _checked=False, dem=layer: self._run_reproject(dem))
            widget.layout().addWidget(button)
            bar.pushWidget(widget, Qgis.MessageLevel.Warning, 0)
        except Exception:  # noqa: BLE001 — this runs in a click handler; a plain message will do
            self._show_message(Qgis.MessageLevel.Warning, text)

    def _run_reproject(self, layer=None) -> None:
        """Open Processing's warp tool on `layer`.

        Everything is inside the guard: this runs in a click handler, where an exception — a
        disabled Processing plugin, a dialog that refuses to open, a mistake of ours — takes the
        whole interpreter down. A message the user can act on is the worst that should happen.
        """
        try:
            from processing import execAlgorithmDialog  # a core plugin, but it can be disabled
            alive = layer is not None and not sip.isdeleted(layer)
            execAlgorithmDialog("gdal:warpreproject", {"INPUT": layer} if alive else {})
        except Exception:  # noqa: BLE001 — ImportError included
            self._show_message(Qgis.MessageLevel.Warning, REPROJECT_UNAVAILABLE)

    def _show_message(self, level, text: str) -> None:
        self.iface.messageBar().pushMessage(self.tr("Terrain Sketch"), text, level, 8)

    def _confirm_dialog(self, text: str) -> bool:
        return QMessageBox.question(self, self.tr("Terrain Sketch"), text) == QMessageBox.StandardButton.Yes

    def _dialog_start_dir(self) -> str:
        """Where a scenario file dialog should open: beside the current scenario file, or the
        project's home folder — empty, same as today, when the project has none either."""
        path = self.controller.scenario_path
        return os.path.dirname(path) if path else QgsProject.instance().homePath()

    def _save_dialog(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Save scenario"), self._dialog_start_dir(),
                                              self.tr("Terrain Sketch scenario (*.gpkg)"))
        if path and not path.lower().endswith(".gpkg"):
            path += ".gpkg"
            # The dialog's own overwrite check ran on the name as typed, before the extension was
            # added, so replacing an existing scenario would otherwise happen without a question.
            if os.path.exists(path) and not self.confirm(SCENARIO_REPLACE.format(os.path.basename(path))):
                return ""
        return path

    def _open_dialog(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Open scenario"), self._dialog_start_dir(),
                                              self.tr("Terrain Sketch scenario (*.gpkg)"))
        return path

    def _dem_choice_dialog(self, text: str):
        """"scenario" to start on the scenario's own DEM, "current" to open it on this one, None to cancel."""
        box = QMessageBox(QMessageBox.Icon.Question, self.tr("Terrain Sketch"), text,
                          QMessageBox.StandardButton.Cancel, self)
        theirs = box.addButton(self.tr("Start on its DEM"), QMessageBox.ButtonRole.AcceptRole)
        mine = box.addButton(self.tr("Open on this DEM"), QMessageBox.ButtonRole.ActionRole)
        box.setDefaultButton(theirs)
        box.exec()
        clicked = box.clickedButton()
        return "scenario" if clicked is theirs else "current" if clicked is mine else None

    def _save_question(self, text: str, can_cancel: bool = True):
        """True to save, False to discard, None to cancel (only offered when `can_cancel`)."""
        buttons = QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
        if can_cancel:
            buttons |= QMessageBox.StandardButton.Cancel
        answer = QMessageBox.question(self, self.tr("Terrain Sketch"), text, buttons)
        if answer == QMessageBox.StandardButton.Cancel:
            return None
        return answer == QMessageBox.StandardButton.Save

    def _export_dialog(self) -> str:
        title = (self.tr("Export modified DEM (saved with decimals, 32-bit float)") if self.controller.dem_is_integer
                 else self.tr("Export modified DEM"))
        path, _ = QFileDialog.getSaveFileName(self, title, "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
            # as for scenarios: the dialog asked about replacing the name as typed, not this one
            if os.path.exists(path) and not self.confirm(EXPORT_REPLACE.format(os.path.basename(path))):
                return ""
        return path
