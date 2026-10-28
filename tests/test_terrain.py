"""Terrains (#15): `terrain:` models (height shapes + splat layers), the Heightfield API, chunked LOD meshes with
skirts, the splat map, the Godot scene with its HeightMapShape3D, lint, preview and build integration."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from conftest import make_project, ok_model, run_json, sphere_text, write_model

from kiln.build import build
from kiln.godot import find_godot_binary, verify
from kiln.lint import lint_project
from kiln.project import Project
from kiln.terrain import NO_PATH, Heightfield, compute, fbm, meshes, skirt_depth, splat_png
from kiln.vendor.gltf import read_accessor, read_glb, validate

GODOT_CONFIG = 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "game/assets/kiln"\nexport = ["glb", "godot"]\n'
PROJECT_GODOT = 'config_version=5\n\n[application]\nconfig/name="kiln test"\n\n[rendering]\nrenderer/rendering_method="mobile"\n'

TERRAIN = """\
name: land
terrain:
  size: [64, 32]
  cell: 0.5
  chunk: 16
  lod: [30, 60]
  seed: 2
  shapes:
    - hill: { at: [-16, 0], radius: 10, height: 6 }
    - plateau: { at: [14, 0], radius: 5, edge: 2, height: 3, blend: max }
    - path: { points: [[-32, -12], [0, -10], [32, -12]], width: 3, edge: 2, depth: 0.3 }
  splat:
    - grass: { color: green }
    - dirt: { color: wood, path: { within: 2 } }
    - rock: { color: grey, slope: { above: 30, fade: 4 } }
