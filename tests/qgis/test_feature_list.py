import pytest
from qgis.core import QgsFillSymbol, QgsGeometry, QgsPointXY
from qgis.PyQt.QtCore import QEvent, QModelIndex, QPointF, Qt
from qgis.PyQt.QtCore import QRect
from qgis.PyQt.QtGui import QColor, QImage, QMouseEvent, QPainter
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QAbstractItemView, QApplication, QStyleOptionViewItem

from qgis_helpers import UTM, line_through, panel, spin_event_loop, start_session
from terrain_sketch.core.tools import Mode, Tool
from terrain_sketch.gui.feature_list import (FLAGGED_ROLE, ID_ROLE, PICTURE_ROLE, PICTURE_SIZE, SUBTITLE_ROLE,
                                             SYMBOL_ROLE, FeatureListModel, FeatureListView, FeatureRowDelegate)
from terrain_sketch.qgis_io.symbols import to_xml

RED = to_xml(QgsFillSymbol.createSimple({"color": "255,0,0,255", "outline_style": "no"}))


def test_feature_list_edits_go_through_the_controller(tmp_path):
    c = start_session(tmp_path)
    a, b, d = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20, 30))
    model = FeatureListModel(c)
    assert model.rowCount() == 3 and model.data(model.index(0)) == a.name
    model.setData(model.index(1), Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert not c.feature(b.id).enabled
    model.setData(model.index(2), "Barrier", Qt.ItemDataRole.EditRole)
    assert c.feature(d.id).name == "Barrier"
    model.dropMimeData(model.mimeData([model.index(0)]), Qt.DropAction.MoveAction, 3, 0, QModelIndex())
    assert [f.id for f in c.features] == [b.id, d.id, a.id]
    assert [model.data(model.index(r), ID_ROLE) for r in range(3)] == [b.id, d.id, a.id]


def test_flagged_features_show_a_warning(tmp_path):
    c = start_session(tmp_path)
    far = QgsGeometry.fromPolylineXY([QgsPointXY(0, 0), QgsPointXY(10, 10)])
    c.add_drawn(Tool.ADD, Mode.PATH, far, UTM)
    model = FeatureListModel(c)
    assert "outside the DEM" in model.data(model.index(0), Qt.ItemDataRole.ToolTipRole)
    assert model.data(model.index(0), FLAGGED_ROLE) is True                    # the delegate paints the warning
    delegate = FeatureRowDelegate()
    size = delegate.sizeHint(QStyleOptionViewItem(), model.index(0))
    assert size.height() > 0 and size.width() >= 0                            # does not raise, gives a real size


def test_a_row_says_what_the_feature_is_and_what_it_moves(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    model = FeatureListModel(c)
    subtitle = model.index(0).data(SUBTITLE_ROLE)
    assert subtitle.startswith("Raise path") and "fill" in subtitle and "m³" in subtitle
    assert "cut" not in subtitle                      # a raise tool only fills
    c.set_enabled(dike.id, False)                     # a feature that changes nothing says only what it is
    assert model.index(0).data(SUBTITLE_ROLE) == "Raise path"


def test_the_view_installs_the_row_delegate_on_its_own(tmp_path):
    """main_dock.py builds a FeatureListView with no delegate of its own — the view must install
    FeatureRowDelegate itself, or the production panel paints with Qt's stock delegate (no picture,
    no subtitle, no warning, no chevron — and DecorationRole no longer carries the warning icon
    either, so it would show nothing at all) and hit-tests the checkbox in the wrong place."""
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))
    assert isinstance(view.itemDelegate(), FeatureRowDelegate)


def test_clicking_a_row_opens_it_but_clicking_its_checkbox_only_toggles_it(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))    # no setItemDelegate here — exercised as main_dock.py builds it
    view.resize(300, 120)
    opened = []
    view.rowOpened.connect(opened.append)
    rect = view.visualRect(view.model().index(0))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())      # the row body
    assert opened == [dike.id]
    box = FeatureRowDelegate.checkbox_rect(rect)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=box.center())       # the checkbox
    assert opened == [dike.id] and not c.feature(dike.id).enabled


def test_pressing_space_over_the_current_row_toggles_it(tmp_path):
    """The stock delegate's Key_Space/Key_Select checkbox toggle has nothing to do with the mouse
    hit-test our editorEvent override disables, and must keep working."""
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = FeatureListView(FeatureListModel(c))
    view.resize(300, 120)
    view.setCurrentIndex(view.model().index(0))
    assert c.feature(dike.id).enabled
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert not c.feature(dike.id).enabled


