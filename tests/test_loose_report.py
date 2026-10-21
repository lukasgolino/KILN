"""The LOOSE! dogfooding report (LOOSE_REPORT.md, items 1-16): each fix, pinned down."""

from __future__ import annotations

import base64
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from conftest import arms_text, built_of, closed_faces, errors_of, make_project, ok_model, sphere_text, write_model
from kiln.build import build
from kiln.builder import build_model, cache_key
from kiln.export import to_glb
from kiln.lint import lint_project
from kiln.mesher import Mesh
from kiln.project import Project
from kiln.rig import animation_poses
from kiln.vendor.gltf import read_accessor, read_glb
from test_importer import box_glb


def rules(project: Project) -> list[str]:
    return [f.rule for f in lint_project(project).findings]


# 1. repeated outline points
def test_extrude_drops_repeated_points(project: Project) -> None:
    text = """\
name: thing
parts:
  - extrude: { points: [[0, 0], [1, 0], [1, 0], [1, 1], [0, 1], [0, 0]], height: 0.4, at: [0, 0.2, 0] }
    color: red
"""
    model, _ = ok_model(project, text)
    assert model.parts[0].geometry.params["points"] == [[0, 0], [1, 0], [1, 1], [0, 1]]
    built = built_of(project, text)
    assert np.isfinite(built.painted.vertices).all() and built.triangles > 0


def test_extrude_with_too_few_distinct_points_is_an_error(project: Project) -> None:
    text = "name: thing\nparts:\n  - extrude: { points: [[0, 0], [1, 0], [1, 0], [0, 0]], height: 0.4 }\n    color: red\n"
    assert any(f.rule == "E003" and "different points" in f.message for f in errors_of(project, text))


# 2. paint ownership respects later cuts
def test_part_inside_a_cut_gets_its_own_colour(project: Project) -> None:
    text = """\
name: thing
parts:
  - box: { at: [0, 1, 0], size: [2, 2, 0.4] }
    color: grey
  - box: { at: [0, 0.7, 0], size: [0.8, 1.4, 1] }
    cut: true
  - box: { at: [0, 0.7, 0], size: [0.76, 1.36, 0.1] }
    color: blue
"""
    built = built_of(project, text)
    p = built.painted
    centre = p.vertices[p.faces].mean(axis=1)
    door = (np.abs(centre[:, 0]) < 0.3) & (centre[:, 1] < 1.2) & (centre[:, 2] > 0.04)  # the door's front
    colours = {p.groups[g].color_name.split("#")[0] for g in p.face_group[door]}
    assert colours == {"blue"}, colours


# 3. W101 judged at full detail; W111 when the budget loses a part; W112 for LODs
def test_hidden_part_is_w101(project: Project) -> None:
    write_model(project, """\
name: thing
parts:
  - sphere: { at: [0, 0.5, 0], radius: 0.5 }
    color: red
  - sphere: { at: [0, 0.5, 0], radius: 0.2 }
    color: blue
""")  # fmt: skip
    assert "W101" in rules(project)


