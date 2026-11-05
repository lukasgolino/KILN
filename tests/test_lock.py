"""#105: the flat tapered `lock` shape and `scale` on any part."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project
from kiln.sdf import Geometry, part_thickness

LOCK = {"points": [[0, 0, 0], [0, 0.3, 0]], "width": 0.08, "thickness": 0.02, "width_to": 0.08, "thickness_to": 0.02, "facing": [0, 0, 1]}

MODEL = """\
name: thing
parts:
  - sphere: {{ at: [0, 0.3, 0], radius: 0.3 }}
    color: red
  - lock: {{ points: [[0, 0.5, 0.25], [0, 0.75, 0.3]], width: 0.08, thickness: 0.02, width_to: 0, facing: [0, 0, 1] }}
    color: red
{extra}"""


def test_lock_section_is_flat_and_elliptical() -> None:
    g = Geometry("lock", LOCK)
    p = np.array([[0.04, 0.15, 0.0], [0.0, 0.15, 0.01], [0.0, 0.15, 0.0], [0.1, 0.15, 0.0], [0.0, 0.15, 0.05]])
    d = g.distance(p)
    np.testing.assert_allclose(d[:2], 0.0, atol=1e-9)  # half the width across, half the thickness through
    assert d[2] == pytest.approx(-0.01)  # the middle: half the thickness deep
    np.testing.assert_allclose(d[3:], [0.06, 0.04], atol=1e-9)  # exact along both axes outside


def test_lock_tapers_to_a_point() -> None:
    g = Geometry("lock", {**LOCK, "width_to": 0.0, "thickness_to": 0.0})
    tip = g.distance(np.array([[0.0, 0.3, 0.0], [0.0, 0.31, 0.0]]))
    assert abs(tip[0]) < 1e-4 and tip[1] == pytest.approx(0.01, abs=1e-4)


def test_lock_facing_turns_the_flat_side() -> None:
    g = Geometry("lock", {**LOCK, "facing": [1, 0, 0]})  # flat sides look along x: the width runs along z now
    d = g.distance(np.array([[0.0, 0.15, 0.04], [0.01, 0.15, 0.0]]))
    np.testing.assert_allclose(d, 0.0, atol=1e-9)


def test_scale_stretches_in_the_part_frame() -> None:
    g = Geometry("sphere", {"radius": 0.1}, scale=np.array([1.0, 2.0, 0.5]))
    d = g.distance(np.array([[0.1, 0, 0], [0, 0.2, 0], [0, 0, 0.05], [0, 0, 0]]))
    np.testing.assert_allclose(d[:3], 0.0, atol=1e-12)  # the surface is where the stretch puts it
    assert d[3] == pytest.approx(-0.05)  # inside: a bound (radius x the smallest stretch)
    lo, hi = g.bounds()
    np.testing.assert_allclose(hi, [0.1, 0.2, 0.05])
    assert part_thickness(g) == pytest.approx(0.1)


def test_lock_and_scale_parse_and_build(project: Project) -> None:
    model, _, findings = load(project, MODEL.format(extra="  - sphere: { at: [0.2, 0.3, 0], radius: 0.1 }\n    scale: [1, 1, 0.4]\n    color: red\n"))
    assert model is not None, findings
    lock = model.parts[1].geometry
    assert lock.params["thickness_to"] == 0.02 and lock.params["width_to"] == 0.0
    np.testing.assert_array_equal(model.parts[2].geometry.scale, [1, 1, 0.4])
    path = write_model(project, MODEL.format(extra=""))
    result = lint_paths(project, [path])
    assert not [f for f in result.findings if f.severity == "error"], result.findings
    assert result.built["thing"].triangles > 0


@pytest.mark.parametrize(("extra", "where"), [
    ("    scale: [1, 0, 1]\n", "parts[2].scale"),
    ("    scale: [1, 1]\n", "parts[2].scale"),
    ("    scale: 0.5\n    blend: none\n", "parts[2]"),
])  # fmt: skip
def test_bad_scale(project: Project, extra: str, where: str) -> None:
    _, _, findings = load(project, MODEL.format(extra="  - sphere: { at: [0.2, 0.3, 0], radius: 0.1 }\n    color: red\n" + extra))
    assert any(f.rule == "E003" and f.where == where for f in findings), findings


def test_lock_facing_zero_is_an_error(project: Project) -> None:
    text = MODEL.format(extra="").replace("facing: [0, 0, 1]", "facing: [0, 0, 0]")
    _, _, findings = load(project, text)
    assert any(f.rule == "E003" and (f.where or "").endswith("facing") for f in findings)
