# Terrain Scenarios — Plan 1: Core Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure-Python terrain engine of Terrain Scenarios: the 7 terrain tools, pixel selection modes, side slopes, cross and long profiles, volumes, and the windowed feature-stack recompute. It comes with a complete automated test suite and needs no QGIS GUI.

**Architecture:** `terrain_scenarios/core/` holds pure numpy/scipy/GDAL modules with no QGIS imports. A `DemGrid` keeps the DEM in memory. `apply_feature` edits a grid in place, part by part. `FeatureStack` keeps the untouched original plus the working result, and after every change it recomputes only the window that can differ, including the dependency closure of overlapping features. `terrain_scenarios/model/feature.py` defines the immutable `TerrainFeature` data class that the engine consumes.

**Tech Stack:** Python 3.12, numpy 2.5, scipy 1.18, GDAL/OGR 3.13 (all bundled with QGIS 4.2.2), and pytest 9 as a dev-only dependency installed into `.devdeps/`.

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-scenarios-design.md` (§4 Architecture, §5 Tool behaviour, §6.3 Pixel modes, §8.3 Recompute, §10 Testing). Plan 1 implements spec milestone 1. Milestones 2–6 get their own plans (see "Roadmap" at the end).

## Global Constraints

- Target: QGIS 4.x (Qt6, Python 3.12), tested against QGIS 4.2.2 on macOS at `/Applications/QGIS-final-4_2_2.app`.
- `terrain_scenarios/core/` and `terrain_scenarios/model/` must never import `qgis` or `PyQt`. They may only use numpy, scipy and `osgeo` (gdal/ogr).
- No runtime dependency beyond what QGIS 4 bundles. pytest is dev-only, installed by `scripts/test.sh` into `.devdeps/`, and never shipped.
- The original DEM is never modified. Nodata cells are never modified or used as reference elevations.
- Raise tools compute `new = max(old, design)` (never remove material). Lower tools compute `new = min(old, design)` (never add material). Interpolate sets the design. Add and Subtract shift by the amount.
- Distances and elevations are in metres. Grids are north-up (negative pixel height); rotated rasters are rejected.
- Pixel modes: `all_touched`, `centre` (default) and `fully_inside`.
- Performance target: recompute of a 500×500-cell window in under 50 ms. The prototype measured 54 ms for 567×517 cells.
- Every package module (under `terrain_scenarios/`) starts with a one-line docstring and uses `from __future__ import annotations` where it has type hints. Test modules (`tests/`) need neither. All code uses 4-space indentation.
- Run tests only through `scripts/test.sh`, which sets `PYTHONHOME`, `PYTHONPATH` and `PROJ_DATA` for the QGIS app bundle.

## File Structure

| File | Responsibility |
|---|---|
| `scripts/test.sh` | Runs pytest with QGIS's bundled Python; installs pytest into `.devdeps/` on first run |
| `pytest.ini` | Test discovery settings |
| `terrain_scenarios/__init__.py` | Package marker (`classFactory` is added in Plan 2) |
| `terrain_scenarios/core/__init__.py` | Package marker |
| `terrain_scenarios/core/tools.py` | `Tool`, `Mode`, `PixelMode`, `Combine` enums and the `TOOL_INFO` table |
| `terrain_scenarios/core/grid.py` | `Window` (a cell block) and `DemGrid` (values, validity, geotransform, sampling) |
| `terrain_scenarios/core/geometry.py` | OGR helpers: parts, coordinates, envelope, corridor buffer, densify, WKB builders |
| `terrain_scenarios/core/mask.py` | Geometry → boolean mask for the three pixel modes |
| `terrain_scenarios/core/stations.py` | Station along a polyline and signed offset for points |
| `terrain_scenarios/core/profiles.py` | Cross-profile evaluation beyond a corridor edge or outline |
| `terrain_scenarios/core/volumes.py` | Cut/fill and pond storage |
| `terrain_scenarios/core/operations.py` | The 7 tools, `apply_feature`, footprints, flags, `rule_profile` |
| `terrain_scenarios/core/engine.py` | `FeatureStack`: dirty detection, dependency closure, windowed replay, preview |
| `terrain_scenarios/model/__init__.py` | Package marker |
| `terrain_scenarios/model/feature.py` | `TerrainFeature` dataclass, dict (de)serialisation, `new_feature` defaults |
| `tests/core/helpers.py` | Synthetic DEM builders and a `feature()` shortcut for tests |
| `tests/core/test_*.py` | One test module per core module |

Cell coordinate convention used throughout the tests: on a grid built with `make_grid(rows=40, cols=40, cell=1.0)`, cell `(r, c)` has its centre at `x = c + 0.5` and `y = 39.5 - r`, so row indices grow southwards.

---

### Task 1: Project scaffold, test runner, tool definitions and DemGrid

**Files:**
- Create: `scripts/test.sh`, `pytest.ini`, `terrain_scenarios/__init__.py`, `terrain_scenarios/core/__init__.py`, `terrain_scenarios/core/tools.py`, `terrain_scenarios/core/grid.py`, `tests/core/helpers.py`
- Modify: `.gitignore` (add `.devdeps/` and `.pytest_cache/`)
- Test: `tests/core/test_grid.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Tool` (INTERPOLATE, RAISE_PATH, LOWER_PATH, RAISE_FLAT, LOWER_FLAT, ADD, SUBTRACT), `Mode` (PATH, AREA), `PixelMode` (ALL_TOUCHED, CENTRE, FULLY_INSIDE), `Combine`, `ToolInfo(modes, combine, has_slopes, direction, reports_storage)` and `TOOL_INFO: dict[Tool, ToolInfo]`.
  - `Window(row0, col0, rows, cols)` with `.row1`, `.col1`, `.slices`, `.union(other|None)`, `.intersects(w)` and `.contains(w)`.
  - `DemGrid(data, valid, geotransform)` with `.from_array(array, gt, nodata=None)`, `.rows`, `.cols`, `.cell_width`, `.cell_height`, `.cell_size`, `.cell_area`, `.full_window`, `.copy()`, `.window_geotransform(w)`, `.subgrid(w)` (copy), `.view(w)` (shares memory), `.world_to_pixel(x, y) -> (col_f, row_f)`, `.cell_centers() -> (X, Y)`, `.window_for_bbox(xmin, ymin, xmax, ymax, margin_cells=0) -> Window | None` and `.sample(x, y, search_cells=3) -> float` (NaN if none).
  - Test helpers `make_grid(func, rows=40, cols=40, cell=1.0, nodata_cells=())`, `flat(z)`, `tilted(X, Y)` and `NODATA`.

- [ ] **Step 1: Create the test runner, pytest config, package markers and .gitignore entries**

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
if [ ! -d "$ROOT/.devdeps/pytest" ]; then
  "$PY" -m pip install -q --disable-pip-version-check --target "$ROOT/.devdeps" pytest >/dev/null 2>&1
fi
cd "$ROOT"
exec "$PY" -m pytest "$@"
```

**File:** `pytest.ini`
```ini
[pytest]
testpaths = tests
addopts = -q
```

**File:** `terrain_scenarios/__init__.py`
```python
"""Terrain Scenarios QGIS plugin."""
```

**File:** `terrain_scenarios/core/__init__.py`
```python
"""Pure-Python terrain engine (numpy/scipy/GDAL, no QGIS imports)."""
```

Run:
```bash
chmod +x scripts/test.sh && printf '.devdeps/\n.pytest_cache/\n' >> .gitignore
```

