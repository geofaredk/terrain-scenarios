"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import configparser
import os
import pathlib
import shutil
import tempfile
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import replace
from typing import NamedTuple

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsMessageLog, QgsProject,
                       QgsRasterDemTerrainProvider, QgsSymbol)
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QUndoStack

from ..core.engine import FeatureStack
from ..core.operations import FeatureStats
from ..core.sections import default_section_line, long_section, rescale_long_profile, section_along
from ..core.tools import Mode, Tool
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io import scenario
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import CHANGE_NAME, WORKING_NAME, DemError, WorkingFiles, export_dem, read_dem
from ..qgis_io.scenario import ScenarioError
from ..qgis_io.symbols import from_xml, style_of
from .help_texts import (COPY_NAME, DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER, FILES_ARE_THE_DEM,
                         FILES_KEPT_IN_OLD_FOLDER, FILES_NOT_MOVED, FILES_NOT_RELEASED, FILES_NOT_RESTORED,
                         NO_FEATURES_SELECTED, NO_SESSION, RESULT_LAYER_REMOVED, SCENARIO_NOT_APPLIED,
                         SESSION_ENDED_DEM_REMOVED, TOOL_LABELS, UNDO_ADD, UNDO_DELETE, UNDO_DUPLICATE,
                         UNDO_PROFILE, UNDO_RENAME, UNDO_REORDER, UNDO_SECTION_LINE, UNDO_SETTINGS, UNDO_SHAPE,
                         UNDO_STYLE, UNDO_STYLES, UNDO_TURN_OFF, UNDO_TURN_ON, VIEW_3D_NO_LAYER)
from .undo import FeatureListChange

LOG_TAG = "Terrain Sketch"
FILES_SUFFIX = "_files"


def scenario_files_folder(path: str) -> str:
    """Where a scenario's working rasters live once it is saved: `flood.gpkg` → `flood_files/` (spec §8.2)."""
    return os.path.splitext(path)[0] + FILES_SUFFIX


def plugin_version() -> str:
    """The version from metadata.txt, so a scenario records what wrote it."""
    parser = configparser.ConfigParser()
    try:
        parser.read(pathlib.Path(__file__).resolve().parent.parent / "metadata.txt")
        return parser.get("general", "version", fallback="")
    except Exception:  # noqa: BLE001 — a missing version must never stop a save
        return ""


class PreviewImage(NamedTuple):
    """What a drag preview hands the GUI: where it is, what changed, and the running stats."""

    bounds: tuple          # (xmin, ymin, xmax, ymax) in the DEM CRS
    change: object         # float32 array, new minus original, over those bounds
    stats: FeatureStats


PREVIEW_INTERVAL = 60  # ms between preview recomputes while dragging (spec 8.3)

EMPTY_SECTION = {"stations": (), "terrain": (), "design": (), "custom": False}
EMPTY_AREA_SECTION = {"stations": (), "before": (), "after": (), "line": None}


