"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

import html
import importlib
import os
import traceback

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsMessageLog,
                       QgsProject, QgsRasterLayer)
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsPanelWidget, QgsPanelWidgetStack, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.convert import from_wkb
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .help_texts import (CHANGE_DEM_LINK, DEM_NOT_READABLE, EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE,
                         EXPORT_NOT_ADDED, EXPORT_REPLACE, REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS,
                         SCENARIO_MENU_TIP, SCENARIO_NOT_APPLIED, SCENARIO_NOT_APPLIED_ON_ITS_DEM, SCENARIO_OPENED,
                         SCENARIO_OTHER_DEM, SCENARIO_REPLACE, SCENARIO_SAVED, SECTION_LINE_HINT, SHAPE_NOT_TRANSFORMED,
                         SKETCHING_ON, START_HEADING, START_INTRO, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES,
                         PROFILES_TIP, VIEW_3D_NOT_OPENED, VIEW_3D_TIP)
from . import illustrations
from .controller import LOG_TAG
from .feature_list import FeatureListModel, FeatureListView
from .map_tools.base import SketchTool
from .map_tools.brush import BrushTool
from .map_tools.draw_line import DrawLineTool
from .map_tools.draw_polygon import DrawPolygonTool
from .map_tools.freehand import FreehandTool
from .map_tools.vertex_edit import VertexEditTool
from .muted import MutedLabel
from .overlay import PreviewOverlay
from .properties_page import PropertiesPage
from .selection import BRUSH_EXTEND_HINT, EDIT_HINT, EDIT_ICON, METHOD_HINTS, Method
from .tool_gallery import ToolGallery
from .undo import UndoKeys

VIEW_WELCOME, VIEW_SESSION = range(2)
PROFILES_ICON = "/mActionElevationProfile.svg"


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


def _scenario_action(menu: QMenu, icon: str, text: str, tip: str) -> QAction:
    """One entry of the Scenario ▾ menu: same icon, text and tooltip shape as the buttons it replaces."""
    action = menu.addAction(QgsApplication.getThemeIcon(icon), text)
    action.setToolTip(f"{text}\n{tip}")
    return action


class _IllustrationLabel(QLabel):
    """A themed illustration (spec §4's welcome-view picture) that redraws itself on a theme switch,
    the same way every other illustration and `MutedLabel` follow `QEvent.Type.PaletteChange`."""

    def __init__(self, name: str, size: QSize, parent=None):
        super().__init__(parent)
        self._name = name
        self._size = size
        self.setFixedSize(size)
        self._apply()

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._apply()
        super().changeEvent(event)

    def _apply(self) -> None:
        self.setPixmap(illustrations.pixmap(self._name, self._size, self.palette()))


class _PagePanel(QgsPanelWidget):
    """Hosts an existing widget as one page of the panel stack, built fresh each time it is opened.

    A temporary wrapper: Task 4 turns `ToolGallery` and Task 5 turns `PropertiesPage` into
    `QgsPanelWidget`s of their own, at which point `open_page` targets them directly and this
    class goes away. `content` keeps its identity — it is only reparented — so `dock.gallery` and
    `dock.properties` stay the same objects other code already reaches for.

    `QgsPanelWidgetStack` defaults `autoDelete` to True and `acceptPanel()` schedules the panel for
    deletion: left alone, that `deleteLater()` takes `content` down with it, since `addWidget`
    reparented it into this wrapper's layout. `release_content()` — called from `close_page` before
    `acceptPanel()` — takes `content` back out first, so it survives; a fresh wrapper is then built
    the next time the same content is opened again, so the (now-empty) old wrapper is still cleaned
    up normally instead of leaking one shell widget per open."""

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self.setDockMode(True)
        self.setPanelTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)

    def release_content(self, parent) -> None:
        """Take the wrapped content out and reparent it to `parent`, hidden, before this wrapper is
        destroyed. A no-op if it has already been taken (e.g. moved straight into a new wrapper for
        the same content, as opening the same page again for a different feature does)."""
        layout = self.layout()
        item = layout.takeAt(0) if layout.count() else None
        content = item.widget() if item is not None else None
        if content is not None:
            content.setParent(parent)
            content.hide()


