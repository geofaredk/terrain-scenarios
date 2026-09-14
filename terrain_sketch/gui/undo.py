"""Undo and redo for the feature list (spec §7.4)."""
from __future__ import annotations

from qgis.PyQt.QtGui import QUndoCommand

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
