# Terrain Sketch — Plan 8: Profile Editor, Area Sections, Guidance and Scenario Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the rest of the v1 spec and the deferred backlog. The cross profile shows both sides of a path and the left one can be edited; an area gets its read-only section with a line the user can redraw; the arrow-key nudge and the Properties page stop losing or multiplying changes; the guidance says what a height is measured from and shows the pixel modes; the panels remember their place; and a saved scenario keeps its working rasters beside it and can open on the DEM it was made on.

**Architecture:** No new layers of the architecture. `core/sections.py` gains the whole cross-section (`whole_cross_section`, `set_whole_cross_section`) and the area section (`default_section_line`, `section_along`), `core/engine.py` gains `terrain_around`, and `TerrainFeature` gains `section_line`, stored as WKT in the scenario. The GUI keeps talking to the engine only through `SketchController` (`area_section`, `section_line`, `set_section_line`, `scenario_dem_source`), and panel state goes through `gui/settings.py`.

**Tech Stack:** QGIS 4.2.2 Python API (PyQt6 via `qgis.PyQt`, Qt 6.11), GDAL/OGR 3.13, numpy, scipy (`ConvexHull`); pytest (dev-only) with a headless `QgsApplication`.

**Spec:** `docs/superpowers/specs/2026-09-11-terrain-sketch-design.md` — §5.4 (cross profile with both sides; the area's read-only section and "Draw section line"), §6.3 and §7.2 (the pixel-mode picture; tool-specific H/D labels), §7.1 (panel and group state under `terrain_sketch/`), §7.3 (arrow keys), §8.2 step 3 (working GeoTIFFs in `<scenario>_files/`), §8.4 (`section_line`, loading on a different DEM), §9. Plans 1-7 are merged on `main`; **read the Plan 7 addendum first**: its two "Deferred to Plan 8" tables are this plan's backlog, and where it and the code disagree with an older plan, the code is authoritative.

## Global Constraints

- Target QGIS 4.x (Qt6) only. Import Qt through `qgis.PyQt` and always use fully scoped Qt6 enums.
- Native look (spec §7.1): only standard Qt/QGIS widgets and palette colours, QGIS theme icons via `QgsApplication.getThemeIcon`, **no stylesheets**. The UI inherits the active QGIS theme, light or dark. Illustrations are SVG templates with colour tokens.
- `terrain_sketch/core/` and `terrain_sketch/model/` never import `qgis` or `PyQt`; `qgis_io/` never imports `gui/`. Widgets never call the engine, files or layers directly — only `SketchController`.
- Errors never take QGIS down: user problems become message-bar messages; unexpected errors are caught and logged to the "Terrain Sketch" tab. **An exception raised inside a Qt callback aborts the interpreter** — slots, signal handlers, button clicks, menu actions, event filters, key and mouse handlers and map-tool callbacks included. Use `SketchController.find()`, never `feature()`, from anything reachable from Qt.
- Every feature-list change is one undo step through `SketchController._commit`; the saved state is `undo_stack.isClean()`. A save that fails must leave the previous file readable.
- Every user-facing string lives in `gui/help_texts.py`; widget captions use `self.tr("literal")`. Never call `tr()` on a non-literal. English only.
- Package modules start with a one-line docstring and use `from __future__ import annotations` where they have type hints; test modules need neither. 4-space indentation. Imports sorted within their group. Lines of new code stay within 120 characters.
- Tests run only through `scripts/test.sh`. Never run `scripts/dev_install.sh`. In a test hook reached from a Qt signal or a button click, **record the call and assert afterwards — never `pytest.fail()` inside it**. A real modal dialog hangs the offscreen suite: `tests/qgis/conftest.py` answers them, and a test about a question replaces the panel's hook (`confirm`, `confirm_save`, `choose_dem`, …).
- GDAL runs with exceptions enabled throughout the plugin. Close GDAL datasources explicitly.

## Decisions made while prototyping (read before implementing)

Every claim below about QGIS or Qt behaviour was probed headless against QGIS 4.2.2. The three product decisions marked **(user)** were put to the user before the prototype was built.

- **Scope.** Everything in the Plan 7 addendum's two Plan 8 tables, except the items listed at the end of this plan with a reason. The spec's v1 items still missing — the area section and its "Draw section line", the pixel-mode picture, tool-specific labels, panel state and `<scenario>_files/` — are all here.
- **The cross profile shows the whole cross-section (user).** A path's plot runs from the end of the left slope to the end of the right one, centre line at 0, left at negative offsets as seen looking along the drawing direction; "Left" and "Right" are written in the plot. No handle crosses the centre, the two crest edges always move together (width is one value), and while Symmetric is ticked every handle with a mirror image takes it along. `set_whole_cross_section` reads each side as `set_cross_section` always has, except that a side whose points are still the ones the plot was given keeps what the feature has; width, slope and reach are single values, so each comes from the side where it changed (right when both did), and with Symmetric the side whose break points changed is copied. A side whose breaks run past the reach has no slope-end handle (`cross_section` draws none), so its last point is read as a break and its slope and reach are kept — the Task 3 review found that reading it as the slope's end let an edit on the other side rewrite the slope and drop the berm (probed). Crest edges only move sideways. An area keeps its one-sided edge profile: it has no sides and no break points.
- **The end-cap sliver is fixed in the engine.** A cell exactly on the extended axis past an end cap belonged to neither side and always took the right-hand shape — a one-cell notch into a left-hand berm (probed). `stations_offsets` now gives such a cell offset 0, and `_path_values` gives it whichever side the combine rule keeps (max for raise tools, min for lower), among the sides whose reach covers it. Only cells at an end are affected; a bend is not. The end test allows 1e-9 m, because a cell's station and the path's length are summed differently and can differ in the last bit (probed).
- **An arrow key commits once, when it is let go.** Each press and auto-repeat moves the handle and previews; the key's release — not an auto-repeated one — commits, as does losing focus while it is held. A reload of the plot under a held key drops the pending commit. Holding Up for a second is now one recompute, one file write and one undo step instead of about thirty.
- **A reach that rounds to 0 keeps the reach it had**, like the slope already did, so a terminus dragged hard against the edge no longer silently cancels the slope.
- **The Properties page follows every change, except in a field the user is typing in.** It reloads its values on `featuresChanged` (so a cross-profile drag's width, slope and reach show up, and the next arrow step no longer writes the old width back); a spin box whose line edit `isModified()` keeps its typed text. That same rule fixes the Undo button throwing away a typed value: the undo happens, and the typed value is still there to confirm with Enter. `MainDock._history_restored` no longer reloads the page itself.
- **The area section (spec §5.4).** Its default line runs through the centroid along the longer side of the minimum-area rotated rectangle around the outline's convex hull (rotating calipers over the hull edges, in numpy/scipy), west to east, and on past the outline by the reach of outside slopes plus max(5 cells, 10 % of its length) so the ground around shows. `FeatureStack.terrain_around(fid, window)` replays the stack to just before the feature over its footprint grown to the line, and applies the feature once more for "after"; `section_along` samples both with the grid's bilinear sampling and leaves out stations off the grid. The right-hand panel shows it read-only: dashed before, solid after.
- **The section line is part of the feature**: `TerrainFeature.section_line` (WKB in the DEM CRS, `None` for the default), written to the scenario's documented `section_line` field as WKT. It does not change the terrain (`_same_result` ignores it, so no recompute), but it is one undo step ("Move the section line of …") and it marks the scenario unsaved. "Draw section line" in the Profiles panel puts a line tool on the map through `MainDock`; "Reset line" goes back to the default. The selected area's line is drawn on the map as a dashed rubber band.
- **Pictures that tell the tools apart.** The four raise and lower tool pictures shared one trapezoid. All seven are now a long section along the drawn path over one shared ground with a dip and a bump: a path tool's surface runs from end to end with the ground (and the bump pokes through a raised path), a flat tool's is level, Interpolate fills the dip and cuts the bump, Add and Subtract keep the relief. Every band closes along the drawn ground, which removes the sliver gaps. The pixel pictures use an outline at least 3 units from every cell centre and draw the centres on top. The generator scripts stay out of the repository; the SVGs are the source of truth, and tests check their geometry.
- **The parameter diagram's reach bar stays as drawn.** It runs from the crest edge past the toe, which is what "max reach" means — the slope met the ground before its cap. The Plan 5 note read it as an overrun.
- **The amount field names its reference**: "Height above the path", "Height above the highest point", "Depth below the lowest edge", "Height added"… The label word-wraps, so the longest one does not widen the panel (measured: 330 px either way). The pixel field's tooltip shows the three modes side by side as PNG `data:` images; Qt's rich text renders them (probed).
- **Panel state lives under `terrain_sketch/` (spec §7.1).** QGIS restores its window layout long before a plugin creates its panels, so the plugin stores each panel's dock area, whether it floats, its docked width or height, and its floating geometry — on `dockLocationChanged`, `topLevelChanged` and unload — and restores them when it creates the panel. `QgsCollapsibleGroupBox` saves under its own `QgsCollapsibleGroupBox/…` key, which the plugin can neither find nor clear, so its own saving is turned off and `settings.remember_collapsed` keeps the state instead (a box that is not shown does not report a collapse, probed).
- **Working rasters beside the scenario (user; spec §8.2 step 3).** Whenever the session has a scenario file — after Save, Save as or Open — the working and change GeoTIFFs live in `<scenario>_files/`, so a QGIS project saved with those layers finds them later; without one (New) they live in a temp folder. They move whenever that changes, so edits to another scenario never write over a scenario's own rasters. Moving copies the files, repoints the three layers with `setDataSource` (their styles and a 3D terrain on the Modified DEM layer survive, probed) and removes the old folder only when it was a temp one. A folder that cannot be written leaves the files where they were, with a message — the save itself has already happened. A session that ends removes only a temp folder.
- **Save after opening on another DEM writes this DEM's record, as today (user).**
- **Opening a scenario made on another DEM offers that DEM** when its file is still there: "Start on its DEM" (the layer already in the project that reads the file, or a new one; the unsaved-work question has been asked once already) or "Open on this DEM", or Cancel. When its file is gone, the Plan 6 question is unchanged.
- **Loose ends.** The test suite shuts down every `SketchController` a test made (`shutdown` is safe twice); `FeatureListModel.data` looks one feature up instead of building a dict; a drop of unknown ids is ignored instead of raising in Qt; copies of one feature stay in the order they were made; a Start whose working files fail in any way removes its folder; the export message adds a file already in the project only once and names the log for an unexpected failure; Export DEM… is an icon button like the other file actions; `load`/`load_meta` share one reader; a save back to the scenario's own file keeps its created date whatever the path's spelling.

## File Structure

| File | Responsibility |
|---|---|
| `terrain_sketch/core/sections.py` | Whole cross-section, reach rounding, default section line, section sampling |
| `terrain_sketch/core/engine.py` | `terrain_around`: terrain just before and after a feature over a grown window |
| `terrain_sketch/core/operations.py`, `core/stations.py` | The axis past an end cap |
| `terrain_sketch/model/feature.py` | `section_line` |
| `terrain_sketch/qgis_io/scenario.py` | `section_line` as WKT; one reader for `load` and `load_meta` |
| `terrain_sketch/qgis_io/raster_io.py`, `qgis_io/layers.py` | `WorkingFiles.move_to`, `SketchLayers.repoint` |
| `terrain_sketch/gui/controller.py` | Area section and section line, working rasters beside the scenario, the scenario's DEM, loose ends |
| `terrain_sketch/gui/profile_widget.py` | Mirrored cross profile, key-release commits |
| `terrain_sketch/gui/profile_dock.py` | Whole cross-section, area section, section-line buttons |
| `terrain_sketch/gui/properties_page.py` | Values follow every change; labels; pixel picture; group state |
| `terrain_sketch/gui/main_dock.py` | Section-line drawing and band, the DEM choice on Open, export and list loose ends |
| `terrain_sketch/gui/settings.py`, `terrain_sketch/plugin.py` | Dock placement and collapsed groups under `terrain_sketch/` |
| `terrain_sketch/gui/illustrations/` | Seven tool pictures, three pixel pictures, `data_uri` |
| `terrain_sketch/gui/help_texts.py`, `gui/feature_list.py` | Texts; list loose ends |

---

### Task 1: Loose ends

Small defects and test hygiene from the Plan 6 and 7 reviews. Nothing here changes what a user sees except the export message and the Export DEM… button.

**Files:**
- Modify: `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/feature_list.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/qgis_io/scenario.py`
- Test: `tests/qgis/conftest.py`, `tests/qgis/test_export_options.py`, `tests/qgis/test_file_safety.py`, `tests/qgis/test_list_actions.py`, `tests/qgis/test_scenario_file.py`, `tests/qgis/test_scenario_session.py`

**Interfaces:**
- Consumes: `SketchController.set_dem`, `shutdown`, `duplicate_feature`, `save_scenario`, `open_scenario`; `FeatureListModel`; `MainDock._file_button`, `_add_export`; `scenario.load`, `load_meta`.
- Produces: `SketchController.shutdown()` safe to call twice; `controller._same_file(path, other) -> bool`; `SketchController._mark_scenario(path, created)`; `help_texts.EXPORT_ADD_FAILED`; `main_dock._same_source(source, path) -> bool`; `scenario._reading(path, read)`; `tests/qgis/conftest.py` shuts down every controller after each test.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/conftest.py`
```python
"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject, QgsSettings

from terrain_sketch.gui import settings as plugin_settings
from terrain_sketch.gui.controller import SketchController

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()

# Every controller listens to the one QgsProject. Without letting go after each test, the controllers of
# every earlier test would still answer the next test's project signals.
_controllers = []
_controller_init = SketchController.__init__


def _tracked_init(self, *args, **kwargs):
    _controller_init(self, *args, **kwargs)
    _controllers.append(self)


SketchController.__init__ = _tracked_init


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
    while _controllers:
        _controllers.pop().shutdown()
    _clear_plugin_settings()


def _clear_plugin_settings() -> None:
    """Drop everything under the plugin's settings group so tests cannot inherit each other's."""
    settings = QgsSettings()
    settings.beginGroup(plugin_settings.GROUP)
    settings.remove("")
    settings.endGroup()
```

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
from terrain_sketch.gui.help_texts import EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED
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


def test_two_messages_about_the_same_file_add_it_once(tmp_path):
    """Exporting twice to one file leaves two messages, each with its own button."""
    from qgis.PyQt.QtWidgets import QPushButton
    iface, _c, dock = panel(tmp_path)
    path = export(dock, tmp_path)
    _text, first = pushed(iface)
    export(dock, tmp_path)
    _text, second = pushed(iface)
    for widget in (first, second):
        next(b for b in widget.findChildren(QPushButton) if b.text() == "Add to project").click()
    assert len([l for l in QgsProject.instance().mapLayers().values() if l.source() == path]) == 1


def test_an_unexpected_failure_adding_the_export_points_to_the_log(tmp_path):
    from unittest import mock
    _iface, _c, dock = panel(tmp_path)
    path = export(dock, tmp_path)
    heard = []
    dock._show_message = lambda level, text: heard.append(text)
    with mock.patch.object(QgsProject, "addMapLayer", side_effect=RuntimeError("layer registry refused")):
        dock._add_export(path)
    assert heard == [EXPORT_ADD_FAILED.format(path)]


def test_export_is_an_icon_button_like_the_other_file_actions(tmp_path):
    from qgis.PyQt.QtCore import Qt
    _iface, _c, dock = panel(tmp_path)
    assert dock.export_button.toolButtonStyle() == dock.save_scenario_button.toolButtonStyle() \
        == Qt.ToolButtonStyle.ToolButtonIconOnly
    assert dock.export_button.toolTip().startswith("Export DEM…\n")
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


def test_working_files_failing_in_an_unexpected_way_leave_no_folder_behind(tmp_path, monkeypatch):
    import tempfile
    made = []
    real = tempfile.mkdtemp
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kw: made.append(real(**kw)) or made[-1])
    c = SketchController(QgsProject.instance())
    dem = dem_layer(tmp_path)
    with mock.patch.object(controller_module, "WorkingFiles", side_effect=ValueError("a GDAL surprise")):
        with pytest.raises(DemError):
            c.set_dem(dem)
    assert made and not os.path.exists(made[0])


def test_a_start_that_fails_leaves_the_running_session_as_it_was(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    folder, working = c.files.folder, c.layers.working_id
    (tmp_path / "geographic").mkdir()
    with pytest.raises(DemError):
        c.set_dem(dem_layer(tmp_path / "geographic", name="lat_lon", crs="EPSG:4326",
                            gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001)))
    assert c.has_dem and [f.id for f in c.features] == [dike.id]
    assert os.path.isdir(folder) and QgsProject.instance().mapLayer(working) is not None


def test_shutting_a_controller_down_twice_is_safe(tmp_path):
    c = start_session(tmp_path)
    c.shutdown()
    c.shutdown()
    QgsProject.instance().clear()          # no longer listening, so nothing of it runs
    assert not c.has_dem
```

**File:** `tests/qgis/test_list_actions.py`
```python
"""The feature list's context menu (spec §7.2): Rename, Duplicate, Zoom to, Delete."""
from dataclasses import replace
from unittest import mock

import numpy as np
from qgis.core import QgsProject
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QMimeData, QModelIndex, Qt
from qgis.PyQt.QtWidgets import QAbstractItemView, QMenu

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.feature_list import MIME_TYPE
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
    assert replace(copy, id=dike.id, name=dike.name, enabled=dike.enabled) == dike   # every other field
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


def test_copies_of_one_feature_stay_in_the_order_they_were_made(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    first, second = c.duplicate_feature(dike.id), c.duplicate_feature(dike.id)
    assert [f.id for f in c.features] == [dike.id, first.id, second.id, pond.id]


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


def test_rename_after_the_list_changed_under_the_open_menu_does_not_take_qgis_down(tmp_path):
    """The menu runs its own event loop, so the list can change before Rename is picked. A row
    index taken when the menu was built then points past the end of the list, or at another feature."""
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    dock.show()
    rename = menu_action(dock, pond.id, "Rename")
    c.delete_feature(pond.id)                      # e.g. a layer signal while the menu is open
    rename.trigger()                               # the stale row used to abort QGIS
    assert dock.feature_view.state() != QAbstractItemView.State.EditingState


def test_a_context_menu_is_deleted_once_it_has_closed(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.show()
    position = dock.feature_view.visualRect(dock.model.index(0)).center()
    menus = len(dock.findChildren(QMenu))                           # the toolbar has one of its own
    with mock.patch.object(QMenu, "exec", return_value=None):      # the user closes it at once
        for _ in range(3):
            dock._context_menu(position)
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(dock.findChildren(QMenu)) == menus


def test_a_drop_of_features_the_list_does_not_have_changes_nothing(tmp_path):
    """A drag that started before the list changed carries ids that are no longer there; the drop
    runs inside Qt, where reorder()'s ValueError would abort QGIS."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    data = QMimeData()
    data.setData(MIME_TYPE, "\n".join([pond.id, "a feature that was deleted"]).encode())
    assert dock.model.dropMimeData(data, Qt.DropAction.MoveAction, 0, 0, QModelIndex()) is False
    assert [f.id for f in c.features] == [dike.id, pond.id]
```

**File:** `tests/qgis/test_scenario_file.py`
```python
"""The scenario GeoPackage on its own: what goes into the file and what comes back out."""
import os
from unittest import mock

import pytest
from osgeo import ogr
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.qgis_io import scenario
from terrain_sketch.qgis_io.scenario import (FEATURES_LAYER, META_TABLE, ScenarioError, ScenarioMeta,
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
    every = ScenarioMeta(dem_crs="EPSG:25832", dem_size="40x40", dem_pixel_size="1.0,1.0", dem_extent="0,0,40,40")
    moved = ScenarioMeta(dem_crs="EPSG:3035", dem_size="20x20", dem_pixel_size="2.0,2.0", dem_extent="5,5,45,45")
    assert every.differences(moved) == ["coordinate system", "size in pixels", "pixel size", "extent"]


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
    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        load(path)
    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        load_meta(path)


def test_saving_over_a_file_open_as_a_wal_layer_is_refused(tmp_path):
    """`os.replace` over a GeoPackage another program holds open in WAL mode (QGIS showing the
    scenario as a layer) leaves that program's `-wal`/`-shm` beside the new file — SQLite
    documents that pairing as a corruption path."""
    c = start_session(tmp_path)
    path = str(tmp_path / "open-elsewhere.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    before = (tmp_path / "open-elsewhere.gpkg").read_bytes()
    (tmp_path / "open-elsewhere.gpkg-wal").write_bytes(b"")

    with pytest.raises(ScenarioError):
        save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "open-elsewhere.gpkg").read_bytes() == before


def test_saving_over_a_geopackage_that_is_not_a_scenario_is_refused(tmp_path):
    """`os.replace` destroys every layer in the file it replaces — so a GeoPackage that holds
    the DEM or a user's other layers, not a scenario, must never be chosen as a save target."""
    c = start_session(tmp_path)
    path = str(tmp_path / "other.gpkg")
    source = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    source.CreateLayer("roads", None, ogr.wkbLineString)
    source.Close()
    before = (tmp_path / "other.gpkg").read_bytes()

    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "other.gpkg").read_bytes() == before


def test_saving_over_a_non_geopackage_file_is_refused(tmp_path):
    c = start_session(tmp_path)
    path = tmp_path / "notes.gpkg"
    path.write_text("not a geopackage")
    before = path.read_bytes()

    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        save(str(path), c.features, dem_meta(c.info, c.stack.original))
    assert path.read_bytes() == before


def test_replacing_an_existing_scenario_still_works(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "existing.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    save(path, c.features, dem_meta(c.info, c.stack.original))
    assert len(load(path)[0]) == 1


def test_a_save_that_fails_half_way_leaves_the_previous_file_readable(tmp_path):
    c = start_session(tmp_path)
    features = two_features(c)
    path = str(tmp_path / "precious.gpkg")
    save(path, features, dem_meta(c.info, c.stack.original))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 5, 34, 5), UTM)

    with mock.patch.object(scenario, "_write_meta", side_effect=RuntimeError("disk full")):
        with pytest.raises(ScenarioError):
            save(path, c.features, dem_meta(c.info, c.stack.original))
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


def test_a_replace_check_that_raises_is_reported_as_a_scenario_error_not_crashed(tmp_path):
    """`_is_scenario_file` guards only `ogr.Open` — `ExecuteSQL` and friends can still raise
    RuntimeError (e.g. "database is locked"). That must become ScenarioError, not escape raw:
    an exception escaping the Save button's Qt slot aborts QGIS."""
    c = start_session(tmp_path)
    path = str(tmp_path / "locked.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    before = (tmp_path / "locked.gpkg").read_bytes()

    with mock.patch.object(scenario, "_is_scenario_file", side_effect=RuntimeError("database is locked")):
        with pytest.raises(ScenarioError):
            save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "locked.gpkg").read_bytes() == before
    assert not [n for n in os.listdir(tmp_path) if ".saving-" in n]


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

**File:** `tests/qgis/test_scenario_session.py`
```python
"""Scenarios in a session: opening, saving, and never losing work that was not saved."""
import time
from unittest import mock

import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import SCENARIO_NOT_APPLIED
from terrain_sketch.qgis_io.scenario import ScenarioError, dem_meta, load, load_meta, save

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


def test_saving_to_the_same_file_by_another_spelling_keeps_the_created_date(tmp_path):
    c = start_session(tmp_path)
    two_features(c)
    (tmp_path / "elsewhere").mkdir()
    c.save_scenario(str(tmp_path / "dated.gpkg"))
    first = load_meta(str(tmp_path / "dated.gpkg"))
    time.sleep(1.1)                                                  # timestamps are to the second
    c.update_feature(c.features[0].id, amount=2.2)
    c.save_scenario(str(tmp_path / "elsewhere" / ".." / "dated.gpkg"))
    assert load_meta(str(tmp_path / "dated.gpkg")).created == first.created


def test_a_scenario_that_cannot_be_applied_changes_nothing(tmp_path):
    """`theirs.gpkg` is someone else's scenario, never opened by this session before — if
    `_scenario_path` were wrongly retargeted to it, the next Save would write over a file this
    session never touched. Saving the current work to `mine.gpkg` first, and building `theirs`
    from a separate feature list rather than through this controller, is what lets the test
    catch that: with both saved to the same file (as the previous version of this test did),
    `scenario_path` already equals it before opening, so a retarget to the same value is
    invisible."""
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    mine = str(tmp_path / "mine.gpkg")
    c.save_scenario(mine)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other = start_session(elsewhere)
    other.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    theirs = str(tmp_path / "theirs.gpkg")
    save(theirs, other.features, dem_meta(other.info, other.stack.original))

    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    before = c.features

    with mock.patch.object(c.stack, "update", side_effect=RuntimeError("engine refused")):
        with pytest.raises(ScenarioError, match=SCENARIO_NOT_APPLIED):
            c.open_scenario(theirs)
    assert c.features == before and c.find(pond.id) is not None
    assert c.is_dirty                               # the unsaved pond is still unsaved
    assert c.scenario_path == mine                  # not retargeted to the file that failed to open


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
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/qgis/test_export_options.py`
Expected: collection error `ImportError: cannot import name 'EXPORT_ADD_FAILED' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: The fixes**

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
```

Replace the whole file:

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

    def _id_at(self, index) -> str | None:
        """The feature id at `index`, or None. Qt checks only that a row is not negative, so an
        index kept across a reset (e.g. by a context menu) can point past the end of the list."""
        return self._ids[index.row()] if index.isValid() and index.row() < len(self._ids) else None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        fid = self._id_at(index)
        if fid is None:
            return None
        feature = self.controller.find(fid)
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
        fid = self._id_at(index)
        if fid is None:
            return False
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
        ids = (self._id_at(i) for i in indexes)
        data.setData(MIME_TYPE, "\n".join(fid for fid in ids if fid is not None).encode())
        return data

    def dropMimeData(self, data, action, row, column, parent):  # noqa: N802 — Qt override
        if action != Qt.DropAction.MoveAction or not data.hasFormat(MIME_TYPE):
            return False
        moving = bytes(data.data(MIME_TYPE)).decode().split("\n")
        if not set(moving) <= set(self._ids):
            return False     # ids from another list, or from before a change: reorder() would raise in this Qt callback
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
EXPORT_ADD_FAILED = ("The exported DEM {} could not be added to the project; see the 'Terrain Sketch' log tab "
                     "for details.")

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

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It is the project's terrain, but only a temporary one, "
               "even if you save the project meanwhile: the terrain you had before is put back when this "
               "session ends.")
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
from .help_texts import (EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED, EXPORT_REPLACE,
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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self._brush_extends = False       # set with _brush_fid, but kept when that feature goes
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
        self.export_button = _file_button(
            "/mActionSharingExport.svg", self.tr("Export DEM…"),
            self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
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
        carries on. The Properties page reloads its fields, which otherwise keep the undone values.
        `_brush_extends`, not `_brush_fid`: an undo that removes the feature itself has already cleared
        the id (featuresChanged comes first), and the brush would then add the old outline as a new feature."""
        self.stop_editing()
        if self._brush_extends:
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
        try:
            geometry = self._to_canvas(self.controller.feature_geometry(fid))
        except QgsCsException:
            # runs from selection and change signals, on every change: no message here, Edit shape
            # and Zoom to feature give one when the user acts on the outline
            self.highlight.reset(Qgis.GeometryType.Line)
            return
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
                if self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
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
    def read(source, layer):
        rows = sorted((_from_ogr(f) for f in layer), key=lambda pair: pair[0])
        return [feature for _order, feature in rows], _read_meta(source)
    return _reading(path, read)


def load_meta(path: str) -> ScenarioMeta:
    """Only the metadata, to compare DEMs before deciding whether to load. Raises ScenarioError
    for a file that is not a readable scenario, exactly as `load` would."""
    return _reading(path, lambda source, _layer: _read_meta(source))


def _reading(path: str, read):
    """`read(source, layer)` on the scenario at `path`, with the handle closed afterwards and any
    failure turned into a ScenarioError the user can read."""
    source = None
    try:
        source, layer = _open(path)
        return read(source, layer)
    except ScenarioError:
        raise
    except Exception as error:  # noqa: BLE001 — GDAL raises many types; the user gets one message
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

Run: `scripts/test.sh tests/qgis/test_export_options.py tests/qgis/test_file_safety.py tests/qgis/test_list_actions.py tests/qgis/test_scenario_file.py tests/qgis/test_scenario_session.py` → Expected: `61 passed`
Run: `scripts/test.sh` → Expected: `461 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/controller.py terrain_sketch/gui/feature_list.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/qgis_io/scenario.py tests/qgis/conftest.py tests/qgis/test_export_options.py tests/qgis/test_file_safety.py tests/qgis/test_list_actions.py tests/qgis/test_scenario_file.py tests/qgis/test_scenario_session.py
git commit -m "fix: loose ends in the list, the export message, scenario reading and test teardown"
```

---

### Task 2: Profile editor keys and a Properties page that keeps up

**Files:**
- Modify: `terrain_sketch/core/sections.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/gui/profile_widget.py`, `terrain_sketch/gui/properties_page.py`
- Test: `tests/core/test_sections.py`, `tests/qgis/test_profile_dock.py`, `tests/qgis/test_profile_widget.py`, `tests/qgis/test_undo_panel.py`

**Interfaces:**
- Consumes: `ProfileWidget.keyPressEvent`, `set_profile`, `clear`; `core.sections.set_cross_section`; `PropertiesPage.show_feature`; `MainDock._history_restored`.
- Produces: `profile_widget.NUDGE_KEYS`; `ProfileWidget.keyReleaseEvent`, `focusOutEvent`, `_commit_nudge()`; `sections._reach(distance, current) -> float`; `PropertiesPage._load_values(feature)` and `_refresh_values()` (connected to `featuresChanged`).

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_sections.py`
```python
import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, multi_wkb, polygon_wkb
from terrain_sketch.core.sections import (cross_section, long_section, set_cross_section,
                                          supports_long_profile)
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


def test_a_feature_with_no_terminal_slope_and_multiple_breaks_survives_a_round_trip():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0), (6.0, -2.0))
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(10.0)


def test_an_unsorted_break_list_produces_a_non_decreasing_distance_sequence():
    f = dike(width=4.0, slope_n=2.0, reach=20.0, cross_right=((6.0, -2.0), (3.0, -1.0)))
    points = cross_section(f)
    distances = [d for d, z in points]
    assert distances == sorted(distances)


def test_an_ordinary_round_trip_with_one_break_and_a_slope_remains_unchanged():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0),)
    assert changes["slope_n"] == pytest.approx(3.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_deleting_the_terminal_slope_yields_zero_slope_and_reach():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0)])
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)
    assert changes["cross_right"] == ()


def test_a_terminus_dragged_onto_the_edge_produces_no_break_at_distance_zero():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.0, -0.5)])
    assert changes["cross_right"] == ()
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)


def test_a_terminus_dragged_onto_the_last_break_produces_one_break_not_two():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (5.0, -1.0), (5.0, -1.5)])
    assert changes["cross_right"] == ((3.0, -1.5),)
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_an_identity_round_trip_through_the_no_terminus_branch_changes_nothing():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(f.width)
    assert changes["cross_right"] == f.cross_right
    assert changes["slope_n"] == pytest.approx(f.slope_n)
    assert changes["reach"] == pytest.approx(f.reach)


def two_part_dike(**kw):
    """A RAISE_PATH whose geometry has two separate line parts."""
    return feature(Tool.RAISE_PATH, Mode.PATH,
                   multi_wkb([line_wkb([(5, 20), (15, 20)]), line_wkb([(25, 20), (35, 20)])]), **kw)


def test_a_multi_part_path_does_not_support_a_custom_long_profile():
    assert supports_long_profile(dike())
    assert not supports_long_profile(two_part_dike())
    pond = feature(Tool.LOWER_FLAT, Mode.AREA,
                   polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]))
    assert not supports_long_profile(pond)


def test_a_multi_part_path_reports_the_rule_line_not_the_stored_custom_profile():
    """The engine applies a long profile only to a single-part path, so reporting one here
    would show the user a design line their terrain does not follow."""
    stored = ((0.0, 20.0), (10.0, 20.0))
    section = long_section(two_part_dike(amount=2.0, long_profile=stored), make_grid(tilted))
    assert not section["custom"]
    assert section["design"] != stored
    # the rule line: the terrain under the longest part plus the height
    assert section["design"][0][1] == pytest.approx(section["terrain"][0] + 2.0, abs=0.1)


def test_an_areas_cross_section_edit_writes_no_break_points():
    """Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    break list to `side_dz`, so storing them would keep a value the engine silently discards."""
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]),
                   slope_n=2.0, reach=6.0, amount=1.0)
    changes = set_cross_section(pond, 1, [(0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)])
    assert "cross_right" not in changes and "cross_left" not in changes
    assert "width" not in changes                       # an area has no corridor either
    assert changes["slope_n"] == pytest.approx(3.3333)  # 5 m run over 1.5 m rise
    assert changes["reach"] == pytest.approx(8.0)


def test_a_terminus_dragged_hard_against_its_neighbour_keeps_the_side_slope():
    """`_move_handle` clamps a dragged handle to neighbour + 1e-6, and a run that small rounds
    to 0.0 — the "no terminal slope" sentinel. There is no undo, so the slope is kept."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.000001, -3.0)])
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_terminus_dragged_hard_against_the_edge_keeps_its_reach():
    """A reach that rounds to 0.0 stops the slope at the edge — the slope kept by the test above
    would then change nothing."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.00001, -3.0)])
    assert changes["reach"] == pytest.approx(20.0)
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_real_but_very_flat_slope_is_still_written():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (22.0, -0.5)])
    assert changes["slope_n"] == pytest.approx(40.0)
```

**File:** `tests/qgis/test_profile_dock.py`
```python
import pytest
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent

from qgis_helpers import UTM, line_layer, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.help_texts import (AREA_LONG_SECTION_HINT, AREA_LONG_SECTION_NOTE,
                                           MULTIPART_LONG_SECTION_NOTE)
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


def test_the_side_slope_is_shared_between_the_sides_and_the_tip_says_so(tmp_path):
    """`slope_n` and `reach` are single per-feature fields (spec 5.4), so unticking Symmetric
    cannot stop them applying to both sides. The tooltip has to say that rather than promise
    that every edit is mirrored only while it is ticked."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(False)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (2.0, 0.0), (14.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.slope_n == pytest.approx(3.0) and updated.reach == pytest.approx(12.0)
    tip = dock.symmetric.toolTip()
    assert "break point" in tip.lower() and "both sides" in tip
    assert "every cross-profile edit" not in tip


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
    assert not dock.long.editable and not dock.symmetric.isEnabled()
    # there is no section through an area yet, so the panel says so instead of painting nothing
    assert dock.long.points == [] and dock.long.terrain == []
    assert dock.long.hint == AREA_LONG_SECTION_HINT
    assert dock.note.text() == AREA_LONG_SECTION_NOTE
    # and it never tells a user to select a feature they have already selected
    assert "Select or draw a feature" not in dock.long.hint
    assert "read-only section through the feature" not in dock.note.text()


def two_part_dike(controller):
    """One RAISE_PATH feature whose geometry has two separate line parts."""
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    return controller.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)


def test_a_multi_part_path_gets_a_read_only_long_panel_and_keeps_its_height_field(tmp_path):
    """The engine applies a custom long profile only to a single-part path, so offering one here
    would store the user's drags, disable Height, and change no terrain at all."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = two_part_dike(c)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert not dock.long.editable
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    assert not dock.reset_long.isEnabled()
    assert not c.long_section(dike.id)["custom"]

    # even with one already stored (an earlier version, or a path that was later extended)
    c.update_feature(dike.id, long_profile=((0.0, 20.0), (10.0, 20.0)))
    dock.show_feature(dike.id)
    assert not c.long_section(dike.id)["custom"]
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount.isEnabled()          # Height still drives the result, so it stays editable
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)   # the rule, not the 20 m profile


def test_an_area_cross_profile_refuses_break_points(tmp_path):
    """Break points are not supported for areas in v1 (spec 5.4): the engine discards them."""
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert dock.cross.editable and not dock.cross.allow_breaks
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 35, 34, 35), UTM)
    dock.show_feature(dike.id)
    assert dock.cross.allow_breaks


def test_editing_an_areas_cross_profile_stores_no_break_points(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)))
    updated = c.feature(pond.id)
    assert updated.cross_right == () and updated.cross_left == ()
    assert updated.reach == pytest.approx(8.0)      # the terminal slope still writes back


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


def test_deleting_the_shown_feature_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    c.delete_feature(dike.id)  # the Delete button, still showing this feature's profiles
    assert dock.cross.points == [] and dock.long.points == []


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


def mouse(widget, kind, point):
    event = QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent, QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent}[kind](event)


def test_undoing_the_shown_feature_during_a_drag_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    cross = dock.cross
    cross.resize(400, 200)
    handle = cross._to_screen(*cross.points[1])
    mouse(cross, QEvent.Type.MouseButtonPress, handle)
    assert cross._dragging == 1
    c.undo_stack.undo()                            # Ctrl+Z in the Profiles panel undoes the Add
    assert c.features == () and cross.points == []
    mouse(cross, QEvent.Type.MouseMove, handle + QPointF(20, -20))
    mouse(cross, QEvent.Type.MouseButtonRelease, handle + QPointF(20, -20))
    assert c.features == ()


def test_the_properties_page_follows_a_cross_profile_drag(tmp_path):
    """A drag moves the width, slope and reach. A page still showing the old values would write the
    old width back with the next arrow step on any of them."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (2.5, 0.0), (7.0, -1.2)))
    updated = c.feature(dike.id)
    assert (updated.width, updated.slope_n, updated.reach) == pytest.approx((5.0, 3.75, 4.5))
    assert page.width.value() == pytest.approx(5.0) and page.reach.value() == pytest.approx(4.5)
    assert page.slope.value() == pytest.approx(3.8)            # shown to its one decimal
    assert c.feature(dike.id).slope_n == pytest.approx(3.75)   # and not written back rounded
```

**File:** `tests/qgis/test_profile_widget.py`
```python
import pytest
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QKeyEvent, QMouseEvent

from terrain_sketch.gui.profile_widget import NUDGE, NUDGE_FINE, Kind, ProfileWidget


def press(widget, x, y, button=Qt.MouseButton.LeftButton, kind=QEvent.Type.MouseButtonPress):
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent,
     QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent,
     QEvent.Type.MouseButtonDblClick: widget.mouseDoubleClickEvent}[kind](event)


def widget_with(points, kind=Kind.CROSS, size=(400, 200), **kw):
    w = ProfileWidget(kind)
    w.resize(*size)
    w.set_profile(points, **kw)
    return w


def key(widget, which, modifiers=Qt.KeyboardModifier.NoModifier, release=True):
    """Press and let go of a key, as a tap does; the press event is returned."""
    event = QKeyEvent(QEvent.Type.KeyPress, which, modifiers)
    widget.keyPressEvent(event)
    if release:
        widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, modifiers))
    return event


def hold(widget, which, repeats):
    """Hold a key down: one press, then auto-repeated press and release pairs, then the real release."""
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, which, Qt.KeyboardModifier.NoModifier))
    for _ in range(repeats):
        widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, Qt.KeyboardModifier.NoModifier, "", True))
        widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, which, Qt.KeyboardModifier.NoModifier, "", True))
    widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, Qt.KeyboardModifier.NoModifier))


def select(widget, x, z):
    """Click a handle without moving it, as the user does before nudging with the arrow keys."""
    point = widget._to_screen(x, z)
    press(widget, point.x(), point.y())
    press(widget, point.x(), point.y(), kind=QEvent.Type.MouseButtonRelease)


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


def test_the_arrow_keys_nudge_the_selected_handle_and_commit_when_let_go():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)

    ignored = key(w, Qt.Key.Key_Up)                     # nothing selected yet
    assert not ignored.isAccepted() and committed == []

    select(w, 12.0, -3.0)
    assert committed == []                              # a click that moves nothing commits nothing
    accepted = key(w, Qt.Key.Key_Up, release=False)
    assert accepted.isAccepted()
    assert w.points[2][1] == pytest.approx(-3.0 + NUDGE)
    assert len(during) == 1 and committed == []         # shown while the key is down…
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    assert len(committed) == 1 and committed[-1] == tuple(w.points)   # …committed when it is let go

    key(w, Qt.Key.Key_Down)
    assert w.points[2][1] == pytest.approx(-3.0)
    key(w, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert w.points[2][0] == pytest.approx(12.0 + NUDGE_FINE)   # Shift nudges finely
    key(w, Qt.Key.Key_Left)
    assert w.points[2][0] == pytest.approx(12.0 + NUDGE_FINE - NUDGE)
    assert len(committed) == 4


def test_holding_an_arrow_key_is_one_change_not_one_per_repeat():
    """Auto-repeat sends about thirty presses a second, and each commit is a recompute, a file write
    and an undo step."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    hold(w, Qt.Key.Key_Up, repeats=9)
    assert w.points[2][1] == pytest.approx(-3.0 + 10 * NUDGE)
    assert len(during) == 10 and len(committed) == 1 and committed[0] == tuple(w.points)


def test_a_nudge_is_committed_when_the_plot_loses_focus_before_the_key_is_let_go():
    from qgis.PyQt.QtGui import QFocusEvent
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    key(w, Qt.Key.Key_Down, release=False)
    w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert len(committed) == 1
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    assert len(committed) == 1                          # the late release commits nothing more


def test_a_nudge_the_plot_was_reloaded_under_is_not_committed():
    """An undo can reload or clear the plot while a key is held; the release must not commit points
    that belonged to the profile before."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    key(w, Qt.Key.Key_Up, release=False)
    w.set_profile([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    assert committed == []


def test_the_arrow_keys_are_ignored_in_a_read_only_plot_and_for_other_keys():
    w = widget_with([(0.0, 10.0), (15.0, 11.0), (30.0, 12.0)], kind=Kind.LONG)
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 15.0, 11.0)
    assert key(w, Qt.Key.Key_Delete).isAccepted() is False   # not a nudge key
    w.editable = False
    assert key(w, Qt.Key.Key_Up).isAccepted() is False
    assert w.points[1] == (15.0, 11.0) and committed == []


def test_a_nudge_cannot_push_a_handle_past_its_neighbour():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (2.05, -1.0)])
    select(w, 2.05, -1.0)
    key(w, Qt.Key.Key_Left)                         # NUDGE is 0.1: further left than the neighbour
    assert w.points[1][0] < w.points[2][0]


def test_a_plot_without_break_points_refuses_to_add_or_remove_them():
    """An area's break points are discarded by the engine (spec 5.4), so the plot must not
    pretend to take them."""
    points = [(0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)]
    w = widget_with(points, allow_breaks=False)
    committed = []
    w.profileCommitted.connect(committed.append)
    target = w._to_screen(5.0, 1.0)
    press(w, target.x(), target.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 4 and committed == []           # nothing added
    handle = w._to_screen(3.0, 0.5)
    press(w, handle.x(), handle.y(), button=Qt.MouseButton.RightButton)
    assert len(w.points) == 4 and committed == []           # nothing removed
    # the terminal slope is still draggable: only the break points are off limits
    start = w._to_screen(8.0, 2.0)
    press(w, start.x(), start.y())
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseMove)
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert len(committed) == 1 and w.points[3][1] > 2.0


def test_clearing_the_plot_mid_drag_ends_the_drag():
    """Ctrl+Z during a drag can remove the shown feature, which clears the plot under the mouse.
    The next mouse move and release happen inside Qt, where an IndexError would abort QGIS."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    start = w._to_screen(2.0, 0.0)
    press(w, start.x(), start.y())
    assert w._dragging == 1
    w.clear()
    assert w._dragging == -1 and w._before is None
    press(w, start.x() + 20, start.y() - 20, kind=QEvent.Type.MouseMove)
    press(w, start.x() + 20, start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert w.points == [] and committed == []
```

**File:** `tests/qgis/test_undo_panel.py`
```python
"""Undo and redo from the panel: the buttons, Ctrl+Z where it belongs, and what the panel does after."""
import pytest
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


def test_undo_that_removes_the_feature_a_brush_extends_stops_the_brush(tmp_path):
    """The undo removes the pond itself. The brush still holds the pond's outline, and finishing it
    must not bring the undone pond back as a new feature."""
    _iface, c, dock = panel(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.feature_view.select_id(pond.id)
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    dock.gallery.select_mode(Mode.AREA)
    dock.gallery.method_buttons[Method.BRUSH].click()
    brush = dock.draw_tool
    assert brush is not None and dock._brush_fid == pond.id
    dock.undo_button.click()                               # undoes the Add of the pond
    assert c.features == () and dock.draw_tool is None
    brush.finish()                                         # a click that was already on its way
    assert c.features == ()


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


def test_ctrl_z_in_a_text_field_of_the_panel_is_left_to_that_field(tmp_path):
    """A spin box or line edit keeps Ctrl+Z for its own text, as everywhere in Qt: while there is
    typed text to undo, pressing it there must neither undo a Terrain Sketch change nor reach
    QGIS's own undo."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.pages.currentIndex() == PAGE_PROPERTIES
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    spin.selectAll()
    QTest.keyClicks(spin, "2")                             # typed, not yet committed
    assert spin.lineEdit().text() == "2 m"
    press(spin, QKeySequence.StandardKey.Undo)
    assert len(c.features) == 1 and c.find(dike.id).amount == 1.0 and qgis_undo == []
    assert spin.lineEdit().text() == "1.00 m"              # the field undid its own text


def test_ctrl_z_after_stepping_a_setting_undoes_the_change(tmp_path):
    """The arrows commit each step, so the field has no text of its own to undo: Ctrl+Z there
    undoes the whole adjustment, as one step, like it does anywhere else in the panel."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    for _ in range(3):
        QTest.keyClick(spin, Qt.Key.Key_Up)
        spin_event_loop(5)
    assert c.find(dike.id).amount == pytest.approx(1.3)
    press(spin, QKeySequence.StandardKey.Undo)
    assert c.find(dike.id).amount == 1.0 and spin.value() == 1.0 and qgis_undo == []
    press(spin, QKeySequence.StandardKey.Redo)
    assert c.find(dike.id).amount == pytest.approx(1.3) and qgis_undo == []


def test_ctrl_z_after_a_field_undid_its_own_text_undoes_the_last_change(tmp_path):
    """Once the typed text is undone the field has only a redo left, so the next Ctrl+Z goes on to
    the feature change instead of doing nothing."""
    iface, c, dock = panel(tmp_path)
    _window, qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    QTest.keyClick(spin, Qt.Key.Key_Up)
    spin_event_loop(5)
    spin.selectAll()
    QTest.keyClicks(spin, "2")                             # typed, not yet committed
    press(spin, QKeySequence.StandardKey.Undo)             # the field undoes its own text
    assert c.find(dike.id).amount == pytest.approx(1.1)
    press(spin, QKeySequence.StandardKey.Undo)
    assert c.find(dike.id).amount == 1.0 and qgis_undo == []


def test_the_undo_button_leaves_a_value_the_user_is_still_typing(tmp_path):
    """The button takes no focus, so the field keeps it and its typed text. Undo changes the feature;
    the typed value is still there to confirm with Enter, not silently thrown away."""
    iface, c, dock = panel(tmp_path)
    _window, _qgis_undo = in_a_window(iface, dock)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    c.update_feature(dike.id, width=dike.width + 1.0)
    spin = dock.properties.amount
    spin.setFocus()
    spin_event_loop(10)
    spin.selectAll()
    QTest.keyClicks(spin, "2")                             # typed, not yet committed
    dock.undo_button.click()
    assert c.find(dike.id).width == dike.width                   # the width change was undone
    assert dock.properties.width.value() == pytest.approx(dike.width)
    assert spin.lineEdit().text() == "2 m"
    QTest.keyClick(spin, Qt.Key.Key_Return)
    assert c.find(dike.id).amount == 2.0
```
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/qgis/test_profile_widget.py`
Expected: exit code 1 with `3 failed, 13 passed`

- [ ] **Step 3: Implement**

Replace the whole file:

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
    sorted_breaks = sorted(breaks, key=lambda b: b[0])
    for distance, dz in sorted_breaks:
        points.append((edge + float(distance), float(dz)))
    if limit > (sorted_breaks[-1][0] if sorted_breaks else 0.0):
        dz, _in_extent = side_dz(np.array([limit]), sorted_breaks, feature.slope_n, feature.reach,
                                 info.direction)
        points.append((edge + limit, float(dz[0])))
    return tuple(points)


def set_cross_section(feature, side: int, points) -> dict:
    """Turn edited cross-section points back into feature fields.

    `points` are ((distance from the centre line, dz), ...) as `cross_section` returns them.
    The first interior point sets the width; the rest become break points relative to the
    corridor edge; the last segment's run over rise sets the side slope.
    """
    pts = sorted([(float(d), float(z)) for d, z in points if float(d) >= 0.0], key=lambda p: p[0])
    if len(pts) < 2:
        raise ValueError("a cross section needs at least a centre and an edge point")
    edge = pts[1][0]
    changes: dict = {}
    # Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    # break list to `side_dz`, so writing them here would store a value the engine discards.
    breaks_key = ("cross_right" if side >= 0 else "cross_left") if feature.mode is Mode.PATH else None
    if feature.mode is Mode.PATH:
        changes["width"] = max(2.0 * edge, 0.1)

    # Only treat the final point as a slope terminus when the feature has a terminal slope
    # AND that point lies strictly beyond the last break; otherwise all points after the
    # edge are break points.
    has_terminal_slope = feature.slope_n > 0.0
    last_break_distance = pts[-2][0] if len(pts) > 2 else edge
    last_point_is_terminus = has_terminal_slope and pts[-1][0] > last_break_distance

    if last_point_is_terminus:
        interior, last = pts[2:-1], pts[-1]
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in interior)
        run = last[0] - (interior[-1][0] if interior else edge)
        rise = abs(last[1] - (interior[-1][1] if interior else 0.0))
        changes["slope_n"] = _slope_n(run, rise, feature.slope_n)
        changes["reach"] = _reach(last[0] - edge, feature.reach)
    else:
        # No terminal slope: all points after edge are breaks. Derive slope_n and reach.
        # Filter out breaks at distance 0 (at the edge itself) and collapse duplicates.
        interior = [(d, z) for d, z in pts[2:] if d > edge]

        # Collapse duplicate distances: keep the later (rightmost) value
        seen_distances = {}
        for d, z in interior:
            seen_distances[d] = z

        deduplicated = sorted(seen_distances.items())
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in deduplicated)
        changes["slope_n"] = 0.0
        changes["reach"] = 0.0 if not deduplicated else feature.reach

    return changes


def _slope_n(run: float, rise: float, current: float) -> float:
    """The terminal slope 1:n from a run over a rise, rounded to the stored four decimals.

    0.0 is the "no terminal slope" sentinel, so a run too small to round to a non-zero n — a
    terminus dragged hard against its neighbour — keeps the slope the feature already has
    rather than silently losing it. There is no undo.
    """
    if rise <= 1e-9:
        return 0.0
    rounded = round(run / rise, 4)
    return rounded if rounded > 0.0 else current


def _reach(distance: float, current: float) -> float:
    """The slope's reach from the terminus's distance beyond the edge, rounded like the slope.

    A reach of 0.0 stops the slope at the edge, so a terminus dragged hard against the edge rounds to
    nothing only by accident — the same drag `_slope_n` guards against — and keeps the reach it had."""
    rounded = round(distance, 4)
    return rounded if rounded > 0.0 else current


def section_part(feature):
    """The part a long section runs along: for a multi-part path, the longest one."""
    geometry_parts = [p for p in split_parts(feature.geometry_wkb) if is_line(p)]
    if feature.mode is not Mode.PATH or not geometry_parts:
        return None
    return max(geometry_parts, key=lambda p: _length(line_coords(p)))


def supports_long_profile(feature) -> bool:
    """Whether a custom long profile would actually drive this feature's terrain.

    `operations.apply_feature` uses one only for a single-part path (spec 5.4), so for anything
    else the editor must not offer one: it would be stored, shown as custom and then discarded,
    while the Height/Depth that does drive the result sits disabled.
    """
    if feature.mode is not Mode.PATH:
        return False
    try:
        return len(split_parts(feature.geometry_wkb)) == 1
    except ValueError:
        return False


def long_section(feature, grid: DemGrid, terrain: DemGrid | None = None) -> dict:
    """Reference terrain and design line along the feature's centre line.

    Returns `{"stations", "terrain", "design", "custom"}`: stations in metres from the start,
    terrain sampled on `terrain` (the state just before this feature) and the design line
    either from the feature's custom long profile or regenerated from the tool rule.

    `custom` is False whenever the engine would ignore the stored profile — a multi-part path —
    so the editor never presents a line the terrain does not follow.
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
    if feature.long_profile is not None and supports_long_profile(feature):
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
from .help_texts import (EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED, EXPORT_REPLACE,
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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self._brush_extends = False       # set with _brush_fid, but kept when that feature goes
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
        self.export_button = _file_button(
            "/mActionSharingExport.svg", self.tr("Export DEM…"),
            self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
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
        carries on. (The Properties page follows every change on its own.)
        `_brush_extends`, not `_brush_fid`: an undo that removes the feature itself has already cleared
        the id (featuresChanged comes first), and the brush would then add the old outline as a new feature."""
        self.stop_editing()
        if self._brush_extends:
            self.end_drawing()

    def _refresh_highlight(self) -> None:
        self._update_highlight(self.feature_view.selected_id())

    def _update_highlight(self, fid) -> None:
        """Outline the selected feature on the map."""
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
                if self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
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
from .overlay import CUT, FILL

MARGIN_LEFT, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_RIGHT = 46, 26, 10, 12
SHADE_ALPHA = 70        # the plot shades the same change as the map overlay, but behind the lines
GRAB_PIXELS = 8
HANDLE_RADIUS = 4
NUDGE, NUDGE_FINE = 0.1, 0.01
NUDGE_KEYS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right)


class Kind(Enum):
    CROSS = "cross"
    LONG = "long"


class ProfileWidget(QWidget):
    """Draws the reference terrain, the design line and draggable handles.

    Dragging emits `profileChanged` continuously and `profileCommitted` on release, both with
    the full point list. The arrow keys work the same way: each press (and each auto-repeat while a
    key is held) emits `profileChanged`, and letting go of the key commits once. The widget owns no
    feature state: whoever drives it sets points and applies the edits.
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
        self.allow_breaks = True
        self.hint = PROFILE_EMPTY_HINT
        self.selected = -1
        self._dragging = -1
        self._before: list | None = None
        self._nudge_before: list | None = None   # the points before the arrow key now held
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- contents -------------------------------------------------------------------

    def set_profile(self, points, terrain=(), editable=True, allow_breaks=True,
                    hint: str = PROFILE_EMPTY_HINT) -> None:
        """Show `points` over `terrain`.

        `allow_breaks` is False when the engine does not use break points for this feature, so
        the plot must refuse to add or remove them; `hint` is what an empty plot says instead of
        the default "select a feature". The widget knows nothing about features: the dock, which
        does, sets both.
        """
        self.points = [(float(x), float(z)) for x, z in points]
        self.terrain = [(float(x), float(z)) for x, z in terrain]
        self.editable = editable
        self.allow_breaks = allow_breaks
        self.hint = hint
        self.selected = -1
        self._dragging = -1
        self._nudge_before = None
        self.update()

    def clear(self, hint: str = PROFILE_EMPTY_HINT) -> None:
        self.points, self.terrain, self.hint, self.selected = [], [], hint, -1
        self._dragging, self._before = -1, None   # an undo can clear the plot under a drag
        self._nudge_before = None
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
        """Fill above the reference in warm, cut below it in cool — the drag preview's colours.

        These are the overlay's FILL and CUT, so the plot and the map agree while a handle is
        dragged. The committed change layer has a ramp of its own (`qgis_io/layers.py`).
        """
        reference = self._resampled_terrain()
        if reference is None:
            return
        for colour, above in ((QColor(*FILL, SHADE_ALPHA), True), (QColor(*CUT, SHADE_ALPHA), False)):
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
            if self.allow_breaks and index > 0 and index < len(self.points) - 1:
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
        if not 0 <= self._dragging < len(self.points):
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
        if not self.editable or not self.allow_breaks or event.button() != Qt.MouseButton.LeftButton:
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
        if not 0 <= self.selected < len(self.points) or not self.editable or event.key() not in deltas:
            event.ignore()
            return
        if self._nudge_before is None:
            self._nudge_before = list(self.points)
        dx, dz = deltas[event.key()]
        x, z = self.points[self.selected]
        self._move_handle(self.selected, (x + dx, z + dz))
        self.profileChanged.emit(tuple(self.points))
        event.accept()

    def keyReleaseEvent(self, event):  # noqa: N802 — Qt override
        """Commit a nudge when its key is let go. A held key sends a release with every auto-repeat
        too, so those are skipped: a second of holding Up is one change, not thirty."""
        if event.key() not in NUDGE_KEYS or event.isAutoRepeat():
            event.ignore()
            return
        self._commit_nudge()
        event.accept()

    def focusOutEvent(self, event):  # noqa: N802 — Qt override
        self._commit_nudge()   # the release never comes to a plot that lost focus while a key was held
        super().focusOutEvent(event)

    def _commit_nudge(self) -> None:
        before, self._nudge_before = self._nudge_before, None
        if before is not None and before != self.points:
            self.profileCommitted.emit(tuple(self.points))

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
        controller.featuresChanged.connect(self._refresh_values)
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
            self.amount_label.setText(label or "")
            self._load_values(feature)
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

    def _load_values(self, feature) -> None:
        """Show the feature's values in the fields — except in a field the user is still typing in:
        a change from elsewhere (a profile drag, an undo) must not throw away what they typed."""
        # Only a profile the engine actually uses fixes the heights: on a multi-part path it
        # is discarded, and Height/Depth is then the one control that still drives the result.
        custom = feature.long_profile is not None and supports_long_profile(feature)
        for spin, value in ((self.amount, feature.amount), (self.width, feature.width),
                            (self.slope, feature.slope_n), (self.reach, feature.reach)):
            if not spin.lineEdit().isModified():
                spin.setValue(value)
        self.amount.setEnabled(not custom)
        self.amount.setToolTip(AMOUNT_IS_CUSTOM if custom else self._amount_tip)
        self.slope_position.setCurrentIndex(1 if feature.slopes_inside else 0)
        self.pixel_mode.setCurrentIndex(self.pixel_mode.findData(feature.pixel_mode.value))

    def _refresh_values(self) -> None:
        """Keep the fields in step with the feature whenever the list changes: a cross-profile drag
        moves the width, slope and reach, and an undo can change anything. Runs in a slot."""
        try:
            feature = self.controller.find(self._fid) if self._fid is not None else None
            if feature is None:
                return
            self._loading = True
            try:
                self._load_values(feature)
            finally:
                self._loading = False
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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

Run: `scripts/test.sh tests/core/test_sections.py tests/qgis/test_profile_dock.py tests/qgis/test_profile_widget.py tests/qgis/test_undo_panel.py` → Expected: `69 passed`
Run: `scripts/test.sh` → Expected: `467 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/core/sections.py terrain_sketch/gui/main_dock.py terrain_sketch/gui/profile_widget.py terrain_sketch/gui/properties_page.py tests/core/test_sections.py tests/qgis/test_profile_dock.py tests/qgis/test_profile_widget.py tests/qgis/test_undo_panel.py
git commit -m "fix(gui): an arrow key commits once when let go, and the Properties page follows every change"
```

---

### Task 3: The whole cross-section, and the axis past an end cap

**Files:**
- Modify: `terrain_sketch/core/operations.py`, `terrain_sketch/core/sections.py`, `terrain_sketch/core/stations.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/profile_dock.py`, `terrain_sketch/gui/profile_widget.py`
- Test: `tests/core/test_operations.py`, `tests/core/test_sections.py`, `tests/qgis/test_profile_dock.py`, `tests/qgis/test_profile_widget.py`, `tests/qgis/test_undo.py`

**Interfaces:**
- Consumes: Task 2's `ProfileWidget` (`_nudge_before`, `NUDGE_KEYS`); `sections.cross_section`, `set_cross_section`; `operations._path_values`; `stations.stations_offsets`.
- Produces: `sections.whole_cross_section(feature) -> tuple`, `set_whole_cross_section(feature, points, symmetric=False) -> dict`, `SAME`; `ProfileWidget.mirrored`, `symmetric`, `set_profile(..., mirrored=False)`, `profile_widget.MIN_HALF_WIDTH`; `help_texts.CROSS_SIDES_TIP`; `stations_offsets` gives 0 on the line through the nearest segment.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/core/test_operations.py`
```python
import numpy as np
import pytest

import terrain_sketch.core.operations as operations_module
from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.geometry import line_wkb, multi_wkb, polygon_wkb
from terrain_sketch.core.operations import (FLAG_BAD_GEOMETRY, FLAG_NO_PIXELS,
                                            FLAG_NODATA_REFERENCE, FLAG_OUTSIDE, apply_feature)
from terrain_sketch.core.tools import Mode, PixelMode, Tool

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


def test_raise_flat_area_levels_from_its_outline_so_a_knoll_inside_pokes_through():
    """The reference is the highest point on the outline the user draws, not the highest ground
    the outline covers. The panel says so in three places; this is the case that tells them
    apart, and the one a user drawing a pad around a knoll actually meets."""
    grid = make_grid(lambda X, Y: 10.0 + bump(X, Y))     # a 3 m knoll at (20, 20.5), flat elsewhere
    before, after, _ = run(grid, feature(Tool.RAISE_FLAT, Mode.AREA, square(10.3, 10.3, 30.3, 30.3),
                                         amount=1.0, slope_n=0.0))
    assert before[ROW, 20] > 12.9                        # the knoll, ~3 m above the outline
    assert after[15, 15] == pytest.approx(11.0, abs=0.01)          # outline maximum plus 1 m
    assert after[ROW, 20] == pytest.approx(before[ROW, 20], abs=1e-6)  # left alone: it is higher


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


@pytest.mark.parametrize("mode", list(PixelMode))
@pytest.mark.parametrize("tool, sign", [(Tool.RAISE_PATH, 1.0), (Tool.LOWER_PATH, -1.0)])
def test_path_cross_section_has_no_gap_in_any_pixel_mode(tool, sign, mode):
    """Slope distance must be measured from the pixel-mode's own crest (`core`), not always
    from the centre-mode band: otherwise the ring between the crest and the band is neither
    crest nor slope and stays untouched, leaving a gap in the cross-section (I1)."""
    _, after, _ = run(make_grid(flat(10)),
                      feature(tool, Mode.PATH, EAST_WEST, amount=2.0, width=4.0, slope_n=2.0, pixel_mode=mode))
    col = sign * (after[:, 20] - 10.0)
    top = int(np.argmax(col))
    assert col[top] == pytest.approx(2.0)
    assert (np.diff(col[top::-1]) <= 1e-6).all()
    assert (np.diff(col[top:]) <= 1e-6).all()


def test_wide_path_with_a_sharp_bend_is_not_cut_off(monkeypatch):
    """A sharp mitred bend's corridor can extend up to the full width beyond the vertex; the
    footprint window must cover the whole mitre spike, not just the line's own bbox padded by
    width/2 + slope limit (I2). A too-small window truncates the slope, so a much larger
    MARGIN_CELLS must produce the identical result once the footprint is correct."""
    wkb = line_wkb([(30.0, 20.0), (40.0, 60.0), (50.0, 20.0)])
    f = feature(Tool.RAISE_PATH, Mode.PATH, wkb, amount=3.0, width=12.0, slope_n=2.0, reach=5.0)
    default = make_grid(flat(0), rows=100, cols=80)
    apply_feature(f, default)
    monkeypatch.setattr(operations_module, "MARGIN_CELLS", 30)
    wide_margin = make_grid(flat(0), rows=100, cols=80)
    apply_feature(f, wide_margin)
    np.testing.assert_array_equal(default.data, wide_margin.data)


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


def test_straight_past_an_end_the_axis_follows_the_side_the_combine_rule_keeps():
    """A cell exactly on the extended axis is on neither side. It used to take the right-hand shape
    always, leaving a one-cell notch into a berm on the left."""
    axis = line_wkb([(10.5, 20.5), (29.5, 20.5)])                      # through the centres of row 19
    grid = make_grid(flat(10.0))
    apply_feature(feature(Tool.RAISE_PATH, Mode.PATH, axis, amount=2.0, width=3.0, slope_n=2.0, reach=10.0,
                          cross_left=((2.0, 0.0),)), grid)            # a berm at crest level on the left only
    after = grid.data.astype(float)
    beyond = slice(31, 36)                                           # past the east end
    np.testing.assert_allclose(after[19, beyond], after[18, beyond])  # the left (north) row, with its berm
    assert (after[19, beyond] > after[20, beyond]).any()

    lowered = make_grid(flat(10.0))
    apply_feature(feature(Tool.LOWER_PATH, Mode.PATH, axis, amount=2.0, width=3.0, slope_n=2.0, reach=10.0,
                          cross_left=((2.0, 0.0),)), lowered)         # a lower tool keeps the deeper side
    cut = lowered.data.astype(float)
    np.testing.assert_allclose(cut[19, beyond], cut[18, beyond])
    assert (cut[19, beyond] < cut[20, beyond]).any()


def test_the_axis_past_the_far_end_is_found_even_when_the_lengths_differ_in_the_last_bit():
    """The station of a cell past the end and the path's length are summed differently; on some paths
    the station falls one bit short of the length, and the far end kept its notch."""
    bent = line_wkb([(4.034, 4.192), (10.5, 20.5), (29.5, 20.5)])
    grid = make_grid(flat(10.0))
    apply_feature(feature(Tool.RAISE_PATH, Mode.PATH, bent, amount=2.0, width=3.0, slope_n=2.0, reach=10.0,
                          cross_left=((2.0, 0.0),)), grid)
    after = grid.data.astype(float)
    beyond = slice(31, 36)
    np.testing.assert_allclose(after[19, beyond], after[18, beyond])


def test_a_point_straight_ahead_of_an_end_is_on_neither_side():
    from terrain_sketch.core.stations import stations_offsets
    coords = np.array([[0.0, 0.0], [10.0, 0.0]])
    station, offset = stations_offsets(coords, np.array([15.0, -3.0, 5.0, 5.0]), np.array([0.0, 0.0, 2.0, -2.0]))
    assert list(offset) == [0.0, 0.0, -2.0, 2.0] and list(station) == [10.0, 0.0, 5.0, 5.0]
```

**File:** `tests/core/test_sections.py`
```python
import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, multi_wkb, polygon_wkb
from terrain_sketch.core.sections import (cross_section, long_section, set_cross_section, set_whole_cross_section,
                                          supports_long_profile, whole_cross_section)
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


def test_a_feature_with_no_terminal_slope_and_multiple_breaks_survives_a_round_trip():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0), (6.0, -2.0))
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(10.0)


def test_an_unsorted_break_list_produces_a_non_decreasing_distance_sequence():
    f = dike(width=4.0, slope_n=2.0, reach=20.0, cross_right=((6.0, -2.0), (3.0, -1.0)))
    points = cross_section(f)
    distances = [d for d, z in points]
    assert distances == sorted(distances)


def test_an_ordinary_round_trip_with_one_break_and_a_slope_remains_unchanged():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0),)
    assert changes["slope_n"] == pytest.approx(3.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_deleting_the_terminal_slope_yields_zero_slope_and_reach():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0)])
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)
    assert changes["cross_right"] == ()


def test_a_terminus_dragged_onto_the_edge_produces_no_break_at_distance_zero():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.0, -0.5)])
    assert changes["cross_right"] == ()
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)


def test_a_terminus_dragged_onto_the_last_break_produces_one_break_not_two():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (5.0, -1.0), (5.0, -1.5)])
    assert changes["cross_right"] == ((3.0, -1.5),)
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_an_identity_round_trip_through_the_no_terminus_branch_changes_nothing():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(f.width)
    assert changes["cross_right"] == f.cross_right
    assert changes["slope_n"] == pytest.approx(f.slope_n)
    assert changes["reach"] == pytest.approx(f.reach)


def two_part_dike(**kw):
    """A RAISE_PATH whose geometry has two separate line parts."""
    return feature(Tool.RAISE_PATH, Mode.PATH,
                   multi_wkb([line_wkb([(5, 20), (15, 20)]), line_wkb([(25, 20), (35, 20)])]), **kw)


def test_a_multi_part_path_does_not_support_a_custom_long_profile():
    assert supports_long_profile(dike())
    assert not supports_long_profile(two_part_dike())
    pond = feature(Tool.LOWER_FLAT, Mode.AREA,
                   polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]))
    assert not supports_long_profile(pond)


def test_a_multi_part_path_reports_the_rule_line_not_the_stored_custom_profile():
    """The engine applies a long profile only to a single-part path, so reporting one here
    would show the user a design line their terrain does not follow."""
    stored = ((0.0, 20.0), (10.0, 20.0))
    section = long_section(two_part_dike(amount=2.0, long_profile=stored), make_grid(tilted))
    assert not section["custom"]
    assert section["design"] != stored
    # the rule line: the terrain under the longest part plus the height
    assert section["design"][0][1] == pytest.approx(section["terrain"][0] + 2.0, abs=0.1)


def test_an_areas_cross_section_edit_writes_no_break_points():
    """Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    break list to `side_dz`, so storing them would keep a value the engine silently discards."""
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]),
                   slope_n=2.0, reach=6.0, amount=1.0)
    changes = set_cross_section(pond, 1, [(0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)])
    assert "cross_right" not in changes and "cross_left" not in changes
    assert "width" not in changes                       # an area has no corridor either
    assert changes["slope_n"] == pytest.approx(3.3333)  # 5 m run over 1.5 m rise
    assert changes["reach"] == pytest.approx(8.0)


def test_a_terminus_dragged_hard_against_its_neighbour_keeps_the_side_slope():
    """`_move_handle` clamps a dragged handle to neighbour + 1e-6, and a run that small rounds
    to 0.0 — the "no terminal slope" sentinel. There is no undo, so the slope is kept."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.000001, -3.0)])
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_terminus_dragged_hard_against_the_edge_keeps_its_reach():
    """A reach that rounds to 0.0 stops the slope at the edge — the slope kept by the test above
    would then change nothing."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.00001, -3.0)])
    assert changes["reach"] == pytest.approx(20.0)
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_real_but_very_flat_slope_is_still_written():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (22.0, -0.5)])
    assert changes["slope_n"] == pytest.approx(40.0)


def test_the_whole_cross_section_runs_from_the_left_slope_to_the_right_one():
    f = dike(width=4.0, slope_n=2.0, reach=10.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5),))
    points = whole_cross_section(f)
    assert points[0][0] == pytest.approx(-12.0) and points[-1][0] == pytest.approx(12.0)
    assert (-4.0, -0.5) in points and (-2.0, 0.0) in points and (2.0, 0.0) in points and (6.0, -1.5) in points
    assert [x for x, _z in points] == sorted(x for x, _z in points)
    assert not any(x == 0.0 for x, _z in points)                # no centre handle: the crest runs across it


def test_an_untouched_whole_section_writes_back_what_the_feature_has():
    f = dike(width=4.5, slope_n=2.5, reach=12.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5), (6.0, -1.6)))
    changes = set_whole_cross_section(f, whole_cross_section(f))
    assert changes["width"] == pytest.approx(4.5)
    assert changes["slope_n"] == pytest.approx(2.5) and changes["reach"] == pytest.approx(12.0)
    for side in ("cross_left", "cross_right"):
        assert len(changes[side]) == len(getattr(f, side))
        for written, stored in zip(changes[side], getattr(f, side)):
            assert written == pytest.approx(stored)


def test_a_left_side_edit_changes_the_left_side_and_the_shared_slope():
    f = dike(width=4.0, slope_n=3.0, reach=10.0)
    points = list(whole_cross_section(f))
    points[0] = (-14.0, -4.0)                                   # the left slope's end: 12 m out, 4 m down
    changes = set_whole_cross_section(f, points)
    assert changes["reach"] == pytest.approx(12.0) and changes["slope_n"] == pytest.approx(3.0)
    assert changes["cross_left"] == () and changes["cross_right"] == ()


def test_symmetric_copies_the_edited_side_whichever_side_it_is():
    f = dike(width=4.0, slope_n=3.0, reach=10.0)
    left_berm = [(-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (12.0, -10.0 / 3.0)]
    assert set_whole_cross_section(f, left_berm, symmetric=True)["cross_right"] == ((4.0, -1.0),)
    right_berm = [(-12.0, -10.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)]
    assert set_whole_cross_section(f, right_berm, symmetric=True)["cross_left"] == ((4.0, -1.0),)
    unticked = set_whole_cross_section(f, left_berm, symmetric=False)
    assert unticked["cross_left"] == ((4.0, -1.0),) and unticked["cross_right"] == ()


def test_editing_one_side_leaves_a_side_with_breaks_past_its_reach_as_it_was():
    """A berm beyond the reach leaves that side without a slope-end handle. Reading its last berm as the
    slope's end rewrote the slope and the reach and dropped the berm while the user edited the other side."""
    f = dike(width=4.0, slope_n=3.0, reach=5.0, cross_right=((2.0, -0.5), (8.0, -1.0)))
    points = list(whole_cross_section(f))
    assert points[-1] == (10.0, -1.0)                               # the berm is the last handle
    points[0] = (-10.0, -8.0 / 3.0)                                 # the left slope's end, 3 m further out
    changes = set_whole_cross_section(f, points)
    assert changes["cross_right"] == f.cross_right and changes["cross_left"] == ()
    assert changes["slope_n"] == pytest.approx(3.0) and changes["reach"] == pytest.approx(8.0)


def test_a_side_whose_breaks_run_past_its_reach_keeps_its_slope_when_edited():
    f = dike(width=4.0, slope_n=3.0, reach=5.0, cross_right=((2.0, -0.5), (8.0, -1.0)))
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (4.0, -0.5), (10.0, -1.4)])
    assert changes["cross_right"] == ((2.0, -0.5), (8.0, -1.4))
    assert "slope_n" not in changes and "reach" not in changes


def test_the_side_that_was_not_edited_does_not_change_the_shared_values():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0),))
    points = list(whole_cross_section(f))
    points[-1] = (6.0, -1.5)                                        # drag the right berm
    changes = set_whole_cross_section(f, points)
    assert changes["cross_right"] == ((4.0, -1.5),) and changes["reach"] == pytest.approx(10.0)
    # a stored value halfway between two four-decimal numbers still counts as unchanged on the other side
    odd = dike(width=4.0, slope_n=3.0, reach=40.34765)
    moved = list(whole_cross_section(odd))
    moved[0] = (moved[0][0] - 3.0, moved[0][1] - 1.0)
    assert set_whole_cross_section(odd, moved)["reach"] == pytest.approx(43.34765, abs=1e-4)
```

**File:** `tests/qgis/test_profile_dock.py`
```python
import pytest
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent

from qgis_helpers import UTM, line_layer, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.help_texts import (AREA_LONG_SECTION_HINT, AREA_LONG_SECTION_NOTE,
                                           MULTIPART_LONG_SECTION_NOTE)
from terrain_sketch.gui.profile_dock import ProfileDock


def test_the_profile_dock_loads_the_selected_feature(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.mirrored                                     # both sides of the path
    assert (-dike.width / 2.0, 0.0) in dock.cross.points and (dike.width / 2.0, 0.0) in dock.cross.points
    assert dock.cross.points[0][0] == -dock.cross.points[-1][0] < 0.0
    assert len(dock.long.terrain) == 200 and len(dock.long.points) >= 2
    assert dock.note.text() == ""


def test_editing_the_cross_profile_writes_width_and_slope_back(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, )
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((-15.0, -4.0), (-3.0, 0.0), (3.0, 0.0), (15.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.width == pytest.approx(6.0)
    assert updated.slope_n == pytest.approx(3.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)


def test_symmetric_mirrors_the_edit_to_the_other_side(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=10.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(True)
    # a berm added on the right; the left side is still as it was
    dock.cross.profileCommitted.emit(((-12.0, -10.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)))
    updated = c.feature(dike.id)
    assert updated.cross_left == updated.cross_right == ((4.0, -1.0),)
    dock.symmetric.setChecked(False)
    assert dock.cross.points == [(-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)]
    dock.cross.profileCommitted.emit(((-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (8.0, -2.0), (14.0, -4.0)))
    after = c.feature(dike.id)
    assert after.cross_right == ((6.0, -2.0),) and after.cross_left == ((4.0, -1.0),)


def test_the_side_slope_is_shared_between_the_sides_and_the_tip_says_so(tmp_path):
    """`slope_n` and `reach` are single per-feature fields (spec 5.4), so unticking Symmetric
    cannot stop them applying to both sides. The tooltip has to say that rather than promise
    that every edit is mirrored only while it is ticked."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=20.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(False)
    # only the right slope's end moves; the left side is still as it was
    dock.cross.profileCommitted.emit(((-22.0, -20.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (14.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.slope_n == pytest.approx(3.0) and updated.reach == pytest.approx(12.0)
    tip = dock.symmetric.toolTip()
    assert "break point" in tip.lower() and "both sides" in tip
    assert "every cross-profile edit" not in tip


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
    assert not dock.long.editable and not dock.symmetric.isEnabled()
    # there is no section through an area yet, so the panel says so instead of painting nothing
    assert dock.long.points == [] and dock.long.terrain == []
    assert dock.long.hint == AREA_LONG_SECTION_HINT
    assert dock.note.text() == AREA_LONG_SECTION_NOTE
    # and it never tells a user to select a feature they have already selected
    assert "Select or draw a feature" not in dock.long.hint
    assert "read-only section through the feature" not in dock.note.text()


def two_part_dike(controller):
    """One RAISE_PATH feature whose geometry has two separate line parts."""
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    return controller.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)


def test_a_multi_part_path_gets_a_read_only_long_panel_and_keeps_its_height_field(tmp_path):
    """The engine applies a custom long profile only to a single-part path, so offering one here
    would store the user's drags, disable Height, and change no terrain at all."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = two_part_dike(c)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert not dock.long.editable
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    assert not dock.reset_long.isEnabled()
    assert not c.long_section(dike.id)["custom"]

    # even with one already stored (an earlier version, or a path that was later extended)
    c.update_feature(dike.id, long_profile=((0.0, 20.0), (10.0, 20.0)))
    dock.show_feature(dike.id)
    assert not c.long_section(dike.id)["custom"]
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount.isEnabled()          # Height still drives the result, so it stays editable
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)   # the rule, not the 20 m profile


def test_an_area_cross_profile_refuses_break_points(tmp_path):
    """Break points are not supported for areas in v1 (spec 5.4): the engine discards them."""
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert dock.cross.editable and not dock.cross.allow_breaks
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 35, 34, 35), UTM)
    dock.show_feature(dike.id)
    assert dock.cross.allow_breaks


def test_editing_an_areas_cross_profile_stores_no_break_points(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)))
    updated = c.feature(pond.id)
    assert updated.cross_right == () and updated.cross_left == ()
    assert updated.reach == pytest.approx(8.0)      # the terminal slope still writes back


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


def test_deleting_the_shown_feature_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    c.delete_feature(dike.id)  # the Delete button, still showing this feature's profiles
    assert dock.cross.points == [] and dock.long.points == []


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


def mouse(widget, kind, point):
    event = QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent, QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent}[kind](event)


def test_undoing_the_shown_feature_during_a_drag_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    cross = dock.cross
    cross.resize(400, 200)
    handle = cross._to_screen(*cross.points[1])
    mouse(cross, QEvent.Type.MouseButtonPress, handle)
    assert cross._dragging == 1
    c.undo_stack.undo()                            # Ctrl+Z in the Profiles panel undoes the Add
    assert c.features == () and cross.points == []
    mouse(cross, QEvent.Type.MouseMove, handle + QPointF(20, -20))
    mouse(cross, QEvent.Type.MouseButtonRelease, handle + QPointF(20, -20))
    assert c.features == ()


def test_the_properties_page_follows_a_cross_profile_drag(tmp_path):
    """A drag moves the width, slope and reach. A page still showing the old values would write the
    old width back with the next arrow step on any of them."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((-7.0, -1.2), (-2.5, 0.0), (2.5, 0.0), (7.0, -1.2)))
    updated = c.feature(dike.id)
    assert (updated.width, updated.slope_n, updated.reach) == pytest.approx((5.0, 3.75, 4.5))
    assert page.width.value() == pytest.approx(5.0) and page.reach.value() == pytest.approx(4.5)
    assert page.slope.value() == pytest.approx(3.8)            # shown to its one decimal
    assert c.feature(dike.id).slope_n == pytest.approx(3.75)   # and not written back rounded


def test_the_left_side_of_a_path_can_be_given_its_own_berm(tmp_path):
    """Until the whole cross-section was shown, only the right side could be edited."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=10.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(False)
    right = [p for p in dock.cross.points if p[0] > 0.0]
    dock.cross.profileCommitted.emit(((-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), *right))
    updated = c.feature(dike.id)
    assert updated.cross_left == ((4.0, -1.0),) and updated.cross_right == ()
    assert (updated.width, updated.slope_n, updated.reach) == pytest.approx((4.0, 3.0, 10.0))
    assert sample(c.layers.working, 20, 16) > sample(c.layers.working, 20, 24)   # north is left of an eastward path


def test_the_symmetric_box_tells_the_plot_to_move_mirror_handles_together(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.symmetric
    dock.symmetric.setChecked(False)
    assert not dock.cross.symmetric


def test_the_cross_plot_explains_its_sides_only_for_a_path_it_can_edit(tmp_path):
    from terrain_sketch.gui.help_texts import CROSS_SIDES_TIP
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 25, 25, 35), UTM)
    band = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 5, 34, 5), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.toolTip() == CROSS_SIDES_TIP
    for other in (pond.id, band.id, None):
        dock.show_feature(other)
        assert dock.cross.toolTip() == "", other
```

**File:** `tests/qgis/test_profile_widget.py`
```python
import pytest
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QKeyEvent, QMouseEvent

from terrain_sketch.gui.profile_widget import NUDGE, NUDGE_FINE, Kind, ProfileWidget


def press(widget, x, y, button=Qt.MouseButton.LeftButton, kind=QEvent.Type.MouseButtonPress):
    event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent,
     QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent,
     QEvent.Type.MouseButtonDblClick: widget.mouseDoubleClickEvent}[kind](event)


def widget_with(points, kind=Kind.CROSS, size=(400, 200), **kw):
    w = ProfileWidget(kind)
    w.resize(*size)
    w.set_profile(points, **kw)
    return w


def key(widget, which, modifiers=Qt.KeyboardModifier.NoModifier, release=True):
    """Press and let go of a key, as a tap does; the press event is returned."""
    event = QKeyEvent(QEvent.Type.KeyPress, which, modifiers)
    widget.keyPressEvent(event)
    if release:
        widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, modifiers))
    return event


def hold(widget, which, repeats):
    """Hold a key down: one press, then auto-repeated press and release pairs, then the real release."""
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, which, Qt.KeyboardModifier.NoModifier))
    for _ in range(repeats):
        widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, Qt.KeyboardModifier.NoModifier, "", True))
        widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, which, Qt.KeyboardModifier.NoModifier, "", True))
    widget.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, which, Qt.KeyboardModifier.NoModifier))


def select(widget, x, z):
    """Click a handle without moving it, as the user does before nudging with the arrow keys."""
    point = widget._to_screen(x, z)
    press(widget, point.x(), point.y())
    press(widget, point.x(), point.y(), kind=QEvent.Type.MouseButtonRelease)


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


def test_the_arrow_keys_nudge_the_selected_handle_and_commit_when_let_go():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)

    ignored = key(w, Qt.Key.Key_Up)                     # nothing selected yet
    assert not ignored.isAccepted() and committed == []

    select(w, 12.0, -3.0)
    assert committed == []                              # a click that moves nothing commits nothing
    accepted = key(w, Qt.Key.Key_Up, release=False)
    assert accepted.isAccepted()
    assert w.points[2][1] == pytest.approx(-3.0 + NUDGE)
    assert len(during) == 1 and committed == []         # shown while the key is down…
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    assert len(committed) == 1 and committed[-1] == tuple(w.points)   # …committed when it is let go

    key(w, Qt.Key.Key_Down)
    assert w.points[2][1] == pytest.approx(-3.0)
    key(w, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    assert w.points[2][0] == pytest.approx(12.0 + NUDGE_FINE)   # Shift nudges finely
    key(w, Qt.Key.Key_Left)
    assert w.points[2][0] == pytest.approx(12.0 + NUDGE_FINE - NUDGE)
    assert len(committed) == 4


def test_holding_an_arrow_key_is_one_change_not_one_per_repeat():
    """Auto-repeat sends about thirty presses a second, and each commit is a recompute, a file write
    and an undo step."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    during, committed = [], []
    w.profileChanged.connect(during.append)
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    hold(w, Qt.Key.Key_Up, repeats=9)
    assert w.points[2][1] == pytest.approx(-3.0 + 10 * NUDGE)
    assert len(during) == 10 and len(committed) == 1 and committed[0] == tuple(w.points)


def test_a_nudge_is_committed_when_the_plot_loses_focus_before_the_key_is_let_go():
    from qgis.PyQt.QtGui import QFocusEvent
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    key(w, Qt.Key.Key_Down, release=False)
    w.focusOutEvent(QFocusEvent(QEvent.Type.FocusOut))
    assert len(committed) == 1
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier))
    assert len(committed) == 1                          # the late release commits nothing more


def test_a_nudge_the_plot_was_reloaded_under_is_not_committed():
    """An undo can reload or clear the plot while a key is held; the release must not commit points
    that belonged to the profile before."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 12.0, -3.0)
    key(w, Qt.Key.Key_Up, release=False)
    w.set_profile([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    w.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier))
    assert committed == []


def test_the_arrow_keys_are_ignored_in_a_read_only_plot_and_for_other_keys():
    w = widget_with([(0.0, 10.0), (15.0, 11.0), (30.0, 12.0)], kind=Kind.LONG)
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, 15.0, 11.0)
    assert key(w, Qt.Key.Key_Delete).isAccepted() is False   # not a nudge key
    w.editable = False
    assert key(w, Qt.Key.Key_Up).isAccepted() is False
    assert w.points[1] == (15.0, 11.0) and committed == []


def test_a_nudge_cannot_push_a_handle_past_its_neighbour():
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (2.05, -1.0)])
    select(w, 2.05, -1.0)
    key(w, Qt.Key.Key_Left)                         # NUDGE is 0.1: further left than the neighbour
    assert w.points[1][0] < w.points[2][0]


def test_a_plot_without_break_points_refuses_to_add_or_remove_them():
    """An area's break points are discarded by the engine (spec 5.4), so the plot must not
    pretend to take them."""
    points = [(0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)]
    w = widget_with(points, allow_breaks=False)
    committed = []
    w.profileCommitted.connect(committed.append)
    target = w._to_screen(5.0, 1.0)
    press(w, target.x(), target.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 4 and committed == []           # nothing added
    handle = w._to_screen(3.0, 0.5)
    press(w, handle.x(), handle.y(), button=Qt.MouseButton.RightButton)
    assert len(w.points) == 4 and committed == []           # nothing removed
    # the terminal slope is still draggable: only the break points are off limits
    start = w._to_screen(8.0, 2.0)
    press(w, start.x(), start.y())
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseMove)
    press(w, start.x(), start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert len(committed) == 1 and w.points[3][1] > 2.0


def test_clearing_the_plot_mid_drag_ends_the_drag():
    """Ctrl+Z during a drag can remove the shown feature, which clears the plot under the mouse.
    The next mouse move and release happen inside Qt, where an IndexError would abort QGIS."""
    w = widget_with([(0.0, 0.0), (2.0, 0.0), (12.0, -3.0)])
    committed = []
    w.profileCommitted.connect(committed.append)
    start = w._to_screen(2.0, 0.0)
    press(w, start.x(), start.y())
    assert w._dragging == 1
    w.clear()
    assert w._dragging == -1 and w._before is None
    press(w, start.x() + 20, start.y() - 20, kind=QEvent.Type.MouseMove)
    press(w, start.x() + 20, start.y() - 20, kind=QEvent.Type.MouseButtonRelease)
    assert w.points == [] and committed == []


def whole(width=4.0, left=(), right=((12.0, -3.0),)):
    """A mirrored plot: left-side points (negative), the two crest edges, right-side points."""
    edge = width / 2.0
    points = [*left, (-edge, 0.0), (edge, 0.0), *right]
    return widget_with(points, mirrored=True)


def drag(widget, x, z, to_x, to_z):
    start, end = widget._to_screen(x, z), widget._to_screen(to_x, to_z)
    press(widget, start.x(), start.y())
    press(widget, end.x(), end.y(), kind=QEvent.Type.MouseMove)
    press(widget, end.x(), end.y(), kind=QEvent.Type.MouseButtonRelease)


def test_the_two_crest_edges_move_together():
    w = whole(left=((-12.0, -3.0),))
    drag(w, 2.0, 0.0, 3.0, 0.0)
    assert w.points[1][0] == pytest.approx(-w.points[2][0]) and w.points[2][0] == pytest.approx(3.0, abs=0.1)
    assert w.points[1][1] == w.points[2][1] == 0.0                # the crest stays level


def test_the_crest_stays_level_while_an_edge_is_dragged_or_nudged():
    w = whole(left=((-12.0, -3.0),))
    drag(w, 2.0, 0.0, 3.0, 1.5)                                   # dragged up and out
    assert w.points[1][1] == w.points[2][1] == 0.0
    committed = []
    w.profileCommitted.connect(committed.append)
    select(w, *w.points[2])
    key(w, Qt.Key.Key_Up)
    assert w.points[2][1] == 0.0 and committed == []               # nothing to commit


def test_no_handle_crosses_the_centre_line():
    w = whole(left=((-12.0, -3.0),))
    drag(w, -2.0, 0.0, 5.0, 0.0)                                  # the left edge dragged far to the right
    assert w.points[1][0] < 0.0 < w.points[2][0]
    assert w.points[2][0] <= 12.0


def test_with_symmetric_on_a_handle_takes_its_mirror_image_along():
    w = whole(left=((-12.0, -3.0),))
    w.symmetric = True
    drag(w, 12.0, -3.0, 14.0, -4.0)
    assert w.points[0][0] == pytest.approx(-w.points[3][0]) and w.points[0][1] == pytest.approx(w.points[3][1])
    w.symmetric = False
    drag(w, 14.0, w.points[3][1], 10.0, -2.0)
    assert w.points[0][0] != pytest.approx(-w.points[3][0])       # off: only the dragged side moves


def test_a_handle_without_a_mirror_image_moves_alone_even_when_symmetric():
    w = whole(left=((-12.0, -3.0),), right=((6.0, -1.0), (12.0, -3.0)))
    w.symmetric = True
    before = list(w.points)
    drag(w, 6.0, -1.0, 7.0, -1.5)
    assert w.points[:3] == before[:3]


def test_the_arrow_keys_move_both_crest_edges():
    w = whole(left=((-12.0, -3.0),))
    select(w, 2.0, 0.0)
    key(w, Qt.Key.Key_Right)
    assert w.points[2][0] == pytest.approx(2.0 + NUDGE) and w.points[1][0] == pytest.approx(-2.0 - NUDGE)


def test_the_crest_edges_cannot_be_removed_and_nothing_is_added_on_the_crest():
    w = whole(left=((-12.0, -3.0),))
    committed = []
    w.profileCommitted.connect(committed.append)
    edge = w._to_screen(2.0, 0.0)
    press(w, edge.x(), edge.y(), button=Qt.MouseButton.RightButton)
    crest = w._to_screen(0.5, 0.0)
    press(w, crest.x(), crest.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 4 and committed == []
    slope = w._to_screen(7.0, -1.5)
    press(w, slope.x(), slope.y(), kind=QEvent.Type.MouseButtonDblClick)
    assert len(w.points) == 5 and len(committed) == 1              # a berm on a slope is fine
```

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
from terrain_sketch.gui.profile_dock import ProfileDock


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


def test_each_drag_in_the_profiles_panel_is_its_own_profile_step(tmp_path):
    """The panel's cross-profile drags also move width, slope and reach, which alone count as
    settings; they must still be one named profile step each, never merged."""
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    start = c.undo_stack.index()
    dock._cross_edited([(-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0)], True)
    after_first = c.find(dike.id)
    dock._cross_edited([(-7.0, -1.2), (-2.5, 0.0), (2.5, 0.0), (7.0, -1.2)], True)
    assert c.undo_stack.index() == start + 2
    assert c.undo_stack.undoText() == UNDO_PROFILE.format(dike.name)
    c.undo_stack.undo()
    assert c.find(dike.id) == after_first               # one drag back, not both

    dock.show_feature(pond.id)                          # an area drag sends only slope and reach
    dock._cross_edited([(0.0, 0.0), (0.5, 0.0), (4.0, 1.0)], True)
    assert c.undo_stack.undoText() == UNDO_PROFILE.format(pond.name)


def test_the_profile_reset_buttons_are_profile_steps(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.update_feature(dike.id, cross_right=((3.0, -0.6),), long_profile=((0.0, 12.0), (29.0, 13.0)))
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    start = c.undo_stack.index()
    dock._reset_cross()
    assert c.undo_stack.undoText() == UNDO_PROFILE.format(dike.name)
    dock._reset_long()
    assert c.undo_stack.index() == start + 2 and c.undo_stack.undoText() == UNDO_PROFILE.format(dike.name)


def test_an_undo_the_engine_refuses_leaves_the_scenario_unsaved(tmp_path):
    from unittest import mock
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "saved.gpkg"))
    c.update_feature(dike.id, amount=2.0)
    with mock.patch.object(c.stack, "update", side_effect=MemoryError("no room")):
        c.undo_stack.undo()                             # lands on the saved step, list unchanged
    assert c.find(dike.id).amount == 2.0
    assert c.is_dirty                                   # still the unsaved change on screen


def test_an_emptied_scenario_that_was_never_saved_has_nothing_to_keep(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    c.delete_feature(dike.id)
    c.delete_feature(pond.id)
    assert not c.is_dirty and c.undo_stack.canUndo()


def test_a_change_that_changes_nothing_still_refreshes_the_views(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    heard = []
    c.featuresChanged.connect(lambda: heard.append(True))
    c.update_feature(dike.id, amount=dike.amount)
    assert heard == [True]


def test_an_add_the_engine_refuses_returns_nothing_and_leaves_no_work(tmp_path):
    from unittest import mock
    c = start_session(tmp_path)
    with mock.patch.object(c.stack, "update", side_effect=RuntimeError("refused")):
        assert c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM) is None
    assert c.features == () and not c.is_dirty and not c.undo_stack.canUndo()


def test_stepping_a_setting_back_after_a_save_is_clean_again(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "saved.gpkg"))
    c.update_feature(dike.id, amount=2.0)
    c.update_feature(dike.id, amount=1.0)
    assert not c.is_dirty
```
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/core/test_sections.py`
Expected: collection error `ImportError: cannot import name 'set_whole_cross_section' from 'terrain_sketch.core.sections'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/core/operations.py`
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
    dz = np.where(left, dz_l, dz_r)
    # Past an end cap, a cell exactly on the extended axis belongs to neither side. It takes whichever
    # side the combine rule would keep, as if both side shapes were built there, instead of always the
    # right-hand one — a visible step when the two sides differ.
    length = float(vertex_stations(coords)[-1])
    # (the stations and the length are summed in different ways, so the far end can be one bit short)
    axis = (offset == 0.0) & ~core & ((station <= 0.0) | (station >= length - 1e-9))
    if axis.any():
        keep = np.maximum if info.combine is Combine.MAX else np.minimum
        unused = -np.inf if info.combine is Combine.MAX else np.inf
        both = keep(np.where(ext_l, dz_l, unused), np.where(ext_r, dz_r, unused))
        dz = np.where(axis & (ext_l | ext_r), both, dz)
        in_extent = np.where(axis, ext_l | ext_r, in_extent)
    dz = np.where(core, 0.0, dz)
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

Replace the whole file:

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
SAME = 1e-4   # values are written back at four decimals, so closer than this is the same value


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
    sorted_breaks = sorted(breaks, key=lambda b: b[0])
    for distance, dz in sorted_breaks:
        points.append((edge + float(distance), float(dz)))
    if limit > (sorted_breaks[-1][0] if sorted_breaks else 0.0):
        dz, _in_extent = side_dz(np.array([limit]), sorted_breaks, feature.slope_n, feature.reach,
                                 info.direction)
        points.append((edge + limit, float(dz[0])))
    return tuple(points)


def set_cross_section(feature, side: int, points) -> dict:
    """Turn edited cross-section points back into feature fields.

    `points` are ((distance from the centre line, dz), ...) as `cross_section` returns them.
    The first interior point sets the width; the rest become break points relative to the
    corridor edge; the last segment's run over rise sets the side slope.
    """
    pts = sorted([(float(d), float(z)) for d, z in points if float(d) >= 0.0], key=lambda p: p[0])
    if len(pts) < 2:
        raise ValueError("a cross section needs at least a centre and an edge point")
    edge = pts[1][0]
    changes: dict = {}
    # Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    # break list to `side_dz`, so writing them here would store a value the engine discards.
    breaks_key = ("cross_right" if side >= 0 else "cross_left") if feature.mode is Mode.PATH else None
    if feature.mode is Mode.PATH:
        changes["width"] = max(2.0 * edge, 0.1)

    # The final point is the slope's end only if the plot drew one: `cross_section` adds it when the
    # reach goes past the last break. With breaks beyond the reach there is none, and reading the last
    # break as the slope's end would rewrite the slope and the reach and drop that break.
    has_terminal_slope = feature.slope_n > 0.0
    last_break_distance = pts[-2][0] if len(pts) > 2 else edge
    stored = feature.cross_right if side >= 0 else feature.cross_left
    drew_terminus = side_limit(stored, feature.slope_n, feature.reach) > max([0.0] + [float(d) for d, _ in stored])
    last_point_is_terminus = has_terminal_slope and drew_terminus and pts[-1][0] > last_break_distance

    if has_terminal_slope and not drew_terminus:
        # every point after the edge is a break; the slope and its reach are not on the plot to change
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in pts[2:] if d > edge)
    elif last_point_is_terminus:
        interior, last = pts[2:-1], pts[-1]
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in interior)
        run = last[0] - (interior[-1][0] if interior else edge)
        rise = abs(last[1] - (interior[-1][1] if interior else 0.0))
        changes["slope_n"] = _slope_n(run, rise, feature.slope_n)
        changes["reach"] = _reach(last[0] - edge, feature.reach)
    else:
        # No terminal slope: all points after edge are breaks. Derive slope_n and reach.
        # Filter out breaks at distance 0 (at the edge itself) and collapse duplicates.
        interior = [(d, z) for d, z in pts[2:] if d > edge]

        # Collapse duplicate distances: keep the later (rightmost) value
        seen_distances = {}
        for d, z in interior:
            seen_distances[d] = z

        deduplicated = sorted(seen_distances.items())
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in deduplicated)
        changes["slope_n"] = 0.0
        changes["reach"] = 0.0 if not deduplicated else feature.reach

    return changes


