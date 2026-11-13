"""#171: other models placed in a model (`instances:`), each its own build at its own detail."""

from __future__ import annotations

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


def test_lods_hold_their_budget_and_maps_are_refused(desk: Project) -> None:
    write_model(desk, DESK.replace("resolution: 0.03\n", "resolution: 0.03\nlod: [60]\n"), "desk")
    assert not build(desk).errors
    doc, _ = read_glb((desk.output_dir / "models" / "desk.lod1.glb").read_bytes())
    tris = sum(desk_acc["count"] // 3 for m in doc["meshes"] for prim in m["primitives"] for desk_acc in [doc["accessors"][prim["indices"]]])
    assert tris <= 60 * 1.5, tris
    write_model(desk, DESK.replace("resolution: 0.03\n", "resolution: 0.03\nnormal_map: 256\n"), "desk")
    assert any("normal map" in f.message for f in build(desk).findings)


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
    """#295: a placed model's texture and decal come with it (back in its own frame), turned with the instance; a
    scaled instance leaves them out."""
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
    assert textured.sum() == (crate.painted.face_decal >= 0).sum()  # the turned crate's faces; not the scaled one's
    d = p.decals[int(p.face_decal[textured][0])]
    assert d.copy is not None
    own = corner_uv(crate.painted.decals[0], crate.painted.vertices[crate.painted.faces[crate.painted.face_decal >= 0]])
    placed = corner_uv(d, p.vertices[p.faces[textured]])
    assert np.allclose(np.sort(own.reshape(-1)), np.sort(placed.reshape(-1)), atol=1e-6)  # the same image coordinates
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "shelf.glb").read_bytes())
    assert doc.get("images")