- [ ] **Step 2: Write the tool definitions**

These are plain data with no behaviour to test on their own; the operations tests exercise them.

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
```

- [ ] **Step 3: Write the test helpers and the failing grid tests**

**File:** `tests/core/helpers.py`
```python
"""Shared helpers for core tests: synthetic DEMs."""
import numpy as np

from terrain_scenarios.core.grid import DemGrid

NODATA = -9999.0


def make_grid(func, rows=40, cols=40, cell=1.0, nodata_cells=()):
    """North-up grid covering x 0..cols*cell and y 0..rows*cell with z = func(X, Y) at cell centres."""
    gt = (0.0, cell, 0.0, rows * cell, 0.0, -cell)
    xs = (np.arange(cols) + 0.5) * cell
    ys = rows * cell - (np.arange(rows) + 0.5) * cell
    X, Y = np.meshgrid(xs, ys)
    data = np.broadcast_to(np.asarray(func(X, Y), dtype=np.float32), X.shape).copy()
    for r, c in nodata_cells:
        data[r, c] = NODATA
    return DemGrid.from_array(data, gt, nodata=NODATA)


def flat(z):
    return lambda X, Y: np.full(X.shape, float(z))


def tilted(X, Y):
    """Rises 0.1 m per metre towards the east."""
    return 10.0 + 0.1 * X
```

**File:** `tests/core/test_grid.py`
```python
import math

import numpy as np
import pytest

from helpers import make_grid
from terrain_scenarios.core.grid import DemGrid, Window


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
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core/test_grid.py -v`
Expected: a collection error, `ModuleNotFoundError: No module named 'terrain_scenarios.core.grid'`. The first run also installs pytest into `.devdeps/`, which takes about 10 s.

- [ ] **Step 5: Implement the grid**

**File:** `terrain_scenarios/core/grid.py`
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

    def __init__(self, data: np.ndarray, valid: np.ndarray, geotransform):
        gt = tuple(float(v) for v in geotransform)
        if gt[2] != 0.0 or gt[4] != 0.0:
            raise ValueError("Rotated rasters are not supported")
        if gt[5] >= 0.0:
            raise ValueError("Raster must be north-up (negative pixel height)")
        self.data = data
        self.valid = valid
        self.geotransform = gt

    @classmethod
    def from_array(cls, array, geotransform, nodata=None) -> DemGrid:
        data = np.array(array, dtype=np.float32)
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
        return DemGrid(self.data.copy(), self.valid.copy(), self.geotransform)

    def window_geotransform(self, window: Window) -> tuple:
        x0, px, _, y0, _, py = self.geotransform
        return (x0 + window.col0 * px, px, 0.0, y0 + window.row0 * py, 0.0, py)

    def subgrid(self, window: Window) -> DemGrid:
        """Independent copy of a window."""
        rs, cs = window.slices
        return DemGrid(self.data[rs, cs].copy(), self.valid[rs, cs].copy(), self.window_geotransform(window))

    def view(self, window: Window) -> DemGrid:
        """Window sharing memory with this grid: writes to the view change this grid."""
        rs, cs = window.slices
        return DemGrid(self.data[rs, cs], self.valid[rs, cs], self.window_geotransform(window))

    def world_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        """Continuous (col, row); cell (r, c) covers [c, c+1) x [r, r+1)."""
        x0, px, _, y0, _, py = self.geotransform
        return (x - x0) / px, (y - y0) / py

    def cell_centers(self) -> tuple[np.ndarray, np.ndarray]:
        x0, px, _, y0, _, py = self.geotransform
        xs = x0 + (np.arange(self.cols) + 0.5) * px
        ys = y0 + (np.arange(self.rows) + 0.5) * py
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

- [ ] **Step 6: Run the tests to verify they pass**

Run: `scripts/test.sh tests/core/test_grid.py -v`
Expected: `6 passed`

- [ ] **Step 7: Commit**

```bash
git add .gitignore pytest.ini scripts/test.sh terrain_scenarios tests
git commit -m "feat(core): scaffold, test runner, tool definitions and DemGrid"
```

---

### Task 2: Geometry helpers

**Files:**
- Create: `terrain_scenarios/core/geometry.py`
- Test: `tests/core/test_geometry.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (OGR only).
- Produces:
  - `split_parts(wkb: bytes) -> list[ogr.Geometry]`: single-part 2D LineStrings and Polygons; raises `ValueError` for points and other types.
  - `is_line(part) -> bool`, `line_coords(part) -> ndarray (N, 2)` (repeated points removed), `polygon_rings(part) -> list[ndarray]` (exterior first, closed) and `envelope(part) -> (xmin, ymin, xmax, ymax)`.
  - `simplify_line(part, tolerance)`, `corridor(line_part, width) -> ogr polygon` (flat caps, mitre joins) and `densify(coords, step) -> ndarray`.
  - `line_wkb(coords) -> bytes`, `polygon_wkb(exterior, holes=()) -> bytes` and `multi_wkb(wkbs) -> bytes`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_geometry.py`
```python
import numpy as np
import pytest
from osgeo import ogr

from terrain_scenarios.core.geometry import (corridor, densify, envelope, is_line, line_coords,
                                          line_wkb, multi_wkb, polygon_wkb, split_parts)


def test_split_parts_handles_multi_and_rejects_points():
    wkb = multi_wkb([line_wkb([(0, 0), (1, 1)]), line_wkb([(2, 2), (3, 3)])])
    parts = split_parts(wkb)
    assert len(parts) == 2 and all(is_line(p) for p in parts)
    assert not is_line(split_parts(polygon_wkb([(0, 0), (1, 0), (1, 1)]))[0])
    with pytest.raises(ValueError):
        split_parts(bytes(ogr.CreateGeometryFromWkt("POINT (1 1)").ExportToWkb()))


def test_corridor_has_flat_end_caps():
    c = corridor(split_parts(line_wkb([(0, 0), (10, 0)]))[0], 2.0)
    assert c.GetArea() == pytest.approx(20.0)
    assert envelope(c) == pytest.approx((0, -1, 10, 1))


def test_line_coords_drops_repeated_points():
    line = split_parts(line_wkb([(0, 0), (0, 0), (5, 0), (5, 0), (5, 5)]))[0]
    np.testing.assert_array_equal(line_coords(line), [[0, 0], [5, 0], [5, 5]])


def test_densify_keeps_vertices_and_max_spacing():
    pts = densify(np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 4.0]]), 3.0)
    assert pts[0].tolist() == [0, 0] and pts[-1].tolist() == [10, 4]
    assert [10.0, 0.0] in pts.tolist()
    assert np.hypot(*np.diff(pts, axis=0).T).max() <= 3.0 + 1e-9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core/test_geometry.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_scenarios.core.geometry'`

- [ ] **Step 3: Implement the geometry helpers**

The flat-cap buffer uses `Geometry.Buffer(distance, options)`. That's the options form of `Buffer`, verified in the GDAL 3.13 Python bindings shipped with QGIS 4.2.2. `BufferEx` is **not** available there.

