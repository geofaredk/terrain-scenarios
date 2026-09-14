"""The Volumes panel: what the numbers say, and when Storage is shown at all."""
import numpy as np
import pytest

from qgis_helpers import UTM, line_through, square, start_session
from terrain_sketch.core.tools import TOOL_INFO, Mode, Tool, reports_storage
from terrain_sketch.gui.help_texts import FLAG_TEXTS, NO_VOLUME_YET, SCENARIO_TOTALS, VOLUME_STORAGE_NOTE, cubic_metres
from terrain_sketch.gui.properties_page import PropertiesPage


def test_a_raised_dike_reports_its_fill_and_no_cut(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=2.0, width=6.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)

    stats = c.stats(dike.id)
    assert stats.fill > 0.0
    assert page.fill_value.text() == cubic_metres(stats.fill)
    assert page.cut_value.text() == cubic_metres(0.0)


def test_a_dug_pond_reports_its_cut_and_its_storage(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    c.update_feature(pond.id, amount=1.5)
    page = PropertiesPage(c)
    page.show_feature(pond.id)

    stats = c.stats(pond.id)
    assert stats.cut > 0.0 and stats.storage is not None
    assert page.cut_value.text() == cubic_metres(stats.cut)
    assert page.storage_value.text() == f"≈ {cubic_metres(stats.storage)} {VOLUME_STORAGE_NOTE}"


def test_storage_is_hidden_for_a_tool_that_cannot_hold_water(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    page = PropertiesPage(c)

    page.show_feature(pond.id)
    assert page.volume_form.isRowVisible(page.storage_value)
    page.show_feature(dike.id)
    assert not page.volume_form.isRowVisible(page.storage_value)
    page.show_feature(pond.id)
    assert page.volume_form.isRowVisible(page.storage_value)   # and it comes back


def test_the_storage_line_wraps_instead_of_widening_the_page(tmp_path):
    """The Storage value (`≈ 128 m³ below the lowest rim point (static, no inflow routing)`) is
    long prose, not a number to keep on one line — without word wrap it forces the whole page
    much wider whenever a pond (which shows Storage) is selected instead of a dike (which does
    not)."""
    c = start_session(tmp_path)
    # The dike sits away from the pond (row 5 vs. the pond's rows 10-25): overlapping them would
    # raise the ground the pond is dug into and leave it without a rim, so Storage would read
    # "—" instead of the long line this is about.
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 5, 34, 5), UTM)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    c.update_feature(pond.id, amount=1.5)
    assert c.stats(pond.id).storage is not None      # otherwise this is not exercising the long line

    def width_for(fid) -> int:
        # A fresh page per feature: reusing one and switching `show_feature` mid-test leaves a
        # once-activated Qt layout that does not widen back out for a later, wider selection in
        # this offscreen test platform — unlike a real docked panel, which reflows on every resize.
        page = PropertiesPage(c)
        page.show()
        page.show_feature(fid)
        page.layout().invalidate()
        page.layout().activate()
        return page.minimumSizeHint().width()

    dike_width = width_for(dike.id)
    pond_width = width_for(pond.id)
    assert pond_width <= dike_width + 40, (dike_width, pond_width)


def test_selecting_another_feature_shows_its_own_problems(tmp_path):
    """The Volumes group must not take the place of the problem check when a feature is shown."""
    c = start_session(tmp_path)
    runs_off = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 60, 20), UTM)
    inside = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 30, 34, 30), UTM)
    flags = c.stats(runs_off.id).flags
    assert flags and not c.stats(inside.id).flags
    page = PropertiesPage(c)
    page.show()

    page.show_feature(runs_off.id)
    assert page.problems.isVisible() and FLAG_TEXTS[flags[0]] in page.problems.text()
    page.show_feature(inside.id)
    assert not page.problems.isVisible()
    page.show_feature(runs_off.id)
    assert page.problems.isVisible()


