"""kiln.api helpers and textures (#216 review)."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import load, write_model
from PIL import Image

from kiln import api
from kiln.builder import cache_key
from kiln.project import Project, load_project
from kiln.style import Style


def test_part_and_offset_carry_textures_and_decals() -> None:
    p = api.part("cylinder", "red", radius=0.1, height=0.2, at=[0, 0.1, 0],
                 texture={"image": "textures/t.png", "project": "cylindrical", "at": [0, 0, 0], "texel": 0.01},
                 decal={"image": "decals/d.png", "axis": "z", "at": [0, 0.1, 0.1], "size": [0.1, 0.1]})  # fmt: skip
    assert "texture" in p and "texture" not in p["cylinder"]
    (moved,) = api.offset([p], dx=1.0)
    assert moved["cylinder"]["at"] == [1.0, 0.1, 0] and moved["texture"]["at"] == [1.0, 0, 0] and moved["decal"]["at"] == [1.0, 0.1, 0.1]
    assert p["texture"]["at"] == [0, 0, 0]  # the input is left alone


def test_cache_key_follows_the_texture_image(project: Project) -> None:
    (project.root / "textures").mkdir(exist_ok=True)
    image = project.root / "textures" / "t.png"
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(image)
    text = "name: thing\nparts:\n  - sphere: { radius: 0.3 }\n    color: red\n    texture: { image: textures/t.png, texel: 0.01 }\n"
    model, style, _ = load(project, text)
    assert model is not None and style is not None
    palette, _ = project.palette(model.palette)
    before = cache_key(model, style, palette)
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(image)
    model, style, _ = project.load(write_model(project, text))
    assert model is not None and style is not None
    assert cache_key(model, style, palette) != before


def test_a_look_only_style_edit_keeps_the_built_mesh(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    """#174: the mesh cache follows a style's [shape] and [budgets], not its [look], [materials] or notes; the cached
    build comes back with the style as it is now."""
    from kiln import builder

    style_file = project.styles_dir / "own.style.toml"
    style_file.parent.mkdir(parents=True, exist_ok=True)

    def with_style(text: str) -> Style:
        style_file.write_text('extends = "soft_toy"\n' + text, encoding="utf-8")
        style, findings = load_project(start=project.root).style("own")  # a fresh run: a project keeps its styles
        assert style is not None, findings
        return style

    plain = with_style("")

    path = write_model(project, "name: ball\nstyle: own\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n", "ball")
    model = project.load(path)[0]
    assert model is not None
    cache = project.root / ".kiln-cache"
    calls: list[str] = []
    real = builder.build_model

    def counted(*a: Any, **k: Any) -> Any:
        calls.append("built")
        return real(*a, **k)

    monkeypatch.setattr(builder, "build_model", counted)
    first = builder.build_cached(model, plain, {}, cache)
    looked = with_style('notes = "rounder"\n[look]\nexposure = 1.4\n[materials]\ndefault = { roughness = 0.9 }\n')
    assert builder.cache_key(model, looked, {}) == builder.cache_key(model, plain, {})
    again = builder.build_cached(model, looked, {}, cache)
    assert calls == ["built"] and again.style is looked and again.style.materials["default"].roughness == 0.9
    assert again.triangles == first.triangles
    for shaped in ("[shape]\nresolution = 0.02\n", "[shape]\nsharp_angle = 20\n", "[budgets]\ndefault = 500\n"):
        other = with_style(shaped)
        assert builder.cache_key(model, other, {}) != builder.cache_key(model, plain, {}), shaped
