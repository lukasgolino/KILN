"""Optional Blender imports (.fbx/.blend/.obj -> glb): findings without Blender always run; the conversions need a
Blender 4.x binary (BLENDER=/path or `blender` on PATH) and skip without one (CI has none)."""

from __future__ import annotations

import json
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from conftest import ok_model, run_json
from kiln import blender
from kiln.build import build
from kiln.importer import read_mesh
from kiln.project import Project
from kiln.retarget import clip_names
from kiln.vendor.gltf import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, Document, read_glb

HAVE_BLENDER = int((blender.blender_version(blender.find_blender() or "") or "0").split(".")[0]) >= blender.MIN_MAJOR if blender.find_blender() else False
needs_blender = pytest.mark.skipif(not HAVE_BLENDER, reason="needs a Blender 4.x binary (BLENDER=/path)")

# a square pyramid, 2 wide and 2 high, standing on y = 0 (.obj is +Y up like glTF)
PYRAMID_V = np.array([[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1], [0, 2, 0]], float)
PYRAMID_F = np.array([[0, 1, 2], [0, 2, 3], [0, 4, 1], [1, 4, 2], [2, 4, 3], [3, 4, 0]])
OBJ = "".join(f"v {x:g} {y:g} {z:g}\n" for x, y, z in PYRAMID_V) + "".join(f"f {a + 1} {b + 1} {c + 1}\n" for a, b, c in PYRAMID_F)

SOURCE = """\
name: thing
class: prop
source: {{ file: imports/{file}, licence: CC0-1.0, author: Someone, url: "https://example.com" }}
process: {{ scale: 1.0, recolor: keep }}
"""

# run inside Blender: a 2 m cube with a red vertex colour, skinned to a one-bone armature with a "Wave" action;
# saved as .blend and exported as .fbx
MAKE = r"""
import sys
import bpy

blend, fbx = sys.argv[sys.argv.index("--") + 1 :][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
cube = bpy.context.object
cube.name = "Cube"
attr = cube.data.color_attributes.new("Col", "FLOAT_COLOR", "POINT")
for d in attr.data:
    d.color = (0.8, 0.1, 0.1, 1.0)
cube.data.color_attributes.active_color = attr
bpy.ops.object.armature_add(location=(0, 0, 0))
rig = bpy.context.object
rig.name = "Rig"
group = cube.vertex_groups.new(name="Bone")
group.add(list(range(len(cube.data.vertices))), 1.0, "REPLACE")
cube.parent = rig
cube.modifiers.new("Armature", "ARMATURE").object = rig
rig.animation_data_create()
action = bpy.data.actions.new("Wave")
rig.animation_data.action = action
bone = rig.pose.bones["Bone"]
bone.rotation_mode = "XYZ"
for frame, angle in ((1, 0.0), (10, 0.5), (20, 0.0)):
    bone.rotation_euler = (0.0, 0.0, angle)
    bone.keyframe_insert("rotation_euler", frame=frame)
bpy.ops.wm.save_as_mainfile(filepath=blend)
bpy.ops.export_scene.fbx(filepath=fbx)
"""


def pyramid_glb(path: Path) -> Path:
    doc = Document("test")
    pos = doc.accessor(PYRAMID_V.astype(np.float32), target=ARRAY_BUFFER, bounds=True)
    idx = doc.accessor(PYRAMID_F.reshape(-1).astype(np.uint32), target=ELEMENT_ARRAY_BUFFER)
    doc.add("meshes", {"primitives": [{"attributes": {"POSITION": pos}, "indices": idx}]})
    doc.add("nodes", {"mesh": 0})
    doc.json["scenes"] = [{"nodes": [0]}]
    doc.json["scene"] = 0
    path.write_bytes(doc.glb())
    return path


def triangles(path: Path) -> list[Any]:
    """The mesh's triangles in world space, each starting at its smallest corner (winding kept), sorted."""
    v, f, _, _ = read_mesh(path)
    out = []
    for tri in np.round(v[f], 5).tolist():
        k = tri.index(min(tri))
        out.append(tri[k:] + tri[:k])
    return sorted(out)


def area_and_volume(path: Path) -> tuple[float, float]:
    v, f, _, _ = read_mesh(path)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    return float(np.linalg.norm(np.cross(b - a, c - a), axis=1).sum() / 2), float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)


