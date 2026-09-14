# Terrain Sketch — Plan 7: Undo, the 3D View and the Known Crash Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the spec's sixth milestone. Every feature-list change can be undone and redone from buttons or Ctrl+Z. The modified DEM can be shown in a 3D view. The list gets Rename and Duplicate, and Export DEM offers to add its result to the project. First, close the crash paths and file leftovers that earlier reviews found.

**Architecture:** Undo is snapshot-based. `FeatureListChange` (a `QUndoCommand` in `gui/undo.py`) keeps the whole immutable feature list before and after a change, and undo or redo hand a list back to `SketchController._set`, which recomputes only the changed window. Every user edit goes through `SketchController._commit`. The saved state of a scenario is the `QUndoStack`'s clean state. Ctrl+Z reaches the stack through an event filter, `UndoKeys`, on the Terrain Sketch panels and on the map canvas; it claims the key during `ShortcutOverride` so it wins over QGIS's own layer-editing undo, but only there. The 3D view replaces the project's terrain provider with one on the Modified DEM layer and puts the previous one back when the session ends.

**Tech Stack:** QGIS 4.2.2 Python API (PyQt6 via `qgis.PyQt`, Qt 6.11: `QUndoStack`, `QToolBar`), `QgsRasterDemTerrainProvider`, GDAL 3.13, numpy; pytest (dev-only) with a headless `QgsApplication`.

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-sketch-design.md` — §7.2 (the list's context menu: Rename, Duplicate, Zoom to, Delete; the header's Undo, Redo and 3D view), §7.4 (undo), §8.5 (export options and the 3D view), §9 (errors never take QGIS down), §11 milestone 6. Plans 1-6 are merged on `main`; **read the Plan 6 addendum first**. The deferred backlog that is not here moves to Plan 8 (table at the end).

## Global Constraints

- Target QGIS 4.x (Qt6) only. Import Qt through `qgis.PyQt` and always use fully scoped Qt6 enums.
- Native look (spec §7.1): only standard Qt/QGIS widgets and palette colours, QGIS theme icons via `QgsApplication.getThemeIcon`, **no stylesheets**. The UI inherits the active QGIS theme, light or dark.
- `terrain_sketch/core/` and `terrain_sketch/model/` never import `qgis` or `PyQt`; `qgis_io/` never imports `gui/`. Widgets never call the engine, files or layers directly — only `SketchController`.
- Errors never take QGIS down: user problems become message-bar messages; unexpected errors are caught and logged. **An exception raised inside a Qt callback aborts the interpreter** — slots, signal handlers, button clicks, menu actions, event filters and map-tool callbacks included. `SketchController.feature()` raises for an unknown id; use `find()` from anything reachable from Qt.
- Undo covers feature-list edits only (spec §7.4). New, Open, Start on another DEM, closing the project, removing the DEM and unloading the plugin clear the history, so each must still find the work saved or ask first. A save that fails must leave the previous file readable.
- Every user-facing string lives in `gui/help_texts.py`; widget captions use `self.tr("literal")`. Never call `tr()` on a non-literal. English only.
- Package modules start with a one-line docstring and use `from __future__ import annotations` where they have type hints; test modules need neither. 4-space indentation. Imports sorted within their group.
- Tests run only through `scripts/test.sh`. Never run `scripts/dev_install.sh`. In a test hook reached from a Qt signal or a button click, **record the call and assert afterwards — never `pytest.fail()` inside it**: `Failed` is a `BaseException`, passes the plugin's `except Exception` guards and aborts the whole run.
- GDAL runs with exceptions enabled throughout the plugin. Close GDAL datasources explicitly with `Close()`.

## Decisions made while prototyping (read before implementing)

Every claim below about QGIS or Qt behaviour was probed headless against QGIS 4.2.2, not taken from documentation.

- **Scope.** The Plan 6 backlog held about 30 items. This plan takes the rest of milestone 6 (undo, 3D view), the spec's list and export options, and every crash or file-leftover item. The profile-editor and guidance polish moves to Plan 8.
- **Undo keeps whole lists, not diffs.** Features are frozen dataclasses, so a list before and after a change share every untouched feature. Undo hands a list back to `_set`, which runs the same windowed recompute as an edit; a test undoes and redoes a long run of every kind of change and compares the terrain with a from-scratch replay after each step.
- **A change that changes nothing records nothing.** `_commit` compares the lists first, so an identical edit costs no undo step and no longer marks the scenario unsaved (a Plan 6 deferral).
- **The steps of one setting merge; everything else stays its own step.** Changes to the same settings of the same feature share a merge key, so a spin box's steps undo in one go. Renames, toggles, shape edits and profile drags do not merge. Qt never merges into the step a scenario was saved at, and a merge that returns to where it started removes the step (both probed).
- **Saved = the undo stack's clean state.** Save marks it clean; New, Open and Start clear it. Undoing back to the saved state makes the scenario clean again. Deleting every feature of a saved scenario is now unsaved work that is asked about before it is dropped (a Plan 6 deferral).
- **An undo the engine refuses leaves the history index moved.** `_set` still turns the failure into a message and a log entry, and the list stays as it was. The engine accepted that exact list before, so this needs a bug elsewhere; it is not worth rolling the stack back for.
- **Ctrl+Z is claimed by an event filter, not a shortcut.** QGIS binds the same keys in its main window, and two shortcuts for one key cancel each other out. `UndoKeys` accepts `ShortcutOverride` and acts on the key press that follows. Probed: this beats a window-level Ctrl+Z action; a focused spin box or line edit keeps Ctrl+Z for its own text, as everywhere in Qt; `QgsMapCanvas` does **not** call a map tool's `shortcutEvent` for it in 4.2.2, so the canvas needs its own filter, which only claims the keys while the active map tool is a `SketchTool`. The filter is installed on the main panel, on the Profiles panel and on the canvas.
- **After an undo or redo, tools bound to the old list stop.** A vertex edit and a brush stroke that extends a feature hold its old outline and would put it back on their next change, so both end. Drawing a new feature does not depend on the list and carries on. The Properties page reloads its fields only after an undo or redo — reloading on every change would rewrite a spin box while the user types in it.
- **The header is a toolbar.** Undo, Redo and 3D view took the header row from 367 px to more than 437 px of minimum width, measured offscreen. In a `QToolBar` — as in QGIS's own panels — buttons that do not fit move behind », so the header no longer sets the panel's width. The Hillshade checkbox moves up beside Start; spec §7.2 counts both rows as the header.
- **A duplicate starts turned off.** Most tools measure from the terrain beneath them, so an identical copy on top of a Raise path raises the dike a second time (a prototype test caught this). The copy sits right after the original, named "… (copy)", and changes nothing until the user moves or reshapes it and ticks it on.
- **The 3D view uses the project's terrain.** `show_in_3d` sets a `QgsRasterDemTerrainProvider` on the Modified DEM layer at scale 1 and remembers the provider it replaced. Closing the session puts it back — unless the user has since chosen another terrain, which is theirs to keep. A new 3D view opens through `iface.createNewMapCanvas3D`; if that returns nothing or raises, QGIS's own `mActionNew3DMapCanvas` action is triggered; failing both, a message says how to open one by hand. The action's object name cannot be verified headless and is on the manual checklist.
- **"Add to project" is a button on the export message.** Spec §8.5 describes a dialog option, but the file dialog is the platform's own and cannot carry one, so the success message offers it, as the Reproject… message already does. An integer source DEM gets a note both in the dialog title (where the platform shows it) and in the message. Integer detection uses the band array's numpy dtype: these GDAL bindings have no `DataTypeIsInteger`.
- **Crash paths closed.** `_zoom_to` (deferred since Plan 2) and the shape transform behind Edit shape and Brush can raise `QgsCsException` inside a slot; each now shows a message. Writing the test for a half-built layer group exposed another: `SketchLayers` cleaning up after itself removes layers, which reaches `_on_layers_removed` while `layers` is still `None` — an `AttributeError` inside a Qt signal. The slot now returns in that state.
- **Working files are removed with their session**, including after a Start whose working files could not be written. Errors are ignored: on Windows a file QGIS has not released yet stays behind, which is not worth a message.

## File Structure

| File | Responsibility |
|---|---|
| `terrain_sketch/gui/undo.py` | `FeatureListChange` (one undoable change) and `UndoKeys` (Ctrl+Z where it belongs) |
| `terrain_sketch/gui/controller.py` | `undo_stack`, `_commit`, `duplicate_feature`, `show_in_3d`, `dem_is_integer`; working-folder and terrain clean-up |
| `terrain_sketch/gui/main_dock.py` | The header toolbar (Undo, Redo, 3D view), the list's context menu, export options, guarded transforms |
| `terrain_sketch/gui/properties_page.py` | The title follows a rename |
| `terrain_sketch/gui/help_texts.py` | Undo texts, 3D and export messages |
| `terrain_sketch/qgis_io/layers.py` | A layer group that fails half way removes itself |
| `terrain_sketch/qgis_io/raster_io.py` | `DemInfo.integer`, `WorkingFiles.folder` |
| `terrain_sketch/qgis_io/scenario.py` | Enables OGR exceptions itself (Plan 6 deferral) |
| `scripts/build_zip.sh` | Says when `zip` is missing (Plan 6 deferral) |

---

### Task 1: Crash paths and file safety

Close the crash paths and leftovers the earlier reviews found, plus three Plan 6 loose ends: the `cubic_metres` type hint, `ogr.UseExceptions()` in `scenario.py`, and the missing-`zip` message.

**Files:**
- Modify: `scripts/build_zip.sh`, `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/qgis_io/layers.py`, `terrain_sketch/qgis_io/raster_io.py`, `terrain_sketch/qgis_io/scenario.py`
- Test: `tests/core/test_build_zip.py`, `tests/qgis/test_file_safety.py`

**Interfaces:**
- Consumes: `SketchController.find`, `feature_geometry`, `set_dem`, `close`; `MainDock._to_canvas`, `_export_dialog`, `confirm`; `SketchLayers`; `WorkingFiles`.
- Produces: `help_texts.SHAPE_NOT_TRANSFORMED`, `EXPORT_REPLACE`; `WorkingFiles.folder`; `SketchLayers` removes a half-built group before re-raising; `_on_layers_removed` ignores removals while `layers is None`; a session's working folder is deleted when the session is dropped.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_build_zip.py`
```python
"""The installable ZIP: what a user receives when they install from it."""
import configparser
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_zip.sh"


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("zip")
    result = subprocess.run([str(SCRIPT), str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    path = Path(result.stdout.strip())
    assert path.is_file(), result.stdout
    with zipfile.ZipFile(path) as archive:
        return path, archive.namelist()


def test_the_zip_is_named_for_the_version_in_metadata(built):
    path, _names = built
    parser = configparser.ConfigParser()
    parser.read(ROOT / "terrain_sketch" / "metadata.txt")
    assert path.name == f"terrain_sketch-{parser.get('general', 'version')}.zip"


def test_everything_sits_under_one_folder_qgis_can_install(built):
    _path, names = built
    assert names, "the archive is empty"
    assert all(name.startswith("terrain_sketch/") for name in names), \
        [n for n in names if not n.startswith("terrain_sketch/")]
    assert "terrain_sketch/metadata.txt" in names
    assert "terrain_sketch/__init__.py" in names


def test_the_plugin_ships_what_it_needs_at_runtime(built):
    _path, names = built
    for needed in ("terrain_sketch/plugin.py", "terrain_sketch/gui/main_dock.py",
                   "terrain_sketch/core/engine.py", "terrain_sketch/qgis_io/scenario.py"):
        assert needed in names, needed
    assert any(name.endswith(".svg") for name in names), "the illustrations were left out"


def test_the_user_does_not_receive_our_tests_or_caches(built):
    _path, names = built
    assert not [n for n in names if "__pycache__" in n or n.endswith((".pyc", ".pyo"))]
    assert not [n for n in names if ".DS_Store" in n]
    assert not [n for n in names if "/tests/" in n or n.startswith("tests/")]
    assert not [n for n in names if "/.devdeps/" in n or "/scripts/" in n]


def fake_repo(tmp_path, metadata="[general]\nversion=1.0\n", init=True):
    """A minimal repo the script can be pointed at, so its refusals can be exercised."""
    fake = tmp_path / "repo"
    (fake / "terrain_sketch").mkdir(parents=True)
    (fake / "scripts").mkdir()
    script = fake / "scripts" / "build_zip.sh"
    script.write_bytes(SCRIPT.read_bytes())
    script.chmod(0o755)
    if metadata is not None:
        (fake / "terrain_sketch" / "metadata.txt").write_text(metadata)
    if init:
        (fake / "terrain_sketch" / "__init__.py").write_text("")
    return script


def test_a_missing_metadata_file_is_refused_by_name(tmp_path):
    script = fake_repo(tmp_path, metadata=None)
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "metadata.txt missing" in result.stderr    # the script's own message, not sed's
    assert not list(tmp_path.glob("*.zip"))


def test_a_plugin_without_an_init_file_is_refused(tmp_path):
    script = fake_repo(tmp_path, init=False)
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "__init__.py missing" in result.stderr
    assert not list(tmp_path.glob("*.zip"))


def test_a_metadata_file_without_a_version_is_refused(tmp_path):
    """The version drives the file name, so building without one must stop, not ship
    `terrain_sketch-.zip` that every later build silently overwrites."""
    script = fake_repo(tmp_path, metadata="[general]\nname=Terrain Sketch\n")
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "no version=" in result.stderr
    assert not list(tmp_path.glob("*.zip"))


def test_a_relative_output_directory_still_lands_in_the_caller_s_cwd(tmp_path):
    """`.` is resolved against the caller's cwd, not against the staging directory the script
    later `cd`s into — otherwise the ZIP is written where the EXIT trap deletes it, and the
    script prints a path and exits 0 with nothing at it."""
    result = subprocess.run([str(SCRIPT), "."], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    printed = Path(result.stdout.strip())
    assert printed.is_file(), f"printed {printed} but it does not exist"
    assert list(tmp_path.glob("*.zip")), "no ZIP landed in the caller's directory"


def test_a_missing_output_directory_is_refused_before_anything_is_built(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = subprocess.run([str(SCRIPT), str(missing)], capture_output=True, text=True)
    assert result.returncode != 0
    assert not missing.exists()
    assert not list(tmp_path.glob("*.zip"))


def test_an_editor_swap_file_does_not_ship(tmp_path):
    script = fake_repo(tmp_path)
    (script.parents[1] / "terrain_sketch" / ".plugin.py.swp").write_text("swap")
    out = tmp_path / "out"
    out.mkdir()
    result = subprocess.run([str(script), str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    path = Path(result.stdout.strip())
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    assert not [n for n in names if n.endswith(".swp")], names


def test_a_machine_without_zip_is_told_so(tmp_path):
    """Everything the script needs except `zip` is on PATH; the message names what is missing
    instead of bash's generic "command not found" from half way through."""
    import shutil
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("bash", "dirname", "sed", "head", "mktemp", "tar", "rm"):
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    out = tmp_path / "out"
    out.mkdir()
    result = subprocess.run([str(bin_dir / "bash"), str(SCRIPT), str(out)], capture_output=True, text=True,
                            env={"PATH": str(bin_dir)})
    assert result.returncode != 0
    assert "zip command is not installed" in result.stderr
    assert not list(out.glob("*.zip"))
```

**File:** `tests/qgis/test_file_safety.py`
```python
"""Paths that used to crash QGIS or leave files behind: projection failures, replaced exports,
temporary working files and a half-built layer group."""
import os
from unittest import mock

import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui import controller as controller_module
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import EXPORT_REPLACE, SHAPE_NOT_TRANSFORMED
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.gui.selection import Method
from terrain_sketch.qgis_io.layers import GROUP_NAME
from terrain_sketch.qgis_io.raster_io import DemError


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def messages(iface) -> list[str]:
    return [call[0][1] for call in iface.messageBar().pushMessage.call_args_list]


def test_zooming_to_a_feature_whose_outline_cannot_be_projected_is_a_message(tmp_path):
    iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    with mock.patch.object(QgsCoordinateTransform, "transformBoundingBox", side_effect=QgsCsException("forced")):
        dock._zoom_to(dike.id)                      # the context-menu action's slot
    assert SHAPE_NOT_TRANSFORMED in messages(iface)


def test_zooming_to_a_feature_that_has_gone_does_nothing(tmp_path):
    iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    extent = iface.mapCanvas().extent()
    c.delete_feature(dike.id)
    dock._zoom_to(dike.id)
    assert iface.mapCanvas().extent() == extent


def test_editing_a_shape_that_cannot_be_projected_is_a_message_not_a_crash(tmp_path):
    iface, c, dock = panel(tmp_path)
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    with mock.patch.object(QgsGeometry, "transform", side_effect=QgsCsException("forced")):
        dock.edit_button.setChecked(True)          # toggled -> slot; an exception there aborts QGIS
    assert dock.edit_tool is None and not dock.edit_button.isChecked()
    assert SHAPE_NOT_TRANSFORMED in messages(iface)


def test_brushing_onto_a_shape_that_cannot_be_projected_is_a_message_not_a_crash(tmp_path):
    iface, c, dock = panel(tmp_path)
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    with mock.patch.object(QgsGeometry, "transform", side_effect=QgsCsException("forced")):
        dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock.draw_tool is None and dock._brush_fid is None
    assert SHAPE_NOT_TRANSFORMED in messages(iface)


@pytest.mark.parametrize("typed, replaced", [("flood", True), ("flood.tif", False)])
def test_an_export_name_typed_without_tif_asks_before_replacing_that_file(tmp_path, monkeypatch, typed, replaced):
    """The dialog checks for overwriting before `.tif` is added, so an existing flood.tif would be
    replaced silently when the user types just `flood`."""
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, _c, dock = panel(tmp_path)
    (tmp_path / "flood.tif").write_bytes(b"an earlier export")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / typed), "")))
    questions = []
    dock.confirm = lambda text: questions.append(text) or False
    assert dock._export_dialog() == ("" if replaced else str(tmp_path / "flood.tif"))
    assert questions == ([EXPORT_REPLACE.format("flood.tif")] if replaced else [])
    dock.confirm = lambda text: True
    assert dock._export_dialog() == str(tmp_path / "flood.tif")


def test_closing_a_session_removes_its_working_files(tmp_path):
    c = start_session(tmp_path)
    folder = c.files.folder
    assert os.path.isfile(os.path.join(folder, "working_dem.tif"))
    c.close()
    assert not os.path.exists(folder)


def test_clearing_the_project_removes_the_working_files(tmp_path):
    c = start_session(tmp_path)
    folder = c.files.folder
    QgsProject.instance().clear()
    assert not c.has_dem and not os.path.exists(folder)


def test_starting_on_another_dem_removes_only_the_old_working_files(tmp_path):
    c = start_session(tmp_path)
    old = c.files.folder
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    assert not os.path.exists(old) and os.path.isdir(c.files.folder)


def test_working_files_that_cannot_be_written_leave_no_folder_behind(tmp_path, monkeypatch):
    import tempfile
    made = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(real(**kw)) or made[-1])
    c = SketchController(QgsProject.instance())
    dem = dem_layer(tmp_path)
    with mock.patch.object(controller_module, "WorkingFiles", side_effect=OSError("disk full")):
        with pytest.raises(DemError):
            c.set_dem(dem)
    assert made and not os.path.exists(made[0])


def test_a_layer_group_that_fails_half_way_is_removed_again(tmp_path):
    """The group is in the layer tree before its layers are wired up; a failure there (here the
    hillshade node cannot be found, so hiding it raises) must not leave a half-built group."""
    from qgis.core import QgsLayerTreeGroup
    c = SketchController(QgsProject.instance())
    dem = dem_layer(tmp_path)
    with mock.patch.object(QgsLayerTreeGroup, "findLayer", return_value=None) as find:
        with pytest.raises(DemError):
            c.set_dem(dem)
    project = QgsProject.instance()
    assert find.called                                  # it really failed after the group existed
    assert project.layerTreeRoot().findGroup(GROUP_NAME) is None
    assert not project.mapLayersByName("Sketch outlines") and not project.mapLayersByName("Modified DEM")
    assert project.mapLayer(dem.id()) is not None       # the user's DEM is untouched
    assert not c.has_dem
```
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/qgis/test_file_safety.py`
Expected: collection error `ImportError: cannot import name 'EXPORT_REPLACE' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: The fixes**

Replace the whole file:

**File:** `scripts/build_zip.sh`
```bash
#!/usr/bin/env bash
# Build the installable plugin ZIP: Plugins ▸ Manage and Install Plugins ▸ Install from ZIP.
# Usage: scripts/build_zip.sh [output-directory]   (default: the repo root)
#
# Only what the plugin needs at runtime goes in. Tests, the dev virtualenv, caches and the
# scratch profile stay out: a user installing this should not receive our test suite.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Resolved to an absolute path before anything below `cd`s elsewhere: a relative directory (e.g.
# `.`, meaning the caller's cwd) would otherwise be interpreted against the staging directory once
# the script has cd'd there, silently writing the ZIP where the EXIT trap then deletes it. `cd`ing
# into it here also makes a missing output directory fail immediately, with a clear reason.
OUT_DIR="$(cd "${1:-$ROOT}" && pwd)"
PACKAGE="terrain_sketch"

if ! command -v zip >/dev/null 2>&1; then
  echo "build_zip.sh: the zip command is not installed" >&2
  exit 1
fi

# metadata.txt is what QGIS reads to list the plugin; without it the ZIP installs as nothing.
# Checked before the version is read, so a missing file reports itself rather than a sed error.
if [ ! -f "$ROOT/$PACKAGE/metadata.txt" ]; then
  echo "build_zip.sh: $PACKAGE/metadata.txt missing" >&2
  exit 1
fi
VERSION="$(sed -n 's/^version=//p' "$ROOT/$PACKAGE/metadata.txt" | head -1)"
if [ -z "$VERSION" ]; then
  echo "build_zip.sh: no version= in $PACKAGE/metadata.txt" >&2
  exit 1
fi
ZIP="$OUT_DIR/${PACKAGE}-${VERSION}.zip"

# Build from a clean staging copy so nothing local (a stray .pyc, an editor swap file) ships.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$PACKAGE"
tar -c -C "$ROOT/$PACKAGE" \
    --exclude="__pycache__" --exclude="*.pyc" --exclude="*.pyo" --exclude=".DS_Store" \
    --exclude="*~" --exclude="*.swp" --exclude=".pytest_cache" \
    . | tar -x -C "$STAGE/$PACKAGE"

# __init__.py is what makes QGIS able to import the plugin at all. Checked on the staging copy,
# which also catches a tar that produced nothing.
test -f "$STAGE/$PACKAGE/__init__.py"  || { echo "build_zip.sh: __init__.py missing" >&2; exit 1; }
test -f "$STAGE/$PACKAGE/metadata.txt" || { echo "build_zip.sh: staging copy is incomplete" >&2; exit 1; }

rm -f "$ZIP"
(cd "$STAGE" && zip -q -r "$ZIP" "$PACKAGE")
echo "$ZIP"
```

Replace the whole file:

**File:** `terrain_sketch/gui/controller.py`
```python
"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import configparser
import os
import pathlib
import shutil
import tempfile
import traceback
from dataclasses import replace
from typing import NamedTuple

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

from ..core.engine import FeatureStack
from ..core.operations import FeatureStats
from ..core.sections import long_section, rescale_long_profile
from ..core.tools import Mode, Tool
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io import scenario
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from ..qgis_io.scenario import ScenarioError
from .help_texts import (DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER, NO_FEATURES_SELECTED, NO_SESSION,
                         RESULT_LAYER_REMOVED, SCENARIO_NOT_APPLIED, SESSION_ENDED_DEM_REMOVED, TOOL_LABELS)

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


class SketchController(QObject):
    """Owns the session: the DEM, the ordered feature list, the engine, the files and the layers."""

    featuresChanged = pyqtSignal()
    sessionChanged = pyqtSignal()
    previewUpdated = pyqtSignal(str, object)  # (feature id, PreviewImage) while dragging
    previewCleared = pyqtSignal()
    message = pyqtSignal(object, str)  # (Qgis.MessageLevel, text for the message bar)

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
        self._dirty = False
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
        except (OSError, RuntimeError, MemoryError) as error:
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
        self._closing = True
        try:
            if self.layers is not None:
                self.layers.remove()
        finally:
            self._closing = False
        self._drop_session()

    def shutdown(self) -> None:
        """Close the session and stop listening to the project (plugin unload)."""
        self.close()
        self.project.layersRemoved.disconnect(self._on_layers_removed)
        self.project.cleared.disconnect(self._drop_session)
        self.project.aboutToBeCleared.disconnect(self._drop_session)

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
        self._set([*self._features, feature])
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
        self.cancel_preview()  # the committed result replaces whatever the overlay was showing
        self._set([replace(f, **changes) if f.id == fid else f for f in self._features])

    def set_enabled(self, fid: str, enabled: bool) -> None:
        self.update_feature(fid, enabled=bool(enabled))

    def delete_feature(self, fid: str) -> None:
        self._set([f for f in self._features if f.id != fid])

    def reorder(self, ids) -> None:
        by_id = {f.id: f for f in self._features}
        if sorted(ids) != sorted(by_id):
            raise ValueError("reorder() needs every feature id exactly once")
        self._set([by_id[i] for i in ids])

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
        """Whether anything has changed since the last save or load of a scenario."""
        return self._dirty

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
        created = self._created if path == self._scenario_path else ""
        meta = scenario.dem_meta(self.info, self.stack.original, version=plugin_version(), created=created)
        written = scenario.save(path, self._features, meta, crs_wkt=getattr(self.info, "crs_wkt", ""))
        self._scenario_path = path
        self._created = written.created
        self._dirty = False
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
        self._scenario_path = path
        self._created = meta.created
        self._dirty = False
        self.sessionChanged.emit()

    def _forget_scenario(self) -> None:
        self._scenario_path = None
        self._created = ""
        self._dirty = False

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
        self._dirty = True
        self.featuresChanged.emit()
        return True

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
        if self.before_discard is None or self.stack is None or not self._dirty or not self._features:
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
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)
```

Replace the whole file:

**File:** `terrain_sketch/gui/help_texts.py`
```python
"""Every description, example, tooltip and message the user reads, in one place.

Translation, and a deliberate deviation from the spec. Spec §2 ("In scope (v1)") asks for every
string to be wrapped in `tr()` so it can be translated later. That does not work for strings held
in a module like this one: `tr()` extracts only string *literals*, so `self.tr(SOME_CONSTANT)` at
the point of use produces nothing for a translator while looking like it does. These are therefore
plain strings, and the call sites pass them straight through.

The spec's intent still holds — the strings stay in one place, which is what makes translating
them later a contained job. When that happens, mark them here (with `QT_TRANSLATE_NOOP` or by
moving them into the classes that show them); widget captions already call `self.tr("literal")`
and keep working unchanged.
"""
from __future__ import annotations

from ..core.operations import FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS, FLAG_NODATA_REFERENCE, FLAG_OUTSIDE
from ..core.tools import PixelMode, Tool

TOOL_LABELS = {
    Tool.INTERPOLATE: "Interpolate",
    Tool.RAISE_PATH: "Raise path",
    Tool.LOWER_PATH: "Lower path",
    Tool.RAISE_FLAT: "Raise flat",
    Tool.LOWER_FLAT: "Lower flat",
    Tool.ADD: "Add to terrain",
    Tool.SUBTRACT: "Subtract from terrain",
}

TOOL_SUMMARIES = {
    Tool.INTERPOLATE: "A straight grade between the terrain at the start and end of the path, or a smooth "
                      "surface between the corners of an area. Example: cut through an embankment that "
                      "blocks a flow path, or fill an old ditch.",
    Tool.RAISE_PATH: "Adds material along the path, following the terrain uphill or downhill; it never "
                     "removes material. Example: a wall or emergency dike along a river bank.",
    Tool.LOWER_PATH: "Removes material along the path, following the terrain; it never adds material. "
                     "Example: a ditch or swale that drains a road towards a pond.",
    Tool.RAISE_FLAT: "A level top at the highest point of the path or outline plus the height. "
                     "Example: a flat dam, or building footprints.",
    Tool.LOWER_FLAT: "A level bottom at the lowest point of the path or outline minus the depth. "
                     "Example: a flat culvert, or a retention basin.",
    Tool.ADD: "Raises every selected cell by the height, keeping the relief. "
              "Example: an inflatable flood barrier on a street.",
    Tool.SUBTRACT: "Lowers every selected cell by the depth, keeping the slope changes. "
                   "Example: a pipe trench in a road, or deepening a canal to its bed.",
}

PIXEL_MODE_LABELS = {
    PixelMode.ALL_TOUCHED: "All touched",
    PixelMode.CENTRE: "Centre inside",
    PixelMode.FULLY_INSIDE: "Fully inside",
}

PIXEL_MODE_TIPS = {
    PixelMode.ALL_TOUCHED: "Every pixel the shape touches (generous).",
    PixelMode.CENTRE: "Pixels whose centre lies inside the shape (closest to the true area).",
    PixelMode.FULLY_INSIDE: "Only pixels completely inside the shape (strict).",
}

FLAG_TEXTS = {
    FLAG_OUTSIDE: "This feature lies outside the DEM.",
    FLAG_NO_PIXELS: "No pixels are selected — try 'All touched' or a larger width.",
    FLAG_NODATA_REFERENCE: "The start, end or edge of this feature lies outside the DEM or on nodata.",
    FLAG_BAD_GEOMETRY: "The shape of this feature cannot be used.",
}

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Sketch never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Sketch session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Sketch layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."
SHAPE_NOT_TRANSFORMED = ("This feature's shape cannot be shown in the map's coordinate system, so it cannot "
                         "be zoomed to or edited here. Set the project to the DEM's coordinate system and "
                         "try again.")
EXPORT_REPLACE = "{} already exists. Replace it?"


def amount_label(tool: Tool) -> str | None:
    """Label of the amount field, or None when the tool has no amount."""
    if tool is Tool.INTERPOLATE:
        return None
    if tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT):
        return "Depth"
    return "Height"

PROFILE_EMPTY_HINT = "Select or draw a feature to edit its shape here."
CUSTOM_PROFILE_NOTE = ("Custom long profile: the heights are fixed and no longer follow the "
                       "terrain underneath. Use Reset to rule to go back.")
AREA_LONG_SECTION_HINT = "A section through an area arrives in a later version."
AREA_LONG_SECTION_NOTE = ("An area has no long profile to edit. A section through the feature "
                          "arrives in a later version; until then, use the cross profile on the "
                          "left to shape its sides.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
SYMMETRIC_TIP = ("While this is ticked, break points are mirrored to the other side of the path. "
                 "Width and side slope are single values that always apply to both sides.")
AMOUNT_IS_CUSTOM = ("The long profile was edited by hand, so its heights are fixed. Use "
                    "Reset to rule in the profile panel to drive the shape from this value again.")


TOOL_EXAMPLES = {
    Tool.INTERPOLATE: ("A bridge or culvert was captured as a solid bank across a channel, so "
                       "water cannot pass. Draw a line along the channel through it and Terrain "
                       "Sketch runs a smooth grade between the two ends."),
    Tool.RAISE_PATH: ("A 1.5 m flood embankment along a river. Draw the line the crest follows, "
                      "set Height 1.5 m, Width 3 m and a 1:3 side slope."),
    Tool.LOWER_PATH: ("A swale carrying runoff to a pond. Draw its route, set Depth 0.6 m and "
                      "Width 2 m; the slopes tie it back into the ground."),
    Tool.RAISE_FLAT: ("A building pad above the flood level. Draw the outline and set the height "
                      "above the highest point on the outline you draw, so the whole pad sits "
                      "level."),
    Tool.LOWER_FLAT: ("A detention basin. Draw the outline, set Depth 1.2 m, and set Slopes to "
                      "Inside the outline so the sides slope down within it instead of the basin "
                      "growing outwards; the bottom comes out flat."),
    Tool.ADD: ("A 0.3 m layer of fill over a field. Draw the outline; the ground keeps its shape "
               "and every cell rises by the same amount."),
    Tool.SUBTRACT: ("Stripping 0.2 m of topsoil. Draw the outline; the ground keeps its shape and "
                    "every cell drops by the same amount."),
}

TOOL_DESCRIPTIONS = {
    Tool.INTERPOLATE: ("Replaces the terrain under the shape with a smooth grade between its "
                       "edges, so a missing or wrong patch is bridged rather than raised or cut."),
    Tool.RAISE_PATH: ("Builds a raised corridor along a line: a flat crest of the width you set, "
                      "with side slopes running down to meet the ground."),
    Tool.LOWER_PATH: ("Cuts a channel along a line: a flat bottom of the width you set, with "
                      "sides sloping up to meet the ground."),
    Tool.RAISE_FLAT: ("Lifts everything inside the shape to one level, measured from the highest "
                      "point on the line or outline you draw, with slopes tying the edge back "
                      "into the ground."),
    Tool.LOWER_FLAT: ("Cuts everything inside the shape down to one level, measured from the "
                      "lowest point on the line or outline you draw, with slopes tying the edge "
                      "back in."),
    Tool.ADD: "Adds the same height to every cell inside the shape; the terrain keeps its shape.",
    Tool.SUBTRACT: ("Takes the same height off every cell inside the shape; the terrain keeps "
                    "its shape."),
}

FIELD_TIPS = {
    "amount": ("How far the feature rises (height) or cuts (depth): above or below the straight "
               "grade between the path's ends, the highest or lowest point of the path or "
               "outline, or the terrain itself for Add and Subtract. For a 1.5 m embankment, "
               "set 1.5."),
    "width": ("How wide the flat part is — the crest of a dike, or the bottom of a ditch. A farm "
              "track is about 3 m; a footpath about 1.5 m."),
    "slope_n": ("How far the side slope runs out for every metre of height. 1:3 means 3 m "
                "outwards per 1 m up, about the steepest a mown grass embankment usually gets. "
                "0 means no side slopes at all."),
    "reach": ("The side slopes stop this far from the edge even if they have not met the ground. "
              "Set 5 m to keep a 1.5 m embankment out of a neighbouring plot that starts 5 m "
              "from the crest."),
    "slopes_inside": ("Inside: the outline is the top edge and the slopes run down within it — a "
                      "pond. Outside: the outline is the flat part and the slopes run out beyond "
                      "it — a raised pad."),
    "pixel_mode": ("Which cells count as covered by your shape. Narrow features can miss every "
                   "cell centre, which is when All touched helps."),
}

NO_FEATURES_SELECTED = ("Nothing is selected in that layer. Untick \'Selected features only\', or "
                        "select the features you want on the map first.")
EMPTY_LAYER = "That layer has no features to use."
PICK_A_LAYER = "Pick a layer above first."


def tool_tooltip(tool: Tool) -> str:
    """What a gallery item shows on hover: what the tool does, then a worked example."""
    return f"{TOOL_DESCRIPTIONS[tool]}\n\n{TOOL_EXAMPLES[tool]}"

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Sketch cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float | None) -> str:
    """A volume a user can read at a glance: no decimals once it is past a hundred.

    Cut and fill are magnitudes, so a minus sign here can only be floating-point residue —
    a negative zero out of a subtraction, or a few millilitres left over a million cells.
    Either would reach the user as "-0.00 m³", which reads as a bug, so the sign is dropped
    from anything that rounds to zero."""
    if value is None:
        return NO_VOLUME_YET
    size = abs(value)
    text = f"{value:,.0f}" if size >= 100.0 else f"{value:,.1f}" if size >= 1.0 else f"{value:.2f}"
    if text.startswith("-") and not any(digit in "123456789" for digit in text):
        text = text[1:]
    return f"{text} m³"


UNSAVED_CHANGES = ("This scenario has changes that are not saved. Save them before continuing?")
SCENARIO_SAVED = "Scenario saved to {}"
SCENARIO_REPLACE = "{} already exists. Replace it?"
SCENARIO_OPENED = "Scenario opened from {}"
SCENARIO_DEM_DIFFERS = ("This scenario was made on a DEM with a different {}.\n\n"
                        "Open it on this DEM anyway? The features keep their map position, so check "
                        "the result before using it.\n\n"
                        "Choose No to keep your current work, then pick the DEM the scenario was made "
                        "for and press Start before opening it.")
SCENARIO_NOT_APPLIED = ("The scenario could not be applied to this DEM, so it was not opened. "
                        "Your current features are unchanged.")
UNSAVED_BEFORE_CLOSING = ("Terrain Sketch is closing this scenario, and it has changes that are not "
                          "saved. Save them now?")
```

Replace the whole file:

**File:** `terrain_sketch/gui/main_dock.py`
```python
"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsApplication, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsProject
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (EXPORT_REPLACE, REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                         SCENARIO_SAVED, SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES)
from .map_tools.brush import BrushTool
from .map_tools.draw_line import DrawLineTool
from .map_tools.draw_polygon import DrawPolygonTool
from .map_tools.freehand import FreehandTool
from .map_tools.vertex_edit import VertexEditTool
from .overlay import PreviewOverlay
from .properties_page import PropertiesPage
from .selection import BRUSH_EXTEND_HINT, EDIT_HINT, EDIT_ICON, METHOD_HINTS, Method
from .tool_gallery import ToolGallery

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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)

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
        layout.addLayout(dem_row)

        tools_row = QHBoxLayout()
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
            tools_row.addWidget(button)
        self.export_button = QToolButton()
        self.export_button.setIcon(QgsApplication.getThemeIcon("/mActionSharingExport.svg"))
        self.export_button.setText(self.tr("Export DEM…"))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setToolTip(self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
        self.hillshade_box = QCheckBox(self.tr("Hillshade"))
        tools_row.addWidget(self.export_button)
        tools_row.addWidget(self.hillshade_box)
        tools_row.addStretch(1)
        layout.addLayout(tools_row)

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
        controller.featuresChanged.connect(self._refresh_highlight)
        controller.featuresChanged.connect(self._drop_missing_brush_target)
        controller.featuresChanged.connect(self._sync_selection_page)
        controller.sessionChanged.connect(self._session_changed)
        controller.message.connect(self._show_message)
        controller.previewUpdated.connect(self._preview_updated)
        controller.previewCleared.connect(lambda: self.overlay.clear())
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        tool, self.draw_tool, self._brush_fid = self.draw_tool, None, None
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
        self.iface.mapCanvas().scene().removeItem(self.highlight)

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
                       self.edit_button, self.feature_view, *self.scenario_buttons):
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
        self._asked_about_unsaved = True   # the user has just answered; closing the old session must not ask again
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
        finally:
            self._asked_about_unsaved = False

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
            try:
                initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
            except QgsCsException:
                self._brush_fid = None
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
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.setText(self._drawing_hint(method))
        self.hint.show()

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

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map."""
        if fid is None or not self.controller.has_dem or fid not in {f.id for f in self.controller.features}:
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        geometry = self._to_canvas(self.controller.feature_geometry(fid))
        self.highlight.reset(geometry.type())
        self.highlight.setToGeometry(geometry, None)

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
        try:
            differences = self.controller.scenario_differences(path)
            if differences and not self.confirm(SCENARIO_DEM_DIFFERS.format(", ".join(differences))):
                return
            self.stop_tools()
            self.controller.open_scenario(path)
        except ScenarioError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))
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
        self._show_message(Qgis.MessageLevel.Success, self.tr("Exported the modified DEM to {}").format(path))

    def _context_menu(self, position) -> None:
        index = self.feature_view.indexAt(position)
        if not index.isValid():
            return
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(QgsApplication.getThemeIcon("/mActionZoomToLayer.svg"), self.tr("Zoom to feature"),
                       lambda: self._zoom_to(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"),
                       lambda: self.controller.delete_feature(fid))
        menu.exec(self.feature_view.viewport().mapToGlobal(position))

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
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export modified DEM"), "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
            # as for scenarios: the dialog asked about replacing the name as typed, not this one
            if os.path.exists(path) and not self.confirm(EXPORT_REPLACE.format(os.path.basename(path))):
                return ""
        return path
```

Replace the whole file:

**File:** `terrain_sketch/qgis_io/layers.py`
```python
"""The "Terrain Sketch" layer group: modified DEM, change, hillshade and sketch outlines."""
from __future__ import annotations

from qgis.core import (Qgis, QgsColorRampShader, QgsFeature, QgsFillSymbol, QgsHillshadeRenderer,
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
```

Replace the whole file:

**File:** `terrain_sketch/qgis_io/raster_io.py`
```python
"""Reading the DEM into the engine; writing the working/change GeoTIFFs and the export."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer

from ..core.grid import DemGrid, Window

gdal.UseExceptions()

WARN_CELLS = 50_000_000
DEFAULT_NODATA = -9999.0
_CREATE_OPTIONS = ["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"]


class DemError(Exception):
    """The chosen layer cannot be used as the DEM; the message is shown to the user."""


class GeographicDemError(DemError):
    """A DEM in degrees. A DemError to every existing caller, but the panel checks for it so it
    can offer to reproject rather than only complaining."""


@dataclass(frozen=True)
class DemInfo:
    path: str
    crs_wkt: str
    nodata: float  # nodata value written to the working, change and exported files
    band_count: int
    warnings: tuple = ()


def read_dem(layer) -> tuple[DemGrid, DemInfo]:
    """Band 1 of a file-based raster layer in a projected CRS, as a DemGrid."""
    if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
        raise DemError("Pick a valid raster layer as the DEM.")
    if layer.providerType() != "gdal":
        raise DemError("Only file-based rasters (for example GeoTIFF) can be used as the DEM.")
    if layer.crs().isGeographic():
        raise GeographicDemError("The DEM uses latitude/longitude. Slopes and widths need metres: reproject it to a "
                       "projected CRS first (Raster ▸ Projections ▸ Warp).")
    try:
        ds = gdal.Open(layer.source())
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        array = band.ReadAsArray()
    except (RuntimeError, MemoryError) as error:
        raise DemError(f"The DEM could not be read: {error}") from error
    try:
        grid = DemGrid.from_array(array, ds.GetGeoTransform(), nodata)
    except ValueError as error:
        raise DemError(f"This raster cannot be used as the DEM: {error}.") from error
    warnings = []
    if ds.RasterCount > 1:
        warnings.append(f"The DEM has {ds.RasterCount} bands; band 1 is used.")
    cells = grid.rows * grid.cols
    if cells > WARN_CELLS:
        warnings.append(f"The DEM has {cells / 1e6:.0f} million cells and needs about "
                        f"{cells * 12 / 1e9:.1f} GB of memory; consider clipping it to your site.")
    info = DemInfo(layer.source(), layer.crs().toWkt(),
                   DEFAULT_NODATA if nodata is None else float(nodata), ds.RasterCount, tuple(warnings))
    return grid, info


class WorkingFiles:
    """The working DEM and the change raster (working − original) of a session, on disk."""

    def __init__(self, folder: str, original: DemGrid, info: DemInfo):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.working_path = os.path.join(folder, "working_dem.tif")
        self.change_path = os.path.join(folder, "change.tif")
        self._original = original
        self._info = info
        _write_tif(self.working_path, _for_output(original.data, original.valid, info.nodata), original, info)
        _write_tif(self.change_path, _for_output(np.zeros(original.data.shape), original.valid, info.nodata),
                   original, info)

    def write(self, window: Window, working: DemGrid) -> None:
        """Write one window of the working DEM and its change into both files."""
        rows, cols = window.slices
        valid = self._original.valid[rows, cols]
        values = working.data[rows, cols]
        change = values.astype(np.float64) - self._original.data[rows, cols]
        for path, block in ((self.working_path, _for_output(values, valid, self._info.nodata)),
                            (self.change_path, _for_output(change, valid, self._info.nodata))):
            ds = gdal.Open(path, gdal.GA_Update)
            ds.GetRasterBand(1).WriteArray(block, window.col0, window.row0)
            ds.FlushCache()
            ds = None


def export_dem(path: str, working: DemGrid, info: DemInfo) -> None:
    """Float32 GeoTIFF of the modified DEM on the original grid, CRS and nodata value."""
    _write_tif(path, _for_output(working.data, working.valid, info.nodata), working, info,
               extra_options=["PREDICTOR=3"])


def _for_output(values: np.ndarray, valid: np.ndarray, nodata: float) -> np.ndarray:
    """Float32 copy with nodata cells set to `nodata`; valid cells that happen to equal
    `nodata` are nudged by one float step so they do not turn into holes."""
    out = values.astype(np.float32, copy=True)
    marker = np.float32(nodata)
    clash = valid & (out == marker)
    out[clash] = np.nextafter(marker, np.float32(np.inf))
    out[~valid] = marker
    return out


def _write_tif(path: str, array: np.ndarray, grid: DemGrid, info: DemInfo, extra_options=()) -> None:
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.cols, grid.rows, 1, gdal.GDT_Float32,
                                              _CREATE_OPTIONS + list(extra_options))
    ds.SetGeoTransform(grid.geotransform)
    ds.SetProjection(info.crs_wkt)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(info.nodata)
    band.WriteArray(array)
    ds.FlushCache()
    ds = None
```

Replace the whole file:

**File:** `terrain_sketch/qgis_io/scenario.py`
```python
"""Saving and loading a scenario as a GeoPackage: the features layer plus a metadata table.

The file is a normal GeoPackage, so a user can open it in QGIS and look at the outlines without
the plugin. That is the point of the format choice: the features layer carries real geometry in
the DEM's CRS, and everything the engine needs to rebuild a feature travels in ordinary fields
beside it (spec §8.4).
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from osgeo import ogr, osr

from ..core.tools import Mode, PixelMode, Tool
from ..model.feature import TerrainFeature

ogr.UseExceptions()   # also relied on by sibling modules; set here so this module stands alone

FEATURES_LAYER = "features"
META_TABLE = "terrain_sketch_meta"
PARAM_FIELDS = ("amount", "width", "slope_n", "reach", "slopes_inside")
FIELDS = (("order", ogr.OFTInteger), ("name", ogr.OFTString), ("tool", ogr.OFTString),
          ("mode", ogr.OFTString), ("enabled", ogr.OFTInteger), ("pixel_mode", ogr.OFTString),
          ("params", ogr.OFTString), ("cross_profile", ogr.OFTString),
          ("long_profile", ogr.OFTString), ("section_line", ogr.OFTString))
# section_line is written as null: no feature carries a custom area section line yet, and the
# field is kept so a file written now still has the documented layout when one does (spec §8.4).

# qgis_io/scenario.py cannot import gui/help_texts.py (Global Constraints: "qgis_io/scenario.py
# uses ogr/osr only"), so these messages live beside the rest of this module's own ScenarioError
# text (e.g. "Terrain Sketch could not create {path}." below) rather than there.
SCENARIO_FILE_IN_USE = ("{} is open in another program (such as a layer in QGIS), so it was not saved. "
                        "Remove that layer or close the program, then try again.")
SCENARIO_WOULD_REPLACE_OTHER_FILE = ("{} is not a Terrain Sketch scenario, so saving would replace it "
                                     "entirely. Choose another name.")


class ScenarioError(Exception):
    """The scenario file cannot be written or read; the message is shown to the user."""


@dataclass(frozen=True)
class ScenarioMeta:
    """What the file records about the DEM it was built on, so a mismatch can be reported."""

    dem_source: str = ""
    dem_crs: str = ""
    dem_extent: str = ""
    dem_size: str = ""
    dem_pixel_size: str = ""
    plugin_version: str = ""
    created: str = ""
    modified: str = ""

    def differences(self, other: ScenarioMeta) -> list[str]:
        """Which DEM properties disagree, in words a user can act on. Ignores the bookkeeping
        fields — only the DEM's identity matters for whether a scenario still applies."""
        labels = {"dem_crs": "coordinate system", "dem_size": "size in pixels",
                  "dem_pixel_size": "pixel size", "dem_extent": "extent"}
        return [text for key, text in labels.items()
                if getattr(self, key) and getattr(other, key)
                and getattr(self, key) != getattr(other, key)]


def dem_meta(info, grid, version: str = "", created: str = "") -> ScenarioMeta:
    """Describe the DEM a scenario is being saved against. Never raises: this is bookkeeping,
    and a DEM whose CRS cannot be named must still be saveable."""
    x0, w, _rx, y0, _ry, h = grid.geotransform
    return ScenarioMeta(
        dem_source=getattr(info, "path", ""),
        dem_crs=_crs_id(getattr(info, "crs_wkt", "")),
        dem_extent=_round6((x0, y0 + h * grid.rows, x0 + w * grid.cols, y0)),
        dem_size=f"{grid.cols}x{grid.rows}",
        dem_pixel_size=_round6((abs(w), abs(h))),
        plugin_version=version,
        created=created,
    )


def save(path: str, features, meta: ScenarioMeta, crs_wkt: str = "") -> ScenarioMeta:
    """Write `features` and `meta` to `path`, replacing any file already there, and return the
    metadata as written — with `created` and `modified` filled in.

    The file is built beside the target and moved over it only once it is complete, so a save
    that fails half way — a full disk, a feature GDAL refuses — leaves the previous scenario
    readable instead of destroying it. There is no undo to recover it from."""
    driver = ogr.GetDriverByName("GPKG")
    if driver is None:
        raise ScenarioError("This QGIS has no GeoPackage driver, so scenarios cannot be saved.")
    folder, name = os.path.split(os.path.abspath(path))
    partial = os.path.join(folder, f"{os.path.splitext(name)[0]}.saving-{uuid.uuid4().hex[:8]}.gpkg")
    source = None
    try:
        _check_replaceable(path)
        source = driver.CreateDataSource(partial)
        if source is None:
            raise ScenarioError(f"Terrain Sketch could not create {path}.")
        layer = source.CreateLayer(FEATURES_LAYER, _srs(crs_wkt or meta.dem_crs), ogr.wkbUnknown)
        for field, kind in FIELDS:
            layer.CreateField(ogr.FieldDefn(field, kind))
        for order, feature in enumerate(features):
            layer.CreateFeature(_to_ogr(layer, order, feature))
        written = _write_meta(source, meta)
        # Closed explicitly rather than by dropping the name: closing is what flushes the file, and
        # any other reference — a traceback frame, say — would otherwise keep it open, which on
        # Windows blocks both the move below and the clean-up of a failed attempt.
        source.Close()
        source = None
        os.replace(partial, path)
        return written
    except ScenarioError:
        _discard_partial(source, partial)
        raise
    except Exception as error:  # noqa: BLE001 — GDAL raises many types; the user gets one message
        _discard_partial(source, partial)
        raise ScenarioError(f"Terrain Sketch could not save the scenario: {error}") from error


def _check_replaceable(path: str) -> None:
    """Refuse to let `save` replace `path` whole when that would be unsafe. `os.replace` destroys
    every layer already in the file, so the target must already be a Terrain Sketch scenario —
    and even then, not one another program currently has open."""
    if os.path.exists(path + "-wal") or os.path.exists(path + "-shm"):
        # SQLite documents leaving WAL/SHM siblings orphaned beside a file swapped in under a
        # program that still has the original open (as QGIS does for a scenario shown as a
        # layer) as a corruption path.
        raise ScenarioError(SCENARIO_FILE_IN_USE.format(path))
    if os.path.exists(path) and not _is_scenario_file(path):
        raise ScenarioError(SCENARIO_WOULD_REPLACE_OTHER_FILE.format(path))


def _is_scenario_file(path: str) -> bool:
    """Whether `path` already holds a Terrain Sketch scenario. Checked on the GeoPackage's own
    SQLite catalogue rather than through `_open`/`FEATURES_LAYER`: an empty scenario (no features
    yet) still has `META_TABLE`, and that table was written with a plain `CREATE TABLE`, not
    through OGR's own layer-creation API, so it never appears via `GetLayerByName` either way."""
    try:
        source = ogr.Open(path)
    except RuntimeError:                           # the plugin runs GDAL with exceptions on
        return False
    if source is None:
        return False
    try:
        result = source.ExecuteSQL(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{META_TABLE}'")
        if result is None:
            return False
        try:
            return result.GetFeatureCount() > 0
        finally:
            source.ReleaseResultSet(result)
    finally:
        source.Close()


def _discard_partial(source, partial: str) -> None:
    if source is not None:
        try:
            source.Close()
        except Exception:  # noqa: BLE001 — already failing; the original error is the one to report
            pass
    for leftover in (partial, partial + "-journal", partial + "-wal", partial + "-shm"):
        try:
            os.remove(leftover)
        except OSError:
            pass


def load(path: str) -> tuple[list[TerrainFeature], ScenarioMeta]:
    """Read a scenario back. Raises ScenarioError for anything unreadable."""
    source = None
    try:
        source, layer = _open(path)
        rows = sorted((_from_ogr(f) for f in layer), key=lambda pair: pair[0])
        return [feature for _order, feature in rows], _read_meta(source)
    except ScenarioError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ScenarioError(f"Terrain Sketch could not read the scenario: {error}") from error
    finally:
        _close(source)


def load_meta(path: str) -> ScenarioMeta:
    """Only the metadata, to compare DEMs before deciding whether to load. Raises ScenarioError
    for a file that is not a readable scenario, exactly as `load` would."""
    source = None
    try:
        source, _layer = _open(path)
        return _read_meta(source)
    except ScenarioError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ScenarioError(f"Terrain Sketch could not read the scenario: {error}") from error
    finally:
        _close(source)


def _open(path: str):
    source = ogr.Open(path)
    if source is None:
        raise ScenarioError(f"Terrain Sketch could not open {path}.")
    layer = source.GetLayerByName(FEATURES_LAYER)
    if layer is None:
        source.Close()
        raise ScenarioError(f"{path} is not a Terrain Sketch scenario: it has no '{FEATURES_LAYER}' layer.")
    return source, layer


def _close(source) -> None:
    """Release a read handle now, not whenever it is collected: a scenario that is still open
    cannot be replaced by the next save on Windows."""
    if source is not None:
        try:
            source.Close()
        except Exception:  # noqa: BLE001 — reading already succeeded or failed on its own terms
            pass


def _to_ogr(layer, order: int, feature: TerrainFeature):
    out = ogr.Feature(layer.GetLayerDefn())
    out.SetGeometry(ogr.CreateGeometryFromWkb(feature.geometry_wkb))
    out.SetField("order", order)
    out.SetField("name", feature.name)
    out.SetField("tool", feature.tool.value)
    out.SetField("mode", feature.mode.value)
    out.SetField("enabled", int(feature.enabled))
    out.SetField("pixel_mode", feature.pixel_mode.value)
    out.SetField("params", json.dumps({k: getattr(feature, k) for k in PARAM_FIELDS}))
    out.SetField("cross_profile", json.dumps({"left": [list(p) for p in feature.cross_left],
                                              "right": [list(p) for p in feature.cross_right]}))
    if feature.long_profile is not None:
        out.SetField("long_profile", json.dumps([list(p) for p in feature.long_profile]))
    return out


def _from_ogr(row) -> tuple[int, TerrainFeature]:
    geometry = row.GetGeometryRef()
    if geometry is None:
        raise ScenarioError("A feature in the scenario has no geometry.")
    params = json.loads(row.GetField("params") or "{}")
    cross = json.loads(row.GetField("cross_profile") or "{}")
    long_profile = row.GetField("long_profile")
    feature = TerrainFeature(
        # A fresh id, never one derived from the row: two files both have a row 1, and a panel
        # still showing feature 1 of the old scenario must not silently retarget the new one.
        id=uuid.uuid4().hex,
        name=row.GetField("name") or "Feature",
        tool=Tool(row.GetField("tool")),
        mode=Mode(row.GetField("mode")),
        geometry_wkb=bytes(geometry.ExportToWkb()),
        enabled=bool(row.GetField("enabled")),
        pixel_mode=PixelMode(row.GetField("pixel_mode")),
        cross_left=tuple(tuple(p) for p in cross.get("left", ())),
        cross_right=tuple(tuple(p) for p in cross.get("right", ())),
        long_profile=None if not long_profile else tuple(tuple(p) for p in json.loads(long_profile)),
        **{k: params[k] for k in PARAM_FIELDS if k in params},
    )
    return int(row.GetField("order") or 0), feature


def _write_meta(source, meta: ScenarioMeta) -> ScenarioMeta:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = replace(meta, created=meta.created or now, modified=now)
    values = {k: str(v) for k, v in written.__dict__.items()}
    source.ExecuteSQL(f'CREATE TABLE "{META_TABLE}" (key TEXT PRIMARY KEY, value TEXT)')
    for key, value in values.items():
        escaped = value.replace("'", "''")
        source.ExecuteSQL(f"INSERT INTO \"{META_TABLE}\" (key, value) VALUES ('{key}', '{escaped}')")
    return written


def _read_meta(source) -> ScenarioMeta:
    result = source.ExecuteSQL(f'SELECT key, value FROM "{META_TABLE}"')
    if result is None:
        return ScenarioMeta()
    try:
        pairs = {row.GetField("key"): row.GetField("value") for row in result}
    finally:
        source.ReleaseResultSet(result)
    known = ScenarioMeta().__dict__
    return ScenarioMeta(**{k: v for k, v in pairs.items() if k in known})


def _srs(definition: str):
    """A spatial reference from WKT or an id like EPSG:25832; None when it cannot be read."""
    if not definition:
        return None
    srs = osr.SpatialReference()
    try:
        if srs.SetFromUserInput(definition) != 0:
            return None
    except RuntimeError:                           # the plugin runs GDAL with exceptions on
        return None
    return srs


def _crs_id(wkt: str) -> str:
    """EPSG:nnnn when the CRS has a code, otherwise its name. Never raises — with GDAL
    exceptions on, AutoIdentifyEPSG throws for every CRS it cannot match, which is exactly
    the local or custom grid a scenario must still be saveable on."""
    srs = _srs(wkt)
    if srs is None:
        return ""
    try:
        srs.AutoIdentifyEPSG()
    except RuntimeError:
        pass
    code = srs.GetAuthorityCode(None)
    return f"EPSG:{code}" if code else srs.GetName() or ""


def _round6(values) -> str:
    return ",".join(f"{v:.6f}" for v in values)
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_file_safety.py tests/core/test_build_zip.py` → Expected: `22 passed`
Run: `scripts/test.sh` → Expected: `378 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/build_zip.sh terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/qgis_io/layers.py terrain_sketch/qgis_io/raster_io.py terrain_sketch/qgis_io/scenario.py tests/core/test_build_zip.py tests/qgis/test_file_safety.py
git commit -m "fix: projection failures, replaced exports, working files and a half-built layer group"
```

---

### Task 2: Undo in the controller

**Files:**
- Create: `terrain_sketch/gui/undo.py`
- Modify: `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`
- Test: `tests/qgis/test_undo.py`

**Interfaces:**
- Consumes: `SketchController._set(features) -> bool`, `find`, `cancel_preview`; Plan 6's `is_dirty`, `save_scenario`, `open_scenario`, `new_scenario`, `_forget_scenario`, `before_discard`.
- Produces: `gui/undo.py` `FeatureListChange(restore, before, after, text, key=None)`; `SketchController.undo_stack` (`QUndoStack`), signal `featuresRestored`, `_commit(features, text, key=None) -> bool`; `add_drawn` returns None when the engine refuses; `update_feature`/`delete_feature` do nothing for an unknown id; `is_dirty` is `not undo_stack.isClean()`; `help_texts.UNDO_ADD`, `UNDO_DELETE`, `UNDO_RENAME`, `UNDO_TURN_ON`, `UNDO_TURN_OFF`, `UNDO_REORDER`, `UNDO_SHAPE`, `UNDO_PROFILE`, `UNDO_SETTINGS`.

- [ ] **Step 1: Write the failing test**

**File:** `tests/qgis/test_undo.py`
```python
"""Undo and redo over the feature list (spec §7.4): every kind of change, merging, and the saved state."""
import numpy as np
import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, square, start_session
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.help_texts import (UNDO_ADD, UNDO_DELETE, UNDO_PROFILE, UNDO_RENAME, UNDO_REORDER,
                                           UNDO_SETTINGS, UNDO_SHAPE, UNDO_TURN_OFF, UNDO_TURN_ON)


def terrain(c):
    return c.stack.working.data.copy()


def replayed(c):
    """The terrain a fresh engine computes for the controller's current list, from scratch."""
    fresh = FeatureStack(c.stack.original)
    fresh.update(c.features)
    return fresh.working.data


def dike_and_pond(c):
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    return dike, pond


EDITS = {
    "add": lambda c, dike, pond: c.add_drawn(Tool.ADD, Mode.AREA, square(2, 30, 12, 38), UTM),
    "delete": lambda c, dike, pond: c.delete_feature(pond.id),
    "rename": lambda c, dike, pond: c.update_feature(dike.id, name="Sea wall"),
    "toggle": lambda c, dike, pond: c.set_enabled(dike.id, False),
    "reorder": lambda c, dike, pond: c.reorder([pond.id, dike.id]),
    "settings": lambda c, dike, pond: c.update_feature(dike.id, amount=2.5, width=5.0),
    "pixels": lambda c, dike, pond: c.update_feature(pond.id, pixel_mode=PixelMode.ALL_TOUCHED),
    "profile": lambda c, dike, pond: c.update_feature(dike.id, cross_right=((3.0, -0.6),)),
    "shape": lambda c, dike, pond: c.set_geometry(dike.id, line_through(5, 24, 34, 28), UTM),
}


@pytest.mark.parametrize("edit", sorted(EDITS))
def test_every_kind_of_change_undoes_and_redoes_exactly(tmp_path, edit):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    list_before, terrain_before = c.features, terrain(c)
    EDITS[edit](c, dike, pond)
    list_after, terrain_after = c.features, terrain(c)
    assert list_after != list_before

    c.undo_stack.undo()
    assert c.features == list_before
    assert np.array_equal(terrain(c), terrain_before)
    assert np.array_equal(terrain(c), replayed(c))          # the windowed recompute is still exact
    c.undo_stack.redo()
    assert c.features == list_after
    assert np.array_equal(terrain(c), terrain_after)


def test_each_change_says_what_undo_will_do(tmp_path):
    c = start_session(tmp_path)
    texts = []
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    texts.append(c.undo_stack.undoText())
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    for change in (lambda: c.update_feature(dike.id, amount=2.0),
                   lambda: c.update_feature(dike.id, cross_right=((3.0, -0.6),)),
                   lambda: c.set_geometry(dike.id, line_through(5, 24, 34, 28), UTM),
                   lambda: c.set_enabled(pond.id, False),
                   lambda: c.set_enabled(pond.id, True),
                   lambda: c.reorder([pond.id, dike.id]),
                   lambda: c.update_feature(dike.id, name="Sea wall"),
                   lambda: c.delete_feature(pond.id)):
        change()
        texts.append(c.undo_stack.undoText())
    assert texts == [UNDO_ADD.format("Raise path 1"), UNDO_SETTINGS.format("Raise path 1"),
                     UNDO_PROFILE.format("Raise path 1"), UNDO_SHAPE.format("Raise path 1"),
                     UNDO_TURN_OFF.format("Lower flat 1"), UNDO_TURN_ON.format("Lower flat 1"),
                     UNDO_REORDER, UNDO_RENAME.format("Raise path 1"), UNDO_DELETE.format("Lower flat 1")]


def test_the_steps_of_one_setting_merge_into_one_undo(tmp_path):
    """A spin box reports every step; the user thinks of the whole adjustment as one change."""
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    start = c.undo_stack.index()
    for value in (1.5, 2.0, 2.5, 3.0):
        c.update_feature(dike.id, amount=value)
    assert c.undo_stack.index() == start + 1
    c.undo_stack.undo()
    assert c.find(dike.id).amount == 1.0


def test_different_settings_or_features_stay_separate_steps(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    start = c.undo_stack.index()
    c.update_feature(dike.id, amount=2.0)
    c.update_feature(dike.id, width=5.0)          # another setting of the same feature
    c.update_feature(pond.id, width=5.0)          # the same setting of another feature
    c.update_feature(dike.id, width=6.0)          # back to the first: not merged across the pond
    assert c.undo_stack.index() == start + 4


def test_stepping_a_setting_back_to_where_it_was_leaves_no_step(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    start = c.undo_stack.index()
    c.update_feature(dike.id, amount=2.0)
    c.update_feature(dike.id, amount=1.0)
    assert c.undo_stack.index() == start


def test_a_change_that_changes_nothing_records_nothing_and_stays_saved(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "same.gpkg"))
    start = c.undo_stack.index()
    c.update_feature(dike.id, amount=dike.amount, name=dike.name)
    assert c.undo_stack.index() == start and not c.is_dirty


def test_the_scenario_is_unsaved_exactly_when_undo_has_left_the_saved_state(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "clean.gpkg"))
    c.update_feature(dike.id, amount=2.0)
    assert c.is_dirty
    c.undo_stack.undo()
    assert not c.is_dirty                        # back to what is on disk
    c.undo_stack.redo()
    assert c.is_dirty
    c.undo_stack.undo()
    c.undo_stack.undo()                          # before the save point
    assert c.is_dirty


def test_a_setting_changed_after_a_save_does_not_merge_into_the_saved_step(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.update_feature(dike.id, amount=2.0)
    c.save_scenario(str(tmp_path / "saved.gpkg"))
    c.update_feature(dike.id, amount=3.0)
    c.undo_stack.undo()
    assert c.find(dike.id).amount == 2.0 and not c.is_dirty


def test_new_open_and_start_leave_nothing_to_undo(tmp_path):
    c = start_session(tmp_path)
    dike_and_pond(c)
    path = str(tmp_path / "history.gpkg")
    c.save_scenario(path)
    c.update_feature(c.features[0].id, amount=2.0)
    c.open_scenario(path)
    assert not c.undo_stack.canUndo() and not c.is_dirty
    c.add_drawn(Tool.ADD, Mode.AREA, square(2, 30, 12, 38), UTM)
    c.new_scenario()
    assert not c.undo_stack.canUndo() and not c.is_dirty
    c.add_drawn(Tool.ADD, Mode.AREA, square(2, 30, 12, 38), UTM)
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    assert not c.undo_stack.canUndo() and not c.is_dirty


def test_a_change_the_engine_refuses_records_nothing(tmp_path):
    from unittest import mock
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    start = c.undo_stack.index()
    with mock.patch.object(c.stack, "update", side_effect=RuntimeError("refused")):
        c.update_feature(dike.id, amount=4.0)
    assert c.undo_stack.index() == start and c.find(dike.id).amount == 1.0


def test_deleting_every_feature_of_a_saved_scenario_still_asks_before_it_is_dropped(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "emptied.gpkg"))
    c.delete_feature(dike.id)
    c.delete_feature(pond.id)
    asked = []
    c.before_discard = lambda: asked.append(True)
    QgsProject.instance().clear()
    assert asked == [True]


def test_undo_and_redo_announce_that_the_list_was_restored(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.update_feature(dike.id, amount=2.0)
    heard = []
    c.featuresRestored.connect(lambda: heard.append(True))
    c.undo_stack.undo()
    c.undo_stack.redo()
    assert heard == [True, True]


def test_a_long_run_of_undo_and_redo_keeps_the_terrain_exact(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    for name in sorted(set(EDITS) - {"add", "delete"}) + ["add"]:   # reorder needs exactly the two
        EDITS[name](c, dike, pond)
    while c.undo_stack.canUndo():
        c.undo_stack.undo()
        assert np.array_equal(terrain(c), replayed(c))
    assert c.features == ()
    while c.undo_stack.canRedo():
        c.undo_stack.redo()
        assert np.array_equal(terrain(c), replayed(c))
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_undo.py`
Expected: collection error `ImportError: cannot import name 'UNDO_ADD' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: Implement**

Every mutation now goes through `_commit`, and `_dirty` is gone: the undo stack's clean state replaces it. `_offer_save_before_discard` no longer requires features, so an emptied scenario still asks.

Replace the whole file:

**File:** `terrain_sketch/gui/controller.py`
```python
"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import configparser
import os
import pathlib
import shutil
import tempfile
import traceback
from dataclasses import replace
from typing import NamedTuple

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QUndoStack

from ..core.engine import FeatureStack
from ..core.operations import FeatureStats
from ..core.sections import long_section, rescale_long_profile
from ..core.tools import Mode, Tool
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io import scenario
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from ..qgis_io.scenario import ScenarioError
from .help_texts import (DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER, NO_FEATURES_SELECTED, NO_SESSION,
                         RESULT_LAYER_REMOVED, SCENARIO_NOT_APPLIED, SESSION_ENDED_DEM_REMOVED, TOOL_LABELS,
                         UNDO_ADD, UNDO_DELETE, UNDO_PROFILE, UNDO_RENAME, UNDO_REORDER, UNDO_SETTINGS, UNDO_SHAPE,
                         UNDO_TURN_OFF, UNDO_TURN_ON)
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
        except (OSError, RuntimeError, MemoryError) as error:
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
        self._closing = True
        try:
            if self.layers is not None:
                self.layers.remove()
        finally:
            self._closing = False
        self._drop_session()

    def shutdown(self) -> None:
        """Close the session and stop listening to the project (plugin unload)."""
        self.close()
        self.project.layersRemoved.disconnect(self._on_layers_removed)
        self.project.cleared.disconnect(self._drop_session)
        self.project.aboutToBeCleared.disconnect(self._drop_session)

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
        self.cancel_preview()  # the committed result replaces whatever the overlay was showing
        feature = self.find(fid)
        if feature is None:
            return
        text, key = _describe(feature, changes)
        self._commit([replace(f, **changes) if f.id == fid else f for f in self._features], text, key)

    def set_enabled(self, fid: str, enabled: bool) -> None:
        self.update_feature(fid, enabled=bool(enabled))

    def delete_feature(self, fid: str) -> None:
        feature = self.find(fid)
        if feature is not None:
            self._commit([f for f in self._features if f.id != fid], UNDO_DELETE.format(feature.name))

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
        """Whether the features differ from the last save or load of a scenario. Follows undo:
        undoing back to the saved state makes the scenario clean again."""
        return not self.undo_stack.isClean()

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
        created = self._created if path == self._scenario_path else ""
        meta = scenario.dem_meta(self.info, self.stack.original, version=plugin_version(), created=created)
        written = scenario.save(path, self._features, meta, crs_wkt=getattr(self.info, "crs_wkt", ""))
        self._scenario_path = path
        self._created = written.created
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
        self._scenario_path = path
        self._created = meta.created
        self.undo_stack.clear()   # the history belonged to the features that were just replaced
        self.sessionChanged.emit()

    def _forget_scenario(self) -> None:
        self._scenario_path = None
        self._created = ""
        self.undo_stack.clear()

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
            return True
        if not self._set(after):
            return False
        self.undo_stack.push(FeatureListChange(self._restore, before, after, text, key))
        return True

    def _restore(self, features) -> None:
        """Undo or redo. Runs inside QUndoStack from a button or a key, so it never raises: `_set`
        already turns an engine failure into a message."""
        self.cancel_preview()
        if self.stack is not None:
            self._set(features)
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
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)


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
```

Replace the whole file:

**File:** `terrain_sketch/gui/help_texts.py`
```python
"""Every description, example, tooltip and message the user reads, in one place.

Translation, and a deliberate deviation from the spec. Spec §2 ("In scope (v1)") asks for every
string to be wrapped in `tr()` so it can be translated later. That does not work for strings held
in a module like this one: `tr()` extracts only string *literals*, so `self.tr(SOME_CONSTANT)` at
the point of use produces nothing for a translator while looking like it does. These are therefore
plain strings, and the call sites pass them straight through.

The spec's intent still holds — the strings stay in one place, which is what makes translating
them later a contained job. When that happens, mark them here (with `QT_TRANSLATE_NOOP` or by
moving them into the classes that show them); widget captions already call `self.tr("literal")`
and keep working unchanged.
"""
from __future__ import annotations