**File:** `terrain_scenarios/core/geometry.py`
```python
"""OGR geometry helpers: WKB in/out, single-part LineStrings/Polygons in the DEM CRS."""
from __future__ import annotations

import math

import numpy as np
from osgeo import ogr

ogr.UseExceptions()

_SINGLE = (ogr.wkbLineString, ogr.wkbPolygon)
_MULTI = (ogr.wkbMultiLineString, ogr.wkbMultiPolygon, ogr.wkbGeometryCollection)


def split_parts(wkb: bytes) -> list:
    """Single-part 2D LineStrings/Polygons contained in `wkb`. Raises ValueError for other types."""
    geom = ogr.CreateGeometryFromWkb(bytes(wkb))
    parts: list = []
    _collect(geom, parts)
    return parts


def _collect(geom, parts: list) -> None:
    if geom is None or geom.IsEmpty():
        return
    gtype = ogr.GT_Flatten(geom.GetGeometryType())
    if ogr.GT_IsNonLinear(gtype):
        geom = geom.GetLinearGeometry()
        gtype = ogr.GT_Flatten(geom.GetGeometryType())
    if gtype in _SINGLE:
        part = geom.Clone()
        part.FlattenTo2D()
        parts.append(part)
    elif gtype in _MULTI:
        for i in range(geom.GetGeometryCount()):
            _collect(geom.GetGeometryRef(i), parts)
    else:
        raise ValueError(f"Unsupported geometry type: {ogr.GeometryTypeToName(gtype)}")


def is_line(part) -> bool:
    return ogr.GT_Flatten(part.GetGeometryType()) == ogr.wkbLineString


def line_coords(part) -> np.ndarray:
    """(N, 2) vertices with consecutive duplicates removed."""
    pts = np.array(part.GetPoints(), dtype=float)[:, :2]
    keep = np.ones(len(pts), dtype=bool)
    keep[1:] = np.any(np.diff(pts, axis=0) != 0.0, axis=1)
    return pts[keep]


def polygon_rings(part) -> list[np.ndarray]:
    """Closed rings as (N, 2) arrays, exterior first."""
    return [np.array(part.GetGeometryRef(i).GetPoints(), dtype=float)[:, :2]
            for i in range(part.GetGeometryCount())]


def envelope(part) -> tuple[float, float, float, float]:
    xmin, xmax, ymin, ymax = part.GetEnvelope()
    return xmin, ymin, xmax, ymax


def simplify_line(part, tolerance: float):
    simple = part.Simplify(tolerance)
    return simple if simple is not None and not simple.IsEmpty() else part


def corridor(line_part, width: float):
    """The line buffered by width/2 with flat end caps and mitre joins."""
    return line_part.Buffer(width / 2.0, ["ENDCAP_STYLE=FLAT", "JOIN_STYLE=MITRE", "MITRE_LIMIT=2.0"])


def densify(coords: np.ndarray, step: float) -> np.ndarray:
    """Points along a polyline/ring at most `step` apart, including every vertex."""
    out = [coords[:1]]
    for a, b in zip(coords[:-1], coords[1:]):
        n = max(1, math.ceil(float(np.hypot(*(b - a))) / step))
        t = np.arange(1, n + 1)[:, None] / n
        out.append(a + t * (b - a))
    return np.vstack(out)


def line_wkb(coords) -> bytes:
    g = ogr.Geometry(ogr.wkbLineString)
    for x, y in coords:
        g.AddPoint_2D(float(x), float(y))
    return bytes(g.ExportToWkb())


def polygon_wkb(exterior, holes=()) -> bytes:
    g = ogr.Geometry(ogr.wkbPolygon)
    for ring_coords in (exterior, *holes):
        ring = ogr.Geometry(ogr.wkbLinearRing)
        for x, y in ring_coords:
            ring.AddPoint_2D(float(x), float(y))
        ring.CloseRings()
        g.AddGeometry(ring)
    return bytes(g.ExportToWkb())


def multi_wkb(wkbs) -> bytes:
    """Combine single-part WKBs of the same kind into a Multi* WKB."""
    parts = [ogr.CreateGeometryFromWkb(bytes(w)) for w in wkbs]
    kind = ogr.wkbMultiLineString if is_line(parts[0]) else ogr.wkbMultiPolygon
    g = ogr.Geometry(kind)
    for p in parts:
        g.AddGeometry(p)
    return bytes(g.ExportToWkb())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/test.sh tests/core/test_geometry.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/core/geometry.py tests/core/test_geometry.py
git commit -m "feat(core): OGR geometry helpers with flat-cap corridors"
```

---

### Task 3: Pixel masks (all touched / centre inside / fully inside)

**Files:**
- Create: `terrain_scenarios/core/mask.py`
- Test: `tests/core/test_mask.py`

**Interfaces:**
- Consumes: `DemGrid` (Task 1), `PixelMode` (Task 1), and `polygon_wkb`/`split_parts` (Task 2, tests only).
- Produces:
  - `rasterize(geom, grid, all_touched: bool) -> ndarray[bool]` with the shape of `grid`.
  - `polygon_mask(polygon, grid, mode: PixelMode) -> ndarray[bool]`.
  - The fully-inside rule: `centre & ~all_touched(boundary)`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_mask.py`
```python
import numpy as np
import pytest

from helpers import make_grid
from terrain_scenarios.core.geometry import polygon_wkb, split_parts
from terrain_scenarios.core.mask import polygon_mask
from terrain_scenarios.core.tools import PixelMode

# Square from 0.7 to 4.6 on a 1 m grid: touches cells 0..4, centres 1..4 inside, cells 1..3 fully inside.
SQUARE = polygon_wkb([(0.7, 0.7), (4.6, 0.7), (4.6, 4.6), (0.7, 4.6)])


@pytest.mark.parametrize("mode, count", [
    (PixelMode.ALL_TOUCHED, 25),
    (PixelMode.CENTRE, 16),
    (PixelMode.FULLY_INSIDE, 9),
])
def test_square_cell_counts(mode, count):
    grid = make_grid(lambda X, Y: 0 * X, rows=6, cols=6)
    assert polygon_mask(split_parts(SQUARE)[0], grid, mode).sum() == count


def test_modes_are_nested_for_random_polygons():
    rng = np.random.default_rng(1)
    grid = make_grid(lambda X, Y: 0 * X, rows=30, cols=30)
    for _ in range(20):
        cx, cy = rng.uniform(8, 22, 2)
        radius = rng.uniform(2, 8)
        angles = np.sort(rng.uniform(0, 2 * np.pi, 7))
        ring = [(cx + radius * rng.uniform(0.6, 1) * np.cos(a), cy + radius * rng.uniform(0.6, 1) * np.sin(a))
                for a in angles]
        poly = split_parts(polygon_wkb(ring))[0]
        touched, centre, inside = (polygon_mask(poly, grid, m) for m in
                                   (PixelMode.ALL_TOUCHED, PixelMode.CENTRE, PixelMode.FULLY_INSIDE))
        assert (inside <= centre).all() and (centre <= touched).all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core/test_mask.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_scenarios.core.mask'`

- [ ] **Step 3: Implement the masks**

