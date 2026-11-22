"""Scenarios in a session: opening, saving, and never losing work that was not saved."""
import time
from unittest import mock

import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, sample, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import SCENARIO_NOT_APPLIED
from terrain_sketch.qgis_io.scenario import ScenarioError, dem_meta, load, load_meta, save

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
    c.update_feature(pond.id, pixel_mode=PixelMode.ALL_TOUCHED, slopes_inside=True, enabled=False)
    return c.features


def test_editing_marks_the_scenario_unsaved_and_saving_or_starting_afresh_clears_it(tmp_path):
    c = start_session(tmp_path)
    assert not c.is_dirty and c.scenario_path is None
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.is_dirty
    path = str(tmp_path / "work.gpkg")
    c.save_scenario(path)
    assert not c.is_dirty and c.scenario_path == path
    c.update_feature(dike.id, name="Sea wall")      # a rename is saved too, so it counts
    assert c.is_dirty
    c.new_scenario()
    assert c.features == () and not c.is_dirty and c.scenario_path is None


def test_scenario_actions_need_a_session():
    c = SketchController(QgsProject.instance())
    for action in (c.save_scenario, c.open_scenario, c.scenario_differences):
        with pytest.raises(ScenarioError):
            action("anything.gpkg")


def test_a_reloaded_scenario_rebuilds_the_same_terrain(tmp_path):
    """The point of saving: reopen on a fresh session and the DEM comes out the same."""
    c = start_session(tmp_path)
    two_features(c)
    path = str(tmp_path / "rebuild.gpkg")
    save(path, c.features, dem_meta(c.info, c.stack.original))
    on_the_dike = sample(c.layers.working, 20, 20)
    in_the_pond = sample(c.layers.working, 18, 18)
    c.close()

    again = tmp_path / "again"
    again.mkdir()
    fresh = start_session(again)
    assert sample(fresh.layers.working, 20, 20) != pytest.approx(on_the_dike)   # untouched DEM first
    fresh.open_scenario(path)
    assert sample(fresh.layers.working, 20, 20) == pytest.approx(on_the_dike)
    assert sample(fresh.layers.working, 18, 18) == pytest.approx(in_the_pond)
    assert not fresh.is_dirty                  # what is on screen is exactly what is in the file
    assert fresh.scenario_path == path


def test_saving_again_keeps_the_date_the_scenario_was_created(tmp_path):
    c = start_session(tmp_path)
    two_features(c)
    path = str(tmp_path / "dated.gpkg")
    c.save_scenario(path)
    first = load_meta(path)
    time.sleep(1.1)                                                  # timestamps are to the second
    c.update_feature(c.features[0].id, amount=2.2)
    c.save_scenario(path)
    second = load_meta(path)
    assert second.created == first.created
    assert second.modified > first.modified


def test_saving_to_the_same_file_by_another_spelling_keeps_the_created_date(tmp_path):
    c = start_session(tmp_path)
    two_features(c)
    (tmp_path / "elsewhere").mkdir()
    c.save_scenario(str(tmp_path / "dated.gpkg"))
    first = load_meta(str(tmp_path / "dated.gpkg"))
    time.sleep(1.1)                                                  # timestamps are to the second
    c.update_feature(c.features[0].id, amount=2.2)
    c.save_scenario(str(tmp_path / "elsewhere" / ".." / "dated.gpkg"))
    assert load_meta(str(tmp_path / "dated.gpkg")).created == first.created


def test_a_scenario_that_cannot_be_applied_changes_nothing(tmp_path):
    """`theirs.gpkg` is someone else's scenario, never opened by this session before — if
    `_scenario_path` were wrongly retargeted to it, the next Save would write over a file this
    session never touched. Saving the current work to `mine.gpkg` first, and building `theirs`
    from a separate feature list rather than through this controller, is what lets the test
    catch that: with both saved to the same file (as the previous version of this test did),
    `scenario_path` already equals it before opening, so a retarget to the same value is
    invisible."""
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    mine = str(tmp_path / "mine.gpkg")
    c.save_scenario(mine)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other = start_session(elsewhere)
    other.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    theirs = str(tmp_path / "theirs.gpkg")
    save(theirs, other.features, dem_meta(other.info, other.stack.original))

    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    before = c.features

    with mock.patch.object(c.stack, "update", side_effect=RuntimeError("engine refused")):
        with pytest.raises(ScenarioError, match=SCENARIO_NOT_APPLIED):
            c.open_scenario(theirs)
    assert c.features == before and c.find(pond.id) is not None
    assert c.is_dirty                               # the unsaved pond is still unsaved
    assert c.scenario_path == mine                  # not retargeted to the file that failed to open


def test_starting_on_another_dem_forgets_the_scenario_file(tmp_path):
    """Otherwise the next Save writes the new, empty session over the scenario just left."""
    c = start_session(tmp_path)
    two_features(c)
    path = str(tmp_path / "left-behind.gpkg")
    c.save_scenario(path)
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    assert c.scenario_path is None and not c.is_dirty
    assert len(load(path)[0]) == 2


def test_a_dem_on_a_crs_without_an_epsg_code_can_be_saved_and_reopened(tmp_path):
    c = SketchController(QgsProject.instance())
    c.set_dem(dem_layer(tmp_path, crs=LOCAL_GRID))
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), c.dem_crs)
    path = str(tmp_path / "local.gpkg")
    c.save_scenario(path)                          # raised "Unsupported SRS" from a Qt slot before
    assert c.scenario_differences(path) == []
    c.open_scenario(path)
    assert len(c.features) == 1


def test_a_session_dropped_with_unsaved_changes_asks_first_and_survives_a_failing_hook(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    c.before_discard = lambda: asked.append(len(c.features)) or 1 / 0
    QgsProject.instance().clear()                  # raises inside a Qt signal if unguarded
    assert asked == [1]                            # asked while the features still existed
    assert not c.has_dem


def test_a_session_without_changes_is_dropped_without_asking(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.save_scenario(str(tmp_path / "clean.gpkg"))
    asked = []
    c.before_discard = lambda: asked.append(True)  # recorded, not pytest.fail: that would escape a Qt slot
    QgsProject.instance().clear()
    assert not c.has_dem and asked == []


def _group_name(c) -> str:
    return c.layers.group.name()


def test_the_group_is_called_scenario_before_any_file(tmp_path):
    c = start_session(tmp_path)
    assert _group_name(c) == "Scenario"


def test_the_group_takes_the_name_of_the_scenario_opened(tmp_path):
    c = start_session(tmp_path)
    two_features(c)
    path = str(tmp_path / "flood defence.gpkg")
    c.save_scenario(path)
    c.new_scenario()
    assert _group_name(c) == "Scenario"
    c.open_scenario(path)
    assert _group_name(c) == "flood defence"


def test_the_group_takes_the_name_a_scenario_is_saved_as(tmp_path):
    c = start_session(tmp_path)
    two_features(c)
    c.save_scenario(str(tmp_path / "north.gpkg"))
    assert _group_name(c) == "north"
    c.save_scenario(str(tmp_path / "south.gpkg"))
    assert _group_name(c) == "south"


def test_a_scenario_that_fails_to_open_keeps_the_group_name(tmp_path):
    c = start_session(tmp_path)
    two_features(c)
    c.save_scenario(str(tmp_path / "kept.gpkg"))
    broken = tmp_path / "broken.gpkg"
    broken.write_text("not a geopackage")
    with pytest.raises(ScenarioError):
        c.open_scenario(str(broken))
    assert _group_name(c) == "kept"
