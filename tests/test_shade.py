"""#231 shade paint: darker in crevices, lighter on top, darker underneath, as a COLOR_0 multiplier in any colour mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from conftest import CONFIG, load, make_project, write_model

from kiln.build import build
from kiln.lint import lint_paths
from kiln.project import Project
from kiln.render import View, render
from kiln.shade import Shade, effective, shading
from kiln.vendor.gltf import read_accessor, read_glb

GROOVED = """\
name: thing
parts:
  - sphere: { at: [0, 0.5, 0], radius: 0.3 }
    color: white
  - torus: { at: [0, 0.5, 0], radius: 0.3, thickness: 0.03 }
    cut: true
"""
SHADE = "shade: { cavity: 0.5, top: 0.2, under: 0.15 }\n"


def test_notation(project: Project) -> None:
    model, _, findings = load(project, GROOVED + SHADE)
    assert model is not None and not findings, findings
    assert model.shade == {"cavity": 0.5, "top": 0.2, "under": 0.15}
    for bad in ("shade: { cavity: 2 }", "shade: { gloom: 0.2 }", "shade: { top: on }", "shade: 0.3"):
        _, _, findings = load(project, GROOVED + bad + "\n")
        assert [f.where for f in findings] == ["shade"], (bad, findings)


def test_a_model_shade_goes_over_its_styles_and_atlas_ao_is_a_cavity() -> None:
    from kiln.style import load_style

    assert Shade(0.3, 0.1, 0.0).over({"top": 0.2}) == Shade(0.3, 0.2, 0.0)
    style, findings = load_style("soft_toy")
    assert style is not None and not findings and not style.shade.on  # off by default

    class B:  # just what effective() reads
        def __init__(self, shade: Shade, model: dict[str, float]) -> None:
            self.style = type("S", (), {"shade": shade})()
            self.model = type("M", (), {"shade": model})()

    assert effective(B(Shade(0.3, 0.1), {"top": 0.2}), 0.0) == Shade(0.3, 0.2, 0.0)  # type: ignore[arg-type]
    assert effective(B(Shade(0.3), {}), 0.65) == Shade(0.65)  # type: ignore[arg-type]
    assert effective(B(Shade(0.8), {}), 0.65) == Shade(0.8)  # type: ignore[arg-type]


def test_style_shade_table(tmp_path: Path) -> None:
    from kiln.style import load_style

    styles = tmp_path
    (styles / "mine.style.toml").write_text('extends = "soft_toy"\n[shade]\ncavity = 0.25\ntop = 0.12\n')
    style, findings = load_style("mine", styles)
    assert style is not None and not findings and style.shade == Shade(0.25, 0.12, 0.0)
    (styles / "bad.style.toml").write_text('extends = "soft_toy"\n[shade]\ncavity = 3\n')
    style, findings = load_style("bad", styles)
    assert style is None and [f.where for f in findings] == ["shade"]


def test_the_groove_is_darker(project: Project) -> None:
    built = lint_paths(project, [write_model(project, GROOVED + "shade: { cavity: 0.8 }\n")]).built["thing"]
    mult = shading(built)
    assert mult is not None and mult.shape == built.painted.faces.shape and 0 < mult.min() and mult.max() <= 1
    r = np.linalg.norm(built.painted.vertices[built.painted.faces] - [0, 0.5, 0], axis=2)
    groove, rest = r < 0.29, r >= 0.295  # corners inside the cut / on the sphere's surface
    assert groove.any() and rest.any()
    assert mult[groove].mean() < mult[rest].mean() - 0.05
    plain = lint_paths(project, [write_model(project, GROOVED)]).built["thing"]
    assert shading(plain) is None  # off by default


def test_the_top_keeps_its_colour_the_sides_darken_the_underside_most(project: Project) -> None:
    built = lint_paths(project, [write_model(project, GROOVED + "shade: { top: 0.2, under: 0.15 }\n")]).built["thing"]
    mult = shading(built)
    assert mult is not None
    n = built.normals
    ny = n[..., 1] / np.linalg.norm(n, axis=2)
    assert np.allclose(mult, (1 - 0.2 * (1 - np.maximum(ny, 0))) * (1 - 0.15 * np.maximum(-ny, 0)), atol=1e-4)
    assert mult[ny > 0.95].min() > 0.99 and mult[ny < -0.95].max() < 0.7


def test_a_flat_top_keeps_its_colour_to_the_hard_edge(project: Project) -> None:
    """Per corner, not per vertex: the top face's corners on the box's edge follow the top's normal."""
    box = "name: thing\nparts:\n  - box: { at: [0, 0.3, 0], size: [0.6, 0.6, 0.6] }\n    color: white\n    hard: true\nshade: { top: 0.3 }\n"
    built = lint_paths(project, [write_model(project, box)]).built["thing"]
    mult = shading(built)
    assert mult is not None
    ny = built.normals[..., 1] / np.linalg.norm(built.normals, axis=2)
    assert (ny > 0.99).sum() >= 6 and mult[ny > 0.99].min() == 1.0  # every top corner, edges too
    assert np.allclose(mult[np.abs(ny) < 0.01], 0.7)  # the sides


