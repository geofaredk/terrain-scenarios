import numpy as np
import pytest
from osgeo import ogr

from terrain_sketch.core.geometry import (corridor, densify, envelope, is_line, line_coords,
                                          line_wkb, multi_wkb, polygon_wkb, split_parts)


def test_split_parts_handles_multi_and_rejects_points():
    wkb = multi_wkb([line_wkb([(0, 0), (1, 1)]), line_wkb([(2, 2), (3, 3)])])
    parts = split_parts(wkb)
    assert len(parts) == 2 and all(is_line(p) for p in parts)
    assert not is_line(split_parts(polygon_wkb([(0, 0), (1, 0), (1, 1)]))[0])
    with pytest.raises(ValueError):
        split_parts(bytes(ogr.CreateGeometryFromWkt("POINT (1 1)").ExportToWkb()))


def test_corridor_has_flat_end_caps():
    c = corridor(split_parts(line_wkb([(0, 0), (10, 0)]))[0], 2.0)
    assert c.GetArea() == pytest.approx(20.0)
    assert envelope(c) == pytest.approx((0, -1, 10, 1))


def test_line_coords_drops_repeated_points():
    line = split_parts(line_wkb([(0, 0), (0, 0), (5, 0), (5, 0), (5, 5)]))[0]
    np.testing.assert_array_equal(line_coords(line), [[0, 0], [5, 0], [5, 5]])


def test_densify_keeps_vertices_and_max_spacing():
    pts = densify(np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 4.0]]), 3.0)
    assert pts[0].tolist() == [0, 0] and pts[-1].tolist() == [10, 4]
    assert [10.0, 0.0] in pts.tolist()
    assert np.hypot(*np.diff(pts, axis=0).T).max() <= 3.0 + 1e-9
