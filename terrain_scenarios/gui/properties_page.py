"""The feature page: header (illustration, name, tool + volume), actions, problems, the fields and
the Advanced section. Every change is applied to the terrain immediately."""
from __future__ import annotations

import html
import traceback

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox, QgsDoubleSpinBox, QgsPanelWidget, QgsScrollArea
from qgis.PyQt.QtCore import QEvent, QSize, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QToolButton,
                                 QVBoxLayout, QWidget)

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode
from . import illustrations, settings
from .illustrations import section
from .controller import LOG_TAG
from .feature_list import feature_subtitle
from .help_texts import (AMOUNT_IS_CUSTOM, FIELD_TIPS, FLAG_TEXTS, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS,
                         amount_label)
from .muted import MutedLabel
from .page_layout import apply_page_margins
from .selection import EDIT_ICON, ZOOM_ICON

DIAGRAM = QSize(230, 110)   # the section diagram's viewBox, at 1:1
HEADER_PICTURE = QSize(72, 36)
PIXEL_ICON = QSize(32, 32)
PIXEL_PICTURE = 72   # each of the three pictures in the Pixels to change tooltip


def _spin(minimum: float, maximum: float, step: float, suffix: str, decimals: int) -> QgsDoubleSpinBox:
    spin = QgsDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setShowClearButton(False)
    spin.setKeyboardTracking(False)  # recompute when a value is committed, not on every keystroke
    return spin


def _action_button(icon: str, text: str, tip: str, checkable: bool = False) -> QToolButton:
    """An icon-only, auto-raised button for the action row — text is kept for screen readers and
    heads the tooltip, the same shape `MainDock`'s own toolbar buttons use."""
    button = QToolButton()
    button.setIcon(QgsApplication.getThemeIcon(icon))
    button.setText(text)
    button.setToolTip(tip)
    button.setAutoRaise(True)
    button.setCheckable(checkable)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    return button


