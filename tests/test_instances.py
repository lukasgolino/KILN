"""#171: other models placed in a model (`instances:`), each its own build at its own detail."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import errors_of, run_json, write_model

from kiln.build import build
from kiln.cli import main
from kiln.gltf_check import read_glb
from kiln.lint import lint_paths
from kiln.project import Project

SCREW = "name: screw\nresolution: 0.004\nparts:\n  - cylinder: { at: [0, 0.01, 0], radius: 0.01, height: 0.02 }\n    color: grey\n"
DESK = """\
name: desk
resolution: 0.03
parts:
  - box: { at: [0, 0.05, 0], size: [1.0, 0.1, 0.6] }
    color: wood
instances:
  - { model: screw, at: [0.2, 0.1, 0] }
  - { model: screw, at: [-0.2, 0.1, 0.1], rotate: [0, 45, 0], scale: 2 }
"""


@pytest.fixture
def desk(project: Project) -> Project:
    write_model(project, SCREW, "screw")
    write_model(project, DESK, "desk")
    return project


def test_instances_keep_their_own_detail(desk: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln.cli import _built

    monkeypatch.chdir(desk.root)
    screw = _built(desk, "screw")
    scene = _built(desk, "desk")
    assert scene.triangles >= 2 * screw.triangles  # both screws, each with all its triangles
    v = scene.painted.vertices
    grey = np.array([scene.painted.groups[g].color == "#8a93a3" for g in scene.painted.face_group])
    tops = v[scene.painted.faces[grey]].reshape(-1, 3)
    assert abs(tops[:, 1].max() - (0.1 + 0.04)) < 2e-3  # the big screw (scale 2) stands 4 cm on the desk top
    assert np.isclose(tops[:, 0].max(), 0.21, atol=2e-3)  # the first screw at x = 0.2, radius 1 cm


def test_the_glb_carries_them(desk: Project) -> None:
    assert not build(desk).errors
    doc, _ = read_glb((desk.output_dir / "models" / "desk.glb").read_bytes())
    assert any(m["name"].startswith("default_grey") for m in doc["materials"])


def test_missing_and_circular_instances(desk: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(desk, DESK.replace("model: screw, at: [0.2", "model: bolt, at: [0.2"), "desk")
    found = [f for f in lint_paths(desk, [desk.models_dir / "desk.kiln.yaml"], geometry=False).findings if f.rule == "E011"]
    assert found and "bolt" in found[0].message
    write_model(desk, SCREW + "instances: [{ model: desk }]\n", "screw")
    write_model(desk, DESK, "desk")
    monkeypatch.chdir(desk.root)
    code, out = run_json(["preview", "desk", "--views", "front", "--size", "64"], capsys)
    assert code != 0 and "circle" in str(out), out
    assert main(["--json", "build", "desk"]) != 0


def test_bad_entries_are_refused(project: Project) -> None:
    for entry in ("[{ model: desk }]", "[{ model: screw, scale: 0 }]", "[{ model: screw, id: nope }]", "{ model: screw }"):
        text = DESK.split("instances:")[0].replace("name: desk", "name: desk") + f"instances: {entry}\n"
        assert any(f.rule == "E003" for f in errors_of(project, text, "desk")), entry


def test_an_instance_moves_with_its_part(desk: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln.cli import _built

    rigged = DESK.replace("    color: wood\n", "    color: wood\n  - box: { at: [0.3, 0.2, 0], size: [0.1, 0.2, 0.1] }\n    id: arm\n    color: red\n") \
        .replace("  - { model: screw, at: [0.2, 0.1, 0] }", "  - { model: screw, at: [0.3, 0.3, 0], id: arm }") + "skin: rigid\nrig:\n  arm: { pivot: [0.3, 0.1, 0] }\n"  # fmt: skip
    write_model(desk, rigged, "desk")
    monkeypatch.chdir(desk.root)
    scene = _built(desk, "desk")
    bones = {scene.painted.groups[g].bone for g in scene.painted.face_group if scene.painted.groups[g].color == "#8a93a3"}
    assert bones == {"arm", "root"}  # one screw on the arm, one on the root


def test_the_instance_origin_goes_at_at(desk: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln.cli import _built

    write_model(desk, SCREW + "origin: center\n", "screw")
    monkeypatch.chdir(desk.root)
    scene = _built(desk, "desk")
    p = scene.painted
    grey = np.array([p.groups[g].color == "#8a93a3" for g in p.face_group])
    first = p.vertices[p.faces[grey]].reshape(-1, 3)
    first = first[first[:, 0] > 0]
    assert abs((first[:, 1].min() + first[:, 1].max()) / 2 - 0.1) < 2e-3  # its centre at y = 0.1, as its glb's origin


def test_lods_hold_their_budget_and_a_mapped_scene_takes_references(desk: Project) -> None:
    write_model(desk, DESK.replace("resolution: 0.03\n", "resolution: 0.03\nlod: [60]\n"), "desk")
    assert not build(desk).errors
    doc, _ = read_glb((desk.output_dir / "models" / "desk.lod1.glb").read_bytes())
    tris = sum(desk_acc["count"] // 3 for m in doc["meshes"] for prim in m["primitives"] for desk_acc in [doc["accessors"][prim["indices"]]])
    assert tris <= 60 * 1.5, tris
    write_model(desk, DESK.replace("resolution: 0.03\n", "resolution: 0.03\nnormal_map: 256\n"), "desk")
    assert not build(desk).errors  # (#355) its screws are references now, not refused


def test_a_partial_build_rebuilds_the_scene(desk: Project) -> None:
    from kiln.build import _with_dependents

    paths = _with_dependents(desk, [desk.models_dir / "screw.kiln.yaml"])
    assert {p.name for p in paths} == {"screw.kiln.yaml", "desk.kiln.yaml"}


def test_no_dependents_builds_only_what_is_named(desk: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(desk.root)
    code, out = run_json(["build", "screw", "--no-dependents"], capsys)
    assert code == 0 and out["models"] == ["screw"], out
    code, out = run_json(["build", "screw"], capsys)
    assert code == 0 and sorted(out["models"]) == ["desk", "screw"], out


def test_instances_keep_their_textures_and_decals(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    """#295, #353: a placed model's texture and decal come with it (back in its own frame), turned and scaled with the
    instance."""
    from PIL import Image

    from kiln.cli import _built
    from kiln.paint import corner_uv

    (project.root / "textures").mkdir(exist_ok=True)
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(project.root / "textures" / "tile.png")
    write_model(project, "name: crate\nparts:\n  - box: { at: [0, 0.1, 0], size: [0.2, 0.2, 0.2] }\n    color: wood\n"
                "    texture: { image: textures/tile.png, project: box, texel: 0.01 }\n", "crate")  # fmt: skip
    write_model(project, "name: shelf\nparts:\n  - box: { at: [0, 0.05, 0], size: [1.0, 0.1, 0.6] }\n    color: grey\ninstances:\n"
                "  - { model: crate, at: [0.3, 0.1, 0], rotate: [0, 30, 0] }\n  - { model: crate, at: [-0.3, 0.1, 0], scale: 0.5 }\n", "shelf")  # fmt: skip
    monkeypatch.chdir(project.root)
    crate, shelf = _built(project, "crate"), _built(project, "shelf")
    p = shelf.painted
    textured = p.face_decal >= 0
    assert textured.sum() == 2 * (crate.painted.face_decal >= 0).sum()  # the turned crate's faces and the scaled one's
    own = corner_uv(crate.painted.decals[0], crate.painted.vertices[crate.painted.faces[crate.painted.face_decal >= 0]])
    for k in sorted(set(p.face_decal[textured].tolist())):  # each copy (turned, scaled): the crate's own image coordinates
        d = p.decals[k]
        assert d.copy is not None
        placed = corner_uv(d, p.vertices[p.faces[p.face_decal == k]])
        assert np.allclose(np.sort(own.reshape(-1)), np.sort(placed.reshape(-1)), atol=1e-6)
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "shelf.glb").read_bytes())
    assert doc.get("images")


def test_lint_sees_the_instances_and_a_scene_of_instances_only(project: Project) -> None:
    """#333: lint measures the scene with its instances (size, triangle line, pieces joined by them); the budget is
    the model's own; a scene needs no parts of its own."""
    write_model(project, SCREW, "screw")
    write_model(project, "name: link\nparts:\n  - box: { at: [0, 0.01, 0], size: [0.1, 0.02, 0.02] }\n    color: grey\n", "link")
    clasp = ("name: clasp\nparts:\n  - box: { at: [-0.1, 0.01, 0], size: [0.1, 0.02, 0.04] }\n    color: wood\n"
             "  - box: { at: [0.1, 0.01, 0], size: [0.1, 0.02, 0.04] }\n    color: wood\ninstances:\n  - { model: link, at: [0, 0, 0] }\n")  # fmt: skip
    result = lint_paths(project, [write_model(project, clasp, "clasp")])
    rules = [f.rule for f in result.findings]
    assert "W103" not in rules, [f.format() for f in result.findings]  # the link joins the two halves
    built = result.built["clasp"]
    assert built.own_triangles and built.triangles > built.own_triangles
    tray = lint_paths(project, [write_model(project, "name: tray\ninstances:\n  - { model: screw, at: [0.1, 0, 0] }\n  - { model: screw, at: [-0.1, 0, 0] }\n", "tray")])
    assert not [f for f in tray.findings if f.severity == "error"], [f.format() for f in tray.findings]
    assert tray.built["tray"].triangles > 0
    assert not build(project).errors


