"""The 'New feature' page: the drawing hint while one is running, then three headed sections —
Feature (a grid of button tiles and an Info box describing the picked tool), Shape (Line or Area) and
Selection Tool (the three ways to mark it, the running one kept highlighted)."""
from __future__ import annotations

import traceback

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.gui import QgsPanelWidget
from qgis.PyQt.QtCore import QEvent, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import (QButtonGroup, QFrame, QGridLayout, QGroupBox, QLabel, QListView, QListWidget,
                                 QListWidgetItem, QPushButton, QSizePolicy, QStyle, QStyledItemDelegate,
                                 QStyleOptionButton, QVBoxLayout)

from ..core.tools import TOOL_INFO, Mode, Tool
from . import illustrations
from .controller import LOG_TAG
from .help_texts import TOOL_LABELS, TOOL_SUMMARIES, tool_tooltip
from .layer_source import LayerSource
from .page_layout import apply_page_margins
from .selection import METHOD_ICONS, METHOD_LABELS, METHOD_TIPS, Method

TILE_ICON_SIZE = QSize(96, 48)
TILE_GRID_SIZE = QSize(116, 92)   # the smallest cell a tile gets; cells widen to fill the row
BUTTON_GAP = 4          # the small gap between the buttons of a row, and between tiles
BUTTON_HEIGHT_SCALE = 1.5   # Shape and Selection Tool buttons: half again the style's own button height
SHAPE_ICONS = {Mode.PATH: "/mIconLineLayer.svg", Mode.AREA: "/mIconPolygonLayer.svg"}


class _ButtonTileDelegate(QStyledItemDelegate):
    """Paints each tool tile as the style's own push button — icon above, text below — pressed
    while it is the selected tool, so the tiles read as the same kind of button as the Shape and
    Selection Tool rows. Each button keeps half a gap clear on every side of its cell, which makes
    a full gap between neighbours."""

    def paint(self, painter, option, index):  # noqa: D102 — Qt override
        # Guarded: a Qt virtual override, reached from the view's paint event.
        try:
            widget = option.widget
            style = widget.style()
            button = QStyleOptionButton()
            button.rect = option.rect.adjusted(BUTTON_GAP // 2, BUTTON_GAP // 2, -BUTTON_GAP // 2, -BUTTON_GAP // 2)
            button.palette = option.palette
            button.state = QStyle.StateFlag.State_Enabled
            if option.state & QStyle.StateFlag.State_Selected:
                button.state |= QStyle.StateFlag.State_On | QStyle.StateFlag.State_Sunken
            else:
                button.state |= QStyle.StateFlag.State_Off | QStyle.StateFlag.State_Raised
            if option.state & QStyle.StateFlag.State_MouseOver:
                button.state |= QStyle.StateFlag.State_MouseOver
            style.drawControl(QStyle.ControlElement.CE_PushButtonBevel, button, painter, widget)

            inner = button.rect.adjusted(4, 6, -4, -4)
            icon_rect = inner.adjusted(0, 0, 0, -(inner.height() - TILE_ICON_SIZE.height()))
            index.data(Qt.ItemDataRole.DecorationRole).paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)
            text_rect = inner.adjusted(0, TILE_ICON_SIZE.height() + 2, 0, 0)
            style.drawItemText(painter, text_rect,
                               int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                               option.palette, True, index.data(Qt.ItemDataRole.DisplayRole),
                               QPalette.ColorRole.ButtonText)
        except Exception:  # noqa: BLE001 — this runs from a Qt virtual override
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def sizeHint(self, option, index):  # noqa: N802 — Qt override
        return option.widget.gridSize() if option.widget is not None else TILE_GRID_SIZE


