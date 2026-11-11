"""#149: `on:` places a part on the blended surface of earlier parts."""

from __future__ import annotations

import numpy as np
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
