"""#198: a pixel motif tiled round a part's axis."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model
from PIL import Image

from kiln.lint import lint_paths
from kiln.notation import Pattern
from kiln.paint import _pattern_fn
from kiln.project import Project

HAT = """\
name: thing
budget: 12000
resolution: 0.008
parts:
  - cylinder: { at: [0, 0.25, 0], radius: 0.3, height: 0.5 }
    color: blue
    pattern: { type: pixel, color: gold, size: 0.03, at: 0.0, repeat: 8, rows: ["#..#", ".##.", "#..#"] }
"""


def test_the_motif_function() -> None:
    p = Pattern("pixel", "#000000", "black", 0.1, (0.0, 1.0, 0.0), 0.5, pixels=("#.", ".#"), repeat=4)
    f = _pattern_fn(p)
    cell = 2 * np.pi / 8  # 8 columns round (2 x 4)

    def at(col: float, row: float) -> float:  # the middle of a cell
        a = (col + 0.5) * cell
        return float(f(np.array([[np.cos(a), 0.1 - (row + 0.5) * 0.1, np.sin(a)]]))[0])

    assert at(0, 0) > 0 and at(1, 0) < 0 and at(0, 1) < 0 and at(1, 1) > 0  # rows top first, columns round
    assert at(2, 0) > 0  # the motif repeats round
    assert at(0, 3) < 0  # nothing outside its rows


def test_a_trim_builds_and_shows_both_colours(project: Project) -> None:
    p = lint_paths(project, [write_model(project, HAT)]).built["thing"].painted
    names = [g.color_name.split("#")[0] for g in p.groups]
    tri = p.vertices[p.faces]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    gold = np.isin(p.face_group, [i for i, n in enumerate(names) if n == "gold"])
    side = 2 * np.pi * 0.3 * 0.09  # the band: 3 rows of 3 cm round the side
    assert 0.3 * side < area[gold].sum() < 0.7 * side  # about the motif's painted share (5 of 12 cells)
    y = tri[gold].mean(axis=1)[:, 1]
    assert y.min() > 0.25 - 0.05 and y.max() < 0.25 + 0.05  # within its rows, round the part's own centre


def test_an_image_motif_and_errors(project: Project) -> None:
    img = Image.new("RGBA", (4, 3), (0, 0, 0, 0))
    for x, y in ((0, 0), (3, 0), (1, 1), (2, 1), (0, 2), (3, 2)):
        img.putpixel((x, y), (255, 255, 255, 255))
    img.save(project.root / "decals" / "motif.png")
    model, _, findings = load(project, HAT.replace('rows: ["#..#", ".##.", "#..#"]', "image: decals/motif.png"))
    assert model is not None and not findings, findings
    assert model.parts[0].patterns[0].pixels == ("#..#", ".##.", "#..#")
    for bad in ('rows: ["#.", "#"]', "repeat: 0, rows: [\"#\"]", 'rows: ["#"], image: decals/motif.png', "image: nope.png"):
        _, _, findings = load(project, HAT.replace('rows: ["#..#", ".##.", "#..#"]', bad))
        assert findings, bad
    _, _, findings = load(project, HAT.replace("type: pixel", "type: stripes"))
    assert any("for type: pixel" in f.message for f in findings), findings