def test_preview_and_render_carry_the_shade(in_project: Project) -> None:
    from kiln.cli import _built

    write_model(in_project, GROOVED)
    plain = _built(in_project, "thing")
    assert plain.ao is None
    write_model(in_project, GROOVED + SHADE)
    shaded = _built(in_project, "thing")
    assert shaded.ao is not None and shaded.ao.min() < 0.8
    a = np.asarray(render(plain, View(0, 20), 96)).astype(float)
    b = np.asarray(render(shaded, View(0, 20), 96)).astype(float)
    lit = a[..., 3] > 0
    assert b[lit][:, :3].mean() < a[lit][:, :3].mean() - 5


def colour0(project: Project) -> list[np.ndarray]:
    doc, binary = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    return [read_accessor(doc, binary, p["attributes"]["COLOR_0"]) for m in doc["meshes"] for p in m["primitives"] if "COLOR_0" in p["attributes"]]


def test_build_writes_the_multiplier_in_every_colour_mode(project: Project, tmp_path: Path) -> None:
    write_model(project, GROOVED)
    assert not build(project).errors
    assert colour0(project) == []  # off: no COLOR_0, as before
    write_model(project, GROOVED + SHADE)  # a shade-only edit: the cached mesh, a new multiplier
    result = build(project)
    assert not result.errors, result.findings
    assert result.manifest["models"]["thing"]["shade"] == {"cavity": 0.5, "top": 0.2, "under": 0.15}
    grey = np.concatenate(colour0(project))
    assert grey.min() < 0.8 and grey.max() <= 1.0 and np.allclose(grey[:, 0], grey[:, 1])  # a grey multiplier per material
    from kiln.project import load_project

    root = tmp_path / "vc"
    vc = load_project(make_project(root, (project.root / "kiln.toml").read_text() + "\nvertex_colors = true\n").root)
    write_model(vc, GROOVED.replace("color: white", "color: gold") + SHADE)
    assert not build(vc).errors
    rgb = np.concatenate(colour0(vc))
    gold = np.array([0xF2, 0xC1, 0x4E]) / 255
    gold = np.where(gold <= 0.04045, gold / 12.92, ((gold + 0.055) / 1.055) ** 2.4)
    ratio = rgb[:, :3] / gold  # the colours x the multiplier: still gold, darker in places
    assert np.allclose(ratio, ratio[:, :1], atol=1e-3) and ratio.max() <= 1 + 1e-4 and ratio.min() < 0.8


def test_atlas_lods_attr_and_godot_scenes_carry_it(tmp_path: Path) -> None:
    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "art", CONFIG + 'output_dir = "../assets/kiln"\nexport = ["glb", "godot"]\natlas = true\n')
    attr = GROOVED.replace("    color: white\n", "    color: white\n    attr: { heat: 0.5 }\n", 1)
    write_model(project, attr + SHADE + "lod: [300]\n")
    result = build(project)
    assert not result.errors, result.findings
    models = tmp_path / "assets" / "kiln" / "models"
    for glb in ("thing.glb", "thing.lod1.glb"):
        doc, binary = read_glb((models / glb).read_bytes())
        prim = doc["meshes"][0]["primitives"][0]
        rgba = read_accessor(doc, binary, prim["attributes"]["COLOR_0"])
        assert rgba.shape[1] == 4 and np.allclose(rgba[:, 3], 0.5) and rgba[:, 0].min() < 0.8, glb  # shade in RGB, attr in alpha
        assert np.allclose(rgba[:, 0], rgba[:, 2])
    assert "_encode_colours" in (models / "thing.tscn").read_text()  # the scene reads COLOR_0 (Compatibility re-encode too)



def test_a_colour_mapped_model_gets_it_per_texel(tmp_path: Path) -> None:
    """#266: with a base colour map the shade is painted into the map (the groove, the sides and the underside darker)
    and the mapped faces carry no COLOR_0 multiplier on top (no double shading)."""
    import io

    from PIL import Image

    from kiln import bake as bk

    if not bk.available():
        return  # xatlas not installed (kiln-gen[bake])
    faded = GROOVED + "  - sphere: { at: [0, 0.8, 0], radius: 0.1 }\n    color: gold\n    blend: 0.03\n    color_blend: 0.04\n"

    def made(text: str, root: Path) -> tuple[np.ndarray, list[dict[str, Any]]]:
        proj = make_project(root)
        write_model(proj, text)
        assert not build(proj).errors
        doc, _ = read_glb((proj.output_dir / "models" / "thing.glb").read_bytes())
        prims = [p for m in doc["meshes"] for p in m["primitives"] if doc["materials"][p["material"]]["name"].startswith("default_mapped")]
        img = np.asarray(Image.open(io.BytesIO((proj.output_dir / "models" / "thing.color.png").read_bytes())).convert("L"), dtype=float)
        return img, prims

    plain, _ = made(faded, tmp_path / "a")
    shaded, mapped = made(faded + SHADE, tmp_path / "b")
    assert mapped and not any("COLOR_0" in p["attributes"] for p in mapped)
    filled = (plain != 128) & (plain > 40)
    ratio = shaded[filled] / np.maximum(plain[filled], 1)
    assert ratio.max() <= 1.02 and ratio.min() < 0.85 and np.median(ratio) < 0.97  # darker, never lighter (sRGB: 0.85 is ~0.7 linear)
