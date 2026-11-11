"""#167: lint W128, a round part on so few triangles that it reads as a polygon."""

from __future__ import annotations

from conftest import write_model

from kiln.lint import lint_paths
from kiln.project import Project

SPHERES = "".join(f"  - sphere: {{ at: [{(i % 8) * 0.25:.2f}, {0.1 + (i // 8) * 0.25:.2f}, 0], radius: 0.1 }}\n    color: wood\n" for i in range(40))


def w128(project: Project, text: str) -> list[str]:
    return [f.message for f in lint_paths(project, [write_model(project, text)]).findings if f.rule == "W128"]


def test_forty_small_spheres_on_a_small_budget_warn(project: Project) -> None:
    found = w128(project, "name: thing\nclass: prop\nbudget: 1000\nparts:\n" + SPHERES)
    assert len(found) == 40 and "reads as a polygon" in found[0] and "budget: (1000)" in found[0]
    assert w128(project, "name: thing\nclass: prop\nbudget: 3000\nparts:\n" + SPHERES) == []  # ~75 each: round enough


def test_a_mostly_hidden_or_hard_part_is_fine(project: Project) -> None:
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
    assert w128(project, "name: thing\nclass: prop\nbudget: 1000\nlint: { disable: [W128] }\nparts:\n" + SPHERES) == []  # can be turned off


def test_copies_count_each(project: Project) -> None:
    ring = "name: thing\nclass: prop\nbudget: 400\nparts:\n  - sphere: { at: [0.5, 0.1, 0], radius: 0.1 }\n    color: wood\n" \
           "    array: { count: 12, around: y }\n"
    found = w128(project, ring)
    assert len(found) == 1 and "copies" in found[0]
