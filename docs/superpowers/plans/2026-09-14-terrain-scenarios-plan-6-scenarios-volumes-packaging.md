# Terrain Scenarios — Plan 6: Scenarios, Volumes and Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Work persists, the numbers are visible, and the plugin can be installed. A scenario saves to a plain GeoPackage and opens again onto the DEM; the Properties page shows fill, cut and pond storage for the selected feature and totals for the whole scenario; and a script builds the ZIP that *Plugins ▸ Install from ZIP* accepts. Nothing a user has not saved is ever discarded without a question.

**Architecture:** `qgis_io/scenario.py` reads and writes the GeoPackage with `ogr` only (no `qgis`), building the file beside its target and moving it into place once complete. `SketchController` owns the scenario state — the file, whether it is saved, when it was created — and exposes one hook, `before_discard`, that the panel fills with a save question; the controller itself never shows UI. The Volumes group reads `FeatureStats` the engine already computes, and asks `core.tools.reports_storage` — the rule the engine uses — whether a Storage figure exists.

**Tech Stack:** QGIS 4.2.2 Python API (PyQt6 via `qgis.PyQt`, Qt 6.11), GDAL/OGR 3.13 (GeoPackage driver), numpy; pytest (dev-only) with a headless `QgsApplication`; bash + `zip` for packaging.

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-scenarios-design.md` — §5.5 (volumes), §7.2 (scenario actions, the Volumes group), §8.4 (the scenario file, loading against a different DEM, save prompts), §11 milestone 6. Plans 1-5 are merged on `main`; **read the Plan 5 addendum first**. Milestone 6 is split: undo/redo and the 3D view move to Plan 7 with the deferred backlog (see the end of this plan).

## Global Constraints

- Target QGIS 4.x (Qt6) only. Import Qt through `qgis.PyQt` and always use fully scoped Qt6 enums.
- Native look (spec §7.1): only standard Qt/QGIS widgets and palette colours, QGIS theme icons via `QgsApplication.getThemeIcon`, **no stylesheets**. The UI inherits the active QGIS theme, light or dark.
- `terrain_scenarios/core/` and `terrain_scenarios/model/` never import `qgis` or `PyQt`; `qgis_io/scenario.py` uses `ogr`/`osr` only. Widgets never call the engine, files or layers directly — only `SketchController`.
- Errors never take QGIS down: user problems become message-bar messages; unexpected errors are caught and logged. **An exception raised inside a Qt callback aborts the interpreter** — this has cost the project three hard crashes, and Plan 6's prototype had a fourth waiting (see Decisions). Anything reachable from a slot, a signal or a button must let only the exception types its caller catches escape. `SketchController.feature()` raises for an unknown id; use `find()` from slots.
- **There is no undo.** Every path that replaces or drops features — New, Open, Start on another DEM, closing the project, removing the DEM, unloading the plugin — must either find the work saved or ask first. A save that fails must leave the previous file readable.
- Every user-facing string lives in `gui/help_texts.py`; widget captions use `self.tr("literal")`. Never call `tr()` on a non-literal (Plan 5 removed those). English only.
- Package modules start with a one-line docstring and use `from __future__ import annotations` where they have type hints; test modules need neither. 4-space indentation. Imports sorted within their group.
- Tests run only through `scripts/test.sh`. Never run `scripts/dev_install.sh`. In a test hook reached from a Qt signal or a button click, **record the call and assert afterwards — never `pytest.fail()` inside it**: `Failed` is a `BaseException`, passes the plugin's `except Exception` guards and aborts the whole run.
- GDAL runs with exceptions enabled throughout the plugin. Close GDAL datasources explicitly with `Close()`.

## Decisions made while prototyping (read before implementing)

These came out of re-reading spec §8.4 against a 315-test prototype whose tests all passed mutation checks — and finding a crash and three ways to lose work that the suite could not see.

- **A DEM whose CRS has no EPSG code must be saveable.** With GDAL exceptions on, `osr.SpatialReference.AutoIdentifyEPSG()` raises `RuntimeError: Unsupported SRS` for any local survey grid. Reached from `dem_meta()`, outside the save's error mapping, that escaped the Save button's slot as a `RuntimeError` and would have aborted QGIS. `_crs_id` now swallows it and falls back to the CRS name; the features layer gets its SRS from the DEM's WKT, not from that name.
- **A save is built beside its target and moved over it when complete** (`<name>.saving-<hex>.gpkg`, then `os.replace`). Writing in place destroyed the previous scenario whenever a save failed half way. The failed attempt's file and SQLite sidecars are removed.
- **A load that cannot be applied changes nothing.** `_set` now returns `False` when the engine refuses the features, and `open_scenario` raises `ScenarioError(SCENARIO_NOT_APPLIED)` without touching the scenario path, `created` date or unsaved state. Before, the path pointed at the file that failed to open while the old features stayed on screen marked as saved — the next Save wrote them over it.
- **Dropping a session forgets the scenario file.** Otherwise Start on another DEM kept the old path, and Save wrote the new, empty session over the scenario just left.
- **Loaded features get fresh ids.** Ids derived from the GeoPackage row (`gpkg-1`) repeat across files, so a panel still showing feature 1 of scenario A silently retargeted feature 1 of scenario B. Opening also stops any drawing or vertex edit in progress.
- **A scenario made on a different DEM is only opened once the user agrees** (spec §8.4: "warns and offers to load anyway or to pick another DEM"). `scenario_differences(path)` reads only the metadata; the panel asks with `confirm`; No keeps the current work untouched.
- **Save prompts everywhere work can be lost.** New, Open and Start ask Save / Discard / Cancel through `_keep_unsaved_work`. Closing the project, removing the DEM and unloading the plugin reach the controller's `_drop_session`, which calls `before_discard` first; the panel asks Save / Discard only, because none of those can be cancelled from a plugin. Start sets `_asked_about_unsaved` while it closes the old session so the user is not asked twice, and clears it in `finally` so a refused Start (a geographic DEM) leaves the work protected.
- **The controller shows no UI.** `before_discard` is a plain attribute the panel fills; the controller calls it only when there is a session with unsaved features, and guards it — it runs from project and layer signals.
- **Ask before replacing a scenario after adding `.gpkg`.** The file dialog's overwrite check runs on the name as typed; `flood` becoming `flood.gpkg` would otherwise replace an existing scenario silently. (Export DEM has the same flaw with `.tif`; it is listed for Plan 7.)
- **Storage follows one rule.** `core.tools.reports_storage(tool, mode)` — Interpolate only in area mode (spec §5.5) — is used by both `apply_feature` and the Volumes group, so the panel never shows a Storage row the engine will not fill. The figure is prefixed `≈` as §5.5 writes it.
- **No `-0.00 m³`.** Cut and fill are magnitudes; a minus sign is floating-point residue, so `cubic_metres` drops it from anything that rounds to zero and keeps it on a genuine negative.
- **The four file actions are icon-only, auto-raised tool buttons** like QGIS's own dock toolbars (spec §7.2: "icon buttons with tooltips"); the tooltip starts with the action's name. Six text buttons and a checkbox do not fit a right-hand dock. Export DEM keeps its label as the main output action and moves to `mActionSharingExport.svg`, because Save as… now needs `mActionFileSaveAs.svg`.
- **The test suite can no longer hang on a dialog.** conftest clears the project around every test, which now legitimately asks a panel with unsaved work whether to save. An autouse fixture answers `QMessageBox.question` with Discard/No/Cancel and returns empty paths from `QFileDialog`; tests about a prompt replace the panel's own hooks.
- **`show_feature` refreshes problems and volumes.** The prototype replaced the problems refresh with the volumes refresh; a test now selects a flagged feature, a clean one, then the flagged one again.

## File Structure

| File | Responsibility |
|---|---|
| `terrain_scenarios/core/tools.py` | `reports_storage(tool, mode)`: whether a feature can hold water |
| `terrain_scenarios/core/operations.py` | Computes storage through that rule |
| `terrain_scenarios/qgis_io/scenario.py` | The GeoPackage: `save`, `load`, `load_meta`, `dem_meta`, `ScenarioMeta`, `ScenarioError` |
| `terrain_scenarios/gui/controller.py` | `totals()`, scenario state, `save_scenario` / `open_scenario` / `scenario_differences` / `new_scenario`, `before_discard` |
| `terrain_scenarios/gui/properties_page.py` | The Volumes group |
| `terrain_scenarios/gui/main_dock.py` | New, Open…, Save, Save as…; every save question |
| `terrain_scenarios/gui/help_texts.py` | Volume and scenario strings, `cubic_metres` |
| `scripts/build_zip.sh` | The installable ZIP |
| `tests/qgis/conftest.py` | No modal dialog can block a test run |

---

### Task 1: Volumes in the Properties page

**Files:**
- Modify: `terrain_scenarios/core/tools.py`, `terrain_scenarios/core/operations.py`, `terrain_scenarios/gui/help_texts.py`, `terrain_scenarios/gui/controller.py`, `terrain_scenarios/gui/properties_page.py`
- Test: `tests/qgis/test_volumes_panel.py`

**Interfaces:**
- Consumes: `FeatureStats(cut, fill, storage, changed_cells, flags)` from `core.operations`; `total_cut_fill(original, working) -> (cut, fill)` from `core.volumes`; `SketchController.stats(fid)`, `find(fid)`, `featuresChanged`.
- Produces: `core.tools.reports_storage(tool: Tool, mode: Mode) -> bool`; `SketchController.totals() -> tuple[float, float]` as `(cut, fill)`, `(0.0, 0.0)` without a session; `help_texts.cubic_metres(value: float | None) -> str`, `NO_VOLUME_YET`, `SCENARIO_TOTALS` (`.format(fill=, cut=)`), `VOLUME_FILL_TIP`, `VOLUME_CUT_TIP`, `VOLUME_STORAGE_TIP`, `VOLUME_STORAGE_NOTE`; `PropertiesPage.volumes`, `.fill_value`, `.cut_value`, `.storage_value`, `.totals_value`, `.volume_form`.

- [ ] **Step 1: Write the failing test**

**File:** `tests/qgis/test_volumes_panel.py`
```python
"""The Volumes panel: what the numbers say, and when Storage is shown at all."""
import numpy as np
import pytest

from qgis_helpers import UTM, line_through, square, start_session
from terrain_scenarios.core.tools import TOOL_INFO, Mode, Tool, reports_storage
from terrain_scenarios.gui.help_texts import FLAG_TEXTS, NO_VOLUME_YET, SCENARIO_TOTALS, VOLUME_STORAGE_NOTE, cubic_metres
from terrain_scenarios.gui.properties_page import PropertiesPage


