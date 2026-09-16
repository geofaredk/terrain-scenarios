"""Shared layout helper for the drill-in pages (New feature, the feature page): the style's own
page margins, so content keeps a normal gap from the panel edge like every other QGIS panel,
rather than the hard-coded zero margin that used to let it touch the edge (VISUAL c)."""
from __future__ import annotations

from qgis.PyQt.QtWidgets import QLayout, QStyle, QWidget


def apply_page_margins(layout: QLayout, widget: QWidget) -> None:
    """Set `layout`'s margins to `widget`'s own style's layout pixel metrics, so the margin
    follows the platform style instead of a value picked by eye."""
    style = widget.style()
    layout.setContentsMargins(
        style.pixelMetric(QStyle.PixelMetric.PM_LayoutLeftMargin, widget=widget),
        style.pixelMetric(QStyle.PixelMetric.PM_LayoutTopMargin, widget=widget),
        style.pixelMetric(QStyle.PixelMetric.PM_LayoutRightMargin, widget=widget),
        style.pixelMetric(QStyle.PixelMetric.PM_LayoutBottomMargin, widget=widget),
    )
