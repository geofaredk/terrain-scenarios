"""Undo and redo over the feature list (spec §7.4): every kind of change, merging, and the saved state."""
import numpy as np
import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, line_through, square, start_session
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.help_texts import (UNDO_ADD, UNDO_DELETE, UNDO_PROFILE, UNDO_RENAME, UNDO_REORDER,
                                           UNDO_SETTINGS, UNDO_SHAPE, UNDO_TURN_OFF, UNDO_TURN_ON)
from terrain_sketch.gui.profile_dock import ProfileDock


def terrain(c):
    return c.stack.working.data.copy()


def replayed(c):
    """The terrain a fresh engine computes for the controller's current list, from scratch."""
    fresh = FeatureStack(c.stack.original)
    fresh.update(c.features)
    return fresh.working.data


def dike_and_pond(c):
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    return dike, pond


EDITS = {
    "add": lambda c, dike, pond: c.add_drawn(Tool.ADD, Mode.AREA, square(2, 30, 12, 38), UTM),
    "delete": lambda c, dike, pond: c.delete_feature(pond.id),
    "rename": lambda c, dike, pond: c.update_feature(dike.id, name="Sea wall"),
    "toggle": lambda c, dike, pond: c.set_enabled(dike.id, False),
    "reorder": lambda c, dike, pond: c.reorder([pond.id, dike.id]),
    "settings": lambda c, dike, pond: c.update_feature(dike.id, amount=2.5, width=5.0),
    "pixels": lambda c, dike, pond: c.update_feature(pond.id, pixel_mode=PixelMode.ALL_TOUCHED),
    "profile": lambda c, dike, pond: c.update_feature(dike.id, cross_right=((3.0, -0.6),)),
    "shape": lambda c, dike, pond: c.set_geometry(dike.id, line_through(5, 24, 34, 28), UTM),
}


@pytest.mark.parametrize("edit", sorted(EDITS))
def test_every_kind_of_change_undoes_and_redoes_exactly(tmp_path, edit):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    list_before, terrain_before = c.features, terrain(c)
    EDITS[edit](c, dike, pond)
    list_after, terrain_after = c.features, terrain(c)
    assert list_after != list_before

    c.undo_stack.undo()
    assert c.features == list_before
    assert np.array_equal(terrain(c), terrain_before)
    assert np.array_equal(terrain(c), replayed(c))          # the windowed recompute is still exact
    c.undo_stack.redo()
    assert c.features == list_after
    assert np.array_equal(terrain(c), terrain_after)


def test_each_change_says_what_undo_will_do(tmp_path):
    c = start_session(tmp_path)
    texts = []
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    texts.append(c.undo_stack.undoText())
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    for change in (lambda: c.update_feature(dike.id, amount=2.0),
                   lambda: c.update_feature(dike.id, cross_right=((3.0, -0.6),)),
                   lambda: c.set_geometry(dike.id, line_through(5, 24, 34, 28), UTM),
                   lambda: c.set_enabled(pond.id, False),
                   lambda: c.set_enabled(pond.id, True),
                   lambda: c.reorder([pond.id, dike.id]),
                   lambda: c.update_feature(dike.id, name="Sea wall"),
                   lambda: c.delete_feature(pond.id)):
        change()
        texts.append(c.undo_stack.undoText())
    assert texts == [UNDO_ADD.format("Raise path 1"), UNDO_SETTINGS.format("Raise path 1"),
                     UNDO_PROFILE.format("Raise path 1"), UNDO_SHAPE.format("Raise path 1"),
                     UNDO_TURN_OFF.format("Lower flat 1"), UNDO_TURN_ON.format("Lower flat 1"),
                     UNDO_REORDER, UNDO_RENAME.format("Raise path 1"), UNDO_DELETE.format("Lower flat 1")]


