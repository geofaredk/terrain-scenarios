"""'What do you want to build?' — the tool list and the 'Where?' buttons (illustrated in Plan 5)."""
from __future__ import annotations

from qgis.core import QgsApplication
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout, QWidget

from ..core.tools import TOOL_INFO, Mode, Tool
from .help_texts import TOOL_LABELS, TOOL_SUMMARIES


class ToolGallery(QWidget):
    drawRequested = pyqtSignal(object, object)  # Tool, Mode

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
        layout.addWidget(QLabel(self.tr("Where?")))
        row = QHBoxLayout()
        self.line_button = self._where_button("/mActionCaptureLine.svg", self.tr("Draw line"), Mode.PATH)
        self.area_button = self._where_button("/mActionCapturePolygon.svg", self.tr("Draw area"), Mode.AREA)
        row.addWidget(self.line_button)
        row.addWidget(self.area_button)
        row.addStretch(1)
        layout.addLayout(row)
        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self._tool_changed()

    def selected_tool(self) -> Tool | None:
        item = self.tool_list.currentItem()
        return Tool(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def select_tool(self, tool: Tool) -> None:
        for row in range(self.tool_list.count()):
            if self.tool_list.item(row).data(Qt.ItemDataRole.UserRole) == tool.value:
                self.tool_list.setCurrentRow(row)

    def _where_button(self, icon: str, text: str, mode: Mode) -> QToolButton:
        button = QToolButton()
        button.setIcon(QgsApplication.getThemeIcon(icon))
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        button.clicked.connect(lambda _checked=False, m=mode: self._draw(m))
        return button

    def _tool_changed(self, *_args) -> None:
        tool = self.selected_tool()
        self.summary.setText(TOOL_SUMMARIES[tool] if tool else self.tr("Pick a tool, then choose where to draw it."))
        modes = TOOL_INFO[tool].modes if tool else ()
        self.line_button.setEnabled(Mode.PATH in modes)
        self.area_button.setEnabled(Mode.AREA in modes)

    def _draw(self, mode: Mode) -> None:
        tool = self.selected_tool()
        if tool is not None:
            self.drawRequested.emit(tool, mode)
