"""#202: glowing colours keep their hue (capped strength, dimmed lit colour); a part's own emission strength."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.bake import _oklab
from kiln.build import build
from kiln.export import GLOW_PEAK, glow_strength, srgb_to_linear
from kiln.lint import lint_paths
from kiln.project import Project
from kiln.render import View, render
from kiln.vendor.gltf import read_glb

GEMS = """\
name: thing
parts:
  - sphere: { at: [-0.3, 0.3, 0], radius: 0.15 }
    color: "#ffa8c4"
    material: glow
  - sphere: { at: [0.3, 0.3, 0], radius: 0.15 }
    color: "#3fd08a"
    material: glow
    emission: 0.6
"""


def test_the_strength_is_capped_per_colour() -> None:
    pink = srgb_to_linear("#ffa8c4")
    assert glow_strength(pink, 2.0) == GLOW_PEAK / max(pink)  # a bright colour: capped
    dim = srgb_to_linear("#202020")
    assert glow_strength(dim, 2.0) == 2.0  # a dark one keeps the preset's strength


def test_materials_and_a_parts_own_emission(project: Project) -> None:
    style = (project.root / "styles" / "fast.style.toml").read_text()
    if "glow" not in style:
        (project.root / "styles" / "fast.style.toml").write_text(style + "\n[materials]\nglow = { emission = 2.0 }\n" if "[materials]" not in style
                                                                 else style.replace("[materials]\n", "[materials]\nglow = { emission = 2.0 }\n"))  # fmt: skip
    model, _, findings = load(project, GEMS)
    assert model is not None and not findings, findings
    assert [p.material for p in model.parts] == ["glow", "glow@0.6"]
    write_model(project, GEMS)
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    strength = {m["name"].split("_")[0]: m.get("extensions", {}).get("KHR_materials_emissive_strength", {}).get("emissiveStrength", 1.0)
                for m in doc["materials"] if "emissiveFactor" in m}  # fmt: skip
    assert abs(strength["glow@0.6"] - 0.6) < 1e-6  # its own strength (under the cap)
    assert strength["glow"] < 2.0  # the pink's capped
    base = {m["name"].split("_")[0]: m["pbrMetallicRoughness"]["baseColorFactor"] for m in doc["materials"]}
    assert max(base["glow"][:3]) < 0.5  # its lit colour dimmed: the glow carries it
    for bad in ("emission: -1", "emission: soft"):
        _, _, findings = load(project, GEMS.replace("emission: 0.6", bad))
        assert any(f.where == "parts[1].emission" for f in findings), (bad, findings)


def test_the_preview_keeps_the_hue(project: Project) -> None:
    style = (project.root / "styles" / "fast.style.toml").read_text()
    if "glow =" not in style:
        (project.root / "styles" / "fast.style.toml").write_text(style + ("\n[materials]\n" if "[materials]" not in style else "\n") + "glow = { emission = 2.0 }\n")
    built = lint_paths(project, [write_model(project, GEMS.replace("    emission: 0.6\n", ""))]).built["thing"]
    image = np.asarray(render(built, View(0, 0), 200)).astype(float)
    lit = image[..., 3] > 0
    xs = np.nonzero(lit.any(axis=0))[0]
    left = image[:, xs.min() : (xs.min() + xs.max()) // 2][lit[:, xs.min() : (xs.min() + xs.max()) // 2]][:, :3].mean(axis=0)
    c = left / 255
    lab = _oklab(np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).reshape(1, 3))[0]
    assert np.hypot(lab[1], lab[2]) > 0.04  # the pink stays pink (it went white: chroma 0)


def test_a_decal_on_a_glowing_part_keeps_its_white_factor(project: Project) -> None:
    from PIL import Image

    Image.new("RGBA", (8, 8), (250, 220, 40, 255)).save(project.root / "decals" / "sq.png")
    style = (project.root / "styles" / "fast.style.toml").read_text()
    if "glow =" not in style:
        (project.root / "styles" / "fast.style.toml").write_text(style + ("\n[materials]\n" if "[materials]" not in style else "\n") + "glow = { emission = 2.0 }\n")
    text = GEMS.replace("    material: glow\n", "    material: glow\n    decal: { image: decals/sq.png, axis: z, at: [-0.3, 0.3, 0.15], size: [0.1, 0.1] }\n", 1)
    write_model(project, text)
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    decal = [m for m in doc["materials"] if "decal" in m["name"]]
    assert decal and decal[0]["pbrMetallicRoughness"]["baseColorFactor"] == [1.0, 1.0, 1.0, 1.0]


def test_rims_find_their_preset_and_at_names_are_refused(tmp_path: object) -> None:
    from pathlib import Path

    from kiln.godot import APPLY_SCRIPT, ATLAS_SCRIPT
    from kiln.style import load_style

    for script in (APPLY_SCRIPT, ATLAS_SCRIPT):
        assert 'get_slice("_", 0).get_slice("@", 0)' in script  # skin@0.5 still finds the skin preset's rim
    folder = Path(str(tmp_path))
    (folder / "x.style.toml").write_text('extends = "soft_toy"\n[materials]\n"glow@2" = { emission = 2.0 }\n')
    bad, findings = load_style("x", folder)
    assert bad is None and any("@" in f.message for f in findings)


def test_emission_on_a_cut_is_refused(project: Project) -> None:
    _, _, findings = load(project, GEMS + "  - box: { at: [0, 0.3, 0], size: [0.1, 0.1, 0.1] }\n    cut: true\n    emission: 1\n")
    assert any(f.where == "parts[2].emission" for f in findings), findings


def test_an_atlas_variant_glow_is_not_held_at_the_base_cap(tmp_path: object) -> None:
    from pathlib import Path

    from conftest import CONFIG, make_project

    project = make_project(Path(str(tmp_path)) / "a", CONFIG + "atlas = true\n")
    style = (project.root / "styles" / "fast.style.toml").read_text()
    (project.root / "styles" / "fast.style.toml").write_text(style + ("\n[materials]\n" if "[materials]" not in style else "\n") + "glow = { emission = 2.0 }\n")
    text = "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.15 }\n    color: \"#ffa8c4\"\n    material: glow\n" \
           "variants:\n  dark: { swap: { \"#ffa8c4\": \"#401020\" } }\n"
    write_model(project, text)
    result = build(project)
    assert not result.errors, result.findings
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    strength = doc["materials"][0]["extensions"]["KHR_materials_emissive_strength"]["emissiveStrength"]
    dark = srgb_to_linear("#401020")
    assert abs(strength - glow_strength(dark, 2.0)) < 1e-6  # the variant's darker colour sets the shared strength


def test_presets_read_a_part_emission_off_the_name() -> None:
    from kiln.style import load_style

    style, _ = load_style("soft_toy")
    assert style is not None
    base = style.materials["default"]
    glow = style.materials.get("default@0.6")
    assert glow is not None and glow.emission == 0.6 and glow.roughness == base.roughness
    assert style.materials.get("default@x") == base  # a bad amount: the preset as it is, never None
