"""Use lines or areas from a vector layer that is already in the project."""
from __future__ import annotations

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .help_texts import PICK_A_LAYER
from ..core.tools import Mode


class LayerSource(QWidget):
    """Layer picker, "selected features only" and the button that turns them into a feature."""

    useRequested = pyqtSignal(object, bool)  # QgsVectorLayer, selected_only

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(self.tr("Layer")))
        self.layer_combo = QgsMapLayerComboBox()
        row.addWidget(self.layer_combo, 1)
        layout.addLayout(row)
        self.selected_only = QCheckBox(self.tr("Selected features only"))
        layout.addWidget(self.selected_only)
        self.use_button = QPushButton(self.tr("Use these features"))
        self._use_tip = self.tr("Every feature becomes one part of a single Terrain Scenarios "
                                "feature; they share the same values.")
        layout.addWidget(self.use_button)
        self.use_button.clicked.connect(self._use)
        self.layer_combo.layerChanged.connect(self._refresh_use_button)
        # the combo fills itself from the project, so watch the model too: a layer added after
        # this widget was built does not always arrive as layerChanged
        model = self.layer_combo.model()
        model.rowsInserted.connect(self._refresh_use_button)
        model.rowsRemoved.connect(self._refresh_use_button)
        self.set_mode(Mode.PATH)

    def set_mode(self, mode: Mode) -> None:
        """Show line layers for paths and polygon layers for areas."""
        self.layer_combo.setFilters(Qgis.LayerFilter.LineLayer if mode is Mode.PATH else Qgis.LayerFilter.PolygonLayer)
        self._refresh_use_button()

    def _refresh_use_button(self, *_args) -> None:
        """A button that does nothing when pressed is worse than a disabled one. It is dead only
        when the project has no layer of the right kind to offer."""
        usable = self.layer_combo.count() > 0
        self.use_button.setEnabled(usable)
        self.use_button.setToolTip(self._use_tip if usable else PICK_A_LAYER)

    def _use(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is not None:
            self.useRequested.emit(layer, self.selected_only.isChecked())
