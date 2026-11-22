import json
from dataclasses import replace

import pytest

from terrain_sketch.core.geometry import line_wkb, polygon_wkb
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.model.feature import TerrainFeature, new_feature

TRIANGLE = polygon_wkb([(0, 0), (1, 0), (1, 1)])


def test_round_trip_through_json_dict():
    f = TerrainFeature(id="a", name="Dike", tool=Tool.RAISE_PATH, mode=Mode.PATH,
                       geometry_wkb=line_wkb([(0, 0), (1, 1)]), cross_left=((2.0, -0.5),),
                       long_profile=((0.0, 10.0), (1.4, 11.0)))
    d = json.loads(json.dumps(f.to_dict()))
    assert TerrainFeature.from_dict(d) == f
    pond = TerrainFeature(id="b", name="Pond", tool=Tool.LOWER_FLAT, mode=Mode.AREA, geometry_wkb=TRIANGLE,
                          section_line=line_wkb([(-1, 0.5), (2, 0.5)]))
    assert TerrainFeature.from_dict(json.loads(json.dumps(pond.to_dict()))) == pond


def test_new_feature_defaults():
    pond = new_feature(Tool.LOWER_FLAT, Mode.AREA, TRIANGLE, cell_size=0.4)
    assert pond.slopes_inside and pond.width == 1.2 and pond.name == "Lower flat" and len(pond.id) == 32
    pad = new_feature(Tool.RAISE_FLAT, Mode.AREA, TRIANGLE, cell_size=0.1)
    assert not pad.slopes_inside and pad.width == 1.0
    assert not new_feature(Tool.LOWER_FLAT, Mode.PATH, line_wkb([(0, 0), (1, 0)]), 1.0).slopes_inside


def test_tool_mode_mismatch_is_rejected():
    with pytest.raises(ValueError):
        TerrainFeature(id="x", name="x", tool=Tool.RAISE_PATH, mode=Mode.AREA, geometry_wkb=TRIANGLE)


def test_features_compare_and_hash_by_value():
    f = new_feature(Tool.ADD, Mode.AREA, TRIANGLE, 1.0)
    assert f == replace(f) and hash(f) == hash(replace(f))
    assert f != replace(f, amount=2.0)


def test_list_fields_are_normalised_to_hashable_tuples():
    f = new_feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(0, 0), (1, 0)]), 1.0)
    g = replace(f, cross_left=[[2, -0.5]], long_profile=[[0, 10], [1, 11]])
    assert g.cross_left == ((2.0, -0.5),) and g.long_profile == ((0.0, 10.0), (1.0, 11.0))
    assert isinstance(hash(g), int)


def test_style_round_trips_through_the_dict():
    f = replace(new_feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(0, 0), (5, 0)]), 1.0), style="<symbol/>")
    assert TerrainFeature.from_dict(json.loads(json.dumps(f.to_dict()))).style == "<symbol/>"


def test_a_dict_without_style_is_unstyled():
    d = new_feature(Tool.RAISE_PATH, Mode.PATH, line_wkb([(0, 0), (5, 0)]), 1.0).to_dict()
    del d["style"]
    assert TerrainFeature.from_dict(d).style is None
