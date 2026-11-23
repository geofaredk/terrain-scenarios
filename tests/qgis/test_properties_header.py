"""The feature page header (its summary line, problems) and the groups the page does not have."""
from qgis.PyQt.QtWidgets import QWidget

from qgis_helpers import UTM, line_through, square, start_session
from terrain_scenarios.core.tools import Mode, Tool
from terrain_scenarios.gui.feature_list import feature_subtitle
from terrain_scenarios.gui.help_texts import FLAG_TEXTS
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


def test_the_header_summary_is_just_the_tool_label_and_follows_an_edit(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.update_feature(dike.id, amount=1.0)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    assert page.header_summary.text() == "Raise path" and "m³" not in page.header_summary.text()

    c.update_feature(dike.id, tool=Tool.RAISE_FLAT)
    assert page.header_summary.text() == feature_subtitle(c, dike.id) != "Raise path"


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
