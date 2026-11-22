"""The scenario GeoPackage on its own: what goes into the file and what comes back out."""
import os
from dataclasses import replace
from unittest import mock

import pytest
from osgeo import ogr
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, square, start_session
from terrain_scenarios.core.tools import Mode, PixelMode, Tool
from terrain_scenarios.gui.controller import SketchController
from terrain_scenarios.qgis_io import scenario
from terrain_scenarios.qgis_io.scenario import (FEATURES_LAYER, META_TABLE, ScenarioError, ScenarioMeta,
                                             dem_meta, load, load_meta, save)

# A projected CRS with no EPSG code, like a local survey grid. GDAL cannot identify it.
LOCAL_GRID = ('PROJCS["Local survey grid",GEOGCS["ETRS89",DATUM["ETRS89",SPHEROID["GRS 1980",6378137,'
              '298.257222101]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
              'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",0],'
              'PARAMETER["central_meridian",9.5],PARAMETER["scale_factor",0.9996],'
              'PARAMETER["false_easting",500000],PARAMETER["false_northing",0],UNIT["metre",1]]')


def two_features(c):
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    c.update_feature(dike.id, amount=1.8, width=4.5, slope_n=2.5, reach=12.0,
                     cross_right=((3.0, -0.6),), long_profile=((0.0, 12.0), (29.0, 13.0)))
    c.update_feature(pond.id, pixel_mode=PixelMode.ALL_TOUCHED, slopes_inside=True, enabled=False,
                     section_line=line_through(8, 17, 27, 18).asWkb().data())
    return c.features


def test_a_scenario_round_trips_every_field(tmp_path):
    c = start_session(tmp_path)
    saved = two_features(c)
    path = str(tmp_path / "scenario.gpkg")
    save(path, saved, dem_meta(c.info, c.stack.original))
    loaded, _meta = load(path)
    assert len(loaded) == len(saved)
    for before, after in zip(saved, loaded):
        assert after.name == before.name and after.tool is before.tool
        assert after.mode is before.mode and after.enabled == before.enabled
        assert after.pixel_mode is before.pixel_mode
        assert after.amount == before.amount and after.width == before.width
        assert after.slope_n == before.slope_n and after.reach == before.reach
        assert after.slopes_inside == before.slopes_inside
        assert after.cross_left == before.cross_left and after.cross_right == before.cross_right
        assert after.long_profile == before.long_profile
        assert after.geometry_wkb == before.geometry_wkb
        assert after.section_line == before.section_line
    assert loaded[1].section_line is not None and loaded[0].section_line is None


def test_style_survives_save_and_load(tmp_path):
    c = start_session(tmp_path)
    styled = [replace(f, style="<symbol a='1'/>") if i == 0 else f for i, f in enumerate(two_features(c))]
    path = str(tmp_path / "styled.gpkg")
    save(path, styled, dem_meta(c.info, c.stack.original))
    loaded, _ = load(path)
    assert [f.style for f in loaded] == ["<symbol a='1'/>", None]


def test_a_scenario_without_a_style_column_opens_unstyled(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "old.gpkg")
    save(path, two_features(c), dem_meta(c.info, c.stack.original))
    source = ogr.Open(path, 1)
    layer = source.GetLayerByName(FEATURES_LAYER)
    layer.DeleteField(layer.GetLayerDefn().GetFieldIndex("style"))
    source.Close()
    loaded = load(path)[0]
    assert len(loaded) == 2 and all(f.style is None for f in loaded)


def test_the_saved_order_is_the_order_that_comes_back(tmp_path):
    c = start_session(tmp_path)
    saved = two_features(c)
    path = str(tmp_path / "order.gpkg")
    save(path, saved, dem_meta(c.info, c.stack.original))
    assert [f.name for f in load(path)[0]] == [f.name for f in saved]


