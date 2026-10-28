"""#29: font text fills nonzero (overlapping glyph contours join), and font_axes picks a variable font's instance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import built_of, closed_faces, errors_of, ok_model
from kiln.fillrule import _area, _inside, needs_union, nonzero, untangle
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


# Cinzel's 8 at wght 700 (OFL), as svgpath gives it: one contour that crosses itself four times at the waist
CINZEL_8_700 = [[[-0.2225,-0.5215], [-0.21937,-0.55913], [-0.20998,-0.59317], [-0.19432,-0.62361], [-0.16071,-0.66171], [-0.11623,-0.69009], [-0.06283,-0.70783], [-0.00243,-0.714], [0.0555,-0.70914], [0.10828,-0.69379], [0.15349,-0.66875], [0.18868,-0.63488], [0.20544,-0.6078], [0.2155,-0.57764], [0.21885,-0.54439], [0.21263,-0.50166], [0.19396,-0.46511], [0.16522,-0.43515], [0.12878,-0.41221], [0.08687,-0.39646], [0.04171,-0.38807], [0.01046,-0.39396], [0.03736,-0.41159], [0.05782,-0.43634], [0.07253,-0.4658], [0.08214,-0.49757], [0.08729,-0.52911], [0.08861,-0.55786], [0.08214,-0.60217], [0.06395,-0.63818], [0.04572,-0.65601], [0.02312,-0.66704], [-0.00386,-0.67125], [-0.03005,-0.66866], [-0.05197,-0.65926], [-0.06961,-0.64305], [-0.08705,-0.61047], [-0.09286,-0.57154], [-0.08963,-0.5431], [-0.07995,-0.51773], [-0.06315,-0.49428], [-0.03857,-0.47161], [-0.00533,-0.44832], [0.03746,-0.42303], [0.11734,-0.38104], [0.19025,-0.33539], [0.22005,-0.30789], [0.24309,-0.27561], [0.25783,-0.23691], [0.26275,-0.19018], [0.25896,-0.14925], [0.2476,-0.11247], [0.22866,-0.07984], [0.20285,-0.05171], [0.17086,-0.02843], [0.13271,-0.01], [0.06557,0.008], [-0.01214,0.014], [-0.0593,0.01149], [-0.10518,0.00395], [-0.14806,-0.00891], [-0.18621,-0.02736], [-0.21825,-0.05199], [-0.24277,-0.08339], [-0.25815,-0.12185], [-0.26275,-0.16764], [-0.25876,-0.20432], [-0.24757,-0.23605], [-0.2306,-0.26313], [-0.20927,-0.28582], [-0.15866,-0.32018], [-0.10547,-0.34255], [-0.08117,-0.35022], [-0.0605,-0.35618], [-0.02193,-0.35539], [-0.06422,-0.33025], [-0.09911,-0.29382], [-0.11647,-0.26269], [-0.127,-0.22539], [-0.13068,-0.18193], [-0.12722,-0.13836], [-0.1163,-0.1015], [-0.09793,-0.07136], [-0.07308,-0.0487], [-0.04274,-0.03429], [-0.00689,-0.02814], [0.02974,-0.03036], [0.06107,-0.04064], [0.08656,-0.05774], [0.10566,-0.08038], [0.11759,-0.10701], [0.12157,-0.13611], [0.11911,-0.16025], [0.11171,-0.18138], [0.09943,-0.20037], [0.08229,-0.21809], [0.06047,-0.23507], [0.03418,-0.25182], [0.00344,-0.26898], [-0.03171,-0.28714], [-0.09586,-0.32388], [-0.12798,-0.34603], [-0.15793,-0.37175], [-0.18404,-0.40167], [-0.20464,-0.43641], [-0.21804,-0.47626]]]

# Cinzel's X at wght 400 (OFL): two strokes and five serif bars, overlapping
CINZEL_X_400 = [[[-0.175,-0.7], [0.27,-0.001], [0.19,-0.001], [-0.253,-0.7]], [[-0.162,-0.072], [-0.16775,-0.05788], [-0.167,-0.0435], [-0.16113,-0.03025], [-0.1515,-0.0195], [-0.13962,-0.01238], [-0.127,-0.01], [-0.1205,-0.01], [-0.114,-0.01], [-0.114,0.0], [-0.341,0.0], [-0.341,-0.01], [-0.327,-0.01], [-0.29625,-0.0145], [-0.268,-0.028], [-0.24375,-0.04725], [-0.225,-0.069]], [[-0.022,-0.372], [0.001,-0.329], [-0.207,-0.001], [-0.271,-0.001]], [[0.145,-0.072], [0.227,-0.068], [0.24575,-0.04637], [0.27,-0.0275], [0.298,-0.01438], [0.328,-0.01], [0.342,-0.01], [0.342,0.0], [0.098,0.0], [0.098,-0.01], [0.104,-0.01], [0.11,-0.01], [0.12912,-0.015], [0.1445,-0.03], [0.15137,-0.0505]], [[-0.082,-0.7], [-0.082,-0.69], [-0.088,-0.69], [-0.094,-0.69], [-0.10663,-0.68763], [-0.1185,-0.6805], [-0.128,-0.66975], [-0.1335,-0.6565], [-0.13412,-0.64213], [-0.129,-0.628], [-0.209,-0.631], [-0.22763,-0.65275], [-0.2515,-0.672], [-0.27938,-0.6855], [-0.31,-0.69], [-0.324,-0.69], [-0.324,-0.7]], [[0.255,-0.7], [0.02,-0.354], [-0.014,-0.378], [0.19,-0.7]], [[0.323,-0.7], [0.323,-0.69], [0.309,-0.69], [0.27913,-0.6855], [0.2515,-0.672], [0.22737,-0.65275], [0.208,-0.631], [0.144,-0.628], [0.14987,-0.64213], [0.1495,-0.6565], [0.14413,-0.66975], [0.135,-0.6805], [0.12325,-0.68763], [0.11,-0.69], [0.104,-0.69], [0.098,-0.69], [0.098,-0.7]]]


def _winding(point: list[float], loop: list[list[float]]) -> int:
    x, y = point
    w = 0
    for i in range(len(loop)):
        (x0, y0), (x1, y1) = loop[i - 1], loop[i]
        side = (x1 - x0) * (y - y0) - (x - x0) * (y1 - y0)
        if y0 <= y < y1 and side > 0:
            w += 1
        elif y1 <= y < y0 and side < 0:
            w -= 1
    return w


def _fills_nonzero(raw: list[list[list[float]]], out: list[list[list[float]]]) -> bool:
    """Every sample point of the outlines' box is inside the even-odd fill of `out` exactly where `raw`'s winding
    number is non-zero."""
    xs, ys = [p[0] for loop in raw for p in loop], [p[1] for loop in raw for p in loop]
    for i in range(61):
        for j in range(61):
            pt = [min(xs) + (max(xs) - min(xs)) * (i + 0.5) / 61, min(ys) + (max(ys) - min(ys)) * (j + 0.5) / 61]
            if (sum(_winding(pt, loop) for loop in raw) != 0) != (sum(_inside(pt, loop) for loop in out) % 2 == 1):
                return False
    return True


def test_untangle_splits_a_contour_where_it_crosses_itself() -> None:
    bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0]]
    halves = untangle(bowtie)
    assert sorted(round(_area(loop), 9) for loop in halves) == [-0.25, 0.25]  # each half keeps its own direction
    square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert untangle(square) == [square]


@pytest.mark.parametrize("bevel", [0.0, 0.01])
def test_self_crossing_contour_fills_nonzero(project: Project, bevel: float) -> None:
    """#71: an 8 drawn as one contour crossing itself was passed on as it was (nonzero only joined separate
    contours), so a bevel cracked it (E013). It's split at its crossings: an outline and two counters."""
    out = nonzero(CINZEL_8_700)
    assert len(out) == 3 and _fills_nonzero(CINZEL_8_700, out)
    holes = f", holes: {out[1:]}"
    edge = f"\n    bevel: {bevel}" if bevel else ""
    text = f"name: thing\nclass: prop\nparts:\n  - extrude: {{ points: {out[0]}{holes}, height: 0.16 }}\n    color: red{edge}\n"
    built = built_of(project, text)
    assert built.pieces == 1
    if bevel:
        assert closed_faces(built.painted.faces)


def test_overlapping_serif_bars_fill_as_one_outline(project: Project) -> None:
    """#72: Cinzel's X came out of the union as three outlines (five pieces) and its bevelled build hung in the CSG;
    fixed by splitting CSG outlines that visit a point twice (#67). One outline, one closed piece."""
    out = nonzero(CINZEL_X_400)
    assert len(out) == 1 and _fills_nonzero(CINZEL_X_400, out)
    text = f"name: thing\nclass: prop\nparts:\n  - extrude: {{ points: {out[0]}, height: 0.16 }}\n    color: red\n    bevel: 0.01\n"
    built = built_of(project, text)
    assert built.pieces == 1 and closed_faces(built.painted.faces)


def test_font_axes_needs_a_variable_font(project: Project) -> None:
    _overlap_font(project.root / "fonts" / "overlap.ttf")
    text = "name: thing\nparts:\n  - extrude: { text: L, font: fonts/overlap.ttf, height: 0.1, font_axes: { wght: 900 } }\n    color: red\n"
    assert any(f.rule == "E003" and "isn't a variable font" in f.message for f in errors_of(project, text))
    assert any(f.rule == "E003" and "font_axes" in f.message for f in errors_of(project, text.replace("{ wght: 900 }", "900")))