def test_interpolate_shows_storage_for_an_area_but_not_along_a_path(tmp_path):
    c = start_session(tmp_path)
    strip = c.add_drawn(Tool.INTERPOLATE, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    patch = c.add_drawn(Tool.INTERPOLATE, Mode.AREA, square(10, 10, 25, 25), UTM)
    page = PropertiesPage(c)
    page.show_feature(strip.id)
    assert not page.volume_form.isRowVisible(page.storage_value)   # a row that could only ever say "—"
    page.show_feature(patch.id)
    assert page.volume_form.isRowVisible(page.storage_value)


def test_the_panel_and_the_engine_agree_on_which_features_have_storage(tmp_path):
    """The row is shown by `reports_storage`; the figure is computed by the engine. A feature the
    engine gives storage to must never have its row hidden — otherwise the panel computes a
    number nobody sees while showing `NO_VOLUME_YET` in its place. `reports_storage` is allowed
    to show the row for a feature the engine happens to give no storage (a pond with no rim, say);
    this only checks the direction that would otherwise hide a real figure."""
    c = start_session(tmp_path, np.pad(np.full((20, 20), 5.0, np.float32), 10, constant_values=10.0))
    shapes = {Mode.PATH: line_through(5, 20, 34, 20), Mode.AREA: square(12, 12, 27, 27)}
    for tool, info in TOOL_INFO.items():
        for mode in info.modes:
            feature = c.add_drawn(tool, mode, shapes[mode], UTM)
            c.update_feature(feature.id, amount=1.0)
            has_storage = c.stats(feature.id).storage is not None
            assert has_storage <= reports_storage(tool, mode), (tool, mode)
            c.delete_feature(feature.id)


def test_the_numbers_follow_an_edit(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=1.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    before = page.fill_value.text()

    c.update_feature(dike.id, amount=3.0)
    assert page.fill_value.text() != before
    assert page.fill_value.text() == cubic_metres(c.stats(dike.id).fill)


def test_the_whole_scenario_line_adds_the_features_up(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 5, 34, 5), UTM)
    c.update_feature(dike.id, amount=2.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    one_feature = page.totals_value.text()

    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 20, 25, 33), UTM)
    c.update_feature(pond.id, amount=1.5)
    page.show_feature(dike.id)                      # still looking at the dike
    assert page.fill_value.text() == cubic_metres(c.stats(dike.id).fill)
    assert page.totals_value.text() != one_feature  # but the totals grew
    cut, fill = c.totals()
    assert cut > 0.0 and fill > 0.0
    assert page.totals_value.text() == SCENARIO_TOTALS.format(fill=cubic_metres(fill), cut=cubic_metres(cut))


def test_a_disabled_feature_leaves_nothing_in_the_totals(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=2.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert c.totals() != (0.0, 0.0)

    c.update_feature(dike.id, enabled=False)
    assert c.totals() == (0.0, 0.0)
    assert page.totals_value.text() == SCENARIO_TOTALS.format(fill=cubic_metres(0.0), cut=cubic_metres(0.0))


def test_a_refresh_volumes_failure_is_logged_not_raised(tmp_path, monkeypatch):
    """`_refresh_volumes` runs from `featuresChanged`, a Qt signal — an exception escaping it
    takes QGIS down, the same rule the engine and the file/layer writes in `_set` already
    follow."""
    import terrain_sketch.gui.properties_page as properties_page_module

    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)

    log = []
    monkeypatch.setattr(properties_page_module.QgsMessageLog, "logMessage",
                        staticmethod(lambda text, *a, **kw: log.append(text)))

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(c, "totals", boom)
    page._refresh_volumes()          # must not raise

    assert log and "RuntimeError" in log[-1]


@pytest.mark.parametrize("value, expected", [
    (0.0, "0.00 m³"), (0.5, "0.50 m³"), (1.0, "1.0 m³"), (99.94, "99.9 m³"),
    (100.0, "100 m³"), (12345.6, "12,346 m³"), (None, NO_VOLUME_YET)])
def test_volumes_are_written_the_way_a_reader_expects(value, expected):
    assert cubic_metres(value) == expected


@pytest.mark.parametrize("value", [-0.0, -0.004, -0.0049])
def test_a_volume_that_rounds_to_zero_never_shows_a_minus_sign(value):
    assert cubic_metres(value) == "0.00 m³"


def test_a_volume_that_really_is_negative_keeps_its_sign():
    assert cubic_metres(-5.0) == "-5.0 m³"       # a genuine negative is a bug worth seeing
    assert cubic_metres(-0.49) == "-0.49 m³"     # only what ROUNDS to zero loses the sign
