"""#233: the skin style preset; #262: a style's [shape] color_blend default."""

from __future__ import annotations

from pathlib import Path

from conftest import make_project, write_model

from kiln.lint import lint_paths
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
    assert style is not None and not findings
    assert style.shade.on and style.color_blend == 0.03
    assert all(m.rim == 0 for m in style.materials.values()) and style.materials["default"].roughness >= 0.8  # matte, no rim


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


def test_it_builds_and_the_default_raises_no_w127(tmp_path: Path) -> None:
    project = make_project(tmp_path / "p")
    text = CRITTER.replace("STYLE", "skin").replace("EOF_PART\n", "") + "relief:\n  - { on: [body, head], length: 0.07, width: 0.035, lift: 0.006 }\n"
    result = lint_paths(project, [write_model(project, text)])
    assert not result.errors, result.findings
    assert "W127" not in [f.rule for f in result.findings]
    built = result.built["thing"]
    lay = built.bake.layers
    assert lay is not None and lay.mix is not None and (lay.mix > 0).sum() > 100  # the belly fades
    assert built.ao is None  # (previews add the shade; the build writes it into COLOR_0)


def test_style_color_blend_errors(tmp_path: Path) -> None:
    (tmp_path / "x.style.toml").write_text('extends = "soft_toy"\n[shape]\ncolor_blend = 2\n')
    style, findings = load_style("x", tmp_path)
    assert style is None and [f.where for f in findings] == ["shape.color_blend"]
