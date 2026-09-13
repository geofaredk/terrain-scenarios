# Terrain Sketch — Plan 4: Profiles and Live Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every feature an editable shape. A bottom dock shows the selected feature's cross profile and long profile as draggable plots, and while a handle is dragged the map shows what the change would do — without committing anything until the mouse is released.

**Architecture:** Two new core modules do the arithmetic: `sections.py` turns a feature into the point lists the editors draw (and edited points back into feature fields), and `FeatureStack` gains `terrain_before()` plus a drag-optimised `preview_for()`. Above them, `ProfileWidget` is a `QPainter` plot with draggable handles, `ProfileDock` binds two of them to the controller, and `PreviewOverlay` paints the uncommitted result on the canvas. Every edit still goes through `SketchController`.

**Tech Stack:** QGIS 4.2.2 Python API (PyQt6 via `qgis.PyQt`, Qt 6.11), GDAL 3.13, numpy, scipy.ndimage; pytest (dev-only) with a headless `QgsApplication`.

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-sketch-design.md` — §5.4 (cross and long profiles), §7.3 (the bottom dock), §8.3 steps 4-5 (preview while dragging, commit), §11 milestone 4. Plans 1-3 are merged on `main`; read the Plan 3 addendum before starting.

## Global Constraints

- Target QGIS 4.x (Qt6) only. Import Qt through `qgis.PyQt` and always use fully scoped Qt6 enums (`Qt.MouseButton.LeftButton`, `Qgis.GeometryType.Polygon`, …).
- Native look (spec §7.1, §9): only standard Qt/QGIS widgets and palette colours, QGIS theme icons via `QgsApplication.getThemeIcon`, no stylesheets. The profile dock follows QGIS's Elevation Profile: palette background, light grid, axis labels in metres.
- `terrain_sketch/core/` and `terrain_sketch/model/` never import `qgis` or `PyQt`. Widgets never call the engine, files or layers directly — only `SketchController`.
- Errors never take QGIS down: user problems become message-bar messages; unexpected engine errors are caught and logged. **An exception raised inside a Qt callback aborts the interpreter** — this has already cost this project two hard crashes, so any method reachable from a mouse or key handler must tolerate a stale feature id.
- User-facing strings live in `gui/help_texts.py`; widget captions use `self.tr()`. English only.
- Package modules start with a one-line docstring and use `from __future__ import annotations` where they have type hints; test modules need neither. 4-space indentation.
- Tests run only through `scripts/test.sh` (headless QGIS, `QT_QPA_PLATFORM=offscreen`). Never run `scripts/dev_install.sh`.
- A preview never touches the working DEM, the GeoTIFFs or the feature list. Only `update_feature` commits.
- Out of scope here (Plan 5): illustrations, rich help, `QgsSettings` persistence, the "Reproject…" button. (Plan 6): scenarios, the volumes panel, undo/redo, the 3D view, packaging.

## Decisions made while prototyping (read before implementing)

- **The drag preview has its own engine path.** `preview()` re-replays the whole stack every frame, which measured 175 ms on a 1000×1000 window — 5.7 fps against the spec's 15. `preview_for(feature_id, features)` caches the terrain *before* the dragged feature (which the drag cannot change) and replays only that feature and the ones after it: 10.1 ms, 99 fps. Same numbers at 500×500: 52 ms versus 5.2 ms.
- **The controller does not own the overlay.** It has no canvas, and reaching for one would put layer concerns in the engine boundary. It emits `previewUpdated(fid, PreviewImage)` with the bounds and the change array; `MainDock`, which already holds `iface`, owns the `PreviewOverlay` canvas item.
- **`change` is measured against the original terrain, not the working DEM** — the same convention as the session's Change layer, so the overlay and that layer agree.
- **Editing the cross profile is symmetric by default.** The checkbox mirrors edits to the other side. Asymmetric profiles are reachable by unticking it, with one known limitation recorded at the end of this plan.
- **A custom long profile disables the Height/Depth field** rather than letting two controls fight over the same heights, and "Reset to rule" re-enables it.
- **Reshaping a path rescales a custom long profile's stations** by the change in length, so a hand-edited profile keeps its shape relative to the path instead of pointing off the end.

## File Structure

| File | Responsibility |
|---|---|
| `terrain_sketch/core/sections.py` | Cross-section and long-section sampling; edited points back into feature fields; long-profile rescaling |
| `terrain_sketch/core/engine.py` | `terrain_before()`, the drag-optimised `preview_for()`, window-cache pruning, rename-is-free |
| `terrain_sketch/core/grid.py` | `window_bounds()`: a window's extent in map units, for georeferencing the overlay |
| `terrain_sketch/gui/profile_widget.py` | The plot: axes, reference terrain, design line, cut/fill shading, draggable handles |
| `terrain_sketch/gui/profile_dock.py` | The bottom dock: two plots, Symmetric, the reset buttons, and the write-back |
| `terrain_sketch/gui/overlay.py` | `PreviewOverlay` canvas item and the `change_image` colouring |
| `terrain_sketch/gui/controller.py` | `preview()`, `cancel_preview()`, `long_section()`, `find()`, throttling |
| `terrain_sketch/gui/properties_page.py` | Height/Depth disabled while the long profile is custom |
| `terrain_sketch/gui/main_dock.py`, `plugin.py` | Own the overlay, follow the selection, register the bottom dock |

---

### Task 1: The engine's drag path

**Files:**
- Modify: `terrain_sketch/core/engine.py`, `terrain_sketch/core/grid.py`
- Test: `tests/core/test_preview_drag.py`

**Interfaces:**
- Consumes: `FeatureStack`, `Window`, `DemGrid`, `apply_feature` as they stand on `main`.
- Produces: `FeatureStack.terrain_before(feature_id, features=None) -> (Window, DemGrid) | None`; `FeatureStack.preview_for(feature_id, features) -> Preview | None`; `FeatureStack._prune_windows()`; module-level `COMPUTED_FIELDS` and `_same_result(a, b)`; `DemGrid.window_bounds(window) -> (xmin, ymin, xmax, ymax)`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_preview_drag.py`
```python
import time
from dataclasses import replace

import numpy as np
import pytest

from helpers import feature, flat, make_grid
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, polygon_wkb
from terrain_sketch.core.operations import apply_feature
from terrain_sketch.core.tools import Mode, Tool


def square(x0, y0, x1, y1):
    return polygon_wkb([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def stack_with_three(rows=60, cols=60):
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, square(5, 5, 55, 55), id="pad", amount=3.0)
    dike = feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(10, 30), (50, 30)]), id="dike",
                   amount=2.0, width=4.0)
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, square(20, 40, 30, 50), id="pond", amount=1.5)
    stack = FeatureStack(make_grid(flat(10), rows=rows, cols=cols))
    stack.update([pad, dike, pond])
    return stack, [pad, dike, pond]


def test_preview_for_matches_a_full_replay():
    stack, features = stack_with_three()
    dragged = replace(features[1], amount=4.0)
    result = stack.preview_for("dike", [features[0], dragged, features[2]])
    expected = stack.original.subgrid(result.window)
    for f in (features[0], dragged, features[2]):
        apply_feature(f, expected)
    assert np.allclose(result.grid.data, expected.data, equal_nan=True)


def test_preview_for_reuses_the_terrain_under_the_dragged_feature():
    stack, features = stack_with_three()
    for amount in (2.5, 3.0, 3.5):
        stack.preview_for("dike", [features[0], replace(features[1], amount=amount), features[2]])
    key_after = stack._before_key
    stack.preview_for("dike", [features[0], replace(features[1], amount=4.0), features[2]])
    assert stack._before_key == key_after  # the cached base survived every frame of the drag


def test_editing_a_feature_before_the_dragged_one_rebuilds_the_cache():
    stack, features = stack_with_three()
    stack.preview_for("dike", features)
    first = stack._before_key
    moved = replace(features[0], amount=6.0)
    stack.preview_for("dike", [moved, features[1], features[2]])
    assert stack._before_key != first


def test_preview_for_beats_a_full_preview_on_a_large_window():
    stack, features = stack_with_three(rows=400, cols=400)
    dragged = [replace(features[1], amount=a) for a in np.linspace(2.0, 5.0, 12)]

    stack.preview_for("dike", [features[0], dragged[0], features[2]])  # warm the cache
    t0 = time.perf_counter()
    for d in dragged:
        stack.preview_for("dike", [features[0], d, features[2]])
    fast = (time.perf_counter() - t0) / len(dragged)

    t0 = time.perf_counter()
    for d in dragged:
        stack.preview([features[0], d, features[2]])
    full = (time.perf_counter() - t0) / len(dragged)

    assert fast < full, f"drag path {fast*1000:.1f} ms is not faster than full {full*1000:.1f} ms"
    assert fast < 0.066, f"a drag frame took {fast*1000:.1f} ms, over the 15 fps budget"


def test_preview_for_falls_back_to_a_full_preview_for_a_disabled_feature():
    stack, features = stack_with_three()
    off = replace(features[1], enabled=False)
    assert stack.preview_for("dike", [features[0], off, features[2]]) is not None


def test_preview_for_returns_none_for_an_unknown_feature():
    stack, features = stack_with_three()
    assert stack.preview_for("nope", features) is None


def test_committing_an_update_drops_the_drag_cache():
    stack, features = stack_with_three()
    stack.preview_for("dike", features)
    assert stack._before_key is not None
    stack.update([features[0], replace(features[1], amount=9.0), features[2]])
    assert stack._before_key is None


def test_a_long_drag_does_not_grow_the_window_cache():
    stack, features = stack_with_three()
    assert len(stack._windows) == 3
    for amount in np.linspace(2.0, 5.0, 40):
        stack.preview_for("dike", [features[0], replace(features[1], amount=float(amount)),
                                   features[2]])
    assert len(stack._windows) == 3  # one entry per committed feature, not one per frame


def test_a_full_preview_does_not_grow_the_window_cache_either():
    stack, features = stack_with_three()
    for amount in np.linspace(2.0, 5.0, 40):
        stack.preview([features[0], replace(features[1], amount=float(amount)), features[2]])
    assert len(stack._windows) == 3


def test_renaming_a_feature_changes_no_terrain_and_no_window():
    stack, features = stack_with_three()
    before = stack.working.data.copy()
    window = stack.update([features[0], replace(features[1], name="Embankment"), features[2]])
    assert window is None
    assert np.array_equal(stack.working.data, before, equal_nan=True)
    assert stack.features[1].name == "Embankment"
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/core/test_preview_drag.py`
Expected: collection passes but every test errors with `AttributeError: 'FeatureStack' object has no attribute 'preview_for'` (and `terrain_before`)

