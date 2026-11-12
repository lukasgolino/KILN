"""#175: see-through materials (a preset's alpha): glb BLEND, previews dithered, Godot toon alpha, W131 with atlas."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from conftest import CONFIG, FAST_STYLE, built_of, make_project, write_model

from kiln.build import build
from kiln.gltf_check import read_glb
from kiln.godot import APPLY_SCRIPT
from kiln.lint import lint_paths
from kiln.project import Project
from kiln.render import View, render
from kiln.style import load_style

PANE = """\
name: thing
parts:
  - box: { at: [0, 0.3, -0.2], size: [0.6, 0.6, 0.05] }
    color: red
  - box: { at: [0, 0.3, 0.1], size: [0.4, 0.4, 0.02] }
    id: pane
    color: blue
    material: clear
rig:
  pane: { separate: true }
"""


def test_clear_writes_a_blended_material(project: Project) -> None:
    write_model(project, PANE)
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    clear = [m for m in doc["materials"] if m["name"].startswith("clear_")]
    assert clear and clear[0]["alphaMode"] == "BLEND" and clear[0]["pbrMetallicRoughness"]["baseColorFactor"][3] == 0.35
    assert all("alphaMode" not in m for m in doc["materials"] if not m["name"].startswith("clear_"))


def test_the_preview_shows_what_is_behind(project: Project) -> None:
    image = np.asarray(render(built_of(project, PANE), View(), 128)).astype(int)
    middle = image[50:78, 50:78, :3].reshape(-1, 3)
    reds = (middle[:, 0] > 120) & (middle[:, 2] < 90)
    blues = (middle[:, 2] > 120) & (middle[:, 0] < 90)
    assert reds.mean() > 0.3 and blues.mean() > 0.15  # the red board through the dithered pane, and the pane


def test_alpha_is_checked(tmp_path: Path) -> None:
    for bad in ("1.5", "0.0"):
        (tmp_path / "x.style.toml").write_text(f'extends = "soft_toy"\n[materials]\nfog = {{ alpha = {bad} }}\n')
        style, findings = load_style("x", tmp_path)
        assert style is None and any("alpha" in f.message for f in findings), bad


def test_godot_keeps_the_alpha() -> None:
    assert "_see_through(toon_shader)" in APPLY_SCRIPT and "ALPHA = albedo.a" in APPLY_SCRIPT
    assert "Color(swap[hex], source.albedo_color.a)" in APPLY_SCRIPT  # a variant recolour stays see-through


def test_atlas_warns_that_glass_is_opaque(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG + "atlas = true\n")
    (project.root / "styles" / "fast.style.toml").write_text(FAST_STYLE)
    path = write_model(project, PANE)
    found = [f for f in lint_paths(project, [path], geometry=False).findings if f.rule == "W131"]
    assert len(found) == 1 and "clear" in found[0].message