from ..core.operations import FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS, FLAG_NODATA_REFERENCE, FLAG_OUTSIDE
from ..core.tools import PixelMode, Tool

TOOL_LABELS = {
    Tool.INTERPOLATE: "Interpolate",
    Tool.RAISE_PATH: "Raise path",
    Tool.LOWER_PATH: "Lower path",
    Tool.RAISE_FLAT: "Raise flat",
    Tool.LOWER_FLAT: "Lower flat",
    Tool.ADD: "Add to terrain",
    Tool.SUBTRACT: "Subtract from terrain",
}

TOOL_SUMMARIES = {
    Tool.INTERPOLATE: "A straight grade between the terrain at the start and end of the path, or a smooth "
                      "surface between the corners of an area. Example: cut through an embankment that "
                      "blocks a flow path, or fill an old ditch.",
    Tool.RAISE_PATH: "Adds material along the path, following the terrain uphill or downhill; it never "
                     "removes material. Example: a wall or emergency dike along a river bank.",
    Tool.LOWER_PATH: "Removes material along the path, following the terrain; it never adds material. "
                     "Example: a ditch or swale that drains a road towards a pond.",
    Tool.RAISE_FLAT: "A level top at the highest point of the path or outline plus the height. "
                     "Example: a flat dam, or building footprints.",
    Tool.LOWER_FLAT: "A level bottom at the lowest point of the path or outline minus the depth. "
                     "Example: a flat culvert, or a retention basin.",
    Tool.ADD: "Raises every selected cell by the height, keeping the relief. "
              "Example: an inflatable flood barrier on a street.",
    Tool.SUBTRACT: "Lowers every selected cell by the depth, keeping the slope changes. "
                   "Example: a pipe trench in a road, or deepening a canal to its bed.",
}

PIXEL_MODE_LABELS = {
    PixelMode.ALL_TOUCHED: "All touched",
    PixelMode.CENTRE: "Centre inside",
    PixelMode.FULLY_INSIDE: "Fully inside",
}

PIXEL_MODE_TIPS = {
    PixelMode.ALL_TOUCHED: "Every pixel the shape touches (generous).",
    PixelMode.CENTRE: "Pixels whose centre lies inside the shape (closest to the true area).",
    PixelMode.FULLY_INSIDE: "Only pixels completely inside the shape (strict).",
}

FLAG_TEXTS = {
    FLAG_OUTSIDE: "This feature lies outside the DEM.",
    FLAG_NO_PIXELS: "No pixels are selected — try 'All touched' or a larger width.",
    FLAG_NODATA_REFERENCE: "The start, end or edge of this feature lies outside the DEM or on nodata.",
    FLAG_BAD_GEOMETRY: "The shape of this feature cannot be used.",
}

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Sketch never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Sketch session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Sketch layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."
SHAPE_NOT_TRANSFORMED = ("This feature's shape cannot be shown in the map's coordinate system, so it cannot "
                         "be zoomed to or edited here. Set the project to the DEM's coordinate system and "
                         "try again.")
EXPORT_REPLACE = "{} already exists. Replace it?"

# What Undo and Redo will do, shown as "Undo Add Dike 1" in their buttons' tooltips.
UNDO_ADD = "Add {}"
UNDO_DELETE = "Delete {}"
UNDO_RENAME = "Rename {}"
UNDO_TURN_ON = "Turn on {}"
UNDO_TURN_OFF = "Turn off {}"
UNDO_REORDER = "Reorder features"
UNDO_SHAPE = "Edit the shape of {}"
UNDO_PROFILE = "Change the profile of {}"
UNDO_SETTINGS = "Change the settings of {}"


def amount_label(tool: Tool) -> str | None:
    """Label of the amount field, or None when the tool has no amount."""
    if tool is Tool.INTERPOLATE:
        return None
    if tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT):
        return "Depth"
    return "Height"

PROFILE_EMPTY_HINT = "Select or draw a feature to edit its shape here."
CUSTOM_PROFILE_NOTE = ("Custom long profile: the heights are fixed and no longer follow the "
                       "terrain underneath. Use Reset to rule to go back.")
AREA_LONG_SECTION_HINT = "A section through an area arrives in a later version."
AREA_LONG_SECTION_NOTE = ("An area has no long profile to edit. A section through the feature "
                          "arrives in a later version; until then, use the cross profile on the "
                          "left to shape its sides.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
SYMMETRIC_TIP = ("While this is ticked, break points are mirrored to the other side of the path. "
                 "Width and side slope are single values that always apply to both sides.")
AMOUNT_IS_CUSTOM = ("The long profile was edited by hand, so its heights are fixed. Use "
                    "Reset to rule in the profile panel to drive the shape from this value again.")


TOOL_EXAMPLES = {
    Tool.INTERPOLATE: ("A bridge or culvert was captured as a solid bank across a channel, so "
                       "water cannot pass. Draw a line along the channel through it and Terrain "
                       "Sketch runs a smooth grade between the two ends."),
    Tool.RAISE_PATH: ("A 1.5 m flood embankment along a river. Draw the line the crest follows, "
                      "set Height 1.5 m, Width 3 m and a 1:3 side slope."),
    Tool.LOWER_PATH: ("A swale carrying runoff to a pond. Draw its route, set Depth 0.6 m and "
                      "Width 2 m; the slopes tie it back into the ground."),
    Tool.RAISE_FLAT: ("A building pad above the flood level. Draw the outline and set the height "
                      "above the highest point on the outline you draw, so the whole pad sits "
                      "level."),
    Tool.LOWER_FLAT: ("A detention basin. Draw the outline, set Depth 1.2 m, and set Slopes to "
                      "Inside the outline so the sides slope down within it instead of the basin "
                      "growing outwards; the bottom comes out flat."),
    Tool.ADD: ("A 0.3 m layer of fill over a field. Draw the outline; the ground keeps its shape "
               "and every cell rises by the same amount."),
    Tool.SUBTRACT: ("Stripping 0.2 m of topsoil. Draw the outline; the ground keeps its shape and "
                    "every cell drops by the same amount."),
}

TOOL_DESCRIPTIONS = {
    Tool.INTERPOLATE: ("Replaces the terrain under the shape with a smooth grade between its "
                       "edges, so a missing or wrong patch is bridged rather than raised or cut."),
    Tool.RAISE_PATH: ("Builds a raised corridor along a line: a flat crest of the width you set, "
                      "with side slopes running down to meet the ground."),
    Tool.LOWER_PATH: ("Cuts a channel along a line: a flat bottom of the width you set, with "
                      "sides sloping up to meet the ground."),
    Tool.RAISE_FLAT: ("Lifts everything inside the shape to one level, measured from the highest "
                      "point on the line or outline you draw, with slopes tying the edge back "
                      "into the ground."),
    Tool.LOWER_FLAT: ("Cuts everything inside the shape down to one level, measured from the "
                      "lowest point on the line or outline you draw, with slopes tying the edge "
                      "back in."),
    Tool.ADD: "Adds the same height to every cell inside the shape; the terrain keeps its shape.",
    Tool.SUBTRACT: ("Takes the same height off every cell inside the shape; the terrain keeps "
                    "its shape."),
}

FIELD_TIPS = {
    "amount": ("How far the feature rises (height) or cuts (depth): above or below the straight "
               "grade between the path's ends, the highest or lowest point of the path or "
               "outline, or the terrain itself for Add and Subtract. For a 1.5 m embankment, "
               "set 1.5."),
    "width": ("How wide the flat part is — the crest of a dike, or the bottom of a ditch. A farm "
              "track is about 3 m; a footpath about 1.5 m."),
    "slope_n": ("How far the side slope runs out for every metre of height. 1:3 means 3 m "
                "outwards per 1 m up, about the steepest a mown grass embankment usually gets. "
                "0 means no side slopes at all."),
    "reach": ("The side slopes stop this far from the edge even if they have not met the ground. "
              "Set 5 m to keep a 1.5 m embankment out of a neighbouring plot that starts 5 m "
              "from the crest."),
    "slopes_inside": ("Inside: the outline is the top edge and the slopes run down within it — a "
                      "pond. Outside: the outline is the flat part and the slopes run out beyond "
                      "it — a raised pad."),
    "pixel_mode": ("Which cells count as covered by your shape. Narrow features can miss every "
                   "cell centre, which is when All touched helps."),
}

NO_FEATURES_SELECTED = ("Nothing is selected in that layer. Untick \'Selected features only\', or "
                        "select the features you want on the map first.")
EMPTY_LAYER = "That layer has no features to use."
PICK_A_LAYER = "Pick a layer above first."


def tool_tooltip(tool: Tool) -> str:
    """What a gallery item shows on hover: what the tool does, then a worked example."""
    return f"{TOOL_DESCRIPTIONS[tool]}\n\n{TOOL_EXAMPLES[tool]}"

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Sketch cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float | None) -> str:
    """A volume a user can read at a glance: no decimals once it is past a hundred.

    Cut and fill are magnitudes, so a minus sign here can only be floating-point residue —
    a negative zero out of a subtraction, or a few millilitres left over a million cells.
    Either would reach the user as "-0.00 m³", which reads as a bug, so the sign is dropped
    from anything that rounds to zero."""
    if value is None:
        return NO_VOLUME_YET
    size = abs(value)
    text = f"{value:,.0f}" if size >= 100.0 else f"{value:,.1f}" if size >= 1.0 else f"{value:.2f}"
    if text.startswith("-") and not any(digit in "123456789" for digit in text):
        text = text[1:]
    return f"{text} m³"


UNSAVED_CHANGES = ("This scenario has changes that are not saved. Save them before continuing?")
SCENARIO_SAVED = "Scenario saved to {}"
SCENARIO_REPLACE = "{} already exists. Replace it?"
SCENARIO_OPENED = "Scenario opened from {}"
SCENARIO_DEM_DIFFERS = ("This scenario was made on a DEM with a different {}.\n\n"
                        "Open it on this DEM anyway? The features keep their map position, so check "
                        "the result before using it.\n\n"
                        "Choose No to keep your current work, then pick the DEM the scenario was made "
                        "for and press Start before opening it.")
SCENARIO_NOT_APPLIED = ("The scenario could not be applied to this DEM, so it was not opened. "
                        "Your current features are unchanged.")
UNSAVED_BEFORE_CLOSING = ("Terrain Sketch is closing this scenario, and it has changes that are not "
                          "saved. Save them now?")
```

Create:

**File:** `terrain_sketch/gui/undo.py`
```python
"""Undo and redo for the feature list (spec §7.4)."""
from __future__ import annotations

from qgis.PyQt.QtGui import QUndoCommand

MERGE_ID = 1  # every mergeable change shares one id; `key` decides whether two actually merge


class FeatureListChange(QUndoCommand):
    """One change to the feature list, kept as the whole list before and after it.

    Features are immutable, so the two lists share every feature the change did not touch and
    cost little more than pointers. Undo and redo hand a list back to the controller, which
    recomputes only the window that differs — the same path as the original edit.

    A change is pushed after it has already been applied, so the first `redo()`, which Qt calls
    on push, does nothing. Changes with the same `key` (the same settings of the same feature,
    e.g. every step of a spin box) merge into one step; Qt never merges into the step a scenario
    was saved at, so undo can always return to exactly what is on disk."""

    def __init__(self, restore, before, after, text: str, key=None):
        super().__init__(text)
        self._restore = restore
        self.before = tuple(before)
        self.after = tuple(after)
        self.key = key
        self._pushed = False

    def id(self) -> int:  # noqa: A003 — Qt override
        return MERGE_ID if self.key is not None else -1

    def redo(self) -> None:
        if not self._pushed:
            self._pushed = True
            return
        self._restore(self.after)

    def undo(self) -> None:
        self._restore(self.before)

    def mergeWith(self, other) -> bool:  # noqa: N802 — Qt override
        if other.key != self.key:
            return False
        self.after = other.after
        self.setObsolete(self.after == self.before)   # stepped back to where it started: no step at all
        return True
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_undo.py` → Expected: `21 passed`
Run: `scripts/test.sh` → Expected: `399 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/undo.py tests/qgis/test_undo.py
git commit -m "feat(gui): undo and redo for every change to the feature list"
```

---

### Task 3: Undo in the panel

**Files:**
- Modify: `terrain_sketch/gui/main_dock.py`, `terrain_sketch/gui/undo.py`
- Test: `tests/qgis/qgis_helpers.py`, `tests/qgis/test_undo_panel.py`

**Interfaces:**
- Consumes: Task 2's `undo_stack` and `featuresRestored`; `MainDock.stop_editing`, `end_drawing`, `_brush_fid`, `feature_view`, `pages`, `properties.show_feature`; `SketchTool` (`map_tools/base.py`); `ProfileDock` passed as `profiles`.
- Produces: `undo.UndoKeys(stack, applies=lambda: True, parent=None)`; `MainDock.toolbar` (`QToolBar`), `undo_action`, `redo_action`, `undo_button`, `redo_button`, `undo_keys`, `canvas_undo_keys`; the Hillshade checkbox moves to the DEM row. `qgis_helpers.fake_iface()` stubs `iconSize` like the real interface.

- [ ] **Step 1: Write the failing test**

`fake_iface` gains an `iconSize` stub — the panel now asks the interface for QGIS's docked-toolbar icon size, and a bare `Mock` would hand back something `setIconSize` rejects.

**File:** `tests/qgis/qgis_helpers.py`
```python
"""Helpers for the QGIS integration tests: small GeoTIFF DEMs on a UTM grid (EPSG:25832)."""
from unittest import mock

import numpy as np
from osgeo import gdal
from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsRectangle, QgsVectorLayer)
from qgis.gui import QgisInterface, QgsMapCanvas, QgsMessageBarItem
from qgis.PyQt.QtCore import QEventLoop, QSize, QTimer
from qgis.PyQt.QtWidgets import QMainWindow

gdal.UseExceptions()

X0, Y0, CELL = 612000.0, 6178040.0, 1.0  # top-left corner of the test DEMs
UTM = QgsCoordinateReferenceSystem("EPSG:25832")


def write_dem(path, array, crs="EPSG:25832", nodata=-9999.0, gt=None, bands=1) -> str:
    array = np.asarray(array, dtype=np.float32)
    rows, cols = array.shape
    ds = gdal.GetDriverByName("GTiff").Create(str(path), cols, rows, bands, gdal.GDT_Float32)
    ds.SetGeoTransform(gt or (X0, CELL, 0.0, Y0, 0.0, -CELL))
    ds.SetProjection(crs)
    for b in range(1, bands + 1):
        band = ds.GetRasterBand(b)
        band.WriteArray(array)
        if nodata is not None:
            band.SetNoDataValue(nodata)
    ds.FlushCache()
    ds = None
    return str(path)


def dem_layer(tmp_path, array=None, name="dem", **kw) -> QgsRasterLayer:
    """A 40 x 40 flat 10 m DEM (or `array`) added to the project."""
    if array is None:
        array = np.full((40, 40), 10.0, np.float32)
    layer = QgsRasterLayer(write_dem(tmp_path / f"{name}.tif", array, **kw), name)
    assert layer.isValid()
    QgsProject.instance().addMapLayer(layer)
    return layer


def world(col: float, row: float) -> tuple[float, float]:
    """Map coordinates of a cell centre on the test grid."""
    return X0 + (col + 0.5) * CELL, Y0 - (row + 0.5) * CELL


def line_through(c0, r0, c1, r1) -> QgsGeometry:
    return QgsGeometry.fromPolylineXY([QgsPointXY(*world(c0, r0)), QgsPointXY(*world(c1, r1))])


def square(c0, r0, c1, r1) -> QgsGeometry:
    corners = [world(c0, r0), world(c1, r0), world(c1, r1), world(c0, r1), world(c0, r0)]
    return QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in corners]])


def sample(layer, col, row) -> float:
    return layer.dataProvider().sample(QgsPointXY(*world(col, row)), 1)[0]


def read_tif(path):
    ds = gdal.Open(str(path))
    band = ds.GetRasterBand(1)
    return band.ReadAsArray(), band.GetNoDataValue()


def fake_iface():
    """A QgisInterface mock with a real main window and a UTM map canvas over the test grid.

    The canvas has no parent so it lives as long as a test holds it, even after the mock is gone."""
    iface = mock.Mock(spec=QgisInterface)
    iface.mainWindow.return_value = QMainWindow()
    canvas = QgsMapCanvas()
    canvas.resize(400, 400)
    canvas.setDestinationCrs(UTM)
    canvas.setExtent(QgsRectangle(X0, Y0 - 40, X0 + 40, Y0))
    iface.mapCanvas.return_value = canvas
    iface.iconSize.return_value = QSize(16, 16)   # QGIS's default docked-toolbar icon size
    # The bar stays a Mock so tests can assert pushMessage was called, but createMessage hands
    # back a REAL item: the panel builds a button onto it, and a Mock there would let a broken
    # widget path pass unnoticed — it aborted the interpreter instead.
    bar = mock.Mock()
    bar.createMessage.side_effect = lambda title, text: QgsMessageBarItem(title, text)
    iface.messageBar.return_value = bar
    return iface


def start_session(tmp_path, array=None):
    """A SketchController with a session on a fresh test DEM."""
    from terrain_sketch.gui.controller import SketchController  # imported late: the GUI package comes in a later task

    controller = SketchController(QgsProject.instance())
    controller.set_dem(dem_layer(tmp_path, array))
    return controller


