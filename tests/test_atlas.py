"""Palette atlas (CC0 parity M9): one material per model, variants as texture swaps, baked occlusion."""

from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from conftest import CONFIG, arms_text, make_project, sphere_text, write_model
from kiln.atlas import AO_STRENGTH, CELL, ambient_occlusion
from kiln.build import BuildResult, build
from kiln.export import to_glb
from kiln.gltf_check import accessor, check_glb
from kiln.godot import ATLAS_SCRIPT, APPLY_SCRIPT, find_godot_binary, verify
from kiln.project import Project, load_project, parse_config
from kiln.vendor.gltf import NEAREST, read_glb

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


def demo_project(root: Path, extra: str, models: tuple[str, ...] = ("knight", "pilot")) -> Project:
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns("previews", ".kiln-cache"))
    config = (root / "kiln.toml").read_text().replace('output_dir = "../godot/assets/kiln"', 'output_dir = "out"').replace('export = ["glb", "godot"]', 'export = ["glb"]')
    (root / "kiln.toml").write_text(config.replace("style_version = 1\n", f"style_version = 1\n{extra}"))
    for path in (root / "models").glob("*.kiln.yaml"):
        if path.name.split(".")[0] not in models:
            path.unlink()
    return load_project(root)


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> tuple[Project, BuildResult]:
    project = demo_project(tmp_path_factory.mktemp("atlas") / "demo", "atlas = true\natlas_ao = true\n")
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    return project, result


def glb(project: Project, name: str) -> tuple[dict[str, Any], bytes]:
    return read_glb((project.output_dir / "models" / f"{name}.glb").read_bytes())


def prims(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for m in doc["meshes"] for p in m["primitives"]]


def png(project: Project, name: str) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO((project.output_dir / "models" / name).read_bytes())).convert("RGB"))


def test_knight_is_one_material(demo: tuple[Project, BuildResult]) -> None:
    project, _ = demo
    data = (project.output_dir / "models" / "knight.glb").read_bytes()
    assert check_glb(data) == []
    doc, _ = read_glb(data)
    assert len(prims(doc)) <= 2  # soft-skinned body + the separate helmet's node, one shared material
    assert [m["name"] for m in doc["materials"]] == ["atlas"]
    pbr = doc["materials"][0]["pbrMetallicRoughness"]
    assert {doc["images"][doc["textures"][pbr[k]["index"]]["source"]]["uri"] for k in ("baseColorTexture", "metallicRoughnessTexture")} \
        == {"knight.palette.png", "knight.material.png"}  # fmt: skip
    assert doc["samplers"] == [{"magFilter": NEAREST, "minFilter": NEAREST, "wrapS": 33071, "wrapT": 33071}]  # no mipmaps: cells never bleed


