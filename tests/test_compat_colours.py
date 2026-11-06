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


@pytest.mark.skipif(os.environ.get("KILN_ENGINE_RENDER") != "1" or find_godot_binary() is None or shutil.which("xvfb-run") is None,
                    reason="renders offscreen through tools/godot_window.sh: KILN_ENGINE_RENDER=1, Godot and xvfb")  # fmt: skip
@pytest.mark.parametrize("renderer", ["gl_compatibility", "forward_plus"])
def test_vertex_colours_render_like_material_colours(tmp_path: Path, renderer: str) -> None:
    game = coloured_project(tmp_path, True, "vc")
    coloured_project(tmp_path, False, "plain")
    shutil.copy(REPO / "tests/fixtures/colour_probe.gd", game / "colour_probe.gd")
    godot = find_godot_binary()
    assert godot is not None
    subprocess.run([godot, "--headless", "--path", str(game), "--import"], capture_output=True, timeout=300)

    def probe(scene: str) -> tuple[int, ...]:
        run = subprocess.run([str(REPO / "tools/godot_window.sh"), godot, "--rendering-method", renderer, "--path", str(game), "-s",
                              "colour_probe.gd", "--", scene], capture_output=True, text=True, timeout=300)  # fmt: skip
        line = next((x for x in run.stdout.splitlines() if x.startswith("KILN_PROBE ")), None)
        assert line is not None, (run.stdout + run.stderr)[-3000:]
        hex_ = line.split()[1]
        return tuple(int(hex_[i : i + 2], 16) for i in (0, 2, 4))

    vc, plain = probe("res://assets/vc/models/ball.tscn"), probe("res://assets/plain/models/ball.tscn")
    assert all(abs(a - b) <= 3 for a, b in zip(vc, plain, strict=True)), (vc, plain)
