"""Paint: cutting triangles along borders, colour groups, patterns and decals."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import built_of, closed_faces, errors_of, ok_model, sphere_text
from PIL import Image

from kiln.builder import field_of
from kiln.mesher import dual_contour
from kiln.paint import decal_uv, refine, split
from kiln.project import Project
from kiln.sdf import Field, Geometry


def sphere_mesh() -> tuple[np.ndarray, np.ndarray]:
    mesh = dual_contour(Field([Geometry("sphere", {"radius": 0.5})], margin=0.1), 0.05)
    return mesh.vertices, mesh.faces


def test_split_cuts_along_the_zero_line_without_cracks() -> None:
    v, f = sphere_mesh()
    values = v[:, 0] - 0.1
    nv, nf, negative, parent = split(v, f, values, np.ones(len(f), dtype=bool))
    assert len(nf) > len(f) and len(parent) == len(nf)
    assert closed_faces(nf)
    centroid_x = nv[nf].mean(axis=1)[:, 0]
    assert np.all(centroid_x[negative] <= 0.1 + 1e-9)
    assert np.all(centroid_x[~negative] >= 0.1 - 1e-9)
    # every face is entirely on one side
    corner_x = nv[nf][:, :, 0]
    assert np.all(corner_x[negative] <= 0.1 + 1e-9) and np.all(corner_x[~negative] >= 0.1 - 1e-9)
    # area is kept
    def area(vv: np.ndarray, ff: np.ndarray) -> float:
        return float(np.linalg.norm(np.cross(vv[ff[:, 1]] - vv[ff[:, 0]], vv[ff[:, 2]] - vv[ff[:, 0]]), axis=1).sum() / 2)

    assert area(nv, nf) == pytest.approx(area(v, f))


def test_split_only_touches_selected_faces() -> None:
    v, f = sphere_mesh()
    selected = np.zeros(len(f), dtype=bool)
    nv, nf, _, parent = split(v, f, v[:, 0], selected)
    assert nv is v and nf is f
    np.testing.assert_array_equal(parent, np.arange(len(f)))


def test_refine_splits_long_edges_and_stays_closed() -> None:
    v, f = sphere_mesh()
    nv, nf, parent = refine(v, f, np.ones(len(f), dtype=bool), 0.02, lambda x: x / np.linalg.norm(x, axis=1, keepdims=True) * 0.5)
    assert len(nf) > len(f) and len(parent) == len(nf)
    assert closed_faces(nf)


def test_refine_of_a_few_faces_stays_closed_and_leaves_far_faces() -> None:
    """#123: refine looks only at the selected faces and their neighbours; the rest of the mesh stays as it was."""
    v, f = sphere_mesh()
    centres = v[f].mean(axis=1)
    selected = centres[:, 0] > 0.35
    nv, nf, parent = refine(v, f, selected, 0.01, lambda x: x / np.linalg.norm(x, axis=1, keepdims=True) * 0.5)
    assert len(nf) > len(f) and closed_faces(nf)
    far = np.flatnonzero(centres[:, 0] < 0.2)
    assert (np.bincount(parent, minlength=len(f))[far] == 1).all()  # far faces aren't split
    np.testing.assert_array_equal(nv[: len(v)], v)


def test_split_far_from_the_cut_keeps_faces() -> None:
    v, f = sphere_mesh()
    centres = v[f].mean(axis=1)
    selected = centres[:, 1] > 0.3
    nv, nf, _, parent = split(v, f, v[:, 0] - 0.01, selected)
    assert closed_faces(nf)
    far = np.flatnonzero(centres[:, 1] < 0.1)
    assert (np.bincount(parent, minlength=len(f))[far] == 1).all()


def two_colour(project: Project) -> str:
    return """\
name: thing
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    color: red
  - sphere: { at: [0, 0.45, 0.2], radius: 0.15 }
    color: white
    material: plastic
"""


