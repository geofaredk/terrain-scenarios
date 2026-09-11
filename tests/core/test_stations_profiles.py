import numpy as np

from terrain_sketch.core.profiles import side_dz
from terrain_sketch.core.stations import stations_offsets, vertex_stations


def test_station_and_signed_offset():
    coords = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
    X = np.array([5.0, 5.0, 12.0, 11.0])
    Y = np.array([2.0, -3.0, 5.0, -1.0])
    station, offset = stations_offsets(coords, X, Y)
    np.testing.assert_allclose(station, [5, 5, 15, 10])
    np.testing.assert_allclose(offset, [-2, 3, 2, np.sqrt(2)])  # left negative, right positive
    np.testing.assert_allclose(vertex_stations(coords), [0, 10, 20])


def test_terminal_slope_goes_down_until_reach():
    dz, inside = side_dz([0, 3, 6, 9], (), slope_n=3, reach=6, direction=-1)
    np.testing.assert_allclose(dz, [0, -1, -2, -3])
    assert inside.tolist() == [True, True, True, False]


def test_break_points_then_upward_slope():
    dz, inside = side_dz([1, 2, 4, 6], ((2.0, 0.5), (4.0, 0.5)), slope_n=2, reach=10, direction=1)
    np.testing.assert_allclose(dz, [0.25, 0.5, 0.5, 1.5])
    assert inside.all()


def test_no_slope_ends_at_last_break():
    _, inside = side_dz([0, 1, 2], (), slope_n=0, reach=10, direction=-1)
    assert inside.tolist() == [True, False, False]
