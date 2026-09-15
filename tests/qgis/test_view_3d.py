"""The 3D view (spec §8.5): the modified DEM as the project's terrain, a new 3D view, and the
terrain the user had put back afterwards."""
import sys
from unittest import mock

from qgis.core import QgsFlatTerrainProvider, QgsProject, QgsRasterDemTerrainProvider
from qgis.PyQt.QtGui import QAction

from qgis_helpers import UTM, dem_layer, fake_iface, line_through, panel, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.controller import SketchController
from terrain_sketch.gui.help_texts import VIEW_3D_NO_LAYER, VIEW_3D_NOT_OPENED
from terrain_sketch.gui.main_dock import MainDock


def terrain():
    return QgsProject.instance().elevationProperties().terrainProvider()


def a_flat_terrain_at(offset: float) -> None:
    flat = QgsFlatTerrainProvider()
    flat.setOffset(offset)
    QgsProject.instance().elevationProperties().setTerrainProvider(flat)


def messages(iface) -> list[str]:
    return [call[0][1] for call in iface.messageBar().pushMessage.call_args_list]


def test_the_modified_dem_becomes_the_terrain_at_true_scale(tmp_path):
    c = start_session(tmp_path)
    assert c.show_in_3d()
    provider = terrain()
    assert isinstance(provider, QgsRasterDemTerrainProvider)
    assert provider.layer().id() == c.layers.working_id and provider.scale() == 1.0