**File:** `terrain_scenarios/core/mask.py`
```python
"""Geometry -> boolean cell mask for the three pixel modes (GDAL in-memory rasterisation)."""
from __future__ import annotations

import numpy as np
from osgeo import gdal, ogr

from .grid import DemGrid
from .tools import PixelMode

gdal.UseExceptions()


def rasterize(geom, grid: DemGrid, all_touched: bool) -> np.ndarray:
    raster = gdal.GetDriverByName("MEM").Create("", grid.cols, grid.rows, 1, gdal.GDT_Byte)
    raster.SetGeoTransform(grid.geotransform)
    vector = gdal.GetDriverByName("MEM").Create("", 0, 0, 0, gdal.GDT_Unknown)
    layer = vector.CreateLayer("g", geom_type=ogr.wkbUnknown)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geom)
    layer.CreateFeature(feature)
    options = ["ALL_TOUCHED=TRUE"] if all_touched else []
    gdal.RasterizeLayer(raster, [1], layer, burn_values=[1], options=options)
    return raster.GetRasterBand(1).ReadAsArray().astype(bool)


def polygon_mask(polygon, grid: DemGrid, mode: PixelMode) -> np.ndarray:
    """Cells selected by `polygon` over the whole of `grid`.

    all_touched: every cell the polygon touches; centre: cells whose centre is inside;
    fully_inside: centre inside and not crossed by the boundary."""
    if mode is PixelMode.ALL_TOUCHED:
        return rasterize(polygon, grid, all_touched=True)
    centre = rasterize(polygon, grid, all_touched=False)
    if mode is PixelMode.CENTRE:
        return centre
    return centre & ~rasterize(polygon.GetBoundary(), grid, all_touched=True)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/test.sh tests/core/test_mask.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/core/mask.py tests/core/test_mask.py
git commit -m "feat(core): pixel masks for all-touched, centre and fully-inside modes"
```

---

### Task 4: Stations along a path and cross-profile evaluation

**Files:**
- Create: `terrain_scenarios/core/stations.py`, `terrain_scenarios/core/profiles.py`
- Test: `tests/core/test_stations_profiles.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (numpy only).
- Produces:
  - `vertex_stations(coords) -> ndarray`: cumulative length at each vertex.
  - `stations_offsets(coords, X, Y) -> (station, offset)`: offset is positive on the right of travel and negative on the left.
  - `side_limit(breaks, slope_n, reach) -> float`: the farthest distance a side can change.
  - `side_dz(x, breaks, slope_n, reach, direction) -> (dz, in_extent)`: `breaks` are `((distance beyond edge, dz), ...)`, and `direction` is -1 (down, raise tools) or +1 (up, lower tools).

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_stations_profiles.py`
```python
import numpy as np

from terrain_scenarios.core.profiles import side_dz
from terrain_scenarios.core.stations import stations_offsets, vertex_stations


def test_station_and_signed_offset():
    coords = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
    X = np.array([5.0, 5.0, 12.0, 11.0])
    Y = np.array([2.0, -3.0, 5.0, -1.0])
    station, offset = stations_offsets(coords, X, Y)
    np.testing.assert_allclose(station, [5, 5, 15, 10])
    np.testing.assert_allclose(offset, [-2, 3, 2, np.sqrt(2)])  # left negative, right positive
    np.testing.assert_allclose(vertex_stations(coords), [0, 10, 20])


def test_terminal_slope_goes_down_until_reach():
    dz, inside = side_dz([0, 3, 6, 9], (), slope_n=3, reach=6, direction=-1)
    np.testing.assert_allclose(dz, [0, -1, -2, -3])
    assert inside.tolist() == [True, True, True, False]


def test_break_points_then_upward_slope():
    dz, inside = side_dz([1, 2, 4, 6], ((2.0, 0.5), (4.0, 0.5)), slope_n=2, reach=10, direction=1)
    np.testing.assert_allclose(dz, [0.25, 0.5, 0.5, 1.5])
    assert inside.all()


def test_no_slope_ends_at_last_break():
    _, inside = side_dz([0, 1, 2], (), slope_n=0, reach=10, direction=-1)
    assert inside.tolist() == [True, False, False]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core/test_stations_profiles.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_scenarios.core.profiles'`

- [ ] **Step 3: Implement stations and profiles**

**File:** `terrain_scenarios/core/stations.py`
```python
"""Station (distance along a path) and signed offset of points relative to a polyline."""
from __future__ import annotations

import numpy as np


def vertex_stations(coords: np.ndarray) -> np.ndarray:
    """Cumulative distance along the polyline at each vertex (first = 0)."""
    seg = np.hypot(*np.diff(coords, axis=0).T)
    return np.concatenate([[0.0], np.cumsum(seg)])


def stations_offsets(coords: np.ndarray, X: np.ndarray, Y: np.ndarray):
    """For every point: station of the nearest point on the polyline and the signed
    distance to it (positive right of the direction of travel, negative left)."""
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    best = np.full(X.shape, np.inf)
    station = np.zeros(X.shape)
    side = np.ones(X.shape)
    cum = 0.0
    for (ax, ay), (bx, by) in zip(coords[:-1], coords[1:]):
        dx, dy = bx - ax, by - ay
        length2 = dx * dx + dy * dy
        length = float(np.sqrt(length2))
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / length2, 0.0, 1.0)
        d2 = (X - (ax + t * dx)) ** 2 + (Y - (ay + t * dy)) ** 2
        better = d2 < best
        best = np.where(better, d2, best)
        station = np.where(better, cum + t * length, station)
        cross = dx * (Y - ay) - dy * (X - ax)  # > 0: left of travel (y axis up)
        side = np.where(better, np.where(cross > 0.0, -1.0, 1.0), side)
        cum += length
    return station, side * np.sqrt(best)
```

**File:** `terrain_scenarios/core/profiles.py`
```python
"""Cross-profile evaluation beyond a corridor edge or outline."""
from __future__ import annotations

import numpy as np


def side_limit(breaks, slope_n: float, reach: float) -> float:
    """Farthest distance beyond the edge that a side (break points + slope) can change."""
    last = max([0.0] + [float(x) for x, _ in breaks])
    return max(reach, last) if slope_n > 0.0 else last


def side_dz(x, breaks, slope_n: float, reach: float, direction: int):
    """Height change and in-extent mask at distance `x` (>= 0) beyond the edge.

    `breaks` are (distance, dz) points beyond the edge (the edge itself is (0, 0)).
    After the last point the side slope continues at 1:`slope_n` (`direction` -1 = down,
    +1 = up) until `reach` from the edge; `slope_n` <= 0 means no terminal slope."""
    x = np.asarray(x, dtype=float)
    pts = [(0.0, 0.0)] + sorted((float(a), float(b)) for a, b in breaks if a > 0.0)
    xs = np.array([p[0] for p in pts])
    zs = np.array([p[1] for p in pts])
    dz = np.interp(x, xs, zs)
    if slope_n > 0.0:
        dz = np.where(x > xs[-1], zs[-1] + direction * (x - xs[-1]) / slope_n, dz)
    return dz, x <= side_limit(breaks, slope_n, reach)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/test.sh tests/core/test_stations_profiles.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/core/stations.py terrain_scenarios/core/profiles.py tests/core/test_stations_profiles.py
git commit -m "feat(core): path stations/offsets and cross-profile evaluation"
```

---

### Task 5: TerrainFeature model

**Files:**
- Create: `terrain_scenarios/model/__init__.py`, `terrain_scenarios/model/feature.py`
- Modify: `tests/core/helpers.py` (add the `feature()` shortcut; the full file is shown below)
- Test: `tests/core/test_feature.py`

**Interfaces:**
- Consumes: `Tool`, `Mode`, `PixelMode` and `TOOL_INFO` (Task 1), and `line_wkb`/`polygon_wkb` (Task 2, tests only).
- Produces:
  - `TerrainFeature`, a frozen and hashable dataclass with the fields `id`, `name`, `tool`, `mode`, `geometry_wkb`, `enabled=True`, `pixel_mode=CENTRE`, `amount=1.0`, `width=2.0`, `slope_n=3.0`, `reach=20.0`, `slopes_inside=False`, `cross_left=()`, `cross_right=()` and `long_profile=None`.
  - `.to_dict()` and `TerrainFeature.from_dict(d)`; construction raises `ValueError` for an unsupported tool/mode combination.
  - `default_width(cell_size) -> float` and `new_feature(tool, mode, geometry_wkb, cell_size, name=None) -> TerrainFeature`.
  - Test helper `feature(tool, mode, wkb, **kw)`, which defaults to `id="f1"` and `name="test"`.