def _3d_types_loaded() -> bool:
    """Whether QGIS's 3D Python types are loaded. `createNewMapCanvas3D` hands back a Qgs3DMapCanvas,
    a type from qgis._3d, which qgis.gui does not import: converting the result without it dereferences
    a null type and QGIS crashes, past any except."""
    try:
        importlib.import_module("qgis._3d")
    except ImportError:
        return False
    return True


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
        self._dem_name = ""                 # set by _start_session before its sessionChanged fires
        self._dem_layer = None              # tracked only to keep the status line's name in sync with a rename
        self._session_has_dem = False       # _session_changed's own memory of has_dem, to spot a real transition
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

        # Welcome view (no session): the raise_path illustration, a heading and intro, centred, then
        # the DEM picker and Start — the same row and behaviour as before, just no longer sharing
        # the panel with a session. "Keep sketching" is shown only while a session is still running
        # underneath (reached through the status line's Change… link), to get back to it without
        # pressing Start and discarding every feature.
        welcome_view = QWidget()
        welcome_layout = QVBoxLayout(welcome_view)
        welcome_layout.addStretch(1)
        self.welcome_illustration = _IllustrationLabel("tool_raise_path", QSize(160, 80))
        illustration_row = QHBoxLayout()
        illustration_row.addStretch(1)
        illustration_row.addWidget(self.welcome_illustration)
        illustration_row.addStretch(1)
        welcome_layout.addLayout(illustration_row)
        heading = QLabel(START_HEADING)
        heading_font = heading.font()
        heading_font.setBold(True)
        heading.setFont(heading_font)
        heading.setWordWrap(True)
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        welcome_layout.addWidget(heading)
        intro = QLabel(START_INTRO)
        intro.setWordWrap(True)
        intro.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        welcome_layout.addWidget(intro)
        dem_row = QHBoxLayout()
        dem_row.addWidget(QLabel(self.tr("DEM")))
        self.dem_combo = QgsMapLayerComboBox()
        self.dem_combo.setFilters(Qgis.LayerFilter.RasterLayer)
        dem_row.addWidget(self.dem_combo, 1)
        self.start_button = QPushButton(self.tr("Start"))
        self.start_button.setToolTip(self.tr("Start sketching on this DEM. The DEM itself is never changed."))
        dem_row.addWidget(self.start_button)
        welcome_layout.addLayout(dem_row)
        self.keep_sketching_button = QPushButton(self.tr("Keep sketching"))
        self.keep_sketching_button.setToolTip(
            self.tr("Go back to the session that is still running, without starting a new one."))
        self.keep_sketching_button.hide()   # shown by _session_changed only while a session is live
        welcome_layout.addWidget(self.keep_sketching_button)
        welcome_layout.addStretch(1)

        # The session view: a toolbar, like QGIS's own panels (when the panel is narrower than its
        # buttons, the ones that do not fit move behind the » button instead of forcing it wider),
        # the feature list, and a status line.
        self.toolbar = QToolBar()
        self.toolbar.setIconSize(iface.iconSize(True))
        self.new_button = QToolButton()
        self.new_button.setIcon(QgsApplication.getThemeIcon("/mActionAdd.svg"))
        self.new_button.setText(self.tr("New feature"))
        self.new_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.new_button.setAutoRaise(True)
        self.toolbar.addWidget(self.new_button)
        self.undo_action = controller.undo_stack.createUndoAction(self, self.tr("Undo"))
        self.undo_action.setIcon(QgsApplication.getThemeIcon("/mActionUndo.svg"))
        self.redo_action = controller.undo_stack.createRedoAction(self, self.tr("Redo"))
        self.redo_action.setIcon(QgsApplication.getThemeIcon("/mActionRedo.svg"))
        self.undo_button = _action_button(self.undo_action)
        self.redo_button = _action_button(self.redo_action)
        self.toolbar.addWidget(self.undo_button)
        self.toolbar.addWidget(self.redo_button)
        self.toolbar.addSeparator()
        self.scenario_button = QToolButton()
        self.scenario_button.setIcon(QgsApplication.getThemeIcon("/mActionFileOpen.svg"))
        self.scenario_button.setText(self.tr("Scenario"))
        self.scenario_button.setToolTip(SCENARIO_MENU_TIP)
        self.scenario_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.scenario_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.scenario_button.setAutoRaise(True)
        scenario_menu = QMenu(self)
        self.new_scenario_action = _scenario_action(
            scenario_menu, "/mActionFileNew.svg", self.tr("New scenario"),
            self.tr("Start again with no features. The DEM stays as it is."))
        self.open_scenario_action = _scenario_action(
            scenario_menu, "/mActionFileOpen.svg", self.tr("Open scenario…"),
            self.tr("Open a saved scenario (.gpkg) onto the DEM you started on."))
        self.save_scenario_action = _scenario_action(
            scenario_menu, "/mActionFileSave.svg", self.tr("Save scenario"),
            self.tr("Save the features to a scenario file you can open again later."))
        self.save_as_scenario_action = _scenario_action(
            scenario_menu, "/mActionFileSaveAs.svg", self.tr("Save scenario as…"),
            self.tr("Save the features to a new scenario file, leaving the current one as it is."))
        self.scenario_actions = (self.new_scenario_action, self.open_scenario_action,
                                 self.save_scenario_action, self.save_as_scenario_action)
        self.scenario_button.setMenu(scenario_menu)
        self.toolbar.addWidget(self.scenario_button)
        self.toolbar.addSeparator()
        self.export_button = _file_button(
            "/mActionSharingExport.svg", self.tr("Export DEM…"),
            self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
        self.toolbar.addWidget(self.export_button)
        self.view_3d_button = _file_button("/3d.svg", self.tr("3D view"), VIEW_3D_TIP)
        self.toolbar.addWidget(self.view_3d_button)
        # The Profiles panel stays hidden until this button asks for it, and the button follows the panel
        # when the user closes it there instead.
        self.profiles_button = _file_button(PROFILES_ICON, self.tr("Profiles"), PROFILES_TIP)
        self.profiles_button.setCheckable(True)
        self.profiles_action = self.toolbar.addWidget(self.profiles_button)
        self.profiles_action.setVisible(profiles is not None)

        self.model = FeatureListModel(controller, self)
        self.feature_view = FeatureListView(self.model)

        # `hint`, `delete_button` and `edit_button` move onto later pages (Task 4 and Task 5); kept
        # constructed and working here, parented but not laid out, so nothing that reaches for them
        # mid-plan breaks.
        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.delete_button = QPushButton(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"),
                                         self.tr("Delete"), self)
        self.delete_button.hide()
        self.edit_button = QPushButton(QgsApplication.getThemeIcon(EDIT_ICON), self.tr("Edit shape"), self)
        self.edit_button.setCheckable(True)
        self.edit_button.setToolTip(self.tr("Move, add or remove the points of the selected feature."))
        self.edit_button.hide()

        self.status_label = MutedLabel()
        self.status_label.setOpenExternalLinks(False)

        session_view = QWidget()
        session_layout = QVBoxLayout(session_view)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.addWidget(self.toolbar)
        session_layout.addWidget(self.feature_view, 1)
        session_layout.addWidget(self.status_label)

        self.views = QStackedWidget()
        self.views.addWidget(welcome_view)   # VIEW_WELCOME
        self.views.addWidget(session_view)   # VIEW_SESSION

        self.main_panel = QgsPanelWidget()
        self.main_panel.setDockMode(True)    # QgsPanelWidgetStack.setMainPanel does not set this itself (QGIS 4.2.2):
                                             # a panel opened without it is a modal dialog, which hangs offscreen tests
        main_panel_layout = QVBoxLayout(self.main_panel)
        main_panel_layout.setContentsMargins(0, 0, 0, 0)
        main_panel_layout.addWidget(self.views)

        self.stack = QgsPanelWidgetStack()
        self.stack.setMainPanel(self.main_panel)
        self.setWidget(self.stack)

        # `gallery` and `properties` keep their names and behaviour (spec §12); each is wrapped as a
        # drill-in page until Tasks 4 and 5 make them `QgsPanelWidget`s in their own right. The
        # wrapper itself is rebuilt fresh each time it is opened (see `_PagePanel`); these two
        # attributes always name whichever wrapper is current (or was current last).
        self.gallery = ToolGallery()
        self.properties = PropertiesPage(controller)
        self.gallery_page = None
        self.properties_page = None

        self.start_button.clicked.connect(self._start)
        self.export_button.clicked.connect(self._export)
        self.view_3d_button.clicked.connect(self._open_3d_view)
        self.new_scenario_action.triggered.connect(self._new_scenario)
        self.open_scenario_action.triggered.connect(self._open_scenario)
        self.save_scenario_action.triggered.connect(lambda: self._save_scenario())
        self.save_as_scenario_action.triggered.connect(lambda: self._save_scenario(save_as=True))
        self.new_button.clicked.connect(self._new_feature)
        self.delete_button.clicked.connect(self._delete_selected)
        self.feature_view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.feature_view.customContextMenuRequested.connect(self._context_menu)
        self.gallery.drawRequested.connect(self._begin_drawing)
        self.gallery.layerRequested.connect(self._use_layer)
        self.edit_button.toggled.connect(self._toggle_edit)
        self.status_label.linkActivated.connect(self._show_welcome_view)
        self.keep_sketching_button.clicked.connect(self._keep_sketching)
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
        # QgsPanelWidgetStack.keyPressEvent (verified by probe) consumes every key press itself and
        # never forwards an unhandled one to its parent, unlike a plain QWidget: without this, the
        # key press that follows an accepted ShortcutOverride never reaches the filter above.
        self.stack.installEventFilter(self.undo_keys)
        if profiles is not None:
            profiles.installEventFilter(self.undo_keys)   # the Profiles panel is Terrain Sketch too
            profiles.drawSectionRequested.connect(self._draw_section_line)
            self.profiles_button.toggled.connect(profiles.setUserVisible)
            profiles.closedStateChanged.connect(lambda closed: self.profiles_button.setChecked(not closed))
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
        for widget in (self.export_button, self.new_button, self.delete_button,
                       self.edit_button, self.feature_view, self.view_3d_button):
            widget.setEnabled(has_dem)
        for action in self.scenario_actions:
            action.setEnabled(has_dem)
        self.scenario_button.setEnabled(has_dem)
        self.keep_sketching_button.setVisible(has_dem)
        if self.controller.layers is not None:
            project = self.controller.project
            self.dem_combo.setExceptedLayerList([project.mapLayer(i) for i in self.controller.layers.layer_ids])
        else:
            self.dem_combo.setExceptedLayerList([])
        if has_dem:
            self.status_label.setText(SKETCHING_ON.format(html.escape(self._dem_name)) + CHANGE_DEM_LINK)
        # new_scenario/save_scenario/open_scenario also emit sessionChanged while the same session
        # keeps running (has_dem unchanged): only a real transition closes the open page and moves
        # the view — a stale page over a scenario that was just replaced is featuresChanged's job
        # (_sync_selection_page), not this signal's.
        if has_dem != self._session_has_dem:
            self.close_page()
            self.views.setCurrentIndex(VIEW_SESSION if has_dem else VIEW_WELCOME)
            self._disconnect_dem_name()
        self._session_has_dem = has_dem
        self._update_radius_units()
        self._update_overlay_transform()

    def open_page(self, page) -> None:
        """Push `page` onto the stack, closing whatever page is already open first: the panel never
        drills more than one level deep from the main list."""
        page.setDockMode(True)   # mandatory before openPanel — see the note on `main_panel` above
        self.close_page()
        self.main_panel.openPanel(page)

    def close_page(self) -> None:
        """Accept the open page, if there is one, returning the stack to the main list."""
        current = self.stack.currentPanel()
        if current is not None and current is not self.main_panel:
            if isinstance(current, _PagePanel):
                current.release_content(self)   # save gallery/properties from the delete below
            current.acceptPanel()

    def _show_welcome_view(self, _link: str = "") -> None:
        """The status line's Change… link: back to the welcome view, asking about unsaved work
        first — the session itself keeps running until a new DEM is started, as pressing Start does.
        Stops any drawing or edit in progress: it was running on the map behind the session view,
        which the welcome view no longer shows, and a drawing that then finished would open a
        feature page on top of it."""
        try:
            if self._keep_unsaved_work():
                return
            self.stop_tools()
            self.close_page()
            self.views.setCurrentIndex(VIEW_WELCOME)
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _keep_sketching(self) -> None:
        """The welcome view's second button, shown only while a session is still live (spec-driven
        fix: Change… used to be the only way back, and pressing Start there would have discarded
        every feature just to return to the same session)."""
        try:
            self.views.setCurrentIndex(VIEW_SESSION)
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        self._dem_name = layer.name()      # set before set_dem: sessionChanged fires from inside it
        try:
            self.controller.set_dem(layer)
            self._connect_dem_name(layer)
            return True
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
            return False
        finally:
            self._asked_about_unsaved = False

    def _connect_dem_name(self, layer) -> None:
        """Keep the status line's DEM name in sync with a rename in the Layers panel."""
        self._disconnect_dem_name()
        self._dem_layer = layer
        layer.nameChanged.connect(self._dem_renamed)

    def _disconnect_dem_name(self) -> None:
        if self._dem_layer is not None and not sip.isdeleted(self._dem_layer):
            try:
                self._dem_layer.nameChanged.disconnect(self._dem_renamed)
            except TypeError:   # already disconnected
                pass
        self._dem_layer = None

    def _dem_renamed(self) -> None:
        try:
            if self._dem_layer is not None and not sip.isdeleted(self._dem_layer):
                self._dem_name = self._dem_layer.name()
                if self.controller.has_dem:
                    self.status_label.setText(SKETCHING_ON.format(html.escape(self._dem_name)) + CHANGE_DEM_LINK)
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        self.gallery_page = _PagePanel(self.tr("New feature"), self.gallery, self)
        self.open_page(self.gallery_page)

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
            self.properties_page = _PagePanel("", self.properties, self)
            self.open_page(self.properties_page)
        elif self.controller.has_dem:
            self.close_page()

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
        if self.stack.currentPanel() is not self.properties_page:
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
                if _3d_types_loaded() and self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
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
