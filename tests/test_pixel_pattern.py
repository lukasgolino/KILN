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
    p = Pattern("pixel", "#000000", "black", 0.1, (0.0, 1.0, 0.0), 0.5, pixels=("#.", ".#"), repeat=4, frame="model")
    f = _pattern_fn(p)
    cell = 2 * np.pi / 8  # 8 columns round (2 x 4)

    def at(col: float, row: float) -> float:  # the middle of a cell; columns as cylindrical textures: u = atan2(x, z)
        a = (col + 0.5) * cell - np.pi
        return float(f(np.array([[np.sin(a), 0.1 - (row + 0.5) * 0.1, np.cos(a)]]))[0])

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
    assert 0.9 * 6 / 12 * side < area[gold].sum() < 1.1 * 6 / 12 * side  # the motif's painted share (6 of 12 cells), within 10%
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
    for bad in ('rows: ["#.", "#"]', "repeat: 0, rows: [\"#\"]", 'rows: ["#"], image: decals/motif.png'):
        _, _, findings = load(project, HAT.replace('rows: ["#..#", ".##.", "#..#"]', bad))
        assert findings, bad
    _, _, findings = load(project, HAT.replace("type: pixel", "type: stripes"))
    assert any("for type: pixel" in f.message for f in findings), findings


def test_it_reads_left_to_right_from_outside_and_auto_repeats_square() -> None:
    from kiln.paint import pixel_columns
    from kiln.sdf import Geometry

    p = Pattern("pixel", "#000000", "black", 0.03, (0.0, 1.0, 0.0), 0.5, pixels=("#..",), frame="model")
    drum = Geometry("cylinder", {"radius": 0.3, "height": 0.5, "round": 0.0, "sides": 0})
    assert pixel_columns(p, drum) == 3 * round(2 * np.pi * 0.3 / (3 * 0.03))  # auto: cells about as wide as tall
    f = _pattern_fn(p, drum)
    seen = []
    for k in range(3):  # walking round to the right seen from the front (+z): +x is on the right ... then behind
        a = (k + 0.5) * 2 * np.pi / pixel_columns(p, drum) - np.pi
        seen.append(float(f(np.array([[0.3 * np.sin(a), 0.0, 0.3 * np.cos(a)]]))[0]) > 0)
    assert seen == [True, False, False]  # the motif's first column first
    assert float(f(np.array([[0.001, 0.0, 0.0]]))[0]) <= 0  # columns too narrow near the axis aren't painted


def test_hard_parts_dark_images_and_missing_images(project: Project) -> None:
    _, _, findings = load(project, HAT.replace("    color: blue\n", "    color: blue\n    hard: true\n"))
    assert any("pixel pattern goes on a smooth part" in f.message for f in findings), findings
    Image.new("RGB", (3, 1), (255, 255, 255)).save(project.root / "decals" / "plain.png")
    img = Image.open(project.root / "decals" / "plain.png")
    img.putpixel((1, 0), (0, 0, 0))
    img.save(project.root / "decals" / "plain.png")
    model, _, _ = load(project, HAT.replace('rows: ["#..#", ".##.", "#..#"]', "image: decals/plain.png"))
    assert model is not None and model.parts[0].patterns[0].pixels == (".#.",)  # no transparency: the dark pixels
    _, _, findings = load(project, HAT.replace('rows: ["#..#", ".##.", "#..#"]', "image: decals/none.png"))
    assert [f.rule for f in findings] == ["E011"], findings
