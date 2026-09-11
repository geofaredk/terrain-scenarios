"""Geometry -> boolean cell mask for the three pixel modes (GDAL in-memory rasterisation)."""
from __future__ import annotations

import numpy as np
from osgeo import gdal, ogr

from .grid import DemGrid
from .tools import PixelMode

gdal.UseExceptions()


def rasterize(geom, grid: DemGrid, all_touched: bool) -> np.ndarray:
    raster = gdal.GetDriverByName("MEM").Create("", grid.cols, grid.rows, 1, gdal.GDT_Byte)
    raster.SetGeoTransform(grid.geotransform)
    vector = gdal.GetDriverByName("MEM").Create("", 0, 0, 0, gdal.GDT_Unknown)
    layer = vector.CreateLayer("g", geom_type=ogr.wkbUnknown)
    feature = ogr.Feature(layer.GetLayerDefn())
    feature.SetGeometry(geom)
    layer.CreateFeature(feature)
    options = ["ALL_TOUCHED=TRUE"] if all_touched else []
    gdal.RasterizeLayer(raster, [1], layer, burn_values=[1], options=options)
    return raster.GetRasterBand(1).ReadAsArray().astype(bool)


def polygon_mask(polygon, grid: DemGrid, mode: PixelMode) -> np.ndarray:
    """Cells selected by `polygon` over the whole of `grid`.

    all_touched: every cell the polygon touches; centre: cells whose centre is inside;
    fully_inside: centre inside and not crossed by the boundary."""
    if mode is PixelMode.ALL_TOUCHED:
        return rasterize(polygon, grid, all_touched=True)
    centre = rasterize(polygon, grid, all_touched=False)
    if mode is PixelMode.CENTRE:
        return centre
    return centre & ~rasterize(polygon.GetBoundary(), grid, all_touched=True)
