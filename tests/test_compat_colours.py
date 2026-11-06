"""#124: vertex colours in Godot's Compatibility renderer (decoded from sRGB once more there) match the material colours."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import make_project, sphere_text, write_model
from test_build import PROJECT_GODOT

from kiln.build import build
from kiln.godot import find_godot_binary, verify

REPO = Path(__file__).resolve().parent.parent
CONFIG = 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "game/assets/{out}"\nexport = ["glb", "godot"]\n'


def coloured_project(root: Path, vertex_colors: bool, out: str = "kiln") -> Path:
    project = make_project(root, CONFIG.format(out=out) + f"vertex_colors = {'true' if vertex_colors else 'false'}\n")
    (root / "game").mkdir(exist_ok=True)
    (root / "game" / "project.godot").write_text(PROJECT_GODOT)
    write_model(project, sphere_text("ball"), "ball")
    result = build(project)
    assert result.errors == []
    return root / "game"


def test_only_coloured_glbs_get_the_compat_encode(tmp_path: Path) -> None:
    game = coloured_project(tmp_path / "a", True)
    assert "_encode_colours(mesh_instance.mesh)" in (game / "assets/kiln/models/ball.tscn").read_text()
    game = coloured_project(tmp_path / "b", False)
    assert "_encode_colours" not in (game / "assets/kiln/models/ball.tscn").read_text()  # other scenes as they were


def test_baked_occlusion_gets_the_compat_encode(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG.format(out="kiln") + "atlas = true\natlas_ao = 0.5\n")
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text(PROJECT_GODOT)
    write_model(project, sphere_text("ball"), "ball")
    assert build(project).errors == []
    assert "_encode_colours(mesh_instance.mesh)" in (tmp_path / "game/assets/kiln/models/ball.tscn").read_text()


@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_parses_the_compat_encode(tmp_path: Path) -> None:
    game = coloured_project(tmp_path, True)
    godot = find_godot_binary()
    assert godot is not None
    check = verify(godot, game, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]


RENDER = pytest.mark.skipif(os.environ.get("KILN_ENGINE_RENDER") != "1" or find_godot_binary() is None or shutil.which("xvfb-run") is None,
                            reason="renders offscreen through tools/godot_window.sh: KILN_ENGINE_RENDER=1, Godot and xvfb")  # fmt: skip


def run_probe(game: Path, renderer: str, *args: str) -> list[str]:
    shutil.copy(REPO / "tests/fixtures/colour_probe.gd", game / "colour_probe.gd")
    godot = find_godot_binary()
    assert godot is not None
    subprocess.run([godot, "--headless", "--path", str(game), "--import"], capture_output=True, timeout=300)
    run = subprocess.run([str(REPO / "tools/godot_window.sh"), godot, "--rendering-method", renderer, "--path", str(game), "-s",
                          "colour_probe.gd", "--", *args], capture_output=True, text=True, timeout=300)  # fmt: skip
    lines = [x.split(" ", 1)[1] for x in run.stdout.splitlines() if x.startswith("KILN_")]
    assert lines, (run.stdout + run.stderr)[-3000:]
    return lines


def pixel(game: Path, renderer: str, *scenes: str) -> tuple[int, ...]:
    hex_ = run_probe(game, renderer, "pixel", *scenes)[0]
    return tuple(int(hex_[i : i + 2], 16) for i in (0, 2, 4))


def close(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return all(abs(x - y) <= 3 for x, y in zip(a, b, strict=True))


@RENDER
@pytest.mark.parametrize("renderer", ["gl_compatibility", "forward_plus"])
def test_vertex_colours_render_like_material_colours(tmp_path: Path, renderer: str) -> None:
    game = coloured_project(tmp_path, True, "vc")
    coloured_project(tmp_path, False, "plain")
    vc, plain = pixel(game, renderer, "res://assets/vc/models/ball.tscn"), pixel(game, renderer, "res://assets/plain/models/ball.tscn")
    assert close(vc, plain), (vc, plain)


@RENDER
def test_two_scenes_on_one_glb_encode_it_once(tmp_path: Path) -> None:
    """Two scenes on one glb (a variant scene on the base glb, with atlas + atlas_ao) share the cached mesh; each has its
    own built-in script, so only a mark on the mesh keeps the second from encoding it again."""
    game = coloured_project(tmp_path, True)
    models = game / "assets/kiln/models"
    (models / "ball_copy.tscn").write_text((models / "ball.tscn").read_text())
    alone = pixel(game, "gl_compatibility", "res://assets/kiln/models/ball.tscn")
    after = pixel(game, "gl_compatibility", "res://assets/kiln/models/ball.tscn", "res://assets/kiln/models/ball_copy.tscn")
    assert alone == after


@RENDER
def test_scatter_lods_are_encoded_like_lod_0(tmp_path: Path) -> None:
    project = make_project(tmp_path, CONFIG.format(out="kiln") + "vertex_colors = true\n")
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text(PROJECT_GODOT)
    write_model(project, sphere_text("ball").replace("parts:", "lod: [60]\nparts:"), "ball")
    write_model(project, "name: field\nscatter:\n  onto: flat\n  size: [6, 4]\n  seed: 1\n  place:\n    - model: ball\n"
                         "      density: 1\n      lod: [12]\n", "field")  # fmt: skip
    assert build(project).errors == []
    assert "_encode_colours(mesh)" in (tmp_path / "game/assets/kiln/models/field.tscn").read_text()
    found = run_probe(tmp_path / "game", "gl_compatibility", "bytes", "res://assets/kiln/models/field.tscn")
    colours = {line.split()[1] for line in found}
    assert len(found) >= 2 and len(colours) == 1, found
