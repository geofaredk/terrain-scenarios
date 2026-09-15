"""Remembering panel state between sessions, under the `terrain_sketch/` QgsSettings group."""
from __future__ import annotations

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt

GROUP = "terrain_sketch"
DOCK_AREAS = (Qt.DockWidgetArea.LeftDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea,
              Qt.DockWidgetArea.TopDockWidgetArea, Qt.DockWidgetArea.BottomDockWidgetArea)


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


def remember_collapsed(name: str, box, collapsed: bool = False) -> None:
    """Keep a QgsCollapsibleGroupBox's collapsed state under the plugin's group, starting `collapsed` until
    the user changes it. Left to itself the box saves under its own `QgsCollapsibleGroupBox/…` key, where the
    plugin can neither find nor clear it."""
    try:
        box.setSaveCollapsedState(False)
        box.setCollapsed(bool(load(f"{name}/collapsed", collapsed, bool)))
        box.collapsedStateChanged.connect(lambda collapsed: save(f"{name}/collapsed", bool(collapsed)))
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass


def save_dock(name: str, dock, window) -> None:
    """Remember where a panel is in `window`: its dock area, whether it floats, and its size — or, when it
    floats, its position too. A panel that is not in the window at all (being removed) changes nothing."""
    try:
        area = window.dockWidgetArea(dock)
        if dock.isFloating():
            save(f"{name}/floating", True)
            save_geometry(name, dock)
        elif area in DOCK_AREAS:
            save(f"{name}/floating", False)
            save(f"{name}/area", int(area.value))
            save(f"{name}/width", dock.width())
            save(f"{name}/height", dock.height())
    except Exception:  # noqa: BLE001 — runs from dock signals and unload
        pass


def dock_area(name: str, default):
    """The dock area a panel was last in, or `default`."""
    try:
        area = Qt.DockWidgetArea(int(load(f"{name}/area", int(default.value), int)))
    except Exception:  # noqa: BLE001 — a value from an older or hand-edited profile
        return default
    return area if area in DOCK_AREAS else default


def restore_dock(name: str, dock, window) -> None:
    """Put a panel back the way it was, once it has been added to `window`: floating where it floated, or
    docked at the width (side areas) or height (top and bottom) it had."""
    try:
        if load(f"{name}/floating", False, bool):
            dock.setFloating(True)
            restore_geometry(name, dock)
            return
        across = window.dockWidgetArea(dock) in (Qt.DockWidgetArea.LeftDockWidgetArea,
                                                 Qt.DockWidgetArea.RightDockWidgetArea)
        size = load(f"{name}/width" if across else f"{name}/height", 0, int)
        if size > 0:
            window.resizeDocks([dock], [size], Qt.Orientation.Horizontal if across else Qt.Orientation.Vertical)
    except Exception:  # noqa: BLE001 — persistence is a convenience, never a failure path
        pass