def test_f2_on_a_row_renames_it_in_place_without_opening_its_page(tmp_path):
    """spec §5.2: renaming in the list is F2 (or the context menu's Rename), on the real panel."""
    from qgis.PyQt.QtWidgets import QLineEdit

    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = dock.feature_view
    view.select_id(dike.id)
    QTest.keyClick(view, Qt.Key.Key_F2)
    assert view.state() == QAbstractItemView.State.EditingState
    assert dock.stack.currentPanel() is dock.main_panel                 # no page opened over the editor
    editor = view.indexWidget(view.currentIndex())
    assert isinstance(editor, QLineEdit)
    editor.setText("Sea wall")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QApplication.processEvents()                                         # the delegate commits on a queued call
    assert c.feature(dike.id).name == "Sea wall"
    assert dock.stack.currentPanel() is dock.main_panel


def test_double_clicking_a_row_opens_its_page_and_does_not_start_renaming(tmp_path):
    """The first click of a double click already opens the page, so a rename started by the second
    would be an editor hidden behind that page (spec §5.2)."""
    _iface, c, dock = panel(tmp_path)
    dock.show()
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    view = dock.feature_view
    pos = view.visualRect(view.model().index(0)).center()
    # A real double click arrives as press, release, press, double-click, release; QTest.mouseDClick
    # sends only the double-click event, so the sequence is built by hand.
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    QApplication.sendEvent(view.viewport(), QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(pos), view.viewport().mapToGlobal(QPointF(pos)),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    assert dock.stack.currentPanel() is dock.properties_page
    assert view.state() != QAbstractItemView.State.EditingState
    assert dock.properties.name_edit.text() == c.feature(dike.id).name


def _relative_luminance(colour) -> float:
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(colour.red()) + 0.7152 * channel(colour.green())
            + 0.0722 * channel(colour.blue()))


def _contrast(a, b) -> float:
    """The WCAG contrast ratio between two colours, from 1 (none) to 21 (black on white)."""
    high, low = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _between(colour, a, b) -> bool:
    return all(min(x, y) <= z <= max(x, y) for x, y, z in (
        (a.red(), b.red(), colour.red()), (a.green(), b.green(), colour.green()),
        (a.blue(), b.blue(), colour.blue())))


def _light_palette():
    """Qt's own default palette, with every colour group the same so focus cannot change a row."""
    from qgis.PyQt.QtGui import QPalette
    default, palette = QPalette(), QPalette()
    for role in QPalette.ColorRole:
        if role not in (QPalette.ColorRole.NColorRoles,):
            palette.setColor(role, default.color(QPalette.ColorGroup.Active, role))
    return palette


def _dark_palette():
    from qgis.PyQt.QtGui import QColor, QPalette
    palette = _light_palette()
    for role, rgb in ((QPalette.ColorRole.Window, (53, 53, 53)), (QPalette.ColorRole.WindowText, (240, 240, 240)),
                      (QPalette.ColorRole.Base, (35, 35, 35)), (QPalette.ColorRole.Text, (240, 240, 240)),
                      (QPalette.ColorRole.Button, (53, 53, 53)), (QPalette.ColorRole.ButtonText, (240, 240, 240)),
                      (QPalette.ColorRole.Mid, (90, 90, 90)), (QPalette.ColorRole.Highlight, (60, 110, 180)),
                      (QPalette.ColorRole.HighlightedText, (255, 255, 255))):
        palette.setColor(role, QColor(*rgb))
    return palette


