"""The feature list's context menu (spec §7.2): Rename, Duplicate, Zoom to, Delete."""
import numpy as np
from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QAbstractItemView

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, square, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import COPY_NAME, UNDO_DUPLICATE
from terrain_sketch.gui.main_dock import PAGE_PROPERTIES, MainDock


def panel(tmp_path):
    iface = fake_iface()
    controller = SketchController(QgsProject.instance())
    dock = MainDock(iface, controller)
    dock.dem_combo.setLayer(dem_layer(tmp_path))
    dock.start_button.click()
    return iface, controller, dock


def menu_action(dock, fid, text):
    menu = dock.feature_menu(dock.model.index(dock.model.row_of(fid)))
    return next(action for action in menu.actions() if action.text() == text)


def test_the_menu_offers_rename_duplicate_zoom_and_delete(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    menu = dock.feature_menu(dock.model.index(dock.model.row_of(dike.id)))
    assert [a.text() for a in menu.actions() if not a.isSeparator()] == ["Rename", "Duplicate", "Zoom to feature", "Delete"]
    assert dock.feature_menu(dock.model.index(5)) is None            # off the rows


def test_a_duplicate_copies_everything_turned_off_right_after_the_original(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    c.update_feature(dike.id, amount=2.2, width=5.0, cross_right=((3.0, -0.6),))
    dike = c.find(dike.id)
    before = c.stack.working.data.copy()

    copy = c.duplicate_feature(dike.id)
    assert [f.id for f in c.features] == [dike.id, copy.id, pond.id]
    assert copy.id != dike.id and copy.name == COPY_NAME.format(dike.name)
    for field in ("tool", "mode", "geometry_wkb", "amount", "width", "cross_right", "pixel_mode"):
        assert getattr(copy, field) == getattr(dike, field), field
    assert not copy.enabled
    assert np.array_equal(c.stack.working.data, before)          # the map does not change until it is ticked on
    c.set_enabled(copy.id, True)
    assert not np.array_equal(c.stack.working.data, before)      # which is why: on, it raises the dike again
    c.undo_stack.undo()
    assert c.undo_stack.undoText() == UNDO_DUPLICATE.format(dike.name)
    c.undo_stack.undo()
    assert [f.id for f in c.features] == [dike.id, pond.id]


def test_duplicating_twice_keeps_names_unique(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    first, second = c.duplicate_feature(dike.id), c.duplicate_feature(dike.id)
    assert len({dike.name, first.name, second.name}) == 3


def test_duplicating_a_feature_that_has_gone_does_nothing(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.delete_feature(dike.id)
    assert c.duplicate_feature(dike.id) is None and c.features == ()


def test_duplicate_from_the_menu_selects_the_copy(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    menu_action(dock, dike.id, "Duplicate").trigger()
    assert len(c.features) == 2
    assert dock.feature_view.selected_id() == c.features[1].id


def test_rename_from_the_menu_opens_the_name_for_editing(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.show()
    menu_action(dock, dike.id, "Rename").trigger()
    assert dock.feature_view.state() == QAbstractItemView.State.EditingState


def test_the_properties_title_follows_a_rename_in_the_list(tmp_path):
    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.feature_view.select_id(dike.id)
    assert dock.pages.currentIndex() == PAGE_PROPERTIES
    dock.model.setData(dock.model.index(dock.model.row_of(dike.id)), "Sea wall")
    assert dock.properties.title.text().startswith("Sea wall")


def test_rename_after_the_list_changed_under_the_open_menu_does_not_take_qgis_down(tmp_path):
    """The menu runs its own event loop, so the list can change before Rename is picked. A row
    index taken when the menu was built then points past the end of the list, or at another feature."""
    _iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 8, 25, 16), UTM)
    dock.show()
    rename = menu_action(dock, pond.id, "Rename")
    c.delete_feature(pond.id)                      # e.g. a layer signal while the menu is open
    rename.trigger()                               # the stale row used to abort QGIS
    assert dock.feature_view.state() != QAbstractItemView.State.EditingState
