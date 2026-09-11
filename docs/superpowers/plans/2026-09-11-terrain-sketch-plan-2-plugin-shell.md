# Terrain Sketch — Plan 2: Plugin Shell and First Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the core engine into a usable QGIS 4 plugin: a native Terrain Sketch panel where the user picks a DEM, chooses one of the seven tools, draws a line or an area on the map, tweaks the values and sees the modified DEM, a change layer and a hillshade update immediately, and finally exports the modified DEM as a GeoTIFF.

**Architecture:** `qgis_io/` wraps GDAL/QGIS input and output (DEM reading, the session's working and change GeoTIFFs, the "Terrain Sketch" layer group, geometry conversion into the DEM CRS). `gui/controller.py` (`SketchController`) owns the session and is the only GUI object that touches the engine, files and layers. The widgets (`main_dock.py`, `feature_list.py`, `tool_gallery.py`, `properties_page.py`, `map_tools/`) only talk to the controller. `plugin.py` wires the toolbar button, Raster menu entry and panel into QGIS.

**Tech Stack:** QGIS 4.2.2 Python API (PyQt6 via `qgis.PyQt`, Qt 6.11), GDAL 3.13, numpy; pytest (dev-only) with a headless `QgsApplication` (`QT_QPA_PLATFORM=offscreen`).

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-sketch-design.md` — §4 (architecture), §6.1–6.2 (drawing, geometry handling), §7.1–7.2 (native look, right dock), §8.1–8.3 and §8.5 export (data flow), §9 (error handling), §11 milestone 2. Plan 1 (core engine) is merged on `main`.

## Global Constraints

- Target QGIS 4.x (Qt6) only: `metadata.txt` has `qgisMinimumVersion=4.0`, `qgisMaximumVersion=4.99`. Import Qt through `qgis.PyQt` and always use fully scoped Qt6 enums (`Qt.ItemDataRole.DisplayRole`, `Qgis.GeometryType.Line`, …).
- Native look (spec §7.1): only standard Qt/QGIS widgets (`QgsDockWidget`, `QgsMapLayerComboBox`, `QgsDoubleSpinBox`, message bar), QGIS theme icons via `QgsApplication.getThemeIcon`, no stylesheets or brand colours. Drawing behaves like QGIS digitizing: project snapping, digitizing stroke/fill colours (`QgsMapToolEdit.digitizingStrokeColor()` etc.), right-click/Enter finishes, Backspace/Delete removes the last vertex, Esc cancels.
- `terrain_sketch/core/` and `terrain_sketch/model/` never import `qgis` or `PyQt`. Widgets never call the engine, files or layers directly — only `SketchController`.
- The original DEM is never modified; each session writes its working and change GeoTIFFs to a fresh temporary folder (`tempfile.mkdtemp(prefix="terrain_sketch_")`).
- Errors never take QGIS down: user problems (bad DEM, unusable drawing) become message-bar messages; unexpected engine errors are caught in the controller, logged to the `QgsMessageLog` tab "Terrain Sketch" with the traceback, and reported in the message bar.
- User-facing names, summaries and messages live in `gui/help_texts.py`; widget captions use `self.tr()`. English only.
- Package modules start with a one-line docstring and use `from __future__ import annotations` where they have type hints; test modules need neither. 4-space indentation.
- Tests run only through `scripts/test.sh` (it sets `PYTHONHOME`, `PYTHONPATH`, `PROJ_DATA`, `QGIS_PREFIX_PATH`, `QT_PLUGIN_PATH` and `QT_QPA_PLATFORM=offscreen`). QGIS integration tests live in `tests/qgis/`; their shared helpers are in `tests/qgis/qgis_helpers.py` (never a second `helpers.py`, which would collide with `tests/core/helpers.py`).
- Out of scope here (later plans): freehand, brush and from-layer selection (Plan 3); profile dock and live preview while dragging (Plan 4); illustrations and rich help (Plan 5); scenarios, volumes panel, undo/redo, 3D view, duplicate and ZIP packaging (Plan 6).

## Decisions made while prototyping (read before implementing)

- **Plan 1 carry-overs handled in Task 1:** `TerrainFeature` normalises list fields to tuples (lists from widgets made it unhashable); `FeatureStack.preview()` returns a `Preview(window, grid, stats)` named tuple; `DemGrid.from_array` rejects non-2-D input; `scripts/test.sh` reports pip failures and sets the Qt/QGIS variables.
- **Session start is explicit:** the panel has a DEM picker plus a **Start** button (with a confirmation when features would be discarded) instead of switching sessions whenever the combo box changes.
- **Sketch outlines** show path features as their corridor polygon (the real footprint width), area features as drawn; disabled features are hidden.
- **Layer removal:** the controller listens to `QgsProject.layersRemoved` (after the removal finished). If the DEM or any session layer is removed, the session ends and the remaining session layers are removed synchronously; `QgsProject.cleared` simply drops the session.
- **Drag-and-drop reordering** is done by the model: `dropMimeData` asks the controller to reorder and returns `False`, so the view never deletes the dragged rows itself.
- **Not yet:** the spec's "Reproject…" button (the message names the Warp tool instead) and "Duplicate" in the context menu come with Plans 5 and 6.

## File Structure

| File | Responsibility |
|---|---|
| `terrain_sketch/__init__.py` | `classFactory(iface)` for QGIS (Task 9) |
| `terrain_sketch/metadata.txt`, `icons/terrain_sketch.svg` | Plugin metadata and toolbar icon |
| `terrain_sketch/plugin.py` | `TerrainSketchPlugin`: toolbar button, Raster menu entry, creates/removes the panel, GDAL check |
| `terrain_sketch/qgis_io/compat.py` | `gdal_problems()` — GDAL ≥ 3.11 capability check |
| `terrain_sketch/qgis_io/convert.py` | `to_dem_wkb()` (transform, repair, keep the right parts) and `from_wkb()` |
| `terrain_sketch/qgis_io/raster_io.py` | `read_dem()`, `DemInfo`, `DemError`, `WorkingFiles`, `export_dem()` |
| `terrain_sketch/qgis_io/layers.py` | `SketchLayers`: the "Terrain Sketch" group (outlines, change, hillshade, modified DEM) |
| `terrain_sketch/gui/help_texts.py` | Tool labels and summaries, pixel-mode labels, flag texts, drawing hint |
| `terrain_sketch/gui/controller.py` | `SketchController`: session, feature list, engine, files, layers, messages |
| `terrain_sketch/gui/map_tools/base.py`, `draw_line.py`, `draw_polygon.py` | Drawing tools with snapping and QGIS digitizing keys |
| `terrain_sketch/gui/feature_list.py` | `FeatureListModel` / `FeatureListView` (checkbox, rename, warning, drag to reorder) |
| `terrain_sketch/gui/tool_gallery.py` | "What do you want to build?" list and "Where?" buttons |
| `terrain_sketch/gui/properties_page.py` | Values of the selected feature, applied immediately |
| `terrain_sketch/gui/main_dock.py` | `MainDock`: assembles the panel and runs the drawing flow |
| `scripts/dev_install.sh` | Links the plugin into the QGIS 4 profile for manual testing |
| `tests/qgis/conftest.py`, `qgis_helpers.py` | Headless `QgsApplication`, clean project per test, test DEMs, fake iface |

---

### Task 1: Plan 1 carry-overs (hashable features, preview stats, 2-D check, test runner)

**Files:**
- Modify: `terrain_sketch/model/feature.py`, `terrain_sketch/core/engine.py`, `terrain_sketch/core/grid.py`, `scripts/test.sh`
- Test: `tests/core/test_feature.py`, `tests/core/test_engine.py`, `tests/core/test_grid.py`

**Interfaces:**
- Consumes: the Plan 1 engine as merged on `main`.
- Produces: `TerrainFeature` stores `cross_left`, `cross_right`, `long_profile` as tuples of float pairs and `geometry_wkb` as `bytes` even when given lists/bytearrays; `FeatureStack.preview(features) -> Preview | None` with `Preview(window: Window, grid: DemGrid, stats: dict[str, FeatureStats])` (a `NamedTuple` defined in `core/engine.py`); `DemGrid.from_array` raises `ValueError` for non-2-D arrays; `scripts/test.sh` exports `QGIS_PREFIX_PATH`, `QT_PLUGIN_PATH`, `QT_QPA_PLATFORM` (default `offscreen`) and exits with a message if pytest cannot be installed.

- [ ] **Step 1: Replace the three core test modules (each adds or changes one test)**

**File:** `tests/core/test_feature.py`
```python
import json
from dataclasses import replace

import pytest

from terrain_sketch.core.geometry import line_wkb, polygon_wkb
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.model.feature import TerrainFeature, new_feature

TRIANGLE = polygon_wkb([(0, 0), (1, 0), (1, 1)])


def test_round_trip_through_json_dict():
    f = TerrainFeature(id="a", name="Dike", tool=Tool.RAISE_PATH, mode=Mode.PATH,
                       geometry_wkb=line_wkb([(0, 0), (1, 1)]), cross_left=((2.0, -0.5),),
                       long_profile=((0.0, 10.0), (1.4, 11.0)))
    d = json.loads(json.dumps(f.to_dict()))
    assert TerrainFeature.from_dict(d) == f


def test_new_feature_defaults():
    pond = new_feature(Tool.LOWER_FLAT, Mode.AREA, TRIANGLE, cell_size=0.4)
    assert pond.slopes_inside and pond.width == 1.2 and pond.name == "Lower flat" and len(pond.id) == 32
    pad = new_feature(Tool.RAISE_FLAT, Mode.AREA, TRIANGLE, cell_size=0.1)
    assert not pad.slopes_inside and pad.width == 1.0
    assert not new_feature(Tool.LOWER_FLAT, Mode.PATH, line_wkb([(0, 0), (1, 0)]), 1.0).slopes_inside


def test_tool_mode_mismatch_is_rejected():
    with pytest.raises(ValueError):
        TerrainFeature(id="x", name="x", tool=Tool.RAISE_PATH, mode=Mode.AREA, geometry_wkb=TRIANGLE)


def test_features_compare_and_hash_by_value():
    f = new_feature(Tool.ADD, Mode.AREA, TRIANGLE, 1.0)
    assert f == replace(f) and hash(f) == hash(replace(f))
    assert f != replace(f, amount=2.0)


def test_list_fields_are_normalised_to_hashable_tuples():
    f = new_feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(0, 0), (1, 0)]), 1.0)
    g = replace(f, cross_left=[[2, -0.5]], long_profile=[[0, 10], [1, 11]])
    assert g.cross_left == ((2.0, -0.5),) and g.long_profile == ((0.0, 10.0), (1.0, 11.0))
    assert isinstance(hash(g), int)
```
**File:** `tests/core/test_engine.py`
```python
from dataclasses import replace

import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, polygon_wkb
from terrain_sketch.core.grid import DemGrid
from terrain_sketch.core.operations import FLAG_OUTSIDE, apply_feature
from terrain_sketch.core.tools import TOOL_INFO, Mode, PixelMode, Tool


def square(x0, y0, x1, y1):
    return polygon_wkb([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def oracle(original, features):
    """Straightforward full-grid replay, independent of the engine's windowing."""
    grid = original.copy()
    for f in features:
        if f.enabled:
            apply_feature(f, grid)
    return grid.data


def test_update_changes_only_the_returned_window():
    stack = FeatureStack(make_grid(flat(10), rows=60, cols=60))
    window = stack.update([feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3), amount=1.0)])
    rows, cols = np.nonzero(stack.working.data != stack.original.data)
    assert window.row0 <= rows.min() and rows.max() < window.row1
    assert window.col0 <= cols.min() and cols.max() < window.col1
    assert (stack.original.data == 10).all()
    assert stack.stats["f1"].fill == pytest.approx(25.0)


def test_unchanged_list_needs_no_recompute():
    stack = FeatureStack(make_grid(flat(10)))
    f = feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3))
    stack.update([f])
    assert stack.update([f]) is None


def test_toggle_and_delete_restore_the_original():
    stack = FeatureStack(make_grid(tilted))
    f = feature(Tool.RAISE_FLAT, Mode.AREA, square(10.3, 10.3, 20.3, 20.3))
    stack.update([f])
    assert (stack.working.data != stack.original.data).any()
    stack.update([replace(f, enabled=False)])
    np.testing.assert_array_equal(stack.working.data, stack.original.data)
    stack.update([f])
    stack.update([])
    np.testing.assert_array_equal(stack.working.data, stack.original.data)
    assert stack.stats == {}


