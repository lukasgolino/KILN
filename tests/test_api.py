"""kiln.api helpers and textures (#216 review)."""

from __future__ import annotations

from typing import Any

import pytest
from conftest import load, write_model
from PIL import Image

from kiln import api
from kiln.builder import cache_key
from kiln.project import Project, load_project
from kiln.style import SHAPE_KEYS, Style


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
    """#174: the mesh cache follows a style's [shape] and the budget that applies, not its [look], [materials],
    description or notes; the cached build comes back with the style as it is now, and its export follows it."""
    import json

    from kiln import builder
    from kiln.export import to_glb
    from kiln.vendor.gltf import read_glb

    style_file = project.styles_dir / "own.style.toml"
    style_file.parent.mkdir(parents=True, exist_ok=True)

    def with_style(text: str) -> Style:
        style_file.write_text('extends = "soft_toy"\n' + text, encoding="utf-8")
        style, findings = load_project(start=project.root).style("own")  # a fresh run: a project keeps its styles
        assert style is not None, findings
        return style

    def roughness(built: Any) -> list[float]:
        doc = read_glb(to_glb(built, "test"))[0]
        return [m["pbrMetallicRoughness"]["roughnessFactor"] for m in doc["materials"]]

    plain = with_style("")
    path = write_model(project, "name: ball\nstyle: own\nclass: prop\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n", "ball")
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
    before = roughness(first)
    looked = with_style('description = "another"\nnotes = "rounder"\n[look]\nexposure = 1.4\n[materials]\ndefault = { roughness = 0.9 }\n')
    assert builder.cache_key(model, looked, {}) == builder.cache_key(model, plain, {})
    again = builder.build_cached(model, looked, {}, cache)
    assert calls == ["built"] and again.style is looked and again.triangles == first.triangles
    assert roughness(again) == [0.9] * len(before) and before != roughness(again)  # the export uses today's materials
    json.dumps(builder.shape_key(model, plain))  # the key is plain data
    values = {"smooth": "false", "sharp_angle": "20", "resolution": "0.02", "hard_surface": '"always"', "hard_sides": "8", "max_cells": "128",
              "scale_with_size": "false"}  # fmt: skip
    assert set(values) == set(SHAPE_KEYS)
    for key, value in values.items():
        other = with_style(f"[shape]\n{key} = {value}\n")
        assert builder.cache_key(model, other, {}) != builder.cache_key(model, plain, {}), key
    # budgets: the one that applies to the model, not the table (another class's budget leaves this model's meshes)
    assert builder.cache_key(model, with_style("[budgets]\nprop = 500\n"), {}) != builder.cache_key(model, plain, {})
    assert builder.cache_key(model, with_style("[budgets]\ncharacter = 500\n"), {}) == builder.cache_key(model, plain, {})
    assert builder.cache_key(model, plain, {}, 300) != builder.cache_key(model, plain, {})  # a LOD's own budget


def test_every_style_field_is_keyed_or_known_not_to_change_a_build() -> None:
    """#174: the mesh cache no longer takes the style's text, so a new Style field must be put on one side here: in
    builder.STYLE_KEYED if a builder reads it, else below."""
    import dataclasses

    from kiln.builder import STYLE_KEYED

    not_keyed = {"description", "notes", "materials", "look", "path", "text"}  # read at export or by people only
    fields = {f.name for f in dataclasses.fields(Style)}
    assert set(STYLE_KEYED) | not_keyed == fields and not set(STYLE_KEYED) & not_keyed
