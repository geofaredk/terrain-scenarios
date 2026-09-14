"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

import traceback

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsCollapsibleGroupBox, QgsDoubleSpinBox
from qgis.PyQt.QtCore import QEvent, QSize, Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode, reports_storage
from . import illustrations
from .controller import LOG_TAG
from .help_texts import (AMOUNT_IS_CUSTOM, FIELD_TIPS, FLAG_TEXTS, NO_VOLUME_YET, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS,
                         SCENARIO_TOTALS, TOOL_DESCRIPTIONS, TOOL_EXAMPLES, TOOL_LABELS, TOOL_SUMMARIES,
                         VOLUME_CUT_TIP, VOLUME_FILL_TIP, VOLUME_STORAGE_NOTE, VOLUME_STORAGE_TIP, amount_label,
                         cubic_metres)

DIAGRAM = QSize(200, 96)
TOOL_PICTURE = QSize(120, 64)
PIXEL_ICON = QSize(32, 32)


def _spin(minimum: float, maximum: float, step: float, suffix: str, decimals: int) -> QgsDoubleSpinBox:
    spin = QgsDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSingleStep(step)
    spin.setDecimals(decimals)
    spin.setSuffix(suffix)
    spin.setShowClearButton(False)
    spin.setKeyboardTracking(False)  # recompute when a value is committed, not on every keystroke
    return spin


