"""#167: lint W128, a round part on so few triangles that it reads as a polygon."""

from __future__ import annotations

import re

import pytest
from conftest import write_model

from kiln.lint import lint_paths
from kiln.project import Project

AT = [((i % 8) * 0.25, 0.1 + (i // 8) * 0.25) for i in range(40)]
SHAPES = {
    "sphere": "sphere: {{ at: [{x:.2f}, {y:.2f}, 0], radius: 0.1 }}",
    "ellipsoid": "ellipsoid: {{ at: [{x:.2f}, {y:.2f}, 0], radii: [0.1, 0.08, 0.09] }}",
    "capsule": "capsule: {{ from: [{x:.2f}, {y:.2f}, -0.05], to: [{x:.2f}, {y:.2f}, 0.05], radius: 0.07 }}",
    "torus": "torus: {{ at: [{x:.2f}, {y:.2f}, 0], radius: 0.08, thickness: 0.03 }}",
}


def many(shape: str, budget: int, extra: str = "") -> str:
    parts = "".join(f"  - {SHAPES[shape].format(x=x, y=y)}\n    color: wood\n{extra}" for x, y in AT)
    return f"name: thing\nclass: prop\nbudget: {budget}\nparts:\n" + parts


def w128(project: Project, text: str) -> list[str]:
    return [f.message for f in lint_paths(project, [write_model(project, text)]).findings if f.rule == "W128"]


@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_forty_small_round_parts_on_a_small_budget_warn(project: Project, shape: str) -> None:
    found = w128(project, many(shape, 1000))
    assert len(found) >= 30, (shape, found[:1])  # tori get a few more (their curvature draws triangles)
    assert "reads as a polygon" in found[0] and "(now 1000)" in found[0] and "density: " in found[0]


def test_a_rounder_budget_is_quiet(project: Project) -> None:
    assert w128(project, many("sphere", 3000)) == []  # ~75 each: round enough


TWO = "name: thing\nclass: prop\nbudget: 80\nparts:\n  - sphere: { at: [-0.5, 0.3, 0], radius: 0.3 }\n    color: wood\n" \
      "  - sphere: { at: [0, 1.2, 0], radius: 0.3 }\n    color: wood\n"


def test_coarse_spheres_count_all_their_faces_and_the_advice_comes_from_the_shortfall(project: Project) -> None:
    found = w128(project, TWO)
    assert len(found) == 2, found  # ~45 each: a coarse sphere's face centres sit deep inside it, still counted
    n = int(re.search(r"is (\d+) triangles", found[0]).group(1))  # type: ignore[union-attr]
    assert 34 <= n < 48
    raised = int(re.search(r"budget: (\d+) \(now 80\)", found[0]).group(1))  # type: ignore[union-attr]
    assert raised >= 80 * 48 / n and raised % 100 == 0 and "density: 1.5" in found[0]


def test_hard_stretched_shell_and_hidden_parts_are_left_alone(project: Project) -> None:
    for extra in ("    hard: true\n", "    scale: [1, 1.5, 1]\n", "    shell: 0.02\n"):
        assert w128(project, many("sphere", 1000, extra)) == [], extra
    eye = """\
name: thing
class: prop
budget: 400
parts:
  - sphere: { at: [0, 0.5, 0], radius: 0.3 }
    color: white
  - sphere: { at: [0, 0.5, 0.27], radius: 0.05 }
    color: wood
"""
    assert w128(project, eye) == []  # the pupil shows a cap: few triangles are enough
    assert w128(project, many("sphere", 1000).replace("parts:\n", "lint: { disable: [W128] }\nparts:\n", 1)) == []


def test_copies_count_each_and_a_centred_mirror_is_one(project: Project) -> None:
    ring = "name: thing\nclass: prop\nbudget: 400\nparts:\n  - sphere: { at: [0.5, 0.1, 0], radius: 0.1 }\n    color: wood\n" \
           "    array: { count: 12, around: y }\n"
    found = w128(project, ring)
    assert len(found) == 1 and "in each of its 12 copies" in found[0], found
    centred = TWO.replace("[0, 1.2, 0], radius: 0.3 }\n    color: wood\n", "[0, 1.2, 0], radius: 0.3 }\n    color: wood\n    mirror: x\n")
    found = w128(project, centred)
    assert len(found) == 2 and not any("copies" in f for f in found), found  # mirrored about its own centre: one shape