def test_ending_the_session_puts_the_previous_terrain_back(tmp_path):
    a_flat_terrain_at(5.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    c.show_in_3d()                                 # twice: still the user's terrain that comes back
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 5.0


def test_removing_the_dem_puts_the_previous_terrain_back(tmp_path):
    a_flat_terrain_at(7.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    QgsProject.instance().removeMapLayer(c.dem_layer_id)
    assert not c.has_dem
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 7.0


def test_a_terrain_the_user_chose_afterwards_is_left_alone(tmp_path):
    c = start_session(tmp_path)
    c.show_in_3d()
    a_flat_terrain_at(9.0)                         # the user picked their own terrain meanwhile
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 9.0


def test_a_terrain_the_user_chose_between_two_presses_is_the_one_put_back(tmp_path):
    a_flat_terrain_at(5.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    a_flat_terrain_at(9.0)                         # the user picked their own terrain meanwhile
    c.show_in_3d()                                 # and then pressed 3D view again
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 9.0


def test_removing_the_modified_dem_layer_puts_the_previous_terrain_back_at_once(tmp_path):
    """The terrain would point at a layer that is gone; the session carries on without it."""
    a_flat_terrain_at(5.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    QgsProject.instance().removeMapLayer(c.layers.working_id)
    assert c.has_dem
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 5.0
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 5.0


def test_removing_the_dem_and_the_modified_dem_together_puts_the_previous_terrain_back(tmp_path):
    """close() runs from layersRemoved, when both layers are already gone and the terrain's layer
    reads as None rather than as the Modified DEM."""
    a_flat_terrain_at(6.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    QgsProject.instance().removeMapLayers([c.dem_layer_id, c.layers.working_id])
    assert not c.has_dem
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 6.0


def test_a_terrain_left_on_a_removed_layer_is_put_back_when_the_session_ends(tmp_path):
    """The Modified DEM went while the controller was not listening (its layer reads None)."""
    a_flat_terrain_at(8.0)
    c = start_session(tmp_path)
    c.show_in_3d()
    QgsProject.instance().layersRemoved.disconnect(c._on_layers_removed)
    try:
        QgsProject.instance().removeMapLayer(c.layers.working_id)
    finally:
        QgsProject.instance().layersRemoved.connect(c._on_layers_removed)
    assert terrain().layer() is None
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 8.0


def test_without_the_modified_dem_layer_there_is_nothing_to_show(tmp_path):
    a_flat_terrain_at(3.0)
    c = start_session(tmp_path)
    heard = []
    c.message.connect(lambda _level, text: heard.append(text))
    QgsProject.instance().removeMapLayer(c.layers.working_id)
    assert c.has_dem                               # removing a result layer keeps the session
    assert not c.show_in_3d()
    assert heard[-1] == VIEW_3D_NO_LAYER
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 3.0


def test_the_button_opens_a_3d_view_through_the_interface(tmp_path):
    iface, c, dock = panel(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    dock.view_3d_button.click()
    iface.createNewMapCanvas3D.assert_called_once()
    assert isinstance(terrain(), QgsRasterDemTerrainProvider)
    assert VIEW_3D_NOT_OPENED not in messages(iface)


def test_the_3d_types_are_loaded_before_the_interface_hands_back_a_3d_view(tmp_path, monkeypatch):
    """The interface returns a Qgs3DMapCanvas, a type from qgis._3d. Without that module loaded,
    converting the result to Python dereferences a null type and QGIS crashes — no except catches it."""
    monkeypatch.delitem(sys.modules, "qgis._3d", raising=False)
    iface, _c, dock = panel(tmp_path)
    loaded = []
    iface.createNewMapCanvas3D.side_effect = lambda *_args: loaded.append("qgis._3d" in sys.modules)
    dock.view_3d_button.click()
    assert loaded == [True]


def test_without_the_3d_types_the_interface_is_not_asked_for_a_3d_view(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "qgis._3d", None)          # importing it fails
    iface, _c, dock = panel(tmp_path)
    triggered = []
    action = QAction("New 3D Map View", iface.mainWindow())
    action.setObjectName("mActionNew3DMapCanvas")
    action.triggered.connect(lambda: triggered.append(True))
    dock.view_3d_button.click()
    iface.createNewMapCanvas3D.assert_not_called()
    assert triggered == [True] and VIEW_3D_NOT_OPENED not in messages(iface)


def test_without_the_interface_call_qgis_own_menu_action_is_used(tmp_path):
    iface, _c, dock = panel(tmp_path)
    iface.createNewMapCanvas3D.return_value = None
    triggered = []
    action = QAction("New 3D Map View", iface.mainWindow())
    action.setObjectName("mActionNew3DMapCanvas")
    action.triggered.connect(lambda: triggered.append(True))
    dock.view_3d_button.click()
    assert triggered == [True] and VIEW_3D_NOT_OPENED not in messages(iface)


def test_when_no_3d_view_can_be_opened_the_user_is_told_how(tmp_path):
    iface, _c, dock = panel(tmp_path)
    iface.createNewMapCanvas3D.side_effect = RuntimeError("QGIS built without 3D")
    dock.view_3d_button.click()                    # a slot: the error must not escape
    assert VIEW_3D_NOT_OPENED in messages(iface)
    assert isinstance(terrain(), QgsRasterDemTerrainProvider)   # the terrain is still set for later


def test_an_unexpected_error_opening_the_3d_view_becomes_the_message(tmp_path):
    iface, c, dock = panel(tmp_path)
    c.show_in_3d = mock.Mock(side_effect=RuntimeError("anything at all"))
    dock.view_3d_button.click()                    # a slot: the error must not escape
    assert VIEW_3D_NOT_OPENED in messages(iface)


def test_the_3d_button_waits_for_a_session():
    iface = fake_iface()
    dock = MainDock(iface, SketchController(QgsProject.instance()))
    assert not dock.view_3d_button.isEnabled()
    assert not dock.view_3d_button.icon().isNull()     # getThemeIcon gives a blank for an unknown name


def test_the_button_says_the_3d_terrain_is_temporary_even_in_a_saved_project():
    """The Modified DEM's files go when the session ends, so a project saved meanwhile must not be
    expected to keep that terrain."""
    dock = MainDock(fake_iface(), SketchController(QgsProject.instance()))
    tip = dock.view_3d_button.toolTip()
    assert "temporary" in tip and "save" in tip


def test_a_closed_project_does_not_hand_its_terrain_to_the_next_one(tmp_path):
    """Clearing the project drops the session without close(); the terrain remembered from that
    project must go with it, or the next session would put it into a different project."""
    a_flat_terrain_at(2.0)
    c = SketchController(QgsProject.instance())
    c.set_dem(dem_layer(tmp_path))
    c.show_in_3d()
    QgsProject.instance().clear()                  # a new, empty project
    assert c._terrain_before is None               # nothing is left over for a later session to apply
    a_flat_terrain_at(4.0)                         # the terrain of the new project
    (tmp_path / "next").mkdir()
    c.set_dem(dem_layer(tmp_path / "next", name="next"))
    c.show_in_3d()
    c.close()
    assert isinstance(terrain(), QgsFlatTerrainProvider) and terrain().offset() == 4.0
