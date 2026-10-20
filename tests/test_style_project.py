"""Style presets and files, kiln.toml and project discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import load, make_project, sphere_text
from kiln.project import Config, find_project_root, load_project, parse_config
from kiln.style import builtin_names, load_style, style_summary
from pagan.findings import PaganError


def test_builtin_presets_load() -> None:
    names = builtin_names()
    assert {"soft_toy", "low_poly", "toon", "clay", "diorama"} <= set(names)
    for name in names:
        style, findings = load_style(name)
        assert style is not None, [f.format() for f in findings]
        assert findings == []
        assert style.description and "default" in style.materials
        assert style.budget("character") >= 12
        assert style_summary(style)["name"] == name


def test_preset_differences() -> None:
    low, _ = load_style("low_poly")
    toon, _ = load_style("toon")
    assert low is not None and toon is not None
    assert not low.smooth and low.budget("prop") == 400
    assert toon.look.shader == "toon" and toon.look.outline > 0
    assert toon.smooth and toon.budget("character") == 8000  # inherited from soft_toy


def test_unknown_class_uses_default_budget() -> None:
    style, _ = load_style("soft_toy")
    assert style is not None
    assert style.budget("spaceship") == style.budgets["default"]


def test_extends_merges_tables(tmp_path: Path) -> None:
    (tmp_path / "mine.style.toml").write_text(
        'description = "mine"\nextends = "toon"\n[shape]\nresolution = 0.02\n[materials]\nslime = { roughness = 0.2, emission = 0.5 }\n'
        "[look]\nsaturation = 1.5\n"
    )
    style, findings = load_style("mine", tmp_path)
    assert style is not None, findings
    assert style.resolution == 0.02
    assert style.look.shader == "toon" and style.look.saturation == 1.5  # from toon + own
    assert style.materials["slime"].emission == 0.5
    assert style.materials["plastic"].roughness == 0.42  # from soft_toy, two levels up
    assert style.path == tmp_path / "mine.style.toml"


def test_project_style_can_extend_the_preset_of_the_same_name(tmp_path: Path) -> None:
    (tmp_path / "soft_toy.style.toml").write_text('extends = "soft_toy"\n[look]\noutline = 0.01\n')
    style, findings = load_style("soft_toy", tmp_path)
    assert style is not None, findings
    assert style.look.outline == 0.01 and style.budget("character") == 8000


@pytest.mark.parametrize(
    ("text", "where"),
    [
        ("colour = 1\n", "colour"),
        ("[shape]\nsmooth = 1\n", "shape.smooth"),
        ("[shape]\nresolution = 5.0\n", "shape.resolution"),
        ("[shape]\nsharp_angle = 270\n", "shape.sharp_angle"),
        ("[shape]\nsize = 1\n", "shape.size"),
        ("[budgets]\nprop = 3\n", "budgets"),
        ("[materials]\nslime = { wetness = 1 }\n", "materials.slime"),
        ("[look]\nshader = \"pbr\"\n", "look.shader"),
        ("[look]\ntonemapper = \"magic\"\n", "look.tonemapper"),
        ("[look]\nsky_top = \"blue\"\n", "look.sky_top"),
        ("[look]\nssao = \"yes\"\n", "look.ssao"),
        ("[look]\nshine = 1\n", "look.shine"),
        ("extends = \"bad\"\n", ""),
        ("extends = \"bad\"\n[[x\n", ""),
    ],
)
def test_bad_style_values_are_e006(tmp_path: Path, text: str, where: str) -> None:
    (tmp_path / "bad.style.toml").write_text(text)
    style, findings = load_style("bad", tmp_path)
    assert style is None
    assert findings and all(f.rule == "E006" for f in findings)
    if where:
        assert findings[0].where == where


def test_unknown_style_lists_the_known_ones(tmp_path: Path) -> None:
    style, findings = load_style("nope", tmp_path)
    assert style is None
    assert findings[0].rule == "E006" and "soft_toy" in findings[0].message


def test_model_with_unknown_style_reports_e006(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    model, style, findings = load(project, sphere_text() + "style: nope\n")
    assert model is None and style is None
    assert findings[0].rule == "E006" and findings[0].path == project.models_dir / "thing.kiln.yaml"


def test_model_names_its_own_style_and_palette(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    (tmp_path / "palettes" / "alt.pal.yaml").write_text('name: alt\ncolors:\n  "0": { hex: "#010203", name: red }\n')
    model, style, findings = load(project, sphere_text() + "style: low_poly\npalette: alt  # comment\n")
    assert model is not None and style is not None, findings
    assert style.name == "low_poly" and model.parts[0].color == "#010203"


def test_parse_config_defaults_and_values() -> None:
    cfg, findings = parse_config({}, None)
    assert findings == [] and cfg == Config()
    cfg, findings = parse_config({"default_style": "toon", "default_palette": "main", "output_dir": "out", "preview_dir": "pv",
                                  "export": ["glb", "godot"], "style_version": 3, "lint": {"disable": ["W106"]}}, None)  # fmt: skip
    assert findings == []
    assert (cfg.default_style, cfg.default_palette, cfg.output_dir, cfg.preview_dir) == ("toon", "main", "out", "pv")
    assert cfg.export == ("glb", "godot") and cfg.style_version == 3 and cfg.lint_disable == ("W106",)


@pytest.mark.parametrize(
    ("data", "where"),
    [
        ({"colour": 1}, "colour"), ({"default_style": "Big!"}, "default_style"), ({"default_palette": 3}, "default_palette"),
        ({"output_dir": ""}, "output_dir"), ({"export": ["fbx"]}, "export"), ({"export": []}, "export"),
        ({"style_version": 0}, "style_version"), ({"style_version": True}, "style_version"),
        ({"lint": {"disable": ["E003"]}}, "lint"), ({"lint": {"enable": []}}, "lint"),
    ],
)  # fmt: skip
def test_parse_config_rejects(data: dict[str, object], where: str) -> None:
    _, findings = parse_config(data, Path("kiln.toml"))
    assert [f.where for f in findings] == [where]
    assert findings[0].rule == "E000"


def test_load_project_errors(tmp_path: Path) -> None:
    (tmp_path / "kiln.toml").write_text("export = [\n")
    with pytest.raises(PaganError) as exc:
        load_project(tmp_path)
    assert "invalid TOML" in exc.value.findings[0].message
    (tmp_path / "kiln.toml").write_text('export = ["fbx"]\n')
    with pytest.raises(PaganError):
        load_project(tmp_path)


def test_project_found_from_a_subfolder(tmp_path: Path) -> None:
    make_project(tmp_path)
    path = tmp_path / "models" / "thing.kiln.yaml"
    path.write_text(sphere_text())
    assert find_project_root(path) == tmp_path
    project = load_project(start=path)
    assert project.root == tmp_path.resolve() and project.config.default_style == "fast"
    assert project.output_dir == (tmp_path / "build").resolve()


def test_open_mode_without_kiln_toml(tmp_path: Path) -> None:
    models = tmp_path / "loose" / "models"
    models.mkdir(parents=True)
    path = models / "thing.kiln.yaml"
    path.write_text("name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: '#ff0000'\n")
    project = load_project(start=path)
    assert project.config_path is None
    assert project.root == (tmp_path / "loose").resolve()  # a models/ folder's parent
    assert project.config == Config()
    model, style, findings = project.load(path)
    assert model is not None and style is not None and style.name == "soft_toy", findings
    assert project.palette() == ({}, [])
    assert project.model_paths() == [path]


def test_extends_cycle_is_e006(tmp_path: Path) -> None:
    (tmp_path / "a.style.toml").write_text('extends = "b"\n')
    (tmp_path / "b.style.toml").write_text('extends = "a"\n')
    style, findings = load_style("a", tmp_path)
    assert style is None
    assert findings[0].rule == "E006" and "no cycles" in findings[0].message