def test_paint_gives_clean_colour_groups(project: Project) -> None:
    built = built_of(project, two_colour(project))
    p = built.painted
    assert [(g.color_name, g.material) for g in p.groups] == [("red", "default"), ("white", "plastic")]
    assert closed_faces(p.faces)
    assert set(np.unique(p.face_group)) == {0, 1}
    field = field_of(built.model, built.step)
    centroids = p.vertices[p.faces].mean(axis=1)
    d_red, d_white = field.part_distance(0, centroids), field.part_distance(1, centroids)
    tol = built.step * 0.5
    assert np.all(d_red[p.face_group == 0] <= d_white[p.face_group == 0] + tol)
    assert np.all(d_white[p.face_group == 1] <= d_red[p.face_group == 1] + tol)


def test_same_paint_parts_share_a_group(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0.3, 0.3, 0], radius: 0.1 }\n    color: red\n"
    built = built_of(project, text)
    assert len(built.painted.groups) == 1


def test_rigged_parts_get_their_own_groups(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0.3, 0.3, 0], radius: 0.1 }\n    id: nub\n    color: red\nskin: rigid\n"
    built = built_of(project, text)
    assert sorted(g.bone for g in built.painted.groups) == ["nub", "root"]


@pytest.mark.parametrize(
    "pattern",
    [
        "{ type: stripes, color: blue, size: 0.1, axis: y, width: 0.4 }",
        "{ type: band, color: blue, size: 0.08, axis: y, at: 0.3 }",
        "{ type: dots, color: blue, size: 0.15, width: 0.5 }",
        "{ type: checker, color: blue, size: 0.15 }",
    ],
)
def test_patterns_add_a_second_colour(project: Project, pattern: str) -> None:
    built = built_of(project, sphere_text() + f"    pattern: {pattern}\n")
    p = built.painted
    names = [g.color_name for g in p.groups]
    assert "blue" in names and any(n.startswith("red") for n in names)
    counts = np.bincount(p.face_group, minlength=len(p.groups))
    assert np.all(counts > 0)
    assert closed_faces(p.faces)


def test_band_pattern_is_where_it_says(project: Project) -> None:
    built = built_of(project, sphere_text() + "    pattern: { type: band, color: blue, size: 0.1, axis: y, at: 0.3 }\n")
    p = built.painted
    blue = next(i for i, g in enumerate(p.groups) if g.color_name == "blue")
    y = p.vertices[p.faces[p.face_group == blue]][:, :, 1]
    # borders are cut at full resolution, then simplified within a fraction of a grid step (mesher.BORDER_TOLERANCE)
    assert y.min() >= 0.25 - 1e-3 and y.max() <= 0.35 + 1e-3


def test_decals_mark_faces_facing_their_way(project: Project) -> None:
    Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(project.root / "decals" / "logo.png")
    text = sphere_text() + "    decal: { image: decals/logo.png, axis: z, at: [0, 0.3, 0.3], size: [0.2, 0.2] }\n"
    built = built_of(project, text)
    p = built.painted
    assert len(p.decals) == 1
    marked = p.face_decal == 0
    assert marked.any() and (~marked).any()
    centroids = p.vertices[p.faces[marked]].mean(axis=1)
    assert np.all(centroids[:, 2] > 0.1)  # the front only
    uv = decal_uv(p.decals[0], centroids)
    assert np.all((uv >= -1e-6) & (uv <= 1 + 1e-6))
    assert closed_faces(p.faces)


def test_decal_uv_orientation(project: Project) -> None:
    Image.new("RGBA", (4, 4)).save(project.root / "decals" / "logo.png")
    text = sphere_text() + "    decal: { image: decals/logo.png, axis: z, at: [0, 0.3, 0.3], size: [0.2, 0.4] }\n"
    built = built_of(project, text)
    d = built.painted.decals[0]
    uv = decal_uv(d, np.array([[0, 0.3, 0.3], [0.1, 0.5, 0.3], [-0.1, 0.1, 0.3]]))
    np.testing.assert_allclose(uv, np.array([[0.5, 0.5], [1.0, 0.0], [0.0, 1.0]]), atol=1e-12)  # u to the right seen from the front, v down


