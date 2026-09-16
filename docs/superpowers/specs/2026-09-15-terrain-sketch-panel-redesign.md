# Terrain Sketch — main panel redesign (design)

**Date:** 2026-09-15
**Amends:** `2026-09-11-terrain-sketch-design.md` §7.1 and §7.2. Everything that document says about the
engine, tools, map tools, scenarios, undo, profiles and error handling still holds unchanged.

## 1. Purpose

The main panel works but looks dated: every control is on screen at once, the feature rows carry a name and
nothing else, and "New feature" stacks a long form under the list. This redesign keeps the panel native to
QGIS while making it read as one clear flow: **pick a DEM → list of features → drill into one thing at a
time**.

Non-goals: no change to what the tools compute, to the map tools, to the scenario file, to the Profiles
panel, or to any help text's wording (texts move, they do not change).

## 2. Decisions taken with the user (2026-09-15)

1. **Native widgets plus light palette-derived touches.** No stylesheets and no brand colours. The touches
   allowed are: secondary text in a muted colour derived from the palette, a tool-tile grid that uses the
   theme's own selection highlight, and a segmented Line/Area pair of checkable buttons.
2. **Drill-in navigation** with `QgsPanelWidgetStack`, the same behaviour as QGIS's Layer Styling panel.
3. **New feature is one page**: tool tiles, then shape and how to draw, all on that page.
4. **The DEM picker and Start move off the working view**: a welcome page before a session, and a quiet
   status line during one.

## 3. Structure

```
QgsDockWidget "Terrain Sketch"
└── QgsPanelWidgetStack
    └── main panel (QgsPanelWidget)
        └── QStackedWidget
            ├── welcome view   (no session)
            └── session view   (toolbar · feature list · status line)
    pushed on demand:
    ├── New feature page   (QgsPanelWidget, title "New feature")
    └── Feature page       (QgsPanelWidget, title = the feature's name)
```

**Mandatory:** every `QgsPanelWidget` calls `setDockMode(True)` before it is opened. In QGIS 4.2.2
`QgsPanelWidgetStack.setMainPanel()` does *not* set dock mode, and `openPanel()` on a panel that is not in
dock mode opens a **modal dialog** — which hangs an offscreen test suite forever. A test asserts dock mode
for every page this panel can open.

## 4. Welcome view (no session)

Centred in the panel, with stretch above and below:

- The `raise_path` illustration at 160×80, drawn from the palette like every other illustration.
- A bold heading: "Sketch changes on your terrain".
- The existing start text, word-wrapped: "Pick a DEM above and press Start. Terrain Sketch works on a copy;
  your DEM is never changed." — reworded only to match its new position: "Terrain Sketch works on a copy;
  your DEM is never changed." (constant `START_INTRO`).
- Row: label "DEM" + `QgsMapLayerComboBox` (raster only) + `Start` button, unchanged in behaviour,
  including the excepted-layer handling and the DEM error paths.

The welcome view is also how a user changes DEM mid-session (§6).

## 5. Session view

### 5.1 Toolbar

One `QToolBar`, icon size `iface.iconSize(True)`, in this order:

| Control | Kind | Notes |
|---|---|---|
| **New feature** | `QToolButton`, icon + text beside it (`/mActionAdd.svg`) | The one primary action; opens the New feature page. |
| Undo, Redo | icon buttons on the existing undo/redo actions | unchanged |
| separator | | |
| **Scenario ▾** | `QToolButton`, `InstantPopup`, icon `/mActionFileOpen.svg`, text beside icon | Menu with four `QAction`s: New scenario, Open scenario…, Save scenario, Save scenario as… — same icons, tooltips and slots as today's four buttons. |
| separator | | |
| Export DEM…, 3D view, Profiles (checkable) | icon buttons | unchanged, including the Profiles button's two-way binding with the dock |

Overflow behaviour stays QToolBar's own (»). The whole toolbar is disabled without a session except that the
session view is not shown then at all.

### 5.2 Feature list

Same model, same drag-to-reorder, same context menu, same checkbox, same inline rename. Rows are drawn by a
`QStyledItemDelegate`:

```
┌──────────────────────────────────────────┐
│ ☑  [illus]  Dike north              ⚠  › │
│             Raise path · fill 191 m³     │
└──────────────────────────────────────────┘
```

- **Illustration:** the tool's own picture, 40×20, from `illustrations.icon(f"tool_{tool.value}", …)`.
- **Title:** the feature name in the normal text colour.
- **Subtitle:** `"{tool label} · {volume}"`, where volume is `fill NNN m³` when fill dominates, `cut NNN m³`
  when cut dominates, and `fill NNN m³ · cut NNN m³` when both are non-zero; nothing at all when both are
  zero. Drawn in the muted colour (§8). Values come from `controller.stats(fid)`, a cached lookup.
- **Warning icon** when the feature has flags, as today, with the same tooltip.
- **Chevron** at the right edge, muted, to show the row opens a page. It is drawn with the style's own
  `PE_IndicatorArrowRight` primitive, not a theme icon: `getThemeIcon` returns a null icon in silence for a
  name the theme does not have.
- Row height: two text lines plus padding, at least the illustration's height.
- The checkbox stays a real check state on the model, so clicking it toggles the feature and does **not**
  open the page.

**Opening:** a single click anywhere on a row except the checkbox selects the feature *and* opens its page.
Selection alone (e.g. restored after a model reset, or set by `select_id`) does not open a page — otherwise
undo or a rename would yank the user into a page they did not ask for.

### 5.3 Status line

At the bottom of the session view, muted, word-wrapped: `Sketching on: <DEM layer name>` followed by a
`Change…` link (`QLabel` with a link, `linkActivated`). Activating it goes back to the welcome view with the
unsaved-work question first (the existing `_keep_unsaved_work` path). The session itself keeps running until
a new DEM is started, exactly as pressing Start does today.

## 6. New feature page

Title "New feature", pushed on the stack. Contents, top to bottom:

1. **Tool tiles:** a `QListView` in `IconMode`, `setUniformItemSizes(True)`, `setResizeMode(Adjust)`,
   `setMovement(Static)`, `setWordWrap(True)`, icon size 96×48, grid 116×92, so two or three tiles fit per
   row at normal dock widths and the grid reflows when the dock is resized. One item per tool, with the
   tool's illustration, its label, and today's `tool_tooltip(tool)`.
2. **Summary** of the selected tool (`TOOL_SUMMARIES`), word-wrapped. Before a tool is picked: "Pick a tool,
   then choose where to draw it."
3. **Shape:** label "Shape" and two checkable `QToolButton`s, "Line" and "Area", in an exclusive
   `QButtonGroup`, sitting side by side as a segmented pair. Disabled per tool exactly as the radio buttons
   are today.
4. **Draw it:** the four method buttons (Draw, Freehand, Brush, From layer), text under icon, in a grid that
   wraps, enabled by mode as today. Brush radius (`QgsDoubleSpinBox`, map units suffix) appears only while
   the Brush button is enabled, instead of being permanently visible and greyed.
5. **From layer** expands the existing `LayerSource` widget inline under the buttons.
6. The drawing **hint** (`METHOD_HINTS`, `BRUSH_EXTEND_HINT`) shows on this page while a drawing started
   from it is running, so the user reads it where they started. Hints for work started from a feature —
   `EDIT_HINT` (Edit shape) and `SECTION_LINE_HINT` (Draw section line, from the Profiles panel) — show on
   the feature page instead (§7). `MainDock` routes a hint to whichever page is open.

Picking a tool and a method starts the map tool, as today. When the drawing finishes and the controller adds
the feature, the New feature page closes and the new feature's page opens in its place. Pressing back (or Escape on the page) stops a drawing that is still running and returns to the list. Esc-cancelling a drawing on the map keeps the New feature page open, so the user can try again with another method.

## 7. Feature page

Title = the feature's name; it follows a rename.

1. **Header:** the tool illustration (72×36) beside a `QLineEdit` holding the feature's name (committing
   renames through the controller, so it is undoable), with the tool label and the volume line under it in
   muted text: `Raise path · fill 191 m³ · cut 0 m³`.
