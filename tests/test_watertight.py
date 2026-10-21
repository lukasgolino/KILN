"""Watertight detachables (CC0 parity M1): no cracks, closed separate parts, paint under them, E013, --detach."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from conftest import built_of, errors_of, run_json, write_model
from kiln.builder import build_model
from kiln.lint import geometry_warnings
from kiln.mesher import open_edges
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


def test_detach_preview(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, GUARD, "guard")
    code, data = run_json(["preview", "guard", "--detach"], capsys)
    assert code == 0 and "detach" in data["outputs"]
    write_model(in_project, "name: ball\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n", "ball")
    code, _ = run_json(["preview", "ball", "--detach"], capsys)
    assert code != 0