def test_uvs_sit_on_cell_centres_of_the_right_colour(demo: tuple[Project, BuildResult]) -> None:
    project, result = demo
    entry = result.manifest["models"]["knight"]["atlas"]
    assert entry["palette"] == "models/knight.palette.png" and entry["material"] == "models/knight.material.png" and entry["ao"] is True
    assert entry["ao_strength"] == AO_STRENGTH
    image = png(project, "knight.palette.png")
    w, h = entry["size"]
    assert image.shape == (h, w, 3) and entry["cell"] == CELL
    centres = {tuple(c["uv"]): c for c in entry["cells"]}
    for c in entry["cells"]:  # the palette holds each cell's colour, the material texture its roughness and metal
        x, y = c["pixel"]
        assert "#%02x%02x%02x" % tuple(image[y + CELL // 2, x + CELL // 2]) == c["color"]
    doc, binary = glb(project, "knight")
    material = png(project, "knight.material.png")
    for p in prims(doc):
        uv = accessor(doc, binary, p["attributes"]["TEXCOORD_0"])
        idx = accessor(doc, binary, p["indices"]).reshape(-1, 3)
        assert {tuple(round(float(v), 5) for v in row) for row in uv} <= set(centres)
        assert np.all(uv[idx[:, 0]] == uv[idx[:, 1]]) and np.all(uv[idx[:, 0]] == uv[idx[:, 2]])  # a face is one cell
        px = np.floor(uv * [w, h]).astype(int)
        assert set(map(tuple, material[px[:, 1], px[:, 0]].tolist())) <= {(0, round(r * 255), round(m * 255)) for r, m in
                                                                          ((0.55, 0.35), (0.85, 0.0), (0.42, 0.0), (0.45, 0.5), (0.75, 0.0))}  # fmt: skip
    # the crest (red fabric) is the helmet's highest point
    helmet = next(p for m in doc["meshes"] if m["name"] == "helmet" for p in m["primitives"])
    pos = accessor(doc, binary, helmet["attributes"]["POSITION"])
    top = accessor(doc, binary, helmet["attributes"]["TEXCOORD_0"])[int(pos[:, 1].argmax())]
    assert centres[tuple(round(float(v), 5) for v in top)]["material"] == "fabric"
    assert centres[tuple(round(float(v), 5) for v in top)]["color"] == project.palette("toybox")[0]["red"]


def test_variant_is_a_texture_swap(demo: tuple[Project, BuildResult]) -> None:
    project, result = demo
    variant = result.manifest["models"]["pilot"]["variants"]["copilot"]
    assert variant["palette"] == "models/pilot.copilot.palette.png" and variant["glb"] == "models/pilot.copilot.glb"
    (base, bb), (other, ob) = glb(project, "pilot"), glb(project, "pilot.copilot")
    assert [m["name"].split("_")[0] for m in base["materials"]] == ["atlas", "fabric"]  # the atlas and the cap's decal
    for p, q in zip(prims(base), prims(other), strict=True):
        assert p["attributes"].keys() == q["attributes"].keys()
        for key in p["attributes"]:
            assert accessor(base, bb, p["attributes"][key]).tobytes() == accessor(other, ob, q["attributes"][key]).tobytes()
        assert accessor(base, bb, p["indices"]).tobytes() == accessor(other, ob, q["indices"]).tobytes()
    uris = [i.get("uri") for i in other["images"]]
    assert "pilot.copilot.palette.png" in uris and "pilot.material.png" in uris
    a, b = png(project, "pilot.palette.png"), png(project, "pilot.copilot.palette.png")
    swap = variant["swap"]
    for c in result.manifest["models"]["pilot"]["atlas"]["cells"]:
        x, y = c["pixel"]
        assert "#%02x%02x%02x" % tuple(a[y, x]) == c["color"]
        assert "#%02x%02x%02x" % tuple(b[y, x]) == swap.get(c["color"], c["color"])
    assert not np.array_equal(a, b)


def test_ao_is_a_grey_multiplier_in_range(demo: tuple[Project, BuildResult]) -> None:
    project, _ = demo
    doc, binary = glb(project, "knight")
    ao = np.concatenate([accessor(doc, binary, p["attributes"]["COLOR_0"]) for p in prims(doc)])
    assert np.all(ao[:, 0] == ao[:, 1]) and np.all(ao[:, 0] == ao[:, 2])
    assert ao.min() >= 1 - AO_STRENGTH - 1e-6 and ao.max() <= 1.0
    assert ao.min() < 0.85 and np.median(ao) > 0.9  # creases darken, open surfaces stay bright


def test_ao_strength_scales_the_darkening(demo: tuple[Project, BuildResult]) -> None:
    from kiln.builder import build_model

    project, _ = demo
    model, style, _ = project.load(project.root / "models" / "knight.kiln.yaml")
    assert model is not None and style is not None
    built = build_model(model, style)
    full, light = ambient_occlusion(built), ambient_occlusion(built, 0.2)
    assert light.min() >= 0.8 - 1e-6 and light.min() > full.min()
    assert np.allclose(1 - light, (1 - full) * 0.2 / AO_STRENGTH, atol=1e-3)  # the same occlusion, scaled


def test_builds_are_deterministic(demo: tuple[Project, BuildResult]) -> None:
    project, first = demo
    files = {p: p.read_bytes() for p in first.written}
    again = build(project)
    assert again.written == [] and again.removed == []
    assert all(p.read_bytes() == data for p, data in files.items())


def test_off_is_unchanged(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    write_model(project, arms_text())
    result = build(project)
    assert "atlas" not in result.manifest["models"]["thing"]
    assert not list((project.output_dir / "models").glob("*.png"))
    doc, _ = glb(project, "thing")
    assert "images" not in doc and all("TEXCOORD_0" not in p["attributes"] and "COLOR_0" not in p["attributes"] for p in prims(doc))
    assert len(doc["materials"]) == 2  # red and blue


def test_settings_combinations() -> None:
    assert parse_config({"atlas": True, "atlas_ao": True}, None)[1] == []
    assert [f.where for f in parse_config({"atlas": True, "vertex_colors": True}, None)[1]] == ["atlas"]
    assert [f.where for f in parse_config({"atlas_ao": True}, None)[1]] == ["atlas_ao"]
    assert [f.where for f in parse_config({"atlas": "yes"}, None)[1]] == ["atlas"]
    assert parse_config({"atlas": True, "atlas_ao": True}, None)[0].atlas_ao == AO_STRENGTH
    assert parse_config({"atlas": True, "atlas_ao": 0.3}, None)[0].atlas_ao == 0.3
    assert parse_config({"atlas": True, "atlas_ao": False}, None)[0].atlas_ao == 0.0
    assert [f.where for f in parse_config({"atlas": True, "atlas_ao": 1.5}, None)[1]] == ["atlas_ao"]
    assert [f.where for f in parse_config({"atlas": True, "atlas_ao": "strong"}, None)[1]] == ["atlas_ao"]


GLOW = sphere_text() + """\
  - sphere: { at: [0, 0.62, 0], radius: 0.08 }
    color: gold
    material: glow
  - sphere: { at: [0.2, 0.3, 0.2], radius: 0.12 }
    color: wood
    material: skin
variants:
  night: { swap: { gold: blue } }
"""


def godot_atlas_project(tmp_path: Path, extra: str = "atlas = true\n") -> Project:
    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "art", CONFIG + 'output_dir = "../assets/kiln"\nexport = ["glb", "godot"]\nvariant_glbs = false\n' + extra)
    write_model(project, GLOW)
    return project


def test_glow_rim_and_godot_scenes(tmp_path: Path) -> None:
    project = godot_atlas_project(tmp_path)
    result = build(project)
    assert not result.errors
    entry = result.manifest["models"]["thing"]
    assert entry["atlas"]["glow"] == "models/thing.glow.png" and entry["atlas"]["rim"] == "models/thing.rim.png"
    assert entry["variants"]["night"] == {"swap": {"#f2c14e": "#2f6fd0"}, "palette": "models/thing.night.palette.png",
                                          "glow": "models/thing.night.glow.png", "godot_scene": "res://assets/kiln/models/thing.night.tscn"}  # fmt: skip
    doc, _ = glb(project, "thing")
    mat = doc["materials"][0]
    assert mat["emissiveFactor"] == [1.0, 1.0, 1.0] and mat["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"] == 2.0
    assert "COLOR_0" not in prims(doc)[0]["attributes"]  # atlas_ao off
    models = tmp_path / "assets" / "kiln" / "models"
    scene = (models / "thing.tscn").read_text()
    night = (models / "thing.night.tscn").read_text()
    assert 'path="res://assets/kiln/models/thing.rim.png" id="2_rim_texture"' in scene and 'rim_texture = ExtResource("2_rim_texture")' in scene
    assert 'path="res://assets/kiln/models/thing.glb"' in night and 'palette = ExtResource("3_palette")' in night and 'glow = ExtResource("2_glow")' in night
    assert "@export var palette: Texture2D" in ATLAS_SCRIPT and "palette" not in APPLY_SCRIPT
    assert "filter_nearest" in scene and not (models / "thing.night.glb").exists()


def test_imported_models_get_cavity_occlusion(tmp_path: Path) -> None:
    from test_importer import SOURCE, box_glb

    from kiln.builder import build_model

    project = make_project(tmp_path)
    box_glb(project.root / "imports" / "box.glb")
    model, style, _ = project.load(write_model(project, SOURCE, "crate"))
    assert model is not None and style is not None
    ao = ambient_occlusion(build_model(model, style))
    assert ao.shape[0] > 0 and np.all(ao == 1.0)  # a convex box has no cavities


@pytest.mark.skipif(find_godot_binary() is None, reason="needs Godot 4 (GODOT=/path/to/godot)")
def test_godot_loads_atlas_scenes(tmp_path: Path) -> None:
    godot = find_godot_binary()
    assert godot is not None
    project = godot_atlas_project(tmp_path, "atlas = true\natlas_ao = true\n")
    result = build(project)
    assert not result.errors and result.godot_root is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
