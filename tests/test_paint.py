"""Paint: cutting triangles along borders, colour groups, patterns and decals."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from conftest import built_of, closed_faces, sphere_text
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
    assert y.min() >= 0.25 - 1e-6 and y.max() <= 0.35 + 1e-6


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
