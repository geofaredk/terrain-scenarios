from dataclasses import replace

import numpy as np
import pytest

from helpers import feature, flat, make_grid, tilted
import terrain_scenarios.core.engine as engine_module
from terrain_scenarios.core.engine import FeatureStack
from terrain_scenarios.core.geometry import line_wkb, polygon_wkb
from terrain_scenarios.core.grid import DemGrid
from terrain_scenarios.core.operations import FLAG_OUTSIDE, apply_feature
from terrain_scenarios.core.tools import TOOL_INFO, Mode, PixelMode, Tool
from terrain_scenarios.core.volumes import total_cut_fill


def square(x0, y0, x1, y1):
    return polygon_wkb([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def oracle(original, features):
    """Straightforward full-grid replay, independent of the engine's windowing."""
    grid = original.copy()
    for f in features:
        if f.enabled:
            apply_feature(f, grid)
    return grid.data


def test_update_changes_only_the_returned_window():
    stack = FeatureStack(make_grid(flat(10), rows=60, cols=60))
    window = stack.update([feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3), amount=1.0)])
    rows, cols = np.nonzero(stack.working.data != stack.original.data)
    assert window.row0 <= rows.min() and rows.max() < window.row1
    assert window.col0 <= cols.min() and cols.max() < window.col1
    assert (stack.original.data == 10).all()
    assert stack.stats["f1"].fill == pytest.approx(25.0)


def test_unchanged_list_needs_no_recompute():
    stack = FeatureStack(make_grid(flat(10)))
    f = feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3))
    stack.update([f])
    assert stack.update([f]) is None


def test_a_style_only_change_recomputes_nothing():
    stack = FeatureStack(make_grid(flat(10)))
    f = feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3))
    stack.update([f])
    assert stack.update([replace(f, style="<symbol/>")]) is None


def test_toggle_and_delete_restore_the_original():
    stack = FeatureStack(make_grid(tilted))
    f = feature(Tool.RAISE_FLAT, Mode.AREA, square(10.3, 10.3, 20.3, 20.3))
    stack.update([f])
    assert (stack.working.data != stack.original.data).any()
    stack.update([replace(f, enabled=False)])
    np.testing.assert_array_equal(stack.working.data, stack.original.data)
    stack.update([f])
    stack.update([])
    np.testing.assert_array_equal(stack.working.data, stack.original.data)
    assert stack.stats == {}


def test_order_matters_for_overlapping_features():
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, square(10.3, 10.3, 30.3, 30.3), id="pad", amount=2.0, slope_n=0.0)
    ditch = feature(Tool.LOWER_PATH, Mode.PATH, line_wkb([(5.25, 20.25), (34.75, 20.25)]), id="ditch",
                    amount=1.0, slope_n=0.0)
    ditch_last = FeatureStack(make_grid(flat(10)))
    ditch_last.update([pad, ditch])
    pad_last = FeatureStack(make_grid(flat(10)))
    pad_last.update([ditch, pad])
    assert ditch_last.working.data[19, 20] == pytest.approx(9.0)
    assert pad_last.working.data[19, 20] == pytest.approx(12.0)


def test_reference_elevations_follow_earlier_features():
    """A dike starting on a pad is recomputed when the pad's height changes."""
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, square(4.3, 16.3, 8.3, 24.3), id="pad", amount=1.0, slope_n=0.0)
    dike = feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(6.25, 20.25), (34.75, 20.25)]), id="dike",
                   amount=0.5, slope_n=0.0)
    stack = FeatureStack(make_grid(flat(10)))
    stack.update([pad, dike])
    assert stack.working.data[19, 20] == pytest.approx(11.0, abs=1e-3)
    stack.update([replace(pad, amount=3.0), dike])
    assert stack.working.data[19, 20] == pytest.approx(12.0, abs=1e-3)
    np.testing.assert_allclose(stack.working.data, oracle(stack.original, stack.features))


def test_a_failing_update_leaves_the_stack_unchanged(monkeypatch):
    stack = FeatureStack(make_grid(flat(10)))
    f = feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3), amount=1.0)
    stack.update([f])
    features_before = stack.features
    working_before = stack.working.data.copy()

    def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(engine_module, "apply_feature", boom)
    with pytest.raises(RuntimeError):
        stack.update([replace(f, amount=2.0)])
    assert stack.features == features_before
    np.testing.assert_array_equal(stack.working.data, working_before)