class PropertiesPage(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._fid = None
        self._loading = False
        self.title = QLabel()
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.amount_label = QLabel()
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
        self.form.addRow(self.tr("Pixels to change"), self.pixel_mode)
        self.about = QgsCollapsibleGroupBox(self.tr("About this tool"))
        self.about.setObjectName("TerrainSketchAboutTool")  # QgsCollapsibleGroupBox saves state by name
        self.about_text = QLabel()
        self.about_text.setWordWrap(True)
        self.about_picture = QLabel()
        self.about_picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_layout = QVBoxLayout(self.about)
        about_layout.addWidget(self.about_picture)
        about_layout.addWidget(self.about_text)

        self.diagram = QLabel()
        self.diagram.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.diagram.setToolTip(self.tr("The part the field you are editing controls is "
                                        "highlighted."))

        self.volumes = QgsCollapsibleGroupBox(self.tr("Volumes"))
        self.volumes.setObjectName("TerrainSketchVolumes")
        self.fill_value = QLabel()
        self.fill_value.setWordWrap(True)
        self.fill_value.setToolTip(VOLUME_FILL_TIP)
        self.cut_value = QLabel()
        self.cut_value.setWordWrap(True)
        self.cut_value.setToolTip(VOLUME_CUT_TIP)
        self.storage_value = QLabel()
        self.storage_value.setWordWrap(True)
        self.storage_value.setToolTip(VOLUME_STORAGE_TIP)
        self.totals_value = QLabel()
        self.totals_value.setWordWrap(True)
        volume_form = QFormLayout(self.volumes)
        volume_form.addRow(self.tr("Fill"), self.fill_value)
        volume_form.addRow(self.tr("Cut"), self.cut_value)
        volume_form.addRow(self.tr("Storage"), self.storage_value)
        volume_form.addRow(self.tr("Whole scenario"), self.totals_value)
        self.volume_form = volume_form

        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        layout.addWidget(self.about)
        layout.addWidget(self.diagram)
        layout.addLayout(self.form)
        layout.addWidget(self.volumes)
        layout.addWidget(self.problems)
        layout.addStretch(1)
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
        self._highlight_for = {self.amount: "amount", self.width: "width", self.slope: "slope",
                               self.reach: "reach"}
        controller.featuresChanged.connect(self._refresh_problems)
        controller.featuresChanged.connect(self._refresh_volumes)

    def eventFilter(self, watched, event):  # noqa: N802 — Qt override
        """Highlight the part of the diagram that belongs to whichever field has focus."""
        if event.type() == QEvent.Type.FocusIn:
            self._draw_diagram(self._highlight_for.get(watched))
        return super().eventFilter(watched, event)

    def changeEvent(self, event):  # noqa: N802 — Qt override
        if event.type() == QEvent.Type.PaletteChange and self._fid is not None:
            self._draw_pictures()
        super().changeEvent(event)

    def _draw_diagram(self, highlight: str | None) -> None:
        self.diagram.setPixmap(illustrations.pixmap("parameters", DIAGRAM, self.palette(),
                                                    highlight=highlight))

    def _draw_pictures(self) -> None:
        feature = self.controller.find(self._fid) if self._fid is not None else None
        if feature is None:
            return
        self.about_picture.setPixmap(illustrations.pixmap(f"tool_{feature.tool.value}",
                                                          TOOL_PICTURE, self.palette()))
        self._draw_diagram(None)
        for index in range(self.pixel_mode.count()):
            mode = PixelMode(self.pixel_mode.itemData(index))
            self.pixel_mode.setItemIcon(index, illustrations.icon(f"pixels_{mode.value}",
                                                                  PIXEL_ICON, self.palette()))

    def show_feature(self, fid: str) -> None:
        self._fid = fid
        feature = self.controller.feature(fid)
        info = TOOL_INFO[feature.tool]
        label = amount_label(feature.tool)
        self._loading = True
        try:
            self.title.setText(f"{feature.name} · {TOOL_LABELS[feature.tool]}")
            self.summary.setText(TOOL_SUMMARIES[feature.tool])
            # Only a profile the engine actually uses fixes the heights: on a multi-part path it
            # is discarded, and Height/Depth is then the one control that still drives the result.
            custom = feature.long_profile is not None and supports_long_profile(feature)
            self.amount_label.setText(label or "")
            self.amount.setValue(feature.amount)
            self.amount.setEnabled(not custom)
            self.amount.setToolTip(AMOUNT_IS_CUSTOM if custom else self._amount_tip)
            self.width.setValue(feature.width)
            self.slope.setValue(feature.slope_n)
            self.reach.setValue(feature.reach)
            self.slope_position.setCurrentIndex(1 if feature.slopes_inside else 0)
            self.pixel_mode.setCurrentIndex(self.pixel_mode.findData(feature.pixel_mode.value))
            self.form.setRowVisible(self.amount, label is not None)
            self.form.setRowVisible(self.width, feature.mode is Mode.PATH)
            self.form.setRowVisible(self.slope, info.has_slopes)
            self.form.setRowVisible(self.reach, info.has_slopes)
            self.form.setRowVisible(self.slope_position, info.has_slopes and feature.mode is Mode.AREA)
            self.about_text.setText(f"{TOOL_DESCRIPTIONS[feature.tool]}\n\n"
                                    f"{TOOL_EXAMPLES[feature.tool]}")
            self._draw_pictures()
            self.diagram.setVisible(feature.mode is Mode.PATH and info.has_slopes)
        finally:
            self._loading = False
        self._refresh_problems()
        self._refresh_volumes()

    def _refresh_volumes(self) -> None:
        """Per-feature cut, fill and (for the tools that hold water) storage, plus the scenario
        totals. Storage is hidden rather than shown as zero for a tool that cannot hold water.

        Runs from `featuresChanged`, a Qt signal — an exception escaping it aborts QGIS, so any
        failure here is logged instead of raised, the same rule the controller itself follows."""
        try:
            feature = self.controller.find(self._fid) if self._fid is not None else None
            if feature is None:
                return
            stats = self.controller.stats(self._fid)
            self.fill_value.setText(cubic_metres(stats.fill))
            self.cut_value.setText(cubic_metres(stats.cut))
            shows_storage = reports_storage(feature.tool, feature.mode)
            self.volume_form.setRowVisible(self.storage_value, shows_storage)
            if shows_storage:
                self.storage_value.setText(
                    f"≈ {cubic_metres(stats.storage)} {VOLUME_STORAGE_NOTE}"
                    if stats.storage is not None else NO_VOLUME_YET)
            cut, fill = self.controller.totals()
            self.totals_value.setText(SCENARIO_TOTALS.format(fill=cubic_metres(fill), cut=cubic_metres(cut)))
        except Exception:  # noqa: BLE001 — this runs in a slot
            QgsMessageLog.logMessage(traceback.format_exc(), LOG_TAG, Qgis.MessageLevel.Critical)

    def _changed(self, field: str, value) -> None:
        if self._fid is not None and not self._loading:
            self.controller.update_feature(self._fid, **{field: value})

    def _refresh_problems(self) -> None:
        if self._fid not in {f.id for f in self.controller.features}:
            self._fid = None
            return
        flags = self.controller.stats(self._fid).flags
        self.problems.setText("\n".join(FLAG_TEXTS[flag] for flag in flags))
        self.problems.setVisible(bool(flags))