def test_the_steps_of_one_setting_merge_into_one_undo(tmp_path):
    """A spin box reports every step; the user thinks of the whole adjustment as one change."""
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    start = c.undo_stack.index()
    for value in (1.5, 2.0, 2.5, 3.0):
        c.update_feature(dike.id, amount=value)
    assert c.undo_stack.index() == start + 1
    c.undo_stack.undo()
    assert c.find(dike.id).amount == 1.0


def test_different_settings_or_features_stay_separate_steps(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    start = c.undo_stack.index()
    c.update_feature(dike.id, amount=2.0)
    c.update_feature(dike.id, width=5.0)          # another setting of the same feature
    c.update_feature(pond.id, width=5.0)          # the same setting of another feature
    c.update_feature(dike.id, width=6.0)          # back to the first: not merged across the pond
    assert c.undo_stack.index() == start + 4


def test_stepping_a_setting_back_to_where_it_was_leaves_no_step(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    start = c.undo_stack.index()
    c.update_feature(dike.id, amount=2.0)
    c.update_feature(dike.id, amount=1.0)
    assert c.undo_stack.index() == start


def test_a_change_that_changes_nothing_records_nothing_and_stays_saved(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "same.gpkg"))
    start = c.undo_stack.index()
    c.update_feature(dike.id, amount=dike.amount, name=dike.name)
    assert c.undo_stack.index() == start and not c.is_dirty


def test_the_scenario_is_unsaved_exactly_when_undo_has_left_the_saved_state(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "clean.gpkg"))
    c.update_feature(dike.id, amount=2.0)
    assert c.is_dirty
    c.undo_stack.undo()
    assert not c.is_dirty                        # back to what is on disk
    c.undo_stack.redo()
    assert c.is_dirty
    c.undo_stack.undo()
    c.undo_stack.undo()                          # before the save point
    assert c.is_dirty


def test_a_setting_changed_after_a_save_does_not_merge_into_the_saved_step(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.update_feature(dike.id, amount=2.0)
    c.save_scenario(str(tmp_path / "saved.gpkg"))
    c.update_feature(dike.id, amount=3.0)
    c.undo_stack.undo()
    assert c.find(dike.id).amount == 2.0 and not c.is_dirty


def test_new_open_and_start_leave_nothing_to_undo(tmp_path):
    c = start_session(tmp_path)
    dike_and_pond(c)
    path = str(tmp_path / "history.gpkg")
    c.save_scenario(path)
    c.update_feature(c.features[0].id, amount=2.0)
    c.open_scenario(path)
    assert not c.undo_stack.canUndo() and not c.is_dirty
    c.add_drawn(Tool.ADD, Mode.AREA, square(2, 30, 12, 38), UTM)
    c.new_scenario()
    assert not c.undo_stack.canUndo() and not c.is_dirty
    c.add_drawn(Tool.ADD, Mode.AREA, square(2, 30, 12, 38), UTM)
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    assert not c.undo_stack.canUndo() and not c.is_dirty


def test_a_change_the_engine_refuses_records_nothing(tmp_path):
    from unittest import mock
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    start = c.undo_stack.index()
    with mock.patch.object(c.stack, "update", side_effect=RuntimeError("refused")):
        c.update_feature(dike.id, amount=4.0)
    assert c.undo_stack.index() == start and c.find(dike.id).amount == 1.0


def test_deleting_every_feature_of_a_saved_scenario_still_asks_before_it_is_dropped(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "emptied.gpkg"))
    c.delete_feature(dike.id)
    c.delete_feature(pond.id)
    asked = []
    c.before_discard = lambda: asked.append(True)
    QgsProject.instance().clear()
    assert asked == [True]