def test_copies_share_one_mesh(project: Project) -> None:
    """#353: a model placed several times is one mesh in the glb with a node per copy; read back, the copies stand
    where the merged build has them."""
    from kiln.importer import read_mesh

    write_model(project, SCREW, "screw")
    tray = ("name: tray\nparts:\n  - box: { at: [0, 0.01, 0], size: [0.5, 0.02, 0.3] }\n    color: wood\ninstances:\n"
            "  - { model: screw, at: [0.1, 0.02, 0] }\n  - { model: screw, at: [-0.1, 0.02, 0], rotate: [0, 90, 0] }\n"
            "  - { model: screw, at: [0, 0.02, 0.1], rotate: [90, 0, 0] }\n")  # fmt: skip
    write_model(project, tray, "tray")
    assert not build(project).errors
    path = project.output_dir / "models" / "tray.glb"
    doc, _ = read_glb(path.read_bytes())
    screw_mesh = [k for k, mesh in enumerate(doc["meshes"]) if mesh["name"] == "screw"]
    assert len(screw_mesh) == 1 and sum(1 for n in doc["nodes"] if n.get("mesh") == screw_mesh[0]) == 3
    v, f, _, _ = read_mesh(path)
    import os

    from kiln.cli import _built

    os.chdir(project.root)
    built = _built(project, "tray")
    assert len(f) == len(built.painted.faces)
    read = np.sort(v[f].mean(axis=1), axis=0)  # face centres, as read back with the copies' node transforms
    want = np.sort((built.painted.vertices - built.origin())[built.painted.faces].mean(axis=1), axis=0)
    assert np.allclose(read, want, atol=2e-3)