def whole_cross_section(feature) -> tuple:
    """A path's cross profile across both sides, as a surveyor draws it: ((offset, dz), ...) from the
    end of the left slope to the end of the right one, left of the centre line at negative offsets.
    Left and right are as seen looking along the path in the direction it was drawn."""
    left = cross_section(feature, side=-1)[1:]
    right = cross_section(feature, side=1)[1:]
    return tuple((-x, z) for x, z in reversed(left)) + right


def set_whole_cross_section(feature, points, symmetric: bool = False) -> dict:
    """Turn an edited whole cross profile back into feature fields.

    Each side is read the way `set_cross_section` reads one, but a side whose points are still the ones
    the plot was given is left as the feature has it: reading it back could only add rounding. Width,
    side slope and reach are single values shared by both sides, so each is taken from the side where it
    changed (the right when both did). With `symmetric`, the break points of the side that was edited
    are copied to the other side."""
    pts = [(float(x), float(z)) for x, z in points]
    sides = {}
    for side, key, own in ((1, "cross_right", sorted(p for p in pts if p[0] > 0.0)),
                           (-1, "cross_left", sorted((-x, z) for x, z in pts if x < 0.0))):
        if _same_points(own, cross_section(feature, side=side)[1:]):
            sides[key] = {}
        else:
            sides[key] = set_cross_section(feature, side, [(0.0, 0.0)] + own)
    changes = {key: read.get(key, getattr(feature, key)) for key, read in sides.items()}
    for key in ("width", "slope_n", "reach"):
        current = getattr(feature, key)
        left, right = sides["cross_left"].get(key, current), sides["cross_right"].get(key, current)
        changes[key] = left if abs(left - current) > SAME and abs(right - current) <= SAME else right
    if symmetric:
        if _same_points(changes["cross_right"], feature.cross_right) \
                and not _same_points(changes["cross_left"], feature.cross_left):
            changes["cross_right"] = changes["cross_left"]
        else:
            changes["cross_left"] = changes["cross_right"]
    return changes