- [ ] **Step 3: Implement the engine additions**

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

    def window_bounds(self, window: Window) -> tuple:
        """(xmin, ymin, xmax, ymax) of a window in map units, for georeferencing an overlay."""
        x0, w, _rx, y0, _ry, h = self.geotransform
        left = x0 + window.col0 * w
        right = x0 + window.col1 * w
        top = y0 + window.row0 * h
        bottom = y0 + window.row1 * h
        return (min(left, right), min(top, bottom), max(left, right), max(top, bottom))

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
        self._before_key = None
        self._before_grid: DemGrid | None = None

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
            if o is not None and _same_result(o, n) and old_before[fid] == new_before[fid]:
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

    def terrain_before(self, feature_id: str, features=None) -> tuple[Window, DemGrid] | None:
        """The terrain as it stands just before `feature_id` is applied, over that feature's
        own window. This is the reference a profile editor draws as its dashed line, and the
        `before` state volumes are measured against."""
        features = tuple(self.features if features is None else features)
        target = next((f for f in features if f.id == feature_id), None)
        if target is None:
            return None
        window = self.footprint(target)
        if window is None:
            return None
        window, replay = self.closure(window, features)
        grid = self.original.subgrid(window)
        for f in replay:
            if f.id == feature_id:
                break
            apply_feature(f, grid)
        return window, grid

    def preview_for(self, feature_id: str, features) -> Preview | None:
        """Preview while one feature is being dragged.

        Everything before the dragged feature is independent of the drag, so it is computed
        once and cached; each later call replays only the dragged feature and the ones after
        it onto that cached terrain. That is what makes a drag interactive on a large window
        — the full `preview` path re-replays the whole stack every frame."""
        features = tuple(features)
        target = next((f for f in features if f.id == feature_id), None)
        if target is None or not target.enabled:
            return self.preview(features)
        window = self.footprint(target)
        if window is None:
            return None
        window, replay = self.closure(window, features)
        index = next((i for i, f in enumerate(replay) if f.id == feature_id), None)
        if index is None:
            return None
        key = (feature_id, window, tuple(f for f in replay[:index]))
        if self._before_key != key:
            base = self.original.subgrid(window)
            for f in replay[:index]:
                apply_feature(f, base)
            self._before_key, self._before_grid = key, base
        grid = self._before_grid.copy()
        stats = {f.id: apply_feature(f, grid) for f in replay[index:]}
        self._prune_windows()
        return Preview(window, grid, stats)

    def preview(self, features) -> Preview | None:
        """Result of `features` for the changed window, without changing the stack."""
        features = tuple(features)
        dirty = self.dirty_window(features)
        if dirty is None:
            return None
        window, replay = self.closure(dirty, features)
        grid, stats = self.compute(replay, window)
        self._prune_windows()
        return Preview(window, grid, stats)

    def update(self, features) -> Window | None:
        """Make `features` the current list and recompute; returns the changed window.

        Computes before touching any state, so a failure (e.g. a bad geometry raising inside
        `compute`) leaves `features`, `working` and `stats` exactly as they were."""
        features = tuple(features)
        dirty = self.dirty_window(features)
        if dirty is None:
            self.features = features
            self._refresh_bookkeeping()
            return None
        window, replay = self.closure(dirty, features)
        grid, stats = self.compute(replay, window)
        self.features = features
        self._refresh_bookkeeping()
        self.working.data[window.slices] = grid.data
        self.stats.update(stats)
        return window

    def _prune_windows(self) -> None:
        """Drop cached footprints of features that are not in the committed list.

        Every preview frame asks for the footprint of a *different* transient feature, so
        without this a drag would add one cache entry per frame and never give them back."""
        current = set(self.features)
        self._windows = {f: w for f, w in self._windows.items() if f in current}

    def _refresh_bookkeeping(self) -> None:
        self._before_key, self._before_grid = None, None
        current = set(self.features)
        self._windows = {f: w for f, w in self._windows.items() if f in current}
        ids = {f.id for f in self.features}
        self.stats = {k: v for k, v in self.stats.items() if k in ids}
        for f in self.features:
            if not f.enabled:
                self.stats[f.id] = FeatureStats()
            elif self.footprint(f) is None:
                self.stats[f.id] = FeatureStats(flags=footprint_flags(f))


COMPUTED_FIELDS = ("geometry_wkb", "tool", "mode", "enabled", "pixel_mode", "amount", "width",
                   "slope_n", "reach", "slopes_inside", "cross_left", "cross_right", "long_profile")


def _same_result(a, b) -> bool:
    """Whether two versions of a feature produce the same terrain. `name` is not in that set,
    so renaming a feature costs nothing."""
    if a is None or b is None:
        return False
    return all(getattr(a, f) == getattr(b, f) for f in COMPUTED_FIELDS)


def _predecessors(features, common) -> dict:
    out, seen = {}, []
    for f in features:
        if f.id in common:
            out[f.id] = frozenset(seen)
            seen.append(f.id)
    return out
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/core/test_preview_drag.py` → Expected: `10 passed`
Run: `scripts/test.sh` → Expected: `161 passed`

Note: `test_preview_for_beats_a_full_preview_on_a_large_window` asserts a wall-clock budget (a drag frame under 66 ms, and faster than the full path). It passed with roughly 20× headroom on the development machine; if it is ever flaky on slower hardware, widen the margin rather than deleting the test — the whole point of `preview_for` is that number.

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/core/engine.py terrain_sketch/core/grid.py tests/core/test_preview_drag.py
git commit -m "feat(core): a drag-optimised preview path and the terrain before a feature"
```

---

### Task 2: Section sampling

**Files:**
- Create: `terrain_sketch/core/sections.py`
- Test: `tests/core/test_sections.py`

**Interfaces:**
- Consumes: `geometry.split_parts/is_line/line_coords`, `operations.path_coords/rule_profile/NoReferenceError`, `profiles.side_dz/side_limit`, `stations.vertex_stations`, `TOOL_INFO`.
- Produces: `cross_section(feature, side=1) -> ((distance, dz), ...)`; `set_cross_section(feature, side, points) -> dict` of feature fields; `section_part(feature)`; `long_section(feature, grid, terrain=None) -> {"stations", "terrain", "design", "custom"}`; `rescale_long_profile(feature, geometry_wkb, cell_size)`; `SAMPLES = 200`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_sections.py`
```python
import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, polygon_wkb
from terrain_sketch.core.sections import cross_section, long_section, set_cross_section
from terrain_sketch.core.tools import Mode, Tool


def dike(**kw):
    return feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(5, 20), (35, 20)]), **kw)


def test_cross_section_runs_from_the_centre_over_the_crest_and_down_the_slope():
    points = cross_section(dike(width=4.0, slope_n=3.0, reach=20.0, amount=2.0))
    assert points[0] == (0.0, 0.0)
    assert points[1] == (2.0, 0.0)          # half the width: the crest edge
    assert points[-1][0] == pytest.approx(22.0)   # edge + reach
    assert points[-1][1] == pytest.approx(-20.0 / 3.0)  # a raise tool slopes down


def test_a_break_point_becomes_a_berm_in_the_section():
    points = cross_section(dike(width=4.0, slope_n=2.0, reach=10.0, cross_right=((3.0, -1.0),)))
    assert (5.0, -1.0) in points           # 2.0 edge + 3.0 beyond it
    assert points[-1][0] == pytest.approx(12.0)


def test_the_two_sides_can_differ():
    f = dike(width=4.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5),))
    assert cross_section(f, side=-1)[2] == (4.0, -0.5)
    assert cross_section(f, side=1)[2] == (6.0, -1.5)


def test_editing_the_section_writes_back_width_slope_and_breaks():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (3.0, 0.0), (8.0, -1.0), (14.0, -3.0)])
    assert changes["width"] == pytest.approx(6.0)          # the edge moved to 3.0
    assert changes["cross_right"] == ((5.0, -1.0),)        # stored relative to the edge
    assert changes["slope_n"] == pytest.approx(3.0)        # 6 m run over 2 m rise
    assert changes["reach"] == pytest.approx(11.0)


def test_an_area_section_starts_at_the_outline_itself():
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]),
                   slope_n=2.0, reach=6.0, amount=1.0)
    points = cross_section(pond)
    assert points[0] == (0.0, 0.0) and points[1] == (0.0, 0.0)
    assert points[-1][0] == pytest.approx(6.0)
    assert points[-1][1] == pytest.approx(3.0)   # a lower tool slopes up away from the outline