@pytest.mark.slow
def test_godot_loads_shared_copies(tmp_path: Path) -> None:
    from conftest import make_project

    from kiln.godot import find_godot_binary, verify

    godot = find_godot_binary()
    if godot is None:
        pytest.skip("needs a Godot 4 binary (GODOT=/path)")
    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "game/assets/kiln"\nexport = ["glb", "godot"]\n')
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text('config_version=5\n[application]\nconfig/name="t"\n')
    write_model(project, SCREW, "screw")
    write_model(project, "name: tray\nparts:\n  - box: { at: [0, 0.01, 0], size: [0.5, 0.02, 0.3] }\n    color: wood\ninstances:\n"
                "  - { model: screw, at: [0.1, 0.02, 0] }\n  - { model: screw, at: [-0.1, 0.02, 0], rotate: [0, 90, 0] }\n", "tray")  # fmt: skip
    result = build(project)
    assert not result.errors and result.godot_root is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]


@pytest.mark.slow
def test_instances_with_maps_are_references(tmp_path: Path) -> None:
    """#355: an instance whose model bakes maps is a reference (a node its own scene fills, maps and all), and a scene
    with maps of its own takes instances that way; Godot loads both."""
    from conftest import make_project

    from kiln.godot import find_godot_binary, verify

    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "game/assets/kiln"\nexport = ["glb", "godot"]\n')
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text('config_version=5\n[application]\nconfig/name="t"\n')
    write_model(project, "name: furry\nnormal_map: 256\nparts:\n  - sphere: { at: [0, 0.1, 0], radius: 0.1 }\n    id: body\n    color: wood\n"
                "relief:\n  - on: [body]\n    length: 0.04\n    width: 0.03\n", "furry")  # fmt: skip
    write_model(project, SCREW, "screw")
    write_model(project, "name: shelf\nparts:\n  - box: { at: [0, 0.05, 0], size: [1.0, 0.1, 0.6] }\n    color: wood\ninstances:\n"
                "  - { model: furry, at: [0.3, 0.1, 0], rotate: [0, 90, 0] }\n  - { model: screw, at: [-0.3, 0.1, 0] }\n", "shelf")  # fmt: skip
    write_model(project, "name: mapped\nnormal_map: 256\nparts:\n  - box: { at: [0, 0.05, 0], size: [1.0, 0.1, 0.6] }\n    color: wood\n"
                "instances:\n  - { model: screw, at: [0, 0.1, 0] }\n", "mapped")  # fmt: skip
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    doc, _ = read_glb((project.output_dir / "models" / "shelf.glb").read_bytes())
    ref = [n for n in doc["nodes"] if n["name"].startswith("kiln_ref_furry")]
    assert len(ref) == 1 and "mesh" not in ref[0] and ref[0]["extras"]["kiln_reference"]
    assert not any(m["name"] == "furry" for m in doc["meshes"])
    doc, _ = read_glb((project.output_dir / "models" / "mapped.glb").read_bytes())
    assert any(n["name"].startswith("kiln_ref_screw") for n in doc["nodes"])
    assert 'refs = {"furry": "res://assets/kiln/models/furry.tscn"}' in (project.output_dir / "models" / "shelf.tscn").read_text()
    godot = find_godot_binary()
    if godot is not None and result.godot_root is not None:
        check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
        assert check.ok, check.output[-3000:]