@pytest.mark.parametrize("make_palette", [_light_palette, _dark_palette], ids=["light", "dark"])
def test_a_selected_rows_subtitle_is_readable_on_the_highlight(tmp_path, make_palette):
    """The subtitle and chevron are muted from the colours the row is painted with: HighlightedText
    toward Highlight on a selected row, Text toward Base on any other — never toward Window."""
    from qgis.PyQt.QtGui import QPalette
    from qgis.PyQt.QtWidgets import QStyle

    _iface, c, dock = panel(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    palette = make_palette()
    dock.setPalette(palette)
    dock.resize(360, 650)
    dock.show()
    view = dock.feature_view
    view.select_id(dike.id)
    QApplication.processEvents()
    highlight = palette.color(QPalette.ColorRole.Highlight)
    highlighted_text = palette.color(QPalette.ColorRole.HighlightedText)

    # What is on screen: the painted subtitle reaches 3:1 against the highlight, give or take anti-aliasing
    image = view.viewport().grab().toImage()
    row = view.visualRect(view.model().index(0))
    line = view.fontMetrics().height()
    subtitle_top = row.top() + row.height() // 2
    best = max(_contrast(image.pixelColor(x, y), highlight)
               for y in range(subtitle_top, min(subtitle_top + line, row.bottom()))
               for x in range(row.left() + row.width() // 4, row.right() - row.width() // 4))
    assert best >= 2.8, best

    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.state |= QStyle.StateFlag.State_Selected
    text, muted = FeatureRowDelegate.row_colours(option)
    assert text == highlighted_text
    assert _between(muted, highlighted_text, highlight) and muted != highlighted_text
    assert _contrast(muted, highlight) >= 3.0, _contrast(muted, highlight)

    option.state &= ~QStyle.StateFlag.State_Selected
    text, muted = FeatureRowDelegate.row_colours(option)
    assert text == palette.color(QPalette.ColorRole.Text)
    assert _between(muted, text, palette.color(QPalette.ColorRole.Base)) and muted != text


def test_selection_survives_edits_and_list_changes(tmp_path):
    c = start_session(tmp_path)
    a, b = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20))
    view = FeatureListView(FeatureListModel(c))
    view.select_id(b.id)
    c.update_feature(b.id, amount=2.0)
    assert view.selected_id() == b.id
    c.delete_feature(a.id)
    assert view.selected_id() == b.id


def test_a_row_index_from_before_the_list_shrank_is_ignored(tmp_path):
    """Qt checks only that a row is not negative before handing an index to the model, so an index
    kept across a reset can point past the end of the list — inside a Qt call that must not raise."""
    c = start_session(tmp_path)
    a, b = (c.add_drawn(Tool.ADD, Mode.PATH, line_through(5, r, 30, r), UTM) for r in (10, 20))
    model = FeatureListModel(c)
    stale = model.index(1)
    c.delete_feature(b.id)
    assert model.data(stale) is None
    assert model.setData(stale, "Barrier", Qt.ItemDataRole.EditRole) is False
    assert c.feature(a.id).name != "Barrier"
    assert bytes(model.mimeData([model.index(0), stale]).data("application/x-terrain-sketch-feature-ids")) \
        == a.id.encode()


def test_unstyled_row_has_no_symbol_and_keeps_its_diagram(tmp_path):
    c = start_session(tmp_path)
    c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    model = FeatureListModel(c)
    index = model.index(0)
    assert model.data(index, SYMBOL_ROLE) is None and model.data(index, PICTURE_ROLE) == "tool_raise_path"


def test_styled_row_carries_the_symbol(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    model = FeatureListModel(c)
    c.set_style(dike.id, RED)
    assert to_xml(model.data(model.index(0), SYMBOL_ROLE)) == RED


def test_row_with_unreadable_style_shows_the_tool_diagram(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    model = FeatureListModel(c)
    c.set_style(dike.id, "not xml")
    assert model.data(model.index(0), SYMBOL_ROLE) is None
    assert model.data(model.index(0), PICTURE_ROLE) == "tool_raise_path"


def _picture_centre_pixel(model, row_size=(300, 40)) -> QColor:
    """Paint row 0 through the delegate into an image; the pixel at the picture rectangle's centre."""
    image = QImage(*row_size, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, *row_size)
    box = FeatureRowDelegate.checkbox_rect(option.rect)
    picture = QRect(box.right() + 8, (row_size[1] - PICTURE_SIZE.height()) // 2,
                    PICTURE_SIZE.width(), PICTURE_SIZE.height())
    painter = QPainter(image)
    FeatureRowDelegate().paint(painter, option, model.index(0))
    painter.end()
    return image.pixelColor(picture.center())


def test_styled_row_paints_the_swatch(tmp_path):
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    model = FeatureListModel(c)
    plain = _picture_centre_pixel(model)
    c.set_style(dike.id, RED)
    assert _picture_centre_pixel(model) == QColor(255, 0, 0) and plain != QColor(255, 0, 0)


def test_a_layers_panel_edit_repaints_the_rows(tmp_path):
    from qgis.core import QgsLayerTreeModel, QgsProject, QgsSymbolLegendNode
    c = start_session(tmp_path)
    dike = c.add_drawn(Tool.RAISE_PATH, Mode.PATH, line_through(5, 20, 34, 20), UTM)
    c.set_style(dike.id, RED)
    model = FeatureListModel(c)
    changed = []
    model.dataChanged.connect(lambda *_: changed.append(True))
    root = QgsProject.instance().layerTreeRoot()
    legend = QgsLayerTreeModel(root)
    nodes = [n for n in legend.layerLegendNodes(root.findLayer(c.layers.outlines.id()))
             if isinstance(n, QgsSymbolLegendNode)]
    nodes[0].setSymbol(QgsFillSymbol.createSimple({"color": "0,0,255,255", "outline_style": "no"}))
    spin_event_loop(10)
    assert changed and c.find(dike.id).style != RED
