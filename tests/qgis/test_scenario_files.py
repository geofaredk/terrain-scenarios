"""The working rasters live beside a saved scenario, in `<scenario>_files/` (spec §8.2 step 3)."""
import os

import numpy as np
from qgis.core import QgsProject

from qgis_helpers import UTM, line_through, read_tif, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import scenario_files_folder
from terrain_sketch.gui.help_texts import FILES_NOT_MOVED


def layer_sources(c):
    project = QgsProject.instance()
    return {project.mapLayer(i).source() for i in (c.layers.working_id, c.layers.change_id, c.layers.hillshade_id)}


def test_saving_moves_the_working_rasters_beside_the_scenario_and_keeps_writing_there(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    temp = c.files.folder
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    folder = str(tmp_path / "flood_files")
    assert scenario_files_folder(path) == folder and c.files.folder == folder
    assert layer_sources(c) == {os.path.join(folder, "working_dem.tif"), os.path.join(folder, "change.tif")}
    assert not os.path.exists(temp)                                  # the temp copy is gone
    assert sample(c.layers.working, 20, 20) == 11.0                 # the layers still show the sketch
    c.update_feature(dike.id, amount=2.0)
    working, _nodata = read_tif(os.path.join(folder, "working_dem.tif"))
    assert working[19, 20] == 12.0                                   # edits are written where the layers read


def test_a_scenarios_files_stay_when_the_session_ends(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    c.close()
    assert os.path.isfile(tmp_path / "flood_files" / "working_dem.tif")   # a saved QGIS project still finds them


def test_save_as_moves_the_rasters_and_later_edits_leave_the_first_scenarios_alone(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "first.gpkg"))
    c.save_scenario(str(tmp_path / "second.gpkg"))
    assert c.files.folder == str(tmp_path / "second_files")
    c.update_feature(dike.id, amount=3.0)
    first, _ = read_tif(tmp_path / "first_files" / "working_dem.tif")
    second, _ = read_tif(tmp_path / "second_files" / "working_dem.tif")
    assert first[19, 20] == 11.0 and second[19, 20] == 13.0


def test_a_new_scenario_takes_the_rasters_back_to_a_temp_folder(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    c.new_scenario()
    assert not c.files.folder.startswith(str(tmp_path)) and os.path.isdir(c.files.folder)
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    saved, _ = read_tif(tmp_path / "flood_files" / "working_dem.tif")
    assert saved[15, 15] == 10.0                                      # the new pond went to the temp copy
    temp = c.files.folder
    c.close()
    assert not os.path.exists(temp)


def test_opening_a_scenario_keeps_the_rasters_beside_it(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    c.new_scenario()
    c.open_scenario(path)
    assert c.files.folder == str(tmp_path / "flood_files")
    working, _ = read_tif(tmp_path / "flood_files" / "working_dem.tif")
    assert working[19, 20] == 11.0


def test_a_folder_that_cannot_be_written_leaves_the_rasters_where_they_were(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    (tmp_path / "flood_files").write_text("a file where the folder should go")
    temp = c.files.folder
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    assert os.path.isfile(tmp_path / "flood.gpkg") and not c.is_dirty    # the save itself happened
    assert c.files.folder == temp and os.path.isdir(temp)
    assert len(heard) == 1 and heard[0].startswith(FILES_NOT_MOVED.split("{folder}")[0])
    assert layer_sources(c) == {os.path.join(temp, "working_dem.tif"), os.path.join(temp, "change.tif")}


def test_a_3d_terrain_on_the_modified_dem_follows_the_move(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.show_in_3d()
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    provider = QgsProject.instance().elevationProperties().terrainProvider()
    assert provider.layer().id() == c.layers.working_id
    assert provider.layer().source() == str(tmp_path / "flood_files" / "working_dem.tif")
