# Terrain Sketch — per-feature symbology

Date: 2026-11-22 · Status: design, awaiting approval · Builds on `2026-09-11-terrain-sketch-design.md` and `2026-09-15-terrain-sketch-panel-redesign.md`.

## Intent

Niklas wants each sketched feature to have its own look on the map (outline colour, fill, line style — anything a QGIS symbol can do), styled with QGIS's own layer symbology rather than a plugin-specific editor. The feature list row should show that look, so the list and the map tell the same story. A feature nobody has styled keeps today's look: the grey dashed outline on the map and the tool diagram in the list.

Why: not stated beyond the request. The working assumption is telling features apart on the map (and on maps made from it) at a glance.

## Goals

- Every feature can carry its own symbol, edited through QGIS's standard symbology UI.
- The feature list row shows the feature's symbol (a legend-style swatch, like the Layers panel) in place of the tool diagram once the feature has a style; otherwise the tool diagram, as today.
- The tool stays visible as text in every row — already true: the subtitle reads "Raise path · fill 12 m³" (`gui/feature_list.py:feature_subtitle`).
- Styles survive everything a feature survives: undo/redo, Duplicate, turning off and on, Save, Open, and the layer rebuild on Start.

## Non-goals

- Per-tool styles or style presets (the user chose per-feature styles).
- Styling the Change or Modified DEM layers.
- A plugin-drawn symbol editor; the editing UI is QGIS's.
- Custom icon artwork for the tool diagrams.

## Anti-goals

- Styling that silently disappears (on Start, Open, undo, a rename) — the reason the current workaround (restyle the layer by hand) fails.
- A style change recomputing the terrain or costing a terrain update.
- UI that does not look like part of QGIS (see the native-UI rule in the main spec §"Look").

## Constraints

- QGIS 4.2 Python API, PyQt6 via `qgis.PyQt`. Native widgets only.
- `qgis_io/scenario.py` uses ogr/osr only (no `qgis.core`), so it stores a symbol as an opaque string.
- `model/feature.py` is pure data, no QGIS: the symbol is held there as a string, too.
- Scenario Open gives every feature a fresh id (`scenario.py:_from_ogr`), so nothing persisted may be keyed by feature id.
- Disabled features are not in the "Sketch outlines" layer (`controller._outline_items`), yet their row must still show their symbol.
- Paths are drawn on the map as buffered corridor polygons, so every feature's symbol is a fill symbol.
- Verified by probe in QGIS 4.2.3 (2026-11-22): a symbol edited from the Layers panel (`QgsSymbolLegendNode.setSymbol`) emits only `repaintRequested` on the layer — not `styleChanged` or `rendererChanged`; a category checkbox or label edit emits `styleChanged`; Layer Properties ▸ Apply emits `rendererChanged`. Symbol XML carries a fresh random `id` per symbol layer, so equality must ignore it. `QgsCategorizedSymbolRenderer.originalSymbolForFeature` segfaults unless the renderer was started (`startRender`). A symbol taken from `renderer.categories()[i]` dies with the temporary list: keep the list.

## Approaches

- **A. Styles live in the layer's symbology (chosen).** "Sketch outlines" gets a Categorized renderer with one category per feature. The user edits it like any QGIS layer — Layer Properties ▸ Symbology, or right-click a category in the Layers panel ▸ Edit Symbol / Change Color — plus a shortcut button on the feature page that opens QGIS's symbol editor. Chosen because it is QGIS's own symbology: map, legend, Layers panel and print layouts agree, and it is what the user asked for.
- **B. The plugin keeps each feature's symbol and owns the layer style.** A QGIS symbol button on each feature page; the plugin rebuilds the renderer from its own records. Rejected: edits made in Layer Properties would be overwritten on the next rebuild, which contradicts "use QGIS's layer symbology".

## Design

### Where a style lives

- `TerrainFeature` gains `style: str | None = None` — the feature's fill symbol as QGIS symbol XML, or `None` for "no style of its own". Pure data, compared by value like every other field. `to_dict`/`from_dict` carry it.
- This field is the source of truth. The layer's renderer is built from it, and edits made in the renderer are written back into it. That is what makes undo, Duplicate, disabled features, Save and Open work without special cases.

### The layer

