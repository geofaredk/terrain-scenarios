import pytest

from qgis_helpers import UTM, line_through, sample, start_session
from terrain_sketch.core.tools import Mode, Tool


def test_dragging_a_profile_previews_without_committing(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    before = sample(c.layers.working, 20, 20)
    previews = []
    c.previewUpdated.connect(lambda fid, p: previews.append(p))
    c.preview(dike.id, amount=5.0)
    assert len(previews) == 1
    assert c.feature(dike.id).amount == 1.0            # nothing was committed
    assert sample(c.layers.working, 20, 20) == before  # the working DEM is untouched
    # change is measured against the ORIGINAL terrain, not the working DEM: 10 m ground, 5 m crest
    assert previews[0].change.max() == pytest.approx(5.0, abs=0.2)


def test_previews_are_throttled_to_the_latest_request(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    previews = []
    c.previewUpdated.connect(lambda fid, p: previews.append(p))
    for amount in (2.0, 3.0, 4.0, 5.0):
        c.preview(dike.id, amount=amount)
    assert len(previews) == 1          # the first ran; the rest collapsed into one pending call
    assert c._pending is not None


def test_committing_clears_the_preview(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    cleared = []
    c.previewCleared.connect(lambda: cleared.append(True))
    c.preview(dike.id, amount=5.0)
    c.update_feature(dike.id, amount=5.0)
    assert cleared and c._pending is None
    assert sample(c.layers.working, 20, 20) == pytest.approx(15.0)


def test_a_preview_for_a_deleted_feature_is_ignored(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.delete_feature(dike.id)
    c.preview(dike.id, amount=5.0)     # must not raise: this runs inside a Qt callback
    assert c._pending is None


def test_reshaping_a_path_carries_its_custom_long_profile_along(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 20, 20), UTM)
    c.update_feature(dike.id, long_profile=((0.0, 12.0), (15.0, 13.0)))
    c.set_geometry(dike.id, line_through(5, 20, 35, 20), UTM)   # the path doubles in length
    stations = [s for s, _z in c.feature(dike.id).long_profile]
    assert stations == pytest.approx([0.0, 30.0])