def test_long_section_samples_the_terrain_and_the_rule_design_line():
    grid = make_grid(tilted)
    section = long_section(dike(amount=2.0), grid)
    assert len(section["stations"]) == len(section["terrain"]) == 200
    assert section["stations"][0] == 0.0 and section["stations"][-1] == pytest.approx(30.0)
    assert section["terrain"][0] == pytest.approx(10.5, abs=0.1)    # tilted: 10 + 0.1x at x=5
    assert section["terrain"][-1] == pytest.approx(13.5, abs=0.1)
    assert not section["custom"]
    assert section["design"][0][1] == pytest.approx(section["terrain"][0] + 2.0, abs=0.1)


def test_a_custom_long_profile_is_reported_as_custom_and_used_as_given():
    section = long_section(dike(long_profile=((0.0, 20.0), (30.0, 25.0))), make_grid(tilted))
    assert section["custom"] and section["design"] == ((0.0, 20.0), (30.0, 25.0))


def test_the_long_section_reference_is_the_terrain_before_the_feature():
    grid = make_grid(flat(10))
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, polygon_wkb([(0, 0), (40, 0), (40, 40), (0, 40)]),
                  id="pad", amount=5.0)
    d = dike(id="dike", amount=2.0)
    stack = FeatureStack(grid)
    stack.update([pad, d])
    _window, before = stack.terrain_before("dike")
    on_top = long_section(d, stack.working, terrain=before)
    assert on_top["terrain"][10] == pytest.approx(15.0)          # the pad is already there
    assert on_top["design"][0][1] == pytest.approx(17.0)         # the dike rises from the pad
    plain = long_section(d, grid)
    assert plain["terrain"][10] == pytest.approx(10.0)


def test_terrain_before_is_the_original_for_the_first_feature():
    grid = make_grid(flat(10))
    d = dike(id="dike", amount=2.0)
    stack = FeatureStack(grid)
    stack.update([d])
    _window, before = stack.terrain_before("dike")
    assert np.allclose(before.data, 10.0)


def test_terrain_before_is_none_for_a_feature_that_is_not_there():
    stack = FeatureStack(make_grid(flat(10)))
    assert stack.terrain_before("missing") is None


def test_a_custom_long_profile_follows_a_reshaped_path():
    from terrain_sketch.core.sections import rescale_long_profile
    f = dike(long_profile=((0.0, 10.0), (15.0, 12.0), (30.0, 11.0)))
    longer = line_wkb([(5, 20), (65, 20)])          # the path doubles in length
    assert rescale_long_profile(f, longer, 1.0) == ((0.0, 10.0), (30.0, 12.0), (60.0, 11.0))


def test_rescaling_leaves_a_rule_profile_and_an_unchanged_path_alone():
    from terrain_sketch.core.sections import rescale_long_profile
    rule = dike()
    assert rescale_long_profile(rule, line_wkb([(5, 20), (65, 20)]), 1.0) is None
    same = dike(long_profile=((0.0, 10.0), (30.0, 11.0)))
    assert rescale_long_profile(same, same.geometry_wkb, 1.0) is same.long_profile
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/core/test_sections.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.core.sections'`

- [ ] **Step 3: Implement the sampling**

**File:** `terrain_sketch/core/sections.py`
```python
"""Profile sampling for the editors: the cross-section template and the long section along a path.

Pure geometry and sampling — the widgets draw what these return and hand back edited points.
"""
from __future__ import annotations

import numpy as np

from .geometry import is_line, line_coords, split_parts
from .grid import DemGrid
from .operations import NoReferenceError, path_coords, rule_profile
from .profiles import side_dz, side_limit
from .stations import vertex_stations
from .tools import TOOL_INFO, Mode

SAMPLES = 200


def cross_section(feature, side: int = 1) -> tuple:
    """One side of the cross profile as ((distance from the centre line, dz), ...).

    Starts at the centre (0, 0), runs flat to the corridor edge, then through this side's
    break points, then down the terminal 1:n slope to its limit. `side` is +1 (right) or -1
    (left); for areas the corridor is zero-width, so the outline itself is the edge.
    """
    info = TOOL_INFO[feature.tool]
    edge = 0.5 * feature.width if feature.mode is Mode.PATH else 0.0
    breaks = feature.cross_right if side >= 0 else feature.cross_left
    points = [(0.0, 0.0), (edge, 0.0)]
    if not info.has_slopes:
        return tuple(points)
    limit = side_limit(breaks, feature.slope_n, feature.reach)
    for distance, dz in breaks:
        points.append((edge + float(distance), float(dz)))
    if limit > (breaks[-1][0] if breaks else 0.0):
        dz, _in_extent = side_dz(np.array([limit]), breaks, feature.slope_n, feature.reach,
                                 info.direction)
        points.append((edge + limit, float(dz[0])))
    return tuple(points)


def set_cross_section(feature, side: int, points) -> dict:
    """Turn edited cross-section points back into feature fields.

    `points` are ((distance from the centre line, dz), ...) as `cross_section` returns them.
    The first interior point sets the width; the rest become break points relative to the
    corridor edge; the last segment's run over rise sets the side slope.
    """
    pts = [(float(d), float(z)) for d, z in points if float(d) >= 0.0]
    if len(pts) < 2:
        raise ValueError("a cross section needs at least a centre and an edge point")
    edge = pts[1][0]
    changes: dict = {}
    if feature.mode is Mode.PATH:
        changes["width"] = max(2.0 * edge, 0.1)
    interior, last = pts[2:-1], pts[-1]
    changes["cross_right" if side >= 0 else "cross_left"] = tuple(
        (d - edge, z) for d, z in interior)
    run = last[0] - (interior[-1][0] if interior else edge)
    rise = abs(last[1] - (interior[-1][1] if interior else 0.0))
    changes["slope_n"] = round(run / rise, 4) if rise > 1e-9 else 0.0
    changes["reach"] = round(last[0] - edge, 4)
    return changes


def section_part(feature):
    """The part a long section runs along: for a multi-part path, the longest one."""
    geometry_parts = [p for p in split_parts(feature.geometry_wkb) if is_line(p)]
    if feature.mode is not Mode.PATH or not geometry_parts:
        return None
    return max(geometry_parts, key=lambda p: _length(line_coords(p)))


def long_section(feature, grid: DemGrid, terrain: DemGrid | None = None) -> dict:
    """Reference terrain and design line along the feature's centre line.

    Returns `{"stations", "terrain", "design", "custom"}`: stations in metres from the start,
    terrain sampled on `terrain` (the state just before this feature) and the design line
    either from the feature's custom long profile or regenerated from the tool rule.
    """
    part = section_part(feature)
    coords = None if part is None else line_coords(part)
    if coords is None or len(coords) < 2:
        return {"stations": (), "terrain": (), "design": (), "custom": False}
    reference = terrain if terrain is not None else grid
    length = float(vertex_stations(path_coords(part, grid.cell_size))[-1])
    stations = np.linspace(0.0, length, SAMPLES)
    xs, ys = _walk(coords, stations)
    heights = tuple(float(reference.sample(x, y)) for x, y in zip(xs, ys))
    if feature.long_profile is not None:
        design = tuple((float(s), float(z)) for s, z in feature.long_profile)
        return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": True}
    try:
        design = rule_profile(feature, part, reference)
    except NoReferenceError:
        design = ()
    return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": False}


def _length(coords: np.ndarray) -> float:
    return float(np.sum(np.hypot(np.diff(coords[:, 0]), np.diff(coords[:, 1]))))


def _walk(coords: np.ndarray, stations: np.ndarray):
    """Positions at `stations` metres along the polyline through `coords`."""
    segments = np.hypot(np.diff(coords[:, 0]), np.diff(coords[:, 1]))
    cumulative = np.concatenate([[0.0], np.cumsum(segments)])
    total = cumulative[-1]
    if total <= 0:
        return np.full(stations.shape, coords[0, 0]), np.full(stations.shape, coords[0, 1])
    clamped = np.clip(stations, 0.0, total)
    return (np.interp(clamped, cumulative, coords[:, 0]),
            np.interp(clamped, cumulative, coords[:, 1]))


def rescale_long_profile(feature, geometry_wkb: bytes, cell_size: float):
    """A custom long profile's stations after the path was reshaped.

    Stations are absolute metres along the path, so reshaping it would otherwise leave them
    pointing at the wrong places — or off the end. They are scaled by the change in length,
    which keeps a profile's shape where the user put it relative to the path. Returns the
    feature's existing profile unchanged when there is nothing to do.
    """
    if feature.long_profile is None:
        return feature.long_profile
    old = _path_length(feature.geometry_wkb, cell_size)
    new = _path_length(geometry_wkb, cell_size)
    if old is None or new is None or old <= 0.0 or abs(new - old) < 1e-9:
        return feature.long_profile
    factor = new / old
    return tuple((round(station * factor, 6), z) for station, z in feature.long_profile)


def _path_length(geometry_wkb: bytes, cell_size: float):
    line_parts = [p for p in split_parts(geometry_wkb) if is_line(p)]
    if not line_parts:
        return None
    part = max(line_parts, key=lambda p: _length(line_coords(p)))
    return float(vertex_stations(path_coords(part, cell_size))[-1])
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/core/test_sections.py` → Expected: `12 passed`
Run: `scripts/test.sh` → Expected: `173 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/core/sections.py tests/core/test_sections.py
git commit -m "feat(core): cross-section and long-section sampling for the profile editors"
```

---

### Task 3: The profile plot

**Files:**
- Create: `terrain_sketch/gui/profile_widget.py`
- Modify: `terrain_sketch/gui/help_texts.py` (add `PROFILE_EMPTY_HINT`)
- Test: `tests/qgis/test_profile_widget.py`

**Interfaces:**
- Consumes: `help_texts.PROFILE_EMPTY_HINT`.
- Produces: `Kind` (CROSS, LONG); `ProfileWidget(kind, parent=None)` with signals `profileChanged(object)`, `profileCommitted(object)`, `selectionChanged(int)`; attributes `points`, `terrain`, `editable`, `selected`, `kind`; methods `set_profile(points, terrain=(), editable=True)`, `clear(hint=…)`, `handle_at(position)`, and the internal `_to_screen(x, z)` / `_to_data(position)` the tests drive it through.

