"""The feature list: on/off checkbox, editable name and warning icon; drag rows to reorder."""
from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import QAbstractListModel, QItemSelectionModel, QMimeData, QModelIndex, Qt
from qgis.PyQt.QtWidgets import QAbstractItemView, QListView

from .help_texts import FLAG_TEXTS, TOOL_LABELS

ID_ROLE = Qt.ItemDataRole.UserRole
MIME_TYPE = "application/x-terrain-sketch-feature-ids"


class FeatureListModel(QAbstractListModel):
    """Rows mirror the controller's feature list; every edit goes through the controller."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._ids: list[str] = []
        controller.featuresChanged.connect(self._sync)
        self._sync()

    def _sync(self) -> None:
        ids = [f.id for f in self.controller.features]
        if ids == self._ids:
            if ids:
                self.dataChanged.emit(self.index(0), self.index(len(ids) - 1))
            return
        self.beginResetModel()
        self._ids = ids
        self.endResetModel()

    def row_of(self, fid: str) -> int:
        return self._ids.index(fid) if fid in self._ids else -1

    def rowCount(self, parent=QModelIndex()):  # noqa: N802 — Qt override
        return 0 if parent.isValid() else len(self._ids)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        features = {f.id: f for f in self.controller.features}
        feature = features.get(self._ids[index.row()])
        if feature is None:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return feature.name
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if feature.enabled else Qt.CheckState.Unchecked
        if role == ID_ROLE:
            return feature.id
        flags = self.controller.stats(feature.id).flags
        if role == Qt.ItemDataRole.DecorationRole and flags:
            return QgsApplication.getThemeIcon("/mIconWarning.svg")
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join([TOOL_LABELS[feature.tool]] + [FLAG_TEXTS[flag] for flag in flags])
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802 — Qt override
        if not index.isValid():
            return False
        fid = self._ids[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole:
            self.controller.set_enabled(fid, Qt.CheckState(value) == Qt.CheckState.Checked)
            return True
        if role == Qt.ItemDataRole.EditRole and str(value).strip():
            self.controller.update_feature(fid, name=str(value).strip())
            return True
        return False

    def supportedDropActions(self):  # noqa: N802 — Qt override
        return Qt.DropAction.MoveAction

    def mimeTypes(self):  # noqa: N802 — Qt override
        return [MIME_TYPE]

    def mimeData(self, indexes):  # noqa: N802 — Qt override
        data = QMimeData()
        data.setData(MIME_TYPE, "\n".join(self._ids[i.row()] for i in indexes).encode())
        return data

    def dropMimeData(self, data, action, row, column, parent):  # noqa: N802 — Qt override
        if action != Qt.DropAction.MoveAction or not data.hasFormat(MIME_TYPE):
            return False
        moving = bytes(data.data(MIME_TYPE)).decode().split("\n")
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._ids)
        before = [i for i in self._ids[:row] if i not in moving]
        after = [i for i in self._ids[row:] if i not in moving]
        self.controller.reorder(before + moving + after)
        return False  # the model already reordered itself; the view must not remove the dragged rows


class FeatureListView(QListView):
    """List view with drag-to-reorder that keeps the selected feature across model resets."""

    def __init__(self, model: FeatureListModel, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._remembered = None
        model.modelAboutToBeReset.connect(self._remember)
        model.modelReset.connect(self._restore)

    def selected_id(self) -> str | None:
        indexes = self.selectionModel().selectedIndexes()
        return indexes[0].data(ID_ROLE) if indexes else None

    def select_id(self, fid: str | None) -> None:
        row = self.model().row_of(fid) if fid else -1
        if row < 0:
            self.clearSelection()
            return
        self.selectionModel().setCurrentIndex(self.model().index(row),
                                              QItemSelectionModel.SelectionFlag.ClearAndSelect)

    def _remember(self) -> None:
        self._remembered = self.selected_id()

    def _restore(self) -> None:
        self.select_id(self._remembered)
