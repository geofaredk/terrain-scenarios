from qgis.PyQt.QtCore import QCoreApplication, QEvent, Qt
from qgis.PyQt.QtGui import QFocusEvent, QPalette

from qgis_helpers import UTM, line_through, square, start_session
from terrain_sketch.core.tools import Mode, PixelMode, Tool
from terrain_sketch.gui.help_texts import PIXEL_MODE_LABELS, TOOL_DESCRIPTIONS, TOOL_EXAMPLES
from terrain_sketch.gui.properties_page import PropertiesPage
from terrain_sketch.gui.tool_gallery import ToolGallery


def focus(widget):
    """Deliver a focus-in through the filter chain — widget.event() would bypass it."""
    QCoreApplication.sendEvent(widget, QFocusEvent(QEvent.Type.FocusIn))


def test_every_gallery_row_carries_an_illustration_and_a_worked_example():
    gallery = ToolGallery()
    assert gallery.tool_list.count() == len(Tool)
    for row in range(gallery.tool_list.count()):
        item = gallery.tool_list.item(row)
        tool = Tool(item.data(Qt.ItemDataRole.UserRole))
        assert not item.icon().isNull(), f"{tool.value} has no illustration"
        assert TOOL_DESCRIPTIONS[tool] in item.toolTip()
        assert TOOL_EXAMPLES[tool] in item.toolTip()


def test_the_gallery_redraws_its_illustrations_when_the_theme_changes():
    gallery = ToolGallery()
    first = gallery.tool_list.item(0).icon().pixmap(60, 32).toImage()
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Mid, Qt.GlobalColor.white)
    dark.setColor(QPalette.ColorRole.Highlight, Qt.GlobalColor.yellow)
    gallery.setPalette(dark)   # delivers QEvent.PaletteChange, which must redraw them by itself
    assert gallery.tool_list.item(0).icon().pixmap(60, 32).toImage() != first


def test_a_broken_illustration_does_not_take_qgis_down_on_a_theme_change(monkeypatch):
    """The theme changing redraws every tile's illustration from inside a Qt virtual override
    (`changeEvent`); an SVG that cannot be read there must not abort QGIS, the same guarantee
    `PropertiesPage` already gives its own pictures."""
    from terrain_sketch.gui import illustrations
    gallery = ToolGallery()

    def broken(*_args, **_kwargs):
        raise RuntimeError("an SVG that cannot be read")

    monkeypatch.setattr(illustrations, "pixmap", broken)
    gallery.changeEvent(QEvent(QEvent.Type.PaletteChange))   # must not raise


def test_every_pixel_mode_entry_gets_its_own_picture(tmp_path):
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 25, 25), UTM)
    page = PropertiesPage(c)
    page.show_feature(pond.id)
    shots = []
    for index in range(page.pixel_mode.count()):
        icon = page.pixel_mode.itemIcon(index)
        assert not icon.isNull(), page.pixel_mode.itemText(index)
        shots.append(icon.pixmap(32, 32).toImage().bits().asstring(32 * 32 * 4))
    assert len(set(shots)) == len(PixelMode)   # three modes, three different pictures


def test_the_diagram_highlights_the_field_that_has_focus(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)
    neutral = page.diagram.pixmap().toImage()
    focus(page.width)
    on_width = page.diagram.pixmap().toImage()
    focus(page.slope)
    on_slope = page.diagram.pixmap().toImage()
    assert on_width != neutral and on_slope != neutral and on_width != on_slope


def test_the_diagram_is_hidden_for_a_tool_that_has_no_slopes(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    page.show_feature(c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM).id)
    assert page.diagram.isVisibleTo(page)
    page.show_feature(c.add_drawn(Tool.ADD, Mode.AREA, square(10, 10, 25, 25), UTM).id)
    assert not page.diagram.isVisibleTo(page)


