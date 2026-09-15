"""Bottom dock: the cross profile and the long profile of the selected feature, side by side."""
from __future__ import annotations

from qgis.gui import QgsDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                                 QWidget)

from ..core.sections import (cross_section, set_cross_section, set_whole_cross_section, supports_long_profile,
                             whole_cross_section)
from ..core.tools import TOOL_INFO, Mode
from .help_texts import (AREA_LONG_SECTION_HINT, AREA_LONG_SECTION_NOTE, CROSS_SIDES_TIP, CUSTOM_PROFILE_NOTE,
                         MULTIPART_LONG_SECTION_NOTE, SYMMETRIC_TIP)
from . import settings
from .profile_widget import Kind, ProfileWidget


class ProfileDock(QgsDockWidget):
    """Shows the selected feature's shape and writes every edit back through the controller."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Terrain Sketch — Profiles"))
        self.setObjectName("TerrainSketchProfileDock")
        self.controller = controller
        self._fid = None
        self._loading = False

        self.cross = ProfileWidget(Kind.CROSS)
        self.cross.setToolTip(CROSS_SIDES_TIP)
        self.long = ProfileWidget(Kind.LONG)
        self.symmetric = QCheckBox(self.tr("Symmetric"))
        self.symmetric.setChecked(True)
        self.symmetric.setToolTip(SYMMETRIC_TIP)
        self.cross.symmetric = True
        self.symmetric.toggled.connect(self._symmetric_toggled)
        self.reset_cross = QPushButton(self.tr("Reset shape"))
        self.reset_long = QPushButton(self.tr("Reset to rule"))
        self.note = QLabel()
        self.note.setWordWrap(True)

        body = QWidget()
        layout = QVBoxLayout(body)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        for title, widget, controls in (
                (self.tr("Cross profile"), self.cross, (self.symmetric, self.reset_cross)),
                (self.tr("Long profile"), self.long, (self.reset_long,))):
            panel = QWidget()
            column = QVBoxLayout(panel)
            column.setContentsMargins(0, 0, 0, 0)
            header = QHBoxLayout()
            header.addWidget(QLabel(title))
            header.addStretch(1)
            for control in controls:
                header.addWidget(control)
            column.addLayout(header)
            column.addWidget(widget, 1)
            splitter.addWidget(panel)
        self.splitter = splitter
        splitter.setObjectName("TerrainSketchProfileSplitter")
        settings.restore_state("profile_splitter", splitter)
        splitter.splitterMoved.connect(
            lambda *_args: settings.save_state("profile_splitter", splitter))
        layout.addWidget(splitter, 1)
        layout.addWidget(self.note)
        self.setWidget(body)

        self.cross.profileChanged.connect(lambda points: self._cross_edited(points, False))
        self.cross.profileCommitted.connect(lambda points: self._cross_edited(points, True))
        self.long.profileChanged.connect(lambda points: self._long_edited(points, False))
        self.long.profileCommitted.connect(lambda points: self._long_edited(points, True))
        self.reset_cross.clicked.connect(self._reset_cross)
        self.reset_long.clicked.connect(self._reset_long)
        controller.featuresChanged.connect(self._refresh)
        controller.sessionChanged.connect(self._session_changed)
        self.show_feature(None)

    def show_feature(self, fid) -> None:
        """Load a feature's profiles, or clear both panels when there is no selection."""
        self._fid = fid
        if fid is None or not self.controller.has_dem:
            self.cross.clear()
            self.long.clear()
            self.note.clear()
            self._set_enabled(False)
            return
        self._refresh()

    def _refresh(self) -> None:
        if self._fid is None:
            return
        feature = self.controller.find(self._fid)
        if feature is None:
            self.show_feature(None)
            return
        self._loading = True
        try:
            info = TOOL_INFO[feature.tool]
            is_path = feature.mode is Mode.PATH
            # A path shows both sides around its centre line; an area shows its one edge slope, and
            # takes no break points: the engine discards an area's (spec 5.4).
            if is_path:
                self.cross.set_profile(whole_cross_section(feature), editable=info.has_slopes, mirrored=True)
            else:
                self.cross.set_profile(cross_section(feature, side=1), editable=info.has_slopes,
                                       allow_breaks=False)
            self.symmetric.setEnabled(info.has_slopes and is_path)
            self.reset_cross.setEnabled(info.has_slopes)
            section = self.controller.long_section(self._fid)
            if feature.mode is Mode.AREA:
                # There is no section through an area yet, so say so rather than paint an empty
                # plot under a note promising one.
                self.long.set_profile((), editable=False, hint=AREA_LONG_SECTION_HINT)
                self.note.setText(AREA_LONG_SECTION_NOTE)
            elif not supports_long_profile(feature):
                # A multi-part path: the engine follows the tool rule whatever is stored here.
                self.long.set_profile(section["design"], terrain=self._pairs(section),
                                      editable=False)
                self.note.setText(MULTIPART_LONG_SECTION_NOTE)
            else:
                self.long.set_profile(section["design"], terrain=self._pairs(section))
                self.note.setText(CUSTOM_PROFILE_NOTE if section["custom"] else "")
            self.reset_long.setEnabled(bool(section["custom"]))
        finally:
            self._loading = False

    @staticmethod
    def _pairs(section) -> tuple:
        return tuple(zip(section["stations"], section["terrain"]))

    def _cross_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        feature = self.controller.find(self._fid)
        if feature is None:
            return
        try:
            if feature.mode is Mode.PATH:
                changes = set_whole_cross_section(feature, points, symmetric=self.symmetric.isChecked())
            else:
                changes = set_cross_section(feature, 1, points)
        except ValueError:
            return            # a side without its crest edge; the plot never sends one, and this is a slot
        self._apply(changes, commit)

    def _long_edited(self, points, commit: bool) -> None:
        if self._loading or self._fid is None:
            return
        self._apply({"long_profile": tuple((float(s), float(z)) for s, z in points)}, commit)

    def _apply(self, changes: dict, commit: bool) -> None:
        if commit:
            self.controller.update_profile(self._fid, **changes)
        else:
            self.controller.preview(self._fid, **changes)

    def _reset_cross(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, cross_left=(), cross_right=())

    def _reset_long(self) -> None:
        if self._fid is not None:
            self.controller.update_profile(self._fid, long_profile=None)

    def _symmetric_toggled(self, checked: bool) -> None:
        self.cross.symmetric = checked

    def _session_changed(self) -> None:
        if not self.controller.has_dem:
            self.show_feature(None)

    def _set_enabled(self, enabled: bool) -> None:
        for widget in (self.symmetric, self.reset_cross, self.reset_long):
            widget.setEnabled(enabled)

    def shutdown(self) -> None:
        self.controller.cancel_preview()
