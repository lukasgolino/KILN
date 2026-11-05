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
from kiln.sdf import Field, Geometry
from kiln.vendor.gltf import read_glb

pytestmark = pytest.mark.skipif(not bk.available(), reason="xatlas not installed (kiln[bake])")

BALL = Field([Geometry("sphere", {"radius": 0.3})], margin=0.03)
GROOVED = Field([Geometry("sphere", {"radius": 0.3}), Geometry("torus", {"radius": 0.3, "thickness": 0.01}, op="cut", blend=0.004)], margin=0.03)


def ball_mesh() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = decimate(BALL, dual_contour(BALL, 0.02), 3000, 0.02)
    n = m.vertices / np.linalg.norm(m.vertices, axis=1, keepdims=True)
    return m.vertices, m.faces, n[m.faces]


def decode(b: bk.Bake, vertices: np.ndarray, faces: np.ndarray, normals: np.ndarray, size: int) -> tuple[np.ndarray, np.ndarray]:
    """World normals read back from the map at texel centres (as an engine does), and the points under them."""
    img = np.asarray(Image.open(io.BytesIO(b.png))).astype(float) / 255 * 2 - 1
    face, texel, bary = bk._texels(b.uv, size)
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
    b = bk.bake(GROOVED, v, f, n, 256, 0.02)
    world, p = decode(b, v, f, n, 256)
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
    uv = bk.unwrap(v, f, 256)
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
    a, b = bk.bake(GROOVED, v, f, n, 128, 0.02), bk.bake(GROOVED, v, f, n, 128, 0.02)
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
    assert entry["normal_map"] == 256
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
