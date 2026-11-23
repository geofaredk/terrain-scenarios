"""The feature list: on/off checkbox, editable name, muted subtitle and warning icon; drag rows to
reorder. Each row shows the tool's picture and opens the feature's page when clicked."""
from __future__ import annotations

import traceback

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import QAbstractListModel, QItemSelectionModel, QMimeData, QModelIndex, QRect, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QMouseEvent, QPalette
from qgis.PyQt.QtWidgets import (QAbstractItemView, QApplication, QListView, QStyle, QStyleOptionButton,
                                 QStyleOptionViewItem, QStyledItemDelegate)

from ..qgis_io.symbols import preview_pixmap
from . import illustrations
from .help_texts import FLAG_TEXTS, TOOL_LABELS
from .muted import muted_between

LOG_TAG = "Terrain Scenarios"

ID_ROLE = Qt.ItemDataRole.UserRole
SUBTITLE_ROLE = Qt.ItemDataRole.UserRole + 1
PICTURE_ROLE = Qt.ItemDataRole.UserRole + 2
FLAGGED_ROLE = Qt.ItemDataRole.UserRole + 3
SYMBOL_ROLE = Qt.ItemDataRole.UserRole + 4
SWATCH_ROLE = Qt.ItemDataRole.UserRole + 5
MIME_TYPE = "application/x-terrain-scenarios-feature-ids"


def feature_subtitle(controller, fid: str) -> str:
    """What the feature is: its tool's label."""
    feature = controller.find(fid)
    if feature is None:
        return ""
    return TOOL_LABELS[feature.tool]