def _same_points(a, b) -> bool:
    """Whether two break lists are equal to within the rounding a round trip through the plot adds."""
    return len(a) == len(b) and all(abs(ax - bx) <= SAME and abs(az - bz) <= SAME
                                    for (ax, az), (bx, bz) in zip(a, b))


def _slope_n(run: float, rise: float, current: float) -> float:
    """The terminal slope 1:n from a run over a rise, rounded to the stored four decimals.

    0.0 is the "no terminal slope" sentinel, so a run too small to round to a non-zero n — a
    terminus dragged hard against its neighbour — keeps the slope the feature already has
    rather than silently losing it. There is no undo.
    """
    if rise <= 1e-9:
        return 0.0
    rounded = round(run / rise, 4)
    return rounded if rounded > 0.0 else current


def _reach(distance: float, current: float) -> float:
    """The slope's reach from the terminus's distance beyond the edge, rounded like the slope.

    A reach of 0.0 stops the slope at the edge, so a terminus dragged hard against the edge rounds to
    nothing only by accident — the same drag `_slope_n` guards against — and keeps the reach it had."""
    rounded = round(distance, 4)
    return rounded if rounded > 0.0 else current


def section_part(feature):
    """The part a long section runs along: for a multi-part path, the longest one."""
    geometry_parts = [p for p in split_parts(feature.geometry_wkb) if is_line(p)]
    if feature.mode is not Mode.PATH or not geometry_parts:
        return None
    return max(geometry_parts, key=lambda p: _length(line_coords(p)))


