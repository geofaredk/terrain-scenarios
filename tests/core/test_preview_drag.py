import time
from dataclasses import replace

import numpy as np

from helpers import feature, flat, make_grid
from terrain_sketch.core.engine import FeatureStack
from terrain_sketch.core.geometry import line_wkb, polygon_wkb
from terrain_sketch.core.operations import apply_feature
from terrain_sketch.core.tools import Mode, Tool


def square(x0, y0, x1, y1):
    return polygon_wkb([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def stack_with_three(rows=60, cols=60):
    pad = feature(Tool.RAISE_FLAT, Mode.AREA, square(5, 5, 55, 55), id="pad", amount=3.0)
    dike = feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(10, 30), (50, 30)]), id="dike",
                   amount=2.0, width=4.0)
    pond = feature(Tool.LOWER_FLAT, Mode.AREA, square(20, 40, 30, 50), id="pond", amount=1.5)
    stack = FeatureStack(make_grid(flat(10), rows=rows, cols=cols))
    stack.update([pad, dike, pond])
    return stack, [pad, dike, pond]


def test_preview_for_matches_a_full_replay():
    stack, features = stack_with_three()
    dragged = replace(features[1], amount=4.0)
    result = stack.preview_for("dike", [features[0], dragged, features[2]])
    expected = stack.original.subgrid(result.window)
    for f in (features[0], dragged, features[2]):
        apply_feature(f, expected)
    assert np.allclose(result.grid.data, expected.data, equal_nan=True)
    # Verify stats keys match between preview_for and full preview
    full_result = stack.preview([features[0], dragged, features[2]])
    assert set(result.stats.keys()) == set(full_result.stats.keys())


def test_preview_for_reuses_the_terrain_under_the_dragged_feature():
    stack, features = stack_with_three()
    for amount in (2.5, 3.0, 3.5):
        stack.preview_for("dike", [features[0], replace(features[1], amount=amount), features[2]])
    key_after = stack._before_key
    stack.preview_for("dike", [features[0], replace(features[1], amount=4.0), features[2]])
    assert stack._before_key == key_after  # the cached base survived every frame of the drag


def test_editing_a_feature_before_the_dragged_one_rebuilds_the_cache():
    stack, features = stack_with_three()
    stack.preview_for("dike", features)
    first = stack._before_key
    moved = replace(features[0], amount=6.0)
    stack.preview_for("dike", [moved, features[1], features[2]])
    assert stack._before_key != first


def test_preview_for_beats_a_full_preview_on_a_large_window():
    stack, features = stack_with_three(rows=400, cols=400)
    # every frame must differ from the COMMITTED amount (2.0); a frame equal to it is a no-op
    # that returns before doing any work, and timing that measures nothing
    dragged = [replace(features[1], amount=a) for a in np.linspace(2.5, 5.0, 12)]

    stack.preview_for("dike", [features[0], dragged[0], features[2]])  # warm the cache

    def best(run) -> float:
        """The fastest of several attempts. A mean would let one scheduler hiccup — a build
        running tests in parallel, say — fail a comparison that is really about the algorithm."""
        times = []
        for d in dragged:
            t0 = time.perf_counter()
            run(d)
            times.append(time.perf_counter() - t0)
        return min(times)

    fast = best(lambda d: stack.preview_for("dike", [features[0], d, features[2]]))
    full = best(lambda d: stack.preview([features[0], d, features[2]]))

    assert fast < full, f"drag path {fast*1000:.1f} ms is not faster than full {full*1000:.1f} ms"
    assert fast < 0.066, f"a drag frame took {fast*1000:.1f} ms, over the 15 fps budget"


def test_preview_for_falls_back_to_a_full_preview_for_a_disabled_feature():
    stack, features = stack_with_three()
    off = replace(features[1], enabled=False)
    result = stack.preview_for("dike", [features[0], off, features[2]])
    assert result is not None
    # the fallback is a real replay of the stack with the disabled feature contributing nothing
    expected = stack.original.subgrid(result.window)
    for f in (features[0], features[2]):
        apply_feature(f, expected)
    assert np.allclose(result.grid.data, expected.data, equal_nan=True)
    assert "dike" not in result.stats