class _ToolTileList(QListWidget):
    """The tile grid, sized to fit exactly the rows its current width needs — not stretched to
    fill whatever space `QVBoxLayout` leaves it (`QAbstractScrollArea`'s default vertical size
    policy is `Expanding`), which would crowd the Info, Shape and Selection Tool controls into
    whatever was left at the bottom of the New feature page. `IconMode` with
    `ResizeMode.Adjust` already reflows the tiles into more or fewer columns as the width changes;
    `heightForWidth` is what lets `QVBoxLayout` ask this widget how tall it needs to be for THAT
    width, rather than the other way around — the standard Qt mechanism for a flow layout whose
    height depends on the width it is given (used the same way a word-wrapped `QLabel` reports its
    own height), so the grid keeps reflowing and staying sized-to-content on every resize.

    Frameless and without a background of its own, so the button tiles sit on the panel like the
    rows of buttons below them, and the cells widen to share the whole width (`_cell`), so the
    tiles line up with those rows' edges too."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.viewport().setAutoFillBackground(False)
        self.setItemDelegate(_ButtonTileDelegate(self))
        self.setGridSize(TILE_GRID_SIZE)
        policy = self.sizePolicy()
        policy.setVerticalPolicy(QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _cell(self, width: int) -> tuple[int, QSize]:
        """The column count and cell size for an outer `width`. Columns are counted the way the
        view itself lays them out: from the VIEWPORT width (`width` minus the frame on both sides),
        and a column only really fits if the viewport is wider than an exact multiple of the cell
        width, not merely as wide (`(viewport_width - 1) // cell`): at an exact multiple the view
        fits one column fewer (verified by probe, sweeping every width from 240 to 520 against the
        view's own `visualRect` for the last tile). Getting either wrong under-counts the rows at
        some widths — this widget then gets too little height from the layout, the last tile falls
        below the viewport, and `ScrollBarAlwaysOff` leaves it unreachable. The cell then widens to
        share what is left, staying just under that exact multiple."""
        viewport_width = width - 2 * self.frameWidth()
        columns = max(1, (viewport_width - 1) // TILE_GRID_SIZE.width())
        cell_width = max(TILE_GRID_SIZE.width(), (viewport_width - 1) // columns)
        return columns, QSize(cell_width, TILE_GRID_SIZE.height())

    def hasHeightForWidth(self) -> bool:  # noqa: N802 — Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 — Qt override
        columns, cell = self._cell(width)
        rows = -(-self.count() // columns)   # ceil division: enough rows for every tile
        return rows * cell.height() + 2 * self.frameWidth()

    def sizeHint(self):  # noqa: N802 — Qt override
        width = self.viewport().width() or TILE_GRID_SIZE.width()
        return QSize(width, self.heightForWidth(width))

    def resizeEvent(self, event):  # noqa: N802 — Qt override
        """Guarded: a Qt virtual override — an exception must not stop the view's own resize."""
        try:
            _columns, cell = self._cell(event.size().width())
            if cell != self.gridSize():
                self.setGridSize(cell)
        except Exception:  # noqa: BLE001 — this runs from a Qt virtual override
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        super().resizeEvent(event)


class ToolGallery(QgsPanelWidget):
    drawRequested = pyqtSignal(object, object, object)  # Tool, Mode, Method
    layerRequested = pyqtSignal(object, object, object, bool)  # Tool, Mode, QgsVectorLayer, selected_only
    layerPicked = pyqtSignal()   # From layer chosen: a drawing still running from this page stops

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDockMode(True)   # mandatory before openPanel, or it opens a modal dialog (hangs offscreen tests)

        layout = QVBoxLayout(self)
        apply_page_margins(layout, self)   # a normal gap from the panel edge, as QGIS's own panels have

        # At the top, above the tiles: the page is taller than a typical dock, and what to do next
        # on the map must be readable without scrolling, as on the feature page.
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.hide()
        layout.addWidget(self.hint)

        # Three sections, each a bold heading over its controls, with a section's worth of space
        # between them — the same heading style throughout, so the order reads at a glance.
        section_gap = 2 * self.style().pixelMetric(QStyle.PixelMetric.PM_LayoutVerticalSpacing, widget=self)

        layout.addWidget(self._heading(self.tr("Feature")))
        self.tool_list = _ToolTileList()
        self.tool_list.setViewMode(QListView.ViewMode.IconMode)
        self.tool_list.setUniformItemSizes(True)
        self.tool_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.tool_list.setMovement(QListView.Movement.Static)
        self.tool_list.setWordWrap(True)
        self.tool_list.setIconSize(TILE_ICON_SIZE)
        for tool in Tool:
            item = QListWidgetItem(TOOL_LABELS[tool])
            item.setData(Qt.ItemDataRole.UserRole, tool.value)
            item.setToolTip(tool_tooltip(tool))
            item.setIcon(illustrations.icon(f"tool_{tool.value}", TILE_ICON_SIZE, self.palette()))
            self.tool_list.addItem(item)
        layout.addWidget(self.tool_list)
        self.info_box = QGroupBox(self.tr("Info"))
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        QVBoxLayout(self.info_box).addWidget(self.summary)
        layout.addWidget(self.info_box)

        layout.addSpacing(section_gap)
        layout.addWidget(self._heading(self.tr("Shape")))
        self.line_mode = self._row_button(self.tr("Line"), SHAPE_ICONS[Mode.PATH])
        self.area_mode = self._row_button(self.tr("Area"), SHAPE_ICONS[Mode.AREA])
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.line_mode)
        self.mode_group.addButton(self.area_mode)
        layout.addLayout(self._button_row([self.line_mode, self.area_mode]))

        layout.addSpacing(section_gap)
        layout.addWidget(self._heading(self.tr("Selection Tool")))
        self.method_buttons = {method: self._method_button(method) for method in Method}
        layout.addLayout(self._button_row(list(self.method_buttons.values())))

        self.layer_source = LayerSource()
        self.layer_source.hide()
        layout.addWidget(self.layer_source)

        # The stretch sits below every control, not on the tile grid itself, so leftover space in a
        # tall dock collects here instead of the grid being stretched to fill it.
        layout.addStretch(1)

        self.tool_list.currentItemChanged.connect(self._tool_changed)
        self.line_mode.toggled.connect(self._mode_changed)
        self.area_mode.toggled.connect(self._mode_changed)
        self.layer_source.useRequested.connect(self._use_layer)
        self._tool_changed()

    def selected_tool(self) -> Tool | None:
        item = self.tool_list.currentItem()
        return Tool(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def changeEvent(self, event):  # noqa: N802 — Qt override
        """Redraw the illustrations when QGIS switches between its light and dark themes.

        Guarded: this runs from a Qt virtual override, and `refresh_icons` reads SVG sources from
        disk through `illustrations.icon` — any exception escaping it here would abort QGIS rather
        than merely leave the tiles stale."""
        if event.type() == QEvent.Type.PaletteChange:
            try:
                self.refresh_icons()
            except Exception:  # noqa: BLE001 — this runs from a Qt virtual override
                QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        super().changeEvent(event)

    def refresh_icons(self) -> None:
        for row in range(self.tool_list.count()):
            item = self.tool_list.item(row)
            tool = Tool(item.data(Qt.ItemDataRole.UserRole))
            item.setIcon(illustrations.icon(f"tool_{tool.value}", TILE_ICON_SIZE, self.palette()))

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

    def clear_hint(self) -> None:
        self.hint.hide()

    def _heading(self, text: str) -> QLabel:
        """A section heading: the panel's own font, bold — the one heading style on this page."""
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _button_row(self, buttons) -> QGridLayout:
        """`buttons` side by side in equal columns, filling the panel's width with a small gap."""
        row = QGridLayout()
        row.setHorizontalSpacing(BUTTON_GAP)
        for column, button in enumerate(buttons):
            row.addWidget(button, 0, column)
            row.setColumnStretch(column, 1)
        return row

    def _row_button(self, text: str, icon: str) -> QPushButton:
        """A checkable push button, its icon beside the text, as wide as its column. A push button,
        not a tool button: it keeps its button frame in either state and centres icon and text in
        the widened button, where a tool button pins them to its left edge."""
        button = QPushButton(QgsApplication.getThemeIcon(icon), text)
        button.setCheckable(True)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        button.setFixedHeight(round(button.sizeHint().height() * BUTTON_HEIGHT_SCALE))
        return button

    def _method_button(self, method: Method) -> QPushButton:
        button = self._row_button(METHOD_LABELS[method], METHOD_ICONS[method])
        button.setToolTip(METHOD_TIPS[method])
        button.clicked.connect(lambda _checked=False, m=method: self._pick(m))
        return button

    def active_method(self) -> Method | None:
        """The selection tool now in use — highlighted until its drawing ends — or None."""
        return next((m for m, b in self.method_buttons.items() if b.isChecked()), None)

    def set_active_method(self, method: Method | None) -> None:
        for each, button in self.method_buttons.items():
            button.setChecked(each is method)

    def drawing_ended(self) -> None:
        """A drawing stopped — finished, cancelled or replaced: Draw or Freehand is no longer in
        use. From layer stays highlighted while its form is open."""
        if self.active_method() in (Method.CLICK, Method.FREEHAND):
            self.set_active_method(None)

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
        for button in self.method_buttons.values():
            button.setEnabled(mode is not None)
        if mode is not None:
            self.layer_source.set_mode(mode)
        else:
            self.layer_source.hide()
            if self.active_method() is Method.LAYER:
                self.set_active_method(None)

    def _pick(self, method: Method) -> None:
        """Start `method` and highlight it. The highlight is set after the request: starting a
        drawing first ends the one running, and ending a drawing clears the highlight. A click on
        a button that is already highlighted would otherwise toggle it off; set here, it stays on."""
        try:
            tool, mode = self.selected_tool(), self.selected_mode()
            if tool is None or mode is None:
                self.set_active_method(None)
                return
            self.layer_source.setVisible(method is Method.LAYER)
            if method is Method.LAYER:
                self.layerPicked.emit()
            else:
                self.drawRequested.emit(tool, mode, method)
            self.set_active_method(method)
        except Exception:  # noqa: BLE001 — this runs off a button's clicked signal
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _use_layer(self, layer, selected_only: bool) -> None:
        tool, mode = self.selected_tool(), self.selected_mode()
        if tool is not None and mode is not None:
            self.layerRequested.emit(tool, mode, layer, selected_only)
