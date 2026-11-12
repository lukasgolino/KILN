"""#194: pattern offset; jittered, varied, seeded dots; a second dots pattern no longer hides under the first."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.notation import Pattern
from kiln.paint import _pattern_fn
from kiln.project import Project

TWO = """\
name: thing
budget: 8000
resolution: 0.01
parts:
  - sphere: { at: [0, 0.4, 0], radius: 0.4 }
    color: white
    pattern:
      - { type: dots, color: wood, size: 0.12, width: 0.4 }
      - { type: dots, color: blue, size: 0.12, width: 0.4 }
"""


def test_a_second_dots_pattern_shows(project: Project) -> None:
    p = lint_paths(project, [write_model(project, TWO)]).built["thing"].painted
    tri = p.vertices[p.faces]
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    by = {name: area[np.isin(p.face_group, [i for i, g in enumerate(p.groups) if g.color_name.split("#")[0] == name])].sum()
          for name in ("wood", "blue")}
    assert by["blue"] > 0.5 * by["wood"] > 0  # both colours show, about as much


def test_offset_shifts_and_jitter_is_seeded() -> None:
    plain = Pattern("dots", "#000000", "black", 0.1, (0.0, 1.0, 0.0), 0.4)
    moved = Pattern("dots", "#000000", "black", 0.1, (0.0, 1.0, 0.0), 0.4, offset=(0.05, 0.0, 0.0))
    x = np.array([[0.0, 0.0, 0.0], [0.05, 0.0, 0.0]])
    a, b = _pattern_fn(plain)(x), _pattern_fn(moved)(x)
    assert a[0] > 0 > a[1] and b[1] > 0 > b[0]  # the dot moved half a cell
    jit = [Pattern("dots", "#000000", "black", 0.1, (0.0, 1.0, 0.0), 0.5, jitter=0.6, vary=0.5, seed=s) for s in (1, 1, 2)]
    grid = np.stack(np.meshgrid(*[np.linspace(0, 0.5, 40)] * 2, indexing="ij"), axis=-1).reshape(-1, 2)
    pts = np.c_[grid[:, 0], np.zeros(len(grid)), grid[:, 1]]
    v = [_pattern_fn(q)(pts) > 0 for q in jit]
    assert (v[0] == v[1]).all() and (v[0] != v[2]).any()  # the same seed draws the same dots, another seed others
    assert (v[0] != (_pattern_fn(plain)(pts) > 0)).any()  # moved off the grid


def test_notation(project: Project) -> None:
    model, _, findings = load(project, TWO)
    assert model is not None and not findings, findings
    first, second = model.parts[0].patterns
    assert first.offset == (0.0, 0.0, 0.0) and second.offset == (0.06, 0.06, 0.06)  # half a cell over by itself
    for bad in ("jitter: 2", "offset: 0.1", "vary: -1", "seed: 1.5"):
        _, _, findings = load(project, TWO.replace("width: 0.4 }\n", f"width: 0.4, {bad} }}\n", 1))
        assert findings, bad
    _, _, findings = load(project, TWO.replace("{ type: dots, color: wood, size: 0.12, width: 0.4 }", "{ type: stripes, color: wood, size: 0.12, jitter: 0.5 }"))
    assert any("for dots" in f.message for f in findings), findings
