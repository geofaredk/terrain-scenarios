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
from qgis.PyQt.QtCore import QEvent, QSize, Qt, QTimer
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
                         SCENARIO_OTHER_DEM, SCENARIO_REPLACE, SCENARIO_SAVED, SCENARIO_SAVE_FAILED,
                         SECTION_LINE_HINT, SHAPE_NOT_TRANSFORMED, SKETCHING_ON, START_HEADING, START_INTRO,
                         UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES, PROFILES_TIP, VIEW_3D_NOT_OPENED, VIEW_3D_TIP)
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
from .selection import BRUSH_EXTEND_HINT, EDIT_HINT, METHOD_HINTS, ZOOM_ICON, Method
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
        """Render the illustration. Guarded: this runs from `changeEvent`, a Qt virtual override,
        and `illustrations.pixmap` reads the SVG source from disk — any exception escaping it here
        would abort QGIS rather than merely leave the picture stale."""
        try:
            self.setPixmap(illustrations.pixmap(self._name, self._size, self.palette()))
        except Exception:  # noqa: BLE001 — this runs from a Qt virtual override
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)


class _PagePanel(QgsPanelWidget):
    """Hosts an existing widget as one page of the panel stack, built fresh each time it is opened.

    A wrapper kept for both `ToolGallery` and `PropertiesPage`: each is a single, persistent
    instance (`dock.gallery`, `dock.properties`) that must survive being closed and reopened many
    times over the dock's life — reused across sessions and features so state like the picked tool,
    the brush radius or the undo-key filters installed on `properties`' fields keeps working — but
    pushing the very same `QgsPanelWidget` through `openPanel`/`acceptPanel` a second time corrupts
    the stack (verified by probe). So neither is ever pushed itself: a *fresh* `_PagePanel` wraps
    it on every open, and only the wrapper is ever pushed and accepted. `content` keeps its
    identity — it is only reparented — so `dock.gallery` and `dock.properties` stay the same
    objects other code already reaches for. `PropertiesPage` is a `QgsPanelWidget` in its own right
    too (Task 5), the same as `ToolGallery` — neither is exempt from the "same instance twice"
    restriction, which is why both still go through this wrapper rather than being pushed directly.

    `QgsPanelWidgetStack` defaults `autoDelete` to True and `acceptPanel()` schedules the panel for
    deletion: left alone, that `deleteLater()` takes `content` down with it, since `addWidget`
    reparented it into this wrapper's layout. `release_content()` takes `content` back out first, so
    it survives; a fresh wrapper is then built the next time the same content is opened again, so the
    (now-empty) old wrapper is still cleaned up normally instead of leaking one shell widget per open.

    It is hung off `panelAccepted` — the signal `acceptPanel()` itself emits — rather than called
    only from `MainDock.close_page()`: `QgsPanelWidgetStack` owns a visible "Go back" button and an
    Escape handler that call `acceptPanel()` directly, never through `close_page`. Connecting here
    means every way a page can close — the back button, Escape, `close_page`, and anything QGIS adds
    later — releases the content the same way, verified by probe."""

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        self.setDockMode(True)
        self.setPanelTitle(title)
        self._host = parent   # where release_content puts the content back; not necessarily still
                              # this wrapper's Qt parent by the time it closes (the stack reparents
                              # a pushed panel into its own internal container)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        self.panelAccepted.connect(self._release_on_accept)

    def _release_on_accept(self, _panel=None) -> None:
        try:
            self.release_content(self._host)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def release_content(self, parent) -> None:
        """Take the wrapped content out and reparent it to `parent`, before this wrapper is
        destroyed. A no-op if it has already been taken (e.g. moved straight into a new wrapper for
        the same content, as opening the same page again for a different feature does). Not hidden
        explicitly: `setParent` alone already leaves it invisible until it is shown again, and an
        explicit `hide()` here would set `WA_WState_ExplicitShowHide` — which a later `addWidget`
        into a new wrapper does not clear, leaving every page blank from the second open on
        (verified by probe)."""
        layout = self.layout()
        item = layout.takeAt(0) if layout.count() else None
        content = item.widget() if item is not None else None
        if content is not None:
            content.setParent(parent)