def test_order_matters_for_overlapping_features():
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, square(10.3, 10.3, 30.3, 30.3), id="pad", amount=2.0, slope_n=0.0)
    ditch = feature(Tool.LOWER_PATH, Mode.PATH, line_wkb([(5.25, 20.25), (34.75, 20.25)]), id="ditch",
                    amount=1.0, slope_n=0.0)
    ditch_last = FeatureStack(make_grid(flat(10)))
    ditch_last.update([pad, ditch])
    pad_last = FeatureStack(make_grid(flat(10)))
    pad_last.update([ditch, pad])
    assert ditch_last.working.data[19, 20] == pytest.approx(9.0)
    assert pad_last.working.data[19, 20] == pytest.approx(12.0)


def test_reference_elevations_follow_earlier_features():
    """A dike starting on a pad is recomputed when the pad's height changes."""
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, square(4.3, 16.3, 8.3, 24.3), id="pad", amount=1.0, slope_n=0.0)
    dike = feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(6.25, 20.25), (34.75, 20.25)]), id="dike",
                   amount=0.5, slope_n=0.0)
    stack = FeatureStack(make_grid(flat(10)))
    stack.update([pad, dike])
    assert stack.working.data[19, 20] == pytest.approx(11.0, abs=1e-3)
    stack.update([replace(pad, amount=3.0), dike])
    assert stack.working.data[19, 20] == pytest.approx(12.0, abs=1e-3)
    np.testing.assert_allclose(stack.working.data, oracle(stack.original, stack.features))


def test_preview_does_not_change_the_stack():
    stack = FeatureStack(make_grid(flat(10)))
    preview = stack.preview([feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3))])
    assert (preview.grid.data > 10).any()
    assert preview.stats["f1"].fill == pytest.approx(25.0)
    assert (stack.working.data == 10).all() and stack.features == ()


def test_feature_outside_the_dem_is_flagged():
    stack = FeatureStack(make_grid(flat(10)))
    assert stack.update([feature(Tool.ADD, Mode.PATH, line_wkb([(500, 500), (600, 600)]))]) is None
    assert stack.stats["f1"].flags == (FLAG_OUTSIDE,)


def random_feature(rng, i, size):
    tool = list(Tool)[rng.integers(len(Tool))]
    modes = TOOL_INFO[tool].modes
    mode = modes[rng.integers(len(modes))]
    if mode is Mode.PATH:
        wkb = line_wkb(rng.uniform(3, size - 3, (int(rng.integers(2, 5)), 2)))
    else:
        cx, cy = rng.uniform(8, size - 8, 2)
        radius = rng.uniform(2, 6)
        angles = np.sort(rng.uniform(0, 2 * np.pi, 6))
        wkb = polygon_wkb([(cx + radius * np.cos(a), cy + radius * np.sin(a)) for a in angles])
    return feature(tool, mode, wkb, id=f"f{i}", amount=float(rng.uniform(0.2, 3)),
                   width=float(rng.uniform(1, 4)), slope_n=float(rng.choice([0.0, 1.5, 3.0])),
                   reach=float(rng.uniform(2, 8)),
                   slopes_inside=bool(rng.integers(2)) if mode is Mode.AREA else False,
                   pixel_mode=list(PixelMode)[rng.integers(len(PixelMode))])


@pytest.mark.parametrize("seed", range(6))
def test_windowed_updates_match_full_replay(seed):
    rng = np.random.default_rng(seed)
    size = 60
    stack = FeatureStack(make_grid(lambda X, Y: 10 + 0.05 * X + 2 * np.sin(X / 7) * np.cos(Y / 5),
                                   rows=size, cols=size))
    features = [random_feature(rng, i, size) for i in range(int(rng.integers(1, 9)))]
    stack.update(features)
    np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4)
    for step in range(8):
        action = int(rng.integers(5))
        if action == 0 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], amount=float(rng.uniform(0.2, 3)))
        elif action == 1 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], enabled=not features[k].enabled)
        elif action == 2 and len(features) > 1:
            i, j = rng.choice(len(features), 2, replace=False)
            features[i], features[j] = features[j], features[i]
        elif action == 3 and features:
            features.pop(int(rng.integers(len(features))))
        else:
            features.append(random_feature(rng, 100 + step, size))
        stack.update(features)
        np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4,
                                   err_msg=f"seed {seed} step {step}")


_X0, _Y0, _CELL, _N = 612345.6, 6178901.2, 0.4, 60


def _realistic_grid():
    """North-up grid with a non-integer, sub-metre origin and 0.4 m cells."""
    gt = (_X0, _CELL, 0.0, _Y0 + _N * _CELL, 0.0, -_CELL)
    xs = np.arange(_N) + 0.5
    ys = _N - (np.arange(_N) + 0.5)
    X, Y = np.meshgrid(xs, ys)
    data = (10 + 0.05 * X + 2 * np.sin(X / 7) * np.cos(Y / 5)).astype(np.float32)
    return DemGrid.from_array(data, gt)


def _to_world(u, v):
    return _X0 + u * _CELL, _Y0 + v * _CELL


def _snapped_random_feature(rng, i):
    """Like `random_feature`, but on the realistic grid: coordinates snapped to half cells
    (so they land exactly on cell edges/centres) and widths/reach scaled by the cell size."""
    tool = list(Tool)[rng.integers(len(Tool))]
    modes = TOOL_INFO[tool].modes
    mode = modes[rng.integers(len(modes))]
    snap = lambda a: np.round(a * 2) / 2  # noqa: E731
    if mode is Mode.PATH:
        pts = snap(rng.uniform(3, _N - 3, (int(rng.integers(2, 5)), 2)))
        wkb = line_wkb([_to_world(*p) for p in pts])
    else:
        cx, cy = rng.uniform(8, _N - 8, 2)
        radius = rng.uniform(2, 6)
        angles = np.sort(rng.uniform(0, 2 * np.pi, 6))
        pts = snap(np.c_[cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
        wkb = polygon_wkb([_to_world(*p) for p in pts])
    return feature(tool, mode, wkb, id=f"f{i}", amount=float(rng.uniform(0.2, 3)),
                   width=float(rng.uniform(1, 4)) * _CELL, slope_n=float(rng.choice([0.0, 1.5, 3.0])),
                   reach=float(rng.uniform(2, 8)) * _CELL,
                   slopes_inside=bool(rng.integers(2)) if mode is Mode.AREA else False,
                   pixel_mode=list(PixelMode)[rng.integers(len(PixelMode))])


@pytest.mark.parametrize("seed", range(12))
def test_windowed_updates_match_full_replay_on_a_realistic_grid(seed):
    """Same property as test_windowed_updates_match_full_replay, but on a non-integer,
    sub-metre-cell geotransform where a ULP-level offset between a window taken through a
    subgrid and one taken directly can flip GDAL rasterization on boundaries snapped to
    cell edges/centres (C1)."""
    rng = np.random.default_rng(seed)
    stack = FeatureStack(_realistic_grid())
    features = [_snapped_random_feature(rng, i) for i in range(int(rng.integers(1, 9)))]
    stack.update(features)
    np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4)
    for step in range(8):
        action = int(rng.integers(5))
        if action == 0 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], amount=float(rng.uniform(0.2, 3)))
        elif action == 1 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], enabled=not features[k].enabled)
        elif action == 2 and len(features) > 1:
            i, j = rng.choice(len(features), 2, replace=False)
            features[i], features[j] = features[j], features[i]
        elif action == 3 and features:
            features.pop(int(rng.integers(len(features))))
        else:
            features.append(_snapped_random_feature(rng, 100 + step))
        stack.update(features)
        np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4,
                                   err_msg=f"seed {seed} step {step}")
```
**File:** `tests/core/test_grid.py`
```python
import math

import numpy as np
import pytest

from helpers import make_grid
from terrain_sketch.core.grid import DemGrid, Window


def test_window_for_bbox_adds_margin_and_clips():
    g = make_grid(lambda X, Y: 0 * X, rows=10, cols=10)
    assert g.window_for_bbox(2.5, 2.5, 4.5, 4.5, margin_cells=1) == Window(4, 1, 5, 5)
    assert g.window_for_bbox(-5, -5, 3, 3) == Window(7, 0, 3, 3)
    assert g.window_for_bbox(-5, -5, -1, -1) is None


def test_window_union_intersects_contains():
    a, b = Window(0, 0, 2, 2), Window(1, 1, 3, 3)
    assert a.union(b) == Window(0, 0, 4, 4)
    assert a.intersects(b) and not a.intersects(Window(2, 2, 1, 1))
    assert a.union(b).contains(b) and not a.contains(b)


def test_subgrid_is_a_copy_and_view_shares_memory():
    g = make_grid(lambda X, Y: X + 100 * Y, rows=10, cols=10)
    w = Window(2, 3, 4, 5)
    sub = g.subgrid(w)
    X, Y = sub.cell_centers()
    np.testing.assert_allclose(sub.data, X + 100 * Y)
    sub.data[:] = 5
    assert g.data[2, 3] != 5
    g.view(w).data[:] = 0
    assert g.data[2:6, 3:8].sum() == 0


def test_rejects_rotated_and_south_up_rasters():
    with pytest.raises(ValueError):
        DemGrid.from_array(np.zeros((2, 2)), (0, 1, 0.1, 2, 0, -1))
    with pytest.raises(ValueError):
        DemGrid.from_array(np.zeros((2, 2)), (0, 1, 0, 0, 0, 1))


def test_sample_is_exact_on_a_plane():
    g = make_grid(lambda X, Y: 2 * X + 3 * Y, rows=10, cols=10)
    assert g.sample(4.3, 6.7) == pytest.approx(2 * 4.3 + 3 * 6.7, abs=1e-4)


def test_sample_uses_nearest_valid_cell_next_to_nodata():
    g = make_grid(lambda X, Y: X, rows=10, cols=10, nodata_cells=[(5, 5)])
    assert g.sample(5.5, 4.5) in (4.5, 5.5, 6.5)
    assert math.isnan(g.sample(50.0, 50.0))


def test_nested_windows_share_bit_identical_geotransforms():
    """On a realistic (non-integer, sub-metre) geotransform, a window taken through a
    subgrid must land on exactly the same geotransform as a direct window on the root grid —
    otherwise rasterization of boundaries on cell edges can flip by a ULP-level offset."""
    g = DemGrid.from_array(np.zeros((60, 60), np.float32), (612345.6, 0.4, 0.0, 6178925.2, 0.0, -0.4))
    a, b, c, d = 0, 1, 0, 2
    nested = g.subgrid(Window(a, b, 30, 30)).view(Window(c, d, 10, 10))
    direct = g.view(Window(a + c, b + d, 10, 10))
    assert nested.geotransform == direct.geotransform
    X1, Y1 = nested.cell_centers()
    X2, Y2 = direct.cell_centers()
    assert (X1 == X2).all() and (Y1 == Y2).all()


def test_from_array_rejects_non_2d_input():
    with pytest.raises(ValueError):
        DemGrid.from_array(np.zeros(5), (0, 1, 0, 1, 0, -1))