def supports_long_profile(feature) -> bool:
    """Whether a custom long profile would actually drive this feature's terrain.

    `operations.apply_feature` uses one only for a single-part path (spec 5.4), so for anything
    else the editor must not offer one: it would be stored, shown as custom and then discarded,
    while the Height/Depth that does drive the result sits disabled.
    """
    if feature.mode is not Mode.PATH:
        return False
    try:
        return len(split_parts(feature.geometry_wkb)) == 1
    except ValueError:
        return False


def long_section(feature, grid: DemGrid, terrain: DemGrid | None = None) -> dict:
    """Reference terrain and design line along the feature's centre line.

    Returns `{"stations", "terrain", "design", "custom"}`: stations in metres from the start,
    terrain sampled on `terrain` (the state just before this feature) and the design line
    either from the feature's custom long profile or regenerated from the tool rule.

    `custom` is False whenever the engine would ignore the stored profile — a multi-part path —
    so the editor never presents a line the terrain does not follow.
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
    if feature.long_profile is not None and supports_long_profile(feature):
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

Replace the whole file:

**File:** `terrain_sketch/core/stations.py`
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
    distance to it (positive right of the direction of travel, negative left). A point on the line
    through its nearest segment — on the path, or straight ahead past one of its ends — is on neither
    side and gets 0."""
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
        side = np.where(better, np.sign(-cross), side)
        cum += length
    return station, side * np.sqrt(best)
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
EXPORT_ADD_FAILED = ("The exported DEM {} could not be added to the project; see the 'Terrain Sketch' log tab "
                     "for details.")

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

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It is the project's terrain, but only a temporary one, "
               "even if you save the project meanwhile: the terrain you had before is put back when this "
               "session ends.")
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
CROSS_SIDES_TIP = ("A section across the path, looking along it in the direction it was drawn: its left side "
                   "on the left. Drag the crest edges to change the width, and the ends of the slopes to change "
                   "their steepness and reach; double-click to add a break point, such as a berm, and "
                   "right-click to remove one.")
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

**File:** `terrain_sketch/gui/profile_dock.py`
```python
"""Bottom dock: the cross profile and the long profile of the selected feature, side by side."""
from __future__ import annotations

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                                 QWidget)

from ..core.sections import (cross_section, set_cross_section, set_whole_cross_section, supports_long_profile,
                             whole_cross_section)
from ..core.tools import TOOL_INFO, Mode
from .help_texts import (AREA_LONG_SECTION_HINT, AREA_LONG_SECTION_NOTE, CROSS_SIDES_TIP, CUSTOM_PROFILE_NOTE,
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
        self.cross.symmetric = True
        self.symmetric.toggled.connect(self._symmetric_toggled)
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
            self.cross.setToolTip("")
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
            self.cross.setToolTip(CROSS_SIDES_TIP if is_path and info.has_slopes else "")   # it is about sides
            # A path shows both sides around its centre line; an area shows its one edge slope, and
            # takes no break points: the engine discards an area's (spec 5.4).
            if is_path:
                self.cross.set_profile(whole_cross_section(feature), editable=info.has_slopes, mirrored=True)
            else:
                self.cross.set_profile(cross_section(feature, side=1), editable=info.has_slopes,
                                       allow_breaks=False)
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
        try:
            if feature.mode is Mode.PATH:
                changes = set_whole_cross_section(feature, points, symmetric=self.symmetric.isChecked())
            else:
                changes = set_cross_section(feature, 1, points)
        except ValueError:
            return            # a side without its crest edge; the plot never sends one, and this is a slot
        self._apply(changes, commit)

    def _long_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        self._apply({"long_profile": tuple((float(s), float(z)) for s, z in points)}, commit)

    def _apply(self, changes: dict, commit: bool) -> None:
        if commit:
            self.controller.update_profile(self._fid, **changes)
        else:
            self.controller.preview(self._fid, **changes)

    def _reset_cross(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, cross_left=(), cross_right=())

    def _reset_long(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, long_profile=None)

    def _symmetric_toggled(self, checked: bool) -> None:
        self.cross.symmetric = checked

    def _session_changed(self) -> None:
        if not self.controller.has_dem:
            self.show_feature(None)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.symmetric, self.reset_cross, self.reset_long):
            widget.setEnabled(enabled)

    def shutdown(self) -> None:
        self.controller.cancel_preview()
```

Replace the whole file:

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
from .overlay import CUT, FILL

MARGIN_LEFT, MARGIN_BOTTOM, MARGIN_TOP, MARGIN_RIGHT = 46, 26, 10, 12
SHADE_ALPHA = 70        # the plot shades the same change as the map overlay, but behind the lines
GRAB_PIXELS = 8
HANDLE_RADIUS = 4
NUDGE, NUDGE_FINE = 0.1, 0.01
NUDGE_KEYS = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right)
MIN_HALF_WIDTH = 0.05   # the narrowest corridor a path takes is 0.1 m


class Kind(Enum):
    CROSS = "cross"
    LONG = "long"


class ProfileWidget(QWidget):
    """Draws the reference terrain, the design line and draggable handles.

    Dragging emits `profileChanged` continuously and `profileCommitted` on release, both with
    the full point list. The arrow keys work the same way: each press (and each auto-repeat while a
    key is held) emits `profileChanged`, and letting go of the key commits once. The widget owns no
    feature state: whoever drives it sets points and applies the edits.

    A `mirrored` cross profile shows both sides of a path around a centre line at 0: no handle crosses
    it, the two crest edges move together (a path's width is one value), and while `symmetric` is set
    every handle that has a mirror image on the other side takes it along.
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
        self.allow_breaks = True
        self.mirrored = False
        self.symmetric = False
        self.hint = PROFILE_EMPTY_HINT
        self.selected = -1
        self._dragging = -1
        self._before: list | None = None
        self._nudge_before: list | None = None   # the points before the arrow key now held
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    # ---- contents -------------------------------------------------------------------

    def set_profile(self, points, terrain=(), editable=True, allow_breaks=True,
                    hint: str = PROFILE_EMPTY_HINT, mirrored: bool = False) -> None:
        """Show `points` over `terrain`.

        `allow_breaks` is False when the engine does not use break points for this feature, so
        the plot must refuse to add or remove them; `hint` is what an empty plot says instead of
        the default "select a feature". The widget knows nothing about features: the dock, which
        does, sets both.
        """
        self.points = [(float(x), float(z)) for x, z in points]
        self.terrain = [(float(x), float(z)) for x, z in terrain]
        self.editable = editable
        self.allow_breaks = allow_breaks
        self.mirrored = mirrored
        self.hint = hint
        self.selected = -1
        self._dragging = -1
        self._nudge_before = None
        self.update()

    def clear(self, hint: str = PROFILE_EMPTY_HINT) -> None:
        self.points, self.terrain, self.hint, self.selected = [], [], hint, -1
        self._dragging, self._before = -1, None   # an undo can clear the plot under a drag
        self._nudge_before = None
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
        if self.mirrored:
            self._draw_sides(painter, palette)

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
        """Fill above the reference in warm, cut below it in cool — the drag preview's colours.

        These are the overlay's FILL and CUT, so the plot and the map agree while a handle is
        dragged. The committed change layer has a ramp of its own (`qgis_io/layers.py`).
        """
        reference = self._resampled_terrain()
        if reference is None:
            return
        for colour, above in ((QColor(*FILL, SHADE_ALPHA), True), (QColor(*CUT, SHADE_ALPHA), False)):
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

    def _draw_sides(self, painter, palette) -> None:
        """Say which side is which, and mark the centre line the two sides are measured from."""
        plot = self._plot_rect()
        centre = self._to_screen(0.0, self._z_range()[0]).x()
        painter.setPen(QPen(palette.mid().color(), 1, Qt.PenStyle.DashDotLine))
        painter.drawLine(QPointF(centre, plot.top()), QPointF(centre, plot.bottom()))
        painter.setPen(palette.windowText().color())
        label = plot.adjusted(4, 2, -4, 0)
        painter.drawText(label, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.tr("Left"))
        painter.drawText(label, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, self.tr("Right"))

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
            if self.allow_breaks and 0 < index < len(self.points) - 1 and index not in self._edges():
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
        if not 0 <= self._dragging < len(self.points):
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
        if not self.editable or not self.allow_breaks or event.button() != Qt.MouseButton.LeftButton:
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
        if not 0 <= self.selected < len(self.points) or not self.editable or event.key() not in deltas:
            event.ignore()
            return
        if self._nudge_before is None:
            self._nudge_before = list(self.points)
        dx, dz = deltas[event.key()]
        x, z = self.points[self.selected]
        self._move_handle(self.selected, (x + dx, z + dz))
        self.profileChanged.emit(tuple(self.points))
        event.accept()

    def keyReleaseEvent(self, event):  # noqa: N802 — Qt override
        """Commit a nudge when its key is let go. A held key sends a release with every auto-repeat
        too, so those are skipped: a second of holding Up is one change, not thirty."""
        if event.key() not in NUDGE_KEYS or event.isAutoRepeat():
            event.ignore()
            return
        self._commit_nudge()
        event.accept()

    def focusOutEvent(self, event):  # noqa: N802 — Qt override
        self._commit_nudge()   # the release never comes to a plot that lost focus while a key was held
        super().focusOutEvent(event)

    def _commit_nudge(self) -> None:
        before, self._nudge_before = self._nudge_before, None
        if before is not None and before != self.points:
            self.profileCommitted.emit(tuple(self.points))

    def _move_handle(self, index: int, position) -> None:
        x, z = position
        partner = self._partner(index)
        if not self._can_move_x(index):
            x = self.points[index][0]
        else:
            x = self._clamp_x(index, x)
            if partner is not None:
                x = -self._clamp_x(partner, -x)   # the mirror image must fit between its own neighbours too
            if self.mirrored:
                x = min(x, -MIN_HALF_WIDTH) if self.points[index][0] < 0.0 else max(x, MIN_HALF_WIDTH)
            elif self.kind is Kind.CROSS:
                x = max(x, 0.0)
        if index in self._edges():
            z = self.points[index][1]           # the crest stays level: its edges only move sideways
        if partner is not None:
            self.points[partner] = (-x, z)
        self.points[index] = (x, z)
        self.update()

    def _clamp_x(self, index: int, x: float) -> float:
        if index > 0:
            x = max(x, self.points[index - 1][0] + 1e-6)
        if index < len(self.points) - 1:
            x = min(x, self.points[index + 1][0] - 1e-6)
        return x

    def _edges(self) -> tuple:
        """Indexes of the two crest edges of a mirrored profile: the handles either side of the centre."""
        if not self.mirrored:
            return ()
        right = next((i for i, (x, _z) in enumerate(self.points) if x > 0.0), None)
        return (right - 1, right) if right else ()

    def _partner(self, index: int):
        """The handle that moves with `index`: the other crest edge, or — while `symmetric` — the
        mirror image of any handle that has one."""
        edges = self._edges()
        if index in edges:
            return edges[1] if index == edges[0] else edges[0]
        mirror = len(self.points) - 1 - index
        if self.symmetric and edges and mirror != index and _mirrors(self.points[index], self.points[mirror]):
            return mirror
        return None

    def _can_move_x(self, index: int) -> bool:
        """The first point is pinned (the centre of a one-sided cross profile, the start of a long
        section); in a long section the last one is too (it is the end). A mirrored profile has no
        pinned point: its outer handles are the ends of the slopes."""
        if self.mirrored:
            return True
        if index == 0:
            return False
        return not (self.kind is Kind.LONG and index == len(self.points) - 1)

    def _insertion_index(self, x: float):
        edges = self._edges()
        for index in range(1, len(self.points)):
            if self.points[index - 1][0] < x < self.points[index][0]:
                return None if edges and index == edges[1] else index   # never on the crest itself
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


def _mirrors(a, b) -> bool:
    return abs(a[0] + b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


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

Run: `scripts/test.sh tests/core/test_operations.py tests/core/test_sections.py tests/qgis/test_profile_dock.py tests/qgis/test_profile_widget.py tests/qgis/test_undo.py` → Expected: `126 passed`
Run: `scripts/test.sh` → Expected: `487 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/core/operations.py terrain_sketch/core/sections.py terrain_sketch/core/stations.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/profile_dock.py terrain_sketch/gui/profile_widget.py tests/core/test_operations.py tests/core/test_sections.py tests/qgis/test_profile_dock.py tests/qgis/test_profile_widget.py tests/qgis/test_undo.py
git commit -m "feat(gui): the cross profile shows and edits both sides of a path"
```

---

### Task 4: A section through an area

**Files:**
- Modify: `terrain_sketch/core/engine.py`, `terrain_sketch/core/sections.py`, `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/profile_dock.py`, `terrain_sketch/model/feature.py`, `terrain_sketch/qgis_io/scenario.py`
- Test: `tests/core/test_feature.py`, `tests/core/test_sections.py`, `tests/qgis/test_profile_dock.py`, `tests/qgis/test_scenario_file.py`

**Interfaces:**
- Consumes: `FeatureStack.terrain_before`, `closure`, `footprint`; `sections._walk`, `_length`, `SAMPLES`; `geometry.split_parts`, `polygon_rings`, `line_wkb`; `SketchController.long_section`; `ProfileDock._refresh`.
- Produces: `TerrainFeature.section_line: bytes | None`; `FeatureStack.terrain_around(fid, window=None, features=None) -> (Window, DemGrid, DemGrid) | None`; `sections.default_section_line(feature, cell_size) -> bytes | None`, `section_along(line, before, after) -> dict`; `SketchController.area_section(fid) -> {"stations", "before", "after", "line"}`, `EMPTY_AREA_SECTION`, `_line_window`; `help_texts.AREA_SECTION_EMPTY_HINT`, `AREA_SECTION_NOTE` (replacing `AREA_LONG_SECTION_HINT` and `AREA_LONG_SECTION_NOTE`); `ProfileDock._show_area_section()`, `_show_long_section(feature)`.

- [ ] **Step 1: Write the failing tests**

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
    pond = TerrainFeature(id="b", name="Pond", tool=Tool.LOWER_FLAT, mode=Mode.AREA, geometry_wkb=TRIANGLE,
                          section_line=line_wkb([(-1, 0.5), (2, 0.5)]))
    assert TerrainFeature.from_dict(json.loads(json.dumps(pond.to_dict()))) == pond


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

**File:** `tests/core/test_sections.py`
```python
from dataclasses import replace

import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, multi_wkb, polygon_wkb
from terrain_sketch.core.sections import (cross_section, default_section_line, long_section, section_along,
                                          set_cross_section, set_whole_cross_section, supports_long_profile,
                                          whole_cross_section)
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


def test_a_feature_with_no_terminal_slope_and_multiple_breaks_survives_a_round_trip():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0), (6.0, -2.0))
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(10.0)


def test_an_unsorted_break_list_produces_a_non_decreasing_distance_sequence():
    f = dike(width=4.0, slope_n=2.0, reach=20.0, cross_right=((6.0, -2.0), (3.0, -1.0)))
    points = cross_section(f)
    distances = [d for d, z in points]
    assert distances == sorted(distances)


def test_an_ordinary_round_trip_with_one_break_and_a_slope_remains_unchanged():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(4.0)
    assert changes["cross_right"] == ((3.0, -1.0),)
    assert changes["slope_n"] == pytest.approx(3.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_deleting_the_terminal_slope_yields_zero_slope_and_reach():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0)])
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)
    assert changes["cross_right"] == ()


def test_a_terminus_dragged_onto_the_edge_produces_no_break_at_distance_zero():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.0, -0.5)])
    assert changes["cross_right"] == ()
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(0.0)


def test_a_terminus_dragged_onto_the_last_break_produces_one_break_not_two():
    f = dike(width=4.0, slope_n=3.0, reach=20.0, cross_right=((3.0, -1.0),))
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (5.0, -1.0), (5.0, -1.5)])
    assert changes["cross_right"] == ((3.0, -1.5),)
    assert changes["slope_n"] == pytest.approx(0.0)
    assert changes["reach"] == pytest.approx(20.0)


def test_an_identity_round_trip_through_the_no_terminus_branch_changes_nothing():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0), (6.0, -2.0)))
    points = cross_section(f)
    changes = set_cross_section(f, 1, points)
    assert changes["width"] == pytest.approx(f.width)
    assert changes["cross_right"] == f.cross_right
    assert changes["slope_n"] == pytest.approx(f.slope_n)
    assert changes["reach"] == pytest.approx(f.reach)


def two_part_dike(**kw):
    """A RAISE_PATH whose geometry has two separate line parts."""
    return feature(Tool.RAISE_PATH, Mode.PATH,
                   multi_wkb([line_wkb([(5, 20), (15, 20)]), line_wkb([(25, 20), (35, 20)])]), **kw)


def test_a_multi_part_path_does_not_support_a_custom_long_profile():
    assert supports_long_profile(dike())
    assert not supports_long_profile(two_part_dike())
    pond = feature(Tool.LOWER_FLAT, Mode.AREA,
                   polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]))
    assert not supports_long_profile(pond)


def test_a_multi_part_path_reports_the_rule_line_not_the_stored_custom_profile():
    """The engine applies a long profile only to a single-part path, so reporting one here
    would show the user a design line their terrain does not follow."""
    stored = ((0.0, 20.0), (10.0, 20.0))
    section = long_section(two_part_dike(amount=2.0, long_profile=stored), make_grid(tilted))
    assert not section["custom"]
    assert section["design"] != stored
    # the rule line: the terrain under the longest part plus the height
    assert section["design"][0][1] == pytest.approx(section["terrain"][0] + 2.0, abs=0.1)


def test_an_areas_cross_section_edit_writes_no_break_points():
    """Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    break list to `side_dz`, so storing them would keep a value the engine silently discards."""
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 10), (20, 10), (20, 20), (10, 20)]),
                   slope_n=2.0, reach=6.0, amount=1.0)
    changes = set_cross_section(pond, 1, [(0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)])
    assert "cross_right" not in changes and "cross_left" not in changes
    assert "width" not in changes                       # an area has no corridor either
    assert changes["slope_n"] == pytest.approx(3.3333)  # 5 m run over 1.5 m rise
    assert changes["reach"] == pytest.approx(8.0)


def test_a_terminus_dragged_hard_against_its_neighbour_keeps_the_side_slope():
    """`_move_handle` clamps a dragged handle to neighbour + 1e-6, and a run that small rounds
    to 0.0 — the "no terminal slope" sentinel. There is no undo, so the slope is kept."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.000001, -3.0)])
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_terminus_dragged_hard_against_the_edge_keeps_its_reach():
    """A reach that rounds to 0.0 stops the slope at the edge — the slope kept by the test above
    would then change nothing."""
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (2.00001, -3.0)])
    assert changes["reach"] == pytest.approx(20.0)
    assert changes["slope_n"] == pytest.approx(3.0)


def test_a_real_but_very_flat_slope_is_still_written():
    f = dike(width=4.0, slope_n=3.0, reach=20.0)
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (22.0, -0.5)])
    assert changes["slope_n"] == pytest.approx(40.0)


def test_the_whole_cross_section_runs_from_the_left_slope_to_the_right_one():
    f = dike(width=4.0, slope_n=2.0, reach=10.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5),))
    points = whole_cross_section(f)
    assert points[0][0] == pytest.approx(-12.0) and points[-1][0] == pytest.approx(12.0)
    assert (-4.0, -0.5) in points and (-2.0, 0.0) in points and (2.0, 0.0) in points and (6.0, -1.5) in points
    assert [x for x, _z in points] == sorted(x for x, _z in points)
    assert not any(x == 0.0 for x, _z in points)                # no centre handle: the crest runs across it


def test_an_untouched_whole_section_writes_back_what_the_feature_has():
    f = dike(width=4.5, slope_n=2.5, reach=12.0, cross_left=((2.0, -0.5),), cross_right=((4.0, -1.5), (6.0, -1.6)))
    changes = set_whole_cross_section(f, whole_cross_section(f))
    assert changes["width"] == pytest.approx(4.5)
    assert changes["slope_n"] == pytest.approx(2.5) and changes["reach"] == pytest.approx(12.0)
    for side in ("cross_left", "cross_right"):
        assert len(changes[side]) == len(getattr(f, side))
        for written, stored in zip(changes[side], getattr(f, side)):
            assert written == pytest.approx(stored)


def test_a_left_side_edit_changes_the_left_side_and_the_shared_slope():
    f = dike(width=4.0, slope_n=3.0, reach=10.0)
    points = list(whole_cross_section(f))
    points[0] = (-14.0, -4.0)                                   # the left slope's end: 12 m out, 4 m down
    changes = set_whole_cross_section(f, points)
    assert changes["reach"] == pytest.approx(12.0) and changes["slope_n"] == pytest.approx(3.0)
    assert changes["cross_left"] == () and changes["cross_right"] == ()


def test_symmetric_copies_the_edited_side_whichever_side_it_is():
    f = dike(width=4.0, slope_n=3.0, reach=10.0)
    left_berm = [(-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (12.0, -10.0 / 3.0)]
    assert set_whole_cross_section(f, left_berm, symmetric=True)["cross_right"] == ((4.0, -1.0),)
    right_berm = [(-12.0, -10.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)]
    assert set_whole_cross_section(f, right_berm, symmetric=True)["cross_left"] == ((4.0, -1.0),)
    unticked = set_whole_cross_section(f, left_berm, symmetric=False)
    assert unticked["cross_left"] == ((4.0, -1.0),) and unticked["cross_right"] == ()


def test_editing_one_side_leaves_a_side_with_breaks_past_its_reach_as_it_was():
    """A berm beyond the reach leaves that side without a slope-end handle. Reading its last berm as the
    slope's end rewrote the slope and the reach and dropped the berm while the user edited the other side."""
    f = dike(width=4.0, slope_n=3.0, reach=5.0, cross_right=((2.0, -0.5), (8.0, -1.0)))
    points = list(whole_cross_section(f))
    assert points[-1] == (10.0, -1.0)                               # the berm is the last handle
    points[0] = (-10.0, -8.0 / 3.0)                                 # the left slope's end, 3 m further out
    changes = set_whole_cross_section(f, points)
    assert changes["cross_right"] == f.cross_right and changes["cross_left"] == ()
    assert changes["slope_n"] == pytest.approx(3.0) and changes["reach"] == pytest.approx(8.0)


def test_a_side_whose_breaks_run_past_its_reach_keeps_its_slope_when_edited():
    f = dike(width=4.0, slope_n=3.0, reach=5.0, cross_right=((2.0, -0.5), (8.0, -1.0)))
    changes = set_cross_section(f, 1, [(0.0, 0.0), (2.0, 0.0), (4.0, -0.5), (10.0, -1.4)])
    assert changes["cross_right"] == ((2.0, -0.5), (8.0, -1.4))
    assert "slope_n" not in changes and "reach" not in changes


def test_the_side_that_was_not_edited_does_not_change_the_shared_values():
    f = dike(width=4.0, slope_n=0.0, reach=10.0, cross_right=((3.0, -1.0),))
    points = list(whole_cross_section(f))
    points[-1] = (6.0, -1.5)                                        # drag the right berm
    changes = set_whole_cross_section(f, points)
    assert changes["cross_right"] == ((4.0, -1.5),) and changes["reach"] == pytest.approx(10.0)
    # a stored value halfway between two four-decimal numbers still counts as unchanged on the other side
    odd = dike(width=4.0, slope_n=3.0, reach=40.34765)
    moved = list(whole_cross_section(odd))
    moved[0] = (moved[0][0] - 3.0, moved[0][1] - 1.0)
    assert set_whole_cross_section(odd, moved)["reach"] == pytest.approx(43.34765, abs=1e-4)


def rotated_rectangle(length, breadth, degrees, centre=(20.0, 20.0)):
    c, s = np.cos(np.radians(degrees)), np.sin(np.radians(degrees))
    corners = [(-length / 2, -breadth / 2), (length / 2, -breadth / 2), (length / 2, breadth / 2),
               (-length / 2, breadth / 2)]
    return polygon_wkb([(centre[0] + x * c - y * s, centre[1] + x * s + y * c) for x, y in corners])


def line_points(wkb):
    from osgeo import ogr
    return np.array(ogr.CreateGeometryFromWkb(wkb).GetPoints())[:, :2]


def test_the_default_section_runs_through_the_middle_along_the_longer_side():
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, rotated_rectangle(20.0, 6.0, 30.0), slopes_inside=True)
    start, end = line_points(default_section_line(pond, cell_size=1.0))
    direction = (end - start) / np.hypot(*(end - start))
    assert direction == pytest.approx([np.cos(np.radians(30.0)), np.sin(np.radians(30.0))])
    assert (start + end) / 2 == pytest.approx([20.0, 20.0])                 # through the centroid
    assert np.hypot(*(end - start)) == pytest.approx(20.0 + 2 * 5.0)         # past the outline by five cells


def test_the_default_section_reaches_past_outside_slopes_and_runs_west_to_east():
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, rotated_rectangle(20.0, 6.0, 180.0), slope_n=2.0, reach=8.0)
    start, end = line_points(default_section_line(pad, cell_size=1.0))
    assert start[0] < end[0]
    assert np.hypot(*(end - start)) == pytest.approx(20.0 + 2 * (8.0 + 5.0))


def test_a_path_has_no_default_section_line():
    assert default_section_line(dike(), cell_size=1.0) is None


def test_a_section_samples_before_and_after_and_leaves_out_what_is_off_the_grid():
    grid = make_grid(flat(10.0))
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(10, 15), (30, 15), (30, 25), (10, 25)]),
                   amount=2.0, slopes_inside=False, slope_n=0.0, id="pond")
    stack = FeatureStack(grid)
    stack.update([pond])
    line = line_wkb([(-10.0, 20.0), (35.0, 20.0)])                          # starts 10 m off the west edge
    _window, before, after = stack.terrain_around("pond", grid.window_for_bbox(0, 19, 35, 21))
    section = section_along(line, before, after)
    assert section["stations"][0] > 6.0                                      # the first metres are off the grid
    assert set(np.round(section["before"], 6)) == {10.0}
    assert min(section["after"]) == pytest.approx(8.0) and section["after"][-1] == pytest.approx(10.0)


def test_terrain_around_a_feature_is_before_and_after_it_alone():
    grid = make_grid(flat(10.0))
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, polygon_wkb([(5, 5), (35, 5), (35, 35), (5, 35)]),
                  amount=1.0, slope_n=0.0, id="pad")
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, polygon_wkb([(15, 15), (25, 15), (25, 25), (15, 25)]),
                   amount=3.0, slope_n=0.0, id="pond")
    stack = FeatureStack(grid)
    stack.update([pad, pond])
    window, before, after = stack.terrain_around("pond")
    assert np.array_equal(before.data, stack.terrain_before("pond")[1].data)
    assert before.sample(20.0, 20.0) == pytest.approx(11.0) and after.sample(20.0, 20.0) == pytest.approx(8.0)
    _w, before_off, after_off = stack.terrain_around("pond", features=[pad, replace(pond, enabled=False)])
    assert np.array_equal(before_off.data, after_off.data)                   # a feature turned off changes nothing
```

**File:** `tests/qgis/test_profile_dock.py`
```python
import pytest
from qgis.PyQt.QtCore import QEvent, QPointF, Qt
from qgis.PyQt.QtGui import QMouseEvent

from qgis_helpers import UTM, line_layer, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.help_texts import AREA_SECTION_EMPTY_HINT, AREA_SECTION_NOTE, MULTIPART_LONG_SECTION_NOTE
from terrain_sketch.gui.profile_dock import ProfileDock