def test_noise_leaves_colour_borders_smooth(project: Project) -> None:
    """#100: a noisy torso's border with a blended patch follows where the smooth shapes meet (it was saw-toothed)."""
    from dataclasses import replace

    text = ("name: thing\nparts:\n  - ellipsoid: { at: [0, 0.6, 0], radii: [0.35, 0.6, 0.25] }\n    color: red\n"
            "    noise: { amount: 0.014, scale: 0.1 }\n  - ellipsoid: { at: [0, 0.75, 0.12], radii: [0.22, 0.25, 0.15] }\n"
            "    color: white\n    blend: 0.04\n")  # fmt: skip
    built = built_of(project, text)
    p = built.painted
    group = p.face_group
    shared = np.intersect1d(np.unique(p.faces[group == 0]), np.unique(p.faces[group == 1]))
    assert len(shared) > 8
    plain = [replace(g, noise=None) for g in field_of(built.model, built.step).parts]
    gap = np.abs(plain[0].distance(p.vertices[shared]) - plain[1].distance(p.vertices[shared]))
    assert float(np.median(gap)) < 0.002


def test_patterns_on_a_noisy_part_stay_on_its_surface(project: Project) -> None:
    """The smooth shapes decide colour borders only: vertices refined for a pattern still land on the noisy surface."""
    text = ("name: thing\nbudget: 200000\nparts:\n  - ellipsoid: { at: [0, 0.6, 0], radii: [0.35, 0.6, 0.25] }\n    color: red\n"
            "    noise: { amount: 0.014, scale: 0.1 }\n    pattern: { type: stripes, color: white, size: 0.1, axis: y }\n")  # fmt: skip
    built = built_of(project, text)
    p = built.painted
    v = p.vertices[np.unique(p.faces)]
    assert float(np.abs(field_of(built.model, built.step).distance(v)).max()) < built.step / 4


def _texture_image(project: Project) -> None:
    (project.root / "textures").mkdir(exist_ok=True)
    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(project.root / "textures" / "tile.png")


def test_box_texture_covers_the_part_from_six_sides(project: Project) -> None:
    """#184: a box-projected texture covers every face of its part, as one texture (one material); each face takes
    it from the side it faces, upright and unmirrored seen from there."""
    from kiln.paint import corner_uv

    _texture_image(project)
    text = ("name: thing\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: red\n"
            "    texture: { image: textures/tile.png, project: box, texel: 0.01 }\n")  # fmt: skip
    p = built_of(project, text).painted
    assert (p.face_decal == 0).all() and len(p.decals) == 1 and p.decals[0].size == (0.08, 0.08)
    d = p.decals[0]
    assert d.at == (0.0, 0.2, 0.0)  # the part's centre by default
    seen = {"z": ([1, 0, 0], [0, 1, 0]), "-z": ([-1, 0, 0], [0, 1, 0]), "x": ([0, 0, -1], [0, 1, 0]), "-x": ([0, 0, 1], [0, 1, 0])}
    for side, (right, up) in seen.items():
        a, sign = "xyz".index(side[-1]), (-1.0 if side.startswith("-") else 1.0)
        centre = np.array(d.at)
        centre[a] += sign * 0.2
        tri = np.array([centre, centre + 0.08 * np.array(right), centre + 0.08 * np.array(up)])
        if np.cross(tri[1] - tri[0], tri[2] - tri[0])[a] * sign < 0:
            tri = tri[[0, 2, 1]]
        uv = corner_uv(d, tri[None])[0]
        right_at, up_at = (1, 2) if np.allclose(tri[1], centre + 0.08 * np.array(right)) else (2, 1)
        np.testing.assert_allclose(uv[right_at] - uv[0], [1.0, 0.0], atol=1e-9)  # one tile to the right: u + 1
        np.testing.assert_allclose(uv[up_at] - uv[0], [0.0, -1.0], atol=1e-9)  # one tile up: v - 1 (images run down)