def test_a_raised_dike_reports_its_fill_and_no_cut(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=2.0, width=6.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)

    stats = c.stats(dike.id)
    assert stats.fill > 0.0
    assert page.fill_value.text() == cubic_metres(stats.fill)
    assert page.cut_value.text() == cubic_metres(0.0)


def test_a_dug_pond_reports_its_cut_and_its_storage(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    c.update_feature(pond.id, amount=1.5)
    page = PropertiesPage(c)
    page.show_feature(pond.id)

    stats = c.stats(pond.id)
    assert stats.cut > 0.0 and stats.storage is not None
    assert page.cut_value.text() == cubic_metres(stats.cut)
    assert page.storage_value.text() == f"≈ {cubic_metres(stats.storage)} {VOLUME_STORAGE_NOTE}"


def test_storage_is_hidden_for_a_tool_that_cannot_hold_water(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    page = PropertiesPage(c)

    page.show_feature(pond.id)
    assert page.volume_form.isRowVisible(page.storage_value)
    page.show_feature(dike.id)
    assert not page.volume_form.isRowVisible(page.storage_value)
    page.show_feature(pond.id)
    assert page.volume_form.isRowVisible(page.storage_value)   # and it comes back


def test_selecting_another_feature_shows_its_own_problems(tmp_path):
    """The Volumes group must not take the place of the problem check when a feature is shown."""
    c = start_session(tmp_path)
    runs_off = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 60, 20), UTM)
    inside = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    flags = c.stats(runs_off.id).flags
    assert flags and not c.stats(inside.id).flags
    page = PropertiesPage(c)
    page.show()

    page.show_feature(runs_off.id)
    assert page.problems.isVisible() and FLAG_TEXTS[flags[0]] in page.problems.text()
    page.show_feature(inside.id)
    assert not page.problems.isVisible()
    page.show_feature(runs_off.id)
    assert page.problems.isVisible()


def test_interpolate_shows_storage_for_an_area_but_not_along_a_path(tmp_path):
    c = start_session(tmp_path)
    strip = c.add_drawn(Tool.INTERPOLATE, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    patch = c.add_drawn(Tool.INTERPOLATE, Mode.AREA, square(10, 10, 25, 25), UTM)
    page = PropertiesPage(c)
    page.show_feature(strip.id)
    assert not page.volume_form.isRowVisible(page.storage_value)   # a row that could only ever say "—"
    page.show_feature(patch.id)
    assert page.volume_form.isRowVisible(page.storage_value)


def test_the_panel_and_the_engine_agree_on_which_features_have_storage(tmp_path):
    """The row is shown by `reports_storage`; the figure is computed by the engine. A feature the
    engine gives storage to must never have its row hidden, and a hidden row must mean the
    engine computed none — otherwise the panel hides a number or shows one that is not there."""
    c = start_session(tmp_path, np.pad(np.full((20, 20), 5.0, np.float32), 10, constant_values=10.0))
    shapes = {Mode.PATH: line_through(5, 20, 34, 20), Mode.AREA: square(12, 12, 27, 27)}
    for tool, info in TOOL_INFO.items():
        for mode in info.modes:
            feature = c.add_drawn(tool, mode, shapes[mode], UTM)
            c.update_feature(feature.id, amount=1.0)
            has_storage = c.stats(feature.id).storage is not None
            assert has_storage <= reports_storage(tool, mode), (tool, mode)
            c.delete_feature(feature.id)


def test_the_numbers_follow_an_edit(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=1.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    before = page.fill_value.text()

    c.update_feature(dike.id, amount=3.0)
    assert page.fill_value.text() != before
    assert page.fill_value.text() == cubic_metres(c.stats(dike.id).fill)


def test_the_whole_scenario_line_adds_the_features_up(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 5, 34, 5), UTM)
    c.update_feature(dike.id, amount=2.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    one_feature = page.totals_value.text()

    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 20, 25, 33), UTM)
    c.update_feature(pond.id, amount=1.5)
    page.show_feature(dike.id)                      # still looking at the dike
    assert page.fill_value.text() == cubic_metres(c.stats(dike.id).fill)
    assert page.totals_value.text() != one_feature  # but the totals grew
    cut, fill = c.totals()
    assert cut > 0.0 and fill > 0.0
    assert page.totals_value.text() == SCENARIO_TOTALS.format(fill=cubic_metres(fill), cut=cubic_metres(cut))