- [ ] **Step 1: Extend the test helpers and write the failing tests**

**File:** `tests/core/helpers.py`
```python
"""Shared helpers for core tests: synthetic DEMs and features."""
import numpy as np

from terrain_scenarios.core.grid import DemGrid
from terrain_scenarios.model.feature import TerrainFeature

NODATA = -9999.0


def make_grid(func, rows=40, cols=40, cell=1.0, nodata_cells=()):
    """North-up grid covering x 0..cols*cell and y 0..rows*cell with z = func(X, Y) at cell centres."""
    gt = (0.0, cell, 0.0, rows * cell, 0.0, -cell)
    xs = (np.arange(cols) + 0.5) * cell
    ys = rows * cell - (np.arange(rows) + 0.5) * cell
    X, Y = np.meshgrid(xs, ys)
    data = np.broadcast_to(np.asarray(func(X, Y), dtype=np.float32), X.shape).copy()
    for r, c in nodata_cells:
        data[r, c] = NODATA
    return DemGrid.from_array(data, gt, nodata=NODATA)


def flat(z):
    return lambda X, Y: np.full(X.shape, float(z))


def tilted(X, Y):
    """Rises 0.1 m per metre towards the east."""
    return 10.0 + 0.1 * X


def feature(tool, mode, wkb, **kw):
    kw.setdefault("id", "f1")
    kw.setdefault("name", "test")
    return TerrainFeature(tool=tool, mode=mode, geometry_wkb=wkb, **kw)
```

**File:** `tests/core/test_feature.py`
```python
import json
from dataclasses import replace

import pytest

from terrain_scenarios.core.geometry import line_wkb, polygon_wkb
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.model.feature import TerrainFeature, new_feature

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core -v`
Expected: collection errors `ModuleNotFoundError: No module named 'terrain_scenarios.model'`. Every module importing `helpers` fails to collect until the model exists.

- [ ] **Step 3: Implement the model**

**File:** `terrain_scenarios/model/__init__.py`
```python
"""Scenario data model (no QGIS imports)."""
```

**File:** `terrain_scenarios/model/feature.py`
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/test.sh tests/core -v`
Expected: `22 passed` (18 from Tasks 1–4 plus 4 new)

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/model tests/core/helpers.py tests/core/test_feature.py
git commit -m "feat(model): immutable TerrainFeature with dict round-trip and defaults"
```

---

### Task 6: Volumes (cut/fill and pond storage)

**Files:**
- Create: `terrain_scenarios/core/volumes.py`
- Test: `tests/core/test_volumes.py`

**Interfaces:**
- Consumes: `DemGrid` (Task 1).
- Produces:
  - `cut_fill(before, after, valid, cell_area) -> (cut, fill)` in m³.
  - `pond_storage(after, lowered, valid, cell_area) -> float | None`: storage below the lowest rim cell (8-connected ring) around the lowered region.
  - `total_cut_fill(original: DemGrid, working: DemGrid) -> (cut, fill)`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_volumes.py`
```python
import numpy as np
import pytest

from helpers import flat, make_grid
from terrain_scenarios.core.volumes import cut_fill, pond_storage, total_cut_fill


def test_cut_fill_and_storage_on_small_arrays():
    before = np.full((5, 5), 10.0)
    after = before.copy()
    after[1:4, 1:4] = 8.0
    after[0, 0] = 11.0
    valid = np.ones((5, 5), bool)
    cut, fill = cut_fill(before, after, valid, 2.0)
    assert cut == pytest.approx(36.0) and fill == pytest.approx(2.0)
    assert pond_storage(after, after < before, valid, 1.0) == pytest.approx(18.0)  # spill at 10
    assert pond_storage(after, np.zeros_like(valid), valid, 1.0) is None


def test_pond_storage_ignores_nodata_cells_inside_the_pond():
    after = np.full((5, 5), 10.0)
    after[1:4, 1:4] = 8.0
    after[2, 2] = -9999.0  # nodata sentinel inside the lowered region
    valid = np.ones((5, 5), bool)
    valid[2, 2] = False
    assert pond_storage(after, after < 10.0, valid, 1.0) == pytest.approx(16.0)  # 8 valid cells x 2 m


