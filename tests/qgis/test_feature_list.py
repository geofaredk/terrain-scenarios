from qgis.core import QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import QModelIndex, Qt

from qgis_helpers import UTM, line_through, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.feature_list import ID_ROLE, FeatureListModel, FeatureListView


def test_feature_list_edits_go_through_the_controller(tmp_path):
    c = start_session(tmp_path)
    a, b, d = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20, 30))
    model = FeatureListModel(c)
    assert model.rowCount() == 3 and model.data(model.index(0)) == a.name
    model.setData(model.index(1), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert not c.feature(b.id).enabled
    model.setData(model.index(2), "Barrier", Qt.ItemDataRole.EditRole)
    assert c.feature(d.id).name == "Barrier"
    model.dropMimeData(model.mimeData([model.index(0)]), Qt.DropAction.MoveAction, 3, 0, QModelIndex())
    assert [f.id for f in c.features] == [b.id, d.id, a.id]
    assert [model.data(model.index(r), ID_ROLE) for r in range(3)] == [b.id, d.id, a.id]


def test_flagged_features_show_a_warning(tmp_path):
    c = start_session(tmp_path)
    far = QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(10, 10)])
    c.add_drawn(Tool.ADD, Mode.PATH, far, UTM)
    model = FeatureListModel(c)
    assert "outside the DEM" in model.data(model.index(0), Qt.ItemDataRole.ToolTipRole)
    assert model.data(model.index(0), Qt.ItemDataRole.DecorationRole) is not None


def test_selection_survives_edits_and_list_changes(tmp_path):
    c = start_session(tmp_path)
    a, b = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20))
    view = FeatureListView(FeatureListModel(c))
    view.select_id(b.id)
    c.update_feature(b.id, amount=2.0)
    assert view.selected_id() == b.id
    c.delete_feature(a.id)
    assert view.selected_id() == b.id