def test_a_disabled_feature_leaves_nothing_in_the_totals(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=2.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert c.totals() != (0.0, 0.0)

    c.update_feature(dike.id, enabled=False)
    assert c.totals() == (0.0, 0.0)
    assert page.totals_value.text() == SCENARIO_TOTALS.format(fill=cubic_metres(0.0), cut=cubic_metres(0.0))


@pytest.mark.parametrize("value, expected", [
    (0.0, "0.00 m³"), (0.5, "0.50 m³"), (1.0, "1.0 m³"), (99.94, "99.9 m³"),
    (100.0, "100 m³"), (12345.6, "12,346 m³"), (None, NO_VOLUME_YET)])
def test_volumes_are_written_the_way_a_reader_expects(value, expected):
    assert cubic_metres(value) == expected


@pytest.mark.parametrize("value", [-0.0, -0.004, -0.0049])
def test_a_volume_that_rounds_to_zero_never_shows_a_minus_sign(value):
    assert cubic_metres(value) == "0.00 m³"


def test_a_volume_that_really_is_negative_keeps_its_sign():
    assert cubic_metres(-5.0) == "-5.0 m³"       # a genuine negative is a bug worth seeing
    assert cubic_metres(-0.49) == "-0.49 m³"     # only what ROUNDS to zero loses the sign
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_volumes_panel.py`
Expected: collection error `ImportError: cannot import name 'reports_storage' from 'terrain_scenarios.core.tools'`

- [ ] **Step 3: Share the storage rule**

Replace the whole file:

**File:** `terrain_scenarios/core/tools.py`
```python
"""Tool, mode and pixel-mode definitions shared by the engine, the model and the GUI."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Tool(str, Enum):
    INTERPOLATE = "interpolate"
    RAISE_PATH = "raise_path"
    LOWER_PATH = "lower_path"
    RAISE_FLAT = "raise_flat"
    LOWER_FLAT = "lower_flat"
    ADD = "add"
    SUBTRACT = "subtract"


class Mode(str, Enum):
    PATH = "path"
    AREA = "area"


class PixelMode(str, Enum):
    ALL_TOUCHED = "all_touched"
    CENTRE = "centre"
    FULLY_INSIDE = "fully_inside"


class Combine(str, Enum):
    SET = "set"
    MAX = "max"
    MIN = "min"
    ADD = "add"
    SUBTRACT = "subtract"


@dataclass(frozen=True)
class ToolInfo:
    modes: tuple
    combine: Combine
    has_slopes: bool
    direction: int  # -1: side slopes go down (raise tools), +1: go up (lower tools), 0: no slopes
    reports_storage: bool


TOOL_INFO = {
    Tool.INTERPOLATE: ToolInfo((Mode.PATH, Mode.AREA), Combine.SET, False, 0, True),
    Tool.RAISE_PATH: ToolInfo((Mode.PATH,), Combine.MAX, True, -1, False),
    Tool.LOWER_PATH: ToolInfo((Mode.PATH,), Combine.MIN, True, 1, True),
    Tool.RAISE_FLAT: ToolInfo((Mode.PATH, Mode.AREA), Combine.MAX, True, -1, False),
    Tool.LOWER_FLAT: ToolInfo((Mode.PATH, Mode.AREA), Combine.MIN, True, 1, True),
    Tool.ADD: ToolInfo((Mode.PATH, Mode.AREA), Combine.ADD, False, 0, False),
    Tool.SUBTRACT: ToolInfo((Mode.PATH, Mode.AREA), Combine.SUBTRACT, False, 0, True),
}


def reports_storage(tool: Tool, mode: Mode) -> bool:
    """Whether a feature can hold water, so its storage is worth computing and showing.
    Interpolate only does in area mode (spec §5.5): along a path it grades a strip between two
    ends and leaves no basin. The engine and the Volumes panel both ask here, so they cannot
    disagree about when a Storage figure exists."""
    return TOOL_INFO[tool].reports_storage and (tool is not Tool.INTERPOLATE or mode is Mode.AREA)
```
In `terrain_scenarios/core/operations.py`, the storage condition now asks that rule (`want_line` stays: it is still used above). Replace the whole file:

**File:** `terrain_scenarios/core/operations.py`
```python
"""The seven terrain tools. `apply_feature` edits a DemGrid in place, part by part."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import QhullError

from .geometry import (corridor, densify, envelope, is_line, line_coords, polygon_rings,
                       simplify_line, split_parts)
from .grid import DemGrid, Window
from .mask import polygon_mask
from .profiles import side_dz, side_limit
from .stations import stations_offsets, vertex_stations
from .tools import TOOL_INFO, Combine, Mode, Tool, reports_storage
from .volumes import cut_fill, pond_storage

MARGIN_CELLS = 4  # >= nearest-valid search radius (3) + 1 for bilinear sampling

FLAG_OUTSIDE = "outside"
FLAG_NO_PIXELS = "no_pixels"
FLAG_NODATA_REFERENCE = "nodata_reference"
FLAG_BAD_GEOMETRY = "bad_geometry"


@dataclass(frozen=True)
class FeatureStats:
    cut: float = 0.0
    fill: float = 0.0
    storage: float | None = None
    changed_cells: int = 0
    flags: tuple = ()


class NoReferenceError(Exception):
    """A reference elevation could not be sampled because the terrain there is nodata."""


def path_coords(part, cell_size: float) -> np.ndarray:
    """Vertices of a path part as used by the engine (simplified to half a cell)."""
    return line_coords(simplify_line(part, 0.5 * cell_size))


def rule_profile(feature, part, grid: DemGrid) -> tuple:
    """Design line ((station, z), ...) of a path part from the tool rule, sampled on the
    current terrain. Stations follow the engine's simplified path; the flat tools read the
    drawn (unsimplified) vertices."""
    vertices = line_coords(part)
    length = float(vertex_stations(path_coords(part, grid.cell_size))[-1])
    tool, amount = feature.tool, feature.amount
    if tool in (Tool.RAISE_FLAT, Tool.LOWER_FLAT):
        z = np.array([grid.sample(x, y) for x, y in vertices])
        if np.isnan(z).all():
            raise NoReferenceError
        level = np.nanmax(z) + amount if tool is Tool.RAISE_FLAT else np.nanmin(z) - amount
        return ((0.0, float(level)), (length, float(level)))
    z0, z1 = grid.sample(*vertices[0]), grid.sample(*vertices[-1])
    if math.isnan(z0) or math.isnan(z1):
        raise NoReferenceError
    offset = {Tool.RAISE_PATH: amount, Tool.LOWER_PATH: -amount}.get(tool, 0.0)
    return ((0.0, z0 + offset), (length, z1 + offset))


def part_window(feature, part, grid: DemGrid) -> Window | None:
    info = TOOL_INFO[feature.tool]
    if is_line(part):
        width = max(feature.width, grid.cell_size)
        band = corridor(simplify_line(part, 0.5 * grid.cell_size), width)
        r = _path_side_limit(feature) if info.has_slopes else 0.0
        if band is None or band.IsEmpty():
            xmin, ymin, xmax, ymax = envelope(part)
            r = width / 2.0
        else:
            xmin, ymin, xmax, ymax = envelope(band)
        return grid.window_for_bbox(xmin - r, ymin - r, xmax + r, ymax + r, MARGIN_CELLS)
    xmin, ymin, xmax, ymax = envelope(part)
    r = feature.reach if (info.has_slopes and feature.slope_n > 0.0 and not feature.slopes_inside) else 0.0
    return grid.window_for_bbox(xmin - r, ymin - r, xmax + r, ymax + r, MARGIN_CELLS)


def feature_window(feature, grid: DemGrid) -> Window | None:
    """Every cell the feature may read or change, or None if it misses the grid."""
    try:
        parts = split_parts(feature.geometry_wkb)
    except ValueError:
        return None
    window = None
    for part in parts:
        w = part_window(feature, part, grid)
        if w is not None:
            window = w.union(window)
    return window


def footprint_flags(feature) -> tuple:
    """Flags for a feature that has no window on the grid."""
    try:
        split_parts(feature.geometry_wkb)
    except ValueError:
        return (FLAG_BAD_GEOMETRY,)
    return (FLAG_OUTSIDE,)


def apply_feature(feature, grid: DemGrid) -> FeatureStats:
    """Apply one feature to `grid` in place and report its volumes and problems."""
    info = TOOL_INFO[feature.tool]
    try:
        parts = split_parts(feature.geometry_wkb)
    except ValueError:
        return FeatureStats(flags=(FLAG_BAD_GEOMETRY,))
    want_line = feature.mode is Mode.PATH
    long_profile = feature.long_profile if len(parts) == 1 else None
    flags: set = set()
    cut = fill = 0.0
    storage = None
    changed = 0
    on_grid = selected_any = False
    for part in parts:
        if is_line(part) != want_line:
            flags.add(FLAG_BAD_GEOMETRY)
            continue
        window = part_window(feature, part, grid)
        if window is None:
            continue
        on_grid = True
        view = grid.view(window)
        before = view.data.astype(np.float64)
        try:
            if want_line:
                new, selected = _path_values(feature, info, part, view, long_profile)
            else:
                new, selected = _area_values(feature, info, part, view)
        except NoReferenceError:
            flags.add(FLAG_NODATA_REFERENCE)
            continue
        selected &= view.valid
        if not selected.any():
            continue
        selected_any = True
        view.data[selected] = new[selected].astype(view.data.dtype)
        after = view.data.astype(np.float64)
        c, f = cut_fill(before, after, view.valid, grid.cell_area)
        cut, fill = cut + c, fill + f
        changed += int(((after != before) & view.valid).sum())
        if reports_storage(feature.tool, feature.mode):
            s = pond_storage(after, (after < before) & view.valid, view.valid, grid.cell_area)
            if s is not None:
                storage = (storage or 0.0) + s
    if not on_grid and not flags:
        flags.add(FLAG_OUTSIDE)
    elif on_grid and not selected_any and not flags:
        flags.add(FLAG_NO_PIXELS)
    return FeatureStats(cut, fill, storage, changed, tuple(sorted(flags)))


def _combine(combine: Combine, old: np.ndarray, design: np.ndarray) -> np.ndarray:
    if combine is Combine.MAX:
        return np.maximum(old, design)
    if combine is Combine.MIN:
        return np.minimum(old, design)
    return design


def _path_values(feature, info, drawn, view: DemGrid, long_profile):
    part = simplify_line(drawn, 0.5 * view.cell_size)
    coords = line_coords(part)
    old = view.data.astype(np.float64)
    if len(coords) < 2:
        return old, np.zeros(old.shape, bool)
    width = max(feature.width, view.cell_size)
    band_geom = corridor(part, width)
    core = polygon_mask(band_geom, view, feature.pixel_mode)
    if feature.tool is Tool.ADD:
        return old + feature.amount, core
    if feature.tool is Tool.SUBTRACT:
        return old - feature.amount, core
    profile = sorted(long_profile) if long_profile else rule_profile(feature, drawn, view)
    if feature.tool is Tool.INTERPOLATE:
        station, _ = _stations(coords, view, core)
        return np.interp(station, [p[0] for p in profile], [p[1] for p in profile]), core
    if not core.any():
        return old, core
    # distance beyond the crest (the outline lies half a cell from core centres)
    dist = ndimage.distance_transform_edt(~core, sampling=(view.cell_height, view.cell_width))
    beyond = np.maximum(dist - 0.5 * view.cell_size, 0.0)
    # stations only where a cell can change: the crest and the cells within slope reach
    station, offset = _stations(coords, view, core | (beyond <= _path_side_limit(feature)))
    zline = np.interp(station, [p[0] for p in profile], [p[1] for p in profile])
    dz_l, ext_l = side_dz(beyond, feature.cross_left, feature.slope_n, feature.reach, info.direction)
    dz_r, ext_r = side_dz(beyond, feature.cross_right, feature.slope_n, feature.reach, info.direction)
    left = offset < 0.0
    in_extent = np.where(left, ext_l, ext_r)
    dz = np.where(core, 0.0, np.where(left, dz_l, dz_r))
    slope_cells = ~core & in_extent
    return _combine(info.combine, old, zline + dz), core | slope_cells


def _path_side_limit(feature) -> float:
    return max(side_limit(feature.cross_left, feature.slope_n, feature.reach),
               side_limit(feature.cross_right, feature.slope_n, feature.reach))


def _stations(coords: np.ndarray, view: DemGrid, cells: np.ndarray):
    """Station and signed offset for the selected cells (zero elsewhere)."""
    X, Y = view.cell_centers()
    station = np.zeros(cells.shape)
    offset = np.zeros(cells.shape)
    station[cells], offset[cells] = stations_offsets(coords, X[cells], Y[cells])
    return station, offset


def _area_values(feature, info, part, view: DemGrid):
    core = polygon_mask(part, view, feature.pixel_mode)
    old = view.data.astype(np.float64)
    tool = feature.tool
    if tool is Tool.ADD:
        return old + feature.amount, core
    if tool is Tool.SUBTRACT:
        return old - feature.amount, core
    if tool is Tool.INTERPOLATE:
        return _vertex_surface(part, view), core
    ring = densify(polygon_rings(part)[0], view.cell_size)
    z = np.array([view.sample(x, y) for x, y in ring])
    if np.isnan(z).all():
        raise NoReferenceError
    level = np.nanmax(z) + feature.amount if tool is Tool.RAISE_FLAT else np.nanmin(z) - feature.amount
    design, selected = _area_design(feature, info, core, view, float(level))
    return _combine(info.combine, old, design), selected


def _area_design(feature, info, core: np.ndarray, view: DemGrid, level: float):
    design = np.full(core.shape, level)
    if feature.slope_n <= 0.0 or not core.any() or core.all():
        return design, core
    sampling = (view.cell_height, view.cell_width)
    half_cell = 0.5 * view.cell_size
    if not feature.slopes_inside:
        dist = ndimage.distance_transform_edt(~core, sampling=sampling)
        beyond = np.maximum(dist - half_cell, 0.0)
        dz, in_extent = side_dz(beyond, (), feature.slope_n, feature.reach, info.direction)
        return level + np.where(core, 0.0, dz), core | in_extent
    dist, (ri, ci) = ndimage.distance_transform_edt(core, sampling=sampling, return_indices=True)
    inward = np.maximum(dist - half_cell, 0.0)
    edge = view.data[ri, ci].astype(np.float64)  # terrain just outside the outline
    if info.direction > 0:
        slope = np.maximum(level, edge - inward / feature.slope_n)
    else:
        slope = np.minimum(level, edge + inward / feature.slope_n)
    return np.where(view.valid[ri, ci], slope, level), core


def _vertex_surface(part, view: DemGrid) -> np.ndarray:
    pts = np.vstack([ring[:-1] for ring in polygon_rings(part)])
    z = np.array([view.sample(x, y) for x, y in pts])
    ok = ~np.isnan(z)
    if not ok.any():
        raise NoReferenceError
    pts, z = pts[ok], z[ok]
    X, Y = view.cell_centers()
    nearest = NearestNDInterpolator(pts, z)(X, Y)
    try:
        surface = LinearNDInterpolator(pts, z)(X, Y)
    except (QhullError, ValueError):
        return nearest
    return np.where(np.isnan(surface), nearest, surface)
```
- [ ] **Step 4: The volume strings, the scenario totals and the Volumes group**

Replace the whole file — it adds the volume strings and `cubic_metres` after `REPROJECT_UNAVAILABLE`:

**File:** `terrain_scenarios/gui/help_texts.py`
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

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Scenarios never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Scenarios session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Scenarios layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."


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

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Scenarios cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float) -> str:
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
```
Replace the whole file — it adds `from ..core.volumes import total_cut_fill` and `totals()` just before `export_dem`:

**File:** `terrain_scenarios/gui/controller.py`
```python
"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import os
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
from ..core.volumes import total_cut_fill
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from .help_texts import (DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER, NO_FEATURES_SELECTED, NO_SESSION,
                         RESULT_LAYER_REMOVED, SESSION_ENDED_DEM_REMOVED, TOOL_LABELS)

LOG_TAG = "Terrain Scenarios"


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
        try:
            files = WorkingFiles(tempfile.mkdtemp(prefix="terrain_scenarios_"), grid, info)
        except (OSError, RuntimeError, MemoryError) as error:
            raise DemError(f"Terrain Scenarios could not create its working files: {error}") from error
        self.close()
        self.stack = FeatureStack(grid)
        self.info = info
        self.files = files
        try:
            self.layers = SketchLayers(self.project, layer, self.files.working_path, self.files.change_path)
        except Exception as error:  # noqa: BLE001 — never leave a half-built session behind
            self._drop_session()
            raise DemError(f"Terrain Scenarios could not create its layers: {error}") from error
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
        """(cut, fill) for the whole scenario, in cubic metres."""
        if not self.has_dem:
            return (0.0, 0.0)
        return total_cut_fill(self.stack.original, self.stack.working)

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

    def _set(self, features) -> None:
        features = list(features)
        try:
            window = self.stack.update(features)
        except Exception:  # noqa: BLE001 — never let an engine error take QGIS down or desync the feature list
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Scenarios could not update the terrain; "
                                                          "see the 'Terrain Scenarios' log tab for details.")
            self.featuresChanged.emit()
            return
        self._features = features
        try:
            if window is not None:
                self.files.write(window, self.stack.working)
                self.layers.refresh()
            self.layers.set_outlines(self._outline_items())
        except Exception:  # noqa: BLE001 — never let a file/layer error take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Scenarios could not update the terrain; "
                                                          "see the 'Terrain Scenarios' log tab for details.")
        self.featuresChanged.emit()

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
        self.cancel_preview()  # a queued frame must not fire against a session that is gone
        had_session = self.stack is not None
        self.stack = self.info = self.files = self.layers = None
        self.dem_layer_id = None
        self.dem_crs = QgsCoordinateReferenceSystem()
        self._features = []
        if had_session:
            self.sessionChanged.emit()
            self.featuresChanged.emit()

    def _on_layers_removed(self, items) -> None:
        if self._closing or self.stack is None:
            return
        ids = {item if isinstance(item, str) else item.id() for item in items}
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)
```
Replace the whole file — the Volumes group sits between the form and the problems label, `show_feature` refreshes **both** problems and volumes, and `featuresChanged` refreshes volumes too:

**File:** `terrain_scenarios/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

from qgis.gui import QgsCollapsibleGroupBox, QgsDoubleSpinBox
from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode, reports_storage
from . import illustrations
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
        self.about.setObjectName("TerrainScenariosAboutTool")  # QgsCollapsibleGroupBox saves state by name
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
        self.volumes.setObjectName("TerrainScenariosVolumes")
        self.fill_value = QLabel()
        self.fill_value.setToolTip(VOLUME_FILL_TIP)
        self.cut_value = QLabel()
        self.cut_value.setToolTip(VOLUME_CUT_TIP)
        self.storage_value = QLabel()
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
            self.title.setText(f"{feature.name} · {TOOL_LABELS[feature.tool]}")
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
        totals. Storage is hidden rather than shown as zero for a tool that cannot hold water."""
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

    def _changed(self, field: str, value) -> None:
        if self._fid is not None and not self._loading:
            self.controller.update_feature(self._fid, **{field: value})

    def _refresh_problems(self) -> None:
        if self._fid not in {f.id for f in self.controller.features}:
            self._fid = None
            return
        flags = self.controller.stats(self._fid).flags
        self.problems.setText("\n".join(FLAG_TEXTS[flag] for flag in flags))
        self.problems.setVisible(bool(flags))
```
- [ ] **Step 5: Run the tests**

Run: `scripts/test.sh tests/qgis/test_volumes_panel.py` → Expected: `20 passed`
Run: `scripts/test.sh` → Expected: `294 passed`

- [ ] **Step 6: Commit**

```bash
git add terrain_scenarios/core/tools.py terrain_scenarios/core/operations.py terrain_scenarios/gui/help_texts.py terrain_scenarios/gui/controller.py terrain_scenarios/gui/properties_page.py tests/qgis/test_volumes_panel.py
git commit -m "feat(gui): fill, cut and storage for the selected feature, and scenario totals"
```

---

### Task 2: The scenario file

**Files:**
- Create: `terrain_scenarios/qgis_io/scenario.py`
- Test: `tests/qgis/test_scenario_file.py`

**Interfaces:**
- Consumes: `TerrainFeature` (`model.feature`), `Tool`, `Mode`, `PixelMode` (`core.tools`); a session's `info` (`.path`, `.crs_wkt`) and `stack.original` (`DemGrid`: `.geotransform`, `.cols`, `.rows`).
- Produces: `ScenarioError(Exception)`; frozen `ScenarioMeta(dem_source, dem_crs, dem_extent, dem_size, dem_pixel_size, plugin_version, created, modified)` with `differences(other) -> list[str]` ("coordinate system", "size in pixels", "pixel size", "extent"); `dem_meta(info, grid, version="", created="") -> ScenarioMeta` (never raises); `save(path, features, meta, crs_wkt="") -> ScenarioMeta` (the metadata as written); `load(path) -> (list[TerrainFeature], ScenarioMeta)`; `load_meta(path) -> ScenarioMeta`. Every failure of `save`, `load` and `load_meta` is a `ScenarioError`.

- [ ] **Step 1: Write the failing test**

**File:** `tests/qgis/test_scenario_file.py`
```python
"""The scenario GeoPackage on its own: what goes into the file and what comes back out."""
import os
from unittest import mock

import pytest
from osgeo import ogr
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, square, start_session
from terrain_scenarios.core.tools import Mode, PixelMode, Tool
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.qgis_io import scenario
from terrain_scenarios.qgis_io.scenario import (FEATURES_LAYER, META_TABLE, ScenarioError, ScenarioMeta,
                                             dem_meta, load, load_meta, save)

# A projected CRS with no EPSG code, like a local survey grid. GDAL cannot identify it.
LOCAL_GRID = ('PROJCS["Local survey grid",GEOGCS["ETRS89",DATUM["ETRS89",SPHEROID["GRS 1980",6378137,'
              '298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
              'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
              'PARAMETER["central_meridian",9.5],PARAMETER["scale_factor",0.9996],'
              'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]]')


def two_features(c):
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    c.update_feature(dike.id, amount=1.8, width=4.5, slope_n=2.5, reach=12.0,
                     cross_right=((3.0, -0.6),), long_profile=((0.0, 12.0), (29.0, 13.0)))
    c.update_feature(pond.id, pixel_mode=PixelMode.ALL_TOUCHED, slopes_inside=True, enabled=False)
    return c.features


def test_a_scenario_round_trips_every_field(tmp_path):
    c = start_session(tmp_path)
    saved = two_features(c)
    path = str(tmp_path / "scenario.gpkg")
    save(path, saved, dem_meta(c.info, c.stack.original))
    loaded, _meta = load(path)
    assert len(loaded) == len(saved)
    for before, after in zip(saved, loaded):
        assert after.name == before.name and after.tool is before.tool
        assert after.mode is before.mode and after.enabled == before.enabled
        assert after.pixel_mode is before.pixel_mode
        assert after.amount == before.amount and after.width == before.width
        assert after.slope_n == before.slope_n and after.reach == before.reach
        assert after.slopes_inside == before.slopes_inside
        assert after.cross_left == before.cross_left and after.cross_right == before.cross_right
        assert after.long_profile == before.long_profile
        assert after.geometry_wkb == before.geometry_wkb


def test_the_saved_order_is_the_order_that_comes_back(tmp_path):
    c = start_session(tmp_path)
    saved = two_features(c)
    path = str(tmp_path / "order.gpkg")
    save(path, saved, dem_meta(c.info, c.stack.original))
    assert [f.name for f in load(path)[0]] == [f.name for f in saved]


def test_the_file_is_a_readable_geopackage_with_the_documented_layer(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "plain.gpkg")
    save(path, two_features(c), dem_meta(c.info, c.stack.original))
    source = ogr.Open(path)                      # opened as a plain GeoPackage, no plugin involved
    assert source.GetLayerByName(FEATURES_LAYER) is not None
    layer = source.GetLayerByName(FEATURES_LAYER)
    names = {layer.GetLayerDefn().GetFieldDefn(i).GetName()
             for i in range(layer.GetLayerDefn().GetFieldCount())}
    assert {"order", "name", "tool", "mode", "enabled", "pixel_mode", "params",
            "cross_profile", "long_profile", "section_line"} <= names
    assert layer.GetFeatureCount() == 2
    assert layer.GetNextFeature().GetGeometryRef() is not None    # real geometry, not a blob
    rows = source.ExecuteSQL(f'SELECT key, value FROM "{META_TABLE}"')
    keys = {row.GetField("key") for row in rows}
    source.ReleaseResultSet(rows)
    assert keys == {"plugin_version", "dem_source", "dem_crs", "dem_extent", "dem_size",
                    "dem_pixel_size", "created", "modified"}           # spec §8.4, exactly


def test_the_metadata_records_the_dem_it_was_built_on(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "meta.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original, version="9.9"))
    _features, meta = load(path)
    assert meta.dem_size == f"{c.stack.original.cols}x{c.stack.original.rows}"
    assert meta.dem_crs.startswith("EPSG:") and meta.plugin_version == "9.9"
    assert meta.created and meta.modified


def test_a_different_dem_is_reported_as_specific_differences():
    same = ScenarioMeta(dem_crs="EPSG:25832", dem_size="40x40", dem_pixel_size="1.0,1.0")
    assert same.differences(same) == []
    other = ScenarioMeta(dem_crs="EPSG:4326", dem_size="80x80", dem_pixel_size="1.0,1.0")
    assert set(same.differences(other)) == {"coordinate system", "size in pixels"}


def test_metadata_a_file_does_not_carry_is_not_reported_as_a_difference():
    known = ScenarioMeta(dem_crs="EPSG:25832", dem_size="40x40")
    assert known.differences(ScenarioMeta()) == []      # an older file with no metadata


def test_opening_something_that_is_not_a_scenario_is_reported(tmp_path):
    plain = tmp_path / "notes.txt"
    plain.write_text("not a geopackage")
    with pytest.raises(ScenarioError):
        load(str(plain))


def test_opening_something_that_is_not_a_scenario_is_reported_before_loading(tmp_path):
    path = tmp_path / "notes.gpkg"
    path.write_text("not a geopackage")
    with pytest.raises(ScenarioError):
        load_meta(str(path))


def test_saving_where_it_cannot_be_written_is_reported(tmp_path):
    c = start_session(tmp_path)
    with pytest.raises(ScenarioError):
        save(str(tmp_path / "no-such-dir" / "x.gpkg"), c.features, dem_meta(c.info, c.stack.original))


def test_a_geopackage_without_the_features_layer_is_not_taken_for_a_scenario(tmp_path):
    path = str(tmp_path / "other.gpkg")
    source = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    source.CreateLayer("roads", None, ogr.wkbLineString)
    source.Close()
    with pytest.raises(ScenarioError, match="not a Terrain Scenarios scenario"):
        load(path)
    with pytest.raises(ScenarioError, match="not a Terrain Scenarios scenario"):
        load_meta(path)


def test_a_save_that_fails_half_way_leaves_the_previous_file_readable(tmp_path):
    c = start_session(tmp_path)
    features = two_features(c)
    path = str(tmp_path / "precious.gpkg")
    save(path, features, dem_meta(c.info, c.stack.original))
    one_more = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 5, 34, 5), UTM)

    with mock.patch.object(scenario, "_write_meta", side_effect=RuntimeError("disk full")):
        with pytest.raises(ScenarioError):
            save(path, c.features, dem_meta(c.info, c.stack.original))
    assert len(c.features) == 3 and one_more is not None
    assert len(load(path)[0]) == 2                                  # the last good save survives
    assert not [n for n in os.listdir(tmp_path) if ".saving-" in n]  # and nothing half-written is left


def test_saving_returns_the_dates_it_wrote(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "dates.gpkg")
    first = save(path, two_features(c), dem_meta(c.info, c.stack.original))
    assert first.created and first.modified and load_meta(path) == first
    again = save(path, c.features, dem_meta(c.info, c.stack.original, created="2020-01-01T00:00:00+00:00"))
    assert again.created == "2020-01-01T00:00:00+00:00"            # a known creation date is kept


def test_every_load_gives_the_features_new_ids(tmp_path):
    """Two scenario files both have a first row. Ids taken from the row would let a panel that
    is still showing feature 1 of the old scenario silently edit feature 1 of the new one."""
    c = start_session(tmp_path)
    saved_ids = {f.id for f in two_features(c)}
    path = str(tmp_path / "ids.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    first = {f.id for f in load(path)[0]}
    second = {f.id for f in load(path)[0]}
    assert len(first) == len(second) == 2
    assert not first & second and not first & saved_ids


def test_a_dem_on_a_crs_without_an_epsg_code_is_described_and_written_with_its_crs(tmp_path):
    c = SketchController(QgsProject.instance())
    c.set_dem(dem_layer(tmp_path, crs=LOCAL_GRID))
    meta = dem_meta(c.info, c.stack.original)                     # raised "Unsupported SRS" before
    assert meta.dem_crs == "Local survey grid"
    path = str(tmp_path / "local.gpkg")
    save(path, [], meta, crs_wkt=c.info.crs_wkt)

    source = ogr.Open(path)                        # held: a layer dies with its datasource
    srs = source.GetLayerByName(FEATURES_LAYER).GetSpatialRef()
    assert srs is not None                         # QGIS draws the outlines in the right place
    assert srs.GetName() == "Local survey grid"
    source = None
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_scenario_file.py`
Expected: collection error `ImportError: cannot import name 'scenario' from 'terrain_scenarios.qgis_io'`

- [ ] **Step 3: Write the module**

**File:** `terrain_scenarios/qgis_io/scenario.py`
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

FEATURES_LAYER = "features"
META_TABLE = "terrain_scenarios_meta"
PARAM_FIELDS = ("amount", "width", "slope_n", "reach", "slopes_inside")
FIELDS = (("order", ogr.OFTInteger), ("name", ogr.OFTString), ("tool", ogr.OFTString),
          ("mode", ogr.OFTString), ("enabled", ogr.OFTInteger), ("pixel_mode", ogr.OFTString),
          ("params", ogr.OFTString), ("cross_profile", ogr.OFTString),
          ("long_profile", ogr.OFTString), ("section_line", ogr.OFTString))
# section_line is written as null: no feature carries a custom area section line yet, and the
# field is kept so a file written now still has the documented layout when one does (spec §8.4).


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
        source = driver.CreateDataSource(partial)
        if source is None:
            raise ScenarioError(f"Terrain Scenarios could not create {path}.")
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
        raise ScenarioError(f"Terrain Scenarios could not save the scenario: {error}") from error


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
        raise ScenarioError(f"Terrain Scenarios could not read the scenario: {error}") from error
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
        raise ScenarioError(f"Terrain Scenarios could not read the scenario: {error}") from error
    finally:
        _close(source)


def _open(path: str):
    source = ogr.Open(path)
    if source is None:
        raise ScenarioError(f"Terrain Scenarios could not open {path}.")
    layer = source.GetLayerByName(FEATURES_LAYER)
    if layer is None:
        source.Close()
        raise ScenarioError(f"{path} is not a Terrain Scenarios scenario: it has no '{FEATURES_LAYER}' layer.")
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

Run: `scripts/test.sh tests/qgis/test_scenario_file.py` → Expected: `14 passed`
Run: `scripts/test.sh` → Expected: `308 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/qgis_io/scenario.py tests/qgis/test_scenario_file.py
git commit -m "feat(io): scenario GeoPackage that survives a failed save and any CRS"
```

---

### Task 3: Scenarios in the session

**Files:**
- Modify: `terrain_scenarios/gui/controller.py`, `terrain_scenarios/gui/help_texts.py`
- Test: `tests/qgis/test_scenario_session.py`

**Interfaces:**
- Consumes: Task 2's `scenario` module; Task 1's `totals()`.
- Produces on `SketchController`: `is_dirty` and `scenario_path` (read-only properties); `new_scenario()`; `save_scenario(path)`, `scenario_differences(path) -> list[str]`, `open_scenario(path)` — each raises `ScenarioError` (with `NO_SESSION` when there is no session); `before_discard: Callable[[], None] | None`; module function `plugin_version() -> str`. `_set(features)` now returns `bool`. `help_texts.SCENARIO_NOT_APPLIED`.

- [ ] **Step 1: Write the failing test**

**File:** `tests/qgis/test_scenario_session.py`
```python
"""Scenarios in a session: opening, saving, and never losing work that was not saved."""
import time
from unittest import mock

import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, sample, square, start_session
from terrain_scenarios.core.tools import Mode, PixelMode, Tool
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.gui.help_texts import SCENARIO_NOT_APPLIED
from terrain_scenarios.qgis_io.scenario import ScenarioError, dem_meta, load, load_meta, save

LOCAL_GRID = ('PROJCS["Local survey grid",GEOGCS["ETRS89",DATUM["ETRS89",SPHEROID["GRS 1980",6378137,'
              '298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
              'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
              'PARAMETER["central_meridian",9.5],PARAMETER["scale_factor",0.9996],'
              'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]]')


def two_features(c):
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    c.update_feature(dike.id, amount=1.8, width=4.5, slope_n=2.5, reach=12.0,
                     cross_right=((3.0, -0.6),), long_profile=((0.0, 12.0), (29.0, 13.0)))
    c.update_feature(pond.id, pixel_mode=PixelMode.ALL_TOUCHED, slopes_inside=True, enabled=False)
    return c.features


def test_editing_marks_the_scenario_unsaved_and_saving_or_starting_afresh_clears_it(tmp_path):
    c = start_session(tmp_path)
    assert not c.is_dirty and c.scenario_path is None
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.is_dirty
    path = str(tmp_path / "work.gpkg")
    c.save_scenario(path)
    assert not c.is_dirty and c.scenario_path == path
    c.update_feature(dike.id, name="Sea wall")      # a rename is saved too, so it counts
    assert c.is_dirty
    c.new_scenario()
    assert c.features == () and not c.is_dirty and c.scenario_path is None


def test_scenario_actions_need_a_session():
    c = SketchController(QgsProject.instance())
    for action in (c.save_scenario, c.open_scenario, c.scenario_differences):
        with pytest.raises(ScenarioError):
            action("anything.gpkg")


def test_a_reloaded_scenario_rebuilds_the_same_terrain(tmp_path):
    """The point of saving: reopen on a fresh session and the DEM comes out the same."""
    c = start_session(tmp_path)
    two_features(c)
    path = str(tmp_path / "rebuild.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    on_the_dike = sample(c.layers.working, 20, 20)
    in_the_pond = sample(c.layers.working, 18, 18)
    c.close()

    again = tmp_path / "again"
    again.mkdir()
    fresh = start_session(again)
    assert sample(fresh.layers.working, 20, 20) != pytest.approx(on_the_dike)   # untouched DEM first
    fresh.open_scenario(path)
    assert sample(fresh.layers.working, 20, 20) == pytest.approx(on_the_dike)
    assert sample(fresh.layers.working, 18, 18) == pytest.approx(in_the_pond)
    assert not fresh.is_dirty                  # what is on screen is exactly what is in the file
    assert fresh.scenario_path == path


def test_saving_again_keeps_the_date_the_scenario_was_created(tmp_path):
    c = start_session(tmp_path)
    two_features(c)
    path = str(tmp_path / "dated.gpkg")
    c.save_scenario(path)
    first = load_meta(path)
    time.sleep(1.1)                                                  # timestamps are to the second
    c.update_feature(c.features[0].id, amount=2.2)
    c.save_scenario(path)
    second = load_meta(path)
    assert second.created == first.created
    assert second.modified > first.modified


def test_a_scenario_that_cannot_be_applied_changes_nothing(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    theirs = str(tmp_path / "theirs.gpkg")
    c.save_scenario(theirs)
    mine = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    before = c.features

    with mock.patch.object(c.stack, "update", side_effect=RuntimeError("engine refused")):
        with pytest.raises(ScenarioError, match=SCENARIO_NOT_APPLIED):
            c.open_scenario(theirs)
    assert c.features == before and c.find(mine.id) is not None
    assert c.is_dirty                              # the unsaved pond is still unsaved
    assert c.scenario_path == theirs               # still the file these features came from


def test_starting_on_another_dem_forgets_the_scenario_file(tmp_path):
    """Otherwise the next Save writes the new, empty session over the scenario just left."""
    c = start_session(tmp_path)
    two_features(c)
    path = str(tmp_path / "left-behind.gpkg")
    c.save_scenario(path)
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    assert c.scenario_path is None and not c.is_dirty
    assert len(load(path)[0]) == 2


def test_a_dem_on_a_crs_without_an_epsg_code_can_be_saved_and_reopened(tmp_path):
    c = SketchController(QgsProject.instance())
    c.set_dem(dem_layer(tmp_path, crs=LOCAL_GRID))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), c.dem_crs)
    path = str(tmp_path / "local.gpkg")
    c.save_scenario(path)                          # raised "Unsupported SRS" from a Qt slot before
    assert c.scenario_differences(path) == []
    c.open_scenario(path)
    assert len(c.features) == 1


def test_a_session_dropped_with_unsaved_changes_asks_first_and_survives_a_failing_hook(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    c.before_discard = lambda: asked.append(len(c.features)) or 1 / 0
    QgsProject.instance().clear()                  # raises inside a Qt signal if unguarded
    assert asked == [1]                            # asked while the features still existed
    assert not c.has_dem


def test_a_session_without_changes_is_dropped_without_asking(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "clean.gpkg"))
    asked = []
    c.before_discard = lambda: asked.append(True)  # recorded, not pytest.fail: that would escape a Qt slot
    QgsProject.instance().clear()
    assert not c.has_dem and asked == []
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_scenario_session.py`
Expected: collection error `ImportError: cannot import name 'SCENARIO_NOT_APPLIED' from 'terrain_scenarios.gui.help_texts'`

- [ ] **Step 3: The message**

Replace the whole file — it adds `SCENARIO_NOT_APPLIED` at the end:

**File:** `terrain_scenarios/gui/help_texts.py`
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

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Scenarios never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Scenarios session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Scenarios layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."


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

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Scenarios cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float) -> str:
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