def test_preview_does_not_change_the_stack():
    stack = FeatureStack(make_grid(flat(10)))
    preview = stack.preview([feature(Tool.ADD, Mode.AREA, square(10.3, 10.3, 15.3, 15.3))])
    assert (preview.grid.data > 10).any()
    assert preview.stats["f1"].fill == pytest.approx(25.0)
    assert (stack.working.data == 10).all() and stack.features == ()


def test_feature_outside_the_dem_is_flagged():
    stack = FeatureStack(make_grid(flat(10)))
    assert stack.update([feature(Tool.ADD, Mode.PATH, line_wkb([(500, 500), (600, 600)]))]) is None
    assert stack.stats["f1"].flags == (FLAG_OUTSIDE,)


def random_feature(rng, i, size):
    tool = list(Tool)[rng.integers(len(Tool))]
    modes = TOOL_INFO[tool].modes
    mode = modes[rng.integers(len(modes))]
    if mode is Mode.PATH:
        wkb = line_wkb(rng.uniform(3, size - 3, (int(rng.integers(2, 5)), 2)))
    else:
        cx, cy = rng.uniform(8, size - 8, 2)
        radius = rng.uniform(2, 6)
        angles = np.sort(rng.uniform(0, 2 * np.pi, 6))
        wkb = polygon_wkb([(cx + radius * np.cos(a), cy + radius * np.sin(a)) for a in angles])
    return feature(tool, mode, wkb, id=f"f{i}", amount=float(rng.uniform(0.2, 3)),
                   width=float(rng.uniform(1, 4)), slope_n=float(rng.choice([0.0, 1.5, 3.0])),
                   reach=float(rng.uniform(2, 8)),
                   slopes_inside=bool(rng.integers(2)) if mode is Mode.AREA else False,
                   pixel_mode=list(PixelMode)[rng.integers(len(PixelMode))])


@pytest.mark.parametrize("seed", range(6))
def test_windowed_updates_match_full_replay(seed):
    rng = np.random.default_rng(seed)
    size = 60
    stack = FeatureStack(make_grid(lambda X, Y: 10 + 0.05 * X + 2 * np.sin(X / 7) * np.cos(Y / 5),
                                   rows=size, cols=size))
    features = [random_feature(rng, i, size) for i in range(int(rng.integers(1, 9)))]
    stack.update(features)
    np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4)
    for step in range(8):
        action = int(rng.integers(5))
        if action == 0 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], amount=float(rng.uniform(0.2, 3)))
        elif action == 1 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], enabled=not features[k].enabled)
        elif action == 2 and len(features) > 1:
            i, j = rng.choice(len(features), 2, replace=False)
            features[i], features[j] = features[j], features[i]
        elif action == 3 and features:
            features.pop(int(rng.integers(len(features))))
        else:
            features.append(random_feature(rng, 100 + step, size))
        stack.update(features)
        np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4,
                                   err_msg=f"seed {seed} step {step}")


def _assert_totals_match(stack, label=None):
    """`stack.totals` is maintained incrementally by `update()`; it must always agree with a
    from-scratch `total_cut_fill` over the whole grid, not just the windows `update()` touched."""
    expected_cut, expected_fill = total_cut_fill(stack.original, stack.working)
    cut, fill = stack.totals
    for actual, expected in ((cut, expected_cut), (fill, expected_fill)):
        assert actual >= 0.0, label                     # clamped: never a negative running total
        if expected == 0.0:
            assert actual == pytest.approx(0.0, abs=1e-6), label
        else:
            assert actual == pytest.approx(expected, rel=1e-6), label


def test_a_new_stack_has_zero_running_totals():
    stack = FeatureStack(make_grid(flat(10)))
    assert stack.totals == (0.0, 0.0)


