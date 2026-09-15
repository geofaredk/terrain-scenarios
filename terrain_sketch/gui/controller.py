"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import configparser
import os
import pathlib
import shutil
import tempfile
import traceback
import uuid
from dataclasses import replace
from typing import NamedTuple

from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsMessageLog, QgsProject,
                       QgsRasterDemTerrainProvider)
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
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from ..qgis_io.scenario import ScenarioError
from .help_texts import (COPY_NAME, DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER,
                         NO_FEATURES_SELECTED, NO_SESSION, RESULT_LAYER_REMOVED, SCENARIO_NOT_APPLIED,
                         SESSION_ENDED_DEM_REMOVED, TOOL_LABELS, UNDO_ADD, UNDO_DELETE, UNDO_DUPLICATE,
                         UNDO_PROFILE, UNDO_RENAME, UNDO_REORDER, UNDO_SETTINGS, UNDO_SHAPE, UNDO_TURN_OFF,
                         UNDO_TURN_ON, VIEW_3D_NO_LAYER)
from .undo import FeatureListChange

LOG_TAG = "Terrain Sketch"


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

    def __init__(self, project: QgsProject, parent=None):
        super().__init__(parent)
        self.project = project
        self.stack = None
        self.info = None
        self.files = None
        self.layers = None
        self.dem_layer_id = None
        self.dem_crs = QgsCoordinateReferenceSystem()
        self._features: list[TerrainFeature] = []
        self._closing = False
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
        try:
            self.layers = SketchLayers(self.project, layer, self.files.working_path, self.files.change_path)
        except Exception as error:  # noqa: BLE001 — never leave a half-built session behind
            self._drop_session()
            raise DemError(f"Terrain Sketch could not create its layers: {error}") from error
        self.dem_layer_id = layer.id()
        self.dem_crs = QgsCoordinateReferenceSystem(layer.crs())
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
        feature = self.find(fid)
        if feature is None or not self.has_dem or feature.mode is not Mode.AREA:
            return EMPTY_AREA_SECTION.copy()
        try:
            grid = self.stack.original
            line = feature.section_line or default_section_line(feature, grid.cell_size)
            if line is None:
                return EMPTY_AREA_SECTION.copy()
            around = self.stack.terrain_around(fid, _line_window(grid, line))
            if around is None:
                return EMPTY_AREA_SECTION.copy()
            _window, before, after = around
            return {**section_along(line, before, after), "line": line}
        except Exception:  # noqa: BLE001 — a profile panel must never take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            return EMPTY_AREA_SECTION.copy()

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
        self.sessionChanged.emit()

    def scenario_differences(self, path: str) -> list[str]:
        """How the DEM `path` was built on differs from the one in use, in words for the user;
        empty when they match. Raises ScenarioError when the file cannot be read."""
        if not self.has_dem:
            raise ScenarioError(NO_SESSION)
        return scenario.dem_meta(self.info, self.stack.original).differences(scenario.load_meta(path))

    def open_scenario(self, path: str) -> None:
        """Replace the features with the scenario at `path`. Raises ScenarioError when the file
        cannot be read or its features cannot be applied — and then nothing has changed: the
        current features, the file they belong to and their unsaved state all stay as they were,
        so the next Save cannot write them over the scenario that failed to open."""
        if not self.has_dem:
            raise ScenarioError(NO_SESSION)
        features, meta = scenario.load(path)
        if not self._set(features):
            raise ScenarioError(SCENARIO_NOT_APPLIED)
        self.undo_stack.clear()   # the history belonged to the features that were just replaced
        self._mark_scenario(path, meta.created)
        self.sessionChanged.emit()

    def _mark_scenario(self, path: str, created: str) -> None:
        """The features now belong to the scenario file at `path`, first saved at `created`."""
        self._scenario_path = path
        self._created = created

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

    def set_hillshade_visible(self, visible: bool) -> None:
        if self.layers is not None:
            self.layers.set_hillshade_visible(visible)

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
                self.files.write(window, self.stack.working)
                self.layers.refresh()
            self.layers.set_outlines(self._outline_items())
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
            items.append((f.name, TOOL_LABELS[f.tool], geometry))
        return items

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
        had_session = self.stack is not None
        self._forget_scenario()  # a Save after this must not write the next session over this file
        self._terrain_before = None  # the project is being cleared, or close() has already put it back
        folder = self.files.folder if self.files is not None else None
        self.stack = self.info = self.files = self.layers = None
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
    """The undo text for `changes` to `feature`, and the merge key — set only for settings, so the
    steps of one spin box become one undo step while a rename, a toggle, a reshaped outline or a
    dragged profile each stay their own."""
    fields = frozenset(changes)
    if fields == {"name"}:
        return UNDO_RENAME.format(feature.name), None
    if fields == {"enabled"}:
        return (UNDO_TURN_ON if changes["enabled"] else UNDO_TURN_OFF).format(feature.name), None
    if "geometry_wkb" in fields:
        return UNDO_SHAPE.format(feature.name), None
    if fields <= PROFILE_FIELDS:
        return UNDO_PROFILE.format(feature.name), None
    return UNDO_SETTINGS.format(feature.name), (feature.id, fields)
