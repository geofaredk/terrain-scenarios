"""The feature page header's summary (tool, fill, cut) and the volume formatting behind it."""
import pytest
from qgis.PyQt.QtWidgets import QWidget

from qgis_helpers import UTM, line_through, square, start_session
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.feature_list import feature_subtitle
from terrain_scenarios.gui.help_texts import FLAG_TEXTS, NO_VOLUME_YET, cubic_metres
from terrain_scenarios.gui.properties_page import PropertiesPage


def test_selecting_another_feature_shows_its_own_problems(tmp_path):
    """The header summary refresh must not take the place of the problem check when a feature is shown."""
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

def test_the_page_has_no_volumes_or_about_group(tmp_path):
    from qgis.gui import QgsCollapsibleGroupBox
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    titles = {box.title() for box in page.findChildren(QgsCollapsibleGroupBox)}
    assert "Volumes" not in titles and "About this tool" not in titles
    assert not hasattr(page, "volumes") and not hasattr(page, "about")
    assert page.findChild(QWidget, "TerrainScenariosVolumes") is None


def test_the_header_summary_follows_an_edit(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=1.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    before = page.header_summary.text()
    assert cubic_metres(c.stats(dike.id).fill) in before

    c.update_feature(dike.id, amount=3.0)
    assert page.header_summary.text() != before
    assert page.header_summary.text() == feature_subtitle(c, dike.id)


def test_a_refresh_summary_failure_is_logged_not_raised(tmp_path, monkeypatch):
    """`_refresh_summary` runs from `featuresChanged`, a Qt signal — an exception escaping it
    takes QGIS down, the same rule the engine and the file/layer writes in `_set` already
    follow."""
    import terrain_scenarios.gui.properties_page as properties_page_module

    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)

    log = []
    monkeypatch.setattr(properties_page_module.QgsMessageLog, "logMessage",
                        staticmethod(lambda text, *a, **kw: log.append(text)))

    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(properties_page_module, "feature_subtitle", boom)
    page._refresh_summary()          # must not raise

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