def test_the_profile_dock_loads_the_selected_feature(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.mirrored                                     # both sides of the path
    assert (-dike.width / 2.0, 0.0) in dock.cross.points and (dike.width / 2.0, 0.0) in dock.cross.points
    assert dock.cross.points[0][0] == -dock.cross.points[-1][0] < 0.0
    assert len(dock.long.terrain) == 200 and len(dock.long.points) >= 2
    assert dock.note.text() == ""


def test_editing_the_cross_profile_writes_width_and_slope_back(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM, )
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((-15.0, -4.0), (-3.0, 0.0), (3.0, 0.0), (15.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.width == pytest.approx(6.0)
    assert updated.slope_n == pytest.approx(3.0)
    assert sample(c.layers.working, 20, 20) == pytest.approx(11.0)


def test_symmetric_mirrors_the_edit_to_the_other_side(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=10.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(True)
    # a berm added on the right; the left side is still as it was
    dock.cross.profileCommitted.emit(((-12.0, -10.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)))
    updated = c.feature(dike.id)
    assert updated.cross_left == updated.cross_right == ((4.0, -1.0),)
    dock.symmetric.setChecked(False)
    assert dock.cross.points == [(-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (6.0, -1.0), (12.0, -3.0)]
    dock.cross.profileCommitted.emit(((-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), (2.0, 0.0), (8.0, -2.0), (14.0, -4.0)))
    after = c.feature(dike.id)
    assert after.cross_right == ((6.0, -2.0),) and after.cross_left == ((4.0, -1.0),)


def test_the_side_slope_is_shared_between_the_sides_and_the_tip_says_so(tmp_path):
    """`slope_n` and `reach` are single per-feature fields (spec 5.4), so unticking Symmetric
    cannot stop them applying to both sides. The tooltip has to say that rather than promise
    that every edit is mirrored only while it is ticked."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=20.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(False)
    # only the right slope's end moves; the left side is still as it was
    dock.cross.profileCommitted.emit(((-22.0, -20.0 / 3.0), (-2.0, 0.0), (2.0, 0.0), (14.0, -4.0)))
    updated = c.feature(dike.id)
    assert updated.slope_n == pytest.approx(3.0) and updated.reach == pytest.approx(12.0)
    tip = dock.symmetric.toolTip()
    assert "break point" in tip.lower() and "both sides" in tip
    assert "every cross-profile edit" not in tip


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


def test_an_area_feature_gets_a_read_only_section_through_it(tmp_path):
    """Spec §5.4: before and after along a line through the middle of the area."""
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)   # 19 m by 10 m
    c.update_feature(pond.id, amount=2.0, slope_n=0.0)                          # straight sides
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert not dock.long.editable and not dock.symmetric.isEnabled() and not dock.reset_long.isEnabled()
    assert dock.note.text() == AREA_SECTION_NOTE
    before = [z for _s, z in dock.long.terrain]
    after = [z for _s, z in dock.long.points]
    assert len(before) == len(after) > 100
    assert max(before) == pytest.approx(10.0) and min(after) == pytest.approx(8.0, abs=0.05)
    assert after[0] == pytest.approx(10.0) and after[-1] == pytest.approx(10.0)   # it reaches past the outline
    stations = [s for s, _z in dock.long.points]
    assert stations[-1] - stations[0] > 19.0                    # along the longer side, west to east
    assert dock.long.hint == AREA_SECTION_EMPTY_HINT            # what an empty section would say


def two_part_dike(controller):
    """One RAISE_PATH feature whose geometry has two separate line parts."""
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10), line_through(5, 30, 30, 30)])
    return controller.add_from_layer(Tool.RAISE_PATH, Mode.PATH, layer)


def test_a_multi_part_path_gets_a_read_only_long_panel_and_keeps_its_height_field(tmp_path):
    """The engine applies a custom long profile only to a single-part path, so offering one here
    would store the user's drags, disable Height, and change no terrain at all."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = two_part_dike(c)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert not dock.long.editable
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    assert not dock.reset_long.isEnabled()
    assert not c.long_section(dike.id)["custom"]

    # even with one already stored (an earlier version, or a path that was later extended)
    c.update_feature(dike.id, long_profile=((0.0, 20.0), (10.0, 20.0)))
    dock.show_feature(dike.id)
    assert not c.long_section(dike.id)["custom"]
    assert dock.note.text() == MULTIPART_LONG_SECTION_NOTE
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.amount.isEnabled()          # Height still drives the result, so it stays editable
    assert sample(c.layers.working, 20, 10) == pytest.approx(11.0)   # the rule, not the 20 m profile


def test_an_area_cross_profile_refuses_break_points(tmp_path):
    """Break points are not supported for areas in v1 (spec 5.4): the engine discards them."""
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert dock.cross.editable and not dock.cross.allow_breaks
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 35, 34, 35), UTM)
    dock.show_feature(dike.id)
    assert dock.cross.allow_breaks


def test_editing_an_areas_cross_profile_stores_no_break_points(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    dock.cross.profileCommitted.emit(((0.0, 0.0), (0.0, 0.0), (3.0, 0.5), (8.0, 2.0)))
    updated = c.feature(pond.id)
    assert updated.cross_right == () and updated.cross_left == ()
    assert updated.reach == pytest.approx(8.0)      # the terminal slope still writes back


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


def test_deleting_the_shown_feature_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    c.delete_feature(dike.id)  # the Delete button, still showing this feature's profiles
    assert dock.cross.points == [] and dock.long.points == []


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


def mouse(widget, kind, point):
    event = QMouseEvent(kind, point, point, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent, QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent}[kind](event)


def test_undoing_the_shown_feature_during_a_drag_does_not_take_qgis_down(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    cross = dock.cross
    cross.resize(400, 200)
    handle = cross._to_screen(*cross.points[1])
    mouse(cross, QEvent.Type.MouseButtonPress, handle)
    assert cross._dragging == 1
    c.undo_stack.undo()                            # Ctrl+Z in the Profiles panel undoes the Add
    assert c.features == () and cross.points == []
    mouse(cross, QEvent.Type.MouseMove, handle + QPointF(20, -20))
    mouse(cross, QEvent.Type.MouseButtonRelease, handle + QPointF(20, -20))
    assert c.features == ()


def test_the_properties_page_follows_a_cross_profile_drag(tmp_path):
    """A drag moves the width, slope and reach. A page still showing the old values would write the
    old width back with the next arrow step on any of them."""
    from terrain_sketch.gui.properties_page import PropertiesPage
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.cross.profileCommitted.emit(((-7.0, -1.2), (-2.5, 0.0), (2.5, 0.0), (7.0, -1.2)))
    updated = c.feature(dike.id)
    assert (updated.width, updated.slope_n, updated.reach) == pytest.approx((5.0, 3.75, 4.5))
    assert page.width.value() == pytest.approx(5.0) and page.reach.value() == pytest.approx(4.5)
    assert page.slope.value() == pytest.approx(3.8)            # shown to its one decimal
    assert c.feature(dike.id).slope_n == pytest.approx(3.75)   # and not written back rounded


def test_the_left_side_of_a_path_can_be_given_its_own_berm(tmp_path):
    """Until the whole cross-section was shown, only the right side could be edited."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, width=4.0, slope_n=3.0, reach=10.0)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    dock.symmetric.setChecked(False)
    right = [p for p in dock.cross.points if p[0] > 0.0]
    dock.cross.profileCommitted.emit(((-12.0, -3.0), (-6.0, -1.0), (-2.0, 0.0), *right))
    updated = c.feature(dike.id)
    assert updated.cross_left == ((4.0, -1.0),) and updated.cross_right == ()
    assert (updated.width, updated.slope_n, updated.reach) == pytest.approx((4.0, 3.0, 10.0))
    assert sample(c.layers.working, 20, 16) > sample(c.layers.working, 20, 24)   # north is left of an eastward path


def test_the_symmetric_box_tells_the_plot_to_move_mirror_handles_together(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.symmetric
    dock.symmetric.setChecked(False)
    assert not dock.cross.symmetric


def test_an_area_section_follows_the_features_own_line_and_a_path_has_none(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    own = line_through(20, 5, 20, 35).asWkb().data()                        # north to south, 30 m
    c.update_feature(pond.id, section_line=own)
    section = c.area_section(pond.id)
    assert section["line"] == own and section["stations"][-1] == pytest.approx(30.0)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 35, 34, 35), UTM)
    assert c.area_section(dike.id)["stations"] == () and c.area_section("gone")["line"] is None


def test_the_cross_plot_explains_its_sides_only_for_a_path_it_can_edit(tmp_path):
    from terrain_sketch.gui.help_texts import CROSS_SIDES_TIP
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 25, 25, 35), UTM)
    band = c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, 5, 34, 5), UTM)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    assert dock.cross.toolTip() == CROSS_SIDES_TIP
    for other in (pond.id, band.id, None):
        dock.show_feature(other)
        assert dock.cross.toolTip() == "", other
```

**File:** `tests/qgis/test_scenario_file.py`
```python
"""The scenario GeoPackage on its own: what goes into the file and what comes back out."""
import os
from unittest import mock

import pytest
from osgeo import ogr
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.qgis_io import scenario
from terrain_sketch.qgis_io.scenario import (FEATURES_LAYER, META_TABLE, ScenarioError, ScenarioMeta,
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
    c.update_feature(pond.id, pixel_mode=PixelMode.ALL_TOUCHED, slopes_inside=True, enabled=False,
                     section_line=line_through(8, 17, 27, 18).asWkb().data())
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
        assert after.section_line == before.section_line
    assert loaded[1].section_line is not None and loaded[0].section_line is None


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
    every = ScenarioMeta(dem_crs="EPSG:25832", dem_size="40x40", dem_pixel_size="1.0,1.0", dem_extent="0,0,40,40")
    moved = ScenarioMeta(dem_crs="EPSG:3035", dem_size="20x20", dem_pixel_size="2.0,2.0", dem_extent="5,5,45,45")
    assert every.differences(moved) == ["coordinate system", "size in pixels", "pixel size", "extent"]


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
    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        load(path)
    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        load_meta(path)


def test_saving_over_a_file_open_as_a_wal_layer_is_refused(tmp_path):
    """`os.replace` over a GeoPackage another program holds open in WAL mode (QGIS showing the
    scenario as a layer) leaves that program's `-wal`/`-shm` beside the new file — SQLite
    documents that pairing as a corruption path."""
    c = start_session(tmp_path)
    path = str(tmp_path / "open-elsewhere.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    before = (tmp_path / "open-elsewhere.gpkg").read_bytes()
    (tmp_path / "open-elsewhere.gpkg-wal").write_bytes(b"")

    with pytest.raises(ScenarioError):
        save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "open-elsewhere.gpkg").read_bytes() == before


def test_saving_over_a_geopackage_that_is_not_a_scenario_is_refused(tmp_path):
    """`os.replace` destroys every layer in the file it replaces — so a GeoPackage that holds
    the DEM or a user's other layers, not a scenario, must never be chosen as a save target."""
    c = start_session(tmp_path)
    path = str(tmp_path / "other.gpkg")
    source = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    source.CreateLayer("roads", None, ogr.wkbLineString)
    source.Close()
    before = (tmp_path / "other.gpkg").read_bytes()

    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "other.gpkg").read_bytes() == before


def test_saving_over_a_non_geopackage_file_is_refused(tmp_path):
    c = start_session(tmp_path)
    path = tmp_path / "notes.gpkg"
    path.write_text("not a geopackage")
    before = path.read_bytes()

    with pytest.raises(ScenarioError, match="not a Terrain Sketch scenario"):
        save(str(path), c.features, dem_meta(c.info, c.stack.original))
    assert path.read_bytes() == before


def test_replacing_an_existing_scenario_still_works(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "existing.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    save(path, c.features, dem_meta(c.info, c.stack.original))
    assert len(load(path)[0]) == 1


def test_a_save_that_fails_half_way_leaves_the_previous_file_readable(tmp_path):
    c = start_session(tmp_path)
    features = two_features(c)
    path = str(tmp_path / "precious.gpkg")
    save(path, features, dem_meta(c.info, c.stack.original))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 5, 34, 5), UTM)

    with mock.patch.object(scenario, "_write_meta", side_effect=RuntimeError("disk full")):
        with pytest.raises(ScenarioError):
            save(path, c.features, dem_meta(c.info, c.stack.original))
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


def test_a_replace_check_that_raises_is_reported_as_a_scenario_error_not_crashed(tmp_path):
    """`_is_scenario_file` guards only `ogr.Open` — `ExecuteSQL` and friends can still raise
    RuntimeError (e.g. "database is locked"). That must become ScenarioError, not escape raw:
    an exception escaping the Save button's Qt slot aborts QGIS."""
    c = start_session(tmp_path)
    path = str(tmp_path / "locked.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    before = (tmp_path / "locked.gpkg").read_bytes()

    with mock.patch.object(scenario, "_is_scenario_file", side_effect=RuntimeError("database is locked")):
        with pytest.raises(ScenarioError):
            save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "locked.gpkg").read_bytes() == before
    assert not [n for n in os.listdir(tmp_path) if ".saving-" in n]


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
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/core/test_sections.py`
Expected: collection error `ImportError: cannot import name 'default_section_line' from 'terrain_sketch.core.sections'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/core/engine.py`
```python
"""FeatureStack: the ordered list of features and the windowed recompute of the working DEM."""
from __future__ import annotations

from typing import NamedTuple

from .grid import DemGrid, Window
from .operations import FeatureStats, apply_feature, feature_window, footprint_flags
from .volumes import cut_fill


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
        self._before_cache: tuple[DemGrid, dict] | None = None
        # (cut, fill) for the whole grid, kept in step by `update()` so reading it never re-scans
        # every cell — working starts equal to original, so there is nothing to report yet.
        self._totals = (0.0, 0.0)

    @property
    def totals(self) -> tuple[float, float]:
        """Running (cut, fill) in cubic metres for the whole scenario."""
        return self._totals

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
        replayed = self._replay_before(feature_id, features)
        return None if replayed is None else replayed[:2]

    def terrain_around(self, feature_id: str, window: Window | None = None,
                       features=None) -> tuple[Window, DemGrid, DemGrid] | None:
        """The terrain just before and just after `feature_id`, over its own window grown to take in
        `window` too — an area's section line reaches past the feature to show the ground around it."""
        replayed = self._replay_before(feature_id, features, window)
        if replayed is None:
            return None
        window, before, target = replayed
        after = before.copy()
        if target.enabled:
            apply_feature(target, after)
        return window, before, after

    def _replay_before(self, feature_id: str, features=None, extra: Window | None = None):
        """(window, terrain just before the feature, the feature), or None when it is not in the list
        or misses the grid."""
        features = tuple(self.features if features is None else features)
        target = next((f for f in features if f.id == feature_id), None)
        if target is None:
            return None
        window = self.footprint(target)
        if window is None:
            return None
        window, replay = self.closure(window.union(extra) if extra is not None else window, features)
        grid = self.original.subgrid(window)
        # By list position, not by `replay` membership: a disabled target is not in `replay` at
        # all, and stopping at its id would then never fire and apply the whole stack — including
        # the features that come after it.
        position = next(i for i, f in enumerate(features) if f.id == feature_id)
        order = {f.id: i for i, f in enumerate(features)}
        for f in replay:
            if order.get(f.id, position) >= position:
                break
            apply_feature(f, grid)
        self._prune_windows()
        return window, grid, target

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
            before_stats = {}
            for f in replay[:index]:
                before_stats[f.id] = apply_feature(f, base)
            self._before_key, self._before_cache = key, (base, before_stats)
        base, before_stats = self._before_cache
        grid = base.copy()
        stats = dict(before_stats)
        stats.update({f.id: apply_feature(f, grid) for f in replay[index:]})
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
        valid = self.original.valid[window.slices]
        cell_area = self.original.cell_area
        before_cut, before_fill = cut_fill(self.original.data[window.slices], self.working.data[window.slices],
                                           valid, cell_area)
        after_cut, after_fill = cut_fill(self.original.data[window.slices], grid.data, valid, cell_area)
        self.features = features
        self._refresh_bookkeeping()
        self.working.data[window.slices] = grid.data
        self.stats.update(stats)
        cut, fill = self._totals
        # Clamped: cut and fill are magnitudes, so a genuine total can never be negative — only
        # floating-point drift from repeated subtract/add over many updates could make it so.
        self._totals = (max(0.0, cut - before_cut + after_cut), max(0.0, fill - before_fill + after_fill))
        return window

    def _prune_windows(self) -> None:
        """Drop cached footprints of features that are not in the committed list.

        Every preview frame asks for the footprint of a *different* transient feature, so
        without this a drag would add one cache entry per frame and never give them back."""
        current = set(self.features)
        self._windows = {f: w for f, w in self._windows.items() if f in current}

    def _refresh_bookkeeping(self) -> None:
        self._before_key, self._before_cache = None, None
        self._prune_windows()
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

Replace the whole file:

**File:** `terrain_sketch/core/sections.py`
```python
"""Profile sampling for the editors: the cross-section template and the long section along a path.

Pure geometry and sampling — the widgets draw what these return and hand back edited points.
"""
from __future__ import annotations

import math

import numpy as np
from osgeo import ogr
from scipy.spatial import ConvexHull, QhullError

from .geometry import is_line, line_coords, line_wkb, polygon_rings, split_parts
from .grid import DemGrid
from .operations import NoReferenceError, path_coords, rule_profile
from .profiles import side_dz, side_limit
from .stations import vertex_stations
from .tools import TOOL_INFO, Mode

SAMPLES = 200
SAME = 1e-4   # values are written back at four decimals, so closer than this is the same value


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
    sorted_breaks = sorted(breaks, key=lambda b: b[0])
    for distance, dz in sorted_breaks:
        points.append((edge + float(distance), float(dz)))
    if limit > (sorted_breaks[-1][0] if sorted_breaks else 0.0):
        dz, _in_extent = side_dz(np.array([limit]), sorted_breaks, feature.slope_n, feature.reach,
                                 info.direction)
        points.append((edge + limit, float(dz[0])))
    return tuple(points)


def set_cross_section(feature, side: int, points) -> dict:
    """Turn edited cross-section points back into feature fields.

    `points` are ((distance from the centre line, dz), ...) as `cross_section` returns them.
    The first interior point sets the width; the rest become break points relative to the
    corridor edge; the last segment's run over rise sets the side slope.
    """
    pts = sorted([(float(d), float(z)) for d, z in points if float(d) >= 0.0], key=lambda p: p[0])
    if len(pts) < 2:
        raise ValueError("a cross section needs at least a centre and an edge point")
    edge = pts[1][0]
    changes: dict = {}
    # Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    # break list to `side_dz`, so writing them here would store a value the engine discards.
    breaks_key = ("cross_right" if side >= 0 else "cross_left") if feature.mode is Mode.PATH else None
    if feature.mode is Mode.PATH:
        changes["width"] = max(2.0 * edge, 0.1)

    # The final point is the slope's end only if the plot drew one: `cross_section` adds it when the
    # reach goes past the last break. With breaks beyond the reach there is none, and reading the last
    # break as the slope's end would rewrite the slope and the reach and drop that break.
    has_terminal_slope = feature.slope_n > 0.0
    last_break_distance = pts[-2][0] if len(pts) > 2 else edge
    stored = feature.cross_right if side >= 0 else feature.cross_left
    drew_terminus = side_limit(stored, feature.slope_n, feature.reach) > max([0.0] + [float(d) for d, _ in stored])
    last_point_is_terminus = has_terminal_slope and drew_terminus and pts[-1][0] > last_break_distance

    if has_terminal_slope and not drew_terminus:
        # every point after the edge is a break; the slope and its reach are not on the plot to change
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in pts[2:] if d > edge)
    elif last_point_is_terminus:
        interior, last = pts[2:-1], pts[-1]
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in interior)
        run = last[0] - (interior[-1][0] if interior else edge)
        rise = abs(last[1] - (interior[-1][1] if interior else 0.0))
        changes["slope_n"] = _slope_n(run, rise, feature.slope_n)
        changes["reach"] = _reach(last[0] - edge, feature.reach)
    else:
        # No terminal slope: all points after edge are breaks. Derive slope_n and reach.
        # Filter out breaks at distance 0 (at the edge itself) and collapse duplicates.
        interior = [(d, z) for d, z in pts[2:] if d > edge]

        # Collapse duplicate distances: keep the later (rightmost) value
        seen_distances = {}
        for d, z in interior:
            seen_distances[d] = z

        deduplicated = sorted(seen_distances.items())
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in deduplicated)
        changes["slope_n"] = 0.0
        changes["reach"] = 0.0 if not deduplicated else feature.reach

    return changes


def whole_cross_section(feature) -> tuple:
    """A path's cross profile across both sides, as a surveyor draws it: ((offset, dz), ...) from the
    end of the left slope to the end of the right one, left of the centre line at negative offsets.
    Left and right are as seen looking along the path in the direction it was drawn."""
    left = cross_section(feature, side=-1)[1:]
    right = cross_section(feature, side=1)[1:]
    return tuple((-x, z) for x, z in reversed(left)) + right


def set_whole_cross_section(feature, points, symmetric: bool = False) -> dict:
    """Turn an edited whole cross profile back into feature fields.

    Each side is read the way `set_cross_section` reads one, but a side whose points are still the ones
    the plot was given is left as the feature has it: reading it back could only add rounding. Width,
    side slope and reach are single values shared by both sides, so each is taken from the side where it
    changed (the right when both did). With `symmetric`, the break points of the side that was edited
    are copied to the other side."""
    pts = [(float(x), float(z)) for x, z in points]
    sides = {}
    for side, key, own in ((1, "cross_right", sorted(p for p in pts if p[0] > 0.0)),
                           (-1, "cross_left", sorted((-x, z) for x, z in pts if x < 0.0))):
        if _same_points(own, cross_section(feature, side=side)[1:]):
            sides[key] = {}
        else:
            sides[key] = set_cross_section(feature, side, [(0.0, 0.0)] + own)
    changes = {key: read.get(key, getattr(feature, key)) for key, read in sides.items()}
    for key in ("width", "slope_n", "reach"):
        current = getattr(feature, key)
        left, right = sides["cross_left"].get(key, current), sides["cross_right"].get(key, current)
        changes[key] = left if abs(left - current) > SAME and abs(right - current) <= SAME else right
    if symmetric:
        if _same_points(changes["cross_right"], feature.cross_right) \
                and not _same_points(changes["cross_left"], feature.cross_left):
            changes["cross_right"] = changes["cross_left"]
        else:
            changes["cross_left"] = changes["cross_right"]
    return changes


def _same_points(a, b) -> bool:
    """Whether two break lists are equal to within the rounding a round trip through the plot adds."""
    return len(a) == len(b) and all(abs(ax - bx) <= SAME and abs(az - bz) <= SAME
                                    for (ax, az), (bx, bz) in zip(a, b))


def _slope_n(run: float, rise: float, current: float) -> float:
    """The terminal slope 1:n from a run over a rise, rounded to the stored four decimals.

    0.0 is the "no terminal slope" sentinel, so a run too small to round to a non-zero n — a
    terminus dragged hard against its neighbour — keeps the slope the feature already has
    rather than silently losing it. There is no undo.
    """
    if rise <= 1e-9:
        return 0.0
    rounded = round(run / rise, 4)
    return rounded if rounded > 0.0 else current


def _reach(distance: float, current: float) -> float:
    """The slope's reach from the terminus's distance beyond the edge, rounded like the slope.

    A reach of 0.0 stops the slope at the edge, so a terminus dragged hard against the edge rounds to
    nothing only by accident — the same drag `_slope_n` guards against — and keeps the reach it had."""
    rounded = round(distance, 4)
    return rounded if rounded > 0.0 else current


def section_part(feature):
    """The part a long section runs along: for a multi-part path, the longest one."""
    geometry_parts = [p for p in split_parts(feature.geometry_wkb) if is_line(p)]
    if feature.mode is not Mode.PATH or not geometry_parts:
        return None
    return max(geometry_parts, key=lambda p: _length(line_coords(p)))


def supports_long_profile(feature) -> bool:
    """Whether a custom long profile would actually drive this feature's terrain.

    `operations.apply_feature` uses one only for a single-part path (spec 5.4), so for anything
    else the editor must not offer one: it would be stored, shown as custom and then discarded,
    while the Height/Depth that does drive the result sits disabled.
    """
    if feature.mode is not Mode.PATH:
        return False
    try:
        return len(split_parts(feature.geometry_wkb)) == 1
    except ValueError:
        return False


def long_section(feature, grid: DemGrid, terrain: DemGrid | None = None) -> dict:
    """Reference terrain and design line along the feature's centre line.

    Returns `{"stations", "terrain", "design", "custom"}`: stations in metres from the start,
    terrain sampled on `terrain` (the state just before this feature) and the design line
    either from the feature's custom long profile or regenerated from the tool rule.

    `custom` is False whenever the engine would ignore the stored profile — a multi-part path —
    so the editor never presents a line the terrain does not follow.
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
    if feature.long_profile is not None and supports_long_profile(feature):
        design = tuple((float(s), float(z)) for s, z in feature.long_profile)
        return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": True}
    try:
        design = rule_profile(feature, part, reference)
    except NoReferenceError:
        design = ()
    return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": False}


def default_section_line(feature, cell_size: float) -> bytes | None:
    """The line an area's section runs along until the user draws one (spec §5.4): through the
    centroid, along the longer side of the smallest rotated rectangle around the outline, and on past
    the outline — beyond the reach of outside slopes — so the section shows the ground around it.
    Runs west to east (or south to north). None for a path, or an outline too thin to have a longer side."""
    parts = [p for p in split_parts(feature.geometry_wkb) if not is_line(p)] if feature.mode is Mode.AREA else []
    if not parts:
        return None
    points = np.vstack([polygon_rings(p)[0] for p in parts])
    try:
        hull = points[ConvexHull(points).vertices]
    except (QhullError, ValueError):
        return None
    along, best = None, None
    for a, b in zip(hull, np.roll(hull, -1, axis=0)):
        edge = b - a
        size = float(np.hypot(*edge))
        if size == 0.0:
            continue
        u = edge / size
        v = np.array([-u[1], u[0]])
        span_u, span_v = np.ptp(hull @ u), np.ptp(hull @ v)
        if best is None or span_u * span_v < best:
            best, along = span_u * span_v, (u if span_u >= span_v else v)
    if along[0] < 0.0 or (along[0] == 0.0 and along[1] < 0.0):
        along = -along
    outline = ogr.CreateGeometryFromWkb(bytes(feature.geometry_wkb))
    centre = np.array(outline.Centroid().GetPoints()[0][:2])
    t = (points - centre) @ along
    outside = TOOL_INFO[feature.tool].has_slopes and feature.slope_n > 0.0 and not feature.slopes_inside
    margin = (feature.reach if outside else 0.0) + max(5.0 * cell_size, 0.1 * float(np.ptp(t)))
    return line_wkb([centre + (t.min() - margin) * along, centre + (t.max() + margin) * along])


def section_along(line: bytes, before: DemGrid, after: DemGrid) -> dict:
    """Terrain before and after a feature along `line`: `{"stations", "before", "after"}`, stations in
    metres from the line's start. Stations where either terrain is nodata or off the grid are left out."""
    coords = line_coords(ogr.CreateGeometryFromWkb(bytes(line)))
    empty = {"stations": (), "before": (), "after": ()}
    if len(coords) < 2 or _length(coords) <= 0.0:
        return empty
    stations = np.linspace(0.0, _length(coords), SAMPLES)
    xs, ys = _walk(coords, stations)
    rows = [(float(s), before.sample(x, y), after.sample(x, y)) for s, x, y in zip(stations, xs, ys)]
    rows = [row for row in rows if not (math.isnan(row[1]) or math.isnan(row[2]))]
    if not rows:
        return empty
    out = tuple(zip(*rows))
    return {"stations": out[0], "before": out[1], "after": out[2]}


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
EXPORT_ADD_FAILED = ("The exported DEM {} could not be added to the project; see the 'Terrain Sketch' log tab "
                     "for details.")

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

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It is the project's terrain, but only a temporary one, "
               "even if you save the project meanwhile: the terrain you had before is put back when this "
               "session ends.")
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
AREA_SECTION_EMPTY_HINT = "There is no terrain to show along this feature's section line."
AREA_SECTION_NOTE = ("A section straight through the area: dashed is the ground before this feature, solid is "
                     "the result. Shape the sides with the cross profile on the left.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
CROSS_SIDES_TIP = ("A section across the path, looking along it in the direction it was drawn: its left side "
                   "on the left. Drag the crest edges to change the width, and the ends of the slopes to change "
                   "their steepness and reach; double-click to add a break point, such as a berm, and "
                   "right-click to remove one.")
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

**File:** `terrain_sketch/gui/profile_dock.py`
```python
"""Bottom dock: the cross profile and the long profile of the selected feature, side by side."""
from __future__ import annotations

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                                 QWidget)

from ..core.sections import (cross_section, set_cross_section, set_whole_cross_section, supports_long_profile,
                             whole_cross_section)
from ..core.tools import TOOL_INFO, Mode
from .help_texts import (AREA_SECTION_EMPTY_HINT, AREA_SECTION_NOTE, CROSS_SIDES_TIP, CUSTOM_PROFILE_NOTE,
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
        self.cross.symmetric = True
        self.symmetric.toggled.connect(self._symmetric_toggled)
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
            self.cross.setToolTip("")
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
            self.cross.setToolTip(CROSS_SIDES_TIP if is_path and info.has_slopes else "")   # it is about sides
            # A path shows both sides around its centre line; an area shows its one edge slope, and
            # takes no break points: the engine discards an area's (spec 5.4).
            if is_path:
                self.cross.set_profile(whole_cross_section(feature), editable=info.has_slopes, mirrored=True)
            else:
                self.cross.set_profile(cross_section(feature, side=1), editable=info.has_slopes,
                                       allow_breaks=False)
            self.symmetric.setEnabled(info.has_slopes and is_path)
            self.reset_cross.setEnabled(info.has_slopes)
            if feature.mode is Mode.AREA:
                self._show_area_section()
            else:
                self._show_long_section(feature)
        finally:
            self._loading = False

    def _show_area_section(self) -> None:
        """An area has no long profile; the right-hand panel shows a read-only section through it
        instead, the ground before and after the feature (spec §5.4)."""
        area = self.controller.area_section(self._fid)
        self.long.set_profile(tuple(zip(area["stations"], area["after"])),
                              terrain=tuple(zip(area["stations"], area["before"])), editable=False,
                              hint=AREA_SECTION_EMPTY_HINT)
        self.note.setText(AREA_SECTION_NOTE)
        self.reset_long.setEnabled(False)

    def _show_long_section(self, feature) -> None:
        section = self.controller.long_section(self._fid)
        if not supports_long_profile(feature):
            # A multi-part path: the engine follows the tool rule whatever is stored here.
            self.long.set_profile(section["design"], terrain=self._pairs(section),
                                  editable=False)
            self.note.setText(MULTIPART_LONG_SECTION_NOTE)
        else:
            self.long.set_profile(section["design"], terrain=self._pairs(section))
            self.note.setText(CUSTOM_PROFILE_NOTE if section["custom"] else "")
        self.reset_long.setEnabled(bool(section["custom"]))

    @staticmethod
    def _pairs(section) -> tuple:
        return tuple(zip(section["stations"], section["terrain"]))

    def _cross_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        feature = self.controller.find(self._fid)
        if feature is None:
            return
        try:
            if feature.mode is Mode.PATH:
                changes = set_whole_cross_section(feature, points, symmetric=self.symmetric.isChecked())
            else:
                changes = set_cross_section(feature, 1, points)
        except ValueError:
            return            # a side without its crest edge; the plot never sends one, and this is a slot
        self._apply(changes, commit)

    def _long_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        self._apply({"long_profile": tuple((float(s), float(z)) for s, z in points)}, commit)

    def _apply(self, changes: dict, commit: bool) -> None:
        if commit:
            self.controller.update_profile(self._fid, **changes)
        else:
            self.controller.preview(self._fid, **changes)

    def _reset_cross(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, cross_left=(), cross_right=())

    def _reset_long(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, long_profile=None)

    def _symmetric_toggled(self, checked: bool) -> None:
        self.cross.symmetric = checked

    def _session_changed(self) -> None:
        if not self.controller.has_dem:
            self.show_feature(None)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.symmetric, self.reset_cross, self.reset_long):
            widget.setEnabled(enabled)

    def shutdown(self) -> None:
        self.controller.cancel_preview()
```

Replace the whole file:

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
    section_line: bytes | None = None  # areas: WKB line the section runs along; None = the default line

    def __post_init__(self):
        if self.mode not in TOOL_INFO[self.tool].modes:
            raise ValueError(f"{self.tool.value} does not support {self.mode.value} mode")
        # the GUI may pass lists; store hashable tuples of float pairs (the engine caches by value)
        object.__setattr__(self, "geometry_wkb", bytes(self.geometry_wkb))
        object.__setattr__(self, "cross_left", _points(self.cross_left))
        object.__setattr__(self, "cross_right", _points(self.cross_right))
        if self.long_profile is not None:
            object.__setattr__(self, "long_profile", _points(self.long_profile))
        if self.section_line is not None:
            object.__setattr__(self, "section_line", bytes(self.section_line))

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
            "section_line": None if self.section_line is None else self.section_line.hex(),
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
            section_line=None if d.get("section_line") is None else bytes.fromhex(d["section_line"]),
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
    def read(source, layer):
        rows = sorted((_from_ogr(f) for f in layer), key=lambda pair: pair[0])
        return [feature for _order, feature in rows], _read_meta(source)
    return _reading(path, read)


def load_meta(path: str) -> ScenarioMeta:
    """Only the metadata, to compare DEMs before deciding whether to load. Raises ScenarioError
    for a file that is not a readable scenario, exactly as `load` would."""
    return _reading(path, lambda source, _layer: _read_meta(source))


def _reading(path: str, read):
    """`read(source, layer)` on the scenario at `path`, with the handle closed afterwards and any
    failure turned into a ScenarioError the user can read."""
    source = None
    try:
        source, layer = _open(path)
        return read(source, layer)
    except ScenarioError:
        raise
    except Exception as error:  # noqa: BLE001 — GDAL raises many types; the user gets one message
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
    if feature.section_line is not None:
        out.SetField("section_line", ogr.CreateGeometryFromWkb(feature.section_line).ExportToWkt())
    return out


def _from_ogr(row) -> tuple[int, TerrainFeature]:
    geometry = row.GetGeometryRef()
    if geometry is None:
        raise ScenarioError("A feature in the scenario has no geometry.")
    params = json.loads(row.GetField("params") or "{}")
    cross = json.loads(row.GetField("cross_profile") or "{}")
    long_profile = row.GetField("long_profile")
    section_line = row.GetField("section_line")
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
        section_line=None if not section_line else bytes(ogr.CreateGeometryFromWkt(section_line).ExportToWkb()),
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

Run: `scripts/test.sh tests/core/test_feature.py tests/core/test_sections.py tests/qgis/test_profile_dock.py tests/qgis/test_scenario_file.py` → Expected: `79 passed`
Run: `scripts/test.sh` → Expected: `493 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/core/engine.py terrain_sketch/core/sections.py terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/profile_dock.py terrain_sketch/model/feature.py terrain_sketch/qgis_io/scenario.py tests/core/test_feature.py tests/core/test_sections.py tests/qgis/test_profile_dock.py tests/qgis/test_scenario_file.py
git commit -m "feat: a read-only section through an area, before and after the feature"
```

---

### Task 5: Draw an area's section line

**Files:**
- Modify: `terrain_sketch/core/sections.py`, `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/gui/profile_dock.py`
- Test: `tests/qgis/test_section_line.py`

**Interfaces:**
- Consumes: Task 4's `section_line`, `area_section`, `default_section_line`; `SketchController.update_feature`, `_describe`; `convert.to_dem_wkb`, `from_wkb`; `MainDock._begin_drawing`, `end_drawing`, `stop_tools`, `_update_highlight`, `_to_canvas`; `DrawLineTool`.
- Produces: `SketchController.section_line(fid) -> bytes | None`, `set_section_line(fid, geometry, crs=None) -> bool`; `help_texts.UNDO_SECTION_LINE`, `SECTION_LINE_HINT`, `DRAW_SECTION_TIP`, `RESET_SECTION_TIP`; `ProfileDock.drawSectionRequested(str)`, `draw_section`, `reset_section`; `MainDock.section_band`, `_activate_drawing(hint)`, `_draw_section_line(fid)`, `_section_drawn(fid, geometry)`, `_update_section_band(fid)`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_section_line.py`
```python
"""The line an area's section runs along (spec §5.4): drawn on the map, shown there, undone, reset."""
import numpy as np
import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import SECTION_LINE_HINT, UNDO_SECTION_LINE
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.gui.map_tools.draw_line import DrawLineTool
from terrain_sketch.gui.profile_dock import ProfileDock
from terrain_sketch.qgis_io.convert import from_wkb


def pond_and_dike(c):
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 35, 34, 35), UTM)
    return pond, dike


def panels(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    profiles = ProfileDock(controller)
    dock = MainDock(iface, controller, profiles)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, profiles, dock


def test_a_drawn_section_line_is_stored_in_the_dem_crs_as_one_undo_step(tmp_path):
    c = start_session(tmp_path)
    pond, _dike = pond_and_dike(c)
    terrain = c.stack.working.data.copy()
    web = QgsCoordinateReferenceSystem("EPSG:3857")
    drawn = QgsGeometry(line_through(20, 5, 20, 35))
    drawn.transform(QgsCoordinateTransform(UTM, web, QgsProject.instance()))
    steps = c.undo_stack.count()
    assert c.set_section_line(pond.id, drawn, web)
    stored = from_wkb(c.find(pond.id).section_line)
    assert stored.asPolyline()[0].x() == pytest.approx(line_through(20, 5, 20, 35).asPolyline()[0].x(), abs=0.01)
    assert c.undo_stack.count() == steps + 1 and c.undo_stack.undoText() == UNDO_SECTION_LINE.format(pond.name)
    assert np.array_equal(c.stack.working.data, terrain)          # the terrain does not change
    assert c.is_dirty                                             # but the scenario file holds the line
    c.undo_stack.undo()
    assert c.find(pond.id).section_line is None


def test_resetting_the_line_goes_back_to_the_default_through_the_middle(tmp_path):
    c = start_session(tmp_path)
    pond, _dike = pond_and_dike(c)
    default = c.section_line(pond.id)
    c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert c.section_line(pond.id) != default
    assert c.set_section_line(pond.id, None)
    assert c.find(pond.id).section_line is None and c.section_line(pond.id) == default


def test_only_an_area_that_still_exists_takes_a_section_line(tmp_path):
    c = start_session(tmp_path)
    pond, dike = pond_and_dike(c)
    steps = c.undo_stack.count()
    assert not c.set_section_line(dike.id, line_through(20, 5, 20, 35), UTM)
    assert c.section_line(dike.id) is None
    c.delete_feature(pond.id)
    assert not c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert c.undo_stack.count() == steps + 1                     # only the delete


def test_a_drawing_that_is_not_a_line_is_a_message(tmp_path):
    c = start_session(tmp_path)
    pond, _dike = pond_and_dike(c)
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    assert not c.set_section_line(pond.id, square(1, 1, 5, 5), UTM)
    assert heard and c.find(pond.id).section_line is None


def test_the_profiles_panel_offers_the_section_buttons_for_an_area_only(tmp_path):
    c = start_session(tmp_path)
    pond, dike = pond_and_dike(c)
    dock = ProfileDock(c)
    dock.show_feature(pond.id)
    assert not dock.draw_section.isHidden() and not dock.reset_section.isHidden() and dock.reset_long.isHidden()
    assert dock.draw_section.isEnabled() and not dock.reset_section.isEnabled()   # nothing to reset yet
    asked = []
    dock.drawSectionRequested.connect(asked.append)
    dock.draw_section.click()
    assert asked == [pond.id]
    c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert dock.reset_section.isEnabled()
    dock.reset_section.click()
    assert c.find(pond.id).section_line is None
    dock.show_feature(dike.id)
    assert dock.draw_section.isHidden() and dock.reset_section.isHidden() and not dock.reset_long.isHidden()


def test_draw_section_line_puts_a_line_tool_on_the_map_and_stores_what_is_drawn(tmp_path):
    iface, c, profiles, dock = panels(tmp_path)
    pond, _dike = pond_and_dike(c)
    dock.feature_view.select_id(pond.id)
    profiles.draw_section.click()
    canvas = iface.mapCanvas()
    assert isinstance(dock.draw_tool, DrawLineTool) and canvas.mapTool() is dock.draw_tool
    assert dock.hint.text() == SECTION_LINE_HINT
    dock.draw_tool.finished.emit(line_through(20, 5, 20, 35))
    assert dock.draw_tool is None and c.find(pond.id).section_line is not None
    assert len(c.features) == 2                                  # a section line, not a new feature
    assert profiles.long.points[-1][0] == pytest.approx(30.0)    # the section now runs along it


def test_the_map_shows_the_section_line_of_the_selected_area(tmp_path):
    _iface, c, _profiles, dock = panels(tmp_path)
    pond, dike = pond_and_dike(c)
    dock.feature_view.select_id(pond.id)
    shown = dock.section_band.asGeometry()
    assert not shown.isEmpty() and shown.asWkt(3) == from_wkb(c.section_line(pond.id)).asWkt(3)
    c.set_section_line(pond.id, line_through(20, 5, 20, 35), UTM)
    assert dock.section_band.asGeometry().asWkt(3) == from_wkb(c.find(pond.id).section_line).asWkt(3)
    dock.feature_view.select_id(dike.id)
    assert dock.section_band.asGeometry().isEmpty()


def test_finishing_a_section_line_for_an_area_that_was_undone_adds_nothing(tmp_path):
    _iface, c, profiles, dock = panels(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 12, 29, 22), UTM)
    dock.feature_view.select_id(pond.id)
    profiles.draw_section.click()
    tool = dock.draw_tool
    c.undo_stack.undo()                                          # the pond goes while the line is drawn
    tool.finished.emit(line_through(20, 5, 20, 35))
    assert c.features == () and dock.draw_tool is None
```
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/qgis/test_section_line.py`
Expected: collection error `ImportError: cannot import name 'SECTION_LINE_HINT' from 'terrain_sketch.gui.help_texts'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/core/sections.py`
```python
"""Profile sampling for the editors: the cross-section template and the long section along a path.

Pure geometry and sampling — the widgets draw what these return and hand back edited points.
"""
from __future__ import annotations

import math

import numpy as np
from osgeo import ogr
from scipy.spatial import ConvexHull, QhullError

from .geometry import is_line, line_coords, line_wkb, polygon_rings, split_parts
from .grid import DemGrid
from .operations import NoReferenceError, path_coords, rule_profile
from .profiles import side_dz, side_limit
from .stations import vertex_stations
from .tools import TOOL_INFO, Mode

SAMPLES = 200
SAME = 1e-4   # values are written back at four decimals, so closer than this is the same value


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
    sorted_breaks = sorted(breaks, key=lambda b: b[0])
    for distance, dz in sorted_breaks:
        points.append((edge + float(distance), float(dz)))
    if limit > (sorted_breaks[-1][0] if sorted_breaks else 0.0):
        dz, _in_extent = side_dz(np.array([limit]), sorted_breaks, feature.slope_n, feature.reach,
                                 info.direction)
        points.append((edge + limit, float(dz[0])))
    return tuple(points)


def set_cross_section(feature, side: int, points) -> dict:
    """Turn edited cross-section points back into feature fields.

    `points` are ((distance from the centre line, dz), ...) as `cross_section` returns them.
    The first interior point sets the width; the rest become break points relative to the
    corridor edge; the last segment's run over rise sets the side slope.
    """
    pts = sorted([(float(d), float(z)) for d, z in points if float(d) >= 0.0], key=lambda p: p[0])
    if len(pts) < 2:
        raise ValueError("a cross section needs at least a centre and an edge point")
    edge = pts[1][0]
    changes: dict = {}
    # Break points are not supported for areas in v1 (spec 5.4): `_area_design` passes an empty
    # break list to `side_dz`, so writing them here would store a value the engine discards.
    breaks_key = ("cross_right" if side >= 0 else "cross_left") if feature.mode is Mode.PATH else None
    if feature.mode is Mode.PATH:
        changes["width"] = max(2.0 * edge, 0.1)

    # The final point is the slope's end only if the plot drew one: `cross_section` adds it when the
    # reach goes past the last break. With breaks beyond the reach there is none, and reading the last
    # break as the slope's end would rewrite the slope and the reach and drop that break.
    has_terminal_slope = feature.slope_n > 0.0
    last_break_distance = pts[-2][0] if len(pts) > 2 else edge
    stored = feature.cross_right if side >= 0 else feature.cross_left
    drew_terminus = side_limit(stored, feature.slope_n, feature.reach) > max([0.0] + [float(d) for d, _ in stored])
    last_point_is_terminus = has_terminal_slope and drew_terminus and pts[-1][0] > last_break_distance

    if has_terminal_slope and not drew_terminus:
        # every point after the edge is a break; the slope and its reach are not on the plot to change
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in pts[2:] if d > edge)
    elif last_point_is_terminus:
        interior, last = pts[2:-1], pts[-1]
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in interior)
        run = last[0] - (interior[-1][0] if interior else edge)
        rise = abs(last[1] - (interior[-1][1] if interior else 0.0))
        changes["slope_n"] = _slope_n(run, rise, feature.slope_n)
        changes["reach"] = _reach(last[0] - edge, feature.reach)
    else:
        # No terminal slope: all points after edge are breaks. Derive slope_n and reach.
        # Filter out breaks at distance 0 (at the edge itself) and collapse duplicates.
        interior = [(d, z) for d, z in pts[2:] if d > edge]

        # Collapse duplicate distances: keep the later (rightmost) value
        seen_distances = {}
        for d, z in interior:
            seen_distances[d] = z

        deduplicated = sorted(seen_distances.items())
        if breaks_key is not None:
            changes[breaks_key] = tuple((d - edge, z) for d, z in deduplicated)
        changes["slope_n"] = 0.0
        changes["reach"] = 0.0 if not deduplicated else feature.reach

    return changes