Behaviour the tests pin: dragging emits `profileChanged` per move and one `profileCommitted` on release (none if nothing moved); the first handle never moves sideways, and in a long section neither does the last; a handle cannot cross its neighbours; double-click inserts, right-click removes an interior point; a read-only widget ignores all of it.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_profile_widget.py`
```python
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent

from terrain_sketch.gui.profile_widget import Kind, ProfileWidget


def press(widget, x, y, button=Qt.MouseButton.LeftButton, kind=QEvent.Type.MouseButtonPress):
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent,
     QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent,
     QEvent.Type.MouseButtonDblClick: widget.mouseDoubleClickEvent}[kind](event)


def widget_with(points, kind=Kind.CROSS, size=(400, 200)):
    w = ProfileWidget(kind)
    w.resize(*size)
    w.set_profile(points)
    return w


def test_a_widget_with_no_feature_shows_the_hint_and_no_handles():
    w = ProfileWidget(Kind.CROSS)
    w.resize(400, 200)
    assert w.points == [] and w.handle_at(QPointF(10, 10)) == -1


def test_dragging_a_handle_emits_while_moving_and_once_on_release():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)
    start = w._to_screen(12.0, -3.0)
    press(w, start.x(), start.y())
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseMove)
    assert len(during) == 1 and during[-1][-1][1] > -3.0   # the handle moved up
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert len(committed) == 1 and committed[-1] == during[-1]


def test_a_drag_that_does_not_move_commits_nothing():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    point = w._to_screen(2.0, 0.0)
    press(w, point.x(), point.y())
    press(w, point.x(), point.y(), kind=QEvent.Type.MouseButtonRelease)
    assert committed == []


def test_the_first_handle_cannot_move_sideways():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    start = w._to_screen(0.0, 0.0)
    press(w, start.x(), start.y())
    press(w, start.x() + 40, start.y(), kind=QEvent.Type.MouseMove)
    assert w.points[0][0] == 0.0


def test_handles_cannot_be_dragged_past_their_neighbours():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    middle = w._to_screen(2.0, 0.0)
    press(w, middle.x(), middle.y())
    press(w, w._to_screen(20.0, 0.0).x(), middle.y(), kind=QEvent.Type.MouseMove)
    assert w.points[1][0] < w.points[2][0]


