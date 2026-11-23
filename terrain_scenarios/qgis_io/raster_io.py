"""Reading the DEM into the engine; writing the working/change GeoTIFFs and the export."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

import numpy as np
from osgeo import gdal
from qgis.core import QgsRasterLayer

from ..core.grid import DemGrid, Window

gdal.UseExceptions()

WARN_CELLS = 50_000_000
WORKING_NAME, CHANGE_NAME = "working_dem.tif", "change.tif"
DEFAULT_NODATA = -9999.0
_CREATE_OPTIONS = ["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"]


class DemError(Exception):
    """The chosen layer cannot be used as the DEM; the message is shown to the user."""


class GeographicDemError(DemError):
    """A DEM in degrees. A DemError to every existing caller, but the panel checks for it so it
    can offer to reproject rather than only complaining."""


@dataclass(frozen=True)
class DemInfo:
    path: str
    crs_wkt: str
    nodata: float  # nodata value written to the working, change and exported files
    band_count: int
    warnings: tuple = ()
    integer: bool = False  # the source stores whole numbers; the working files and export are float32


def read_dem(layer) -> tuple[DemGrid, DemInfo]:
    """Band 1 of a file-based raster layer in a projected CRS, as a DemGrid."""
    if not isinstance(layer, QgsRasterLayer) or not layer.isValid():
        raise DemError("Pick a valid raster layer as the DEM.")
    if layer.providerType() != "gdal":
        raise DemError("Only file-based rasters (for example GeoTIFF) can be used as the DEM.")
    if layer.crs().isGeographic():
        raise GeographicDemError("The DEM uses latitude/longitude. Slopes and widths need metres: reproject it to a "
                       "projected CRS first (Raster ▸ Projections ▸ Warp).")
    try:
        ds = gdal.Open(layer.source())
        band = ds.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        array = band.ReadAsArray()
    except (RuntimeError, MemoryError) as error:
        raise DemError(f"The DEM could not be read: {error}") from error
    try:
        grid = DemGrid.from_array(array, ds.GetGeoTransform(), nodata)
    except ValueError as error:
        raise DemError(f"This raster cannot be used as the DEM: {error}.") from error
    warnings = []
    if ds.RasterCount > 1:
        warnings.append(f"The DEM has {ds.RasterCount} bands; band 1 is used.")
    cells = grid.rows * grid.cols
    if cells > WARN_CELLS:
        warnings.append(f"The DEM has {cells / 1e6:.0f} million cells and needs about "
                        f"{cells * 12 / 1e9:.1f} GB of memory; consider clipping it to your site.")
    info = DemInfo(layer.source(), layer.crs().toWkt(),
                   DEFAULT_NODATA if nodata is None else float(nodata), ds.RasterCount, tuple(warnings),
                   integer=bool(np.issubdtype(array.dtype, np.integer)))
    return grid, info


class WorkingFiles:
    """The working DEM and the change raster (working − original) of a session, on disk."""

    def __init__(self, folder: str, original: DemGrid, info: DemInfo):
        os.makedirs(folder, exist_ok=True)
        self.folder = folder
        self.working_path = os.path.join(folder, WORKING_NAME)
        self.change_path = os.path.join(folder, CHANGE_NAME)
        self._original = original
        self._info = info
        _write_tif(self.working_path, _for_output(original.data, original.valid, info.nodata), original, info)
        _write_tif(self.change_path, _for_output(np.zeros(original.data.shape), original.valid, info.nodata),
                   original, info)

    def move_to(self, folder: str) -> None:
        """Copy both files into `folder` and write there from now on. The old files are left for the caller
        to remove. Each copy is made under a temporary name and only then put in place, so a copy that fails
        half way — a full disk — neither changes the files in use nor leaves a truncated raster in `folder`,
        nor the folder itself when this made it and it is empty."""
        existed = os.path.isdir(folder)
        os.makedirs(folder, exist_ok=True)
        moves = [(source, os.path.join(folder, name)) for source, name in
                 ((self.working_path, WORKING_NAME), (self.change_path, CHANGE_NAME))]
        try:
            for source, target in moves:
                shutil.copyfile(source, target + ".copying")
        except BaseException:
            for _source, target in moves:
                if os.path.exists(target + ".copying"):
                    os.remove(target + ".copying")
            if not existed and not os.listdir(folder):
                os.rmdir(folder)
            raise
        for _source, target in moves:
            os.replace(target + ".copying", target)
        self.folder, self.working_path, self.change_path = folder, moves[0][1], moves[1][1]

    def write(self, window: Window, working: DemGrid) -> None:
        """Write one window of the working DEM and its change into both files."""
        rows, cols = window.slices
        valid = self._original.valid[rows, cols]
        values = working.data[rows, cols]
        change = values.astype(np.float64) - self._original.data[rows, cols]
        for path, block in ((self.working_path, _for_output(values, valid, self._info.nodata)),
                            (self.change_path, _for_output(change, valid, self._info.nodata))):
            ds = gdal.Open(path, gdal.GA_Update)
            ds.GetRasterBand(1).WriteArray(block, window.col0, window.row0)
            ds.FlushCache()
            ds = None


def export_dem(path: str, working: DemGrid, info: DemInfo) -> None:
    """Float32 GeoTIFF of the modified DEM on the original grid, CRS and nodata value."""
    _write_tif(path, _for_output(working.data, working.valid, info.nodata), working, info,
               extra_options=["PREDICTOR=3"])


def _for_output(values: np.ndarray, valid: np.ndarray, nodata: float) -> np.ndarray:
    """Float32 copy with nodata cells set to `nodata`; valid cells that happen to equal
    `nodata` are nudged by one float step so they do not turn into holes."""
    out = values.astype(np.float32, copy=True)
    marker = np.float32(nodata)
    clash = valid & (out == marker)
    out[clash] = np.nextafter(marker, np.float32(np.inf))
    out[~valid] = marker
    return out


def _write_tif(path: str, array: np.ndarray, grid: DemGrid, info: DemInfo, extra_options=()) -> None:
    ds = gdal.GetDriverByName("GTiff").Create(path, grid.cols, grid.rows, 1, gdal.GDT_Float32,
                                              _CREATE_OPTIONS + list(extra_options))
    ds.SetGeoTransform(grid.geotransform)
    ds.SetProjection(info.crs_wkt)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(info.nodata)
    band.WriteArray(array)
    ds.FlushCache()
    ds = None