def test_undo_and_redo_announce_that_the_list_was_restored(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.update_feature(dike.id, amount=2.0)
    heard = []
    c.featuresRestored.connect(lambda: heard.append(True))
    c.undo_stack.undo()
    c.undo_stack.redo()
    assert heard == [True, True]


def test_a_long_run_of_undo_and_redo_keeps_the_terrain_exact(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    for name in sorted(set(EDITS) - {"add", "delete"}) + ["add"]:   # reorder needs exactly the two
        EDITS[name](c, dike, pond)
    while c.undo_stack.canUndo():
        c.undo_stack.undo()
        assert np.array_equal(terrain(c), replayed(c))
    assert c.features == ()
    while c.undo_stack.canRedo():
        c.undo_stack.redo()
        assert np.array_equal(terrain(c), replayed(c))


def test_each_drag_in_the_profiles_panel_is_its_own_profile_step(tmp_path):
    """The panel's cross-profile drags also move width, slope and reach, which alone count as
    settings; they must still be one named profile step each, never merged."""
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    start = c.undo_stack.index()
    dock._cross_edited([(0.0, 0.0), (2.0, 0.0), (6.0, -1.0)], True)
    after_first = c.find(dike.id)
    dock._cross_edited([(0.0, 0.0), (2.5, 0.0), (7.0, -1.2)], True)
    assert c.undo_stack.index() == start + 2
    assert c.undo_stack.undoText() == UNDO_PROFILE.format(dike.name)
    c.undo_stack.undo()
    assert c.find(dike.id) == after_first               # one drag back, not both

    dock.show_feature(pond.id)                          # an area drag sends only slope and reach
    dock._cross_edited([(0.0, 0.0), (0.5, 0.0), (4.0, 1.0)], True)
    assert c.undo_stack.undoText() == UNDO_PROFILE.format(pond.name)


def test_the_profile_reset_buttons_are_profile_steps(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.update_feature(dike.id, cross_right=((3.0, -0.6),), long_profile=((0.0, 12.0), (29.0, 13.0)))
    dock = ProfileDock(c)
    dock.show_feature(dike.id)
    start = c.undo_stack.index()
    dock._reset_cross()
    assert c.undo_stack.undoText() == UNDO_PROFILE.format(dike.name)
    dock._reset_long()
    assert c.undo_stack.index() == start + 2 and c.undo_stack.undoText() == UNDO_PROFILE.format(dike.name)


def test_an_undo_the_engine_refuses_leaves_the_scenario_unsaved(tmp_path):
    from unittest import mock
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "saved.gpkg"))
    c.update_feature(dike.id, amount=2.0)
    with mock.patch.object(c.stack, "update", side_effect=MemoryError("no room")):
        c.undo_stack.undo()                             # lands on the saved step, list unchanged
    assert c.find(dike.id).amount == 2.0
    assert c.is_dirty                                   # still the unsaved change on screen


def test_an_emptied_scenario_that_was_never_saved_has_nothing_to_keep(tmp_path):
    c = start_session(tmp_path)
    dike, pond = dike_and_pond(c)
    c.delete_feature(dike.id)
    c.delete_feature(pond.id)
    assert not c.is_dirty and c.undo_stack.canUndo()


def test_a_change_that_changes_nothing_still_refreshes_the_views(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    heard = []
    c.featuresChanged.connect(lambda: heard.append(True))
    c.update_feature(dike.id, amount=dike.amount)
    assert heard == [True]


def test_an_add_the_engine_refuses_returns_nothing_and_leaves_no_work(tmp_path):
    from unittest import mock
    c = start_session(tmp_path)
    with mock.patch.object(c.stack, "update", side_effect=RuntimeError("refused")):
        assert c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM) is None
    assert c.features == () and not c.is_dirty and not c.undo_stack.canUndo()


def test_stepping_a_setting_back_after_a_save_is_clean_again(tmp_path):
    c = start_session(tmp_path)
    dike, _pond = dike_and_pond(c)
    c.save_scenario(str(tmp_path / "saved.gpkg"))
    c.update_feature(dike.id, amount=2.0)
    c.update_feature(dike.id, amount=1.0)
    assert not c.is_dirty
