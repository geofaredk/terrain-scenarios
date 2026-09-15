import os

import numpy as np
import pytest

from qgis_helpers import CELL, X0, Y0, dem_layer, read_tif
from terrain_sketch.core.grid import Window
from terrain_sketch.qgis_io.raster_io import DemError, WorkingFiles, export_dem, read_dem


def test_read_dem_returns_grid_and_info(tmp_path):
    array = np.arange(1200, dtype=np.float32).reshape(30, 40) + 1.0
    array[0, 0] = -9999.0
    grid, info = read_dem(dem_layer(tmp_path, array))
    assert grid.data.shape == (30, 40) and not grid.valid[0, 0] and grid.valid[0, 1]
    assert grid.geotransform == (X0, CELL, 0.0, Y0, 0.0, -CELL)
    assert info.nodata == -9999.0 and info.warnings == () and info.band_count == 1


def test_a_dem_whose_file_disappeared_raises_dem_error(tmp_path):
    layer = dem_layer(tmp_path)
    os.remove(layer.source())
    with pytest.raises(DemError):
        read_dem(layer)


def test_geographic_dem_is_refused(tmp_path):
    layer = dem_layer(tmp_path, crs="EPSG:4326", gt=(9.0, 0.001, 0.0, 55.7, 0.0, -0.001))
    with pytest.raises(DemError, match="latitude"):
        read_dem(layer)


def test_multi_band_dem_uses_band_one_with_a_warning(tmp_path):
    _, info = read_dem(dem_layer(tmp_path, bands=2))
    assert any("band 1" in w for w in info.warnings)


def test_working_files_follow_window_writes(tmp_path):
    grid, info = read_dem(dem_layer(tmp_path))
    files = WorkingFiles(str(tmp_path / "session"), grid, info)
    working = grid.copy()
    working.data[5:7, 8:10] = 12.5
    files.write(Window(5, 8, 2, 2), working)
    values, _ = read_tif(files.working_path)
    change, nodata = read_tif(files.change_path)
    assert values[5, 8] == 12.5 and values[0, 0] == 10.0
    assert change[5, 8] == pytest.approx(2.5) and change[0, 0] == 0.0 and nodata == info.nodata


def test_export_keeps_nodata_and_nudges_clashing_values(tmp_path):
    array = np.full((10, 10), 10.0, np.float32)
    array[0, 0] = -9999.0
    grid, info = read_dem(dem_layer(tmp_path, array))
    working = grid.copy()
    working.data[1, 1] = -9999.0  # a valid cell that happens to equal the nodata value
    out = tmp_path / "export.tif"
    export_dem(str(out), working, info)
    exported, nodata = read_tif(out)
    assert exported.dtype == np.float32 and nodata == -9999.0
    assert exported[0, 0] == -9999.0
    assert exported[1, 1] != -9999.0 and exported[1, 1] == pytest.approx(-9999.0)


def test_change_raster_keeps_valid_cells_when_nodata_is_zero(tmp_path):
    array = np.full((10, 10), 10.0, np.float32)
    array[0, 0] = 0.0
    grid, info = read_dem(dem_layer(tmp_path, array, nodata=0.0))
    files = WorkingFiles(str(tmp_path / "session"), grid, info)
    change, nodata = read_tif(files.change_path)
    assert nodata == 0.0 and change[0, 0] == 0.0  # the real nodata cell stays nodata
    assert (change[1:, 1:] != 0.0).all() and change[5, 5] == pytest.approx(0.0)  # unchanged cells are no holes
    files.write(Window(5, 5, 1, 1), grid.copy())
    change, _ = read_tif(files.change_path)
    assert change[5, 5] != 0.0


def test_a_move_that_fails_leaves_no_folder_it_made(tmp_path, monkeypatch):
    import shutil
    grid, info = read_dem(dem_layer(tmp_path))
    files = WorkingFiles(str(tmp_path / "session"), grid, info)
    monkeypatch.setattr(shutil, "copyfile", lambda *_a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        files.move_to(str(tmp_path / "flood_files"))
    assert not os.path.exists(tmp_path / "flood_files")
    assert files.folder == str(tmp_path / "session")
    (tmp_path / "kept").mkdir()                                          # a folder that was there stays
    with pytest.raises(OSError):
        files.move_to(str(tmp_path / "kept"))
    assert os.path.isdir(tmp_path / "kept")