def test_part_lost_in_decimation_is_w111(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    import kiln.builder as builder

    real = builder.decimate_regions  # type: ignore[attr-defined]

    def drop_the_pole(*args: object, **kwargs: object) -> tuple[Mesh, np.ndarray]:
        mesh, region = real(*args, **kwargs)  # type: ignore[arg-type]
        keep = mesh.vertices[mesh.faces].mean(axis=1)[:, 1] < 1.02  # as if the budget had erased the pole
        return Mesh(mesh.vertices, mesh.faces[keep]), region[keep]

    monkeypatch.setattr(builder, "decimate_regions", drop_the_pole)
    built = built_of(project, sphere_text().replace("radius: 0.3", "radius: 0.5").replace("[0, 0.3, 0]", "[0, 0.5, 0]")
                     + "  - cylinder: { at: [0, 1.2, 0], radius: 0.06, height: 0.4 }\n    color: red\n")  # fmt: skip
    assert built.lost == (1,) and built.hidden == ()
    from kiln.lint import geometry_warnings

    assert [f.rule for f in geometry_warnings(built, {}, project)].count("W111") == 1


def test_lod_missing_its_target_is_w112(project: Project) -> None:
    striped = sphere_text() + "    pattern: { type: stripes, color: blue, size: 0.05, axis: y }\nlod: [12]\n"  # stripes need triangles
    write_model(project, striped)
    result = build(project)
    assert any(f.rule == "W112" for f in result.findings)


# 4 + 5. imports keep their textures; the cache sees them
def _with_texture(glb: Path) -> Path:
    """The box as a .gltf (buffer inline) whose material refers to Textures/colormap.png, like a Kenney kit."""
    doc, binary = read_glb(glb.read_bytes())
    doc["buffers"] = [{"byteLength": len(binary), "uri": "data:application/octet-stream;base64," + base64.b64encode(binary).decode()}]
    doc["images"] = [{"uri": "Textures/colormap.png"}]
    doc["textures"] = [{"source": 0}]
    path = glb.with_suffix(".gltf")
    path.write_text(json.dumps(doc))
    glb.unlink()
    return path


def test_import_copies_textures_and_cache_sees_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln.cli import main
    from kiln.importer import missing_files

    pack = tmp_path / "pack"
    pack.mkdir()
    glb = _with_texture(box_glb(pack / "box.glb"))
    assert missing_files(glb) == ["Textures/colormap.png"]
    project = make_project(tmp_path / "art")
    monkeypatch.chdir(project.root)
    assert main(["import", str(glb), "--licence", "CC0-1.0"]) == 1  # the texture isn't there: refused
    (pack / "Textures").mkdir()
    from PIL import Image

    Image.new("RGB", (4, 4), (200, 30, 30)).save(pack / "Textures" / "colormap.png")
    assert main(["import", str(glb), "--licence", "CC0-1.0", "--force"]) == 0
    copied = project.root / "imports" / "Textures" / "colormap.png"
    assert copied.is_file()
    assert (project.root / "imports" / "box.gltf").is_file()
    model, style, _ = project.load(project.models_dir / "box.kiln.yaml")
    assert model is not None and style is not None
    before = cache_key(model, style, {})
    Image.new("RGB", (4, 4), (30, 200, 30)).save(copied)
    assert cache_key(model, style, {}) != before
    copied.unlink()
    with pytest.raises(ValueError, match="Textures/colormap.png"):
        build_model(model, style)


# 6. Godot checks run in a throwaway project
def test_godot_sandbox_copies_only_the_output(tmp_path: Path) -> None:
    from kiln.godot import _folder, _sandbox

    game = tmp_path / "game"
    (game / "assets" / "kiln" / "models").mkdir(parents=True)
    (game / "assets" / "kiln" / "models" / "a.glb").write_bytes(b"glb")
    (game / "assets" / "kiln" / "models" / "a.glb.import").write_text("host import")
    (game / "fonts").mkdir()
    (game / "project.godot").write_text('config_version=5\n\n[rendering]\n\nrenderer/rendering_method="mobile"\n')
    assert _folder("res://assets/kiln/manifest.json") == _folder("res://assets/kiln/models/a.tscn") == "res://assets/kiln"
    root = _sandbox(game, "res://assets/kiln", tmp_path / "tmp")
    assert (root / "assets" / "kiln" / "models" / "a.glb").is_file()
    assert not (root / "assets" / "kiln" / "models" / "a.glb.import").exists() and not (root / "fonts").exists()
    assert 'renderer/rendering_method="mobile"' in (root / "project.godot").read_text()


# 7. no PAGAN dependency
def test_kiln_does_not_import_pagan() -> None:
    code = "import sys, kiln.cli, kiln.build, kiln.mcp_server; print('pagan' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


# 8. .gdignore inside a Godot project
def test_init_inside_a_godot_project_writes_gdignore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln.cli import main

    (tmp_path / "project.godot").write_text("config_version=5\n")
    monkeypatch.chdir(tmp_path)
    assert main(["init", "art3d"]) == 0
    assert (tmp_path / "art3d" / ".gdignore").is_file()
    outside = tmp_path.parent / f"{tmp_path.name}_plain"
    assert main(["init", str(outside)]) == 0
    assert not (outside / ".gdignore").exists()


# 9 + 10. part boxes in the manifest; list values in rig meta
def test_manifest_part_boxes_and_vector_meta(project: Project) -> None:
    text = arms_text().replace("  arm_l: { pivot: [0.3, 0.6, 0] }", "  arm_l: { pivot: [0.3, 0.6, 0], meta: { hand: [0.45, 0.35, 0], side: left } }")
    write_model(project, text)
    result = build(project)
    arm = result.manifest["models"]["thing"]["parts"]["arm_l"]
    assert arm["meta"] == {"hand": [0.45, 0.35, 0], "side": "left"}
    assert arm["aabb"]["min"][0] > 0.2 and arm["aabb"]["max"][0] < 0.6
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    node = next(n for n in doc["nodes"] if n.get("name") == "arm_l")
    assert node["extras"]["hand"] == [0.45, 0.35, 0]


# 11. separate parts are their own closed meshes
def test_separate_part_is_its_own_closed_mesh(project: Project) -> None:
    text = """\
name: thing
class: character
parts:
  - sphere: { at: [0, 0.5, 0], radius: 0.4 }
    color: red
  - sphere: { at: [0, 0.8, 0], radius: 0.3 }
    id: helmet
    color: grey
rig:
  helmet: { pivot: [0, 0.8, 0], separate: true }
skin: soft
"""
    built = built_of(project, text)
    p = built.painted
    helmet = np.array([p.groups[g].bone == "helmet" for g in p.face_group])
    assert closed_faces(p.faces[helmet]) and closed_faces(p.faces[~helmet])  # neither has a hole
    assert built.pieces == 1


# 12. model families
def test_template_extends_and_remove(project: Project) -> None:
    write_model(project, """\
name: soldier
template: true
class: character
parts:
  - capsule: { from: [0, 0.3, 0], to: [0, 0.7, 0], radius: 0.3 }
    color: red
  - sphere: { at: [0.3, 0.6, 0], radius: 0.08 }
    id: arm_l
    mirror: x
    mirror_id: arm_r
    color: red
  - cone: { at: [0, 1.1, 0], radius: 0.2, height: 0.3 }
    id: hat
    color: grey
rig:
  arm_l: { pivot: [0.3, 0.6, 0] }
  hat: { pivot: [0, 1, 0] }
animations:
  wave: { fps: 8, cycle: { type: wave, arms: [arm_r] } }
""", "soldier")  # fmt: skip
    write_model(project, """\
name: archer
extends: soldier
description: an archer
remove: [hat]
parts:
  - sphere: { at: [0, 1.05, 0], radius: 0.15 }
    id: hood
    color: green
variants:
  blue: { swap: { red: blue } }
""", "archer")  # fmt: skip
    model, _ = ok_model(project, (project.models_dir / "archer.kiln.yaml").read_text(), "archer")
    assert model.ids == ["root", "arm_l", "arm_r", "hood"] and model.cls == "character" and model.description == "an archer"
    assert set(model.rig) == {"arm_l", "arm_r"} and "wave" in model.animations and model.variants and model.extends == "soldier"
    result = build(project)
    assert result.models == ["archer"]  # the template isn't built
    bad = errors_of(project, "name: other\nextends: archer\n", "other")
    assert any(f.rule == "E012" and "template" in f.message for f in bad)


# 13. cycles with pose overrides
def test_cycle_with_pose_overrides(project: Project) -> None:
    text = arms_text().replace(
        "  wave: { fps: 8, cycle: { type: wave, arms: [arm_l, arm_r], frames: 4 } }",
        "  wave: { fps: 8, cycle: { type: wave, arms: [arm_l, arm_r], frames: 4 }, poses: [{ arm_l: { rotate: [0, 0, -90] } }] }",
    )
    model, _ = ok_model(project, text)
    frames = animation_poses(model.animations["wave"], model)
    assert len(frames) == 4
    assert all(f["arm_l"].rotate == (0.0, 0.0, -90.0) for f in frames)
    assert len({f["arm_r"].rotate for f in frames}) > 1  # still waving


# 14. variants as material swaps
def test_variants_without_glbs(tmp_path: Path) -> None:
    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "art", 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "../assets/kiln"\n'
                           'export = ["glb", "godot"]\nvariant_glbs = false\n')  # fmt: skip
    write_model(project, sphere_text() + "variants:\n  team: { swap: { red: blue } }\n")
    result = build(project)
    entry = result.manifest["models"]["thing"]["variants"]["team"]
    assert "glb" not in entry and entry["swap"] == {"#e8413c": "#2f6fd0"}
    scene = (tmp_path / "assets" / "kiln" / "models" / "thing.team.tscn").read_text()
    assert 'path="res://assets/kiln/models/thing.glb"' in scene and '"e8413c": Color(' in scene
    assert not (tmp_path / "assets" / "kiln" / "models" / "thing.team.glb").exists()