class SketchController(QObject):
    """Owns the session: the DEM, the ordered feature list, the engine, the files and the layers."""

    featuresChanged = pyqtSignal()
    sessionChanged = pyqtSignal()
    previewUpdated = pyqtSignal(str, object)  # (feature id, PreviewImage) while dragging
    previewCleared = pyqtSignal()
    message = pyqtSignal(object, str)  # (Qgis.MessageLevel, text for the message bar)
    featuresRestored = pyqtSignal()    # undo or redo replaced the feature list
    stylesChanged = pyqtSignal()       # a feature's displayed symbol may have changed

    def __init__(self, project: QgsProject, parent=None):
        super().__init__(parent)
        self.project = project
        self.stack = None
        self.info = None
        self.files = None
        self._files_owner = None       # the scenario file whose `_files` folder holds the working rasters, if any
        self._files_edited = False     # whether those rasters changed since that scenario was saved or opened
        self.layers = None
        self.dem_layer_id = None
        self.dem_crs = QgsCoordinateReferenceSystem()
        self._features: list[TerrainFeature] = []
        self._closing = False
        self._writing_outlines = False  # the controller's own outline-layer writes are not the user's edits
        self._pending = None
        self.undo_stack = QUndoStack(self)
        self._terrain_before = None   # the project's terrain before show_in_3d replaced it
        self._scenario_path = None
        self._created = ""
        # Called, if set, just before a session with unsaved changes is dropped — the project
        # closing, the DEM being removed, the plugin unloading — so the panel can offer to save.
        # The controller shows no UI itself; the callable must not raise, but is guarded anyway.
        self.before_discard = None
        self._throttle = QTimer(self)
        self._throttle.setInterval(PREVIEW_INTERVAL)
        self._throttle.timeout.connect(self._throttle_elapsed)
        # An edit in the Layers panel is read back once control is back in the event loop: committing it
        # inside the legend node's own method would make the layer tree rebuild, and delete, that node
        # while its method still runs. Restarted on each signal, so a burst of them is read back once.
        self._style_read = QTimer(self)
        self._style_read.setSingleShot(True)
        self._style_read.setInterval(0)
        self._style_read.timeout.connect(self._read_outline_styles)
        project.layersRemoved.connect(self._on_layers_removed)
        project.cleared.connect(self._drop_session)
        project.aboutToBeCleared.connect(self._drop_session)

    @property
    def has_dem(self) -> bool:
        return self.stack is not None

    @property
    def features(self) -> tuple:
        return tuple(self._features)

    def feature(self, fid: str) -> TerrainFeature:
        return next(f for f in self._features if f.id == fid)

    def find(self, fid: str) -> TerrainFeature | None:
        """The feature, or None if it is gone. Use this wherever a stale id can arrive —
        `feature()` raises, and an exception inside a Qt callback aborts QGIS."""
        return next((f for f in self._features if f.id == fid), None)

    def stats(self, fid: str) -> FeatureStats:
        return self.stack.stats.get(fid, FeatureStats()) if self.stack else FeatureStats()

    def feature_geometry(self, fid: str) -> QgsGeometry:
        """The feature's drawn geometry in the DEM CRS."""
        return from_wkb(self.feature(fid).geometry_wkb)

    def set_dem(self, layer) -> None:
        """Start a new session on `layer`. Raises DemError (user-facing message) before changing anything;
        if it fails after the previous session was already closed, the session is dropped cleanly."""
        grid, info = read_dem(layer)
        folder = tempfile.mkdtemp(prefix="terrain_sketch_")
        try:
            files = WorkingFiles(folder, grid, info)
        except Exception as error:  # noqa: BLE001 — whatever went wrong, the new folder must not stay behind
            shutil.rmtree(folder, ignore_errors=True)
            raise DemError(f"Terrain Sketch could not create its working files: {error}") from error
        self.close()
        self.stack = FeatureStack(grid)
        self.info = info
        self.files = files
        self._files_owner, self._files_edited = None, False
        try:
            self.layers = SketchLayers(self.project, layer, self.files.working_path, self.files.change_path)
        except Exception as error:  # noqa: BLE001 — never leave a half-built session behind
            self._drop_session()
            raise DemError(f"Terrain Sketch could not create its layers: {error}") from error
        self.dem_layer_id = layer.id()
        self.dem_crs = QgsCoordinateReferenceSystem(layer.crs())
        # a Layers-panel symbol edit emits only repaintRequested; a checkbox or label edit, styleChanged;
        # Layer Properties ▸ Apply, rendererChanged
        outlines = self.layers.outlines
        for signal in (outlines.repaintRequested, outlines.styleChanged, outlines.rendererChanged):
            signal.connect(self._on_outline_style)
        for warning in info.warnings:
            self.message.emit(Qgis.MessageLevel.Warning, warning)
        self.sessionChanged.emit()
        self.featuresChanged.emit()

    def close(self) -> None:
        """End the session and remove its layers from the project."""
        self._restore_terrain()   # before the layer the terrain points at goes
        self._closing = True
        try:
            if self.layers is not None:
                self.layers.remove()
        finally:
            self._closing = False
        self._drop_session()

    def shutdown(self) -> None:
        """Close the session and stop listening to the project (plugin unload). Safe to call twice:
        the test suite shuts down every controller a test made, including ones the test already shut down."""
        self.close()
        for signal, slot in ((self.project.layersRemoved, self._on_layers_removed),
                             (self.project.cleared, self._drop_session),
                             (self.project.aboutToBeCleared, self._drop_session)):
            try:
                signal.disconnect(slot)
            except TypeError:       # already disconnected
                pass

    def add_drawn(self, tool: Tool, mode: Mode, geometry: QgsGeometry, crs, name: str | None = None) -> TerrainFeature | None:
        """Turn a drawn geometry (in `crs`) into a new feature with default values. Returns None,
        with a message, when the drawing cannot be used or no session is active."""
        if not self.has_dem:
            self.message.emit(Qgis.MessageLevel.Warning, NO_SESSION)
            return None
        try:
            wkb = to_dem_wkb(geometry, crs, self.dem_crs, mode)
        except ValueError as error:
            self.message.emit(Qgis.MessageLevel.Warning, str(error))
            return None
        except QgsCsException:
            self.message.emit(Qgis.MessageLevel.Warning, DRAWING_NOT_TRANSFORMED)
            return None
        feature = new_feature(tool, mode, wkb, self.stack.original.cell_size,
                              name=self._unique(name) if name else self._unique_name(tool))
        if not self._commit([*self._features, feature], UNDO_ADD.format(feature.name)):
            return None
        return feature

    def add_from_layer(self, tool: Tool, mode: Mode, layer, selected_only: bool = False) -> TerrainFeature | None:
        """One multi-part feature from a vector layer's features; each part keeps its own reference levels."""
        if not self.has_dem:
            self.message.emit(Qgis.MessageLevel.Warning, NO_SESSION)
            return None
        source = layer.getSelectedFeatures() if selected_only else layer.getFeatures()
        geometries = [QgsGeometry(f.geometry()) for f in source if not f.geometry().isEmpty()]
        if not geometries:
            self.message.emit(Qgis.MessageLevel.Warning,
                              NO_FEATURES_SELECTED if selected_only else EMPTY_LAYER)
            return None
        combined = geometries[0] if len(geometries) == 1 else QgsGeometry.collectGeometry(geometries)
        return self.add_drawn(tool, mode, combined, layer.crs(), name=layer.name())

    def set_geometry(self, fid: str, geometry: QgsGeometry, crs) -> bool:
        """Replace a feature's shape (brush and vertex editing); False, with a message, if unusable.
        A feature that no longer exists — deleted while a brush or vertex edit was still running —
        is reported like a missing session, never raised: this runs inside a Qt callback."""
        feature = next((f for f in self._features if f.id == fid), None)
        if not self.has_dem or feature is None:
            self.message.emit(Qgis.MessageLevel.Warning, NO_SESSION)
            return False
        try:
            wkb = to_dem_wkb(geometry, crs, self.dem_crs, feature.mode)
        except ValueError as error:
            self.message.emit(Qgis.MessageLevel.Warning, str(error))
            return False
        except QgsCsException:
            self.message.emit(Qgis.MessageLevel.Warning, DRAWING_NOT_TRANSFORMED)
            return False
        changes = {"geometry_wkb": wkb}
        rescaled = rescale_long_profile(feature, wkb, self.stack.original.cell_size)
        if rescaled is not feature.long_profile:
            changes["long_profile"] = rescaled
        if feature.section_line is not None and not from_wkb(feature.section_line).intersects(from_wkb(wkb)):
            changes["section_line"] = None   # a section across empty ground shows nothing: back to the default line
        self.update_feature(fid, **changes)
        return True

    def update_feature(self, fid: str, **changes) -> None:
        self._update(fid, changes, _describe)

    def update_profile(self, fid: str, **changes) -> None:
        """A change made in the Profiles panel: one undo step per drag or reset, never merged, and
        named as a profile change — even though a cross-profile drag also moves the width, slope
        and reach, which on their own would count as settings."""
        self._update(fid, changes, lambda feature, _changes: (UNDO_PROFILE.format(feature.name), None))

    def _update(self, fid: str, changes: dict, describe) -> None:
        self.cancel_preview()  # the committed result replaces whatever the overlay was showing
        feature = self.find(fid)
        if feature is None:
            return
        text, key = describe(feature, changes)
        self._commit([replace(f, **changes) if f.id == fid else f for f in self._features], text, key)

    def set_enabled(self, fid: str, enabled: bool) -> None:
        self.update_feature(fid, enabled=bool(enabled))

    def set_style(self, fid: str, style: str | None) -> None:
        """Give the feature its own symbol (symbol XML), or with None the default look. The terrain does
        not change; the steps of one editing session merge into one undo step."""
        self.update_feature(fid, style=style)

    def uses_feature_styles(self) -> bool:
        """Whether the map draws each feature with its own stored style: False once the user put another
        renderer on the outline layer. True with no session or no outline layer, where nothing else draws."""
        if self.layers is None or self.project.mapLayer(self.layers.outlines_id) is None:
            return True
        return self.layers.is_managed()

    def use_feature_styles(self) -> None:
        """Put the per-feature renderer back on the outline layer, built from the stored styles."""
        if self.layers is not None:
            with self._outline_writes():
                self.layers.use_feature_styles(self._style_entries())
        self.stylesChanged.emit()

    def display_symbol(self, fid: str) -> QgsSymbol | None:
        """The symbol the feature is shown with: what the user's own renderer draws for it while that is in
        charge and the feature is on the map, otherwise its stored style. None for no style of its own (the
        default look), or a feature that is gone."""
        feature = self.find(fid)
        if feature is None:
            return None
        if feature.enabled and not self.uses_feature_styles():
            return self.layers.drawn_symbol(fid)
        return from_xml(feature.style)

    def delete_feature(self, fid: str) -> None:
        feature = self.find(fid)
        if feature is not None:
            self._commit([f for f in self._features if f.id != fid], UNDO_DELETE.format(feature.name))

    def duplicate_feature(self, fid: str) -> TerrainFeature | None:
        """A copy of the feature, with every setting and profile, placed right after it in the list —
        after any copies already made of it, so they stay in the order they were made. It starts
        turned off: most tools measure from the terrain beneath them, so an identical copy on top
        would not be a copy at all — a raised path would come out twice as high. The user moves or
        reshapes it, then ticks it on. None when the feature no longer exists."""
        feature = self.find(fid)
        if feature is None:
            return None
        copy_name = COPY_NAME.format(feature.name)
        copy = replace(feature, id=uuid.uuid4().hex, name=self._unique(copy_name), enabled=False)
        index = self._features.index(feature) + 1
        while index < len(self._features) and self._features[index].name.startswith(copy_name):
            index += 1
        features = [*self._features[:index], copy, *self._features[index:]]
        if not self._commit(features, UNDO_DUPLICATE.format(feature.name)):
            return None
        return copy

    def reorder(self, ids) -> None:
        by_id = {f.id: f for f in self._features}
        if sorted(ids) != sorted(by_id):
            raise ValueError("reorder() needs every feature id exactly once")
        self._commit([by_id[i] for i in ids], UNDO_REORDER)

    def preview(self, fid: str, **changes) -> None:
        """Show what `changes` would do, without committing them.

        Called on every frame of a profile drag, so it is throttled: at most one recompute per
        PREVIEW_INTERVAL ms, with the latest request winning. The result goes to the overlay
        only — the working DEM, the files and the feature list are untouched until the drag is
        committed with `update_feature`."""
        if not self.has_dem or self.find(fid) is None:
            return
        self._pending = (fid, changes)
        if self._throttle.isActive():
            return
        self._run_preview()
        self._throttle.start()

    def cancel_preview(self) -> None:
        """Drop any pending preview and clear the overlay (drag cancelled or session ended)."""
        self._pending = None
        self._throttle.stop()
        self.previewCleared.emit()

    def long_section(self, fid: str) -> dict:
        """Reference terrain and design line for the profile editors, measured against the
        terrain as it stands just before this feature.

        Called from `ProfileDock._refresh`, which is a slot, and its chain reaches
        `geometry.split_parts` — which raises for a geometry it cannot use. An exception in a Qt
        callback takes QGIS down, so a failure is logged and reported as an empty section."""
        feature = self.find(fid)
        if feature is None or not self.has_dem:
            return EMPTY_SECTION.copy()
        try:
            before = self.stack.terrain_before(fid)
            terrain = before[1] if before is not None else None
            return long_section(feature, self.stack.working, terrain=terrain)
        except Exception:  # noqa: BLE001 — a profile panel must never take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            return EMPTY_SECTION.copy()

    def area_section(self, fid: str) -> dict:
        """The terrain just before and just after an area feature along its section line (spec §5.4):
        `{"stations", "before", "after", "line"}`, the line as WKB in the DEM CRS — the feature's own,
        or the default one through its middle. Reached from a slot, so a failure is logged and
        reported as an empty section, as for `long_section`."""
        line = self.section_line(fid)
        if line is None:
            return EMPTY_AREA_SECTION.copy()
        try:
            around = self.stack.terrain_around(fid, _line_window(self.stack.original, line))
            if around is None:
                return EMPTY_AREA_SECTION.copy()
            _window, before, after = around
            return {**section_along(line, before, after), "line": line}
        except Exception:  # noqa: BLE001 — a profile panel must never take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            return EMPTY_AREA_SECTION.copy()

    def section_line(self, fid: str) -> bytes | None:
        """The line an area feature's section runs along, as WKB in the DEM CRS: the one the user drew,
        or the default through the middle of the area. None for anything else. Never raises — the map
        shows this line from selection and change signals."""
        feature = self.find(fid)
        if feature is None or not self.has_dem or feature.mode is not Mode.AREA:
            return None
        try:
            return feature.section_line or default_section_line(feature, self.stack.original.cell_size)
        except Exception:  # noqa: BLE001 — a geometry the section cannot use shows no line
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
            return None

    def set_section_line(self, fid: str, geometry: QgsGeometry | None, crs=None) -> bool:
        """Make `geometry` (a line in `crs`) the line an area's section runs along, or with None go back
        to the default line. One undo step; the terrain does not change. False, with a message when the
        drawing cannot be used, and silently when the feature is not an area that still exists."""
        feature = self.find(fid)
        if not self.has_dem or feature is None or feature.mode is not Mode.AREA:
            return False
        wkb = None
        if geometry is not None:
            try:
                wkb = to_dem_wkb(geometry, crs, self.dem_crs, Mode.PATH)
            except ValueError as error:
                self.message.emit(Qgis.MessageLevel.Warning, str(error))
                return False
            except QgsCsException:
                self.message.emit(Qgis.MessageLevel.Warning, DRAWING_NOT_TRANSFORMED)
                return False
        self.update_feature(fid, section_line=wkb)
        return True

    def _run_preview(self) -> None:
        if self._pending is None:
            return
        fid, changes = self._pending
        self._pending = None
        features = [replace(f, **changes) if f.id == fid else f for f in self._features]
        try:
            result = self.stack.preview_for(fid, features)
        except Exception:  # noqa: BLE001 — a preview must never take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            return
        if result is None:
            return
        original = self.stack.original.subgrid(result.window)
        change = result.grid.data - original.data
        bounds = self.stack.original.window_bounds(result.window)
        self.previewUpdated.emit(fid, PreviewImage(bounds, change,
                                                   result.stats.get(fid, FeatureStats())))

    def _throttle_elapsed(self) -> None:
        """One interval passed: run the newest request, or stop until the next one arrives."""
        if self._pending is None:
            self._throttle.stop()
            return
        self._run_preview()

    def totals(self) -> tuple[float, float]:
        """(cut, fill) for the whole scenario, in cubic metres. `FeatureStack` keeps this running
        incrementally, so reading it does not rescan the whole grid on every commit."""
        if not self.has_dem:
            return (0.0, 0.0)
        return self.stack.totals

    @property
    def is_dirty(self) -> bool:
        """Whether there is work a save would keep: the features differ from the last save or load.
        Follows undo — undoing back to the saved state makes the scenario clean again — and a
        scenario that was never saved and has been emptied again has nothing to keep."""
        return not self.undo_stack.isClean() and bool(self._features or self._scenario_path)

    @property
    def scenario_path(self) -> str | None:
        """Where this scenario was last saved or loaded from, if anywhere."""
        return self._scenario_path

    def new_scenario(self) -> None:
        """Drop every feature and forget the file, keeping the DEM session as it is."""
        if not self._release_files():
            self.message.emit(Qgis.MessageLevel.Warning, FILES_NOT_RELEASED.format(folder=self.files.folder))
            return
        if self._set([]):
            self._forget_scenario()
            self.sessionChanged.emit()

    def save_scenario(self, path: str) -> None:
        """Write the scenario to `path`. Raises ScenarioError with a message for the user."""
        if not self.has_dem:
            raise ScenarioError(NO_SESSION)
        created = self._created if _same_file(path, self._scenario_path) else ""
        meta = scenario.dem_meta(self.info, self.stack.original, version=plugin_version(), created=created)
        written = scenario.save(path, self._features, meta, crs_wkt=getattr(self.info, "crs_wkt", ""))
        self._mark_scenario(path, written.created)
        self.undo_stack.setClean()
        self._place_files()
        self.sessionChanged.emit()

    def scenario_differences(self, path: str) -> list[str]:
        """How the DEM `path` was built on differs from the one in use, in words for the user;
        empty when they match. Raises ScenarioError when the file cannot be read."""
        if not self.has_dem:
            raise ScenarioError(NO_SESSION)
        return scenario.dem_meta(self.info, self.stack.original).differences(scenario.load_meta(path))

    def scenario_dem_source(self, path: str) -> str | None:
        """The DEM file the scenario at `path` was made on, when it is still there and is not the one in use —
        so opening can offer to start on it. None otherwise. Raises ScenarioError when the file cannot be read."""
        if not self.has_dem:
            raise ScenarioError(NO_SESSION)
        source = scenario.load_meta(path).dem_source
        if not source or not os.path.isfile(source) or _same_file(source, self.info.path):
            return None
        return source

    def open_scenario(self, path: str) -> None:
        """Replace the features with the scenario at `path`. Raises ScenarioError when the file
        cannot be read or its features cannot be applied — and then the current features, the file
        they belong to and their unsaved state stay as they were, so the next Save cannot write them
        over the scenario that failed to open; the working rasters may have moved to a temp folder.

        The rasters go beside the scenario only when it was made on this DEM. On another one they hold
        its features on this DEM's ground, not its saved terrain, so they stay in a temp folder until
        the next Save writes this DEM's record."""
        if not self.has_dem:
            raise ScenarioError(NO_SESSION)
        features, meta = scenario.load(path)
        if not self._release_files():
            raise ScenarioError(FILES_NOT_RELEASED.format(folder=self.files.folder))
        if not self._set(features):
            raise ScenarioError(SCENARIO_NOT_APPLIED)
        self.undo_stack.clear()   # the history belonged to the features that were just replaced
        self._mark_scenario(path, meta.created)
        if meta.dem_source and _same_file(meta.dem_source, self.info.path) \
                and not scenario.dem_meta(self.info, self.stack.original).differences(meta):
            self._place_files()
        self.sessionChanged.emit()

    def _mark_scenario(self, path: str, created: str) -> None:
        """The features now belong to the scenario file at `path`, first saved at `created`."""
        self._scenario_path = path
        self._created = created

    def _place_files(self) -> None:
        """Keep the working rasters beside the scenario just saved or opened (spec §8.2 step 3), in
        `<scenario>_files/`, so a QGIS project saved with these layers still finds them later."""
        target = scenario_files_folder(self._scenario_path)
        if self._files_owner is not None and _same_file(target, self.files.folder):
            self._files_owner, self._files_edited = self._scenario_path, False   # already there, and now saved
            return
        self._move_files(target, owner=self._scenario_path)

    def _release_files(self) -> bool:
        """Before the features are replaced (New, Open): move the working rasters off a scenario's folder
        into a temp one, or the next features would be written over that scenario's saved rasters. False
        when they cannot be moved; the caller tells the user."""
        return self._files_owner is None or self._move_files(None, owner=None)

    def _move_files(self, folder: str | None, owner: str | None) -> bool:
        """Move the working rasters to `folder` — a new temp folder when `owner` is None, otherwise the
        `_files` folder of the scenario file `owner` — and point the layers at them. The folder left
        behind is removed when it was a temp one; when it was a scenario's and the session edited it since
        that scenario was saved, it is put back to the saved terrain. A scenario folder that cannot be
        written, or that holds this session's own DEM, falls back to a temp folder, with a message
        (spec §9). A failed move to a temp folder says nothing: the caller knows what was refused.
        True when the rasters moved."""
        old_folder, old_owner, old_edited = self.files.folder, self._files_owner, self._files_edited
        if owner is not None and any(_same_file(self.info.path, os.path.join(folder, name))
                                     for name in (WORKING_NAME, CHANGE_NAME)):
            # a session started on a scenario's working raster: moving there would overwrite its own DEM
            return self._files_not_placed(FILES_ARE_THE_DEM.format(folder=folder), folder, old_owner, old_folder)
        try:
            if owner is None:
                folder = tempfile.mkdtemp(prefix="terrain_sketch_")
            self.files.move_to(folder)
        except Exception as error:  # noqa: BLE001 — a read-only share, a full disk, a file another program holds
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
            if owner is None:
                if folder is not None:
                    shutil.rmtree(folder, ignore_errors=True)
                return False
            return self._files_not_placed(FILES_NOT_MOVED.format(folder=folder, error=error), folder, old_owner,
                                          old_folder)
        self._files_owner, self._files_edited = owner, False
        if self.layers is not None:
            self.layers.repoint(self.files.working_path, self.files.change_path)
        if old_owner is None:
            shutil.rmtree(old_folder, ignore_errors=True)
        elif old_edited:
            self._restore_saved_rasters(old_owner, old_folder)
        return True

    def _files_not_placed(self, text: str, folder: str, old_owner: str | None, old_folder: str) -> bool:
        """The rasters could not go to the scenario folder `folder`. Off another scenario's folder they go to a
        temp one, not left writing into that scenario's rasters; when even that fails they stay in `old_folder`
        until the session ends, which puts it back to its saved scenario. Tells the user which. Always False."""
        if old_owner is not None and not self._move_files(None, owner=None):
            text = FILES_KEPT_IN_OLD_FOLDER.format(folder=folder, old_folder=old_folder)
        self.message.emit(Qgis.MessageLevel.Warning, text)
        return False

    def _restore_saved_rasters(self, path: str, folder: str) -> None:
        """Put a scenario's `_files` rasters back to its saved terrain, recomputed from the scenario file:
        the session edited them without saving, and a QGIS project saved with those layers must not show
        changes the user discarded. A failure is a message, never an exception."""
        try:
            features, _meta = scenario.load(path)
            stack = FeatureStack(self.stack.original)
            window = stack.update(features)
            files = WorkingFiles(folder, self.stack.original, self.info)
            if window is not None:
                files.write(window, stack.working)
        except Exception as error:  # noqa: BLE001 — reached from buttons and project signals
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
            self.message.emit(Qgis.MessageLevel.Warning, FILES_NOT_RESTORED.format(folder=folder, error=error))

    def _forget_scenario(self) -> None:
        self._scenario_path = None
        self._created = ""
        self.undo_stack.clear()

    def show_in_3d(self) -> bool:
        """Make the modified DEM the project's terrain, at true vertical scale, so a 3D view shows
        the sketched landscape (spec §8.5). The terrain it replaces is kept and put back when the
        session ends. False, with a message, when there is no Modified DEM layer to show."""
        layer = self.project.mapLayer(self.layers.working_id) if self.layers is not None else None
        if layer is None:
            self.message.emit(Qgis.MessageLevel.Warning, VIEW_3D_NO_LAYER)
            return False
        properties = self.project.elevationProperties()
        current = properties.terrainProvider()
        if self._terrain_before is None or not self._terrain_is_ours(current):
            self._terrain_before = current.clone()   # a terrain the user chose since the last press is theirs
        provider = QgsRasterDemTerrainProvider()
        provider.setLayer(layer)
        provider.setScale(1.0)
        properties.setTerrainProvider(provider)
        return True

    def _restore_terrain(self) -> None:
        """Put back the terrain show_in_3d replaced — unless the user has since chosen another one
        themselves, which is theirs to keep."""
        before, self._terrain_before = self._terrain_before, None
        if before is None:
            return
        properties = self.project.elevationProperties()
        if self._terrain_is_ours(properties.terrainProvider()):
            properties.setTerrainProvider(before)

    def _terrain_is_ours(self, provider) -> bool:
        """Whether `provider` is the one show_in_3d set: a DEM terrain on the Modified DEM layer, or
        on a layer that has gone. Only ours can have lost its layer through the session's own
        removal, and a terrain on nothing is worth nothing to keep."""
        if not isinstance(provider, QgsRasterDemTerrainProvider):
            return False
        layer = provider.layer()
        return layer is None or (self.layers is not None and layer.id() == self.layers.working_id)

    @property
    def dem_is_integer(self) -> bool:
        """Whether the session's DEM stores whole numbers — its export is float32 regardless."""
        return self.info is not None and self.info.integer

    def export_dem(self, path: str) -> None:
        """Write the modified DEM to `path`; raises RuntimeError without a session, or if `path`
        would overwrite the source DEM or one of this session's working files."""
        if not self.has_dem:
            raise RuntimeError(NO_SESSION)
        target = os.path.realpath(path)
        protected = {os.path.realpath(self.info.path), os.path.realpath(self.files.working_path),
                    os.path.realpath(self.files.change_path)}
        if target in protected:
            raise RuntimeError(EXPORT_OVER_SOURCE)
        export_dem(path, self.stack.working, self.info)

    def _set(self, features) -> bool:
        """Apply `features`; False, with the previous list kept, when the engine refuses them."""
        features = list(features)
        try:
            window = self.stack.update(features)
        except Exception:  # noqa: BLE001 — never let an engine error take QGIS down or desync the feature list
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Sketch could not update the terrain; "
                                                          "see the 'Terrain Sketch' log tab for details.")
            self.featuresChanged.emit()
            return False
        self._features = features
        try:
            if window is not None:
                self._files_edited = True
                self.files.write(window, self.stack.working)
                self.layers.refresh()
            with self._outline_writes():
                self.layers.set_outlines(self._outline_items())
                self.layers.apply_styles(self._style_entries())
        except Exception:  # noqa: BLE001 — never let a file/layer error take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Sketch could not update the terrain; "
                                                          "see the 'Terrain Sketch' log tab for details.")
        self.featuresChanged.emit()
        return True

    def _commit(self, features, text: str, key=None) -> bool:
        """Apply a change the user made and record it for undo. A change that leaves the list as it
        was records nothing, so it neither costs an undo step nor marks the scenario unsaved."""
        before, after = tuple(self._features), tuple(features)
        if after == before:
            self.featuresChanged.emit()   # a view showing values the change normalised away re-syncs
            return True
        if not self._set(after):
            return False
        self.undo_stack.push(FeatureListChange(self._restore, before, after, text, key))
        return True

    def _restore(self, features) -> None:
        """Undo or redo. Runs inside QUndoStack from a button or a key, so it never raises: `_set`
        already turns an engine failure into a message. The stack moves its index even when the
        engine refuses the list, so the saved state is forgotten then: an unchanged list that
        happened to land on the saved step must not be reported as saved."""
        self.cancel_preview()
        if self.stack is not None:
            if not self._set(features):
                self.undo_stack.resetClean()
            self.featuresRestored.emit()

    def _outline_items(self) -> list:
        items = []
        for f in self._features:
            if not f.enabled:
                continue
            geometry = from_wkb(f.geometry_wkb)
            if f.mode is Mode.PATH:
                width = max(f.width, self.stack.original.cell_size)
                geometry = geometry.buffer(width / 2.0, 8, Qgis.EndCapStyle.Flat, Qgis.JoinStyle.Miter, 2.0)
            items.append((f.id, f.name, TOOL_LABELS[f.tool], geometry))
        return items

    def _style_entries(self) -> list:
        """(feature id, name, style) for each feature on the outline layer, in list order."""
        return [(f.id, f.name, f.style) for f in self._features if f.enabled]

    @contextmanager
    def _outline_writes(self):
        """Around every write the controller makes to the outline layer: each one repaints the layer or
        emits styleChanged at once, and `_on_outline_style` must not take that for the user's edit — inside
        an undo it would read the old symbols back and commit them again."""
        self._writing_outlines = True
        try:
            yield
        finally:
            self._writing_outlines = False

    def _on_outline_style(self, *_args) -> None:
        """The outline layer was restyled or repainted: an edit made in QGIS's own symbology — the Layers
        panel, Layer Properties — is read back from the event loop (see `_style_read`). Reached from layer
        signals, so it never raises."""
        if self._writing_outlines or self.stack is None or self.layers is None:
            return
        try:
            self._style_read.start()
        except Exception:  # noqa: BLE001 — a layer signal must never take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _read_outline_styles(self) -> None:
        """The edit `_on_outline_style` saw comes back to the features as one undo step. The session or the
        outline layer may have gone since; a timer slot, so it never raises."""
        if self.stack is None or self.layers is None:
            return
        try:
            if self.layers.is_managed():   # False once the outline layer is gone
                self._take_outline_styles()
            self.stylesChanged.emit()
        except Exception:  # noqa: BLE001 — a timer slot must never take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _take_outline_styles(self) -> None:
        """Commit, as one change, each category's symbol and label that differ from its feature's style and
        name. Categories of no enabled feature are ignored, and so are blank labels and a label that is just
        the feature id — what Classify labels each category with, not a name the user typed. A feature with
        no category keeps its style, and gets its category back on the next update."""
        styles = self.layers.read_styles()
        features, changed = [], []
        for feature in self._features:
            if feature.enabled and feature.id in styles:
                label, style = styles[feature.id]
                changes = {}
                # stripped both sides: a name with a trailing space ("Dike " from From layer) is no rename
                if label.strip() not in ("", feature.id, feature.name.strip()):
                    changes["name"] = label.strip()
                if style != style_of(from_xml(feature.style)):  # compared as the layer would save it
                    changes["style"] = style
                if changes:
                    changed.append((feature, set(changes)))
                    feature = replace(feature, **changes)
            features.append(feature)
        if not changed:
            return
        first, fields = changed[0]
        if len(changed) == 1 and fields == {"style"}:
            text = UNDO_STYLE.format(first.name)
        elif len(changed) == 1 and fields == {"name"}:
            text = UNDO_RENAME.format(first.name)
        else:
            text = UNDO_STYLES
        self.cancel_preview()  # as for any committed change: the overlay must not outlive it
        self._commit(features, text)

    def _unique_name(self, tool: Tool) -> str:
        names = {f.name for f in self._features}
        n = 1
        while f"{TOOL_LABELS[tool]} {n}" in names:
            n += 1
        return f"{TOOL_LABELS[tool]} {n}"

    def _unique(self, name: str) -> str:
        names = {f.name for f in self._features}
        if name not in names:
            return name
        n = 2
        while f"{name} {n}" in names:
            n += 1
        return f"{name} {n}"

    def _drop_session(self) -> None:
        self._offer_save_before_discard()
        self.cancel_preview()  # a queued frame must not fire against a session that is gone
        self._style_read.stop()  # nor a read-back of the outline layer
        had_session = self.stack is not None
        if had_session and self._files_owner is not None and self._files_edited:
            self._restore_saved_rasters(self._files_owner, self.files.folder)   # the edits were not saved
        self._forget_scenario()  # a Save after this must not write the next session over this file
        self._terrain_before = None  # the project is being cleared, or close() has already put it back
        # A scenario's `_files` folder is the scenario's, and stays; only a temp folder goes with the session
        folder = self.files.folder if self.files is not None and self._files_owner is None else None
        self.stack = self.info = self.files = self.layers = None
        self._files_owner, self._files_edited = None, False
        self.dem_layer_id = None
        self.dem_crs = QgsCoordinateReferenceSystem()
        self._features = []
        if folder is not None:
            # Each session writes a DEM-sized working and change GeoTIFF. Without this every Start
            # leaves both behind in the temp folder. Errors are ignored: on Windows a layer QGIS has
            # not released yet keeps its file locked, and a leftover file is not worth a message.
            shutil.rmtree(folder, ignore_errors=True)
        if had_session:
            self.sessionChanged.emit()
            self.featuresChanged.emit()

    def _offer_save_before_discard(self) -> None:
        if self.before_discard is None or self.stack is None or not self.is_dirty:
            return
        try:
            self.before_discard()
        except Exception:  # noqa: BLE001 — reached from project and layer signals; must not take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _on_layers_removed(self, items) -> None:
        # `layers` is still None while set_dem builds the group, and a group that fails half way
        # removes its own layers again — which lands here, inside a Qt signal
        if self._closing or self.stack is None or self.layers is None:
            return
        ids = {item if isinstance(item, str) else item.id() for item in items}
        if self.layers.working_id in ids:
            self._restore_terrain()   # the terrain now shows nothing; checked first, as close() needs it too
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)