def whole_cross_section(feature) -> tuple:
    """A path's cross profile across both sides, as a surveyor draws it: ((offset, dz), ...) from the
    end of the left slope to the end of the right one, left of the centre line at negative offsets.
    Left and right are as seen looking along the path in the direction it was drawn."""
    left = cross_section(feature, side=-1)[1:]
    right = cross_section(feature, side=1)[1:]
    return tuple((-x, z) for x, z in reversed(left)) + right


def set_whole_cross_section(feature, points, symmetric: bool = False) -> dict:
    """Turn an edited whole cross profile back into feature fields.

    Each side is read the way `set_cross_section` reads one, but a side whose points are still the ones
    the plot was given is left as the feature has it: reading it back could only add rounding. Width,
    side slope and reach are single values shared by both sides, so each is taken from the side where it
    changed (the right when both did). With `symmetric`, the break points of the side that was edited
    are copied to the other side."""
    pts = [(float(x), float(z)) for x, z in points]
    sides = {}
    for side, key, own in ((1, "cross_right", sorted(p for p in pts if p[0] > 0.0)),
                           (-1, "cross_left", sorted((-x, z) for x, z in pts if x < 0.0))):
        if _same_points(own, cross_section(feature, side=side)[1:]):
            sides[key] = {}
        else:
            sides[key] = set_cross_section(feature, side, [(0.0, 0.0)] + own)
    changes = {key: read.get(key, getattr(feature, key)) for key, read in sides.items()}
    for key in ("width", "slope_n", "reach"):
        current = getattr(feature, key)
        left, right = sides["cross_left"].get(key, current), sides["cross_right"].get(key, current)
        changes[key] = left if abs(left - current) > SAME and abs(right - current) <= SAME else right
    if symmetric:
        if _same_points(changes["cross_right"], feature.cross_right) \
                and not _same_points(changes["cross_left"], feature.cross_left):
            changes["cross_right"] = changes["cross_left"]
        else:
            changes["cross_left"] = changes["cross_right"]
    return changes


def _same_points(a, b) -> bool:
    """Whether two break lists are equal to within the rounding a round trip through the plot adds."""
    return len(a) == len(b) and all(abs(ax - bx) <= SAME and abs(az - bz) <= SAME
                                    for (ax, az), (bx, bz) in zip(a, b))


def _slope_n(run: float, rise: float, current: float) -> float:
    """The terminal slope 1:n from a run over a rise, rounded to the stored four decimals.

    0.0 is the "no terminal slope" sentinel, so a run too small to round to a non-zero n — a
    terminus dragged hard against its neighbour — keeps the slope the feature already has
    rather than silently losing it. There is no undo.
    """
    if rise <= 1e-9:
        return 0.0
    rounded = round(run / rise, 4)
    return rounded if rounded > 0.0 else current


def _reach(distance: float, current: float) -> float:
    """The slope's reach from the terminus's distance beyond the edge, rounded like the slope.

    A reach of 0.0 stops the slope at the edge, so a terminus dragged hard against the edge rounds to
    nothing only by accident — the same drag `_slope_n` guards against — and keeps the reach it had."""
    rounded = round(distance, 4)
    return rounded if rounded > 0.0 else current


def section_part(feature):
    """The part a long section runs along: for a multi-part path, the longest one."""
    geometry_parts = [p for p in split_parts(feature.geometry_wkb) if is_line(p)]
    if feature.mode is not Mode.PATH or not geometry_parts:
        return None
    return max(geometry_parts, key=lambda p: _length(line_coords(p)))


def supports_long_profile(feature) -> bool:
    """Whether a custom long profile would actually drive this feature's terrain.

    `operations.apply_feature` uses one only for a single-part path (spec 5.4), so for anything
    else the editor must not offer one: it would be stored, shown as custom and then discarded,
    while the Height/Depth that does drive the result sits disabled.
    """
    if feature.mode is not Mode.PATH:
        return False
    try:
        return len(split_parts(feature.geometry_wkb)) == 1
    except ValueError:
        return False


def long_section(feature, grid: DemGrid, terrain: DemGrid | None = None) -> dict:
    """Reference terrain and design line along the feature's centre line.

    Returns `{"stations", "terrain", "design", "custom"}`: stations in metres from the start,
    terrain sampled on `terrain` (the state just before this feature) and the design line
    either from the feature's custom long profile or regenerated from the tool rule.

    `custom` is False whenever the engine would ignore the stored profile — a multi-part path —
    so the editor never presents a line the terrain does not follow.
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
    if feature.long_profile is not None and supports_long_profile(feature):
        design = tuple((float(s), float(z)) for s, z in feature.long_profile)
        return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": True}
    try:
        design = rule_profile(feature, part, reference)
    except NoReferenceError:
        design = ()
    return {"stations": tuple(stations), "terrain": heights, "design": design, "custom": False}


def default_section_line(feature, cell_size: float) -> bytes | None:
    """The line an area's section runs along until the user draws one (spec §5.4): through the
    centroid, along the longer side of the smallest rotated rectangle around the outline, and on past
    the outline — beyond the reach of outside slopes — so the section shows the ground around it.
    Runs west to east (or south to north). None for a path, or an outline too thin to have a longer side."""
    parts = [p for p in split_parts(feature.geometry_wkb) if not is_line(p)] if feature.mode is Mode.AREA else []
    if not parts:
        return None
    points = np.vstack([polygon_rings(p)[0] for p in parts])
    try:
        hull = points[ConvexHull(points).vertices]
    except (QhullError, ValueError):
        return None
    along, best = None, None
    for a, b in zip(hull, np.roll(hull, -1, axis=0)):
        edge = b - a
        size = float(np.hypot(*edge))
        if size == 0.0:
            continue
        u = edge / size
        v = np.array([-u[1], u[0]])
        span_u, span_v = np.ptp(hull @ u), np.ptp(hull @ v)
        if best is None or span_u * span_v < best:
            best, along = span_u * span_v, (u if span_u >= span_v else v)
    if along[0] < 0.0 or (along[0] == 0.0 and along[1] < 0.0):
        along = -along
    outline = ogr.CreateGeometryFromWkb(bytes(feature.geometry_wkb))
    centre = np.array(outline.Centroid().GetPoints()[0][:2])
    t = (points - centre) @ along
    outside = TOOL_INFO[feature.tool].has_slopes and feature.slope_n > 0.0 and not feature.slopes_inside
    margin = (feature.reach if outside else 0.0) + max(5.0 * cell_size, 0.1 * float(np.ptp(t)))
    return line_wkb([centre + (t.min() - margin) * along, centre + (t.max() + margin) * along])


def section_along(line: bytes, before: DemGrid, after: DemGrid) -> dict:
    """Terrain before and after a feature along `line`: `{"stations", "before", "after"}`, stations in
    metres from the line's start. Stations where either terrain is nodata or off the grid are left out."""
    empty = {"stations": (), "before": (), "after": ()}
    lines = [line_coords(p) for p in split_parts(line) if is_line(p)]
    coords = max(lines, key=_length, default=np.zeros((0, 2)))
    if len(coords) < 2 or _length(coords) <= 0.0:
        return empty
    stations = np.linspace(0.0, _length(coords), SAMPLES)
    xs, ys = _walk(coords, stations)
    rows = [(float(s), before.sample(x, y), after.sample(x, y)) for s, x, y in zip(stations, xs, ys)]
    rows = [row for row in rows if not (math.isnan(row[1]) or math.isnan(row[2]))]
    if not rows:
        return empty
    out = tuple(zip(*rows))
    return {"stations": out[0], "before": out[1], "after": out[2]}


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
                         UNDO_PROFILE, UNDO_RENAME, UNDO_REORDER, UNDO_SECTION_LINE, UNDO_SETTINGS, UNDO_SHAPE,
                         UNDO_TURN_OFF, UNDO_TURN_ON, VIEW_3D_NO_LAYER)
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
    if fields == {"section_line"}:
        return UNDO_SECTION_LINE.format(feature.name), None
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
EXPORT_ADD_FAILED = ("The exported DEM {} could not be added to the project; see the 'Terrain Sketch' log tab "
                     "for details.")

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
UNDO_SECTION_LINE = "Move the section line of {}"
COPY_NAME = "{} (copy)"

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It is the project's terrain, but only a temporary one, "
               "even if you save the project meanwhile: the terrain you had before is put back when this "
               "session ends.")
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
AREA_SECTION_EMPTY_HINT = "There is no terrain to show along this feature's section line."
AREA_SECTION_NOTE = ("A section through the area along the dashed line on the map: dashed here is the ground "
                     "before this feature, solid is the result. Shape the sides with the cross profile on the left.")
DRAW_SECTION_TIP = "Draw the line on the map that this section runs along."
RESET_SECTION_TIP = "Put the section line back through the middle of the area, along its longer side."
SECTION_LINE_HINT = ("Click to draw the section line. Right-click or press Enter to finish, Backspace removes the "
                     "last point, Esc cancels.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
CROSS_SIDES_TIP = ("A section across the path, looking along it in the direction it was drawn: its left side "
                   "on the left. Drag the crest edges to change the width, and the ends of the slopes to change "
                   "their steepness and reach; double-click to add a break point, such as a berm, and "
                   "right-click to remove one.")
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
from ..qgis_io.convert import from_wkb
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .controller import LOG_TAG
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED, EXPORT_REPLACE,
                         REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                         SCENARIO_SAVED, SECTION_LINE_HINT, SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING,
                         UNSAVED_CHANGES, VIEW_3D_NOT_OPENED, VIEW_3D_TIP)
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
        self._asked_about_unsaved = False
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self._brush_extends = False       # set with _brush_fid, but kept when that feature goes
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)
        self.section_band = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)   # an area's section line
        self.section_band.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.section_band.setWidth(QgsMapToolEdit.digitizingStrokeWidth())
        self.section_band.setLineStyle(Qt.PenStyle.DashLine)

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
        self.export_button = _file_button(
            "/mActionSharingExport.svg", self.tr("Export DEM…"),
            self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
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
            profiles.drawSectionRequested.connect(self._draw_section_line)
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
        self.draw_tool = DrawLineTool(self.iface.mapCanvas())
        self.draw_tool.finished.connect(lambda geometry, f=fid: self._section_drawn(f, geometry))
        self._activate_drawing(SECTION_LINE_HINT)

    def _section_drawn(self, fid: str, geometry) -> None:
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
                if self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
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

**File:** `terrain_sketch/gui/profile_dock.py`
```python
"""Bottom dock: the cross profile and the long profile of the selected feature, side by side."""
from __future__ import annotations

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                                 QWidget)

from ..core.sections import (cross_section, set_cross_section, set_whole_cross_section, supports_long_profile,
                             whole_cross_section)
from ..core.tools import TOOL_INFO, Mode
from .help_texts import (AREA_SECTION_EMPTY_HINT, AREA_SECTION_NOTE, CROSS_SIDES_TIP, CUSTOM_PROFILE_NOTE,
                         DRAW_SECTION_TIP, MULTIPART_LONG_SECTION_NOTE, RESET_SECTION_TIP, SYMMETRIC_TIP)
from . import settings
from .profile_widget import Kind, ProfileWidget


class ProfileDock(QgsDockWidget):
    """Shows the selected feature's shape and writes every edit back through the controller."""

    drawSectionRequested = pyqtSignal(str)   # feature id: draw the section line of this area on the map

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
        self.cross.symmetric = True
        self.symmetric.toggled.connect(self._symmetric_toggled)
        self.reset_cross = QPushButton(self.tr("Reset shape"))
        self.reset_long = QPushButton(self.tr("Reset to rule"))
        self.draw_section = QPushButton(self.tr("Draw section line"))
        self.draw_section.setToolTip(DRAW_SECTION_TIP)
        self.reset_section = QPushButton(self.tr("Reset line"))
        self.reset_section.setToolTip(RESET_SECTION_TIP)
        self.note = QLabel()
        self.note.setWordWrap(True)

        body = QWidget()
        layout = QVBoxLayout(body)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        for title, widget, controls in (
                (self.tr("Cross profile"), self.cross, (self.symmetric, self.reset_cross)),
                (self.tr("Long profile"), self.long, (self.draw_section, self.reset_section, self.reset_long))):
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
        self.draw_section.clicked.connect(self._draw_section)
        self.reset_section.clicked.connect(self._reset_section)
        controller.featuresChanged.connect(self._refresh)
        controller.sessionChanged.connect(self._session_changed)
        self.show_feature(None)

    def show_feature(self, fid) -> None:
        """Load a feature's profiles, or clear both panels when there is no selection."""
        self._fid = fid
        if fid is None or not self.controller.has_dem:
            self.cross.setToolTip("")
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
            self.cross.setToolTip(CROSS_SIDES_TIP if is_path and info.has_slopes else "")   # it is about sides
            # A path shows both sides around its centre line; an area shows its one edge slope, and
            # takes no break points: the engine discards an area's (spec 5.4).
            if is_path:
                self.cross.set_profile(whole_cross_section(feature), editable=info.has_slopes, mirrored=True)
            else:
                self.cross.set_profile(cross_section(feature, side=1), editable=info.has_slopes,
                                       allow_breaks=False)
            self.symmetric.setEnabled(info.has_slopes and is_path)
            self.reset_cross.setEnabled(info.has_slopes)
            if feature.mode is Mode.AREA:
                self._show_area_section()
            else:
                self._show_long_section(feature)
        finally:
            self._loading = False

    def _show_area_section(self) -> None:
        """An area has no long profile; the right-hand panel shows a read-only section through it
        instead, the ground before and after the feature (spec §5.4)."""
        area = self.controller.area_section(self._fid)
        self.long.set_profile(tuple(zip(area["stations"], area["after"])),
                              terrain=tuple(zip(area["stations"], area["before"])), editable=False,
                              hint=AREA_SECTION_EMPTY_HINT)
        self.note.setText(AREA_SECTION_NOTE)
        self._show_section_buttons(True)
        self.draw_section.setEnabled(True)
        self.reset_section.setEnabled(self.controller.find(self._fid).section_line is not None)

    def _show_long_section(self, feature) -> None:
        self._show_section_buttons(False)
        section = self.controller.long_section(self._fid)
        if not supports_long_profile(feature):
            # A multi-part path: the engine follows the tool rule whatever is stored here.
            self.long.set_profile(section["design"], terrain=self._pairs(section),
                                  editable=False)
            self.note.setText(MULTIPART_LONG_SECTION_NOTE)
        else:
            self.long.set_profile(section["design"], terrain=self._pairs(section))
            self.note.setText(CUSTOM_PROFILE_NOTE if section["custom"] else "")
        self.reset_long.setEnabled(bool(section["custom"]))

    @staticmethod
    def _pairs(section) -> tuple:
        return tuple(zip(section["stations"], section["terrain"]))

    def _cross_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        feature = self.controller.find(self._fid)
        if feature is None:
            return
        try:
            if feature.mode is Mode.PATH:
                changes = set_whole_cross_section(feature, points, symmetric=self.symmetric.isChecked())
            else:
                changes = set_cross_section(feature, 1, points)
        except ValueError:
            return            # a side without its crest edge; the plot never sends one, and this is a slot
        self._apply(changes, commit)

    def _long_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        self._apply({"long_profile": tuple((float(s), float(z)) for s, z in points)}, commit)

    def _apply(self, changes: dict, commit: bool) -> None:
        if commit:
            self.controller.update_profile(self._fid, **changes)
        else:
            self.controller.preview(self._fid, **changes)

    def _reset_cross(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, cross_left=(), cross_right=())

    def _reset_long(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, long_profile=None)

    def _show_section_buttons(self, area: bool) -> None:
        """An area's panel has a section line to draw or reset; a path's has a long profile to reset."""
        self.draw_section.setVisible(area)
        self.reset_section.setVisible(area)
        self.reset_long.setVisible(not area)

    def _draw_section(self) -> None:
        if self._fid is not None:
            self.drawSectionRequested.emit(self._fid)

    def _reset_section(self) -> None:
        if self._fid is not None:
            self.controller.set_section_line(self._fid, None)

    def _symmetric_toggled(self, checked: bool) -> None:
        self.cross.symmetric = checked

    def _session_changed(self) -> None:
        if not self.controller.has_dem:
            self.show_feature(None)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.symmetric, self.reset_cross, self.reset_long, self.draw_section, self.reset_section):
            widget.setEnabled(enabled)

    def shutdown(self) -> None:
        self.controller.cancel_preview()
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_section_line.py` → Expected: `8 passed`
Run: `scripts/test.sh` → Expected: `501 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/core/sections.py terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/gui/profile_dock.py tests/qgis/test_section_line.py
git commit -m "feat(gui): draw, show and reset the line an area's section runs along"
```

---

### Task 6: Guidance labels, the pixel picture and clearer tool pictures

The SVG files below are complete replacements; write them byte for byte.

**Files:**
- Modify: `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/illustrations/__init__.py`, `terrain_sketch/gui/illustrations/pixels_all_touched.svg`, `terrain_sketch/gui/illustrations/pixels_centre.svg`, `terrain_sketch/gui/illustrations/pixels_fully_inside.svg`, `terrain_sketch/gui/illustrations/tool_add.svg`, `terrain_sketch/gui/illustrations/tool_interpolate.svg`, `terrain_sketch/gui/illustrations/tool_lower_flat.svg`, `terrain_sketch/gui/illustrations/tool_lower_path.svg`, `terrain_sketch/gui/illustrations/tool_raise_flat.svg`, `terrain_sketch/gui/illustrations/tool_raise_path.svg`, `terrain_sketch/gui/illustrations/tool_subtract.svg`, `terrain_sketch/gui/properties_page.py`
- Test: `tests/qgis/test_guidance.py`, `tests/qgis/test_illustrations.py`, `tests/qgis/test_panels.py`

**Interfaces:**
- Consumes: `help_texts.amount_label`, `FIELD_TIPS`, `PIXEL_MODE_LABELS`; `illustrations.pixmap`; `PropertiesPage._draw_pictures`, `show_feature`.
- Produces: `help_texts.AMOUNT_LABELS`, `amount_label(tool, mode) -> str | None`; `illustrations.data_uri(name, size, palette) -> str`; `properties_page.PIXEL_PICTURE`, `PropertiesPage._pixel_modes_tip() -> str`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_guidance.py`
```python
from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtGui import QFocusEvent, QPalette

from qgis_helpers import UTM, line_through, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.help_texts import PIXEL_MODE_LABELS, TOOL_DESCRIPTIONS, TOOL_EXAMPLES
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
    gallery.setPalette(dark)   # delivers QEvent.PaletteChange, which must redraw them by itself
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
    assert page.about.objectName() == "TerrainSketchAboutTool"
    page.about.setCollapsed(True)
    assert page.about.isCollapsed()


def test_the_amount_label_says_what_the_height_or_depth_is_measured_from():
    """"Height" alone let users measure a flat pad from the ground under it rather than from its
    highest point (spec §7.2: the label depends on the tool)."""
    from terrain_sketch.core.tools import TOOL_INFO
    from terrain_sketch.gui.help_texts import amount_label
    labels = {}
    for tool in Tool:
        for mode in TOOL_INFO[tool].modes:
            labels[(tool, mode)] = amount_label(tool, mode)
    assert labels.pop((Tool.INTERPOLATE, Mode.PATH)) is None and labels.pop((Tool.INTERPOLATE, Mode.AREA)) is None
    for (tool, _mode), label in labels.items():
        lowers = tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT)
        assert label.startswith("Depth" if lowers else "Height"), label
        assert len(label.split()) > 1, label                     # never the bare word
    assert "highest" in labels[(Tool.RAISE_FLAT, Mode.PATH)] and "lowest" in labels[(Tool.LOWER_FLAT, Mode.AREA)]
    assert labels[(Tool.RAISE_PATH, Mode.PATH)] != labels[(Tool.RAISE_FLAT, Mode.PATH)]


def test_the_pixels_tooltip_shows_the_three_modes_side_by_side_in_the_theme(tmp_path):
    import base64
    from qgis.PyQt.QtGui import QImage
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(pond.id)
    tip = page.pixel_mode.toolTip()
    images = tip.split('src="data:image/png;base64,')[1:]
    assert len(images) == 3
    for mode in PixelMode:
        assert f">{PIXEL_MODE_LABELS[mode]}<" in tip
    first = QImage.fromData(base64.b64decode(images[0].split('"')[0]))
    assert not first.isNull() and first.width() == 72

    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Mid, Qt.GlobalColor.white)
    dark.setColor(QPalette.ColorRole.Highlight, Qt.GlobalColor.yellow)
    page.setPalette(dark)                                       # the theme changes
    assert page.pixel_mode.toolTip() != tip
```

**File:** `tests/qgis/test_illustrations.py`
```python
import re

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
    """A key the template does not tag must emphasise nothing, not dim the whole diagram: that is
    what a renamed part in an SVG would otherwise do, silently."""
    source = illustrations.svg_source("parameters", light(), highlight="nope")
    assert source.count('opacity="1"') == 4 and '0.25' not in source


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


def point_in_polygon(point, polygon):
    """Ray casting algorithm for point-in-polygon test."""
    x, y = point
    n = len(polygon)
    inside = False
    x1, y1 = polygon[0]
    for i in range(1, n + 1):
        x2, y2 = polygon[i % n]
        if y > min(y1, y2):
            if y <= max(y1, y2):
                if x <= max(x1, x2):
                    if y1 != y2:
                        xinters = (y - y1) * (x2 - x1) / (y2 - y1) + x1
                    if x1 == x2 or x <= xinters:
                        inside = not inside
        x1, y1 = x2, y2
    return inside


def parse_filled_cells_from_svg(svg_path):
    """Extract filled cell coordinates from pixels_*.svg file."""
    source = open(svg_path).read()
    cells = set()
    for match in re.finditer(r'<rect\s+x="(\d+)"\s+y="(\d+)"\s+width="16"\s+height="16"\s+fill=', source):
        x, y = int(match.group(1)), int(match.group(2))
        cells.add((x, y))
    return cells


def cell_centre_inside_polygon(cell_x, cell_y, polygon):
    """Check if the centre of a cell (x, y in SVG coords) is inside the polygon."""
    centre_x = cell_x + 8
    centre_y = cell_y + 8
    return point_in_polygon((centre_x, centre_y), polygon)


def cell_fully_inside_polygon(cell_x, cell_y, polygon):
    """Check if all four corners of a cell are inside the polygon."""
    corners = [
        (cell_x, cell_y),
        (cell_x + 16, cell_y),
        (cell_x + 16, cell_y + 16),
        (cell_x, cell_y + 16),
    ]
    return all(point_in_polygon(corner, polygon) for corner in corners)


def test_pixels_centre_fills_cells_whose_centre_is_inside():
    """Verify pixels_centre.svg fills only cells whose centre falls inside the outline."""
    outline = [(12, 26), (43, 20), (44, 51), (11, 54)]
    svg_file = illustrations.HERE / "pixels_centre.svg"
    filled = parse_filled_cells_from_svg(svg_file)

    expected_filled = set()
    for cell_x in [8, 24, 40]:
        for cell_y in [8, 24, 40]:
            if cell_centre_inside_polygon(cell_x, cell_y, outline):
                expected_filled.add((cell_x, cell_y))

    assert filled == expected_filled, f"pixels_centre filled {filled}, expected {expected_filled}"


def test_pixels_all_touched_fills_all_cells_the_outline_crosses():
    """Verify pixels_all_touched.svg fills every cell the outline touches."""
    outline = [(12, 26), (43, 20), (44, 51), (11, 54)]
    svg_file = illustrations.HERE / "pixels_all_touched.svg"
    filled = parse_filled_cells_from_svg(svg_file)

    expected_filled = set()
    for cell_x in [8, 24, 40]:
        for cell_y in [8, 24, 40]:
            corners = [
                (cell_x, cell_y),
                (cell_x + 16, cell_y),
                (cell_x + 16, cell_y + 16),
                (cell_x, cell_y + 16),
            ]
            if any(point_in_polygon(corner, outline) for corner in corners):
                expected_filled.add((cell_x, cell_y))

    assert filled == expected_filled, f"pixels_all_touched filled {filled}, expected {expected_filled}"


def test_pixels_fully_inside_fills_only_cells_entirely_within_the_outline():
    """Verify pixels_fully_inside.svg fills only cells lying entirely within the outline."""
    outline = [(12, 26), (43, 20), (44, 51), (11, 54)]
    svg_file = illustrations.HERE / "pixels_fully_inside.svg"
    filled = parse_filled_cells_from_svg(svg_file)

    expected_filled = set()
    for cell_x in [8, 24, 40]:
        for cell_y in [8, 24, 40]:
            if cell_fully_inside_polygon(cell_x, cell_y, outline):
                expected_filled.add((cell_x, cell_y))

    assert filled == expected_filled, f"pixels_fully_inside filled {filled}, expected {expected_filled}"


def path_points(d):
    """The vertices of an SVG path written with absolute M and L commands only."""
    return [(float(x), float(y)) for x, y in re.findall(r"[ML]\s*(-?[\d.]+)\s+(-?[\d.]+)", d)]


def drawn_path(source, attribute, colour):
    """The `d` of the first path whose `attribute` is `colour` (a colour token, unrendered)."""
    for d, value in re.findall(r'<path\s+d="([^"]+)"[^>]*?\s' + attribute + r'="([^"]+)"', source):
        if value == colour:
            return d
    raise AssertionError(f"no path with {attribute}={colour}")


def height_at(polyline, x):
    """The y of a polyline at x, interpolated straight between the vertices around it."""
    for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
        if x1 <= x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    raise AssertionError(f"x={x} lies outside the drawn terrain")


def test_the_add_and_subtract_bands_stay_parallel_to_the_terrain():
    """Add and Subtract shift every cell by the same amount, so the band they draw has to keep a
    constant distance from the ground. A band that pinches or bows shows relief the tool never
    makes — and the descriptions beside these pictures promise the terrain keeps its shape."""
    for name, band in (("tool_add", "{fill}"), ("tool_subtract", "{cut}")):
        source = (illustrations.HERE / f"{name}.svg").read_text()
        ground = path_points(drawn_path(source, "stroke", "{terrain}"))
        surface = path_points(drawn_path(source, "stroke", "{line}"))
        assert len(surface) >= 3, name
        offsets = [height_at(ground, x) - y for x, y in surface]
        assert max(offsets) - min(offsets) < 1.0, f"{name} surface is not parallel: {offsets}"
        # and the band between the two lines closes on the ground, with nothing floating between
        for x, y in path_points(drawn_path(source, "fill", band)):
            on_surface = any(abs(x - sx) < 0.01 and abs(y - sy) < 0.01 for sx, sy in surface)
            assert on_surface or abs(height_at(ground, x) - y) < 1.0, \
                f"{name} band vertex ({x}, {y}) is neither on its surface nor on the ground"



def svg_source(name):
    return (illustrations.HERE / f"{name}.svg").read_text()


def filled_regions(source, colour):
    return [path_points(d) for d, value in re.findall(r'<path\s+d="([^"]+)"[^>]*?\sfill="([^"]+)"', source)
            if value == colour]


def test_the_bands_of_the_raise_and_lower_tools_close_along_the_drawn_ground():
    """A band closed with a straight base across a wavy ground leaves a gap where the ground dips
    below the base, or covers the ground where it rises above."""
    for name, colour in (("tool_raise_path", "{fill}"), ("tool_raise_flat", "{fill}"),
                         ("tool_lower_path", "{cut}"), ("tool_lower_flat", "{cut}")):
        source = svg_source(name)
        ground = path_points(drawn_path(source, "stroke", "{terrain}"))
        regions = filled_regions(source, colour)
        assert regions, name
        for region in regions:
            xs = [x for x, _y in region]
            vertices = {(round(x, 2), round(y, 2)) for x, y in region}
            for gx, gy in ground:
                if min(xs) < gx < max(xs):
                    assert (gx, gy) in vertices, f"{name} band skips the ground vertex ({gx}, {gy})"