SCENARIO_NOT_APPLIED = ("The scenario could not be applied to this DEM, so it was not opened. "
                        "Your current features are unchanged.")
```
- [ ] **Step 4: Scenario state in the controller**

Replace the whole file. Read `_drop_session` closely: it offers to save **before** anything is dropped, and forgets the scenario file so the next Save cannot write a new session over it. `open_scenario` commits the path, dates and saved state only after `_set` succeeded.

**File:** `terrain_scenarios/gui/controller.py`
```python
"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import configparser
import os
import pathlib
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
from ..core.volumes import total_cut_fill
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io import scenario
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from ..qgis_io.scenario import ScenarioError
from .help_texts import (DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER, NO_FEATURES_SELECTED, NO_SESSION,
                         RESULT_LAYER_REMOVED, SCENARIO_NOT_APPLIED, SESSION_ENDED_DEM_REMOVED, TOOL_LABELS)

LOG_TAG = "Terrain Scenarios"


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
        try:
            files = WorkingFiles(tempfile.mkdtemp(prefix="terrain_scenarios_"), grid, info)
        except (OSError, RuntimeError, MemoryError) as error:
            raise DemError(f"Terrain Scenarios could not create its working files: {error}") from error
        self.close()
        self.stack = FeatureStack(grid)
        self.info = info
        self.files = files
        try:
            self.layers = SketchLayers(self.project, layer, self.files.working_path, self.files.change_path)
        except Exception as error:  # noqa: BLE001 — never leave a half-built session behind
            self._drop_session()
            raise DemError(f"Terrain Scenarios could not create its layers: {error}") from error
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
        """(cut, fill) for the whole scenario, in cubic metres."""
        if not self.has_dem:
            return (0.0, 0.0)
        return total_cut_fill(self.stack.original, self.stack.working)

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
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Scenarios could not update the terrain; "
                                                          "see the 'Terrain Scenarios' log tab for details.")
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
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Scenarios could not update the terrain; "
                                                          "see the 'Terrain Scenarios' log tab for details.")
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
        self.stack = self.info = self.files = self.layers = None
        self.dem_layer_id = None
        self.dem_crs = QgsCoordinateReferenceSystem()
        self._features = []
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
        if self._closing or self.stack is None:
            return
        ids = {item if isinstance(item, str) else item.id() for item in items}
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)
```
- [ ] **Step 5: Run the tests**

Run: `scripts/test.sh tests/qgis/test_scenario_session.py` → Expected: `9 passed`
Run: `scripts/test.sh` → Expected: `317 passed`

- [ ] **Step 6: Commit**

```bash
git add terrain_scenarios/gui/controller.py terrain_scenarios/gui/help_texts.py tests/qgis/test_scenario_session.py
git commit -m "feat(gui): scenario state in the controller, and no Save that can overwrite the wrong file"
```

---

### Task 4: Scenario actions in the panel

**Files:**
- Modify: `terrain_scenarios/gui/main_dock.py`, `terrain_scenarios/gui/help_texts.py`, `tests/qgis/conftest.py`
- Test: `tests/qgis/test_scenario_panel.py`

**Interfaces:**
- Consumes: Task 3's controller API and `before_discard`; `classFactory` / `TerrainScenariosPlugin.unload()` (unchanged — it already shuts the dock down before the controller, and the dock stays alive until `deleteLater` runs).
- Produces on `MainDock`: `new_scenario_button`, `open_scenario_button`, `save_scenario_button`, `save_as_scenario_button`, `scenario_buttons` (those four); replaceable hooks `ask_save_path() -> str`, `ask_open_path() -> str`, `confirm_save(text, can_cancel=True) -> True | False | None` (save / discard / cancel), alongside the existing `confirm(text) -> bool`. `help_texts`: `UNSAVED_CHANGES`, `SCENARIO_SAVED`, `SCENARIO_REPLACE`, `SCENARIO_OPENED`, `SCENARIO_DEM_DIFFERS` (one `{}` for the joined differences), `UNSAVED_BEFORE_CLOSING`.

- [ ] **Step 1: Keep dialogs from blocking the suite**

From this task on, closing a project with unsaved work asks a question, and conftest closes the project around every test. Replace the whole file:

**File:** `tests/qgis/conftest.py`
```python
"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject, QgsSettings