def test_texture_stays_on_its_part(project: Project) -> None:
    """#216 review: a textured part paints its own group: another part of the same colour isn't textured, and the
    part's own pattern colours paint over its texture."""
    _texture_image(project)
    text = ("name: thing\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: red\n"
            "    texture: { image: textures/tile.png, project: box, texel: 0.01 }\n"
            "    pattern: { type: stripes, color: blue, size: 0.1, width: 0.4, axis: y }\n"
            "  - sphere: { at: [0.8, 0.2, 0], radius: 0.2 }\n    color: red\n")  # fmt: skip
    p = built_of(project, text).painted
    centre = p.vertices[p.faces].mean(axis=1)
    on_sphere = centre[:, 0] > 0.5
    assert (p.face_decal[on_sphere] < 0).all() and (p.face_decal[~on_sphere] == 0).any()
    blue = [k for k, g in enumerate(p.groups) if g.color == "#2f6fd0" or g.color_name.startswith("blue")]
    assert blue and (p.face_decal[np.isin(p.face_group, blue)] < 0).all()


def test_cylindrical_texture_wraps_the_side_and_lays_flat_on_the_caps(project: Project) -> None:
    """#184: cylindrical wraps round the axis by arc length (texels keep their size); caps take it flat; faces across
    the seam get corner UVs on one side of it."""
    from kiln.paint import corner_uv

    _texture_image(project)
    text = ("name: thing\nparts:\n  - cylinder: { at: [0.5, 0.25, 0], radius: 0.2, height: 0.5 }\n    color: red\n"
            "    texture: { image: textures/tile.png, project: cylindrical, size: [0.1, 0.1] }\n")  # fmt: skip
    p = built_of(project, text).painted
    d = p.decals[0]
    assert len(p.decals) == 1 and (p.face_decal == 0).all() and d.at == (0.5, 0.25, 0.0)  # round the part's own axis
    corners = p.vertices[p.faces]
    uv = corner_uv(d, corners)
    span = uv[..., 0].max(axis=1) - uv[..., 0].min(axis=1)
    assert span.max() < 6  # no face smears across the seam (that would be the whole way round: 12.6 tiles; a cap is 4 across)
    np.testing.assert_allclose(decal_uv(d, np.array([[0.5, 0.25, 0.2], [0.7, 0.25, 0.0]]))[:, 0], [0.0, np.pi / 2 * 0.2 / 0.1], atol=1e-9)
    n = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    cap = np.abs(n[:, 1]) > 0.9 * np.linalg.norm(n, axis=1)
    top = corners[cap & (n[:, 1] > 0)]
    np.testing.assert_allclose(corner_uv(d, top)[..., 0], (top[..., 0] - 0.5) / 0.1, atol=1e-9)  # flat from above: u = x


def test_cone_tip_is_not_a_seam() -> None:
    from pathlib import Path

    from kiln.notation import Decal
    from kiln.paint import corner_uv

    d = Decal(Path("t.png"), "y", (0.0, 0.0, 0.0), (0.1, 0.1), "cylindrical")
    tri = np.array([[[0.0, 1.0, 0.0], [0.005, 0.5, -0.1], [-0.005, 0.5, -0.1]]])  # tip on the axis; base corners either side of the seam
    uv = corner_uv(d, tri)
    assert abs(uv[0, 1, 0] - uv[0, 2, 0]) < 0.2  # the base stays on one side of the seam (the tip's angle is ignored)


