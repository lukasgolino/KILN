"""#146: a decal on a part whose colours other parts share (gradient bands, pattern stripes) marks only its own faces."""

from __future__ import annotations

import time

import numpy as np
import pytest
from conftest import write_model
from PIL import Image

from kiln.lint import lint_paths
from kiln.project import Project

TWO = """\
name: thing
parts:
  - box: { at: [-0.3, 0.3, 0], size: [0.4, 0.6, 0.4], round: 0.05 }
    color: red
EXTRA
    decal: { image: decals/sq.png, axis: z, at: [-0.3, 0.3, 0.2], size: [1.4, 0.5] }
  - box: { at: [0.3, 0.3, 0], size: [0.4, 0.6, 0.4], round: 0.05 }
    color: red
EXTRA
"""
GRADIENT = "    gradient: { to: blue, steps: 3 }\n"
STRIPES = "    pattern: { type: stripes, color: blue, size: 0.1, axis: y }\n"


def square(project: Project) -> None:
    Image.new("RGBA", (64, 64), (250, 220, 40, 255)).save(project.root / "decals" / "sq.png")


@pytest.mark.parametrize("extra", [GRADIENT, STRIPES])
def test_a_wide_decal_stays_on_its_own_part_and_covers_its_bands(project: Project, extra: str) -> None:
    square(project)
    p = lint_paths(project, [write_model(project, TWO.replace("EXTRA\n", extra))]).built["thing"].painted
    tri = p.vertices[p.faces]
    centre = tri.mean(axis=1)
    on = p.face_decal >= 0
    assert not (on & (centre[:, 0] > 0.05)).any()  # nothing on the right box, though the rectangle reaches it
    front = (centre[:, 0] < -0.12) & (centre[:, 0] > -0.48) & (np.abs(centre[:, 1] - 0.3) < 0.2) & (centre[:, 2] > 0.19)
    area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1) / 2
    assert area[front & on].sum() > 0.95 * area[front].sum()  # its own front, every band of it, carries the decal


def test_a_pocket_cut_into_the_decal_keeps_its_floor(project: Project) -> None:
    """A cut wall or floor is the cut part's surface, though a same-coloured part inside the pocket is nearer."""
    square(project)
    text = """\
name: thing
parts:
  - box: { at: [0, 0.3, 0], size: [0.6, 0.6, 0.4], round: 0.02 }
    color: red
    gradient: { to: blue, steps: 3 }
    decal: { image: decals/sq.png, axis: z, at: [0, 0.3, 0.2], size: [0.5, 0.5] }
  - sphere: { at: [0, 0.3, 0.02], radius: 0.06 }
    color: red
    gradient: { to: blue, steps: 3 }
  - box: { at: [0, 0.3, 0.2], size: [0.3, 0.3, 0.3] }
    cut: true
"""
    p = lint_paths(project, [write_model(project, text)]).built["thing"].painted
    tri = p.vertices[p.faces]
    centre = tri.mean(axis=1)
    floor = (np.abs(centre[:, 2] - 0.05) < 0.01) & (np.abs(centre[:, 0]) < 0.14) & (np.abs(centre[:, 1] - 0.3) < 0.14)
    floor &= np.linalg.norm(centre - [0, 0.3, 0.02], axis=1) > 0.08  # (not the sphere)
    assert floor.any() and (p.face_decal[floor] >= 0).mean() > 0.9


def test_many_parts_sharing_a_gradient_stay_cheap(project: Project) -> None:
    square(project)
    balls = "".join(f"  - sphere: {{ at: [{0.5 + (k % 10) * 0.12:.2f}, {0.1 + (k // 10) * 0.12:.2f}, 0], radius: 0.05 }}\n    color: red\n{GRADIENT}"
                    for k in range(60))  # fmt: skip
    text = TWO.replace("EXTRA\n", GRADIENT) + balls
    start = time.perf_counter()
    lint_paths(project, [write_model(project, text)])
    assert time.perf_counter() - start < 60  # (each part's distance only near it; 0.2 s of paint, not seconds)