def test_the_file_is_a_readable_geopackage_with_the_documented_layer(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "plain.gpkg")
    save(path, two_features(c), dem_meta(c.info, c.stack.original))
    source = ogr.Open(path)                      # opened as a plain GeoPackage, no plugin involved
    assert source.GetLayerByName(FEATURES_LAYER) is not None
    layer = source.GetLayerByName(FEATURES_LAYER)
    names = {layer.GetLayerDefn().GetFieldDefn(i).GetName()
             for i in range(layer.GetLayerDefn().GetFieldCount())}
    assert {"order", "name", "tool", "mode", "enabled", "pixel_mode", "params",
            "cross_profile", "long_profile", "section_line", "style"} <= names
    assert layer.GetFeatureCount() == 2
    assert layer.GetNextFeature().GetGeometryRef() is not None    # real geometry, not a blob
    rows = source.ExecuteSQL(f'SELECT key, value FROM "{META_TABLE}"')
    keys = {row.GetField("key") for row in rows}
    source.ReleaseResultSet(rows)
    assert keys == {"plugin_version", "dem_source", "dem_crs", "dem_extent", "dem_size",
                    "dem_pixel_size", "created", "modified"}           # spec §8.4, exactly


def test_the_metadata_records_the_dem_it_was_built_on(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "meta.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original, version="9.9"))
    _features, meta = load(path)
    assert meta.dem_size == f"{c.stack.original.cols}x{c.stack.original.rows}"
    assert meta.dem_crs.startswith("EPSG:") and meta.plugin_version == "9.9"
    assert meta.created and meta.modified


def test_a_different_dem_is_reported_as_specific_differences():
    same = ScenarioMeta(dem_crs="EPSG:25832", dem_size="40x40", dem_pixel_size="1.0,1.0")
    assert same.differences(same) == []
    other = ScenarioMeta(dem_crs="EPSG:4326", dem_size="80x80", dem_pixel_size="1.0,1.0")
    assert set(same.differences(other)) == {"coordinate system", "size in pixels"}
    every = ScenarioMeta(dem_crs="EPSG:25832", dem_size="40x40", dem_pixel_size="1.0,1.0", dem_extent="0,0,40,40")
    moved = ScenarioMeta(dem_crs="EPSG:3035", dem_size="20x20", dem_pixel_size="2.0,2.0", dem_extent="5,5,45,45")
    assert every.differences(moved) == ["coordinate system", "size in pixels", "pixel size", "extent"]


def test_metadata_a_file_does_not_carry_is_not_reported_as_a_difference():
    known = ScenarioMeta(dem_crs="EPSG:25832", dem_size="40x40")
    assert known.differences(ScenarioMeta()) == []      # an older file with no metadata


def test_opening_something_that_is_not_a_scenario_is_reported(tmp_path):
    plain = tmp_path / "notes.txt"
    plain.write_text("not a geopackage")
    with pytest.raises(ScenarioError):
        load(str(plain))


def test_opening_something_that_is_not_a_scenario_is_reported_before_loading(tmp_path):
    path = tmp_path / "notes.gpkg"
    path.write_text("not a geopackage")
    with pytest.raises(ScenarioError):
        load_meta(str(path))


def test_saving_where_it_cannot_be_written_is_reported(tmp_path):
    c = start_session(tmp_path)
    with pytest.raises(ScenarioError):
        save(str(tmp_path / "no-such-dir" / "x.gpkg"), c.features, dem_meta(c.info, c.stack.original))


def test_a_geopackage_without_the_features_layer_is_not_taken_for_a_scenario(tmp_path):
    path = str(tmp_path / "other.gpkg")
    source = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    source.CreateLayer("roads", None, ogr.wkbLineString)
    source.Close()
    with pytest.raises(ScenarioError, match="not a Terrain Scenarios file"):
        load(path)
    with pytest.raises(ScenarioError, match="not a Terrain Scenarios file"):
        load_meta(path)


def test_saving_over_a_file_open_as_a_wal_layer_is_refused(tmp_path):
    """`os.replace` over a GeoPackage another program holds open in WAL mode (QGIS showing the
    scenario as a layer) leaves that program's `-wal`/`-shm` beside the new file — SQLite
    documents that pairing as a corruption path."""
    c = start_session(tmp_path)
    path = str(tmp_path / "open-elsewhere.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    before = (tmp_path / "open-elsewhere.gpkg").read_bytes()
    (tmp_path / "open-elsewhere.gpkg-wal").write_bytes(b"")

    with pytest.raises(ScenarioError):
        save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "open-elsewhere.gpkg").read_bytes() == before


def test_saving_over_a_geopackage_that_is_not_a_scenario_is_refused(tmp_path):
    """`os.replace` destroys every layer in the file it replaces — so a GeoPackage that holds
    the DEM or a user's other layers, not a scenario, must never be chosen as a save target."""
    c = start_session(tmp_path)
    path = str(tmp_path / "other.gpkg")
    source = ogr.GetDriverByName("GPKG").CreateDataSource(path)
    source.CreateLayer("roads", None, ogr.wkbLineString)
    source.Close()
    before = (tmp_path / "other.gpkg").read_bytes()

    with pytest.raises(ScenarioError, match="not a Terrain Scenarios file"):
        save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "other.gpkg").read_bytes() == before


