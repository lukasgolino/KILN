"""#233: the skin style preset; #262: a style's [shape] color_blend default."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from conftest import make_project, write_model

from kiln.lint import lint_paths
from kiln.project import Project
from kiln.style import load_style

CRITTER = """\
name: thing
class: creature
style: STYLE
parts:
  - ellipsoid: { at: [0, 0.45, 0], radii: [0.28, 0.4, 0.24] }
    id: body
    color: wood
  - ellipsoid: { at: [0, 0.42, 0.14], radii: [0.18, 0.26, 0.13] }
    id: belly
    color: gold
    blend: 0.06
  - sphere: { at: [0, 0.98, 0.02], radius: 0.2 }
    id: head
    color: wood
    blend: 0.08
  - sphere: { at: [0.07, 1.02, 0.18], radius: 0.03 }
    id: eye
    color: white
EOF_PART
"""


def test_the_preset_turns_the_look_on() -> None:
    style, findings = load_style("skin")
    toy, _ = load_style("soft_toy")
    assert style is not None and toy is not None and not findings
    assert style.shade.on and style.color_blend == 0.03
    assert toy.materials["skin"].rim > 0 and style.materials["skin"].rim == 0  # matte skin, no rim (soft_toy's has one)
    assert style.materials["default"].roughness >= 0.8
    assert set(toy.materials) <= set(style.materials)  # every material the other presets offer (api.tree uses leaf)


def test_a_style_color_blend_fades_blended_parts_only(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    model, _, findings = project.load(write_model(project, CRITTER.replace("STYLE", "skin").replace("EOF_PART\n", "")))
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    by_id = {p.id: p.color_blend for p in model.parts}
    assert by_id == {"body": 0.0, "belly": 0.03, "head": 0.03, "eye": 0.0}  # the first part and a crisp eye don't fade
    assert model.normal_map == 1024  # the colour map comes on
    model, _, _ = project.load(write_model(project, CRITTER.replace("STYLE", "skin").replace("EOF_PART\n", "    color_blend: 0\n")))
    assert model is not None and model.parts[3].color_blend == 0.0  # (the eye said so)
    model, _, _ = project.load(write_model(project, CRITTER.replace("STYLE", "skin").replace("    blend: 0.06\n", "    blend: 0.06\n    color_blend: 0\n").replace("EOF_PART\n", "")))
    assert model is not None and model.parts[1].color_blend == 0.0  # a part's own 0 wins
    model, _, _ = project.load(write_model(project, CRITTER.replace("STYLE", "soft_toy").replace("EOF_PART\n", "")))
    assert model is not None and all(p.color_blend == 0 for p in model.parts) and not model.normal_map  # other styles: as before


FAST = 'extends = "skin"\n[shape]\nresolution = 0.02\n'  # the preset, coarser: quicker builds in tests


def fast_project(tmp_path: Path, extra: str = "") -> Project:
    project = make_project(tmp_path / "p")
    (project.root / "styles" / "fastskin.style.toml").write_text(FAST + extra)
    return project


def test_it_builds_and_an_explicit_zero_stays_crisp(tmp_path: Path) -> None:
    project = fast_project(tmp_path)
    small = "class: creature\nnormal_map: 256\n"  # small maps: quick
    text = CRITTER.replace("class: creature\n", small).replace("STYLE", "fastskin").replace("EOF_PART\n", "") + "relief:\n  - { on: [body, head], length: 0.07, width: 0.035, lift: 0.006 }\n"
    result = lint_paths(project, [write_model(project, text)])
    assert not result.errors, result.findings
    assert "W127" not in [f.rule for f in result.findings]
    lay = result.built["thing"].bake.layers
    assert lay is not None and lay.mix is not None and (lay.mix > 0).sum() > 100  # the belly fades
    snout = CRITTER.replace("class: creature\n", small).replace("STYLE", "fastskin").replace("EOF_PART\n", "    blend: 0.03\n    color_blend: 0\n")  # the eye blends, says 0
    built = lint_paths(project, [write_model(project, snout)]).built["thing"]
    lay = built.bake.layers
    eye = [g for g, grp in enumerate(built.painted.groups) if grp.color_name.split("#")[0] == "white"]
    assert eye
    assert lay is not None and lay.other is not None
    assert not np.isin(lay.other[lay.mix > 0], eye).any()  # nothing fades toward the eye ...
    assert not np.isin(lay.group[lay.mix > 0], eye).any()  # ... nor on it


def test_hard_parts_and_one_colour_models_get_no_maps(tmp_path: Path) -> None:
    project = fast_project(tmp_path, 'hard_surface = "always"\n')  # (under FAST's [shape])
    boxes = "name: thing\nstyle: fastskin\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: wood\n" \
            "  - box: { at: [0, 0.5, 0], size: [0.3, 0.3, 0.3] }\n    color: gold\n    blend: 0.03\n"
    model, _, _ = project.load(write_model(project, boxes))
    assert model is not None and all(p.color_blend == 0 for p in model.parts) and not model.normal_map  # made hard: crisp
    plain = make_project(tmp_path / "q")
    (plain.root / "styles" / "fastskin.style.toml").write_text(FAST)
    one = CRITTER.replace("STYLE", "fastskin").replace("EOF_PART\n", "").replace("color: gold", "color: wood").replace("color: white", "color: wood")
    model, _, _ = plain.load(write_model(plain, one))
    assert model is not None and not model.normal_map  # one colour: nothing to fade, no bake


def test_style_color_blend_errors(tmp_path: Path) -> None:
    (tmp_path / "x.style.toml").write_text('extends = "soft_toy"\n[shape]\ncolor_blend = 2\n')
    style, findings = load_style("x", tmp_path)
    assert style is None and [f.where for f in findings] == ["shape.color_blend"]
