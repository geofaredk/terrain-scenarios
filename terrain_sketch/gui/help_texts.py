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

VIEW_3D_TIP = ("Show the modified DEM in a new 3D view. It becomes the project's terrain until this "
               "session ends; the terrain you had before is put back then.")
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
