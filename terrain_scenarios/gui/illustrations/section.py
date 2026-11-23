"""The feature page's cross-section diagram, drawn from the feature's own values (spec §7).

The section is the one `core.sections.flat_ground_section` gives: both sides on flat ground, out
to where they meet it. It fills the drawing's width; its height is true to scale unless that
would leave it flatter than MIN_HEIGHT, when it is stretched to that and a note says by how much
("Height ×5"). The labels carry the values, and each sits in a part tagged `{opacity-<key>}` so
the field with focus can be emphasised exactly as in the other illustrations.
"""
from __future__ import annotations

import math

from qgis.PyQt.QtGui import QPalette, QPixmap

from ...core.sections import flat_ground_section
from . import fill_tokens, render

WIDTH, HEIGHT = 230, 110          # the viewBox; the page shows it at DIAGRAM's aspect
LEFT, RIGHT = 10, 158             # the section's horizontal room; the height label lives beyond RIGHT
HEIGHT_DIM = 188                  # x of the height dimension line; its label sits right of it
ROOM = 58                         # vertical room between the ground line and the crest (or bottom)
MIN_HEIGHT = 24                   # flatter than this on screen and the height is exaggerated
GROUND_UP, GROUND_DOWN = 82, 28   # y of the ground line for a raise tool / a lower tool
FONT = 10
CHAR_WIDTH = 6                    # a generous average glyph width at FONT, to keep labels apart