def spin_event_loop(ms: int) -> None:
    """Run the Qt event loop for `ms` milliseconds, so a queued QTimer (like the preview
    throttle) actually fires instead of just sitting there unexercised in a synchronous test."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def line_layer(name, geometries, add_to_project=True) -> QgsVectorLayer:
    """A memory line layer in the test CRS holding `geometries`."""
    layer = QgsVectorLayer("LineString?crs=EPSG:25832", name, "memory")
    features = []
    for geometry in geometries:
        feature = QgsFeature()
        feature.setGeometry(geometry)
        features.append(feature)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    if add_to_project:
        QgsProject.instance().addMapLayer(layer)
    return layer
```

**File:** `tests/qgis/test_undo_panel.py`
```python
"""Undo and redo from the panel: the buttons, Ctrl+Z where it belongs, and what the panel does after."""
from qgis.core import QgsProject
from qgis.gui import QgsMapToolPan
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QKeySequence
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, spin_event_loop, square
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import UNDO_ADD
from terrain_sketch.gui.main_dock import PAGE_PROPERTIES, MainDock
from terrain_sketch.gui.profile_dock import ProfileDock
from terrain_sketch.gui.selection import Method


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def in_a_window(iface, dock):
    """The dock inside an active main window that, like QGIS, binds Ctrl+Z to its own undo."""
    window = iface.mainWindow()
    window.setCentralWidget(iface.mapCanvas())
    window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
    qgis_undo = []
    action = QAction("QGIS undo", window)
    action.setShortcuts([QKeySequence(QKeySequence.StandardKey.Undo), QKeySequence(QKeySequence.StandardKey.Redo)])
    action.triggered.connect(lambda: qgis_undo.append(True))
    window.addAction(action)
    window.show()
    window.activateWindow()
    spin_event_loop(50)
    return window, qgis_undo


def press(widget, standard_key):
    widget.setFocus()
    spin_event_loop(10)
    QTest.keySequence(QApplication.focusWidget() or widget, QKeySequence(standard_key))
    spin_event_loop(10)


def test_the_undo_buttons_follow_the_history_and_say_what_they_will_do(tmp_path):
    _iface, c, dock = panel(tmp_path)
    assert not dock.undo_button.icon().isNull() and not dock.redo_button.icon().isNull()
    assert not dock.undo_button.isEnabled() and not dock.redo_button.isEnabled()
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dock.undo_button.isEnabled() and not dock.redo_button.isEnabled()
    assert UNDO_ADD.format("Raise path 1") in dock.undo_button.toolTip()
    dock.undo_button.click()
    assert c.features == ()
    assert dock.redo_button.isEnabled() and UNDO_ADD.format("Raise path 1") in dock.redo_button.toolTip()
    dock.redo_button.click()
    assert len(c.features) == 1


def test_ctrl_z_in_the_panel_undoes_terrain_sketch_not_qgis(tmp_path):
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    press(dock.feature_view, QKeySequence.StandardKey.Undo)
    assert c.features == () and qgis_undo == []
    press(dock.feature_view, QKeySequence.StandardKey.Redo)
    assert len(c.features) == 1 and qgis_undo == []


def test_ctrl_z_in_the_profiles_panel_undoes_terrain_sketch_too(tmp_path):
    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    profiles = ProfileDock(c)
    dock = MainDock(iface, c, profiles)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    window, qgis_undo = in_a_window(iface, dock)
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, profiles)
    spin_event_loop(20)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    press(profiles.widget(), QKeySequence.StandardKey.Undo)
    assert c.features == () and qgis_undo == []


def test_ctrl_z_on_the_map_undoes_terrain_sketch_while_one_of_its_tools_is_active(tmp_path):
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert iface.mapCanvas().mapTool() is dock.draw_tool
    press(iface.mapCanvas(), QKeySequence.StandardKey.Undo)
    assert c.features == () and qgis_undo == []
    assert dock.draw_tool is not None                 # drawing a new feature carries on


def test_ctrl_z_on_the_map_is_left_to_qgis_with_any_other_tool(tmp_path):
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pan = QgsMapToolPan(iface.mapCanvas())
    iface.mapCanvas().setMapTool(pan)
    press(iface.mapCanvas(), QKeySequence.StandardKey.Undo)
    assert len(c.features) == 1 and qgis_undo == [True]


def test_undo_stops_a_vertex_edit_that_would_put_the_old_outline_back(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.set_geometry(dike.id, line_through(5, 24, 34, 28), UTM)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.undo_button.click()
    assert dock.edit_tool is None and not dock.edit_button.isChecked()


def test_undo_stops_a_brush_that_extends_a_feature(tmp_path):
    _iface, c, dock = panel(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    c.update_feature(pond.id, amount=2.0)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock.draw_tool is not None and dock._brush_fid == pond.id
    dock.undo_button.click()
    assert dock.draw_tool is None and dock._brush_fid is None


def test_undo_reloads_the_properties_page(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.pages.currentIndex() == PAGE_PROPERTIES
    dock.properties.amount.setValue(2.5)                   # through the page, as a user would
    assert c.find(dike.id).amount == 2.5
    dock.undo_button.click()
    assert c.find(dike.id).amount == 1.0
    assert dock.properties.amount.value() == 1.0           # not still showing the undone 2.5


def test_the_panel_header_does_not_make_the_panel_wider(tmp_path):
    """Seven buttons in a row forced a right-hand panel past 400 px; in a toolbar the ones that do
    not fit go behind », so the header is no longer what sets the panel's minimum width."""
    _iface, _c, dock = panel(tmp_path)
    dock.show()
    assert dock.toolbar.minimumSizeHint().width() < 100
    assert dock.widget().minimumSizeHint().width() < 360
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_undo_panel.py`
Expected: FAIL (8 failed, 1 passed) with `AttributeError: 'MainDock' object has no attribute 'undo_button'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/gui/main_dock.py`
```python
"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsApplication, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsProject
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (EXPORT_REPLACE, REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                         SCENARIO_SAVED, SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES)
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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)

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
        self.export_button = QToolButton()
        self.export_button.setIcon(QgsApplication.getThemeIcon("/mActionSharingExport.svg"))
        self.export_button.setText(self.tr("Export DEM…"))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setToolTip(self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
        self.toolbar.addWidget(self.export_button)
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
        self.canvas_undo_keys = UndoKeys(controller.undo_stack, applies=self._sketch_tool_active, parent=self)
        iface.mapCanvas().installEventFilter(self.canvas_undo_keys)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        tool, self.draw_tool, self._brush_fid = self.draw_tool, None, None
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
        self.iface.mapCanvas().scene().removeItem(self.highlight)
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
                       self.edit_button, self.feature_view, *self.scenario_buttons):
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
        self._asked_about_unsaved = True   # the user has just answered; closing the old session must not ask again
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
        finally:
            self._asked_about_unsaved = False

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
            try:
                initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
            except QgsCsException:
                self._brush_fid = None
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
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.setText(self._drawing_hint(method))
        self.hint.show()

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
        carries on. The Properties page reloads its fields, which otherwise keep the undone values."""
        self.stop_editing()
        if self._brush_fid is not None:
            self.end_drawing()
        fid = self.feature_view.selected_id()
        if self.pages.currentIndex() == PAGE_PROPERTIES and fid is not None and self.controller.find(fid) is not None:
            self.properties.show_feature(fid)

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map."""
        if fid is None or not self.controller.has_dem or fid not in {f.id for f in self.controller.features}:
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        geometry = self._to_canvas(self.controller.feature_geometry(fid))
        self.highlight.reset(geometry.type())
        self.highlight.setToGeometry(geometry, None)

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
        try:
            differences = self.controller.scenario_differences(path)
            if differences and not self.confirm(SCENARIO_DEM_DIFFERS.format(", ".join(differences))):
                return
            self.stop_tools()
            self.controller.open_scenario(path)
        except ScenarioError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))
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
        self._show_message(Qgis.MessageLevel.Success, self.tr("Exported the modified DEM to {}").format(path))

    def _context_menu(self, position) -> None:
        index = self.feature_view.indexAt(position)
        if not index.isValid():
            return
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(QgsApplication.getThemeIcon("/mActionZoomToLayer.svg"), self.tr("Zoom to feature"),
                       lambda: self._zoom_to(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"),
                       lambda: self.controller.delete_feature(fid))
        menu.exec(self.feature_view.viewport().mapToGlobal(position))

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
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export modified DEM"), "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
            # as for scenarios: the dialog asked about replacing the name as typed, not this one
            if os.path.exists(path) and not self.confirm(EXPORT_REPLACE.format(os.path.basename(path))):
                return ""
        return path
```

Replace the whole file:

**File:** `terrain_sketch/gui/undo.py`
```python
"""Undo and redo for the feature list, and the keys that reach them (spec §7.4)."""
from __future__ import annotations

import traceback

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QEvent, QObject
from qgis.PyQt.QtGui import QKeySequence, QUndoCommand

MERGE_ID = 1  # every mergeable change shares one id; `key` decides whether two actually merge


class FeatureListChange(QUndoCommand):
    """One change to the feature list, kept as the whole list before and after it.

    Features are immutable, so the two lists share every feature the change did not touch and
    cost little more than pointers. Undo and redo hand a list back to the controller, which
    recomputes only the window that differs — the same path as the original edit.

    A change is pushed after it has already been applied, so the first `redo()`, which Qt calls
    on push, does nothing. Changes with the same `key` (the same settings of the same feature,
    e.g. every step of a spin box) merge into one step; Qt never merges into the step a scenario
    was saved at, so undo can always return to exactly what is on disk."""

    def __init__(self, restore, before, after, text: str, key=None):
        super().__init__(text)
        self._restore = restore
        self.before = tuple(before)
        self.after = tuple(after)
        self.key = key
        self._pushed = False

    def id(self) -> int:  # noqa: A003 — Qt override
        return MERGE_ID if self.key is not None else -1

    def redo(self) -> None:
        if not self._pushed:
            self._pushed = True
            return
        self._restore(self.after)

    def undo(self) -> None:
        self._restore(self.before)

    def mergeWith(self, other) -> bool:  # noqa: N802 — Qt override
        if other.key != self.key:
            return False
        self.after = other.after
        self.setObsolete(self.after == self.before)   # stepped back to where it started: no step at all
        return True


class UndoKeys(QObject):
    """Ctrl+Z and Ctrl+Shift+Z for Terrain Sketch while the panel, or the map with a Terrain
    Sketch tool active, has focus — and QGIS's own undo everywhere else.

    Installed as an event filter. QGIS binds the same keys to layer-editing undo in its main
    window, and two shortcuts for one key cancel each other out, so this claims the key during
    `ShortcutOverride` (which Qt sends before resolving shortcuts) and acts on the key press that
    follows. `applies` decides per event whether the keys are ours; it must not raise."""

    def __init__(self, stack, applies=lambda: True, parent=None):
        super().__init__(parent)
        self.stack = stack
        self.applies = applies

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 — Qt override
        kind = event.type()
        if kind not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        try:
            undo = event.matches(QKeySequence.StandardKey.Undo)
            redo = not undo and event.matches(QKeySequence.StandardKey.Redo)
            if not (undo or redo) or not self.applies():
                return False
            if kind == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            (self.stack.undo if undo else self.stack.redo)()
            return True
        except Exception:  # noqa: BLE001 — an event filter must never raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "Terrain Sketch", Qgis.MessageLevel.Critical)
            return False
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_undo_panel.py` → Expected: `9 passed`
Run: `scripts/test.sh` → Expected: `408 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/main_dock.py terrain_sketch/gui/undo.py tests/qgis/qgis_helpers.py tests/qgis/test_undo_panel.py
git commit -m "feat(gui): Undo and Redo buttons, and Ctrl+Z in the Terrain Sketch panels and tools"
```

---

### Task 4: Rename and Duplicate

**Files:**
- Modify: `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/gui/properties_page.py`
- Test: `tests/qgis/test_list_actions.py`

**Interfaces:**
- Consumes: Task 2's `_commit`; `SketchController._unique`; `FeatureListView.edit`, `select_id`; `FeatureListModel.row_of`.
- Produces: `SketchController.duplicate_feature(fid) -> TerrainFeature | None` (turned off, right after the original, undoable); `MainDock.feature_menu(index) -> QMenu | None` with Rename, Duplicate, Zoom to feature, Delete; the Properties title follows a rename; `help_texts.UNDO_DUPLICATE`, `COPY_NAME`.

- [ ] **Step 1: Write the failing test**

**File:** `tests/qgis/test_list_actions.py`
```python
"""The feature list's context menu (spec §7.2): Rename, Duplicate, Zoom to, Delete."""
import numpy as np
from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QAbstractItemView

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import COPY_NAME, UNDO_DUPLICATE
from terrain_sketch.gui.main_dock import PAGE_PROPERTIES, MainDock


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def menu_action(dock, fid, text):
    menu = dock.feature_menu(dock.model.index(dock.model.row_of(fid)))
    return next(action for action in menu.actions() if action.text() == text)


def test_the_menu_offers_rename_duplicate_zoom_and_delete(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    menu = dock.feature_menu(dock.model.index(dock.model.row_of(dike.id)))
    assert [a.text() for a in menu.actions() if not a.isSeparator()] == ["Rename", "Duplicate", "Zoom to feature", "Delete"]
    assert dock.feature_menu(dock.model.index(5)) is None            # off the rows


def test_a_duplicate_copies_everything_turned_off_right_after_the_original(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    c.update_feature(dike.id, amount=2.2, width=5.0, cross_right=((3.0, -0.6),))
    dike = c.find(dike.id)
    before = c.stack.working.data.copy()

    copy = c.duplicate_feature(dike.id)
    assert [f.id for f in c.features] == [dike.id, copy.id, pond.id]
    assert copy.id != dike.id and copy.name == COPY_NAME.format(dike.name)
    for field in ("tool", "mode", "geometry_wkb", "amount", "width", "cross_right", "pixel_mode"):
        assert getattr(copy, field) == getattr(dike, field), field
    assert not copy.enabled
    assert np.array_equal(c.stack.working.data, before)          # the map does not change until it is ticked on
    c.set_enabled(copy.id, True)
    assert not np.array_equal(c.stack.working.data, before)      # which is why: on, it raises the dike again
    c.undo_stack.undo()
    assert c.undo_stack.undoText() == UNDO_DUPLICATE.format(dike.name)
    c.undo_stack.undo()
    assert [f.id for f in c.features] == [dike.id, pond.id]


def test_duplicating_twice_keeps_names_unique(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    first, second = c.duplicate_feature(dike.id), c.duplicate_feature(dike.id)
    assert len({dike.name, first.name, second.name}) == 3


def test_duplicating_a_feature_that_has_gone_does_nothing(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.delete_feature(dike.id)
    assert c.duplicate_feature(dike.id) is None and c.features == ()


def test_duplicate_from_the_menu_selects_the_copy(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    menu_action(dock, dike.id, "Duplicate").trigger()
    assert len(c.features) == 2
    assert dock.feature_view.selected_id() == c.features[1].id


def test_rename_from_the_menu_opens_the_name_for_editing(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.show()
    menu_action(dock, dike.id, "Rename").trigger()
    assert dock.feature_view.state() == QAbstractItemView.State.EditingState


def test_the_properties_title_follows_a_rename_in_the_list(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.pages.currentIndex() == PAGE_PROPERTIES
    dock.model.setData(dock.model.index(dock.model.row_of(dike.id)), "Sea wall")
    assert dock.properties.title.text().startswith("Sea wall")
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_list_actions.py`
Expected: collection error `ImportError: cannot import name 'COPY_NAME' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/gui/controller.py`
```python
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

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QUndoStack

from ..core.engine import FeatureStack
from ..core.operations import FeatureStats
from ..core.sections import long_section, rescale_long_profile
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
                         UNDO_TURN_ON)
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
        except (OSError, RuntimeError, MemoryError) as error:
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
        self._closing = True
        try:
            if self.layers is not None:
                self.layers.remove()
        finally:
            self._closing = False
        self._drop_session()

    def shutdown(self) -> None:
        """Close the session and stop listening to the project (plugin unload)."""
        self.close()
        self.project.layersRemoved.disconnect(self._on_layers_removed)
        self.project.cleared.disconnect(self._drop_session)
        self.project.aboutToBeCleared.disconnect(self._drop_session)

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
        self.cancel_preview()  # the committed result replaces whatever the overlay was showing
        feature = self.find(fid)
        if feature is None:
            return
        text, key = _describe(feature, changes)
        self._commit([replace(f, **changes) if f.id == fid else f for f in self._features], text, key)

    def set_enabled(self, fid: str, enabled: bool) -> None:
        self.update_feature(fid, enabled=bool(enabled))

    def delete_feature(self, fid: str) -> None:
        feature = self.find(fid)
        if feature is not None:
            self._commit([f for f in self._features if f.id != fid], UNDO_DELETE.format(feature.name))

    def duplicate_feature(self, fid: str) -> TerrainFeature | None:
        """A copy of the feature, with every setting and profile, placed right after it in the list.
        It starts turned off: most tools measure from the terrain beneath them, so an identical copy
        on top would not be a copy at all — a raised path would come out twice as high. The user
        moves or reshapes it, then ticks it on. None when the feature no longer exists."""
        feature = self.find(fid)
        if feature is None:
            return None
        copy = replace(feature, id=uuid.uuid4().hex, name=self._unique(COPY_NAME.format(feature.name)),
                       enabled=False)
        index = self._features.index(feature)
        features = [*self._features[:index + 1], copy, *self._features[index + 1:]]
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
        """Whether the features differ from the last save or load of a scenario. Follows undo:
        undoing back to the saved state makes the scenario clean again."""
        return not self.undo_stack.isClean()

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
        created = self._created if path == self._scenario_path else ""
        meta = scenario.dem_meta(self.info, self.stack.original, version=plugin_version(), created=created)
        written = scenario.save(path, self._features, meta, crs_wkt=getattr(self.info, "crs_wkt", ""))
        self._scenario_path = path
        self._created = written.created
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
        self._scenario_path = path
        self._created = meta.created
        self.undo_stack.clear()   # the history belonged to the features that were just replaced
        self.sessionChanged.emit()

    def _forget_scenario(self) -> None:
        self._scenario_path = None
        self._created = ""
        self.undo_stack.clear()

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
            return True
        if not self._set(after):
            return False
        self.undo_stack.push(FeatureListChange(self._restore, before, after, text, key))
        return True

    def _restore(self, features) -> None:
        """Undo or redo. Runs inside QUndoStack from a button or a key, so it never raises: `_set`
        already turns an engine failure into a message."""
        self.cancel_preview()
        if self.stack is not None:
            self._set(features)
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
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)


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
```

Replace the whole file:

**File:** `terrain_sketch/gui/help_texts.py`
```python
"""Every description, example, tooltip and message the user reads, in one place.

Translation, and a deliberate deviation from the spec. Spec §2 ("In scope (v1)") asks for every
string to be wrapped in `tr()` so it can be translated later. That does not work for strings held
in a module like this one: `tr()` extracts only string *literals*, so `self.tr(SOME_CONSTANT)` at
the point of use produces nothing for a translator while looking like it does. These are therefore
plain strings, and the call sites pass them straight through.

The spec's intent still holds — the strings stay in one place, which is what makes translating
them later a contained job. When that happens, mark them here (with `QT_TRANSLATE_NOOP` or by
moving them into the classes that show them); widget captions already call `self.tr("literal")`
and keep working unchanged.
"""
from __future__ import annotations

from ..core.operations import FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS, FLAG_NODATA_REFERENCE, FLAG_OUTSIDE
from ..core.tools import PixelMode, Tool

TOOL_LABELS = {
    Tool.INTERPOLATE: "Interpolate",
    Tool.RAISE_PATH: "Raise path",
    Tool.LOWER_PATH: "Lower path",
    Tool.RAISE_FLAT: "Raise flat",
    Tool.LOWER_FLAT: "Lower flat",
    Tool.ADD: "Add to terrain",
    Tool.SUBTRACT: "Subtract from terrain",
}

TOOL_SUMMARIES = {
    Tool.INTERPOLATE: "A straight grade between the terrain at the start and end of the path, or a smooth "
                      "surface between the corners of an area. Example: cut through an embankment that "
                      "blocks a flow path, or fill an old ditch.",
    Tool.RAISE_PATH: "Adds material along the path, following the terrain uphill or downhill; it never "
                     "removes material. Example: a wall or emergency dike along a river bank.",
    Tool.LOWER_PATH: "Removes material along the path, following the terrain; it never adds material. "
                     "Example: a ditch or swale that drains a road towards a pond.",
    Tool.RAISE_FLAT: "A level top at the highest point of the path or outline plus the height. "
                     "Example: a flat dam, or building footprints.",
    Tool.LOWER_FLAT: "A level bottom at the lowest point of the path or outline minus the depth. "
                     "Example: a flat culvert, or a retention basin.",
    Tool.ADD: "Raises every selected cell by the height, keeping the relief. "
              "Example: an inflatable flood barrier on a street.",
    Tool.SUBTRACT: "Lowers every selected cell by the depth, keeping the slope changes. "
                   "Example: a pipe trench in a road, or deepening a canal to its bed.",
}

PIXEL_MODE_LABELS = {
    PixelMode.ALL_TOUCHED: "All touched",
    PixelMode.CENTRE: "Centre inside",
    PixelMode.FULLY_INSIDE: "Fully inside",
}

PIXEL_MODE_TIPS = {
    PixelMode.ALL_TOUCHED: "Every pixel the shape touches (generous).",
    PixelMode.CENTRE: "Pixels whose centre lies inside the shape (closest to the true area).",
    PixelMode.FULLY_INSIDE: "Only pixels completely inside the shape (strict).",
}

FLAG_TEXTS = {
    FLAG_OUTSIDE: "This feature lies outside the DEM.",
    FLAG_NO_PIXELS: "No pixels are selected — try 'All touched' or a larger width.",
    FLAG_NODATA_REFERENCE: "The start, end or edge of this feature lies outside the DEM or on nodata.",
    FLAG_BAD_GEOMETRY: "The shape of this feature cannot be used.",
}

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Sketch never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Sketch session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Sketch layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."
SHAPE_NOT_TRANSFORMED = ("This feature's shape cannot be shown in the map's coordinate system, so it cannot "
                         "be zoomed to or edited here. Set the project to the DEM's coordinate system and "
                         "try again.")
EXPORT_REPLACE = "{} already exists. Replace it?"

# What Undo and Redo will do, shown as "Undo Add Dike 1" in their buttons' tooltips.
UNDO_ADD = "Add {}"
UNDO_DELETE = "Delete {}"
UNDO_RENAME = "Rename {}"
UNDO_TURN_ON = "Turn on {}"
UNDO_TURN_OFF = "Turn off {}"
UNDO_REORDER = "Reorder features"
UNDO_SHAPE = "Edit the shape of {}"
UNDO_PROFILE = "Change the profile of {}"
UNDO_SETTINGS = "Change the settings of {}"
UNDO_DUPLICATE = "Duplicate {}"
COPY_NAME = "{} (copy)"


def amount_label(tool: Tool) -> str | None:
    """Label of the amount field, or None when the tool has no amount."""
    if tool is Tool.INTERPOLATE:
        return None
    if tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT):
        return "Depth"
    return "Height"

PROFILE_EMPTY_HINT = "Select or draw a feature to edit its shape here."
CUSTOM_PROFILE_NOTE = ("Custom long profile: the heights are fixed and no longer follow the "
                       "terrain underneath. Use Reset to rule to go back.")
AREA_LONG_SECTION_HINT = "A section through an area arrives in a later version."
AREA_LONG_SECTION_NOTE = ("An area has no long profile to edit. A section through the feature "
                          "arrives in a later version; until then, use the cross profile on the "
                          "left to shape its sides.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
SYMMETRIC_TIP = ("While this is ticked, break points are mirrored to the other side of the path. "
                 "Width and side slope are single values that always apply to both sides.")
AMOUNT_IS_CUSTOM = ("The long profile was edited by hand, so its heights are fixed. Use "
                    "Reset to rule in the profile panel to drive the shape from this value again.")


TOOL_EXAMPLES = {
    Tool.INTERPOLATE: ("A bridge or culvert was captured as a solid bank across a channel, so "
                       "water cannot pass. Draw a line along the channel through it and Terrain "
                       "Sketch runs a smooth grade between the two ends."),
    Tool.RAISE_PATH: ("A 1.5 m flood embankment along a river. Draw the line the crest follows, "
                      "set Height 1.5 m, Width 3 m and a 1:3 side slope."),
    Tool.LOWER_PATH: ("A swale carrying runoff to a pond. Draw its route, set Depth 0.6 m and "
                      "Width 2 m; the slopes tie it back into the ground."),
    Tool.RAISE_FLAT: ("A building pad above the flood level. Draw the outline and set the height "
                      "above the highest point on the outline you draw, so the whole pad sits "
                      "level."),
    Tool.LOWER_FLAT: ("A detention basin. Draw the outline, set Depth 1.2 m, and set Slopes to "
                      "Inside the outline so the sides slope down within it instead of the basin "
                      "growing outwards; the bottom comes out flat."),
    Tool.ADD: ("A 0.3 m layer of fill over a field. Draw the outline; the ground keeps its shape "
               "and every cell rises by the same amount."),
    Tool.SUBTRACT: ("Stripping 0.2 m of topsoil. Draw the outline; the ground keeps its shape and "
                    "every cell drops by the same amount."),
}

TOOL_DESCRIPTIONS = {
    Tool.INTERPOLATE: ("Replaces the terrain under the shape with a smooth grade between its "
                       "edges, so a missing or wrong patch is bridged rather than raised or cut."),
    Tool.RAISE_PATH: ("Builds a raised corridor along a line: a flat crest of the width you set, "
                      "with side slopes running down to meet the ground."),
    Tool.LOWER_PATH: ("Cuts a channel along a line: a flat bottom of the width you set, with "
                      "sides sloping up to meet the ground."),
    Tool.RAISE_FLAT: ("Lifts everything inside the shape to one level, measured from the highest "
                      "point on the line or outline you draw, with slopes tying the edge back "
                      "into the ground."),
    Tool.LOWER_FLAT: ("Cuts everything inside the shape down to one level, measured from the "
                      "lowest point on the line or outline you draw, with slopes tying the edge "
                      "back in."),
    Tool.ADD: "Adds the same height to every cell inside the shape; the terrain keeps its shape.",
    Tool.SUBTRACT: ("Takes the same height off every cell inside the shape; the terrain keeps "
                    "its shape."),
}

FIELD_TIPS = {
    "amount": ("How far the feature rises (height) or cuts (depth): above or below the straight "
               "grade between the path's ends, the highest or lowest point of the path or "
               "outline, or the terrain itself for Add and Subtract. For a 1.5 m embankment, "
               "set 1.5."),
    "width": ("How wide the flat part is — the crest of a dike, or the bottom of a ditch. A farm "
              "track is about 3 m; a footpath about 1.5 m."),
    "slope_n": ("How far the side slope runs out for every metre of height. 1:3 means 3 m "
                "outwards per 1 m up, about the steepest a mown grass embankment usually gets. "
                "0 means no side slopes at all."),
    "reach": ("The side slopes stop this far from the edge even if they have not met the ground. "
              "Set 5 m to keep a 1.5 m embankment out of a neighbouring plot that starts 5 m "
              "from the crest."),
    "slopes_inside": ("Inside: the outline is the top edge and the slopes run down within it — a "
                      "pond. Outside: the outline is the flat part and the slopes run out beyond "
                      "it — a raised pad."),
    "pixel_mode": ("Which cells count as covered by your shape. Narrow features can miss every "
                   "cell centre, which is when All touched helps."),
}

NO_FEATURES_SELECTED = ("Nothing is selected in that layer. Untick \'Selected features only\', or "
                        "select the features you want on the map first.")
EMPTY_LAYER = "That layer has no features to use."
PICK_A_LAYER = "Pick a layer above first."


def tool_tooltip(tool: Tool) -> str:
    """What a gallery item shows on hover: what the tool does, then a worked example."""
    return f"{TOOL_DESCRIPTIONS[tool]}\n\n{TOOL_EXAMPLES[tool]}"

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Sketch cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float | None) -> str:
    """A volume a user can read at a glance: no decimals once it is past a hundred.

    Cut and fill are magnitudes, so a minus sign here can only be floating-point residue —
    a negative zero out of a subtraction, or a few millilitres left over a million cells.
    Either would reach the user as "-0.00 m³", which reads as a bug, so the sign is dropped
    from anything that rounds to zero."""
    if value is None:
        return NO_VOLUME_YET
    size = abs(value)
    text = f"{value:,.0f}" if size >= 100.0 else f"{value:,.1f}" if size >= 1.0 else f"{value:.2f}"
    if text.startswith("-") and not any(digit in "123456789" for digit in text):
        text = text[1:]
    return f"{text} m³"


UNSAVED_CHANGES = ("This scenario has changes that are not saved. Save them before continuing?")
SCENARIO_SAVED = "Scenario saved to {}"
SCENARIO_REPLACE = "{} already exists. Replace it?"
SCENARIO_OPENED = "Scenario opened from {}"
SCENARIO_DEM_DIFFERS = ("This scenario was made on a DEM with a different {}.\n\n"
                        "Open it on this DEM anyway? The features keep their map position, so check "
                        "the result before using it.\n\n"
                        "Choose No to keep your current work, then pick the DEM the scenario was made "
                        "for and press Start before opening it.")
SCENARIO_NOT_APPLIED = ("The scenario could not be applied to this DEM, so it was not opened. "
                        "Your current features are unchanged.")
UNSAVED_BEFORE_CLOSING = ("Terrain Sketch is closing this scenario, and it has changes that are not "
                          "saved. Save them now?")
```

Replace the whole file:

**File:** `terrain_sketch/gui/main_dock.py`
```python
"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsApplication, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsProject
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (EXPORT_REPLACE, REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                         SCENARIO_SAVED, SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES)
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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)

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
        self.export_button = QToolButton()
        self.export_button.setIcon(QgsApplication.getThemeIcon("/mActionSharingExport.svg"))
        self.export_button.setText(self.tr("Export DEM…"))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setToolTip(self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
        self.toolbar.addWidget(self.export_button)
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
        self.canvas_undo_keys = UndoKeys(controller.undo_stack, applies=self._sketch_tool_active, parent=self)
        iface.mapCanvas().installEventFilter(self.canvas_undo_keys)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        tool, self.draw_tool, self._brush_fid = self.draw_tool, None, None
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
        self.iface.mapCanvas().scene().removeItem(self.highlight)
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
                       self.edit_button, self.feature_view, *self.scenario_buttons):
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
        self._asked_about_unsaved = True   # the user has just answered; closing the old session must not ask again
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
        finally:
            self._asked_about_unsaved = False

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
            try:
                initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
            except QgsCsException:
                self._brush_fid = None
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
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.setText(self._drawing_hint(method))
        self.hint.show()

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
        carries on. The Properties page reloads its fields, which otherwise keep the undone values."""
        self.stop_editing()
        if self._brush_fid is not None:
            self.end_drawing()
        fid = self.feature_view.selected_id()
        if self.pages.currentIndex() == PAGE_PROPERTIES and fid is not None and self.controller.find(fid) is not None:
            self.properties.show_feature(fid)

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map."""
        if fid is None or not self.controller.has_dem or fid not in {f.id for f in self.controller.features}:
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        geometry = self._to_canvas(self.controller.feature_geometry(fid))
        self.highlight.reset(geometry.type())
        self.highlight.setToGeometry(geometry, None)

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
        try:
            differences = self.controller.scenario_differences(path)
            if differences and not self.confirm(SCENARIO_DEM_DIFFERS.format(", ".join(differences))):
                return
            self.stop_tools()
            self.controller.open_scenario(path)
        except ScenarioError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))
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
        self._show_message(Qgis.MessageLevel.Success, self.tr("Exported the modified DEM to {}").format(path))

    def _context_menu(self, position) -> None:
        menu = self.feature_menu(self.feature_view.indexAt(position))
        if menu is not None:
            menu.exec(self.feature_view.viewport().mapToGlobal(position))

    def feature_menu(self, index) -> QMenu | None:
        """The list's context menu for the row at `index` (spec §7.2), or None off the rows."""
        if not index.isValid():
            return None
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(self.tr("Rename"), lambda: self.feature_view.edit(index))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDuplicateFeature.svg"), self.tr("Duplicate"),
                       lambda: self._duplicate(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionZoomToLayer.svg"), self.tr("Zoom to feature"),
                       lambda: self._zoom_to(fid))
        menu.addSeparator()
        menu.addAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"),
                       lambda: self.controller.delete_feature(fid))
        return menu

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
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export modified DEM"), "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
            # as for scenarios: the dialog asked about replacing the name as typed, not this one
            if os.path.exists(path) and not self.confirm(EXPORT_REPLACE.format(os.path.basename(path))):
                return ""
        return path
```

Replace the whole file:

**File:** `terrain_sketch/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

import traceback

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox, QgsDoubleSpinBox
from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode, reports_storage
from . import illustrations
from .controller import LOG_TAG
from .help_texts import (AMOUNT_IS_CUSTOM, FIELD_TIPS, FLAG_TEXTS, NO_VOLUME_YET, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS,
                         SCENARIO_TOTALS, TOOL_DESCRIPTIONS, TOOL_EXAMPLES, TOOL_LABELS, TOOL_SUMMARIES,
                         VOLUME_CUT_TIP, VOLUME_FILL_TIP, VOLUME_STORAGE_NOTE, VOLUME_STORAGE_TIP, amount_label,
                         cubic_metres)

DIAGRAM = QSize(200, 96)
TOOL_PICTURE = QSize(120, 64)
PIXEL_ICON = QSize(32, 32)


def _spin(minimum: float, maximum: float, step: float, suffix: str, decimals: int) -> QgsDoubleSpinBox:
    spin = QgsDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setShowClearButton(False)
    spin.setKeyboardTracking(False)  # recompute when a value is committed, not on every keystroke
    return spin


class PropertiesPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._fid = None
        self._loading = False
        self.title = QLabel()
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.amount_label = QLabel()
        self.amount = _spin(0.0, 100.0, 0.1, " m", 2)
        # one source of truth: show_feature swaps between this and AMOUNT_IS_CUSTOM, so the
        # concrete example has to live here or it is lost the moment a feature is selected
        self._amount_tip = FIELD_TIPS["amount"]
        self.width = _spin(0.1, 500.0, 0.5, " m", 2)
        self.slope = _spin(0.0, 50.0, 0.5, "", 1)
        self.slope.setPrefix("1 : ")
        self.reach = _spin(0.0, 500.0, 1.0, " m", 1)
        self.slope_position = QComboBox()
        self.slope_position.addItem(self.tr("Outside the outline"), False)
        self.slope_position.addItem(self.tr("Inside the outline"), True)
        self.pixel_mode = QComboBox()
        for mode in PixelMode:
            self.pixel_mode.addItem(PIXEL_MODE_LABELS[mode], mode.value)
            self.pixel_mode.setItemData(self.pixel_mode.count() - 1, PIXEL_MODE_TIPS[mode], Qt.ItemDataRole.ToolTipRole)
        self.form = QFormLayout()
        self.form.addRow(self.amount_label, self.amount)
        self.form.addRow(self.tr("Width"), self.width)
        self.form.addRow(self.tr("Side slope"), self.slope)
        self.form.addRow(self.tr("Max. slope reach"), self.reach)
        self.form.addRow(self.tr("Slopes"), self.slope_position)
        self.form.addRow(self.tr("Pixels to change"), self.pixel_mode)
        self.about = QgsCollapsibleGroupBox(self.tr("About this tool"))
        self.about.setObjectName("TerrainSketchAboutTool")  # QgsCollapsibleGroupBox saves state by name
        self.about_text = QLabel()
        self.about_text.setWordWrap(True)
        self.about_picture = QLabel()
        self.about_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout = QVBoxLayout(self.about)
        about_layout.addWidget(self.about_picture)
        about_layout.addWidget(self.about_text)

        self.diagram = QLabel()
        self.diagram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diagram.setToolTip(self.tr("The part the field you are editing controls is "
                                        "highlighted."))

        self.volumes = QgsCollapsibleGroupBox(self.tr("Volumes"))
        self.volumes.setObjectName("TerrainSketchVolumes")
        self.fill_value = QLabel()
        self.fill_value.setWordWrap(True)
        self.fill_value.setToolTip(VOLUME_FILL_TIP)
        self.cut_value = QLabel()
        self.cut_value.setWordWrap(True)
        self.cut_value.setToolTip(VOLUME_CUT_TIP)
        self.storage_value = QLabel()
        self.storage_value.setWordWrap(True)
        self.storage_value.setToolTip(VOLUME_STORAGE_TIP)
        self.totals_value = QLabel()
        self.totals_value.setWordWrap(True)
        volume_form = QFormLayout(self.volumes)
        volume_form.addRow(self.tr("Fill"), self.fill_value)
        volume_form.addRow(self.tr("Cut"), self.cut_value)
        volume_form.addRow(self.tr("Storage"), self.storage_value)
        volume_form.addRow(self.tr("Whole scenario"), self.totals_value)
        self.volume_form = volume_form

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        layout.addWidget(self.about)
        layout.addWidget(self.diagram)
        layout.addLayout(self.form)
        layout.addWidget(self.volumes)
        layout.addWidget(self.problems)
        layout.addStretch(1)
        self.amount.valueChanged.connect(lambda value: self._changed("amount", value))
        self.width.valueChanged.connect(lambda value: self._changed("width", value))
        self.slope.valueChanged.connect(lambda value: self._changed("slope_n", value))
        self.reach.valueChanged.connect(lambda value: self._changed("reach", value))
        self.slope_position.currentIndexChanged.connect(
            lambda _i: self._changed("slopes_inside", bool(self.slope_position.currentData())))
        self.pixel_mode.currentIndexChanged.connect(
            lambda _i: self._changed("pixel_mode", PixelMode(self.pixel_mode.currentData())))
        for widget, key in ((self.amount, "amount"), (self.width, "width"), (self.slope, "slope_n"),
                            (self.reach, "reach"), (self.slope_position, "slopes_inside"),
                            (self.pixel_mode, "pixel_mode")):
            widget.setToolTip(FIELD_TIPS[key])
            widget.installEventFilter(self)
        self._highlight_for = {self.amount: "amount", self.width: "width", self.slope: "slope",
                               self.reach: "reach"}
        controller.featuresChanged.connect(self._refresh_problems)
        controller.featuresChanged.connect(self._refresh_volumes)

    def eventFilter(self, watched, event):  # noqa: N802 — Qt override
        """Highlight the part of the diagram that belongs to whichever field has focus."""
        if event.type() == QEvent.Type.FocusIn:
            self._draw_diagram(self._highlight_for.get(watched))
        return super().eventFilter(watched, event)

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange and self._fid is not None:
            self._draw_pictures()
        super().changeEvent(event)

    def _draw_diagram(self, highlight: str | None) -> None:
        self.diagram.setPixmap(illustrations.pixmap("parameters", DIAGRAM, self.palette(),
                                                    highlight=highlight))

    def _draw_pictures(self) -> None:
        feature = self.controller.find(self._fid) if self._fid is not None else None
        if feature is None:
            return
        self.about_picture.setPixmap(illustrations.pixmap(f"tool_{feature.tool.value}",
                                                          TOOL_PICTURE, self.palette()))
        self._draw_diagram(None)
        for index in range(self.pixel_mode.count()):
            mode = PixelMode(self.pixel_mode.itemData(index))
            self.pixel_mode.setItemIcon(index, illustrations.icon(f"pixels_{mode.value}",
                                                                  PIXEL_ICON, self.palette()))

    def show_feature(self, fid: str) -> None:
        self._fid = fid
        feature = self.controller.feature(fid)
        info = TOOL_INFO[feature.tool]
        label = amount_label(feature.tool)
        self._loading = True
        try:
            self.title.setText(_title(feature))
            self.summary.setText(TOOL_SUMMARIES[feature.tool])
            # Only a profile the engine actually uses fixes the heights: on a multi-part path it
            # is discarded, and Height/Depth is then the one control that still drives the result.
            custom = feature.long_profile is not None and supports_long_profile(feature)
            self.amount_label.setText(label or "")
            self.amount.setValue(feature.amount)
            self.amount.setEnabled(not custom)
            self.amount.setToolTip(AMOUNT_IS_CUSTOM if custom else self._amount_tip)
            self.width.setValue(feature.width)
            self.slope.setValue(feature.slope_n)
            self.reach.setValue(feature.reach)
            self.slope_position.setCurrentIndex(1 if feature.slopes_inside else 0)
            self.pixel_mode.setCurrentIndex(self.pixel_mode.findData(feature.pixel_mode.value))
            self.form.setRowVisible(self.amount, label is not None)
            self.form.setRowVisible(self.width, feature.mode is Mode.PATH)
            self.form.setRowVisible(self.slope, info.has_slopes)
            self.form.setRowVisible(self.reach, info.has_slopes)
            self.form.setRowVisible(self.slope_position, info.has_slopes and feature.mode is Mode.AREA)
            self.about_text.setText(f"{TOOL_DESCRIPTIONS[feature.tool]}\n\n"
                                    f"{TOOL_EXAMPLES[feature.tool]}")
            self._draw_pictures()
            self.diagram.setVisible(feature.mode is Mode.PATH and info.has_slopes)
        finally:
            self._loading = False
        self._refresh_problems()
        self._refresh_volumes()

    def _refresh_volumes(self) -> None:
        """Per-feature cut, fill and (for the tools that hold water) storage, plus the scenario
        totals. Storage is hidden rather than shown as zero for a tool that cannot hold water.

        Runs from `featuresChanged`, a Qt signal — an exception escaping it aborts QGIS, so any
        failure here is logged instead of raised, the same rule the controller itself follows."""
        try:
            feature = self.controller.find(self._fid) if self._fid is not None else None
            if feature is None:
                return
            stats = self.controller.stats(self._fid)
            self.fill_value.setText(cubic_metres(stats.fill))
            self.cut_value.setText(cubic_metres(stats.cut))
            shows_storage = reports_storage(feature.tool, feature.mode)
            self.volume_form.setRowVisible(self.storage_value, shows_storage)
            if shows_storage:
                self.storage_value.setText(
                    f"≈ {cubic_metres(stats.storage)} {VOLUME_STORAGE_NOTE}"
                    if stats.storage is not None else NO_VOLUME_YET)
            cut, fill = self.controller.totals()
            self.totals_value.setText(SCENARIO_TOTALS.format(fill=cubic_metres(fill), cut=cubic_metres(cut)))
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _changed(self, field: str, value) -> None:
        if self._fid is not None and not self._loading:
            self.controller.update_feature(self._fid, **{field: value})

    def _refresh_problems(self) -> None:
        if self._fid not in {f.id for f in self.controller.features}:
            self._fid = None
            return
        feature = self.controller.find(self._fid)
        self.title.setText(_title(feature))   # follows a rename in the list
        flags = self.controller.stats(self._fid).flags
        self.problems.setText("\n".join(FLAG_TEXTS[flag] for flag in flags))
        self.problems.setVisible(bool(flags))


def _title(feature) -> str:
    return f"{feature.name} · {TOOL_LABELS[feature.tool]}"
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_list_actions.py` → Expected: `7 passed`
Run: `scripts/test.sh` → Expected: `415 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/gui/properties_page.py tests/qgis/test_list_actions.py
git commit -m "feat(gui): Rename and Duplicate in the feature list"
```

---

### Task 5: The 3D view

**Files:**
- Modify: `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`
- Test: `tests/qgis/test_view_3d.py`

**Interfaces:**
- Consumes: `SketchLayers.working_id`; `QgsProject.elevationProperties()`; `iface.createNewMapCanvas3D`; Task 3's `toolbar` and `_file_button`.
- Produces: `SketchController.show_in_3d() -> bool` and `_restore_terrain()` (called first in `close()`); `MainDock.view_3d_button` (enabled with a session), `_open_3d_view`; `help_texts.VIEW_3D_TIP`, `VIEW_3D_NOT_OPENED`, `VIEW_3D_NO_LAYER`.

- [ ] **Step 1: Write the failing test**

**File:** `tests/qgis/test_view_3d.py`
```python
"""The 3D view (spec §8.5): the modified DEM as the project's terrain, a new 3D view, and the
terrain the user had put back afterwards."""
from qgis.core import QgsFlatTerrainProvider, QgsProject, QgsRasterDemTerrainProvider
from qgis.PyQt.QtGui import QAction

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import VIEW_3D_NO_LAYER, VIEW_3D_NOT_OPENED
from terrain_sketch.gui.main_dock import MainDock


def terrain():
    return QgsProject.instance().elevationProperties().terrainProvider()


def a_flat_terrain_at(offset: float) -> None:
    flat = QgsFlatTerrainProvider()
    flat.setOffset(offset)
    QgsProject.instance().elevationProperties().setTerrainProvider(flat)


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def messages(iface) -> list[str]:
    return [call[0][1] for call in iface.messageBar().pushMessage.call_args_list]


def test_the_modified_dem_becomes_the_terrain_at_true_scale(tmp_path):
    c = start_session(tmp_path)
    assert c.show_in_3d()
    provider = terrain()
    assert isinstance(provider, QgsRasterDemTerrainProvider)
    assert provider.layer().id() == c.layers.working_id and provider.scale() == 1.0


def test_ending_the_session_puts_the_previous_terrain_back(tmp_path):
    a_flat_terrain_at(5.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    c.show_in_3d()                                 # twice: still the user's terrain that comes back
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 5.0


def test_removing_the_dem_puts_the_previous_terrain_back(tmp_path):
    a_flat_terrain_at(7.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    QgsProject.instance().removeMapLayer(c.dem_layer_id)
    assert not c.has_dem
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 7.0


def test_a_terrain_the_user_chose_afterwards_is_left_alone(tmp_path):
    c = start_session(tmp_path)
    c.show_in_3d()
    a_flat_terrain_at(9.0)                         # the user picked their own terrain meanwhile
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 9.0


def test_without_the_modified_dem_layer_there_is_nothing_to_show(tmp_path):
    a_flat_terrain_at(3.0)
    c = start_session(tmp_path)
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    QgsProject.instance().removeMapLayer(c.layers.working_id)
    assert c.has_dem                               # removing a result layer keeps the session
    assert not c.show_in_3d()
    assert heard[-1] == VIEW_3D_NO_LAYER
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 3.0


def test_the_button_opens_a_3d_view_through_the_interface(tmp_path):
    iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.view_3d_button.click()
    iface.createNewMapCanvas3D.assert_called_once()
    assert isinstance(terrain(), QgsRasterDemTerrainProvider)
    assert VIEW_3D_NOT_OPENED not in messages(iface)


def test_without_the_interface_call_qgis_own_menu_action_is_used(tmp_path):
    iface, _c, dock = panel(tmp_path)
    iface.createNewMapCanvas3D.return_value = None
    triggered = []
    action = QAction("New 3D Map View", iface.mainWindow())
    action.setObjectName("mActionNew3DMapCanvas")
    action.triggered.connect(lambda: triggered.append(True))
    dock.view_3d_button.click()
    assert triggered == [True] and VIEW_3D_NOT_OPENED not in messages(iface)


def test_when_no_3d_view_can_be_opened_the_user_is_told_how(tmp_path):
    iface, _c, dock = panel(tmp_path)
    iface.createNewMapCanvas3D.side_effect = RuntimeError("QGIS built without 3D")
    dock.view_3d_button.click()                    # a slot: the error must not escape
    assert VIEW_3D_NOT_OPENED in messages(iface)
    assert isinstance(terrain(), QgsRasterDemTerrainProvider)   # the terrain is still set for later


def test_the_3d_button_waits_for_a_session():
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    assert not dock.view_3d_button.isEnabled()
    assert not dock.view_3d_button.icon().isNull()     # getThemeIcon gives a blank for an unknown name


def test_a_closed_project_does_not_hand_its_terrain_to_the_next_one(tmp_path):
    """Clearing the project drops the session without close(); the terrain remembered from that
    project must go with it, or the next session would put it into a different project."""
    a_flat_terrain_at(2.0)
    c = SketchController(QgsProject.instance())
    c.set_dem(dem_layer(tmp_path))
    c.show_in_3d()
    QgsProject.instance().clear()                  # a new, empty project
    a_flat_terrain_at(4.0)                         # the terrain of the new project
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    c.show_in_3d()
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 4.0
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_view_3d.py`
Expected: collection error `ImportError: cannot import name 'VIEW_3D_NO_LAYER' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/gui/controller.py`
```python
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
from ..core.sections import long_section, rescale_long_profile
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
        except (OSError, RuntimeError, MemoryError) as error:
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
        """Close the session and stop listening to the project (plugin unload)."""
        self.close()
        self.project.layersRemoved.disconnect(self._on_layers_removed)
        self.project.cleared.disconnect(self._drop_session)
        self.project.aboutToBeCleared.disconnect(self._drop_session)

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
        self.cancel_preview()  # the committed result replaces whatever the overlay was showing
        feature = self.find(fid)
        if feature is None:
            return
        text, key = _describe(feature, changes)
        self._commit([replace(f, **changes) if f.id == fid else f for f in self._features], text, key)

    def set_enabled(self, fid: str, enabled: bool) -> None:
        self.update_feature(fid, enabled=bool(enabled))

    def delete_feature(self, fid: str) -> None:
        feature = self.find(fid)
        if feature is not None:
            self._commit([f for f in self._features if f.id != fid], UNDO_DELETE.format(feature.name))

    def duplicate_feature(self, fid: str) -> TerrainFeature | None:
        """A copy of the feature, with every setting and profile, placed right after it in the list.
        It starts turned off: most tools measure from the terrain beneath them, so an identical copy
        on top would not be a copy at all — a raised path would come out twice as high. The user
        moves or reshapes it, then ticks it on. None when the feature no longer exists."""
        feature = self.find(fid)
        if feature is None:
            return None
        copy = replace(feature, id=uuid.uuid4().hex, name=self._unique(COPY_NAME.format(feature.name)),
                       enabled=False)
        index = self._features.index(feature)
        features = [*self._features[:index + 1], copy, *self._features[index + 1:]]
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
        """Whether the features differ from the last save or load of a scenario. Follows undo:
        undoing back to the saved state makes the scenario clean again."""
        return not self.undo_stack.isClean()

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
        created = self._created if path == self._scenario_path else ""
        meta = scenario.dem_meta(self.info, self.stack.original, version=plugin_version(), created=created)
        written = scenario.save(path, self._features, meta, crs_wkt=getattr(self.info, "crs_wkt", ""))
        self._scenario_path = path
        self._created = written.created
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
        self._scenario_path = path
        self._created = meta.created
        self.undo_stack.clear()   # the history belonged to the features that were just replaced
        self.sessionChanged.emit()

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
        if self._terrain_before is None:
            self._terrain_before = properties.terrainProvider().clone()
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
        current = properties.terrainProvider()
        ours = self.layers.working_id if self.layers is not None else None
        if isinstance(current, QgsRasterDemTerrainProvider) and current.layer() is not None \
                and current.layer().id() == ours:
            properties.setTerrainProvider(before)

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
            return True
        if not self._set(after):
            return False
        self.undo_stack.push(FeatureListChange(self._restore, before, after, text, key))
        return True

    def _restore(self, features) -> None:
        """Undo or redo. Runs inside QUndoStack from a button or a key, so it never raises: `_set`
        already turns an engine failure into a message."""
        self.cancel_preview()
        if self.stack is not None:
            self._set(features)
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
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)


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
```

Replace the whole file:

**File:** `terrain_sketch/gui/help_texts.py`
```python
"""Every description, example, tooltip and message the user reads, in one place.

Translation, and a deliberate deviation from the spec. Spec §2 ("In scope (v1)") asks for every
string to be wrapped in `tr()` so it can be translated later. That does not work for strings held
in a module like this one: `tr()` extracts only string *literals*, so `self.tr(SOME_CONSTANT)` at
the point of use produces nothing for a translator while looking like it does. These are therefore
plain strings, and the call sites pass them straight through.

The spec's intent still holds — the strings stay in one place, which is what makes translating
them later a contained job. When that happens, mark them here (with `QT_TRANSLATE_NOOP` or by
moving them into the classes that show them); widget captions already call `self.tr("literal")`
and keep working unchanged.
"""
from __future__ import annotations

from ..core.operations import FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS, FLAG_NODATA_REFERENCE, FLAG_OUTSIDE
from ..core.tools import PixelMode, Tool

TOOL_LABELS = {
    Tool.INTERPOLATE: "Interpolate",
    Tool.RAISE_PATH: "Raise path",
    Tool.LOWER_PATH: "Lower path",
    Tool.RAISE_FLAT: "Raise flat",
    Tool.LOWER_FLAT: "Lower flat",
    Tool.ADD: "Add to terrain",
    Tool.SUBTRACT: "Subtract from terrain",
}

TOOL_SUMMARIES = {
    Tool.INTERPOLATE: "A straight grade between the terrain at the start and end of the path, or a smooth "
                      "surface between the corners of an area. Example: cut through an embankment that "
                      "blocks a flow path, or fill an old ditch.",
    Tool.RAISE_PATH: "Adds material along the path, following the terrain uphill or downhill; it never "
                     "removes material. Example: a wall or emergency dike along a river bank.",
    Tool.LOWER_PATH: "Removes material along the path, following the terrain; it never adds material. "
                     "Example: a ditch or swale that drains a road towards a pond.",
    Tool.RAISE_FLAT: "A level top at the highest point of the path or outline plus the height. "
                     "Example: a flat dam, or building footprints.",
    Tool.LOWER_FLAT: "A level bottom at the lowest point of the path or outline minus the depth. "
                     "Example: a flat culvert, or a retention basin.",
    Tool.ADD: "Raises every selected cell by the height, keeping the relief. "
              "Example: an inflatable flood barrier on a street.",
    Tool.SUBTRACT: "Lowers every selected cell by the depth, keeping the slope changes. "
                   "Example: a pipe trench in a road, or deepening a canal to its bed.",
}

PIXEL_MODE_LABELS = {
    PixelMode.ALL_TOUCHED: "All touched",
    PixelMode.CENTRE: "Centre inside",
    PixelMode.FULLY_INSIDE: "Fully inside",
}

PIXEL_MODE_TIPS = {
    PixelMode.ALL_TOUCHED: "Every pixel the shape touches (generous).",
    PixelMode.CENTRE: "Pixels whose centre lies inside the shape (closest to the true area).",
    PixelMode.FULLY_INSIDE: "Only pixels completely inside the shape (strict).",
}

FLAG_TEXTS = {
    FLAG_OUTSIDE: "This feature lies outside the DEM.",
    FLAG_NO_PIXELS: "No pixels are selected — try 'All touched' or a larger width.",
    FLAG_NODATA_REFERENCE: "The start, end or edge of this feature lies outside the DEM or on nodata.",
    FLAG_BAD_GEOMETRY: "The shape of this feature cannot be used.",
}

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Sketch never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Sketch session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Sketch layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."
SHAPE_NOT_TRANSFORMED = ("This feature's shape cannot be shown in the map's coordinate system, so it cannot "
                         "be zoomed to or edited here. Set the project to the DEM's coordinate system and "
                         "try again.")
EXPORT_REPLACE = "{} already exists. Replace it?"

# What Undo and Redo will do, shown as "Undo Add Dike 1" in their buttons' tooltips.
UNDO_ADD = "Add {}"
UNDO_DELETE = "Delete {}"
UNDO_RENAME = "Rename {}"
UNDO_TURN_ON = "Turn on {}"
UNDO_TURN_OFF = "Turn off {}"
UNDO_REORDER = "Reorder features"
UNDO_SHAPE = "Edit the shape of {}"
UNDO_PROFILE = "Change the profile of {}"
UNDO_SETTINGS = "Change the settings of {}"
UNDO_DUPLICATE = "Duplicate {}"
COPY_NAME = "{} (copy)"

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It becomes the project's terrain until this "
               "session ends; the terrain you had before is put back then.")
VIEW_3D_NOT_OPENED = ("The modified DEM is now the project's terrain, but Terrain Sketch could not open a "
                      "3D view. Open one with View ▸ 3D Map Views ▸ New 3D Map View.")
VIEW_3D_NO_LAYER = ("The Modified DEM layer is no longer in the project, so there is nothing to show in 3D. "
                    "Press Start to create it again.")


def amount_label(tool: Tool) -> str | None:
    """Label of the amount field, or None when the tool has no amount."""
    if tool is Tool.INTERPOLATE:
        return None
    if tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT):
        return "Depth"
    return "Height"