def test_saving_over_a_non_geopackage_file_is_refused(tmp_path):
    c = start_session(tmp_path)
    path = tmp_path / "notes.gpkg"
    path.write_text("not a geopackage")
    before = path.read_bytes()

    with pytest.raises(ScenarioError, match="not a Terrain Scenarios file"):
        save(str(path), c.features, dem_meta(c.info, c.stack.original))
    assert path.read_bytes() == before


def test_replacing_an_existing_scenario_still_works(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "existing.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    save(path, c.features, dem_meta(c.info, c.stack.original))
    assert len(load(path)[0]) == 1


def test_a_save_that_fails_half_way_leaves_the_previous_file_readable(tmp_path):
    c = start_session(tmp_path)
    features = two_features(c)
    path = str(tmp_path / "precious.gpkg")
    save(path, features, dem_meta(c.info, c.stack.original))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 5, 34, 5), UTM)

    with mock.patch.object(scenario, "_write_meta", side_effect=RuntimeError("disk full")):
        with pytest.raises(ScenarioError):
            save(path, c.features, dem_meta(c.info, c.stack.original))
    assert len(load(path)[0]) == 2                                  # the last good save survives
    assert not [n for n in os.listdir(tmp_path) if ".saving-" in n]  # and nothing half-written is left


def test_saving_returns_the_dates_it_wrote(tmp_path):
    c = start_session(tmp_path)
    path = str(tmp_path / "dates.gpkg")
    first = save(path, two_features(c), dem_meta(c.info, c.stack.original))
    assert first.created and first.modified and load_meta(path) == first
    again = save(path, c.features, dem_meta(c.info, c.stack.original, created="2020-01-01T00:00:00+00:00"))
    assert again.created == "2020-01-01T00:00:00+00:00"            # a known creation date is kept