from terrain_scenarios.gui import settings as plugin_settings

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A real modal dialog in an offscreen run waits forever and hangs the whole suite. Every
    project clear below can legitimately ask to save a panel's unsaved work, so the defaults
    answer the way closing without saving would. A test that is about a prompt replaces the
    panel's own hook (`confirm_save`, `confirm`, `ask_save_path`…) and asserts on that."""
    from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

    def question(_parent, _title, _text, buttons=QMessageBox.StandardButton.Yes, *_rest):
        for answer in (QMessageBox.StandardButton.Discard, QMessageBox.StandardButton.No,
                       QMessageBox.StandardButton.Cancel):
            if buttons & answer:
                return answer
        return QMessageBox.StandardButton.NoButton

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))


@pytest.fixture(autouse=True)
def clean_project(no_modal_dialogs):
    QgsProject.instance().clear()
    _clear_plugin_settings()
    yield
    QgsProject.instance().clear()
    _clear_plugin_settings()


def _clear_plugin_settings() -> None:
    """Drop everything under the plugin's settings group so tests cannot inherit each other's."""
    settings = QgsSettings()
    settings.beginGroup(plugin_settings.GROUP)
    settings.remove("")
    settings.endGroup()
```
- [ ] **Step 2: Write the failing test**

**File:** `tests/qgis/test_scenario_panel.py`
```python
"""The scenario buttons: New, Open, Save and Save as, and every question asked before work is lost."""
import numpy as np
import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_scenarios import classFactory
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.gui.help_texts import (SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                                           UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES)
from terrain_scenarios.gui.main_dock import MainDock
from terrain_scenarios.qgis_io.scenario import dem_meta, load, save


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def test_saving_then_opening_restores_the_features(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    path = str(tmp_path / "panel.gpkg")
    dock.ask_save_path = lambda: path
    dock.save_scenario_button.click()
    assert not c.is_dirty and c.scenario_path == path

    dock.confirm_save = lambda text, can_cancel=True: False           # discard, we already saved
    dock.new_scenario_button.click()
    assert c.features == () and c.scenario_path is None

    dock.ask_open_path = lambda: path
    dock.open_scenario_button.click()
    assert [f.name for f in c.features] == ["Raise path 1", "Lower flat 1"]
    assert not c.is_dirty


def test_a_second_save_does_not_ask_again(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    path = str(tmp_path / "once.gpkg")
    dock.ask_save_path = lambda: asked.append(1) or path
    dock.save_scenario_button.click()
    c.update_feature(c.features[0].id, amount=2.0)
    dock.save_scenario_button.click()
    assert len(asked) == 1                            # the path is remembered


def test_editing_marks_the_scenario_unsaved_and_saving_clears_it(tmp_path):
    _iface, c, dock = panel(tmp_path)
    assert not c.is_dirty
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.is_dirty
    dock.ask_save_path = lambda: str(tmp_path / "dirty.gpkg")
    dock.save_scenario_button.click()
    assert not c.is_dirty
    c.update_feature(dike.id, amount=3.0)
    assert c.is_dirty


def test_discarding_unsaved_work_is_confirmed_first(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or None      # cancel
    dock.new_scenario_button.click()
    assert asked == [UNSAVED_CHANGES]
    assert len(c.features) == 1                        # cancelling kept the work


def test_choosing_save_in_the_prompt_writes_before_discarding(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "prompted.gpkg")
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: path
    dock.new_scenario_button.click()
    assert c.features == ()
    dock.ask_open_path = lambda: path
    dock.open_scenario_button.click()
    assert len(c.features) == 1                        # the work was saved, not lost


def test_backing_out_of_the_save_dialog_keeps_the_work(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: ""                    # the user cancelled the file dialog
    dock.new_scenario_button.click()
    assert len(c.features) == 1


def scenario_from_another_dem(tmp_path, array) -> str:
    """Save a one-feature scenario built on its own DEM of shape `array`, and return the path."""
    room = tmp_path / f"other{array.shape[0]}"
    room.mkdir()
    other = start_session(room, array)
    other.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(room / "other.gpkg")
    save(path, other.features, dem_meta(other.info, other.stack.original))
    return path


def messages(iface) -> list[str]:
    return [call[0][1] for call in iface.messageBar().pushMessage.call_args_list]


def test_a_scenario_from_a_different_dem_is_only_opened_once_the_user_agrees(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 10.0, np.float32))
    _iface, c, dock = panel(tmp_path)
    mine = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.confirm_save = lambda text, can_cancel=True: False       # carry on without saving
    dock.ask_open_path = lambda: path
    questions = []
    dock.confirm = lambda text: questions.append(text) or False   # No: pick another DEM first
    dock.open_scenario_button.click()

    assert questions == [SCENARIO_DEM_DIFFERS.format("size in pixels, extent")]
    assert [f.id for f in c.features] == [mine.id]                # nothing was replaced
    assert c.is_dirty                                             # and it is still unsaved

    dock.confirm = lambda text: True                              # Yes: open it anyway
    dock.open_scenario_button.click()
    assert len(c.features) == 1 and c.features[0].tool is Tool.RAISE_PATH
    assert c.scenario_path == path


def test_a_scenario_from_the_same_dem_opens_without_asking(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((40, 40), 10.0, np.float32))
    iface, c, dock = panel(tmp_path)
    dock.ask_open_path = lambda: path
    questions = []
    dock.confirm = lambda text: questions.append(text) or True
    dock.open_scenario_button.click()

    assert questions == [] and len(c.features) == 1
    assert SCENARIO_OPENED.format(path) in messages(iface)


def test_the_scenario_buttons_wait_for_a_session(tmp_path):
    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    dock = MainDock(iface, c)
    assert not any(button.isEnabled() for button in dock.scenario_buttons)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    assert all(button.isEnabled() for button in dock.scenario_buttons)


def test_save_as_always_asks_and_leaves_the_first_file_as_it_was(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    first, second = str(tmp_path / "first.gpkg"), str(tmp_path / "second.gpkg")
    dock.ask_save_path = lambda: first
    dock.save_scenario_button.click()
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)

    dock.ask_save_path = lambda: second
    dock.save_as_scenario_button.click()
    assert c.scenario_path == second
    assert len(load(first)[0]) == 1 and len(load(second)[0]) == 2


def test_closing_the_project_offers_to_save_unsaved_work(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "rescued.gpkg")
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append((text, can_cancel)) or True
    dock.ask_save_path = lambda: path
    QgsProject.instance().clear()

    assert asked == [(UNSAVED_BEFORE_CLOSING, False)]   # a closing project cannot be cancelled
    assert len(load(path)[0]) == 1


def test_removing_the_dem_offers_to_save_before_the_session_ends(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "dem-gone.gpkg")
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: path
    QgsProject.instance().removeMapLayer(c.dem_layer_id)
    assert not c.has_dem
    assert len(load(path)[0]) == 1


def test_unloading_the_plugin_offers_to_save_unsaved_work(tmp_path):
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    dock, c = plugin.dock, plugin.controller
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "unloaded.gpkg")
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or True
    dock.ask_save_path = lambda: path
    plugin.unload()

    assert asked == [UNSAVED_BEFORE_CLOSING]
    assert len(load(path)[0]) == 1


def test_starting_on_another_dem_asks_about_unsaved_work_once(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or False   # discard
    (tmp_path / "next").mkdir()
    dock.dem_combo.setLayer(dem_layer(tmp_path / "next", name="next"))
    dock.start_button.click()

    assert asked == [UNSAVED_CHANGES]              # not a second time as the old session closes
    assert c.has_dem and c.features == ()


def test_cancelling_the_question_keeps_the_session(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    old_dem = c.dem_layer_id
    dock.confirm_save = lambda text, can_cancel=True: None
    (tmp_path / "next").mkdir()
    dock.dem_combo.setLayer(dem_layer(tmp_path / "next", name="next"))
    dock.start_button.click()
    assert c.dem_layer_id == old_dem and len(c.features) == 1


def test_a_start_that_fails_leaves_the_work_unsaved_and_still_protected(tmp_path):
    iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.confirm_save = lambda text, can_cancel=True: False                  # discard…
    (tmp_path / "geo").mkdir()
    dock.dem_combo.setLayer(dem_layer(tmp_path / "geo", name="geo", crs="EPSG:4326"))
    dock.start_button.click()                                               # …but Start is refused
    assert len(c.features) == 1 and c.is_dirty

    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or False
    QgsProject.instance().clear()
    assert asked == [UNSAVED_BEFORE_CLOSING]        # the refused Start did not switch protection off


def test_opening_a_scenario_ends_an_edit_in_progress(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "edit.gpkg")
    c.save_scenario(path)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.ask_open_path = lambda: path
    dock.open_scenario_button.click()
    assert dock.edit_tool is None                  # its feature is gone; editing on would rewrite another


def test_every_scenario_button_shows_an_icon_and_says_what_it_does(tmp_path):
    """getThemeIcon hands back a null icon for a name it does not know, and an icon-only button
    then renders as blank space — so check the real buttons, not a list of names."""
    _iface, _c, dock = panel(tmp_path)
    for button in (*dock.scenario_buttons, dock.export_button):
        assert not button.icon().isNull(), button.text()
    for button in dock.scenario_buttons:
        assert button.toolTip().startswith(button.text() + "\n"), button.text()
    icons = [button.icon().cacheKey() for button in (dock.save_as_scenario_button, dock.export_button)]
    assert icons[0] != icons[1]                    # Save as… and Export DEM… no longer look the same


@pytest.mark.parametrize("typed, replaced", [("flood", True), ("flood.gpkg", False)])
def test_a_name_typed_without_gpkg_asks_before_replacing_that_scenario(tmp_path, monkeypatch, typed, replaced):
    """The file dialog checks for overwriting before `.gpkg` is added, so an existing flood.gpkg
    would be replaced silently when the user types just `flood`. A name typed with the extension
    has already been through the dialog's own question."""
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, _c, dock = panel(tmp_path)
    (tmp_path / "flood.gpkg").write_bytes(b"an earlier scenario")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / typed), "")))
    questions = []
    dock.confirm = lambda text: questions.append(text) or False     # No: keep the old file

    assert dock._save_dialog() == ("" if replaced else str(tmp_path / "flood.gpkg"))
    assert questions == ([SCENARIO_REPLACE.format("flood.gpkg")] if replaced else [])

    dock.confirm = lambda text: True
    assert dock._save_dialog() == str(tmp_path / "flood.gpkg")
