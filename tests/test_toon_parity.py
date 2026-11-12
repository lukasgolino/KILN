"""#183: the preview's toon look as Godot draws it: the sun's light without Godot's PI, outlines as the inverted hull."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
from conftest import FAST_STYLE, built_of, sphere_text

from kiln.godot import TOON_SHADER, toon_shader
from kiln.project import Project
from kiln.render import View, render
from kiln.style import Look
from kiln.terrain import TOON_LIGHT


def _toon(project: Project, outline: float) -> None:
    style = project.root / "styles" / "fast.style.toml"
    style.write_text(FAST_STYLE.replace('"soft_toy"', '"toon"') + f"\n[look]\noutline = {outline}\n")


def test_godot_toon_light_drops_the_pi_in_light_color() -> None:
    for shader in (TOON_SHADER, toon_shader(Look(shader="toon", toon_softness=0.3, toon_specular=0.5), False), TOON_LIGHT):
        lines = [line for line in shader.splitlines() if "LIGHT_COLOR" in line]
        assert lines and all("LIGHT_COLOR / PI" in line for line in lines), lines


def test_outlines_grow_outward_only(project: Project) -> None:
    _toon(project, 0.05)
    ball = built_of(project, sphere_text())
    lined = np.asarray(render(ball, View(), 128)).astype(int)
    style = replace(ball.style, look=replace(ball.style.look, outline=0.0))
    plain = np.asarray(render(replace(ball, style=style), View(), 128)).astype(int)
    inside = plain[:, :, 3] == 255
    shrunk = inside.copy()
    for axis in (0, 1):
        for step in (1, -1):
            shrunk &= np.roll(inside, step, axis)  # one pixel in from the edge (box filtering blends the edge pixels)
    assert np.abs(lined[shrunk, :3] - plain[shrunk, :3]).max() <= 2  # nothing drawn over the part itself
    ring = (lined[:, :, 3] == 255) & ~inside
    radius = np.sqrt(inside.sum() / np.pi)
    expected = np.pi * ((radius + 0.05 * radius / 0.3) ** 2 - radius**2)  # a 0.05 m hull round a 0.3 m sphere
    assert 0.6 * expected < ring.sum() < 1.4 * expected