def test_decal_paints_over_a_texture(project: Project) -> None:
    _texture_image(project)
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(project.root / "decals" / "logo.png")
    text = ("name: thing\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: red\n"
            "    decal: { image: decals/logo.png, axis: z, at: [0, 0.2, 0.2], size: [0.2, 0.2] }\n"
            "    texture: { image: textures/tile.png, project: box, size: [0.1, 0.1] }\n")  # fmt: skip
    p = built_of(project, text).painted
    assert p.decals[0].project == "planar" and (p.face_decal == 0).any() and (p.face_decal >= 0).all()


def test_named_textures_and_triplanar(project: Project) -> None:
    """#320: a texture defined once under textures: and used by name on several parts; project: triplanar gives box
    UVs in the glb, a material name KILN's Godot scenes turn into uv1_triplanar, and a blended preview."""
    from kiln.builder import build_model
    from kiln.export import to_glb
    from kiln.render import View, render
    from kiln.vendor.gltf import read_glb

    _texture_image(project)
    text = ("name: thing\ntextures:\n  print: { image: textures/tile.png, project: triplanar, size: [0.1, 0.1] }\nparts:\n"
            "  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: red\n    texture: print\n"
            "  - sphere: { at: [0, 0.6, 0], radius: 0.15 }\n    color: red\n    texture: print\n")  # fmt: skip
    model, style = ok_model(project, text)
    assert all(p.texture is not None and p.texture.project == "triplanar" for p in model.parts)
    built = build_model(model, style, palette=project.palette(None)[0])
    doc, _ = read_glb(to_glb(built, "kiln"))
    assert any("_tri0.1x0.1#" in m["name"] for m in doc["materials"])
    image = np.asarray(render(built, View(30.0, 20.0), 96))
    blue = (image[..., 2] > 150) & (image[..., 0] < 80) & (image[..., 3] > 0)
    assert blue.sum() > 200  # the print shows in the preview
    errors = errors_of(project, text.replace("texture: print\n  - sphere", "texture: nope\n  - sphere"))
    assert any("isn't one of the model's textures" in f.message for f in errors)


def test_a_motif_print_scatters_coloured_stamps(project: Project) -> None:
    """#312: texture motif: stamps in several colours scattered over a seamless tile, seeded, made once."""
    from kiln.notation import load_model

    (project.root / "decals").mkdir(exist_ok=True)
    flower = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for x in range(16):
        for y in range(16):
            if (x - 7.5) ** 2 + (y - 7.5) ** 2 < 49:
                flower.putpixel((x, y), (230, 60, 140, 255) if (x - 7.5) ** 2 + (y - 7.5) ** 2 > 9 else (250, 210, 40, 255))
    flower.save(project.root / "decals" / "flower.png")
    Image.new("RGBA", (8, 16), (40, 150, 60, 255)).save(project.root / "decals" / "leaf.png")
    text = ("name: thing\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: white\n"
            "    texture: { motif: { images: [decals/flower.png, decals/leaf.png], count: 20, seed: 3 }, project: triplanar, size: [0.2, 0.2] }\n")  # fmt: skip
    model, _ = ok_model(project, text)
    tex = model.parts[0].texture
    assert tex is not None and tex.image.is_file() and ".kiln-cache" in str(tex.image)
    tile = np.asarray(Image.open(tex.image).convert("RGBA"))
    colours = {tuple(int(c) // 40 for c in px[:3]) for px in tile.reshape(-1, 4) if px[3] > 200}
    assert len(colours) >= 3  # pink, yellow, green
    again, _ = ok_model(project, text)
    assert again.parts[0].texture is not None and again.parts[0].texture.image == tex.image  # the same seed: the same tile
    palette, _ = project.palette(None)
    _, findings = load_model(write_model_text(project, text.replace("count: 20", "count: 0")), palette, set())
    assert any("motif is" in f.message for f in findings)


def write_model_text(project: Project, text: str) -> Path:
    path = project.models_dir / "thing.kiln.yaml"
    path.write_text(text)
    return path
