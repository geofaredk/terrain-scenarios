"""Saving and loading a scenario as a GeoPackage: the features layer plus a metadata table.

The file is a normal GeoPackage, so a user can open it in QGIS and look at the outlines without
the plugin. That is the point of the format choice: the features layer carries real geometry in
the DEM's CRS, and everything the engine needs to rebuild a feature travels in ordinary fields
beside it (spec §8.4).
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from osgeo import ogr, osr

from ..core.tools import Mode, PixelMode, Tool
from ..model.feature import TerrainFeature

ogr.UseExceptions()   # also relied on by sibling modules; set here so this module stands alone

FEATURES_LAYER = "features"
META_TABLE = "terrain_sketch_meta"
PARAM_FIELDS = ("amount", "width", "slope_n", "reach", "slopes_inside")
FIELDS = (("order", ogr.OFTInteger), ("name", ogr.OFTString), ("tool", ogr.OFTString),
          ("mode", ogr.OFTString), ("enabled", ogr.OFTInteger), ("pixel_mode", ogr.OFTString),
          ("params", ogr.OFTString), ("cross_profile", ogr.OFTString),
          ("long_profile", ogr.OFTString), ("section_line", ogr.OFTString))
# section_line is written as null: no feature carries a custom area section line yet, and the
# field is kept so a file written now still has the documented layout when one does (spec §8.4).

# qgis_io/scenario.py cannot import gui/help_texts.py (Global Constraints: "qgis_io/scenario.py
# uses ogr/osr only"), so these messages live beside the rest of this module's own ScenarioError
# text (e.g. "Terrain Sketch could not create {path}." below) rather than there.
SCENARIO_FILE_IN_USE = ("{} is open in another program (such as a layer in QGIS), so it was not saved. "
                        "Remove that layer or close the program, then try again.")
SCENARIO_WOULD_REPLACE_OTHER_FILE = ("{} is not a Terrain Sketch scenario, so saving would replace it "
                                     "entirely. Choose another name.")


class ScenarioError(Exception):
    """The scenario file cannot be written or read; the message is shown to the user."""


@dataclass(frozen=True)
class ScenarioMeta:
    """What the file records about the DEM it was built on, so a mismatch can be reported."""

    dem_source: str = ""
    dem_crs: str = ""
    dem_extent: str = ""
    dem_size: str = ""
    dem_pixel_size: str = ""
    plugin_version: str = ""
    created: str = ""
    modified: str = ""

    def differences(self, other: ScenarioMeta) -> list[str]:
        """Which DEM properties disagree, in words a user can act on. Ignores the bookkeeping
        fields — only the DEM's identity matters for whether a scenario still applies."""
        labels = {"dem_crs": "coordinate system", "dem_size": "size in pixels",
                  "dem_pixel_size": "pixel size", "dem_extent": "extent"}
        return [text for key, text in labels.items()
                if getattr(self, key) and getattr(other, key)
                and getattr(self, key) != getattr(other, key)]


def dem_meta(info, grid, version: str = "", created: str = "") -> ScenarioMeta:
    """Describe the DEM a scenario is being saved against. Never raises: this is bookkeeping,
    and a DEM whose CRS cannot be named must still be saveable."""
    x0, w, _rx, y0, _ry, h = grid.geotransform
    return ScenarioMeta(
        dem_source=getattr(info, "path", ""),
        dem_crs=_crs_id(getattr(info, "crs_wkt", "")),
        dem_extent=_round6((x0, y0 + h * grid.rows, x0 + w * grid.cols, y0)),
        dem_size=f"{grid.cols}x{grid.rows}",
        dem_pixel_size=_round6((abs(w), abs(h))),
        plugin_version=version,
        created=created,
    )


