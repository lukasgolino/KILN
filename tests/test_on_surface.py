"""#149: `on:` places a part on the blended surface of earlier parts."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project
from kiln.sdf import Field

BODY = """\
name: thing
class: creature
parts:
  - ellipsoid: { at: [0, 0.5, 0], radii: [0.3, 0.45, 0.25] }
    id: body
    color: wood
  - sphere: { at: [0, 1.0, 0], radius: 0.2 }
    id: head
    color: wood
    blend: 0.1
"""
TUFT = """\
  - cone: {{ radius: 0.03, height: 0.1 }}
    id: tuft
    color: gold
    on: {{ part: [body, head], near: {near}{extra} }}
"""


def placed(project: Project, near: str, extra: str = "", more: str = "") -> tuple[object, np.ndarray, np.ndarray]:
    model, _, findings = load(project, BODY + TUFT.format(near=near, extra=extra) + more)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    g = model.parts[2].geometry
    up = (g.rotation if g.rotation is not None else np.eye(3)) @ np.array([0.0, 1.0, 0.0])
    return model, np.asarray(g.at), up


def test_a_part_sits_on_the_blended_surface_facing_out(project: Project) -> None:
    model, at, up = placed(project, "[0.25, 0.8, 0.0]")  # in the neck's blend: neither the body's nor the head's own surface
    surface = Field([p.geometry for p in model.parts[:2]], 0.05)  # type: ignore[attr-defined]
    assert abs(float(surface.distance(at[None])[0])) < 1e-4  # on the blended surface
    normal = surface.gradient(at[None], 1e-5)[0]
    assert float(up @ normal) > 0.999  # its y axis is the surface normal
    _, lifted, _ = placed(project, "[0.25, 0.8, 0.0]", ", offset: 0.05")
    assert abs(float(surface.distance(lifted[None])[0]) - 0.05) < 2e-3


def test_align_false_only_moves_it_and_a_mirrored_twin_follows(project: Project) -> None:
    _, _, up = placed(project, "[0.25, 0.8, 0.0]", ", align: false")
    assert np.allclose(up, [0, 1, 0])
    twin = "    mirror_id: tuft_r\n    mirror: x\n"
    model, _, _ = placed(project, "[0.25, 0.8, 0.1]", "", twin)
    a, b = model.parts[2].geometry, model.parts[3].geometry  # type: ignore[attr-defined]
    assert np.allclose(b.at, a.at * [-1, 1, 1])
    built = lint_paths(project, [write_model(project, BODY + TUFT.format(near="[0.25, 0.8, 0.1]", extra="") + twin)]).built["thing"]
    assert built.triangles > 0


def test_errors(project: Project) -> None:
    for bad, where in (("on: { part: tail, near: [0, 0, 0] }", "parts[2].on"), ("on: { part: body }", "parts[2].on"),
                       ("on: { part: body, near: [0.2, 0.5, 0] }\n    at: [0, 0, 0]", "parts[2].on")):
        text = BODY + "  - sphere: { radius: 0.03 }\n    color: gold\n    " + bad + "\n"
        _, _, findings = load(project, text)
        assert any(f.where == where for f in findings), (bad, findings)


def test_cuts_detail_and_fitted_shells(project: Project) -> None:
    near = "[0.25, 0.55, 0.0]"
    _, plain, _ = placed(project, near)
    cut = BODY + "  - box: { at: [0.3, 0.55, 0], size: [0.1, 0.1, 0.1] }\n    cut: true\n" + TUFT.format(near=near, extra="")
    model, _, findings = load(project, cut)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    assert model.parts[3].geometry.at[0] < plain[0] - 0.02  # a cut listed before it applies
    detail = "normal_map: 256\n" + BODY + "  - box: { at: [0.3, 0.55, 0], size: [0.1, 0.1, 0.1] }\n    cut: true\n    detail: true\n" \
        + TUFT.format(near=near, extra="")
    model, _, findings = load(project, detail)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    tuft = next(p for p in model.parts if p.id == "tuft")
    assert np.allclose(tuft.geometry.at, plain, atol=1e-6)  # a detail cut is only in the normal map: no effect
    shell = BODY + "  - sphere: { at: [0, 1.0, 0], radius: 0.35 }\n    id: hood\n    color: gold\n    shell: 0.01\n    fit: { to: head, gap: 0.05 }\n" \
        + "  - cone: { radius: 0.02, height: 0.05 }\n    color: wood\n    on: { part: hood, near: [0, 1.4, 0] }\n"
    model, _, findings = load(project, shell)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    assert model.parts[3].geometry.at[1] > 1.2 + 0.03  # on the fitted shell (gap 0.05 over the head), not the unfitted sphere


def test_chained_rotated_rolled_and_mirrored(project: Project) -> None:
    chain = TUFT.format(near="[0.25, 0.8, 0.0]", extra="") + "  - sphere: { radius: 0.01 }\n    color: wood\n    on: { part: tuft, near: [0.4, 0.9, 0] }\n"
    model, _, findings = load(project, BODY + chain)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    tip = Field([p.geometry for p in model.parts[:3]], 0.05, frozenset({2}))
    assert abs(float(tip.distance(model.parts[3].geometry.at[None])[0])) < 1e-4  # on the tuft placed before it
    _, _, up = placed(project, "[0.25, 0.8, 0.0]", ", roll: 90", "    rotate: [0, 45, 0]\n")
    _, _, up0 = placed(project, "[0.25, 0.8, 0.0]")
    assert np.allclose(up, up0, atol=1e-6)  # rotate and roll spin about the shape's y: y stays on the normal
    folded, at, _ = placed(project, "[0.25, 0.8, 0.0]", "", "    mirror: x\n")
    assert folded.parts[2].geometry.mirror == (0,) and at[0] > 0.2  # type: ignore[attr-defined]


def test_more_errors_and_templates(project: Project) -> None:
    arr = BODY + TUFT.format(near="[0.25, 0.8, 0.0]", extra="") + "    array: { count: 3, around: y }\n"
    _, _, findings = load(project, arr)
    assert any(f.where == "parts[2].on" for f in findings), findings
    bolt = BODY + "  - bolt: { size: 0.02 }\n    on: { part: body, near: [0.3, 0.5, 0] }\n"
    _, _, findings = load(project, bolt)
    assert any(f.where == "parts[2].on" for f in findings), findings
    with pytest.MonkeyPatch.context() as mp:  # a field with no way out (flat: the walk can't move)
        mp.setattr(Field, "gradient", lambda self, p, eps: np.zeros_like(p))
        _, _, findings = load(project, BODY + TUFT.format(near="[0.25, 0.8, 0.0]", extra=""))
    assert any(f.where == "parts[2].on" and "settle" in f.message for f in findings), findings
    template = "template: true\n" + BODY.replace("name: thing\n", "name: thing\n", 1) + "  - sphere: { radius: 0.01 }\n    color: gold\n" \
        "    on: { part: helmet, near: [0, 1.3, 0] }\n"
    _, _, findings = load(project, template)
    assert not any(f.where == "parts[2].on" for f in findings), findings  # the ids may come from another template