def section_template(feature) -> str:
    """The diagram's SVG with its colour and highlight tokens still in place."""
    section = flat_ground_section(feature)
    raise_tool = section.direction < 0
    left = [(-x, z) for x, z in reversed(section.left)]
    right = list(section.right)
    left_extent = max(x for x, _z in section.left)
    right_extent = max(x for x, _z in section.right)
    tallest = max(abs(z) for _x, z in section.left + section.right)

    sx = (RIGHT - LEFT) / max(left_extent + right_extent, 1e-9)
    factor = 1
    if tallest * sx > ROOM:                    # too tall: everything shrinks, the shape keeps its angles
        sx = ROOM / tallest
    elif 0.0 < tallest * sx < MIN_HEIGHT:      # too flat: only the height is stretched, and said so
        factor = math.ceil(MIN_HEIGHT / (tallest * sx))
    sy = sx * factor
    centre = LEFT + left_extent * sx + 0.5 * ((RIGHT - LEFT) - (left_extent + right_extent) * sx)
    ground = GROUND_UP if raise_tool else GROUND_DOWN

    def point(x, z):
        return centre + x * sx, ground - z * sy

    def path(points):
        return " ".join(f"{'M' if i == 0 else 'L'}{px:.1f} {py:.1f}"
                        for i, (px, py) in enumerate(point(x, z) for x, z in points))

    outline = left + right[1:]
    colour = "{fill}" if raise_tool else "{cut}"
    crest_y = point(0, outline[len(left) - 1][1])[1]
    edge_l, edge_r = point(-0.5 * feature.width, 0)[0], point(0.5 * feature.width, 0)[0]
    parts = [
        f'<path d="M0 {ground} L{RIGHT + 4} {ground}" fill="none" stroke="{{terrain}}" stroke-width="2"/>',
        f'<path d="{path(outline)} Z" fill="{colour}" fill-opacity="0.35" stroke="none"/>',
        f'<path d="{path(outline)}" fill="none" stroke="{{line}}" stroke-width="2" stroke-linejoin="round"/>',
    ]

    # Width: across the crest (above a dike, below a ditch's bottom).
    dim_y = crest_y - 6 if raise_tool else crest_y + 6
    text_y = dim_y - 4 if raise_tool else dim_y + 12
    parts.append(
        f'<g opacity="{{opacity-width}}">'
        f'<path d="M{edge_l:.1f} {dim_y:.1f} L{edge_r:.1f} {dim_y:.1f} M{edge_l:.1f} {dim_y - 3:.1f} '
        f'L{edge_l:.1f} {dim_y + 3:.1f} M{edge_r:.1f} {dim_y - 3:.1f} L{edge_r:.1f} {dim_y + 3:.1f}" '
        f'stroke="{{text}}" stroke-width="1.2"/>'
        f'{_text((edge_l + edge_r) / 2, text_y, f"{feature.width:.1f} m", "middle")}</g>')

    # Height or depth: a dimension line right of the drawing, from the ground to the crest.
    parts.append(
        f'<g opacity="{{opacity-amount}}">'
        f'<path d="M{HEIGHT_DIM} {ground} L{HEIGHT_DIM} {crest_y:.1f} M{HEIGHT_DIM - 3} {ground} '
        f'L{HEIGHT_DIM + 3} {ground} M{HEIGHT_DIM - 3} {crest_y:.1f} L{HEIGHT_DIM + 3} {crest_y:.1f}" '
        f'stroke="{{text}}" stroke-width="1.2"/>'
        f'{_text(HEIGHT_DIM + 4, (ground + crest_y) / 2 + 3.5, f"{feature.amount:.2f} m", "start")}</g>'
        if feature.amount > 0.0 else '<g opacity="{opacity-amount}"></g>')

    # Side slope: the right side's last sloped segment, emphasised, with 1:n beside it.
    slope = _slope_segment(right) if feature.slope_n > 0.0 else None
    if slope is not None:
        (x0, y0), (x1, y1) = point(*slope[0]), point(*slope[1])
        label_y = (y0 + y1) / 2 + (-4 if raise_tool else 12)
        label = f"1:{feature.slope_n:g}"
        # beside the slope, but never into the height label right of the drawing
        label_x = min((x0 + x1) / 2 + 6, HEIGHT_DIM - 4 - CHAR_WIDTH * len(label))
        if label_x < (x0 + x1) / 2 + 6:    # pulled in over the shape: level with the slope's middle instead
            label_y = (y0 + y1) / 2 + 3.5
        parts.append(
            f'<g opacity="{{opacity-slope}}">'
            f'<path d="M{x0:.1f} {y0:.1f} L{x1:.1f} {y1:.1f}" stroke="{{text}}" stroke-width="3" opacity="0.8"/>'
            f'{_text(label_x, label_y, label, "start")}</g>')
    else:
        parts.append('<g opacity="{opacity-slope}"></g>')

    # Max. reach: only when it stops a slope before the ground, from the crest edge to that stop.
    if section.cut_short:
        stop = point(max(x for x, _z in right), 0)[0]
        reach_y = ground + 10 if raise_tool else ground - 10
        label_y = reach_y + 12 if raise_tool else reach_y - 4
        parts.append(
            f'<g opacity="{{opacity-reach}}">'
            f'<path d="M{edge_r:.1f} {reach_y} L{stop:.1f} {reach_y}" stroke="{{text}}" stroke-width="1.2" '
            f'stroke-dasharray="3 2"/>'
            f'<path d="M{edge_r:.1f} {reach_y - 3} L{edge_r:.1f} {reach_y + 3} M{stop:.1f} {reach_y - 3} '
            f'L{stop:.1f} {reach_y + 3}" stroke="{{text}}" stroke-width="1.2"/>'
            f'{_text((edge_r + stop) / 2, label_y, f"{feature.reach:g} m", "middle")}</g>')
    else:
        parts.append('<g opacity="{opacity-reach}"></g>')

    if factor > 1:
        note_y = HEIGHT - 4 if raise_tool else 12
        parts.append(f'<g fill-opacity="0.6">{_text(LEFT, note_y, f"Height ×{factor}", "start")}</g>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}">'
            + "".join(parts) + "</svg>")


def section_svg(feature, palette: QPalette, highlight: str | None = None) -> str:
    """The diagram for `feature`, in `palette`'s colours, with `highlight`'s part emphasised."""
    return fill_tokens(section_template(feature), palette, highlight)


def section_pixmap(feature, size, palette: QPalette, highlight: str | None = None) -> QPixmap:
    return render(section_svg(feature, palette, highlight), size)


def _slope_segment(side):
    """The last segment of a side that runs out sideways and changes height: the terminal slope."""
    for (x0, z0), (x1, z1) in reversed(list(zip(side, side[1:]))):
        if x1 > x0 and z1 != z0:
            return (x0, z0), (x1, z1)
    return None


def _text(x, y, text, anchor):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{FONT}" text-anchor="{anchor}" '
            f'fill="{{text}}">{text}</text>')
