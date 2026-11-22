# Terrain Scenarios panel redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Rebuild the Terrain Scenarios main panel as drill-in pages — a welcome view, a feature list with rich
rows, a one-page New feature flow and a feature page — using native QGIS widgets.

**Architecture:** The dock's widget becomes a `QgsPanelWidgetStack`. Its main panel holds a `QStackedWidget`
with the welcome view and the session view (toolbar, feature list, status line). `ToolGallery` and
`PropertiesPage` become `QgsPanelWidget` pages pushed onto the stack. The controller API, map tools,
scenario handling, undo and the Profiles dock are untouched.

**Tech Stack:** QGIS 4.2.2 (PyQt6 via `qgis.PyQt`), Python 3.12, pytest through `scripts/test.sh` (offscreen).

**Spec:** `docs/superpowers/specs/2026-09-15-terrain-scenarios-panel-redesign.md` (amends
`docs/superpowers/specs/2026-09-11-terrain-scenarios-design.md` §7.1–7.2).

## Global Constraints

- Native widgets only; no stylesheets, no hard-coded colours. Every colour comes from the widget's
  `QPalette`, and anything derived from it is recomputed on `QEvent.Type.PaletteChange`.
- **Every `QgsPanelWidget` calls `setDockMode(True)` before being opened.** `QgsPanelWidgetStack.setMainPanel`
  does not set it in 4.2.2, and `openPanel` on a panel that is not in dock mode opens a **modal dialog**,
  which hangs the offscreen suite forever.
- Any exception escaping a Qt slot aborts QGIS: every slot keeps its `try/except` + `QgsMessageLog` guard,
  and new slots get one.
- `QgsApplication.getThemeIcon` returns a null icon in silence for an unknown name. Do not introduce a new
  theme-icon name without a test asserting `not icon.isNull()`; prefer `QStyle` primitives for decorations.
- Help texts keep their current wording and live in `gui/help_texts.py`. New strings go there too.
- The full suite must pass at every commit: `scripts/test.sh -q`. Baseline on this branch: **557 passing**.
- Work happens on the branch `feat/panel-redesign` in the primary checkout (the QGIS profile symlinks the
  plugin from there, so the user can test it). Do not create a worktree, do not merge.

---

### Task 1: Muted text helper

**Files:**
- Create: `terrain_scenarios/gui/muted.py`
- Test: `tests/qgis/test_muted.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `muted_colour(palette: QPalette) -> QColor` and `class MutedLabel(QLabel)`. Both used by
  Tasks 2, 3 and 5.

- [ ] **Step 1: Write the failing test**

```python
"""Secondary text drawn in a colour derived from the palette, never hard-coded."""
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QWidget

from terrain_scenarios.gui.muted import MutedLabel, muted_colour


def palette_of(text: str, window: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.WindowText, QColor(text))
    palette.setColor(QPalette.ColorRole.Text, QColor(text))
    palette.setColor(QPalette.ColorRole.Window, QColor(window))
    palette.setColor(QPalette.ColorRole.Base, QColor(window))
    return palette


def test_muted_text_sits_between_the_text_and_the_background():
    light = muted_colour(palette_of("#000000", "#ffffff"))
    assert 100 < light.red() < 160 and light.red() == light.green() == light.blue()
    dark = muted_colour(palette_of("#ffffff", "#000000"))
    assert 100 < dark.red() < 160          # readable in both themes, never the background itself


def test_the_label_follows_a_theme_change():
    parent = QWidget()
    parent.setPalette(palette_of("#000000", "#ffffff"))
    label = MutedLabel("Raise path", parent)
    was = label.palette().color(QPalette.ColorRole.WindowText)
    parent.setPalette(palette_of("#ffffff", "#000000"))
    assert label.palette().color(QPalette.ColorRole.WindowText) != was
```

- [ ] **Step 2: Run it and watch it fail**

Run: `scripts/test.sh tests/qgis/test_muted.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'terrain_scenarios.gui.muted'`.

- [ ] **Step 3: Write the module**

```python
"""Secondary text: the palette's own text colour, toned down so it reads as supporting information."""
from __future__ import annotations

from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtWidgets import QLabel

BLEND = 0.45   # how far the text colour moves towards the background


