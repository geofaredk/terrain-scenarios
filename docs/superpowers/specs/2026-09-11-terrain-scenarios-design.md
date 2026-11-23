# Terrain Scenarios — Design Spec

**Date:** 2026-09-11
**Status:** Approved in brainstorming, pending written-spec review
**Target:** QGIS 4.x (Qt6, Python 3.12). Tested against QGIS 4.2.2 on macOS.

## 1. Purpose

Terrain Scenarios is a QGIS 4 plugin for modifying a DEM playfully and non-destructively. Flood risk managers and landscape architects "draw" landscape features and SuDS (dikes, ditches, ponds, basins, barriers, trenches) onto a DEM and get back a modified DEM. They then feed that DEM into a separate flood-simulation tool.

The core values are **intuitive** (usable by non-GIS experts), **explained** (every option has a description, a usage example and an illustration) and **native** (it looks and behaves like part of QGIS, not an application inside QGIS).

## 2. Scope

### In scope (v1)

- The 7 terrain tools from `tools.md` (§5), with path and/or area modes.
- 5 ways to select the area: draw line, draw area (polygon), freehand line or shape (lasso), brush painting, and features from a project vector layer (§6).
- Pixel selection modes: *all touched*, *centre inside* (default) and *fully inside* (§6.3).
- Side slopes with a 1:n ratio and maximum reach. Area slopes can go inside or outside the outline (§5.3).
- An editable **cross profile** and **long profile**, with draggable points, in a bottom dock (§7.3).
- A non-destructive **feature list**: every feature stays editable, can be toggled and reordered, and changes can be undone.
- Live preview, a working DEM layer, and a **difference layer** (new − original). (The optional hillshade was removed on 2026-09-15.)
- **Cut/fill volumes** per feature and in total, and **pond storage volume** for depressions.
- **Scenario save/load** to a GeoPackage, **Export** of the final DEM as a GeoTIFF, and a **3D preview**.
- Contextual help: descriptions, usage examples, and theme-aware SVG illustrations.
- English UI, with every string wrapped in `tr()` so it can be translated later.

### Out of scope (v1)