```
- [ ] **Step 2: Run them to verify the new tests fail**

Run: `scripts/test.sh tests/core/test_feature.py tests/core/test_engine.py tests/core/test_grid.py`
Expected: exactly 3 failures — `test_list_fields_are_normalised_to_hashable_tuples` (the lists are stored as lists), `test_preview_does_not_change_the_stack` (`AttributeError: 'tuple' object has no attribute 'grid'`), `test_from_array_rejects_non_2d_input` (`DID NOT RAISE`).

- [ ] **Step 3: Implement the three changes**

**File:** `terrain_sketch/model/feature.py`
```python
"""TerrainFeature: one drawn landscape feature and its parameters (pure data, no QGIS)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..core.tools import TOOL_INFO, Mode, PixelMode, Tool


@dataclass(frozen=True)
class TerrainFeature:
    id: str
    name: str
    tool: Tool
    mode: Mode
    geometry_wkb: bytes              # LineString/Polygon or Multi*, in the DEM CRS
    enabled: bool = True
    pixel_mode: PixelMode = PixelMode.CENTRE
    amount: float = 1.0              # height H (raise/add) or depth D (lower/subtract), m, >= 0
    width: float = 2.0               # path corridor width W, m
    slope_n: float = 3.0             # side slope 1:n (n m across per 1 m height); 0 = none
    reach: float = 20.0              # maximum horizontal reach of a side slope, m
    slopes_inside: bool = False      # area features: slopes inside the outline
    cross_left: tuple = ()           # ((distance beyond corridor edge, dz), ...)
    cross_right: tuple = ()
    long_profile: tuple | None = None  # ((station, absolute z), ...); None = tool rule

    def __post_init__(self):
        if self.mode not in TOOL_INFO[self.tool].modes:
            raise ValueError(f"{self.tool.value} does not support {self.mode.value} mode")
        # the GUI may pass lists; store hashable tuples of float pairs (the engine caches by value)
        object.__setattr__(self, "geometry_wkb", bytes(self.geometry_wkb))
        object.__setattr__(self, "cross_left", _points(self.cross_left))
        object.__setattr__(self, "cross_right", _points(self.cross_right))
        if self.long_profile is not None:
            object.__setattr__(self, "long_profile", _points(self.long_profile))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tool": self.tool.value,
            "mode": self.mode.value,
            "geometry_wkb": self.geometry_wkb.hex(),
            "enabled": self.enabled,
            "pixel_mode": self.pixel_mode.value,
            "amount": self.amount,
            "width": self.width,
            "slope_n": self.slope_n,
            "reach": self.reach,
            "slopes_inside": self.slopes_inside,
            "cross_left": [list(p) for p in self.cross_left],
            "cross_right": [list(p) for p in self.cross_right],
            "long_profile": None if self.long_profile is None else [list(p) for p in self.long_profile],
        }

    @classmethod
    def from_dict(cls, d: dict) -> TerrainFeature:
        return cls(
            id=d["id"],
            name=d["name"],
            tool=Tool(d["tool"]),
            mode=Mode(d["mode"]),
            geometry_wkb=bytes.fromhex(d["geometry_wkb"]),
            enabled=bool(d.get("enabled", True)),
            pixel_mode=PixelMode(d.get("pixel_mode", PixelMode.CENTRE.value)),
            amount=float(d.get("amount", 1.0)),
            width=float(d.get("width", 2.0)),
            slope_n=float(d.get("slope_n", 3.0)),
            reach=float(d.get("reach", 20.0)),
            slopes_inside=bool(d.get("slopes_inside", False)),
            cross_left=_points(d.get("cross_left")),
            cross_right=_points(d.get("cross_right")),
            long_profile=None if d.get("long_profile") is None else _points(d["long_profile"]),
        )


def _points(seq) -> tuple:
    return tuple((float(a), float(b)) for a, b in (seq or ()))


def default_width(cell_size: float) -> float:
    return round(max(3.0 * cell_size, 1.0), 1)


def new_feature(tool: Tool, mode: Mode, geometry_wkb: bytes, cell_size: float,
                name: str | None = None) -> TerrainFeature:
    """A feature with the defaults the GUI uses right after drawing."""
    return TerrainFeature(
        id=uuid.uuid4().hex,
        name=name or tool.value.replace("_", " ").capitalize(),
        tool=tool,
        mode=mode,
        geometry_wkb=bytes(geometry_wkb),
        width=default_width(cell_size),
        slopes_inside=mode is Mode.AREA and TOOL_INFO[tool].direction > 0,
    )
```
**File:** `terrain_sketch/core/engine.py`
```python
"""FeatureStack: the ordered list of features and the windowed recompute of the working DEM."""
from __future__ import annotations

from typing import NamedTuple

from .grid import DemGrid, Window
from .operations import FeatureStats, apply_feature, feature_window, footprint_flags


class Preview(NamedTuple):
    """What `FeatureStack.preview` returns: the changed window, its values and per-feature stats."""

    window: Window
    grid: DemGrid
    stats: dict


class FeatureStack:
    """Holds the untouched `original`, the `working` result and per-feature stats.

    Call `update(features)` with the complete new ordered feature list after every change;
    it recomputes only the cells that can differ and returns that window (or None)."""

    def __init__(self, original: DemGrid):
        self.original = original
        self.working = original.copy()
        self.features: tuple = ()
        self.stats: dict[str, FeatureStats] = {}
        self._windows: dict = {}

    def footprint(self, feature) -> Window | None:
        if feature not in self._windows:
            self._windows[feature] = feature_window(feature, self.original)
        return self._windows[feature]

    def dirty_window(self, features) -> Window | None:
        """Union of the footprints of every feature that was added, removed, edited,
        toggled or moved relative to overlapping features."""
        old = {f.id: f for f in self.features}
        new = {f.id: f for f in features}
        common = old.keys() & new.keys()
        old_before = _predecessors(self.features, common)
        new_before = _predecessors(features, common)
        dirty = None
        for fid in old.keys() | new.keys():
            o, n = old.get(fid), new.get(fid)
            if o is not None and o == n and old_before[fid] == new_before[fid]:
                continue
            for f in (o, n):
                if f is not None and f.enabled:
                    w = self.footprint(f)
                    if w is not None:
                        dirty = w.union(dirty)
        return dirty

    def closure(self, window: Window, features) -> tuple[Window, list]:
        """Grow `window` until it fully contains every enabled feature overlapping it, so the
        reference elevations of those features are recomputed too. Returns the window and
        the features to replay, in list order."""
        active = [(f, self.footprint(f)) for f in features if f.enabled]
        grown = True
        while grown:
            grown = False
            for _, w in active:
                if w is not None and w.intersects(window) and not window.contains(w):
                    window = window.union(w)
                    grown = True
        return window, [f for f, w in active if w is not None and w.intersects(window)]

    def compute(self, features, window: Window) -> tuple[DemGrid, dict]:
        """Replay `features` in order over `window`, starting from the original terrain."""
        grid = self.original.subgrid(window)
        stats = {f.id: apply_feature(f, grid) for f in features}
        return grid, stats

    def preview(self, features) -> Preview | None:
        """Result of `features` for the changed window, without changing the stack."""
        features = tuple(features)
        dirty = self.dirty_window(features)
        if dirty is None:
            return None
        window, replay = self.closure(dirty, features)
        grid, stats = self.compute(replay, window)
        return Preview(window, grid, stats)

    def update(self, features) -> Window | None:
        """Make `features` the current list and recompute; returns the changed window."""
        features = tuple(features)
        dirty = self.dirty_window(features)
        self.features = features
        self._refresh_bookkeeping()
        if dirty is None:
            return None
        window, replay = self.closure(dirty, features)
        grid, stats = self.compute(replay, window)
        self.working.data[window.slices] = grid.data
        self.stats.update(stats)
        return window

    def _refresh_bookkeeping(self) -> None:
        current = set(self.features)
        self._windows = {f: w for f, w in self._windows.items() if f in current}
        ids = {f.id for f in self.features}
        self.stats = {k: v for k, v in self.stats.items() if k in ids}
        for f in self.features:
            if not f.enabled:
                self.stats[f.id] = FeatureStats()
            elif self.footprint(f) is None:
                self.stats[f.id] = FeatureStats(flags=footprint_flags(f))


def _predecessors(features, common) -> dict:
    out, seen = {}, []
    for f in features:
        if f.id in common:
            out[f.id] = frozenset(seen)
            seen.append(f.id)
    return out
```
**File:** `terrain_sketch/core/grid.py`
```python
"""DEM held in memory: values, validity mask, north-up geotransform and cell windows."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Window:
    """Block of cells: rows row0..row0+rows-1 and cols col0..col0+cols-1."""

    row0: int
    col0: int
    rows: int
    cols: int

    @property
    def row1(self) -> int:
        return self.row0 + self.rows

    @property
    def col1(self) -> int:
        return self.col0 + self.cols

    @property
    def slices(self) -> tuple[slice, slice]:
        return slice(self.row0, self.row1), slice(self.col0, self.col1)

    def union(self, other: Window | None) -> Window:
        if other is None:
            return self
        r0, c0 = min(self.row0, other.row0), min(self.col0, other.col0)
        r1, c1 = max(self.row1, other.row1), max(self.col1, other.col1)
        return Window(r0, c0, r1 - r0, c1 - c0)

    def intersects(self, other: Window) -> bool:
        return (self.row0 < other.row1 and other.row0 < self.row1
                and self.col0 < other.col1 and other.col0 < self.col1)

    def contains(self, other: Window) -> bool:
        return (self.row0 <= other.row0 and self.col0 <= other.col0
                and other.row1 <= self.row1 and other.col1 <= self.col1)


class DemGrid:
    """A north-up raster block. `data` is float32; cells where `valid` is False are nodata."""

    def __init__(self, data: np.ndarray, valid: np.ndarray, geotransform, offset=(0, 0)):
        gt = tuple(float(v) for v in geotransform)
        if gt[2] != 0.0 or gt[4] != 0.0:
            raise ValueError("Rotated rasters are not supported")
        if gt[5] >= 0.0:
            raise ValueError("Raster must be north-up (negative pixel height)")
        self.data = data
        self.valid = valid
        self.root = gt
        self.offset = (int(offset[0]), int(offset[1]))

    @property
    def geotransform(self) -> tuple:
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        return (rx0 + col_off * px, px, 0.0, ry0 + row_off * py, 0.0, py)

    @classmethod
    def from_array(cls, array, geotransform, nodata=None) -> DemGrid:
        data = np.array(array, dtype=np.float32)
        if data.ndim != 2:
            raise ValueError("DEM data must be a 2-D array")
        valid = np.isfinite(data)
        if nodata is not None:
            valid &= data != np.float32(nodata)
        return cls(data, valid, geotransform)

    @property
    def rows(self) -> int:
        return self.data.shape[0]

    @property
    def cols(self) -> int:
        return self.data.shape[1]

    @property
    def cell_width(self) -> float:
        return self.geotransform[1]

    @property
    def cell_height(self) -> float:
        return -self.geotransform[5]

    @property
    def cell_size(self) -> float:
        return 0.5 * (self.cell_width + self.cell_height)

    @property
    def cell_area(self) -> float:
        return self.cell_width * self.cell_height

    @property
    def full_window(self) -> Window:
        return Window(0, 0, self.rows, self.cols)

    def copy(self) -> DemGrid:
        return DemGrid(self.data.copy(), self.valid.copy(), self.root, self.offset)

    def window_geotransform(self, window: Window) -> tuple:
        """Root-based geotransform of `window` (in this grid's local coordinates): every path
        to the same absolute cells produces a bit-identical tuple."""
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        return (rx0 + (col_off + window.col0) * px, px, 0.0, ry0 + (row_off + window.row0) * py, 0.0, py)

    def subgrid(self, window: Window) -> DemGrid:
        """Independent copy of a window."""
        rs, cs = window.slices
        row_off, col_off = self.offset
        offset = (row_off + window.row0, col_off + window.col0)
        return DemGrid(self.data[rs, cs].copy(), self.valid[rs, cs].copy(), self.root, offset)

    def view(self, window: Window) -> DemGrid:
        """Window sharing memory with this grid: writes to the view change this grid."""
        rs, cs = window.slices
        row_off, col_off = self.offset
        offset = (row_off + window.row0, col_off + window.col0)
        return DemGrid(self.data[rs, cs], self.valid[rs, cs], self.root, offset)

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """Continuous (col, row); cell (r, c) covers [c, c+1) x [r, r+1)."""
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        return (x - rx0) / px - col_off, (y - ry0) / py - row_off

    def cell_centers(self) -> tuple[np.ndarray, np.ndarray]:
        rx0, px, _, ry0, _, py = self.root
        row_off, col_off = self.offset
        xs = rx0 + (col_off + np.arange(self.cols) + 0.5) * px
        ys = ry0 + (row_off + np.arange(self.rows) + 0.5) * py
        return np.meshgrid(xs, ys)

    def window_for_bbox(self, xmin, ymin, xmax, ymax, margin_cells: int = 0) -> Window | None:
        """Cells touching the bbox plus a margin, clipped to the grid; None if outside."""
        c_lo, r_lo = self.world_to_pixel(xmin, ymax)
        c_hi, r_hi = self.world_to_pixel(xmax, ymin)
        c0 = max(math.floor(c_lo) - margin_cells, 0)
        r0 = max(math.floor(r_lo) - margin_cells, 0)
        c1 = min(math.ceil(c_hi) + margin_cells, self.cols)
        r1 = min(math.ceil(r_hi) + margin_cells, self.rows)
        if c1 <= c0 or r1 <= r0:
            return None
        return Window(r0, c0, r1 - r0, c1 - c0)

    def sample(self, x: float, y: float, search_cells: int = 3) -> float:
        """Bilinear elevation at (x, y). If a needed cell is nodata or the point lies off the
        grid, the nearest valid cell within `search_cells` is used; NaN if there is none."""
        cf, rf = self.world_to_pixel(x, y)
        inside = 0.0 <= cf < self.cols and 0.0 <= rf < self.rows
        if inside:
            u, v = cf - 0.5, rf - 0.5
            c0, r0 = math.floor(u), math.floor(v)
            fu, fv = u - c0, v - r0
            total = 0.0
            ok = True
            for r, c, w in ((r0, c0, (1 - fu) * (1 - fv)), (r0, c0 + 1, fu * (1 - fv)),
                            (r0 + 1, c0, (1 - fu) * fv), (r0 + 1, c0 + 1, fu * fv)):
                r = min(max(r, 0), self.rows - 1)
                c = min(max(c, 0), self.cols - 1)
                if not self.valid[r, c]:
                    ok = False
                    break
                total += w * float(self.data[r, c])
            if ok:
                return total
        return self._nearest_valid(cf, rf, search_cells)

    def _nearest_valid(self, cf: float, rf: float, search_cells: int) -> float:
        rc, cc = math.floor(rf), math.floor(cf)
        r0, r1 = max(rc - search_cells, 0), min(rc + search_cells + 1, self.rows)
        c0, c1 = max(cc - search_cells, 0), min(cc + search_cells + 1, self.cols)
        if r1 <= r0 or c1 <= c0:
            return math.nan
        block = self.valid[r0:r1, c0:c1]
        if not block.any():
            return math.nan
        rr, cc_ = np.nonzero(block)
        d2 = (rr + r0 + 0.5 - rf) ** 2 + (cc_ + c0 + 0.5 - cf) ** 2
        k = int(np.argmin(d2))
        return float(self.data[rr[k] + r0, cc_[k] + c0])
