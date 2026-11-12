"""#183: the preview's toon look as Godot draws it: the sun's light without Godot's PI, outlines as the inverted hull."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
from conftest import FAST_STYLE, arms_text, built_of, sphere_text

from kiln.export import Built, srgb_to_linear
from kiln.godot import TOON_SHADER, toon_shader
from kiln.project import Project
from kiln.render import View, _grade, _to_srgb, render
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


def _look(ball: Built, **changes: Any) -> Built:
    return replace(ball, style=replace(ball.style, look=replace(ball.style.look, **changes)))


def test_hidden_parts_leave_no_outline(project: Project) -> None:
    _toon(project, 0.05)
    body = built_of(project, arms_text(skin="rigid"))
    hide = frozenset({"arm_l"})
    lined = np.asarray(render(body, View(), 128, hide=hide))[:, :, 3] == 255
    plain = np.asarray(render(_look(body, outline=0.0), View(), 128, hide=hide))[:, :, 3] > 0
    lo, hi = body.painted.vertices.min(axis=0), body.painted.vertices.max(axis=0)
    width = int(np.ceil(0.05 * 128 / (float(np.linalg.norm(hi - lo)) * 1.08))) + 2
    near = plain.copy()
    for _ in range(2 * width):  # (4-neighbour steps: a diamond, so twice the radius covers the disc)
        near = near | np.roll(near, 1, 0) | np.roll(near, -1, 0) | np.roll(near, 1, 1) | np.roll(near, -1, 1)
    assert not (lined & ~near).any()  # every outline pixel hugs a part still shown: none where the arm was


def test_terrain_colours_draw_no_outline(project: Project) -> None:
    _toon(project, 0.05)
    ball = built_of(project, sphere_text())
    colors = np.full((len(ball.painted.faces), 3, 3), 0.3)
    assert (np.asarray(render(ball, View(), 64, colors=colors)) == np.asarray(render(_look(ball, outline=0.0), View(), 64, colors=colors))).all()


def test_outline_colour_goes_through_the_look(project: Project) -> None:
    _toon(project, 0.05)
    ball = _look(built_of(project, sphere_text()), outline_color="#808080", tonemapper="filmic", exposure=2.0)
    image = np.asarray(render(ball, View(), 128)).astype(int)
    plain = np.asarray(render(_look(ball, outline=0.0), View(), 128))
    ring = (image[:, :, 3] == 255) & (plain[:, :, 3] == 0)
    values, counts = np.unique(image[ring][:, :3], axis=0, return_counts=True)
    want = np.round(_to_srgb(_grade(np.array([srgb_to_linear("#808080")]), ball.style.look))[0] * 255)
    assert np.abs(values[counts.argmax()] - want).max() <= 1 and want[0] != 128  # the tone curve moved it
