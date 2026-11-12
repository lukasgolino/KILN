"""#275: the look kit's fill light: a second, weaker sun without shadows, in the Godot look scene and the previews."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from kiln.godot import look_scene
from kiln.style import load_style


def test_skin_has_a_fill_from_the_other_side_and_the_look_scene_carries_it() -> None:
    style, findings = load_style("skin")
    assert style is not None and not findings
    look = style.look
    assert look.fill_energy > 0 and look.fill_direction == look.sun_yaw + 180
    scene = look_scene(style)
    fill = scene[scene.index('[node name="Fill"') :]
    assert "shadow_enabled = false" in fill and f"light_energy = {look.fill_energy:.6g}" in fill
    plain, _ = load_style("soft_toy")
    assert plain is not None and plain.look.fill_energy == 0 and '"Fill"' not in look_scene(plain)


def test_bad_fill_energy(tmp_path: Path) -> None:
    (tmp_path / "x.style.toml").write_text('extends = "soft_toy"\n[look]\nfill_energy = -1.0\n')
    _, findings = load_style("x", tmp_path)
    assert any(f.where == "look.fill_energy" for f in findings)


def test_the_preview_lights_the_shadow_side() -> None:
    from conftest import CONFIG, make_project, write_model  # noqa: F401

    from kiln.builder import build_model
    from kiln.notation import load_model
    from kiln.render import View, render

    style, _ = load_style("soft_toy")
    assert style is not None
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        proj = make_project(Path(d))
        path = write_model(proj, "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: white\n")
        palette, _ = proj.palette(None)
        model, _ = load_model(path, palette, set(style.materials))
        assert model is not None
        built = build_model(model, style, palette=palette)
        yaw = style.look.sun_yaw + 180  # look from the shadow side
        dark = np.asarray(render(built, View(yaw, 0.0), 96))[..., :3].astype(float)
        built.style = replace(style, look=replace(style.look, fill_energy=0.5))
        lit = np.asarray(render(built, View(yaw, 0.0), 96))[..., :3].astype(float)
        assert lit.sum() > dark.sum() * 1.05