def test_total_cut_fill_compares_working_with_original():
    original = make_grid(flat(10))
    working = original.copy()
    working.data[0, 0] = 12
    working.data[1, 1] = 9
    cut, fill = total_cut_fill(original, working)
    assert cut == pytest.approx(1.0) and fill == pytest.approx(2.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core/test_volumes.py -v`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_scenarios.core.volumes'`

- [ ] **Step 3: Implement volumes**

**File:** `terrain_scenarios/core/volumes.py`
```python
"""Cut/fill and pond storage volumes."""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from .grid import DemGrid


def cut_fill(before: np.ndarray, after: np.ndarray, valid: np.ndarray, cell_area: float):
    """(cut, fill) in cubic metres between two elevation arrays over valid cells."""
    diff = np.where(valid, after.astype(np.float64) - before.astype(np.float64), 0.0)
    return float(-diff[diff < 0.0].sum() * cell_area), float(diff[diff > 0.0].sum() * cell_area)


def pond_storage(after: np.ndarray, lowered: np.ndarray, valid: np.ndarray, cell_area: float):
    """Static storage below the lowest rim cell around the lowered region, or None.

    The rim is the ring of valid cells bordering the lowered region (8-connected);
    nodata cells never count as pond or rim."""
    lowered = lowered & valid
    if not lowered.any():
        return None
    rim = ndimage.binary_dilation(lowered, structure=np.ones((3, 3), bool)) & ~lowered & valid
    if not rim.any():
        return None
    spill = float(after[rim].min())
    depth = np.where(lowered, spill - after.astype(np.float64), 0.0)
    return float(np.clip(depth, 0.0, None).sum() * cell_area)


def total_cut_fill(original: DemGrid, working: DemGrid):
    """(cut, fill) of the whole scenario."""
    return cut_fill(original.data, working.data, original.valid, original.cell_area)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/test.sh tests/core/test_volumes.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/core/volumes.py tests/core/test_volumes.py
git commit -m "feat(core): cut/fill and pond storage volumes"
```

---

### Task 7: The seven terrain tools (`operations.py`)

**Files:**
- Create: `terrain_scenarios/core/operations.py`
- Modify: `tests/core/test_volumes.py` (add the dike volume test; the full file is shown below)
- Test: `tests/core/test_operations.py`

**Interfaces:**
- Consumes:
  - `DemGrid`, `Window` and `TOOL_INFO`/enums (Task 1).
  - The geometry helpers (Task 2).
  - `polygon_mask` (Task 3).
  - `stations_offsets`, `vertex_stations`, `side_dz` and `side_limit` (Task 4).
  - `TerrainFeature` fields (Task 5).
  - `cut_fill` and `pond_storage` (Task 6).
- Produces:
  - `MARGIN_CELLS = 4`.
  - Flags `FLAG_OUTSIDE = "outside"`, `FLAG_NO_PIXELS = "no_pixels"`, `FLAG_NODATA_REFERENCE = "nodata_reference"` and `FLAG_BAD_GEOMETRY = "bad_geometry"`.
  - `FeatureStats(cut=0.0, fill=0.0, storage=None, changed_cells=0, flags=())`, a frozen dataclass.
  - `NoReferenceError`.
  - `path_coords(part, cell_size) -> ndarray`: the simplified path vertices, which Plan 4's profile editor also uses.
  - `rule_profile(feature, part, grid) -> ((station, z), ...)`: the tool-rule design line of one path part, which Plan 4 also uses.
  - `part_window(feature, part, grid) -> Window | None` and `feature_window(feature, grid) -> Window | None`: every cell a feature may read or change, including slope reach and margin.
  - `footprint_flags(feature) -> tuple` and `apply_feature(feature, grid) -> FeatureStats` (edits `grid` in place).

Behaviour, per spec §5:
- **Paths** use a flat-capped corridor of width `max(W, cell)`; the pixel mode selects the corridor cells.
- **Path side slopes** are measured as distance beyond the corridor. This is the Euclidean distance transform of the centre-mode corridor minus half a cell, so dike ends slope down too and leave no hole.
- **Cells with slope values**: stations and offsets are computed only for cells that can change.
- **Areas** use distance transforms for outside slopes. Inside slopes use the terrain just outside the outline (`return_indices`).
- **Storage** is reported for Interpolate (area), Lower path, Lower flat and Subtract, over the lowered cells.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_operations.py`
```python
import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_scenarios.core.geometry import line_wkb, multi_wkb, polygon_wkb
from terrain_scenarios.core.operations import (FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS,
                                            FLAG_NODATA_REFERENCE, FLAG_OUTSIDE, apply_feature)
from terrain_scenarios.core.tools import Mode, PixelMode, Tool

# On the default 40 x 40 grid (1 m cells) cell (r, c) has its centre at x = c + 0.5, y = 39.5 - r.
EAST_WEST = line_wkb([(5.25, 20.25), (34.75, 20.25)])  # runs through row 19 (y 20..21)
ROW = 19


def square(x0, y0, x1, y1):
    return polygon_wkb([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def bump(X, Y):
    return 3.0 * np.exp(-((X - 20.0) ** 2 + (Y - 20.5) ** 2) / 8.0)


def run(grid, f):
    before = grid.data.astype(float).copy()
    stats = apply_feature(f, grid)
    return before, grid.data.astype(float), stats


def test_add_path_raises_corridor_by_exact_amount():
    _, after, stats = run(g := make_grid(flat(5)), feature(Tool.ADD, Mode.PATH, EAST_WEST, amount=1.5, width=3.0))
    changed = after != 5.0
    assert changed.sum() == 3 * 30  # rows 18..20, cols 5..34
    np.testing.assert_allclose(after[changed], 6.5)
    assert stats.fill == pytest.approx(90 * 1.5) and stats.cut == 0 and stats.storage is None
    assert g.valid.all()


def test_subtract_area_keeps_the_relief():
    before, after, stats = run(make_grid(tilted), feature(Tool.SUBTRACT, Mode.AREA, square(10.3, 10.3, 20.3, 20.3), amount=2.0))
    changed = after != before
    assert changed.sum() == 100
    np.testing.assert_allclose((before - after)[changed], 2.0, atol=1e-5)
    assert stats.cut == pytest.approx(200.0, rel=1e-5)


def test_interpolate_path_grades_straight_through_a_bump():
    _, after, _ = run(make_grid(lambda X, Y: tilted(X, Y) + bump(X, Y)),
                      feature(Tool.INTERPOLATE, Mode.PATH, EAST_WEST, width=1.0))
    xs = np.arange(5, 34) + 0.5
    np.testing.assert_allclose(after[ROW, 5:34], 10 + 0.1 * xs, atol=1e-3)


def test_raise_path_never_lowers_and_builds_a_crest():
    before, after, stats = run(make_grid(lambda X, Y: tilted(X, Y) + bump(X, Y)),
                               feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, amount=1.0, width=2.0, slope_n=2.0))
    assert (after >= before - 1e-5).all()
    assert after[ROW, 8] == pytest.approx(10 + 0.1 * 8.5 + 1.0, abs=1e-3)  # 1 m above the grade
    assert after[ROW, 20] == pytest.approx(before[ROW, 20])  # the 3 m bump is already higher
    assert stats.cut == 0 and stats.fill > 0


def test_lower_path_never_raises_and_cuts_a_ditch():
    before, after, stats = run(make_grid(lambda X, Y: tilted(X, Y) - bump(X, Y)),
                               feature(Tool.LOWER_PATH, Mode.PATH, EAST_WEST, amount=1.0, width=2.0, slope_n=2.0))
    assert (after <= before + 1e-5).all()
    assert after[ROW, 8] == pytest.approx(10 + 0.1 * 8.5 - 1.0, abs=1e-3)
    assert after[ROW, 20] == pytest.approx(before[ROW, 20])  # the pit is already deeper
    assert stats.fill == 0 and stats.cut > 0


def test_path_side_slopes_fall_one_in_n_including_the_ends():
    _, after, _ = run(make_grid(flat(0)),
                      feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, amount=2.0, width=2.0, slope_n=4.0))
    assert after[ROW, 20] == pytest.approx(2.0)
    np.testing.assert_allclose(np.diff(after[18:12:-1, 20]), -0.25, atol=1e-6)  # northwards
    assert after[ROW, 35] > after[ROW, 36] > 0.0  # the dike end slopes down, no hole
    assert after[0, 20] == 0.0  # beyond 8 m the slope has met the ground


def test_raise_flat_path_is_level_at_highest_vertex_plus_height():
    wkb = line_wkb([(5.25, 20.25), (20.25, 20.25), (34.75, 20.25)])
    _, after, _ = run(make_grid(tilted), feature(Tool.RAISE_FLAT, Mode.PATH, wkb, amount=0.5, width=1.0, slope_n=0.0))
    np.testing.assert_allclose(after[ROW, 5:35], 10 + 0.1 * 34.75 + 0.5, atol=1e-4)


def test_lower_flat_area_basin_and_storage():
    _, after, stats = run(make_grid(flat(10)),
                          feature(Tool.LOWER_FLAT, Mode.AREA, square(10.3, 10.3, 20.3, 20.3), amount=1.0, slope_n=0.0))
    assert (after == 9).sum() == 100
    assert stats.cut == pytest.approx(100.0)
    assert stats.storage == pytest.approx(100.0)


def test_area_slopes_outside_fall_one_in_n_and_stop_at_reach():
    poly = square(15.3, 15.3, 25.3, 25.3)  # cells 15..24
    _, after, _ = run(make_grid(flat(0)), feature(Tool.RAISE_FLAT, Mode.AREA, poly, amount=2.0, slope_n=4.0))
    assert after[20, 20] == pytest.approx(2.0)
    np.testing.assert_allclose(np.diff(after[20, 25:31]), -0.25, atol=1e-6)
    _, capped, _ = run(make_grid(flat(0)),
                       feature(Tool.RAISE_FLAT, Mode.AREA, poly, amount=2.0, slope_n=40.0, reach=3.0))
    assert capped[20, 26] > 0.0 and capped[20, 29] == 0.0


def test_pond_slopes_inside_meet_the_terrain_at_the_outline():
    poly = square(10.3, 10.3, 30.3, 30.3)  # cells 10..29
    _, after, stats = run(make_grid(flat(10)), feature(Tool.LOWER_FLAT, Mode.AREA, poly, amount=2.0,
                                                       slope_n=2.0, slopes_inside=True))
    assert after[20, 10] == pytest.approx(9.75)  # first cell inside the outline
    np.testing.assert_allclose(np.diff(after[20, 10:14]), -0.5, atol=1e-6)
    assert after[20, 20] == pytest.approx(8.0)  # flat floor
    assert (after[:, :10] == 10).all()  # nothing outside the outline changes
    assert stats.storage == pytest.approx(stats.cut)


def test_interpolate_area_reproduces_a_plane_and_fills_a_ditch():
    ditch = lambda X, Y: tilted(X, Y) - np.where(np.abs(X - 20.5) < 1.0, 2.0, 0.0)  # noqa: E731
    grid = make_grid(ditch)
    poly = polygon_wkb([(12.3, 12.3), (28.7, 12.1), (29.2, 27.9), (24.7, 31.3), (11.8, 27.7)])
    before, after, _ = run(grid, feature(Tool.INTERPOLATE, Mode.AREA, poly))
    X, _ = grid.cell_centers()
    changed = after != before
    np.testing.assert_allclose(after[changed], (10 + 0.1 * X)[changed], atol=1e-3)
    assert after[20, 20] == pytest.approx(10 + 0.1 * 20.5, abs=1e-3)  # ditch cell filled


def test_nodata_cells_are_never_modified():
    grid = make_grid(flat(10), nodata_cells=[(15, 15), (16, 16)])
    _, after, _ = run(grid, feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 30.3, 30.3), amount=1.0))
    assert after[15, 15] == -9999 and after[16, 16] == -9999 and not grid.valid[15, 15]
    assert after[20, 20] == 11


