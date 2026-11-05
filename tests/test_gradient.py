"""#106: gradient: a part's colour going to another, root to tip, in steps."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project

MODEL = """\
name: thing
parts:
  - sphere: {{ at: [0, 0.3, 0], radius: 0.3 }}
    color: red
  - capsule: {{ from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }}
    color: red
    gradient: {gradient}
"""


def test_gradient_becomes_bands(project: Project) -> None:
    model, _, findings = load(project, MODEL.format(gradient="{ to: white, steps: 3 }"))
    assert model is not None, findings
    part = model.parts[1]
    assert [round(p.at, 4) for p in part.patterns] == [0.3333, 0.6667] and all(p.type == "along" for p in part.patterns)
    white = part.patterns[-1].color
    assert part.patterns[-1].color_name == "white" and part.patterns[0].color not in (part.color, white)  # a mix between


def test_gradient_paints_root_to_tip(project: Project) -> None:
    path = write_model(project, MODEL.format(gradient="{ to: white, steps: 3 }"))
    result = lint_paths(project, [path])
    assert not [f for f in result.findings if f.severity == "error"], result.findings
    built = result.built["thing"]
    p = built.painted
    centres = p.vertices[p.faces].mean(axis=1)
    on_capsule = (centres[:, 1] > 0.62) & (np.abs(centres[:, 0]) < 0.06)
    colours = np.array([p.groups[g].color for g in p.face_group])
    low = colours[on_capsule & (centres[:, 1] < 0.66)]
    tip = colours[on_capsule & (centres[:, 1] > 0.86)]
    model = built.model
    assert set(tip) == {model.parts[1].patterns[-1].color}
    assert model.parts[1].patterns[0].color in set(low)


def test_gradient_from_and_axis(project: Project) -> None:
    text = MODEL.format(gradient="{ from: blue, to: white, steps: 2, along: y }").replace("capsule: { from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }",
                                                                                           "box: { at: [0, 0.7, 0], size: [0.1, 0.4, 0.1] }")
    model, _, findings = load(project, text)
    assert model is not None, findings
    part = model.parts[1]
    assert part.color_name == "blue" and len(part.patterns) == 1 and part.patterns[0].at == 0.5


@pytest.mark.parametrize("gradient", ["{ steps: 3 }", "{ to: white, steps: 1 }", "{ to: white, along: sideways }", "{ to: nocolour }"])
def test_bad_gradient(project: Project, gradient: str) -> None:
    _, _, findings = load(project, MODEL.format(gradient=gradient))
    assert any(f.rule in ("E003", "E004") and (f.where or "").startswith("parts[1].gradient") for f in findings), findings


def test_path_gradient_needs_a_path(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white, along: path }").replace("capsule: { from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }",
                                                                      "box: { at: [0, 0.7, 0], size: [0.1, 0.4, 0.1] }")
    _, _, findings = load(project, text)
    assert any(f.rule == "E003" and f.where == "parts[1].gradient" for f in findings)
