"""#329: a material's grain: a fine bumpy finish in the normals (rough cloth), no geometry."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from conftest import make_project, write_model

from kiln.godot import look_scene, model_scene
from kiln.lint import lint_paths
from kiln.render import View, render
from kiln.style import load_style


def test_grain_parses_and_reaches_the_godot_scene(tmp_path: Path) -> None:
    (tmp_path / "felt.style.toml").write_text('extends = "soft_toy"\n[materials.felt]\nroughness = 0.9\ngrain = 0.5\ngrain_size = 0.006\n')
    style, findings = load_style("felt", tmp_path)
    assert style is not None and not findings and style.materials["felt"].grain == 0.5
    (tmp_path / "bad.style.toml").write_text('extends = "soft_toy"\n[materials.felt]\ngrain = 2.0\n')
    _, findings = load_style("bad", tmp_path)
    assert any(f.where == "materials.felt" for f in findings)
    assert 'grains = {"felt": [0.5, 0.006]}' in model_scene("thing", "res://thing.glb", style)
    assert look_scene(style)


def test_the_preview_shows_the_grain(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    built = lint_paths(project, [write_model(project, "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: white\n")]).built["thing"]
    plain = np.asarray(render(built, View(20.0, 15.0), 128))[..., :3].astype(float)
    style = built.style
    built.style = replace(style, materials={**style.materials, "default": replace(style.materials["default"], grain=0.8, grain_size=0.01)})
    grainy = np.asarray(render(built, View(20.0, 15.0), 128))[..., :3].astype(float)
    body = plain.sum(axis=2) > 0
    assert np.abs(grainy - plain)[body].mean() > 2.0  # bumps show on the sphere


@pytest.mark.slow
def test_godot_loads_a_grainy_material(tmp_path: Path) -> None:


    from kiln.build import build
    from kiln.godot import find_godot_binary, verify

    godot = find_godot_binary()
    if godot is None:
        pytest.skip("needs a Godot 4 binary (GODOT=/path)")
    project = make_project(tmp_path, 'default_style = "felt"\ndefault_palette = "main"\noutput_dir = "game/assets/kiln"\nexport = ["glb", "godot"]\n')
    (tmp_path / "styles" / "felt.style.toml").write_text('extends = "soft_toy"\n[materials.felt]\nroughness = 0.9\ngrain = 0.5\ngrain_size = 0.006\n')
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text('config_version=5\n[application]\nconfig/name="t"\n')
    from kiln.project import load_project

    project = load_project(tmp_path)
    write_model(project, "name: ball\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: white\n    material: felt\n", "ball")
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    assert result.godot_root is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]


@pytest.mark.slow
def test_godot_variant_scene_recolours_glow_with_the_cap(tmp_path: Path) -> None:
    """#288: a variant scene that recolours by the swap table (no variant glbs) caps and dims the glow as the glb does;
    the script loads in Godot."""
    from kiln.build import build
    from kiln.godot import find_godot_binary, verify
    from kiln.project import load_project

    godot = find_godot_binary()
    if godot is None:
        pytest.skip("needs a Godot 4 binary (GODOT=/path)")
    make_project(tmp_path, 'default_style = "soft_toy"\ndefault_palette = "main"\noutput_dir = "game/assets/kiln"\nexport = ["glb", "godot"]\n')
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text('config_version=5\n[application]\nconfig/name="t"\n')
    project = load_project(tmp_path)
    write_model(project, "name: lamp\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: gold\n    material: glow\nvariants:\n  w: { swap: { gold: white } }\n", "lamp")
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    scene = (project.output_dir / "models" / "lamp.w.tscn").read_text()
    assert "emissions = {" in scene and "glow_peak = 0.75" in scene  # soft_toy: filmic, exposure 1
    assert result.godot_root is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
