"""The scenario buttons: New, Open, Save and Save as, and every question asked before work is lost."""
import numpy as np
import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch import classFactory
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import (SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_OTHER_DEM,
                                           SCENARIO_REPLACE, SCENARIO_SAVE_FAILED, UNSAVED_BEFORE_CLOSING,
                                           UNSAVED_CHANGES)
from terrain_sketch.gui.main_dock import MainDock
from terrain_sketch.qgis_io.scenario import dem_meta, load, save


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def test_saving_then_opening_restores_the_features(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    path = str(tmp_path / "panel.gpkg")
    dock.ask_save_path = lambda: path
    dock.save_scenario_action.trigger()
    assert not c.is_dirty and c.scenario_path == path

    dock.confirm_save = lambda text, can_cancel=True: False           # discard, we already saved
    dock.new_scenario_action.trigger()
    assert c.features == () and c.scenario_path is None

    dock.ask_open_path = lambda: path
    dock.open_scenario_action.trigger()
    assert [f.name for f in c.features] == ["Raise path 1", "Lower flat 1"]
    assert not c.is_dirty


def test_a_second_save_does_not_ask_again(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    path = str(tmp_path / "once.gpkg")
    dock.ask_save_path = lambda: asked.append(1) or path
    dock.save_scenario_action.trigger()
    c.update_feature(c.features[0].id, amount=2.0)
    dock.save_scenario_action.trigger()
    assert len(asked) == 1                            # the path is remembered
    assert not c.is_dirty                              # and the second click actually wrote
    assert load(path)[0][0].amount == 2.0


def test_editing_marks_the_scenario_unsaved_and_saving_clears_it(tmp_path):
    _iface, c, dock = panel(tmp_path)
    assert not c.is_dirty
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.is_dirty
    dock.ask_save_path = lambda: str(tmp_path / "dirty.gpkg")
    dock.save_scenario_action.trigger()
    assert not c.is_dirty
    c.update_feature(dike.id, amount=3.0)
    assert c.is_dirty


def test_discarding_unsaved_work_is_confirmed_first(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or None      # cancel
    dock.new_scenario_action.trigger()
    assert asked == [UNSAVED_CHANGES]
    assert len(c.features) == 1                        # cancelling kept the work


def test_choosing_save_in_the_prompt_writes_before_discarding(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "prompted.gpkg")
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: path
    dock.new_scenario_action.trigger()
    assert c.features == ()
    dock.ask_open_path = lambda: path
    dock.open_scenario_action.trigger()
    assert len(c.features) == 1                        # the work was saved, not lost


def test_backing_out_of_the_save_dialog_keeps_the_work(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: ""                    # the user cancelled the file dialog
    dock.new_scenario_action.trigger()
    assert len(c.features) == 1
    # Leave the dock able to end the session cleanly: a real user who keeps choosing Save with a
    # file dialog that can never succeed would keep being asked (that is the point of I1), but a
    # stub stuck on "always Save, never a path" must not turn this test's own teardown `clear()`
    # into an infinite retry.
    dock.confirm_save = lambda text, can_cancel=True: False


def scenario_from_another_dem(tmp_path, array) -> str:
    """Save a one-feature scenario built on its own DEM of shape `array`, and return the path."""
    room = tmp_path / f"other{array.shape[0]}"
    room.mkdir()
    other = start_session(room, array)
    other.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(room / "other.gpkg")
    save(path, other.features, dem_meta(other.info, other.stack.original))
    return path


def messages(iface) -> list[str]:
    return [call[0][1] for call in iface.messageBar().pushMessage.call_args_list]


def test_a_scenario_from_a_different_dem_is_only_opened_once_the_user_agrees(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 10.0, np.float32))
    (tmp_path / "other30" / "dem.tif").unlink()                  # its own DEM is gone, so it is this one or nothing
    _iface, c, dock = panel(tmp_path)
    mine = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.confirm_save = lambda text, can_cancel=True: False       # carry on without saving
    dock.ask_open_path = lambda: path
    questions = []
    dock.confirm = lambda text: questions.append(text) or False   # No: pick another DEM first
    dock.open_scenario_action.trigger()

    assert questions == [SCENARIO_DEM_DIFFERS.format("size in pixels, extent")]
    assert [f.id for f in c.features] == [mine.id]                # nothing was replaced
    assert c.is_dirty                                             # and it is still unsaved

    dock.confirm = lambda text: True                              # Yes: open it anyway
    dock.open_scenario_action.trigger()
    assert len(c.features) == 1 and c.features[0].tool is Tool.RAISE_PATH
    assert c.scenario_path == path


def test_a_scenario_from_the_same_dem_opens_without_asking(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((40, 40), 10.0, np.float32))
    iface, c, dock = panel(tmp_path)
    dock.ask_open_path = lambda: path
    questions = []
    dock.confirm = lambda text: questions.append(text) or True
    dock.open_scenario_action.trigger()

    assert questions == [] and len(c.features) == 1
    assert SCENARIO_OPENED.format(path) in messages(iface)


def test_the_scenario_actions_wait_for_a_session(tmp_path):
    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    dock = MainDock(iface, c)
    assert not any(action.isEnabled() for action in dock.scenario_actions)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    assert all(action.isEnabled() for action in dock.scenario_actions)


def test_save_as_always_asks_and_leaves_the_first_file_as_it_was(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    first, second = str(tmp_path / "first.gpkg"), str(tmp_path / "second.gpkg")
    dock.ask_save_path = lambda: first
    dock.save_scenario_action.trigger()
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)

    dock.ask_save_path = lambda: second
    dock.save_as_scenario_action.trigger()
    assert c.scenario_path == second
    assert len(load(first)[0]) == 1 and len(load(second)[0]) == 2


def test_closing_the_project_offers_to_save_unsaved_work(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "rescued.gpkg")
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append((text, can_cancel)) or True
    dock.ask_save_path = lambda: path
    QgsProject.instance().clear()

    assert asked == [(UNSAVED_BEFORE_CLOSING, False)]   # a closing project cannot be cancelled
    assert len(load(path)[0]) == 1


def test_a_failed_save_before_closing_asks_again_until_it_succeeds(tmp_path):
    """Save chosen but the file dialog is then cancelled (or the save fails) must not drop the
    session silently — the question repeats until a save succeeds or the user chooses Discard."""
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "retried.gpkg")
    paths = iter(["", path])                          # first Save picks nothing, second succeeds
    dock.ask_save_path = lambda: next(paths)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append((text, can_cancel)) or True
    QgsProject.instance().clear()

    assert asked == [(UNSAVED_BEFORE_CLOSING, False), (UNSAVED_BEFORE_CLOSING, False)]
    assert len(load(path)[0]) == 1


def _recording_confirm(recorded, controller, answers):
    """A `confirm_save` stub: records `(text, can_cancel, feature ids still present)` on every
    call — so a test can check the session was not dropped before the recorded answer said to —
    then answers from `answers` in order."""
    iterator = iter(answers)

    def stub(text, can_cancel=True):
        recorded.append((text, can_cancel, tuple(f.id for f in controller.features)))
        return next(iterator)

    return stub


def test_a_repeatedly_failing_save_before_the_project_closes_asks_until_an_explicit_discard(tmp_path):
    """Round 3 ruling: `before_discard` cannot cancel anything — `SketchController._drop_session`
    calls it and then always drops the session, whatever it did. Round 2's fix stopped the
    question after one unexpected save failure, which left the session to be dropped a moment
    later with no explicit Discard from the user — silent data loss. The question must instead
    repeat, carrying the failure, until the user explicitly answers Discard: here, Save (fails),
    Save (fails again), Discard."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.ask_save_path = lambda: str(tmp_path / "boom.gpkg")

    def boom(_path):
        raise RuntimeError("boom")

    c.save_scenario = boom
    recorded = []
    dock.confirm_save = _recording_confirm(recorded, c, [True, True, False])   # Save, Save, Discard

    QgsProject.instance().clear()

    assert len(recorded) == 3                                     # asked exactly 3 times
    for text, can_cancel, feature_ids in recorded:
        assert can_cancel is False                                # this path never offers Cancel
        assert feature_ids == (dike.id,)                          # not dropped before this answer
    assert SCENARIO_SAVE_FAILED in recorded[1][0]                  # the 2nd question carries the failure
    assert SCENARIO_SAVE_FAILED in recorded[2][0]                  # …and so does the 3rd
    assert not c.has_dem and c.features == ()                      # gone only now, after Discard


def test_a_repeatedly_failing_save_before_the_dem_is_removed_asks_until_an_explicit_discard(tmp_path):
    """The DEM-removed path, same shape as the test above."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dem_id = c.dem_layer_id
    dock.ask_save_path = lambda: str(tmp_path / "boom.gpkg")

    def boom(_path):
        raise RuntimeError("boom")

    c.save_scenario = boom
    recorded = []
    dock.confirm_save = _recording_confirm(recorded, c, [True, True, False])

    QgsProject.instance().removeMapLayer(dem_id)

    assert len(recorded) == 3
    for text, can_cancel, feature_ids in recorded:
        assert can_cancel is False
        assert feature_ids == (dike.id,)
    assert SCENARIO_SAVE_FAILED in recorded[1][0]
    assert SCENARIO_SAVE_FAILED in recorded[2][0]
    assert not c.has_dem and c.features == ()


def test_a_repeatedly_failing_save_before_the_plugin_unloads_asks_until_an_explicit_discard(tmp_path):
    """The plugin-unload path, same shape as the two tests above."""
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    dock, c = plugin.dock, plugin.controller
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.ask_save_path = lambda: str(tmp_path / "boom.gpkg")

    def boom(_path):
        raise RuntimeError("boom")

    c.save_scenario = boom
    recorded = []
    dock.confirm_save = _recording_confirm(recorded, c, [True, True, False])

    plugin.unload()

    assert len(recorded) == 3
    for text, can_cancel, feature_ids in recorded:
        assert can_cancel is False
        assert feature_ids == (dike.id,)
    assert SCENARIO_SAVE_FAILED in recorded[1][0]
    assert SCENARIO_SAVE_FAILED in recorded[2][0]
    assert not c.has_dem and c.features == ()


def test_a_cancelled_save_dialog_on_a_cancellable_path_keeps_the_work(tmp_path):
    """Unlike the three non-cancellable paths above, `_keep_unsaved_work`-driven paths (Start on
    another DEM, Change… then Start, New scenario, Open scenario) can genuinely back out.
    Choosing Save and then cancelling the file dialog (`ask_save_path` returning "") is "wanted to
    save but did not" — `_keep_unsaved_work` already turns that into backing out rather than
    discarding, and still does after the round-3 fix: the "no path chosen" case still returns
    plain `False` from `_save_scenario`, unchanged."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.confirm_save = lambda text, can_cancel=True: True   # wants to save
    dock.ask_save_path = lambda: ""                          # then cancels the file dialog

    second = dem_layer(tmp_path, name="second")
    dock.dem_combo.setLayer(second)
    dock.start_button.click()                                # backs out: the file dialog was cancelled

    assert c.has_dem and [f.id for f in c.features] == [dike.id]
    dock.confirm_save = lambda text, can_cancel=True: False   # let the fixture's own teardown clear() finish
    QgsProject.instance().clear()


def test_new_scenario_backs_out_when_a_save_it_wanted_fails(tmp_path):
    """Cancellable path (spec's own list): `_new_scenario` asks first through
    `_keep_unsaved_work`, which can genuinely back out — unlike the three non-cancellable paths
    above, nothing forces this session to be dropped regardless of what the question does."""
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: str(tmp_path / "boom.gpkg")

    def boom(_path):
        raise RuntimeError("boom")

    c.save_scenario = boom
    dock.new_scenario_action.trigger()

    assert c.has_dem and [f.id for f in c.features] == [dike.id]
    dock.confirm_save = lambda text, can_cancel=True: False   # let the fixture's own teardown clear() finish
    QgsProject.instance().clear()


def test_a_save_failure_after_the_file_is_written_is_treated_as_saved(tmp_path):
    """IMPORTANT: `controller.save_scenario` writes the file, marks it (`_mark_scenario`, which
    sets `controller.scenario_path`), and only then does further bookkeeping
    (`undo_stack.setClean`, `_place_files`) that can still fail unexpectedly — after the file is
    already safely on disk. Telling the user it "could not be saved" would be wrong, and looping
    to ask again pointless (a resave would hit the very same bug): `_save_scenario` must recognise
    the file was actually written and treat it as done."""
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "written.gpkg")
    dock.ask_save_path = lambda: path

    def boom():
        raise RuntimeError("boom")

    c._place_files = boom   # after the write and _mark_scenario, before this bug

    assert dock._save_scenario() is True
    assert c.scenario_path == path   # the write really did happen
    warnings = [call.args[1] for call in dock.iface.messageBar().pushMessage.call_args_list]
    assert any(path in w and "saved" in w.lower() for w in warnings)


def test_removing_the_dem_offers_to_save_before_the_session_ends(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "dem-gone.gpkg")
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: path
    QgsProject.instance().removeMapLayer(c.dem_layer_id)
    assert not c.has_dem
    assert len(load(path)[0]) == 1


def test_unloading_the_plugin_offers_to_save_unsaved_work(tmp_path):
    iface = fake_iface()
    plugin = classFactory(iface)
    plugin.initGui()
    plugin.action.setChecked(True)
    dock, c = plugin.dock, plugin.controller
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "unloaded.gpkg")
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or True
    dock.ask_save_path = lambda: path
    plugin.unload()

    assert asked == [UNSAVED_BEFORE_CLOSING]
    assert len(load(path)[0]) == 1


def test_starting_on_another_dem_asks_about_unsaved_work_once(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or False   # discard
    (tmp_path / "next").mkdir()
    dock.dem_combo.setLayer(dem_layer(tmp_path / "next", name="next"))
    dock.start_button.click()

    assert asked == [UNSAVED_CHANGES]              # not a second time as the old session closes
    assert c.has_dem and c.features == ()


def test_cancelling_the_question_keeps_the_session(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    old_dem = c.dem_layer_id
    dock.confirm_save = lambda text, can_cancel=True: None
    (tmp_path / "next").mkdir()
    dock.dem_combo.setLayer(dem_layer(tmp_path / "next", name="next"))
    dock.start_button.click()
    assert c.dem_layer_id == old_dem and len(c.features) == 1


def test_a_start_that_fails_leaves_the_work_unsaved_and_still_protected(tmp_path):
    iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.confirm_save = lambda text, can_cancel=True: False                  # discard…
    (tmp_path / "geo").mkdir()
    dock.dem_combo.setLayer(dem_layer(tmp_path / "geo", name="geo", crs="EPSG:4326"))
    dock.start_button.click()                                               # …but Start is refused
    assert len(c.features) == 1 and c.is_dirty

    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or False
    QgsProject.instance().clear()
    assert asked == [UNSAVED_BEFORE_CLOSING]        # the refused Start did not switch protection off


def test_opening_a_scenario_ends_an_edit_in_progress(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "edit.gpkg")
    c.save_scenario(path)
    dock.feature_view.select_id(dike.id)
    dock.edit_button.setChecked(True)
    assert dock.edit_tool is not None
    dock.ask_open_path = lambda: path
    dock.open_scenario_action.trigger()
    assert dock.edit_tool is None                  # its feature is gone; editing on would rewrite another


def test_the_save_and_open_dialogs_start_beside_the_current_scenario(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "current.gpkg")
    c.save_scenario(path)

    save_dirs, open_dirs = [], []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: save_dirs.append(a[2]) or ("", "")))
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: open_dirs.append(a[2]) or ("", "")))

    dock._save_dialog()
    dock._open_dialog()
    assert save_dirs == [str(tmp_path)]
    assert open_dirs == [str(tmp_path)]


def test_the_save_dialog_starts_at_the_project_home_without_a_scenario_yet(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, _c, dock = panel(tmp_path)
    save_dirs = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: save_dirs.append(a[2]) or ("", "")))

    dock._save_dialog()
    assert save_dirs == [QgsProject.instance().homePath()]


def test_every_scenario_action_shows_an_icon_and_says_what_it_does(tmp_path):
    """getThemeIcon hands back a null icon for a name it does not know, and an icon-only button or
    action then renders as blank space — so check the real actions, not a list of names."""
    _iface, _c, dock = panel(tmp_path)
    for item in (*dock.scenario_actions, dock.export_button, dock.new_button, dock.scenario_button):
        assert not item.icon().isNull(), item.text()
    for action in dock.scenario_actions:
        assert action.toolTip().startswith(action.text() + "\n"), action.text()
    icons = [item.icon().cacheKey() for item in (dock.save_as_scenario_action, dock.export_button)]
    assert icons[0] != icons[1]                    # Save as… and Export DEM… no longer look the same


def test_a_replace_check_that_raises_is_shown_as_a_warning_not_crashed(tmp_path):
    """A RuntimeError out of the replace check (e.g. "database is locked") must reach the user
    as a message-bar warning, exactly like any other save failure — not escape the Save button's
    Qt slot, which would abort QGIS."""
    from unittest import mock

    from terrain_sketch.qgis_io import scenario

    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "locked.gpkg")
    c.save_scenario(path)
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.ask_save_path = lambda: path

    with mock.patch.object(scenario, "_is_scenario_file", side_effect=RuntimeError("database is locked")):
        dock.save_scenario_action.trigger()

    assert any("database is locked" in text for text in messages(_iface))
    assert c.is_dirty


@pytest.mark.parametrize("typed, replaced", [("flood", True), ("flood.gpkg", False)])
def test_a_name_typed_without_gpkg_asks_before_replacing_that_scenario(tmp_path, monkeypatch, typed, replaced):
    """The file dialog checks for overwriting before `.gpkg` is added, so an existing flood.gpkg
    would be replaced silently when the user types just `flood`. A name typed with the extension
    has already been through the dialog's own question."""
    from qgis.PyQt.QtWidgets import QFileDialog
    _iface, _c, dock = panel(tmp_path)
    (tmp_path / "flood.gpkg").write_bytes(b"an earlier scenario")
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / typed), "")))
    questions = []
    dock.confirm = lambda text: questions.append(text) or False     # No: keep the old file

    assert dock._save_dialog() == ("" if replaced else str(tmp_path / "flood.gpkg"))
    assert questions == ([SCENARIO_REPLACE.format("flood.gpkg")] if replaced else [])

    dock.confirm = lambda text: True
    assert dock._save_dialog() == str(tmp_path / "flood.gpkg")