@pytest.fixture(autouse=True)
def fresh_versions() -> Iterator[None]:
    blender.blender_version.cache_clear()
    yield
    blender.blender_version.cache_clear()


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """cube.blend and cube.fbx, made by Blender itself (nothing binary committed)."""
    if not HAVE_BLENDER:
        pytest.skip("needs a Blender 4.x binary (BLENDER=/path)")
    folder = tmp_path_factory.mktemp("made")
    run = subprocess.run([blender.find_blender() or "", "-b", "--factory-startup", "--python-exit-code", "1", "--python-expr", MAKE, "--",
                          str(folder / "cube.blend"), str(folder / "cube.fbx")], capture_output=True, text=True, timeout=600, check=False)  # fmt: skip
    assert run.returncode == 0, run.stderr[-2000:]
    return {"blend": folder / "cube.blend", "fbx": folder / "cube.fbx"}


def fake_blender(tmp_path: Path, version: str, fail: str = "") -> str:
    """A stand-in `blender`: prints its version; converting fails with `fail` on stderr."""
    script = tmp_path / "fake-blender"
    script.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "Blender {version}"; exit 0; fi\n'
                      f'echo "Read prefs"; echo "line 1\\nline 2\\n{fail}" >&2; exit 1\n')  # fmt: skip
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


# --- without Blender (CI) ---


