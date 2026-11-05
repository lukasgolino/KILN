"""#109: software previews show the occlusion atlas_ao bakes into the vertex colours."""

from __future__ import annotations

import numpy as np
from conftest import write_model

from kiln.atlas import ambient_occlusion
from kiln.lint import lint_paths
from kiln.project import Project
from kiln.render import View, render

NOOK = """\
name: thing
parts:
  - box: { at: [0, 0.2, 0], size: [0.6, 0.4, 0.6] }
    color: white
  - box: { at: [0, 0.5, -0.2], size: [0.6, 0.6, 0.2] }
    color: white
"""


def test_render_multiplies_in_the_baked_occlusion(project: Project) -> None:
    built = lint_paths(project, [write_model(project, NOOK)]).built["thing"]
    plain = np.asarray(render(built, View(30, 20), 96)).astype(float)
    built.ao = ambient_occlusion(built, 0.65)
    shaded = np.asarray(render(built, View(30, 20), 96)).astype(float)
    lit = plain[..., 3] > 0
    assert shaded[lit][:, :3].mean() < plain[lit][:, :3].mean() - 0.2  # the nook darkens
    assert (shaded[..., 3] == plain[..., 3]).all()  # same silhouette
