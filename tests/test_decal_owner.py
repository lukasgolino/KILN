"""#146: a decal on a part whose colours other parts share (a gradient, a pattern, the same colour) marks only its own faces."""

from __future__ import annotations

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


@pytest.mark.parametrize("extra", ["    gradient: { to: blue, steps: 3 }\n", "    pattern: { type: stripes, color: blue, size: 0.1, axis: y }\n", ""])
def test_a_wide_decal_stays_on_its_own_part(project: Project, extra: str) -> None:
    Image.new("RGBA", (64, 64), (250, 220, 40, 255)).save(project.root / "decals" / "sq.png")
    p = lint_paths(project, [write_model(project, TWO.replace("EXTRA\n", extra))]).built["thing"].painted
    centre = p.vertices[p.faces].mean(axis=1)
    on = p.face_decal >= 0
    assert on.sum() > 20 and not (on & (centre[:, 0] > 0.05)).any()  # nothing on the right box, though the rectangle reaches it
