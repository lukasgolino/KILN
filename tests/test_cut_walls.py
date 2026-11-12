"""#178: a cut with a colour paints the walls it makes (an inked groove, panel lines)."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import built_of, errors_of

from kiln.project import Project

GROOVE = """\
name: thing
parts:
  - box: {{ at: [0, 0.2, 0], size: [0.6, 0.4, 0.6] }}
    color: red{hard}
  - box: {{ at: [0, 0.4, 0], size: [0.06, 0.12, 0.8] }}
    cut: true
    color: black
"""


@pytest.mark.parametrize("hard", ["", "\n    hard: true"])
def test_a_coloured_cut_paints_its_walls(project: Project, hard: str) -> None:
    built = built_of(project, GROOVE.format(hard=hard))
    p = built.painted
    centre = p.vertices[p.faces].mean(axis=1)
    black = np.array([p.groups[g].color == "#141414" for g in p.face_group])
    in_groove = (np.abs(centre[:, 0]) < 0.03 + 1e-3) & (centre[:, 1] > 0.34 - 1e-3) & (centre[:, 1] < 0.4 - 1e-3)
    top = (centre[:, 1] > 0.4 - 1e-3) & (np.abs(centre[:, 0]) > 0.06)
    area = 0.5 * np.linalg.norm(np.cross(p.vertices[p.faces[:, 1]] - p.vertices[p.faces[:, 0]], p.vertices[p.faces[:, 2]] - p.vertices[p.faces[:, 0]]), axis=1)
    assert area[in_groove & black].sum() > 0.8 * area[in_groove].sum() > 0  # the groove's floor and sides
    assert area[top & black].sum() < 0.05 * area[top].sum()  # the top around it stays red


def test_a_plain_cut_paints_nothing(project: Project) -> None:
    built = built_of(project, GROOVE.format(hard="").replace("    color: black\n", ""))
    assert {g.color for g in built.painted.groups} == {"#e8413c"}


@pytest.mark.parametrize("extra", ["    intersect: true\n    color: black\n", "    cut: true\n    material: metal\n"])
def test_paint_on_intersects_and_material_alone_are_refused(project: Project, extra: str) -> None:
    text = "name: thing\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.6, 0.4, 0.6] }\n    color: red\n  - box: { at: [0, 0.4, 0], size: [0.1, 0.1, 0.1] }\n" + extra
    assert any(f.rule == "E003" for f in errors_of(project, text)), extra


def test_a_part_laid_in_the_groove_keeps_its_colour(project: Project) -> None:
    text = GROOVE.format(hard="") + "  - capsule: { from: [0, 0.37, -0.2], to: [0, 0.37, 0.2], radius: 0.025 }\n    color: blue\n"
    p = built_of(project, text).painted
    blue = np.array([p.groups[g].color == "#2f6fd0" for g in p.face_group])
    c = p.vertices[p.faces].mean(axis=1)
    rod = (np.hypot(c[:, 0], c[:, 1] - 0.37) < 0.028) & (np.abs(c[:, 2]) < 0.18) & (c[:, 1] > 0.35)
    assert rod.any() and blue[rod].mean() > 0.7  # the rod is blue, not the groove's black (was 0; the rest: groove faces near it)
