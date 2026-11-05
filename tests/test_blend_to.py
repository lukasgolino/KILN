"""#107: blend_to melts a part into the parts it names and keeps a crisp groove against the rest."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project
from kiln.sdf import Field, Geometry

BODY = Geometry("sphere", {"radius": 0.3})
LOCK = {"from": [-0.05, 0.25, 0], "to": [-0.05, 0.5, 0], "radius": 0.04, "radius_to": 0.04}
TWIN = {**LOCK, "from": [0.05, 0.25, 0], "to": [0.05, 0.5, 0]}


def field(blend_to: bool) -> Field:
    targets = frozenset({0}) if blend_to else None
    return Field([BODY, Geometry("capsule", LOCK, blend=0.04, blend_to=targets), Geometry("capsule", TWIN, blend=0.04, blend_to=targets)], 0.01)


def test_groove_between_neighbours_stays_crisp() -> None:
    groove = np.array([[0.0, 0.42, 0.0]])  # between the two locks, above the body
    assert field(True).distance(groove)[0] == pytest.approx(0.01)  # the gap between them
    assert field(False).distance(groove)[0] < 0.005  # a plain blend fills it


def test_root_still_melts_into_the_body() -> None:
    root = np.array([[-0.095, 0.31, 0.0]])
    crisp = Field([BODY, Geometry("capsule", LOCK)], 0.01).distance(root)[0]
    assert field(True).distance(root)[0] < crisp - 0.002


MODEL = """\
name: thing
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    id: body
    color: red
  - capsule: { from: [-0.05, 0.55, 0], to: [-0.05, 0.8, 0], radius: 0.04 }
    color: red
    blend: 0.04
    blend_to: body
"""


def test_blend_to_parses_and_builds(project: Project) -> None:
    model, _, findings = load(project, MODEL)
    assert model is not None, findings
    assert model.parts[1].geometry.blend_to == frozenset({0})
    result = lint_paths(project, [write_model(project, MODEL)])
    assert not [f for f in result.findings if f.severity == "error"], result.findings


@pytest.mark.parametrize("change", [("blend_to: body", "blend_to: nobody"), ("blend: 0.04", "blend: 0"), ("blend_to: body", "blend_to: 3")])
def test_bad_blend_to(project: Project, change: tuple[str, str]) -> None:
    _, _, findings = load(project, MODEL.replace(*change))
    assert any(f.rule == "E003" and f.where == "parts[1].blend_to" for f in findings), findings
