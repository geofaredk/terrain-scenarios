import time
from dataclasses import replace

from helpers import feature, make_grid
from terrain_scenarios.core.engine import FeatureStack
from terrain_scenarios.core.geometry import line_wkb
from terrain_scenarios.core.tools import Mode, Tool


def test_recompute_of_a_500_by_500_window_is_fast():
    """Spec target: < 50 ms on an M-class Mac. The assertion is looser to stay stable on CI."""
    stack = FeatureStack(make_grid(lambda X, Y: 10 + 0.01 * X, rows=1000, cols=1000, cell=0.4))
    wkb = line_wkb([(40.2, 150.2), (80.3, 230.1), (120.1, 190.3), (150.2, 300.2), (180.1, 260.2), (220.3, 350.1)])
    dike = feature(Tool.RAISE_PATH, Mode.PATH, wkb, amount=1.5, width=3.0, slope_n=3.0, reach=10.0)
    stack.update([dike])
    start = time.perf_counter()
    window = stack.update([replace(dike, amount=2.0)])
    elapsed = time.perf_counter() - start
    print(f"window {window.rows}x{window.cols}: {elapsed * 1000:.1f} ms")
    assert window.rows >= 500 and window.cols >= 450
    assert elapsed < 0.25