PROFILE_EMPTY_HINT = "Select or draw a feature to edit its shape here."
CUSTOM_PROFILE_NOTE = ("Custom long profile: the heights are fixed and no longer follow the "
                       "terrain underneath. Use Reset to rule to go back.")
AREA_LONG_SECTION_HINT = "A section through an area arrives in a later version."
AREA_LONG_SECTION_NOTE = ("An area has no long profile to edit. A section through the feature "
                          "arrives in a later version; until then, use the cross profile on the "
                          "left to shape its sides.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
SYMMETRIC_TIP = ("While this is ticked, break points are mirrored to the other side of the path. "
                 "Width and side slope are single values that always apply to both sides.")
AMOUNT_IS_CUSTOM = ("The long profile was edited by hand, so its heights are fixed. Use "
                    "Reset to rule in the profile panel to drive the shape from this value again.")


TOOL_EXAMPLES = {
    Tool.INTERPOLATE: ("A bridge or culvert was captured as a solid bank across a channel, so "
                       "water cannot pass. Draw a line along the channel through it and Terrain "
                       "Sketch runs a smooth grade between the two ends."),
    Tool.RAISE_PATH: ("A 1.5 m flood embankment along a river. Draw the line the crest follows, "
                      "set Height 1.5 m, Width 3 m and a 1:3 side slope."),
    Tool.LOWER_PATH: ("A swale carrying runoff to a pond. Draw its route, set Depth 0.6 m and "
                      "Width 2 m; the slopes tie it back into the ground."),
    Tool.RAISE_FLAT: ("A building pad above the flood level. Draw the outline and set the height "
                      "above the highest point on the outline you draw, so the whole pad sits "
                      "level."),
    Tool.LOWER_FLAT: ("A detention basin. Draw the outline, set Depth 1.2 m, and set Slopes to "
                      "Inside the outline so the sides slope down within it instead of the basin "
                      "growing outwards; the bottom comes out flat."),
    Tool.ADD: ("A 0.3 m layer of fill over a field. Draw the outline; the ground keeps its shape "
               "and every cell rises by the same amount."),
    Tool.SUBTRACT: ("Stripping 0.2 m of topsoil. Draw the outline; the ground keeps its shape and "
                    "every cell drops by the same amount."),
}

TOOL_DESCRIPTIONS = {
    Tool.INTERPOLATE: ("Replaces the terrain under the shape with a smooth grade between its "
                       "edges, so a missing or wrong patch is bridged rather than raised or cut."),
    Tool.RAISE_PATH: ("Builds a raised corridor along a line: a flat crest of the width you set, "
                      "with side slopes running down to meet the ground."),
    Tool.LOWER_PATH: ("Cuts a channel along a line: a flat bottom of the width you set, with "
                      "sides sloping up to meet the ground."),
    Tool.RAISE_FLAT: ("Lifts everything inside the shape to one level, measured from the highest "
                      "point on the line or outline you draw, with slopes tying the edge back "
                      "into the ground."),
    Tool.LOWER_FLAT: ("Cuts everything inside the shape down to one level, measured from the "
                      "lowest point on the line or outline you draw, with slopes tying the edge "
                      "back in."),
    Tool.ADD: "Adds the same height to every cell inside the shape; the terrain keeps its shape.",
    Tool.SUBTRACT: ("Takes the same height off every cell inside the shape; the terrain keeps "
                    "its shape."),
}

FIELD_TIPS = {
    "amount": ("How far the feature rises (height) or cuts (depth): above or below the straight "
               "grade between the path's ends, the highest or lowest point of the path or "
               "outline, or the terrain itself for Add and Subtract. For a 1.5 m embankment, "
               "set 1.5."),
    "width": ("How wide the flat part is — the crest of a dike, or the bottom of a ditch. A farm "
              "track is about 3 m; a footpath about 1.5 m."),
    "slope_n": ("How far the side slope runs out for every metre of height. 1:3 means 3 m "
                "outwards per 1 m up, about the steepest a mown grass embankment usually gets. "
                "0 means no side slopes at all."),
    "reach": ("The side slopes stop this far from the edge even if they have not met the ground. "
              "Set 5 m to keep a 1.5 m embankment out of a neighbouring plot that starts 5 m "
              "from the crest."),
    "slopes_inside": ("Inside: the outline is the top edge and the slopes run down within it — a "
                      "pond. Outside: the outline is the flat part and the slopes run out beyond "
                      "it — a raised pad."),
    "pixel_mode": ("Which cells count as covered by your shape. Narrow features can miss every "
                   "cell centre, which is when All touched helps."),
}

NO_FEATURES_SELECTED = ("Nothing is selected in that layer. Untick \'Selected features only\', or "
                        "select the features you want on the map first.")
EMPTY_LAYER = "That layer has no features to use."
PICK_A_LAYER = "Pick a layer above first."


def tool_tooltip(tool: Tool) -> str:
    """What a gallery item shows on hover: what the tool does, then a worked example."""
    return f"{TOOL_DESCRIPTIONS[tool]}\n\n{TOOL_EXAMPLES[tool]}"

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Sketch cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float | None) -> str:
    """A volume a user can read at a glance: no decimals once it is past a hundred.

    Cut and fill are magnitudes, so a minus sign here can only be floating-point residue —
    a negative zero out of a subtraction, or a few millilitres left over a million cells.
    Either would reach the user as "-0.00 m³", which reads as a bug, so the sign is dropped
    from anything that rounds to zero."""
    if value is None:
        return NO_VOLUME_YET
    size = abs(value)
    text = f"{value:,.0f}" if size >= 100.0 else f"{value:,.1f}" if size >= 1.0 else f"{value:.2f}"
    if text.startswith("-") and not any(digit in "123456789" for digit in text):
        text = text[1:]
    return f"{text} m³"