def test_double_click_adds_a_point_and_right_click_removes_it():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    target = w._to_screen(7.0, -1.0)
    press(w, target.x(), target.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 4 and len(committed) == 1
    added = w._to_screen(*w.points[2])
    press(w, added.x(), added.y(), button=Qt.MouseButton.RightButton)
    assert len(w.points) == 3 and len(committed) == 2


def test_a_read_only_widget_ignores_edits():
    w = ProfileWidget(Kind.LONG)
    w.resize(400, 200)
    w.set_profile([(0.0, 10.0), (30.0, 12.0)], editable=False)
    committed = []
    w.profileCommitted.connect(committed.append)
    point = w._to_screen(30.0, 12.0)
    press(w, point.x(), point.y())
    press(w, point.x(), point.y() - 30, kind=QEvent.Type.MouseMove)
    assert w.points[-1] == (30.0, 12.0) and committed == []


def test_the_long_profile_keeps_its_end_stations_fixed():
    w = widget_with([(0.0, 10.0), (15.0, 11.0), (30.0, 12.0)], kind=Kind.LONG)
    end = w._to_screen(30.0, 12.0)
    press(w, end.x(), end.y())
    press(w, end.x() - 60, end.y() - 10, kind=QEvent.Type.MouseMove)
    assert w.points[-1][0] == 30.0 and w.points[-1][1] > 12.0   # height moved, station did not
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_profile_widget.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui.profile_widget'`

- [ ] **Step 3: Implement the widget**

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

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Sketch never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Sketch session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Sketch layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."

NO_FEATURES_IN_LAYER = "That layer has no features of the right kind to use here."


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
AREA_LONG_SECTION_NOTE = ("For an area this panel is a read-only section through the feature, "
                          "showing the terrain before and after.")
SYMMETRIC_TIP = "Mirror every cross-profile edit to the other side of the path."
AMOUNT_IS_CUSTOM = ("The long profile was edited by hand, so its heights are fixed. Use "
                    "Reset to rule in the profile panel to drive the shape from this value again.")
```
**File:** `terrain_sketch/gui/profile_widget.py`
```python
"""A profile plot with draggable handles, in cross-section or long-section mode."""
from __future__ import annotations

import math
from enum import Enum

from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

from .help_texts import PROFILE_EMPTY_HINT

MARGIN_LEFT, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_RIGHT = 46, 26, 10, 12
GRAB_PIXELS = 8
HANDLE_RADIUS = 4
NUDGE, NUDGE_FINE = 0.1, 0.01


class Kind(Enum):
    CROSS = "cross"
    LONG = "long"


class ProfileWidget(QWidget):
    """Draws the reference terrain, the design line and draggable handles.

    Dragging emits `profileChanged` continuously and `profileCommitted` on release, both with
    the full point list. The widget owns no feature state: whoever drives it sets points and
    applies the edits.
    """

    profileChanged = pyqtSignal(object)     # ((x, z), ...) while dragging
    profileCommitted = pyqtSignal(object)   # ((x, z), ...) on release
    selectionChanged = pyqtSignal(int)      # index of the highlighted handle, -1 for none

    def __init__(self, kind: Kind, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.points: list[tuple[float, float]] = []
        self.terrain: list[tuple[float, float]] = []
        self.editable = True
        self.hint = PROFILE_EMPTY_HINT
        self.selected = -1
        self._dragging = -1
        self._before: list | None = None
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- contents -------------------------------------------------------------------

    def set_profile(self, points, terrain=(), editable=True) -> None:
        self.points = [(float(x), float(z)) for x, z in points]
        self.terrain = [(float(x), float(z)) for x, z in terrain]
        self.editable = editable
        self.selected = -1
        self._dragging = -1
        self.update()

    def clear(self, hint: str = PROFILE_EMPTY_HINT) -> None:
        self.points, self.terrain, self.hint, self.selected = [], [], hint, -1
        self.update()

    def handle_at(self, position) -> int:
        """Index of the handle within grab distance of a widget position, or -1."""
        for index, (x, z) in enumerate(self.points):
            if (self._to_screen(x, z) - QPointF(position.x(), position.y())).manhattanLength() \
                    <= GRAB_PIXELS * 2:
                return index
        return -1

    # ---- painting -------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802 — Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        if not self.points and not self.terrain:
            painter.setPen(palette.mid().color())
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             self.hint)
            return
        self._draw_grid(painter, palette)
        if self.terrain:
            self._draw_terrain(painter, palette)
        self._draw_design(painter, palette)
        if self.editable:
            self._draw_handles(painter, palette)

    def _draw_grid(self, painter, palette) -> None:
        plot = self._plot_rect()
        painter.setPen(QPen(palette.mid().color(), 1))
        painter.drawRect(plot)
        grid = QColor(palette.mid().color())
        grid.setAlpha(60)
        for value in self._ticks(*self._z_range()):
            y = self._to_screen(self._x_range()[0], value).y()
            painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(palette.windowText().color())
            painter.drawText(QRectF(0, y - 8, MARGIN_LEFT - 4, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{value:g}")
        for value in self._ticks(*self._x_range()):
            x = self._to_screen(value, self._z_range()[0]).x()
            painter.setPen(QPen(grid, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            painter.setPen(palette.windowText().color())
            painter.drawText(QRectF(x - 30, plot.bottom() + 2, 60, MARGIN_BOTTOM - 4),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             f"{value:g}")
        painter.setPen(palette.windowText().color())
        painter.drawText(QRectF(0, 0, MARGIN_LEFT + 40, MARGIN_TOP + 8),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.tr("m"))

    def _draw_terrain(self, painter, palette) -> None:
        pen = QPen(palette.windowText().color(), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawPolyline(QPolygonF([self._to_screen(x, z) for x, z in self.terrain]))

    def _draw_design(self, painter, palette) -> None:
        if len(self.points) < 2:
            return
        design = [self._to_screen(x, z) for x, z in self.points]
        if self.terrain:
            self._shade_between(painter)
        painter.setPen(QPen(palette.highlight().color(), 2))
        painter.drawPolyline(QPolygonF(design))

    def _shade_between(self, painter) -> None:
        """Fill above the reference in warm, cut below it in cool — the map's change colours."""
        reference = self._resampled_terrain()
        if reference is None:
            return
        for colour, above in ((QColor(230, 140, 60, 70), True), (QColor(60, 120, 200, 70), False)):
            path = QPainterPath()
            started = False
            for (x, z), (_rx, rz) in zip(self.points, reference):
                if (z > rz) == above and abs(z - rz) > 1e-9:
                    if not started:
                        path.moveTo(self._to_screen(x, rz))
                        started = True
                    path.lineTo(self._to_screen(x, z))
                elif started:
                    path.lineTo(self._to_screen(x, rz))
                    path.closeSubpath()
                    started = False
            if started:
                path.lineTo(self._to_screen(self.points[-1][0], reference[-1][1]))
                path.closeSubpath()
            painter.fillPath(path, colour)

    def _resampled_terrain(self):
        if not self.terrain:
            return None
        xs = [x for x, _ in self.terrain]
        zs = [z for _, z in self.terrain]
        out = []
        for x, _z in self.points:
            out.append((x, _interpolate(x, xs, zs)))
        return out

    def _draw_handles(self, painter, palette) -> None:
        for index, (x, z) in enumerate(self.points):
            centre = self._to_screen(x, z)
            painter.setPen(QPen(palette.highlight().color(), 1))
            painter.setBrush(palette.highlight() if index == self.selected else palette.base())
            painter.drawEllipse(centre, HANDLE_RADIUS, HANDLE_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)

    # ---- interaction ----------------------------------------------------------------

    def mousePressEvent(self, event):  # noqa: N802 — Qt override
        if not self.editable:
            return
        index = self.handle_at(event.position())
        if event.button() == Qt.MouseButton.RightButton:
            if index > 0 and index < len(self.points) - 1:
                self.points.pop(index)
                self.selected = -1
                self.update()
                self.profileCommitted.emit(tuple(self.points))
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.selected = index
        self._dragging = index
        self._before = list(self.points)
        self.selectionChanged.emit(index)
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802 — Qt override
        if self._dragging < 0:
            return
        self._move_handle(self._dragging, self._to_data(event.position()))
        self.profileChanged.emit(tuple(self.points))

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt override
        if self._dragging < 0:
            return
        self._dragging = -1
        if self._before != self.points:
            self.profileCommitted.emit(tuple(self.points))
        self._before = None

    def mouseDoubleClickEvent(self, event):  # noqa: N802 — Qt override
        if not self.editable or event.button() != Qt.MouseButton.LeftButton:
            return
        x, z = self._to_data(event.position())
        index = self._insertion_index(x)
        if index is None:
            return
        self.points.insert(index, (x, z))
        self.selected = index
        self._dragging = -1
        self.update()
        self.profileCommitted.emit(tuple(self.points))

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        step = NUDGE_FINE if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else NUDGE
        deltas = {Qt.Key.Key_Up: (0.0, step), Qt.Key.Key_Down: (0.0, -step),
                  Qt.Key.Key_Left: (-step, 0.0), Qt.Key.Key_Right: (step, 0.0)}
        if self.selected < 0 or not self.editable or event.key() not in deltas:
            event.ignore()
            return
        dx, dz = deltas[event.key()]
        x, z = self.points[self.selected]
        self._move_handle(self.selected, (x + dx, z + dz))
        self.profileCommitted.emit(tuple(self.points))
        event.accept()

    def _move_handle(self, index: int, position) -> None:
        x, z = position
        if not self._can_move_x(index):
            x = self.points[index][0]
        else:
            low = self.points[index - 1][0] if index > 0 else None
            high = self.points[index + 1][0] if index < len(self.points) - 1 else None
            if low is not None:
                x = max(x, low + 1e-6)
            if high is not None:
                x = min(x, high - 1e-6)
            x = max(x, 0.0) if self.kind is Kind.CROSS else x
        self.points[index] = (x, z)
        self.update()

    def _can_move_x(self, index: int) -> bool:
        """The first point is pinned; in a long section the last one is too (it is the end)."""
        if index == 0:
            return False
        return not (self.kind is Kind.LONG and index == len(self.points) - 1)

    def _insertion_index(self, x: float):
        for index in range(1, len(self.points)):
            if self.points[index - 1][0] < x < self.points[index][0]:
                return index
        return None

    # ---- coordinate transforms ------------------------------------------------------

    def _plot_rect(self) -> QRectF:
        return QRectF(MARGIN_LEFT, MARGIN_TOP,
                      max(self.width() - MARGIN_LEFT - MARGIN_RIGHT, 1.0),
                      max(self.height() - MARGIN_TOP - MARGIN_BOTTOM, 1.0))

    def _x_range(self) -> tuple[float, float]:
        xs = [x for x, _ in self.points] + [x for x, _ in self.terrain]
        return (min(xs), max(xs)) if xs else (0.0, 1.0)

    def _z_range(self) -> tuple[float, float]:
        zs = [z for _, z in self.points] + [z for _, z in self.terrain]
        if not zs:
            return (0.0, 1.0)
        low, high = min(zs), max(zs)
        if high - low < 1e-6:
            low, high = low - 0.5, high + 0.5
        pad = (high - low) * 0.12
        return low - pad, high + pad

    def _to_screen(self, x: float, z: float) -> QPointF:
        plot = self._plot_rect()
        x0, x1 = self._x_range()
        z0, z1 = self._z_range()
        sx = plot.left() + (x - x0) / (x1 - x0 or 1.0) * plot.width()
        sy = plot.bottom() - (z - z0) / (z1 - z0 or 1.0) * plot.height()
        return QPointF(sx, sy)

    def _to_data(self, position) -> tuple[float, float]:
        plot = self._plot_rect()
        x0, x1 = self._x_range()
        z0, z1 = self._z_range()
        x = x0 + (position.x() - plot.left()) / (plot.width() or 1.0) * (x1 - x0)
        z = z0 + (plot.bottom() - position.y()) / (plot.height() or 1.0) * (z1 - z0)
        return float(x), float(z)

    @staticmethod
    def _ticks(low: float, high: float, count: int = 5) -> list:
        if high <= low:
            return [low]
        raw = (high - low) / count
        magnitude = 10 ** _floor_log10(raw)
        step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw),
                   default=magnitude)
        first = step * round(low / step + 0.5)
        out, value = [], first
        while value <= high:
            out.append(round(value, 6))
            value += step
        return out


def _floor_log10(value: float) -> int:
    return int(math.floor(math.log10(value))) if value > 0 else 0


def _interpolate(x: float, xs, zs) -> float:
    if not xs:
        return 0.0
    if x <= xs[0]:
        return zs[0]
    if x >= xs[-1]:
        return zs[-1]
    for i in range(1, len(xs)):
        if xs[i] >= x:
            span = xs[i] - xs[i - 1]
            t = 0.0 if span <= 0 else (x - xs[i - 1]) / span
            return zs[i - 1] + t * (zs[i] - zs[i - 1])
    return zs[-1]
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_profile_widget.py` → Expected: `8 passed`
Run: `scripts/test.sh` → Expected: `181 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/profile_widget.py terrain_sketch/gui/help_texts.py tests/qgis/test_profile_widget.py
git commit -m "feat(gui): a profile plot with draggable handles"
```

---

### Task 4: The preview overlay

**Files:**
- Create: `terrain_sketch/gui/overlay.py`
- Test: `tests/qgis/test_overlay.py`

**Interfaces:**
- Consumes: `QgsMapCanvasItem`, numpy.
- Produces: `change_image(change) -> QImage | None` (warm where the terrain rose, cool where it was cut, transparent where nothing changed, `None` when nothing changed at all); `PreviewOverlay(canvas, crs_transform=None)` with `show_change(bounds, change)`, `clear()`, `dispose()`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_overlay.py`
```python
import numpy as np

from terrain_sketch.gui.overlay import change_image


def test_the_change_image_is_warm_for_fill_and_cool_for_cut():
    change = np.array([[0.0, 2.0], [-2.0, 0.0]], dtype=np.float32)
    image = change_image(change)
    assert image is not None and image.width() == 2 and image.height() == 2
    assert image.pixelColor(1, 0).red() > image.pixelColor(1, 0).blue()    # fill: warm
    assert image.pixelColor(0, 1).blue() > image.pixelColor(0, 1).red()    # cut: cool
    assert image.pixelColor(0, 0).alpha() == 0                            # unchanged: invisible


def test_an_unchanged_window_makes_no_image():
    assert change_image(np.zeros((4, 4), dtype=np.float32)) is None
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_overlay.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui.overlay'`

- [ ] **Step 3: Implement the overlay**

**File:** `terrain_sketch/gui/overlay.py`
```python
"""A canvas item that draws the drag preview: cut and fill over the window being changed."""
from __future__ import annotations

import numpy as np
from qgis.core import QgsPointXY, QgsRectangle
from qgis.gui import QgsMapCanvasItem
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtGui import QImage

FILL = (230, 140, 60)   # warm: the terrain rose
CUT = (60, 120, 200)    # cool: the terrain was cut
FULL_ALPHA_AT = 1.0     # metres of change that reach full opacity
MAX_ALPHA = 200


class PreviewOverlay(QgsMapCanvasItem):
    """Paints a change image georeferenced over the map while a profile handle is dragged.

    It lives on the canvas, not in the layer tree: a preview is uncommitted, so it must not
    look like one of the session's layers or survive the drag that made it.
    """

    def __init__(self, canvas, crs_transform=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.crs_transform = crs_transform
        self.image: QImage | None = None
        self.bounds: QgsRectangle | None = None
        self.setZValue(100)
        self.hide()

    def show_change(self, bounds, change) -> None:
        """`bounds` is (xmin, ymin, xmax, ymax) in the DEM CRS; `change` is new minus original."""
        image = change_image(change)
        if image is None:
            self.clear()
            return
        self.image = image
        self.bounds = self._to_canvas_crs(QgsRectangle(*bounds))
        self.updatePosition()
        self.show()
        self.update()

    def clear(self) -> None:
        self.image, self.bounds = None, None
        self.hide()

    def dispose(self) -> None:
        """Take the item off the canvas; call before dropping the reference."""
        self.clear()
        scene = self.canvas.scene()
        if scene is not None:
            scene.removeItem(self)

    def updatePosition(self) -> None:  # noqa: N802 — Qt/QGIS override
        if self.bounds is not None:
            self.setRect(self.bounds)

    def paint(self, painter, option=None, widget=None) -> None:
        if self.image is None or self.bounds is None:
            return
        painter.drawImage(self._target_rect(), self.image)

    def _target_rect(self) -> QRectF:
        """The item's own rectangle in canvas pixels, which is what setRect gave us."""
        top_left = self.toCanvasCoordinates(QgsPointXY(self.bounds.xMinimum(),
                                                       self.bounds.yMaximum())) - self.pos()
        bottom_right = self.toCanvasCoordinates(QgsPointXY(self.bounds.xMaximum(),
                                                           self.bounds.yMinimum())) - self.pos()
        return QRectF(top_left, bottom_right)

    def _to_canvas_crs(self, rectangle: QgsRectangle) -> QgsRectangle:
        if self.crs_transform is None:
            return rectangle
        return self.crs_transform.transformBoundingBox(rectangle)


def change_image(change) -> QImage | None:
    """An RGBA image of a change array: warm where it rose, cool where it was cut.

    Opacity grows with the size of the change so a 5 cm shave stays faint and a 2 m dike reads
    strongly; cells that did not change at all stay fully transparent.
    """
    values = np.asarray(change, dtype=np.float32)
    if values.ndim != 2 or values.size == 0:
        return None
    magnitude = np.abs(np.nan_to_num(values, nan=0.0))
    if not np.any(magnitude > 0):
        return None
    alpha = np.clip(magnitude / FULL_ALPHA_AT, 0.0, 1.0) * MAX_ALPHA
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    rising = np.nan_to_num(values, nan=0.0) > 0
    for channel in range(3):
        rgba[..., channel] = np.where(rising, FILL[channel], CUT[channel])
    rgba[..., 3] = alpha.astype(np.uint8)
    rgba = np.ascontiguousarray(rgba)
    rows, cols = values.shape
    image = QImage(rgba.data, cols, rows, 4 * cols, QImage.Format.Format_RGBA8888)
    return image.copy()  # detach from the numpy buffer before it goes out of scope
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_overlay.py` → Expected: `2 passed`
Run: `scripts/test.sh` → Expected: `183 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/overlay.py tests/qgis/test_overlay.py
git commit -m "feat(gui): a canvas overlay showing an uncommitted change"
```

---

### Task 5: The controller's preview API

**Files:**
- Modify: `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/properties_page.py`, `terrain_sketch/gui/help_texts.py`
- Test: `tests/qgis/test_preview.py`

**Interfaces:**
- Consumes: `FeatureStack.preview_for`/`terrain_before` (Task 1), `sections.long_section`/`rescale_long_profile` (Task 2).
- Produces: `PreviewImage(bounds, change, stats)`; `PREVIEW_INTERVAL = 60`; signals `previewUpdated(str, object)` and `previewCleared()`; `SketchController.preview(fid, **changes)`, `cancel_preview()`, `long_section(fid)`, `find(fid) -> TerrainFeature | None`. `update_feature` now cancels any pending preview first, and `set_geometry` rescales a custom long profile. `PropertiesPage` disables Height/Depth while the long profile is custom, with `help_texts.AMOUNT_IS_CUSTOM` as its tooltip.

Note on `find()` versus `feature()`: `feature()` raises for an unknown id and stays that way for its existing callers. Everything reachable from a mouse or key handler — which is everything in this task — must use `find()`, because an exception inside a Qt callback aborts QGIS.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_preview.py`
```python
import pytest

from qgis_helpers import UTM, line_through, sample, start_session
from terrain_sketch.core.tools import Mode, Tool


def test_dragging_a_profile_previews_without_committing(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    before = sample(c.layers.working, 20, 20)
    previews = []
    c.previewUpdated.connect(lambda fid, p: previews.append(p))
    c.preview(dike.id, amount=5.0)
    assert len(previews) == 1
    assert c.feature(dike.id).amount == 1.0            # nothing was committed
    assert sample(c.layers.working, 20, 20) == before  # the working DEM is untouched
    # change is measured against the ORIGINAL terrain, not the working DEM: 10 m ground, 5 m crest
    assert previews[0].change.max() == pytest.approx(5.0, abs=0.2)


def test_previews_are_throttled_to_the_latest_request(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    previews = []
    c.previewUpdated.connect(lambda fid, p: previews.append(p))
    for amount in (2.0, 3.0, 4.0, 5.0):
        c.preview(dike.id, amount=amount)
    assert len(previews) == 1          # the first ran; the rest collapsed into one pending call
    assert c._pending is not None


def test_committing_clears_the_preview(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    cleared = []
    c.previewCleared.connect(lambda: cleared.append(True))
    c.preview(dike.id, amount=5.0)
    c.update_feature(dike.id, amount=5.0)
    assert cleared and c._pending is None
    assert sample(c.layers.working, 20, 20) == pytest.approx(15.0)


def test_a_preview_for_a_deleted_feature_is_ignored(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.delete_feature(dike.id)
    c.preview(dike.id, amount=5.0)     # must not raise: this runs inside a Qt callback
    assert c._pending is None


def test_reshaping_a_path_carries_its_custom_long_profile_along(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 20, 20), UTM)
    c.update_feature(dike.id, long_profile=((0.0, 12.0), (15.0, 13.0)))
    c.set_geometry(dike.id, line_through(5, 20, 35, 20), UTM)   # the path doubles in length
    stations = [s for s, _z in c.feature(dike.id).long_profile]
    assert stations == pytest.approx([0.0, 30.0])
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_preview.py`
Expected: 5 failures — `AttributeError: 'SketchController' object has no attribute 'previewUpdated'` and `… has no attribute 'preview'`

- [ ] **Step 3: Implement the preview API**

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

NO_SESSION = "Pick a DEM and press Start first."

EXPORT_OVER_SOURCE = "Choose a new file name: Terrain Sketch never overwrites your DEM or its own working files."

SESSION_ENDED_DEM_REMOVED = "The Terrain Sketch session ended because its DEM was removed from the project."

RESULT_LAYER_REMOVED = "A Terrain Sketch layer was removed from the project. Your features are kept and export still works."

DRAWING_NOT_TRANSFORMED = "The drawing could not be converted to the DEM's coordinate system."

NO_FEATURES_IN_LAYER = "That layer has no features of the right kind to use here."


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
AREA_LONG_SECTION_NOTE = ("For an area this panel is a read-only section through the feature, "
                          "showing the terrain before and after.")
SYMMETRIC_TIP = "Mirror every cross-profile edit to the other side of the path."
AMOUNT_IS_CUSTOM = ("The long profile was edited by hand, so its heights are fixed. Use "
                    "Reset to rule in the profile panel to drive the shape from this value again.")
```
**File:** `terrain_sketch/gui/controller.py`
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
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from .help_texts import (DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, NO_FEATURES_IN_LAYER, NO_SESSION,
                         RESULT_LAYER_REMOVED, SESSION_ENDED_DEM_REMOVED, TOOL_LABELS)

LOG_TAG = "Terrain Sketch"


class PreviewImage(NamedTuple):
    """What a drag preview hands the GUI: where it is, what changed, and the running stats."""

    bounds: tuple          # (xmin, ymin, xmax, ymax) in the DEM CRS
    change: object         # float32 array, new minus original, over those bounds
    stats: FeatureStats


PREVIEW_INTERVAL = 60  # ms between preview recomputes while dragging (spec 8.3)


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
            files = WorkingFiles(tempfile.mkdtemp(prefix="terrain_sketch_"), grid, info)
        except (OSError, RuntimeError, MemoryError) as error:
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
            self.message.emit(Qgis.MessageLevel.Warning, NO_FEATURES_IN_LAYER)
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
        terrain as it stands just before this feature."""
        feature = self.find(fid)
        if feature is None or not self.has_dem:
            return {"stations": (), "terrain": (), "design": (), "custom": False}
        before = self.stack.terrain_before(fid)
        terrain = before[1] if before is not None else None
        return long_section(feature, self.stack.working, terrain=terrain)

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
            self.message.emit(Qgis.MessageLevel.Critical, "Terrain Sketch could not update the terrain; "
                                                          "see the 'Terrain Sketch' log tab for details.")
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

    def _unique(self, name: str) -> str:
        names = {f.name for f in self._features}
        if name not in names:
            return name
        n = 2
        while f"{name} {n}" in names:
            n += 1
        return f"{name} {n}"

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
        if self.dem_layer_id in ids:
            self.close()  # the removal has finished, so the remaining session layers can go too
            self.message.emit(Qgis.MessageLevel.Warning, SESSION_ENDED_DEM_REMOVED)
        elif ids & set(self.layers.layer_ids):
            self.message.emit(Qgis.MessageLevel.Info, RESULT_LAYER_REMOVED)
```
**File:** `terrain_sketch/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.tools import TOOL_INFO, Mode, PixelMode
from .help_texts import AMOUNT_IS_CUSTOM, FLAG_TEXTS, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS, TOOL_LABELS, TOOL_SUMMARIES, amount_label


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
        self._amount_tip = self.tr("How far the feature rises (height) or cuts (depth): above or below the "
                                   "straight grade between the path's ends, the highest or lowest point of "
                                   "the path or outline, or the terrain itself for Add and Subtract.")
        self.amount.setToolTip(self._amount_tip)
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
            custom = feature.long_profile is not None
            self.amount_label.setText(self.tr(label) if label else "")
            self.amount.setValue(feature.amount)
            # a custom long profile fixes the heights, so H/D no longer drives them
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

Run: `scripts/test.sh tests/qgis/test_preview.py` → Expected: `5 passed`
Run: `scripts/test.sh` → Expected: `188 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/controller.py terrain_sketch/gui/properties_page.py terrain_sketch/gui/help_texts.py tests/qgis/test_preview.py
git commit -m "feat(gui): throttled live preview that never commits"
```

---

### Task 6: The profile dock, wired up

**Files:**
- Create: `terrain_sketch/gui/profile_dock.py`
- Modify: `terrain_sketch/gui/main_dock.py`, `terrain_sketch/plugin.py`
- Test: `tests/qgis/test_profile_dock.py`, `tests/qgis/test_dock_plugin.py`

**Interfaces:**
- Consumes: everything from Tasks 1-5.
- Produces: `ProfileDock(controller, parent=None)` with `cross`, `long`, `symmetric`, `reset_cross`, `reset_long`, `note`, `show_feature(fid)`, `shutdown()`; `MainDock(iface, controller, profiles=None, parent=None)` now owns `overlay` and calls `profiles.show_feature(...)` on every selection change; `TerrainSketchPlugin.profiles` is registered in the bottom dock area and torn down on unload.

`test_dock_plugin.py` changes in one place: the plugin now registers two docks, so the lifecycle test asserts `addDockWidget.call_count == 2` and the same for removal.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_profile_dock.py`
```python
import pytest

from qgis_helpers import UTM, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.profile_dock import ProfileDock


def test_the_profile_dock_loads_the_selected_feature(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.points[0] == (0.0, 0.0)
    assert dock.cross.points[1][0] == pytest.approx(dike.width / 2.0)
    assert len(dock.long.terrain) == 200 and len(dock.long.points) >= 2
    assert dock.note.text() == ""


def test_editing_the_cross_profile_writes_width_and_slope_back(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, )
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (3.0, 0.0), (15.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.width == pytest.approx(6.0)
    assert updated.slope_n == pytest.approx(3.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)


def test_symmetric_mirrors_the_edit_to_the_other_side(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(True)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)))
    updated = c.feature(dike.id)
    assert updated.cross_left == updated.cross_right == ((4.0, -1.0),)
    dock.symmetric.setChecked(False)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (2.0, 0.0), (8.0, -2.0), (14.0, -4.0)))
    after = c.feature(dike.id)
    assert after.cross_right == ((6.0, -2.0),) and after.cross_left == ((4.0, -1.0),)


def test_editing_the_long_profile_makes_it_custom_and_reset_restores_the_rule(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, )
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.long.profileCommitted.emit(((0.0, 14.0), (29.0, 14.0)))
    assert c.feature(dike.id).long_profile == ((0.0, 14.0), (29.0, 14.0))
    assert dock.note.text() and dock.reset_long.isEnabled()
    assert sample(c.layers.working, 20, 20) == pytest.approx(14.0)
    dock.reset_long.click()
    assert c.feature(dike.id).long_profile is None
    assert dock.note.text() == ""


def test_an_area_feature_gets_a_read_only_long_panel(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert not dock.long.editable and dock.note.text()
    assert not dock.symmetric.isEnabled()


def test_the_dock_clears_when_the_selection_or_the_session_goes(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.points
    dock.show_feature(None)
    assert dock.cross.points == [] and dock.long.points == []
    dock.show_feature(dike.id)
    c.close()
    assert dock.cross.points == []


def test_a_custom_long_profile_disables_the_height_field(tmp_path):
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount.isEnabled()
    c.update_feature(dike.id, long_profile=((0.0, 14.0), (29.0, 14.0)))
    page.show_feature(dike.id)
    assert not page.amount.isEnabled() and "fixed" in page.amount.toolTip()
```
**File:** `tests/qgis/test_dock_plugin.py`
```python
import pytest
from qgis.core import QgsProject

from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, sample, square, world
from terrain_sketch import classFactory
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.selection import Method
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.main_dock import PAGE_GALLERY, PAGE_PROPERTIES, PAGE_START, MainDock
from terrain_sketch.qgis_io.layers import GROUP_NAME


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
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
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


def test_ending_the_session_stops_a_drawing_in_progress(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.CLICK].click()
    assert dock.draw_tool is not None
    QgsProject.instance().removeMapLayer(dem.id())  # the user removes the DEM while still drawing
    assert not controller.has_dem and dock.draw_tool is None and dock.hint.isHidden()
    assert iface.mapCanvas().mapTool() is None


def test_hiding_the_panel_stops_a_drawing_and_leaves_no_rubber_band(tmp_path):
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    plugin.dock.dem_combo.setLayer(dem_layer(tmp_path))
    plugin.dock.start_button.click()
    n0 = len(iface.mapCanvas().scene().items())
    plugin.dock.gallery.select_tool(Tool.RAISE_PATH)
    plugin.dock.gallery.select_mode(Mode.PATH)
    plugin.dock.gallery.method_buttons[Method.CLICK].click()
    plugin.action.setChecked(False)
    assert plugin.dock.draw_tool is None
    assert len(iface.mapCanvas().scene().items()) == n0


def test_a_new_session_applies_the_hillshade_checkbox(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path)
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    dock.hillshade_box.setChecked(True)
    dock.confirm = lambda text: True
    dock.start_button.click()
    node = QgsProject.instance().layerTreeRoot().findGroup(GROUP_NAME).findLayer(controller.layers.hillshade_id)
    assert node.itemVisibilityChecked()


def test_plugin_adds_and_removes_its_button_menu_and_panel():
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    iface.addToolBarIcon.assert_called_once_with(plugin.action)
    iface.addPluginToRasterMenu.assert_called_once()
    plugin.action.setChecked(True)
    assert plugin.dock is not None and plugin.profiles is not None
    assert iface.addDockWidget.call_count == 2  # the panel on the right, the profiles below
    plugin.unload()
    iface.removeToolBarIcon.assert_called_once()
    assert iface.removeDockWidget.call_count == 2
    assert plugin.dock is None and plugin.profiles is None
    assert plugin.controller is None and plugin.action is None


def _session_dock(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def test_the_brush_extends_the_selected_area_feature(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    pond = controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock._brush_fid == pond.id and not dock.draw_tool.geometry.isEmpty()
    dock.draw_tool.apply_stroke([QgsPointXY(*world(25, 15))])  # paint next to the pond
    dock.draw_tool.finish()
    assert len(controller.features) == 1  # the pond grew, no second feature
    assert sample(controller.layers.working, 25, 15) < 10.0


def test_vertex_editing_reshapes_the_selected_feature(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.edit_tool.geometryChanged.emit(line_through(5, 10, 34, 10))
    assert sample(controller.layers.working, 20, 10) == pytest.approx(11.0)
    assert sample(controller.layers.working, 20, 20) == pytest.approx(10.0)
    dock.edit_button.setChecked(False)
    assert dock.edit_tool is None


def test_selecting_a_feature_highlights_it_on_the_map(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.highlight.numberOfVertices() > 0
    dock.feature_view.clearSelection()
    assert dock.highlight.numberOfVertices() == 0


def test_deleting_the_brushed_feature_mid_stroke_does_not_take_qgis_down(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    pond = controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    brush = dock.draw_tool
    assert dock._brush_fid == pond.id
    controller.delete_feature(pond.id)  # the Delete button or the row context menu, still painting
    assert dock._brush_fid is None
    brush.apply_stroke([QgsPointXY(*world(25, 15))])
    brush.finish()  # a stale target used to raise StopIteration out of this Qt callback
    assert len(controller.features) == 1 and controller.features[0].id != pond.id


def test_the_brush_hint_names_the_feature_it_extends(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    pond = controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    assert dock._brush_fid == pond.id and pond.name in dock.hint.text()
    dock.end_drawing()
    dock.feature_view.clearSelection()
    dock.gallery.method_buttons[Method.BRUSH].click()  # nothing selected: this paints a new feature
    assert dock._brush_fid is None and pond.name not in dock.hint.text()


def test_selecting_a_row_leaves_the_drawing_hint_up(tmp_path):
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    dock.gallery.method_buttons[Method.FREEHAND].click()
    assert not dock.hint.isHidden()
    dock.feature_view.select_id(dike.id)  # the user checks a row while the trace is still running
    assert dock.draw_tool is not None and not dock.hint.isHidden()


def test_closing_the_panel_stops_the_edit_tool_too(tmp_path):
    iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.close()
    assert dock.edit_tool is None and iface.mapCanvas().mapTool() is None


def test_the_brush_radius_follows_the_canvas_crs(tmp_path):
    iface, _controller, dock = _session_dock(tmp_path)
    assert dock.gallery.brush_spin.suffix() == " m"  # the test canvas is UTM
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert dock.gallery.brush_spin.suffix() == " degrees"
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_profile_dock.py tests/qgis/test_dock_plugin.py`
Expected: `test_profile_dock.py` fails collection with `ModuleNotFoundError: No module named 'terrain_sketch.gui.profile_dock'`

- [ ] **Step 3: Implement the dock and the wiring**

**File:** `terrain_sketch/gui/profile_dock.py`
```python
"""Bottom dock: the cross profile and the long profile of the selected feature, side by side."""
from __future__ import annotations

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                                 QWidget)

from ..core.sections import cross_section, long_section, set_cross_section
from ..core.tools import TOOL_INFO, Mode
from .help_texts import AREA_LONG_SECTION_NOTE, CUSTOM_PROFILE_NOTE, SYMMETRIC_TIP
from .profile_widget import Kind, ProfileWidget


class ProfileDock(QgsDockWidget):
    """Shows the selected feature's shape and writes every edit back through the controller."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Terrain Sketch — Profiles"))
        self.setObjectName("TerrainSketchProfileDock")
        self.controller = controller
        self._fid = None
        self._loading = False

        self.cross = ProfileWidget(Kind.CROSS)
        self.long = ProfileWidget(Kind.LONG)
        self.symmetric = QCheckBox(self.tr("Symmetric"))
        self.symmetric.setChecked(True)
        self.symmetric.setToolTip(SYMMETRIC_TIP)
        self.reset_cross = QPushButton(self.tr("Reset shape"))
        self.reset_long = QPushButton(self.tr("Reset to rule"))
        self.note = QLabel()
        self.note.setWordWrap(True)

        body = QWidget()
        layout = QVBoxLayout(body)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        for title, widget, controls in (
                (self.tr("Cross profile"), self.cross, (self.symmetric, self.reset_cross)),
                (self.tr("Long profile"), self.long, (self.reset_long,))):
            panel = QWidget()
            column = QVBoxLayout(panel)
            column.setContentsMargins(0, 0, 0, 0)
            header = QHBoxLayout()
            header.addWidget(QLabel(title))
            header.addStretch(1)
            for control in controls:
                header.addWidget(control)
            column.addLayout(header)
            column.addWidget(widget, 1)
            splitter.addWidget(panel)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.note)
        self.setWidget(body)

        self.cross.profileChanged.connect(lambda points: self._cross_edited(points, False))
        self.cross.profileCommitted.connect(lambda points: self._cross_edited(points, True))
        self.long.profileChanged.connect(lambda points: self._long_edited(points, False))
        self.long.profileCommitted.connect(lambda points: self._long_edited(points, True))
        self.reset_cross.clicked.connect(self._reset_cross)
        self.reset_long.clicked.connect(self._reset_long)
        controller.featuresChanged.connect(self._refresh)
        controller.sessionChanged.connect(self._session_changed)
        self.show_feature(None)

    def show_feature(self, fid) -> None:
        """Load a feature's profiles, or clear both panels when there is no selection."""
        self._fid = fid
        if fid is None or not self.controller.has_dem:
            self.cross.clear()
            self.long.clear()
            self.note.clear()
            self._set_enabled(False)
            return
        self._refresh()

    def _refresh(self) -> None:
        if self._fid is None:
            return
        feature = self.controller.feature(self._fid)
        if feature is None:
            self.show_feature(None)
            return
        self._loading = True
        try:
            info = TOOL_INFO[feature.tool]
            self.cross.set_profile(cross_section(feature, side=1), editable=info.has_slopes)
            self.symmetric.setEnabled(info.has_slopes and feature.mode is Mode.PATH)
            self.reset_cross.setEnabled(info.has_slopes)
            section = self.controller.long_section(self._fid)
            if feature.mode is Mode.AREA:
                self.long.set_profile(section["design"], terrain=self._pairs(section),
                                      editable=False)
                self.note.setText(AREA_LONG_SECTION_NOTE)
            else:
                self.long.set_profile(section["design"], terrain=self._pairs(section))
                self.note.setText(CUSTOM_PROFILE_NOTE if section["custom"] else "")
            self.reset_long.setEnabled(bool(section["custom"]))
        finally:
            self._loading = False

    @staticmethod
    def _pairs(section) -> tuple:
        return tuple(zip(section["stations"], section["terrain"]))

    def _cross_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        feature = self.controller.feature(self._fid)
        if feature is None:
            return
        changes = set_cross_section(feature, 1, points)
        if self.symmetric.isChecked() and feature.mode is Mode.PATH:
            changes["cross_left"] = changes["cross_right"]
        self._apply(changes, commit)

    def _long_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        self._apply({"long_profile": tuple((float(s), float(z)) for s, z in points)}, commit)

    def _apply(self, changes: dict, commit: bool) -> None:
        if commit:
            self.controller.update_feature(self._fid, **changes)
        else:
            self.controller.preview(self._fid, **changes)

    def _reset_cross(self) -> None:
        if self._fid is not None:
            self.controller.update_feature(self._fid, cross_left=(), cross_right=())

    def _reset_long(self) -> None:
        if self._fid is not None:
            self.controller.update_feature(self._fid, long_profile=None)

    def _session_changed(self) -> None:
        if not self.controller.has_dem:
            self.show_feature(None)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.symmetric, self.reset_cross, self.reset_long):
            widget.setEnabled(enabled)

    def shutdown(self) -> None:
        self.controller.cancel_preview()
```
**File:** `terrain_sketch/gui/main_dock.py`
```python
"""The Terrain Sketch panel: DEM, feature list, tool gallery and feature properties."""
from __future__ import annotations

from qgis.core import Qgis, QgsApplication, QgsCoordinateTransform, QgsGeometry, QgsProject
from qgis.gui import QgsDockWidget, QgsMapLayerComboBox, QgsMapToolEdit, QgsRubberBand
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                                 QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..core.tools import Mode
from ..qgis_io.raster_io import DemError
from .feature_list import FeatureListModel, FeatureListView
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


class MainDock(QgsDockWidget):
    def __init__(self, iface, controller, profiles=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Terrain Sketch"))
        self.setObjectName("TerrainSketchDock")
        self.iface = iface
        self.controller = controller
        self.profiles = profiles          # the bottom profile dock, if the plugin made one
        self.overlay = PreviewOverlay(iface.mapCanvas())
        self.draw_tool = None
        self._previous_tool = None
        self.confirm = self._confirm_dialog  # replaceable in tests
        self.ask_export_path = self._export_dialog  # replaceable in tests
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
                       self.edit_button, self.feature_view):
            widget.setEnabled(has_dem)
        if self.controller.layers is not None:
            project = self.controller.project
            self.dem_combo.setExceptedLayerList([project.mapLayer(i) for i in self.controller.layers.layer_ids])
            self.controller.set_hillshade_visible(self.hillshade_box.isChecked())
        else:
            self.dem_combo.setExceptedLayerList([])
        self.pages.setCurrentIndex(PAGE_GALLERY if has_dem else PAGE_START)
        self._update_radius_units()

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

    def _preview_updated(self, _fid, preview) -> None:
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
            return self.tr(BRUSH_EXTEND_HINT).format(self.controller.feature(self._brush_fid).name)
        return self.tr(METHOD_HINTS[method])

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
        self.hint.setText(self.tr(EDIT_HINT))
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
from .gui.profile_dock import ProfileDock
from .qgis_io.compat import gdal_problems

MENU = "&Terrain Sketch"


class TerrainSketchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dock = None
        self.profiles = None
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
        if self.profiles is not None:
            self.profiles.shutdown()
            self.iface.removeDockWidget(self.profiles)
            self.profiles.deleteLater()
            self.profiles = None
        if self.dock is not None:
            self.dock.shutdown()
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
            if not checked:
                self.dock.stop_tools()
            self.dock.setUserVisible(checked)
        if self.profiles is not None:
            self.profiles.setUserVisible(checked)

    def _create_dock(self) -> bool:
        problems = gdal_problems()
        if problems:
            self.iface.messageBar().pushCritical("Terrain Sketch", " ".join(problems))
            return False
        self.controller = SketchController(QgsProject.instance())
        self.profiles = ProfileDock(self.controller, self.iface.mainWindow())
        self.dock = MainDock(self.iface, self.controller, self.profiles, self.iface.mainWindow())
        self.dock.closedStateChanged.connect(lambda closed: self.action.setChecked(not closed))
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.profiles)
        return True
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_profile_dock.py tests/qgis/test_dock_plugin.py` → Expected: `21 passed`
Run: `scripts/test.sh` → Expected: `195 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/profile_dock.py terrain_sketch/gui/main_dock.py terrain_sketch/plugin.py tests/qgis/test_profile_dock.py tests/qgis/test_dock_plugin.py
git commit -m "feat(gui): the profile dock, wired to the panel and the plugin"
```

---

## Deferred items this plan closes

From the Plan 3 addendum and the Plan 1/2 carry-overs:

- **Preview performance.** Was ~200 ms at 1000×1000 against a 15 fps target; `preview_for` makes it 10.1 ms (99 fps). Measured in Task 1's test.
- **`FeatureStack.terrain_before(feature_id)`** — added in Task 1, and it is what the long section draws its dashed reference from.
- **Pruning `_windows` during preview.** Confirmed leak before the fix: a 60-frame drag left 60 cached windows, one per transient feature. `_prune_windows()` keeps only committed features; two tests pin it.
- **Renaming should not recompute.** `dirty_window` compared whole features, so a rename replayed the stack. It now compares `COMPUTED_FIELDS`, which excludes `name`.
- **Custom long-profile stations on a reshaped path** — `rescale_long_profile` scales them by the change in length, called from `set_geometry`.

## Known limitation, recorded deliberately

**End-cap cells on an asymmetric profile.** Measured during prototyping: with strongly different left and right profiles, cells off the axis beyond an end cap correctly take their own side's profile, but the thin on-axis sliver directly past each cap takes the right-hand one. It is invisible while Symmetric is ticked (the default), and fixing it means reworking how offsets are assigned past the caps — more engine surgery than this plan's scope. Left for a dedicated pass; noted here so the next reader does not rediscover it as a new bug.

## Manual check in QGIS (for the human, after merge)

1. Rebuild and reinstall the plugin, restart QGIS. Start a session on a projected DEM — a **Terrain Sketch — Profiles** dock should appear at the bottom.
2. Draw a **Raise path** dike. Select it: the cross profile shows the crest and slope, the long profile shows the terrain dashed with the design line above it.
3. Drag the slope handle in the cross profile. The map should update live while you drag, and the Width/Side slope fields should settle on release.
4. Untick **Symmetric** and drag again — only one side should change.
5. Drag a long-profile handle down. Height should grey out and the note should say the profile is custom; **Reset to rule** brings it back.
6. Draw a pond with **Lower flat**: the long panel becomes a read-only section, and Symmetric greys out.
7. Select a dike, press **Edit shape**, and stretch the path: a custom long profile should stretch with it rather than falling off the end.

## Roadmap: Plans 5-6

| Plan | Milestone | Builds on Plan 4 via |
|---|---|---|
| 5 | Illustrated gallery, help texts, pixel-mode pictures, "Reproject…" button, `QgsSettings` persistence, translation-ready strings | `help_texts.py`, `ProfileDock`, `ToolGallery` |
| 6 | Scenario GeoPackage, volumes panel, undo/redo, 3D view, duplicate/rename, ZIP packaging | `terrain_before` (volumes), `PreviewImage`, `TerrainFeature.to_dict/from_dict` |