- QGIS 3 support.
- Very large DEMs. Over about 50M pixels the plugin warns but still works in memory; there is no tiling.
- Processing algorithms and batch or command-line use.
- Contour-based reshaping.
- Per-feature values taken from attribute fields.
- Translations.
- Multi-band rasters (band 1 is used, with a notice).
- DEMs in a geographic CRS (they're refused; see §9).
- Any hydraulic simulation.

## 3. Key decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Codebase | Fresh start; nothing is reused from Terrain Studio |
| Workflow | Non-destructive editable feature list; the original DEM is never modified |
| Core approach | In-memory numpy engine, windowed recompute, live canvas overlay while dragging, working GeoTIFF written on release |
| Profiles | Both a cross profile (template swept along the path) and a long profile (design line along the path), with draggable points |
| Freehand | Both a brush and a freehand lasso/line |
| Pixel modes | All touched, centre inside (default), fully inside |
| Area slopes | Chosen per feature: inside the outline (default for lower tools) or outside (default for raise tools) |
| Layout | Right dock (feature list, tool gallery, properties with help) plus a bottom dock (cross and long profile side by side) |
| Look | Native QGIS widgets and theme icons only; no custom stylesheets |
| DEM size | Local sites up to about 50M pixels, whole grid in memory |
| Name | Terrain Scenarios |

## 4. Architecture

### 4.1 Guiding rule

Every selection method is converted into a **geometry**, stored in the DEM CRS:

| Method | Resulting geometry |
|---|---|
| Draw line | LineString |
| Draw area | Polygon |
| Freehand | LineString, or a Polygon if closed (end within 10 screen pixels of the start) |
| Brush | (Multi)Polygon: the strokes buffered by the brush radius and merged, minus erase strokes |
| From layer | Copies of the source geometries (reprojected and repaired) as one multi-part feature |

A `TerrainFeature` can be **multi-part**. Each part is computed independently, with its own reference elevations, and all parts share the same parameters. For example, 23 imported building outlines become one "Buildings (23 parts)" entry.

### 4.2 Package layout

```
terrain_scenarios/
  __init__.py            classFactory
  metadata.txt           qgisMinimumVersion=4.0, qgisMaximumVersion=4.99
  plugin.py              entry point; toolbar action + Raster ▸ Terrain Scenarios menu; creates the docks
  core/                  pure Python: numpy, scipy, osgeo (gdal/ogr). NO qgis imports.
    tools.py             Tool / Mode / PixelMode enums and the TOOL_INFO table
    grid.py              DemGrid (root geotransform + integer block offsets), Window, bilinear sampling
    geometry.py          OGR helpers: WKB in/out, parts, vertices, simplify, flat-cap corridor
    mask.py              geometry → boolean cell mask for the 3 pixel modes
    stations.py          per-cell station s and signed offset o relative to a polyline
    profiles.py          side-profile evaluation beyond an edge: break points + terminal 1:n slope
    operations.py        the 7 tools: apply_feature(feature, grid) → FeatureStats; footprints; rule profiles
    volumes.py           cut/fill, pond storage
    engine.py            FeatureStack: ordered features, dependency closure, windowed replay
  model/
    feature.py           TerrainFeature dataclass + (de)serialisation to dict/JSON
    scenario.py          GeoPackage save/load (uses ogr, no qgis)
  qgis_io/
    raster_io.py         read DEM band into DemGrid; create/update working + difference GeoTIFFs by window
    layers.py            layer group named after the scenario ("Scenario" before a file): Modified DEM, Change, Sketch outlines; refresh; 3D view
    convert.py           QgsGeometry ↔ core geometry, CRS transforms, makeValid
  gui/
    main_dock.py         right dock: DEM picker, scenario actions, feature list, stacked pages
    feature_list.py      list model/view: checkboxes, drag-reorder, warning icons, context menu
    tool_gallery.py      "What do you want to build?" icon grid + "Where?" buttons
    properties_page.py   About-this-tool, Shape, Pixels, Volumes group boxes
    profile_dock.py      bottom dock: splitter with two ProfileWidgets
    profile_widget.py    QPainter plot with draggable handles (cross or long mode)
    overlay.py           QgsMapCanvasItem showing a live cut/fill image while dragging
    map_tools/
      base.py            shared snapping, rubber-band styling from digitizing settings, key handling
      draw_line.py  draw_polygon.py  freehand.py  brush.py  pick_layer.py  vertex_edit.py
    undo.py              QUndoStack commands over the feature list
    help_texts.py        all descriptions, examples and tooltips in one place
    illustrations/       SVG templates with colour tokens, rendered through QSvgRenderer
    icons/               plugin icon + tool icons
tests/
  core/                  pytest, no QGIS needed (only numpy/scipy/gdal)
  qgis/                  integration tests via qgis.testing (headless QGIS 4)
```

**Boundaries.** `core/` knows nothing about QGIS and can be tested on synthetic arrays. `model/` knows features and files but not the GUI. `qgis_io/` is the only place that touches QGIS layers or files, apart from the GUI itself. `gui/` talks to the engine only through a small controller API (§8.1).

## 5. Tool behaviour

### 5.1 Shared concepts

- **Reference terrain.** Elevations a tool reads (start and end point, vertices, boundary) come from the terrain as it stands **at that feature's position in the list**, meaning the original plus all enabled features earlier in the list. Point elevations use bilinear sampling. A reference point on nodata uses the nearest valid cell within 3 cells; otherwise the feature is flagged (§9).
- **Path corridor.** A path feature has a **width** W: the crest for raise tools, the bottom for lower tools, the band for the other tools. The corridor is the line buffered by W/2 with flat end caps and mitre joins (OGR `Geometry.Buffer(W/2, ["ENDCAP_STYLE=FLAT", "JOIN_STYLE=MITRE"])`, verified with the GDAL 3.13 bindings in QGIS 4.2.2). The minimum W is 1 cell size. The default W is `max(3 × cell size, 1 m)`, rounded to a sensible value.
- **Stations.** For each cell in the working window, `stations.py` computes the station *s* (distance along the path of the nearest point) and the signed offset *o* (left negative, right positive). Before this step, freehand lines are simplified with a tolerance of half a cell.
- **Design surface for paths:** `design(cell) = z(s) + cross(o)`, where `z(s)` is the long-profile design line and `cross` is the cross profile.
- **Combine rules** enforce the guarantees in `tools.md`: raise tools use `new = max(old, design)` (never removes material), lower tools use `new = min(old, design)` (never adds material), Interpolate uses `new = design`, and Add and Subtract use `new = old ± H`.
- **Nodata cells** are never modified and never used as reference elevations.
- **Multi-part features:** each part gets its own reference elevations. Parts are applied in order, and each part sees the result of the parts before it.

### 5.2 The seven tools

| # | Tool | Modes | Path: design line z(s) | Area: design | Combine | Slopes |
|---|---|---|---|---|---|---|
| 1 | Interpolate | path, area | linear from z(start) to z(end) | Delaunay-linear surface over the polygon's vertex elevations; cells outside the hull use the nearest vertex | set | no |
| 2 | Raise path | path | linear z(start)→z(end) + H | – | max | yes |
| 3 | Lower path | path | linear z(start)→z(end) − D | – | min | yes |
| 4 | Raise flat | path, area | flat at max(vertex elevations) + H | flat at max(boundary elevations) + H | max | yes |
| 5 | Lower flat | path, area | flat at min(vertex elevations) − D | flat at min(boundary elevations) − D | min | yes |
| 6 | Add to terrain | path, area | – (old + H within the corridor) | old + H inside | add | no |
| 7 | Subtract from terrain | path, area | – (old − D within the corridor) | old − D inside | subtract | no |

"Boundary elevations" means the terrain sampled along the polygon ring at an interval of one cell. "Vertex elevations" means the terrain at the drawn vertices.

### 5.3 Side slopes (tools 2–5)

Parameters: **slope 1:n** (horizontal run per 1 m of height; `n = 0` means no slope) and **max reach** (horizontal cap in metres; default 20 m).

- **Paths:** the slopes are part of the cross profile (§5.4). Beyond the last profile point, the slope continues at the last segment's ratio until it reaches max reach. Because of the combine rule, the slope blends into the terrain wherever it meets the ground. The distance for the slope is measured to the flat-capped corridor itself (a distance transform of the corridor), so a dike's ends slope down as well and there's no gap at the end caps.
- **Areas, slopes outside the outline** (default for Raise flat): the distance `d` outside the footprint comes from `scipy.ndimage.distance_transform_edt`. For raise tools `design = z_flat − d/n`, and for lower tools `design = z_flat + d/n`, up to max reach.
- **Areas, slopes inside the outline** (default for Lower flat, e.g. a pond whose outline is the top edge): `d` is the distance inside the footprint, and `T_edge` is the reference terrain at the nearest outline cell (from the EDT `return_indices`). For lower tools `design = max(z_flat, T_edge − d/n)`, and for raise tools `design = min(z_flat, T_edge + d/n)`. With inside slopes, the flat floor or top is automatically smaller than the outline.

### 5.4 Profiles

**Cross profile** (paths; amended 2026-09-11 to match the built engine): the corridor of width W (the crest for raise tools, the bottom for lower tools) is flat and symmetric around the path. Beyond each corridor edge, each side has an optional list of break points `(distance beyond the edge, dz)`, e.g. a berm, followed by the terminal side slope 1:n up to the max reach. The left and right break lists can differ (`cross_left`, `cross_right`).

- The default has no break points: a flat crest or bottom of width W, then the 1:n slope.
- In the editor:
  - Dragging a crest-edge handle changes W (symmetrically).
  - You can drag break points beyond the edge or double-click to add one; right-click deletes one.
  - A **Symmetric** checkbox (on by default) mirrors break-point edits to the other side.
  - A handle at the end of the terminal slope changes n.
- Width and slope stay editable as numbers at all times. Break points are stored relative to the crest edge, so a wider W carries them outward. **Reset shape** removes all break points.
- An asymmetric or crowned crest is not supported in v1.
- For area features, the cross profile editor shows the edge slope (distance from the outline against dz) and edits n and max reach. Break points are not supported for areas in v1.

**LongProfile** (paths): a list of `(station, absolute z)` points.

- The default comes from the tool rule: the start and end points, and the flat line for the flat tools.
- The editor shows the reference terrain along the centre line (dashed), the design line, and handles. You can drag handles vertically (and intermediate handles horizontally) and double-click to add a point.
- Once overridden, H/D shows "custom", and **Reset to rule** restores the default.
- **Rule profiles vs custom profiles.** While the long profile is *not* overridden, it is regenerated from the tool rule on every replay, so it follows changes in the reference terrain (e.g. an earlier feature raising the start point). Overridden points store **absolute** elevations and stay fixed when the terrain underneath changes. The panel shows a small "custom (fixed elevations)" note so users know.
- The combine rule still applies, so a raise path can never cut terrain, even with a dragged profile.
- For area features, the long-profile panel becomes a **read-only inspection section** showing before and after along a line. By default the line runs through the centroid along the longer side of the oriented minimum bounding box. The user can redraw it with a "Draw section line" button.
- For multi-part path features, custom long profiles are disabled. The panel shows the part nearest the last click.

### 5.5 Volumes

- *Note (2026-11-23): volume figures (cut, fill, pond storage, totals) were removed from the plugin at the owner's request, so nothing below is implemented and the feature summary shows only the tool label.*

- The cell area is `|pixel_width × pixel_height|`.
- **Per feature:** `fill = Σ max(0, after − before) × area` and `cut = Σ max(0, before − after) × area`, where *before* and *after* are the states just before and just after that feature during replay.
- **Scenario total:** computed from `working − original`.
- **Pond storage** (for tools 3, 5 and 7, and for Interpolate in area mode whenever it lowers terrain): the spill level is the minimum of the new terrain over the ring of cells (8-connected) bordering the **lowered** region, and `storage = Σ max(0, spill − new) × area` over the lowered region. It's shown as "≈ storage below the lowest rim point (static, no inflow routing)".

## 6. Selecting the area

### 6.1 Map tools

All map tools share `map_tools/base.py`:

- **QGIS snapping** (`QgsSnappingUtils` from the canvas) with the snap indicator.
- **Rubber bands** styled from the user's digitizing settings.
- **Keys:** Backspace or Delete removes the last vertex, Esc cancels, Enter or right-click finishes.
- A status-bar hint describes the current action.

| Tool | Interaction |
|---|---|
| Draw line | Click vertices, right-click to finish (at least 2 vertices) |
| Draw area | Click corners, right-click to close (at least 3 vertices) |
| Freehand | Press and drag to trace; release to finish. Ending near the start closes it as a polygon when the tool supports areas |
| Brush | A circle cursor shows the radius. Press and drag to paint; hold Shift to erase. Change the radius with Ctrl+wheel or `[` `]` (it's also in the panel). Enter or right-click finishes. With a brush feature selected, the brush adds to or erases from that feature |
| From layer | Panel form: a vector layer picker (line or polygon, depending on the tool), "Selected features only", and **Use these features** |
| Vertex edit | Active while a non-brush feature is selected: drag vertices, double-click a segment to add a vertex, hover a vertex and press Delete to remove it |

Only methods that fit the tool's modes are enabled. Raise path and Lower path accept lines only. Tools with both modes show a **Line / Area** toggle above the "Where?" buttons.

### 6.2 Geometry handling

- Geometries are transformed to the DEM CRS on creation (`qgis_io/convert.py`) and repaired with `makeValid`.
- Brush strokes are merged with a simplification tolerance of half a cell.

### 6.3 Pixel modes (`core/mask.py`, using GDAL in-memory rasterisation)

These apply to the polygon, or to the corridor polygon for paths. Side slopes are outside this mask and are always computed per cell.

| Mode | Rule |
|---|---|
| All touched | `RasterizeLayer(..., ALL_TOUCHED=TRUE)` of the polygon |
| Centre inside (default) | Standard rasterisation (the cell centre is inside) |
| Fully inside | `all_touched(polygon) AND NOT all_touched(boundary rings)` |

## 7. User interface

### 7.1 Native-look rules (mandatory)

- Only standard Qt/QGIS widgets: `QgsMapLayerComboBox`, `QgsDoubleSpinBox` (with a unit suffix and clear value), `QgsCollapsibleGroupBox`, `QgsMessageBar` / `iface.messageBar()`, `QToolButton`, `QListView`/`QTreeView`, `QStackedWidget`, `QSplitter`.
- QGIS theme icons (`QgsApplication.getThemeIcon`) for standard actions: add line, add polygon, freehand, select, delete, save, open, 3D, zoom-to. Custom icons only for the 7 tools and the brush, drawn in the flat QGIS icon style.
- No custom stylesheets or brand colours. The UI inherits the active QGIS theme (light or dark).
- **Illustrations** are SVG templates with colour tokens (`{terrain}`, `{line}`, `{fill}`, `{cut}`, `{text}`). The tokens are replaced from the `QPalette` (plus fixed orange for fill and blue for cut) before rendering.
- The profile dock follows the look of QGIS's Elevation Profile: palette background, light grid, axis labels in metres.
- The collapsed or expanded state of group boxes and the dock and splitter geometry are persisted with `QgsSettings` under `terrain_scenarios/`.

### 7.2 Right dock "Terrain Scenarios"

> **Superseded 2026-09-15** by `2026-09-15-terrain-scenarios-panel-redesign.md`: the panel was
> restructured into drill-in pages (welcome view, feature list, New feature page, feature page).
> The rules below still describe what the panel contains; that document describes how it is laid
> out and navigated.

1. **Header row:**
   - The DEM picker (`QgsMapLayerComboBox`, raster only).
   - Scenario actions (icon buttons with tooltips): New, Open…, Save, Save as…, Export DEM…, 3D view.
   - A **Profiles** toggle button that shows and hides the bottom dock, which is hidden until it is used (added 2026-09-15).
2. **Feature list** (`feature_list.py`):
   - Each row has a checkbox (enabled), a tool icon, a name, and a warning icon when flagged.
   - Drag to reorder.
   - Context menu: Rename, Duplicate, Zoom to, Delete.
   - Selecting a row selects the feature on the map and loads its profiles.
   - **New feature**, **Delete** and **Edit shape** buttons sit above the list (moved there 2026-09-15). A handle below the list changes its height; the split is remembered.
3. **Stacked page area:**
   - **Gallery page:**
     - "What do you want to build?" is an icon grid of the 7 tools. Each item shows a side-view illustration and the tool name; its tooltip gives the one-line description and a usage example.
     - Below the grid is the **Line / Area** toggle (when applicable), then "Where?", five `QToolButton`s with text under the icon: Draw line, Draw area, Freehand, Brush, From layer.
     - Picking a tool and then a "Where?" method starts the map tool. Finishing the drawing creates the feature with default parameters, adds it to the list, selects it, and shows its Properties page.
   - **Properties page** (for the selected feature):
     - *About this tool*: a collapsible group with the description, usage examples, and the tool's illustration.
     - *Shape*: only the parameters relevant to the tool and mode. The diagram next to them highlights the part controlled by the field that has focus.
       - H or D: "Height above the path", "Depth below the path", "Height above the highest point", and so on; the label depends on the tool.
       - Width.
       - Slope 1:n.
       - Max reach.
       - Slope position (Inside/Outside, area only).
       - Brush radius (brush only).
     - *Pixels to change*: a combobox with an illustrated icon per mode, plus a tooltip containing the three-panel picture.
     - *Volumes*: a collapsible group, collapsed until opened, with fill, cut and (when applicable) storage for this feature, plus the scenario totals.
     - *Note (2026-11-23): the header and feature-list summary no longer show cut/fill volumes, only the tool label.*
     - *Note (2026-11-22): the *About this tool* and *Volumes* groups were removed from the page at the user's request.*
4. Every parameter has a tooltip with its meaning and an example, and the field labels use plain language. All texts live in `help_texts.py`.

### 7.3 Bottom dock "Terrain Scenarios — Profiles"

- A `QSplitter` holds two `ProfileWidget`s: **Cross profile** on the left and **Long profile** on the right.
- `ProfileWidget` is a `QWidget` with a custom `paintEvent`. It shows an axis grid, the reference terrain (dashed), the design line, fill and cut shading, and handles.
- Mouse interaction: hover highlights a handle and shows its value in a tooltip; drag moves it; double-click adds a point; right-click deletes one.
- Keyboard: arrow keys nudge the selected handle (0.1 m, or 0.01 m with Shift).
- Dragging emits `profileChanged` (throttled), and releasing emits `profileCommitted`.
- Vertical exaggeration is automatic, and both axes are labelled in metres.
- With no feature selected, both panels show a short hint: "Select or draw a feature to edit its shape here."

### 7.4 Undo

- A `QUndoStack` covers feature-list operations: add, delete, reorder, toggle, rename, parameter change, profile change, geometry edit.
- Ctrl+Z and Ctrl+Shift+Z work while the dock or a Terrain Scenarios map tool has focus, so they don't clash with QGIS's own layer-editing undo. There are also Undo and Redo buttons in the dock header.

## 8. Data flow

### 8.1 Controller API (between the GUI and the engine)

`SketchController` lives in `gui/` and uses `core` and `qgis_io`:

- `set_dem(layer)`, `new_scenario()`, `open_scenario(path)`, `save_scenario(path)`, `export_dem(path)`
- `add_feature(feature)`, `update_feature(id, **changes)`, `delete_feature(id)`, `reorder(ids)`, `set_enabled(id, bool)`
- `preview(id, **changes)` computes only the overlay and doesn't commit.
- Signals: `featuresChanged`, `featureComputed(id, stats)`, `rasterUpdated(window)`, `warning(id, message)`

### 8.2 Loading a DEM

1. Validate the layer: it must be a raster; if it has more than one band, band 1 is used with a notice. A geographic CRS is refused (§9).
2. Read band 1 into a float32 `original` plus a nodata mask. Keep an immutable `original` and a mutable `working` copy.
3. Create the working GeoTIFF (float32, same grid, CRS and nodata, LZW) and the difference GeoTIFF (float32, 0 = no change). They go in a session temp folder, or in `<scenario>_files/` once the scenario is saved.
4. Add the layer group **Terrain Scenarios**:
   - **Modified DEM**, with the renderer copied from the source layer.
   - **Change (new − original)**, with a diverging ramp: blue for cut, orange for fill, transparent at 0.
   - **Sketch outlines**, a memory vector layer showing feature outlines and labels (read-only mirror).

### 8.3 Recompute on change

1. `affected = bbox(old footprint) ∪ bbox(new footprint)`. A footprint includes the slope reach plus a 1-cell margin.
2. **Dependency closure.** Add the full extent of every enabled feature whose footprint intersects `affected`, and repeat until nothing more is added. This guarantees that the reference elevations of every overlapping feature are recomputed correctly.
3. Restore `working[affected] = original[affected]`, then replay every enabled feature intersecting `affected` in list order, restricted to `affected`. Record the per-feature stats.
4. **While dragging** (`preview`): run steps 1–3 on a scratch copy of the window, throttled to at most one run per 60 ms with the latest request winning. Update only the `overlay.py` canvas item, which draws the change image (cut/fill colours) georeferenced over the window.
5. **On commit:** apply the result to `working`, then write that window into the working and difference GeoTIFFs (`WriteArray` with an offset). Call `dataProvider().reloadData()` and `triggerRepaint()` on the affected layers, remove the overlay, and update the volumes.

**Performance targets** (an M-class Mac at 0.4 m resolution): recompute of a 500×500 window in under 50 ms, and a drag preview of at least 15 fps for windows up to 1000×1000.

### 8.4 Scenario file (GeoPackage)

- The layer `features` has a generic `GEOMETRY` type in the DEM CRS. Its fields: `order` (int), `name`, `tool`, `mode` (`path`/`area`), `enabled`, `pixel_mode`, `params` (JSON), `cross_profile` (JSON), `long_profile` (JSON or null), `section_line` (WKT or null).
- The table `terrain_scenarios_meta` holds key and value pairs: `plugin_version`, `dem_source`, `dem_crs`, `dem_extent`, `dem_size`, `dem_pixel_size`, `created`, `modified`.
- **Loading** compares the metadata with the chosen DEM. If they differ, it warns and offers to load anyway or to pick another DEM. It then recomputes everything.
- On closing a project, unloading the plugin or switching scenario, a scenario with unsaved changes triggers a save prompt.

### 8.5 Export and 3D

- **Export DEM…** writes a float32 GeoTIFF on the original grid, CRS and nodata, with LZW compression and a predictor. An option adds the result to the project. Integer source DEMs are exported as float32 and the dialog says so.
- **3D view** sets the project's elevation terrain to the working DEM (`QgsProject.elevationProperties().setTerrainProvider(QgsRasterDemTerrainProvider)`, vertical scale 1). It then opens a new 3D map view: through `iface.createNewMapCanvas3D()` when that's available, otherwise by triggering QGIS's own *View ▸ 3D Map Views ▸ New 3D Map View* action. The previous terrain provider is remembered and restored when the scenario closes. If the 3D view can't be opened, a message bar note explains how to open it manually.
  - *Note (2026-11-23): detail and live update, after a user report — a ~50 m wall was written to the Modified DEM but did not appear in the 3D view, edits after that never showed in an open view, and every new view started coarse again. QGIS seeds a view's DEM terrain at 16 samples per tile edge, which steps over a feature a few cells wide, and never rebuilds a view when the raster under it is rewritten. Now every 3D view whose terrain is a DEM terrain on the session's Modified DEM — the one the 3D button opens and any the user opens through QGIS (noticed through the main window's new docks and the project's views manager, not by polling) — gets a resolution of the DEM's larger side in cells, capped at 512 (vertices per tile = resolution²; QGIS's own UI allows up to 4096), and never lowered below what the user set. After each write of the working raster (edits, undo/redo, opening a scenario, the files moving on save) such views rebuild from the file once a burst of writes has paused for 300 ms; because setting equal terrain settings is a no-op, the rebuild sets a 1 m taller skirt and then the real settings back. Views on any other terrain are never touched; without QGIS's 3D module nothing happens. Code: `gui/view_3d.py`.*

## 9. Error handling

| Situation | Behaviour |
|---|---|
| No DEM selected | The gallery and "Where?" buttons are disabled and a hint says "Pick a DEM layer first" |
| Geographic CRS | The DEM is refused, with a message bar and a **Reproject…** button that opens Processing `gdal:warpreproject` |
| More than 50M pixels | Warning with the estimated memory use; the user can continue |
| Feature entirely outside the DEM | Kept and flagged with a warning icon and tooltip, plus a message bar note |
| No cells selected (e.g. "fully inside" on a narrow corridor) | Flagged: "No pixels selected — try 'All touched' or a larger width" |
| Reference point on nodata | Nearest valid cell within 3 cells is used; otherwise the feature is flagged |
| Invalid or foreign-CRS input geometry | Reprojected and repaired; if repair fails, rejected with a message |
| Working file not writable | Falls back to the session temp folder, with a message |
| Unexpected exception | Caught at the controller boundary, shown in the message bar and logged to `QgsMessageLog` tab "Terrain Scenarios" with a traceback; QGIS never crashes and the feature is flagged |
| Source DEM layer removed from project | Editing is disabled and the user is asked to pick a DEM again |

## 10. Testing

- **Test runner:** QGIS 4.2.2 bundles Python 3.12.11, numpy 2.5, scipy 1.18, GDAL 3.13 and shapely 2.1, but **not pytest**. A dev-only virtual environment built on QGIS's interpreter (`--system-site-packages`, plus `pip install pytest`) runs both test suites. A `scripts/test.sh` wrapper sets `PYTHONHOME`, `PYTHONPATH` and `PROJ_DATA` for the app bundle. pytest is never a runtime dependency of the plugin.
- **`tests/core` (pytest, no QGIS app needed):**
  - Each tool on synthetic DEMs (plane, tilted plane, bump, pit): Add is exactly +H; Interpolate on a path is linear; the flat tools produce a level result.
  - The invariants: raise never lowers any cell, lower never raises any cell, and nodata cells are unchanged.
  - Slopes: the measured gradient equals 1/n, the reach cap is respected, and inside and outside slope placement both behave as specified.
  - Pixel modes: counts on known polygons match hand-computed masks, with fully inside ⊆ centre inside ⊆ all touched.
  - Profiles: the default templates match the parameters; custom points are applied; a raise with a dragged-down long profile still never cuts.
  - Volumes against analytic cases, e.g. a box pond and a prism dike.
  - **Windowed replay equals full replay:** a randomised property test over stacks of 1–8 features, including reordering, toggling and editing.
- **`tests/qgis` (qgis.testing, headless QGIS 4.2.2):**
  - Raster I/O round trip.
  - Layer group creation and refresh.
  - Scenario save and load round trip.
  - `convert.py` CRS handling.
  - Map tools fed synthetic `QgsMapMouseEvent`s produce the expected geometries.
  - `ProfileWidget` dragging via QTest emits the right points.
  - Controller end-to-end: load a DEM, add a feature, export, and compare.
- **Manual QA checklist** (in the plan): every tool × every selection method in QGIS 4.2.2, with both light and dark themes.

## 11. Milestones (for the implementation plan)

1. **Core engine:** grid, geometry, mask, stations, profiles, slopes, operations, volumes, engine, plus the full `tests/core`.
2. **Plugin shell and first flow:** the plugin, the docks, DEM loading, the working and difference layers, draw line and draw area, the feature list, recompute and write, and export.
3. **All selection methods:** freehand, brush, from layer, vertex editing, pixel modes in the UI, and the Line/Area toggle.
4. **Profile dock:** `ProfileWidget` in cross and long modes, dragging with live overlay preview, and reset buttons.
5. **Guidance:** the tool gallery with illustrations, the About-this-tool texts, tooltips, the parameter diagrams, and the pixel-mode pictures.
6. **Scenario and extras:** GeoPackage save and load, volumes in the UI, 3D view, undo/redo, error flags, and a packaging script that builds the plugin ZIP.
