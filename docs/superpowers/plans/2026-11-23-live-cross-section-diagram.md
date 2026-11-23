# Live Cross-Section Diagram Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The feature page's diagram draws the feature's own cross-section, from its values, in a
collapsible "Cross-section" box.

**Architecture:**
- A pure function in `core/sections.py` turns a feature into its section on flat ground.
- `gui/illustrations` builds an SVG from that section, with the same colour tokens and
  `{opacity-key}` highlight tags as the other illustrations, and renders it.
- `PropertiesPage` puts the picture in a `QgsCollapsibleGroupBox` and redraws it on every
  feature change.
- The static `parameters.svg` goes away.

**Tech Stack:** Python 3.12, PyQt6 via qgis.PyQt, QSvgRenderer, pytest via `scripts/test.sh`.

**Spec:** docs/superpowers/specs/2026-11-23-live-cross-section-diagram-design.md

## Global Constraints

- Colours come only from the tokens `{terrain}`, `{line}`, `{text}`, `{fill}` (raise tools) and
  `{cut}` (lower tools).
- The SVG uses only paths, lines and text: no filters.
- Every Qt slot and override is guarded with try/except and logs under LOG_TAG.
- Label text: width "3.0 m" (1 decimal), height or depth "1.20 m" (2 decimals), slope "1:2"
  (`:g`), reach "8 m" (`:g`), and the note "Height ×5".

## Review Focus

- **Slope 1:0, so no terminal slope:** the side drops straight down at the edge, or at the last
  break; there is no slope label and nothing crashes.
- **Height 0:** a flat line on the ground, with no "Height ×" note and no division by zero.
- **Reach shorter than the run of the slope:** a vertical step down to the ground, and the reach
  label appears.
- **A break point below the ground on a raise tool:** the side ends where it first meets the
  ground.
- **Lower tools:** the section sits below the ground line and uses the cut colour.

---

### Task 1: `flat_ground_section(feature)` in `core/sections.py`

**Interfaces:**
- **Produces:** `flat_ground_section(feature) -> FlatSection`, a frozen dataclass with these
  fields:
  - `left`, `right`: tuples of (offset ≥ 0 from the centre line, z relative to the ground).
    Each starts at (0, crest z), and z is +amount for raise tools and −amount for lower tools. Each
    side ends on the ground (z = 0), with a vertical step appended if the side stopped above or
    below it.
  - `direction`: from TOOL_INFO.
  - `cut_short`: True when either side needed that step because of reach.
- **Algorithm:** take `cross_section(feature, side)`, which gives dz relative to the crest. Map
  each point to z = crest + dz, and stop at the first point where the side meets or crosses the
  ground, at the interpolated crossing. If the last point is not on the ground, append
  (offset, 0).
  - `cut_short` = a step was appended, slope_n > 0, and amount > 0.

**Tests** (in `tests/core/test_sections.py`):
- **A plain dike:** width 4, amount 1, slope 2, reach 10 gives a right side of
  `((0,1),(2,1),(4,0))`, with `cut_short` False.
- **A ditch:** Lower path with the same values gives z values −1, −1, 0.
- **Reach 1 with slope 2 and amount 1:** the right side is `((0,1),(2,1),(3,0.5),(3,0))` and
  `cut_short` is True.
- **slope_n 0:** the right side is `((0,1),(2,1),(2,0))`.
- **Amount 0:** every z is 0.

### Task 2: the section SVG in `gui/illustrations`

**Interfaces:**
- **Produces:**
  - `section_svg(feature, palette, highlight=None) -> str`: tokens filled; the same highlight
    rules as `svg_source`, with the part keys `width`, `amount`, `slope` and `reach`.
  - `section_pixmap(feature, size, palette, highlight=None) -> QPixmap`.
- **Refactor:** factor the token and highlight substitution out of `svg_source` into a helper that
  both use.
- **Drawing:**
  - Horizontal fit: the left plus right extent fills the width minus the margins.
  - Vertical scale: the same as horizontal, but if the shape's height on screen falls below the
    minimum, exaggerate by k = ceil(min / true height) and add the "Height ×k" note. If it is
    taller than the box, scale everything down uniformly.
  - Delete `parameters.svg` and its two template tests. Highlight and unknown-highlight tests move
    to `section_svg`.

**Tests** (in `tests/qgis/test_illustrations.py`):
- The SVG for a dike with width 3 contains "3.0 m", "1:2" and the height label, and has no "{".
- The fill colour is used for Raise path and the cut colour for Lower path.
- Doubling the amount changes the pixmap.
- A flat feature (amount 0.3, width 20) has a "Height ×" note; a tall one (amount 2, width 2) does
  not.
- The reach label is present only when `cut_short`.

### Task 3: the collapsible box on `PropertiesPage`

**Changes:**
- `self.diagram_box = QgsCollapsibleGroupBox("Cross-section")` holds `self.diagram`. It is
  remembered with `settings.remember_collapsed("cross_section_group", box, collapsed=False)`.
- The box takes the diagram's place in the layout.
- Visibility moves from the diagram to the box.
- `_draw_diagram` uses `section_pixmap` with the shown feature and the current highlight, kept in
  `self._highlight`.
- `_refresh_values` redraws it.

**Tests** (in `tests/qgis/test_guidance.py`):
- Update the hidden/visible test to use the box.
- Changing the amount through the controller changes `page.diagram.pixmap()`.
- The box is a `QgsCollapsibleGroupBox` titled "Cross-section".
- Remove the dated "parameters" references in the spec (§7), with a dated note.
