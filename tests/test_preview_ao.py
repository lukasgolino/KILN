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
    built.ao = ambient_occlusion(built, 0.65)[built.painted.faces]
    shaded = np.asarray(render(built, View(30, 20), 96)).astype(float)
    lit = plain[..., 3] > 0
    assert shaded[lit][:, :3].mean() < plain[lit][:, :3].mean() - 0.2  # the nook darkens
    assert (shaded[..., 3] == plain[..., 3]).all()  # same silhouette


def test_preview_commands_read_atlas_ao_from_kiln_toml(in_project: Project, capsys: object) -> None:
    from kiln.cli import _built

    write_model(in_project, NOOK)
    assert _built(in_project, "thing").ao is None
    cfg = in_project.root / "kiln.toml"
    cfg.write_text(cfg.read_text() + "\natlas = true\natlas_ao = 0.5\n")
    from kiln.project import load_project

    built = _built(load_project(in_project.root), "thing")
    assert built.ao is not None and built.ao.min() >= 0.5 and built.ao.min() < 1.0


def test_fitted_and_effect_merges_carry_the_occlusion(project: Project) -> None:
    from kiln.preview import _merged_ao

    built = lint_paths(project, [write_model(project, NOOK)]).built["thing"]
    assert _merged_ao([built, built]) is None
    built.ao = ambient_occlusion(built, 0.5)[built.painted.faces]
    merged = _merged_ao([built, built])
    assert merged is not None and len(merged) == 2 * len(built.painted.faces)
