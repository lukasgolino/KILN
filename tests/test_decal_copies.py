"""#211: a decal on every copy of an array; decal size from the image's pixels."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model
from PIL import Image

from kiln.build import build
from kiln.lint import lint_paths
from kiln.project import Project
from kiln.vendor.gltf import read_glb

RING = """\
name: thing
budget: 6000
resolution: 0.01
parts:
  - box: { at: [0.5, 0.3, 0], size: [0.12, 0.2, 0.12], round: 0.02 }
    color: blue
    array: { count: 8, around: y, center: [0, 0.3, 0] }
    decal: { image: decals/sq.png, axis: x, at: [0.56, 0.3, 0], size: [0.08, 0.08], per_copy: true }
"""


def square(project: Project) -> None:
    Image.new("RGBA", (16, 16), (250, 220, 40, 255)).save(project.root / "decals" / "sq.png")


def test_every_copy_carries_the_decal(project: Project) -> None:
    square(project)
    p = lint_paths(project, [write_model(project, RING)]).built["thing"].painted
    centre = p.vertices[p.faces].mean(axis=1)
    on = p.face_decal >= 0
    angles = np.degrees(np.arctan2(centre[on][:, 2], centre[on][:, 0])) % 360
    slots = {int(round(a / 45)) % 8 for a in angles}
    assert slots == set(range(8))  # one on each of the 8 copies
    radius = np.hypot(centre[on][:, 0], centre[on][:, 2])
    assert radius.min() > 0.55  # each on its copy's outer face
    single = lint_paths(project, [write_model(project, RING.replace(", per_copy: true", ""))]).built["thing"].painted
    assert len({int(round(a / 45)) % 8 for a in np.degrees(np.arctan2(*(single.vertices[single.faces].mean(axis=1)[single.face_decal >= 0][:, [2, 0]].T))) % 360}) == 1


def test_the_copies_share_one_texture(project: Project) -> None:
    square(project)
    write_model(project, RING)
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    assert len(doc.get("images", [])) == 1 and len(doc.get("textures", [])) == 1


def test_texel_sizes_the_decal_from_its_pixels(project: Project) -> None:
    square(project)
    model, _, findings = load(project, RING.replace("size: [0.08, 0.08]", "texel: 0.005"))
    assert model is not None and not findings, findings
    assert model.parts[0].decal is not None and model.parts[0].decal.size == (0.08, 0.08)  # 16 pixels x 5 mm
    for bad in ("size: [0.08, 0.08], texel: 0.005", "per_copy: 1, size: [0.08, 0.08]"):
        _, _, findings = load(project, RING.replace("size: [0.08, 0.08], per_copy: true", bad))
        assert findings, bad