class FeatureListModel(QAbstractListModel):
    """Rows mirror the controller's feature list; every edit goes through the controller."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._ids: list[str] = []
        self._symbols: dict = {}      # fid -> the symbol display_symbol gave (or None), kept until the next _sync
        self._swatches: dict = {}     # fid -> the pixmap made from it; painting must not rebuild either
        controller.featuresChanged.connect(self._sync)
        controller.stylesChanged.connect(self._sync)      # an edit made in QGIS's Layers panel
        self._sync()

    def _sync(self) -> None:
        self._symbols.clear()
        self._swatches.clear()
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

    def _id_at(self, index) -> str | None:
        """The feature id at `index`, or None. Qt checks only that a row is not negative, so an
        index kept across a reset (e.g. by a context menu) can point past the end of the list."""
        return self._ids[index.row()] if index.isValid() and index.row() < len(self._ids) else None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        fid = self._id_at(index)
        if fid is None:
            return None
        feature = self.controller.find(fid)
        if feature is None:
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return feature.name
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if feature.enabled else Qt.CheckState.Unchecked
        if role == ID_ROLE:
            return feature.id
        if role == SUBTITLE_ROLE:
            return feature_subtitle(self.controller, feature.id)
        if role == PICTURE_ROLE:
            return f"tool_{feature.tool.value}"
        if role == SYMBOL_ROLE:
            return self._symbol(feature.id)
        if role == SWATCH_ROLE:
            return self._swatch(feature.id)
        flags = self.controller.stats(feature.id).flags
        if role == FLAGGED_ROLE:
            return bool(flags)
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join([TOOL_LABELS[feature.tool]] + [FLAG_TEXTS[flag] for flag in flags])
        return None

    def _symbol(self, fid: str):
        if fid not in self._symbols:
            self._symbols[fid] = self.controller.display_symbol(fid)
        return self._symbols[fid]

    def _swatch(self, fid: str):
        if fid not in self._swatches:
            symbol = self._symbol(fid)
            self._swatches[fid] = None if symbol is None else preview_pixmap(symbol, PICTURE_SIZE)
        return self._swatches[fid]

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):  # noqa: N802 — Qt override
        fid = self._id_at(index)
        if fid is None:
            return False
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
        ids = (self._id_at(i) for i in indexes)
        data.setData(MIME_TYPE, "\n".join(fid for fid in ids if fid is not None).encode())
        return data

    def dropMimeData(self, data, action, row, column, parent):  # noqa: N802 — Qt override
        if action != Qt.DropAction.MoveAction or not data.hasFormat(MIME_TYPE):
            return False
        moving = bytes(data.data(MIME_TYPE)).decode().split("\n")
        if not set(moving) <= set(self._ids):
            return False     # ids from another list, or from before a change: reorder() would raise in this Qt callback
        if row < 0:
            row = parent.row() if parent.isValid() else len(self._ids)
        before = [i for i in self._ids[:row] if i not in moving]
        after = [i for i in self._ids[row:] if i not in moving]
        self.controller.reorder(before + moving + after)
        return False  # the model already reordered itself; the view must not remove the dragged rows


PADDING = 6
SPACING = 8
PICTURE_SIZE = QSize(40, 20)
WARNING_SIZE = 16
CHEVRON_WIDTH = 12


class FeatureRowDelegate(QStyledItemDelegate):
    """Paints a row: the check indicator, the tool's picture, its name and muted subtitle, an
    optional warning icon, and a chevron — everything but the check indicator in the palette's
    (or muted) colours, so the row follows a QGIS theme switch."""

    @staticmethod
    def checkbox_rect(row_rect) -> QRect:
        """Where the check indicator sits within a row's rect — the one hit-test both the
        delegate's paint and the view's mouseReleaseEvent use, so they can never disagree."""
        style = QApplication.style()
        width = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorWidth)
        height = style.pixelMetric(QStyle.PixelMetric.PM_IndicatorHeight)
        x = row_rect.left() + PADDING
        y = row_rect.top() + (row_rect.height() - height) // 2
        return QRect(x, y, width, height)

    @staticmethod
    def row_colours(option) -> tuple:
        """(text, muted) for a row: the colours the row's text is drawn in, taken from the
        background the row is actually painted on — HighlightedText muted toward Highlight on a
        selected row, Text muted toward Base on any other (list rows sit on Base, not Window)."""
        palette = option.palette
        if option.state & QStyle.StateFlag.State_Selected:
            text = palette.color(QPalette.ColorRole.HighlightedText)
            background = palette.color(QPalette.ColorRole.Highlight)
        else:
            text = palette.color(QPalette.ColorRole.Text)
            background = palette.color(QPalette.ColorRole.Base)
        return text, muted_between(text, background)

    @staticmethod
    def picture_palette(option, text, muted) -> QPalette:
        """The palette the row's picture is drawn from. On a selected row the picture's line
        (Highlight) and terrain (Mid) would sit on the highlight itself, so they take the row's
        text and muted colours instead."""
        palette = QPalette(option.palette)
        if option.state & QStyle.StateFlag.State_Selected:
            palette.setColor(QPalette.ColorRole.Highlight, text)
            palette.setColor(QPalette.ColorRole.WindowText, text)
            palette.setColor(QPalette.ColorRole.Mid, muted)
        return palette

    def sizeHint(self, option, index):  # noqa: N802 — Qt override
        option = QStyleOptionViewItem(option)
        self.initStyleOption(option, index)
        line_height = option.fontMetrics.height()
        text_height = 2 * line_height + PADDING
        width = option.rect.width() or 250
        return QSize(width, max(text_height, PICTURE_SIZE.height()) + 2 * PADDING)

    def editorEvent(self, event, model, option, index):  # noqa: N802 — Qt override
        """The view's mouseReleaseEvent is the one place that toggles the checkbox on a mouse
        click (see checkbox_rect): the base implementation hit-tests its own, differently
        positioned checkbox rect, and letting both run could flip the state twice on one click.
        Anything that is not a mouse event — in particular the Key_Space/Key_Select toggle the
        base implementation also handles — is unaffected and still works."""
        if isinstance(event, QMouseEvent):
            return False
        return super().editorEvent(event, model, option, index)

    def paint(self, painter, option, index):  # noqa: N802 — Qt override
        try:
            self._paint(painter, option, index)
        except Exception:  # noqa: BLE001 — an exception escaping a Qt paint callback aborts QGIS
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _paint(self, painter, option, index) -> None:
        style = option.widget.style() if option.widget is not None else QApplication.style()
        painter.save()
        try:
            if option.state & QStyle.StateFlag.State_Selected:
                painter.fillRect(option.rect, option.palette.color(QPalette.ColorRole.Highlight))
            text_colour, muted = self.row_colours(option)

            checkbox_rect = self.checkbox_rect(option.rect)
            checkbox_option = QStyleOptionButton()
            checkbox_option.rect = checkbox_rect
            checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            checkbox_option.state = QStyle.StateFlag.State_Enabled | (
                QStyle.StateFlag.State_On if checked else QStyle.StateFlag.State_Off)
            style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorCheckBox, checkbox_option, painter,
                                option.widget)

            picture_rect = QRect(checkbox_rect.right() + SPACING,
                                 option.rect.top() + (option.rect.height() - PICTURE_SIZE.height()) // 2,
                                 PICTURE_SIZE.width(), PICTURE_SIZE.height())
            swatch = index.data(SWATCH_ROLE)
            picture_name = index.data(PICTURE_ROLE)
            if swatch is not None:
                painter.drawPixmap(picture_rect, swatch)
            elif picture_name:
                picture_palette = self.picture_palette(option, text_colour, muted)
                painter.drawPixmap(picture_rect, illustrations.pixmap(picture_name, PICTURE_SIZE, picture_palette))

            right = option.rect.right() - PADDING
            chevron_rect = QRect(right - CHEVRON_WIDTH, option.rect.top(), CHEVRON_WIDTH, option.rect.height())
            right = chevron_rect.left() - SPACING

            warning_rect = None
            if index.data(FLAGGED_ROLE):
                warning_rect = QRect(right - WARNING_SIZE,
                                     option.rect.top() + (option.rect.height() - WARNING_SIZE) // 2,
                                     WARNING_SIZE, WARNING_SIZE)
                right = warning_rect.left() - SPACING

            text_left = picture_rect.right() + SPACING
            text_rect = QRect(text_left, option.rect.top() + PADDING // 2, max(right - text_left, 0),
                              option.rect.height() - PADDING)
            line_height = option.fontMetrics.height()
            title_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), line_height)
            subtitle_rect = QRect(text_rect.left(), title_rect.bottom(), text_rect.width(), line_height)

            painter.setPen(text_colour)
            title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             option.fontMetrics.elidedText(title, Qt.TextElideMode.ElideRight, title_rect.width()))

            painter.setPen(muted)
            subtitle = str(index.data(SUBTITLE_ROLE) or "")
            painter.drawText(subtitle_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             option.fontMetrics.elidedText(subtitle, Qt.TextElideMode.ElideRight,
                                                          subtitle_rect.width()))

            if warning_rect is not None:
                icon = QgsApplication.getThemeIcon("/mIconWarning.svg")
                if not icon.isNull():
                    icon.paint(painter, warning_rect)

            arrow_option = QStyleOptionViewItem(option)
            arrow_option.rect = chevron_rect
            arrow_palette = QPalette(option.palette)
            for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
                arrow_palette.setColor(role, muted)
            arrow_option.palette = arrow_palette
            style.drawPrimitive(QStyle.PrimitiveElement.PE_IndicatorArrowRight, arrow_option, painter, option.widget)
        finally:
            painter.restore()


class FeatureListView(QListView):
    """List view with drag-to-reorder that keeps the selected feature across model resets.

    A click outside the checkbox opens the feature's page (`rowOpened`); a click on the checkbox
    toggles it; Enter/Return opens the current row. Renaming in the list is F2 (or the context
    menu's Rename), not a double click: its first click has already opened the page."""

    rowOpened = pyqtSignal(str)

    def __init__(self, model: FeatureListModel, parent=None):
        super().__init__(parent)
        self.setModel(model)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setItemDelegate(FeatureRowDelegate(self))
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

    def mouseReleaseEvent(self, event):  # noqa: N802 — Qt override
        index = self.indexAt(event.pos())
        super().mouseReleaseEvent(event)
        if self.state() == QAbstractItemView.State.EditingState:
            return          # a release while a rename is open belongs to that rename, not a plain open
        if not index.isValid() or event.button() != Qt.MouseButton.LeftButton:
            return
        rect = self.visualRect(index)
        if FeatureRowDelegate.checkbox_rect(rect).contains(event.pos()):
            checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
            new_state = Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked
            self.model().setData(index, new_state.value, Qt.ItemDataRole.CheckStateRole)
            return
        fid = index.data(ID_ROLE)
        if fid is not None:
            self.rowOpened.emit(fid)

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        """Return/Enter opens the current row; F2 renames it. Qt's own F2 handling is compiled out
        on macOS, where its edit key is Return instead, and Return opens the page here — so F2 is
        handled explicitly on every platform. Guarded: an exception escaping this Qt override
        would abort QGIS."""
        try:
            if self.state() != QAbstractItemView.State.EditingState:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    fid = self.currentIndex().data(ID_ROLE)
                    if fid is not None:
                        self.rowOpened.emit(fid)
                        return
                elif event.key() == Qt.Key.Key_F2 and self.currentIndex().isValid():
                    if self.edit(self.currentIndex(), QAbstractItemView.EditTrigger.EditKeyPressed, event):
                        return
        except Exception:  # noqa: BLE001 — this runs from a Qt virtual override
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        super().keyPressEvent(event)

    def _remember(self) -> None:
        self._remembered = self.selected_id()

    def _restore(self) -> None:
        self.select_id(self._remembered)