class PropertiesPage(QgsPanelWidget):
    """The feature page (spec §7): a persistent, single instance for the dock's whole life, opened
    on `MainDock`'s panel stack through `MainDock.open_page` — see the note on `_PagePanel` in
    `main_dock.py` for why it is never pushed onto the stack directly."""

    deleteRequested = pyqtSignal(str)
    zoomRequested = pyqtSignal(str)
    editShapeToggled = pyqtSignal(bool)
    titleChanged = pyqtSignal(str)   # panelTitle() just changed (spec §7: the title bar follows a rename)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setDockMode(True)   # mandatory before openPanel, or it opens a modal dialog (hangs offscreen tests)
        self.controller = controller
        self._fid = None
        self._loading = False
        self._highlight = None   # the diagram part of the field with focus, kept across redraws

        # Header: the tool illustration beside the name — renames commit through the controller, so
        # they are undoable — with the tool label and volume line under it, muted (spec §7.1).
        self.header_picture = QLabel()
        self.header_picture.setFixedSize(HEADER_PICTURE)
        self.name_edit = QLineEdit()
        self.name_edit.setToolTip(self.tr("The feature's name."))
        name_font = self.name_edit.font()
        name_font.setBold(True)
        self.name_edit.setFont(name_font)
        self.name_edit.editingFinished.connect(self._commit_rename)
        self.header_summary = MutedLabel()
        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.addWidget(self.name_edit)
        header_text.addWidget(self.header_summary)
        header_row = QHBoxLayout()
        header_row.addWidget(self.header_picture)
        header_row.addLayout(header_text, 1)

        # Action row (spec §7.2): Edit shape, Zoom to feature, Delete. Each is a signal so
        # `MainDock` keeps owning the slots it already has and nothing about undo changes.
        self.edit_button = _action_button(
            EDIT_ICON, self.tr("Edit shape"),
            self.tr("Move, add or remove the points of the selected feature."), checkable=True)
        self.zoom_button = _action_button(ZOOM_ICON, self.tr("Zoom to feature"), self.tr("Zoom to feature"))
        self.delete_button = _action_button("/mActionDeleteSelected.svg", self.tr("Delete"), self.tr("Delete"))
        self.edit_button.toggled.connect(self.editShapeToggled)
        self.zoom_button.clicked.connect(self._request_zoom)
        self.delete_button.clicked.connect(self._request_delete)
        action_row = QHBoxLayout()
        action_row.addWidget(self.edit_button)
        action_row.addWidget(self.zoom_button)
        action_row.addWidget(self.delete_button)
        action_row.addStretch(1)

        # The drawing hint for work started from this page (Edit shape; Draw section line, from the
        # Profiles dock) — spec §6 item 6, §7. `MainDock.show_hint`/`clear_hint` route here whenever
        # this page is the one open.
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.hide()

        self.amount_label = QLabel()
        self.amount_label.setWordWrap(True)   # "Height above the highest point" must not set the panel's width
        self.amount = _spin(0.0, 100.0, 0.1, " m", 2)
        # one source of truth: show_feature swaps between this and AMOUNT_IS_CUSTOM, so the
        # concrete example has to live here or it is lost the moment a feature is selected
        self._amount_tip = FIELD_TIPS["amount"]
        self.width = _spin(0.1, 500.0, 0.5, " m", 2)
        self.slope = _spin(0.0, 50.0, 0.5, "", 1)
        self.slope.setPrefix("1 : ")
        self.reach = _spin(0.0, 500.0, 1.0, " m", 1)
        self.slope_position = QComboBox()
        self.slope_position.addItem(self.tr("Outside the outline"), False)
        self.slope_position.addItem(self.tr("Inside the outline"), True)
        self.pixel_mode = QComboBox()
        for mode in PixelMode:
            self.pixel_mode.addItem(PIXEL_MODE_LABELS[mode], mode.value)
            self.pixel_mode.setItemData(self.pixel_mode.count() - 1, PIXEL_MODE_TIPS[mode], Qt.ItemDataRole.ToolTipRole)
        self.form = QFormLayout()
        self.form.addRow(self.amount_label, self.amount)
        self.form.addRow(self.tr("Width"), self.width)
        self.form.addRow(self.tr("Side slope"), self.slope)
        self.form.addRow(self.tr("Max. slope reach"), self.reach)
        self.form.addRow(self.tr("Slopes"), self.slope_position)

        self.advanced = QgsCollapsibleGroupBox(self.tr("Advanced"))
        self.advanced.setObjectName("TerrainScenariosAdvanced")
        settings.remember_collapsed("advanced_group", self.advanced, collapsed=True)
        advanced_form = QFormLayout(self.advanced)
        advanced_form.addRow(self.tr("Pixels to change"), self.pixel_mode)

        # The feature's own cross-section, drawn from its values, in a box the user can fold away.
        self.diagram_box = QgsCollapsibleGroupBox(self.tr("Cross-section"))
        self.diagram_box.setObjectName("TerrainScenariosCrossSection")
        settings.remember_collapsed("cross_section_group", self.diagram_box, collapsed=False)
        self.diagram = QLabel()
        self.diagram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diagram.setToolTip(self.tr("The part the field you are editing controls is "
                                        "highlighted."))
        QVBoxLayout(self.diagram_box).addWidget(self.diagram)

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.hide()

        content = QWidget()
        content_layout = QVBoxLayout(content)
        apply_page_margins(content_layout, content)   # a normal gap from the panel edge, as QGIS's own panels have
        content_layout.addLayout(header_row)
        content_layout.addLayout(action_row)
        # Directly under the action row (spec §6 item 6): a hint for work started from
        # this page — Edit shape, or Draw section line from the Profiles dock — must never scroll
        # out of sight below Advanced, which can expand to any length.
        content_layout.addWidget(self.hint)
        content_layout.addWidget(self.problems)
        content_layout.addWidget(self.diagram_box)
        content_layout.addLayout(self.form)
        content_layout.addWidget(self.advanced)
        content_layout.addStretch(1)

        # The page scrolls (spec §7) so a narrow, short dock never clips the fields.
        self.scroll_area = QgsScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)

        self.amount.valueChanged.connect(lambda value: self._changed("amount", value))
        self.width.valueChanged.connect(lambda value: self._changed("width", value))
        self.slope.valueChanged.connect(lambda value: self._changed("slope_n", value))
        self.reach.valueChanged.connect(lambda value: self._changed("reach", value))
        self.slope_position.currentIndexChanged.connect(
            lambda _i: self._changed("slopes_inside", bool(self.slope_position.currentData())))
        self.pixel_mode.currentIndexChanged.connect(
            lambda _i: self._changed("pixel_mode", PixelMode(self.pixel_mode.currentData())))
        for widget, key in ((self.amount, "amount"), (self.width, "width"), (self.slope, "slope_n"),
                            (self.reach, "reach"), (self.slope_position, "slopes_inside"),
                            (self.pixel_mode, "pixel_mode")):
            widget.setToolTip(FIELD_TIPS[key])
            widget.installEventFilter(self)
        self.name_edit.installEventFilter(self)   # Escape there discards typed text — see eventFilter
        self._highlight_for = {self.amount: "amount", self.width: "width", self.slope: "slope",
                               self.reach: "reach"}
        controller.featuresChanged.connect(self._refresh_problems)
        controller.featuresChanged.connect(self._refresh_values)
        controller.featuresChanged.connect(self._refresh_summary)

    def eventFilter(self, watched, event):  # noqa: N802 — Qt override
        """Highlight the part of the diagram that belongs to whichever field has focus. Also: Escape
        in the name field or a spin box (amount, width, slope, reach) discards whatever has been
        typed there before it reaches this page's own `keyPressEvent` (inherited from
        `QgsPanelWidget`, dockMode `True`) and closes the page — losing focus as the page closes
        would otherwise commit that text (through `editingFinished` for the name field, or the
        spin's own `interpretText()` on focus-out), and Escape is meant to cancel, not commit (spec
        §7). Not consumed: the key still propagates on to close the page, same as Escape anywhere
        else on it."""
        if event.type() == QEvent.Type.FocusIn:
            try:
                self._draw_diagram(self._highlight_for.get(watched))
            except Exception:  # noqa: BLE001 — an event filter must never take QGIS down
                QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        elif event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            try:
                if watched is self.name_edit:
                    self._discard_name_edit()
                elif watched in self._highlight_for:
                    self._discard_spin_edit(watched)
            except Exception:  # noqa: BLE001 — an event filter must never take QGIS down
                QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        return super().eventFilter(watched, event)

    def _discard_name_edit(self) -> None:
        """Restore the name field to the feature's current name and forget any typed text, so the
        focus-out that follows Escape closing the page commits nothing (`_commit_rename` only acts
        when the text actually differs)."""
        feature = self.controller.find(self._fid) if self._fid is not None else None
        if feature is not None:
            self.name_edit.setText(feature.name)
        self.name_edit.setModified(False)

    def _discard_spin_edit(self, spin) -> None:
        """Restore `spin`'s displayed text to its own last-committed value, discarding whatever has
        been typed but never committed (Return, or the arrows) — the same Escape-cancels rule
        `_discard_name_edit` gives the name field (spec §7), extended to every field on this page.
        `spin.value()` is untouched by typing alone (`setKeyboardTracking(False)`), so it still
        holds the last committed value; `setValue` with that same value still redraws the displayed
        text (Qt does this even when the value itself does not change — verified by probe), which is
        what stops the focus-out that follows Escape closing the page from committing the typed
        text through the spin's own `interpretText()`."""
        spin.setValue(spin.value())

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange and self._fid is not None:
            try:
                self._draw_pictures()
            except Exception:  # noqa: BLE001 — a Qt event handler must never take QGIS down
                QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)
        super().changeEvent(event)

    def clear_hint(self) -> None:
        self.hint.hide()

    def _draw_diagram(self, highlight: str | None) -> None:
        self._highlight = highlight
        feature = self.controller.find(self._fid) if self._fid is not None else None
        if feature is not None and _has_diagram(feature):
            self.diagram.setPixmap(section.section_pixmap(feature, DIAGRAM, self.palette(),
                                                          highlight=highlight))

    def _draw_pictures(self) -> None:
        feature = self.controller.find(self._fid) if self._fid is not None else None
        if feature is None:
            return
        self.header_picture.setPixmap(illustrations.pixmap(f"tool_{feature.tool.value}",
                                                            HEADER_PICTURE, self.palette()))
        self._draw_diagram(self._highlight)
        for index in range(self.pixel_mode.count()):
            mode = PixelMode(self.pixel_mode.itemData(index))
            self.pixel_mode.setItemIcon(index, illustrations.icon(f"pixels_{mode.value}",
                                                                  PIXEL_ICON, self.palette()))
        self.pixel_mode.setToolTip(self._pixel_modes_tip())

    def _pixel_modes_tip(self) -> str:
        """The field's tip with the three pixel modes side by side under it (spec §7.2), drawn in the
        current theme's colours like every other picture on the page."""
        size = PIXEL_PICTURE
        pictures = "".join(
            f'<td align="center"><img src="{illustrations.data_uri(f"pixels_{mode.value}", size, self.palette())}"'
            f' width="{size}" height="{size}"/></td>' for mode in PixelMode)
        names = "".join(f'<td align="center">{html.escape(PIXEL_MODE_LABELS[mode])}</td>' for mode in PixelMode)
        return f"<p>{html.escape(FIELD_TIPS['pixel_mode'])}</p><table><tr>{pictures}</tr><tr>{names}</tr></table>"

    def show_feature(self, fid: str) -> None:
        retargeting = fid == self._fid   # re-shown for the feature already on screen, not a fresh open
        self._fid = fid
        feature = self.controller.feature(fid)
        info = TOOL_INFO[feature.tool]
        label = amount_label(feature.tool, feature.mode)
        self._loading = True
        try:
            self._set_title(feature.name)
            # The "still typing" rule (as `_load_values` already gives every numeric field) only
            # applies when this is the same feature re-shown — e.g. `MainDock` retargeting the open
            # page after some other change. A genuinely different feature always replaces the text.
            if not (retargeting and self.name_edit.isModified()):
                self.name_edit.setText(feature.name)
            self.header_summary.setText(feature_subtitle(self.controller, fid))
            self.amount_label.setText(label or "")
            self._load_values(feature)
            self.form.setRowVisible(self.amount, label is not None)
            self.form.setRowVisible(self.width, feature.mode is Mode.PATH)
            self.form.setRowVisible(self.slope, info.has_slopes)
            self.form.setRowVisible(self.reach, info.has_slopes)
            self.form.setRowVisible(self.slope_position, info.has_slopes and feature.mode is Mode.AREA)
            if not retargeting:
                self._highlight = None
            self._draw_pictures()
            self.diagram_box.setVisible(_has_diagram(feature))
        finally:
            self._loading = False
        self._refresh_problems()
        self._refresh_summary()

    def _load_values(self, feature) -> None:
        """Show the feature's values in the fields — except in a field the user is still typing in:
        a change from elsewhere (a profile drag, an undo) must not throw away what they typed."""
        # Only a profile the engine actually uses fixes the heights: on a multi-part path it
        # is discarded, and Height/Depth is then the one control that still drives the result.
        custom = feature.long_profile is not None and supports_long_profile(feature)
        for spin, value in ((self.amount, feature.amount), (self.width, feature.width),
                            (self.slope, feature.slope_n), (self.reach, feature.reach)):
            if not spin.lineEdit().isModified():
                spin.setValue(value)
        self.amount.setEnabled(not custom)
        self.amount.setToolTip(AMOUNT_IS_CUSTOM if custom else self._amount_tip)
        self.slope_position.setCurrentIndex(1 if feature.slopes_inside else 0)
        self.pixel_mode.setCurrentIndex(self.pixel_mode.findData(feature.pixel_mode.value))

    def _refresh_values(self) -> None:
        """Keep the fields in step with the feature whenever the list changes: a cross-profile drag
        moves the width, slope and reach, and an undo can change anything. Runs in a slot."""
        try:
            feature = self.controller.find(self._fid) if self._fid is not None else None
            if feature is None:
                return
            self._loading = True
            try:
                self._load_values(feature)
            finally:
                self._loading = False
            self._draw_diagram(self._highlight)   # the section follows every value, wherever it changed
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _refresh_summary(self) -> None:
        """Keep the header's muted summary (tool, fill, cut) in step with the engine.

        Runs from `featuresChanged`, a Qt signal — an exception escaping it aborts QGIS, so any
        failure here is logged instead of raised, the same rule the controller itself follows."""
        try:
            if self._fid is not None and self.controller.find(self._fid) is not None:
                self.header_summary.setText(feature_subtitle(self.controller, self._fid))
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _changed(self, field: str, value) -> None:
        if self._fid is not None and not self._loading:
            self.controller.update_feature(self._fid, **{field: value})

    def _refresh_problems(self) -> None:
        if self._fid not in {f.id for f in self.controller.features}:
            self._fid = None
            return
        feature = self.controller.find(self._fid)
        self._set_title(feature.name)   # follows a rename in the list
        if not self.name_edit.isModified():   # … without clobbering a name the user is still typing
            self.name_edit.setText(feature.name)
        flags = self.controller.stats(self._fid).flags
        self.problems.setText("\n".join(FLAG_TEXTS[flag] for flag in flags))
        self.problems.setVisible(bool(flags))

    def _set_title(self, name: str) -> None:
        """`setPanelTitle` has no notify signal of its own; `titleChanged` lets `MainDock` keep the
        stack's own title bar in step with a rename (spec §7) without polling."""
        self.setPanelTitle(name)
        self.titleChanged.emit(name)

    def _commit_rename(self) -> None:
        """The header's name field: committed through the controller on editingFinished, so the
        rename is undoable like every other change on this page. Either way — a real rename, an
        empty field (rejected) or one with leading/trailing spaces (stripped) — the field ends up
        showing exactly the name the controller now holds, never blank and never padded."""
        if self._fid is None or self._loading:
            return
        feature = self.controller.find(self._fid)
        if feature is None:
            return
        name = self.name_edit.text().strip()
        if name and name != feature.name:
            self.controller.update_feature(self._fid, name=name)
            feature = self.controller.find(self._fid)
        self.name_edit.setText(feature.name)
        self.name_edit.setModified(False)

    def _request_zoom(self) -> None:
        if self._fid is not None:
            self.zoomRequested.emit(self._fid)

    def _request_delete(self) -> None:
        if self._fid is not None:
            self.deleteRequested.emit(self._fid)


def _has_diagram(feature) -> bool:
    """Only a path with side slopes has a cross-section worth drawing."""
    return feature.mode is Mode.PATH and TOOL_INFO[feature.tool].has_slopes
