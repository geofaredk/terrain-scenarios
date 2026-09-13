"""Use lines or areas from a vector layer that is already in the project."""
from __future__ import annotations

from qgis.core import Qgis
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

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
        self.use_button.setToolTip(self.tr("Every feature becomes one part of a single Terrain Sketch feature; "
                                           "they share the same values."))
        layout.addWidget(self.use_button)
        self.use_button.clicked.connect(self._use)
        self.set_mode(Mode.PATH)

    def set_mode(self, mode: Mode) -> None:
        """Show line layers for paths and polygon layers for areas."""
        self.layer_combo.setFilters(Qgis.LayerFilter.LineLayer if mode is Mode.PATH else Qgis.LayerFilter.PolygonLayer)

    def _use(self) -> None:
        layer = self.layer_combo.currentLayer()
        if layer is not None:
            self.useRequested.emit(layer, self.selected_only.isChecked())
