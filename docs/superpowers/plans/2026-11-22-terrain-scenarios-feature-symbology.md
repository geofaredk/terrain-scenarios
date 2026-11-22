# Per-Feature Symbology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each Terrain Scenarios feature carries its own map symbol, edited through QGIS's own layer symbology, shown as a swatch in its feature-list row, and saved with the scenario.

**Architecture:** `TerrainFeature.style` (symbol XML, `None` = default) is the source of truth. `SketchLayers` keeps "Sketch outlines" on a Categorized renderer on a new `fid` field, updated in place from the features; the controller reads edits made in QGIS's UI back into the features as undoable changes, and stops managing the renderer when the user replaces it with another type. The list row and the feature page show the symbol.

**Tech Stack:** QGIS 4.2.3 Python API (PyQt6 via `qgis.PyQt`), GDAL/OGR for the scenario file, pytest with a headless `QgsApplication`.

**Spec:** `docs/superpowers/specs/2026-11-22-terrain-scenarios-feature-symbology-design.md` — read it first; this plan argues from it.

## Global Constraints

- Run tests only through `QGIS_APP=/Applications/QGIS-final-4_2_3.app scripts/test.sh [pytest args]` (the installed app is 4.2.3; the script's default still names 4.2.2). Never run `scripts/dev_install.sh`.
- Baseline before Task 1: **654 passed**. Each task states its expected new total.
- Native QGIS widgets only, no stylesheets (main spec, "Look").
- Every Qt slot, signal handler and paint callback the plugin adds catches `Exception` and logs to `QgsMessageLog` with `LOG_TAG` — an exception escaping into Qt aborts QGIS. In a test hook reached from a signal, record and assert afterwards; never `pytest.fail()` inside it.
- `qgis_io/scenario.py` uses ogr/osr only; `model/feature.py` imports no QGIS.
- User-facing text lives in `terrain_scenarios/gui/help_texts.py`.
- QGIS facts verified by probe (spec, Constraints): a Layers-panel symbol edit emits only `repaintRequested`; checkbox and label edits emit `styleChanged`; Layer Properties ▸ Apply emits `rendererChanged`. Symbol XML has random symbol-layer `id`s. `originalSymbolForFeature` segfaults on an unstarted renderer. Keep the list returned by `renderer.categories()` alive while using a category's symbol.

## Review Focus

1. **A Layers-panel edit re-enters the controller.** Writing the edit back commits, which rewrites the outlines and the renderer, which emits `repaintRequested`/`styleChanged` again. Expected: exactly one undo step, no loop. Tested in Task 3 (`test_layers_panel_symbol_edit_is_one_undo_step`).
2. **The user removed the outline layer.** Expected: the Style button and undo still change the stored style, rows show the stored style, nothing raises. Tested in Task 3 (`test_styles_work_without_the_outline_layer`).
3. **A scenario whose `style` text is not a symbol** (hand-edited, or from a later version). Expected: it opens, that feature is unstyled. Tested in Task 2 (`test_from_xml_rejects_what_is_not_a_fill_symbol`) and Task 4 (`test_row_with_unreadable_style_shows_the_tool_diagram`).
4. **Categories that are not features** — an "all other values" category, or values left from a Classify. Expected: ignored on read-back, never a crash, never a phantom rename. Tested in Task 3 (`test_categories_that_are_not_features_are_ignored`).
5. **Turning a styled feature off and on.** Expected: its category leaves the legend and comes back with the same symbol. Tested in Task 3 (`test_turned_off_feature_keeps_its_style`).

---

### Task 1: The style field on a feature and in the scenario file

**Files:**
- Modify: `terrain_scenarios/model/feature.py` (dataclass field, `to_dict`, `from_dict`)
- Modify: `terrain_scenarios/qgis_io/scenario.py` (`FIELDS`, `_to_ogr`, `_from_ogr`)
- Test: `tests/core/test_feature.py`, `tests/core/test_engine.py`, `tests/qgis/test_scenario_file.py`

**Interfaces:**
- Produces: `TerrainFeature.style: str | None = None` (last field). Scenario column `style` (OFTString, NULL = unstyled).

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_feature.py
def test_style_round_trips_through_the_dict():
    f = replace(new_feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(0, 0), (5, 0)]), 1.0), style="<symbol/>")
    assert TerrainFeature.from_dict(json.loads(json.dumps(f.to_dict()))).style == "<symbol/>"