```
- [ ] **Step 4: Replace the test runner**

**File:** `scripts/test.sh`
```bash
#!/usr/bin/env bash
# Run the test suite with the Python interpreter bundled in QGIS 4 (macOS app bundle).
# Usage: scripts/test.sh [pytest args]   e.g. scripts/test.sh tests/core -k mask
# Override the app location with QGIS_APP=/Applications/Other-QGIS.app scripts/test.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QGIS_APP="${QGIS_APP:-/Applications/QGIS-final-4_2_2.app}"
B="$QGIS_APP/Contents"
PY="$B/MacOS/python3.12"
export PYTHONHOME="$B/Resources"
export PYTHONPATH="$ROOT:$B/Resources/python3.12:$B/Resources/python3.12/site-packages:$B/Resources/python3.12/lib-dynload:$ROOT/.devdeps"
export PROJ_DATA="$B/Resources/qgis/proj"
export QGIS_PREFIX_PATH="$QGIS_APP"
export QT_PLUGIN_PATH="$B/PlugIns"
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"
if [ ! -d "$ROOT/.devdeps/pytest" ]; then
  if ! "$PY" -m pip install -q --disable-pip-version-check --target "$ROOT/.devdeps" pytest; then
    echo "scripts/test.sh: could not install pytest into .devdeps/ (the first run needs a network connection)" >&2
    exit 1
  fi
fi
cd "$ROOT"
exec "$PY" -m pytest "$@"
```
- [ ] **Step 5: Run the core suite**

Run: `scripts/test.sh tests/core`
Expected: `77 passed`

- [ ] **Step 6: Commit**

```bash
git add terrain_sketch/model/feature.py terrain_sketch/core/engine.py terrain_sketch/core/grid.py scripts/test.sh tests/core
git commit -m "feat(core): hashable feature lists, preview stats, 2-D check; headless test runner"
```

---

### Task 2: QGIS test harness, GDAL check and geometry conversion

**Files:**
- Create: `terrain_sketch/qgis_io/__init__.py`, `terrain_sketch/qgis_io/compat.py`, `terrain_sketch/qgis_io/convert.py`, `tests/qgis/conftest.py`, `tests/qgis/qgis_helpers.py`
- Test: `tests/qgis/test_convert.py`

**Interfaces:**
- Consumes: `core.geometry.split_parts/is_line`, `core.tools.Mode`.
- Produces: `gdal_problems() -> list[str]` (empty when GDAL has the MEM vector driver and flat-cap `Buffer`); `to_dem_wkb(geometry: QgsGeometry, source_crs, dem_crs, mode: Mode) -> bytes` (transform, `makeValid` when invalid, keep only line parts for `Mode.PATH` / polygon parts for `Mode.AREA`, raise `ValueError` with a user-facing message if none remain); `from_wkb(wkb) -> QgsGeometry`. Test helpers (`tests/qgis/qgis_helpers.py`): `X0, Y0, CELL, UTM`, `write_dem`, `dem_layer(tmp_path, array=None, name="dem", crs=…, nodata=…, gt=…, bands=…)`, `world(col, row)`, `line_through(c0, r0, c1, r1)`, `square(c0, r0, c1, r1)`, `sample(layer, col, row)`, `read_tif(path)`, `fake_iface()`, `start_session(tmp_path, array=None)` (imports the controller lazily; used from Task 5 on). `conftest.py` creates one `QgsApplication` at import and clears `QgsProject.instance()` before and after every test.

- [ ] **Step 1: Create the test harness and the failing tests**

**File:** `tests/qgis/conftest.py`
```python
"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()


@pytest.fixture(autouse=True)
def clean_project():
    QgsProject.instance().clear()
    yield
    QgsProject.instance().clear()
```
**File:** `tests/qgis/qgis_helpers.py`
```python
"""Helpers for the QGIS integration tests: small GeoTIFF DEMs on a UTM grid (EPSG:25832)."""
from unittest import mock

import numpy as np
from osgeo import gdal
from qgis.core import (QgsCoordinateReferenceSystem, QgsGeometry, QgsPointXY, QgsProject, QgsRasterLayer,
                       QgsRectangle)
from qgis.gui import QgisInterface, QgsMapCanvas
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
    return iface


def start_session(tmp_path, array=None):
    """A SketchController with a session on a fresh test DEM."""
    from terrain_sketch.gui.controller import SketchController  # imported late: the GUI package comes in a later task

    controller = SketchController(QgsProject.instance())
    controller.set_dem(dem_layer(tmp_path, array))
    return controller
```
**File:** `tests/qgis/test_convert.py`
```python
import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsGeometry

from qgis_helpers import UTM
from terrain_sketch.core.geometry import is_line, split_parts
from terrain_sketch.core.tools import Mode
from terrain_sketch.qgis_io.compat import gdal_problems
from terrain_sketch.qgis_io.convert import from_wkb, to_dem_wkb

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def test_bundled_gdal_has_everything_the_engine_needs():
    assert gdal_problems() == []


def test_bowtie_polygon_is_repaired_into_two_parts():
    bowtie = QgsGeometry.fromWkt("POLYGON((0 0, 10 10, 10 0, 0 10, 0 0))")
    parts = split_parts(to_dem_wkb(bowtie, UTM, UTM, Mode.AREA))
    assert len(parts) == 2 and not any(is_line(p) for p in parts)


def test_only_parts_of_the_wanted_dimension_are_kept():
    mixed = QgsGeometry.fromWkt("GEOMETRYCOLLECTION(POINT(1 1), LINESTRING(0 0, 5 5), POLYGON((0 0, 1 0, 1 1, 0 0)))")
    assert [is_line(p) for p in split_parts(to_dem_wkb(mixed, UTM, UTM, Mode.PATH))] == [True]
    with pytest.raises(ValueError):
        to_dem_wkb(QgsGeometry.fromWkt("LINESTRING(0 0, 5 5)"), UTM, UTM, Mode.AREA)


def test_geometry_is_transformed_to_the_dem_crs():
    back = from_wkb(to_dem_wkb(QgsGeometry.fromWkt("LINESTRING(9 55.7, 9.001 55.7)"), WGS84, UTM, Mode.PATH))
    assert 400000 < back.vertexAt(0).x() < 600000
    assert back.length() == pytest.approx(62.7, rel=0.05)
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_convert.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.qgis_io'`

- [ ] **Step 3: Implement the modules**

**File:** `terrain_sketch/qgis_io/__init__.py`
```python
"""QGIS/GDAL input and output: DEM reading, working files, layers, geometry conversion."""
```
**File:** `terrain_sketch/qgis_io/compat.py`
```python
"""Checks that the GDAL shipped with QGIS offers what the engine needs (GDAL 3.11 or newer)."""
from __future__ import annotations

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()


def gdal_problems() -> list[str]:
    """User-facing descriptions of missing GDAL capabilities; empty when all is well."""
    problems = []
    mem = gdal.GetDriverByName("MEM")
    if mem is None or mem.GetMetadataItem(gdal.DCAP_VECTOR) != "YES":
        problems.append("GDAL's in-memory driver cannot hold vector layers.")
    try:
        line = ogr.CreateGeometryFromWkt("LINESTRING (0 0, 1 0)")
        flat = line.Buffer(0.5, ["ENDCAP_STYLE=FLAT"])
        if flat is None or abs(flat.GetArea() - 1.0) > 1e-9:
            problems.append("GDAL cannot buffer lines with flat ends.")
    except (RuntimeError, TypeError):
        problems.append("GDAL cannot buffer lines with flat ends.")
    if problems:
        problems.append(f"Terrain Sketch needs GDAL 3.11 or newer; this QGIS has GDAL {gdal.__version__}.")
    return problems
```
**File:** `terrain_sketch/qgis_io/convert.py`
```python
"""QGIS geometries to engine WKB in the DEM CRS, and back."""
from __future__ import annotations

from qgis.core import Qgis, QgsCoordinateTransform, QgsGeometry, QgsProject

from ..core.tools import Mode


def to_dem_wkb(geometry: QgsGeometry, source_crs, dem_crs, mode: Mode) -> bytes:
    """Transform to the DEM CRS, repair, and keep only the parts that fit `mode` (lines for
    paths, polygons for areas). Raises ValueError with a user-facing message if none remain."""
    geom = QgsGeometry(geometry)
    if source_crs != dem_crs:
        geom.transform(QgsCoordinateTransform(source_crs, dem_crs, QgsProject.instance()))
    if not geom.isGeosValid():
        geom = geom.makeValid()
    wanted = Qgis.GeometryType.Line if mode is Mode.PATH else Qgis.GeometryType.Polygon
    parts = [p for p in geom.asGeometryCollection() if p.type() == wanted and not p.isEmpty()]
    if not parts:
        kind = "line" if mode is Mode.PATH else "area"
        raise ValueError(f"The drawn shape contains no {kind} that can be used.")
    combined = parts[0] if len(parts) == 1 else QgsGeometry.collectGeometry(parts)
    return bytes(combined.asWkb())


def from_wkb(wkb: bytes) -> QgsGeometry:
    geometry = QgsGeometry()
    geometry.fromWkb(bytes(wkb))
    return geometry
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_convert.py` → Expected: `4 passed`
Run: `scripts/test.sh` → Expected: `81 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/qgis_io tests/qgis
git commit -m "feat(qgis_io): headless QGIS test harness, GDAL check, geometry conversion"
```

---

### Task 3: DEM reading, working files and export

**Files:**
- Create: `terrain_sketch/qgis_io/raster_io.py`
- Test: `tests/qgis/test_raster_io.py`

**Interfaces:**
- Consumes: `core.grid.DemGrid/Window`.
- Produces: `DemError(Exception)` (user-facing message); `DemInfo(path, crs_wkt, nodata, band_count, warnings)` (frozen dataclass; `nodata` is the value written to all output files, `-9999.0` when the DEM has none); `read_dem(layer) -> (DemGrid, DemInfo)` (refuses non-raster/invalid, non-GDAL providers and geographic CRSs; band 1; warnings for extra bands and > 50 M cells); `WorkingFiles(folder, original, info)` with `.working_path`, `.change_path` and `.write(window, working)`; `export_dem(path, working, info)` (float32 LZW GeoTIFF with `PREDICTOR=3`); in the working, change and exported files, valid cells equal to the nodata value are nudged by one float step.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_raster_io.py`
```python
import numpy as np
import pytest

from qgis_helpers import CELL, X0, Y0, dem_layer, read_tif
from terrain_sketch.core.grid import Window
from terrain_sketch.qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem


def test_read_dem_returns_grid_and_info(tmp_path):
    array = np.arange(1200, dtype=np.float32).reshape(30, 40) + 1.0
    array[0, 0] = -9999.0
    grid, info = read_dem(dem_layer(tmp_path, array))
    assert grid.data.shape == (30, 40) and not grid.valid[0, 0] and grid.valid[0, 1]
    assert grid.geotransform == (X0, CELL, 0.0, Y0, 0.0, -CELL)
    assert info.nodata == -9999.0 and info.warnings == () and info.band_count == 1


def test_geographic_dem_is_refused(tmp_path):
    layer = dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    with pytest.raises(DemError, match="latitude"):
        read_dem(layer)


def test_multi_band_dem_uses_band_one_with_a_warning(tmp_path):
    _, info = read_dem(dem_layer(tmp_path, bands=2))
    assert any("band 1" in w for w in info.warnings)


def test_working_files_follow_window_writes(tmp_path):
    grid, info = read_dem(dem_layer(tmp_path))
    files = WorkingFiles(str(tmp_path / "session"), grid, info)
    working = grid.copy()
    working.data[5:7, 8:10] = 12.5
    files.write(Window(5, 8, 2, 2), working)
    values, _ = read_tif(files.working_path)
    change, nodata = read_tif(files.change_path)
    assert values[5, 8] == 12.5 and values[0, 0] == 10.0
    assert change[5, 8] == pytest.approx(2.5) and change[0, 0] == 0.0 and nodata == info.nodata


