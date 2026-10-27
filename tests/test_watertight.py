"""Watertight detachables (CC0 parity M1): no cracks, closed separate parts, paint under them, E013, --detach."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from conftest import built_of, errors_of, make_project, run_json, write_model
from kiln.builder import build_model
from kiln.lint import geometry_warnings
from kiln.mesher import open_edges, pinches
from kiln.paint import split
from kiln.project import Project, load_project

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"

GUARD = """\
name: guard
class: character
parts:
  - capsule: { from: [0, 0.35, 0], to: [0, 0.8, 0], radius: 0.25 }
    color: red
  - sphere: { at: [0, 1.25, 0], radius: 0.3 }
    id: head
    color: white
    blend: 0.05
  - cylinder: { at: [0, 1.45, 0], radius: 0.47, height: 0.05 }
    id: helmet
    color: grey
  - sphere: { at: [0, 1.4, 0], radius: 0.33 }
    id: helmet
    color: grey
    shell: { thickness: 0.03, open: -y }
rig:
  head: { pivot: [0, 0.95, 0] }
  helmet: { parent: head, separate: true, under: { color: wood } }
skin: soft
"""


@pytest.mark.parametrize("name", ["pilot", "knight", "archer", "passenger"])
def test_demo_characters_have_no_cracks(name: str) -> None:
    project = load_project(DEMO)
    model, style, _ = project.load(DEMO / "models" / f"{name}.kiln.yaml")
    assert model is not None and style is not None
    palette, _ = project.palette(model.palette)
    built = build_model(model, style, palette=palette)
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0


def test_helmet_brim_through_the_head_leaves_it_closed(project: Project) -> None:
    built = built_of(project, GUARD, "guard")
    p = built.painted
    assert len(open_edges(p.vertices, p.faces)) == 0
    bones = np.array([p.groups[g].bone for g in p.face_group])
    for bone in ("head", "helmet"):  # each piece closed on its own (the head without the helmet)
        mine = p.faces[bones == bone] if bone == "helmet" else p.faces[bones != "helmet"]
        assert len(open_edges(p.vertices, mine)) == 0, bone


def test_under_paints_what_the_helmet_covers(project: Project) -> None:
    built = built_of(project, GUARD, "guard")
    p = built.painted
    under = [g for g in p.groups if g.color_name.startswith("wood")]
    assert under and all(g.bone == "head" for g in under)
    faces = np.isin(p.face_group, [p.groups.index(g) for g in under])
    centres = p.vertices[p.faces[faces]].mean(axis=1)
    assert centres[:, 1].min() > 1.3  # the crown, not the face


def test_under_needs_a_separate_part(project: Project) -> None:
    text = GUARD.replace("separate: true, under", "under")
    assert any(f.rule == "E007" and "under" in f.message for f in errors_of(project, text, "guard"))


def test_split_leaves_no_t_junctions() -> None:
    # a square of two triangles sharing the diagonal 1-2; only the first is cut, and the cut crosses the diagonal
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], float)
    f = np.array([[0, 1, 2], [1, 3, 2]])
    out_v, faces, _, parent = split(v, f, v[:, 0] - 0.5, np.array([True, False]))
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    directed = {tuple(e) for e in edges.tolist()}
    open_ = [e for e in directed if (e[1], e[0]) not in directed]
    # only the square's outline is open (it gained the cut's point on its bottom side); the diagonal is closed
    mids = out_v[np.array(open_)].mean(axis=1)
    assert len(open_) == 5 and np.all(np.isclose(mids[:, 0], 0) | np.isclose(mids[:, 0], 1) | np.isclose(mids[:, 1], 0) | np.isclose(mids[:, 1], 1))
    assert set(parent.tolist()) == {0, 1}


def test_e013_reports_cracks(project: Project) -> None:
    built = built_of(project, "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n")
    assert not [f for f in geometry_warnings(built, {}, project) if f.rule == "E013"]
    p = built.painted
    cracked = replace(built, painted=replace(p, faces=p.faces[1:], face_group=p.face_group[1:], face_decal=p.face_decal[1:]))
    found = [f for f in geometry_warnings(cracked, {}, project) if f.rule == "E013"]
    assert found and found[0].severity == "error" and "3 open edges" in found[0].message
    # #10: each crack on its own, with where it is and what it's on
    far = int(np.argmax(p.vertices[p.faces].mean(axis=1)[:, 1]))  # a face at the top, away from face 0
    keep = np.setdiff1d(np.arange(len(p.faces)), [0, far])
    two = replace(built, painted=replace(p, faces=p.faces[keep], face_group=p.face_group[keep], face_decal=p.face_decal[keep]))
    message = [f for f in geometry_warnings(two, {}, project) if f.rule == "E013"][0].message
    assert "6 open edges (cracks) in 2 place(s): 3 at [" in message and message.count("on red (root)") == 2
    top = p.vertices[p.faces[far]].mean(axis=0)  # a missing triangle's crack is centred on it
    assert f"[{top[0]:.3f}, {top[1]:.3f}, {top[2]:.3f}]" in message


def test_e013_reports_sheets_that_touch(project: Project) -> None:
    # #25: closed but not a manifold (no open edges): a second ball standing on the first one's top vertex
    built = built_of(project, "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n")
    p = built.painted
    top, bottom = int(np.argmax(p.vertices[:, 1])), int(np.argmin(p.vertices[:, 1]))
    stacked = np.concatenate([p.vertices, p.vertices - p.vertices[bottom] + p.vertices[top]])
    two = replace(built, painted=replace(p, vertices=stacked, faces=np.concatenate([p.faces, p.faces + len(p.vertices)]),
                                         face_group=np.tile(p.face_group, 2), face_decal=np.tile(p.face_decal, 2)))  # fmt: skip
    found = [f for f in geometry_warnings(two, {}, project) if f.rule == "E013"]
    assert len(found) == 1 and found[0].severity == "error"
    at = p.vertices[top]
    assert f"0 edge(s) with more than two faces and 1 point(s) where two sheets touch, in 1 place(s): 1 at [{at[0]:.3f}, {at[1]:.3f}, " \
           f"{at[2]:.3f}] on red (root)" in found[0].message


def test_detach_preview(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, GUARD, "guard")
    code, data = run_json(["preview", "guard", "--detach"], capsys)
    assert code == 0 and "detach" in data["outputs"]
    write_model(in_project, "name: ball\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n", "ball")
    code, _ = run_json(["preview", "ball", "--detach"], capsys)
    assert code != 0


# #61: the simplifier can put a vertex exactly onto a locked border vertex beside it; relaxing moved one of the two
# before they were joined, leaving two border copies at one place no longer joined by an edge (crowded edges, E013)
FINE_STYLE = """\
extends = "toon"

