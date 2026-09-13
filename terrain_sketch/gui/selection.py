"""How the user marks the area of a feature: click, freehand, brush or an existing layer."""
from __future__ import annotations

from enum import Enum


class Method(str, Enum):
    CLICK = "click"
    FREEHAND = "freehand"
    BRUSH = "brush"
    LAYER = "layer"


METHOD_LABELS = {
    Method.CLICK: "Draw",
    Method.FREEHAND: "Freehand",
    Method.BRUSH: "Brush",
    Method.LAYER: "From layer",
}

METHOD_ICONS = {
    Method.CLICK: "/mActionCaptureLine.svg",
    Method.FREEHAND: "/mActionSelectFreehand.svg",
    Method.BRUSH: "/mActionAddBasicCircle.svg",
    Method.LAYER: "/mActionAddOgrLayer.svg",
}

METHOD_TIPS = {
    Method.CLICK: "Click point by point; right-click or Enter finishes.",
    Method.FREEHAND: "Hold the mouse and trace the shape; release to finish.",
    Method.BRUSH: "Paint over the cells with a round brush; hold Shift to erase, [ and ] change the radius.",
    Method.LAYER: "Use lines or areas from a layer that is already in your project.",
}

METHOD_HINTS = {
    Method.CLICK: "Click to add points. Right-click or press Enter to finish, Backspace removes the last "
                  "point, Esc cancels.",
    Method.FREEHAND: "Hold the left mouse button and trace the shape. Release to finish, Esc cancels.",
    Method.BRUSH: "Paint with the left mouse button, hold Shift to erase. [ and ] or Ctrl+wheel change the "
                  "radius. Right-click or Enter finishes, Esc cancels.",
    Method.LAYER: "Pick a layer below and press 'Use these features'.",
}

BRUSH_EXTEND_HINT = ("Extending {} — paint with the left mouse button to add to it, hold Shift to erase. "
                     "[ and ] or Ctrl+wheel change the radius. Right-click or Enter finishes, Esc cancels.")

EDIT_ICON = "/mActionVertexTool.svg"

EDIT_HINT = ("Drag a vertex to move it, double-click a segment to add one, press Delete to remove the vertex "
             "under the cursor. Esc stops editing.")
