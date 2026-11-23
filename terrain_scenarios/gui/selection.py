"""How the user marks the area of a feature: click, freehand or an existing layer."""
from __future__ import annotations

from enum import Enum


class Method(str, Enum):
    CLICK = "click"
    FREEHAND = "freehand"
    LAYER = "layer"


METHOD_LABELS = {
    Method.CLICK: "Draw",
    Method.FREEHAND: "Freehand",
    Method.LAYER: "From layer",
}

METHOD_ICONS = {
    Method.CLICK: "/mActionCaptureLine.svg",
    Method.FREEHAND: "/mActionSelectFreehand.svg",
    Method.LAYER: "/mActionAddOgrLayer.svg",
}

METHOD_TIPS = {
    Method.CLICK: "Click point by point; right-click or Enter finishes.",
    Method.FREEHAND: "Hold the mouse and trace the shape; release to finish.",
    Method.LAYER: "Use lines or areas from a layer that is already in your project.",
}

METHOD_HINTS = {
    Method.CLICK: "Click to add points. Right-click or press Enter to finish, Backspace removes the last "
                  "point, Esc cancels.",
    Method.FREEHAND: "Hold the left mouse button and trace the shape. Release to finish, Esc cancels.",
    Method.LAYER: "Pick a layer below and press 'Use these features'.",
}

EDIT_ICON = "/mActionVertexTool.svg"
ZOOM_ICON = "/mActionZoomToLayer.svg"   # the feature page's Zoom to feature button reuses the context menu's icon

EDIT_HINT = ("Drag a vertex to move it, double-click a segment to add one, press Delete to remove the vertex "
             "under the cursor. Esc stops editing.")