```
- [ ] **Step 3: Run it to see it fail**

Run: `scripts/test.sh tests/qgis/test_scenario_panel.py`
Expected: collection error `ImportError: cannot import name 'SCENARIO_DEM_DIFFERS' from 'terrain_scenarios.gui.help_texts'`

- [ ] **Step 4: The strings**

Replace the whole file — the scenario strings go between `cubic_metres` and `SCENARIO_NOT_APPLIED`:

**File:** `terrain_scenarios/gui/help_texts.py`
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

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Scenarios never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Scenarios session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Scenarios layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."


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

REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Scenarios cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")


VOLUME_FILL_TIP = "Material added: the volume between the original ground and the new surface."
VOLUME_CUT_TIP = "Material removed: the volume between the new surface and the original ground."
VOLUME_STORAGE_TIP = ("Roughly how much water this hollow holds before it spills at its lowest "
                      "rim point. Static: it ignores inflow, outflow and any pipe.")
VOLUME_STORAGE_NOTE = "below the lowest rim point (static, no inflow routing)"
NO_VOLUME_YET = "—"
SCENARIO_TOTALS = "{fill} fill · {cut} cut"


def cubic_metres(value: float) -> str:
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
UNSAVED_BEFORE_CLOSING = ("Terrain Scenarios is closing this scenario, and it has changes that are not "
                          "saved. Save them now?")
```
- [ ] **Step 5: The panel**

