"""Hard surface (CC0 parity M2): exact polygons, sides, bevels and chamfers, exact CSG, crisp creases."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from conftest import built_of, closed_faces, errors_of, ok_model, signed_volume
from kiln.builder import build_model, hard_parts
from kiln.export import to_glb
from kiln.hard import HardSpec, bevelled, intersect, solid, subtract, to_mesh, union
from kiln.hard import _planes_box
from kiln.lint import geometry_warnings
from kiln.mesher import open_edges
from kiln.project import Project, load_project
from kiln.sdf import Geometry, cylinder

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


def mesh_of(shape: str, params: dict[str, object], spec: HardSpec = HardSpec(), at: tuple[float, float, float] = (0, 0, 0)) -> tuple:  # type: ignore[type-arg]
    m = to_mesh(solid(Geometry(shape, dict(params), at=np.array(at, float)), spec, 0))
    return m, len(set(m.face_polygon.tolist()))


def test_chamfered_box_has_26_faces() -> None:
    assert len(bevelled(*_planes_box([1, 1, 1]), 0.1, 1)) == 26
    m, polygons = mesh_of("box", {"size": [1, 1, 1], "round": 0.0}, HardSpec(12, 0.1, 1))
    assert polygons == 26 and closed_faces(m.faces)


def test_eight_sided_cylinder_is_eight_quads_and_two_caps() -> None:
    m, polygons = mesh_of("cylinder", {"radius": 0.5, "height": 1.0, "sides": 8, "round": 0.0})
    assert polygons == 10
    assert m.triangles == 8 * 2 + 2 * 6
    # corners on the radius: the octagon's area
    assert signed_volume(m.vertices, m.faces) == pytest.approx(0.5 * 8 * 0.25 * np.sin(np.pi / 4), rel=1e-7)


@pytest.mark.parametrize("shape,params", [
    ("sphere", {"radius": 0.5, "sides": 10}), ("ellipsoid", {"radii": [0.3, 0.5, 0.2]}), ("torus", {"radius": 0.5, "thickness": 0.1}),
    ("lathe", {"profile": [[0, 0], [0.3, 0], [0.4, 0.5], [0.2, 1], [0, 1]]}), ("wedge", {"size": [1, 0.5, 1]}),
    ("extrude", {"points": [[0, 0], [1, 0], [1, 1], [0.5, 0.4], [0, 1]], "height": 0.2, "round": 0.0}),
    ("capsule", {"from": [0, 0, 0], "to": [0, 1, 0.3], "radius": 0.2, "radius_to": 0.1}),
    ("cone", {"radius": 0.5, "radius_top": 0.0, "height": 1.0, "sides": 4}),
])  # fmt: skip
def test_every_hard_shape_is_closed_and_outward(shape: str, params: dict[str, object]) -> None:
    m, _ = mesh_of(shape, params)
    assert closed_faces(m.faces) and signed_volume(m.vertices, m.faces) > 0


def test_csg_is_exact_and_watertight() -> None:
    box = solid(Geometry("box", {"size": [1, 1, 1], "round": 0.0}), HardSpec(), 0)
    other = solid(Geometry("box", {"size": [1, 1, 1], "round": 0.0}, at=np.array([0.5, 0.5, 0.5])), HardSpec(), 1)
    for op, volume in ((union, 1.875), (subtract, 0.875), (intersect, 0.125)):
        m = to_mesh(op(box, other))
        assert closed_faces(m.faces)
        assert signed_volume(m.vertices, m.faces) == pytest.approx(volume, abs=1e-9)
        assert set(m.face_part.tolist()) == {0, 1}  # every face knows its part
    # coplanar fragments are merged again: a union of two boxes is few triangles
    assert to_mesh(union(box, other)).triangles <= 40


def test_crease_is_kept_at_a_csg_seam(project: Project) -> None:
    text = """\
name: thing
parts:
  - box: { at: [0, 0.25, 0], size: [1, 0.5, 1] }
    color: red
    blend: none
  - box: { at: [0, 0.75, 0], size: [0.4, 0.5, 0.4] }
    color: red
    blend: none
"""
    built = built_of(project, text)
    p = built.painted
    assert closed_faces(np.unique(np.round(p.vertices, 9), axis=0, return_inverse=True)[1].reshape(-1)[p.faces])
    # every corner normal is its face's own (all edges here are 90 degrees: crisp)
    face_n = np.cross(p.vertices[p.faces[:, 1]] - p.vertices[p.faces[:, 0]], p.vertices[p.faces[:, 2]] - p.vertices[p.faces[:, 0]])
    face_n /= np.linalg.norm(face_n, axis=1, keepdims=True)
    assert np.allclose(built.normals, face_n[:, None, :], atol=1e-6)


def test_hard_parts_follow_the_style(project: Project) -> None:
    text = """\
name: thing
parts:
  - box: { at: [0, 0.25, 0], size: [1, 0.5, 1] }
    color: red
  - cylinder: { at: [0, 0.7, 0], radius: 0.2, height: 0.4, sides: 6 }
    color: blue
  - sphere: { at: [0, 1, 0], radius: 0.1 }
    color: red
    noise: { amount: 0.01 }
"""
    model, style = ok_model(project, text)
    assert hard_parts(model, style) == {1}  # auto: only the part asking (sides)
    always = project.style("low_poly")[0]
    assert always is not None and always.hard_surface == "always"
    assert hard_parts(model, always) == {0, 1}  # noise needs the smooth field


def test_hard_and_smooth_parts_mix(project: Project) -> None:
    text = """\
