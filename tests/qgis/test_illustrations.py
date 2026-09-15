import re

from qgis.PyQt.QtCore import QSize
from qgis.PyQt.QtGui import QColor, QPalette

from terrain_sketch.core.tools import PixelMode, Tool
from terrain_sketch.gui import illustrations
from terrain_sketch.gui.overlay import CUT, FILL


def light() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Mid, QColor(140, 140, 140))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(20, 80, 200))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(10, 10, 10))
    return palette


def dark() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Mid, QColor(90, 90, 90))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(120, 180, 255))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(240, 240, 240))
    return palette


def test_every_tool_and_pixel_mode_has_an_illustration():
    names = illustrations.available()
    for tool in Tool:
        assert f"tool_{tool.value}" in names, f"no illustration for {tool.value}"
    for mode in PixelMode:
        assert f"pixels_{mode.value}" in names, f"no illustration for {mode.value}"
    assert "parameters" in names


def test_no_colour_token_survives_rendering():
    for name in illustrations.available():
        source = illustrations.svg_source(name, light())
        assert "{" not in source and "}" not in source, f"{name} kept an unfilled token"


def test_the_palette_drives_the_colours_so_the_theme_is_followed():
    light_source = illustrations.svg_source("tool_raise_path", light())
    dark_source = illustrations.svg_source("tool_raise_path", dark())
    assert "#8c8c8c" in light_source and "#5a5a5a" in dark_source
    assert light_source != dark_source


def test_fill_and_cut_stay_the_map_colours_in_both_themes():
    fill, cut = QColor(*FILL).name(), QColor(*CUT).name()
    for palette in (light(), dark()):
        assert fill in illustrations.svg_source("tool_raise_path", palette)
        assert cut in illustrations.svg_source("tool_lower_path", palette)


def test_the_parameter_diagram_exposes_the_parts_the_fields_control():
    assert illustrations.tagged_parts(open(
        illustrations.HERE / "parameters.svg").read()) == ["width", "amount", "slope", "reach"]


def test_highlighting_one_part_dims_the_others():
    source = illustrations.svg_source("parameters", light(), highlight="slope")
    assert source.count('opacity="0.25"') == 3 and source.count('opacity="1"') == 1
    every = illustrations.svg_source("parameters", light())
    assert every.count('opacity="1"') == 4 and '0.25' not in every


def test_an_unknown_highlight_leaves_every_part_visible():
    """A key the template does not tag must emphasise nothing, not dim the whole diagram: that is
    what a renamed part in an SVG would otherwise do, silently."""
    source = illustrations.svg_source("parameters", light(), highlight="nope")
    assert source.count('opacity="1"') == 4 and '0.25' not in source


def test_every_illustration_renders_to_a_non_blank_pixmap():
    palette = light()
    for name in illustrations.available():
        image = illustrations.pixmap(name, QSize(64, 64), palette).toImage()
        assert image.size() == QSize(64, 64), name
        painted = sum(1 for y in range(0, 64, 2) for x in range(0, 64, 2)
                      if image.pixelColor(x, y).alpha() > 0)
        assert painted > 20, f"{name} rendered almost nothing ({painted} samples painted)"


def test_a_square_size_may_be_given_as_a_plain_int():
    assert illustrations.pixmap("tool_add", 48, light()).size() == QSize(48, 48)


def test_the_three_pixel_modes_really_do_look_different():
    palette = light()
    shots = [illustrations.pixmap(f"pixels_{m.value}", 64, palette).toImage() for m in PixelMode]
    def signature(image):
        return tuple(image.pixelColor(x, y).alpha() > 0
                     for y in range(8, 56, 4) for x in range(8, 56, 4))
    assert len(set(signature(s) for s in shots)) == 3


def point_in_polygon(point, polygon):
    """Ray casting algorithm for point-in-polygon test."""
    x, y = point
    n = len(polygon)
    inside = False
    x1, y1 = polygon[0]
    for i in range(1, n + 1):
        x2, y2 = polygon[i % n]
        if y > min(y1, y2):
            if y <= max(y1, y2):
                if x <= max(x1, x2):
                    if y1 != y2:
                        xinters = (y - y1) * (x2 - x1) / (y2 - y1) + x1
                    if x1 == x2 or x <= xinters:
                        inside = not inside
        x1, y1 = x2, y2
    return inside


