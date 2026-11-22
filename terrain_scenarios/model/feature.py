"""TerrainFeature: one drawn landscape feature and its parameters (pure data, no QGIS)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from ..core.tools import TOOL_INFO, Mode, PixelMode, Tool


@dataclass(frozen=True)
class TerrainFeature:
    id: str
    name: str
    tool: Tool
    mode: Mode
    geometry_wkb: bytes              # LineString/Polygon or Multi*, in the DEM CRS
    enabled: bool = True
    pixel_mode: PixelMode = PixelMode.CENTRE
    amount: float = 1.0              # height H (raise/add) or depth D (lower/subtract), m, >= 0
    width: float = 2.0               # path corridor width W, m
    slope_n: float = 3.0             # side slope 1:n (n m across per 1 m height); 0 = none
    reach: float = 20.0              # maximum horizontal reach of a side slope, m
    slopes_inside: bool = False      # area features: slopes inside the outline
    cross_left: tuple = ()           # ((distance beyond corridor edge, dz), ...)
    cross_right: tuple = ()
    long_profile: tuple | None = None  # ((station, absolute z), ...); None = tool rule
    section_line: bytes | None = None  # areas: WKB line the section runs along; None = the default line
    style: str | None = None         # QGIS symbol XML for the map; None = the default symbol

    def __post_init__(self):
        if self.mode not in TOOL_INFO[self.tool].modes:
            raise ValueError(f"{self.tool.value} does not support {self.mode.value} mode")
        # the GUI may pass lists; store hashable tuples of float pairs (the engine caches by value)
        object.__setattr__(self, "geometry_wkb", bytes(self.geometry_wkb))
        object.__setattr__(self, "cross_left", _points(self.cross_left))
        object.__setattr__(self, "cross_right", _points(self.cross_right))
        if self.long_profile is not None:
            object.__setattr__(self, "long_profile", _points(self.long_profile))
        if self.section_line is not None:
            object.__setattr__(self, "section_line", bytes(self.section_line))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "tool": self.tool.value,
            "mode": self.mode.value,
            "geometry_wkb": self.geometry_wkb.hex(),
            "enabled": self.enabled,
            "pixel_mode": self.pixel_mode.value,
            "amount": self.amount,
            "width": self.width,
            "slope_n": self.slope_n,
            "reach": self.reach,
            "slopes_inside": self.slopes_inside,
            "cross_left": [list(p) for p in self.cross_left],
            "cross_right": [list(p) for p in self.cross_right],
            "long_profile": None if self.long_profile is None else [list(p) for p in self.long_profile],
            "section_line": None if self.section_line is None else self.section_line.hex(),
            "style": self.style,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TerrainFeature:
        return cls(
            id=d["id"],
            name=d["name"],
            tool=Tool(d["tool"]),
            mode=Mode(d["mode"]),
            geometry_wkb=bytes.fromhex(d["geometry_wkb"]),
            enabled=bool(d.get("enabled", True)),
            pixel_mode=PixelMode(d.get("pixel_mode", PixelMode.CENTRE.value)),
            amount=float(d.get("amount", 1.0)),
            width=float(d.get("width", 2.0)),
            slope_n=float(d.get("slope_n", 3.0)),
            reach=float(d.get("reach", 20.0)),
            slopes_inside=bool(d.get("slopes_inside", False)),
            cross_left=_points(d.get("cross_left")),
            cross_right=_points(d.get("cross_right")),
            long_profile=None if d.get("long_profile") is None else _points(d["long_profile"]),
            section_line=None if d.get("section_line") is None else bytes.fromhex(d["section_line"]),
            style=d.get("style"),
        )


def _points(seq) -> tuple:
    return tuple((float(a), float(b)) for a, b in (seq or ()))


def default_width(cell_size: float) -> float:
    return round(max(3.0 * cell_size, 1.0), 1)


def new_feature(tool: Tool, mode: Mode, geometry_wkb: bytes, cell_size: float,
                name: str | None = None) -> TerrainFeature:
    """A feature with the defaults the GUI uses right after drawing."""
    return TerrainFeature(
        id=uuid.uuid4().hex,
        name=name or tool.value.replace("_", " ").capitalize(),
        tool=tool,
        mode=mode,
        geometry_wkb=bytes(geometry_wkb),
        width=default_width(cell_size),
        slopes_inside=mode is Mode.AREA and TOOL_INFO[tool].direction > 0,
    )