def muted_colour(palette: QPalette) -> QColor:
    """The palette's text colour blended towards its background, so it follows light and dark themes."""
    text = palette.color(QPalette.ColorRole.WindowText)
    back = palette.color(QPalette.ColorRole.Window)
    mix = lambda a, b: round(a + (b - a) * BLEND)   # noqa: E731 — one expression, used three times
    return QColor(mix(text.red(), back.red()), mix(text.green(), back.green()), mix(text.blue(), back.blue()))


class MutedLabel(QLabel):
    """A label in the muted colour that repaints itself when QGIS switches theme."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self._apply()

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange:
            self._apply()
        super().changeEvent(event)

    def _apply(self) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.WindowText, muted_colour(self.palette()))
        super().setPalette(palette)
```

- [ ] **Step 4: Run the test — it passes**

Run: `scripts/test.sh tests/qgis/test_muted.py -q` → 2 passed.

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/gui/muted.py tests/qgis/test_muted.py
git commit -m "feat(gui): muted secondary text derived from the palette"
```

---

### Task 2: Feature list rows

**Files:**
- Modify: `terrain_scenarios/gui/feature_list.py`
- Test: `tests/qgis/test_feature_list.py` (add `from qgis.PyQt.QtTest import QTest`)

**Interfaces:**
- Consumes: `muted_colour` from Task 1.
- Produces:
  - `FeatureListModel` roles: `ID_ROLE` (unchanged), `SUBTITLE_ROLE`, `PICTURE_ROLE` (a `QPixmap` of the
    tool illustration at 40×20), `FLAGGED_ROLE` (bool).
  - `feature_subtitle(controller, fid) -> str` — `"{tool label}"`, plus `" · fill N m³"` and/or
    `" · cut N m³"` when those are non-zero, using `help_texts.cubic_metres`.
  - `FeatureListView.rowOpened = pyqtSignal(str)` — the feature id, emitted on a click on a row outside its
    checkbox, and on Enter/Return with a row current.
  - `FeatureRowDelegate(QStyledItemDelegate)`.
- The existing checkbox, rename, drag-reorder, context menu and `select_id`/`selected_id` behaviour is
  unchanged.

- [ ] **Step 1: Write the failing tests**

Add to `tests/qgis/test_feature_list.py` (the file already builds a controller with features; follow its
existing helpers):

```python
def test_a_row_says_what_the_feature_is_and_what_it_moves(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    model = FeatureListModel(c)
    subtitle = model.index(0).data(SUBTITLE_ROLE)
    assert subtitle.startswith("Raise path") and "fill" in subtitle and "m³" in subtitle
    assert "cut" not in subtitle                      # a raise tool only fills
    c.set_enabled(dike.id, False)                     # a feature that changes nothing says only what it is
    assert model.index(0).data(SUBTITLE_ROLE) == "Raise path"


def test_clicking_a_row_opens_it_but_clicking_its_checkbox_only_toggles_it(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))
    view.setItemDelegate(FeatureRowDelegate(view))
    view.resize(300, 120)
    opened = []
    view.rowOpened.connect(opened.append)
    rect = view.visualRect(view.model().index(0))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())      # the row body
    assert opened == [dike.id]
    box = FeatureRowDelegate.checkbox_rect(rect)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=box.center())       # the checkbox
    assert opened == [dike.id] and not c.feature(dike.id).enabled


def test_a_flagged_feature_still_shows_its_warning(tmp_path):
    ...   # keep the existing flag assertions working through FLAGGED_ROLE and the delegate's sizeHint
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/test.sh tests/qgis/test_feature_list.py -q`
Expected: FAIL on the missing `SUBTITLE_ROLE` import.

- [ ] **Step 3: Implement**

- Add the roles and `feature_subtitle`; the model returns `Qt.ItemDataRole.DecorationRole` no more — the
  delegate draws both picture and warning.
- `FeatureRowDelegate.paint` draws, left to right: the check indicator (via
  `QApplication.style().drawPrimitive(PE_IndicatorCheckBox, …)` inside the rect the delegate also uses for
  hit-testing), the picture, the title in the normal text colour, the subtitle under it in
  `muted_colour(option.palette)`, the warning icon, and `PE_IndicatorArrowRight` in the muted colour.
- `sizeHint` returns two text lines plus 6 px padding, at least the picture's height.
- Hit-testing lives in one place: `FeatureRowDelegate.checkbox_rect(option_rect)`, used by both the delegate
  and the view's `mouseReleaseEvent`.
- The view emits `rowOpened` from `mouseReleaseEvent` (outside the checkbox rect, on a valid index) and from
  `keyPressEvent` for Return/Enter.

- [ ] **Step 4: Run the tests — they pass**

Run: `scripts/test.sh tests/qgis/test_feature_list.py tests/qgis/test_list_actions.py -q`

- [ ] **Step 5: Commit**

```bash
git add terrain_scenarios/gui/feature_list.py tests/qgis/test_feature_list.py
git commit -m "feat(gui): feature rows show the tool, its picture and its volume"
```

---

### Task 3: The panel shell — stack, welcome view, toolbar, status line

**Files:**
- Modify: `terrain_scenarios/gui/main_dock.py`
- Modify: `terrain_scenarios/gui/help_texts.py` (add `START_INTRO`, `START_HEADING`, `SKETCHING_ON`,
  `CHANGE_DEM_LINK`, `SCENARIO_MENU_TIP`)
- Test: `tests/qgis/test_panels.py`, `tests/qgis/test_scenario_panel.py`, `tests/qgis/test_dock_plugin.py`

**Interfaces:**
- Consumes: `MutedLabel` (Task 1), `FeatureListView.rowOpened` (Task 2).
- The tests below use a `panel(tmp_path)` helper that builds `fake_iface()`, a `SketchController`, a
  `MainDock`, sets a DEM and presses Start — the same helper `tests/qgis/test_view_3d.py` already defines.
  Move one into `tests/qgis/qgis_helpers.py` and let both files use it.
- Produces, on `MainDock`:
  - `stack: QgsPanelWidgetStack`, `main_panel: QgsPanelWidget`, `views: QStackedWidget` with
    `VIEW_WELCOME, VIEW_SESSION = range(2)`.
  - `open_page(page: QgsPanelWidget)` — sets dock mode and opens it through `main_panel.openPanel`;
    `close_page()` — accepts the open page if there is one.
  - Kept attributes: `dem_combo`, `start_button`, `feature_view`, `model`, `toolbar`, `new_button`,
    `undo_action`, `redo_action`, `export_button`, `view_3d_button`, `profiles_button`.
  - New: `scenario_button` (`QToolButton`, `InstantPopup`) with actions `new_scenario_action`,
    `open_scenario_action`, `save_scenario_action`, `save_as_scenario_action`, connected to the existing
    slots unchanged. `scenario_actions` is the tuple of the four.
  - `status_label: MutedLabel` showing `SKETCHING_ON.format(name)` plus the `Change…` link.
- Removed: `list_splitter` and its settings key, `pages`/`PAGE_*`, `hint` (moves to the New feature page in
  Task 4 — keep the attribute until then so nothing breaks mid-plan), `list_row` buttons `delete_button` and
  `edit_button` (they move to the feature page in Task 5; keep them constructed but not laid out until then).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_panel_opens_on_a_welcome_view_and_switches_to_the_session(tmp_path):
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    assert dock.views.currentIndex() == VIEW_WELCOME
    layer = dem_layer(tmp_path)
    dock.dem_combo.setLayer(layer)
    dock.start_button.click()
    assert dock.views.currentIndex() == VIEW_SESSION
    assert layer.name() in dock.status_label.text()


def test_every_page_the_panel_opens_is_in_dock_mode(tmp_path):
    """A panel that is not in dock mode opens a modal dialog, which never returns offscreen."""
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    assert dock.main_panel.dockMode() and dock.stack.currentPanel().dockMode()


def test_the_scenario_actions_live_behind_one_menu_button(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    assert [a.text() for a in dock.scenario_button.menu().actions()] == [
        "New scenario", "Open scenario…", "Save scenario", "Save scenario as…"]


def test_changing_the_dem_goes_back_to_the_welcome_view(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dock.status_label.linkActivated.emit("change")
    assert dock.views.currentIndex() == VIEW_WELCOME and c.has_dem     # the session keeps running until Start
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/test.sh tests/qgis/test_panels.py -q` → FAIL on the missing `views` attribute.

- [ ] **Step 3: Implement**

Restructure `MainDock.__init__` into: build the welcome view; build the session view (toolbar, feature view,
status line); put both in `self.views`; put `self.views` in `self.main_panel` (a `QgsPanelWidget` with
`setDockMode(True)`); `self.stack.setMainPanel(self.main_panel)`; `self.setWidget(self.stack)`.
`_session_changed` switches `self.views` and closes any open page when the session ends. Keep every existing
signal connection and slot body; only the widget that holds them moves.

- [ ] **Step 4: Run the suite**

Run: `scripts/test.sh -q`. Expect failures only in tests that name the removed structure; update those to
the new one in this task, keeping their assertions.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(gui): panel stack with a welcome view, a slim toolbar and a status line"
```

---

### Task 4: New feature page

**Files:**
- Modify: `terrain_scenarios/gui/tool_gallery.py` (becomes the page), `terrain_scenarios/gui/main_dock.py`
- Test: `tests/qgis/test_panels.py`, `tests/qgis/test_guidance.py`

**Interfaces:**
- `ToolGallery(QgsPanelWidget)` with `setPanelTitle(tr("New feature"))`, `setDockMode(True)` in `__init__`,
  and the existing signals `drawRequested(Tool, Mode, Method)` and
  `layerRequested(Tool, Mode, layer, selected_only)` unchanged.
- Kept methods: `selected_tool`, `selected_mode`, `select_tool`, `select_mode`, `brush_radius`,
  `set_brush_radius`, `set_radius_units`, `refresh_icons`.
- New: `show_hint(text: str)` / `clear_hint()` — the drawing hint now lives on this page.
- `MainDock.new_button` opens the page; when the controller adds a feature while the page is open, the page
  closes and the feature page opens (Task 5 wires the second half; until then it closes).

- [ ] **Step 1: Write the failing tests**

```python
def test_the_tools_are_shown_as_tiles(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    gallery = dock.gallery
    assert gallery.tool_list.viewMode() == QListView.ViewMode.IconMode
    assert gallery.tool_list.count() == len(Tool)
    assert not gallery.tool_list.item(0).icon().isNull()


def test_the_brush_radius_is_only_there_when_the_brush_is(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.RAISE_PATH)
    dock.gallery.select_mode(Mode.PATH)
    assert not dock.gallery.brush_spin.isVisibleTo(dock.gallery)     # no brush on a line
    dock.gallery.select_mode(Mode.AREA)
    assert dock.gallery.brush_spin.isVisibleTo(dock.gallery)


def test_shape_is_a_segmented_pair_that_disables_what_the_tool_cannot_do(tmp_path):
    _iface, _c, dock = panel(tmp_path)
    dock.new_button.click()
    dock.gallery.select_tool(Tool.LOWER_FLAT)
    assert dock.gallery.line_mode.isCheckable() and dock.gallery.area_mode.isCheckable()
    assert dock.gallery.mode_group.checkedButton() is not None


def test_drawing_a_feature_closes_the_new_feature_page(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dock.new_button.click()
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert dock.stack.currentPanel() is dock.main_panel
```

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/test.sh tests/qgis/test_panels.py -q`.

- [ ] **Step 3: Implement** the tile view (`IconMode`, `setUniformItemSizes(True)`,
`setResizeMode(QListView.ResizeMode.Adjust)`, `setMovement(QListView.Movement.Static)`, `setWordWrap(True)`,
`setIconSize(QSize(96, 48))`, `setGridSize(QSize(116, 92))`), the segmented `QToolButton` pair for Shape, the
method grid, brush-radius visibility, the hint label, and the page wiring in `MainDock`.

- [ ] **Step 4: Run the suite** — `scripts/test.sh -q`, fixing the guidance tests that assert where the hint
appears.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(gui): New feature page with tool tiles and a segmented shape choice"
```

---

### Task 5: Feature page

**Files:**
- Modify: `terrain_scenarios/gui/properties_page.py`, `terrain_scenarios/gui/main_dock.py`
- Test: `tests/qgis/test_panels.py`, `tests/qgis/test_volumes_panel.py`, `tests/qgis/test_settings.py`

**Interfaces:**
- `PropertiesPage(QgsPanelWidget)`: `setDockMode(True)`; `show_feature(fid)` also sets the panel title and
  the header; new widgets `name_edit: QLineEdit`, `header_picture: QLabel`, `header_summary: MutedLabel`,
  `edit_button`, `zoom_button`, `delete_button`, `advanced: QgsCollapsibleGroupBox`.
- Signals: `deleteRequested(str)`, `zoomRequested(str)`, `editShapeToggled(bool)` — `MainDock` connects them
  to the slots it already has (`_delete_selected`, the context menu's zoom action, `_toggle_edit`), so the
  behaviour and undo entries do not change.
- The existing fields, their tooltips, the focus-highlight diagram, `_load_values`' "still typing" rule,
  `_refresh_values`, `_refresh_volumes` and `_refresh_problems` are unchanged.
- `settings.remember_collapsed("advanced_group", …, collapsed=True)` and `about_group` now also starts
  collapsed.

- [ ] **Step 1: Write the failing tests**

```python
def test_opening_a_feature_shows_its_page_with_name_and_volume(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    page = dock.properties
    assert dock.stack.currentPanel() is page and page.panelTitle() == dike.name
    assert page.name_edit.text() == dike.name and "Raise path" in page.header_summary.text()
    assert "m³" in page.header_summary.text()


def test_renaming_in_the_header_is_undoable(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.name_edit.setText("Dike north")
    dock.properties.name_edit.editingFinished.emit()
    assert c.feature(dike.id).name == "Dike north"
    c.undo_stack.undo()
    assert c.feature(dike.id).name == dike.name and dock.properties.name_edit.text() == dike.name


def test_deleting_from_the_page_goes_back_to_the_list(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.delete_button.click()
    assert dock.stack.currentPanel() is dock.main_panel and c.features == []


def test_pixels_to_change_sits_under_advanced_and_starts_collapsed(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    page = dock.properties
    assert page.advanced.isCollapsed() and page.pixel_mode.parent() is not None
    assert page.volumes.isCollapsed() and page.about.isCollapsed()
```

- [ ] **Step 2: Run them and watch them fail** — `scripts/test.sh tests/qgis/test_panels.py -q`.

- [ ] **Step 3: Implement** the header, action row, `QgsScrollArea`, the Advanced group, and the `MainDock`
wiring: `feature_view.rowOpened` → `properties.show_feature(fid)` + `open_page(properties)`; the page's
signals → the existing slots.

- [ ] **Step 4: Run the suite** — `scripts/test.sh -q`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(gui): feature page with a header, actions and grouped fields"
```

---

### Task 6: Navigation rules and the test sweep

**Files:**
- Modify: `terrain_scenarios/gui/main_dock.py`
- Test: `tests/qgis/test_panels.py`, `tests/qgis/test_undo_panel.py`, `tests/qgis/test_dock_plugin.py`,
  `tests/qgis/test_settings.py`, and any test still describing the old structure.

- [ ] **Step 1: Write the failing tests** — one per row of spec §9:

```python
def test_the_page_closes_when_its_feature_is_deleted_elsewhere(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    c.delete_feature(dike.id)
    assert dock.stack.currentPanel() is dock.main_panel


def test_undo_that_removes_the_open_feature_closes_its_page(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    c.undo_stack.undo()                       # undoes the add
    assert dock.stack.currentPanel() is dock.main_panel


def test_ending_the_session_closes_any_page_and_shows_the_welcome_view(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    c.close()
    assert dock.stack.currentPanel() is dock.main_panel and dock.views.currentIndex() == VIEW_WELCOME


def test_going_back_keeps_the_feature_selected_and_highlighted(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.rowOpened.emit(dike.id)
    dock.properties.acceptPanel()
    assert dock.feature_view.selected_id() == dike.id
```

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement** the rules in `MainDock`: `featuresChanged` closes the page when the open feature
is gone; `sessionChanged` closes pages and switches views; `stop_tools` on hide is unchanged.

- [ ] **Step 4: Run the whole suite and check the count** — `scripts/test.sh -q`; every test passes and the
count is at least the 557 baseline plus the new ones.

- [ ] **Step 5: Render the panel** with `.superpowers/plan8-tools/render_panel.py` (adapted to the new
structure) in light and dark, and check by eye that the welcome view, list, New feature page and feature page
are laid out as the spec describes. Save the images under `.superpowers/redesign/`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(gui): navigation rules for the drill-in pages"
```

---

## Manual check in QGIS (for the user, before merging)

1. Open QGIS with a DEM loaded. Terrain Scenarios opens on the welcome view; press Start.
2. New feature → the tiles reflow when you widen the dock; pick Raise path, Line, Draw; draw a dike.
3. The feature's page opens. Rename it in the header, change Height, press Ctrl+Z twice.
4. Go back; the row shows "Raise path · fill … m³" and stays selected.
5. Toggle the checkbox — it must not open the page.
6. Scenario ▾ → Save scenario, then New scenario; Export DEM…, 3D view, Profiles still work.
7. Switch QGIS between light and dark themes: the muted text and the tool pictures follow.
8. "Change…" in the status line returns to the welcome view and asks about unsaved work.