def test_preview_for_returns_none_for_an_unknown_feature():
    stack, features = stack_with_three()
    assert stack.preview_for("nope", features) is None


def test_committing_an_update_drops_the_drag_cache():
    stack, features = stack_with_three()
    stack.preview_for("dike", features)
    assert stack._before_key is not None
    stack.update([features[0], replace(features[1], amount=9.0), features[2]])
    assert stack._before_key is None


def test_a_long_drag_does_not_grow_the_window_cache():
    stack, features = stack_with_three()
    assert len(stack._windows) == 3
    for amount in np.linspace(2.0, 5.0, 40):
        stack.preview_for("dike", [features[0], replace(features[1], amount=float(amount)),
                                   features[2]])
    assert len(stack._windows) == 3  # one entry per committed feature, not one per frame


def test_a_full_preview_does_not_grow_the_window_cache_either():
    stack, features = stack_with_three()
    for amount in np.linspace(2.0, 5.0, 40):
        stack.preview([features[0], replace(features[1], amount=float(amount)), features[2]])
    assert len(stack._windows) == 3


def test_renaming_a_feature_changes_no_terrain_and_no_window():
    stack, features = stack_with_three()
    before = stack.working.data.copy()
    window = stack.update([features[0], replace(features[1], name="Embankment"), features[2]])
    assert window is None
    assert np.array_equal(stack.working.data, before, equal_nan=True)
    assert stack.features[1].name == "Embankment"


def test_terrain_before_the_first_feature_is_the_original():
    stack, features = stack_with_three()
    result = stack.terrain_before("pad", features)
    assert result is not None
    window, grid = result
    # The terrain before the first feature should be the original (unmodified)
    expected = stack.original.subgrid(window)
    assert np.array_equal(grid.data, expected.data, equal_nan=True)


def test_terrain_before_a_later_feature_includes_earlier_ones():
    stack, features = stack_with_three()
    result = stack.terrain_before("pond", features)
    assert result is not None
    window, grid = result
    # The terrain before pond should include pad and dike
    expected = stack.original.subgrid(window)
    apply_feature(features[0], expected)  # pad
    apply_feature(features[1], expected)  # dike
    assert np.allclose(grid.data, expected.data, equal_nan=True)


def test_terrain_before_returns_none_for_unknown_feature():
    stack, features = stack_with_three()
    assert stack.terrain_before("unknown", features) is None


def test_terrain_before_cache_does_not_grow_with_transient_features():
    stack, features = stack_with_three()
    assert len(stack._windows) == 3
    for amount in np.linspace(2.0, 5.0, 40):
        moved = replace(features[1], amount=float(amount))
        stack.terrain_before("pond", [features[0], moved, features[2]])
    assert len(stack._windows) == 3  # should not grow with transient features


def test_terrain_before_a_disabled_feature_excludes_the_features_after_it():
    """A disabled feature is not in `replay`, so stopping at its id never fires. Its reference
    terrain must still be "everything before me", not the whole stack — the profile editor draws
    it for any selected feature, enabled or not."""
    stack, features = stack_with_three()
    off = replace(features[1], enabled=False)
    result = stack.terrain_before("dike", [features[0], off, features[2]])
    assert result is not None
    window, grid = result
    expected = stack.original.subgrid(window)
    apply_feature(features[0], expected)      # the pad only: the pond comes after the dike
    assert np.allclose(grid.data, expected.data, equal_nan=True)
    # and the pond, which comes later, really would have changed this window
    with_pond = stack.original.subgrid(window)
    apply_feature(features[0], with_pond)
    apply_feature(features[2], with_pond)
    assert not np.allclose(grid.data, with_pond.data, equal_nan=True)
