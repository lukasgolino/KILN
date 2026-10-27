"""#31: effect previews: fade drawn as ordered dithering, a contact sheet at chosen times (`--at`), the floor as a grid."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from conftest import built_of, run_json, sphere_text, write_model
from kiln import preview as pv
from kiln.project import Project
from kiln.render import View, render
from test_mcp import call

BURST = """effect:
  seed: 3
  floor: 0
  emit:
    - model: spark
      count: 6
      at: [0, 0.5, 0]
      life: [0.5, 1.0]
      burst: [1, 2]
      gravity: 9.8
      fade: { 0: 1, 1: 0 }
"""


def test_fade_dithers_and_lets_the_background_through(project: Project) -> None:
    ball = built_of(project, sphere_text())
    faces = len(ball.painted.faces)
    solid = np.asarray(render(ball, View(), 64))[:, :, 3]
    same = np.asarray(render(ball, View(), 64, fade=np.ones(faces)))[:, :, 3]
    assert (solid == same).all()  # fade 1: as before
    half = np.asarray(render(ball, View(), 64, fade=np.full(faces, 0.5)))[:, :, 3]
    inside = solid == 255
    assert 0.4 < (half[inside] == 255).mean() < 0.6 and (half[inside] == 0).mean() > 0.4  # every other pixel: a dither
    assert not np.asarray(render(ball, View(), 64, fade=np.zeros(faces)))[:, :, 3].any()


def test_faded_toon_pieces_have_no_outline_in_their_holes(project: Project) -> None:
    style = project.root / "styles" / "fast.style.toml"
    style.write_text(style.read_text().replace('"soft_toy"', '"toon"'))
    ball = built_of(project, sphere_text())
    a = np.asarray(render(ball, View(), 64, fade=np.full(len(ball.painted.faces), 0.5)))
    assert (a[:, :, 3] == 0).sum() > (np.asarray(render(ball, View(), 64))[:, :, 3] == 0).sum() + 500


@pytest.fixture
def burst(project: Project) -> Project:
    write_model(project, sphere_text("spark"), "spark")
    write_model(project, sphere_text("burst") + BURST, "burst")
    return project


def _sheet(project: Project, times: list[float] | None, floor: bool = True) -> Image.Image:
    text = sphere_text("burst") + (BURST if floor else BURST.replace("  floor: 0\n", ""))
    built = built_of(project, text, "burst")
    return pv.effect_strip(built, {"spark": built_of(project, sphere_text("spark"), "spark")}, times=times)


def test_contact_sheet_at_chosen_times_with_the_floor_grid(burst: Project) -> None:
    default = _sheet(burst, None)
    five = _sheet(burst, [0, 0.1, 0.25, 0.5, 1])
    assert default.width > five.width  # 8 frames vs 5
    plain = np.asarray(_sheet(burst, [0, 0.1, 0.25, 0.5, 1], floor=False)).astype(int)
    grid = np.asarray(five).astype(int)
    assert plain.shape == grid.shape and (np.abs(plain - grid).sum(axis=2) > 0).sum() > 1000  # the floor's lines
    assert _sheet(burst, [0.5]).width < five.width
    with pytest.raises(ValueError):
        _sheet(burst, [50.0])  # nothing alive


def test_cli_and_mcp_at(burst: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(burst.root)
    code, out = run_json(["preview", "burst", "--effect", "--at", "0,0.1,0.25,0.5,1"], capsys)
    assert code == 0 and (burst.preview_dir / "burst" / "effect.png").is_file(), out
    for bad in (["--effect", "--at", "0,x"], ["--effect", "--at", "-1"], ["--at", "0.5"], ["--effect", "--at", "50"]):
        code, out = run_json(["preview", "burst", *bad], capsys)
        assert code != 0 and not out["ok"], bad
    result, images = call(burst, "preview", {"model": "burst", "which": "effect", "at": [0, 0.25]})
    assert result["ok"] and images == 1
    result, images = call(burst, "preview", {"model": "burst", "at": [0.25]})
    assert not result["ok"] and "effect" in result["findings"][0]["message"]