def test_export_keeps_nodata_and_nudges_clashing_values(tmp_path):
    array = np.full((10, 10), 10.0, np.float32)
    array[0, 0] = -9999.0
    grid, info = read_dem(dem_layer(tmp_path, array))
    working = grid.copy()
    working.data[1, 1] = -9999.0  # a valid cell that happens to equal the nodata value
    out = tmp_path / "export.tif"
    export_dem(str(out), working, info)
    exported, nodata = read_tif(out)
    assert exported.dtype == np.float32 and nodata == -9999.0
    assert exported[0, 0] == -9999.0
    assert exported[1, 1] != -9999.0 and exported[1, 1] == pytest.approx(-9999.0)


def test_change_raster_keeps_valid_cells_when_nodata_is_zero(tmp_path):
    array = np.full((10, 10), 10.0, np.float32)
    array[0, 0] = 0.0
    grid, info = read_dem(dem_layer(tmp_path, array, nodata=0.0))
    files = WorkingFiles(str(tmp_path / "session"), grid, info)
    change, nodata = read_tif(files.change_path)
    assert nodata == 0.0 and change[0, 0] == 0.0  # the real nodata cell stays nodata
    assert (change[1:, 1:] != 0.0).all() and change[5, 5] == pytest.approx(0.0)  # unchanged cells are no holes
    files.write(Window(5, 5, 1, 1), grid.copy())
    change, _ = read_tif(files.change_path)
    assert change[5, 5] != 0.0
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_raster_io.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.qgis_io.raster_io'`

- [ ] **Step 3: Implement raster I/O**

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
        raise DemError("The DEM uses latitude/longitude. Slopes and widths need metres: reproject it to a "
                       "projected CRS first (Raster ▸ Projections ▸ Warp).")
    ds = gdal.Open(layer.source())
    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    try:
        grid = DemGrid.from_array(band.ReadAsArray(), ds.GetGeoTransform(), nodata)
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

Run: `scripts/test.sh tests/qgis/test_raster_io.py` → Expected: `6 passed`
Run: `scripts/test.sh` → Expected: `87 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/qgis_io/raster_io.py tests/qgis/test_raster_io.py
git commit -m "feat(qgis_io): read the DEM, write working/change GeoTIFFs, export"
```

---

### Task 4: The "Terrain Sketch" layer group

**Files:**
- Create: `terrain_sketch/qgis_io/layers.py`
- Test: `tests/qgis/test_layers.py`

**Interfaces:**
- Consumes: `WorkingFiles` paths (Task 3).
- Produces: `GROUP_NAME = "Terrain Sketch"`, `CHANGE_LIMIT = 2.0`; `SketchLayers(project, dem_layer, working_path, change_path)` inserts a group at the top with, top to bottom, "Sketch outlines" (read-only memory polygon layer, fields `name`, `tool`, dashed outline, labels), "Change (new − original)" (pseudocolour: blue cut … transparent 0 … orange-red fill, ±`CHANGE_LIMIT` m), "Hillshade" (hidden, 50 % opacity) and "Modified DEM" (renderer cloned from the DEM); attributes `outlines`, `change`, `hillshade`, `working`, `group`, `layer_ids` and `outlines_id`, `change_id`, `hillshade_id`, `working_id`; methods `refresh()`, `set_outlines(items)` with `items = [(name, tool_label, QgsGeometry), …]`, `set_hillshade_visible(bool)`, `remove()` — all look layers up by id and skip layers the user already removed.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_layers.py`
```python
from qgis.core import QgsGeometry, QgsPointXY, QgsProject

from qgis_helpers import dem_layer, world
from terrain_sketch.core.grid import Window
from terrain_sketch.qgis_io.layers import GROUP_NAME, SketchLayers
from terrain_sketch.qgis_io.raster_io import WorkingFiles, read_dem


def _layers(tmp_path):
    dem = dem_layer(tmp_path)
    grid, info = read_dem(dem)
    files = WorkingFiles(str(tmp_path / "s"), grid, info)
    return grid, files, SketchLayers(QgsProject.instance(), dem, files.working_path, files.change_path)


def test_group_holds_the_four_layers_in_order(tmp_path):
    _, _, layers = _layers(tmp_path)
    group = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME)
    assert [n.layer().name() for n in group.findLayers()] == [
        "Sketch outlines", "Change (new − original)", "Hillshade", "Modified DEM"]
    assert not group.findLayer(layers.hillshade.id()).itemVisibilityChecked()
    assert type(layers.change.renderer()).__name__ == "QgsSingleBandPseudoColorRenderer"
    assert type(layers.hillshade.renderer()).__name__ == "QgsHillshadeRenderer"


def test_refresh_shows_new_values_and_outlines_update(tmp_path):
    grid, files, layers = _layers(tmp_path)
    working = grid.copy()
    working.data[2, 3] = 15.0
    files.write(Window(2, 3, 1, 1), working)
    layers.refresh()
    x, y = world(3, 2)
    assert layers.working.dataProvider().sample(QgsPointXY(x, y), 1)[0] == 15.0
    triangle = QgsGeometry.fromWkt(f"POLYGON(({x} {y}, {x + 5} {y}, {x + 5} {y - 5}, {x} {y}))")
    layers.set_outlines([("Pond", "Lower flat", triangle)])
    assert layers.outlines.featureCount() == 1


def test_remove_takes_the_group_and_its_layers_away(tmp_path):
    _, _, layers = _layers(tmp_path)
    layers.remove()
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None
    assert all(QgsProject.instance().mapLayer(i) is None for i in layers.layer_ids)


def test_hillshade_toggle_and_cleanup_tolerate_layers_the_user_removed(tmp_path):
    _, _, layers = _layers(tmp_path)
    group = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME)
    layers.set_hillshade_visible(True)
    assert group.findLayer(layers.hillshade_id).itemVisibilityChecked()
    QgsProject.instance().removeMapLayers([layers.hillshade_id, layers.outlines_id])  # the user deletes two layers
    layers.set_hillshade_visible(False)
    layers.refresh()
    layers.set_outlines([])
    layers.remove()
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None
    assert all(QgsProject.instance().mapLayer(i) is None for i in layers.layer_ids)
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_layers.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.qgis_io.layers'`

- [ ] **Step 3: Implement the layer group**

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
        self.group = project.layerTreeRoot().insertGroup(0, GROUP_NAME)
        for layer in (self.outlines, self.change, self.hillshade, self.working):
            project.addMapLayer(layer, False)
            self.group.addLayer(layer)
        self.group.findLayer(self.hillshade.id()).setItemVisibilityChecked(False)
        self.layer_ids = [layer.id() for layer in (self.outlines, self.change, self.hillshade, self.working)]
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
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_layers.py` → Expected: `4 passed`
Run: `scripts/test.sh` → Expected: `91 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/qgis_io/layers.py tests/qgis/test_layers.py
git commit -m "feat(qgis_io): Terrain Sketch layer group with change and hillshade"
```

---

### Task 5: Help texts and the SketchController

**Files:**
- Create: `terrain_sketch/gui/__init__.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/controller.py`
- Test: `tests/qgis/test_controller.py`

**Interfaces:**
- Consumes: `FeatureStack`, `FeatureStats`, `new_feature`, `to_dem_wkb/from_wkb`, `read_dem/WorkingFiles/export_dem`, `SketchLayers`.
- Produces (`help_texts.py`): `TOOL_LABELS`, `TOOL_SUMMARIES` (dict by `Tool`), `PIXEL_MODE_LABELS`, `PIXEL_MODE_TIPS` (dict by `PixelMode`), `FLAG_TEXTS` (dict by `FLAG_*`), `DRAW_HINT`, `NO_SESSION`, `amount_label(tool) -> "Height" | "Depth" | None`.
- Produces (`controller.py`): `SketchController(project, parent=None)` (a `QObject`) with signals `featuresChanged()`, `sessionChanged()`, `message(level, text)`; attributes `project`, `stack`, `info`, `files`, `layers`, `dem_layer_id`, `dem_crs`; properties `has_dem`, `features` (tuple); methods `feature(fid)`, `stats(fid)`, `feature_geometry(fid)`, `set_dem(layer)` (raises `DemError` before changing anything), `close()`, `shutdown()`, `add_drawn(tool, mode, geometry, crs) -> TerrainFeature | None` (None, with a message, when the drawing cannot be used or no session is active; names "Raise path 1", "Raise path 2", …), `update_feature(fid, **changes)`, `set_enabled(fid, enabled)`, `delete_feature(fid)`, `reorder(ids)` (`ValueError` unless every id exactly once), `export_dem(path)` (raises `RuntimeError(NO_SESSION)` without a session), `set_hillshade_visible(bool)`. Every change runs `FeatureStack.update`, writes the changed window, refreshes the layers and outlines, then emits `featuresChanged`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_controller.py`
```python
import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, read_tif, sample, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.qgis_io.layers import GROUP_NAME
from terrain_sketch.qgis_io.raster_io import DemError


def test_drawing_a_dike_updates_the_modified_dem(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dike.name == "Raise path 1" and c.features == (dike,)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)  # 1 m above the flat 10 m ground
    assert sample(c.layers.change, 20, 20) == pytest.approx(1.0)
    assert c.stats(dike.id).fill > 0 and c.layers.outlines.featureCount() == 1


def test_editing_toggling_and_deleting_recompute(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=2.5)
    assert sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    c.set_enabled(dike.id, False)
    assert sample(c.layers.working, 20, 20) == pytest.approx(10.0)
    assert c.layers.outlines.featureCount() == 0
    c.delete_feature(dike.id)
    assert c.features == ()


def test_names_are_unique_and_reorder_changes_the_order(tmp_path):
    c = start_session(tmp_path)
    a = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 10, 30, 10), UTM)
    b = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 30, 30, 30), UTM)
    assert (a.name, b.name) == ("Add to terrain 1", "Add to terrain 2")
    c.reorder([b.id, a.id])
    assert [f.id for f in c.features] == [b.id, a.id]
    with pytest.raises(ValueError):
        c.reorder([a.id])


def test_an_unusable_drawing_is_reported_and_not_added(tmp_path):
    c = start_session(tmp_path)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_drawn(Tool.RAISE_FLAT, Mode.AREA, line_through(5, 5, 10, 10), UTM) is None
    assert c.features == () and messages


def test_export_writes_the_modified_dem(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.export_dem(str(tmp_path / "out.tif"))
    exported, _ = read_tif(tmp_path / "out.tif")
    assert exported[20, 20] == pytest.approx(11.0) and exported[0, 0] == pytest.approx(10.0)


def test_removing_the_dem_layer_ends_the_session(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    QgsProject.instance().removeMapLayer(c.dem_layer_id)
    assert not c.has_dem and c.features == () and messages
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None


def test_a_geographic_dem_is_refused_without_side_effects(tmp_path):
    c = SketchController(QgsProject.instance())
    with pytest.raises(DemError):
        c.set_dem(dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001)))
    assert not c.has_dem
    assert QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME) is None


def test_drawing_or_exporting_without_a_session_is_reported_not_raised(tmp_path):
    c = start_session(tmp_path)
    c.close()  # e.g. the DEM layer was removed while the user was still drawing
    messages = []
    c.message.connect(lambda level, text: messages.append(text))
    assert c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM) is None
    assert messages and not c.dem_crs.isValid()
    with pytest.raises(RuntimeError, match="Start"):
        c.export_dem(str(tmp_path / "out.tif"))
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_controller.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui'`

- [ ] **Step 3: Implement help texts and the controller**