def test_every_numeric_field_quotes_a_real_measurement_in_its_tooltip(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    # check AFTER a feature is shown: that is the only state in which these fields are visible,
    # and show_feature rewrites the amount tooltip, so checking before it proves nothing
    page.show_feature(dike.id)
    for widget in (page.amount, page.width, page.slope, page.reach):
        tip = widget.toolTip()
        assert len(tip) > 40, tip
        assert any(ch.isdigit() for ch in tip), f"no concrete measurement in: {tip}"


def test_the_choice_fields_name_a_real_case_for_each_option(tmp_path):
    c = start_session(tmp_path)
    page = PropertiesPage(c)
    # these two are choices, not measurements, so they earn their keep with named examples
    slopes = page.slope_position.toolTip()
    assert "Inside" in slopes and "Outside" in slopes
    assert "pond" in slopes and "pad" in slopes
    pixels = page.pixel_mode.toolTip()
    assert len(pixels) > 40 and "All touched" in pixels


def test_the_amount_label_says_what_the_height_or_depth_is_measured_from():
    """"Height" alone let users measure a flat pad from the ground under it rather than from its
    highest point (spec §7.2: the label depends on the tool)."""
    from terrain_sketch.core.tools import TOOL_INFO
    from terrain_sketch.gui.help_texts import amount_label
    labels = {}
    for tool in Tool:
        for mode in TOOL_INFO[tool].modes:
            labels[(tool, mode)] = amount_label(tool, mode)
    assert labels.pop((Tool.INTERPOLATE, Mode.PATH)) is None and labels.pop((Tool.INTERPOLATE, Mode.AREA)) is None
    for (tool, _mode), label in labels.items():
        lowers = tool in (Tool.LOWER_PATH, Tool.LOWER_FLAT, Tool.SUBTRACT)
        assert label.startswith("Depth" if lowers else "Height"), label
        assert len(label.split()) > 1, label                     # never the bare word
    assert "highest" in labels[(Tool.RAISE_FLAT, Mode.PATH)] and "lowest" in labels[(Tool.LOWER_FLAT, Mode.AREA)]
    assert labels[(Tool.RAISE_PATH, Mode.PATH)] != labels[(Tool.RAISE_FLAT, Mode.PATH)]


def test_the_pixels_tooltip_shows_the_three_modes_side_by_side_in_the_theme(tmp_path):
    import base64
    from qgis.PyQt.QtGui import QImage
    c = start_session(tmp_path)
    pond = c.add_drawn(Tool.LOWER_FLAT, Mode.AREA, square(10, 10, 20, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(pond.id)
    tip = page.pixel_mode.toolTip()
    images = tip.split('src="data:image/png;base64,')[1:]
    assert len(images) == 3
    for mode in PixelMode:
        assert f">{PIXEL_MODE_LABELS[mode]}<" in tip
    first = QImage.fromData(base64.b64decode(images[0].split('"')[0]))
    assert not first.isNull() and first.width() == 72

    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Mid, Qt.GlobalColor.white)
    dark.setColor(QPalette.ColorRole.Highlight, Qt.GlobalColor.yellow)
    page.setPalette(dark)                                       # the theme changes
    assert page.pixel_mode.toolTip() != tip


def test_a_picture_that_cannot_be_drawn_does_not_take_qgis_down(tmp_path, monkeypatch):
    """The theme changing and a field taking focus both redraw pictures from inside a Qt handler."""
    from terrain_sketch.gui import illustrations
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    page = PropertiesPage(c)
    page.show_feature(dike.id)

    def broken(*_args, **_kwargs):
        raise RuntimeError("an SVG that cannot be read")

    monkeypatch.setattr(illustrations, "pixmap", broken)
    page.changeEvent(QEvent(QEvent.Type.PaletteChange))
    page.eventFilter(page.width, QFocusEvent(QEvent.Type.FocusIn))


def test_the_amount_labels_and_summaries_name_what_the_engine_measures_from():
    """An area's level is the highest or lowest point of its outline, as the About text says; a raised or
    lowered path follows the straight grade between the ground at its ends, not every bump in between."""
    from terrain_sketch.gui.help_texts import TOOL_SUMMARIES, amount_label
    for tool in (Tool.RAISE_FLAT, Tool.LOWER_FLAT):
        assert amount_label(tool, Mode.AREA) == amount_label(tool, Mode.PATH)
        assert "point" in amount_label(tool, Mode.AREA) and "edge" not in amount_label(tool, Mode.AREA)
    for tool, change in ((Tool.RAISE_PATH, "plus the height"), (Tool.LOWER_PATH, "minus the depth")):
        summary = TOOL_SUMMARIES[tool]
        assert "straight grade between the ground at" in summary and change in summary
        assert "following the terrain" not in summary