- "Sketch outlines" gets a `feature_id` field next to `name` and `tool` (not `fid`: a GeoPackage export — QGIS's default for Save Features As and Make Permanent — reserves that name for its integer key). The plugin writes a `QgsCategorizedSymbolRenderer` on `feature_id` with one category per **enabled** feature, so the legend, Layers panel and print layouts list exactly what is on the map. A turned-off feature keeps its style in the model and gets its category back when turned on. The category label is the feature's name and follows renames. *(Claude's call.)*
- The renderer is updated **in place** (categories added, removed, relabelled, re-symbolled), not replaced, so renderer- and layer-level settings the user sets — opacity, blending, symbol levels, label font — last for the session. Only the per-feature symbols are saved in the scenario; the rest goes back to defaults on Start or Open. *(Claude's call: saving the whole layer style would change the file format for settings few users touch.)*
- Layers panel controls on a category: unticking a category's checkbox only hides it on the map for the session, like any QGIS layer — it does not turn the feature off or touch the terrain. Editing a category's label in Layer Properties renames the feature (undoable). *(Claude's calls.)*
- A feature with `style is None` gets the default symbol: today's transparent fill with a 0.5 dark-grey dashed outline.
- Name labels stay as today.
- The renderer is rebuilt when the feature list changes (add, delete, rename, reorder, style change) — not on every terrain update.

### Editing

- **In QGIS's UI:** when the user changes the outline layer's renderer (`rendererChanged` / `styleChanged`), the plugin reads each category's symbol back, compares it with the feature's `style`, and commits the differences as one undoable change ("Change style of North dike" for one, "Change styles" for several). A symbol equal to the default symbol is stored as `None`.
- **On the feature page:** a `QgsSymbolButton` (fill symbol type, connected to the canvas and the outline layer for the expression context) in the feature page's form, labelled "Style". Changing it commits the same change. Its built-in menu gives copy/paste of a symbol between features and a reset — "Reset" here means back to default (`None`).
- A style-only change does not run the terrain engine: the controller recognises a change whose only differing field is `style` the way it already recognises name-only and enabled-only changes, and only refreshes the outline layer and the list.
- The change marks the scenario unsaved, like any other edit.
- While the user's own renderer is in charge (see below), the Style button is disabled, with a tooltip pointing to "Use feature styles again": an edit there would not show on the map. *(Claude's call, made while planning.)*

### When the user replaces the layer's style (decided by Niklas)

- The plugin manages the layer only while its renderer is a Categorized renderer on `feature_id`. Editing symbols inside it, adding or deleting categories, and pressing **Classify** (random colours) all count as style edits: matched symbols are written back to the features as one undoable change. A feature whose category was deleted keeps its stored style and gets its category back on the next update.
- Once the user switches to anything else — Single symbol, Rule-based, Graduated, Categorized on another field, Paste Style, a loaded .qml — the plugin **keeps their renderer and stops managing it**: it no longer adds, removes or rewrites categories, and writes nothing back. Features keep their stored styles untouched.
- While their renderer is in charge, each row shows the symbol the layer actually draws for that feature (asked from the renderer per feature), so the list still matches the map. A turned-off feature, not on the map, shows its stored style or the tool diagram.
- A **"Use feature styles again"** action puts the per-feature Categorized renderer back from the stored styles. It sits in the outline layer's context menu in the Layers panel and in the feature list's menu, and is an ordinary QGIS-styled action.
- The user's own renderer is not saved in the scenario. After Save and Open, on New, or on Start, the per-feature styles are back in charge: Open and New put the per-feature renderer back on the outline layer (a fresh start), and Start builds a new layer with it.

### The feature list

- `PICTURE_ROLE` keeps returning the tool diagram name for an unstyled feature. For a styled one the row paints a swatch of the feature's symbol (`QgsSymbolLayerUtils.symbolPreviewPixmap`) at the picture's size and position. Selected rows keep the existing contrast treatment for the text; the swatch is drawn as is, like the Layers panel does.
- The subtitle is unchanged (tool name · volumes).

### Duplicate, undo, open, save

- Duplicate copies `style` (it is just another field on the copy).
- Undo/redo restore `style` with everything else; the renderer follows.
- **Save** writes a new `style` text column on the features table (empty = no style). Older files without the column open with every feature unstyled. Files saved with styles open in older plugin versions without error (the extra column is ignored).
- **Open** reads it back; the renderer is rebuilt from the loaded features, and replaces the user's own renderer if one was in charge.
- **Start** begins a session with an empty feature list (as today), and its new outline layer starts with the per-feature renderer. *(Corrected while planning: Start does not carry features over, so there are no styles to carry.)*

## Left to the builder / calls made by Claude (to check)

- Storing the symbol as QGIS XML (`QgsSymbolLayerUtils.symbolProperties`/`QgsSymbolLayerUtils.saveSymbol` round-trip) — the builder picks the exact serialisation that round-trips a fill symbol losslessly in QGIS 4.2.
- Exact placement of the Style button on the feature page, following the existing form layout.
- Tests through `scripts/test.sh` (note: its default `QGIS_APP` still names 4.2.2; the installed app is 4.2.3).