def test_multi_part_areas_use_their_own_reference_levels():
    west, east = square(5.3, 15.3, 10.3, 20.3), square(25.3, 15.3, 30.3, 20.3)
    _, after, _ = run(make_grid(tilted), feature(Tool.RAISE_FLAT, Mode.AREA, multi_wkb([west, east]),
                                                 amount=1.0, slope_n=0.0))
    assert after[22, 7] == pytest.approx(10 + 0.1 * 10.3 + 1.0, abs=1e-3)
    assert after[22, 27] == pytest.approx(10 + 0.1 * 30.3 + 1.0, abs=1e-3)


def test_dragged_long_profile_still_never_cuts():
    low = ((0.0, 5.0), (29.5, 5.0))
    before, after, stats = run(make_grid(flat(10)), feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, long_profile=low))
    assert (after == before).all() and stats.fill == 0 and stats.flags == ()
    high = ((0.0, 12.0), (29.5, 14.0))
    _, after2, _ = run(make_grid(flat(10)), feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST, long_profile=high, slope_n=0.0))
    assert after2[ROW, 20] == pytest.approx(12.0 + 2.0 * (20.5 - 5.25) / 29.5, abs=1e-3)


def test_problem_flags():
    grid = make_grid(flat(10))
    far = feature(Tool.ADD, Mode.PATH, line_wkb([(500, 500), (600, 600)]))
    assert apply_feature(far, grid).flags == (FLAG_OUTSIDE,)
    thin = feature(Tool.ADD, Mode.PATH, EAST_WEST, width=1.0, pixel_mode=PixelMode.FULLY_INSIDE)
    assert apply_feature(thin, grid).flags == (FLAG_NO_PIXELS,)
    wrong = feature(Tool.ADD, Mode.PATH, square(1.3, 1.3, 5.3, 5.3))
    assert apply_feature(wrong, grid).flags == (FLAG_BAD_GEOMETRY,)
    holes = [(r, c) for r in range(12, 29) for c in range(0, 14)]
    start_on_nodata = feature(Tool.RAISE_PATH, Mode.PATH, EAST_WEST)
    assert FLAG_NODATA_REFERENCE in apply_feature(start_on_nodata, make_grid(flat(10), nodata_cells=holes)).flags
```

Replace the whole test volume module to add the dike check:

**File:** `tests/core/test_volumes.py`
```python
import numpy as np
import pytest

from helpers import feature, flat, make_grid
from terrain_scenarios.core.geometry import line_wkb
from terrain_scenarios.core.operations import apply_feature
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.core.volumes import cut_fill, pond_storage, total_cut_fill


def test_cut_fill_and_storage_on_small_arrays():
    before = np.full((5, 5), 10.0)
    after = before.copy()
    after[1:4, 1:4] = 8.0
    after[0, 0] = 11.0
    valid = np.ones((5, 5), bool)
    cut, fill = cut_fill(before, after, valid, 2.0)
    assert cut == pytest.approx(36.0) and fill == pytest.approx(2.0)
    assert pond_storage(after, after < before, valid, 1.0) == pytest.approx(18.0)  # spill at 10
    assert pond_storage(after, np.zeros_like(valid), valid, 1.0) is None


def test_pond_storage_ignores_nodata_cells_inside_the_pond():
    after = np.full((5, 5), 10.0)
    after[1:4, 1:4] = 8.0
    after[2, 2] = -9999.0  # nodata sentinel inside the lowered region
    valid = np.ones((5, 5), bool)
    valid[2, 2] = False
    assert pond_storage(after, after < 10.0, valid, 1.0) == pytest.approx(16.0)  # 8 valid cells x 2 m


def test_total_cut_fill_compares_working_with_original():
    original = make_grid(flat(10))
    working = original.copy()
    working.data[0, 0] = 12
    working.data[1, 1] = 9
    cut, fill = total_cut_fill(original, working)
    assert cut == pytest.approx(1.0) and fill == pytest.approx(2.0)


