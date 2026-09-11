"""FeatureStack: the ordered list of features and the windowed recompute of the working DEM."""
from __future__ import annotations

from typing import NamedTuple

from .grid import DemGrid, Window
from .operations import FeatureStats, apply_feature, feature_window, footprint_flags


class Preview(NamedTuple):
    """What `FeatureStack.preview` returns: the changed window, its values and per-feature stats."""

    window: Window
    grid: DemGrid
    stats: dict


class FeatureStack:
    """Holds the untouched `original`, the `working` result and per-feature stats.

    Call `update(features)` with the complete new ordered feature list after every change;
    it recomputes only the cells that can differ and returns that window (or None)."""

    def __init__(self, original: DemGrid):
        self.original = original
        self.working = original.copy()
        self.features: tuple = ()
        self.stats: dict[str, FeatureStats] = {}
        self._windows: dict = {}

    def footprint(self, feature) -> Window | None:
        if feature not in self._windows:
            self._windows[feature] = feature_window(feature, self.original)
        return self._windows[feature]

    def dirty_window(self, features) -> Window | None:
        """Union of the footprints of every feature that was added, removed, edited,
        toggled or moved relative to overlapping features."""
        old = {f.id: f for f in self.features}
        new = {f.id: f for f in features}
        common = old.keys() & new.keys()
        old_before = _predecessors(self.features, common)
        new_before = _predecessors(features, common)
        dirty = None
        for fid in old.keys() | new.keys():
            o, n = old.get(fid), new.get(fid)
            if o is not None and o == n and old_before[fid] == new_before[fid]:
                continue
            for f in (o, n):
                if f is not None and f.enabled:
                    w = self.footprint(f)
                    if w is not None:
                        dirty = w.union(dirty)
        return dirty

    def closure(self, window: Window, features) -> tuple[Window, list]:
        """Grow `window` until it fully contains every enabled feature overlapping it, so the
        reference elevations of those features are recomputed too. Returns the window and
        the features to replay, in list order."""
        active = [(f, self.footprint(f)) for f in features if f.enabled]
        grown = True
        while grown:
            grown = False
            for _, w in active:
                if w is not None and w.intersects(window) and not window.contains(w):
                    window = window.union(w)
                    grown = True
        return window, [f for f, w in active if w is not None and w.intersects(window)]

    def compute(self, features, window: Window) -> tuple[DemGrid, dict]:
        """Replay `features` in order over `window`, starting from the original terrain."""
        grid = self.original.subgrid(window)
        stats = {f.id: apply_feature(f, grid) for f in features}
        return grid, stats

    def preview(self, features) -> Preview | None:
        """Result of `features` for the changed window, without changing the stack."""
        features = tuple(features)
        dirty = self.dirty_window(features)
        if dirty is None:
            return None
        window, replay = self.closure(dirty, features)
        grid, stats = self.compute(replay, window)
        return Preview(window, grid, stats)

    def update(self, features) -> Window | None:
        """Make `features` the current list and recompute; returns the changed window."""
        features = tuple(features)
        dirty = self.dirty_window(features)
        self.features = features
        self._refresh_bookkeeping()
        if dirty is None:
            return None
        window, replay = self.closure(dirty, features)
        grid, stats = self.compute(replay, window)
        self.working.data[window.slices] = grid.data
        self.stats.update(stats)
        return window

    def _refresh_bookkeeping(self) -> None:
        current = set(self.features)
        self._windows = {f: w for f, w in self._windows.items() if f in current}
        ids = {f.id for f in self.features}
        self.stats = {k: v for k, v in self.stats.items() if k in ids}
        for f in self.features:
            if not f.enabled:
                self.stats[f.id] = FeatureStats()
            elif self.footprint(f) is None:
                self.stats[f.id] = FeatureStats(flags=footprint_flags(f))


def _predecessors(features, common) -> dict:
    out, seen = {}, []
    for f in features:
        if f.id in common:
            out[f.id] = frozenset(seen)
            seen.append(f.id)
    return out