UNSAVED_CHANGES = ("This scenario has changes that are not saved. Save them before continuing?")
SCENARIO_SAVED = "Scenario saved to {}"
SCENARIO_REPLACE = "{} already exists. Replace it?"
SCENARIO_OPENED = "Scenario opened from {}"
SCENARIO_DEM_DIFFERS = ("This scenario was made on a DEM with a different {}.\n\n"
                        "Open it on this DEM anyway? The features keep their map position, so check "
                        "the result before using it.\n\n"
                        "Choose No to keep your current work, then pick the DEM the scenario was made "
                        "for and press Start before opening it.")
SCENARIO_NOT_APPLIED = ("The scenario could not be applied to this DEM, so it was not opened. "
                        "Your current features are unchanged.")
UNSAVED_BEFORE_CLOSING = ("Terrain Sketch is closing this scenario, and it has changes that are not "
                          "saved. Save them now?")
```

Replace the whole file:

**File:** `terrain_sketch/gui/main_dock.py`
```python
"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

import os
import traceback

from qgis.core import (Qgis, QgsApplication, QgsCoordinateTransform, QgsCsException, QgsGeometry, QgsMessageLog,
                       QgsProject)
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .controller import LOG_TAG
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (EXPORT_REPLACE, REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                         SCENARIO_SAVED, SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES,
                         VIEW_3D_NOT_OPENED, VIEW_3D_TIP)
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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)

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
        self.export_button = QToolButton()
        self.export_button.setIcon(QgsApplication.getThemeIcon("/mActionSharingExport.svg"))
        self.export_button.setText(self.tr("Export DEM…"))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setToolTip(self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
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
        self.canvas_undo_keys = UndoKeys(controller.undo_stack, applies=self._sketch_tool_active, parent=self)
        iface.mapCanvas().installEventFilter(self.canvas_undo_keys)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        tool, self.draw_tool, self._brush_fid = self.draw_tool, None, None
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
        self.iface.mapCanvas().scene().removeItem(self.highlight)
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
        self._asked_about_unsaved = True   # the user has just answered; closing the old session must not ask again
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
        finally:
            self._asked_about_unsaved = False

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
            try:
                initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
            except QgsCsException:
                self._brush_fid = None
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
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.setText(self._drawing_hint(method))
        self.hint.show()

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
        carries on. The Properties page reloads its fields, which otherwise keep the undone values."""
        self.stop_editing()
        if self._brush_fid is not None:
            self.end_drawing()
        fid = self.feature_view.selected_id()
        if self.pages.currentIndex() == PAGE_PROPERTIES and fid is not None and self.controller.find(fid) is not None:
            self.properties.show_feature(fid)

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map."""
        if fid is None or not self.controller.has_dem or fid not in {f.id for f in self.controller.features}:
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        geometry = self._to_canvas(self.controller.feature_geometry(fid))
        self.highlight.reset(geometry.type())
        self.highlight.setToGeometry(geometry, None)

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
        try:
            differences = self.controller.scenario_differences(path)
            if differences and not self.confirm(SCENARIO_DEM_DIFFERS.format(", ".join(differences))):
                return
            self.stop_tools()
            self.controller.open_scenario(path)
        except ScenarioError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))
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
        self._show_message(Qgis.MessageLevel.Success, self.tr("Exported the modified DEM to {}").format(path))

    def _open_3d_view(self) -> None:
        """The modified DEM as the project's terrain, then a new 3D view (spec §8.5): through the
        interface when this QGIS offers it, otherwise through QGIS's own New 3D Map View action,
        otherwise a message saying how to open one by hand."""
        if not self.controller.show_in_3d():
            return
        try:
            if self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
                return
        except Exception:  # noqa: BLE001 — a QGIS built without 3D; this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
        action = self.iface.mainWindow().findChild(QAction, "mActionNew3DMapCanvas")
        if action is not None and action.isEnabled():
            action.trigger()
            return
        self._show_message(Qgis.MessageLevel.Warning, VIEW_3D_NOT_OPENED)

    def _context_menu(self, position) -> None:
        menu = self.feature_menu(self.feature_view.indexAt(position))
        if menu is not None:
            menu.exec(self.feature_view.viewport().mapToGlobal(position))

    def feature_menu(self, index) -> QMenu | None:
        """The list's context menu for the row at `index` (spec §7.2), or None off the rows."""
        if not index.isValid():
            return None
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(self.tr("Rename"), lambda: self.feature_view.edit(index))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDuplicateFeature.svg"), self.tr("Duplicate"),
                       lambda: self._duplicate(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionZoomToLayer.svg"), self.tr("Zoom to feature"),
                       lambda: self._zoom_to(fid))
        menu.addSeparator()
        menu.addAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"),
                       lambda: self.controller.delete_feature(fid))
        return menu

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
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export modified DEM"), "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
            # as for scenarios: the dialog asked about replacing the name as typed, not this one
            if os.path.exists(path) and not self.confirm(EXPORT_REPLACE.format(os.path.basename(path))):
                return ""
        return path
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_view_3d.py` → Expected: `10 passed`
Run: `scripts/test.sh` → Expected: `425 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py tests/qgis/test_view_3d.py
git commit -m "feat(gui): show the modified DEM in a 3D view, and put the project's terrain back afterwards"
```

---

### Task 6: Export options

**Files:**
- Modify: `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/qgis_io/raster_io.py`
- Test: `tests/qgis/test_export_options.py`

**Interfaces:**
- Consumes: `read_dem`'s band array; `SketchController.export_dem`; `iface.messageBar().createMessage`/`pushWidget` (the pattern `_offer_reproject` uses).
- Produces: `DemInfo.integer`; `SketchController.dem_is_integer`; `MainDock._offer_to_add_export(path, text)`, `_add_export(path, button=None)`; the export dialog's title notes float32 for an integer DEM; `help_texts.EXPORT_DONE`, `EXPORT_INTEGER_NOTE`, `EXPORT_NOT_ADDED`.

- [ ] **Step 1: Write the failing test**

**File:** `tests/qgis/test_export_options.py`
```python
"""Export DEM's options (spec §8.5): add the result to the project, and say when an integer DEM is
exported with decimals."""
import numpy as np
from osgeo import gdal
from qgis.core import QgsProject, QgsRasterLayer

from qgis_helpers import CELL, UTM, X0, Y0, fake_iface, line_through
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED
from terrain_sketch.gui.main_dock import MainDock


def integer_dem(tmp_path) -> QgsRasterLayer:
    path = str(tmp_path / "whole_metres.tif")
    ds = gdal.GetDriverByName("GTiff").Create(path, 40, 40, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((X0, CELL, 0.0, Y0, 0.0, -CELL))
    ds.SetProjection(UTM.toWkt())
    ds.GetRasterBand(1).WriteArray(np.full((40, 40), 10, np.int16))
    ds = None
    layer = QgsRasterLayer(path, "whole metres")
    QgsProject.instance().addMapLayer(layer)
    return layer


def panel(tmp_path, dem=None):
    from qgis_helpers import dem_layer
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem or dem_layer(tmp_path))
    dock.start_button.click()
    assert controller.has_dem
    return iface, controller, dock


def pushed(iface):
    """(text, widget) of the last message pushed as a widget."""
    widget = iface.messageBar().pushWidget.call_args[0][0]
    return widget.text(), widget


def export(dock, tmp_path, name="exported.tif"):
    path = str(tmp_path / name)
    dock.ask_export_path = lambda: path
    dock.export_button.click()
    return path


def test_the_export_message_offers_to_add_the_result_to_the_project(tmp_path):
    from qgis.PyQt.QtWidgets import QPushButton
    iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = export(dock, tmp_path)
    text, widget = pushed(iface)
    assert text == EXPORT_DONE.format(path)
    button = next(b for b in widget.findChildren(QPushButton) if b.text() == "Add to project")
    assert widget.layout().indexOf(button) >= 0   # laid out in the message, not floating at its corner
    button.click()
    added = [layer for layer in QgsProject.instance().mapLayers().values() if layer.source() == path]
    assert len(added) == 1 and added[0].isValid()
    assert not button.isEnabled()                 # a second click would add a duplicate
    button.click()
    assert len([l for l in QgsProject.instance().mapLayers().values() if l.source() == path]) == 1


def test_an_export_that_has_gone_is_reported_instead_of_added(tmp_path):
    import os
    iface, _c, dock = panel(tmp_path)
    path = export(dock, tmp_path)
    os.remove(path)
    heard = []
    dock._show_message = lambda level, text: heard.append(text)
    dock._add_export(path)
    assert heard == [EXPORT_NOT_ADDED.format(path)]
    assert not [l for l in QgsProject.instance().mapLayers().values() if l.source() == path]


def test_an_integer_dem_is_exported_with_decimals_and_the_user_is_told(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    iface, c, dock = panel(tmp_path, integer_dem(tmp_path))
    assert c.dem_is_integer
    titles = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda _parent, title, *a, **k: titles.append(title) or ("", "")))
    dock._export_dialog()
    assert "32-bit float" in titles[0]

    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = export(dock, tmp_path)
    text, _widget = pushed(iface)
    assert text == f"{EXPORT_DONE.format(path)}. {EXPORT_INTEGER_NOTE}"
    assert gdal.Open(path).GetRasterBand(1).DataType == gdal.GDT_Float32


def test_a_float_dem_gets_no_integer_note(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    iface, c, dock = panel(tmp_path)
    assert not c.dem_is_integer
    titles = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda _parent, title, *a, **k: titles.append(title) or ("", "")))
    dock._export_dialog()
    assert "32-bit" not in titles[0]
    path = export(dock, tmp_path)
    text, _widget = pushed(iface)
    assert EXPORT_INTEGER_NOTE not in text
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_export_options.py`
Expected: collection error `ImportError: cannot import name 'EXPORT_DONE' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/gui/controller.py`
```python
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
from ..core.sections import long_section, rescale_long_profile
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
        except (OSError, RuntimeError, MemoryError) as error:
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
        """Close the session and stop listening to the project (plugin unload)."""
        self.close()
        self.project.layersRemoved.disconnect(self._on_layers_removed)
        self.project.cleared.disconnect(self._drop_session)
        self.project.aboutToBeCleared.disconnect(self._drop_session)

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
        self.cancel_preview()  # the committed result replaces whatever the overlay was showing
        feature = self.find(fid)
        if feature is None:
            return
        text, key = _describe(feature, changes)
        self._commit([replace(f, **changes) if f.id == fid else f for f in self._features], text, key)

    def set_enabled(self, fid: str, enabled: bool) -> None:
        self.update_feature(fid, enabled=bool(enabled))

    def delete_feature(self, fid: str) -> None:
        feature = self.find(fid)
        if feature is not None:
            self._commit([f for f in self._features if f.id != fid], UNDO_DELETE.format(feature.name))

    def duplicate_feature(self, fid: str) -> TerrainFeature | None:
        """A copy of the feature, with every setting and profile, placed right after it in the list.
        It starts turned off: most tools measure from the terrain beneath them, so an identical copy
        on top would not be a copy at all — a raised path would come out twice as high. The user
        moves or reshapes it, then ticks it on. None when the feature no longer exists."""
        feature = self.find(fid)
        if feature is None:
            return None
        copy = replace(feature, id=uuid.uuid4().hex, name=self._unique(COPY_NAME.format(feature.name)),
                       enabled=False)
        index = self._features.index(feature)
        features = [*self._features[:index + 1], copy, *self._features[index + 1:]]
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
        """Whether the features differ from the last save or load of a scenario. Follows undo:
        undoing back to the saved state makes the scenario clean again."""
        return not self.undo_stack.isClean()

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
        created = self._created if path == self._scenario_path else ""
        meta = scenario.dem_meta(self.info, self.stack.original, version=plugin_version(), created=created)
        written = scenario.save(path, self._features, meta, crs_wkt=getattr(self.info, "crs_wkt", ""))
        self._scenario_path = path
        self._created = written.created
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
        self._scenario_path = path
        self._created = meta.created
        self.undo_stack.clear()   # the history belonged to the features that were just replaced
        self.sessionChanged.emit()

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
        if self._terrain_before is None:
            self._terrain_before = properties.terrainProvider().clone()
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
        current = properties.terrainProvider()
        ours = self.layers.working_id if self.layers is not None else None
        if isinstance(current, QgsRasterDemTerrainProvider) and current.layer() is not None \
                and current.layer().id() == ours:
            properties.setTerrainProvider(before)

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
            return True
        if not self._set(after):
            return False
        self.undo_stack.push(FeatureListChange(self._restore, before, after, text, key))
        return True

    def _restore(self, features) -> None:
        """Undo or redo. Runs inside QUndoStack from a button or a key, so it never raises: `_set`
        already turns an engine failure into a message."""
        self.cancel_preview()
        if self.stack is not None:
            self._set(features)
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
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)


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
```

Replace the whole file:

**File:** `terrain_sketch/gui/help_texts.py`
```python
"""Every description, example, tooltip and message the user reads, in one place.

Translation, and a deliberate deviation from the spec. Spec §2 ("In scope (v1)") asks for every
string to be wrapped in `tr()` so it can be translated later. That does not work for strings held
in a module like this one: `tr()` extracts only string *literals*, so `self.tr(SOME_CONSTANT)` at
the point of use produces nothing for a translator while looking like it does. These are therefore
plain strings, and the call sites pass them straight through.

The spec's intent still holds — the strings stay in one place, which is what makes translating
them later a contained job. When that happens, mark them here (with `QT_TRANSLATE_NOOP` or by
moving them into the classes that show them); widget captions already call `self.tr("literal")`
and keep working unchanged.
"""
from __future__ import annotations

from ..core.operations import FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS, FLAG_NODATA_REFERENCE, FLAG_OUTSIDE
from ..core.tools import PixelMode, Tool

