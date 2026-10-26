"""Attachments fitted to CC0 characters (CC0 parity M6), against KayKit's CC0 Knight."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from conftest import CONFIG, built_of, errors_of, make_project, write_model
from kiln.build import build
from kiln.fitting import MeshDistance, bone_matrix, read_surface
from kiln.godot import find_godot_binary, verify
from kiln.lint import geometry_warnings
from kiln.mesher import open_edges
from kiln.project import Project
from kiln.vendor.gltf import read_glb

KAYKIT = Path(__file__).resolve().parent / "fixtures" / "kaykit"

HELM = """\
name: thing
class: prop
fit_to: { file: imports/Knight.glb, bone: head, meshes: [Knight_Head] }
parts:
  - sphere: { at: [0, 1.62, 0], radius: 0.8 }
    color: grey
    shell: { thickness: 0.04, open: -y }
    fit: { to: target, gap: 0.015 }
  - box: { at: [0, 1.75, 0.6], size: [0.7, 0.35, 0.6] }
    cut: true
lint: { disable: [W106] }
"""


@pytest.fixture
def knight(project: Project) -> Project:
    for name in ("Knight.glb", "knight_texture.png"):
        shutil.copy(KAYKIT / name, project.root / "imports" / name)
    return project


def test_mesh_distance_is_signed_and_exact_near_the_surface() -> None:
    v, f = read_surface(KAYKIT / "Knight.glb", ("Knight_Head",))
    md = MeshDistance.build(v, f)
    centres = v[f].mean(axis=1)[:50]
    normals = np.cross(v[f[:50, 1]] - v[f[:50, 0]], v[f[:50, 2]] - v[f[:50, 0]])
    normals /= np.linalg.norm(normals, axis=1, keepdims=True)
    assert np.allclose(md.distance(centres), 0, atol=1e-9)
    # (a face in a crease, or with another part of the head just behind it, may be nearer: most aren't)
    assert np.isclose(md.distance(centres + normals * 0.01), 0.01).mean() > 0.9
    assert np.isclose(md.distance(centres - normals * 0.005), -0.005).mean() > 0.9


def test_helmet_fitted_to_the_knights_head(knight: Project) -> None:
    built = built_of(knight, HELM)
    p = built.painted
    assert len(open_edges(p.vertices, p.faces)) == 0
    v, f = read_surface(knight.root / "imports" / "Knight.glb", ("Knight_Head",))
    depth = MeshDistance.build(v, f).distance(p.vertices[np.unique(p.faces)])
    assert depth.min() > 0.015 - 2 * built.step  # never in the head: at least the gap away
    assert depth.max() < 0.055 + 2 * built.step  # and hugging it: within the gap plus the wall
    assert not [x for x in geometry_warnings(built, {}, knight) if x.rule == "W113"]


def test_attachment_is_exported_in_the_bones_space(knight: Project) -> None:
    write_model(knight, HELM)
    build(knight)
    doc, _ = read_glb((knight.output_dir / "models" / "thing.glb").read_bytes())
    root = doc["nodes"][doc["scenes"][0]["nodes"][0]]
    assert root["extras"] == {"kiln_attach": "head"}
    m = np.array(root["matrix"]).reshape(4, 4).T
    assert np.allclose(m @ bone_matrix(knight.root / "imports" / "Knight.glb", "head"), np.eye(4), atol=1e-5)
    manifest = json.loads((knight.output_dir / "manifest.json").read_text())
    assert manifest["models"]["thing"]["attach"] == {"file": "Knight.glb", "bone": "head"}


def test_sinking_into_the_character_is_flagged(knight: Project) -> None:
    text = "name: thing\nclass: prop\nfit_to: { file: imports/Knight.glb, bone: head, meshes: [Knight_Head] }\nparts:\n" \
           "  - sphere: { at: [0, 1.75, 0.45], radius: 0.15 }\n    color: red\nlint: { disable: [W106] }\n"
    built = built_of(knight, text)
    assert [x for x in geometry_warnings(built, {}, knight) if x.rule == "W113"]


def test_fit_to_errors(knight: Project) -> None:
    assert any("no bone 'neck'" in f.message for f in errors_of(knight, HELM.replace("bone: head", "bone: neck")))
    assert any("no mesh Knight_Hat" in f.message for f in errors_of(knight, HELM.replace("[Knight_Head]", "[Knight_Hat]")))
    no_target = HELM.replace("fit_to: { file: imports/Knight.glb, bone: head, meshes: [Knight_Head] }\n", "")
    assert any("fit: target" in f.message for f in errors_of(knight, no_target))


@pytest.mark.skipif(find_godot_binary() is None, reason="needs Godot 4 (GODOT=/path/to/godot)")
def test_godot_hangs_the_attachment_on_its_bone(tmp_path: Path) -> None:
    godot = find_godot_binary()
    assert godot is not None
    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "art", CONFIG + 'output_dir = "../assets/kiln"\nexport = ["glb", "godot"]\n')
    for name in ("Knight.glb", "knight_texture.png"):
        shutil.copy(KAYKIT / name, project.root / "imports" / name)
    write_model(project, HELM)
    result = build(project)
    assert not result.errors and result.godot_root is not None
    assert result.attachments == {"thing": project.root / "imports" / "Knight.glb"}
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json", result.attachments)
    assert check.ok, check.output[-3000:]
    manifest = project.output_dir / "manifest.json"  # on the wrong bone it lands elsewhere: the check sees it
    data = json.loads(manifest.read_text())
    data["models"]["thing"]["attach"]["bone"] = "chest"
    manifest.write_text(json.dumps(data))
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json", result.attachments)
    assert not check.ok and "thing on its bone lands at" in check.output, check.output[-3000:]