# 15. parallel builds give the same models
def test_parallel_lint_matches_serial(tmp_path: Path) -> None:
    outs = []
    for jobs in ("1", "2"):
        project = make_project(tmp_path / jobs)
        write_model(project, sphere_text("a"), "a")
        write_model(project, arms_text("b"), "b")
        os.environ["KILN_JOBS"] = jobs
        try:
            result = lint_project(project)
        finally:
            del os.environ["KILN_JOBS"]
        outs.append({n: to_glb(b, "test") for n, b in sorted(result.built.items())})
    assert outs[0] == outs[1]


# 16. loose parts may float
def test_loose_parts_are_not_floating_pieces(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0, 1.2, 0], radius: 0.1 }\n    color: gold\n"
    assert built_of(project, text).pieces == 2
    assert built_of(project, text + "    loose: true\n").pieces == 1


# 18. the scene script shares materials and keeps the game's overrides
def test_scene_script_shares_materials_and_keeps_overrides() -> None:
    from kiln.godot import APPLY_SCRIPT

    assert "static var _shared" in APPLY_SCRIPT and "get_surface_override_material(i) != null" in APPLY_SCRIPT


# 19. vertex colours: one surface per material preset
def test_vertex_colors_merge_surfaces(tmp_path: Path) -> None:
    from kiln.gltf_check import accessor, check_glb

    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\nvertex_colors = true\n')
    write_model(project, arms_text().replace("color: blue", "color: blue\n    material: plastic"))
    build(project)
    data = (project.output_dir / "models" / "thing.glb").read_bytes()
    assert check_glb(data) == []
    doc, binary = read_glb(data)
    prims = [p for m in doc["meshes"] for p in m["primitives"]]
    names = sorted({doc["materials"][p["material"]]["name"] for p in prims})
    assert names == ["default_vertex#ffffff", "plastic_vertex#ffffff"]
    colours = np.concatenate([accessor(doc, binary, p["attributes"]["COLOR_0"]) for p in prims])
    assert len(np.unique(np.round(colours, 4), axis=0)) == 2  # red body, blue arms


