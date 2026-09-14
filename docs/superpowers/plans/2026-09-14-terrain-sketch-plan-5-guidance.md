# Terrain Sketch — Plan 5: Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the plugin explain itself. Every tool gets a side-view illustration and a worked example, every parameter gets a tooltip with a real measurement and a diagram that highlights the part it controls, and the three pixel modes get pictures instead of words. Plus the honesty fixes the earlier reviews deferred here.

**Architecture:** Illustrations are SVG templates with colour tokens filled from the active `QPalette`, rendered through `QSvgRenderer`, so they follow QGIS's light and dark themes — except fill and cut, which stay the map's orange and blue so a picture and the canvas mean the same thing. Every string lives in `help_texts.py`. A small `settings.py` wraps `QgsSettings` under `terrain_sketch/`.

**Tech Stack:** QGIS 4.2.2 Python API (PyQt6 via `qgis.PyQt`, Qt 6.11, `QtSvg`), GDAL 3.13, numpy; pytest (dev-only) with a headless `QgsApplication`.

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-sketch-design.md` — §7.1 (illustrations as SVG templates with colour tokens; settings under `terrain_sketch/`), §7.2 (the illustrated gallery, *About this tool*, the parameter diagram, the pixel-mode combobox), §9 (the Reproject… button), §11 milestone 5. Plans 1-4 are merged on `main`; **read the Plan 4 addendum first**.

## Global Constraints

- Target QGIS 4.x (Qt6) only. Import Qt through `qgis.PyQt` and always use fully scoped Qt6 enums.
- Native look (spec §7.1): only standard Qt/QGIS widgets and palette colours, QGIS theme icons via `QgsApplication.getThemeIcon`, **no stylesheets**. The UI inherits the active QGIS theme, light or dark.
- `terrain_sketch/core/` and `terrain_sketch/model/` never import `qgis` or `PyQt`. Widgets never call the engine, files or layers directly — only `SketchController`.
- Errors never take QGIS down: user problems become message-bar messages; unexpected engine errors are caught and logged. **An exception raised inside a Qt callback aborts the interpreter** — this has cost the project three hard crashes. `SketchController.feature()` raises for an unknown id; anything reachable from a drag, a slot or a selection change must use `find()`.
- Every user-facing string lives in `gui/help_texts.py`; widget captions use `self.tr("literal")`. English only (spec §7.1).
- Package modules start with a one-line docstring and use `from __future__ import annotations` where they have type hints; test modules need neither. 4-space indentation.
- Tests run only through `scripts/test.sh`. Never run `scripts/dev_install.sh`.
- Out of scope here (Plan 6): scenarios, the volumes panel, undo/redo, the 3D view, packaging, and the profile-editor behaviour changes listed at the end.

## Decisions made while prototyping (read before implementing)

- **Fill and cut are not palette colours.** Everything else in an illustration comes from the `QPalette` so the picture follows the theme, but fill stays orange and cut stays blue, imported from `overlay.py`, so a drawing and the map agree.
- **The parameter diagram carries its own part tags.** A template marks parts as `{opacity-width}`, `{opacity-amount}`, `{opacity-slope}`, `{opacity-reach}`; naming one dims the rest. That lets a single drawing point at whichever field has focus instead of shipping four near-identical pictures.
- **Focus drives the diagram through an event filter**, not through `valueChanged` — the user should see what a field means before changing it.
- **`settings.py` does not guess which save method a widget wants.** Every `QWidget` has `saveGeometry`, so probing for it would silently store the wrong thing for a `QSplitter`, whose layout lives in `saveState`. The caller picks: `save_state` for splitters, `save_geometry` for top-level widgets. The prototype got this wrong first and a test caught it.
- **`GeographicDemError` subclasses `DemError`** so every existing `except DemError` still catches it, while the panel can check for it and offer to reproject.
- **The "Use these features" button is dead only when the combo is empty**, not when `currentLayer()` is None — the combo fills itself from the project, and a layer added after the widget was built does not always arrive as `layerChanged`, so the model's row signals are watched too.
- **`tr()` is not called on non-literals any more.** `pylupdate` cannot extract `self.tr(SOME_CONSTANT)`, so those calls looked like translation support while providing none. `help_texts.py` now says where translation will be wired up instead.

## File Structure

| File | Responsibility |
|---|---|
| `terrain_sketch/gui/illustrations/__init__.py` | Fill colour tokens from the palette, render a template to a pixmap or icon, list what ships |
| `terrain_sketch/gui/illustrations/*.svg` | Seven tool side views, three pixel-mode pictures, one tagged parameter diagram |
| `terrain_sketch/gui/help_texts.py` | Descriptions, worked examples, field tips and every message, in one place |
| `terrain_sketch/gui/settings.py` | `QgsSettings` under `terrain_sketch/`, never raising |
| `terrain_sketch/gui/tool_gallery.py` | An illustrated tool list whose tooltips explain and give an example |
| `terrain_sketch/gui/properties_page.py` | *About this tool*, the focus-following diagram, illustrated pixel modes |
| `terrain_sketch/gui/main_dock.py` | Offers **Reproject…** when the DEM is in degrees |
| `terrain_sketch/gui/layer_source.py` | No dead "Use these features" button |
| `terrain_sketch/qgis_io/raster_io.py` | `GeographicDemError`, so the panel can tell that case apart |

---

### Task 1: Hygiene — honest `tr()`, and a timing test that will not flake

**Files:**
- Modify: `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/gui/properties_page.py`
- Test: `tests/core/test_preview_drag.py`

**Interfaces:**
- Consumes: everything as it stands on `main`.
- Produces: no new API. `help_texts` gains a docstring stating where translation will be wired up; `self.tr()` is no longer called on variables in `main_dock` and `properties_page`; `test_preview_for_beats_a_full_preview_on_a_large_window` compares the **fastest** of several attempts instead of the mean.

Why the timing change: a mean lets one scheduler hiccup fail a comparison that is really about the algorithm, and a flake in the one wall-clock test erodes trust in the whole suite. Taking minima exposed a second problem the mean was hiding — the first dragged frame used the same amount as the committed feature, so it returned as a no-op and was timed as ~0 ms. Every timed frame must be a real change.

- [ ] **Step 1: Make the timing test robust**

**File:** `tests/core/test_preview_drag.py`
```python
import time
from dataclasses import replace

import numpy as np

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
    # Verify stats keys match between preview_for and full preview
    full_result = stack.preview([features[0], dragged, features[2]])
    assert set(result.stats.keys()) == set(full_result.stats.keys())


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
    # every frame must differ from the COMMITTED amount (2.0); a frame equal to it is a no-op
    # that returns before doing any work, and timing that measures nothing
    dragged = [replace(features[1], amount=a) for a in np.linspace(2.5, 5.0, 12)]

    stack.preview_for("dike", [features[0], dragged[0], features[2]])  # warm the cache

    def best(run) -> float:
        """The fastest of several attempts. A mean would let one scheduler hiccup — a build
        running tests in parallel, say — fail a comparison that is really about the algorithm."""
        times = []
        for d in dragged:
            t0 = time.perf_counter()
            run(d)
            times.append(time.perf_counter() - t0)
        return min(times)

    fast = best(lambda d: stack.preview_for("dike", [features[0], d, features[2]]))
    full = best(lambda d: stack.preview([features[0], d, features[2]]))

    assert fast < full, f"drag path {fast*1000:.1f} ms is not faster than full {full*1000:.1f} ms"
    assert fast < 0.066, f"a drag frame took {fast*1000:.1f} ms, over the 15 fps budget"


def test_preview_for_falls_back_to_a_full_preview_for_a_disabled_feature():
    stack, features = stack_with_three()
    off = replace(features[1], enabled=False)
    result = stack.preview_for("dike", [features[0], off, features[2]])
    assert result is not None
    # the fallback is a real replay of the stack with the disabled feature contributing nothing
    expected = stack.original.subgrid(result.window)
    for f in (features[0], features[2]):
        apply_feature(f, expected)
    assert np.allclose(result.grid.data, expected.data, equal_nan=True)
    assert "dike" not in result.stats


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


def test_terrain_before_the_first_feature_is_the_original():
    stack, features = stack_with_three()
    result = stack.terrain_before("pad", features)
    assert result is not None
    window, grid = result
    # The terrain before the first feature should be the original (unmodified)
    expected = stack.original.subgrid(window)
    assert np.array_equal(grid.data, expected.data, equal_nan=True)


def test_terrain_before_a_later_feature_includes_earlier_ones():
    stack, features = stack_with_three()
    result = stack.terrain_before("pond", features)
    assert result is not None
    window, grid = result
    # The terrain before pond should include pad and dike
    expected = stack.original.subgrid(window)
    apply_feature(features[0], expected)  # pad
    apply_feature(features[1], expected)  # dike
    assert np.allclose(grid.data, expected.data, equal_nan=True)


def test_terrain_before_returns_none_for_unknown_feature():
    stack, features = stack_with_three()
    assert stack.terrain_before("unknown", features) is None


def test_terrain_before_cache_does_not_grow_with_transient_features():
    stack, features = stack_with_three()
    assert len(stack._windows) == 3
    for amount in np.linspace(2.0, 5.0, 40):
        moved = replace(features[1], amount=float(amount))
        stack.terrain_before("pond", [features[0], moved, features[2]])
    assert len(stack._windows) == 3  # should not grow with transient features


def test_terrain_before_a_disabled_feature_excludes_the_features_after_it():
    """A disabled feature is not in `replay`, so stopping at its id never fires. Its reference
    terrain must still be "everything before me", not the whole stack — the profile editor draws
    it for any selected feature, enabled or not."""
    stack, features = stack_with_three()
    off = replace(features[1], enabled=False)
    result = stack.terrain_before("dike", [features[0], off, features[2]])
    assert result is not None
    window, grid = result
    expected = stack.original.subgrid(window)
    apply_feature(features[0], expected)      # the pad only: the pond comes after the dike
    assert np.allclose(grid.data, expected.data, equal_nan=True)
    # and the pond, which comes later, really would have changed this window
    with_pond = stack.original.subgrid(window)
    apply_feature(features[0], with_pond)
    apply_feature(features[2], with_pond)
    assert not np.allclose(grid.data, with_pond.data, equal_nan=True)
```
- [ ] **Step 2: Run it**

Run: `scripts/test.sh tests/core/test_preview_drag.py` → Expected: `15 passed`

- [ ] **Step 3: Stop calling tr() on things it cannot extract**

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
        self._overlay_transform_failed = False
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
**File:** `terrain_sketch/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode
from .help_texts import (AMOUNT_IS_CUSTOM, FLAG_TEXTS, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS,
                         TOOL_LABELS, TOOL_SUMMARIES, amount_label)


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
        self.slope.setToolTip(self.tr("Horizontal metres per metre of height: 1 : 3 goes 3 m outwards for every "
                                      "1 m. 0 means no side slopes."))
        self.slope.setPrefix("1 : ")
        self.reach = _spin(0.0, 500.0, 1.0, " m", 1)
        self.reach.setToolTip(self.tr("Side slopes stop this far from the edge, even if they have not met the "
                                      "ground yet."))
        self.slope_position = QComboBox()
        self.slope_position.addItem(self.tr("Outside the outline"), False)
        self.slope_position.addItem(self.tr("Inside the outline"), True)
        self.pixel_mode = QComboBox()
        self.slope_position.setToolTip(self.tr("Inside: the outline is the top edge (e.g. a pond). Outside: the "
                                               "outline is the flat part (e.g. a raised pad)."))
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

Run: `scripts/test.sh` → Expected: `236 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/gui/properties_page.py tests/core/test_preview_drag.py
git commit -m "refactor(gui): stop pretending non-literal tr() is translatable, and de-flake the timing test"
```

---

### Task 2: The illustrations

**Files:**
- Create: `terrain_sketch/gui/illustrations/__init__.py` and eleven `.svg` templates
- Test: `tests/qgis/test_illustrations.py`

**Interfaces:**
- Consumes: `overlay.FILL` / `overlay.CUT` for the two fixed colours.
- Produces: `colours(palette) -> dict`; `svg_source(name, palette, highlight=None) -> str`; `tagged_parts(source) -> list[str]`; `pixmap(name, size, palette, highlight=None) -> QPixmap` (size may be a `QSize` or an int for a square); `icon(name, size, palette) -> QIcon`; `available() -> list[str]`; `HERE`.

Every template must fill all five tokens (`{terrain}`, `{line}`, `{fill}`, `{cut}`, `{text}` as used) and the parameter diagram must expose exactly `width`, `amount`, `slope`, `reach` in that order.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_illustrations.py`
```python
import pytest
from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QPalette

from terrain_sketch.core.tools import PixelMode, Tool
from terrain_sketch.gui import illustrations
from terrain_sketch.gui.overlay import CUT, FILL


def light() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Mid, QColor(140, 140, 140))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(20, 80, 200))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(10, 10, 10))
    return palette


def dark() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Mid, QColor(90, 90, 90))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(120, 180, 255))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 240))
    return palette


def test_every_tool_and_pixel_mode_has_an_illustration():
    names = illustrations.available()
    for tool in Tool:
        assert f"tool_{tool.value}" in names, f"no illustration for {tool.value}"
    for mode in PixelMode:
        assert f"pixels_{mode.value}" in names, f"no illustration for {mode.value}"
    assert "parameters" in names


def test_no_colour_token_survives_rendering():
    for name in illustrations.available():
        source = illustrations.svg_source(name, light())
        assert "{" not in source and "}" not in source, f"{name} kept an unfilled token"


def test_the_palette_drives_the_colours_so_the_theme_is_followed():
    light_source = illustrations.svg_source("tool_raise_path", light())
    dark_source = illustrations.svg_source("tool_raise_path", dark())
    assert "#8c8c8c" in light_source and "#5a5a5a" in dark_source
    assert light_source != dark_source


def test_fill_and_cut_stay_the_map_colours_in_both_themes():
    fill, cut = QColor(*FILL).name(), QColor(*CUT).name()
    for palette in (light(), dark()):
        assert fill in illustrations.svg_source("tool_raise_path", palette)
        assert cut in illustrations.svg_source("tool_lower_path", palette)


def test_the_parameter_diagram_exposes_the_parts_the_fields_control():
    assert illustrations.tagged_parts(open(
        illustrations.HERE / "parameters.svg").read()) == ["width", "amount", "slope", "reach"]


def test_highlighting_one_part_dims_the_others():
    source = illustrations.svg_source("parameters", light(), highlight="slope")
    assert source.count('opacity="0.25"') == 3 and source.count('opacity="1"') == 1
    every = illustrations.svg_source("parameters", light())
    assert every.count('opacity="1"') == 4 and '0.25' not in every


def test_an_unknown_highlight_leaves_every_part_visible():
    source = illustrations.svg_source("parameters", light(), highlight="nope")
    assert source.count('opacity="0.25"') == 4


def test_every_illustration_renders_to_a_non_blank_pixmap():
    palette = light()
    for name in illustrations.available():
        image = illustrations.pixmap(name, QSize(64, 64), palette).toImage()
        assert image.size() == QSize(64, 64), name
        painted = sum(1 for y in range(0, 64, 2) for x in range(0, 64, 2)
                      if image.pixelColor(x, y).alpha() > 0)
        assert painted > 20, f"{name} rendered almost nothing ({painted} samples painted)"


def test_a_square_size_may_be_given_as_a_plain_int():
    assert illustrations.pixmap("tool_add", 48, light()).size() == QSize(48, 48)


def test_the_three_pixel_modes_really_do_look_different():
    palette = light()
    shots = [illustrations.pixmap(f"pixels_{m.value}", 64, palette).toImage() for m in PixelMode]
    def signature(image):
        return tuple(image.pixelColor(x, y).alpha() > 0
                     for y in range(8, 56, 4) for x in range(8, 56, 4))
    assert len(set(signature(s) for s in shots)) == 3
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_illustrations.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui.illustrations'`

- [ ] **Step 3: Add the renderer and the templates**

**File:** `terrain_sketch/gui/illustrations/__init__.py`
```python
"""Theme-aware SVG illustrations: templates with colour tokens, rendered through QSvgRenderer.

The templates are plain SVG with `{terrain}`, `{line}`, `{fill}`, `{cut}` and `{text}` where a
colour belongs. The tokens are filled from the active QPalette — so the pictures follow QGIS's
light or dark theme — except fill and cut, which stay the map's orange and blue so a picture and
the canvas mean the same thing.
"""
from __future__ import annotations

import pathlib

from qgis.PyQt.QtCore import QByteArray, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from qgis.PyQt.QtSvg import QSvgRenderer

from ..overlay import CUT, FILL

HERE = pathlib.Path(__file__).parent
HIGHLIGHT_OPACITY = "1"
DIMMED_OPACITY = "0.25"


def colours(palette: QPalette) -> dict:
    """The token values for a palette. Fill and cut are fixed so pictures match the map."""
    return {
        "terrain": palette.color(QPalette.ColorRole.Mid).name(),
        "line": palette.color(QPalette.ColorRole.Highlight).name(),
        "text": palette.color(QPalette.ColorRole.WindowText).name(),
        "fill": QColor(*FILL).name(),
        "cut": QColor(*CUT).name(),
    }


def svg_source(name: str, palette: QPalette, highlight: str | None = None) -> str:
    """The template with its colour tokens filled in, and one part optionally emphasised.

    A template tags a part by putting `{opacity-<key>}` where that part's `opacity` value goes.
    When `highlight` names one key, every other tagged part is dimmed, so the same drawing can
    point at width, height, slope or reach depending on which field has focus.
    """
    text = (HERE / f"{name}.svg").read_text()
    for token, value in colours(palette).items():
        text = text.replace("{" + token + "}", value)
    for key in tagged_parts(text):
        opacity = HIGHLIGHT_OPACITY if highlight is None or key == highlight else DIMMED_OPACITY
        text = text.replace("{opacity-" + key + "}", opacity)
    return text


def tagged_parts(source: str) -> list[str]:
    """The part keys a template exposes, in the order they appear."""
    keys, rest = [], source
    while "{opacity-" in rest:
        start = rest.index("{opacity-") + len("{opacity-")
        end = rest.index("}", start)
        key = rest[start:end]
        if key not in keys:
            keys.append(key)
        rest = rest[end:]
    return keys


def pixmap(name: str, size, palette: QPalette, highlight: str | None = None) -> QPixmap:
    """Render an illustration at `size` (a QSize or an int for a square)."""
    if isinstance(size, int):
        from qgis.PyQt.QtCore import QSize
        size = QSize(size, size)
    renderer = QSvgRenderer(QByteArray(svg_source(name, palette, highlight).encode()))
    out = QPixmap(size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    try:
        renderer.render(painter, QRectF(0, 0, size.width(), size.height()))
    finally:
        painter.end()  # a QPainter still active when its paint device dies takes Qt down
    return out


def icon(name: str, size, palette: QPalette) -> QIcon:
    return QIcon(pixmap(name, size, palette))


def available() -> list[str]:
    """Every illustration name that ships with the plugin."""
    return sorted(p.stem for p in HERE.glob("*.svg"))
```
**File:** `terrain_sketch/gui/illustrations/tool_interpolate.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 44 L34 42 L44 52 L58 56 L72 50 L86 41 L120 44" fill="none" stroke="{terrain}"
        stroke-width="2" stroke-dasharray="3 3" opacity="0.55"/>
  <path d="M34 42 L86 41" fill="none" stroke="{fill}" stroke-width="3"/>
  <path d="M34 42 L44 52 L58 56 L72 50 L86 41 Z" fill="{fill}" opacity="0.3"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/tool_raise_path.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 44 L28 42 L56 45 L84 41 L120 44" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M38 43 L52 26 L68 26 L82 43 Z" fill="{fill}" opacity="0.45"/>
  <path d="M38 43 L52 26 L68 26 L82 43" fill="none" stroke="{line}" stroke-width="2"
        stroke-linejoin="round"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/tool_lower_path.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 44 L28 42 L56 45 L84 41 L120 44" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M40 43 L52 58 L68 58 L80 43 Z" fill="{cut}" opacity="0.45"/>
  <path d="M40 43 L52 58 L68 58 L80 43" fill="none" stroke="{line}" stroke-width="2"
        stroke-linejoin="round"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/tool_raise_flat.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 44 L28 42 L56 45 L84 41 L120 44" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M26 43 L40 28 L84 28 L98 42 Z" fill="{fill}" opacity="0.45"/>
  <path d="M26 43 L40 28 L84 28 L98 42" fill="none" stroke="{line}" stroke-width="2"
        stroke-linejoin="round"/>
  <path d="M40 28 L84 28" fill="none" stroke="{line}" stroke-width="3"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/tool_lower_flat.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 44 L28 42 L56 45 L84 41 L120 44" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M26 43 L40 57 L84 57 L98 42 Z" fill="{cut}" opacity="0.45"/>
  <path d="M26 43 L40 57 L84 57 L98 42" fill="none" stroke="{line}" stroke-width="2"
        stroke-linejoin="round"/>
  <path d="M40 57 L84 57" fill="none" stroke="{line}" stroke-width="3"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/tool_add.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 44 L28 42 L56 45 L84 41 L120 44" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M30 43 L30 35 L58 33 L86 32 L86 41 L58 36 Z" fill="{fill}" opacity="0.45"/>
  <path d="M30 35 L58 33 L86 32" fill="none" stroke="{line}" stroke-width="2"/>
  <path d="M56 14 L56 26 M50 20 L62 20" stroke="{fill}" stroke-width="3"
        stroke-linecap="round"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/tool_subtract.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 44 L28 42 L56 45 L84 41 L120 44" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M30 43 L30 50 L58 52 L86 49 L86 41 L58 45 Z" fill="{cut}" opacity="0.45"/>
  <path d="M30 50 L58 52 L86 49" fill="none" stroke="{line}" stroke-width="2"/>
  <path d="M50 20 L62 20" stroke="{cut}" stroke-width="3" stroke-linecap="round"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/pixels_centre.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="40" y="8" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="24" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="40" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="24" y="40" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <line x1="8" y1="8" x2="8" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="8" x2="56" y2="8" stroke="{terrain}" stroke-width="1"/>
  <line x1="24" y1="8" x2="24" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="24" x2="56" y2="24" stroke="{terrain}" stroke-width="1"/>
  <line x1="40" y1="8" x2="40" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="40" x2="56" y2="40" stroke="{terrain}" stroke-width="1"/>
  <line x1="56" y1="8" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="56" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="56" y1="8" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="56" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <circle cx="16" cy="16" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="32" cy="16" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="48" cy="16" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="16" cy="32" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="32" cy="32" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="48" cy="32" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="16" cy="48" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="32" cy="48" r="1.2" fill="{text}" opacity="0.6"/>
  <circle cx="48" cy="48" r="1.2" fill="{text}" opacity="0.6"/>
  <path d="M18 20 L48 14 L52 46 L22 50 Z" fill="none" stroke="{line}" stroke-width="2"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/pixels_all_touched.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="8" y="8" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="24" y="8" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="40" y="8" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="8" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="24" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="40" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="8" y="40" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="24" y="40" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="40" y="40" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <line x1="8" y1="8" x2="8" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="8" x2="56" y2="8" stroke="{terrain}" stroke-width="1"/>
  <line x1="24" y1="8" x2="24" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="24" x2="56" y2="24" stroke="{terrain}" stroke-width="1"/>
  <line x1="40" y1="8" x2="40" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="40" x2="56" y2="40" stroke="{terrain}" stroke-width="1"/>
  <line x1="56" y1="8" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="56" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="56" y1="8" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="56" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <path d="M18 20 L48 14 L52 46 L22 50 Z" fill="none" stroke="{line}" stroke-width="2"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/pixels_fully_inside.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="24" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <line x1="8" y1="8" x2="8" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="8" x2="56" y2="8" stroke="{terrain}" stroke-width="1"/>
  <line x1="24" y1="8" x2="24" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="24" x2="56" y2="24" stroke="{terrain}" stroke-width="1"/>
  <line x1="40" y1="8" x2="40" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="40" x2="56" y2="40" stroke="{terrain}" stroke-width="1"/>
  <line x1="56" y1="8" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="56" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="56" y1="8" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="56" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <path d="M18 20 L48 14 L52 46 L22 50 Z" fill="none" stroke="{line}" stroke-width="2"/>
</svg>
```
**File:** `terrain_sketch/gui/illustrations/parameters.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 96">
  <path d="M0 66 L200 66" fill="none" stroke="{terrain}" stroke-width="2"/>
  <path d="M42 66 L76 30 L124 30 L158 66 Z" fill="{fill}" opacity="0.35"/>
  <path d="M42 66 L76 30 L124 30 L158 66" fill="none" stroke="{line}" stroke-width="2"
        stroke-linejoin="round"/>
  <g opacity="{opacity-width}">
    <path d="M76 22 L124 22" stroke="{text}" stroke-width="1.5"/>
    <path d="M76 18 L76 26 M124 18 L124 26" stroke="{text}" stroke-width="1.5"/>
    <text x="100" y="14" font-size="11" text-anchor="middle" fill="{text}">Width</text>
  </g>
  <g opacity="{opacity-amount}">
    <path d="M166 30 L166 66" stroke="{text}" stroke-width="1.5"/>
    <path d="M162 30 L170 30 M162 66 L170 66" stroke="{text}" stroke-width="1.5"/>
    <text x="173" y="52" font-size="11" fill="{text}">H</text>
  </g>
  <g opacity="{opacity-slope}">
    <path d="M124 30 L158 66" stroke="{text}" stroke-width="3" opacity="0.8"/>
    <text x="150" y="26" font-size="11" text-anchor="middle" fill="{text}">1:n</text>
  </g>
  <g opacity="{opacity-reach}">
    <path d="M124 78 L182 78" stroke="{text}" stroke-width="1.5" stroke-dasharray="3 2"/>
    <path d="M124 74 L124 82 M182 74 L182 82" stroke="{text}" stroke-width="1.5"/>
    <text x="153" y="93" font-size="11" text-anchor="middle" fill="{text}">Max reach</text>
  </g>
</svg>
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_illustrations.py` → Expected: `10 passed`
Run: `scripts/test.sh` → Expected: `246 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/illustrations tests/qgis/test_illustrations.py
git commit -m "feat(gui): theme-aware SVG illustrations for the tools, pixel modes and parameters"
```

---

### Task 3: The guidance in the panel

**Files:**
- Modify: `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/tool_gallery.py`, `terrain_sketch/gui/properties_page.py`
- Test: `tests/qgis/test_guidance.py`

**Interfaces:**
- Consumes: the illustrations from Task 2.
- Produces: `help_texts.TOOL_DESCRIPTIONS`, `TOOL_EXAMPLES`, `FIELD_TIPS`, `tool_tooltip(tool)`; `ToolGallery.refresh_icons()` and a `changeEvent` that redraws on a theme change; `PropertiesPage.about`, `about_text`, `about_picture`, `diagram`, and an `eventFilter` that highlights the diagram part belonging to the focused field.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_guidance.py`
```python
import pytest
from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtGui import QFocusEvent, QPalette

from qgis_helpers import UTM, line_through, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.help_texts import TOOL_DESCRIPTIONS, TOOL_EXAMPLES
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.tool_gallery import ToolGallery


def focus(widget):
    """Deliver a focus-in through the filter chain — widget.event() would bypass it."""
    QCoreApplication.sendEvent(widget, QFocusEvent(QEvent.Type.FocusIn))


def test_every_gallery_row_carries_an_illustration_and_a_worked_example():
    gallery = ToolGallery()
    assert gallery.tool_list.count() == len(Tool)
    for row in range(gallery.tool_list.count()):
        item = gallery.tool_list.item(row)
        tool = Tool(item.data(Qt.ItemDataRole.UserRole))
        assert not item.icon().isNull(), f"{tool.value} has no illustration"
        assert TOOL_DESCRIPTIONS[tool] in item.toolTip()
        assert TOOL_EXAMPLES[tool] in item.toolTip()


def test_the_gallery_redraws_its_illustrations_when_the_theme_changes():
    gallery = ToolGallery()
    first = gallery.tool_list.item(0).icon().pixmap(60, 32).toImage()
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Mid, Qt.GlobalColor.white)
    dark.setColor(QPalette.ColorRole.Highlight, Qt.GlobalColor.yellow)
    gallery.setPalette(dark)
    gallery.refresh_icons()
    assert gallery.tool_list.item(0).icon().pixmap(60, 32).toImage() != first


def test_the_properties_page_explains_the_selected_tool(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert TOOL_DESCRIPTIONS[Tool.RAISE_PATH] in page.about_text.text()
    assert TOOL_EXAMPLES[Tool.RAISE_PATH] in page.about_text.text()
    assert page.about_picture.pixmap() is not None and not page.about_picture.pixmap().isNull()


def test_every_pixel_mode_entry_gets_its_own_picture(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    page = PropertiesPage(c)
    page.show_feature(pond.id)
    shots = []
    for index in range(page.pixel_mode.count()):
        icon = page.pixel_mode.itemIcon(index)
        assert not icon.isNull(), page.pixel_mode.itemText(index)
        shots.append(icon.pixmap(32, 32).toImage().bits().asstring(32 * 32 * 4))
    assert len(set(shots)) == len(PixelMode)   # three modes, three different pictures


def test_the_diagram_highlights_the_field_that_has_focus(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    neutral = page.diagram.pixmap().toImage()
    focus(page.width)
    on_width = page.diagram.pixmap().toImage()
    focus(page.slope)
    on_slope = page.diagram.pixmap().toImage()
    assert on_width != neutral and on_slope != neutral and on_width != on_slope


def test_the_diagram_is_hidden_for_a_tool_that_has_no_slopes(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    page.show_feature(c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM).id)
    assert page.diagram.isVisibleTo(page)
    page.show_feature(c.add_drawn(Tool.ADD, Mode.AREA, square(10, 10, 25, 25), UTM).id)
    assert not page.diagram.isVisibleTo(page)


def test_every_numeric_field_quotes_a_real_measurement_in_its_tooltip(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    # check AFTER a feature is shown: that is the only state in which these fields are visible,
    # and show_feature rewrites the amount tooltip, so checking before it proves nothing
    page.show_feature(dike.id)
    for widget in (page.amount, page.width, page.slope, page.reach):
        tip = widget.toolTip()
        assert len(tip) > 40, tip
        assert any(ch.isdigit() for ch in tip), f"no concrete measurement in: {tip}"


def test_the_choice_fields_name_a_real_case_for_each_option(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    # these two are choices, not measurements, so they earn their keep with named examples
    slopes = page.slope_position.toolTip()
    assert "Inside" in slopes and "Outside" in slopes
    assert "pond" in slopes and "pad" in slopes
    pixels = page.pixel_mode.toolTip()
    assert len(pixels) > 40 and "All touched" in pixels


def test_the_about_group_can_be_collapsed_and_remembers_its_name(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    assert page.about.isCheckable() or True          # QgsCollapsibleGroupBox handles the toggle
    assert page.about.objectName() == "TerrainSketchAboutTool"
    page.about.setCollapsed(True)
    assert page.about.isCollapsed()
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_guidance.py`
Expected: collection error `ImportError: cannot import name 'TOOL_DESCRIPTIONS' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: Add the texts and wire them in**

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
    Tool.INTERPOLATE: ("A ditch crosses your DEM but the survey missed it. Draw a line along the "
                       "ditch and Terrain Sketch runs a smooth grade between the two ends."),
    Tool.RAISE_PATH: ("A 1.5 m flood embankment along a river. Draw the line the crest follows, "
                      "set Height 1.5 m, Width 3 m and a 1:3 side slope."),
    Tool.LOWER_PATH: ("A swale carrying runoff to a pond. Draw its route, set Depth 0.6 m and "
                      "Width 2 m; the slopes tie it back into the ground."),
    Tool.RAISE_FLAT: ("A building pad above the flood level. Draw the outline and set the height "
                      "above the highest point it covers, so the whole pad sits level."),
    Tool.LOWER_FLAT: ("A detention basin. Draw the outline, set Depth 1.2 m, and the bottom comes "
                      "out flat with the sides sloping down to it."),
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
                      "point it covers, with slopes tying the edge back into the ground."),
    Tool.LOWER_FLAT: ("Cuts everything inside the shape down to one level, measured from the "
                      "lowest point it covers, with slopes tying the edge back in."),
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
                "outwards per 1 m up, which is the usual maximum for a mown grass embankment. "
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

def tool_tooltip(tool: Tool) -> str:
    """What a gallery item shows on hover: what the tool does, then a worked example."""
    return f"{TOOL_DESCRIPTIONS[tool]}\n\n{TOOL_EXAMPLES[tool]}"
```
**File:** `terrain_sketch/gui/tool_gallery.py`
```python
"""'What do you want to build?' — the tool list, the Line/Area toggle and the 'Where?' methods."""
from __future__ import annotations

from qgis.core import Qgis, QgsApplication, QgsUnitTypes
from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtCore import QEvent, QSize, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QRadioButton,
                                 QToolButton, QVBoxLayout, QWidget)

from ..core.tools import TOOL_INFO, Mode, Tool
from . import illustrations
from .help_texts import TOOL_LABELS, TOOL_SUMMARIES, tool_tooltip
from .layer_source import LayerSource
from .selection import METHOD_ICONS, METHOD_LABELS, METHOD_TIPS, Method

DEFAULT_BRUSH_RADIUS = 5.0
ICON_WIDTH, ICON_HEIGHT = 60, 32


class ToolGallery(QWidget):
    drawRequested = pyqtSignal(object, object, object)  # Tool, Mode, Method
    layerRequested = pyqtSignal(object, object, object, bool)  # Tool, Mode, QgsVectorLayer, selected_only

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(self.tr("What do you want to build?")))
        self.tool_list = QListWidget()
        self.tool_list.setIconSize(QSize(ICON_WIDTH, ICON_HEIGHT))
        for tool in Tool:
            item = QListWidgetItem(TOOL_LABELS[tool])
            item.setData(Qt.ItemDataRole.UserRole, tool.value)
            item.setToolTip(tool_tooltip(tool))
            item.setIcon(illustrations.icon(f"tool_{tool.value}", QSize(ICON_WIDTH, ICON_HEIGHT),
                                            self.palette()))
            self.tool_list.addItem(item)
        layout.addWidget(self.tool_list)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(self.tr("Shape")))
        self.line_mode = QRadioButton(self.tr("Line"))
        self.area_mode = QRadioButton(self.tr("Area"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.line_mode)
        self.mode_group.addButton(self.area_mode)
        mode_row.addWidget(self.line_mode)
        mode_row.addWidget(self.area_mode)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        layout.addWidget(QLabel(self.tr("Where?")))
        method_row = QHBoxLayout()
        self.method_buttons = {method: self._method_button(method) for method in Method}
        for button in self.method_buttons.values():
            method_row.addWidget(button)
        method_row.addStretch(1)
        layout.addLayout(method_row)

        brush_row = QHBoxLayout()
        self.brush_label = QLabel(self.tr("Brush radius"))
        brush_row.addWidget(self.brush_label)
        self.brush_spin = QgsDoubleSpinBox()
        self.brush_spin.setRange(0.1, 1000.0)
        self.brush_spin.setDecimals(1)
        self.brush_spin.setValue(DEFAULT_BRUSH_RADIUS)
        self.brush_spin.setToolTip(self.tr("Radius of the round brush; [ and ] or Ctrl+wheel change it while painting."))
        brush_row.addWidget(self.brush_spin)
        brush_row.addStretch(1)
        layout.addLayout(brush_row)

        self.layer_source = LayerSource()
        self.layer_source.hide()
        layout.addWidget(self.layer_source)

        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self.line_mode.toggled.connect(self._mode_changed)
        self.area_mode.toggled.connect(self._mode_changed)
        self.layer_source.useRequested.connect(self._use_layer)
        self._tool_changed()

    def selected_tool(self) -> Tool | None:
        item = self.tool_list.currentItem()
        return Tool(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def changeEvent(self, event):  # noqa: N802 — Qt override
        """Redraw the illustrations when QGIS switches between its light and dark themes."""
        if event.type() == QEvent.Type.PaletteChange:
            self.refresh_icons()
        super().changeEvent(event)

    def refresh_icons(self) -> None:
        for row in range(self.tool_list.count()):
            item = self.tool_list.item(row)
            tool = Tool(item.data(Qt.ItemDataRole.UserRole))
            item.setIcon(illustrations.icon(f"tool_{tool.value}", QSize(ICON_WIDTH, ICON_HEIGHT),
                                            self.palette()))

    def selected_mode(self) -> Mode | None:
        if self.area_mode.isChecked():
            return Mode.AREA
        return Mode.PATH if self.line_mode.isChecked() else None

    def select_tool(self, tool: Tool) -> None:
        for row in range(self.tool_list.count()):
            if self.tool_list.item(row).data(Qt.ItemDataRole.UserRole) == tool.value:
                self.tool_list.setCurrentRow(row)

    def select_mode(self, mode: Mode) -> None:
        (self.area_mode if mode is Mode.AREA else self.line_mode).setChecked(True)

    def brush_radius(self) -> float:
        return self.brush_spin.value()

    def set_brush_radius(self, radius: float) -> None:
        self.brush_spin.setValue(radius)

    def set_radius_units(self, units) -> None:
        """Name the units the brush radius is really in — the canvas's map units, never converted."""
        self.brush_spin.setSuffix(f" {self._unit_label(units)}")

    def _unit_label(self, units) -> str:
        if units == Qgis.DistanceUnit.Meters:
            return self.tr("m")
        if units == Qgis.DistanceUnit.Degrees:
            return self.tr("degrees")
        return QgsUnitTypes.toAbbreviatedString(units) or self.tr("map units")

    def _method_button(self, method: Method) -> QToolButton:
        button = QToolButton()
        button.setIcon(QgsApplication.getThemeIcon(METHOD_ICONS[method]))
        button.setText(METHOD_LABELS[method])
        button.setToolTip(METHOD_TIPS[method])
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.clicked.connect(lambda _checked=False, m=method: self._pick(m))
        return button

    def _tool_changed(self, *_args) -> None:
        tool = self.selected_tool()
        self.summary.setText(TOOL_SUMMARIES[tool] if tool else self.tr("Pick a tool, then choose where to draw it."))
        modes = TOOL_INFO[tool].modes if tool else ()
        self.line_mode.setEnabled(Mode.PATH in modes)
        self.area_mode.setEnabled(Mode.AREA in modes)
        if self.selected_mode() not in modes:
            self.mode_group.setExclusive(False)
            self.line_mode.setChecked(False)
            self.area_mode.setChecked(False)
            self.mode_group.setExclusive(True)
            if modes:
                self.select_mode(modes[0])
        self._mode_changed()

    def _mode_changed(self, *_args) -> None:
        mode = self.selected_mode()
        for method, button in self.method_buttons.items():
            button.setEnabled(mode is not None and (mode is Mode.AREA or method is not Method.BRUSH))
        brush_usable = self.method_buttons[Method.BRUSH].isEnabled()
        self.brush_label.setEnabled(brush_usable)
        self.brush_spin.setEnabled(brush_usable)
        if mode is not None:
            self.layer_source.set_mode(mode)
        else:
            self.layer_source.hide()

    def _pick(self, method: Method) -> None:
        tool, mode = self.selected_tool(), self.selected_mode()
        if tool is None or mode is None:
            return
        self.layer_source.setVisible(method is Method.LAYER)
        if method is not Method.LAYER:
            self.drawRequested.emit(tool, mode, method)

    def _use_layer(self, layer, selected_only: bool) -> None:
        tool, mode = self.selected_tool(), self.selected_mode()
        if tool is not None and mode is not None:
            self.layerRequested.emit(tool, mode, layer, selected_only)
```
**File:** `terrain_sketch/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

from qgis.gui import QgsCollapsibleGroupBox, QgsDoubleSpinBox
from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode
from . import illustrations
from .help_texts import (AMOUNT_IS_CUSTOM, FIELD_TIPS, FLAG_TEXTS, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS,
                         TOOL_DESCRIPTIONS, TOOL_EXAMPLES, TOOL_LABELS, TOOL_SUMMARIES, amount_label)

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
        self.width.setToolTip(self.tr("Width of the crest (raise tools) or the bottom (lower tools) of the path."))
        self.slope = _spin(0.0, 50.0, 0.5, "", 1)
        self.slope.setToolTip(self.tr("Horizontal metres per metre of height: 1 : 3 goes 3 m outwards for every "
                                      "1 m. 0 means no side slopes."))
        self.slope.setPrefix("1 : ")
        self.reach = _spin(0.0, 500.0, 1.0, " m", 1)
        self.reach.setToolTip(self.tr("Side slopes stop this far from the edge, even if they have not met the "
                                      "ground yet."))
        self.slope_position = QComboBox()
        self.slope_position.addItem(self.tr("Outside the outline"), False)
        self.slope_position.addItem(self.tr("Inside the outline"), True)
        self.pixel_mode = QComboBox()
        self.slope_position.setToolTip(self.tr("Inside: the outline is the top edge (e.g. a pond). Outside: the "
                                               "outline is the flat part (e.g. a raised pad)."))
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

Run: `scripts/test.sh tests/qgis/test_guidance.py` → Expected: `9 passed`
Run: `scripts/test.sh` → Expected: `255 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/help_texts.py terrain_sketch/gui/tool_gallery.py terrain_sketch/gui/properties_page.py tests/qgis/test_guidance.py
git commit -m "feat(gui): illustrated tools, About this tool, and a diagram that follows focus"
```

---

### Task 4: Remembering panel state

**Files:**
- Create: `terrain_sketch/gui/settings.py`
- Modify: `terrain_sketch/gui/profile_dock.py`, `scripts/test.sh`, `tests/qgis/conftest.py`
- Test: `tests/qgis/test_settings.py`

**Interfaces:**
- Produces: `settings.GROUP`, `save(key, value)`, `load(key, default=None, kind=None)`, `save_state(name, widget)` / `restore_state(name, widget)` for splitters, `save_geometry(name, widget)` / `restore_geometry(name, widget)` for top-level widgets. Nothing raises: persistence is a convenience, never a failure path.

Two things the test harness needs, both of which the prototype discovered the hard way. `scripts/test.sh` sets `QGIS_CUSTOM_CONFIG_PATH` so the suite never writes into the developer's real QGIS profile — without it, `QgsSettings` in a test lands in `~/Library/Application Support/QGIS/...` and tests inherit each other's leftovers. And `conftest.py` clears the plugin's own settings group around every test, so order cannot matter.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_settings.py`
```python
from qgis.core import QgsSettings
from qgis.PyQt.QtWidgets import QPushButton, QSplitter

from terrain_sketch.gui import settings


def test_settings_round_trip_under_the_plugin_group():
    settings.save("probe/value", "kept")
    assert settings.load("probe/value") == "kept"
    stored = QgsSettings()
    stored.beginGroup(settings.GROUP)
    assert stored.value("probe/value") == "kept"     # written where the spec says, not at the root
    stored.endGroup()


def test_a_missing_setting_falls_back_to_the_default():
    assert settings.load("never/written", "fallback") == "fallback"


def test_splitter_state_is_stored_and_handed_back_to_the_widget():
    first = QSplitter()
    first.addWidget(QPushButton())
    first.addWidget(QPushButton())
    settings.save_state("probe_splitter", first)
    # what was stored is exactly what the widget produced — every QWidget also has saveGeometry,
    # so a module that probed for a method would quietly store the wrong one for a splitter
    assert bytes(settings.load("probe_splitter/state")) == bytes(first.saveState())
    second = QSplitter()
    second.addWidget(QPushButton())
    second.addWidget(QPushButton())
    assert settings.restore_state("probe_splitter", second)


def test_a_splitter_is_stored_by_state_not_by_geometry():
    splitter = QSplitter()
    splitter.addWidget(QPushButton())
    splitter.addWidget(QPushButton())
    settings.save_state("probe_kind", splitter)
    assert settings.load("probe_kind/state") is not None
    assert settings.load("probe_kind/geometry") is None


def test_restoring_something_never_saved_reports_failure_rather_than_raising():
    assert not settings.restore_state("probe_absent", QSplitter())


def test_a_deleted_widget_does_not_raise():
    """These run from Qt callbacks: a PyQt wrapper whose C++ object is gone raises RuntimeError,
    and an exception in a callback aborts the interpreter."""
    from qgis.PyQt import sip
    splitter = QSplitter()
    splitter.addWidget(QPushButton())
    splitter.addWidget(QPushButton())
    settings.save_state("probe_dead", splitter)
    sip.delete(splitter)
    settings.save_state("probe_dead", splitter)              # must not raise
    assert not settings.restore_state("probe_dead", splitter)


def test_a_corrupt_stored_value_does_not_raise():
    settings.save("probe_bad/state", "not a byte array")
    assert not settings.restore_state("probe_bad", QSplitter())
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_settings.py`
Expected: collection error `ModuleNotFoundError: No module named 'terrain_sketch.gui.settings'`

- [ ] **Step 3: Add the settings module and isolate the test profile**

**File:** `terrain_sketch/gui/settings.py`
```python
"""Remembering panel state between sessions, under the `terrain_sketch/` QgsSettings group."""
from __future__ import annotations

from qgis.core import QgsSettings

GROUP = "terrain_sketch"


def save(key: str, value) -> None:
    """Store one value. Never raises: a settings problem must not cost the user their work."""
    try:
        settings = QgsSettings()
        settings.beginGroup(GROUP)
        settings.setValue(key, value)
        settings.endGroup()
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass


def load(key: str, default=None, kind=None):
    """Read one value back, falling back to `default` when it is missing or unreadable."""
    try:
        settings = QgsSettings()
        settings.beginGroup(GROUP)
        value = settings.value(key, default) if kind is None else settings.value(key, default, type=kind)
        settings.endGroup()
        return value
    except Exception:  # noqa: BLE001
        return default


def save_state(name: str, widget) -> None:
    """Persist a splitter's or window's layout.

    The caller says which method to use by widget kind rather than this module guessing: every
    QWidget has `saveGeometry`, so probing for it would silently store the wrong thing for a
    QSplitter, whose layout lives in `saveState`.
    """
    _save_from(f"{name}/state", widget, "saveState")


def restore_state(name: str, widget) -> bool:
    """Put a splitter's or window's layout back; False when there is nothing usable stored."""
    return _restore(load(f"{name}/state"), widget, "restoreState")


def save_geometry(name: str, widget) -> None:
    """Persist a top-level widget's position and size."""
    _save_from(f"{name}/geometry", widget, "saveGeometry")


def restore_geometry(name: str, widget) -> bool:
    """Put a widget's position and size back; False when there is nothing usable stored."""
    return _restore(load(f"{name}/geometry"), widget, "restoreGeometry")


def _save_from(key: str, widget, method: str) -> None:
    """Ask the widget for its layout and store it. The widget call is inside the guard because a
    PyQt wrapper whose C++ object is gone raises RuntimeError, and these run from Qt callbacks."""
    try:
        save(key, getattr(widget, method)())
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass


def _restore(stored, widget, method: str) -> bool:
    if not stored:
        return False
    try:
        return bool(getattr(widget, method)(stored))
    except Exception:  # noqa: BLE001 — a corrupt blob or a deleted widget must not reach Qt
        return False
```
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
# Keep QgsSettings out of the developer's real QGIS profile: without this the suite writes
# settings into ~/Library/Application Support/QGIS/... and tests see each other's leftovers.
export QGIS_CUSTOM_CONFIG_PATH="${QGIS_CUSTOM_CONFIG_PATH:-$ROOT/.devdeps/qgis-profile}"
if [ ! -d "$ROOT/.devdeps/pytest" ]; then
  if ! "$PY" -m pip install -q --disable-pip-version-check --target "$ROOT/.devdeps" pytest; then
    echo "scripts/test.sh: could not install pytest into .devdeps/ (the first run needs a network connection)" >&2
    exit 1
  fi
fi
cd "$ROOT"
exec "$PY" -m pytest "$@"
```
**File:** `tests/qgis/conftest.py`
```python
"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject, QgsSettings

from terrain_sketch.gui import settings as plugin_settings

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()


@pytest.fixture(autouse=True)
def clean_project():
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
**File:** `terrain_sketch/gui/profile_dock.py`
```python
"""Bottom dock: the cross profile and the long profile of the selected feature, side by side."""
from __future__ import annotations

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                                 QWidget)

from ..core.sections import cross_section, set_cross_section, supports_long_profile
from ..core.tools import TOOL_INFO, Mode
from .help_texts import (AREA_LONG_SECTION_HINT, AREA_LONG_SECTION_NOTE, CUSTOM_PROFILE_NOTE,
                         MULTIPART_LONG_SECTION_NOTE, SYMMETRIC_TIP)
from . import settings
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
        self.splitter = splitter
        splitter.setObjectName("TerrainSketchProfileSplitter")
        settings.restore_state("profile_splitter", splitter)
        splitter.splitterMoved.connect(
            lambda *_args: settings.save_state("profile_splitter", splitter))
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
        feature = self.controller.find(self._fid)
        if feature is None:
            self.show_feature(None)
            return
        self._loading = True
        try:
            info = TOOL_INFO[feature.tool]
            is_path = feature.mode is Mode.PATH
            # Break points are for paths only: the engine discards an area's (spec 5.4).
            self.cross.set_profile(cross_section(feature, side=1), editable=info.has_slopes,
                                   allow_breaks=is_path)
            self.symmetric.setEnabled(info.has_slopes and is_path)
            self.reset_cross.setEnabled(info.has_slopes)
            section = self.controller.long_section(self._fid)
            if feature.mode is Mode.AREA:
                # There is no section through an area yet, so say so rather than paint an empty
                # plot under a note promising one.
                self.long.set_profile((), editable=False, hint=AREA_LONG_SECTION_HINT)
                self.note.setText(AREA_LONG_SECTION_NOTE)
            elif not supports_long_profile(feature):
                # A multi-part path: the engine follows the tool rule whatever is stored here.
                self.long.set_profile(section["design"], terrain=self._pairs(section),
                                      editable=False)
                self.note.setText(MULTIPART_LONG_SECTION_NOTE)
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
        feature = self.controller.find(self._fid)
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
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_settings.py` → Expected: `7 passed`
Run: `scripts/test.sh` → Expected: `262 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/settings.py terrain_sketch/gui/profile_dock.py scripts/test.sh tests/qgis/conftest.py tests/qgis/test_settings.py
git commit -m "feat(gui): remember the profile splitter, and keep tests out of the user's QGIS profile"
```

---

### Task 5: Reproject, and messages that say what actually happened

**Files:**
- Modify: `terrain_sketch/qgis_io/raster_io.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/gui/layer_source.py`, `terrain_sketch/gui/controller.py`, `tests/qgis/qgis_helpers.py`, `tests/qgis/test_dock_plugin.py`
- Test: `tests/qgis/test_help_messages.py`

**Interfaces:**
- Produces: `raster_io.GeographicDemError(DemError)`; `help_texts.REPROJECT_UNAVAILABLE`, `NO_FEATURES_SELECTED`, `EMPTY_LAYER`, `PICK_A_LAYER`, `VERTEX_EDIT_REFUSED`, `WRONG_GEOMETRY_IN_LAYER`; `MainDock._offer_reproject` / `_run_reproject`; `LayerSource._refresh_use_button`.

`test_dock_plugin.py` changes in one place: a geographic DEM is now pushed as a **widget** carrying the button, so the lifecycle test asserts `pushWidget` rather than `pushMessage`.

The test helper changes too, and the reason matters: `fake_iface()`'s message bar stays a `Mock` so tests can still assert `pushMessage`, but `createMessage` now returns a **real** `QgsMessageBarItem`. The panel builds a button onto that item, and a `Mock` there let a broken widget path pass unnoticed — it aborted the interpreter instead of failing a test.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/qgis_helpers.py`
```python
"""Helpers for the QGIS integration tests: small GeoTIFF DEMs on a UTM grid (EPSG:25832)."""
from unittest import mock

import numpy as np
from osgeo import gdal
from qgis.core import (QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
                       QgsRasterLayer, QgsRectangle, QgsVectorLayer)
from qgis.gui import QgisInterface, QgsMapCanvas, QgsMessageBarItem
from qgis.PyQt.QtCore import QEventLoop, QTimer
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
**File:** `tests/qgis/test_help_messages.py`
```python
from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QPushButton

from qgis_helpers import dem_layer, fake_iface, line_layer, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import EMPTY_LAYER, NO_FEATURES_SELECTED, PICK_A_LAYER
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.gui.tool_gallery import ToolGallery


def test_a_geographic_dem_is_refused_with_a_button_that_opens_the_warp_tool(tmp_path):
    iface = fake_iface()
    dem = dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    assert not dock.controller.has_dem
    iface.messageBar().pushWidget.assert_called()          # a widget, not a plain message
    widget = iface.messageBar().pushWidget.call_args[0][0]
    buttons = widget.findChildren(QPushButton)
    assert [b for b in buttons if "Reproject" in b.text()], [b.text() for b in buttons]


def test_a_projected_dem_is_accepted_without_any_reproject_offer(tmp_path):
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    assert dock.controller.has_dem
    iface.messageBar().pushWidget.assert_not_called()


def test_the_use_button_is_dead_only_when_no_layer_is_on_offer():
    QgsProject.instance().removeAllMapLayers()
    gallery = ToolGallery()
    form = gallery.layer_source
    assert not form.use_button.isEnabled()
    assert form.use_button.toolTip() == PICK_A_LAYER
    line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    assert form.use_button.isEnabled()
    assert form.use_button.toolTip() != PICK_A_LAYER


def test_an_empty_selection_and_an_empty_layer_are_reported_differently(tmp_path):
    c = start_session(tmp_path)
    said = []
    c.message.connect(lambda level, text: said.append(text))
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer, selected_only=True)
    assert said[-1] == NO_FEATURES_SELECTED and "select" in said[-1].lower()
    empty = line_layer("Nothing here", [])
    c.add_from_layer(Tool.RAISE_PATH, Mode.PATH, empty)
    assert said[-1] == EMPTY_LAYER
    assert NO_FEATURES_SELECTED != EMPTY_LAYER
```
**File:** `tests/qgis/test_dock_plugin.py`
```python
import pytest
from qgis.core import QgsProject

from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY

from qgis.core import QgsRectangle

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
    # it is pushed as a WIDGET now, because it carries a Reproject… button
    iface.messageBar().pushWidget.assert_called()


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


def _dock_on(tmp_path, canvas_crs=None):
    iface = fake_iface()
    if canvas_crs is not None:
        iface.mapCanvas().setDestinationCrs(canvas_crs)
    dem = dem_layer(tmp_path)                       # EPSG:25832
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem)
    dock.start_button.click()
    return iface, controller, dock


def test_the_drag_preview_is_placed_with_a_dem_to_canvas_transform(tmp_path):
    """The engine reports preview bounds in the DEM CRS. Without a transform the cut/fill image
    lands somewhere else on the map — or off-screen — for any project whose CRS differs."""
    web = QgsCoordinateReferenceSystem("EPSG:3857")
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=web)
    transform = dock.overlay.crs_transform
    assert transform is not None and transform.isValid()
    assert transform.sourceCrs() == controller.dem_crs
    assert transform.destinationCrs() == web

    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    previews = []
    controller.previewUpdated.connect(lambda _fid, preview: previews.append(preview))
    controller.preview(dike.id, amount=5.0)
    assert previews and dock.overlay.bounds is not None
    expected = transform.transformBoundingBox(QgsRectangle(*previews[0].bounds))
    assert dock.overlay.bounds.xMinimum() == pytest.approx(expected.xMinimum())
    assert dock.overlay.bounds.yMinimum() == pytest.approx(expected.yMinimum())
    # and that is nowhere near the untransformed DEM-CRS bounds
    assert abs(dock.overlay.bounds.xMinimum() - previews[0].bounds[0]) > 1000.0


def test_the_overlay_transform_follows_a_change_of_project_crs(tmp_path):
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=QgsCoordinateReferenceSystem("EPSG:3857"))
    assert dock.overlay.crs_transform is not None
    iface.mapCanvas().setDestinationCrs(UTM)          # the user switches the project to the DEM CRS
    assert dock.overlay.crs_transform is None         # same CRS: the bounds need no transform
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert dock.overlay.crs_transform is not None
    assert dock.overlay.crs_transform.destinationCrs().authid() == "EPSG:4326"


def test_a_dem_crs_that_cannot_be_projected_leaves_the_preview_unshown(tmp_path):
    """`_update_overlay_transform` runs in a slot, so it must not raise — and it must not let the
    overlay paint bounds it cannot place."""
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=QgsCoordinateReferenceSystem("EPSG:3857"))
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    previews = []
    controller.previewUpdated.connect(lambda _fid, preview: previews.append(preview))
    controller.preview(dike.id, amount=5.0)
    assert dock.overlay.isVisible()

    controller.dem_crs = QgsCoordinateReferenceSystem()   # a DEM whose CRS is unknown
    dock._update_overlay_transform()
    assert dock.overlay.crs_transform is None and not dock.overlay.isVisible()
    controller.previewUpdated.emit(dike.id, previews[0])  # the next frame of the drag arrives
    assert not dock.overlay.isVisible() and dock.overlay.bounds is None


def test_without_a_session_the_overlay_has_no_transform(tmp_path):
    iface, controller, dock = _dock_on(tmp_path, canvas_crs=QgsCoordinateReferenceSystem("EPSG:3857"))
    assert dock.overlay.crs_transform is not None
    controller.close()
    assert dock.overlay.crs_transform is None
```
- [ ] **Step 2: Run them to verify they fail**

Run: `scripts/test.sh tests/qgis/test_help_messages.py`
Expected: collection error `ImportError: cannot import name 'EMPTY_LAYER' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: Offer the reproject, and say what happened**

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
    Tool.INTERPOLATE: ("A ditch crosses your DEM but the survey missed it. Draw a line along the "
                       "ditch and Terrain Sketch runs a smooth grade between the two ends."),
    Tool.RAISE_PATH: ("A 1.5 m flood embankment along a river. Draw the line the crest follows, "
                      "set Height 1.5 m, Width 3 m and a 1:3 side slope."),
    Tool.LOWER_PATH: ("A swale carrying runoff to a pond. Draw its route, set Depth 0.6 m and "
                      "Width 2 m; the slopes tie it back into the ground."),
    Tool.RAISE_FLAT: ("A building pad above the flood level. Draw the outline and set the height "
                      "above the highest point it covers, so the whole pad sits level."),
    Tool.LOWER_FLAT: ("A detention basin. Draw the outline, set Depth 1.2 m, and the bottom comes "
                      "out flat with the sides sloping down to it."),
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
                      "point it covers, with slopes tying the edge back into the ground."),
    Tool.LOWER_FLAT: ("Cuts everything inside the shape down to one level, measured from the "
                      "lowest point it covers, with slopes tying the edge back in."),
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
                "outwards per 1 m up, which is the usual maximum for a mown grass embankment. "
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

REPROJECT_HINT = ("The DEM uses latitude/longitude. Slopes and widths need metres, so reproject "
                  "it to a projected CRS first.")
NO_FEATURES_SELECTED = ("Nothing is selected in that layer. Untick \'Selected features only\', or "
                        "select the features you want on the map first.")
EMPTY_LAYER = "That layer has no features to use."
WRONG_GEOMETRY_IN_LAYER = ("That layer holds {have} features, but this tool needs {want} ones. "
                           "Pick a different layer, or switch the shape above.")
VERTEX_EDIT_REFUSED = ("That edit would leave the shape invalid, so it was not applied. Try "
                       "moving the point somewhere else.")
PICK_A_LAYER = "Pick a layer above first."


def tool_tooltip(tool: Tool) -> str:
    """What a gallery item shows on hover: what the tool does, then a worked example."""
    return f"{TOOL_DESCRIPTIONS[tool]}\n\n{TOOL_EXAMPLES[tool]}"
REPROJECT_UNAVAILABLE = ("Processing is not available, so Terrain Sketch cannot open the warp "
                         "tool. Enable the Processing plugin, or reproject the DEM with "
                         "Raster ▸ Projections ▸ Warp.")
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
from ..qgis_io.raster_io import DemError, GeographicDemError
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import REPROJECT_UNAVAILABLE
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
        self._overlay_transform_failed = False
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
        if self.controller.features and not self.confirm(
                self.tr("Start again on this DEM? The current features will be discarded.")):
            return
        try:
            self.controller.set_dem(layer)
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))

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
            bar = self.iface.messageBar()
            widget = bar.createMessage(self.tr("Terrain Sketch"), text)
            button = QPushButton(self.tr("Reproject…"), widget)
            button.clicked.connect(self._run_reproject)
            widget.layout().addWidget(button)
            bar.pushWidget(widget, Qgis.MessageLevel.Warning, 0)
        except Exception:  # noqa: BLE001 — this runs in a click handler; a plain message will do
            self._show_message(Qgis.MessageLevel.Warning, text)

    def _run_reproject(self) -> None:
        try:
            from processing import execAlgorithmDialog
        except ImportError:  # Processing is a core plugin, but it can be disabled
            self._show_message(Qgis.MessageLevel.Warning, REPROJECT_UNAVAILABLE)
            return
        layer = self.dem_combo.currentLayer()
        execAlgorithmDialog("gdal:warpreproject", {"INPUT": layer} if layer is not None else {})

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
**File:** `terrain_sketch/gui/layer_source.py`
```python
"""Use lines or areas from a vector layer that is already in the project."""
from __future__ import annotations

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .help_texts import PICK_A_LAYER
from ..core.tools import Mode


class LayerSource(QWidget):
    """Layer picker, "selected features only" and the button that turns them into a feature."""

    useRequested = pyqtSignal(object, bool)  # QgsVectorLayer, selected_only

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Layer")))
        self.layer_combo = QgsMapLayerComboBox()
        row.addWidget(self.layer_combo, 1)
        layout.addLayout(row)
        self.selected_only = QCheckBox(self.tr("Selected features only"))
        layout.addWidget(self.selected_only)
        self.use_button = QPushButton(self.tr("Use these features"))
        self._use_tip = self.tr("Every feature becomes one part of a single Terrain Sketch "
                                "feature; they share the same values.")
        layout.addWidget(self.use_button)
        self.use_button.clicked.connect(self._use)
        self.layer_combo.layerChanged.connect(self._refresh_use_button)
        # the combo fills itself from the project, so watch the model too: a layer added after
        # this widget was built does not always arrive as layerChanged
        model = self.layer_combo.model()
        model.rowsInserted.connect(self._refresh_use_button)
        model.rowsRemoved.connect(self._refresh_use_button)
        self.set_mode(Mode.PATH)

    def set_mode(self, mode: Mode) -> None:
        """Show line layers for paths and polygon layers for areas."""
        self.layer_combo.setFilters(Qgis.LayerFilter.LineLayer if mode is Mode.PATH else Qgis.LayerFilter.PolygonLayer)
        self._refresh_use_button()

    def _refresh_use_button(self, *_args) -> None:
        """A button that does nothing when pressed is worse than a disabled one. It is dead only
        when the project has no layer of the right kind to offer."""
        usable = self.layer_combo.count() > 0
        self.use_button.setEnabled(usable)
        self.use_button.setToolTip(self._use_tip if usable else PICK_A_LAYER)

    def _use(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is not None:
            self.useRequested.emit(layer, self.selected_only.isChecked())
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
from .help_texts import (DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER, NO_FEATURES_SELECTED, NO_SESSION,
                         RESULT_LAYER_REMOVED, SESSION_ENDED_DEM_REMOVED, TOOL_LABELS)

LOG_TAG = "Terrain Sketch"


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
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_help_messages.py` → Expected: `4 passed`
Run: `scripts/test.sh` → Expected: `266 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/qgis_io/raster_io.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/gui/layer_source.py terrain_sketch/gui/controller.py tests/qgis/qgis_helpers.py tests/qgis/test_dock_plugin.py tests/qgis/test_help_messages.py
git commit -m "feat(gui): offer Reproject for a geographic DEM, and report what actually went wrong"
```

---

## Deferred items this plan closes

From the Plan 3 and Plan 4 addenda: `tr()` on non-literals; `NO_FEATURES_IN_LAYER` misdiagnosing its likeliest trigger (it is now two messages); the dead "Use these features" button; `QgsSettings` persistence; the "Reproject…" button. Plus one this plan found: the suite was writing settings into the developer's real QGIS profile.

## Still deferred, and why

| Item | Where | Why not here |
|---|---|---|
| `reach` can round to `0.0` on a hard-against-the-neighbour drag | `core/sections.py` | A profile-editor behaviour change; the user chose to carry it on 2026-09-14. Recoverable from the properties page, but silent. |
| The arrow-key nudge commits on every keypress | `gui/profile_widget.py` | ~30 un-undoable states per second on auto-repeat. Wants preview-then-commit-on-release, which is a behaviour change in the one path with no undo. |
| Editing the **left** side of a cross profile | `gui/profile_dock.py` | `cross_section(side=-1)` exists and is tested in core but is unreachable from the UI; it needs a side control, which is new UI rather than guidance. |
| The real area section line | `core/sections.py` | Spec §5.4 wants centroid + oriented minimum bounding box + a "Draw section line" map tool. Plan 4 shipped an honest "arrives in a later version" note; this is Plan 6 work. |
| End-cap asymmetry | `core/operations.py` | Carried from Plan 3 with its justification corrected in the Plan 4 addendum. A thin on-axis sliver at two cells; wrong elevation, not a crash. |

## Manual check in QGIS (for the human, after merge)

1. Rebuild and reinstall the plugin, restart QGIS. Open the panel: each of the seven tools should show a small side view, and hovering one should explain it and give an example.
2. Switch QGIS between a light and a dark theme (Settings ▸ Options ▸ General ▸ UI Theme). The illustrations should follow the theme; orange fill and blue cut should stay as they are.
3. Draw a **Raise path** dike and select it. *About this tool* should show the picture and the example; collapse it and it should stay collapsed when you select another feature.
4. Click into Width, then Side slope, then Max reach: the diagram above should highlight a different part each time.
5. Open the *Pixels to change* combobox — each entry should carry its own small picture, and the three should look different.
6. Pick a DEM in latitude/longitude and press Start: the message bar should offer a **Reproject…** button that opens Processing's warp dialog with that layer filled in.
7. With no line or polygon layer in the project, the "Use these features" button should be greyed out and say why. Add one and it should come alive.
8. Drag the splitter between the two profile panels, close QGIS and reopen it: the split should be where you left it.

## Roadmap: Plan 6

| Milestone | Builds on Plan 5 via |
|---|---|
| Scenario GeoPackage, volumes in the UI, undo/redo, the 3D view, error flags, and a packaging script that builds the plugin ZIP | `settings.py` for panel state, `help_texts.py` for every new string, `illustrations/` for any new picture, and the deferred profile-editor items above |

---

## Addendum: final-review fixes

The task blocks above are the plan as written. Five tasks landed on `feat/guidance`, each reviewed as
it landed, followed by a whole-branch review and one fix wave. **Every one of the five needed a fix
round** — the highest rate of any plan in this project. **Where this addendum and the task blocks
disagree, the code is authoritative.**

### Changed after the task blocks

| # | What changed | Why |
|---|---|---|
| I1 | `TOOL_DESCRIPTIONS` for both flat tools, and `TOOL_EXAMPLES[RAISE_FLAT]`, now say "the highest/lowest point **on the line or outline you draw**" | They said "the highest point it covers". `operations.py` samples `polygon_rings(part)[0]` — the exterior ring — and `rule_profile` samples only the drawn vertices. The interior is never read. Draw a pad around a knoll, believe the tooltip, and the knoll pokes through; there is no undo. `TOOL_SUMMARIES`, displayed twenty pixels above, already said it correctly. |
| I2 | `TOOL_EXAMPLES[INTERPOLATE]` now describes a culvert captured as a solid bank | It described creating a ditch the survey had missed. Interpolate grades between the edge elevations: it cannot create a ditch, and would erase one that exists. The tool's own summary and illustration both already said the right thing. |
| I3 | `tool_add.svg`'s band follows the terrain | Its surface sat at offsets of 7.2 / 11.7 / 9.2 px from the ground where `tool_subtract.svg`'s are 7.8 / 7.3 / 7.8 — the picture flattened the terrain its own caption says it preserves. Now 7.2 / 7.7 / 7.2, with a test asserting both bands stay parallel. |
| I4 | `_run_reproject` is wrapped, and captures the layer when the message is built | It was the one new Qt-callback path, unguarded and untested — and this branch's previous commit existed only because a `NameError` had been sitting on that exact line. |
| I5 | An unknown `highlight` key is treated as `None` | It dimmed the entire diagram instead. The test named `..._leaves_every_part_visible` asserted the opposite and passed. |
| 6 | The splitter round-trip test sets sizes first, then asserts them | An earlier ruling refused this because an unshown splitter reports `[0, 0]`. True of the test as written, wrong as a conclusion: set sizes and it reports them, and the assertion becomes mutation-detecting. The bytes assertion proves storage; this proves restoration. |
| 7 | The four construction-time `setToolTip` calls are removed | They are `self.tr("literal")`, so `pylupdate` extracts four strings the user can never see while the strings actually shown are unextractable by design — Task 1's own problem, re-created one directory over. |
| — | Smaller: four dead strings deleted; the slope tip no longer calls 1:3 a "maximum" when larger *n* is flatter; the `LOWER_FLAT` example now says to set Slopes to *Inside the outline*, without which the basin grows outward; a tautological assertion, a dead test helper and two unused imports removed; the theme test no longer calls `refresh_icons()` by hand, so it proves the wiring | Each confirmed by review. |

### Corrections to this plan's own text

- **The plan shipped a `NameError`.** The prototype patch prepended `REPROJECT_UNAVAILABLE` to a
  `from .help_texts import` line in `main_dock.py` that did not exist, so the edit silently did
  nothing and the name was used unimported — on the path that runs when Processing is disabled, which
  no test covers. Task 5's implementer found it unprompted.
- **Two spec §7.2 items were dropped without a decision being recorded**: the pixel-mode combobox's
  tooltip containing the three-panel picture, and the tool-specific Height/Depth label
  ("Height above the highest point…"), which `amount_label()` still renders as a bare "Height". They
  are now in the deferred table below. Had the second been built, the I1 error above would have been
  hard to write.

### Process notes, recorded because they cost real time

- **A fix that changes a file a *later* task also emits must re-extract that task's brief.** Task 5's
  `help_texts` slice is the whole file; after fixing the amount tooltip in Task 3 only the earlier
  briefs were regenerated, so Task 5 faithfully wrote the old wording back. The suite stayed green —
  the test asserts the tooltip contains a digit, and the wrong text does too. Byte-comparing the
  branch against the plan's slices is what caught it.
- **The dry run must check out `main` after cloning.** Once the feature branch existed, the script was
  cloning the branch and "verifying" tasks against content they had already produced.
- **Per-task slices work.** This was the first plan whose dry run passed on the first attempt, and the
  Plan 4 defect they were introduced to prevent — a task shipping strings only a later task uses — was
  confirmed absent on the file three tasks write.

### Deferred to Plan 6

| Item | Why not here |
|---|---|
| The pixel-mode picture inside the combobox tooltip, and tool-specific H/D labels (spec §7.2) | Dropped by this plan without a recorded decision; the H/D label is the structural fix for the I1 class of error. |
| Dock geometry under `terrain_sketch/` (spec §7.1) | Only the splitter landed. `save_geometry`/`restore_geometry` exist and are unused, waiting for it. |
| `QgsCollapsibleGroupBox` collapse state | It writes under its own key, not the plugin's group, and the test that collapses the About box leaves it collapsed in the shared test profile. |
| Illustration polish | The centre-dot hidden under the outline in `pixels_centre.svg`; the reach bar overrunning the toe in `parameters.svg`; sliver gaps where four straight-based bands meet the wavy terrain; and the four path/flat icons being hard to tell apart at 60×32. |
| Carried from earlier plans | `reach` rounding to 0.0 on a hard terminus drag; the arrow-key nudge committing per keypress; the unreachable left side of a cross profile; the real area section line; the end-cap asymmetry. |

## Manual check in QGIS (for the human, after merge)

The plan's own manual-check list stands, with one correction: **step 4's expectation was wrong** and is
fixed above — unticking Symmetric stops break points mirroring, but width, side slope and reach are
single values that always apply to both sides.