def test_a_scenario_whose_dem_is_still_there_offers_to_start_on_that_dem(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))
    other_dem = str(tmp_path / "other30" / "dem.tif")
    project = QgsProject.instance()
    project.removeMapLayers([l.id() for l in project.mapLayers().values() if l.source() == other_dem])
    _iface, c, dock = panel(tmp_path)
    mine = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or False     # discard my work
    dock.ask_open_path = lambda: path
    choices = []
    dock.choose_dem = lambda text: choices.append(text) or None                       # cancel
    dock.open_scenario_action.trigger()
    assert choices == [SCENARIO_OTHER_DEM.format(dem="dem.tif", differences="size in pixels, extent")]
    assert [f.id for f in c.features] == [mine.id] and c.info.path != other_dem

    dock.choose_dem = lambda text: "scenario"
    dock.open_scenario_action.trigger()
    assert c.has_dem and c.info.path == other_dem and dock.dem_combo.currentLayer().source() == other_dem
    assert len(c.features) == 1 and c.features[0].tool is Tool.RAISE_PATH and c.scenario_path == path
    assert c.scenario_differences(path) == []
    assert len(asked) == 2                          # asked about my unsaved work each time, never again by Start
    rasters = [l for l in project.mapLayers().values() if l.source() == other_dem]
    assert len(rasters) == 1 and project.mapLayersByName("dem")    # added once; the user's own DEM stays