Replace the whole file. Start now asks through `_keep_unsaved_work` instead of the old "Start again on this DEM?" question, so a saved scenario is left without a prompt and an unsaved one can be saved first.

**File:** `terrain_scenarios/gui/main_dock.py`
```python
"""The Terrain Scenarios panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

import os

from qgis.core import Qgis, QgsApplication, QgsCoordinateTransform, QgsGeometry, QgsProject
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                         SCENARIO_SAVED, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES)
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
        self.setWindowTitle(self.tr("Terrain Scenarios"))
        self.setObjectName("TerrainScenariosDock")
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
        start_label = QLabel(self.tr("Pick a DEM above and press Start. Terrain Scenarios works on a copy; your DEM "
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
            initial = self._to_canvas(self.controller.feature_geometry(self._brush_fid)) if self._brush_fid else None
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
        self.edit_tool = VertexEditTool(canvas, self._to_canvas(self.controller.feature_geometry(fid)))
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
        so the question is only Save or Discard."""
        if self._asked_about_unsaved:
            return
        if self.confirm_save(UNSAVED_BEFORE_CLOSING, can_cancel=False):
            self._save_scenario()

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
        canvas = self.iface.mapCanvas()
        transform = QgsCoordinateTransform(self.controller.dem_crs, canvas.mapSettings().destinationCrs(),
                                           QgsProject.instance())
        extent = transform.transformBoundingBox(self.controller.feature_geometry(fid).boundingBox())
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
            widget = bar.createMessage(self.tr("Terrain Scenarios"), text)
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
        self.iface.messageBar().pushMessage(self.tr("Terrain Scenarios"), text, level, 8)

    def _confirm_dialog(self, text: str) -> bool:
        return QMessageBox.question(self, self.tr("Terrain Scenarios"), text) == QMessageBox.StandardButton.Yes

    def _save_dialog(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Save scenario"), "",
                                              self.tr("Terrain Scenarios scenario (*.gpkg)"))
        if path and not path.lower().endswith(".gpkg"):
            path += ".gpkg"
            # The dialog's own overwrite check ran on the name as typed, before the extension was
            # added, so replacing an existing scenario would otherwise happen without a question.
            if os.path.exists(path) and not self.confirm(SCENARIO_REPLACE.format(os.path.basename(path))):
                return ""
        return path

    def _open_dialog(self) -> str:
        path, _ = QFileDialog.getOpenFileName(self, self.tr("Open scenario"), "",
                                              self.tr("Terrain Scenarios scenario (*.gpkg)"))
        return path

    def _save_question(self, text: str, can_cancel: bool = True):
        """True to save, False to discard, None to cancel (only offered when `can_cancel`)."""
        buttons = QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
        if can_cancel:
            buttons |= QMessageBox.StandardButton.Cancel
        answer = QMessageBox.question(self, self.tr("Terrain Scenarios"), text, buttons)
        if answer == QMessageBox.StandardButton.Cancel:
            return None
        return answer == QMessageBox.StandardButton.Save

    def _export_dialog(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export modified DEM"), "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
        return path
```
- [ ] **Step 6: Run the tests**

Run: `scripts/test.sh tests/qgis/test_scenario_panel.py` → Expected: `20 passed`
Run: `scripts/test.sh` → Expected: `337 passed`

- [ ] **Step 7: Commit**

```bash
git add terrain_scenarios/gui/main_dock.py terrain_scenarios/gui/help_texts.py tests/qgis/conftest.py tests/qgis/test_scenario_panel.py
git commit -m "feat(gui): New, Open, Save and Save as, with a question wherever work could be lost"
```

---

### Task 5: The installable ZIP

**Files:**
- Create: `scripts/build_zip.sh`
- Test: `tests/core/test_build_zip.py`

**Interfaces:**
- Consumes: `terrain_scenarios/metadata.txt` (`version=` under `[general]`).
- Produces: `scripts/build_zip.sh [output-directory]` → prints the path of `terrain_scenarios-<version>.zip`; exits non-zero, naming the problem on stderr, when `metadata.txt`, its `version=` or `__init__.py` is missing.