def test_a_dict_without_style_is_unstyled():
    d = new_feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(0, 0), (5, 0)]), 1.0).to_dict()
    del d["style"]
    assert TerrainFeature.from_dict(d).style is None

# tests/core/test_engine.py — use the file's existing stack/feature fixtures
def test_a_style_only_change_recomputes_nothing():
    # after stack.update([f]) has run once:
    assert stack.update([replace(f, style="<symbol/>")]) is None

# tests/qgis/test_scenario_file.py
def test_style_survives_save_and_load(tmp_path):
    c = start_session(tmp_path)
    styled = [replace(f, style="<symbol a='1'/>") if i == 0 else f for i, f in enumerate(two_features(c))]
    path = str(tmp_path / "styled.gpkg")
    save(path, styled, dem_meta(c.info, c.stack.original))
    loaded, _ = load(path)
    assert [f.style for f in loaded] == ["<symbol a='1'/>", None]

def test_a_scenario_without_a_style_column_opens_unstyled(tmp_path):
    # save, then drop the column with ogr.Open(path, 1) / layer.DeleteField(index of "style")
    assert all(f.style is None for f in load(path)[0])
```

Also add `"style"` to the documented-field set in `test_the_file_is_a_readable_geopackage_with_the_documented_layer`.

- [ ] **Step 2: Run them to see them fail**

Run: `QGIS_APP=/Applications/QGIS-final-4_2_3.app scripts/test.sh tests/core/test_feature.py tests/core/test_engine.py tests/qgis/test_scenario_file.py`
Expected: the new tests FAIL (`unexpected keyword argument 'style'` / missing field).

- [ ] **Step 3: Implement**

`style` is not added to `engine.COMPUTED_FIELDS`, which is what makes a style-only change free. `_to_ogr` sets `style` only when not `None`. `_from_ogr` reads it only when `row.GetFieldIndex("style") >= 0` and maps `""` to `None`.

- [ ] **Step 4: Run the full suite**

Run: `QGIS_APP=/Applications/QGIS-final-4_2_3.app scripts/test.sh`
Expected: **659 passed**.

- [ ] **Step 5: Commit** — `feat(model): a feature carries its own symbol, saved in the scenario file`

---

### Task 2: Symbols and the per-feature renderer on the outline layer

**Files:**
- Create: `terrain_scenarios/qgis_io/symbols.py`
- Modify: `terrain_scenarios/qgis_io/layers.py` (fields, constructor, `set_outlines`, new methods; `_style_outlines` keeps only the labelling and read-only part, its symbol moves to `symbols.default_symbol`)
- Modify: `terrain_scenarios/gui/controller.py:_outline_items` (add `f.id` as the first tuple element — the only caller)
- Test: create `tests/qgis/test_symbols.py`; modify `tests/qgis/test_layers.py` (the `set_outlines` call in `test_refresh_shows_new_values_and_outlines_update` gains a fid)

**Interfaces:**
- Produces, in `terrain_scenarios/qgis_io/symbols.py`:
  - `default_symbol() -> QgsFillSymbol` — transparent fill, outline `35,35,35,255`, width `0.5`, style `dash` (today's look).
  - `to_xml(symbol: QgsSymbol) -> str` — `QgsSymbolLayerUtils.saveSymbol` into a `QDomDocument`, with every ` id="…"` attribute removed so equal symbols give equal text.
  - `from_xml(text: str | None) -> QgsFillSymbol | None` — `None` for `None`, `""`, unparseable text, or a symbol that is not a fill symbol.
  - `style_of(symbol: QgsSymbol | None) -> str | None` — `None` when `symbol` is `None` or equals the default symbol, else `to_xml(symbol)`.
  - `preview_pixmap(symbol: QgsSymbol, size: QSize) -> QPixmap` — `QgsSymbolLayerUtils.symbolPreviewPixmap(symbol, size, 0)`.
- Produces, on `SketchLayers` (`qgis_io/layers.py`):
  - `FID_FIELD = "fid"`; outline fields are now `fid:string, name:string, tool:string`.
  - `set_outlines(items)` — items are `(fid, name, tool label, QgsGeometry)`.
  - `is_managed() -> bool` — outline layer still in the project and its renderer is a `QgsCategorizedSymbolRenderer` whose `classAttribute()` is `"fid"`.
  - `apply_styles(entries) -> None` — `entries`: list of `(fid, name, style)` for the enabled features, in list order. No-op unless `is_managed()`. Updates **in place** (`updateCategoryLabel`, `updateCategorySymbol`, `addCategory`, `deleteCategory`), touching a category only where it differs; deletes categories whose value is neither an entry fid nor empty/`None`; keeps each category's render state. Ends with `triggerRepaint()` and `emitStyleChanged()`.
  - `read_styles() -> dict[str, tuple[str, str | None]]` — `{value: (label, style_of(symbol))}` for every category with a non-empty value; `{}` unless `is_managed()`.
  - `use_feature_styles(entries) -> None` — replaces the renderer with a new Categorized renderer on `fid` built from `entries` (same entry type). No-op when the layer is gone.
  - `drawn_symbol(fid: str) -> QgsSymbol | None` — the symbol the current renderer draws for that feature: clone the renderer, `startRender(QgsRenderContext(), fields)`, find the feature by `"fid" = '<fid>'`, `originalSymbolForFeature`, clone it, `stopRender`. `None` when the layer is gone, the feature is not on it, or the renderer draws nothing for it.
  - The constructor sets an empty Categorized renderer on `fid`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/qgis/test_symbols.py
def test_equal_symbols_give_equal_xml():
    assert to_xml(default_symbol()) == to_xml(default_symbol())

def test_xml_round_trips_a_symbol():
    red = QgsFillSymbol.createSimple({"color": "255,0,0,255"})
    assert to_xml(from_xml(to_xml(red))) == to_xml(red)

def test_the_default_symbol_is_no_style():
    assert style_of(default_symbol()) is None and style_of(None) is None
    assert style_of(QgsFillSymbol.createSimple({"color": "255,0,0,255"})) is not None

def test_from_xml_rejects_what_is_not_a_fill_symbol():
    line = QgsLineSymbol.createSimple({})
    assert from_xml(None) is None and from_xml("") is None and from_xml("not xml") is None
    assert from_xml(to_xml(line)) is None

# tests/qgis/test_layers.py
def test_apply_styles_gives_each_feature_a_category(tmp_path):
    _, _, layers = _layers(tmp_path)
    red = to_xml(QgsFillSymbol.createSimple({"color": "255,0,0,255"}))
    layers.apply_styles([("a", "North dike", red), ("b", "Pond", None)])
    cats = layers.outlines.renderer().categories()
    assert [(c.value(), c.label()) for c in cats] == [("a", "North dike"), ("b", "Pond")]
    assert to_xml(cats[0].symbol()) == red and style_of(cats[1].symbol()) is None

def test_apply_styles_updates_in_place_and_keeps_render_state(tmp_path):
    # apply [a, b]; uncheck b via renderer.updateCategoryRenderState(1, False); keep the renderer object;
    # apply [a renamed, b] -> same renderer object (`is`), b still unchecked, a relabelled
    ...

def test_apply_styles_drops_features_no_longer_listed_but_keeps_an_all_other_values_category(tmp_path):
    # add QgsRendererCategory("", default_symbol(), "other") by hand; apply [a] after [a, b]
    assert [c.value() for c in layers.outlines.renderer().categories()] == ["a", ""]

def test_read_styles_reports_labels_and_styles(tmp_path): ...
def test_a_replaced_renderer_is_left_alone(tmp_path):
    layers.outlines.setRenderer(QgsSingleSymbolRenderer(default_symbol()))
    assert not layers.is_managed()
    layers.apply_styles([("a", "A", None)])
    assert isinstance(layers.outlines.renderer(), QgsSingleSymbolRenderer) and layers.read_styles() == {}
    layers.use_feature_styles([("a", "A", None)])
    assert layers.is_managed()

def test_drawn_symbol_is_what_the_map_draws(tmp_path):
    # set_outlines with fid "a"; single-symbol renderer in red -> to_xml(drawn_symbol("a")) == red;
    # drawn_symbol("missing") is None
    ...
```