def test_dike_volume_matches_prism_plus_end_slopes():
    grid = make_grid(flat(0.0), rows=160, cols=160, cell=0.25)
    dike = feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(10.0, 20.0), (30.0, 20.0)]),
                   amount=1.0, width=2.0, slope_n=2.0)
    stats = apply_feature(dike, grid)
    W, H, n, L = 2.0, 1.0, 2.0, 20.0
    prism = L * (W * H + n * H * H)
    ends = W * n * H * H + np.pi * n * n * H ** 3 / 3.0  # two wedges + four quarter cones
    assert stats.fill == pytest.approx(prism + ends, rel=0.03)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core/test_operations.py tests/core/test_volumes.py -v`
Expected: collection errors `ModuleNotFoundError: No module named 'terrain_scenarios.core.operations'`

- [ ] **Step 3: Implement the operations**

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
from .tools import TOOL_INFO, Combine, Mode, PixelMode, Tool
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


def _reach(feature, part, cell_size: float) -> float:
    info = TOOL_INFO[feature.tool]
    if is_line(part):
        extra = max(feature.width, cell_size) / 2.0
        if info.has_slopes:
            extra += _path_side_limit(feature)
        return extra
    if info.has_slopes and feature.slope_n > 0.0 and not feature.slopes_inside:
        return feature.reach
    return 0.0


def part_window(feature, part, grid: DemGrid) -> Window | None:
    xmin, ymin, xmax, ymax = envelope(part)
    r = _reach(feature, part, grid.cell_size)
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
        if info.reports_storage and (feature.tool is not Tool.INTERPOLATE or not want_line):
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
    band = core if feature.pixel_mode is PixelMode.CENTRE else polygon_mask(band_geom, view, PixelMode.CENTRE)
    if not band.any():
        return old, core
    # distance beyond the flat-capped corridor edge (the outline lies half a cell from band centres)
    dist = ndimage.distance_transform_edt(~band, sampling=(view.cell_height, view.cell_width))
    beyond = np.maximum(dist - 0.5 * view.cell_size, 0.0)
    # stations only where a cell can change: the corridor and the cells within slope reach
    station, offset = _stations(coords, view, core | (beyond <= _path_side_limit(feature)))
    zline = np.interp(station, [p[0] for p in profile], [p[1] for p in profile])
    dz_l, ext_l = side_dz(beyond, feature.cross_left, feature.slope_n, feature.reach, info.direction)
    dz_r, ext_r = side_dz(beyond, feature.cross_right, feature.slope_n, feature.reach, info.direction)
    left = offset < 0.0
    in_extent = np.where(left, ext_l, ext_r)
    dz = np.where(core, 0.0, np.where(left, dz_l, dz_r))
    slope_cells = ~band & ~core & in_extent
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `scripts/test.sh tests/core/test_operations.py tests/core/test_volumes.py -v`
Expected: `19 passed` (15 operations + 4 volumes)

- [ ] **Step 5: Run the whole core suite**

Run: `scripts/test.sh tests/core`
Expected: `41 passed`

- [ ] **Step 6: Commit**

```bash
git add terrain_scenarios/core/operations.py tests/core/test_operations.py tests/core/test_volumes.py
git commit -m "feat(core): the seven terrain tools with side slopes, profiles and flags"
```

---

### Task 8: FeatureStack engine (windowed recompute) and performance check

**Files:**
- Create: `terrain_scenarios/core/engine.py`
- Test: `tests/core/test_engine.py`, `tests/core/test_performance.py`

**Interfaces:**
- Consumes: `DemGrid`/`Window` (Task 1), `TerrainFeature` (Task 5), and `FeatureStats`, `apply_feature`, `feature_window` and `footprint_flags` (Task 7).
- Produces `FeatureStack(original: DemGrid)`, which Plan 2's controller relies on:
  - `.original`, `.working` (DemGrid), `.features` (tuple) and `.stats` (`dict[id, FeatureStats]`).
  - `.update(features) -> Window | None`: makes the list current and recomputes; returns the changed window in full-grid cell coordinates.
  - `.preview(features) -> (Window, DemGrid) | None`: the result for the changed window, with no state change.
  - `.footprint(feature) -> Window | None`, `.dirty_window(features)`, `.closure(window, features) -> (Window, list)` and `.compute(features, window) -> (DemGrid, stats)`.
  - Disabled features get `FeatureStats()`. Enabled features off the grid get `FeatureStats(flags=footprint_flags(f))`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_engine.py`
```python
from dataclasses import replace

import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_scenarios.core.engine import FeatureStack
from terrain_scenarios.core.geometry import line_wkb, polygon_wkb
from terrain_scenarios.core.operations import FLAG_OUTSIDE, apply_feature
from terrain_scenarios.core.tools import TOOL_INFO, Mode, PixelMode, Tool


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
    _, grid = stack.preview([feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3))])
    assert (grid.data > 10).any()
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
```

**File:** `tests/core/test_performance.py`
```python
import time
from dataclasses import replace

from helpers import feature, make_grid
from terrain_scenarios.core.engine import FeatureStack
from terrain_scenarios.core.geometry import line_wkb
from terrain_scenarios.core.tools import Mode, Tool


def test_recompute_of_a_500_by_500_window_is_fast():
    """Spec target: < 50 ms on an M-class Mac. The assertion is looser to stay stable on CI."""
    stack = FeatureStack(make_grid(lambda X, Y: 10 + 0.01 * X, rows=1000, cols=1000, cell=0.4))
    wkb = line_wkb([(40.2, 150.2), (80.3, 230.1), (120.1, 190.3), (150.2, 300.2), (180.1, 260.2), (220.3, 350.1)])
    dike = feature(Tool.RAISE_PATH, Mode.PATH, wkb, amount=1.5, width=3.0, slope_n=3.0, reach=10.0)
    stack.update([dike])
    start = time.perf_counter()
    window = stack.update([replace(dike, amount=2.0)])
    elapsed = time.perf_counter() - start
    print(f"window {window.rows}x{window.cols}: {elapsed * 1000:.1f} ms")
    assert window.rows >= 500 and window.cols >= 450
    assert elapsed < 0.25
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `scripts/test.sh tests/core/test_engine.py tests/core/test_performance.py -v`
Expected: collection errors `ModuleNotFoundError: No module named 'terrain_scenarios.core.engine'`

- [ ] **Step 3: Implement the engine**

**File:** `terrain_scenarios/core/engine.py`
```python
"""FeatureStack: the ordered list of features and the windowed recompute of the working DEM."""
from __future__ import annotations

from .grid import DemGrid, Window
from .operations import FeatureStats, apply_feature, feature_window, footprint_flags


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

    def preview(self, features) -> tuple[Window, DemGrid] | None:
        """Result of `features` for the changed window, without changing the stack."""
        features = tuple(features)
        dirty = self.dirty_window(features)
        if dirty is None:
            return None
        window, replay = self.closure(dirty, features)
        grid, _ = self.compute(replay, window)
        return window, grid

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

- [ ] **Step 4: Run the engine and performance tests**

Run: `scripts/test.sh tests/core/test_engine.py tests/core/test_performance.py -v -s`
Expected: `14 passed` (7 engine tests + 6 property-test seeds + 1 performance test). The performance test prints a line like `window 567x517: 54.0 ms`, which is about 46 ms scaled to 500×500. If it reports more than 100 ms on an M-class Mac, profile `_path_values` before continuing; don't loosen the assertion.

- [ ] **Step 5: Run the whole core suite**

Run: `scripts/test.sh tests/core`
Expected: `55 passed`

- [ ] **Step 6: Commit**

```bash
git add terrain_scenarios/core/engine.py tests/core/test_engine.py tests/core/test_performance.py
git commit -m "feat(core): FeatureStack with dependency closure and windowed recompute"
```

---

## Roadmap: Plans 2–6

Each plan is written after the previous milestone lands, against the real interfaces, and follows spec §11:

| Plan | Milestone | Builds on Plan 1 via |
|---|---|---|
| 2 | Plugin shell and first flow: `metadata.txt`, `plugin.py`, the right dock, DEM loading (`qgis_io/raster_io.py`), the working, difference and hillshade layers, draw line/area map tools, the feature list, `SketchController`, and export | `FeatureStack.update/preview`, `new_feature`, `DemGrid.from_array`, `total_cut_fill` |
| 3 | All selection methods: freehand, brush, from layer, vertex edit, pixel-mode UI, and the Line/Area toggle | `geometry.line_wkb/polygon_wkb/multi_wkb`, `PixelMode`, `TOOL_INFO[tool].modes` |
| 4 | Profile dock: `ProfileWidget` (cross and long), live overlay preview, reset buttons | `rule_profile`, `path_coords`, `side_dz`, `FeatureStack.preview`, and the `TerrainFeature.cross_left/right/long_profile` fields |
| 5 | Guidance: tool gallery, illustrations, help texts, tooltips, pixel-mode pictures | `TOOL_INFO` (badges: adds only / removes only / path · area) |
| 6 | Scenario (GeoPackage), volumes UI, 3D view, undo/redo, error flags UI, ZIP packaging | `TerrainFeature.to_dict/from_dict`, `FeatureStats`, `FLAG_*` |