def save(path: str, features, meta: ScenarioMeta, crs_wkt: str = "") -> ScenarioMeta:
    """Write `features` and `meta` to `path`, replacing any file already there, and return the
    metadata as written — with `created` and `modified` filled in.

    The file is built beside the target and moved over it only once it is complete, so a save
    that fails half way — a full disk, a feature GDAL refuses — leaves the previous scenario
    readable instead of destroying it. There is no undo to recover it from."""
    driver = ogr.GetDriverByName("GPKG")
    if driver is None:
        raise ScenarioError("This QGIS has no GeoPackage driver, so scenarios cannot be saved.")
    folder, name = os.path.split(os.path.abspath(path))
    partial = os.path.join(folder, f"{os.path.splitext(name)[0]}.saving-{uuid.uuid4().hex[:8]}.gpkg")
    source = None
    try:
        _check_replaceable(path)
        source = driver.CreateDataSource(partial)
        if source is None:
            raise ScenarioError(f"Terrain Sketch could not create {path}.")
        layer = source.CreateLayer(FEATURES_LAYER, _srs(crs_wkt or meta.dem_crs), ogr.wkbUnknown)
        for field, kind in FIELDS:
            layer.CreateField(ogr.FieldDefn(field, kind))
        for order, feature in enumerate(features):
            layer.CreateFeature(_to_ogr(layer, order, feature))
        written = _write_meta(source, meta)
        # Closed explicitly rather than by dropping the name: closing is what flushes the file, and
        # any other reference — a traceback frame, say — would otherwise keep it open, which on
        # Windows blocks both the move below and the clean-up of a failed attempt.
        source.Close()
        source = None
        os.replace(partial, path)
        return written
    except ScenarioError:
        _discard_partial(source, partial)
        raise
    except Exception as error:  # noqa: BLE001 — GDAL raises many types; the user gets one message
        _discard_partial(source, partial)
        raise ScenarioError(f"Terrain Sketch could not save the scenario: {error}") from error


def _check_replaceable(path: str) -> None:
    """Refuse to let `save` replace `path` whole when that would be unsafe. `os.replace` destroys
    every layer already in the file, so the target must already be a Terrain Sketch scenario —
    and even then, not one another program currently has open."""
    if os.path.exists(path + "-wal") or os.path.exists(path + "-shm"):
        # SQLite documents leaving WAL/SHM siblings orphaned beside a file swapped in under a
        # program that still has the original open (as QGIS does for a scenario shown as a
        # layer) as a corruption path.
        raise ScenarioError(SCENARIO_FILE_IN_USE.format(path))
    if os.path.exists(path) and not _is_scenario_file(path):
        raise ScenarioError(SCENARIO_WOULD_REPLACE_OTHER_FILE.format(path))