[shape]
smooth = true
resolution = 0.005
"""

FLAMES = """\
name: flames
class: nature
budget: 16000
style: fine
skin: soft
rig:
  t0_0: {pivot: [0.0, 0.05, 0.0], sockets: {glow: [0, 0.35, 0], smoke: [0, 1.05, 0]}}
  t0_1: {parent: t0_0, pivot: [-0.007, 0.383, 0.001]}
  t0_2: {parent: t0_1, pivot: [-0.028, 0.717, 0.005]}
  t1_0: {pivot: [0.3, 0.05, 0.12]}
  t1_1: {parent: t1_0, pivot: [0.298, 0.29, 0.122]}
  t1_2: {parent: t1_1, pivot: [0.29, 0.53, 0.128]}
  t2_0: {pivot: [-0.3, 0.05, 0.1]}
  t2_1: {parent: t2_0, pivot: [-0.297, 0.31, 0.091]}
  t2_2: {parent: t2_1, pivot: [-0.289, 0.57, 0.064]}
  t3_0: {pivot: [0.12, 0.05, -0.25]}
  t3_1: {parent: t3_0, pivot: [0.111, 0.27, -0.244]}
  t3_2: {parent: t3_1, pivot: [0.086, 0.49, -0.226]}
  t4_0: {pivot: [-0.15, 0.05, -0.22]}
  t4_1: {parent: t4_0, pivot: [-0.154, 0.25, -0.224]}
  t4_2: {parent: t4_1, pivot: [-0.166, 0.45, -0.237]}
  t5_0: {pivot: [0.38, 0.05, -0.12]}
  t5_1: {parent: t5_0, pivot: [0.387, 0.217, -0.12]}
  t5_2: {parent: t5_1, pivot: [0.406, 0.383, -0.122]}