name: thing
parts:
  - sphere: { at: [0, 0.4, 0], radius: 0.4 }
    color: red
  - cylinder: { at: [0, 0.4, 0], radius: 0.15, height: 1.0, sides: 6 }
    color: blue
  - box: { at: [0, 0.4, 0.35], size: [0.2, 0.2, 0.2] }
    cut: true
"""
    built = built_of(project, text)
    assert {g.color_name for g in built.painted.groups} == {"red", "blue"}
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0
    assert built.pieces == 1


def test_demo_trebuchet_hard_is_kenney_sized() -> None:
    project = load_project(DEMO)
    model, _, findings = project.load(DEMO / "models" / "trebuchet.kiln.yaml")
    low_poly = project.style("low_poly")[0]
    assert model is not None and low_poly is not None
    palette, _ = project.palette(model.palette)
    built = build_model(model, low_poly, palette=palette)
    assert built.triangles <= 2000  # Kenney's trebuchet: 1518
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0
    assert {"wood", "wood_dark", "iron"} <= {g.color_name for g in built.painted.groups}
    # byte-identical rebuilds
    again = build_model(model, low_poly, palette=palette)
    assert to_glb(built, "test") == to_glb(again, "test")


def test_sides_shape_the_smooth_field_too() -> None:
    p = {"radius": 1.0, "height": 1.0, "round": 0.0, "sides": 8}
    corner = np.array([[np.sin(np.pi / 8), 0.0, np.cos(np.pi / 8)]])  # a corner direction: on the radius
    side = np.array([[0.0, 0.0, np.cos(np.pi / 8)]])  # the middle of the front side
    assert abs(cylinder(corner, p)[0]) < 1e-9 and abs(cylinder(side, p)[0]) < 1e-9


def test_hard_notation_errors(project: Project) -> None:
    base = "name: thing\nparts:\n  - {shape}\n    color: red\n{extra}"
    cases = [
        ("sphere: { radius: 0.3 }", "    bevel: 0.02\n", "bevel and chamfer work on"),
        ("box: { size: [1, 1, 1] }", "    bevel: 0.02\n    chamfer: 0.02\n", "not both"),
        ("box: { size: [1, 1, 1] }", "    chamfer: 0.6\n", "less than half"),
        ("cylinder: { radius: 0.3, height: 1, sides: 2 }", "", "sides"),
        ("box: { size: [1, 1, 1] }", "    hard: true\n    noise: { amount: 0.01 }\n", "can't twist or have noise"),
        ("box: { size: [1, 1, 1] }", "    segments: 9\n", "segments"),
    ]
    for shape, extra, message in cases:
        found = errors_of(project, base.format(shape=shape, extra=extra))
        assert any(message in f.message for f in found), (shape, extra, [f.message for f in found])


def test_hard_shell_with_an_open_side(project: Project) -> None:
    text = """\
name: thing
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3, sides: 12 }
    shell: { thickness: 0.03, open: -y }
    color: grey
    hard: true
"""
    built = built_of(project, text)
    p = built.painted
    assert len(open_edges(p.vertices, p.faces)) == 0
    # a bowl: nothing below its centre, and the rim (inside wall) is there
    assert p.vertices[:, 1].min() == pytest.approx(0.3, abs=1e-9)
    radii = np.linalg.norm(p.vertices - [0, 0.3, 0], axis=1)
    assert 0.25 < radii.min() < 0.28


def test_planar_merge_survives_an_outline_that_does_not_close() -> None:
    # LOOSE #45: a patch with a back-to-back sliver pair (from a rotated 4-sided cone on an aimed blade) left an open
    # outline chain; looking up its end crashed lint with a KeyError
    from kiln.hard import _outline_points, _retriangulate

    tris = [[3, 1, 0], [3, 0, 1], [3, 0, 2]]
    v = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.3, 0.0, 0.3]]
    normal = np.array([0.0, 1.0, 0.0])
    assert _outline_points(tris, v, normal) == (set(), {0, 1, 2, 3})
    assert _retriangulate(tris, v, normal, set()) is None  # left as it is


def test_hard_lathe_shell_opens_its_end(project: Project) -> None:
    # LOOSE #44: a hollow lathe helmet (profile anywhere on the axis) came out shattered: lathes weren't shell shapes,
    # and `open: -y` cut at local y = 0 instead of the profile's bottom
    text = """\
name: thing
parts:
  - lathe: { profile: [[0, 1.94], [0.065, 1.935], [0.12, 1.895], [0.14, 1.83], [0.142, 1.765], [0, 1.765]], sides: 12 }
    shell: { thickness: 0.012, open: -y }
    color: grey
    hard: true
"""
    built = built_of(project, text)
    p = built.painted
    assert len(open_edges(p.vertices, p.faces)) == 0
    assert p.vertices[:, 1].min() == pytest.approx(1.765 + 0.012, abs=1e-6)  # only the end wall is gone
    inner = np.hypot(p.vertices[:, 0], p.vertices[:, 2])[np.abs(p.vertices[:, 1] - 1.777) < 1e-6]
    assert inner.min() == pytest.approx(0.142 - 0.012, abs=0.005)  # the rim: an inside wall at the open end
    palette, _ = project.palette(built.model.palette)
    assert not [f for f in geometry_warnings(built, palette, project) if f.rule == "W102"]  # exact polygons: no resolution
