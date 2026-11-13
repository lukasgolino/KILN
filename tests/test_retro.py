"""#358: the retro post pass ([look] post = "retro"): low resolution, a fixed palette, ordered dithering."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import CONFIG, make_project, sphere_text, write_model

from kiln import post
from kiln.build import build
from kiln.godot import find_godot_binary, look_scene, verify
from kiln.project import Project
from kiln.style import Look, load_style

CGA = """\
name: cga
colors:
  "0": { hex: "#000000", name: black }
  "1": { hex: "#55ffff", name: cyan }
  "2": { hex: "#ff55ff", name: magenta }
  "3": { hex: "#ffffff", name: white }
"""
RETRO = '\n[look]\npost = "retro"\npost_palette = "cga"\n'


def _retro_project(root: Path, look: str = RETRO, extra: str = "") -> Project:
    project = make_project(root, CONFIG + extra)
    (project.root / "palettes" / "cga.pal.yaml").write_text(CGA)
    (project.root / "styles" / "fast.style.toml").write_text((project.root / "styles" / "fast.style.toml").read_text() + look)
    write_model(project, sphere_text())
    return project


def test_defaults_are_off_and_scenes_unchanged() -> None:
    look = Look()
    assert look.post == "" and look.post_colors == ()
    style, _ = load_style("low_poly")
    assert style is not None and "Retro" not in look_scene(style)


@pytest.mark.parametrize(("text", "where"), [
    ('post = "crt"', "look.post"),
    ('post = "retro"', "look.post_palette"),
    ('dither = "spiral"', "look.dither"),
    ("post_lines = 8", "look.post_lines"),
    ("pixel_aspect = 0", "look.pixel_aspect"),
    ("dither_strength = 1.5", "look.dither_strength"),
    ("post_colors = []", "look.post_colors"),
])  # fmt: skip
def test_bad_values_are_e006(tmp_path: Path, text: str, where: str) -> None:
    (tmp_path / "bad.style.toml").write_text(f'extends = "low_poly"\n[look]\n{text}\n')
    style, findings = load_style("bad", tmp_path)
    assert style is None and findings and findings[0].rule == "E006" and findings[0].where == where


def test_project_reads_the_palette(tmp_path: Path) -> None:
    project = _retro_project(tmp_path)
    _, style, findings = project.load(project.models_dir / "thing.kiln.yaml")
    assert findings == [] and style is not None
    assert style.look.post_colors == ("#000000", "#55ffff", "#ff55ff", "#ffffff")


def test_unknown_or_big_palette_is_e006(tmp_path: Path) -> None:
    project = _retro_project(tmp_path / "a", RETRO.replace('"cga"', '"nope"'))
    style, findings = project.style()
    assert style is None and findings[0].rule == "E006" and findings[0].where == "look.post_palette" and "nope" in findings[0].message
    project = _retro_project(tmp_path / "b", RETRO.replace('"cga"', '"big"'))
    rows = "\n".join(f'  "{k}": "#{i:02x}{i:02x}{i:02x}"' for i, k in enumerate("0123456789abcdefg"))
    (project.root / "palettes" / "big.pal.yaml").write_text(f"name: big\ncolors:\n{rows}\n")
    style, findings = project.style()
    assert style is None and "17 colours" in findings[0].message


def test_look_scene_has_the_pass(tmp_path: Path) -> None:
    style, findings = _retro_project(tmp_path).style()
    assert style is not None and not findings
    scene = look_scene(style)
    for text in ('[node name="Retro" type="CanvasLayer"', "mouse_filter = 2", "hint_screen_texture", "shader_parameter/count = 4",
                 "0.333333, 1.0, 1.0", "shader_parameter/pattern = 0", 'script = SubResource("GDScript_retro")',
                 "func set_palette", "resource_local_to_scene = true"):  # fmt: skip
        assert text in scene, text


def test_bayer_matrices() -> None:
    for n in (2, 4, 8):
        m = post.bayer(n)
        assert sorted(m.flatten()) == list(range(n * n))
    assert post.bayer(4).tolist() == [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]  # render.BAYER's
    assert post.thresholds("none").tolist() == [[1.0]]


def _look(colors: tuple[str, ...], **keys: object) -> Look:
    from dataclasses import replace

    return replace(Look(post="retro", post_palette="p", post_colors=colors, post_lines=10, pixel_aspect=1.0), **keys)  # type: ignore[arg-type]


def test_retro_only_draws_palette_colours_in_blocks() -> None:
    rng = np.random.default_rng(1)
    image = rng.random((40, 60, 3))
    look = _look(("#000000", "#55ffff", "#ff55ff", "#ffffff"))
    out = post.retro(image, look)
    colours = {tuple(np.round(c * 255).astype(int)) for c in out.reshape(-1, 3)}
    assert colours <= {(0, 0, 0), (85, 255, 255), (255, 85, 255), (255, 255, 255)}
    blocks = out.reshape(10, 4, 15, 4, 3)  # 10 lines of 4 px, square pixels
    assert (blocks == blocks[:, :1, :, :1]).all()


def test_retro_dithers_in_proportion() -> None:
    look = _look(("#000000", "#ffffff"), post_lines=64)
    for level in (0.25, 0.5, 0.75):
        out = post.retro(np.full((64, 64, 3), level), look)
        assert abs(out[..., 0].mean() - level) < 1 / 16 + 1e-9
    flat = post.retro(np.full((64, 64, 3), 0.4), _look(("#000000", "#ffffff"), post_lines=64, dither="none"))
    assert set(np.unique(flat)) == {0.0}
    half = post.retro(np.full((64, 64, 3), 0.5), _look(("#000000", "#ffffff"), post_lines=64, dither_strength=0.5))
    assert 0 < half.mean() < 0.5


def test_pixel_aspect_widens_blocks() -> None:
    look = _look(("#000000", "#ffffff"), post_lines=2, pixel_aspect=2.0)
    image = np.zeros((4, 8, 3))
    image[:, 4:] = 1.0
    out = post.retro(image, look)
    assert post.block_size(4, look) == (4.0, 2.0)
    assert (out[:, :4] == 0).all() and (out[:, 4:] == 1).all()


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
@pytest.mark.parametrize("dither", ["bayer4", "bayer8", "none"])
def test_godot_loads_the_pass(tmp_path: Path, dither: str) -> None:
    godot = find_godot_binary()
    assert godot is not None
    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = _retro_project(tmp_path / "art", RETRO + f'dither = "{dither}"\ndither_strength = 0.5\n',
                             extra='output_dir = "../assets/kiln"\nexport = ["glb", "godot"]\n')
    result = build(project)
    assert not result.errors and result.godot_root is not None
    assert "Retro" in (project.output_dir / "looks" / "fast.tscn").read_text()
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_check_catches_post_shader_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln import godot as kg

    godot = find_godot_binary()
    assert godot is not None
    monkeypatch.setattr(kg, "post_shader", lambda look: "shader_type canvas_item;\nvoid fragment() {\n\tCOLOR = vec4(no_such_thing);\n}\n")
    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = _retro_project(tmp_path / "art", extra='output_dir = "../assets/kiln"\nexport = ["glb", "godot"]\n')
    result = build(project)
    assert result.godot_root is not None
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert not check.ok and "SHADER ERROR" in check.output


def test_previews_draw_the_pass(tmp_path: Path) -> None:
    from kiln import render as rd
    from kiln.builder import build_model
    from kiln.render import View, render

    project = _retro_project(tmp_path)
    model, style, findings = project.load(project.models_dir / "thing.kiln.yaml")
    assert model is not None and style is not None and not findings
    built = build_model(model, style)
    allowed = {(0, 0, 0), (85, 255, 255), (255, 85, 255), (255, 255, 255)}
    image = np.asarray(render(built, View(30.0, 15.0), 200, background=(40, 40, 40, 255)))
    assert {tuple(int(v) for v in c) for c in image[..., :3].reshape(-1, 3)} <= allowed
    assert (np.asarray(render(built, View(30.0, 15.0), 200, background=(40, 40, 40, 255), post=False)) != image).any()
    rd.POST = False
    try:
        raw = np.asarray(render(built, View(30.0, 15.0), 200, background=(40, 40, 40, 255)))
        assert len({tuple(int(v) for v in c) for c in raw[..., :3].reshape(-1, 3)}) > 4
    finally:
        rd.POST = True


@pytest.mark.parametrize(("name", "colours", "lines"), [("retro_cga", 4, 200), ("retro_st", 16, 200), ("retro_mono", 2, 400)])
def test_presets_and_init(tmp_path: Path, name: str, colours: int, lines: int) -> None:
    from kiln.cli import main
    from kiln.project import load_project

    assert main(["init", str(tmp_path / "p"), "--style", name]) == 0
    project = load_project(start=tmp_path / "p")
    style, findings = project.style()
    assert style is not None and not findings
    assert style.look.post == "retro" and style.look.post_lines == lines and len(style.look.post_colors) == colours
    main_palette, pf = project.palette("main")
    assert not pf and {h.lower() for h in main_palette.values()} == set(style.look.post_colors)  # models paint in legal colours
    write_model(project, sphere_text().replace("color: red", "color: black"))
    model, _, mf = project.load(project.models_dir / "thing.kiln.yaml")
    assert model is not None and not mf


def test_hardware_palette_rules_in_kiln(tmp_path: Path) -> None:
    from kiln.vendor.palette import parse_palette
    from kiln.vendor.yamlio import parse_yaml

    pal, findings = parse_palette(parse_yaml('name: p\nhardware: atari-st\ncolors:\n  "0": "#123456"\n'))
    assert pal is None and findings[0].rule == "E004" and "nearest is #242449" in findings[0].message
    pal, findings = parse_palette(parse_yaml('name: p\nhardware: cga\ncolors:\n  "0": "#000000"\n  "1": "#ffffff"\n'))
    assert pal is not None and pal.hardware == "cga" and not findings


def test_float_literals_and_none_thresholds() -> None:
    from dataclasses import replace

    assert post._float(1.0) == "1.0" and post._float(0.03125) == "0.03125" and post._float(1e-7) == "1e-07"
    assert "float[16](0.0, 8.0," in post.SHADER and "float[4](0.0, 2.0, 1.0, 3.0)" in post.SHADER
    look = replace(_look(("#000000", "#ffffff")), dither="none")
    assert "shader_parameter/pattern = 2" in post.material_params(look)


def test_blocks_never_shrink_below_a_pixel() -> None:
    look = _look(("#000000", "#ffffff"), post_lines=400)
    assert post.block_size(150, look) == (1.0, 1.0)
    for size in (150, 300):  # shorter than post_lines: the tile's own pixels, every dither cell used
        out = post.retro(np.full((size, size, 3), 0.25), look)
        assert abs(out[..., 0].mean() - 0.25) < 0.02


def test_alpha_is_snapped() -> None:
    image = np.zeros((10, 10, 4))
    image[..., 3] = np.linspace(0, 1, 10)[None, :]
    out = post.retro(image, _look(("#000000", "#ffffff")))
    assert set(np.unique(out[..., 3])) == {0.0, 1.0}


@pytest.mark.parametrize("pattern", post.PATTERNS)
def test_every_pattern_dithers_in_proportion(pattern: str) -> None:
    look = _look(("#000000", "#ffffff"), post_lines=64, dither=pattern)
    thr = post.threshold(pattern, np.arange(64)[None, :], np.arange(64)[:, None])
    assert thr.shape == (64, 64) and ((thr > 0) & (thr <= 1)).all()
    if pattern == "none":
        return
    for level in (0.25, 0.5, 0.75):  # about that share of white cells for that grey
        out = post.retro(np.full((64, 64, 3), level), look)
        assert abs(out[..., 0].mean() - level) < 0.12, (pattern, level, out[..., 0].mean())


def test_shader_names_every_pattern_in_order() -> None:
    for i, name in enumerate(post.PATTERNS):
        assert f"{i} {name}" in post.SHADER
    assert set(post.PATTERNS) == set(__import__("kiln.style", fromlist=["DITHERS"]).DITHERS)
