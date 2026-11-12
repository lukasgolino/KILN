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