- [ ] **Step 2: Run them to see them fail**

Run: `QGIS_APP=/Applications/QGIS-final-4_2_3.app scripts/test.sh tests/qgis/test_symbols.py tests/qgis/test_layers.py`
Expected: FAIL (`No module named 'terrain_scenarios.qgis_io.symbols'`).

- [ ] **Step 3: Implement** `symbols.py` and the `SketchLayers` changes as listed in Interfaces, and the `_outline_items` tuple change.

- [ ] **Step 4: Run the full suite**

Expected: **669 passed** (4 + 6 new).

- [ ] **Step 5: Commit** — `feat(layers): a per-feature categorized style on the outline layer`

---

### Task 3: The controller keeps features and the layer style in step

**Files:**
- Modify: `terrain_scenarios/gui/controller.py`
- Modify: `terrain_scenarios/gui/help_texts.py` — add `UNDO_STYLE = "Change the style of {}"` and `UNDO_STYLES = "Change feature styles"` beside the other `UNDO_` strings.
- Test: create `tests/qgis/test_feature_styles.py`

**Interfaces:**
- Consumes: Task 2's `SketchLayers` methods, `symbols.from_xml`.
- Produces, on `SketchController`:
  - `stylesChanged = pyqtSignal()` — a feature's displayed symbol may have changed (emitted after every outline-layer style event and after `use_feature_styles`).
  - `set_style(fid: str, style: str | None) -> None` — through `update_feature`. `_describe` gains: `fields == {"style"}` → `(UNDO_STYLE.format(feature.name), (feature.id, fields))`, so the steps of one editing session merge.
  - `uses_feature_styles() -> bool` — `True` with no session, with the outline layer removed, or while `layers.is_managed()`.
  - `use_feature_styles() -> None` — `layers.use_feature_styles(entries)`, then `stylesChanged`.
  - `display_symbol(fid: str) -> QgsSymbol | None` — `None` for an unknown fid. For an enabled feature while `not uses_feature_styles()`: `layers.drawn_symbol(fid)`. Otherwise `from_xml(feature.style)` (`None` = unstyled).

