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
    first = single.vertices[single.faces].mean(axis=1)[single.face_decal >= 0]
    single_slots = {int(round(a / 45)) % 8 for a in np.degrees(np.arctan2(first[:, 2], first[:, 0])) % 360}
    assert len(single_slots) == 1  # without per_copy: the first copy only


def test_the_copies_share_one_texture_and_one_material(project: Project) -> None:
    square(project)
    write_model(project, RING)
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "thing.glb").read_bytes())
    assert len(doc.get("images", [])) == 1 and len(doc.get("textures", [])) == 1
    decal_materials = [m for m in doc["materials"] if "decal" in m["name"]]
    assert len(decal_materials) == 1  # one material (one draw call) for the 8 copies' decals
    prims = [q for mesh in doc["meshes"] for q in mesh["primitives"]]
    assert len(prims) == 2  # the box colour and the decal


def test_a_row_along_the_decals_axis_stays_light_and_manifold(project: Project) -> None:
    square(project)
    row = RING.replace("array: { count: 8, around: y, center: [0, 0.3, 0] }", "array: { count: 6, step: [0.2, 0, 0.003] }")
    result = lint_paths(project, [write_model(project, row)])
    plain = lint_paths(project, [write_model(project, row.replace(", per_copy: true", ""))])
    assert not result.errors, result.findings
    assert result.built["thing"].triangles < 1.3 * plain.built["thing"].triangles  # each copy cut only round its own decal


def test_a_mirror_twin_keeps_per_copy(project: Project) -> None:
    square(project)
    twin = RING.replace("    color: blue\n", "    color: blue\n    mirror: x\n    mirror_id: other\n").replace("count: 8", "count: 3")
    model, _, findings = load(project, twin)
    assert model is not None and not findings, findings
    assert all(q.decal is not None and q.decal.per_copy for q in model.parts)


def test_texel_sizes_the_decal_from_its_pixels(project: Project) -> None:
    square(project)
    model, _, findings = load(project, RING.replace("size: [0.08, 0.08]", "texel: 0.005"))
    assert model is not None and not findings, findings
    assert model.parts[0].decal is not None and model.parts[0].decal.size == (0.08, 0.08)  # 16 pixels x 5 mm
    for bad in ("size: [0.08, 0.08], texel: 0.005", "size: [0, 0], texel: 0.005", "per_copy: 1, size: [0.08, 0.08]"):
        _, _, findings = load(project, RING.replace("size: [0.08, 0.08], per_copy: true", bad))
        assert findings, bad
    _, _, findings = load(project, RING.replace("    array: { count: 8, around: y, center: [0, 0.3, 0] }\n", ""))
    assert any("per_copy puts it on every copy of an array" in f.message for f in findings), findings


def test_previews_show_every_copys_decal(project: Project) -> None:
    from kiln.render import View, render

    square(project)
    built = lint_paths(project, [write_model(project, RING)]).built["thing"]
    image = np.asarray(render(built, View(90, 30), 160)).astype(float)
    yellow = (image[..., 0] > 200) & (image[..., 1] > 170) & (image[..., 2] < 120) & (image[..., 3] > 0)
    plain = lint_paths(project, [write_model(project, RING.replace(", per_copy: true", ""))]).built["thing"]
    one = np.asarray(render(plain, View(90, 30), 160)).astype(float)
    yellow_one = (one[..., 0] > 200) & (one[..., 1] > 170) & (one[..., 2] < 120) & (one[..., 3] > 0)
    assert yellow.sum() > 1.5 * yellow_one.sum() > 0  # the side copies' decals in view too, not the front one alone