**File:** `terrain_sketch/gui/__init__.py`
```python
"""Terrain Sketch user interface: controller, docks, panels and map tools."""
```
**File:** `terrain_sketch/gui/help_texts.py`
```python
"""User-facing names, descriptions and messages in one place (extended in Plan 5)."""
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

DRAW_HINT = ("Click to add points. Right-click or press Enter to finish, Backspace removes the last "
             "point, Esc cancels.")

NO_SESSION = "Pick a DEM and press Start first."


def amount_label(tool: Tool) -> str | None:
    """Label of the amount field, or None when the tool has no amount."""
    if tool is Tool.INTERPOLATE:
        return None
    if tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT):
        return "Depth"
    return "Height"
```
**File:** `terrain_sketch/gui/controller.py`
```python
"""SketchController: the one place where the GUI talks to the engine, the files and the layers."""
from __future__ import annotations

import tempfile
import traceback
from dataclasses import replace

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsGeometry, QgsMessageLog, QgsProject
from qgis.PyQt.QtCore import QObject, pyqtSignal

from ..core.engine import FeatureStack
from ..core.operations import FeatureStats
from ..core.tools import Mode, Tool
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import WorkingFiles, export_dem, read_dem
from .help_texts import NO_SESSION, TOOL_LABELS

LOG_TAG = "Terrain Sketch"


class SketchController(QObject):
    """Owns the session: the DEM, the ordered feature list, the engine, the files and the layers."""

    featuresChanged = pyqtSignal()
    sessionChanged = pyqtSignal()
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
        project.layersRemoved.connect(self._on_layers_removed)
        project.cleared.connect(self._drop_session)

    @property
    def has_dem(self) -> bool:
        return self.stack is not None

    @property
    def features(self) -> tuple:
        return tuple(self._features)

    def feature(self, fid: str) -> TerrainFeature:
        return next(f for f in self._features if f.id == fid)

    def stats(self, fid: str) -> FeatureStats:
        return self.stack.stats.get(fid, FeatureStats()) if self.stack else FeatureStats()

    def feature_geometry(self, fid: str) -> QgsGeometry:
        """The feature's drawn geometry in the DEM CRS."""
        return from_wkb(self.feature(fid).geometry_wkb)

    def set_dem(self, layer) -> None:
        """Start a new session on `layer`. Raises DemError (user-facing message) before changing anything."""
        grid, info = read_dem(layer)
        self.close()
        self.stack = FeatureStack(grid)
        self.info = info
        self.files = WorkingFiles(tempfile.mkdtemp(prefix="terrain_sketch_"), grid, info)
        self.layers = SketchLayers(self.project, layer, self.files.working_path, self.files.change_path)
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

    def add_drawn(self, tool: Tool, mode: Mode, geometry: QgsGeometry, crs) -> TerrainFeature | None:
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
        feature = new_feature(tool, mode, wkb, self.stack.original.cell_size, name=self._unique_name(tool))
        self._set([*self._features, feature])
        return feature

    def update_feature(self, fid: str, **changes) -> None:
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

    def export_dem(self, path: str) -> None:
        """Write the modified DEM to `path`; raises RuntimeError without a session."""
        if not self.has_dem:
            raise RuntimeError(NO_SESSION)
        export_dem(path, self.stack.working, self.info)

    def set_hillshade_visible(self, visible: bool) -> None:
        if self.layers is not None:
            self.layers.set_hillshade_visible(visible)

    def _set(self, features) -> None:
        self._features = list(features)
        try:
            window = self.stack.update(self._features)
            if window is not None:
                self.files.write(window, self.stack.working)
                self.layers.refresh()
            self.layers.set_outlines(self._outline_items())
        except Exception:  # noqa: BLE001 — never let an engine error take QGIS down
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Sketch could not update the terrain; "
                                                          "see the 'Terrain Sketch' log tab for details.")
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

    def _drop_session(self) -> None:
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
        if ids & ({self.dem_layer_id} | set(self.layers.layer_ids)):
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, "The Terrain Sketch session ended because its DEM "
                                                         "or result layers were removed.")
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_controller.py` → Expected: `8 passed`
Run: `scripts/test.sh` → Expected: `99 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui tests/qgis/test_controller.py
git commit -m "feat(gui): SketchController session with working files, layers and messages"
```

---

### Task 6: Drawing map tools

**Files:**
- Create: `terrain_sketch/gui/map_tools/__init__.py`, `terrain_sketch/gui/map_tools/base.py`, `terrain_sketch/gui/map_tools/draw_line.py`, `terrain_sketch/gui/map_tools/draw_polygon.py`
- Test: `tests/qgis/test_map_tools.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (QGIS GUI API only).
- Produces: `DrawTool(canvas)` (`QgsMapTool`) with signals `finished(QgsGeometry in the canvas CRS)` and `cancelled()`, attributes `points`, `band`, `snap_indicator`, class attributes `geometry_type`, `min_vertices`, and methods `build_geometry(points)`, `finish()`, `reset()`; `DrawLineTool` (line, ≥ 2 vertices); `DrawPolygonTool` (polygon, ≥ 3 corners, ring closed explicitly).

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_map_tools.py`
```python
from qgis.gui import QgsMapMouseEvent
from qgis.PyQt.QtCore import QEvent, QPoint, Qt
from qgis.PyQt.QtGui import QKeyEvent

from qgis_helpers import fake_iface
from terrain_sketch.gui.map_tools.draw_line import DrawLineTool
from terrain_sketch.gui.map_tools.draw_polygon import DrawPolygonTool


def click(tool, canvas, x, y, button=Qt.MouseButton.LeftButton):
    tool.canvasReleaseEvent(QgsMapMouseEvent(canvas, QEvent.Type.MouseButtonRelease, QPoint(x, y), button, button,
                                             Qt.KeyboardModifier.NoModifier))


def press(tool, key):
    tool.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_line_tool_emits_the_clicked_line_on_right_click():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 200, 10)
    click(tool, canvas, 0, 0, Qt.MouseButton.RightButton)
    assert len(drawn) == 1 and len(drawn[0].asPolyline()) == 2 and tool.points == []


def test_backspace_removes_the_last_point_and_escape_cancels():
    canvas = fake_iface().mapCanvas()
    tool = DrawLineTool(canvas)
    cancelled = []
    tool.cancelled.connect(lambda: cancelled.append(True))
    for x in (10, 50, 90):
        click(tool, canvas, x, 10)
    press(tool, Qt.Key.Key_Backspace)
    assert len(tool.points) == 2
    press(tool, Qt.Key.Key_Escape)
    assert tool.points == [] and cancelled == [True]


def test_a_polygon_needs_three_corners_and_enter_finishes_it():
    canvas = fake_iface().mapCanvas()
    tool = DrawPolygonTool(canvas)
    drawn = []
    tool.finished.connect(drawn.append)
    click(tool, canvas, 10, 10)
    click(tool, canvas, 100, 10)
    press(tool, Qt.Key.Key_Return)
    assert drawn == []
    click(tool, canvas, 100, 100)
    press(tool, Qt.Key.Key_Return)
    assert len(drawn) == 1 and drawn[0].area() > 0
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_map_tools.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui.map_tools'`

- [ ] **Step 3: Implement the tools**

**File:** `terrain_sketch/gui/map_tools/__init__.py`
```python
"""Map tools for drawing Terrain Sketch features on the canvas."""
```
**File:** `terrain_sketch/gui/map_tools/base.py`
```python
"""Shared behaviour of the drawing tools: snapping, rubber band and QGIS digitizing keys."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointLocator, QgsPointXY
from qgis.gui import QgsMapTool, QgsMapToolEdit, QgsRubberBand, QgsSnapIndicator
from qgis.PyQt.QtCore import Qt, pyqtSignal


class DrawTool(QgsMapTool):
    """Click vertices like in QGIS digitizing: right-click or Enter finishes, Backspace or
    Delete removes the last vertex, Esc cancels. Snaps with the project's snapping settings."""

    finished = pyqtSignal(object)  # QgsGeometry in the canvas CRS
    cancelled = pyqtSignal()

    geometry_type = Qgis.GeometryType.Line
    min_vertices = 2

    def __init__(self, canvas):
        super().__init__(canvas)
        self.points: list[QgsPointXY] = []
        self.band = QgsRubberBand(canvas, self.geometry_type)
        self.band.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.band.setFillColor(QgsMapToolEdit.digitizingFillColor())
        self.band.setWidth(QgsMapToolEdit.digitizingStrokeWidth())
        self.snap_indicator = QgsSnapIndicator(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def build_geometry(self, points: list[QgsPointXY]) -> QgsGeometry:
        return QgsGeometry.fromPolylineXY(points)

    def canvasMoveEvent(self, event):  # noqa: N802 — Qt override
        self._redraw(self._snap(event))

    def canvasReleaseEvent(self, event):  # noqa: N802 — Qt override
        if event.button() == Qt.MouseButton.RightButton:
            self.finish()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.points.append(self._snap(event))
            self._redraw()

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        key = event.key()
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and self.points:
            self.points.pop()
            self._redraw()
            event.accept()
        elif key == Qt.Key.Key_Escape:
            self.reset()
            self.cancelled.emit()
            event.accept()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish()
            event.accept()
        else:
            event.ignore()

    def finish(self) -> None:
        """Emit the drawn geometry; does nothing until there are enough vertices."""
        if len(self.points) < self.min_vertices:
            return
        geometry = self.build_geometry(self.points)
        self.reset()
        self.finished.emit(geometry)

    def reset(self) -> None:
        self.points = []
        self.band.reset(self.geometry_type)
        self.snap_indicator.setMatch(QgsPointLocator.Match())

    def deactivate(self):
        self.reset()
        super().deactivate()

    def _snap(self, event) -> QgsPointXY:
        match = self.canvas().snappingUtils().snapToMap(event.mapPoint())
        self.snap_indicator.setMatch(match)
        return match.point() if match.isValid() else event.mapPoint()

    def _redraw(self, hover: QgsPointXY | None = None) -> None:
        points = self.points + ([hover] if hover is not None and self.points else [])
        self.band.reset(self.geometry_type)
        for i, point in enumerate(points):
            self.band.addPoint(point, i == len(points) - 1)
```
**File:** `terrain_sketch/gui/map_tools/draw_line.py`
```python
"""Draw a line by clicking its vertices."""
from __future__ import annotations

from qgis.core import Qgis

from .base import DrawTool


class DrawLineTool(DrawTool):
    geometry_type = Qgis.GeometryType.Line
    min_vertices = 2
```
**File:** `terrain_sketch/gui/map_tools/draw_polygon.py`
```python
"""Draw an area by clicking its corners."""
from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointXY

from .base import DrawTool


class DrawPolygonTool(DrawTool):
    geometry_type = Qgis.GeometryType.Polygon
    min_vertices = 3

    def build_geometry(self, points: list[QgsPointXY]) -> QgsGeometry:
        return QgsGeometry.fromPolygonXY([points + [points[0]]])
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_map_tools.py` → Expected: `3 passed`
Run: `scripts/test.sh` → Expected: `102 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/map_tools tests/qgis/test_map_tools.py
git commit -m "feat(gui): line and area drawing tools with snapping and digitizing keys"
```

---

### Task 7: The feature list

**Files:**
- Create: `terrain_sketch/gui/feature_list.py`
- Test: `tests/qgis/test_feature_list.py`

**Interfaces:**
- Consumes: `SketchController` (Task 5), `FLAG_TEXTS`, `TOOL_LABELS`.
- Produces: `ID_ROLE = Qt.ItemDataRole.UserRole`, `MIME_TYPE`; `FeatureListModel(controller, parent=None)` (rows mirror `controller.features`; `DisplayRole`/`EditRole` name, `CheckStateRole` enabled, `DecorationRole` warning icon when flagged, `ToolTipRole` tool label plus flag texts; `setData` renames/toggles through the controller; drag-and-drop reorders through `controller.reorder`; `row_of(fid)`); `FeatureListView(model, parent=None)` with `selected_id()`, `select_id(fid)`, and selection kept across model resets.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_feature_list.py`
```python
from qgis.core import QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import QModelIndex, Qt

from qgis_helpers import UTM, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.feature_list import ID_ROLE, FeatureListModel, FeatureListView


def test_feature_list_edits_go_through_the_controller(tmp_path):
    c = start_session(tmp_path)
    a, b, d = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20, 30))
    model = FeatureListModel(c)
    assert model.rowCount() == 3 and model.data(model.index(0)) == a.name
    model.setData(model.index(1), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert not c.feature(b.id).enabled
    model.setData(model.index(2), "Barrier", Qt.ItemDataRole.EditRole)
    assert c.feature(d.id).name == "Barrier"
    model.dropMimeData(model.mimeData([model.index(0)]), Qt.DropAction.MoveAction, 3, 0, QModelIndex())
    assert [f.id for f in c.features] == [b.id, d.id, a.id]
    assert [model.data(model.index(r), ID_ROLE) for r in range(3)] == [b.id, d.id, a.id]


def test_flagged_features_show_a_warning(tmp_path):
    c = start_session(tmp_path)
    far = QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(10, 10)])
    c.add_drawn(Tool.ADD, Mode.PATH, far, UTM)
    model = FeatureListModel(c)
    assert "outside the DEM" in model.data(model.index(0), Qt.ItemDataRole.ToolTipRole)
    assert model.data(model.index(0), Qt.ItemDataRole.DecorationRole) is not None


def test_selection_survives_edits_and_list_changes(tmp_path):
    c = start_session(tmp_path)
    a, b = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20))
    view = FeatureListView(FeatureListModel(c))
    view.select_id(b.id)
    c.update_feature(b.id, amount=2.0)
    assert view.selected_id() == b.id
    c.delete_feature(a.id)
    assert view.selected_id() == b.id
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_feature_list.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui.feature_list'`

- [ ] **Step 3: Implement the list**

