"""#191: paint borders along blends are clean curves at any budget, and decal edges are cut lines, not triangle steps."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import built_of, write_model
from PIL import Image

from kiln.builder import field_of
from kiln.lint import lint_paths
from kiln.paint import DECAL_FACING
from kiln.project import Project

SLEEVE = """\
name: thing
budget: BUDGET
parts:
  - capsule: { from: [0, 0.1, 0], to: [0, 0.7, 0], radius: 0.06 }
    color: wood
  - capsule: { from: [0, 0.45, 0], to: [0, 0.68, 0], radius: 0.075 }
    color: blue
    blend: 0.02
"""
TILTED = """\
name: thing
budget: BUDGET
parts:
  - capsule: { from: [0, 0.1, 0], to: [0.25, 0.65, 0.1], radius: 0.06 }
    color: wood
  - capsule: { from: [0.12, 0.36, 0.05], to: [0.24, 0.63, 0.1], radius: 0.072 }
    color: blue
    blend: 0.015
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


def ring_quality(ring: np.ndarray) -> tuple[float, float]:
    """(largest distance from the ring's best plane, largest turn in degrees going round it in order): a sawtooth is
    off the plane and turns sharply back and forth; a clean ring (tilted or not) is neither."""
    centre = ring.mean(axis=0)
    _, _, vt = np.linalg.svd(ring - centre)
    normal, u, v = vt[2], vt[0], vt[1]
    off = float(np.abs((ring - centre) @ normal).max())
    angle = np.arctan2((ring - centre) @ v, (ring - centre) @ u)
    loop = ring[np.argsort(angle)]
    seg = np.diff(np.concatenate([loop, loop[:1]]), axis=0)
    seg /= np.maximum(np.linalg.norm(seg, axis=1, keepdims=True), 1e-12)
    turn = np.degrees(np.arccos(np.clip((seg * np.roll(seg, -1, axis=0)).sum(axis=1), -1, 1)))
    return off, float(turn.max())


@pytest.mark.parametrize("budget", [3000, 900, 500])
@pytest.mark.parametrize("model", ["sleeve", "tilted"])
def test_a_sleeve_border_is_a_clean_ring_at_any_budget(project: Project, budget: int, model: str) -> None:
    text = (SLEEVE if model == "sleeve" else TILTED).replace("BUDGET", str(budget))
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    p = built.painted
    names = [g.color_name.split("#")[0] for g in p.groups]
    border = border_points(p, names.index("wood"), names.index("blue"))
    shapes = field_of(built.model, built.step).parts
    exact = np.abs(shapes[0].distance(border) - shapes[1].distance(border))
    assert float(exact.max()) < 0.0005, (model, budget, float(exact.max()))  # every border vertex on the exact border
    axis = np.array([0, 1.0, 0]) if model == "sleeve" else np.array([0.24 - 0.12, 0.63 - 0.36, 0.1 - 0.05])
    along = (border - border.mean(axis=0)) @ (axis / np.linalg.norm(axis))
    for ring in (border[along < 0], border[along > 0]):  # the sleeve's lower edge, and its top round the arm
        assert len(ring) >= 6, (model, budget)
        off, turn = ring_quality(ring)
        assert turn < 60, (model, budget, turn)  # no sharp back-and-forth
        if model == "sleeve":
            assert off < 0.0007, (budget, off)  # coaxial: the exact border is a flat ring


@pytest.mark.parametrize(("radius", "budget"), [(0.2, None), (0.05, None), (0.05, 200)])  # a thin or coarse drum too
def test_a_decal_wrapping_a_side_ends_on_a_clean_line(project: Project, radius: float, budget: int | None) -> None:
    Image.new("RGBA", (64, 64), (250, 220, 40, 255)).save(project.root / "decals" / "square.png")
    drum = f"name: thing\n{f'budget: {budget}' if budget else ''}\nparts:\n  - cylinder: {{ at: [0, 0.3, 0], radius: {radius}, height: 0.4 }}\n" \
           f"    color: blue\n    decal: {{ image: decals/square.png, axis: z, at: [0, 0.3, {radius}], size: [{3 * radius}, 0.2] }}\n"
    p = lint_paths(project, [write_model(project, drum)]).built["thing"].painted
    on = p.face_decal >= 0
    inside = np.zeros(len(p.vertices), dtype=bool)
    inside[p.faces[on].reshape(-1)] = True
    outside = np.zeros(len(p.vertices), dtype=bool)
    outside[p.faces[~on].reshape(-1)] = True
    edge = p.vertices[inside & outside]
    side = edge[np.abs(edge[:, 1] - 0.3) < 0.095]  # off the rectangle's top and bottom: where it turns away round the drum
    assert len(side) >= (4 if budget is None else 1)  # (a coarse drum: few points between the rectangle's corners)
    facing = side[:, 2] / np.linalg.norm(side[:, [0, 2]], axis=1)  # the drum's normal . z there
    assert float(np.abs(facing - DECAL_FACING).max()) < 0.1, (radius, budget)  # on the facing limit, not stepped along triangles


