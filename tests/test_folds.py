"""#204: cloth folds round a part's own axis, deepest at the hem."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project
from kiln.sdf import Folds, folds

ROBE = """\
name: thing
resolution: 0.008
budget: 6000
parts:
  - cone: { at: [0, 0.6, 0], radius: 0.4, radius_top: 0.18, height: 1.2 }
    color: blue
    folds: { count: 12, depth: 0.03, from_y: 0.0, to_y: 1.0 }
"""


def test_the_profile() -> None:
    f = Folds(8, 0.02, 0.0, 1.0)
    ring = np.array([[np.cos(a), 0.0, np.sin(a)] for a in np.linspace(0, 2 * np.pi, 64, endpoint=False)])
    d = folds(ring, f, np.zeros(3), None)
    assert d.min() >= 0 and abs(d.max() - 0.02) < 1e-3  # inward only, as deep as asked at the hem
    assert np.isclose(folds(ring + [0, 1.0, 0], f, np.zeros(3), None), 0).all()  # none at to_y
    assert (folds(ring + [0, 0.5, 0], f, np.zeros(3), None) < d + 1e-12).all()  # shallower higher up
    peaks = np.flatnonzero((d > np.roll(d, 1)) & (d >= np.roll(d, -1)))
    assert len(peaks) == 8  # count hollows round the axis


def test_a_robe_builds_with_folds_at_its_hem(project: Project) -> None:
    built = lint_paths(project, [write_model(project, ROBE)]).built["thing"]
    v = built.painted.vertices[np.unique(built.painted.faces)]
    hem = v[(v[:, 1] > 0.05) & (v[:, 1] < 0.15)]
    plain = lint_paths(project, [write_model(project, ROBE.replace("    folds: { count: 12, depth: 0.03, from_y: 0.0, to_y: 1.0 }\n", ""))]).built["thing"]
    w = plain.painted.vertices[np.unique(plain.painted.faces)]
    hem_plain = w[(w[:, 1] > 0.05) & (w[:, 1] < 0.15)]
    spread = float(np.ptp(np.linalg.norm(hem[:, [0, 2]], axis=1) - (0.4 - (hem[:, 1] / 1.2) * 0.22)))
    spread_plain = float(np.ptp(np.linalg.norm(hem_plain[:, [0, 2]], axis=1) - (0.4 - (hem_plain[:, 1] / 1.2) * 0.22)))
    assert spread > spread_plain + 0.015  # the hem goes in and out by about the fold depth


def test_notation_and_mirror(project: Project) -> None:
    model, _, findings = load(project, ROBE)
    assert model is not None and not findings and model.parts[0].geometry.folds == Folds(12, 0.03, 0.0, 1.0, 0.5)
    for bad in ("{ count: 1, depth: 0.03, from_y: 0, to_y: 1 }", "{ count: 12, depth: 0.03, from_y: 1, to_y: 0 }", "{ count: 12, depth: 0.03 }",
                "{ count: 12, depth: 0.5, from_y: 0, to_y: 1 }"):
        _, _, findings = load(project, ROBE.replace("{ count: 12, depth: 0.03, from_y: 0.0, to_y: 1.0 }", bad))
        assert any(f.where == "parts[0].folds" for f in findings), (bad, findings)
    twin = ROBE.replace("at: [0, 0.6, 0]", "at: [0.5, 0.6, 0]").replace("    color: blue\n", "    color: blue\n    mirror: x\n    mirror_id: other\n")
    model, _, _ = load(project, twin)
    assert model is not None and model.parts[1].geometry.folds == model.parts[0].geometry.folds
