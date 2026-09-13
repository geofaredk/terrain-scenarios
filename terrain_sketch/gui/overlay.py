"""A canvas item that draws the drag preview: cut and fill over the window being changed."""
from __future__ import annotations

import numpy as np
from qgis.core import QgsPointXY, QgsRectangle
from qgis.gui import QgsMapCanvasItem
from qgis.PyQt.QtCore import QRectF
from qgis.PyQt.QtGui import QImage

FILL = (230, 140, 60)   # warm: the terrain rose
CUT = (60, 120, 200)    # cool: the terrain was cut
FULL_ALPHA_AT = 1.0     # metres of change that reach full opacity
MAX_ALPHA = 200


class PreviewOverlay(QgsMapCanvasItem):
    """Paints a change image georeferenced over the map while a profile handle is dragged.

    It lives on the canvas, not in the layer tree: a preview is uncommitted, so it must not
    look like one of the session's layers or survive the drag that made it.
    """

    def __init__(self, canvas, crs_transform=None):
        super().__init__(canvas)
        self.canvas = canvas
        self.crs_transform = crs_transform
        self.image: QImage | None = None
        self.bounds: QgsRectangle | None = None
        self.setZValue(100)
        self.hide()

    def show_change(self, bounds, change) -> None:
        """`bounds` is (xmin, ymin, xmax, ymax) in the DEM CRS; `change` is new minus original."""
        image = change_image(change)
        if image is None:
            self.clear()
            return
        self.image = image
        self.bounds = self._to_canvas_crs(QgsRectangle(*bounds))
        self.updatePosition()
        self.show()
        self.update()

    def clear(self) -> None:
        self.image, self.bounds = None, None
        self.hide()

    def dispose(self) -> None:
        """Take the item off the canvas; call before dropping the reference."""
        self.clear()
        scene = self.canvas.scene()
        if scene is not None and self.scene() == scene:
            scene.removeItem(self)

    def updatePosition(self) -> None:  # noqa: N802 — Qt/QGIS override
        if self.bounds is not None:
            self.setRect(self.bounds)

    def paint(self, painter, option=None, widget=None) -> None:
        if self.image is None or self.bounds is None:
            return
        painter.drawImage(self._target_rect(), self.image)

    def _target_rect(self) -> QRectF:
        """The item's own rectangle in canvas pixels, which is what setRect gave us."""
        top_left = self.toCanvasCoordinates(QgsPointXY(self.bounds.xMinimum(),
                                                       self.bounds.yMaximum())) - self.pos()
        bottom_right = self.toCanvasCoordinates(QgsPointXY(self.bounds.xMaximum(),
                                                           self.bounds.yMinimum())) - self.pos()
        return QRectF(top_left, bottom_right)

    def _to_canvas_crs(self, rectangle: QgsRectangle) -> QgsRectangle:
        if self.crs_transform is None:
            return rectangle
        return self.crs_transform.transformBoundingBox(rectangle)


def change_image(change) -> QImage | None:
    """An RGBA image of a change array: warm where it rose, cool where it was cut.

    Opacity grows with the size of the change so a 5 cm shave stays faint and a 2 m dike reads
    strongly; cells that did not change at all stay fully transparent.
    """
    values = np.asarray(change, dtype=np.float32)
    if values.ndim != 2 or values.size == 0:
        return None
    magnitude = np.abs(np.nan_to_num(values, nan=0.0))
    if not np.any(magnitude > 0):
        return None
    alpha = np.clip(magnitude / FULL_ALPHA_AT, 0.0, 1.0) * MAX_ALPHA
    rgba = np.zeros(values.shape + (4,), dtype=np.uint8)
    rising = np.nan_to_num(values, nan=0.0) > 0
    for channel in range(3):
        rgba[..., channel] = np.where(rising, FILL[channel], CUT[channel])
    rgba[..., 3] = alpha.astype(np.uint8)
    rgba = np.ascontiguousarray(rgba)
    rows, cols = values.shape
    image = QImage(rgba.data, cols, rows, 4 * cols, QImage.Format.Format_RGBA8888)
    return image.copy()  # detach from the numpy buffer before it goes out of scope