TOOL_LABELS = {
    Tool.INTERPOLATE: "Interpolate",
    Tool.RAISE_PATH: "Raise path",
    Tool.LOWER_PATH: "Lower path",
    Tool.RAISE_FLAT: "Raise flat",
    Tool.LOWER_FLAT: "Lower flat",
    Tool.ADD: "Add to terrain",
    Tool.SUBTRACT: "Subtract from terrain",
}

TOOL_SUMMARIES = {
    Tool.INTERPOLATE: "A straight grade between the terrain at the start and end of the path, or a smooth "
                      "surface between the corners of an area. Example: cut through an embankment that "
                      "blocks a flow path, or fill an old ditch.",
    Tool.RAISE_PATH: "Adds material along the path, following the terrain uphill or downhill; it never "
                     "removes material. Example: a wall or emergency dike along a river bank.",
    Tool.LOWER_PATH: "Removes material along the path, following the terrain; it never adds material. "
                     "Example: a ditch or swale that drains a road towards a pond.",
    Tool.RAISE_FLAT: "A level top at the highest point of the path or outline plus the height. "
                     "Example: a flat dam, or building footprints.",
    Tool.LOWER_FLAT: "A level bottom at the lowest point of the path or outline minus the depth. "
                     "Example: a flat culvert, or a retention basin.",
    Tool.ADD: "Raises every selected cell by the height, keeping the relief. "
              "Example: an inflatable flood barrier on a street.",
    Tool.SUBTRACT: "Lowers every selected cell by the depth, keeping the slope changes. "
                   "Example: a pipe trench in a road, or deepening a canal to its bed.",
}

PIXEL_MODE_LABELS = {
    PixelMode.ALL_TOUCHED: "All touched",
    PixelMode.CENTRE: "Centre inside",
    PixelMode.FULLY_INSIDE: "Fully inside",
}

PIXEL_MODE_TIPS = {
    PixelMode.ALL_TOUCHED: "Every pixel the shape touches (generous).",
    PixelMode.CENTRE: "Pixels whose centre lies inside the shape (closest to the true area).",
    PixelMode.FULLY_INSIDE: "Only pixels completely inside the shape (strict).",
}

FLAG_TEXTS = {
    FLAG_OUTSIDE: "This feature lies outside the DEM.",
    FLAG_NO_PIXELS: "No pixels are selected — try 'All touched' or a larger width.",
    FLAG_NODATA_REFERENCE: "The start, end or edge of this feature lies outside the DEM or on nodata.",
    FLAG_BAD_GEOMETRY: "The shape of this feature cannot be used.",
}

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Sketch never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Sketch session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Sketch layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."
SHAPE_NOT_TRANSFORMED = ("This feature's shape cannot be shown in the map's coordinate system, so it cannot "
                         "be zoomed to or edited here. Set the project to the DEM's coordinate system and "
                         "try again.")
EXPORT_REPLACE = "{} already exists. Replace it?"
EXPORT_DONE = "Exported the modified DEM to {}"
EXPORT_INTEGER_NOTE = ("Your DEM stores whole numbers; the export keeps decimals (32-bit float), so changes "
                       "smaller than a metre are not rounded away.")
EXPORT_NOT_ADDED = "The exported DEM could not be added to the project: {} cannot be read as a raster."

# What Undo and Redo will do, shown as "Undo Add Dike 1" in their buttons' tooltips.
UNDO_ADD = "Add {}"
UNDO_DELETE = "Delete {}"
UNDO_RENAME = "Rename {}"
UNDO_TURN_ON = "Turn on {}"
UNDO_TURN_OFF = "Turn off {}"
UNDO_REORDER = "Reorder features"
UNDO_SHAPE = "Edit the shape of {}"
UNDO_PROFILE = "Change the profile of {}"
UNDO_SETTINGS = "Change the settings of {}"
UNDO_DUPLICATE = "Duplicate {}"
COPY_NAME = "{} (copy)"

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It becomes the project's terrain until this "
               "session ends; the terrain you had before is put back then.")
VIEW_3D_NOT_OPENED = ("The modified DEM is now the project's terrain, but Terrain Sketch could not open a "
                      "3D view. Open one with View ▸ 3D Map Views ▸ New 3D Map View.")
VIEW_3D_NO_LAYER = ("The Modified DEM layer is no longer in the project, so there is nothing to show in 3D. "
                    "Press Start to create it again.")


def amount_label(tool: Tool) -> str | None:
    """Label of the amount field, or None when the tool has no amount."""
    if tool is Tool.INTERPOLATE:
        return None
    if tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT):
        return "Depth"
    return "Height"

PROFILE_EMPTY_HINT = "Select or draw a feature to edit its shape here."
CUSTOM_PROFILE_NOTE = ("Custom long profile: the heights are fixed and no longer follow the "
                       "terrain underneath. Use Reset to rule to go back.")
AREA_LONG_SECTION_HINT = "A section through an area arrives in a later version."
AREA_LONG_SECTION_NOTE = ("An area has no long profile to edit. A section through the feature "
                          "arrives in a later version; until then, use the cross profile on the "
                          "left to shape its sides.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
SYMMETRIC_TIP = ("While this is ticked, break points are mirrored to the other side of the path. "
                 "Width and side slope are single values that always apply to both sides.")
AMOUNT_IS_CUSTOM = ("The long profile was edited by hand, so its heights are fixed. Use "
                    "Reset to rule in the profile panel to drive the shape from this value again.")


TOOL_EXAMPLES = {
    Tool.INTERPOLATE: ("A bridge or culvert was captured as a solid bank across a channel, so "
                       "water cannot pass. Draw a line along the channel through it and Terrain "
                       "Sketch runs a smooth grade between the two ends."),
    Tool.RAISE_PATH: ("A 1.5 m flood embankment along a river. Draw the line the crest follows, "
                      "set Height 1.5 m, Width 3 m and a 1:3 side slope."),
    Tool.LOWER_PATH: ("A swale carrying runoff to a pond. Draw its route, set Depth 0.6 m and "
                      "Width 2 m; the slopes tie it back into the ground."),
    Tool.RAISE_FLAT: ("A building pad above the flood level. Draw the outline and set the height "
                      "above the highest point on the outline you draw, so the whole pad sits "
                      "level."),
    Tool.LOWER_FLAT: ("A detention basin. Draw the outline, set Depth 1.2 m, and set Slopes to "
                      "Inside the outline so the sides slope down within it instead of the basin "
                      "growing outwards; the bottom comes out flat."),
    Tool.ADD: ("A 0.3 m layer of fill over a field. Draw the outline; the ground keeps its shape "
               "and every cell rises by the same amount."),
    Tool.SUBTRACT: ("Stripping 0.2 m of topsoil. Draw the outline; the ground keeps its shape and "
                    "every cell drops by the same amount."),
}

TOOL_DESCRIPTIONS = {
    Tool.INTERPOLATE: ("Replaces the terrain under the shape with a smooth grade between its "
                       "edges, so a missing or wrong patch is bridged rather than raised or cut."),
    Tool.RAISE_PATH: ("Builds a raised corridor along a line: a flat crest of the width you set, "
                      "with side slopes running down to meet the ground."),
    Tool.LOWER_PATH: ("Cuts a channel along a line: a flat bottom of the width you set, with "
                      "sides sloping up to meet the ground."),
    Tool.RAISE_FLAT: ("Lifts everything inside the shape to one level, measured from the highest "
                      "point on the line or outline you draw, with slopes tying the edge back "
                      "into the ground."),
    Tool.LOWER_FLAT: ("Cuts everything inside the shape down to one level, measured from the "
                      "lowest point on the line or outline you draw, with slopes tying the edge "
                      "back in."),
    Tool.ADD: "Adds the same height to every cell inside the shape; the terrain keeps its shape.",
    Tool.SUBTRACT: ("Takes the same height off every cell inside the shape; the terrain keeps "
                    "its shape."),
}

FIELD_TIPS = {
    "amount": ("How far the feature rises (height) or cuts (depth): above or below the straight "
               "grade between the path's ends, the highest or lowest point of the path or "
               "outline, or the terrain itself for Add and Subtract. For a 1.5 m embankment, "
               "set 1.5."),
    "width": ("How wide the flat part is — the crest of a dike, or the bottom of a ditch. A farm "
              "track is about 3 m; a footpath about 1.5 m."),
    "slope_n": ("How far the side slope runs out for every metre of height. 1:3 means 3 m "
                "outwards per 1 m up, about the steepest a mown grass embankment usually gets. "
                "0 means no side slopes at all."),
    "reach": ("The side slopes stop this far from the edge even if they have not met the ground. "
              "Set 5 m to keep a 1.5 m embankment out of a neighbouring plot that starts 5 m "
              "from the crest."),
    "slopes_inside": ("Inside: the outline is the top edge and the slopes run down within it — a "
                      "pond. Outside: the outline is the flat part and the slopes run out beyond "
                      "it — a raised pad."),
    "pixel_mode": ("Which cells count as covered by your shape. Narrow features can miss every "
                   "cell centre, which is when All touched helps."),
}

NO_FEATURES_SELECTED = ("Nothing is selected in that layer. Untick \'Selected features only\', or "
                        "select the features you want on the map first.")
EMPTY_LAYER = "That layer has no features to use."
PICK_A_LAYER = "Pick a layer above first."


def tool_tooltip(tool: Tool) -> str:
    """What a gallery item shows on hover: what the tool does, then a worked example."""
    return f"{TOOL_DESCRIPTIONS[tool]}\n\n{TOOL_EXAMPLES[tool]}"

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Sketch cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float | None) -> str:
    """A volume a user can read at a glance: no decimals once it is past a hundred.

    Cut and fill are magnitudes, so a minus sign here can only be floating-point residue —
    a negative zero out of a subtraction, or a few millilitres left over a million cells.
    Either would reach the user as "-0.00 m³", which reads as a bug, so the sign is dropped
    from anything that rounds to zero."""
    if value is None:
        return NO_VOLUME_YET
    size = abs(value)
    text = f"{value:,.0f}" if size >= 100.0 else f"{value:,.1f}" if size >= 1.0 else f"{value:.2f}"
    if text.startswith("-") and not any(digit in "123456789" for digit in text):
        text = text[1:]
    return f"{text} m³"


UNSAVED_CHANGES = ("This scenario has changes that are not saved. Save them before continuing?")
SCENARIO_SAVED = "Scenario saved to {}"
SCENARIO_REPLACE = "{} already exists. Replace it?"
SCENARIO_OPENED = "Scenario opened from {}"
SCENARIO_DEM_DIFFERS = ("This scenario was made on a DEM with a different {}.\n\n"
                        "Open it on this DEM anyway? The features keep their map position, so check "
                        "the result before using it.\n\n"
                        "Choose No to keep your current work, then pick the DEM the scenario was made "
                        "for and press Start before opening it.")
SCENARIO_NOT_APPLIED = ("The scenario could not be applied to this DEM, so it was not opened. "
                        "Your current features are unchanged.")
UNSAVED_BEFORE_CLOSING = ("Terrain Sketch is closing this scenario, and it has changes that are not "
                          "saved. Save them now?")
```

Replace the whole file:

**File:** `terrain_sketch/gui/main_dock.py`
```python
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
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .controller import LOG_TAG
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED, EXPORT_REPLACE,
                         REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                         SCENARIO_SAVED, SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES,
                         VIEW_3D_NOT_OPENED, VIEW_3D_TIP)
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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)

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
        self.export_button = QToolButton()
        self.export_button.setIcon(QgsApplication.getThemeIcon("/mActionSharingExport.svg"))
        self.export_button.setText(self.tr("Export DEM…"))
        self.export_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.export_button.setToolTip(self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
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
        self.canvas_undo_keys = UndoKeys(controller.undo_stack, applies=self._sketch_tool_active, parent=self)
        iface.mapCanvas().installEventFilter(self.canvas_undo_keys)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        tool, self.draw_tool, self._brush_fid = self.draw_tool, None, None
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
        self.iface.mapCanvas().scene().removeItem(self.highlight)
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
        self._asked_about_unsaved = True   # the user has just answered; closing the old session must not ask again
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
        finally:
            self._asked_about_unsaved = False

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
            try:
                initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
            except QgsCsException:
                self._brush_fid = None
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
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.setText(self._drawing_hint(method))
        self.hint.show()

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
        carries on. The Properties page reloads its fields, which otherwise keep the undone values."""
        self.stop_editing()
        if self._brush_fid is not None:
            self.end_drawing()
        fid = self.feature_view.selected_id()
        if self.pages.currentIndex() == PAGE_PROPERTIES and fid is not None and self.controller.find(fid) is not None:
            self.properties.show_feature(fid)

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map."""
        if fid is None or not self.controller.has_dem or fid not in {f.id for f in self.controller.features}:
            self.highlight.reset(Qgis.GeometryType.Line)
            return
        geometry = self._to_canvas(self.controller.feature_geometry(fid))
        self.highlight.reset(geometry.type())
        self.highlight.setToGeometry(geometry, None)

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
        try:
            differences = self.controller.scenario_differences(path)
            if differences and not self.confirm(SCENARIO_DEM_DIFFERS.format(", ".join(differences))):
                return
            self.stop_tools()
            self.controller.open_scenario(path)
        except ScenarioError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))
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
        since been moved or deleted becomes a message."""
        try:
            layer = QgsRasterLayer(path, os.path.splitext(os.path.basename(path))[0])
            if not layer.isValid():
                self._show_message(Qgis.MessageLevel.Warning, EXPORT_NOT_ADDED.format(path))
                return
            QgsProject.instance().addMapLayer(layer)
            if button is not None and not sip.isdeleted(button):
                button.setEnabled(False)       # once is enough; a second click would add a duplicate
        except Exception:  # noqa: BLE001
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self._show_message(Qgis.MessageLevel.Warning, EXPORT_NOT_ADDED.format(path))

    def _open_3d_view(self) -> None:
        """The modified DEM as the project's terrain, then a new 3D view (spec §8.5): through the
        interface when this QGIS offers it, otherwise through QGIS's own New 3D Map View action,
        otherwise a message saying how to open one by hand."""
        if not self.controller.show_in_3d():
            return
        try:
            if self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
                return
        except Exception:  # noqa: BLE001 — a QGIS built without 3D; this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
        action = self.iface.mainWindow().findChild(QAction, "mActionNew3DMapCanvas")
        if action is not None and action.isEnabled():
            action.trigger()
            return
        self._show_message(Qgis.MessageLevel.Warning, VIEW_3D_NOT_OPENED)

    def _context_menu(self, position) -> None:
        menu = self.feature_menu(self.feature_view.indexAt(position))
        if menu is not None:
            menu.exec(self.feature_view.viewport().mapToGlobal(position))

    def feature_menu(self, index) -> QMenu | None:
        """The list's context menu for the row at `index` (spec §7.2), or None off the rows."""
        if not index.isValid():
            return None
        fid = self.model.data(index, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction(self.tr("Rename"), lambda: self.feature_view.edit(index))
        menu.addAction(QgsApplication.getThemeIcon("/mActionDuplicateFeature.svg"), self.tr("Duplicate"),
                       lambda: self._duplicate(fid))
        menu.addAction(QgsApplication.getThemeIcon("/mActionZoomToLayer.svg"), self.tr("Zoom to feature"),
                       lambda: self._zoom_to(fid))
        menu.addSeparator()
        menu.addAction(QgsApplication.getThemeIcon("/mActionDeleteSelected.svg"), self.tr("Delete"),
                       lambda: self.controller.delete_feature(fid))
        return menu

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
```

Replace the whole file:

**File:** `terrain_sketch/qgis_io/raster_io.py`
```python
"""Reading the DEM into the engine; writing the working/change GeoTIFFs and the export."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer

from ..core.grid import DemGrid, Window

gdal.UseExceptions()

WARN_CELLS = 50_000_000
DEFAULT_NODATA = -9999.0
_CREATE_OPTIONS = ["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"]


class DemError(Exception):
    """The chosen layer cannot be used as the DEM; the message is shown to the user."""


class GeographicDemError(DemError):
    """A DEM in degrees. A DemError to every existing caller, but the panel checks for it so it
    can offer to reproject rather than only complaining."""


@dataclass(frozen=True)
class DemInfo:
    path: str
    crs_wkt: str
    nodata: float  # nodata value written to the working, change and exported files
    band_count: int
    warnings: tuple = ()
    integer: bool = False  # the source stores whole numbers; the working files and export are float32


def read_dem(layer) -> tuple[DemGrid, DemInfo]:
    """Band 1 of a file-based raster layer in a projected CRS, as a DemGrid."""
    if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
        raise DemError("Pick a valid raster layer as the DEM.")
    if layer.providerType() != "gdal":
        raise DemError("Only file-based rasters (for example GeoTIFF) can be used as the DEM.")
    if layer.crs().isGeographic():
        raise GeographicDemError("The DEM uses latitude/longitude. Slopes and widths need metres: reproject it to a "
                       "projected CRS first (Raster ▸ Projections ▸ Warp).")
    try:
        ds = gdal.Open(layer.source())
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        array = band.ReadAsArray()
    except (RuntimeError, MemoryError) as error:
        raise DemError(f"The DEM could not be read: {error}") from error
    try:
        grid = DemGrid.from_array(array, ds.GetGeoTransform(), nodata)
    except ValueError as error:
        raise DemError(f"This raster cannot be used as the DEM: {error}.") from error
    warnings = []
    if ds.RasterCount > 1:
        warnings.append(f"The DEM has {ds.RasterCount} bands; band 1 is used.")
    cells = grid.rows * grid.cols
    if cells > WARN_CELLS:
        warnings.append(f"The DEM has {cells / 1e6:.0f} million cells and needs about "
                        f"{cells * 12 / 1e9:.1f} GB of memory; consider clipping it to your site.")
    info = DemInfo(layer.source(), layer.crs().toWkt(),
                   DEFAULT_NODATA if nodata is None else float(nodata), ds.RasterCount, tuple(warnings),
                   integer=bool(np.issubdtype(array.dtype, np.integer)))
    return grid, info


class WorkingFiles:
    """The working DEM and the change raster (working − original) of a session, on disk."""

    def __init__(self, folder: str, original: DemGrid, info: DemInfo):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.working_path = os.path.join(folder, "working_dem.tif")
        self.change_path = os.path.join(folder, "change.tif")
        self._original = original
        self._info = info
        _write_tif(self.working_path, _for_output(original.data, original.valid, info.nodata), original, info)
        _write_tif(self.change_path, _for_output(np.zeros(original.data.shape), original.valid, info.nodata),
                   original, info)

    def write(self, window: Window, working: DemGrid) -> None:
        """Write one window of the working DEM and its change into both files."""
        rows, cols = window.slices
        valid = self._original.valid[rows, cols]
        values = working.data[rows, cols]
        change = values.astype(np.float64) - self._original.data[rows, cols]
        for path, block in ((self.working_path, _for_output(values, valid, self._info.nodata)),
                            (self.change_path, _for_output(change, valid, self._info.nodata))):
            ds = gdal.Open(path, gdal.GA_Update)
            ds.GetRasterBand(1).WriteArray(block, window.col0, window.row0)
            ds.FlushCache()
            ds = None


def export_dem(path: str, working: DemGrid, info: DemInfo) -> None:
    """Float32 GeoTIFF of the modified DEM on the original grid, CRS and nodata value."""
    _write_tif(path, _for_output(working.data, working.valid, info.nodata), working, info,
               extra_options=["PREDICTOR=3"])


def _for_output(values: np.ndarray, valid: np.ndarray, nodata: float) -> np.ndarray:
    """Float32 copy with nodata cells set to `nodata`; valid cells that happen to equal
    `nodata` are nudged by one float step so they do not turn into holes."""
    out = values.astype(np.float32, copy=True)
    marker = np.float32(nodata)
    clash = valid & (out == marker)
    out[clash] = np.nextafter(marker, np.float32(np.inf))
    out[~valid] = marker
    return out


def _write_tif(path: str, array: np.ndarray, grid: DemGrid, info: DemInfo, extra_options=()) -> None:
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.cols, grid.rows, 1, gdal.GDT_Float32,
                                              _CREATE_OPTIONS + list(extra_options))
    ds.SetGeoTransform(grid.geotransform)
    ds.SetProjection(info.crs_wkt)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(info.nodata)
    band.WriteArray(array)
    ds.FlushCache()
    ds = None
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_export_options.py` → Expected: `4 passed`
Run: `scripts/test.sh` → Expected: `429 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/qgis_io/raster_io.py tests/qgis/test_export_options.py
git commit -m "feat(gui): add an exported DEM to the project, and say when an integer DEM gains decimals"
```

---

## Manual check in QGIS (for the human, after merge)

The suite cannot see these. Plans 2-6 still have their own lists waiting.

1. `scripts/dev_install.sh`, restart QGIS 4, load a projected DEM, open Terrain Sketch, press **Start**, and draw a dike and a pond.
2. Change the dike's height with the spin box arrows several times, then press Ctrl+Z with focus in the panel. One press should undo the whole adjustment, and the Properties page should show the old value. Ctrl+Shift+Z brings it back.
3. Put a vector layer in editing mode and move one of its features. With focus on the map and the Pan tool active, Ctrl+Z must undo **that layer edit**, not a Terrain Sketch change. Pick a Terrain Sketch drawing tool: Ctrl+Z on the map now undoes Terrain Sketch.
4. Drag a profile in the Profiles panel, click inside that panel, press Ctrl+Z: the profile goes back.
5. Make the Terrain Sketch panel narrow: the header buttons that do not fit should move behind », not squeeze the panel.
6. Right-click a feature: **Rename** edits its name in place and the Properties title follows; **Duplicate** adds an unticked copy right below it.
7. Press **3D view**: a 3D map view should open showing the sketched dike, at true height. Close the session (remove the DEM layer): Project ▸ Properties ▸ Terrain should be back to what it was. If no 3D view opened, check the message's instructions and whether View ▸ 3D Map Views ▸ New 3D Map View works — then report it, because the fallback action's name could only be guessed headless.
8. **Export DEM…**, then **Add to project** on the message: the GeoTIFF appears as a layer, and the button greys out. With an integer DEM (e.g. Int16), the dialog title and the message should both mention 32-bit float.
9. Start a session, note the folder `terrain_sketch_*` in the system temp directory, then close the session: the folder should be gone.

## Deferred to Plan 8

| Item | Why not here |
|---|---|
| Profile editor: `reach` rounding to 0.0 on a hard terminus drag; the arrow-key nudge committing (and now recording an undo step) per keypress; the unreachable left side of a cross profile; the real area section line; the end-cap asymmetry | Editor behaviour, carried since Plans 3-4. |
| Guidance: the pixel-mode picture in the combobox tooltip; tool-specific H/D labels; illustration polish | Plan 5 carry-overs. |
| Panel state: dock geometry under `terrain_sketch/`; `QgsCollapsibleGroupBox` state | Plan 5 carry-overs. |
| Working GeoTIFFs in `<scenario>_files/` once saved (spec §8.2 step 3); Open picking the DEM from `dem_source`; saving after opening another DEM's scenario rewriting its metadata | Scenario refinements and a decision (Plan 6). |
| Replacing a scenario that is open as a QGIS layer on Windows; `_check_replaceable` being check-then-replace | Platform and race edge cases (Plan 6). |
| `FeatureListModel.data()` rebuilding a dict per call; tests never disconnecting `SketchController` from the `QgsProject` singleton | Performance and test hygiene. |
| Plan 6 minors: `load`/`load_meta` repeating one skeleton; `differences()` tested for 2 of 4 labels; a `_mark_scenario` helper; `created` kept by string path comparison | Style and coverage. |
