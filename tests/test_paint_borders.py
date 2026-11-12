"""#191: paint borders along blends and decal edges are clean curves, not sawtooth (a regression guard)."""

from __future__ import annotations

import numpy as np
from conftest import write_model

from kiln.lint import lint_paths
from kiln.project import Project

SLEEVE = """\
name: thing
budget: 3000
parts:
  - capsule: { from: [0, 0.1, 0], to: [0, 0.7, 0], radius: 0.06 }
    color: wood
  - capsule: { from: [0, 0.45, 0], to: [0, 0.68, 0], radius: 0.075 }
    color: blue
    blend: 0.02
"""


def border_points(p: object, a: int, b: int) -> np.ndarray:
    """Vertices on edges between faces of groups a and b."""
    faces, groups = p.faces, p.face_group  # type: ignore[attr-defined]
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    owner = np.tile(groups, 3)
    key = edges[:, 0] * len(p.vertices) + edges[:, 1]  # type: ignore[attr-defined]
    order = np.argsort(key, kind="stable")
    key, owner, edges = key[order], owner[order], edges[order]
    twin = np.flatnonzero(key[1:] == key[:-1])
    on = twin[((owner[twin] == a) & (owner[twin + 1] == b)) | ((owner[twin] == b) & (owner[twin + 1] == a))]
    return p.vertices[np.unique(edges[on])]  # type: ignore[attr-defined, no-any-return]


def test_a_sleeve_border_is_a_clean_ring(project: Project) -> None:
    p = lint_paths(project, [write_model(project, SLEEVE)]).built["thing"].painted
    names = [g.color_name.split("#")[0] for g in p.groups]
    border = border_points(p, names.index("wood"), names.index("blue"))
    for ring in (border[border[:, 1] < 0.6], border[border[:, 1] > 0.6]):  # the sleeve's lower edge, and its top round the arm's cap
        assert len(ring) >= 8
        height = ring[:, 1]
        assert float(height.max() - height.min()) < 0.004  # a flat ring round the arm: no zigzag up and down it
        radius = np.linalg.norm(ring[:, [0, 2]], axis=1)
        assert float(radius.std()) < 0.002  # round, not notched


def test_a_decal_edge_follows_its_rectangle(project: Project, tmp_path: object) -> None:
    from PIL import Image

    (project.root / "decals" / "square.png").parent.mkdir(exist_ok=True)
    Image.new("RGBA", (64, 64), (250, 220, 40, 255)).save(project.root / "decals" / "square.png")
    ball = "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: blue\n" \
           "    decal: { image: decals/square.png, axis: z, at: [0, 0.3, 0.3], size: [0.3, 0.3] }\n"
    p = lint_paths(project, [write_model(project, ball)]).built["thing"].painted
    on = p.face_decal >= 0
    edge = np.zeros(len(p.vertices), dtype=bool)  # vertices of decal faces that also touch plain faces
    inside = np.zeros(len(p.vertices), dtype=bool)
    inside[p.faces[on].reshape(-1)] = True
    outside = np.zeros(len(p.vertices), dtype=bool)
    outside[p.faces[~on].reshape(-1)] = True
    edge = inside & outside
    xy = p.vertices[edge][:, :2] - [0, 0.3]
    gap = np.abs(np.abs(xy) - 0.15).min(axis=1)  # distance to the nearer side of the 0.3 m square (seen along z)
    assert len(xy) >= 16 and float(gap.max()) < 0.003  # the edge lies on the rectangle: cut, not stepped by triangles
