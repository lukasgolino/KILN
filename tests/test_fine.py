"""#306: a part's own finer `resolution`: the mesh in its box is refined onto the surface (a face's detail on a coarse
body), watertight, and only there."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import built_of, closed_faces, errors_of

from kiln.export import Built
from kiln.project import Project

HEAD = """\
name: thing
resolution: 0.04
budget: 6000
parts:
  - sphere: {{ at: [0, 0.4, 0], radius: 0.3 }}
    color: red
  - sphere: {{ at: [0, 0.42, 0.31], radius: 0.022 }}
    color: red
    blend: 0.01{extra}
"""


def test_a_fine_part_shows_detail_the_coarse_cells_miss(project: Project) -> None:
    coarse = built_of(project, HEAD.format(extra=""))
    fine = built_of(project, HEAD.format(extra="\n    resolution: 0.004\n    density: 6"))
    tip = 0.31 + 0.022

    def reach(b: Built) -> float:
        return float(b.painted.vertices[:, 2].max())

    assert tip - reach(fine) < 0.004 < tip - reach(coarse)  # the nose's tip is there with its own cells
    assert closed_faces(fine.painted.faces)
    far = fine.painted.vertices[:, 2] < 0.0  # the back of the head keeps the coarse cells
    edges = np.linalg.norm(fine.painted.vertices[fine.painted.faces[:, 0]] - fine.painted.vertices[fine.painted.faces[:, 1]], axis=1)
    back = np.all(fine.painted.vertices[fine.painted.faces][:, :, 2] < -0.1, axis=1)
    assert far.any() and np.median(edges[back]) > 0.02


@pytest.mark.parametrize("value", ["0", "2", "big"])
def test_resolution_is_checked(project: Project, value: str) -> None:
    assert any(f.where == "parts[1].resolution" for f in errors_of(project, HEAD.format(extra=f"\n    resolution: {value}")))
