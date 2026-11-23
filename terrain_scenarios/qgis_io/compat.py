"""Checks that the GDAL shipped with QGIS offers what the engine needs (GDAL 3.11 or newer)."""
from __future__ import annotations

from osgeo import gdal, ogr

gdal.UseExceptions()
ogr.UseExceptions()


def gdal_problems() -> list[str]:
    """User-facing descriptions of missing GDAL capabilities; empty when all is well."""
    problems = []
    mem = gdal.GetDriverByName("MEM")
    if mem is None or mem.GetMetadataItem(gdal.DCAP_VECTOR) != "YES":
        problems.append("GDAL's in-memory driver cannot hold vector layers.")
    try:
        line = ogr.CreateGeometryFromWkt("LINESTRING (0 0, 1 0)")
        flat = line.Buffer(0.5, ["ENDCAP_STYLE=FLAT"])
        if flat is None or abs(flat.GetArea() - 1.0) > 1e-9:
            problems.append("GDAL cannot buffer lines with flat ends.")
    except (RuntimeError, TypeError):
        problems.append("GDAL cannot buffer lines with flat ends.")
    if problems:
        problems.append(f"Terrain Scenarios needs GDAL 3.11 or newer; this QGIS has GDAL {gdal.__version__}.")
    return problems
