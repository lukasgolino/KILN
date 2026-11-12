"""#180, #203, #212: preview fill light, dark backgrounds, tiles framed on themselves or on a box, line-ups from above."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from conftest import built_of, run_json, sphere_text, write_model

from kiln import preview as pv
from kiln.project import Project
from kiln.render import View, render

FLAT = "name: thing\nparts:\n  - box: { at: [0, 0.01, 0], size: [1.0, 0.02, 1.0] }\n    color: red\n  - box: { at: [0.45, 0.04, 0.45], size: [0.04, 0.04, 0.04] }\n    color: blue\n"


def test_fill_lights_what_faces_away(project: Project) -> None:
    ball = built_of(project, sphere_text())
    below = View(0.0, -60.0)
    dark = np.asarray(render(ball, below, 96)).astype(float)
    lit = np.asarray(render(ball, below, 96, fill=0.6)).astype(float)
    solid = dark[:, :, 3] == 255
    assert lit[solid, :3].mean() > dark[solid, :3].mean() + 10
    assert (np.asarray(render(ball, below, 96, fill=0.0)) == dark.astype(np.uint8)).all()  # off: as before


def test_dark_skies_get_a_dark_background(project: Project) -> None:
    ball = built_of(project, sphere_text())
    assert pv.tile_background(ball.style) == pv.TILE_BG
    night = replace(ball.style, look=replace(ball.style.look, sky_top="#05060a"))
    assert pv.tile_background(night) == pv.DARK_TILE_BG
    assert pv.tile_background(night, "light") == pv.TILE_BG and pv.tile_background(ball.style, "dark") == pv.DARK_TILE_BG


def _covered(image: object) -> float:
    a = np.asarray(image)
    return float((a[:, :, 3] == 255).mean() if a.shape[2] == 4 else 0.0)


def test_tight_tiles_fill_with_flat_props(project: Project) -> None:
    flat = built_of(project, FLAT)
    view = View(0.0, 15.0)
    fit = pv.fit_of(flat)
    loose = render(flat, view, 128, fit=fit)
    tight = pv.Tiles(tight=True).render(flat, view, 128, fit)
    assert _covered(tight) > 2.5 * _covered(loose)


def test_a_frame_box_frames_a_region(project: Project) -> None:
    flat = built_of(project, FLAT)
    tiles = pv.Tiles(frame=((0.4, 0.0, 0.4), (0.5, 0.08, 0.5)))
    def blue(image: object) -> float:
        a = np.asarray(image).astype(int)
        return float(((a[:, :, 2] > 120) & (a[:, :, 0] < 90) & (a[:, :, 3] == 255)).mean())

    framed = blue(tiles.render(flat, View(0.0, 15.0), 128, tiles.fit(flat)))
    whole = blue(render(flat, View(0.0, 15.0), 128, fit=pv.fit_of(flat)))
    assert framed > 0.03 and framed > 10 * whole  # the small blue block, up close


def test_lineup_from_above(project: Project) -> None:
    flat = built_of(project, FLAT)
    ball = built_of(project, sphere_text("ball"), "ball")
    image = pv.lineup([flat, ball], 240, pitch=60.0)
    assert image.width > 200 and image.height > 240


def test_preview_flags(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(project, FLAT)
    monkeypatch.chdir(project.root)
    code, out = run_json(["preview", "thing", "--views", "front", "--size", "64", "--tight", "--fill", "--bg", "dark",
                          "--frame-box", "0.4,0,0.4,0.5,0.08,0.5"], capsys)  # fmt: skip
    assert code == 0 and "views" in out["outputs"], out
    code, out = run_json(["preview", "thing", "--frame-box", "1,2,3"], capsys)
    assert code != 0
    code, out = run_json(["lineup", "thing", "--pitch", "60"], capsys)
    assert code == 0, out


def test_tight_inside_a_frame_box_frames_the_box(project: Project) -> None:
    flat = built_of(project, FLAT)
    box = ((0.4, 0.0, 0.4), (0.5, 0.08, 0.5))
    centre, half = pv._tight(flat, View(0.0, 15.0), pv.Tiles(frame=box).fit(flat), box)
    assert half < 0.1  # the small block, not the whole board


def test_fill_takes_no_amount_and_framing_flags_say_where_they_apply(project: Project, monkeypatch: pytest.MonkeyPatch,
                                                                     capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    write_model(project, FLAT)
    monkeypatch.chdir(project.root)
    code, _ = run_json(["preview", "--fill", "thing", "--views", "front", "--size", "64"], capsys)
    assert code == 0
    code, out = run_json(["preview", "thing", "--closeup", "root", "--tight"], capsys)
    assert code != 0 and "turntable" in str(out)