def test_path_tools_follow_the_ground_between_the_ends_and_flat_tools_are_level():
    """The four raise and lower pictures used to share one trapezoid; what tells them apart is
    whether the built surface is level (flat) or runs from end to end with the ground (path)."""
    def built_heights(name):
        lines = [path_points(d) for d, value in
                 re.findall(r'<path\s+d="([^"]+)"[^>]*?\sstroke="([^"]+)"', svg_source(name)) if value == "{line}"]
        return [y for line in lines for _x, y in line[1:-1]]        # without the two end slopes' feet
    for flat in ("tool_raise_flat", "tool_lower_flat"):
        heights = built_heights(flat)
        assert max(heights) - min(heights) < 0.01, flat
    for path in ("tool_raise_path", "tool_lower_path"):
        heights = built_heights(path)
        assert max(heights) - min(heights) > 5.0, path


def test_interpolate_shows_both_what_it_fills_and_what_it_cuts():
    source = svg_source("tool_interpolate")
    assert filled_regions(source, "{fill}") and filled_regions(source, "{cut}")


def test_every_cell_centre_is_clear_of_the_outline_and_drawn_on_top_of_it():
    """A centre dot under the outline cannot be seen to be inside or outside it."""
    source = svg_source("pixels_centre")
    outline = path_points(re.search(r'<path\s+d="([^"]+)"', source).group(1))
    for cx, cy in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', source):
        px, py = float(cx), float(cy)
        for (ax, ay), (bx, by) in zip(outline, outline[1:] + outline[:1]):
            t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
            assert ((px - ax - t * (bx - ax)) ** 2 + (py - ay - t * (by - ay)) ** 2) ** 0.5 >= 3.0, (px, py)
    assert source.index("<circle") > source.index("<path")
```

**File:** `tests/qgis/test_panels.py`
```python
import pytest
from qgis.core import Qgis, QgsApplication, QgsCoordinateReferenceSystem

from qgis_helpers import UTM, line_layer, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.selection import EDIT_ICON, METHOD_ICONS, Method
from terrain_sketch.gui.tool_gallery import ToolGallery


def test_gallery_offers_only_the_shapes_and_methods_a_tool_supports():
    gallery = ToolGallery()
    gallery.select_tool(Tool.RAISE_PATH)
    assert gallery.line_mode.isEnabled() and not gallery.area_mode.isEnabled()
    assert gallery.selected_mode() is Mode.PATH
    assert gallery.method_buttons[Method.FREEHAND].isEnabled()
    assert not gallery.method_buttons[Method.BRUSH].isEnabled() and not gallery.brush_spin.isEnabled()
    gallery.select_tool(Tool.LOWER_FLAT)
    gallery.select_mode(Mode.AREA)
    assert gallery.method_buttons[Method.BRUSH].isEnabled() and gallery.brush_spin.isEnabled()
    requests = []
    gallery.drawRequested.connect(lambda tool, mode, method: requests.append((tool, mode, method)))
    gallery.method_buttons[Method.FREEHAND].click()
    assert requests == [(Tool.LOWER_FLAT, Mode.AREA, Method.FREEHAND)]
    gallery.method_buttons[Method.LAYER].click()
    assert not gallery.layer_source.isHidden() and len(requests) == 1  # the layer form asks first


def test_layer_form_reports_the_chosen_layer(tmp_path):
    gallery = ToolGallery()
    gallery.select_tool(Tool.RAISE_PATH)
    layer = line_layer("Planned dikes", [line_through(5, 10, 30, 10)])
    gallery.layer_source.layer_combo.setLayer(layer)
    gallery.layer_source.selected_only.setChecked(True)
    asked = []
    gallery.layerRequested.connect(lambda tool, mode, lyr, only: asked.append((tool, mode, lyr.name(), only)))
    gallery.layer_source.use_button.click()
    assert asked == [(Tool.RAISE_PATH, Mode.PATH, "Planned dikes", True)]


def test_properties_show_the_tool_fields_and_apply_changes(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert all(w.toolTip() for w in (page.amount, page.width, page.slope, page.reach, page.slope_position))
    assert page.amount_label.text() == "Height above the path"
    assert page.form.isRowVisible(page.width) and page.form.isRowVisible(page.slope)
    assert not page.form.isRowVisible(page.slope_position)
    page.amount.setValue(2.5)
    assert c.feature(dike.id).amount == 2.5 and sample(c.layers.working, 20, 20) == pytest.approx(12.5)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    page.show_feature(pond.id)
    assert page.amount_label.text() == "Depth below the lowest edge" and not page.form.isRowVisible(page.width)
    assert page.form.isRowVisible(page.slope_position) and page.slope_position.currentData() is True
    page.pixel_mode.setCurrentIndex(page.pixel_mode.findData(PixelMode.ALL_TOUCHED.value))
    assert c.feature(pond.id).pixel_mode is PixelMode.ALL_TOUCHED


def test_every_panel_icon_exists_in_the_qgis_theme():
    """getThemeIcon returns a null icon for an unknown name, and the button then renders blank."""
    for name in (*METHOD_ICONS.values(), EDIT_ICON):
        assert not QgsApplication.getThemeIcon(name).isNull(), name


def test_the_brush_radius_is_labelled_with_the_units_it_is_really_in():
    gallery = ToolGallery()
    gallery.set_radius_units(QgsCoordinateReferenceSystem("EPSG:25832").mapUnits())
    assert gallery.brush_spin.suffix() == " m"
    gallery.set_radius_units(QgsCoordinateReferenceSystem("EPSG:4326").mapUnits())
    assert gallery.brush_spin.suffix() == " degrees"
    gallery.set_radius_units(Qgis.DistanceUnit.Unknown)
    assert gallery.brush_spin.suffix() == " map units"
```
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/qgis/test_guidance.py`
Expected: exit code 1 with `TypeError: amount_label() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Implement**

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
from ..core.tools import Mode, PixelMode, Tool

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
EXPORT_ADD_FAILED = ("The exported DEM {} could not be added to the project; see the 'Terrain Sketch' log tab "
                     "for details.")

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
UNDO_SECTION_LINE = "Move the section line of {}"
COPY_NAME = "{} (copy)"

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It is the project's terrain, but only a temporary one, "
               "even if you save the project meanwhile: the terrain you had before is put back when this "
               "session ends.")
VIEW_3D_NOT_OPENED = ("The modified DEM is now the project's terrain, but Terrain Sketch could not open a "
                      "3D view. Open one with View ▸ 3D Map Views ▸ New 3D Map View.")
VIEW_3D_NO_LAYER = ("The Modified DEM layer is no longer in the project, so there is nothing to show in 3D. "
                    "Press Start to create it again.")


# The amount field says what it is measured from (spec §7.2): a height "above the path" and one "above
# the highest point" are different numbers for the same dike, and a bare "Height" let users set the wrong one.
AMOUNT_LABELS = {
    (Tool.RAISE_PATH, Mode.PATH): "Height above the path",
    (Tool.LOWER_PATH, Mode.PATH): "Depth below the path",
    (Tool.RAISE_FLAT, Mode.PATH): "Height above the highest point",
    (Tool.RAISE_FLAT, Mode.AREA): "Height above the highest edge",
    (Tool.LOWER_FLAT, Mode.PATH): "Depth below the lowest point",
    (Tool.LOWER_FLAT, Mode.AREA): "Depth below the lowest edge",
    (Tool.ADD, Mode.PATH): "Height added",
    (Tool.ADD, Mode.AREA): "Height added",
    (Tool.SUBTRACT, Mode.PATH): "Depth removed",
    (Tool.SUBTRACT, Mode.AREA): "Depth removed",
}


def amount_label(tool: Tool, mode: Mode) -> str | None:
    """Label of the amount field, or None when the tool has no amount (Interpolate)."""
    return AMOUNT_LABELS.get((tool, mode))

PROFILE_EMPTY_HINT = "Select or draw a feature to edit its shape here."
CUSTOM_PROFILE_NOTE = ("Custom long profile: the heights are fixed and no longer follow the "
                       "terrain underneath. Use Reset to rule to go back.")
AREA_SECTION_EMPTY_HINT = "There is no terrain to show along this feature's section line."
AREA_SECTION_NOTE = ("A section through the area along the dashed line on the map: dashed here is the ground "
                     "before this feature, solid is the result. Shape the sides with the cross profile on the left.")
DRAW_SECTION_TIP = "Draw the line on the map that this section runs along."
RESET_SECTION_TIP = "Put the section line back through the middle of the area, along its longer side."
SECTION_LINE_HINT = ("Click to draw the section line. Right-click or press Enter to finish, Backspace removes the "
                     "last point, Esc cancels.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
CROSS_SIDES_TIP = ("A section across the path, looking along it in the direction it was drawn: its left side "
                   "on the left. Drag the crest edges to change the width, and the ends of the slopes to change "
                   "their steepness and reach; double-click to add a break point, such as a berm, and "
                   "right-click to remove one.")
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

from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
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
    point at width, height, slope or reach depending on which field has focus. A `highlight` this
    template does not tag emphasises nothing rather than dimming the whole picture: renaming a
    part key in an SVG must not silently turn the diagram grey.
    """
    text = (HERE / f"{name}.svg").read_text()
    for token, value in colours(palette).items():
        text = text.replace("{" + token + "}", value)
    keys = tagged_parts(text)
    if highlight not in keys:
        highlight = None
    for key in keys:
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


def data_uri(name: str, size, palette: QPalette) -> str:
    """The illustration as a PNG `data:` URI, for an `<img>` in rich text such as a tooltip."""
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap(name, size, palette).save(buffer, "PNG")
    buffer.close()
    return "data:image/png;base64," + bytes(data.toBase64()).decode("ascii")


def available() -> list[str]:
    """Every illustration name that ships with the plugin."""
    return sorted(p.stem for p in HERE.glob("*.svg"))
```

Replace the whole file:

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
  <path d="M12 26 L43 20 L44 51 L11 54 Z" fill="none" stroke="{line}" stroke-width="2"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/pixels_centre.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="8" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="24" y="24" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="8" y="40" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <rect x="24" y="40" width="16" height="16" fill="{fill}" opacity="0.45"/>
  <line x1="8" y1="8" x2="8" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="8" x2="56" y2="8" stroke="{terrain}" stroke-width="1"/>
  <line x1="24" y1="8" x2="24" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="24" x2="56" y2="24" stroke="{terrain}" stroke-width="1"/>
  <line x1="40" y1="8" x2="40" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="40" x2="56" y2="40" stroke="{terrain}" stroke-width="1"/>
  <line x1="56" y1="8" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <line x1="8" y1="56" x2="56" y2="56" stroke="{terrain}" stroke-width="1"/>
  <path d="M12 26 L43 20 L44 51 L11 54 Z" fill="none" stroke="{line}" stroke-width="2"/>
  <circle cx="16" cy="16" r="1.6" fill="{text}"/>
  <circle cx="32" cy="16" r="1.6" fill="{text}"/>
  <circle cx="48" cy="16" r="1.6" fill="{text}"/>
  <circle cx="16" cy="32" r="1.6" fill="{text}"/>
  <circle cx="32" cy="32" r="1.6" fill="{text}"/>
  <circle cx="48" cy="32" r="1.6" fill="{text}"/>
  <circle cx="16" cy="48" r="1.6" fill="{text}"/>
  <circle cx="32" cy="48" r="1.6" fill="{text}"/>
  <circle cx="48" cy="48" r="1.6" fill="{text}"/>
</svg>
```

Replace the whole file:

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
  <path d="M12 26 L43 20 L44 51 L11 54 Z" fill="none" stroke="{line}" stroke-width="2"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/tool_add.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 47 L20 45 L30 46 L38 53 L46 46 L62 41 L72 28 L80 38 L100 35 L120 33" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M20 36 L30 37 L38 44 L46 37 L62 32 L72 19 L80 29 L100 26 L100 35 L80 38 L72 28 L62 41 L46 46 L38 53 L30 46 L20 45 Z" fill="{fill}" opacity="0.45"/>
  <path d="M20 36 L30 37 L38 44 L46 37 L62 32 L72 19 L80 29 L100 26" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M60 6 L60 18 M54 12 L66 12" stroke="{fill}" stroke-width="3" stroke-linecap="round"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/tool_interpolate.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 47 L20 45 L30 46 L38 53 L46 46 L62 41 L72 28 L80 38 L100 35 L120 33" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round" stroke-dasharray="3 3" opacity="0.55"/>
  <path d="M20 45 L30 43.75 L38 42.75 L46 41.75 L62 39.75 L63.06 39.62 L62 41 L46 46 L38 53 L30 46 Z" fill="{fill}" opacity="0.45"/>
  <path d="M79.64 37.55 L80 37.5 L100 35 L80 38 Z" fill="{fill}" opacity="0.45"/>
  <path d="M63.06 39.62 L72 38.5 L79.64 37.55 L72 28 Z" fill="{cut}" opacity="0.45"/>
  <path d="M20 45 L100 35" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/tool_lower_flat.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 47 L20 45 L30 46 L38 53 L46 46 L62 41 L72 28 L80 38 L100 35 L120 33" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M12 45.8 L20 54 L30 54 L38 54 L46 54 L62 54 L72 54 L80 54 L100 54 L108 34.2 L100 35 L80 38 L72 28 L62 41 L46 46 L38 53 L30 46 L20 45 Z" fill="{cut}" opacity="0.45"/>
  <path d="M12 45.8 L20 54 L30 54 L38 54 L46 54 L62 54 L72 54 L80 54 L100 54 L108 34.2" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/tool_lower_path.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 47 L20 45 L30 46 L38 53 L46 46 L62 41 L72 28 L80 38 L100 35 L120 33" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M12 45.8 L20 54 L30 52.75 L36.75 51.91 L30 46 L20 45 Z" fill="{cut}" opacity="0.45"/>
  <path d="M39.67 51.54 L46 50.75 L62 48.75 L72 47.5 L80 46.5 L100 44 L108 34.2 L100 35 L80 38 L72 28 L62 41 L46 46 Z" fill="{cut}" opacity="0.45"/>
  <path d="M12 45.8 L20 54 L30 52.75 L36.75 51.91" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M39.67 51.54 L46 50.75 L62 48.75 L72 47.5 L80 46.5 L100 44 L108 34.2" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/tool_raise_flat.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 47 L20 45 L30 46 L38 53 L46 46 L62 41 L72 28 L80 38 L100 35 L120 33" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M12 45.8 L20 26 L30 26 L38 26 L46 26 L62 26 L72 26 L80 26 L100 26 L108 34.2 L100 35 L80 38 L72 28 L62 41 L46 46 L38 53 L30 46 L20 45 Z" fill="{fill}" opacity="0.45"/>
  <path d="M12 45.8 L20 26 L30 26 L38 26 L46 26 L62 26 L72 26 L80 26 L100 26 L108 34.2" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/tool_raise_path.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 47 L20 45 L30 46 L38 53 L46 46 L62 41 L72 28 L80 38 L100 35 L120 33" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M12 45.8 L20 36 L30 34.75 L38 33.75 L46 32.75 L62 30.75 L70.72 29.66 L62 41 L46 46 L38 53 L30 46 L20 45 Z" fill="{fill}" opacity="0.45"/>
  <path d="M73.09 29.36 L80 28.5 L100 26 L108 34.2 L100 35 L80 38 Z" fill="{fill}" opacity="0.45"/>
  <path d="M12 45.8 L20 36 L30 34.75 L38 33.75 L46 32.75 L62 30.75 L70.72 29.66" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M73.09 29.36 L80 28.5 L100 26 L108 34.2" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/illustrations/tool_subtract.svg`
```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 64">
  <path d="M0 47 L20 45 L30 46 L38 53 L46 46 L62 41 L72 28 L80 38 L100 35 L120 33" fill="none" stroke="{terrain}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M20 54 L30 55 L38 62 L46 55 L62 50 L72 37 L80 47 L100 44 L100 35 L80 38 L72 28 L62 41 L46 46 L38 53 L30 46 L20 45 Z" fill="{cut}" opacity="0.45"/>
  <path d="M20 54 L30 55 L38 62 L46 55 L62 50 L72 37 L80 47 L100 44" fill="none" stroke="{line}" stroke-width="2" stroke-linejoin="round"/>
  <path d="M54 12 L66 12" stroke="{cut}" stroke-width="3" stroke-linecap="round"/>
</svg>
```

Replace the whole file:

**File:** `terrain_sketch/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

import html
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
PIXEL_PICTURE = 72   # each of the three pictures in the Pixels to change tooltip


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
        self.amount_label.setWordWrap(True)   # "Height above the highest point" must not set the panel's width
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
        controller.featuresChanged.connect(self._refresh_values)
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
        self.pixel_mode.setToolTip(self._pixel_modes_tip())

    def _pixel_modes_tip(self) -> str:
        """The field's tip with the three pixel modes side by side under it (spec §7.2), drawn in the
        current theme's colours like every other picture on the page."""
        size = PIXEL_PICTURE
        pictures = "".join(
            f'<td align="center"><img src="{illustrations.data_uri(f"pixels_{mode.value}", size, self.palette())}"'
            f' width="{size}" height="{size}"/></td>' for mode in PixelMode)
        names = "".join(f'<td align="center">{html.escape(PIXEL_MODE_LABELS[mode])}</td>' for mode in PixelMode)
        return f"<p>{html.escape(FIELD_TIPS['pixel_mode'])}</p><table><tr>{pictures}</tr><tr>{names}</tr></table>"

    def show_feature(self, fid: str) -> None:
        self._fid = fid
        feature = self.controller.feature(fid)
        info = TOOL_INFO[feature.tool]
        label = amount_label(feature.tool, feature.mode)
        self._loading = True
        try:
            self.title.setText(_title(feature))
            self.summary.setText(TOOL_SUMMARIES[feature.tool])
            self.amount_label.setText(label or "")
            self._load_values(feature)
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

    def _load_values(self, feature) -> None:
        """Show the feature's values in the fields — except in a field the user is still typing in:
        a change from elsewhere (a profile drag, an undo) must not throw away what they typed."""
        # Only a profile the engine actually uses fixes the heights: on a multi-part path it
        # is discarded, and Height/Depth is then the one control that still drives the result.
        custom = feature.long_profile is not None and supports_long_profile(feature)
        for spin, value in ((self.amount, feature.amount), (self.width, feature.width),
                            (self.slope, feature.slope_n), (self.reach, feature.reach)):
            if not spin.lineEdit().isModified():
                spin.setValue(value)
        self.amount.setEnabled(not custom)
        self.amount.setToolTip(AMOUNT_IS_CUSTOM if custom else self._amount_tip)
        self.slope_position.setCurrentIndex(1 if feature.slopes_inside else 0)
        self.pixel_mode.setCurrentIndex(self.pixel_mode.findData(feature.pixel_mode.value))

    def _refresh_values(self) -> None:
        """Keep the fields in step with the feature whenever the list changes: a cross-profile drag
        moves the width, slope and reach, and an undo can change anything. Runs in a slot."""
        try:
            feature = self.controller.find(self._fid) if self._fid is not None else None
            if feature is None:
                return
            self._loading = True
            try:
                self._load_values(feature)
            finally:
                self._loading = False
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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

Run: `scripts/test.sh tests/qgis/test_guidance.py tests/qgis/test_illustrations.py tests/qgis/test_panels.py` → Expected: `34 passed`
Run: `scripts/test.sh` → Expected: `507 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/help_texts.py terrain_sketch/gui/illustrations/__init__.py terrain_sketch/gui/illustrations/pixels_all_touched.svg terrain_sketch/gui/illustrations/pixels_centre.svg terrain_sketch/gui/illustrations/pixels_fully_inside.svg terrain_sketch/gui/illustrations/tool_add.svg terrain_sketch/gui/illustrations/tool_interpolate.svg terrain_sketch/gui/illustrations/tool_lower_flat.svg terrain_sketch/gui/illustrations/tool_lower_path.svg terrain_sketch/gui/illustrations/tool_raise_flat.svg terrain_sketch/gui/illustrations/tool_raise_path.svg terrain_sketch/gui/illustrations/tool_subtract.svg terrain_sketch/gui/properties_page.py tests/qgis/test_guidance.py tests/qgis/test_illustrations.py tests/qgis/test_panels.py
git commit -m "feat(gui): say what a height is measured from, picture the pixel modes, tell the tools apart"
```

---

### Task 7: Panels and groups remember their state

**Files:**
- Modify: `terrain_sketch/gui/properties_page.py`, `terrain_sketch/gui/settings.py`, `terrain_sketch/plugin.py`
- Test: `tests/qgis/test_dock_plugin.py`, `tests/qgis/test_settings.py`

**Interfaces:**
- Consumes: `settings.save`, `load`, `save_geometry`, `restore_geometry`; `TerrainSketchPlugin._create_dock`, `unload`; `PropertiesPage.about`, `volumes`.
- Produces: `settings.DOCK_AREAS`, `remember_collapsed(name, box)`, `save_dock(name, dock, window)`, `dock_area(name, default)`, `restore_dock(name, dock, window)`; `TerrainSketchPlugin._remember_docks()`; settings keys `main_dock/…`, `profile_dock/…`, `about_group/collapsed`, `volumes_group/collapsed`.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/test_dock_plugin.py`
```python
from unittest import mock

import pytest
from qgis.core import QgsFlatTerrainProvider, QgsProject
from qgis.PyQt.QtCore import QEvent, Qt
from qgis.PyQt.QtGui import QKeyEvent
from qgis.PyQt.QtWidgets import QApplication

from qgis.core import QgsCoordinateReferenceSystem, QgsCsException, QgsGeometry, QgsPointXY

from qgis.core import QgsRectangle

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, sample, square, world
from terrain_sketch import classFactory
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.selection import Method
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import SCENARIO_TOTALS, cubic_metres
from terrain_sketch.gui.main_dock import PAGE_GALLERY, PAGE_PROPERTIES, PAGE_START, MainDock
from terrain_sketch.gui.map_tools.draw_line import DrawLineTool
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


def test_plugin_adds_and_removes_its_button_menu_and_panel(tmp_path):
    flat = QgsFlatTerrainProvider()
    flat.setOffset(5.0)
    QgsProject.instance().elevationProperties().setTerrainProvider(flat)
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    iface.addToolBarIcon.assert_called_once_with(plugin.action)
    iface.addPluginToRasterMenu.assert_called_once()
    plugin.action.setChecked(True)
    assert plugin.dock is not None and plugin.profiles is not None
    assert iface.addDockWidget.call_count == 2  # the panel on the right, the profiles below
    plugin.dock.dem_combo.setLayer(dem_layer(tmp_path))
    plugin.dock.start_button.click()
    controller = plugin.controller              # kept alive, so its undo stack can be watched after unload
    assert controller.show_in_3d()
    plugin.unload()
    iface.removeToolBarIcon.assert_called_once()
    assert iface.removeDockWidget.call_count == 2
    assert plugin.dock is None and plugin.profiles is None
    assert plugin.controller is None and plugin.action is None
    terrain = QgsProject.instance().elevationProperties().terrainProvider()
    assert isinstance(terrain, QgsFlatTerrainProvider) and terrain.offset() == 5.0   # the project's terrain is back
    # The canvas outlives the plugin: its Ctrl+Z filter must go at once, not whenever the dock is deleted
    canvas = iface.mapCanvas()
    canvas.setMapTool(DrawLineTool(canvas))     # a Terrain Sketch tool, as far as that filter could tell
    controller.undo_stack.undo = mock.Mock()
    for kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
        QApplication.sendEvent(canvas, QKeyEvent(kind, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier))
    controller.undo_stack.undo.assert_not_called()


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


def test_an_outline_that_cannot_be_projected_leaves_the_highlight_empty(tmp_path):
    """Selecting and changing a feature redraw the highlight from Qt signals, so a failed
    projection into the map's CRS must not raise there; Edit shape and Zoom say so when used."""
    iface, controller, dock = _session_dock(tmp_path)
    iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    with mock.patch.object(QgsGeometry, "transform", side_effect=QgsCsException("forced")):
        dock.feature_view.select_id(dike.id)
        assert dock.highlight.numberOfVertices() == 0
        controller.update_feature(dike.id, amount=2.0)
        assert dock.highlight.numberOfVertices() == 0
    iface.messageBar().pushMessage.assert_not_called()


def test_deleting_the_shown_feature_leaves_the_properties_page(tmp_path):
    """`featuresChanged` resets the list model, which can clear the Qt selection without
    emitting `selectionChanged` — so the dock must check for itself that Properties is not left
    showing a feature that Delete just removed."""
    _iface, controller, dock = _session_dock(tmp_path)
    dike = controller.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    controller.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.pages.currentIndex() == PAGE_PROPERTIES

    dock.delete_button.click()

    if dock.pages.currentIndex() == PAGE_PROPERTIES:
        fid = dock.feature_view.selected_id()
        assert fid is not None and fid in {f.id for f in controller.features}
        cut, fill = controller.totals()
        assert dock.properties.totals_value.text() == SCENARIO_TOTALS.format(fill=cubic_metres(fill),
                                                                              cut=cubic_metres(cut))
    else:
        assert dock.pages.currentIndex() != PAGE_PROPERTIES


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


def test_the_panels_open_where_they_were_left_and_unloading_remembers_it(tmp_path):
    from terrain_sketch.gui import settings
    iface = fake_iface()
    window = iface.mainWindow()
    iface.addDockWidget.side_effect = window.addDockWidget          # a real window, as in QGIS
    settings.save("main_dock/area", int(Qt.DockWidgetArea.LeftDockWidgetArea.value))
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    assert iface.addDockWidget.call_args_list[0][0] == (Qt.DockWidgetArea.LeftDockWidgetArea, plugin.dock)
    assert window.dockWidgetArea(plugin.profiles) == Qt.DockWidgetArea.BottomDockWidgetArea   # the default
    window.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, plugin.profiles)   # the user moves it
    plugin.unload()
    area = Qt.DockWidgetArea
    assert settings.dock_area("profile_dock", area.BottomDockWidgetArea) == area.TopDockWidgetArea
    assert settings.dock_area("main_dock", area.RightDockWidgetArea) == area.LeftDockWidgetArea
```

**File:** `tests/qgis/test_settings.py`
```python
from qgis.core import QgsSettings
from qgis.PyQt.QtWidgets import QApplication, QPushButton, QSplitter

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
    first.setSizes([300, 100])       # a split the user could have dragged, so there is something
                                     # to recognise at the other end besides a True return value
    settings.save_state("probe_splitter", first)
    # what was stored is exactly what the widget produced — every QWidget also has saveGeometry,
    # so a module that probed for a method would quietly store the wrong one for a splitter
    assert bytes(settings.load("probe_splitter/state")) == bytes(first.saveState())
    second = QSplitter()
    second.addWidget(QPushButton())
    second.addWidget(QPushButton())
    assert settings.restore_state("probe_splitter", second)
    assert second.sizes() == first.sizes()   # restored, not merely reported as restored


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


def test_a_collapsed_group_is_remembered_under_the_plugin_group(tmp_path):
    """QgsCollapsibleGroupBox saves under its own key otherwise, which the plugin cannot clear and
    which leaked a collapsed About box from one test into the next."""
    from qgis_helpers import start_session
    from terrain_sketch.gui.properties_page import PropertiesPage
    stored = QgsSettings()
    for key in stored.allKeys():
        if key.startswith("QgsCollapsibleGroupBox/") and "TerrainSketch" in key:
            stored.remove(key)                     # left in the shared test profile by earlier versions
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    page.show()                                    # a box that is not shown does not report a collapse
    assert not page.about.isCollapsed()
    page.about.setCollapsed(True)
    assert settings.load("about_group/collapsed", False, bool)
    assert not [key for key in QgsSettings().allKeys() if key.startswith("QgsCollapsibleGroupBox/")
                and "TerrainSketch" in key]
    again = PropertiesPage(c)
    again.show()                                   # a box that saved its own state would load it here
    assert again.about.isCollapsed() and not again.volumes.isCollapsed()


def window_with(dock, area):
    from qgis.PyQt.QtWidgets import QMainWindow, QTextEdit
    window = QMainWindow()
    window.setCentralWidget(QTextEdit())
    window.resize(1000, 700)
    window.addDockWidget(area, dock)
    window.show()
    return window


def test_a_docked_panel_comes_back_in_its_area_at_its_width():
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QDockWidget, QTextEdit
    first = QDockWidget("Terrain Sketch")
    first.setWidget(QTextEdit())
    window = window_with(first, Qt.DockWidgetArea.LeftDockWidgetArea)
    window.resizeDocks([first], [340], Qt.Orientation.Horizontal)
    QApplication.processEvents()
    settings.save_dock("probe_dock", first, window)

    second = QDockWidget("Terrain Sketch")
    second.setWidget(QTextEdit())
    area = settings.dock_area("probe_dock", Qt.DockWidgetArea.RightDockWidgetArea)
    assert area == Qt.DockWidgetArea.LeftDockWidgetArea
    other = window_with(second, area)
    settings.restore_dock("probe_dock", second, other)
    QApplication.processEvents()
    assert abs(second.width() - first.width()) <= 2


def test_a_floating_panel_comes_back_floating_where_it_was():
    from qgis.PyQt.QtCore import QRect, Qt
    from qgis.PyQt.QtWidgets import QDockWidget, QTextEdit
    first = QDockWidget("Profiles")
    first.setWidget(QTextEdit())
    window = window_with(first, Qt.DockWidgetArea.BottomDockWidgetArea)
    first.setFloating(True)
    first.setGeometry(QRect(120, 140, 500, 260))
    QApplication.processEvents()
    settings.save_dock("probe_float", first, window)

    second = QDockWidget("Profiles")
    second.setWidget(QTextEdit())
    other = window_with(second, settings.dock_area("probe_float", Qt.DockWidgetArea.BottomDockWidgetArea))
    settings.restore_dock("probe_float", second, other)
    QApplication.processEvents()
    assert second.isFloating() and second.size() == first.size()


def test_a_panel_being_removed_or_never_placed_keeps_what_was_stored():
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QDockWidget, QMainWindow
    area = Qt.DockWidgetArea
    settings.save("probe_kept/area", int(area.TopDockWidgetArea.value))
    settings.save_dock("probe_kept", QDockWidget(), QMainWindow())      # in no area of that window
    assert settings.dock_area("probe_kept", area.RightDockWidgetArea) == area.TopDockWidgetArea
    settings.save("probe_junk/area", "somewhere")
    assert settings.dock_area("probe_junk", area.RightDockWidgetArea) == area.RightDockWidgetArea
    settings.save("probe_none/area", 0)                                 # NoDockWidgetArea
    assert settings.dock_area("probe_none", area.BottomDockWidgetArea) == area.BottomDockWidgetArea
```
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/qgis/test_settings.py`
Expected: exit code 1 with `AttributeError: module 'terrain_sketch.gui.settings' has no attribute 'save_dock'`

- [ ] **Step 3: Implement**

Replace the whole file:

**File:** `terrain_sketch/gui/properties_page.py`
```python
"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

import html
import traceback

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox, QgsDoubleSpinBox
from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode, reports_storage
from . import illustrations, settings
from .controller import LOG_TAG
from .help_texts import (AMOUNT_IS_CUSTOM, FIELD_TIPS, FLAG_TEXTS, NO_VOLUME_YET, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS,
                         SCENARIO_TOTALS, TOOL_DESCRIPTIONS, TOOL_EXAMPLES, TOOL_LABELS, TOOL_SUMMARIES,
                         VOLUME_CUT_TIP, VOLUME_FILL_TIP, VOLUME_STORAGE_NOTE, VOLUME_STORAGE_TIP, amount_label,
                         cubic_metres)

DIAGRAM = QSize(200, 96)
TOOL_PICTURE = QSize(120, 64)
PIXEL_ICON = QSize(32, 32)
PIXEL_PICTURE = 72   # each of the three pictures in the Pixels to change tooltip


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
        self.amount_label.setWordWrap(True)   # "Height above the highest point" must not set the panel's width
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
        self.about.setObjectName("TerrainSketchAboutTool")
        settings.remember_collapsed("about_group", self.about)
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
        settings.remember_collapsed("volumes_group", self.volumes)
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
        controller.featuresChanged.connect(self._refresh_values)
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
        self.pixel_mode.setToolTip(self._pixel_modes_tip())

    def _pixel_modes_tip(self) -> str:
        """The field's tip with the three pixel modes side by side under it (spec §7.2), drawn in the
        current theme's colours like every other picture on the page."""
        size = PIXEL_PICTURE
        pictures = "".join(
            f'<td align="center"><img src="{illustrations.data_uri(f"pixels_{mode.value}", size, self.palette())}"'
            f' width="{size}" height="{size}"/></td>' for mode in PixelMode)
        names = "".join(f'<td align="center">{html.escape(PIXEL_MODE_LABELS[mode])}</td>' for mode in PixelMode)
        return f"<p>{html.escape(FIELD_TIPS['pixel_mode'])}</p><table><tr>{pictures}</tr><tr>{names}</tr></table>"

    def show_feature(self, fid: str) -> None:
        self._fid = fid
        feature = self.controller.feature(fid)
        info = TOOL_INFO[feature.tool]
        label = amount_label(feature.tool, feature.mode)
        self._loading = True
        try:
            self.title.setText(_title(feature))
            self.summary.setText(TOOL_SUMMARIES[feature.tool])
            self.amount_label.setText(label or "")
            self._load_values(feature)
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

    def _load_values(self, feature) -> None:
        """Show the feature's values in the fields — except in a field the user is still typing in:
        a change from elsewhere (a profile drag, an undo) must not throw away what they typed."""
        # Only a profile the engine actually uses fixes the heights: on a multi-part path it
        # is discarded, and Height/Depth is then the one control that still drives the result.
        custom = feature.long_profile is not None and supports_long_profile(feature)
        for spin, value in ((self.amount, feature.amount), (self.width, feature.width),
                            (self.slope, feature.slope_n), (self.reach, feature.reach)):
            if not spin.lineEdit().isModified():
                spin.setValue(value)
        self.amount.setEnabled(not custom)
        self.amount.setToolTip(AMOUNT_IS_CUSTOM if custom else self._amount_tip)
        self.slope_position.setCurrentIndex(1 if feature.slopes_inside else 0)
        self.pixel_mode.setCurrentIndex(self.pixel_mode.findData(feature.pixel_mode.value))

    def _refresh_values(self) -> None:
        """Keep the fields in step with the feature whenever the list changes: a cross-profile drag
        moves the width, slope and reach, and an undo can change anything. Runs in a slot."""
        try:
            feature = self.controller.find(self._fid) if self._fid is not None else None
            if feature is None:
                return
            self._loading = True
            try:
                self._load_values(feature)
            finally:
                self._loading = False
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

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

Replace the whole file:

**File:** `terrain_sketch/gui/settings.py`
```python
"""Remembering panel state between sessions, under the `terrain_sketch/` QgsSettings group."""
from __future__ import annotations

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt

GROUP = "terrain_sketch"
DOCK_AREAS = (Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea,
              Qt.DockWidgetArea.TopDockWidgetArea, Qt.DockWidgetArea.BottomDockWidgetArea)


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


def remember_collapsed(name: str, box) -> None:
    """Keep a QgsCollapsibleGroupBox's collapsed state under the plugin's group. Left to itself the box
    saves under its own `QgsCollapsibleGroupBox/…` key, where the plugin can neither find nor clear it."""
    try:
        box.setSaveCollapsedState(False)
        box.setCollapsed(bool(load(f"{name}/collapsed", False, bool)))
        box.collapsedStateChanged.connect(lambda collapsed: save(f"{name}/collapsed", bool(collapsed)))
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass


def save_dock(name: str, dock, window) -> None:
    """Remember where a panel is in `window`: its dock area, whether it floats, and its size — or, when it
    floats, its position too. A panel that is not in the window at all (being removed) changes nothing."""
    try:
        area = window.dockWidgetArea(dock)
        if dock.isFloating():
            save(f"{name}/floating", True)
            save_geometry(name, dock)
        elif area in DOCK_AREAS:
            save(f"{name}/floating", False)
            save(f"{name}/area", int(area.value))
            save(f"{name}/width", dock.width())
            save(f"{name}/height", dock.height())
    except Exception:  # noqa: BLE001 — runs from dock signals and unload
        pass


def dock_area(name: str, default):
    """The dock area a panel was last in, or `default`."""
    try:
        area = Qt.DockWidgetArea(int(load(f"{name}/area", int(default.value), int)))
    except Exception:  # noqa: BLE001 — a value from an older or hand-edited profile
        return default
    return area if area in DOCK_AREAS else default


def restore_dock(name: str, dock, window) -> None:
    """Put a panel back the way it was, once it has been added to `window`: floating where it floated, or
    docked at the width (side areas) or height (top and bottom) it had."""
    try:
        if load(f"{name}/floating", False, bool):
            dock.setFloating(True)
            restore_geometry(name, dock)
            return
        across = window.dockWidgetArea(dock) in (Qt.DockWidgetArea.LeftDockWidgetArea,
                                                 Qt.DockWidgetArea.RightDockWidgetArea)
        size = load(f"{name}/width" if across else f"{name}/height", 0, int)
        if size > 0:
            window.resizeDocks([dock], [size], Qt.Orientation.Horizontal if across else Qt.Orientation.Vertical)
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass
```

Replace the whole file:

**File:** `terrain_sketch/plugin.py`
```python
"""Plugin entry point: toolbar button, Raster menu entry and the Terrain Sketch panel."""
from __future__ import annotations

import os

from qgis.core import QgsProject
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon

from .gui import settings
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
        self._remember_docks()
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
        window = self.iface.mainWindow()
        # Both panels go back where the user last had them (spec §7.1); QGIS does not do this for a
        # plugin's panels, which are created long after it restored its own window layout.
        for name, dock, default in (("main_dock", self.dock, Qt.DockWidgetArea.RightDockWidgetArea),
                                    ("profile_dock", self.profiles, Qt.DockWidgetArea.BottomDockWidgetArea)):
            self.iface.addDockWidget(settings.dock_area(name, default), dock)
            settings.restore_dock(name, dock, window)
            dock.dockLocationChanged.connect(lambda _area, n=name, d=dock: settings.save_dock(n, d, window))
            dock.topLevelChanged.connect(lambda _floating, n=name, d=dock: settings.save_dock(n, d, window))
        return True

    def _remember_docks(self) -> None:
        window = self.iface.mainWindow()
        for name, dock in (("main_dock", self.dock), ("profile_dock", self.profiles)):
            if dock is not None:
                settings.save_dock(name, dock, window)
```
- [ ] **Step 4: Run the tests**

Run: `scripts/test.sh tests/qgis/test_dock_plugin.py tests/qgis/test_settings.py` → Expected: `32 passed`
Run: `scripts/test.sh` → Expected: `512 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/properties_page.py terrain_sketch/gui/settings.py terrain_sketch/plugin.py tests/qgis/test_dock_plugin.py tests/qgis/test_settings.py
git commit -m "feat(gui): panels and group boxes remember their state under terrain_sketch/"
```

---

### Task 8: Working rasters beside the scenario, and opening on its own DEM

**Files:**
- Modify: `terrain_sketch/gui/controller.py`, `terrain_sketch/gui/help_texts.py`, `terrain_sketch/gui/main_dock.py`, `terrain_sketch/qgis_io/layers.py`, `terrain_sketch/qgis_io/raster_io.py`
- Test: `tests/qgis/conftest.py`, `tests/qgis/test_scenario_files.py`, `tests/qgis/test_scenario_panel.py`

**Interfaces:**
- Consumes: Task 1's `_same_file`, `_mark_scenario`, `main_dock._same_source`; `WorkingFiles`; `SketchLayers`; `SketchController.save_scenario`, `open_scenario`, `new_scenario`, `_drop_session`, `scenario_differences`; `scenario.load_meta`; `MainDock._start`, `_open_scenario`, `confirm`.
- Produces: `raster_io.WORKING_NAME`, `CHANGE_NAME`, `WorkingFiles.move_to(folder)`; `SketchLayers.repoint(working_path, change_path)`; `controller.FILES_SUFFIX`, `scenario_files_folder(path) -> str`; `SketchController.scenario_dem_source(path) -> str | None`, `_place_files()`, `_move_files(folder, temporary)`, `_files_temporary`; `help_texts.FILES_NOT_MOVED`, `SCENARIO_OTHER_DEM`, `DEM_NOT_READABLE`; `MainDock.choose_dem` (hook returning `"scenario"`, `"current"` or `None`), `_dem_choice_dialog(text)`, `_start_session(layer) -> bool`, `_start_on_file(source) -> bool`; the test `conftest.py` answers a `QMessageBox.exec` with no button clicked.

- [ ] **Step 1: Write the failing tests**

**File:** `tests/qgis/conftest.py`
```python
"""Headless QGIS for the integration tests: one QgsApplication, a clean project per test."""
import os

import pytest
from qgis.core import QgsApplication, QgsProject, QgsSettings

from terrain_sketch.gui import settings as plugin_settings
from terrain_sketch.gui.controller import SketchController

QgsApplication.setPrefixPath(os.environ.get("QGIS_PREFIX_PATH", "/Applications/QGIS-final-4_2_2.app"), True)
QGIS_APP = QgsApplication([], True)
QGIS_APP.initQgis()

# Every controller listens to the one QgsProject. Without letting go after each test, the controllers of
# every earlier test would still answer the next test's project signals.
_controllers = []
_controller_init = SketchController.__init__


def _tracked_init(self, *args, **kwargs):
    _controller_init(self, *args, **kwargs)
    _controllers.append(self)


SketchController.__init__ = _tracked_init


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
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Cancel)   # no button clicked
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))


@pytest.fixture(autouse=True)
def clean_project(no_modal_dialogs):
    QgsProject.instance().clear()
    _clear_plugin_settings()
    yield
    QgsProject.instance().clear()
    while _controllers:
        _controllers.pop().shutdown()
    _clear_plugin_settings()


def _clear_plugin_settings() -> None:
    """Drop everything under the plugin's settings group so tests cannot inherit each other's."""
    settings = QgsSettings()
    settings.beginGroup(plugin_settings.GROUP)
    settings.remove("")
    settings.endGroup()
```

**File:** `tests/qgis/test_scenario_files.py`
```python
"""The working rasters live beside a saved scenario, in `<scenario>_files/` (spec §8.2 step 3)."""
import os

import numpy as np
from qgis.core import QgsProject

from qgis_helpers import UTM, line_through, read_tif, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import scenario_files_folder
from terrain_sketch.gui.help_texts import FILES_NOT_MOVED


def layer_sources(c):
    project = QgsProject.instance()
    return {project.mapLayer(i).source() for i in (c.layers.working_id, c.layers.change_id, c.layers.hillshade_id)}


def test_saving_moves_the_working_rasters_beside_the_scenario_and_keeps_writing_there(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    temp = c.files.folder
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    folder = str(tmp_path / "flood_files")
    assert scenario_files_folder(path) == folder and c.files.folder == folder
    assert layer_sources(c) == {os.path.join(folder, "working_dem.tif"), os.path.join(folder, "change.tif")}
    assert not os.path.exists(temp)                                  # the temp copy is gone
    assert sample(c.layers.working, 20, 20) == 11.0                 # the layers still show the sketch
    c.update_feature(dike.id, amount=2.0)
    working, _nodata = read_tif(os.path.join(folder, "working_dem.tif"))
    assert working[19, 20] == 12.0                                   # edits are written where the layers read


def test_a_scenarios_files_stay_when_the_session_ends(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    c.close()
    assert os.path.isfile(tmp_path / "flood_files" / "working_dem.tif")   # a saved QGIS project still finds them


def test_save_as_moves_the_rasters_and_later_edits_leave_the_first_scenarios_alone(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "first.gpkg"))
    c.save_scenario(str(tmp_path / "second.gpkg"))
    assert c.files.folder == str(tmp_path / "second_files")
    c.update_feature(dike.id, amount=3.0)
    first, _ = read_tif(tmp_path / "first_files" / "working_dem.tif")
    second, _ = read_tif(tmp_path / "second_files" / "working_dem.tif")
    assert first[19, 20] == 11.0 and second[19, 20] == 13.0


def test_a_new_scenario_takes_the_rasters_back_to_a_temp_folder(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    c.new_scenario()
    assert not c.files.folder.startswith(str(tmp_path)) and os.path.isdir(c.files.folder)
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    saved, _ = read_tif(tmp_path / "flood_files" / "working_dem.tif")
    assert saved[15, 15] == 10.0                                      # the new pond went to the temp copy
    temp = c.files.folder
    c.close()
    assert not os.path.exists(temp)


def test_opening_a_scenario_keeps_the_rasters_beside_it(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    c.new_scenario()
    c.open_scenario(path)
    assert c.files.folder == str(tmp_path / "flood_files")
    working, _ = read_tif(tmp_path / "flood_files" / "working_dem.tif")
    assert working[19, 20] == 11.0


def test_a_folder_that_cannot_be_written_leaves_the_rasters_where_they_were(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    (tmp_path / "flood_files").write_text("a file where the folder should go")
    temp = c.files.folder
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    assert os.path.isfile(tmp_path / "flood.gpkg") and not c.is_dirty    # the save itself happened
    assert c.files.folder == temp and os.path.isdir(temp)
    assert len(heard) == 1 and heard[0].startswith(FILES_NOT_MOVED.split("{folder}")[0])
    assert layer_sources(c) == {os.path.join(temp, "working_dem.tif"), os.path.join(temp, "change.tif")}


def test_a_3d_terrain_on_the_modified_dem_follows_the_move(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.show_in_3d()
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    provider = QgsProject.instance().elevationProperties().terrainProvider()
    assert provider.layer().id() == c.layers.working_id
    assert provider.layer().source() == str(tmp_path / "flood_files" / "working_dem.tif")
```

**File:** `tests/qgis/test_scenario_panel.py`
```python
"""The scenario buttons: New, Open, Save and Save as, and every question asked before work is lost."""
import numpy as np
import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch import classFactory
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import (SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_OTHER_DEM,
                                           SCENARIO_REPLACE, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES)
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.qgis_io.scenario import dem_meta, load, save


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
    assert not c.is_dirty                              # and the second click actually wrote
    assert load(path)[0][0].amount == 2.0


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
    # Leave the dock able to end the session cleanly: a real user who keeps choosing Save with a
    # file dialog that can never succeed would keep being asked (that is the point of I1), but a
    # stub stuck on "always Save, never a path" must not turn this test's own teardown `clear()`
    # into an infinite retry.
    dock.confirm_save = lambda text, can_cancel=True: False


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
    (tmp_path / "other30" / "dem.tif").unlink()                  # its own DEM is gone, so it is this one or nothing
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


def test_a_failed_save_before_closing_asks_again_until_it_succeeds(tmp_path):
    """Save chosen but the file dialog is then cancelled (or the save fails) must not drop the
    session silently — the question repeats until a save succeeds or the user chooses Discard."""
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "retried.gpkg")
    paths = iter(["", path])                          # first Save picks nothing, second succeeds
    dock.ask_save_path = lambda: next(paths)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append((text, can_cancel)) or True
    QgsProject.instance().clear()

    assert asked == [(UNSAVED_BEFORE_CLOSING, False), (UNSAVED_BEFORE_CLOSING, False)]
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


def test_the_save_and_open_dialogs_start_beside_the_current_scenario(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "current.gpkg")
    c.save_scenario(path)

    save_dirs, open_dirs = [], []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: save_dirs.append(a[2]) or ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: open_dirs.append(a[2]) or ("", "")))

    dock._save_dialog()
    dock._open_dialog()
    assert save_dirs == [str(tmp_path)]
    assert open_dirs == [str(tmp_path)]


def test_the_save_dialog_starts_at_the_project_home_without_a_scenario_yet(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, _c, dock = panel(tmp_path)
    save_dirs = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: save_dirs.append(a[2]) or ("", "")))

    dock._save_dialog()
    assert save_dirs == [QgsProject.instance().homePath()]


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


def test_a_replace_check_that_raises_is_shown_as_a_warning_not_crashed(tmp_path):
    """A RuntimeError out of the replace check (e.g. "database is locked") must reach the user
    as a message-bar warning, exactly like any other save failure — not escape the Save button's
    Qt slot, which would abort QGIS."""
    from unittest import mock

    from terrain_sketch.qgis_io import scenario

    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "locked.gpkg")
    c.save_scenario(path)
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.ask_save_path = lambda: path

    with mock.patch.object(scenario, "_is_scenario_file", side_effect=RuntimeError("database is locked")):
        dock.save_scenario_button.click()

    assert any("database is locked" in text for text in messages(_iface))
    assert c.is_dirty


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


def test_a_scenario_whose_dem_is_still_there_offers_to_start_on_that_dem(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))
    other_dem = str(tmp_path / "other30" / "dem.tif")
    project = QgsProject.instance()
    project.removeMapLayers([l.id() for l in project.mapLayers().values() if l.source() == other_dem])
    _iface, c, dock = panel(tmp_path)
    mine = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or False     # discard my work
    dock.ask_open_path = lambda: path
    choices = []
    dock.choose_dem = lambda text: choices.append(text) or None                       # cancel
    dock.open_scenario_button.click()
    assert choices == [SCENARIO_OTHER_DEM.format(dem="dem.tif", differences="size in pixels, extent")]
    assert [f.id for f in c.features] == [mine.id] and c.info.path != other_dem

    dock.choose_dem = lambda text: "scenario"
    dock.open_scenario_button.click()
    assert c.has_dem and c.info.path == other_dem and dock.dem_combo.currentLayer().source() == other_dem
    assert len(c.features) == 1 and c.features[0].tool is Tool.RAISE_PATH and c.scenario_path == path
    assert c.scenario_differences(path) == []
    assert len(asked) == 2                          # asked about my unsaved work each time, never again by Start
    rasters = [l for l in project.mapLayers().values() if l.source() == other_dem]
    assert len(rasters) == 1 and project.mapLayersByName("dem")    # added once; the user's own DEM stays


def test_starting_on_the_scenarios_dem_reuses_it_when_it_is_already_in_the_project(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))   # its DEM is in the project
    other_dem = str(tmp_path / "other30" / "dem.tif")
    already = next(l for l in QgsProject.instance().mapLayers().values() if l.source() == other_dem)
    _iface, c, dock = panel(tmp_path)
    dock.ask_open_path = lambda: path
    dock.choose_dem = lambda text: "scenario"
    dock.open_scenario_button.click()
    assert c.dem_layer_id == already.id()
    assert len([l for l in QgsProject.instance().mapLayers().values() if l.source() == other_dem]) == 1


def test_opening_on_this_dem_instead_keeps_the_session(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))
    _iface, c, dock = panel(tmp_path)
    first = c.info.path
    dock.ask_open_path = lambda: path
    dock.choose_dem = lambda text: "current"
    dock.open_scenario_button.click()
    assert c.info.path == first and len(c.features) == 1 and c.scenario_path == path


def test_the_dem_question_has_both_choices_and_cancel(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox
    _iface, _c, dock = panel(tmp_path)
    for label, expected in (("Start on its DEM", "scenario"), ("Open on this DEM", "current"), ("Cancel", None)):
        seen = []

        def click(box, label=label):
            seen.append(sorted(b.text() for b in box.buttons()))
            next(b for b in box.buttons() if b.text() == label).click()
            return 0
        monkeypatch.setattr(QMessageBox, "exec", click)
        assert dock._dem_choice_dialog("which DEM?") == expected
        assert seen == [sorted(["Start on its DEM", "Open on this DEM", "Cancel"])]
```
- [ ] **Step 2: Run them to see them fail**

Run: `scripts/test.sh tests/qgis/test_scenario_files.py`
Expected: collection error `ImportError: cannot import name 'scenario_files_folder' from 'terrain_sketch.gui.controller'`

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
from ..core.sections import default_section_line, long_section, rescale_long_profile, section_along
from ..core.tools import Mode, Tool
from ..model.feature import TerrainFeature, new_feature
from ..qgis_io import scenario
from ..qgis_io.convert import from_wkb, to_dem_wkb
from ..qgis_io.layers import SketchLayers
from ..qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem
from ..qgis_io.scenario import ScenarioError
from .help_texts import (COPY_NAME, DRAWING_NOT_TRANSFORMED, EXPORT_OVER_SOURCE, EMPTY_LAYER, FILES_NOT_MOVED,
                         NO_FEATURES_SELECTED, NO_SESSION, RESULT_LAYER_REMOVED, SCENARIO_NOT_APPLIED,
                         SESSION_ENDED_DEM_REMOVED, TOOL_LABELS, UNDO_ADD, UNDO_DELETE, UNDO_DUPLICATE,
                         UNDO_PROFILE, UNDO_RENAME, UNDO_REORDER, UNDO_SECTION_LINE, UNDO_SETTINGS, UNDO_SHAPE,
                         UNDO_TURN_OFF, UNDO_TURN_ON, VIEW_3D_NO_LAYER)
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

    def __init__(self, project: QgsProject, parent=None):
        super().__init__(parent)
        self.project = project
        self.stack = None
        self.info = None
        self.files = None
        self._files_temporary = True   # the working rasters are in a temp folder, not a scenario's
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
        self._files_temporary = True
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
        if self._set([]):
            self._forget_scenario()
            self._place_files()
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
        self._place_files()
        self.sessionChanged.emit()

    def _mark_scenario(self, path: str, created: str) -> None:
        """The features now belong to the scenario file at `path`, first saved at `created`."""
        self._scenario_path = path
        self._created = created

    def _place_files(self) -> None:
        """Keep the working rasters with the scenario the features belong to (spec §8.2 step 3): in
        `<scenario>_files/` beside a saved or opened scenario, so a QGIS project saved with these layers
        still finds them later; in a temp folder when there is no scenario file. They move whenever that
        changes, so edits to a new or another scenario never write over a scenario's own rasters."""
        if self._scenario_path is None:
            if not self._files_temporary:
                self._move_files(tempfile.mkdtemp(prefix="terrain_sketch_"), temporary=True)
        elif self._files_temporary or not _same_file(scenario_files_folder(self._scenario_path), self.files.folder):
            self._move_files(scenario_files_folder(self._scenario_path), temporary=False)

    def _move_files(self, folder: str, temporary: bool) -> None:
        """Move the working rasters to `folder` and point the layers at them. A folder that cannot be written
        leaves them where they are, with a message: the save or open this follows has already happened."""
        old, was_temporary = self.files.folder, self._files_temporary
        try:
            self.files.move_to(folder)
        except Exception as error:  # noqa: BLE001 — a read-only share, a full disk, a file another program holds
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Warning)
            self.message.emit(Qgis.MessageLevel.Warning, FILES_NOT_MOVED.format(folder=folder, error=error))
            if temporary:
                shutil.rmtree(folder, ignore_errors=True)
            return
        self._files_temporary = temporary
        if self.layers is not None:
            self.layers.repoint(self.files.working_path, self.files.change_path)
        if was_temporary:
            shutil.rmtree(old, ignore_errors=True)

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
        # A scenario's `_files` folder is the scenario's, and stays; only a temp folder goes with the session
        folder = self.files.folder if self.files is not None and self._files_temporary else None
        self.stack = self.info = self.files = self.layers = None
        self._files_temporary = True
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
    if fields == {"section_line"}:
        return UNDO_SECTION_LINE.format(feature.name), None
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
from ..core.tools import Mode, PixelMode, Tool

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
EXPORT_ADD_FAILED = ("The exported DEM {} could not be added to the project; see the 'Terrain Sketch' log tab "
                     "for details.")

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
UNDO_SECTION_LINE = "Move the section line of {}"
COPY_NAME = "{} (copy)"

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It is the project's terrain, but only a temporary one, "
               "even if you save the project meanwhile: the terrain you had before is put back when this "
               "session ends.")