parts:
  - {color: '#ffffff', ellipsoid: {at: [0, 0.08, 0], radii: [0.5, 0.14, 0.4]}, material: glow, noise: {amount: 0.03, scale: 0.12, seed: 2}}
  - {blend: 0.06, capsule: {from: [0.0, 0.05, 0.0], radius: 0.24, radius_to: 0.172, to: [-0.007, 0.383, 0.001]}, color: '#ffd040', id: t0_0, material: glow}
  - {blend: 0.06, capsule: {from: [-0.007, 0.383, 0.001], radius: 0.172, radius_to: 0.104, to: [-0.028, 0.717, 0.005]}, color: '#ff8020', id: t0_1, material: glow}
  - {blend: 0.06, capsule: {from: [-0.028, 0.717, 0.005], radius: 0.104, radius_to: 0.02, to: [-0.063, 1.05, 0.011]}, color: '#c02010', id: t0_2, material: glow}
  - {blend: 0.06, capsule: {from: [0.3, 0.05, 0.12], radius: 0.19, radius_to: 0.136, to: [0.298, 0.29, 0.122]}, color: '#ffd040', id: t1_0, material: glow}
  - {blend: 0.06, capsule: {from: [0.298, 0.29, 0.122], radius: 0.136, radius_to: 0.082, to: [0.29, 0.53, 0.128]}, color: '#ff8020', id: t1_1, material: glow}
  - {blend: 0.06, capsule: {from: [0.29, 0.53, 0.128], radius: 0.082, radius_to: 0.02, to: [0.278, 0.77, 0.138]}, color: '#c02010', id: t1_2, material: glow}
  - {blend: 0.06, capsule: {from: [-0.3, 0.05, 0.1], radius: 0.2, radius_to: 0.143, to: [-0.297, 0.31, 0.091]}, color: '#ffd040', id: t2_0, material: glow}
  - {blend: 0.06, capsule: {from: [-0.297, 0.31, 0.091], radius: 0.143, radius_to: 0.087, to: [-0.289, 0.57, 0.064]}, color: '#ff8020', id: t2_1, material: glow}
  - {blend: 0.06, capsule: {from: [-0.289, 0.57, 0.064], radius: 0.087, radius_to: 0.02, to: [-0.276, 0.83, 0.019]}, color: '#c02010', id: t2_2, material: glow}
  - {blend: 0.06, capsule: {from: [0.12, 0.05, -0.25], radius: 0.18, radius_to: 0.129, to: [0.111, 0.27, -0.244]}, color: '#ffd040', id: t3_0, material: glow}
  - {blend: 0.06, capsule: {from: [0.111, 0.27, -0.244], radius: 0.129, radius_to: 0.078, to: [0.086, 0.49, -0.226]}, color: '#ff8020', id: t3_1, material: glow}
  - {blend: 0.06, capsule: {from: [0.086, 0.49, -0.226], radius: 0.078, radius_to: 0.02, to: [0.043, 0.71, -0.197]}, color: '#c02010', id: t3_2, material: glow}
  - {blend: 0.06, capsule: {from: [-0.15, 0.05, -0.22], radius: 0.17, radius_to: 0.122, to: [-0.154, 0.25, -0.224]}, color: '#ffd040', id: t4_0, material: glow}
  - {blend: 0.06, capsule: {from: [-0.154, 0.25, -0.224], radius: 0.122, radius_to: 0.074, to: [-0.166, 0.45, -0.237]}, color: '#ff8020', id: t4_1, material: glow}
  - {blend: 0.06, capsule: {from: [-0.166, 0.45, -0.237], radius: 0.074, radius_to: 0.02, to: [-0.185, 0.65, -0.258]}, color: '#c02010', id: t4_2, material: glow}
  - {blend: 0.06, capsule: {from: [0.38, 0.05, -0.12], radius: 0.14, radius_to: 0.1, to: [0.387, 0.217, -0.12]}, color: '#ffd040', id: t5_0, material: glow}
  - {blend: 0.06, capsule: {from: [0.387, 0.217, -0.12], radius: 0.1, radius_to: 0.061, to: [0.406, 0.383, -0.122]}, color: '#ff8020', id: t5_1, material: glow}
  - {blend: 0.06, capsule: {from: [0.406, 0.383, -0.122], radius: 0.061, radius_to: 0.02, to: [0.439, 0.55, -0.124]}, color: '#c02010', id: t5_2, material: glow}
"""


@pytest.mark.slow
def test_relaxing_next_to_a_border_leaves_no_coincident_vertices(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (project.root / "styles" / "fine.style.toml").write_text(FINE_STYLE)
    built = built_of(project, FLAMES, "flames")
    p = built.painted
    crowded, pinched = pinches(p.vertices, p.faces)
    assert len(crowded) == 0 and len(pinched) == 0
    assert not [f for f in geometry_warnings(built, {}, project) if f.rule == "E013"]