**File:** `terrain_sketch/gui/feature_list.py`
```python
"""The feature list: on/off checkbox, editable name and warning icon; drag rows to reorder."""
from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QAbstractListModel, QItemSelectionModel, QMimeData, QModelIndex, Qt
from qgis.PyQt.QtWidgets import QAbstractItemView, QListView

from .help_texts import FLAG_TEXTS, TOOL_LABELS

ID_ROLE = Qt.ItemDataRole.UserRole
MIME_TYPE = "application/x-terrain-sketch-feature-ids"


class FeatureListModel(QAbstractListModel):
    """Rows mirror the controller's feature list; every edit goes through the controller."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._ids: list[str] = []
        controller.featuresChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        ids = [f.id for f in self.controller.features]
        if ids == self._ids:
            if ids:
                self.dataChanged.emit(self.index(0), self.index(len(ids) - 1))
            return
        self.beginResetModel()
        self._ids = ids
        self.endResetModel()

    def row_of(self, fid: str) -> int:
        return self._ids.index(fid) if fid in self._ids else -1

    def rowCount(self, parent=QModelIndex()):  # noqa: N802 — Qt override
        return 0 if parent.isValid() else len(self._ids)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        features = {f.id: f for f in self.controller.features}
        feature = features.get(self._ids[index.row()])
        if feature is None:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return feature.name
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if feature.enabled else Qt.CheckState.Unchecked
        if role == ID_ROLE:
            return feature.id
        flags = self.controller.stats(feature.id).flags
        if role == Qt.ItemDataRole.DecorationRole and flags:
            return QgsApplication.getThemeIcon("/mIconWarning.svg")
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join([TOOL_LABELS[feature.tool]] + [FLAG_TEXTS[flag] for flag in flags])
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802 — Qt override
        if not index.isValid():
            return False
        fid = self._ids[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole:
            self.controller.set_enabled(fid, Qt.CheckState(value) == Qt.CheckState.Checked)
            return True
        if role == Qt.ItemDataRole.EditRole and str(value).strip():
            self.controller.update_feature(fid, name=str(value).strip())
            return True
        return False

    def supportedDropActions(self):  # noqa: N802 — Qt override
        return Qt.DropAction.MoveAction

    def mimeTypes(self):  # noqa: N802 — Qt override
        return [MIME_TYPE]

    def mimeData(self, indexes):  # noqa: N802 — Qt override
        data = QMimeData()
        data.setData(MIME_TYPE, "\n".join(self._ids[i.row()] for i in indexes).encode())
        return data

    def dropMimeData(self, data, action, row, column, parent):  # noqa: N802 — Qt override
        if action != Qt.DropAction.MoveAction or not data.hasFormat(MIME_TYPE):
            return False
        moving = bytes(data.data(MIME_TYPE)).decode().split("\n")
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._ids)
        before = [i for i in self._ids[:row] if i not in moving]
        after = [i for i in self._ids[row:] if i not in moving]
        self.controller.reorder(before + moving + after)
        return False  # the model already reordered itself; the view must not remove the dragged rows


class FeatureListView(QListView):
    """List view with drag-to-reorder that keeps the selected feature across model resets."""

    def __init__(self, model: FeatureListModel, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._remembered = None
        model.modelAboutToBeReset.connect(self._remember)
        model.modelReset.connect(self._restore)

    def selected_id(self) -> str | None:
        indexes = self.selectionModel().selectedIndexes()
        return indexes[0].data(ID_ROLE) if indexes else None

    def select_id(self, fid: str | None) -> None:
        row = self.model().row_of(fid) if fid else -1
        if row < 0:
            self.clearSelection()
            return
        self.selectionModel().setCurrentIndex(self.model().index(row),
                                              QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def _remember(self) -> None:
        self._remembered = self.selected_id()

    def _restore(self) -> None:
        self.select_id(self._remembered)
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_feature_list.py` → Expected: `3 passed`
Run: `scripts/test.sh` → Expected: `105 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/feature_list.py tests/qgis/test_feature_list.py
git commit -m "feat(gui): feature list with toggling, renaming, warnings and drag-to-reorder"
```

---

### Task 8: Tool gallery and properties page

**Files:**
- Create: `terrain_sketch/gui/tool_gallery.py`, `terrain_sketch/gui/properties_page.py`
- Test: `tests/qgis/test_panels.py`

**Interfaces:**
- Consumes: `SketchController` (Task 5), `TOOL_INFO`, the help texts.
- Produces: `ToolGallery(parent=None)` with signal `drawRequested(Tool, Mode)`, widgets `tool_list`, `summary`, `line_button`, `area_button` (enabled only for the modes the selected tool supports), methods `selected_tool()`, `select_tool(tool)`; `PropertiesPage(controller, parent=None)` with `show_feature(fid)`, widgets `title`, `summary`, `amount_label`, `amount`, `width`, `slope`, `reach`, `slope_position`, `pixel_mode`, `problems`, and `form` (a `QFormLayout` whose rows are shown per tool and mode); every value change calls `controller.update_feature`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_panels.py`
```python
import pytest

from qgis_helpers import UTM, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.tool_gallery import ToolGallery


def test_gallery_offers_only_the_modes_a_tool_supports():
    gallery = ToolGallery()
    assert not gallery.line_button.isEnabled() and not gallery.area_button.isEnabled()
    gallery.select_tool(Tool.RAISE_PATH)
    assert gallery.line_button.isEnabled() and not gallery.area_button.isEnabled()
    gallery.select_tool(Tool.LOWER_FLAT)
    requests = []
    gallery.drawRequested.connect(lambda tool, mode: requests.append((tool, mode)))
    gallery.area_button.click()
    assert requests == [(Tool.LOWER_FLAT, Mode.AREA)]