VIEW_3D_NOT_OPENED = ("The modified DEM is now the project's terrain, but Terrain Sketch could not open a "
                      "3D view. Open one with View ▸ 3D Map Views ▸ New 3D Map View.")
VIEW_3D_NO_LAYER = ("The Modified DEM layer is no longer in the project, so there is nothing to show in 3D. "
                    "Press Start to create it again.")


# The amount field says what it is measured from (spec §7.2): a height "above the path" and one "above
# the highest point" are different numbers for the same dike, and a bare "Height" let users set the wrong one.
AMOUNT_LABELS = {
    (Tool.RAISE_PATH, Mode.PATH): "Height above the path",
    (Tool.LOWER_PATH, Mode.PATH): "Depth below the path",
    (Tool.RAISE_FLAT, Mode.PATH): "Height above the highest point",
    (Tool.RAISE_FLAT, Mode.AREA): "Height above the highest edge",
    (Tool.LOWER_FLAT, Mode.PATH): "Depth below the lowest point",
    (Tool.LOWER_FLAT, Mode.AREA): "Depth below the lowest edge",
    (Tool.ADD, Mode.PATH): "Height added",
    (Tool.ADD, Mode.AREA): "Height added",
    (Tool.SUBTRACT, Mode.PATH): "Depth removed",
    (Tool.SUBTRACT, Mode.AREA): "Depth removed",
}


def amount_label(tool: Tool, mode: Mode) -> str | None:
    """Label of the amount field, or None when the tool has no amount (Interpolate)."""
    return AMOUNT_LABELS.get((tool, mode))

PROFILE_EMPTY_HINT = "Select or draw a feature to edit its shape here."
CUSTOM_PROFILE_NOTE = ("Custom long profile: the heights are fixed and no longer follow the "
                       "terrain underneath. Use Reset to rule to go back.")
AREA_SECTION_EMPTY_HINT = "There is no terrain to show along this feature's section line."
AREA_SECTION_NOTE = ("A section through the area along the dashed line on the map: dashed here is the ground "
                     "before this feature, solid is the result. Shape the sides with the cross profile on the left.")
DRAW_SECTION_TIP = "Draw the line on the map that this section runs along."
RESET_SECTION_TIP = "Put the section line back through the middle of the area, along its longer side."
SECTION_LINE_HINT = ("Click to draw the section line. Right-click or press Enter to finish, Backspace removes the "
                     "last point, Esc cancels.")
MULTIPART_LONG_SECTION_NOTE = ("This feature has more than one part, so its long profile follows "
                               "the tool rule and cannot be edited by hand. Use Height or Depth in "
                               "the panel above to drive its shape.")
CROSS_SIDES_TIP = ("A section across the path, looking along it in the direction it was drawn: its left side "
                   "on the left. Drag the crest edges to change the width, and the ends of the slopes to change "
                   "their steepness and reach; double-click to add a break point, such as a berm, and "
                   "right-click to remove one.")
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
DEM_NOT_READABLE = "{} cannot be read as a raster, so Terrain Sketch cannot start on it."
SCENARIO_OTHER_DEM = ("This scenario was made on {dem}, which differs from the DEM you are using in {differences}."
                      "\n\nStart on {dem} and open the scenario there? Your current DEM stays in the project.")
FILES_NOT_MOVED = ("Terrain Sketch could not put its working rasters in {folder} ({error}). They stay where they "
                   "were, so a QGIS project saved now will not find them next time.")
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
from ..qgis_io.convert import from_wkb
from ..qgis_io.raster_io import DemError, GeographicDemError
from ..qgis_io.scenario import ScenarioError
from .controller import LOG_TAG
from .feature_list import FeatureListModel, FeatureListView
from .help_texts import (DEM_NOT_READABLE, EXPORT_ADD_FAILED, EXPORT_DONE, EXPORT_INTEGER_NOTE, EXPORT_NOT_ADDED,
                         EXPORT_REPLACE, REPROJECT_UNAVAILABLE, SCENARIO_DEM_DIFFERS, SCENARIO_OPENED,
                         SCENARIO_OTHER_DEM, SCENARIO_REPLACE, SCENARIO_SAVED, SECTION_LINE_HINT,
                         SHAPE_NOT_TRANSFORMED, UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES, VIEW_3D_NOT_OPENED,
                         VIEW_3D_TIP)
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
        controller.before_discard = self._offer_save_before_discard
        self.edit_tool = None
        self._brush_fid = None
        self._brush_extends = False       # set with _brush_fid, but kept when that feature goes
        self.highlight = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)
        self.highlight.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.highlight.setFillColor(Qt.GlobalColor.transparent)
        self.highlight.setWidth(QgsMapToolEdit.digitizingStrokeWidth() + 2)
        self.section_band = QgsRubberBand(iface.mapCanvas(), Qgis.GeometryType.Line)   # an area's section line
        self.section_band.setStrokeColor(QgsMapToolEdit.digitizingStrokeColor())
        self.section_band.setWidth(QgsMapToolEdit.digitizingStrokeWidth())
        self.section_band.setLineStyle(Qt.PenStyle.DashLine)

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
        self.export_button = _file_button(
            "/mActionSharingExport.svg", self.tr("Export DEM…"),
            self.tr("Write the modified DEM to a new GeoTIFF, e.g. for a flood simulation."))
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
            profiles.drawSectionRequested.connect(self._draw_section_line)
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
        self._start_session(layer)

    def _start_session(self, layer) -> bool:
        """Start on `layer` once any unsaved work has been dealt with. True when the session started."""
        self._asked_about_unsaved = True   # the user has just answered; closing the old session must not ask again
        try:
            self.controller.set_dem(layer)
            return True
        except DemError as error:
            if isinstance(error, GeographicDemError):
                self._offer_reproject(str(error))
            else:
                self._show_message(Qgis.MessageLevel.Warning, str(error))
            return False
        finally:
            self._asked_about_unsaved = False

    def _start_on_file(self, source: str) -> bool:
        """Start on the DEM at `source`: the layer already in the project that reads it, or a new one."""
        layer = next((layer for layer in QgsProject.instance().mapLayers().values()
                      if isinstance(layer, QgsRasterLayer) and _same_source(layer.source(), source)), None)
        if layer is None:
            layer = QgsRasterLayer(source, os.path.splitext(os.path.basename(source))[0])
            if not layer.isValid():
                self._show_message(Qgis.MessageLevel.Warning, DEM_NOT_READABLE.format(source))
                return False
            QgsProject.instance().addMapLayer(layer)
        self.dem_combo.setLayer(layer)
        return self._start_session(layer)

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
        self.draw_tool = DrawLineTool(self.iface.mapCanvas())
        self.draw_tool.finished.connect(lambda geometry, f=fid: self._section_drawn(f, geometry))
        self._activate_drawing(SECTION_LINE_HINT)

    def _section_drawn(self, fid: str, geometry) -> None:
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
                if self.iface.createNewMapCanvas3D(self.tr("Terrain Sketch 3D")) is not None:
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
```

Replace the whole file:

**File:** `terrain_sketch/qgis_io/layers.py`
```python
"""The "Terrain Sketch" layer group: modified DEM, change, hillshade and sketch outlines."""
from __future__ import annotations

from qgis.core import (Qgis, QgsColorRampShader, QgsDataProvider, QgsFeature, QgsFillSymbol, QgsHillshadeRenderer,
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

    def repoint(self, working_path: str, change_path: str) -> None:
        """Read the working and change rasters from the files they were moved to, keeping each layer's style
        (and so a 3D terrain on the Modified DEM layer). Layers the user removed are skipped."""
        options = QgsDataProvider.ProviderOptions()
        for layer_id, path in ((self.change_id, change_path), (self.hillshade_id, working_path),
                               (self.working_id, working_path)):
            layer = self.project.mapLayer(layer_id)
            if layer is not None:
                layer.setDataSource(path, layer.name(), "gdal", options)

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
import shutil
from dataclasses import dataclass

import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer

from ..core.grid import DemGrid, Window

gdal.UseExceptions()

WARN_CELLS = 50_000_000
WORKING_NAME, CHANGE_NAME = "working_dem.tif", "change.tif"
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
        self.working_path = os.path.join(folder, WORKING_NAME)
        self.change_path = os.path.join(folder, CHANGE_NAME)
        self._original = original
        self._info = info
        _write_tif(self.working_path, _for_output(original.data, original.valid, info.nodata), original, info)
        _write_tif(self.change_path, _for_output(np.zeros(original.data.shape), original.valid, info.nodata),
                   original, info)

    def move_to(self, folder: str) -> None:
        """Copy both files into `folder` and write there from now on. The old files are left for the caller
        to remove, so a copy that fails half way changes nothing: the old ones are still the ones in use."""
        os.makedirs(folder, exist_ok=True)
        working, change = os.path.join(folder, WORKING_NAME), os.path.join(folder, CHANGE_NAME)
        shutil.copyfile(self.working_path, working)
        shutil.copyfile(self.change_path, change)
        self.folder, self.working_path, self.change_path = folder, working, change

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

Run: `scripts/test.sh tests/qgis/test_scenario_files.py tests/qgis/test_scenario_panel.py` → Expected: `35 passed`
Run: `scripts/test.sh` → Expected: `523 passed`

- [ ] **Step 5: Commit**

```bash
git add terrain_sketch/gui/controller.py terrain_sketch/gui/help_texts.py terrain_sketch/gui/main_dock.py terrain_sketch/qgis_io/layers.py terrain_sketch/qgis_io/raster_io.py tests/qgis/conftest.py tests/qgis/test_scenario_files.py tests/qgis/test_scenario_panel.py
git commit -m "feat: keep the working rasters beside a saved scenario, and open a scenario on its own DEM"
```

---

## Manual check in QGIS (for the human, after merge)

The suite cannot see these. Plans 2-7 still have their own lists waiting.

1. `scripts/dev_install.sh`, restart QGIS 4, load a projected DEM, open Terrain Sketch, press **Start**, draw a dike and a pond.
2. Select the dike. The cross profile shows both sides with "Left" and "Right"; draw the dike west to east and check that its left is the north side on the map. Untick Symmetric, double-click on the left slope to add a berm, and check the map.
3. Click a profile handle and hold the Up arrow for a second: the plot moves smoothly, and when you let go the map updates once and Undo takes it back in one step.
4. Drag a crest edge in the cross profile: Width, Side slope and Max. slope reach in the Properties page follow.
5. Type a value in Height without pressing Enter, then click the Undo button: the typed value stays; Enter applies it.
6. Select the pond. The right-hand panel shows a section: dashed before, solid after, and a dashed line on the map. **Draw section line**, draw across the pond, finish with a right-click: the section follows. **Reset line** puts it back.
7. Look at the tool gallery in light and dark themes: the seven pictures should be easy to tell apart at their small size, and the path/flat pairs should read as "follows the ground" and "level". Hover **Pixels to change** for the three pictures.
8. Move the Terrain Sketch panel to the left, float the Profiles panel, collapse About this tool, restart QGIS and open Terrain Sketch: all three come back as you left them.
9. Save a scenario as `flood.gpkg`: a `flood_files` folder appears beside it and the Modified DEM layer's source (Layer Properties ▸ Information) points into it. Save the QGIS project, close QGIS, reopen the project: the Modified DEM layer is still there.
10. **New scenario**, draw something, and check that `flood_files/working_dem.tif` did not change (its modified time).
11. Open a scenario made on another DEM whose file is still on disk: choose **Start on its DEM** and check that the session is on that DEM with the scenario's features.
12. Save a scenario into a read-only folder, or onto a USB stick you then remove: expect a warning that the working rasters stayed where they were, not a crash.

## Still open after Plan 8

| Item | Why not here |
|---|---|
| A multi-part path's long profile shows the longest part, not "the part nearest the last click" (spec §5.4) | Needs the map click routed to the profile panel; the longest part is a usable stand-in. |
| Replacing a scenario that is open as a QGIS layer on Windows; `_check_replaceable` being check-then-replace | Cannot be tested on macOS; accepted as ruled in Plan 6. |
| A settings merge has no time boundary; `_restore_terrain` treats any DEM terrain on the Modified DEM layer as ours | Ruled acceptable in Plan 7; revisit if the manual checks surprise. |
| `EXPORT_REPLACE` repeats `SCENARIO_REPLACE`'s text | One constant per message is the file's convention. |
| Translations | Out of scope for v1 (spec §2). |
