"""Values of the selected feature; every change is applied to the terrain immediately."""
from __future__ import annotations

from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from ..core.sections import supports_long_profile
from ..core.tools import TOOL_INFO, Mode, PixelMode
from .help_texts import AMOUNT_IS_CUSTOM, FLAG_TEXTS, PIXEL_MODE_LABELS, PIXEL_MODE_TIPS, TOOL_LABELS, TOOL_SUMMARIES, amount_label


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
        self._amount_tip = self.tr("How far the feature rises (height) or cuts (depth): above or below the "
                                   "straight grade between the path's ends, the highest or lowest point of "
                                   "the path or outline, or the terrain itself for Add and Subtract.")
        self.amount.setToolTip(self._amount_tip)
        self.width = _spin(0.1, 500.0, 0.5, " m", 2)
        self.width.setToolTip(self.tr("Width of the crest (raise tools) or the bottom (lower tools) of the path."))
        self.slope = _spin(0.0, 50.0, 0.5, "", 1)
        self.slope.setPrefix("1 : ")
        self.slope.setToolTip(self.tr("Horizontal metres per metre of height: 1 : 3 goes 3 m outwards for every "
                                      "1 m. 0 means no side slopes."))
        self.reach = _spin(0.0, 500.0, 1.0, " m", 1)
        self.reach.setToolTip(self.tr("Side slopes stop this far from the edge, even if they have not met the "
                                      "ground yet."))
        self.slope_position = QComboBox()
        self.slope_position.addItem(self.tr("Outside the outline"), False)
        self.slope_position.addItem(self.tr("Inside the outline"), True)
        self.slope_position.setToolTip(self.tr("Inside: the outline is the top edge (e.g. a pond). Outside: the "
                                               "outline is the flat part (e.g. a raised pad)."))
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
        self.problems = QLabel()
        self.problems.setWordWrap(True)
        self.problems.hide()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.title)
        layout.addWidget(self.summary)
        layout.addLayout(self.form)
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
        controller.featuresChanged.connect(self._refresh_problems)

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
            self.amount_label.setText(self.tr(label) if label else "")
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
        finally:
            self._loading = False
        self._refresh_problems()

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
