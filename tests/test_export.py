"""glTF export: validity, node/skin structure, animations, variants, determinism."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from PIL import Image

from conftest import arms_text, built_of, sphere_text
from kiln.export import Built, gltf_name, srgb_to_linear, to_glb
from kiln.gltf_check import accessor, check_glb, read_glb, validate
from kiln.project import Project


def decoded(built: Built, swap: dict[str, str] | None = None) -> tuple[dict[str, Any], bytes]:
    doc, binary = read_glb(to_glb(built, "kiln test", swap))
    assert validate(doc, binary) == []
    return doc, binary


def test_srgb_to_linear() -> None:
    assert srgb_to_linear("#000000") == [0.0, 0.0, 0.0]
    assert srgb_to_linear("#ffffff") == [1.0, 1.0, 1.0]
    assert srgb_to_linear("#808080")[0] == pytest.approx(0.2158605)


def test_gltf_name() -> None:
    assert gltf_name("walk", True) == "walk-loop"
    assert gltf_name("die", False) == "die"


def test_static_model_is_one_node_one_mesh(project: Project) -> None:
    built = built_of(project, sphere_text() + "  - sphere: { at: [0, 0.5, 0.2], radius: 0.1 }\n    color: white\n    material: plastic\n")
    doc, binary = decoded(built)
    assert len(doc["nodes"]) == 1 and doc["scenes"][0]["nodes"] == [0]
    node = doc["nodes"][0]
    assert node["name"] == "root" and node["mesh"] == 0 and node["extras"] == {"kiln_part": "root"}
    mesh = doc["meshes"][0]
    assert mesh["name"] == "thing" and len(mesh["primitives"]) == 2
    assert "skins" not in doc and "animations" not in doc
    names = sorted(m["name"] for m in doc["materials"])
    assert names == ["default_red#e8413c", "plastic_white#f4f4f0"]  # <preset>_<colour>#<hex>: variant scenes recolour by hex
    red = next(m for m in doc["materials"] if m["name"] == "default_red#e8413c")
    assert red["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx(srgb_to_linear("#e8413c"))
    assert red["pbrMetallicRoughness"]["roughnessFactor"] == 0.5
    pos = np.concatenate([accessor(doc, binary, p["attributes"]["POSITION"]) for p in mesh["primitives"]])
    assert pos[:, 1].min() == pytest.approx(0.0, abs=0.01) and pos[:, 1].max() == pytest.approx(0.6, abs=0.01)


def test_emissive_material(project: Project) -> None:
    built = built_of(project, sphere_text().replace("color: red", "color: red\n    material: glow"))
    doc, _ = decoded(built)
    mat = doc["materials"][0]
    assert mat["emissiveFactor"] == pytest.approx(srgb_to_linear("#e8413c"))
    assert mat["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"] == 2.0
    assert doc["extensionsUsed"] == ["KHR_materials_emissive_strength"]


def test_rigid_skin_has_a_node_per_part(project: Project) -> None:
    built = built_of(project, arms_text(skin="rigid"))
    doc, binary = decoded(built)
    names = [n["name"] for n in doc["nodes"]]
    assert names == ["root", "arm_l", "arm_r"]
    assert doc["nodes"][0]["children"] == [1, 2]
    assert "skins" not in doc
    arm = doc["nodes"][1]
    assert arm["translation"] == pytest.approx([0.3, 0.6, 0.0])
    assert doc["meshes"][arm["mesh"]]["name"] == "arm_l"
    # mesh positions are relative to the part's pivot
    pos = accessor(doc, binary, doc["meshes"][arm["mesh"]]["primitives"][0]["attributes"]["POSITION"])
    assert np.linalg.norm(pos, axis=1).min() < 0.15


def test_soft_skin_is_one_skinned_mesh(project: Project) -> None:
    built = built_of(project, arms_text(skin="soft"))
    doc, binary = decoded(built)
    skinned = [n for n in doc["nodes"] if "skin" in n]
    assert len(skinned) == 1 and skinned[0]["name"] == "thing_mesh"
    assert doc["scenes"][0]["nodes"] == [0, len(doc["nodes"]) - 1]
    skin = doc["skins"][0]
    assert skin["joints"] == [0, 1, 2] and skin["skeleton"] == 0
    ibm = accessor(doc, binary, skin["inverseBindMatrices"]).reshape(-1, 4, 4)
    np.testing.assert_allclose(ibm[1].T[:3, 3], [-0.3, -0.6, 0.0], atol=1e-6)
    prim = doc["meshes"][skinned[0]["mesh"]]["primitives"][0]
    assert {"JOINTS_0", "WEIGHTS_0"} <= set(prim["attributes"])
    assert all("mesh" not in n for n in doc["nodes"][:3])


def test_soft_skin_separate_part_stays_rigid(project: Project) -> None:
    text = arms_text(skin="soft").replace("arm_l: { pivot: [0.3, 0.6, 0] }", "arm_l: { pivot: [0.3, 0.6, 0], separate: true }")
    doc, _ = decoded(built_of(project, text))
    by_name = {n["name"]: n for n in doc["nodes"]}
    assert "mesh" in by_name["arm_l"] and "mesh" in by_name["arm_r"]  # the mirrored rig entry is separate too
    assert "skin" in by_name["thing_mesh"]


def test_animations_loop_names_and_keys(project: Project) -> None:
    built = built_of(project, arms_text())
    doc, binary = decoded(built)
    anims = {a["name"]: a for a in doc["animations"]}
    assert set(anims) == {"wave-loop", "hold"}
    wave = anims["wave-loop"]
    times = accessor(doc, binary, wave["samplers"][0]["input"])
    np.testing.assert_allclose(times, [0, 0.125, 0.25, 0.375, 0.5])  # 4 frames + the closing key
    assert len(wave["channels"]) == 3 * 3  # every bone: translation, rotation, scale
    assert {c["target"]["path"] for c in wave["channels"]} == {"translation", "rotation", "scale"}
    hold = anims["hold"]
    np.testing.assert_allclose(accessor(doc, binary, hold["samplers"][0]["input"]), [0, 0.25])


def test_step_interpolation(project: Project) -> None:
    text = arms_text().replace("hold: { fps: 4, loop: false,", "hold: { fps: 4, loop: false, interpolation: step,")
    doc, _ = decoded(built_of(project, text))
    hold = next(a for a in doc["animations"] if a["name"] == "hold")
    assert {s["interpolation"] for s in hold["samplers"]} == {"STEP"}


def test_variants_swap_colours(project: Project) -> None:
    built = built_of(project, sphere_text())
    doc, _ = decoded(built, {"#e8413c": "#2f6fd0"})
    assert doc["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"][:3] == pytest.approx(srgb_to_linear("#2f6fd0"))


def test_decal_texture_is_embedded(project: Project) -> None:
    Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(project.root / "decals" / "logo.png")
    text = sphere_text() + "    decal: { image: decals/logo.png, axis: z, at: [0, 0.3, 0.3], size: [0.2, 0.2] }\n"
    doc, _ = decoded(built_of(project, text))
    assert len(doc["images"]) == 1 and len(doc["textures"]) == 1
    assert doc["samplers"][0]["magFilter"] == 9728  # small images are pixel art: nearest
    decal_mat = next(m for m in doc["materials"] if "decal0" in m["name"])
    assert decal_mat["pbrMetallicRoughness"]["baseColorTexture"] == {"index": 0}
    prims = doc["meshes"][0]["primitives"]
    assert any("TEXCOORD_0" in p["attributes"] for p in prims)


def test_export_is_deterministic(project: Project) -> None:
    a = to_glb(built_of(project, arms_text(skin="soft")), "kiln test")
    b = to_glb(built_of(project, arms_text(skin="soft")), "kiln test")
    assert a == b
    assert check_glb(a) == []


def test_validator_catches_problems(project: Project) -> None:
    doc, binary = read_glb(to_glb(built_of(project, sphere_text()), "kiln test"))
    pos = doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    doc["accessors"][pos]["max"] = [9.0, 9.0, 9.0]
    doc["asset"]["version"] = "1.0"
    problems = validate(doc, binary)
    assert "asset.version must be 2.0" in problems
    assert any("min/max" in p for p in problems)