- [ ] **Step 1: Write the failing test**

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
    parser.read(ROOT / "terrain_scenarios" / "metadata.txt")
    assert path.name == f"terrain_scenarios-{parser.get('general', 'version')}.zip"


def test_everything_sits_under_one_folder_qgis_can_install(built):
    _path, names = built
    assert names, "the archive is empty"
    assert all(name.startswith("terrain_scenarios/") for name in names), \
        [n for n in names if not n.startswith("terrain_scenarios/")]
    assert "terrain_scenarios/metadata.txt" in names
    assert "terrain_scenarios/__init__.py" in names


def test_the_plugin_ships_what_it_needs_at_runtime(built):
    _path, names = built
    for needed in ("terrain_scenarios/plugin.py", "terrain_scenarios/gui/main_dock.py",
                   "terrain_scenarios/core/engine.py", "terrain_scenarios/qgis_io/scenario.py"):
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
    (fake / "terrain_scenarios").mkdir(parents=True)
    (fake / "scripts").mkdir()
    script = fake / "scripts" / "build_zip.sh"
    script.write_bytes(SCRIPT.read_bytes())
    script.chmod(0o755)
    if metadata is not None:
        (fake / "terrain_scenarios" / "metadata.txt").write_text(metadata)
    if init:
        (fake / "terrain_scenarios" / "__init__.py").write_text("")
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
    `terrain_scenarios-.zip` that every later build silently overwrites."""
    script = fake_repo(tmp_path, metadata="[general]\nname=Terrain Scenarios\n")
    result = subprocess.run([str(script), str(tmp_path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "no version=" in result.stderr
    assert not list(tmp_path.glob("*.zip"))
```
- [ ] **Step 2: Run it to see it fail**

Run: `scripts/test.sh tests/core/test_build_zip.py`
Expected: FAIL (3 failed, 4 errors) with `FileNotFoundError: [Errno 2] No such file or directory`

- [ ] **Step 3: Write the script**

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
OUT_DIR="${1:-$ROOT}"
PACKAGE="terrain_scenarios"

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
    . | tar -x -C "$STAGE/$PACKAGE"

# __init__.py is what makes QGIS able to import the plugin at all. Checked on the staging copy,
# which also catches a tar that produced nothing.
test -f "$STAGE/$PACKAGE/__init__.py"  || { echo "build_zip.sh: __init__.py missing" >&2; exit 1; }
test -f "$STAGE/$PACKAGE/metadata.txt" || { echo "build_zip.sh: staging copy is incomplete" >&2; exit 1; }

rm -f "$ZIP"
(cd "$STAGE" && zip -q -r "$ZIP" "$PACKAGE")
echo "$ZIP"
```
Run: `chmod +x scripts/build_zip.sh`

- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/core/test_build_zip.py` → Expected: `7 passed`
Run: `scripts/test.sh` → Expected: `344 passed`

- [ ] **Step 5: Commit**

```bash
git add scripts/build_zip.sh tests/core/test_build_zip.py
git commit -m "build: scripts/build_zip.sh makes the Install-from-ZIP package"
```

---

## Manual check in QGIS (for the human, after merge)

The suite cannot see these; they need a real QGIS window.

1. `scripts/dev_install.sh`, restart QGIS 4, load a projected DEM, open Terrain Scenarios and press **Start**.
2. Draw a **Lower flat** pond and select it. The *Volumes* group should show Cut, a Storage line starting with `≈`, and the whole-scenario line. Draw a **Raise path** dike: its Storage row should disappear.
3. Hover the four icon buttons next to the DEM picker: each tooltip should name the action. Save, type a name **without** `.gpkg`, then Save as… with the same name again: you should be asked before it is replaced.
4. Open the saved `.gpkg` with *Layer ▸ Add Layer ▸ Add Vector Layer*: the outlines should sit on the DEM. Remove that layer again before continuing (see the Plan 7 note on Windows).
5. Change a feature, then **File ▸ New Project**. Terrain Scenarios should ask Save / Discard **before** the project closes — check that QGIS's own "save project?" question and this one do not fight, and that nothing hangs.
6. Change a feature, then remove the DEM layer from the Layers panel: you should be asked to save first.
7. Load a second DEM of a different size, **Start** on it, and **Open** the scenario from step 3: you should be told it was made on a different DEM, and No should leave the (empty) session as it was.
8. `scripts/build_zip.sh /tmp`, then *Plugins ▸ Manage and Install Plugins ▸ Install from ZIP* in a clean profile: the plugin should install and start.

## Deferred to Plan 7

| Item | Why not here |
|---|---|
| **`_zoom_to` can raise `QgsCsException` inside the context-menu slot** | A crash path, deferred since Plan 2. Out of this plan's task boundaries; take it first. |
| Undo/redo (`QUndoStack`) and the 3D view (spec §8.5) | The rest of milestone 6. Undo touches every controller mutation. |
| Working GeoTIFFs in `<scenario>_files/` once saved (spec §8.2 step 3) | A scenario reopens by recomputing, so this only matters for a saved QGIS project pointing at the session's temp files. Moving files that live layers read is its own piece of work. |
| Temp folders are never removed | Each Start writes a DEM-sized working and change GeoTIFF into a new temp folder (Plan 2 deferral, still open). |
| Export DEM appends `.tif` after the dialog's overwrite check | The same flaw this plan fixed for scenarios; same fix. |
| Replacing a scenario that is open as a QGIS layer, on Windows | `os.replace` fails there and the user gets a message; on macOS and Linux it succeeds. |
| Open picking the DEM from the scenario's `dem_source` | Today the user starts on the right DEM first; the mismatch question says so. |
| An edit that changes nothing still marks the scenario unsaved | Fails safe: at worst one question too many. |
| From Plan 2: Duplicate/Rename in the list's context menu (spec §7.2); the Properties title not following a rename; the export "add to project" option and integer-DEM note; cleanup of a partially built layer group; `FeatureListModel.data()` rebuilding a dict per call | Still open. |
| From Plan 5: the pixel-mode picture in the combobox tooltip; tool-specific H/D labels; dock geometry under `terrain_scenarios/`; `QgsCollapsibleGroupBox` state; illustration polish | See the Plan 5 addendum. |
| From Plans 3-4: `reach` rounding to 0.0 on a hard terminus drag; the arrow-key nudge committing per keypress; the unreachable left side of a cross profile; the real area section line; the end-cap asymmetry | See those addenda. |

## Addendum: final-review fixes (2026-09-14)

The five tasks landed byte-identical to the blocks above, each approved by its task review. The final whole-branch review then found no Critical issues but eight Important ones, all in this plan's own text rather than in the transcription. They were fixed in one wave (71e11c7..62a5600). A residual crash path introduced by that wave was fixed on the user's decision (6f970c6). **Where the code on `main` differs from the task blocks above, the code and its tests are authoritative.** 366 tests.

| # | What changed | Why |
|---|---|---|
| I1 | The closing question (project clear, DEM removal, unload) repeats until a save succeeds or the user chooses Discard | Choosing Save and then cancelling the file dialog, or a save that failed, dropped the session silently. |
| I2 | `build_zip.sh` resolves the output directory to an absolute path before staging, and also excludes `*~`, `*.swp`, `.pytest_cache` | `scripts/build_zip.sh .` printed a ZIP path and exited 0, but the ZIP had been written inside the staging folder the trap deletes. |
| I3 | `FeatureStack` keeps running cut/fill totals, adjusted over the changed window in `update()`; `SketchController.totals()` returns them; `_refresh_volumes` is guarded | `totals()` scanned the whole DEM on every commit (0.11 s at 10 M px, 0.70 s and about 1.5 GB of temporary arrays at 50 M px), from an unguarded slot. |
| I4 | Fill, cut and storage labels word-wrap | The storage text pushed the page from 215 px to 481 px wide whenever a pond was selected. |
| I5 | The dock leaves the Properties page when the feature it shows no longer exists | After Delete, the page kept showing the deleted feature with stale totals. |
| I6 | The "failed open changes nothing" test saves to `mine` and opens `theirs` | As written, it could not detect a path retargeted to the file that failed to open. |
| I7 | `save()` refuses when `<target>-wal` or `-shm` exists | Replacing a GeoPackage another program holds open in WAL mode can pair the new file with a stale WAL, which SQLite documents as a corruption path. |
| I8 | `save()` refuses to replace an existing file that is not a Terrain Scenarios scenario (no `terrain_scenarios_meta` table) | Save could replace a GeoPackage holding the DEM or other layers, destroying every layer in it. |
| R | The replace check runs inside `save()`'s `try` | A GDAL error while checking (e.g. "database is locked") escaped the Save slot and aborted QGIS; the fix wave's own test reproduced the abort. |
| — | Smaller: the second-save test checks what was written; a no-op assertion was removed; the Save/Open dialogs start in the scenario's folder or the project home; a test docstring now matches its one-directional check; the two new refusal messages live in `scenario.py`, since `qgis_io` may not import `gui` | Each confirmed by review. |

### Additions to the manual check
9. Change a feature, **File ▸ New Project**, choose Save, then cancel the file dialog. The question should come back; Discard should let the project close.
10. Quit QGIS (Cmd+Q) with unsaved work. Terrain Scenarios should ask after QGIS's own save-project question, and nothing should hang.
11. Close or float the Terrain Scenarios panel, then close the project. The question should still appear in a sensible place.
12. Disable the plugin with unsaved work. The question appears after both panels have gone; check that this is understandable.
13. Remove the DEM with a never-saved scenario and choose Save. The file dialog opens while QGIS is still removing the layer; check that it behaves.
14. Save a scenario while its `.gpkg` is loaded as a layer. Expect a refusal asking you to remove the layer first.
15. Select a pond. The dock should not get wider than with a dike selected.

### Deferred to Plan 7 (in addition to the table above)
| Item | Why not here |
|---|---|
| Saving right after opening a scenario made on a different DEM rewrites its metadata with this DEM's | A decision (Save as first? keep the session dirty?), not a defect. |
| Tests never disconnect `SketchController` from the `QgsProject` singleton | Controllers accumulate across the run. It forced one extra stub reset now that the closing question repeats. |
| `_check_replaceable` is check-then-replace | Another program could open the file between the check and `os.replace`; accepted as ruled. |
| Deferred minors: `cubic_metres` hint should be `float \| None`; `scenario.py` relies on siblings calling `ogr.UseExceptions()`; `load`/`load_meta` repeat one skeleton; `differences()` tested for 2 of 4 labels; no save prompt after deleting every feature of a saved scenario; a `_mark_scenario` helper; `created` kept by string path comparison; no `command -v zip` check | Triaged by the final review as Plan 7. |