# 21. soft toy metal doesn't mirror the sky
def test_soft_toy_metal_is_soft() -> None:
    from kiln.style import load_style

    style, _ = load_style("soft_toy")
    assert style is not None
    assert style.materials["metal"].metallic <= 0.4 and style.materials["skin"].roughness >= 0.8


# 22. sockets: named points that move with their part
def test_sockets_in_glb_and_manifest(project: Project) -> None:
    text = arms_text().replace("  arm_l: { pivot: [0.3, 0.6, 0] }", "  arm_l: { pivot: [0.3, 0.6, 0], sockets: { hand: [0.45, 0.35, 0] } }")
    write_model(project, text)
    result = build(project)
    parts = result.manifest["models"]["thing"]["parts"]
    assert parts["arm_l"]["sockets"]["hand"] == {"position": [0.45, 0.35, 0.0], "offset": [0.15, -0.25, 0.0], "node": "arm_l_hand"}
    assert parts["arm_r"]["sockets"]["hand"]["position"] == [-0.45, 0.35, 0.0]  # mirrored with the rig
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    nodes = {n["name"]: (i, n) for i, n in enumerate(doc["nodes"])}
    index, hand = nodes["arm_l_hand"]
    assert index in nodes["arm_l"][1]["children"] and hand["extras"] == {"kiln_socket": "hand", "kiln_part": "arm_l"}
    np.testing.assert_allclose(hand["translation"], [0.15, -0.25, 0.0], atol=1e-6)