"""


def field_of(project: Project, text: str = TERRAIN) -> Heightfield:
    model, _ = ok_model(project, text, "land")
    assert model.terrain is not None
    return compute(model.terrain)


# --- notation ---------------------------------------------------------------------------------------------------------


def test_parses_a_terrain_model(project: Project) -> None:
    model, _ = ok_model(project, TERRAIN, "land")
    t = model.terrain
    assert t is not None and model.parts == [] and model.cls == "terrain"
    assert t.size == (64.0, 32.0) and t.cells == (128, 64) and t.chunks == (4, 2) and t.chunk_cells == 32 and t.lod == (30.0, 60.0)
    assert [s.kind for s in t.shapes] == ["hill", "plateau", "path"] and t.shapes[1].blend == "max"
    assert [layer.name for layer in t.layers] == ["grass", "dirt", "rock"] and t.layers[2].color == "#8a93a3"
    assert t.layers[2].rules[0].kind == "slope" and t.layers[2].rules[0].above == 30


@pytest.mark.parametrize(("change", "where", "text"), [
    (("  cell: 0.5\n", "  cell: 0.7\n"), "terrain.cell", "whole number of 0.7 m cells"),
    (("  chunk: 16\n", "  chunk: 20\n"), "terrain.chunk", "whole number of 20 m chunks"),
    (("  chunk: 16\n", "  chunk: 1\n"), "terrain.chunk", "cell x 2^2"),
    (("  lod: [30, 60]\n", "  lod: [60, 30]\n"), "terrain.lod", "increasing"),
    (("  seed: 2\n", "  seed: 2\n  colour: red\n"), "terrain.colour", "unknown field"),
    (("radius: 10, height: 6", "radius: 10"), "terrain.shapes[0].hill.height", "required"),
    (("radius: 10, height: 6", "radius: 10, height: 6, width: 3"), "terrain.shapes[0].hill.width", "unknown field"),
    (("blend: max", "blend: blur"), "terrain.shapes[1].plateau.blend", "blend is"),
    (("[[-32, -12], [0, -10], [32, -12]]", "[[0, 0]]"), "terrain.shapes[2].path.points", "2+ different"),
    (("- grass: { color: green }", "- grass: { color: green, slope: { above: 3 } }"), "terrain.splat[0].grass.slope", "first layer"),
    (("slope: { above: 30, fade: 4 }", "slope: { above: 30, below: 10 }"), "terrain.splat[2].rock.slope", "below must be more"),
    (("color: wood", "color: mauve"), "terrain.splat[1].dirt.color", "unknown colour"),
    (("  splat:\n", "  splat:\n    - a: { color: red }\n    - b: { color: red }\n"), "terrain.splat", "1-4 layers"),
])  # fmt: skip
def test_terrain_errors_say_where(project: Project, change: tuple[str, str], where: str, text: str) -> None:
    from conftest import load

    assert change[0] in TERRAIN
    _, _, findings = load(project, TERRAIN.replace(change[0], change[1]), "land")
    errors = [f for f in findings if f.severity == "error"]
    assert any(f.where == where and text in f.message and f.line for f in errors), [f.format() for f in errors]


def test_a_terrain_has_no_parts(project: Project) -> None:
    from conftest import load

    _, _, findings = load(project, TERRAIN.replace("terrain:\n", "skin: soft\nterrain:\n"), "land")
    assert any(f.where == "skin" and "a terrain has no skin" in f.message for f in findings)


# --- the heightfield ----------------------------------------------------------------------------------------------------


def test_heights_follow_the_shapes(project: Project) -> None:
    f = field_of(project)
    assert f.heights.shape == (65, 129)
    assert f.height(-16, 0) == pytest.approx(6.0, abs=1e-9)  # the hill's top
    assert f.height(-16, 9.99) == pytest.approx(0.0, abs=1e-3) and f.height(0, 5) == 0.0  # its edge; untouched ground
    assert f.height(14, 0) == pytest.approx(3.0) and f.height(17, 2) == pytest.approx(3.0)  # the plateau's flat top
    assert f.slope(-16, 0) == pytest.approx(0.0, abs=1e-6) and f.slope(-21, 0) > 20
    n = f.normal(-21, 0)
    assert n[0] < 0 and n[1] > 0 and np.linalg.norm(n) == pytest.approx(1.0)  # facing away from the hill's top
    # the path: sunk by its depth below the (flat) ground along it, the bank blending back up
    assert f.height(0, -10) == pytest.approx(-0.3, abs=1e-6) and f.distance_to_path(0, -10) == pytest.approx(0.0, abs=0.05)
    assert f.distance_to_path(0, 10) == NO_PATH
    assert f.distance(np.array([[0.0, 1.0, 5.0], [-16.0, 5.0, 0.0]])) == pytest.approx([1.0, -1.0])
    lo, hi = f.bounds()
    assert list(lo) == pytest.approx([-32, -0.3, -16]) and list(hi) == pytest.approx([32, 6, 16])


def test_blends(project: Project) -> None:
    def top(blend: str, height: float, smooth: str = "") -> float:
        text = TERRAIN.replace("blend: max", f"blend: {blend}{smooth}").replace("height: 3,", f"height: {height},")
        text = text.replace("- hill: { at: [-16, 0]", "- hill: { at: [14, 0]")  # a 6 m hill under the plateau
        return float(field_of(project, text).height(14, 0))

    assert top("max", 3) == pytest.approx(6.0) and top("max", 8) == pytest.approx(8.0)
    assert top("min", 3) == pytest.approx(3.0) and top("set", 2) == pytest.approx(2.0)
    assert top("add", 3) == pytest.approx(9.0) and top("subtract", 3) == pytest.approx(3.0)
    assert top("max", 6.5, ", smooth: 2") > 6.5  # rounded crease: a little above both near equal heights


def test_splat_weights(project: Project) -> None:
    f = field_of(project)
    assert f.weights.shape == (65, 129, 3) and np.allclose(f.weights.sum(axis=-1), 1.0, atol=1e-5)
    assert list(f.splat(0, 5)) == pytest.approx([1, 0, 0])  # flat, away from the path: grass
    assert f.splat(0, -10)[1] == pytest.approx(1.0)  # on the path: dirt
    assert f.splat(-21, 0)[2] > 0.9  # the hill's steep side: rock
    assert f.layer_names == ["grass", "dirt", "rock"]


def test_noise_is_deterministic_and_bounded() -> None:
    x, z = np.meshgrid(np.linspace(-50, 50, 101), np.linspace(-50, 50, 101))
    a = fbm(x, z, 20.0, 4, 0.5, 7)
    assert np.array_equal(a, fbm(x, z, 20.0, 4, 0.5, 7)) and not np.array_equal(a, fbm(x, z, 20.0, 4, 0.5, 8))
    assert -1.0 <= a.min() < -0.3 and 0.3 < a.max() <= 1.0
    # integer hashing (no random streams): fixed values on every machine
    assert float(fbm(np.array([3.3]), np.array([-7.1]), 10.0, 2, 0.5, 1)[0]) == pytest.approx(0.0085038, abs=1e-6)


# --- meshes and files ------------------------------------------------------------------------------------------------------


def test_chunk_meshes_lods_and_skirts(project: Project) -> None:
    f = field_of(project)
    skirt = skirt_depth(f)
    assert skirt >= f.cell
    for lod, n in ((0, 33), (1, 17), (2, 9)):
        chunks = meshes(f, lod)
        assert len(chunks) == 8 and {(c.ix, c.iz) for c in chunks} == {(i, j) for i in range(4) for j in range(2)}
        c = chunks[0]
        ring = 4 * (n - 1)
        assert len(c.vertices) == n * n + ring and len(c.faces) == 2 * (n - 1) ** 2 + 2 * ring
        assert c.faces.dtype == np.uint16
        top = c.vertices[: n * n]
        assert top[:, 0].min() == pytest.approx(-8) and top[:, 0].max() == pytest.approx(8)  # chunk space
        world = top + np.array([c.centre[0], 0, c.centre[1]])
        assert np.allclose(world[:, 1], f.height(world[:, 0], world[:, 2]), atol=1e-5)  # heights are the grid's
        hang = c.vertices[n * n :] + np.array([c.centre[0], 0, c.centre[1]])  # the skirt: under the chunk's border
        assert np.allclose(np.maximum(np.abs(c.vertices[n * n :, 0]), np.abs(c.vertices[n * n :, 2])), 8)
        assert np.allclose(hang[:, 1], f.height(hang[:, 0], hang[:, 2]) - skirt, atol=1e-5)
        # every face winds counter-clockwise from above (top) or faces outwards (skirt)
        tri = c.vertices[c.faces[: 2 * (n - 1) ** 2]]
        normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        assert (normal[:, 1] > 0).all()
        side = c.vertices[c.faces[2 * (n - 1) ** 2 :]]
        out = np.cross(side[:, 1] - side[:, 0], side[:, 2] - side[:, 0])
        assert ((out[:, [0, 2]] * side.mean(axis=1)[:, [0, 2]]).sum(axis=1) > 0).all()
    # neighbours at the same LOD share their border points exactly
    a, b = meshes(f, 1)[0], meshes(f, 1)[1]
    assert (a.ix, b.ix) == (0, 1)
    ea = a.vertices[:289].reshape(17, 17, 3)[:, -1] + np.array([a.centre[0], 0, a.centre[1]])
    eb = b.vertices[:289].reshape(17, 17, 3)[:, 0] + np.array([b.centre[0], 0, b.centre[1]])
    assert np.allclose(ea, eb)


def test_splat_png_sums_to_one(project: Project) -> None:
    import io

    from PIL import Image

    f = field_of(project)
    image = np.asarray(Image.open(io.BytesIO(splat_png(f))))
    assert image.shape == (65, 129, 3)
    assert (image.astype(int).sum(axis=-1) <= 255).all()
    rest = 255 - image.astype(int).sum(axis=-1)
    assert np.abs(rest / 255 - f.weights[..., 0]).max() < 3 / 255
    assert np.abs(image[..., 0] / 255 - f.weights[..., 1]).max() < 1.5 / 255


def terrain_project(tmp_path: Path) -> Project:
    project = make_project(tmp_path, GODOT_CONFIG)
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text(PROJECT_GODOT)
    write_model(project, TERRAIN, "land")
    return project


def test_build_writes_a_terrain(tmp_path: Path) -> None:
    project = terrain_project(tmp_path)
    result = build(project)
    assert result.errors == [], [f.format() for f in result.findings]
    models = project.output_dir / "models"
    names = sorted(p.name for p in models.iterdir())
    assert names == ["land.glb", "land.glb.import", "land.lod1.glb", "land.lod1.glb.import", "land.lod2.glb", "land.lod2.glb.import",
                     "land.splat.png", "land.splat.png.import", "land.tscn"]  # fmt: skip
    assert "meshes/generate_lods=false" in (models / "land.glb.import").read_text()
    assert "compress/mode=0" in (models / "land.splat.png.import").read_text()
    entry = result.manifest["models"]["land"]
    assert entry["class"] == "terrain" and entry["glb"] == "models/land.glb" and entry["godot_scene"] == "res://assets/kiln/models/land.tscn"
    assert [lod["glb"] for lod in entry["lods"]] == ["models/land.lod1.glb", "models/land.lod2.glb"]
    assert entry["triangles"] > entry["lods"][0]["triangles"] > entry["lods"][1]["triangles"]
    t = entry["terrain"]
    assert t["samples"] == [129, 65] and t["chunks"] == [4, 2] and t["splat"] == "models/land.splat.png"
    assert [(layer["name"], layer["channel"]) for layer in t["layers"]] == [("grass", "rest"), ("dirt", "r"), ("rock", "g")]
    assert t["collision"] == {"samples": [129, 65], "spacing": 0.5} and len(t["probes"]) == 5
    assert "looks" in result.manifest  # the style's look kit, as for models
    doc, binary = read_glb((models / "land.glb").read_bytes())
    assert validate(doc, binary) == []
    root = next(n for n in doc["nodes"] if n["name"] == "land")
    assert len(root["children"]) == 8
    chunk = doc["nodes"][root["children"][0]]
    assert chunk["name"] == "chunk_0_0" and chunk["translation"] == [-24.0, 0.0, -8.0]
    prim = doc["meshes"][chunk["mesh"]]["primitives"][0]
    assert set(prim["attributes"]) == {"POSITION", "NORMAL", "TEXCOORD_0", "COLOR_0"}
    assert doc["accessors"][prim["attributes"]["COLOR_0"]]["normalized"] is True
    uv = read_accessor(doc, binary, prim["attributes"]["TEXCOORD_0"])
    assert uv.min() > 0 and uv.max() < 1
    # the scene: LOD glbs, the splat shader and material, a HeightMapShape3D with the grid's heights
    scene = (models / "land.tscn").read_text()
    assert scene.count("instance=ExtResource") == 3 and "lod_ranges = [0, 30, 60]" in scene
    assert "map_width = 129" in scene and "map_depth = 65" in scene and "uniform sampler2D splat" in scene
    assert "transform = Transform3D(0.5, 0, 0, 0, 0.5, 0, 0, 0, 0.5, 0, 0, 0)" in scene and "uid" not in scene
    data = re.search(r"map_data = PackedFloat32Array\(([^)]*)\)", scene)
    assert data is not None
    heights = np.array([float(v) for v in data.group(1).split(",")]).reshape(65, 129) * 0.5  # stored / spacing
    model, _ = ok_model(project, TERRAIN, "land")
    assert model.terrain is not None
    assert np.abs(heights - compute(model.terrain).heights).max() < 1e-3
    # build twice: nothing changes; a fresh cache gives the same bytes
    first = {p.name: p.read_bytes() for p in models.iterdir()}
    assert build(project).written == []
    shutil.rmtree(project.root / ".kiln-cache")
    again = build(project)
    assert again.written == [] and {p.name: p.read_bytes() for p in models.iterdir()} == first


def test_terrain_settings_change_the_files(tmp_path: Path) -> None:
    project = terrain_project(tmp_path)
    write_model(project, TERRAIN.replace("  lod: [30, 60]\n", "  lod: []\n  collision: false\n"), "land")
    result = build(project)
    assert result.errors == []
    entry = result.manifest["models"]["land"]
    assert "lods" not in entry and entry["terrain"]["collision"] is None
    scene = (project.output_dir / "models" / "land.tscn").read_text()
    assert "HeightMapShape3D" not in scene and "lod_ranges = [0]" in scene
    write_model(project, TERRAIN.replace("  lod: [30, 60]\n", "  collision: 2\n"), "land")
    scene = (project.output_dir / "models" / "land.tscn").read_text() if build(project).errors == [] else ""
    assert "map_width = 65" in scene and "map_depth = 33" in scene and "Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)" in scene


def test_a_terrain_leaves_other_models_alone(tmp_path: Path) -> None:
    project = terrain_project(tmp_path)
    (project.models_dir / "land.kiln.yaml").unlink()
    write_model(project, sphere_text("ball"), "ball")
    assert build(project).errors == []
    out = project.output_dir
    before = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"}
    write_model(project, TERRAIN, "land")
    result = build(project)
    assert result.errors == [] and not [p for p in result.written if "ball" in p.name]
    after = {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    assert all(after[k] == v for k, v in before.items())
    (project.models_dir / "land.kiln.yaml").unlink()  # stale terrain files go
    result = build(project)
    assert not list((out / "models").glob("land*")) and len(result.removed) == 5


# --- lint and preview ---------------------------------------------------------------------------------------------------


def test_lint_warns_about_terrains(project: Project) -> None:
    text = TERRAIN.replace("    - path:", "    - hill: { at: [200, 0], radius: 5, height: 1 }\n    - path:")
    text = text.replace("slope: { above: 30, fade: 4 }", "slope: { above: 80, fade: 1 }")
    write_model(project, text, "land")
    result = lint_project(project)
    found = {(f.rule, f.where) for f in result.findings}
    assert ("W117", "terrain.shapes[2].hill") in found and ("W116", "terrain.splat[2].rock") in found
    assert all(f.line for f in result.findings if f.rule in ("W116", "W117"))
    assert "land" in result.models and "land" not in result.built


def test_preview_a_terrain(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    from PIL import Image

    write_model(in_project, TERRAIN, "land")
    code, result = run_json(["preview", "land"], capsys)
    assert code == 0, result
    assert result["outputs"] == {"terrain": "previews/land/terrain.png"}
    image = Image.open(in_project.root / "previews/land/terrain.png").convert("RGB")
    assert image.width >= 1200
    code, result = run_json(["preview", "land", "--pose", "walk"], capsys)
    assert code == 1 and "is a terrain" in result["findings"][0]["message"]
    write_model(in_project, sphere_text("ball"), "ball")
    code, result = run_json(["lineup"], capsys)
    assert code == 0 and result["models"] == ["ball"]


def test_heightfield_load_for_tools(project: Project) -> None:
    from kiln.terrain import load

    write_model(project, TERRAIN, "land")
    f = load(project, "land")
    assert f.height(-16, 0) == pytest.approx(6.0)
    assert list((project.root / ".kiln-cache").glob("land.terrain.*.pickle"))
    assert load(project, "land").height(-16, 0) == pytest.approx(6.0)  # from the cache
    write_model(project, sphere_text("ball"), "ball")
    with pytest.raises(ValueError, match="not a terrain"):
        load(project, "ball")


@pytest.mark.slow
@pytest.mark.skipif(not Path("/proc/self/status").is_file(), reason="reads the peak from /proc (Linux)")
def test_design_point_memory(tmp_path: Path) -> None:
    """256 x 256 m at 0.5 m cells (the design point) builds in well under 1 GB."""
    project = terrain_project(tmp_path)
    text = TERRAIN.replace("size: [64, 32]", "size: [256, 256]").replace("chunk: 16", "chunk: 32")
    text = text.replace("  shapes:\n", "  shapes:\n    - noise: { scale: 60, height: 4, octaves: 5 }\n")
    write_model(project, text, "land")
    # VmHWM: this process's own peak (ru_maxrss would carry over the forking test process's size across exec)
    code = ("import re, sys\nfrom pathlib import Path\nfrom kiln.build import build\nfrom kiln.project import load_project\n"
            "r = build(load_project(Path(sys.argv[1])))\nassert not r.errors, r.findings\n"
            "print(re.search(r'VmHWM:\\s+(\\d+)', Path('/proc/self/status').read_text()).group(1))\n")  # fmt: skip
    run = subprocess.run([sys.executable, "-c", code, str(project.root)], capture_output=True, text=True, timeout=600)
    assert run.returncode == 0, run.stderr[-2000:]
    peak_mb = int(run.stdout.split()[-1]) / 1024
    assert peak_mb < 600, peak_mb
    manifest = json.loads((project.output_dir / "manifest.json").read_text())
    assert manifest["models"]["land"]["terrain"]["samples"] == [513, 513]


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_loads_a_terrain(tmp_path: Path) -> None:
    project = terrain_project(tmp_path)
    write_model(project, sphere_text("ball"), "ball")
    result = build(project)
    godot = find_godot_binary()
    assert godot is not None and result.godot_root is not None and result.errors == []
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
    assert check.models == 2
    # the checks bite: a probe somewhere else than the collision has it, and a shader that doesn't compile
    manifest = project.output_dir / "manifest.json"
    data = json.loads(manifest.read_text())
    data["models"]["land"]["terrain"]["probes"][0][2] += 0.5
    manifest.write_text(json.dumps(data))
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert not check.ok and "land collision at" in check.output
    scene = project.output_dir / "models" / "land.tscn"
    scene.write_text(scene.read_text().replace("ROUGHNESS = 1.0;", "ROUGHNESS = nonsense;"))
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert not check.ok and "splat shader doesn't compile" in check.output


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_loads_a_toon_terrain(tmp_path: Path) -> None:
    from kiln.project import load_project

    project = terrain_project(tmp_path)
    style = tmp_path / "styles" / "fast.style.toml"
    style.write_text(style.read_text().replace('"soft_toy"', '"toon"'))
    result = build(load_project(project.root))
    godot = find_godot_binary()
    assert godot is not None and result.godot_root is not None and result.errors == []
    assert "void light()" in (project.output_dir / "models" / "land.tscn").read_text()
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