def _line_window(grid, line: bytes):
    """The cells a section line crosses, so the terrain it samples is replayed along all of it."""
    box = from_wkb(line).boundingBox()
    return grid.window_for_bbox(box.xMinimum(), box.yMinimum(), box.xMaximum(), box.yMaximum(), 1)


def _same_file(path: str, other: str | None) -> bool:
    """Whether two spellings of a path name one file — "flood.gpkg" typed again from another folder,
    say — so a save back to the scenario's own file keeps the date it was first created."""
    if other is None:
        return False
    return os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(other))


PROFILE_FIELDS = frozenset({"cross_left", "cross_right", "long_profile"})


def _describe(feature, changes) -> tuple[str, object]:
    """The undo text for `changes` to `feature`, and the merge key — set only for settings and the
    style, so the steps of one spin box or one symbol editor become one undo step while a rename, a
    toggle, a reshaped outline or a dragged profile each stay their own."""
    fields = frozenset(changes)
    if fields == {"style"}:
        return UNDO_STYLE.format(feature.name), (feature.id, fields)
    if fields == {"name"}:
        return UNDO_RENAME.format(feature.name), None
    if fields == {"enabled"}:
        return (UNDO_TURN_ON if changes["enabled"] else UNDO_TURN_OFF).format(feature.name), None
    if "geometry_wkb" in fields:
        return UNDO_SHAPE.format(feature.name), None
    if fields == {"section_line"}:
        return UNDO_SECTION_LINE.format(feature.name), None
    if fields <= PROFILE_FIELDS:
        return UNDO_PROFILE.format(feature.name), None
    return UNDO_SETTINGS.format(feature.name), (feature.id, fields)
