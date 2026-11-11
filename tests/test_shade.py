"""#231 shade paint: darker in crevices, lighter on top, darker underneath, as a COLOR_0 multiplier in any colour mode."""

from __future__ import annotations

import numpy as np
from conftest import load, make_project, write_model

from kiln.atlas import vertex_normals
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


def test_style_shade_table(tmp_path: object) -> None:
    from pathlib import Path

    from kiln.style import load_style

    styles = Path(str(tmp_path))
    (styles / "mine.style.toml").write_text('extends = "soft_toy"\n[shade]\ncavity = 0.25\ntop = 0.12\n')
    style, findings = load_style("mine", styles)
    assert style is not None and not findings and style.shade == Shade(0.25, 0.12, 0.0)
    (styles / "bad.style.toml").write_text('extends = "soft_toy"\n[shade]\ncavity = 3\n')
    style, findings = load_style("bad", styles)
    assert style is None and [f.where for f in findings] == ["shade"]


def test_the_groove_is_darker(project: Project) -> None:
    built = lint_paths(project, [write_model(project, GROOVED + "shade: { cavity: 0.8 }\n")]).built["thing"]
    mult = shading(built)
    assert mult is not None and 0 < mult.min() and mult.max() <= 1
    used = np.unique(built.painted.faces)
    r = np.linalg.norm(built.painted.vertices[used] - [0, 0.5, 0], axis=1)
    groove, rest = r < 0.29, r >= 0.295  # inside the cut / the sphere's surface
    assert groove.any() and rest.any()
    assert mult[used][groove].mean() < mult[used][rest].mean() - 0.05
    plain = lint_paths(project, [write_model(project, GROOVED)]).built["thing"]
    assert shading(plain) is None  # off by default


def test_the_top_keeps_its_colour_the_sides_darken_the_underside_most(project: Project) -> None:
    built = lint_paths(project, [write_model(project, GROOVED + "shade: { top: 0.2, under: 0.15 }\n")]).built["thing"]
    mult = shading(built)
    assert mult is not None
    used = np.unique(built.painted.faces)
    ny, m = vertex_normals(built)[used, 1], mult[used]
    assert np.allclose(m, (1 - 0.2 * (1 - np.maximum(ny, 0))) * (1 - 0.15 * np.maximum(-ny, 0)), atol=1e-4)
    assert m[ny > 0.95].min() > 0.99 and m[ny < -0.95].max() < 0.7


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


def test_build_writes_the_multiplier_in_every_colour_mode(project: Project, tmp_path: object) -> None:
    write_model(project, GROOVED)
    assert not build(project).errors
    assert colour0(project) == []  # off: no COLOR_0, as before
    write_model(project, GROOVED + SHADE)
    result = build(project)
    assert not result.errors, result.findings
    assert result.manifest["models"]["thing"]["shade"] == {"cavity": 0.5, "top": 0.2, "under": 0.15}
    grey = np.concatenate(colour0(project))
    assert grey.min() < 0.8 and grey.max() <= 1.0 and np.allclose(grey[:, 0], grey[:, 1])  # a grey multiplier per material
    from pathlib import Path

    from kiln.project import load_project

    root = Path(str(tmp_path)) / "vc"
    vc = load_project(make_project(root, (project.root / "kiln.toml").read_text() + "\nvertex_colors = true\n").root)
    write_model(vc, GROOVED.replace("color: white", "color: gold") + SHADE)
    assert not build(vc).errors
    rgb = np.concatenate(colour0(vc))
    gold = np.array([0xF2, 0xC1, 0x4E]) / 255
    gold = np.where(gold <= 0.04045, gold / 12.92, ((gold + 0.055) / 1.055) ** 2.4)
    ratio = rgb[:, :3] / gold  # the colours x the multiplier: still gold, darker in places
    assert np.allclose(ratio, ratio[:, :1], atol=1e-3) and ratio.max() <= 1 + 1e-4 and ratio.min() < 0.8
