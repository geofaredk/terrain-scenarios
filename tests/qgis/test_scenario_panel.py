"""The scenario buttons: New, Open, Save and Save as, and every question asked before work is lost."""
import numpy as np
import pytest
from qgis.core import QgsProject

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch import classFactory
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import (SCENARIO_DEM_DIFFERS, SCENARIO_OPENED, SCENARIO_REPLACE,
                                           UNSAVED_BEFORE_CLOSING, UNSAVED_CHANGES)
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
    dock.save_scenario_button.click()
    assert not c.is_dirty and c.scenario_path == path

    dock.confirm_save = lambda text, can_cancel=True: False           # discard, we already saved
    dock.new_scenario_button.click()
    assert c.features == () and c.scenario_path is None

    dock.ask_open_path = lambda: path
    dock.open_scenario_button.click()
    assert [f.name for f in c.features] == ["Raise path 1", "Lower flat 1"]
    assert not c.is_dirty


def test_a_second_save_does_not_ask_again(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    path = str(tmp_path / "once.gpkg")
    dock.ask_save_path = lambda: asked.append(1) or path
    dock.save_scenario_button.click()
    c.update_feature(c.features[0].id, amount=2.0)
    dock.save_scenario_button.click()
    assert len(asked) == 1                            # the path is remembered
    assert not c.is_dirty                              # and the second click actually wrote
    assert load(path)[0][0].amount == 2.0


def test_editing_marks_the_scenario_unsaved_and_saving_clears_it(tmp_path):
    _iface, c, dock = panel(tmp_path)
    assert not c.is_dirty
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    assert c.is_dirty
    dock.ask_save_path = lambda: str(tmp_path / "dirty.gpkg")
    dock.save_scenario_button.click()
    assert not c.is_dirty
    c.update_feature(dike.id, amount=3.0)
    assert c.is_dirty


def test_discarding_unsaved_work_is_confirmed_first(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    asked = []
    dock.confirm_save = lambda text, can_cancel=True: asked.append(text) or None      # cancel
    dock.new_scenario_button.click()
    assert asked == [UNSAVED_CHANGES]
    assert len(c.features) == 1                        # cancelling kept the work


def test_choosing_save_in_the_prompt_writes_before_discarding(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    path = str(tmp_path / "prompted.gpkg")
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: path
    dock.new_scenario_button.click()
    assert c.features == ()
    dock.ask_open_path = lambda: path
    dock.open_scenario_button.click()
    assert len(c.features) == 1                        # the work was saved, not lost


def test_backing_out_of_the_save_dialog_keeps_the_work(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.confirm_save = lambda text, can_cancel=True: True
    dock.ask_save_path = lambda: ""                    # the user cancelled the file dialog
    dock.new_scenario_button.click()
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
    _iface, c, dock = panel(tmp_path)
    mine = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    dock.confirm_save = lambda text, can_cancel=True: False       # carry on without saving
    dock.ask_open_path = lambda: path
    questions = []
    dock.confirm = lambda text: questions.append(text) or False   # No: pick another DEM first
    dock.open_scenario_button.click()

    assert questions == [SCENARIO_DEM_DIFFERS.format("size in pixels, extent")]
    assert [f.id for f in c.features] == [mine.id]                # nothing was replaced
    assert c.is_dirty                                             # and it is still unsaved

    dock.confirm = lambda text: True                              # Yes: open it anyway
    dock.open_scenario_button.click()
    assert len(c.features) == 1 and c.features[0].tool is Tool.RAISE_PATH
    assert c.scenario_path == path


def test_a_scenario_from_the_same_dem_opens_without_asking(tmp_path):
    path = scenario_from_another_dem(tmp_path, np.full((40, 40), 10.0, np.float32))
    iface, c, dock = panel(tmp_path)
    dock.ask_open_path = lambda: path
    questions = []
    dock.confirm = lambda text: questions.append(text) or True
    dock.open_scenario_button.click()

    assert questions == [] and len(c.features) == 1
    assert SCENARIO_OPENED.format(path) in messages(iface)


def test_the_scenario_buttons_wait_for_a_session(tmp_path):
    iface = fake_iface()
    c = SketchController(QgsProject.instance())
    dock = MainDock(iface, c)
    assert not any(button.isEnabled() for button in dock.scenario_buttons)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    assert all(button.isEnabled() for button in dock.scenario_buttons)


def test_save_as_always_asks_and_leaves_the_first_file_as_it_was(tmp_path):
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    first, second = str(tmp_path / "first.gpkg"), str(tmp_path / "second.gpkg")
    dock.ask_save_path = lambda: first
    dock.save_scenario_button.click()
    c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)

    dock.ask_save_path = lambda: second
    dock.save_as_scenario_button.click()
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
    dock.open_scenario_button.click()
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


def test_every_scenario_button_shows_an_icon_and_says_what_it_does(tmp_path):
    """getThemeIcon hands back a null icon for a name it does not know, and an icon-only button
    then renders as blank space — so check the real buttons, not a list of names."""
    _iface, _c, dock = panel(tmp_path)
    for button in (*dock.scenario_buttons, dock.export_button):
        assert not button.icon().isNull(), button.text()
    for button in dock.scenario_buttons:
        assert button.toolTip().startswith(button.text() + "\n"), button.text()
    icons = [button.icon().cacheKey() for button in (dock.save_as_scenario_button, dock.export_button)]
    assert icons[0] != icons[1]                    # Save as… and Export DEM… no longer look the same


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