2. **Action row:** icon buttons — Edit shape (checkable, existing behaviour), Zoom to feature (the existing
   context-menu action), Delete. Delete closes the page and returns to the list.
3. **Problems:** the flags label, shown only when the feature has flags, directly under the actions so a
   warning is not buried.
4. **Diagram** (path features with slopes) and the **fields**, in the existing `QFormLayout` with the same
   labels, tooltips, ranges and focus-highlight behaviour: Height/Depth, Width, Side slope, Max. slope reach,
   Slopes.
5. **Advanced** (`QgsCollapsibleGroupBox`, collapsed by default, remembered): "Pixels to change", the one
   field that is about how the change is rasterised rather than about the shape.
6. **Volumes** (`QgsCollapsibleGroupBox`, collapsed by default, remembered): fill, cut, storage and the
   scenario totals, unchanged.
7. **About this tool** (`QgsCollapsibleGroupBox`, collapsed by default now that the summary is in the
   header, remembered): picture, description and example, unchanged.

The page scrolls (`QgsScrollArea`) so a narrow, short dock never clips the fields.

## 8. Muted text

`gui/muted.py` provides `MutedLabel`, a `QLabel` whose text colour is the palette's text colour blended 45%
toward the window colour, recomputed on `PaletteChange` so it follows a QGIS theme switch. The delegate uses
the same helper function for its subtitle and chevron. No colour is hard-coded; light and dark both follow
the theme.

## 9. Navigation rules

| Event | Result |
|---|---|
| Session starts | stack returns to the main panel, session view shown |
| Session ends (`has_dem` false) | any open page closes; welcome view shown; tools stopped |
| Feature on the open page is deleted, or disappears through undo | that page closes, list shown |
| A drawing finishes | New feature page closes; the new feature's page opens |
| Panel hidden (plugin toggled off) | tools stop, as today; the open page stays for when it returns |
| Back from any page | the list, with the feature still selected and still highlighted on the map |

Selecting a feature — by opening its page or through `select_id` — keeps driving the map highlight and the
Profiles dock exactly as it does today.

## 10. Persistence

- The `list_splitter` setting is gone; there is no splitter any more. Nothing reads it, and a stale value in
  an existing profile is simply ignored.
- The collapsed state of Advanced, Volumes and About this tool is remembered under `terrain_sketch/` as
  today, each starting collapsed.
- Dock area, size and the Profiles dock's state are unchanged.

## 11. Testing

Every rule above is covered in `tests/qgis`, headless like the rest of the suite:

- Dock mode is set on every page that can be opened (guards the modal-dialog hang).
- Opening a feature page, going back, and the four rows of the navigation table in §9.
- A click on the checkbox toggles the feature and does not open a page; a click on the row opens it.
- The delegate's subtitle text for fill-only, cut-only, both and neither.
- The toolbar: the scenario menu holds the four actions and each triggers the same slot as before; the
  Profiles button still tracks the dock.
- The welcome view: Start behaves as today, including the DEM error paths and the excepted layers, and
  `Change…` returns to it with the unsaved-work question.
- New feature page: picking a tool enables the right shapes, brush radius appears only with Brush, drawing a
  feature lands on its page.
- Feature page: rename through the header field is undoable; Delete returns to the list; fields keep the
  existing behaviour (values, tooltips, focus highlight, the "still typing" rule).
- Existing tests that reach for `dock.new_button`, `dock.pages`, the splitter or the old scenario buttons are
  updated to the new structure rather than deleted; the behaviour they assert must still be asserted.

## 12. Compatibility

`MainDock` keeps the attribute names other code already uses where they still make sense: `dem_combo`,
`start_button`, `feature_view`, `model`, `gallery`, `properties`, `profiles_button`, `undo_action`,
`redo_action`, `new_button`, `delete_button`, `edit_button`, `export_button`, `view_3d_button`. `plugin.py`'s
use of `stop_tools()`, `shutdown()` and `profiles_button` is unchanged.