def test_starting_on_the_scenarios_dem_reuses_it_when_it_is_already_in_the_project(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))   # its DEM is in the project
    other_dem = str(tmp_path / "other30" / "dem.tif")
    already = next(l for l in QgsProject.instance().mapLayers().values() if l.source() == other_dem)
    _iface, c, dock = panel(tmp_path)
    dock.ask_open_path = lambda: path
    dock.choose_dem = lambda text: "scenario"
    dock.open_scenario_action.trigger()
    assert c.dem_layer_id == already.id()
    assert len([l for l in QgsProject.instance().mapLayers().values() if l.source() == other_dem]) == 1


def test_opening_on_this_dem_instead_keeps_the_session(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))
    _iface, c, dock = panel(tmp_path)
    first = c.info.path
    dock.ask_open_path = lambda: path
    dock.choose_dem = lambda text: "current"
    dock.open_scenario_action.trigger()
    assert c.info.path == first and len(c.features) == 1 and c.scenario_path == path


def test_the_dem_question_has_both_choices_and_cancel(tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox
    _iface, _c, dock = panel(tmp_path)
    for label, expected in (("Start on its DEM", "scenario"), ("Open on this DEM", "current"), ("Cancel", None)):
        seen = []

        def click(box, label=label):
            seen.append(sorted(b.text() for b in box.buttons()))
            next(b for b in box.buttons() if b.text() == label).click()
            return 0
        monkeypatch.setattr(QMessageBox, "exec", click)
        assert dock._dem_choice_dialog("which DEM?") == expected
        assert seen == [sorted(["Start on its DEM", "Open on this DEM", "Cancel"])]


def test_a_dem_that_cannot_be_started_on_is_not_left_in_the_project(tmp_path):
    from unittest import mock
    from terrain_sketch.qgis_io.raster_io import DemError
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))
    other_dem = str(tmp_path / "other30" / "dem.tif")
    project = QgsProject.instance()
    project.removeMapLayers([l.id() for l in project.mapLayers().values() if l.source() == other_dem])
    _iface, c, dock = panel(tmp_path)
    first = c.info.path
    dock.ask_open_path = lambda: path
    dock.choose_dem = lambda text: "scenario"
    with mock.patch.object(c, "set_dem", side_effect=DemError("refused")):
        dock.open_scenario_action.trigger()
    assert not [l for l in project.mapLayers().values() if l.source() == other_dem]
    assert c.info.path == first and c.scenario_path is None


def test_a_scenario_that_fails_on_its_own_dem_does_not_claim_the_old_features_are_still_there(tmp_path):
    """Starting on its DEM already closed the session the features belonged to."""
    from unittest import mock
    from terrain_sketch.gui.help_texts import SCENARIO_NOT_APPLIED, SCENARIO_NOT_APPLIED_ON_ITS_DEM
    from terrain_sketch.qgis_io.scenario import ScenarioError
    path = scenario_from_another_dem(tmp_path, np.full((30, 30), 12.0, np.float32))
    iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.confirm_save = lambda text, can_cancel=True: False                           # discard my work
    dock.ask_open_path = lambda: path
    dock.choose_dem = lambda text: "scenario"
    with mock.patch.object(c, "open_scenario", side_effect=ScenarioError(SCENARIO_NOT_APPLIED)):
        dock.open_scenario_action.trigger()
    assert c.info.path == str(tmp_path / "other30" / "dem.tif") and c.features == ()
    assert messages(iface)[-1] == SCENARIO_NOT_APPLIED_ON_ITS_DEM
    assert "unchanged" not in SCENARIO_NOT_APPLIED_ON_ITS_DEM
