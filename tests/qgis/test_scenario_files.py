"""The working rasters live beside a saved scenario, in `<scenario>_files/` (spec §8.2 step 3)."""
import os

import numpy as np
from qgis.core import QgsProject

from qgis_helpers import UTM, line_through, read_tif, sample, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import scenario_files_folder
from terrain_sketch.gui.help_texts import FILES_NOT_MOVED, FILES_NOT_RELEASED
from terrain_sketch.qgis_io.raster_io import WorkingFiles


def layer_sources(c):
    project = QgsProject.instance()
    return {project.mapLayer(i).source() for i in (c.layers.working_id, c.layers.change_id)}


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
    assert saved[19, 20] == 11.0                                      # the saved dike is still there
    assert saved[15, 15] == 10.0                                      # and the new pond went to the temp copy
    temp = c.files.folder
    c.close()
    assert not os.path.exists(temp)


def test_opening_a_scenario_keeps_the_rasters_beside_it(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    c.new_scenario()
    assert read_tif(tmp_path / "flood_files" / "working_dem.tif")[0][19, 20] == 11.0
    c.open_scenario(path)
    assert c.files.folder == str(tmp_path / "flood_files")
    working, _ = read_tif(tmp_path / "flood_files" / "working_dem.tif")
    assert working[19, 20] == 11.0


def test_opening_another_scenario_leaves_the_first_scenarios_rasters_as_saved(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    first = str(tmp_path / "first.gpkg")
    c.save_scenario(first)
    c.new_scenario()
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    second = str(tmp_path / "second.gpkg")
    c.save_scenario(second)
    c.open_scenario(first)
    c.open_scenario(second)
    rasters, _ = read_tif(tmp_path / "first_files" / "working_dem.tif")
    assert rasters[19, 20] == 11.0 and rasters[15, 15] == 10.0         # first's dike, and no pond from second
    assert c.files.folder == str(tmp_path / "second_files")


def test_edits_that_are_not_saved_do_not_stay_in_the_scenarios_rasters(tmp_path):
    """The rasters are what a saved QGIS project shows next time: work the user threw away must not."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    c.update_feature(dike.id, amount=4.0)
    assert read_tif(tmp_path / "flood_files" / "working_dem.tif")[0][19, 20] == 14.0   # shown while working
    c.close()                                                          # closed without saving
    assert read_tif(tmp_path / "flood_files" / "working_dem.tif")[0][19, 20] == 11.0


def test_save_as_puts_the_first_scenarios_rasters_back_to_what_it_saved(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "first.gpkg"))
    c.update_feature(dike.id, amount=4.0)
    c.save_scenario(str(tmp_path / "second.gpkg"))
    assert read_tif(tmp_path / "first_files" / "working_dem.tif")[0][19, 20] == 11.0
    assert read_tif(tmp_path / "second_files" / "working_dem.tif")[0][19, 20] == 14.0


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


def test_a_scenario_folder_that_cannot_be_written_falls_back_to_a_temp_folder(tmp_path):
    """Spec §9. Staying in the first scenario's folder would write the second scenario's edits over it."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "first.gpkg"))
    (tmp_path / "second_files").write_text("a file where the folder should go")
    c.save_scenario(str(tmp_path / "second.gpkg"))
    assert not c.files.folder.startswith(str(tmp_path)) and os.path.isdir(c.files.folder)
    c.update_feature(dike.id, amount=4.0)
    assert read_tif(tmp_path / "first_files" / "working_dem.tif")[0][19, 20] == 11.0


def test_new_and_open_change_nothing_when_the_rasters_cannot_leave_the_scenarios_folder(tmp_path, monkeypatch):
    import pytest
    from terrain_sketch.qgis_io.scenario import ScenarioError
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    monkeypatch.setattr(WorkingFiles, "move_to", lambda self, folder: (_ for _ in ()).throw(OSError("no room")))
    c.new_scenario()
    assert len(c.features) == 1 and c.scenario_path == path
    assert heard and heard[-1] == FILES_NOT_RELEASED.format(folder=str(tmp_path / "flood_files"))
    told = len(heard)
    with pytest.raises(ScenarioError, match="could not move"):
        c.open_scenario(path)
    assert len(heard) == told                                          # the panel shows the error: said once
    assert read_tif(tmp_path / "flood_files" / "working_dem.tif")[0][19, 20] == 11.0


def test_moving_the_rasters_over_older_ones_leaves_no_partial_files(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    c.new_scenario()
    c.save_scenario(str(tmp_path / "flood.gpkg"))                    # the same folder again, with nothing in it
    assert sorted(os.listdir(tmp_path / "flood_files")) == ["change.tif", "working_dem.tif"]
    assert read_tif(tmp_path / "flood_files" / "working_dem.tif")[0][19, 20] == 10.0


def test_opening_a_scenario_on_another_dem_leaves_its_rasters_as_saved(tmp_path):
    """The scenario's features replayed on another DEM are not its saved terrain: a QGIS project or a flood
    model reading `flood_files/working_dem.tif` must not get the other DEM's ground."""
    from qgis.core import QgsRasterLayer
    from qgis_helpers import write_dem
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    (tmp_path / "other").mkdir()
    for name, shape in (("same_grid", (40, 40)), ("other_grid", (30, 50))):
        layer = QgsRasterLayer(write_dem(tmp_path / "other" / f"{name}.tif", np.full(shape, 30.0, np.float32)), name)
        QgsProject.instance().addMapLayer(layer)
        c.set_dem(layer)
        c.open_scenario(path)                                         # "Open on this DEM", or no question at all
        assert not c.files.folder.startswith(str(tmp_path)) and len(c.features) == 1
        c.close()                                                     # without saving
        saved, _ = read_tif(tmp_path / "flood_files" / "working_dem.tif")
        assert saved.shape == (40, 40) and saved[19, 20] == 11.0, name


def test_a_session_on_a_scenarios_working_dem_never_writes_over_its_own_dem(tmp_path):
    """A reopened QGIS project shows the Modified DEM layer, which reads `flood_files/working_dem.tif`, and
    nothing stops a user from starting on it. Save as `flood.gpkg` would then move the rasters over that DEM."""
    from qgis.core import QgsRasterLayer
    from terrain_sketch.gui.help_texts import FILES_ARE_THE_DEM
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    c.close()
    dem = str(tmp_path / "flood_files" / "working_dem.tif")
    layer = QgsRasterLayer(dem, "Modified DEM")
    QgsProject.instance().addMapLayer(layer)
    c.set_dem(layer)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    c.save_scenario(str(tmp_path / "flood.gpkg"))
    assert read_tif(dem)[0][19, 20] == 11.0                            # the DEM under the session is unchanged
    assert not c.files.folder.startswith(str(tmp_path))
    assert heard == [FILES_ARE_THE_DEM.format(folder=str(tmp_path / "flood_files"))]


def test_when_neither_the_new_nor_a_temp_folder_can_be_written_the_message_says_where_the_rasters_are(
        tmp_path, monkeypatch):
    from terrain_sketch.gui.help_texts import FILES_KEPT_IN_OLD_FOLDER
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "first.gpkg"))
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    monkeypatch.setattr(WorkingFiles, "move_to", lambda self, folder: (_ for _ in ()).throw(OSError("no room")))
    c.save_scenario(str(tmp_path / "second.gpkg"))
    first = str(tmp_path / "first_files")
    assert c.files.folder == first
    assert heard == [FILES_KEPT_IN_OLD_FOLDER.format(folder=str(tmp_path / "second_files"), old_folder=first)]
    c.update_feature(dike.id, amount=4.0)
    c.close()                                                          # and they are put back, as it says
    assert read_tif(tmp_path / "first_files" / "working_dem.tif")[0][19, 20] == 11.0


def test_a_scenario_that_does_not_name_its_dem_opens_without_taking_qgis_down(tmp_path):
    """Only a hand-edited or third-party file lacks the record, but Open runs in a button's slot."""
    from osgeo import ogr
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "flood.gpkg")
    c.save_scenario(path)
    source = ogr.Open(path, 1)
    source.ExecuteSQL("UPDATE terrain_sketch_meta SET value = NULL WHERE key = 'dem_source'")
    source.Close()
    c.new_scenario()
    c.open_scenario(path)
    assert len(c.features) == 1 and c.scenario_path == path