def _is_scenario_file(path: str) -> bool:
    """Whether `path` already holds a Terrain Sketch scenario. Checked on the GeoPackage's own
    SQLite catalogue rather than through `_open`/`FEATURES_LAYER`: an empty scenario (no features
    yet) still has `META_TABLE`, and that table was written with a plain `CREATE TABLE`, not
    through OGR's own layer-creation API, so it never appears via `GetLayerByName` either way."""
    try:
        source = ogr.Open(path)
    except RuntimeError:                           # the plugin runs GDAL with exceptions on
        return False
    if source is None:
        return False
    try:
        result = source.ExecuteSQL(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{META_TABLE}'")
        if result is None:
            return False
        try:
            return result.GetFeatureCount() > 0
        finally:
            source.ReleaseResultSet(result)
    finally:
        source.Close()


def _discard_partial(source, partial: str) -> None:
    if source is not None:
        try:
            source.Close()
        except Exception:  # noqa: BLE001 — already failing; the original error is the one to report
            pass
    for leftover in (partial, partial + "-journal", partial + "-wal", partial + "-shm"):
        try:
            os.remove(leftover)
        except OSError:
            pass


def load(path: str) -> tuple[list[TerrainFeature], ScenarioMeta]:
    """Read a scenario back. Raises ScenarioError for anything unreadable."""
    source = None
    try:
        source, layer = _open(path)
        rows = sorted((_from_ogr(f) for f in layer), key=lambda pair: pair[0])
        return [feature for _order, feature in rows], _read_meta(source)
    except ScenarioError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ScenarioError(f"Terrain Sketch could not read the scenario: {error}") from error
    finally:
        _close(source)


def load_meta(path: str) -> ScenarioMeta:
    """Only the metadata, to compare DEMs before deciding whether to load. Raises ScenarioError
    for a file that is not a readable scenario, exactly as `load` would."""
    source = None
    try:
        source, _layer = _open(path)
        return _read_meta(source)
    except ScenarioError:
        raise
    except Exception as error:  # noqa: BLE001
        raise ScenarioError(f"Terrain Sketch could not read the scenario: {error}") from error
    finally:
        _close(source)


def _open(path: str):
    source = ogr.Open(path)
    if source is None:
        raise ScenarioError(f"Terrain Sketch could not open {path}.")
    layer = source.GetLayerByName(FEATURES_LAYER)
    if layer is None:
        source.Close()
        raise ScenarioError(f"{path} is not a Terrain Sketch scenario: it has no '{FEATURES_LAYER}' layer.")
    return source, layer


def _close(source) -> None:
    """Release a read handle now, not whenever it is collected: a scenario that is still open
    cannot be replaced by the next save on Windows."""
    if source is not None:
        try:
            source.Close()
        except Exception:  # noqa: BLE001 — reading already succeeded or failed on its own terms
            pass


def _to_ogr(layer, order: int, feature: TerrainFeature):
    out = ogr.Feature(layer.GetLayerDefn())
    out.SetGeometry(ogr.CreateGeometryFromWkb(feature.geometry_wkb))
    out.SetField("order", order)
    out.SetField("name", feature.name)
    out.SetField("tool", feature.tool.value)
    out.SetField("mode", feature.mode.value)
    out.SetField("enabled", int(feature.enabled))
    out.SetField("pixel_mode", feature.pixel_mode.value)
    out.SetField("params", json.dumps({k: getattr(feature, k) for k in PARAM_FIELDS}))
    out.SetField("cross_profile", json.dumps({"left": [list(p) for p in feature.cross_left],
                                              "right": [list(p) for p in feature.cross_right]}))
    if feature.long_profile is not None:
        out.SetField("long_profile", json.dumps([list(p) for p in feature.long_profile]))
    return out


def _from_ogr(row) -> tuple[int, TerrainFeature]:
    geometry = row.GetGeometryRef()
    if geometry is None:
        raise ScenarioError("A feature in the scenario has no geometry.")
    params = json.loads(row.GetField("params") or "{}")
    cross = json.loads(row.GetField("cross_profile") or "{}")
    long_profile = row.GetField("long_profile")
    feature = TerrainFeature(
        # A fresh id, never one derived from the row: two files both have a row 1, and a panel
        # still showing feature 1 of the old scenario must not silently retarget the new one.
        id=uuid.uuid4().hex,
        name=row.GetField("name") or "Feature",
        tool=Tool(row.GetField("tool")),
        mode=Mode(row.GetField("mode")),
        geometry_wkb=bytes(geometry.ExportToWkb()),
        enabled=bool(row.GetField("enabled")),
        pixel_mode=PixelMode(row.GetField("pixel_mode")),
        cross_left=tuple(tuple(p) for p in cross.get("left", ())),
        cross_right=tuple(tuple(p) for p in cross.get("right", ())),
        long_profile=None if not long_profile else tuple(tuple(p) for p in json.loads(long_profile)),
        **{k: params[k] for k in PARAM_FIELDS if k in params},
    )
    return int(row.GetField("order") or 0), feature


def _write_meta(source, meta: ScenarioMeta) -> ScenarioMeta:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = replace(meta, created=meta.created or now, modified=now)
    values = {k: str(v) for k, v in written.__dict__.items()}
    source.ExecuteSQL(f'CREATE TABLE "{META_TABLE}" (key TEXT PRIMARY KEY, value TEXT)')
    for key, value in values.items():
        escaped = value.replace("'", "''")
        source.ExecuteSQL(f"INSERT INTO \"{META_TABLE}\" (key, value) VALUES ('{key}', '{escaped}')")
    return written


def _read_meta(source) -> ScenarioMeta:
    result = source.ExecuteSQL(f'SELECT key, value FROM "{META_TABLE}"')
    if result is None:
        return ScenarioMeta()
    try:
        pairs = {row.GetField("key"): row.GetField("value") for row in result}
    finally:
        source.ReleaseResultSet(result)
    known = ScenarioMeta().__dict__
    return ScenarioMeta(**{k: v for k, v in pairs.items() if k in known})


def _srs(definition: str):
    """A spatial reference from WKT or an id like EPSG:25832; None when it cannot be read."""
    if not definition:
        return None
    srs = osr.SpatialReference()
    try:
        if srs.SetFromUserInput(definition) != 0:
            return None
    except RuntimeError:                           # the plugin runs GDAL with exceptions on
        return None
    return srs


def _crs_id(wkt: str) -> str:
    """EPSG:nnnn when the CRS has a code, otherwise its name. Never raises — with GDAL
    exceptions on, AutoIdentifyEPSG throws for every CRS it cannot match, which is exactly
    the local or custom grid a scenario must still be saveable on."""
    srs = _srs(wkt)
    if srs is None:
        return ""
    try:
        srs.AutoIdentifyEPSG()
    except RuntimeError:
        pass
    code = srs.GetAuthorityCode(None)
    return f"EPSG:{code}" if code else srs.GetName() or ""


def _round6(values) -> str:
    return ",".join(f"{v:.6f}" for v in values)
