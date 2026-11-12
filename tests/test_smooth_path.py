"""#179: tubes and locks follow a smooth curve through their points with smooth: true (straight lines by default)."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project
from kiln.sdf import PATH_STEPS, smooth_path

WAVE = [[0, 0.5, 0], [0.2, 0.7, 0], [0.4, 0.5, 0], [0.6, 0.3, 0], [0.8, 0.5, 0]]


def test_the_curve_passes_through_every_point_and_bends_between_them() -> None:
    curve = np.asarray(smooth_path(WAVE))
    assert len(curve) == 1 + (len(WAVE) - 1) * PATH_STEPS
    assert np.allclose(curve[::PATH_STEPS], WAVE, atol=1e-9)  # through every point, in order
    mid = curve[PATH_STEPS // 2]  # halfway along the first span: off the straight line towards the crest
    assert mid[1] > 0.6 + 0.005
    steps = np.diff(curve, axis=0)
    turns = np.einsum("ij,ij->i", steps[1:], steps[:-1]) / (np.linalg.norm(steps[1:], axis=1) * np.linalg.norm(steps[:-1], axis=1))
    assert turns.min() > np.cos(np.radians(30))  # no kinks: each piece turns a little
    assert smooth_path(WAVE[:2]) == [[float(v) for v in q] for q in WAVE[:2]]  # two points: a straight line


def test_notation_and_build(project: Project) -> None:
    pts = ", ".join(f"[{x}, {y}, {z}]" for x, y, z in WAVE)
    tube = f"name: thing\nparts:\n  - tube: {{ points: [{pts}], radius: 0.03, smooth: true }}\n    color: wood\n"
    model, _, findings = load(project, tube)
    assert model is not None and not findings, findings
    assert len(model.parts[0].geometry.params["points"]) == 33 and "smooth" not in model.parts[0].geometry.params
    model, _, _ = load(project, tube.replace(", smooth: true", ""))
    assert model is not None and model.parts[0].geometry.params["points"] == [list(map(float, q)) for q in WAVE]  # straight by default
    lock = f"name: thing\nparts:\n  - lock: {{ points: [{pts}], width: 0.06, thickness: 0.02, smooth: true }}\n    color: wood\n"
    model, _, findings = load(project, lock)
    assert model is not None and not findings and len(model.parts[0].geometry.params["points"]) == 33, findings
    built = lint_paths(project, [write_model(project, tube)]).built["thing"]
    assert built.triangles > 0
    _, _, findings = load(project, tube.replace("smooth: true", "smooth: 2"))
    assert [f.where for f in findings] == ["parts[0].tube.smooth"], findings
