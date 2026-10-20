"""`kiln build`: output files, manifest, variants, LODs, stale files, Godot scenes, determinism."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from conftest import arms_text, make_project, sphere_text, write_model
from kiln.build import MANIFEST, build
from kiln.gltf_check import check_glb
from kiln.godot import find_godot_binary, look_scene, model_scene, verify
from kiln.project import Project, load_project
from kiln.style import load_style

GODOT_CONFIG = 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "game/assets/kiln"\nexport = ["glb", "godot"]\n'
PROJECT_GODOT = """\
config_version=5

[application]
config/name="kiln test"

[rendering]
renderer/rendering_method="mobile"
"""


def rich_model() -> str:
    return arms_text("hero") + "variants:\n  blue: { swap: { red: blue } }\nlod: [300, 100000]\ndescription: a hero\ntags: [crew]\n"


def test_build_writes_glbs_and_manifest(project: Project) -> None:
    write_model(project, rich_model(), "hero")
    write_model(project, sphere_text("ball"), "ball")
    result = build(project)
    assert result.errors == [] and result.models == ["ball", "hero"]
    out = project.output_dir
    for rel in ("models/ball.glb", "models/hero.glb", "models/hero.blue.glb", "models/hero.lod1.glb", MANIFEST):
        assert (out / rel).is_file(), rel
    assert not (out / "models" / "hero.lod2.glb").exists()  # a LOD bigger than the model is skipped
    for glb in (out / "models").glob("*.glb"):
        assert check_glb(glb.read_bytes()) == [], glb
    manifest = json.loads((out / MANIFEST).read_text())
    assert manifest == result.manifest
    assert (manifest["units"], manifest["up"], manifest["front"]) == ("metres", "+Y", "+Z")
    assert manifest["files"] == sorted(manifest["files"][:-1]) + [MANIFEST]
    hero = manifest["models"]["hero"]
    assert hero["glb"] == "models/hero.glb" and hero["description"] == "a hero" and hero["tags"] == ["crew"]
    assert hero["class"] == "character" and hero["style"] == "fast" and hero["skin"] == "rigid"
    assert set(hero["parts"]) == {"root", "arm_l", "arm_r"}
    arm = hero["parts"]["arm_r"]
    assert {k: arm[k] for k in ("parent", "pivot", "meta", "separate", "node_path")} == {
        "parent": "root", "pivot": [-0.3, 0.6, 0.0], "meta": {}, "separate": False, "node_path": "root/arm_r"}
    assert arm["aabb"]["max"][0] < -0.25 and arm["aabb"]["min"][1] < 0.6 < arm["aabb"]["max"][1]  # the left arm's box, model space
    assert hero["animations"]["wave"] == {"gltf_name": "wave-loop", "fps": 8.0, "frames": 4, "loop": True, "interpolation": "linear", "duration": 0.5,
                                          "start": {"arm_r": {"offset": [0.0, 0.0, 0.0], "rotate": [0.0, 0.0, -150.0]}}}  # the first frame's pose
    assert hero["animations"]["hold"]["gltf_name"] == "hold"
    lo, hi = hero["bounds"]["min"], hero["bounds"]["max"]
    assert lo[1] == pytest.approx(0.0, abs=0.03) and hi[1] == pytest.approx(1.0, abs=0.03)
    assert hero["size"] == pytest.approx([h - low for h, low in zip(hi, lo, strict=True)], abs=1e-4)
    assert hero["variants"] == {"blue": {"glb": "models/hero.blue.glb", "swap": {"#e8413c": "#2f6fd0"}}}
    assert len(hero["lods"]) == 1 and hero["lods"][0]["glb"] == "models/hero.lod1.glb"
    assert hero["lods"][0]["triangles"] < hero["triangles"]
    assert hero["colors"] == ["#2f6fd0", "#e8413c"]
    assert "source" not in hero and "godot_scene" not in hero and "looks" not in manifest


def test_build_stops_on_errors(project: Project) -> None:
    write_model(project, sphere_text().replace("color: red", "color: mauve"))
    result = build(project)
    assert [f.rule for f in result.errors] == ["E004"]
    assert not project.output_dir.exists()


def test_second_build_rewrites_nothing(project: Project) -> None:
    write_model(project, rich_model(), "hero")
    first = build(project)
    second = build(project)
    assert first.written and second.written == [] and second.removed == []
    assert second.unchanged == len(first.written)


def test_only_changed_files_are_rewritten(project: Project) -> None:
    write_model(project, sphere_text("a"), "a")
    write_model(project, sphere_text("b"), "b")
    build(project)
    write_model(project, sphere_text("b").replace("radius: 0.3", "radius: 0.25"), "b")
    result = build(project)
    out = project.output_dir
    assert sorted(result.written) == sorted([out / "models" / "b.glb", out / MANIFEST])


def test_stale_files_are_removed(project: Project) -> None:
    write_model(project, rich_model(), "hero")
    write_model(project, sphere_text("ball"), "ball")
    build(project)
    out = project.output_dir
    sidecar = out / "models" / "ball.glb.import"
    sidecar.write_text("[remap]\n")
    (out / "models" / "mine.glb").write_bytes(b"not ours")
    (project.models_dir / "ball.kiln.yaml").unlink()
    write_model(project, rich_model().replace("variants:\n  blue: { swap: { red: blue } }\n", ""), "hero")
    result = build(project)
    assert sorted(p.name for p in result.removed) == ["ball.glb", "hero.blue.glb"]
    assert not sidecar.exists()
    assert (out / "models" / "mine.glb").exists()  # never listed in a manifest: not ours to delete
    assert "ball" not in json.loads((out / MANIFEST).read_text())["models"]


def test_build_is_deterministic(tmp_path: Path) -> None:
    a = make_project(tmp_path / "a")
    b = make_project(tmp_path / "b")
    for p in (a, b):
        write_model(p, rich_model(), "hero")
        build(p)
    files_a = sorted(p.relative_to(a.output_dir) for p in a.output_dir.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b.output_dir) for p in b.output_dir.rglob("*") if p.is_file())
    assert files_a == files_b
    for rel in files_a:
        assert (a.output_dir / rel).read_bytes() == (b.output_dir / rel).read_bytes(), rel
    # a cold build (no cache) gives the same bytes as a cached one
    glb = (a.output_dir / "models" / "hero.glb").read_bytes()
    shutil.rmtree(a.root / ".kiln-cache")
    (a.output_dir / "models" / "hero.glb").unlink()
    build(a)
    assert (a.output_dir / "models" / "hero.glb").read_bytes() == glb


def test_godot_export_needs_a_godot_project(tmp_path: Path) -> None:
    project = make_project(tmp_path, GODOT_CONFIG)
    write_model(project, sphere_text())
    result = build(project)
    assert [f.rule for f in result.errors] == ["E000"]
    assert "project.godot" in result.errors[0].message


def godot_project(tmp_path: Path) -> Project:
    project = make_project(tmp_path, GODOT_CONFIG)
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text(PROJECT_GODOT)
    return project


def test_godot_export_writes_scenes_and_looks(tmp_path: Path) -> None:
    project = godot_project(tmp_path)
    write_model(project, rich_model(), "hero")
    result = build(project)
    assert result.errors == []
    assert result.godot_root == (tmp_path / "game").resolve()
    out = project.output_dir
    scene = (out / "models" / "hero.tscn").read_text()
    assert 'path="res://assets/kiln/models/hero.glb"' in scene
    assert 'metadata/kiln_style = "fast"' in scene
    look = (out / "looks" / "fast.tscn").read_text()
    assert "WorldEnvironment" in look and "DirectionalLight3D" in look
    manifest = result.manifest
    assert manifest["looks"] == {"fast": "res://assets/kiln/looks/fast.tscn"}
    entry = manifest["models"]["hero"]
    assert entry["godot_scene"] == "res://assets/kiln/models/hero.tscn"
    assert entry["glb_res"] == "res://assets/kiln/models/hero.glb"


def test_model_and_look_scenes_follow_the_style() -> None:
    toon, _ = load_style("toon")
    assert toon is not None
    scene = model_scene("hero", "res://hero.glb", toon)
    assert scene.startswith("[gd_scene format=3]")
    assert 'shader_kind = "toon"' in scene and "outline = 0.012" in scene and '"skin": 0.2' in scene
    look = look_scene(toon)
    assert "tonemap_mode = 0" in look and "ssao_enabled = false" in look and "fog_enabled" not in look
    diorama, _ = load_style("diorama")
    assert diorama is not None
    assert "fog_enabled = true" in look_scene(diorama)


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_loads_everything(tmp_path: Path) -> None:
    project = godot_project(tmp_path)
    write_model(project, rich_model(), "hero")
    write_model(project, arms_text("blob", skin="soft"), "blob")
    write_model(project, sphere_text("ball").replace("color: red", "color: red\n    material: glow"), "ball")
    result = build(project)
    assert result.errors == []
    godot = find_godot_binary()
    assert godot is not None and result.godot_root is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
    assert check.models == 3


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_loads_a_toon_style(tmp_path: Path) -> None:
    project = godot_project(tmp_path)
    (tmp_path / "styles" / "fast.style.toml").write_text((tmp_path / "styles" / "fast.style.toml").read_text().replace('"soft_toy"', '"toon"'))
    write_model(project, arms_text("hero"), "hero")
    result = build(load_project(project.root))
    assert result.errors == [] and result.godot_root is not None
    godot = find_godot_binary()
    assert godot is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]


@pytest.mark.slow
def test_builds_do_not_depend_on_the_hash_seed(tmp_path: Path) -> None:
    """Python randomises str hashes per process: output must not depend on set/dict order of names."""
    import os
    import shutil
    import subprocess
    import sys

    demo = Path(__file__).parent.parent / "examples" / "demo"
    outputs = []
    for seed in ("1", "2"):
        root = tmp_path / seed
        shutil.copytree(demo, root, ignore=shutil.ignore_patterns("previews", ".kiln-cache"))
        config = (root / "kiln.toml").read_text().replace('output_dir = "../godot/assets/kiln"', 'output_dir = "out"').replace('export = ["glb", "godot"]', 'export = ["glb"]')
        (root / "kiln.toml").write_text(config)
        keep = {"passenger.kiln.yaml", "pilot.kiln.yaml"}
        for path in (root / "models").glob("*.kiln.yaml"):
            if path.name not in keep:
                path.unlink()
        env = {**os.environ, "PYTHONHASHSEED": seed}
        run = subprocess.run([sys.executable, "-m", "kiln", "build"], cwd=root, env=env, capture_output=True, text=True, timeout=600)
        assert run.returncode == 0, run.stdout + run.stderr
        outputs.append({p.name: p.read_bytes() for p in sorted((root / "out" / "models").glob("*.glb"))})
    assert outputs[0] == outputs[1]


@pytest.mark.slow
def test_demo_meshes_stay_on_their_surface() -> None:
    """Every demo model's mesh lies on its shapes (decimation once threw thin parts' vertices metres away)."""
    from kiln.builder import build_model, field_of

    project = load_project(Path(__file__).parent.parent / "examples" / "demo")
    palette, _ = project.palette()
    for name in ("archer", "pilot"):
        model, style, _ = project.load(project.models_dir / f"{name}.kiln.yaml")
        assert model and style
        built = build_model(model, style, None, palette)
        field = field_of(model, built.step)
        points = built.painted.vertices[np.unique(built.painted.faces)]
        # each piece (the body, a `separate` cap) on its own surface
        separate = {pid for pid, e in model.rig.items() if e.separate}
        adding = [i for i, p in enumerate(model.parts) if p.geometry.op == "add"]
        pieces = [[i for i in adding if model.parts[i].id not in separate]] + [[i for i in adding if model.parts[i].id == s] for s in separate]
        distance = np.min([np.abs(field.only(piece).distance(points)) for piece in pieces if piece], axis=0)
        assert distance.max() < built.step * 2, name
        assert len(built.painted.faces) <= style.budget(model.cls) * 1.05, name