def test_no_blender_is_a_finding(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("BLENDER", raising=False)
    monkeypatch.setattr("kiln.blender.shutil.which", lambda name: None)
    (project.root / "imports" / "pyramid.obj").write_text(OBJ)
    path = project.models_dir / "thing.kiln.yaml"
    path.write_text(SOURCE.format(file="pyramid.obj"))
    model, _, findings = project.load(path)
    assert model is None or model.source is None
    [finding] = [f for f in findings if f.rule == "E010"]
    assert finding.where == "source.file" and "BLENDER=" in finding.message and "Blender 4.x" in finding.message
    monkeypatch.chdir(project.root)
    code, result = run_json(["import", str(project.root / "imports" / "pyramid.obj"), "--licence", "CC0-1.0", "--force"], capsys)
    assert code == 1 and "BLENDER=" in result["findings"][0]["message"]


def test_old_blender_is_a_finding(project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLENDER", fake_blender(tmp_path, "3.6.5"))
    (project.root / "imports" / "pyramid.obj").write_text(OBJ)
    path = project.models_dir / "thing.kiln.yaml"
    path.write_text(SOURCE.format(file="pyramid.obj"))
    _, _, findings = project.load(path)
    [finding] = [f for f in findings if f.rule == "E010"]
    assert "Blender 3.6.5 is too old" in finding.message and "BLENDER=" in finding.message


def test_blender_failure_shows_its_stderr(project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BLENDER", fake_blender(tmp_path, "4.2.3", "Error: File format is not supported"))
    (project.root / "imports" / "pyramid.obj").write_text(OBJ)
    path = project.models_dir / "thing.kiln.yaml"
    path.write_text(SOURCE.format(file="pyramid.obj"))
    _, _, findings = project.load(path)
    [finding] = [f for f in findings if f.rule == "E010"]
    assert "couldn't convert" in finding.message and "File format is not supported" in finding.message and "line 2" in finding.message
    assert not list((project.root / ".kiln-cache" / "blender").rglob("*.glb"))  # nothing half-written is cached


def test_glb_imports_never_look_for_blender(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(blender, "converted", lambda *a: pytest.fail("Blender run for a glb"))
    pyramid_glb(project.root / "imports" / "pyramid.glb")
    model, _ = ok_model(project, SOURCE.format(file="pyramid.glb"), "thing")
    assert model.source is not None and model.source.original is None


def test_cache_key_covers_obj_materials(tmp_path: Path) -> None:
    obj = tmp_path / "a.obj"
    obj.write_text("mtllib a.mtl\n" + OBJ)
    (tmp_path / "a.mtl").write_text("newmtl red\nKd 1 0 0\nmap_Kd tex.png\n")
    (tmp_path / "tex.png").write_bytes(b"one")
    key = blender.cache_key(obj, "4.2.3")
    assert blender.cache_key(obj, "4.2.3") == key and blender.cache_key(obj, "4.3.0") != key
    (tmp_path / "tex.png").write_bytes(b"two")
    assert blender.cache_key(obj, "4.2.3") != key


# --- with Blender ---


@needs_blender
def test_obj_imports_like_the_same_glb(project: Project, tmp_path: Path) -> None:
    obj = tmp_path / "pyramid.obj"
    obj.write_text(OBJ)
    glb = blender.converted(obj, tmp_path / "cache")
    assert glb.name == "pyramid.glb" and glb.parent.parent == tmp_path / "cache" / "blender"
    assert triangles(glb) == triangles(pyramid_glb(tmp_path / "pyramid.glb"))
    again = blender.converted(obj, tmp_path / "cache2")  # Blender's export is byte-stable run to run
    assert again.read_bytes() == glb.read_bytes()


@needs_blender
@pytest.mark.parametrize("kind", ["fbx", "blend"])
def test_fbx_and_blend_import_like_the_same_glb(made: dict[str, Path], tmp_path: Path, kind: str) -> None:
    glb = blender.converted(made[kind], tmp_path / "cache")
    v, f, cols, _ = read_mesh(glb)
    corners = np.unique(np.round(v, 5), axis=0)
    expected = np.array([[x, y, z] for x in (-1, 1) for y in (0, 2) for z in (-1, 1)], float)  # +Z up in Blender -> +Y up
    np.testing.assert_allclose(corners, expected, atol=1e-5)
    area, volume = area_and_volume(glb)
    assert area == pytest.approx(24.0) and volume == pytest.approx(8.0)  # closed, facing out
    doc, _ = read_glb(glb.read_bytes())
    assert doc.get("skins") and "COLOR_0" in doc["meshes"][0]["primitives"][0]["attributes"]
    assert [n for n in clip_names(glb) if n.endswith("Wave")]  # FBX round trips name it Rig|Rig|Wave
    srgb = [1.055 * c ** (1 / 2.4) - 0.055 for c in (0.8, 0.1, 0.1)]  # Blender's float colours are linear
    np.testing.assert_allclose(cols, np.tile(srgb, (len(f), 1)), atol=0.01)  # the vertex colour came through


@needs_blender
def test_model_source_fbx_builds_credits_and_caches(project: Project, made: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    (project.root / "imports" / "cube.fbx").write_bytes(made["fbx"].read_bytes())
    (project.models_dir / "thing.kiln.yaml").write_text(SOURCE.format(file="cube.fbx"))
    result = build(project)
    assert result.errors == []
    assert result.manifest["models"]["thing"]["source"]["file"] == "cube.fbx"
    assert "**thing**: cube.fbx by Someone" in (project.output_dir / "CREDITS.md").read_text()
    [out] = list(project.output_dir.rglob("thing.glb"))
    first = out.read_bytes()
    runs: list[list[str]] = []
    real = subprocess.run

    def counting(cmd: list[str], **kw: Any) -> Any:
        runs.append(cmd)
        return real(cmd, **kw)

    monkeypatch.setattr("kiln.blender.subprocess.run", counting)
    result = build(project)
    assert result.errors == [] and not [c for c in runs if "--python-expr" in c]  # cache hit: Blender not run again
    assert out.read_bytes() == first


@needs_blender
def test_kiln_import_fbx_writes_a_glb(in_project: Project, made: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["import", str(made["fbx"]), "--licence", "CC0-1.0", "--author", "Someone", "--height", "1.0"], capsys)
    assert code == 0, result
    assert result["file"] == "imports/cube.glb" and (in_project.root / "imports" / "cube.glb").is_file()
    assert not (in_project.root / "imports" / "cube.fbx").exists()
    code, result = run_json(["lint", "cube"], capsys)
    assert code == 0, result["findings"]
    code, result = run_json(["credits"], capsys)
    assert result["credits"][0]["file"] == "cube.glb" and result["credits"][0]["licence"] == "CC0-1.0"
    manifest_dir = in_project.output_dir
    code, _ = run_json(["build"], capsys)
    assert code == 0 and json.loads((manifest_dir / "manifest.json").read_text())["models"]["cube"]["size"][1] == pytest.approx(1.0)


def test_no_blender_for_an_animation_import(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_retarget import HERO

    monkeypatch.delenv("BLENDER", raising=False)
    monkeypatch.setattr("kiln.blender.shutil.which", lambda name: None)
    (project.root / "imports" / "clips.fbx").write_bytes(b"not read")
    path = project.models_dir / "thing.kiln.yaml"
    path.write_text(HERO.split("animations:\n")[0] + "animations:\n  wave: { import: imports/clips.fbx, clip: Wave }\n")
    _, _, findings = project.load(path)
    [finding] = [f for f in findings if f.rule == "E008"]
    assert finding.where == "animations.wave.import" and "BLENDER=" in finding.message


@needs_blender
def test_fit_to_a_blend(project: Project, made: dict[str, Path]) -> None:
    (project.root / "imports" / "cube.blend").write_bytes(made["blend"].read_bytes())
    text = "name: thing\nclass: prop\nfit_to: { file: imports/cube.blend, bone: Bone }\nparts:\n  - sphere: { at: [0, 1, 0], radius: 0.3 }\n    color: grey\n"
    model, _ = ok_model(project, text, "thing")
    assert model.fit_to is not None and model.fit_to[0].name == "cube.glb" and ".kiln-cache" in model.fit_to[0].parts