# 36. vertex colours on glow surfaces of skinned models too
def test_vertex_colors_on_glow_skinned(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\nvertex_colors = true\n')
    write_model(project, arms_text(skin="soft").replace("color: blue", "color: blue\n    material: glow"))
    build(project)
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    prims = [p for m in doc["meshes"] for p in m["primitives"]]
    assert "JOINTS_0" in prims[0]["attributes"] and all("COLOR_0" in p["attributes"] for p in prims)


# 32/43. api.part knows the part-level options
def test_api_part_sorts_part_options() -> None:
    from kiln.api import part

    out = part("sphere", color="red", radius=0.1, loose=True, keep=True, hard=True)
    assert out["loose"] is True and out["keep"] is True and out["hard"] is True and out["sphere"] == {"radius": 0.1}


# 40. model origin: base | center | [x, y, z]
@pytest.mark.parametrize("skin", ["rigid", "soft"])
def test_origin_center_moves_the_glb(project: Project, skin: str) -> None:
    from kiln.fitting import read_surface

    text = arms_text(skin=skin).replace("name: thing\n", "name: thing\norigin: center\n")
    write_model(project, text)
    result = build(project)
    entry = result.manifest["models"]["thing"]
    lo, hi = np.array(entry["bounds"]["min"]), np.array(entry["bounds"]["max"])
    np.testing.assert_allclose(entry["origin"], (lo + hi) / 2, atol=1e-5)
    path = project.output_dir / "models" / "thing.glb"
    doc, _ = read_glb(path.read_bytes())
    root = doc["nodes"][0]
    np.testing.assert_allclose(root["translation"], -np.array(entry["origin"]), atol=1e-5)
    if skin == "rigid":  # rest-pose world positions are centred
        v, _ = read_surface(path)
        np.testing.assert_allclose((v.min(axis=0) + v.max(axis=0)) / 2, 0, atol=1e-4)


def test_origin_point_and_errors(project: Project) -> None:
    built = built_of(project, sphere_text().replace("parts:", "origin: [0, 1, 0]\nparts:", 1))
    np.testing.assert_allclose(built.origin(), [0, 1, 0])
    base = built_of(project, sphere_text().replace("parts:", "origin: base\nparts:", 1))
    lo, _ = base.bounds()
    assert base.origin()[1] == pytest.approx(lo[1])
    assert any(f.rule == "E003" and "origin is base" in f.message for f in errors_of(project, sphere_text().replace("parts:", "origin: top\nparts:", 1)))


# 39. projected UVs
def _uvs(project: Project, text: str) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:

    write_model(project, text)
    result = build(project)
    doc, binary = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    prim = doc["meshes"][0]["primitives"][0]
    pos = read_accessor(doc, binary, prim["attributes"]["POSITION"])
    uv = read_accessor(doc, binary, prim["attributes"]["TEXCOORD_0"])
    return result.manifest["models"]["thing"], pos, uv


@pytest.mark.parametrize("extra", ["", ", sides: 12"])
def test_uv_cylindrical_runs_along_the_axis(project: Project, extra: str) -> None:
    text = f"name: thing\nparts:\n  - cylinder: {{ at: [0, 0.5, 0], radius: 0.2, height: 1{extra} }}\n    color: red\n    uv: cylindrical\n"
    entry, pos, uv = _uvs(project, text)
    assert entry["uv"] == {"set": "TEXCOORD_0", "parts": ["root"]}
    side = np.abs(np.hypot(pos[:, 0], pos[:, 2]) - 0.2) < 0.02
    np.testing.assert_allclose(uv[side, 1], pos[side, 1], atol=0.05)  # v = height over the 1 m box
    assert uv[:, 0].min() >= -1e-6 and uv[:, 0].max() <= 2.0


def test_uv_along_a_tube_and_errors(project: Project) -> None:
    text = ("name: thing\nparts:\n  - tube: { points: [[0, 0.1, 0], [0, 1, 0], [1, 1, 0]], radius: 0.08 }\n    color: red\n"
            "    uv: { project: along, scale: [1, 2] }\n")  # fmt: skip
    _, pos, uv = _uvs(project, text)
    end = pos[:, 0] > 0.95
    assert uv[end, 1].mean() > 1.7  # v reaches 2 (scale) at the far end
    assert any(f.rule == "E003" and "uv projects" in f.message for f in errors_of(project, text.replace("along", "planar")))


# 31. polygon distance: only the edges that can be nearest (same result as the even-odd loop over every edge)
def test_tiled_polygon_distance_matches_even_odd() -> None:
    from kiln.sdf import _even_odd, polygons_2d

    rng = np.random.default_rng(3)
    t = np.linspace(0, 2 * np.pi, 300, endpoint=False)
    r = 0.5 + 0.1 * np.sin(7 * t)
    outer = np.stack([r * np.cos(t), r * np.sin(t)], axis=1)
    hole = 0.15 * np.stack([np.cos(t[::10]), np.sin(t[::10])], axis=1)
    p = np.concatenate([rng.uniform(-0.7, 0.7, (40000, 2)), outer + rng.normal(0, 1e-3, outer.shape)])
    for loops in ([outer], [outer[::-1]], [outer, hole]):
        a = np.concatenate([np.roll(lp, 1, axis=0) for lp in loops])
        b = np.concatenate(loops)
        np.testing.assert_allclose(polygons_2d(p, loops), _even_odd(p, a, b), atol=1e-12)


# 27/28. extrude with holes (one round for every edge) and offset outlines
@pytest.mark.parametrize("hard", [False, True])
def test_extrude_holes_and_offset(project: Project, hard: bool) -> None:
    from kiln.sdf import SHAPES

    square = "[[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]"
    hole = "[[-0.2, -0.2], [0.2, -0.2], [0.2, 0.2], [-0.2, 0.2]]"
    extra = ", hard: true" if hard else ""
    text = f"name: thing\nparts:\n  - extrude: {{ points: {square}, holes: [{hole}], height: 0.2, offset: 0.05, at: [0, 0.1, 0] }}\n    color: red{extra}\n"
    text = text.replace(", hard: true", "\n    hard: true")
    model, _ = ok_model(project, text)
    g = model.parts[0].geometry
    p = np.array([[0.0, 0.1, 0.0], [0.4, 0.1, 0.0], [0.53, 0.1, 0.0], [0.6, 0.1, 0.0], [0.17, 0.1, 0.0]])
    inside = SHAPES["extrude"].fn(p - g.at, g.params) < 0
    assert inside.tolist() == [False, True, True, False, True]  # hole, wall, grown edge, outside, where the hole shrank
    built = built_of(project, text)
    v = built.painted.vertices[np.unique(built.painted.faces)]
    assert v[:, 0].max() == pytest.approx(0.55, abs=0.02)
    centre = np.abs(v[:, [0, 2]]).max(axis=1)
    assert ((centre > 0.14) & (centre < 0.16)).any()  # the hole's wall, 0.05 in from 0.2
    assert not (centre < 0.1).any()
    assert closed_faces(built.painted.faces) if hard else True


# 29. aim any shape from one point to another
def test_aim_points_a_cylinder_between_two_points(project: Project) -> None:
    from kiln.sdf import SHAPES

    text = "name: thing\nparts:\n  - cylinder: { radius: 0.05, aim: [[0, 0, 0], [1, 1, 0]] }\n    color: red\n"
    model, _ = ok_model(project, text)
    g = model.parts[0].geometry
    assert g.params["height"] == pytest.approx(math.sqrt(2))
    np.testing.assert_allclose(g.at, [0.5, 0.5, 0])
    assert g.rotation is not None
    np.testing.assert_allclose(g.rotation @ [0, 1, 0], np.array([1, 1, 0]) / math.sqrt(2), atol=1e-9)
    inside = [[0.1, 0.1, 0], [0.9, 0.9, 0], [0.5, 0.5, 0.04]]
    outside = [[0.5, 0.6, 0], [1.05, 1.05, 0]]
    assert (g.distance(np.array(inside)) < 0).all() and (g.distance(np.array(outside)) > 0).all()
    assert SHAPES["cylinder"]
    down = "name: thing\nparts:\n  - box: { size: [0.1, 0.5, 0.2], aim: { from: [0, 1, 0], to: [0, 0, 0], roll: 90 } }\n    color: red\n"
    g2 = ok_model(project, down)[0].parts[0].geometry
    assert g2.rotation is not None
    np.testing.assert_allclose(g2.rotation @ [0, 1, 0], [0, -1, 0], atol=1e-9)
    bad = text.replace("radius: 0.05,", "radius: 0.05, at: [0, 1, 0],")
    assert any(f.rule == "E003" and "not both" in f.message for f in errors_of(project, bad))


# 30. several patterns on one part, in its own frame
def test_several_patterns_in_the_part_frame(project: Project) -> None:
    text = """\
name: thing
parts:
  - box: { size: [0.4, 1, 0.4], aim: [[0, 0, 0], [1, 0, 0]] }
    color: wood
    pattern:
      - { type: stripes, color: gold, size: 0.25, axis: y, frame: part }
      - { type: band, color: grey, size: 0.1, at: 0, axis: y, frame: part }
"""
    model, _ = ok_model(project, text)
    assert [p.type for p in model.parts[0].patterns] == ["stripes", "band"]
    built = built_of(project, text)
    p = built.painted
    centre = p.vertices[p.faces].mean(axis=1)
    colour = np.array([p.groups[g].color for g in p.face_group])
    top = centre[:, 1] > 0.15  # the box lies along x: stripes and the band run across x
    grey = colour == "#8a93a3"
    assert grey.any() and (np.abs(centre[grey & top, 0] - 0.5) < 0.08).all()
    others = {c for c in colour[top & ~grey]}
    assert len(others) == 2  # wood and the stripes' gold, both still there


def test_ring_array_around_any_direction(project: Project) -> None:
    text = "name: thing\nparts:\n  - sphere: { at: [0, 1, 0], radius: 0.1 }\n    color: red\n    array: { count: 4, around: [1, 0, 0], center: [0, 0, 0] }\n"
    g = ok_model(project, text)[0].parts[0].geometry
    centres = np.array([c.to_world(np.array([[0.0, 1.0, 0.0]]))[0] for c in g.copies])
    np.testing.assert_allclose(centres, [[0, 1, 0], [0, 0, 1], [0, -1, 0], [0, 0, -1]], atol=1e-9)


# 38. per-part numbers exported per vertex
def test_attr_per_vertex(project: Project) -> None:
    from kiln.vendor.gltf import validate

    text = """\
name: thing
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    color: red
    attr: { heat: 0.25 }
  - sphere: { at: [0, 0.8, 0], radius: 0.25 }
    color: red
    attr: { heat: 1, fade: 0.5 }
"""
    write_model(project, text)
    result = build(project)
    entry = result.manifest["models"]["thing"]
    assert entry["attributes"] == {"fade": {"gltf": "_FADE", "color_alpha": True}, "heat": {"gltf": "_HEAT", "color_alpha": False}}
    doc, binary = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    assert not validate(doc, binary)
    prim = doc["meshes"][0]["primitives"][0]
    pos = read_accessor(doc, binary, prim["attributes"]["POSITION"])
    heat = read_accessor(doc, binary, prim["attributes"]["_HEAT"]).reshape(-1)
    color = read_accessor(doc, binary, prim["attributes"]["COLOR_0"])
    assert color.shape[1] == 4 and set(np.round(color[:, 3], 3)) == {0.0, 0.5}
    assert set(np.round(heat[pos[:, 1] < 0.3], 3)) == {0.25} and set(np.round(heat[pos[:, 1] > 0.9], 3)) == {1.0}


# 26. SVG path outlines (fonts' glyphs, logos)
def test_svg_path_flattening() -> None:
    from kiln.svgpath import PathError, outlines

    square = outlines("M0 0 H10 V10 H0 Z", scale=0.1)
    assert square == [[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]]
    circle = outlines("M 1 0 A 1 1 0 1 1 -1 0 A 1 1 0 1 1 1 0 Z", tolerance=0.001)[0]
    r = np.hypot(*np.array(circle).T)
    assert len(circle) > 40 and np.abs(r - 1).max() < 1e-9
    curve = outlines("M0 0 Q 5 10 10 0 T 20 0 L 20 -5 C 15 -8 5 -8 0 -5 z", tolerance=0.01)[0]
    assert len(curve) > 10 and max(p[1] for p in curve) == pytest.approx(5, abs=0.02)  # quadratic peak = half the control height
    two = outlines("M0 0 l 1 0 0 1 z m 3 0 l 1 0 0 1 z")  # relative, implicit line-tos, two subpaths
    assert len(two) == 2 and two[1][0] == (3.0, 0.0)
    with pytest.raises(PathError):
        outlines("M0 0 X 1 2")


@pytest.mark.parametrize("hard", [False, True])
def test_extrude_path_with_counter_and_island(project: Project, hard: bool) -> None:
    from kiln.sdf import SHAPES

    # a ring (outer square with a square counter) and a separate dot on the right
    path = "M0 0 H1 V1 H0 Z M0.3 0.3 V0.7 H0.7 V0.3 Z M1.3 0.4 h0.2 v0.2 h-0.2 z"
    text = f'name: thing\nparts:\n  - extrude: {{ path: "{path}", height: 0.1, at: [0, 0.05, 0] }}\n    color: red\n'
    if hard:
        text += "    hard: true\n"
    model, _ = ok_model(project, text)
    g = model.parts[0].geometry
    assert len(g.params["holes"]) == 2
    p = np.array([[0.1, 0, 0.1], [0.5, 0, 0.5], [1.4, 0, 0.5], [1.15, 0, 0.5]])
    assert (SHAPES["extrude"].fn(p, g.params) < 0).tolist() == [True, False, True, False]
    built = built_of(project, text)
    v = built.painted.vertices[np.unique(built.painted.faces)]
    assert v[:, 0].max() == pytest.approx(1.5, abs=0.02)  # the island is there
    if hard:
        assert closed_faces(built.painted.faces)
    assert any(f.rule == "E003" and "path:" in f.message for f in errors_of(project, text.replace(path, "M0 0 X")))