@pytest.mark.parametrize("seed", range(6))
def test_running_totals_match_a_full_recompute_through_adds_edits_disables_reorders_and_deletes(seed):
    rng = np.random.default_rng(seed)
    size = 60
    stack = FeatureStack(make_grid(lambda X, Y: 10 + 0.05 * X + 2 * np.sin(X / 7) * np.cos(Y / 5),
                                   rows=size, cols=size))
    features = [random_feature(rng, i, size) for i in range(int(rng.integers(1, 9)))]
    stack.update(features)
    _assert_totals_match(stack, (seed, "initial"))
    for step in range(8):
        action = int(rng.integers(5))
        if action == 0 and features:                    # edit
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], amount=float(rng.uniform(0.2, 3)))
        elif action == 1 and features:                   # disable/enable
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], enabled=not features[k].enabled)
        elif action == 2 and len(features) > 1:           # reorder
            i, j = rng.choice(len(features), 2, replace=False)
            features[i], features[j] = features[j], features[i]
        elif action == 3 and features:                    # delete
            features.pop(int(rng.integers(len(features))))
        else:                                              # add
            features.append(random_feature(rng, 100 + step, size))
        stack.update(features)
        _assert_totals_match(stack, (seed, step))


_X0, _Y0, _CELL, _N = 612345.6, 6178901.2, 0.4, 60


def _realistic_grid():
    """North-up grid with a non-integer, sub-metre origin and 0.4 m cells."""
    gt = (_X0, _CELL, 0.0, _Y0 + _N * _CELL, 0.0, -_CELL)
    xs = np.arange(_N) + 0.5
    ys = _N - (np.arange(_N) + 0.5)
    X, Y = np.meshgrid(xs, ys)
    data = (10 + 0.05 * X + 2 * np.sin(X / 7) * np.cos(Y / 5)).astype(np.float32)
    return DemGrid.from_array(data, gt)


def _to_world(u, v):
    return _X0 + u * _CELL, _Y0 + v * _CELL


def _snapped_random_feature(rng, i):
    """Like `random_feature`, but on the realistic grid: coordinates snapped to half cells
    (so they land exactly on cell edges/centres) and widths/reach scaled by the cell size."""
    tool = list(Tool)[rng.integers(len(Tool))]
    modes = TOOL_INFO[tool].modes
    mode = modes[rng.integers(len(modes))]
    snap = lambda a: np.round(a * 2) / 2  # noqa: E731
    if mode is Mode.PATH:
        pts = snap(rng.uniform(3, _N - 3, (int(rng.integers(2, 5)), 2)))
        wkb = line_wkb([_to_world(*p) for p in pts])
    else:
        cx, cy = rng.uniform(8, _N - 8, 2)
        radius = rng.uniform(2, 6)
        angles = np.sort(rng.uniform(0, 2 * np.pi, 6))
        pts = snap(np.c_[cx + radius * np.cos(angles), cy + radius * np.sin(angles)])
        wkb = polygon_wkb([_to_world(*p) for p in pts])
    return feature(tool, mode, wkb, id=f"f{i}", amount=float(rng.uniform(0.2, 3)),
                   width=float(rng.uniform(1, 4)) * _CELL, slope_n=float(rng.choice([0.0, 1.5, 3.0])),
                   reach=float(rng.uniform(2, 8)) * _CELL,
                   slopes_inside=bool(rng.integers(2)) if mode is Mode.AREA else False,
                   pixel_mode=list(PixelMode)[rng.integers(len(PixelMode))])


@pytest.mark.parametrize("seed", range(12))
def test_windowed_updates_match_full_replay_on_a_realistic_grid(seed):
    """Same property as test_windowed_updates_match_full_replay, but on a non-integer,
    sub-metre-cell geotransform where a ULP-level offset between a window taken through a
    subgrid and one taken directly can flip GDAL rasterization on boundaries snapped to
    cell edges/centres (C1)."""
    rng = np.random.default_rng(seed)
    stack = FeatureStack(_realistic_grid())
    features = [_snapped_random_feature(rng, i) for i in range(int(rng.integers(1, 9)))]
    stack.update(features)
    np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4)
    for step in range(8):
        action = int(rng.integers(5))
        if action == 0 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], amount=float(rng.uniform(0.2, 3)))
        elif action == 1 and features:
            k = int(rng.integers(len(features)))
            features[k] = replace(features[k], enabled=not features[k].enabled)
        elif action == 2 and len(features) > 1:
            i, j = rng.choice(len(features), 2, replace=False)
            features[i], features[j] = features[j], features[i]
        elif action == 3 and features:
            features.pop(int(rng.integers(len(features))))
        else:
            features.append(_snapped_random_feature(rng, 100 + step))
        stack.update(features)
        np.testing.assert_allclose(stack.working.data, oracle(stack.original, features), atol=1e-4,
                                   err_msg=f"seed {seed} step {step}")
