"""#26: the richer toon look kit (softness, shadow colour, specular, banded shadows, pixel and darkened outlines)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from conftest import CONFIG, make_project, sphere_text, write_model, built_of
from kiln import godot as kg
from kiln.build import build
from kiln.export import Built
from kiln.godot import APPLY_SCRIPT, ATLAS_TOON_SHADER, OUTLINE_SHADER, TOON_SHADER, find_godot_binary, look_scene, model_scene, outline_shader, toon_shader, verify
from kiln.project import Project
from kiln.render import View, render, toon_lit
from kiln.style import Look, load_style

ALL: dict[str, Any] = {"toon_softness": 0.4, "toon_shadow_color": "#5b4f9e", "toon_specular": 0.6, "toon_shadows": "band",
                       "outline_space": "pixels", "outline": 2.0, "outline_color": "darken"}  # fmt: skip

# sha256 (16 hex) of the scenes before #26: (plain scene, variant + atlas textures + revealed scene, look kit)
BEFORE = {
    "toon": ("e12dc238aa7675fa", "c9692274e96417e7", "cc9a4facd8b30e7e"),
    "soft_toy": ("2d956e21e5eb81cd", "8896b25d6213ddd7", "a806d296a38315d5"),
    "low_poly": ("baaee84bee77bb62", "29737b4a8877c374", "06e872ad04478d6c"),
    "clay": ("7ecb346167048d15", "e1e2f90bbec5c042", "07739d29777b490e"),
    "diorama": ("0f4c57b06e3bd633", "78ee193728091fce", "38f6dd597b7843c3"),
}


def _toon() -> Look:
    style, _ = load_style("toon")
    assert style is not None
    return style.look


def test_presets_write_the_same_scenes_as_before() -> None:
    for name, hashes in BEFORE.items():
        style, _ = load_style(name)
        assert style is not None
        scenes = (model_scene("hero", "res://hero.glb", style),
                  model_scene("hero", "res://hero.glb", style, {"#e8413c": "#2f6fd0"}, {"palette": "res://p.png", "rim_texture": "res://r.png"}, ["cap"]),
                  look_scene(style))  # fmt: skip
        assert tuple(hashlib.sha256(s.encode()).hexdigest()[:16] for s in scenes) == hashes, name


def test_defaults_keep_the_plain_shaders() -> None:
    look = _toon()
    assert toon_shader(look, False) == TOON_SHADER and toon_shader(look, True) == ATLAS_TOON_SHADER
    assert outline_shader(look, False) == OUTLINE_SHADER == outline_shader(look, True)


@pytest.mark.parametrize(("keys", "has", "lacks"), [
    ({"toon_softness": 0.3}, ["uniform float softness = 0.3;", "smoothstep(-0.5 * softness"], ["shadow_color", "uniform float specular", "step(0.5, ATTENUATION)", "floor(n * float(bands))"]),
    ({"toon_shadow_color": "#5b4f9e"}, ["uniform vec4 shadow_color : source_color = vec4(0.356863, 0.309804, 0.619608, 1.0);", "shadow_color.rgb * (1.0 - shade)"],
     ["softness", "uniform float specular", "step(0.5, ATTENUATION)"]),
    ({"toon_specular": 0.6}, ["uniform float specular = 0.6;", "ROUGHNESS = roughness;", "halfway", "max(ALBEDO, vec3(0.05))"], ["softness", "shadow_color", "step(0.5"]),
    ({"toon_shadows": "band"}, ["LIGHT_IS_DIRECTIONAL ? step(0.5, ATTENUATION) : ATTENUATION"], ["softness", "shadow_color", "uniform float specular"]),
])  # fmt: skip
def test_each_toon_key_adds_only_its_code(keys: dict[str, Any], has: list[str], lacks: list[str]) -> None:
    text = toon_shader(replace(_toon(), **keys), False)
    for code in has:
        assert code in text, code
    for code in lacks:
        assert code not in text, code
    assert "render_mode specular_disabled;" in text  # the plain toon's ambient stays


def test_atlas_specular_reads_roughness_from_the_material_texture() -> None:
    text = toon_shader(replace(_toon(), toon_specular=0.5), True)
    assert "uniform sampler2D roughness_texture" in text and "ROUGHNESS = roughness * texture(roughness_texture, UV).g;" in text
    style, _ = load_style("toon")
    assert style is not None
    scene = model_scene("hero", "res://hero.glb", replace(style, look=replace(style.look, toon_specular=0.5)), None, {"rim_texture": "res://r.png"})
    assert 'set_shader_parameter(\\"roughness_texture\\", source.roughness_texture)' in scene
    plain = model_scene("hero", "res://hero.glb", replace(style, look=replace(style.look, toon_specular=0.5)))
    assert 'set_shader_parameter(\\"roughness\\", source.roughness)' in plain and "roughness_texture" not in plain


def test_outline_keys() -> None:
    pixels = outline_shader(replace(_toon(), outline_space="pixels", outline=2.0), False)
    assert "POSITION = clip;" in pixels and "VIEWPORT_SIZE" in pixels and "VERTEX += NORMAL * width;" not in pixels
    assert "ALBEDO = color.rgb;" in pixels  # one colour still
    dark = outline_shader(replace(_toon(), outline_color="darken"), False)
    assert "ALBEDO = color.rgb * COLOR.rgb * 0.15;" in dark and "VERTEX += NORMAL * width;" in dark
    assert "texture(albedo_texture, UV)" in outline_shader(replace(_toon(), outline_color="darken"), True)
    style, _ = load_style("toon")
    assert style is not None
    scene = model_scene("hero", "res://hero.glb", replace(style, look=replace(style.look, outline_color="darken")))
    assert "\noutline_color =" not in scene and 'edge.set_shader_parameter(\\"color\\", albedo)' in scene
    assert "\noutline = 2" in model_scene("hero", "res://hero.glb", replace(style, look=replace(style.look, outline_space="pixels", outline=2.0)))
    assert APPLY_SCRIPT.count('edge.set_shader_parameter("color", outline_color)') == 1


@pytest.mark.parametrize(("text", "where"), [
    ("toon_softness = 1.5", "look.toon_softness"),
    ("toon_softness = -0.1", "look.toon_softness"),
    ("toon_specular = 2.0", "look.toon_specular"),
    ("toon_specular = true", "look.toon_specular"),
    ('toon_shadows = "hard"', "look.toon_shadows"),
    ('toon_shadow_color = "#12"', "look.toon_shadow_color"),
    ('toon_shadow_color = "dark blue"', "look.toon_shadow_color"),
    ('outline_space = "inches"', "look.outline_space"),
    ('outline_space = "pixels"\noutline = 0.012', "look.outline"),
    ('outline_color = "darker"', "look.outline_color"),
])  # fmt: skip
def test_bad_toon_values_are_e006(tmp_path: Path, text: str, where: str) -> None:
    (tmp_path / "bad.style.toml").write_text(f'extends = "toon"\n[look]\n{text}\n')
    style, findings = load_style("bad", tmp_path)
    assert style is None and findings and findings[0].rule == "E006" and findings[0].where == where


def test_good_toon_values_load(tmp_path: Path) -> None:
    (tmp_path / "rich.style.toml").write_text('extends = "toon"\n[look]\ntoon_softness = 0.4\ntoon_shadow_color = "blue"\ntoon_specular = 1\n'
                                             'toon_shadows = "band"\noutline_space = "pixels"\noutline = 2\noutline_color = "darken"\n')  # fmt: skip
    style, findings = load_style("rich", tmp_path)
    assert style is not None and findings == []
    assert (style.look.toon_softness, style.look.toon_shadow_color, style.look.toon_specular, style.look.outline_color) == (0.4, "blue", 1.0, "darken")


def _toon_project(project: Project, look: str) -> None:
    (project.root / "styles" / "fast.style.toml").write_text(
        (project.root / "styles" / "fast.style.toml").read_text().replace('"soft_toy"', '"toon"') + f"\n[look]\n{look}\n")


def test_shadow_colour_from_the_palette(project: Project) -> None:
    _toon_project(project, 'toon_shadow_color = "blue"')
    write_model(project, sphere_text())
    _, style, findings = project.load(project.models_dir / "thing.kiln.yaml")
    assert style is not None and findings == [] and style.look.toon_shadow_color == "#2f6fd0"


def test_unknown_palette_shadow_colour_is_e004(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG)
    _toon_project(project, 'toon_shadow_color = "teal"')
    write_model(project, sphere_text())
    model, style, findings = project.load(project.models_dir / "thing.kiln.yaml")
    assert model is None and [f.rule for f in findings] == ["E004"] and findings[0].where == "look.toon_shadow_color"


def test_toon_lit_softness() -> None:
    ndl = np.linspace(-1, 1, 2001)
    hard = toon_lit(ndl, 3)
    assert set(np.round(hard, 6)) == {0.0, 0.5, 1.0}
    soft = toon_lit(ndl, 3, 0.4)
    assert np.all(np.diff(soft) >= -1e-12) and 0 < np.mean((soft > 0.01) & (soft < 0.49)) < 0.2  # monotone, in-betweens near edges
    far = np.abs((np.clip((ndl + 0.15) / 1.15, 0, 0.999) * 3) % 1 - 0.5) < 0.25  # away from every edge: as the hard bands
    np.testing.assert_allclose(soft[far], hard[far])


@pytest.fixture
def toon_ball(project: Project) -> Built:
    _toon_project(project, "")
    return built_of(project, sphere_text() + "  - sphere: { at: [0.25, 0.3, 0.2], radius: 0.12 }\n    color: blue\n    material: glass\n")


def _render(built: Built, **keys: Any) -> np.ndarray:
    original = built.style
    built.style = replace(original, look=replace(original.look, **keys))
    try:
        return np.asarray(render(built, View(30, 20), 96)).astype(int)
    finally:
        built.style = original


def test_render_changes_only_with_a_key_on(toon_ball: Built) -> None:
    today = _render(toon_ball)
    explicit = _render(toon_ball, toon_softness=0.0, toon_shadow_color="", toon_specular=0.0, toon_shadows="soft", outline_space="metres", outline_color=toon_ball.style.look.outline_color)
    assert np.array_equal(today, explicit)
    for keys in ({"toon_softness": 0.4}, {"toon_shadow_color": "#5b4f9e"}, {"toon_specular": 0.8}, {"outline_space": "pixels", "outline": 3.0},
                 {"outline_color": "darken"}, ALL):  # fmt: skip
        assert not np.array_equal(today, _render(toon_ball, **keys)), keys
    # the software renderer has no cast shadows: banded received shadows can't change a preview
    assert np.array_equal(today, _render(toon_ball, toon_shadows="band"))


def test_shadow_colour_tints_the_dark_side_only(toon_ball: Built) -> None:
    today, tinted = _render(toon_ball), _render(toon_ball, toon_shadow_color="#3050f0")
    changed = np.any(today != tinted, axis=2)
    assert changed.sum() > 50
    assert (tinted[..., 2] - today[..., 2])[changed].mean() > 5  # bluer
    lit_top = today[..., :3].sum(axis=2) >= np.percentile(today[..., :3].sum(axis=2)[today[..., 3] > 0], 95)
    assert not np.any(changed & lit_top & (today[..., 3] > 0) & ~changed)  # sanity
    assert np.mean(changed[lit_top & (today[..., 3] > 0)]) < 0.5  # the brightest band mostly untouched


def test_specular_is_a_small_bright_blob_on_smooth_parts(toon_ball: Built) -> None:
    today, shiny = _render(toon_ball), _render(toon_ball, toon_specular=1.0)
    brighter = shiny[..., :3].sum(axis=2) - today[..., :3].sum(axis=2)
    assert (brighter > 30).sum() > 3 and np.all(brighter >= 0)
    assert (brighter > 0).mean() < 0.05


def test_pixel_outlines_keep_their_thickness(toon_ball: Built) -> None:
    def outline_per_length(size: int, **keys: Any) -> float:
        original = toon_ball.style
        try:
            toon_ball.style = replace(original, look=replace(original.look, outline=0.0))
            bare = np.asarray(render(toon_ball, View(30, 20), size)).astype(int)
            toon_ball.style = replace(original, look=replace(original.look, **keys))
            lined = np.asarray(render(toon_ball, View(30, 20), size)).astype(int)
        finally:
            toon_ball.style = original
        return float(np.abs(bare - lined).max(axis=2).sum()) / 255 / size  # outline area (with partial pixels) per unit of silhouette length

    metres = outline_per_length(64), outline_per_length(256)
    pixels = outline_per_length(64, outline_space="pixels", outline=2.0), outline_per_length(256, outline_space="pixels", outline=2.0)
    assert metres[1] / metres[0] > 2  # a shell in metres: thicker in pixels on a bigger render (4x the size)
    assert pixels[1] / pixels[0] < 1.2  # pixels: no thicker on screen (thinner per length: small renders' inner edges crowd)


def test_darkened_outlines_follow_each_part(toon_ball: Built) -> None:
    a = _render(toon_ball, outline_color="darken")
    plain = _render(toon_ball)
    edge = np.any(a != plain, axis=2) & (a[..., 3] > 0)
    colours = {tuple(c) for c in a[edge][:, :3]}
    assert len(colours) >= 2
    reds = a[edge][:, 0] > a[edge][:, 2] + 10
    blues = a[edge][:, 2] > a[edge][:, 0] + 10
    assert reds.any() and blues.any()  # the red ball's outline is dark red, the blue one's dark blue


def _rich_godot_project(tmp_path: Path, extra: str = "") -> Project:
    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "art", CONFIG + 'output_dir = "../assets/kiln"\nexport = ["glb", "godot"]\n' + extra)
    look = "\n".join(f"{k} = {v!r}".replace("'", '"') for k, v in ALL.items())
    _toon_project(project, look)
    write_model(project, sphere_text() + "  - sphere: { at: [0, 0.62, 0], radius: 0.08 }\n    color: gold\n    material: glow\n")
    return project


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
@pytest.mark.parametrize("extra", ["", "atlas = true\n"])
def test_godot_loads_every_toon_key(tmp_path: Path, extra: str) -> None:
    godot = find_godot_binary()
    assert godot is not None
    project = _rich_godot_project(tmp_path, extra)
    result = build(project)
    assert not result.errors and result.godot_root is not None
    scene = (project.output_dir / "models" / "thing.tscn").read_text()
    assert "smoothstep" in scene and "VIEWPORT_SIZE" in scene and "* 0.15;" in scene
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_check_catches_shader_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    godot = find_godot_binary()
    assert godot is not None
    monkeypatch.setattr(kg, "_toon_light", lambda look: "void light() {\n\tDIFFUSE_LIGHT += vec3(no_such_thing);\n}\n")
    project = _rich_godot_project(tmp_path)
    result = build(project)
    assert not result.errors and result.godot_root is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert not check.ok and "SHADER ERROR" in check.output