def parse_filled_cells_from_svg(svg_path):
    """Extract filled cell coordinates from pixels_*.svg file."""
    source = open(svg_path).read()
    cells = set()
    for match in re.finditer(r'<rect\s+x="(\d+)"\s+y="(\d+)"\s+width="16"\s+height="16"\s+fill=', source):
        x, y = int(match.group(1)), int(match.group(2))
        cells.add((x, y))
    return cells


def cell_centre_inside_polygon(cell_x, cell_y, polygon):
    """Check if the centre of a cell (x, y in SVG coords) is inside the polygon."""
    centre_x = cell_x + 8
    centre_y = cell_y + 8
    return point_in_polygon((centre_x, centre_y), polygon)


def cell_fully_inside_polygon(cell_x, cell_y, polygon):
    """Check if all four corners of a cell are inside the polygon."""
    corners = [
        (cell_x, cell_y),
        (cell_x + 16, cell_y),
        (cell_x + 16, cell_y + 16),
        (cell_x, cell_y + 16),
    ]
    return all(point_in_polygon(corner, polygon) for corner in corners)


def test_pixels_centre_fills_cells_whose_centre_is_inside():
    """Verify pixels_centre.svg fills only cells whose centre falls inside the outline."""
    outline = [(12, 26), (43, 20), (44, 51), (11, 54)]
    svg_file = illustrations.HERE / "pixels_centre.svg"
    filled = parse_filled_cells_from_svg(svg_file)

    expected_filled = set()
    for cell_x in [8, 24, 40]:
        for cell_y in [8, 24, 40]:
            if cell_centre_inside_polygon(cell_x, cell_y, outline):
                expected_filled.add((cell_x, cell_y))

    assert filled == expected_filled, f"pixels_centre filled {filled}, expected {expected_filled}"


def test_pixels_all_touched_fills_all_cells_the_outline_crosses():
    """Verify pixels_all_touched.svg fills every cell the outline touches."""
    outline = [(12, 26), (43, 20), (44, 51), (11, 54)]
    svg_file = illustrations.HERE / "pixels_all_touched.svg"
    filled = parse_filled_cells_from_svg(svg_file)

    expected_filled = set()
    for cell_x in [8, 24, 40]:
        for cell_y in [8, 24, 40]:
            corners = [
                (cell_x, cell_y),
                (cell_x + 16, cell_y),
                (cell_x + 16, cell_y + 16),
                (cell_x, cell_y + 16),
            ]
            if any(point_in_polygon(corner, outline) for corner in corners):
                expected_filled.add((cell_x, cell_y))

    assert filled == expected_filled, f"pixels_all_touched filled {filled}, expected {expected_filled}"


def test_pixels_fully_inside_fills_only_cells_entirely_within_the_outline():
    """Verify pixels_fully_inside.svg fills only cells lying entirely within the outline."""
    outline = [(12, 26), (43, 20), (44, 51), (11, 54)]
    svg_file = illustrations.HERE / "pixels_fully_inside.svg"
    filled = parse_filled_cells_from_svg(svg_file)

    expected_filled = set()
    for cell_x in [8, 24, 40]:
        for cell_y in [8, 24, 40]:
            if cell_fully_inside_polygon(cell_x, cell_y, outline):
                expected_filled.add((cell_x, cell_y))

    assert filled == expected_filled, f"pixels_fully_inside filled {filled}, expected {expected_filled}"


def path_points(d):
    """The vertices of an SVG path written with absolute M and L commands only."""
    return [(float(x), float(y)) for x, y in re.findall(r"[ML]\s*(-?[\d.]+)\s+(-?[\d.]+)", d)]


def drawn_path(source, attribute, colour):
    """The `d` of the first path whose `attribute` is `colour` (a colour token, unrendered)."""
    for d, value in re.findall(r'<path\s+d="([^"]+)"[^>]*?\s' + attribute + r'="([^"]+)"', source):
        if value == colour:
            return d
    raise AssertionError(f"no path with {attribute}={colour}")


def height_at(polyline, x):
    """The y of a polyline at x, interpolated straight between the vertices around it."""
    for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
        if x1 <= x <= x2:
            return y1 + (y2 - y1) * (x - x1) / (x2 - x1)
    raise AssertionError(f"x={x} lies outside the drawn terrain")


