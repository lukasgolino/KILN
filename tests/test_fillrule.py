"""#29: font text fills nonzero (overlapping glyph contours join), and font_axes picks a variable font's instance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import built_of, closed_faces, errors_of, ok_model
from kiln.fillrule import _area, needs_union, nonzero
from kiln.project import Project


def _overlap_font(path: Path) -> Path:
    """A 1000-unit font: L = two overlapping bars (same winding, as static instances of variable fonts keep them),
    Q = a ring with a bar laid across its counter."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    def glyph(loops: list[list[tuple[int, int]]]) -> Any:
        pen = TTGlyphPen(None)
        for loop in loops:
            pen.moveTo(loop[0])
            for pt in loop[1:]:
                pen.lineTo(pt)
            pen.closePath()
        return pen.glyph()

    def cw(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:  # TrueType outer contours are clockwise
        return [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]

    def ccw(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "L", "Q"])
    fb.setupCharacterMap({ord("L"): "L", ord("Q"): "Q"})
    fb.setupGlyf({".notdef": glyph([]), "L": glyph([cw(100, 0, 200, 700), cw(100, 0, 500, 100)]),
                  "Q": glyph([cw(50, 0, 650, 700), ccw(150, 100, 550, 600), cw(0, 300, 700, 400)])})  # fmt: skip
    fb.setupHorizontalMetrics({".notdef": (500, 0), "L": (600, 100), "Q": (700, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "KilnOverlap", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(path))
    return path


def test_nonzero_joins_overlapping_contours() -> None:
    a = [[0.0, 0.0], [0.1, 0.0], [0.1, -0.7], [0.0, -0.7]]
    b = [[0.0, 0.0], [0.5, 0.0], [0.5, -0.1], [0.0, -0.1]]
    assert needs_union([a, b])
    (joined,) = nonzero([a, b])
    assert abs(_area(joined)) == pytest.approx(0.11) and len(joined) == 6  # one L, not a bar with a hole cut out
    ring = [[0.0, 0.0], [0.6, 0.0], [0.6, -0.7], [0.0, -0.7]]
    counter = [[0.1, -0.1], [0.1, -0.6], [0.5, -0.6], [0.5, -0.1]]
    assert nonzero([ring, counter]) == [ring, counter]  # nothing overlaps: left as it is
    bar = [[-0.05, -0.3], [0.65, -0.3], [0.65, -0.4], [-0.05, -0.4]]
    out = nonzero([ring, counter, bar])
    assert len(out) == 3 and sorted(round(abs(_area(loop)), 4) for loop in out) == [0.08, 0.08, 0.43]  # the bar crosses the counter


@pytest.mark.parametrize("hard", [False, True])
def test_overlapping_glyph_contours_extrude_as_one_piece(project: Project, hard: bool) -> None:
    _overlap_font(project.root / "fonts" / "overlap.ttf")
    edge = "\n    bevel: 0.01" if hard else ""
    text = f"name: thing\nclass: prop\nparts:\n  - extrude: {{ text: LQ, font: fonts/overlap.ttf, text_size: 1, height: 0.1 }}\n    color: red{edge}\n"
    model, _ = ok_model(project, text)
    assert len(model.parts[0].geometry.params["holes"]) == 3  # L and Q's ring as outlines, Q's two counters
    built = built_of(project, text)
    assert built.pieces == 2  # L and Q, nothing cut apart
    if hard:
        assert closed_faces(built.painted.faces)


# Cinzel's S at wght 900 (OFL), as svgpath gives it: the S and a bar of its bottom serif overlapping it
CINZEL_S_900 = [[[-0.0285,-0.714], [-0.00275,-0.7135], [0.0305,-0.712], [0.1075,-0.7065], [0.145,-0.703], [0.1775,-0.6995], [0.20225,-0.69588], [0.2165,-0.692], [0.1965,-0.541], [0.1865,-0.541], [0.18178,-0.57533], [0.16761,-0.605], [0.144,-0.63], [0.11217,-0.64889], [0.07333,-0.66022], [0.0275,-0.664], [-0.01039,-0.66139], [-0.04272,-0.65356], [-0.0695,-0.6405], [-0.08983,-0.62333], [-0.10283,-0.60317], [-0.1085,-0.58], [-0.10711,-0.55778], [-0.09894,-0.53911], [-0.084,-0.524], [-0.05413,-0.50475], [-0.0195,-0.487], [0.1675,-0.4], [0.20217,-0.38078], [0.2315,-0.35644], [0.2555,-0.327], [0.27272,-0.29222], [0.28172,-0.25189], [0.2825,-0.206], [0.27428,-0.15566], [0.25662,-0.11163], [0.22953,-0.07391], [0.193,-0.0425], [0.14803,-0.01778], [0.09562,-0.00013], [0.03578,0.01047], [-0.0315,0.014], [-0.08675,0.01175], [-0.1365,0.005], [-0.18013,-0.00538], [-0.217,-0.0185], [-0.24662,-0.03388], [-0.2685,-0.051], [-0.27625,-0.07875], [-0.2775,-0.112], [-0.27313,-0.14787], [-0.264,-0.1835], [-0.25138,-0.21537], [-0.2365,-0.24], [-0.2275,-0.24], [-0.2235,-0.18925], [-0.2055,-0.141], [-0.17425,-0.0985], [-0.1305,-0.065], [-0.09494,-0.04889], [-0.05494,-0.03922], [-0.0105,-0.036], [0.03333,-0.03933], [0.06883,-0.04933], [0.096,-0.066], [0.11517,-0.08689], [0.12667,-0.10956], [0.1305,-0.134], [0.12438,-0.1645], [0.106,-0.192], [0.08606,-0.20933], [0.05889,-0.22667], [0.0245,-0.244], [-0.1385,-0.32], [-0.18033,-0.344], [-0.21383,-0.37333], [-0.239,-0.408], [-0.2555,-0.447], [-0.263,-0.48933], [-0.2615,-0.535], [-0.24875,-0.5885], [-0.2245,-0.633], [-0.18963,-0.66813], [-0.145,-0.6935], [-0.09113,-0.70888]], [[0.2185,-0.704], [0.2155,-0.683], [0.0705,-0.683], [0.0705,-0.704]]]


def test_bevelled_overlapping_contours_stay_closed(project: Project) -> None:
    """#66: where the bar joins the S, the united outline has a 0.2 mm step and a 10 mm notch; vertices clamped to
    different bevel insets there swept their edges across each other and the cap couldn't be triangulated (E013)."""
    (outline,) = nonzero(CINZEL_S_900)
    text = f"name: thing\nclass: prop\nparts:\n  - extrude: {{ points: {outline}, height: 0.16 }}\n    color: red\n    bevel: 0.015\n"
    built = built_of(project, text)
    assert closed_faces(built.painted.faces) and built.pieces == 1


def test_font_axes_needs_a_variable_font(project: Project) -> None:
    _overlap_font(project.root / "fonts" / "overlap.ttf")
    text = "name: thing\nparts:\n  - extrude: { text: L, font: fonts/overlap.ttf, height: 0.1, font_axes: { wght: 900 } }\n    color: red\n"
    assert any(f.rule == "E003" and "isn't a variable font" in f.message for f in errors_of(project, text))
    assert any(f.rule == "E003" and "font_axes" in f.message for f in errors_of(project, text.replace("{ wght: 900 }", "900")))
