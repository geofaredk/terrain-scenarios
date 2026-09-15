"""Undo and redo for the feature list, and the keys that reach them (spec §7.4)."""
from __future__ import annotations

import traceback

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QEvent, QObject
from qgis.PyQt.QtGui import QKeySequence, QUndoCommand

MERGE_ID = 1  # every mergeable change shares one id; `key` decides whether two actually merge


class FeatureListChange(QUndoCommand):
    """One change to the feature list, kept as the whole list before and after it.

    Features are immutable, so the two lists share every feature the change did not touch and
    cost little more than pointers. Undo and redo hand a list back to the controller, which
    recomputes only the window that differs — the same path as the original edit.

    A change is pushed after it has already been applied, so the first `redo()`, which Qt calls
    on push, does nothing. Changes with the same `key` (the same settings of the same feature,
    e.g. every step of a spin box) merge into one step; Qt never merges into the step a scenario
    was saved at, so undo can always return to exactly what is on disk."""

    def __init__(self, restore, before, after, text: str, key=None):
        super().__init__(text)
        self._restore = restore
        self.before = tuple(before)
        self.after = tuple(after)
        self.key = key
        self._pushed = False

    def id(self) -> int:  # noqa: A003 — Qt override
        return MERGE_ID if self.key is not None else -1

    def redo(self) -> None:
        if not self._pushed:
            self._pushed = True
            return
        self._restore(self.after)

    def undo(self) -> None:
        self._restore(self.before)

    def mergeWith(self, other) -> bool:  # noqa: N802 — Qt override
        if other.key != self.key:
            return False
        self.after = other.after
        self.setObsolete(self.after == self.before)   # stepped back to where it started: no step at all
        return True


class UndoKeys(QObject):
    """Ctrl+Z and Ctrl+Shift+Z for Terrain Sketch while the panel, or the map with a Terrain
    Sketch tool active, has focus — and QGIS's own undo everywhere else.

    Installed as an event filter. QGIS binds the same keys to layer-editing undo in its main
    window, and two shortcuts for one key cancel each other out, so this claims the key during
    `ShortcutOverride` (which Qt sends before resolving shortcuts) and acts on the key press that
    follows. `applies(redo)` decides per event whether the key is ours; it must not raise."""

    def __init__(self, stack, applies=lambda _redo: True, parent=None):
        super().__init__(parent)
        self.stack = stack
        self.applies = applies

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 — Qt override
        kind = event.type()
        if kind not in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            return False
        try:
            undo = event.matches(QKeySequence.StandardKey.Undo)
            redo = not undo and event.matches(QKeySequence.StandardKey.Redo)
            if not (undo or redo) or not self.applies(redo):
                return False
            if kind == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            (self.stack.undo if undo else self.stack.redo)()
            return True
        except Exception:  # noqa: BLE001 — an event filter must never raise into Qt
            QgsMessageLog.logMessage(traceback.format_exc(), "Terrain Sketch", Qgis.MessageLevel.Critical)
            return False
