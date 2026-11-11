"""#232 part density: a part's weight on the triangle budget in its surface."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project

MODEL = """\
name: thing
class: creature
budget: 1500
parts:
  - ellipsoid: { at: [0, 0.5, 0], radii: [0.3, 0.45, 0.25] }
    id: body
    color: wood
  - sphere: { at: [0, 1.1, 0], radius: 0.2 }
    id: head
    color: wood
    blend: 0.05
"""


def head_share(project: Project, density: str = "") -> tuple[float, int]:
    built = lint_paths(project, [write_model(project, MODEL + density)]).built["thing"]
    p = built.painted
    centres = p.vertices[p.faces].mean(axis=1)
    return float((centres[:, 1] > 0.95).mean()), len(p.faces)


def test_notation(project: Project) -> None:
    model, _, findings = load(project, MODEL + "    density: 3\n")
    assert model is not None and not findings, findings
    assert [p.density for p in model.parts] == [1.0, 3.0]
    for bad in ("0", "20", "dense"):
        _, _, findings = load(project, MODEL + f"    density: {bad}\n")
        assert [f.where for f in findings] == ["parts[1].density"], (bad, findings)
    _, _, findings = load(project, "normal_map: 256\n" + MODEL + "    density: 2\n    detail: true\n")
    assert any(f.where == "parts[1].density" for f in findings), findings
    mirrored = MODEL.replace("  - sphere: { at: [0, 1.1, 0], radius: 0.2 }\n    id: head", "  - sphere: { at: [0.1, 1.1, 0], radius: 0.2 }\n    id: head\n    mirror: x")
    model, _, findings = load(project, mirrored + "    density: 2\n")
    assert model is not None and [p.density for p in model.parts][1:] == [2.0] * (len(model.parts) - 1), findings


def test_a_dense_part_gets_more_of_the_same_budget(project: Project) -> None:
    plain, total = head_share(project)
    dense, dense_total = head_share(project, "    density: 3\n")
    coarse, _ = head_share(project, "    density: 0.5\n")
    assert dense > plain * 1.3 and coarse < plain * 0.6
    assert abs(dense_total - total) <= total * 0.03  # the total stays the budget


def test_density_1_is_the_default_build(project: Project) -> None:
    a = lint_paths(project, [write_model(project, MODEL)]).built["thing"].painted
    b = lint_paths(project, [write_model(project, MODEL + "    density: 1\n")]).built["thing"].painted
    assert np.array_equal(a.vertices, b.vertices) and np.array_equal(a.faces, b.faces)


def test_a_small_dense_part_keeps_what_it_has_and_the_rest_take_the_budget(project: Project) -> None:
    """A part asking for more than its full-resolution triangles keeps them all; the leftover goes to the rest."""
    tiny = MODEL.replace("radius: 0.2 }\n    id: head", "radius: 0.04 }\n    id: head") + "    density: 8\n"
    built = lint_paths(project, [write_model(project, tiny)]).built["thing"]
    assert len(built.painted.faces) > 1500 * 0.9