Behaviour:
- `_set` calls `layers.apply_styles(entries)` right after `set_outlines`, with entries `(f.id, f.name, f.style)` for enabled features.
- `set_dem` connects the new outline layer's `repaintRequested`, `styleChanged` and `rendererChanged` to one guarded handler `_on_outline_style()`.
- A flag set around every write the controller makes to the outline layer (`set_outlines`, `apply_styles`, `use_feature_styles`) makes `_on_outline_style()` return at once while it is set.
- Otherwise, when `layers.is_managed()`: compare `read_styles()` with the enabled features (ignore values that are not an enabled feature's id, and blank labels). Build one new feature list with every changed `style` and `name` and `_commit` it once: text `UNDO_STYLE.format(name)` when exactly one feature changed only its style, `UNDO_RENAME.format(old name)` when exactly one changed only its name, else `UNDO_STYLES`. A feature with no category keeps its style. Then emit `stylesChanged` (managed or not).

- [ ] **Step 1: Write the failing tests** (in `tests/qgis/test_feature_styles.py`, using `start_session`, `line_through`, `UTM` from `qgis_helpers`; `RED` = `to_xml` of a red fill)

```python
def test_set_style_is_one_undoable_step_and_marks_unsaved(tmp_path):
    c = start_session(tmp_path); dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    count = c.undo_stack.count()
    c.set_style(dike.id, RED); c.set_style(dike.id, BLUE)
    assert c.find(dike.id).style == BLUE and c.undo_stack.count() == count + 1 and c.is_dirty
    assert c.undo_stack.undoText() == "Change the style of " + dike.name
    c.undo_stack.undo()
    assert c.find(dike.id).style is None

def test_set_style_does_not_touch_the_terrain(tmp_path):
    # patch c.files.write with a counting wrapper; set_style -> 0 calls
    ...

def test_set_style_reaches_the_map(tmp_path):
    cats = c.layers.outlines.renderer().categories()
    assert to_xml(cats[0].symbol()) == RED

def test_layers_panel_symbol_edit_is_one_undo_step(tmp_path):
    # QgsLayerTreeModel(root).layerLegendNodes(tree layer of c.layers.outlines); node.setSymbol(red clone)
    assert c.find(dike.id).style == RED and c.undo_stack.count() == count + 1

def test_layers_panel_label_edit_renames_the_feature(tmp_path):
    # node.setData("North dike", Qt.ItemDataRole.EditRole)
    assert c.find(dike.id).name == "North dike" and c.undo_stack.undoText() == "Rename " + old_name

def test_unticking_a_category_changes_no_feature(tmp_path):
    # node.setData(Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
    assert c.find(dike.id).enabled and c.undo_stack.count() == count

def test_categories_that_are_not_features_are_ignored(tmp_path):
    # add categories ("", …) and ("deadbeef", …) to the renderer, emitStyleChanged()
    assert c.features == before and c.undo_stack.count() == count

def test_turned_off_feature_keeps_its_style(tmp_path):
    c.set_style(dike.id, RED); c.set_enabled(dike.id, False)
    assert [cat.value() for cat in c.layers.outlines.renderer().categories()] == []
    c.set_enabled(dike.id, True)
    cats = c.layers.outlines.renderer().categories()
    assert to_xml(cats[0].symbol()) == RED

def test_duplicate_copies_the_style(tmp_path): ...

def test_a_replaced_renderer_is_kept_and_shown(tmp_path):
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(green))
    c.set_style(dike.id, RED)                     # stored, not drawn
    assert isinstance(c.layers.outlines.renderer(), QgsSingleSymbolRenderer)
    assert not c.uses_feature_styles() and to_xml(c.display_symbol(dike.id)) == to_xml(green)
    c.use_feature_styles()
    assert c.uses_feature_styles() and to_xml(c.display_symbol(dike.id)) == RED

def test_styles_work_without_the_outline_layer(tmp_path):
    QgsProject.instance().removeMapLayer(c.layers.outlines_id)
    c.set_style(dike.id, RED)
    assert c.uses_feature_styles() and to_xml(c.display_symbol(dike.id)) == RED

def test_styles_come_back_after_save_and_open(tmp_path):
    # save_scenario, set_style(None), open_scenario -> display_symbol and category symbol are RED again
    ...
```

- [ ] **Step 2: Run them to see them fail**

Run: `QGIS_APP=/Applications/QGIS-final-4_2_3.app scripts/test.sh tests/qgis/test_feature_styles.py`
Expected: FAIL (`'SketchController' object has no attribute 'set_style'`).

- [ ] **Step 3: Implement** as described above.

- [ ] **Step 4: Run the full suite**

Expected: **681 passed** (12 new).

- [ ] **Step 5: Commit** — `feat(controller): feature styles follow edits made in QGIS's symbology`

---

### Task 4: The feature list shows the symbol

**Files:**
- Modify: `terrain_scenarios/gui/feature_list.py`
- Test: `tests/qgis/test_feature_list.py`

**Interfaces:**
- Consumes: `controller.display_symbol`, `controller.stylesChanged`, `symbols.preview_pixmap`.
- Produces: `SYMBOL_ROLE = Qt.ItemDataRole.UserRole + 4` returning `controller.display_symbol(fid)`.

`FeatureListModel` connects `stylesChanged` to `_sync`. `FeatureRowDelegate._paint` draws `preview_pixmap(symbol, PICTURE_SIZE)` into `picture_rect` when `SYMBOL_ROLE` gives a symbol, else the tool diagram as today. The subtitle is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
def test_unstyled_row_has_no_symbol_and_keeps_its_diagram(tmp_path):
    assert model.data(index, SYMBOL_ROLE) is None and model.data(index, PICTURE_ROLE) == "tool_raise_path"

def test_styled_row_carries_the_symbol(tmp_path):
    c.set_style(dike.id, RED)
    assert to_xml(model.data(index, SYMBOL_ROLE)) == RED

def test_row_with_unreadable_style_shows_the_tool_diagram(tmp_path):
    c.set_style(dike.id, "not xml")
    assert model.data(index, SYMBOL_ROLE) is None

def test_styled_row_paints_the_swatch(tmp_path):
    # paint the row into a QImage via the delegate; the pixel at picture_rect's centre is the red fill
    ...

def test_a_layers_panel_edit_repaints_the_rows(tmp_path):
    # record model.dataChanged; edit through the legend node; assert it was emitted
    ...
```

- [ ] **Step 2: Run them to see them fail** — `… scripts/test.sh tests/qgis/test_feature_list.py`; expected FAIL (`cannot import name 'SYMBOL_ROLE'`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite** — expected **686 passed**.
- [ ] **Step 5: Commit** — `feat(gui): a styled feature's row shows its symbol`

---

### Task 5: Style button on the feature page, and "Use feature styles again"

**Files:**
- Modify: `terrain_scenarios/gui/properties_page.py`
- Modify: `terrain_scenarios/gui/main_dock.py` (`__init__`, `_session_changed`, `feature_menu`, `shutdown`)
- Modify: `terrain_scenarios/gui/help_texts.py` — add:
  - `STYLE_TIP = "How this feature looks on the map. Copy, paste or reset it from the arrow menu."`
  - `STYLE_LAYER_TIP = "The Sketch outlines layer has a style of its own. Choose 'Use feature styles again' to style single features."`
  - `USE_FEATURE_STYLES = "Use feature styles again"`
- Test: `tests/qgis/test_feature_styles.py` (page and menu tests)

**Interfaces:**
- Consumes: `controller.set_style`, `uses_feature_styles`, `use_feature_styles`, `stylesChanged`, `symbols.from_xml`/`default_symbol`/`style_of`.
- Produces: `PropertiesPage.style_button: QgsSymbolButton`; `MainDock.use_styles_action: QAction`.

Page: a `QgsSymbolButton` (`setSymbolType(Qgis.SymbolType.Fill)`, `setShowNull(True)`, dialog title "Feature style") as a "Style" row at the end of `self.form`. `show_feature` and `stylesChanged` load it with signals blocked: `from_xml(feature.style) or default_symbol()`. It is enabled only while `controller.uses_feature_styles()`, with `STYLE_TIP` or `STYLE_LAYER_TIP` as its tooltip. Its guarded `changed` handler calls `controller.set_style(fid, style_of(button.symbol()))`. `setToNull` gives `None`, which is "back to default".

Dock: `use_styles_action` calls `controller.use_feature_styles`. In `__init__`: `iface.addCustomActionForLayerType(action, "", Qgis.LayerType.Vector, False)`. On every `sessionChanged` with a session: `iface.addCustomActionForLayer(action, controller.layers.outlines)`. `shutdown`: `iface.removeCustomActionForLayerType(action)`. The action is enabled only while `not controller.uses_feature_styles()`; this is refreshed on `stylesChanged` and `sessionChanged`. `feature_menu` adds it above the separator only while `not controller.uses_feature_styles()`.

- [ ] **Step 1: Write the failing tests**

```python
def test_style_button_shows_and_sets_the_feature_style(tmp_path):
    # panel(tmp_path); open the feature page for dike; page.style_button.setSymbol(red)
    assert c.find(dike.id).style == RED
    page.style_button.setToNull()
    assert c.find(dike.id).style is None
    assert style_of(page.style_button.symbol()) is None     # shows the default look again after reload

def test_opening_the_page_records_nothing(tmp_path):
    assert c.undo_stack.count() == count                    # loading the button must not commit

def test_style_button_follows_a_layers_panel_edit(tmp_path): ...

def test_style_button_is_disabled_under_a_layer_style(tmp_path):
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(green))
    assert not page.style_button.isEnabled() and page.style_button.toolTip() == STYLE_LAYER_TIP

def test_use_feature_styles_again_is_offered_only_when_needed(tmp_path):
    iface.addCustomActionForLayer.assert_called_with(dock.use_styles_action, c.layers.outlines)
    assert not dock.use_styles_action.isEnabled()
    assert USE_FEATURE_STYLES not in [a.text() for a in dock.feature_menu(index).actions()]
    c.layers.outlines.setRenderer(QgsSingleSymbolRenderer(green))
    assert dock.use_styles_action.isEnabled()
    menu_action = next(a for a in dock.feature_menu(index).actions() if a.text() == USE_FEATURE_STYLES)
    menu_action.trigger()
    assert c.uses_feature_styles()

def test_shutdown_removes_the_layer_action(tmp_path):
    dock.shutdown()
    iface.removeCustomActionForLayerType.assert_called_with(dock.use_styles_action)
```

- [ ] **Step 2: Run them to see them fail** — `… scripts/test.sh tests/qgis/test_feature_styles.py`; expected FAIL (`no attribute 'style_button'`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the full suite** — expected **692 passed**.
- [ ] **Step 5: Commit** — `feat(gui): a Style button on the feature page and "Use feature styles again"`

---

## Manual check in QGIS (after Task 5)

1. Draw two features. Both are grey dashed on the map and show their tool diagrams in the list.
2. Set one feature red with the feature page's Style button. The map and its row turn red, and Undo reverts both.
3. Right-click its entry under "Sketch outlines" in the Layers panel ▸ Change Color. The row and the Style button follow, as one undo step.
4. Rename a category's label in Layer Properties. The feature is renamed.
5. Turn the feature off and on. Its legend entry goes and comes back red.
6. Switch the layer to Single symbol. The map and the rows show that style, the Style button is greyed out, and "Use feature styles again" (Layers panel context menu, feature-list menu) brings the red back.
7. Save, Start again, Open. The red is back.
8. Switch between the light and dark themes. The swatches stay readable.
