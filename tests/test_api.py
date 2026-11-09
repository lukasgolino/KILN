"""kiln.api helpers and textures (#216 review)."""

from __future__ import annotations

from conftest import load, write_model
from PIL import Image

from kiln import api
from kiln.builder import cache_key
from kiln.project import Project


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
