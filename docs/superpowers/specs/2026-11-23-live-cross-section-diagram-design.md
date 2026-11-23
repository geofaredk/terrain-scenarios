# Live cross-section diagram on the feature page — design

Approved approach: B (height exaggerated when the shape would be too flat), Niklas, 2026-11-23.

## Intent

The diagram on the feature page (Raise path, Lower path, and Raise flat / Lower flat drawn as a
path) is a fixed picture of a dike today: typing a value only highlights a label. Niklas wants
the drawing itself to follow the values, so the shape on the page is the shape he is defining.

## What it shows

- The cross-section of the feature on flat ground, built from its real values. It uses the same
  geometry the profile dock draws, `core.sections.cross_section`, for both sides:
  - top (or bottom) width;
  - the height or depth;
  - side slopes at 1:n;
  - slopes cut off at Max. reach, where a slope that has not met the ground ends in a vertical
    step, as the engine does on flat ground;
  - the left and right break points, which may differ from side to side.
- Raise tools rise above the ground line; lower tools (a ditch) sink below it. This also fixes
  the current picture, which shows a dike for a ditch.
- The labels carry the values instead of the words: "3.0 m" for the width, "1.20 m" for the
  height or depth, "1:2" for the slope, and "8 m" for the reach. The reach label appears only when
  the reach actually cuts a slope short.
- Highlighting stays: the part belonging to the focused field is emphasised and the rest is
  dimmed, as today.
- The diagram redraws on every value change: typing in a field, profile-dock drags, undo/redo,
  and theme changes.

## Proportions (approach B)

- Horizontal: the whole section, crest plus both sides out to where they meet the ground or stop,
  fills the diagram's width.
- Vertical: at true scale when that leaves the shape readably tall. When true scale would make it
  flatter than a minimum height, the height is exaggerated to that minimum and a small muted note
  says so, for example "Height ×5". The factor is rounded to a whole number. Very tall shapes are
  scaled down to fit the box, never squeezed sideways.
- A height of 0 draws a flat line on the ground, with no exaggeration note.

## Approaches considered

- **A, true to scale:** slope angles are always honest, but low features become slivers.
- **B, exaggerated when flat (chosen):** always readable, and the note tells the user the angles
  are steeper than real.
- A fixed picture with only the numbers changing was ruled out: the shape would still not follow
  the values.

## Constraints

- Native look: colours come from the palette tokens the illustrations already use (terrain, line,
  fill or cut, text), so the diagram follows QGIS's light and dark themes. Fill uses the map's
  orange, cut uses its blue.
- QSvgRenderer only: plain paths and text, no filters.
- Every Qt slot stays guarded: an exception is logged under the "Terrain Scenarios" tag, never
  raised.

## Left to the builder

- Whether the SVG is generated in Python, replacing `parameters.svg`, or drawn with QPainter.
  Generating the SVG keeps the existing highlight mechanism (the `{opacity-key}` tokens) and the
  palette tokens.
- The exact minimum height, margins, label placement and the handling of collisions between
  labels.
