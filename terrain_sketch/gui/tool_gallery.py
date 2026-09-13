"""'What do you want to build?' — the tool list, the Line/Area toggle and the 'Where?' methods."""
from __future__ import annotations

from qgis.core import Qgis, QgsApplication, QgsUnitTypes
from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QRadioButton,
                                 QToolButton, QVBoxLayout, QWidget)

from ..core.tools import TOOL_INFO, Mode, Tool
from .help_texts import TOOL_LABELS, TOOL_SUMMARIES
from .layer_source import LayerSource
from .selection import METHOD_ICONS, METHOD_LABELS, METHOD_TIPS, Method

DEFAULT_BRUSH_RADIUS = 5.0


class ToolGallery(QWidget):
    drawRequested = pyqtSignal(object, object, object)  # Tool, Mode, Method
    layerRequested = pyqtSignal(object, object, object, bool)  # Tool, Mode, QgsVectorLayer, selected_only

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(self.tr("What do you want to build?")))
        self.tool_list = QListWidget()
        for tool in Tool:
            item = QListWidgetItem(TOOL_LABELS[tool])
            item.setData(Qt.ItemDataRole.UserRole, tool.value)
            item.setToolTip(TOOL_SUMMARIES[tool])
            self.tool_list.addItem(item)
        layout.addWidget(self.tool_list)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(self.tr("Shape")))
        self.line_mode = QRadioButton(self.tr("Line"))
        self.area_mode = QRadioButton(self.tr("Area"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.line_mode)
        self.mode_group.addButton(self.area_mode)
        mode_row.addWidget(self.line_mode)
        mode_row.addWidget(self.area_mode)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        layout.addWidget(QLabel(self.tr("Where?")))
        method_row = QHBoxLayout()
        self.method_buttons = {method: self._method_button(method) for method in Method}
        for button in self.method_buttons.values():
            method_row.addWidget(button)
        method_row.addStretch(1)
        layout.addLayout(method_row)

        brush_row = QHBoxLayout()
        self.brush_label = QLabel(self.tr("Brush radius"))
        brush_row.addWidget(self.brush_label)
        self.brush_spin = QgsDoubleSpinBox()
        self.brush_spin.setRange(0.1, 1000.0)
        self.brush_spin.setDecimals(1)
        self.brush_spin.setValue(DEFAULT_BRUSH_RADIUS)
        self.brush_spin.setToolTip(self.tr("Radius of the round brush; [ and ] or Ctrl+wheel change it while painting."))
        brush_row.addWidget(self.brush_spin)
        brush_row.addStretch(1)
        layout.addLayout(brush_row)

        self.layer_source = LayerSource()
        self.layer_source.hide()
        layout.addWidget(self.layer_source)

        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self.line_mode.toggled.connect(self._mode_changed)
        self.area_mode.toggled.connect(self._mode_changed)
        self.layer_source.useRequested.connect(self._use_layer)
        self._tool_changed()

    def selected_tool(self) -> Tool | None:
        item = self.tool_list.currentItem()
        return Tool(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def selected_mode(self) -> Mode | None:
        if self.area_mode.isChecked():
            return Mode.AREA
        return Mode.PATH if self.line_mode.isChecked() else None

    def select_tool(self, tool: Tool) -> None:
        for row in range(self.tool_list.count()):
            if self.tool_list.item(row).data(Qt.ItemDataRole.UserRole) == tool.value:
                self.tool_list.setCurrentRow(row)

    def select_mode(self, mode: Mode) -> None:
        (self.area_mode if mode is Mode.AREA else self.line_mode).setChecked(True)

    def brush_radius(self) -> float:
        return self.brush_spin.value()

    def set_brush_radius(self, radius: float) -> None:
        self.brush_spin.setValue(radius)

    def set_radius_units(self, units) -> None:
        """Name the units the brush radius is really in — the canvas's map units, never converted."""
        self.brush_spin.setSuffix(f" {self._unit_label(units)}")

    def _unit_label(self, units) -> str:
        if units == Qgis.DistanceUnit.Meters:
            return self.tr("m")
        if units == Qgis.DistanceUnit.Degrees:
            return self.tr("degrees")
        return QgsUnitTypes.toAbbreviatedString(units) or self.tr("map units")

    def _method_button(self, method: Method) -> QToolButton:
        button = QToolButton()
        button.setIcon(QgsApplication.getThemeIcon(METHOD_ICONS[method]))
        button.setText(METHOD_LABELS[method])
        button.setToolTip(METHOD_TIPS[method])
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.clicked.connect(lambda _checked=False, m=method: self._pick(m))
        return button

    def _tool_changed(self, *_args) -> None:
        tool = self.selected_tool()
        self.summary.setText(TOOL_SUMMARIES[tool] if tool else self.tr("Pick a tool, then choose where to draw it."))
        modes = TOOL_INFO[tool].modes if tool else ()
        self.line_mode.setEnabled(Mode.PATH in modes)
        self.area_mode.setEnabled(Mode.AREA in modes)
        if self.selected_mode() not in modes:
            self.mode_group.setExclusive(False)
            self.line_mode.setChecked(False)
            self.area_mode.setChecked(False)
            self.mode_group.setExclusive(True)
            if modes:
                self.select_mode(modes[0])
        self._mode_changed()

    def _mode_changed(self, *_args) -> None:
        mode = self.selected_mode()
        for method, button in self.method_buttons.items():
            button.setEnabled(mode is not None and (mode is Mode.AREA or method is not Method.BRUSH))
        brush_usable = self.method_buttons[Method.BRUSH].isEnabled()
        self.brush_label.setEnabled(brush_usable)
        self.brush_spin.setEnabled(brush_usable)
        if mode is not None:
            self.layer_source.set_mode(mode)
        else:
            self.layer_source.hide()

    def _pick(self, method: Method) -> None:
        tool, mode = self.selected_tool(), self.selected_mode()
        if tool is None or mode is None:
            return
        self.layer_source.setVisible(method is Method.LAYER)
        if method is not Method.LAYER:
            self.drawRequested.emit(tool, mode, method)

    def _use_layer(self, layer, selected_only: bool) -> None:
        tool, mode = self.selected_tool(), self.selected_mode()
        if tool is not None and mode is not None:
            self.layerRequested.emit(tool, mode, layer, selected_only)
