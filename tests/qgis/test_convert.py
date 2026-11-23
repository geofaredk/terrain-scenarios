import pytest
from qgis.core import QgsCoordinateReferenceSystem, QgsGeometry

from qgis_helpers import UTM
from terrain_scenarios.core.geometry import is_line, split_parts
from terrain_scenarios.core.tools import Mode
from terrain_scenarios.qgis_io.compat import gdal_problems
from terrain_scenarios.qgis_io.convert import from_wkb, to_dem_wkb

WGS84 = QgsCoordinateReferenceSystem("EPSG:4326")


def test_bundled_gdal_has_everything_the_engine_needs():
    assert gdal_problems() == []


def test_bowtie_polygon_is_repaired_into_two_parts():
    bowtie = QgsGeometry.fromWkt("POLYGON((0 0, 10 10, 10 0, 0 10, 0 0))")
    parts = split_parts(to_dem_wkb(bowtie, UTM, UTM, Mode.AREA))
    assert len(parts) == 2 and not any(is_line(p) for p in parts)


def test_only_parts_of_the_wanted_dimension_are_kept():
    mixed = QgsGeometry.fromWkt("GEOMETRYCOLLECTION(POINT(1 1), LINESTRING(0 0, 5 5), POLYGON((0 0, 1 0, 1 1, 0 0)))")
    assert [is_line(p) for p in split_parts(to_dem_wkb(mixed, UTM, UTM, Mode.PATH))] == [True]
    with pytest.raises(ValueError):
        to_dem_wkb(QgsGeometry.fromWkt("LINESTRING(0 0, 5 5)"), UTM, UTM, Mode.AREA)


def test_geometry_is_transformed_to_the_dem_crs():
    back = from_wkb(to_dem_wkb(QgsGeometry.fromWkt("LINESTRING(9 55.7, 9.001 55.7)"), WGS84, UTM, Mode.PATH))
    assert 400000 < back.vertexAt(0).x() < 600000
    assert back.length() == pytest.approx(62.7, rel=0.05)
