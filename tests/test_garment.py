"""#193: garment, a layer of clothing fitted to earlier parts."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project

TORSO = """\
name: thing
resolution: 0.008
budget: 6000
parts:
  - capsule: { from: [0, 0.6, 0], to: [0, 1.2, 0], radius: 0.22 }
    id: body
    color: wood
  - garment: { fit: [body], gap: 0.01, from_y: 0.75, to_y: 1.3, hem: 0.015, openings: [{ at: [0, 1.05, 0.25], size: [0.14, 0.25, 0.12] }] }
    id: shirt
    color: blue
"""


def test_it_expands_to_a_fitted_shell_a_hem_and_a_cut(project: Project) -> None:
    model, _, findings = load(project, TORSO)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    shirt = [p for p in model.parts if p.id == "shirt"]
    assert len(shirt) == 2 and all(p.geometry.shell > 0 and p.geometry.fit is not None for p in shirt)  # the layer and its hem
    assert shirt[1].geometry.shell > shirt[0].geometry.shell  # the hem is thicker
    opening = model.parts[-1]
    assert opening.geometry.op == "cut" and opening.cut_only == "shirt"


def test_it_builds_a_layer_off_the_body(project: Project) -> None:
    built = lint_paths(project, [write_model(project, TORSO)]).built["thing"]
    p = built.painted
    names = [g.color_name.split("#")[0] for g in p.groups]
    v = p.vertices[np.unique(p.faces[p.face_group == names.index("blue")])]
    radius = np.linalg.norm(v[:, [0, 2]], axis=1)
    middle = (v[:, 1] > 0.85) & (v[:, 1] < 1.15)
    assert float(np.median(radius[middle])) > 0.22 + 0.01  # outside the body by about the gap and the wall
    assert v[:, 1].min() > 0.74 and v[:, 1].max() < 1.31  # between its hem and its top
    body = p.vertices[p.faces[p.face_group == names.index("wood")]].mean(axis=1)  # face centres
    front = (np.abs(body[:, 0]) < 0.05) & (np.abs(body[:, 1] - 1.05) < 0.1) & (body[:, 2] > 0.18)
    assert front.any()  # the body shows through the opening ...
    assert (body[:, 1] < 0.74).any()  # ... and below the hem


def test_errors(project: Project) -> None:
    for bad, why in (("fit: [nobody]", "no earlier part"), ("fit: [body], from_y: 1.3, to_y: 0.8", "from_y < to_y"),
                     ("fit: [body], openings: [{ at: [0, 1, 0] }]", "openings[0]"), ("fit: [body], colour: red", "garment: {")):
        _, _, findings = load(project, TORSO.replace("fit: [body], gap: 0.01, from_y: 0.75, to_y: 1.3, hem: 0.015, openings: [{ at: [0, 1.05, 0.25], size: [0.14, 0.25, 0.12] }]", bad))
        assert any(why in f.message for f in findings), (bad, findings)
    _, _, findings = load(project, TORSO.replace("    id: shirt\n", ""))
    assert any("give it an id" in f.message for f in findings), findings
