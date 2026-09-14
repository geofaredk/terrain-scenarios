"""Tool, mode and pixel-mode definitions shared by the engine, the model and the GUI."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Tool(str, Enum):
    INTERPOLATE = "interpolate"
    RAISE_PATH = "raise_path"
    LOWER_PATH = "lower_path"
    RAISE_FLAT = "raise_flat"
    LOWER_FLAT = "lower_flat"
    ADD = "add"
    SUBTRACT = "subtract"


class Mode(str, Enum):
    PATH = "path"
    AREA = "area"


class PixelMode(str, Enum):
    ALL_TOUCHED = "all_touched"
    CENTRE = "centre"
    FULLY_INSIDE = "fully_inside"


class Combine(str, Enum):
    SET = "set"
    MAX = "max"
    MIN = "min"
    ADD = "add"
    SUBTRACT = "subtract"


@dataclass(frozen=True)
class ToolInfo:
    modes: tuple
    combine: Combine
    has_slopes: bool
    direction: int  # -1: side slopes go down (raise tools), +1: go up (lower tools), 0: no slopes
    reports_storage: bool


TOOL_INFO = {
    Tool.INTERPOLATE: ToolInfo((Mode.PATH, Mode.AREA), Combine.SET, False, 0, True),
    Tool.RAISE_PATH: ToolInfo((Mode.PATH,), Combine.MAX, True, -1, False),
    Tool.LOWER_PATH: ToolInfo((Mode.PATH,), Combine.MIN, True, 1, True),
    Tool.RAISE_FLAT: ToolInfo((Mode.PATH, Mode.AREA), Combine.MAX, True, -1, False),
    Tool.LOWER_FLAT: ToolInfo((Mode.PATH, Mode.AREA), Combine.MIN, True, 1, True),
    Tool.ADD: ToolInfo((Mode.PATH, Mode.AREA), Combine.ADD, False, 0, False),
    Tool.SUBTRACT: ToolInfo((Mode.PATH, Mode.AREA), Combine.SUBTRACT, False, 0, True),
}


def reports_storage(tool: Tool, mode: Mode) -> bool:
    """Whether a feature can hold water, so its storage is worth computing and showing.
    Interpolate only does in area mode (spec §5.5): along a path it grades a strip between two
    ends and leaves no basin. The engine and the Volumes panel both ask here, so they cannot
    disagree about when a Storage figure exists."""
    return TOOL_INFO[tool].reports_storage and (tool is not Tool.INTERPOLATE or mode is Mode.AREA)