def test_every_load_gives_the_features_new_ids(tmp_path):
    """Two scenario files both have a first row. Ids taken from the row would let a panel that
    is still showing feature 1 of the old scenario silently edit feature 1 of the new one."""
    c = start_session(tmp_path)
    saved_ids = {f.id for f in two_features(c)}
    path = str(tmp_path / "ids.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    first = {f.id for f in load(path)[0]}
    second = {f.id for f in load(path)[0]}
    assert len(first) == len(second) == 2
    assert not first & second and not first & saved_ids


def test_a_replace_check_that_raises_is_reported_as_a_scenario_error_not_crashed(tmp_path):
    """`_is_scenario_file` guards only `ogr.Open` — `ExecuteSQL` and friends can still raise
    RuntimeError (e.g. "database is locked"). That must become ScenarioError, not escape raw:
    an exception escaping the Save button's Qt slot aborts QGIS."""
    c = start_session(tmp_path)
    path = str(tmp_path / "locked.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    before = (tmp_path / "locked.gpkg").read_bytes()

    with mock.patch.object(scenario, "_is_scenario_file", side_effect=RuntimeError("database is locked")):
        with pytest.raises(ScenarioError):
            save(path, c.features, dem_meta(c.info, c.stack.original))
    assert (tmp_path / "locked.gpkg").read_bytes() == before
    assert not [n for n in os.listdir(tmp_path) if ".saving-" in n]


def test_a_dem_on_a_crs_without_an_epsg_code_is_described_and_written_with_its_crs(tmp_path):
    c = SketchController(QgsProject.instance())
    c.set_dem(dem_layer(tmp_path, crs=LOCAL_GRID))
    meta = dem_meta(c.info, c.stack.original)                     # raised "Unsupported SRS" before
    assert meta.dem_crs == "Local survey grid"
    path = str(tmp_path / "local.gpkg")
    save(path, [], meta, crs_wkt=c.info.crs_wkt)

    source = ogr.Open(path)                        # held: a layer dies with its datasource
    srs = source.GetLayerByName(FEATURES_LAYER).GetSpatialRef()
    assert srs is not None                         # QGIS draws the outlines in the right place
    assert srs.GetName() == "Local survey grid"
    source = None


def test_a_section_line_that_cannot_be_read_goes_back_to_the_default_line(tmp_path):
    """The line only decides what the Profiles panel shows; it must not refuse the whole scenario."""
    c = start_session(tmp_path)
    path = str(tmp_path / "scenario.gpkg")
    save(path, two_features(c), dem_meta(c.info, c.stack.original))
    source = ogr.Open(path, 1)
    layer = source.GetLayerByName(FEATURES_LAYER)
    for row in layer:
        if row.GetField("section_line"):
            row.SetField("section_line", "LINESTRING (1 2, oops")
            layer.SetFeature(row)
    source.Close()
    loaded, _meta = load(path)
    assert len(loaded) == 2 and all(f.section_line is None for f in loaded)


def saved_as_terrain_sketch(tmp_path, c):
    """A scenario as the plugin wrote it while it was still called Terrain Sketch: the same file,
    with the metadata table under its old name."""
    path = str(tmp_path / "terrain_sketch_era.gpkg")
    save(path, two_features(c), dem_meta(c.info, c.stack.original, version="0.1.0"))
    source = ogr.Open(path, 1)
    source.ExecuteSQL(f'ALTER TABLE "{META_TABLE}" RENAME TO "terrain_sketch_meta"')
    source.Close()
    return path


def test_a_scenario_saved_as_terrain_sketch_still_opens(tmp_path):
    c = start_session(tmp_path)
    path = saved_as_terrain_sketch(tmp_path, c)
    features, meta = load(path)
    assert [f.name for f in features] == [f.name for f in c.features]
    assert meta.plugin_version == "0.1.0"
    assert meta.dem_size == f"{c.stack.original.cols}x{c.stack.original.rows}"


def test_a_scenario_saved_as_terrain_sketch_reports_its_metadata(tmp_path):
    c = start_session(tmp_path)
    meta = load_meta(saved_as_terrain_sketch(tmp_path, c))
    assert meta.plugin_version == "0.1.0" and meta.created and meta.modified
    assert meta.differences(dem_meta(c.info, c.stack.original)) == []


def test_a_scenario_saved_as_terrain_sketch_can_be_saved_over_in_the_new_format(tmp_path):
    c = start_session(tmp_path)
    path = saved_as_terrain_sketch(tmp_path, c)
    save(path, c.features[:1], dem_meta(c.info, c.stack.original, version="9.9"))
    features, meta = load(path)
    assert len(features) == 1 and meta.plugin_version == "9.9"
    source = ogr.Open(path)
    tables = source.ExecuteSQL("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row.GetField("name") for row in tables}
    source.ReleaseResultSet(tables)
    source.Close()
    assert META_TABLE in names and "terrain_sketch_meta" not in names