def test_properties_show_the_tool_fields_and_apply_changes(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount_label.text() == "Height"
    assert page.form.isRowVisible(page.width) and page.form.isRowVisible(page.slope)
    assert not page.form.isRowVisible(page.slope_position)
    page.amount.setValue(2.5)
    assert c.feature(dike.id).amount == 2.5 and sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    page.show_feature(pond.id)
    assert page.amount_label.text() == "Depth" and not page.form.isRowVisible(page.width)
    assert page.form.isRowVisible(page.slope_position) and page.slope_position.currentData() is True
    page.pixel_mode.setCurrentIndex(page.pixel_mode.findData(PixelMode.ALL_TOUCHED.value))
    assert c.feature(pond.id).pixel_mode is PixelMode.ALL_TOUCHED
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_panels.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui.properties_page'`

- [ ] **Step 3: Implement the panels**

**File:** `terrain_sketch/gui/tool_gallery.py`
```python
"""'What do you want to build?' — the tool list and the 'Where?' buttons (illustrated in Plan 5)."""
from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout, QWidget

from ..core.tools import TOOL_INFO, Mode, Tool
from .help_texts import TOOL_LABELS, TOOL_SUMMARIES


class ToolGallery(QWidget):
    drawRequested = pyqtSignal(object, object)  # Tool, Mode

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(self.tr("What do you want to build?")))
        self.tool_list = QListWidget()
        for tool in Tool:
            item = QListWidgetItem(TOOL_LABELS[tool])
            item.setData(Qt.ItemDataRole.UserRole, tool.value)
            item.setToolTip(TOOL_SUMMARIES[tool])
            self.tool_list.addItem(item)
        layout.addWidget(self.tool_list)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        layout.addWidget(QLabel(self.tr("Where?")))
        row = QHBoxLayout()
        self.line_button = self._where_button("/mActionCaptureLine.svg", self.tr("Draw line"), Mode.PATH)
        self.area_button = self._where_button("/mActionCapturePolygon.svg", self.tr("Draw area"), Mode.AREA)
        row.addWidget(self.line_button)
        row.addWidget(self.area_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self._tool_changed()

    def selected_tool(self) -> Tool | None:
        item = self.tool_list.currentItem()
        return Tool(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def select_tool(self, tool: Tool) -> None:
        for row in range(self.tool_list.count()):
            if self.tool_list.item(row).data(Qt.ItemDataRole.UserRole) == tool.value:
                self.tool_list.setCurrentRow(row)

    def _where_button(self, icon: str, text: str, mode: Mode) -> QToolButton:
        button = QToolButton()
        button.setIcon(QgsApplication.getThemeIcon(icon))
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.clicked.connect(lambda _checked=False, m=mode: self._draw(m))
        return button

    def _tool_changed(self, *_args) -> None:
        tool = self.selected_tool()
        self.summary.setText(TOOL_SUMMARIES[tool] if tool else self.tr("Pick a tool, then choose where to draw it."))
        modes = TOOL_INFO[tool].modes if tool else ()
        self.line_button.setEnabled(Mode.PATH in modes)
        self.area_button.setEnabled(Mode.AREA in modes)

    def _draw(self, mode: Mode) -> None:
        tool = self.selected_tool()
        if tool is not None:
            self.drawRequested.emit(tool, mode)
```
**File:** `terrain_sketch/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.tools import TOOL_INFO, Mode, PixelMode
from .help_texts import FLAG_TEXTS, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS, TOOL_LABELS, TOOL_SUMMARIES, amount_label


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
        self.width = _spin(0.1, 500.0, 0.5, " m", 2)
        self.width.setToolTip(self.tr("Width of the crest (raise tools) or the bottom (lower tools) of the path."))
        self.slope = _spin(0.0, 50.0, 0.5, "", 1)
        self.slope.setPrefix("1 : ")
        self.slope.setToolTip(self.tr("Horizontal metres per metre of height: 1 : 3 goes 3 m outwards for every "
                                      "1 m. 0 means no side slopes."))
        self.reach = _spin(0.0, 500.0, 1.0, " m", 1)
        self.reach.setToolTip(self.tr("Side slopes stop this far from the edge, even if they have not met the "
                                      "ground yet."))
        self.slope_position = QComboBox()
        self.slope_position.addItem(self.tr("Outside the outline"), False)
        self.slope_position.addItem(self.tr("Inside the outline"), True)
        self.slope_position.setToolTip(self.tr("Inside: the outline is the top edge (e.g. a pond). Outside: the "
                                               "outline is the flat part (e.g. a raised pad)."))
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
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        layout.addLayout(self.form)
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
        controller.featuresChanged.connect(self._refresh_problems)

    def show_feature(self, fid: str) -> None:
        self._fid = fid
        feature = self.controller.feature(fid)
        info = TOOL_INFO[feature.tool]
        label = amount_label(feature.tool)
        self._loading = True
        try:
            self.title.setText(f"{feature.name} · {TOOL_LABELS[feature.tool]}")
            self.summary.setText(TOOL_SUMMARIES[feature.tool])
            self.amount_label.setText(self.tr(label) if label else "")
            self.amount.setValue(feature.amount)
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
        finally:
            self._loading = False
        self._refresh_problems()

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
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_panels.py` → Expected: `2 passed`
Run: `scripts/test.sh` → Expected: `107 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/tool_gallery.py terrain_sketch/gui/properties_page.py tests/qgis/test_panels.py
git commit -m "feat(gui): tool gallery and live properties page"
```

---

### Task 9: Main dock, plugin entry point and developer install

**Files:**
- Create: `terrain_sketch/gui/main_dock.py`, `terrain_sketch/plugin.py`, `terrain_sketch/metadata.txt`, `terrain_sketch/icons/terrain_sketch.svg`, `scripts/dev_install.sh`
- Modify: `terrain_sketch/__init__.py` (adds `classFactory`)
- Test: `tests/qgis/test_dock_plugin.py`

**Interfaces:**
- Consumes: everything from Tasks 2–8.
- Produces: `PAGE_START, PAGE_GALLERY, PAGE_PROPERTIES = 0, 1, 2`; `MainDock(iface, controller, parent=None)` (`QgsDockWidget`, object name `TerrainSketchDock`) with widgets `dem_combo`, `start_button`, `export_button`, `hillshade_box`, `model`, `feature_view`, `new_button`, `delete_button`, `hint`, `pages`, `gallery`, `properties`, attribute `draw_tool`, replaceable callables `confirm(text) -> bool` and `ask_export_path() -> str`, and `end_drawing()`; `TerrainSketchPlugin(iface)` with `initGui()`, `unload()`, attributes `action`, `dock`, `controller`; `classFactory(iface)`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_dock_plugin.py`
```python
import pytest
from qgis.core import QgsProject

from qgis_helpers import dem_layer, fake_iface, line_through, sample
from terrain_sketch import classFactory
from terrain_sketch.core.tools import Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.main_dock import PAGE_GALLERY, PAGE_PROPERTIES, PAGE_START, MainDock


def test_drawing_a_dike_from_the_panel(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    assert dock.pages.currentIndex() == PAGE_START and not dock.new_button.isEnabled()
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert controller.has_dem and dock.pages.currentIndex() == PAGE_GALLERY
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.line_button.click()
    assert iface.mapCanvas().mapTool() is dock.draw_tool and not dock.hint.isHidden()
    dock.draw_tool.finished.emit(line_through(5, 20, 34, 20))
    assert len(controller.features) == 1
    assert dock.feature_view.selected_id() == controller.features[0].id
    assert dock.pages.currentIndex() == PAGE_PROPERTIES and dock.hint.isHidden() and dock.draw_tool is None
    assert sample(controller.layers.working, 20, 20) == pytest.approx(11.0)
    dock.ask_export_path = lambda: str(tmp_path / "exported.tif")
    dock.export_button.click()
    assert (tmp_path / "exported.tif").exists()


def test_a_geographic_dem_is_reported_in_the_message_bar(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert not dock.controller.has_dem
    iface.messageBar().pushMessage.assert_called()


def test_plugin_adds_and_removes_its_button_menu_and_panel():
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    iface.addToolBarIcon.assert_called_once_with(plugin.action)
    iface.addPluginToRasterMenu.assert_called_once()
    plugin.action.setChecked(True)
    assert plugin.dock is not None
    iface.addDockWidget.assert_called_once()
    plugin.unload()
    iface.removeToolBarIcon.assert_called_once()
    iface.removeDockWidget.assert_called_once()
    assert plugin.dock is None and plugin.controller is None and plugin.action is None
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_dock_plugin.py`
Expected: collection error `ImportError: cannot import name 'classFactory' from 'terrain_sketch'`

- [ ] **Step 3: Implement the dock, the plugin and its metadata**

**File:** `terrain_sketch/gui/main_dock.py`
```python
"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

from qgis.core import Qgis, QgsApplication, QgsCoordinateTransform, QgsProject
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import DRAW_HINT
from .map_tools.draw_line import DrawLineTool
from .map_tools.draw_polygon import DrawPolygonTool
from .properties_page import PropertiesPage
from .tool_gallery import ToolGallery

PAGE_START, PAGE_GALLERY, PAGE_PROPERTIES = range(3)


class MainDock(QgsDockWidget):
    def __init__(self, iface, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Terrain Sketch"))
        self.setObjectName("TerrainSketchDock")
        self.iface = iface
        self.controller = controller
        self.draw_tool = None
        self._previous_tool = None
        self.confirm = self._confirm_dialog  # replaceable in tests
        self.ask_export_path = self._export_dialog  # replaceable in tests

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
        self.export_button = QToolButton()
        self.export_button.setIcon(QgsApplication.getThemeIcon("/mActionFileSaveAs.svg"))
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
        list_row.addWidget(self.new_button)
        list_row.addWidget(self.delete_button)
        list_row.addStretch(1)
        layout.addLayout(list_row)

        self.hint = QLabel(self.tr(DRAW_HINT))
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
        self.hillshade_box.toggled.connect(controller.set_hillshade_visible)
        self.new_button.clicked.connect(self._new_feature)
        self.delete_button.clicked.connect(self._delete_selected)
        self.feature_view.selectionModel().selectionChanged.connect(self._selection_changed)
        self.feature_view.customContextMenuRequested.connect(self._context_menu)
        self.gallery.drawRequested.connect(self._begin_drawing)
        controller.sessionChanged.connect(self._session_changed)
        controller.message.connect(self._show_message)
        self._session_changed()

    def end_drawing(self) -> None:
        """Stop a drawing in progress and give the canvas its previous map tool back."""
        canvas = self.iface.mapCanvas()
        if self.draw_tool is not None:
            if canvas.mapTool() is self.draw_tool:
                if self._previous_tool is not None:
                    canvas.setMapTool(self._previous_tool)
                else:
                    canvas.unsetMapTool(self.draw_tool)
            self.draw_tool.deleteLater()
            self.draw_tool = None
        self.hint.hide()

    def closeEvent(self, event):  # noqa: N802 — Qt override
        self.end_drawing()
        super().closeEvent(event)

    def _session_changed(self) -> None:
        has_dem = self.controller.has_dem
        for widget in (self.export_button, self.hillshade_box, self.new_button, self.delete_button, self.feature_view):
            widget.setEnabled(has_dem)
        if self.controller.layers is not None:
            project = self.controller.project
            self.dem_combo.setExceptedLayerList([project.mapLayer(i) for i in self.controller.layers.layer_ids])
        self.pages.setCurrentIndex(PAGE_GALLERY if has_dem else PAGE_START)

    def _start(self) -> None:
        layer = self.dem_combo.currentLayer()
        if layer is None:
            return
        if self.controller.features and not self.confirm(
                self.tr("Start again on this DEM? The current features will be discarded.")):
            return
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            self._show_message(Qgis.MessageLevel.Warning, str(error))

    def _new_feature(self) -> None:
        self.feature_view.clearSelection()
        self.pages.setCurrentIndex(PAGE_GALLERY)

    def _delete_selected(self) -> None:
        fid = self.feature_view.selected_id()
        if fid is not None:
            self.controller.delete_feature(fid)

    def _selection_changed(self, *_args) -> None:
        fid = self.feature_view.selected_id()
        if fid is not None:
            self.properties.show_feature(fid)
            self.pages.setCurrentIndex(PAGE_PROPERTIES)
        elif self.controller.has_dem:
            self.pages.setCurrentIndex(PAGE_GALLERY)

    def _begin_drawing(self, tool, mode) -> None:
        self.end_drawing()
        canvas = self.iface.mapCanvas()
        self.draw_tool = (DrawLineTool if mode is Mode.PATH else DrawPolygonTool)(canvas)
        self.draw_tool.finished.connect(lambda geometry, t=tool, m=mode: self._drawn(t, m, geometry))
        self.draw_tool.cancelled.connect(self.end_drawing)
        self._previous_tool = canvas.mapTool()
        canvas.setMapTool(self.draw_tool)
        self.hint.show()

    def _drawn(self, tool, mode, geometry) -> None:
        crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self.end_drawing()
        feature = self.controller.add_drawn(tool, mode, geometry, crs)
        if feature is not None:
            self.feature_view.select_id(feature.id)

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

    def _show_message(self, level, text: str) -> None:
        self.iface.messageBar().pushMessage(self.tr("Terrain Sketch"), text, level, 8)

    def _confirm_dialog(self, text: str) -> bool:
        return QMessageBox.question(self, self.tr("Terrain Sketch"), text) == QMessageBox.StandardButton.Yes

    def _export_dialog(self) -> str:
        path, _ = QFileDialog.getSaveFileName(self, self.tr("Export modified DEM"), "", self.tr("GeoTIFF (*.tif)"))
        if path and not path.lower().endswith((".tif", ".tiff")):
            path += ".tif"
        return path
```
**File:** `terrain_sketch/plugin.py`
```python
"""Plugin entry point: toolbar button, Raster menu entry and the Terrain Sketch panel."""
from __future__ import annotations

import os

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon

from .gui.controller import SketchController
from .gui.main_dock import MainDock
from .qgis_io.compat import gdal_problems

MENU = "&Terrain Sketch"


class TerrainSketchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.controller = None

    def initGui(self):  # noqa: N802 — QGIS plugin API
        icon = QIcon(os.path.join(os.path.dirname(__file__), "icons", "terrain_sketch.svg"))
        self.action = QAction(icon, "Terrain Sketch", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.setToolTip("Sketch dikes, ditches, ponds and other features onto a DEM")
        self.action.toggled.connect(self._toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToRasterMenu(MENU, self.action)

    def unload(self):
        if self.dock is not None:
            self.dock.end_drawing()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.controller is not None:
            self.controller.shutdown()
            self.controller = None
        if self.action is not None:
            self.iface.removePluginRasterMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def _toggle(self, checked: bool) -> None:
        if checked and self.dock is None and not self._create_dock():
            self.action.setChecked(False)
            return
        if self.dock is not None:
            self.dock.setUserVisible(checked)

    def _create_dock(self) -> bool:
        problems = gdal_problems()
        if problems:
            self.iface.messageBar().pushCritical("Terrain Sketch", " ".join(problems))
            return False
        self.controller = SketchController(QgsProject.instance())
        self.dock = MainDock(self.iface, self.controller, self.iface.mainWindow())
        self.dock.closedStateChanged.connect(lambda closed: self.action.setChecked(not closed))
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        return True
```
**File:** `terrain_sketch/__init__.py`
```python
"""Terrain Sketch QGIS plugin."""


def classFactory(iface):  # noqa: N802 — name required by QGIS
    from .plugin import TerrainSketchPlugin

    return TerrainSketchPlugin(iface)
```
**File:** `terrain_sketch/metadata.txt`
```ini
[general]
name=Terrain Sketch
qgisMinimumVersion=4.0
qgisMaximumVersion=4.99
description=Sketch dikes, ditches, ponds and other landscape features onto a DEM, non-destructively.
about=Draw terrain modifications straight onto a DEM: raise or lower paths (dikes, ditches), flat pads and basins, interpolated surfaces, and add/subtract relief. Every feature stays editable in a list; the original DEM is never changed. Export the modified DEM as a GeoTIFF for your flood simulation.
version=0.2.0
author=Niklas Jordan
email=hello@niklasjordan.com
category=Raster
icon=icons/terrain_sketch.svg
experimental=True
tags=dem,terrain,flood,suds,dike,pond,landscape
```
**File:** `terrain_sketch/icons/terrain_sketch.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <path d="M2 27 L11 15 L16 21 L21 13 L30 27 Z" fill="#8c6d46"/>
  <path d="M2 27 L30 27" stroke="#3a3a3a" stroke-width="1.5"/>
  <path d="M12 23 L22 23" stroke="#2f7fc1" stroke-width="2.5" stroke-linecap="round"/>
  <path d="M21 3 L28 10 L18 20 L12 20 L12 14 Z" fill="#f2c14e" stroke="#3a3a3a" stroke-width="1.2" stroke-linejoin="round"/>
</svg>
```
**File:** `scripts/dev_install.sh`
```bash
#!/usr/bin/env bash
# Link the plugin into a QGIS 4 profile for development (macOS), then enable "Terrain Sketch"
# in Plugins ▸ Manage and Install Plugins ▸ Installed. Usage: scripts/dev_install.sh [profile]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${1:-default}"
PLUGINS="$HOME/Library/Application Support/QGIS/QGIS4/profiles/$PROFILE/python/plugins"
mkdir -p "$PLUGINS"
if [ -e "$PLUGINS/terrain_sketch" ] && [ ! -L "$PLUGINS/terrain_sketch" ]; then
  echo "$PLUGINS/terrain_sketch exists and is not a link; move it away first." >&2
  exit 1
fi
ln -sfn "$ROOT/terrain_sketch" "$PLUGINS/terrain_sketch"
echo "Linked $PLUGINS/terrain_sketch -> $ROOT/terrain_sketch"
```
Run: `chmod +x scripts/dev_install.sh`

- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_dock_plugin.py` → Expected: `3 passed`
Run: `scripts/test.sh` → Expected: `110 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/__init__.py terrain_sketch/plugin.py terrain_sketch/metadata.txt terrain_sketch/icons terrain_sketch/gui/main_dock.py scripts/dev_install.sh tests/qgis/test_dock_plugin.py
git commit -m "feat: Terrain Sketch panel and plugin entry point"
```

---

## Manual check in QGIS (for the human, after merge)

1. `scripts/dev_install.sh` (links the plugin into the default QGIS 4 profile), restart QGIS 4, enable **Terrain Sketch** under Plugins ▸ Manage and Install Plugins ▸ Installed.
2. Load a projected DEM (e.g. a 0.4 m Danish DHM tile), click the Terrain Sketch toolbar button, pick the DEM, press **Start**.
3. Choose **Raise path**, **Draw line**, click a few points, right-click: the dike appears in "Modified DEM", "Change" and the outlines; change the height and slope in the panel.
4. Choose **Lower flat**, **Draw area** for a pond; tick **Hillshade**; switch a feature off and on; drag it above the dike; export and open the GeoTIFF.
5. Remove the DEM layer from the project: the session ends with a message and the Terrain Sketch group disappears.

## Roadmap: Plans 3–6

| Plan | Milestone | Builds on Plan 2 via |
|---|---|---|
| 3 | Freehand, brush, from layer, vertex editing, pixel-mode pictures, Line/Area toggle | `DrawTool`, `SketchController.add_drawn/update_feature`, `to_dem_wkb` |
| 4 | Profile dock (cross + long), live preview while dragging, `FeatureStack.terrain_before` | `FeatureStack.preview` → `Preview`, `PropertiesPage.show_feature`, `SketchController` signals |
| 5 | Illustrated gallery, help texts, tooltips, "Reproject…" button | `help_texts.py`, `ToolGallery`, `PropertiesPage` |
| 6 | Scenario GeoPackage, volumes panel, undo/redo, 3D view, duplicate, ZIP packaging | `SketchController`, `TerrainFeature.to_dict/from_dict`, `FeatureStats` |
