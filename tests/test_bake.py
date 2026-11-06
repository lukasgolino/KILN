"""#111: normal maps baked from the distance field, and `detail: true` parts only the bake sees."""

from __future__ import annotations

import io

import numpy as np
import pytest
from conftest import load, write_model
from PIL import Image

from kiln import bake as bk
from kiln.build import build
from kiln.gltf_check import check_glb
from kiln.lint import lint_paths
from kiln.mesher import decimate, dual_contour
from kiln.project import Project
from kiln.sdf import Field, Geometry, axis_rotation
from kiln.vendor.gltf import read_glb

pytestmark = pytest.mark.skipif(not bk.available(), reason="xatlas not installed (kiln[bake])")

BALL = Field([Geometry("sphere", {"radius": 0.3})], margin=0.03)
GROOVED = Field([Geometry("sphere", {"radius": 0.3}), Geometry("torus", {"radius": 0.3, "thickness": 0.01}, op="cut", blend=0.004)], margin=0.03)


def ball_mesh() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = decimate(BALL, dual_contour(BALL, 0.02), 3000, 0.02)
    n = m.vertices / np.linalg.norm(m.vertices, axis=1, keepdims=True)
    return m.vertices, m.faces, n[m.faces]


def decode(b: bk.Bake, vertices: np.ndarray, faces: np.ndarray, normals: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """World normals read back from the map at texel centres (as an engine does), and the points under them."""
    img = np.asarray(Image.open(io.BytesIO(b.png))).astype(float) / 255 * 2 - 1
    face, texel, bary = bk._texels(b.uv, b.width, b.height)
    p = (vertices[faces[face]] * bary[:, :, None]).sum(1)
    n = (normals[face] * bary[:, :, None]).sum(1)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    t = (b.tangent[face, :, :3] * bary[:, :, None]).sum(1)
    t -= n * (n * t).sum(1, keepdims=True)
    t /= np.linalg.norm(t, axis=1, keepdims=True)
    up = np.cross(n, t) * np.where((b.tangent[face, :, 3] * bary).sum(1) < 0, -1, 1)[:, None]
    local = img.reshape(-1, 3)[texel]
    world = local[:, :1] * t + local[:, 1:2] * up + local[:, 2:3] * n
    return world / np.linalg.norm(world, axis=1, keepdims=True), p


def test_baked_normals_round_trip() -> None:
    v, f, n = ball_mesh()
    b = bk.bake([GROOVED], np.zeros(len(f), np.int64), v, f, n, 256, 0.02)
    world, p = decode(b, v, f, n)
    q = p.copy()
    for _ in range(3):
        q = q - GROOVED.distance(q)[:, None] * GROOVED.gradient(q, 0.002)
    truth = GROOVED.gradient(q, 0.001)
    angle = np.degrees(np.arccos(np.clip((world * truth).sum(1), -1, 1)))
    assert np.median(angle) < 1.0 and np.percentile(angle, 95) < 3.0
    groove = np.abs(q[:, 1]) < 0.015
    tilt = np.degrees(np.arccos(np.clip((world[groove] * (p[groove] / np.linalg.norm(p[groove], axis=1, keepdims=True))).sum(1), -1, 1)))
    assert np.median(tilt) > 15  # the groove the mesh doesn't have shows in the map


def test_tangents_are_square_unit_and_signed() -> None:
    v, f, n = ball_mesh()
    uv, _, _ = bk.unwrap(v, f, 256)
    t = bk.tangents(v, f, uv, n)
    assert t.shape == (len(f), 3, 4)
    np.testing.assert_allclose(np.linalg.norm(t[..., :3], axis=-1), 1.0, atol=1e-9)
    assert np.abs((t[..., :3] * n).sum(-1)).max() < 1e-9
    assert set(np.unique(t[..., 3])) <= {-1.0, 1.0}
    # +u along the tangent: across each face, uv moves the same way as the position does along it
    p = v[f]
    du = uv[:, 1, 0] - uv[:, 0, 0]
    along = ((p[:, 1] - p[:, 0]) * t[:, 0, :3]).sum(1)
    big = np.abs(du) > 1e-3
    assert (np.sign(du[big]) == np.sign(along[big])).mean() > 0.9


def test_bake_is_deterministic() -> None:
    v, f, n = ball_mesh()
    one = np.zeros(len(f), np.int64)
    a, b = bk.bake([GROOVED], one, v, f, n, 128, 0.02), bk.bake([GROOVED], one, v, f, n, 128, 0.02)
    assert a.png == b.png and np.array_equal(a.uv, b.uv)


MODEL = """\
name: thing
normal_map: 256
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    color: red
  - torus: { at: [0, 0.3, 0], radius: 0.3, thickness: 0.012 }
    cut: true
    blend: 0.004
    detail: true
"""


def test_detail_parts_leave_the_mesh(project: Project) -> None:
    model, _, findings = load(project, MODEL)
    assert model is not None, findings
    assert len(model.parts) == 1 and model.bake_parts is not None and len(model.bake_parts) == 2
    built = lint_paths(project, [write_model(project, MODEL)]).built["thing"]
    v = built.painted.vertices[np.unique(built.painted.faces)]
    r = np.linalg.norm(v - [0, 0.3, 0], axis=1)
    assert r.min() > 0.29  # no groove cut into the mesh
    assert built.bake is not None and built.bake.size == 256


def test_glb_has_uvs_tangents_and_the_map(project: Project) -> None:
    write_model(project, MODEL)
    result = build(project)
    assert not result.errors, result.findings
    entry = result.manifest["models"]["thing"]
    assert entry["normal_map"]["png"] == "models/thing.normal.png" and (project.output_dir / "models" / "thing.normal.png").is_file()
    data = (project.output_dir / entry["glb"]).read_bytes()
    assert check_glb(data) == []
    doc, _ = read_glb(data)
    prim = doc["meshes"][0]["primitives"][0]
    assert {"TEXCOORD_0", "TANGENT", "NORMAL"} <= set(prim["attributes"])
    mat = doc["materials"][prim["material"]]
    assert "normalTexture" in mat


def test_detail_without_a_map_warns(project: Project) -> None:
    text = MODEL.replace("normal_map: 256\n", "")
    result = lint_paths(project, [write_model(project, text)])
    assert any(f.rule == "W121" for f in result.findings)


@pytest.mark.parametrize("size", ["100", "true", "8192"])
def test_bad_normal_map(project: Project, size: str) -> None:
    _, _, findings = load(project, MODEL.replace("normal_map: 256", f"normal_map: {size}"))
    assert any(f.rule == "E003" and f.where == "normal_map" for f in findings)


def test_all_detail_is_an_error(project: Project) -> None:
    text = MODEL.replace("    color: red\n", "    color: red\n    detail: true\n", 1)
    _, _, findings = load(project, text)
    assert any(f.rule == "E009" for f in findings)


def test_godot_scene_reads_the_map(project: Project) -> None:
    from kiln.godot import model_scene
    from kiln.style import load_style

    style, _ = load_style("toon")
    assert style is not None
    plain = model_scene("thing", "res://thing.glb", style)
    mapped = model_scene("thing", "res://thing.glb", style, normal_map=True)
    assert "NORMAL_MAP" not in plain and "NORMAL_MAP = texture(normal_texture, UV)" in mapped
    assert "normal_texture" in mapped.split("GDScript_apply")[1]  # the script hands the glb's map to the shader


def test_green_is_up_the_image() -> None:
    """Independent of the bake's own frame code: a surface leaning towards -v (up the image) gives green > 0.5, towards
    +u red > 0.5, on a flat mesh whose field leans a known way."""
    xs = np.linspace(-0.5, 0.5, 9)
    v = np.array([[x, 0.0, z] for z in xs for x in xs])
    f = np.array([[r * 9 + c, (r + 1) * 9 + c, r * 9 + c + 1] for r in range(8) for c in range(8)]
                 + [[r * 9 + c + 1, (r + 1) * 9 + c, (r + 1) * 9 + c + 1] for r in range(8) for c in range(8)])
    n = np.tile([0.0, 1.0, 0.0], (len(f), 3, 1))
    tilt = np.array([0.08, 1.0, -0.06]) / np.linalg.norm([0.08, 1.0, -0.06])  # leaning on both axes, a plane through the origin
    axis = np.cross([0.0, 1.0, 0.0], tilt)
    turn = axis_rotation(axis, float(np.degrees(np.arccos(tilt[1]))))
    field = Field([Geometry("box", {"size": [3.0, 1.0, 3.0], "round": 0.0}, at=-0.5 * tilt, rotation=turn)], margin=0.05)
    assert (field.gradient(np.zeros((1, 3)), 0.001)[0] * tilt).sum() > 0.99  # the field leans the way we think
    b = bk.bake([field], np.zeros(len(f), np.int64), v, f, n, 256, 0.05)  # (the plane stays within a cell of the mesh)
    img = np.asarray(Image.open(io.BytesIO(b.png))).astype(float) / 255 * 2 - 1
    face, texel, _ = bk._texels(b.uv, b.width, b.height)
    p = v[f]
    uv = b.uv
    # per face, from positions and UVs alone: which way +u and -v (up the image) run in the world
    d1, d2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    e1, e2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    dpdu = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / det[:, None]
    dpdv = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / det[:, None]
    local = img.reshape(-1, 3)[texel]
    expect_red = np.sign((dpdu[face] * tilt).sum(1))
    expect_green = np.sign((-dpdv[face] * tilt).sum(1))
    big = np.abs((dpdu[face] * tilt).sum(1)) > 0.02
    assert (np.sign(local[big, 0]) == expect_red[big]).mean() > 0.95
    big = np.abs((-dpdv[face] * tilt).sum(1)) > 0.02
    assert (np.sign(local[big, 1]) == expect_green[big]).mean() > 0.95


def test_glb_carries_the_bake_uvs_and_tangents(project: Project) -> None:
    from kiln.vendor.gltf import read_accessor

    write_model(project, MODEL)
    result = build(project)
    built = lint_paths(project, [project.models_dir / "thing.kiln.yaml"]).built["thing"]
    doc, binary = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    uv = np.concatenate([read_accessor(doc, binary, pr["attributes"]["TEXCOORD_0"]) for pr in doc["meshes"][0]["primitives"]])
    tan = np.concatenate([read_accessor(doc, binary, pr["attributes"]["TANGENT"]) for pr in doc["meshes"][0]["primitives"]])
    baked = {tuple(np.round(x, 4)) for x in built.bake.uv.reshape(-1, 2)}
    assert {tuple(np.round(x, 4)) for x in uv.astype(float)} <= baked
    assert set(np.unique(tan[:, 3])) <= {-1.0, 1.0} and result.manifest["models"]["thing"]["normal_map"]["size"][0] > 0


def test_detail_renumbering_keeps_cuts_and_blends(project: Project) -> None:
    text = """\
name: thing
normal_map: 256
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    id: body
    color: red
  - torus: { at: [0, 0.3, 0], radius: 0.3, thickness: 0.01 }
    cut: true
    detail: true
  - capsule: { from: [0, 0.55, 0], to: [0, 0.8, 0], radius: 0.04 }
    color: red
    blend: 0.03
    blend_to: body
  - sphere: { at: [0.3, 0.3, 0], radius: 0.05 }
    cut: body
"""
    model, _, findings = load(project, text)
    assert model is not None, findings
    assert len(model.parts) == 3 and model.bake_index == [0, 2, 3]
    assert model.parts[1].geometry.blend_to == frozenset({0}) and model.parts[2].geometry.cut_only == frozenset({0})
    assert model.bake_parts is not None and model.bake_parts[2].blend_to == frozenset({0})


def test_detail_parts_are_not_targets(project: Project) -> None:
    text = MODEL.replace("    cut: true\n    blend: 0.004\n    detail: true\n", "    id: fur\n    color: red\n    detail: true\n") + \
        "  - capsule: { from: [0, 0.55, 0], to: [0, 0.8, 0], radius: 0.04 }\n    color: red\n    blend: 0.03\n    blend_to: fur\n"
    _, _, findings = load(project, text)
    assert any(f.rule == "E003" and f.where == "parts[2].blend_to" for f in findings), findings


def test_atlas_and_normal_map_is_a_lint_error(project: Project) -> None:
    cfg = project.root / "kiln.toml"
    cfg.write_text(cfg.read_text() + "\natlas = true\n")
    from kiln.project import load_project

    proj = load_project(project.root)
    result = lint_paths(proj, [write_model(proj, MODEL)])
    assert any(f.rule == "E003" and f.where == "normal_map" for f in result.findings)


def test_lods_bake_smaller_maps(project: Project) -> None:
    write_model(project, MODEL.replace("normal_map: 256\n", "normal_map: 512\nbudget: 3000\nlod: [800]\n"))
    result = build(project)
    assert not result.errors, result.findings
    assert (project.output_dir / "models" / "thing.lod1.normal.png").is_file()
    w = Image.open(project.output_dir / "models" / "thing.normal.png").width
    w1 = Image.open(project.output_dir / "models" / "thing.lod1.normal.png").width
    assert w1 < w


def test_detail_finer_than_a_texel_blurs_instead_of_speckling(project: Project) -> None:
    """#125: each texel is filtered (four samples, a gradient step of half a texel): bumps far smaller than a texel
    average out instead of aliasing into speckle (unfiltered, this map's tilt had a std of 0.10)."""
    text = "name: thing\nnormal_map: 256\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n    noise: { amount: 0.001, scale: 0.002 }\n"
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    assert built.bake is not None
    tilt = np.asarray(Image.open(io.BytesIO(built.bake.png))).astype(float)[:, :, :2] / 255 * 2 - 1
    assert float(tilt.std()) < 0.06


def test_normal_strength_scales_the_tilt(project: Project) -> None:
    text = ("name: thing\nnormal_map: 256\n{strength}parts:\n  - sphere: {{ at: [0, 0.3, 0], radius: 0.3 }}\n    color: red\n"
            "  - box: {{ at: [0, 0.3, 0.3], size: [0.02, 0.4, 0.02] }}\n    cut: true\n    detail: true\n")  # fmt: skip
    tilts = []
    for strength in ("", "normal_strength: 0.5\n"):
        built = lint_paths(project, [write_model(project, text.format(strength=strength))]).built["thing"]
        assert built.bake is not None
        tilts.append(np.abs(np.asarray(Image.open(io.BytesIO(built.bake.png))).astype(float)[:, :, :2] - 128).sum(axis=2))
    groove = tilts[0] > 20  # where the groove tilts the map
    assert groove.sum() > 20 and tilts[1][groove].mean() < tilts[0][groove].mean() * 0.75
    _, _, findings = load(project, text.format(strength="normal_strength: 9\n"))
    assert any(f.where == "normal_strength" for f in findings)
    _, _, findings = load(project, text.format(strength="normal_strength: 0.5\n").replace("normal_map: 256\n", "").replace("    detail: true\n", ""))
    assert any(f.where == "normal_strength" for f in findings)
