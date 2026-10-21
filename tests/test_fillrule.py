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


def test_font_axes_needs_a_variable_font(project: Project) -> None:
    _overlap_font(project.root / "fonts" / "overlap.ttf")
    text = "name: thing\nparts:\n  - extrude: { text: L, font: fonts/overlap.ttf, height: 0.1, font_axes: { wght: 900 } }\n    color: red\n"
    assert any(f.rule == "E003" and "isn't a variable font" in f.message for f in errors_of(project, text))
    assert any(f.rule == "E003" and "font_axes" in f.message for f in errors_of(project, text.replace("{ wght: 900 }", "900")))