def test_the_add_and_subtract_bands_stay_parallel_to_the_terrain():
    """Add and Subtract shift every cell by the same amount, so the band they draw has to keep a
    constant distance from the ground. A band that pinches or bows shows relief the tool never
    makes — and the descriptions beside these pictures promise the terrain keeps its shape."""
    for name, band in (("tool_add", "{fill}"), ("tool_subtract", "{cut}")):
        source = (illustrations.HERE / f"{name}.svg").read_text()
        ground = path_points(drawn_path(source, "stroke", "{terrain}"))
        surface = path_points(drawn_path(source, "stroke", "{line}"))
        assert len(surface) >= 3, name
        offsets = [height_at(ground, x) - y for x, y in surface]
        assert max(offsets) - min(offsets) < 1.0, f"{name} surface is not parallel: {offsets}"
        # and the band between the two lines closes on the ground, with nothing floating between
        for x, y in path_points(drawn_path(source, "fill", band)):
            on_surface = any(abs(x - sx) < 0.01 and abs(y - sy) < 0.01 for sx, sy in surface)
            assert on_surface or abs(height_at(ground, x) - y) < 1.0, \
                f"{name} band vertex ({x}, {y}) is neither on its surface nor on the ground"



def svg_source(name):
    return (illustrations.HERE / f"{name}.svg").read_text()


def filled_regions(source, colour):
    return [path_points(d) for d, value in re.findall(r'<path\s+d="([^"]+)"[^>]*?\sfill="([^"]+)"', source)
            if value == colour]


def test_the_bands_of_the_raise_and_lower_tools_close_along_the_drawn_ground():
    """A band closed with a straight base across a wavy ground leaves a gap where the ground dips
    below the base, or covers the ground where it rises above."""
    for name, colour in (("tool_raise_path", "{fill}"), ("tool_raise_flat", "{fill}"),
                         ("tool_lower_path", "{cut}"), ("tool_lower_flat", "{cut}")):
        source = svg_source(name)
        ground = path_points(drawn_path(source, "stroke", "{terrain}"))
        regions = filled_regions(source, colour)
        assert regions, name
        for region in regions:
            xs = [x for x, _y in region]
            vertices = {(round(x, 2), round(y, 2)) for x, y in region}
            for gx, gy in ground:
                if min(xs) < gx < max(xs):
                    assert (gx, gy) in vertices, f"{name} band skips the ground vertex ({gx}, {gy})"


def test_path_tools_follow_the_ground_between_the_ends_and_flat_tools_are_level():
    """The four raise and lower pictures used to share one trapezoid; what tells them apart is
    whether the built surface is level (flat) or runs from end to end with the ground (path)."""
    def built_heights(name):
        lines = [path_points(d) for d, value in
                 re.findall(r'<path\s+d="([^"]+)"[^>]*?\sstroke="([^"]+)"', svg_source(name)) if value == "{line}"]
        return [y for line in lines for _x, y in line[1:-1]]        # without the two end slopes' feet
    for flat in ("tool_raise_flat", "tool_lower_flat"):
        heights = built_heights(flat)
        assert max(heights) - min(heights) < 0.01, flat
    for path in ("tool_raise_path", "tool_lower_path"):
        heights = built_heights(path)
        assert max(heights) - min(heights) > 5.0, path


def test_interpolate_shows_both_what_it_fills_and_what_it_cuts():
    source = svg_source("tool_interpolate")
    assert filled_regions(source, "{fill}") and filled_regions(source, "{cut}")


def test_every_cell_centre_is_clear_of_the_outline_and_drawn_on_top_of_it():
    """A centre dot under the outline cannot be seen to be inside or outside it."""
    source = svg_source("pixels_centre")
    outline = path_points(re.search(r'<path\s+d="([^"]+)"', source).group(1))
    for cx, cy in re.findall(r'<circle cx="([\d.]+)" cy="([\d.]+)"', source):
        px, py = float(cx), float(cy)
        for (ax, ay), (bx, by) in zip(outline, outline[1:] + outline[:1]):
            t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2)))
            assert ((px - ax - t * (bx - ax)) ** 2 + (py - ay - t * (by - ay)) ** 2) ** 0.5 >= 3.0, (px, py)
    assert source.index("<circle") > source.index("<path")
