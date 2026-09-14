"""Remembering panel state between sessions, under the `terrain_sketch/` QgsSettings group."""
from __future__ import annotations

from qgis.core import QgsSettings

GROUP = "terrain_sketch"


def save(key: str, value) -> None:
    """Store one value. Never raises: a settings problem must not cost the user their work."""
    try:
        settings = QgsSettings()
        settings.beginGroup(GROUP)
        settings.setValue(key, value)
        settings.endGroup()
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass


def load(key: str, default=None, kind=None):
    """Read one value back, falling back to `default` when it is missing or unreadable."""
    try:
        settings = QgsSettings()
        settings.beginGroup(GROUP)
        value = settings.value(key, default) if kind is None else settings.value(key, default, type=kind)
        settings.endGroup()
        return value
    except Exception:  # noqa: BLE001
        return default


def save_state(name: str, widget) -> None:
    """Persist a splitter's or window's layout.

    The caller says which method to use by widget kind rather than this module guessing: every
    QWidget has `saveGeometry`, so probing for it would silently store the wrong thing for a
    QSplitter, whose layout lives in `saveState`.
    """
    _save_from(f"{name}/state", widget, "saveState")


def restore_state(name: str, widget) -> bool:
    """Put a splitter's or window's layout back; False when there is nothing usable stored."""
    return _restore(load(f"{name}/state"), widget, "restoreState")


def save_geometry(name: str, widget) -> None:
    """Persist a top-level widget's position and size."""
    _save_from(f"{name}/geometry", widget, "saveGeometry")


def restore_geometry(name: str, widget) -> bool:
    """Put a widget's position and size back; False when there is nothing usable stored."""
    return _restore(load(f"{name}/geometry"), widget, "restoreGeometry")


def _save_from(key: str, widget, method: str) -> None:
    """Ask the widget for its layout and store it. The widget call is inside the guard because a
    PyQt wrapper whose C++ object is gone raises RuntimeError, and these run from Qt callbacks."""
    try:
        save(key, getattr(widget, method)())
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass


def _restore(stored, widget, method: str) -> bool:
    if not stored:
        return False
    try:
        return bool(getattr(widget, method)(stored))
    except Exception:  # noqa: BLE001 — a corrupt blob or a deleted widget must not reach Qt
        return False