def test_a_decal_edge_follows_its_rectangle(project: Project) -> None:
    Image.new("RGBA", (64, 64), (250, 220, 40, 255)).save(project.root / "decals" / "square.png")
    ball = "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: blue\n" \
           "    decal: { image: decals/square.png, axis: z, at: [0, 0.3, 0.3], size: [0.3, 0.3] }\n"
    p = lint_paths(project, [write_model(project, ball)]).built["thing"].painted
    on = p.face_decal >= 0
    inside = np.zeros(len(p.vertices), dtype=bool)
    inside[p.faces[on].reshape(-1)] = True
    outside = np.zeros(len(p.vertices), dtype=bool)
    outside[p.faces[~on].reshape(-1)] = True
    xy = p.vertices[inside & outside][:, :2] - [0, 0.3]
    gap = np.abs(np.abs(xy) - 0.15).min(axis=1)  # distance to the nearer side of the 0.3 m square (seen along z)
    assert len(xy) >= 16 and float(gap.max()) < 0.003


def test_a_border_cut_across_follows_what_paint_paints(project: Project) -> None:
    """A cut after the sleeve takes part of its surface away: the border it leaves is where paint puts it."""
    text = SLEEVE.replace("BUDGET", "900") + "  - torus: { at: [0, 0.45, 0], radius: 0.075, thickness: 0.012 }\n    cut: true\n"
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    p = built.painted
    names = [g.color_name.split("#")[0] for g in p.groups]
    border = border_points(p, names.index("wood"), names.index("blue"))
    shapes = field_of(built.model, built.step).parts
    sleeve = np.maximum(shapes[1].distance(border), -shapes[2].distance(border))  # the sleeve less the cut, as paint
    arm = np.maximum(shapes[0].distance(border), -shapes[2].distance(border))
    assert len(border) >= 6 and float(np.median(np.abs(sleeve - arm))) < 0.0005


def test_a_decal_on_a_faceted_part_skips_sides_square_to_it(project: Project) -> None:
    Image.new("RGBA", (64, 64), (250, 220, 40, 255)).save(project.root / "decals" / "square.png")
    prism = "name: thing\nparts:\n  - cylinder: { at: [0, 0.3, 0], radius: 0.2, height: 0.4, sides: 8 }\n    color: blue\n    hard: true\n" \
            "    decal: { image: decals/square.png, axis: z, at: [0, 0.3, 0.2], size: [0.5, 0.2] }\n"
    p = lint_paths(project, [write_model(project, prism)]).built["thing"].painted
    tri = p.vertices[p.faces[p.face_decal >= 0]]
    normal = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normal /= np.linalg.norm(normal, axis=1, keepdims=True)
    assert len(tri) and float((normal @ np.array([0, 0, 1.0])).min()) > DECAL_FACING  # no decal on the sides square to it


def test_a_decal_draws_no_facing_line_through_flat_faces(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    """On a hard part the face's own normal decides; a facing-limit line through its flat faces (vertex normals
    average across crisp edges) only added triangles (+45% on a decal-heavy hard watch case)."""
    from kiln import paint

    Image.new("RGBA", (8, 8), (250, 220, 40, 255)).save(project.root / "decals" / "top.png")
    text = ("name: NAME\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.6, 0.4, 0.6] }\n    color: red\n    hard: true\n"
            "    decal: { image: decals/top.png, axis: y, at: [0, 0.4, 0], size: [0.7, 0.7] }\n")  # fmt: skip
    counts = []
    for k, limit in enumerate((0.25, -2.0)):  # -2: no facing line at all (each build its own model: its own cache entry)
        monkeypatch.setattr(paint, "DECAL_FACING", limit)
        counts.append(built_of(project, text.replace("NAME", f"thing{k}"), f"thing{k}").triangles)
    assert counts[0] == counts[1], counts