def _3d_types_loaded() -> bool:
    """Whether QGIS's 3D Python types are loaded. `createNewMapCanvas3D` hands back a Qgs3DMapCanvas,
    a type from qgis._3d, which qgis.gui does not import: converting the result without it dereferences
    a null type and QGIS crashes, past any except."""
    try:
        importlib.import_module("qgis._3d")
    except ImportError:
        return False
    return True


def _has_text_history(edit, redo: bool) -> bool:
    """Whether `edit` (a `QLineEdit`, or a spin box's own `lineEdit()`) has typed text of its own
    left to undo or redo — the field's Ctrl+Z is its own only while this is true (see
    `MainDock.spin_undo_keys`, which now also covers the header's `name_edit`)."""
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
        self._hint_text = None            # remembered so `_reroute_hint` can follow a page opening or closing
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

        self.status_label = MutedLabel()
        self.status_label.setOpenExternalLinks(False)

        # A hint for work with no page open — a section line drawn from the Profiles dock after
        # going back to the list (spec §6 item 6, as amended) — shows here, under the toolbar.
        self.session_hint = QLabel()
        self.session_hint.setWordWrap(True)
        self.session_hint.hide()

        session_view = QWidget()
        session_layout = QVBoxLayout(session_view)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.addWidget(self.toolbar)
        session_layout.addWidget(self.session_hint)
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

        # A permanent, never-shown parking spot for `gallery`/`properties` while neither page is
        # open — both are built once and reused for the dock's whole life (below), so each spends
        # most of its life parented here rather than inside a page, instead of ever calling `hide()`
        # on either widget itself: an explicit `hide()` sets `WA_WState_ExplicitShowHide`, which a
        # later `addWidget` into a new wrapper does not clear, leaving every page blank from the
        # second open on (verified by probe). This is what its *initial* parenting (below) actually
        # fixes: a widget constructed with the dock itself as parent (as `gallery` was) picks up the
        # dock's own visibility the moment `MainDock.show()` runs, and paints as an unplaced ~100×30
        # box at (0, 0) until the New feature page is opened for the first time (verified by probe).
        # `_PagePanel.release_content` also returns content here rather than to the dock directly —
        # `setParent` alone already leaves a widget invisible once it has been reparented at least
        # once (verified by probe), so this is not load-bearing the same way, but keeps every path a
        # released page's content takes consistent with the one that matters.
        self._released_pages = QWidget(self)
        self._released_pages.hide()

        # `gallery` and `properties` keep their names and behaviour (spec §12); each is wrapped as a
        # drill-in page (see `_PagePanel`) — a single, persistent instance that survives being
        # closed and reopened for the dock's whole life, since state like the picked tool, the
        # brush radius, or `spin_undo_keys`' filters on `properties`' fields must keep working.
        self.gallery = ToolGallery(self._released_pages)
        self.gallery.drawRequested.connect(self._begin_drawing)
        self.gallery.layerRequested.connect(self._use_layer)
        # `ToolGallery` is a `QgsPanelWidget`: its own `keyPressEvent` (dockMode True) answers
        # Escape itself, by calling its own `acceptPanel()` — before the key press ever reaches the
        # `_PagePanel` wrapper that is actually on the stack. Forwarding its `panelAccepted` to
        # `close_page` is what makes Escape inside the tiles close the real page (verified by probe:
        # without this, Escape inside the gallery is silently swallowed).
        self.gallery.panelAccepted.connect(self.close_page)
        self.properties = PropertiesPage(controller, self._released_pages)
        # `PropertiesPage` is a `QgsPanelWidget` too (dockMode True), with exactly the same Escape
        # hazard as `gallery` above — its own keyPressEvent answers Escape by calling its own
        # `acceptPanel()`, emitting `properties.panelAccepted` rather than the `_PagePanel` wrapper's,
        # before the key ever reaches the wrapper actually on the stack. Same fix, same reason.
        self.properties.panelAccepted.connect(self.close_page)
        self.properties.titleChanged.connect(self._sync_feature_page_title)
        # spec §12: `delete_button` and `edit_button` keep their names, now as the feature page's
        # own buttons — there is no second set. `zoom_button` has no dock-level alias; nothing
        # outside `properties` reaches for it.
        self.delete_button = self.properties.delete_button
        self.edit_button = self.properties.edit_button
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
        self.feature_view.rowOpened.connect(self._open_feature_page)
        self.properties.deleteRequested.connect(self._delete_selected)
        self.properties.zoomRequested.connect(self._zoom_to)
        self.properties.editShapeToggled.connect(self._toggle_edit)
        self.feature_view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.feature_view.customContextMenuRequested.connect(self._context_menu)
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
        controller.previewCleared.connect(self._clear_preview)
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
            profiles.closedStateChanged.connect(self._profiles_closed_state_changed)
        # A spin box (or the header's name field) claims Ctrl+Z for its own text even when it has
        # none to undo, as after a spin's arrows committed each step; only while there is typed
        # text to undo (or redo) is that key its own — otherwise it must reach the undo stack, or a
        # stale Ctrl+Z in name_edit would undo old typed text and the next focus-out would commit
        # that text as a rename.
        self.spin_undo_keys = []
        page = self.properties
        for edit in (page.amount, page.width, page.slope, page.reach, page.name_edit):
            line_edit = edit.lineEdit() if hasattr(edit, "lineEdit") else edit
            keys = UndoKeys(controller.undo_stack, applies=lambda redo, e=line_edit: not _has_text_history(e, redo),
                            parent=self)
            edit.installEventFilter(keys)
            self.spin_undo_keys.append(keys)
        self.canvas_undo_keys = UndoKeys(controller.undo_stack, applies=lambda _redo: self._sketch_tool_active(),
                                       parent=self)
        iface.mapCanvas().installEventFilter(self.canvas_undo_keys)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back. Guarded:
        reached directly from `draw_tool.cancelled`, a Qt signal (`_activate_drawing`), as well as
        from many plain callers that only depend on it running — it never returns a value, so a
        caller loses nothing when the guard below swallows an exception instead of raising it."""
        try:
            tool, self.draw_tool, self._brush_fid, self._brush_extends = self.draw_tool, None, None, False
            self._section_fid = None
            self._release_tool(tool)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def stop_editing(self) -> None:
        """Leave vertex editing and give the canvas its previous map tool back. Guarded: reached
        directly from `edit_tool.cancelled`, a Qt signal, as well as from many plain callers that
        depend on nothing but it running — it never returns a value, so a caller loses nothing when
        the guard below swallows an exception instead of raising it."""
        try:
            tool, self.edit_tool = self.edit_tool, None
            self._release_tool(tool)
            if self.edit_button.isChecked():
                self.edit_button.setChecked(False)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
            self.clear_hint()

    def closeEvent(self, event):  # noqa: N802 — Qt override
        """Guarded: a Qt virtual override — an exception here must not stop `super().closeEvent`
        from running, which is what actually lets the dock close."""
        try:
            self.stop_tools()
        except Exception:  # noqa: BLE001 — this runs from a Qt virtual override
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        super().closeEvent(event)

    def _session_changed(self) -> None:
        try:
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
                self.dem_combo.setExceptedLayerList(
                    [project.mapLayer(i) for i in self.controller.layers.layer_ids])
            else:
                self.dem_combo.setExceptedLayerList([])
            if has_dem:
                self.status_label.setText(SKETCHING_ON.format(html.escape(self._dem_name)) + CHANGE_DEM_LINK)
            # new_scenario/save_scenario/open_scenario also emit sessionChanged while the same
            # session keeps running (has_dem unchanged): only a real transition closes the open
            # page and moves the view — a stale page over a scenario that was just replaced is
            # featuresChanged's job (_sync_selection_page), not this signal's.
            if has_dem != self._session_has_dem:
                self.close_page()
                self.views.setCurrentIndex(VIEW_SESSION if has_dem else VIEW_WELCOME)
                self._disconnect_dem_name()
            self._session_has_dem = has_dem
            self._update_radius_units()
            self._update_overlay_transform()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def open_page(self, page) -> None:
        """Push `page` onto the stack, closing whatever page is already open first: the panel never
        drills more than one level deep from the main list."""
        page.setDockMode(True)   # mandatory before openPanel — see the note on `main_panel` above
        self.close_page()
        self.main_panel.openPanel(page)

    def close_page(self) -> None:
        """Accept the open page, if there is one, returning the stack to the main list. `_PagePanel`
        releases its own content on `panelAccepted`, so this covers the same ground as the stack's
        own Go back button and Escape, which call `acceptPanel()` directly and never reach here.

        Guarded: connected directly to `gallery.panelAccepted` and `properties.panelAccepted`, both
        Qt signals, as well as called directly from plain code — it never returns a value, so a
        caller loses nothing when the guard below swallows an exception instead of raising it."""
        try:
            current = self.stack.currentPanel()
            if current is not None and current is not self.main_panel:
                current.acceptPanel()
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    @property
    def hint(self) -> QLabel:
        """The drawing hint, on whichever page (or, with none open, the session view itself)
        currently owns one. Kept as `dock.hint` so every existing caller and test keeps working
        unchanged."""
        return self._hint_target()

    def show_hint(self, text: str) -> None:
        """Show the instruction text for whichever activity is running. `METHOD_HINTS` and
        `BRUSH_EXTEND_HINT` belong to the New feature page. `EDIT_HINT` (Edit shape) and
        `SECTION_LINE_HINT` (Draw section line, from the Profiles dock) belong to the feature page
        (spec §6 item 6, §7) and show there whenever it is the page open; with no page open at all —
        a section line drawn from the Profiles dock after going back to the list — the hint shows
        under the toolbar in the session view instead (spec §6 item 6, as amended). Routed here
        rather than at each call site, so every caller stays unchanged.

        The text is remembered (`_hint_text`) so `_reroute_hint` can move it to wherever the hint
        belongs whenever a page opens or closes while the activity it describes is still running —
        a section line drawn from the Profiles dock, say, outlives the feature page it may have
        been started from or later opened on (spec §9), and without this the hint would either be
        left showing on a page that just closed (invisible) or not appear on one that just opened."""
        self._hint_text = text
        self._reroute_hint()

    def clear_hint(self) -> None:
        self._hint_text = None
        self.gallery.clear_hint()
        self.properties.clear_hint()
        self.session_hint.hide()

    def _schedule_reroute_hint(self, _panel=None) -> None:
        """Reroute the hint once the page that just closed has actually left the stack.

        Connected to a wrapper's own `panelAccepted` (see `_new_feature`, `_open_feature_page`),
        which is also where `QgsPanelWidgetStack` connects its own internal handling that pops the
        panel and makes `main_panel` current again — added *after* ours, since we connect before
        ever calling `open_page`/`openPanel`. Qt runs a signal's slots in connection order, so a
        `_reroute_hint` connected directly here would run before that pop and see the just-closed
        page as still current (verified by probe). Posting it instead runs it once every slot
        connected to this `panelAccepted` — including the stack's own — has already run.

        Guarded: connected directly to a `_PagePanel`'s own `panelAccepted`, a Qt signal."""
        try:
            QTimer.singleShot(0, self._reroute_hint)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _reroute_hint(self) -> None:
        """Move the remembered hint text (if any) onto whichever label it now belongs on, hiding it
        everywhere else first. Called after `show_hint`, and whenever the open page changes while
        an activity with a hint of its own is still running — see `_new_feature`,
        `_open_feature_page`, and the `panelAccepted` connections they make on their own wrapper
        (through `_schedule_reroute_hint`), which fire on every way a page can close (the stack's
        own Back button and Escape included, not just `close_page`).

        Guarded: `_schedule_reroute_hint` reaches this from a `QTimer.singleShot` callback, where an
        exception would abort QGIS same as from any other Qt callback."""
        try:
            self.gallery.clear_hint()
            self.properties.clear_hint()
            self.session_hint.hide()
            if self._hint_text is None:
                return
            target = self._hint_target()
            target.setText(self._hint_text)
            target.show()
        except Exception:  # noqa: BLE001 — this runs from a QTimer callback
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _hint_target(self) -> QLabel:
        current = self.stack.currentPanel()
        if current is self.properties_page:
            return self.properties.hint
        if current is self.gallery_page:
            return self.gallery.hint
        return self.session_hint

    def _stop_drawing_on_gallery_close(self, _panel=None) -> None:
        """Pressing the stack's own Back button, or Escape inside the tiles (forwarded from
        `gallery.panelAccepted`), while a drawing started from the New feature page is still running
        must stop it and give the canvas back its previous tool (spec §6.6) — the page is gone, so
        there is no more hint and no more UI to finish or cancel it from. A no-op when the drawing
        already ended before the page closed (the ordinary case: `_drawn` calls `end_drawing` itself,
        before selecting the new feature opens the next page, which is what actually closes this one)."""
        try:
            if self.draw_tool is not None:
                self.end_drawing()
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        slots, so a CRS that cannot be projected leaves the preview unshown instead of raising
        (the inner guard below), and the outer one catches anything else this slot could still
        raise."""
        try:
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
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _update_radius_units(self) -> None:
        """Label the brush radius with the canvas's own map units — the brush buffers in them.
        Guarded: reached from `destinationCrsChanged`, a Qt signal."""
        try:
            self.gallery.set_radius_units(self.iface.mapCanvas().mapUnits())
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _drop_missing_brush_target(self) -> None:
        """The feature a brush stroke extends can be deleted while the stroke is still running.
        Guarded: runs from `featuresChanged`, a Qt signal."""
        try:
            if self._brush_fid is not None and self._brush_fid not in {f.id for f in self.controller.features}:
                self._brush_fid = None
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _start(self) -> None:
        """Guarded: reached from `start_button.clicked`, a Qt signal."""
        try:
            layer = self.dem_combo.currentLayer()
            if layer is None:
                return
            if self._keep_unsaved_work():
                return
            self._start_session(layer)
        except Exception:  # noqa: BLE001 — this runs in a click slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        try:
            self.feature_view.clearSelection()
            self.gallery_page = _PagePanel(self.tr("New feature"), self.gallery, self._released_pages)
            self.gallery_page.panelAccepted.connect(self._stop_drawing_on_gallery_close)
            # A hint whose activity outlives this page (there is none today — a New feature page
            # drawing stops with the page, see `_stop_drawing_on_gallery_close` above — but this
            # keeps both pages symmetric and correct if that ever changes) must move off this page
            # the moment it closes, whichever way that happens (spec §6 item 6, as amended).
            self.gallery_page.panelAccepted.connect(self._schedule_reroute_hint)
            self.open_page(self.gallery_page)
            self._reroute_hint()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _open_feature_page(self, fid: str) -> None:
        """Open `fid`'s feature page — the only two ways in (spec §5.2, §9): a click or Enter on its
        row (`feature_view.rowOpened`), or a finished drawing / From layer for a brand-new feature
        (`_drawn`, `_use_layer`). Selection alone never opens a page — see `_selection_changed` —
        so this also selects the row itself: a real click already will have (`rowOpened` fires after
        `QListView`'s own click handling), but reopening an already-selected row (spec §9's back-then-
        reclick case) produces no `selectionChanged` at all, and this must still work."""
        try:
            self.feature_view.select_id(fid)
            self.properties.show_feature(fid)
            self.properties_page = _PagePanel(self.properties.panelTitle(), self.properties, self._released_pages)
            # Edit shape's button lives on this page: closing it — Back, Escape, or the page
            # closing itself because the feature it shows just disappeared — must stop editing,
            # since there is no more way to switch it off from here (spec §7, §9).
            self.properties_page.panelAccepted.connect(self._stop_editing_on_feature_page_close)
            # A section line started from the Profiles dock outlives this page closing (spec §9) —
            # its hint must move to wherever it belongs next (the list's session view) the moment
            # that happens, whichever way it does (Back, Escape, the feature itself disappearing).
            self.properties_page.panelAccepted.connect(self._schedule_reroute_hint)
            self.open_page(self.properties_page)
            # Opening this page can itself be what a hint's activity is waiting to land on — a
            # section line started from the Profiles dock while looking at the list, its hint
            # showing under the toolbar, whose area's own page is then opened (spec §6 item 6).
            self._reroute_hint()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _stop_editing_on_feature_page_close(self, _panel=None) -> None:
        try:
            self.stop_editing()
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _sync_feature_page_title(self, name: str) -> None:
        """Spec §7: "The panel's title bar follows a rename." `QgsPanelWidgetStack` writes its
        title label once, when a panel is pushed (`panelTitle()` read at that moment) — there is no
        live-update signal or refresh method (verified by probe) — so a rename while the feature
        page is open has to update both the open wrapper's own `panelTitle()` (in case it is ever
        read back) and the stack's title `QLabel` directly, the same way tests already reach
        `mBackButton`. Guarded: reached from `properties.titleChanged`, a Qt signal — a
        differently-styled QGIS build without that label must change nothing and never raise."""
        try:
            if self.properties_page is None or self.stack.currentPanel() is not self.properties_page:
                return
            self.properties_page.setPanelTitle(name)
            label = self.stack.findChild(QLabel, "mTitleText")
            if label is not None:
                label.setText(f" {name} ")   # the exact padding QgsPanelWidgetStack itself uses (verified by probe)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _delete_selected(self, fid=None) -> None:
        """Guarded: reached from `properties.deleteRequested`, a Qt signal."""
        try:
            fid = fid or self.feature_view.selected_id()
            if fid is not None:
                self.controller.delete_feature(fid)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _preview_updated(self, _fid, preview) -> None:
        """Guarded: reached from `controller.previewUpdated`, a Qt signal."""
        try:
            if self._overlay_transform_failed:
                return  # the bounds cannot be placed on this canvas; showing them would mislead
            self.overlay.show_change(preview.bounds, preview.change)
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _clear_preview(self) -> None:
        """Guarded: reached from `controller.previewCleared`, a Qt signal (a bare lambda calling
        `self.overlay.clear()` directly used to sit on this connection with no guard at all)."""
        try:
            self.overlay.clear()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _profiles_closed_state_changed(self, closed: bool) -> None:
        """Guarded: reached from `profiles.closedStateChanged`, a Qt signal (a bare lambda calling
        `self.profiles_button.setChecked(...)` directly used to sit on this connection with no
        guard at all)."""
        try:
            self.profiles_button.setChecked(not closed)
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _selection_changed(self, *_args) -> None:
        """Keep the map highlight and the Profiles dock in step with the list selection (spec §5.2,
        §9) — this never opens a closed page by itself. When the feature page is already open it
        follows the selection instead: shows whichever feature is now selected, or closes if none
        is — an undo, a model reset or a rename must not leave it showing a stale feature."""
        try:
            fid = self.feature_view.selected_id()
            self.stop_editing()
            if self._section_fid is not None and fid != self._section_fid:
                self.end_drawing()      # the line being drawn is the other area's, which the panel no longer shows
            if self.profiles is not None:
                self.profiles.show_feature(fid)
            self.edit_button.setEnabled(fid is not None)
            self._update_highlight(fid)
            if self.stack.currentPanel() is self.properties_page:
                if fid is not None:
                    self.properties.show_feature(fid)
                elif self.controller.has_dem:
                    self.close_page()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _begin_drawing(self, tool, mode, method) -> None:
        """Guarded: reached from `gallery.drawRequested`, a Qt signal."""
        try:
            self.stop_tools()
            canvas = self.iface.mapCanvas()
            if method is Method.BRUSH:
                self._brush_fid = self._brush_target(tool, mode)
                self._brush_extends = self._brush_fid is not None
                try:
                    initial = (self._to_canvas(self.controller.feature_geometry(self._brush_fid))
                              if self._brush_fid else None)
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
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _activate_drawing(self, hint: str) -> None:
        """Put `draw_tool` on the map, remembering the tool it replaces, and show what to do."""
        canvas = self.iface.mapCanvas()
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.show_hint(hint)

    def _draw_section_line(self, fid: str) -> None:
        """Draw the line an area's section runs along (spec §5.4), asked for by the Profiles panel.
        Guarded: reached from `profiles.drawSectionRequested`, a Qt signal."""
        try:
            if self.controller.find(fid) is None:
                return
            self.stop_tools()
            self._section_fid = fid
            self.draw_tool = DrawLineTool(self.iface.mapCanvas())
            self.draw_tool.finished.connect(lambda geometry, f=fid: self._section_drawn(f, geometry))
            self._activate_drawing(SECTION_LINE_HINT)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _section_drawn(self, fid: str, geometry) -> None:
        """Guarded: reached from `draw_tool.finished`, a Qt signal."""
        try:
            if fid != self._section_fid:
                return                  # the drawing already ended: the selection moved to another feature
            crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            self.end_drawing()
            self.controller.set_section_line(fid, geometry, crs)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        """Guarded: reached from `draw_tool.finished` (via the lambda `_begin_drawing` connects),
        a Qt signal."""
        try:
            crs = self.iface.mapCanvas().mapSettings().destinationCrs()
            fid = self._brush_fid
            self.end_drawing()
            if fid is not None:
                self.controller.set_geometry(fid, geometry, crs)
                self.feature_view.select_id(fid)
                return
            feature = self.controller.add_drawn(tool, mode, geometry, crs)
            if feature is not None:
                self._open_feature_page(feature.id)   # a finished drawing opens the new feature's page (spec §9)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _use_layer(self, tool, mode, layer, selected_only) -> None:
        """Guarded: reached from `gallery.layerRequested`, a Qt signal."""
        try:
            feature = self.controller.add_from_layer(tool, mode, layer, selected_only)
            if feature is not None:
                self._open_feature_page(feature.id)   # From layer opens the new feature's page too (spec §9)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _toggle_edit(self, checked: bool) -> None:
        """Guarded: reached from `properties.editShapeToggled`, a Qt signal."""
        try:
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
            self.show_hint(EDIT_HINT)
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _edited(self, fid, geometry) -> None:
        """Guarded: reached from `edit_tool.geometryChanged`, a Qt signal."""
        try:
            self.controller.set_geometry(fid, geometry, self.iface.mapCanvas().mapSettings().destinationCrs())
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _map_tool_set(self, new_tool, _old_tool=None) -> None:
        """The user picked another map tool: stop our drawing or editing. Guarded: reached from
        `iface.mapCanvas().mapToolSet`, a Qt signal."""
        try:
            if self.draw_tool is not None and new_tool is not self.draw_tool:
                self.end_drawing()
            if self.edit_tool is not None and new_tool is not self.edit_tool:
                self.stop_editing()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        dock behave as if the user had deselected whenever that happens.

        Two things a feature that just disappeared (deleted, or undone away) must never leave
        running, whether or not its page happens to be open right now (spec §9): Edit shape — its
        button lives on the feature page, but the map tool itself keeps running on the canvas even
        while that page is closed — and a section line being drawn for it, started from the
        Profiles dock. Runs from `featuresChanged`, a Qt signal: an exception here must be logged,
        not raised."""
        try:
            ids = {f.id for f in self.controller.features}
            fid = self.feature_view.selected_id()
            if fid is None or fid not in ids:
                self.stop_editing()
            if self._section_fid is not None and self._section_fid not in ids:
                self.end_drawing()
            if self.stack.currentPanel() is not self.properties_page:
                return
            fid = self.feature_view.selected_id()
            if fid is None or fid not in {f.id for f in self.controller.features}:
                self._selection_changed()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _sketch_tool_active(self) -> bool:
        return isinstance(self.iface.mapCanvas().mapTool(), SketchTool)

    def _history_restored(self) -> None:
        """Undo or redo replaced the feature list underneath whatever the panel shows. A vertex
        edit or a brush stroke that extends a feature holds that feature's old outline and would
        put it straight back, so both stop; drawing a new feature does not depend on the list and
        carries on. (The Properties page follows every change on its own.)
        `_brush_extends`, not `_brush_fid`: an undo that removes the feature itself has already cleared
        the id (featuresChanged comes first), and the brush would then add the old outline as a new feature.

        Guarded: reached from `controller.featuresRestored`, a Qt signal."""
        try:
            self.stop_editing()
            if self._brush_extends:
                self.end_drawing()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _refresh_highlight(self) -> None:
        """Guarded: reached from `featuresChanged` and `destinationCrsChanged`, both Qt signals."""
        try:
            self._update_highlight(self.feature_view.selected_id())
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        """Guarded: reached from `new_scenario_action.triggered`, a Qt signal."""
        try:
            if self._keep_unsaved_work():
                return
            self.stop_tools()               # an edit in progress belongs to a feature that is about to go
            self.controller.new_scenario()
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _open_scenario(self) -> None:
        """Ask about unsaved work first, then for the file — the order QGIS's own Open Project uses.
        A scenario made on a different DEM is only opened once the user has agreed to it. Guarded:
        reached from `open_scenario_action.triggered`, a Qt signal."""
        try:
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
                    text = SCENARIO_NOT_APPLIED_ON_ITS_DEM  # starting on its DEM already closed the features' session
                self._show_message(Qgis.MessageLevel.Warning, text)
                return
            self._show_message(Qgis.MessageLevel.Success, SCENARIO_OPENED.format(path))
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _save_scenario(self, save_as: bool = False) -> bool | None:
        """Save, asking for a path when there is not one yet. True when it was written; False for
        an ordinary failure (no path chosen, or a `ScenarioError`) worth asking about again; None
        for an unexpected exception, which is not — the same retry would only fail the same way,
        so `_offer_save_before_discard` treats `None` as a reason to stop asking rather than loop
        forever, unlike an ordinary `False`.

        Guarded: reached directly from the Scenario menu's Save / Save as… actions (a Qt signal via
        a lambda), as well as called directly by `_keep_unsaved_work` and
        `_offer_save_before_discard`, both of which depend on the value it returns — an unexpected
        exception here is shown to the user the same way a `ScenarioError` already is, rather than
        escaping a Qt callback."""
        try:
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
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self._show_message(Qgis.MessageLevel.Warning, SCENARIO_SAVE_FAILED)
            return None

    def _offer_save_before_discard(self) -> None:
        """The controller is about to drop a session with unsaved changes — the project is closing,
        the DEM was removed or the plugin is unloading. None of those can be cancelled from here,
        so the question is only Save or Discard — but choosing Save and then cancelling the file
        dialog, or an ordinary save failure (`_save_scenario` returning `False`), must not drop the
        session silently: the question repeats until a save succeeds or the user chooses Discard.
        An unexpected failure (`_save_scenario` returning `None`) is different: it already told the
        user through the message bar, and retrying would only repeat the same failure, so this
        stops asking rather than looping on a question that can never get a useful new answer."""
        if self._asked_about_unsaved:
            return
        while self.confirm_save(UNSAVED_BEFORE_CLOSING, can_cancel=False):
            if self._save_scenario() is not False:
                return

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
        """Guarded: reached from `export_button.clicked`, a Qt signal."""
        try:
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
        except Exception:  # noqa: BLE001 — this runs in a click slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        """Guarded: reached from `feature_view.customContextMenuRequested`, a Qt signal."""
        try:
            menu = self.feature_menu(self.feature_view.indexAt(position))
            if menu is not None:
                menu.exec(self.feature_view.viewport().mapToGlobal(position))
                menu.deleteLater()   # parented to the dock, it and its actions would otherwise stay for good
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def feature_menu(self, index) -> QMenu | None:
        """The list's context menu for the row at `index` (spec §7.2), or None off the rows."""
        if not index.isValid():
            return None
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(self.tr("Rename"), lambda: self._rename(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDuplicateFeature.svg"), self.tr("Duplicate"),
                       lambda: self._duplicate(fid))
        menu.addAction(QgsApplication.getThemeIcon(ZOOM_ICON), self.tr("Zoom to feature"),
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
        """Runs from the context menu and from `properties.zoomRequested` (a Qt signal), so a
        feature that has gone or an outline that cannot be projected into the map's CRS becomes a
        message rather than an exception in a slot."""
        try:
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
        except Exception:  # noqa: BLE001 — this runs off a Qt signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
        """Guarded: reached from `controller.message`, a Qt signal, as well as from many already-
        guarded callers — kept redundant here since this is also the one path every one of them
        shares."""
        try:
            self.iface.messageBar().pushMessage(self.tr("Terrain Sketch"), text, level, 8)
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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
