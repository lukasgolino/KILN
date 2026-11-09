"""Dual contouring, decimation and connected pieces."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from conftest import closed, signed_volume

from kiln.mesher import MAX_CELLS, Mesh, components, decimate, dual_contour, grid_step, model_step, pinches, remove_unused, unpinch
from kiln.sdf import SHAPES, Field, Geometry


def field(shape: str, params: dict[str, Any], at: tuple[float, float, float] = (0, 0, 0)) -> Field:
    return Field([Geometry(shape, {**SHAPES[shape].defaults, **params}, at=np.array(at, float))], margin=0.06)


def check_closed_outward(mesh: Mesh) -> None:
    assert mesh.triangles > 0
    assert closed(mesh)
    assert signed_volume(mesh.vertices, mesh.faces) > 0  # counter-clockwise from outside


def test_sphere_is_closed_and_on_the_surface() -> None:
    f = field("sphere", {"radius": 0.5})
    mesh = dual_contour(f, 0.04)
    check_closed_outward(mesh)
    r = np.linalg.norm(mesh.vertices[np.unique(mesh.faces)], axis=1)
    assert np.abs(r - 0.5).max() < 0.02
    assert signed_volume(mesh.vertices, mesh.faces) == pytest.approx(4 / 3 * np.pi * 0.125, rel=0.03)
    assert components(mesh) == 1


def test_box_keeps_sharp_corners() -> None:
    f = field("box", {"size": [0.6, 0.4, 0.5]})
    mesh = dual_contour(f, 0.035)
    check_closed_outward(mesh)
    v = mesh.vertices[np.unique(mesh.faces)]
    np.testing.assert_allclose(v.min(axis=0), [-0.3, -0.2, -0.25], atol=2e-3)
    np.testing.assert_allclose(v.max(axis=0), [0.3, 0.2, 0.25], atol=2e-3)
    corner = np.array([0.3, 0.2, 0.25])
    assert np.linalg.norm(v - corner, axis=1).min() < 5e-3  # a vertex sits on the corner (marching cubes would bevel it)
    assert signed_volume(mesh.vertices, mesh.faces) == pytest.approx(0.6 * 0.4 * 0.5, rel=0.01)


def test_cylinder_closed_with_flat_caps() -> None:
    f = field("cylinder", {"radius": 0.3, "height": 0.8}, (0, 0.4, 0))
    mesh = dual_contour(f, 0.04)
    check_closed_outward(mesh)
    v = mesh.vertices[np.unique(mesh.faces)]
    assert v[:, 1].min() == pytest.approx(0.0, abs=2e-3)
    assert v[:, 1].max() == pytest.approx(0.8, abs=2e-3)
    assert np.linalg.norm(v[:, [0, 2]], axis=1).max() == pytest.approx(0.3, abs=5e-3)


def test_lathe_touching_the_axis_has_no_inner_surface() -> None:
    # r / step + 2.5 is a whole number: a column of grid points lies exactly on the axis
    f = Field([Geometry("lathe", {"profile": [[0, 0], [0.25, 0], [0.25, 0.5], [0, 0.5]]})], margin=0.06)
    mesh = dual_contour(f, 0.02)
    check_closed_outward(mesh)
    v = mesh.vertices[np.unique(mesh.faces)]
    r = np.linalg.norm(v[:, [0, 2]], axis=1)
    assert not np.any((r < 0.1) & (v[:, 1] > 0.1) & (v[:, 1] < 0.4))


def test_ellipsoid_centre_on_the_grid_is_inside() -> None:
    f = Field([Geometry("ellipsoid", {"radii": [0.25, 0.25, 0.25]})], margin=0.06)  # 0.25 / 0.025 + 2.5: on the grid
    mesh = dual_contour(f, 0.025)
    check_closed_outward(mesh)
    assert components(mesh) == 1


def test_decimate_hits_the_budget_and_stays_on_the_surface() -> None:
    f = field("sphere", {"radius": 0.5})
    mesh = dual_contour(f, 0.02)
    assert mesh.triangles > 2000
    small = decimate(f, mesh, 500, 0.02)
    assert small.triangles <= 500
    assert small.triangles > 300
    r = np.linalg.norm(small.vertices[np.unique(small.faces)], axis=1)
    assert np.abs(r - 0.5).max() < 2e-3
    assert decimate(f, mesh, 10**6, 0.02) is mesh


def test_components_counts_pieces() -> None:
    a = Geometry("sphere", {"radius": 0.2}, at=np.array([-0.5, 0, 0]))
    b = Geometry("sphere", {"radius": 0.2}, at=np.array([0.5, 0, 0]))
    mesh = dual_contour(Field([a, b], margin=0.05), 0.04)
    assert closed(mesh)
    assert components(mesh) == 2
    joined = Geometry("box", {"size": [1.0, 0.1, 0.1], "round": 0.0})
    assert components(dual_contour(Field([a, b, joined], margin=0.05), 0.04)) == 1


def test_cut_makes_a_closed_hollow() -> None:
    outer = Geometry("box", {"size": [0.6, 0.6, 0.6], "round": 0.0})
    hole = Geometry("cylinder", {"radius": 0.15, "height": 1.0, "round": 0.0}, op="cut")
    mesh = dual_contour(Field([outer, hole], margin=0.05), 0.03)
    check_closed_outward(mesh)
    assert signed_volume(mesh.vertices, mesh.faces) == pytest.approx(0.216 - np.pi * 0.15**2 * 0.6, rel=0.03)


def test_empty_field_gives_an_empty_mesh() -> None:
    only_cut = Field([Geometry("sphere", {"radius": 0.2}, op="cut")], margin=0.05)
    assert dual_contour(only_cut, 0.05).triangles == 0


def test_remove_unused() -> None:
    m = Mesh(np.array([[0.0, 0, 0], [9, 9, 9], [1, 0, 0], [0, 1, 0]]), np.array([[0, 2, 3]]))
    out = remove_unused(m)
    assert len(out.vertices) == 3
    np.testing.assert_array_equal(out.vertices[out.faces[0]], m.vertices[[0, 2, 3]])


def test_grid_step_limits_cells() -> None:
    assert grid_step(1.0, 0.01) == 0.01
    assert 100.0 / grid_step(100.0, 0.01) <= MAX_CELLS
    small = model_step(field("sphere", {"radius": 0.5}), 0.01)
    big = model_step(field("sphere", {"radius": 4.0}), 0.01)
    assert small == pytest.approx(0.01)
    assert big > small


def test_meshing_is_deterministic() -> None:
    f = field("capsule", {"from": [0, 0, 0], "to": [0.3, 0.5, 0.1], "radius": 0.15, "radius_to": 0.1})
    a, b = dual_contour(f, 0.03), dual_contour(f, 0.03)
    np.testing.assert_array_equal(a.vertices, b.vertices)
    np.testing.assert_array_equal(a.faces, b.faces)


def test_decimate_regions_keeps_borders_and_stays_closed() -> None:
    from kiln.mesher import decimate_regions

    f = field("sphere", {"radius": 0.5})
    mesh = dual_contour(f, 0.02)
    region = (mesh.vertices[mesh.faces].mean(axis=1)[:, 1] > 0.2).astype(np.int64)  # a cap and the rest
    out, out_region = decimate_regions(f, mesh, region, 600, 0.02)
    assert out.triangles <= 700 and len(out_region) == out.triangles
    check_closed_outward(out)
    # the border between the two regions survives decimation, thinned out
    full = mesh.vertices[np.unique(mesh.faces[region == 1])]
    rest = mesh.vertices[np.unique(mesh.faces[region == 0])]
    border_full = {tuple(np.round(p, 9)) for p in full} & {tuple(np.round(p, 9)) for p in rest}
    a = {tuple(np.round(p, 9)) for p in out.vertices[np.unique(out.faces[out_region == 1])]}
    b = {tuple(np.round(p, 9)) for p in out.vertices[np.unique(out.faces[out_region == 0])]}
    assert a & b and len(a & b) < len(border_full)  # thinned out, but present


def test_grid_grows_where_blends_bulge_out_of_the_boxes() -> None:
    # a straw tuft: seven capsules blended at one hub; the smooth unions bulge below every part's box, out of the
    # sampling grid, and dual contouring left a hole in the bottom (E013, #11)
    ends = [(0.121, 0.205, -0.433), (-0.448, 0.065, 0.042), (0.45, 0.166, 0.001), (-0.442, 0.19, 0.084), (-0.314, 0.193, 0.322),
            (-0.064, 0.2, 0.445), (-0.057, 0.104, -0.446)]  # fmt: skip
    parts = [Geometry("capsule", {**SHAPES["capsule"].defaults, "from": (0, 0.05, 0), "to": e, "radius": 0.035, "radius_to": 0.02}, blend=0.03)
             for e in ends]  # fmt: skip
    f = Field(parts, margin=0.06)
    step = 0.005
    assert f.distance(np.array([[0.0, f.bounds()[0][1] - 2.5 * step, 0.0]]))[0] < 0  # the surface is below the old grid
    check_closed_outward(dual_contour(f, step))


def no_pinches(mesh: Mesh) -> bool:
    edges, vertices = pinches(mesh.vertices, mesh.faces)
    return len(edges) == 0 and len(vertices) == 0


def test_a_wall_thinner_than_a_cell_meshes_as_a_manifold() -> None:
    # #25: both sides of the wall cross the same cells; one vertex per cell pinched them together (edges with four faces)
    shell = Geometry("sphere", {**SHAPES["sphere"].defaults, "radius": 0.3}, shell=0.012, shell_side="in", open=(1, -1.0))
    mesh = dual_contour(Field([shell], margin=0.06), 0.02)
    check_closed_outward(mesh)
    assert no_pinches(mesh)


def test_decimating_a_thin_plate_leaves_no_pinches() -> None:
    # #25: the simplifier doesn't check that an edge's ends share only the vertices across it, and joined both sides
    # of a plate thinner than its triangles
    f = field("box", {"size": [0.6, 0.012, 0.6]})
    mesh = dual_contour(f, 0.02)
    for budget in (2000, 600):
        out = decimate(f, mesh, budget, 0.02)
        assert out.triangles <= budget * 1.02
        check_closed_outward(out)
        assert no_pinches(out)
        assert np.abs(f.distance(out.vertices)).max() < 0.004  # each side pulled back onto its own surface


def tetrahedron(flip: tuple[float, float, float] = (1, 1, 1)) -> tuple[np.ndarray, np.ndarray]:
    v = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float) * np.array(flip)
    f = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    return v, (f if np.prod(flip) > 0 else f[:, ::-1])


def test_unpinch_splits_sheets_that_touch() -> None:
    a, fa = tetrahedron()
    for shared, flip in ((1, (-1, -1, -1)), (2, (1, -1, -1))):  # touching at a vertex; along an edge (four faces on it)
        b, fb = tetrahedron(flip)
        v = np.concatenate([a, b[shared:]])
        f = np.concatenate([fa, np.where(fb < shared, fb, fb + 4 - shared)])
        edges, vertices = pinches(v, f)
        assert (len(edges), len(vertices)) == ((0, 1) if shared == 1 else (1, 0))
        out = Mesh(*unpinch(v, f))
        assert len(out.vertices) == len(v) + shared and no_pinches(out)
        check_closed_outward(out)
        untouched = np.flatnonzero(~np.isin(f, np.arange(shared)).any(axis=1))
        np.testing.assert_array_equal(out.faces[untouched], f[untouched])
    # a few faces split off a bigger piece are a pocket a collapse folded up: dropped
    ball = dual_contour(field("sphere", {"radius": 0.3}), 0.05)
    top = int(np.argmax(ball.vertices[:, 1]))
    v = np.concatenate([ball.vertices, a[1:] * 0.01 + ball.vertices[top]])
    f = np.concatenate([ball.faces, np.where(fa == 0, top, fa - 1 + len(ball.vertices))])
    np.testing.assert_array_equal(unpinch(v, f)[1], ball.faces)


def test_thin_sharp_rim_reaches_its_edge() -> None:
    # #25: a cone roof overhanging its post; the rim's tip is thinner than a cell. Crossing points taken linearly
    # between grid values sat off the surface there (with the rim's in-between normal), and best-fit points beyond
    # their cell were held back: the rim came out ragged, up to 3/4 of a step short
    step = 0.02
    post = Geometry("cylinder", {**SHAPES["cylinder"].defaults, "radius": 0.2, "height": 0.6}, at=np.array([0, 0.3, 0.0]))
    roof = Geometry("cone", {**SHAPES["cone"].defaults, "radius": 0.4, "radius_top": 0.0, "height": 0.3}, at=np.array([0, 0.75, 0.0]))
    mesh = dual_contour(Field([post, roof], margin=0.06), step)
    check_closed_outward(mesh)
    v = mesh.vertices[np.unique(mesh.faces)]
    rim = v[np.abs(v[:, 1] - 0.6) < 2 * step]
    sector = ((np.arctan2(rim[:, 2], rim[:, 0]) + np.pi) / (2 * np.pi) * 90).astype(int) % 90
    radius = np.linalg.norm(rim[:, [0, 2]], axis=1)
    reach = (np.array([radius[sector == k].max() for k in range(90)]) - 0.4) / step  # the rim's furthest point, per 4 degrees
    assert reach.min() > -0.2 and reach.max() < 0.05 and reach.std() < 0.05


def test_close_pockets_joins_twin_caps_but_not_touching_sheets() -> None:
    """#131: two copies of a vertex at one place capping the same ring (a zero-volume pocket) are joined and their
    faces go as twins; two sheets that only touch at a point keep their vertices."""
    from kiln.mesher import close_pockets, drop_twins

    v = np.array([[0, 0, 0], [0, 0, 0], [1, 0, 0], [0, 1, 0], [-1, -1, 0.0], [5, 5, 5], [6, 5, 5], [5, 6, 5]], dtype=float)
    caps = np.array([[1, 3, 2], [1, 2, 4], [1, 4, 3], [0, 2, 3], [0, 4, 2], [0, 3, 4]])
    f, tag = drop_twins(*close_pockets(v, caps, np.arange(len(caps))))
    assert len(f) == 0 and len(tag) == 0
    touching = np.array([[0, 2, 3], [1, 6, 7]])  # vertices 0 and 1 at one place, different neighbours
    (f,) = close_pockets(v, touching)
    np.testing.assert_array_equal(f, touching)


def test_close_pockets_needs_twin_caps_not_just_the_same_neighbours() -> None:
    """Coincident vertices fanning over the same neighbours in another order (or wound the same way) aren't a pocket."""
    from kiln.mesher import close_pockets

    v = np.array([[0, 0, 0], [0, 0, 0], [1, 0, 0], [0, 1, 0], [-1, 0, 0], [0, -1, 0]], dtype=float)
    a = [[0, 2, 3], [0, 3, 4], [0, 4, 5], [0, 5, 2]]
    b = [[1, 2, 4], [1, 4, 3], [1, 3, 5], [1, 5, 2]]  # same neighbours, another fan order
    faces = np.array(a + b)
    (f,) = close_pockets(v, faces)
    np.testing.assert_array_equal(f, faces)
    same_way = np.array(a + [[1, x, y] for _, x, y in a])  # a duplicate cap wound the same way
    (f,) = close_pockets(v, same_way)
    np.testing.assert_array_equal(f, same_way)


def _relax_reference(f_: Field, mesh: Mesh, fixed: np.ndarray, step: float, iterations: int = 8, rate: float = 0.5) -> Mesh:
    """relax as it was before it re-tested only the faces that moved: every face, every round."""
    from kiln.mesher import BAD_ASPECT, BAD_TILT_COS, nearest_part, project

    v, f = mesh.vertices.copy(), mesh.faces
    e = np.unique(np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1), axis=0)
    a, b = np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]])
    degree = np.bincount(a, minlength=len(v)).astype(float)
    normal = f_.gradient(v, step * 0.01)
    crease = np.zeros(len(v), dtype=bool)
    part = nearest_part(f_, v)
    sharp = (normal[e[:, 0]] * normal[e[:, 1]]).sum(axis=1) < BAD_TILT_COS
    sharp &= ~fixed[e[:, 0]] & ~fixed[e[:, 1]] & (part[e[:, 0]] == part[e[:, 1]])
    crease[e[sharp].reshape(-1)] = True
    for _ in range(iterations):
        p = v[f]
        n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        area2 = np.linalg.norm(n, axis=1)
        tilt = (n * f_.gradient(p.mean(axis=1), step * 0.01)).sum(axis=1) < BAD_TILT_COS * area2
        longest = np.max(np.linalg.norm(p - np.roll(p, 1, axis=1), axis=2), axis=1)
        bad = tilt | (longest**2 > BAD_ASPECT * np.maximum(area2, 1e-18))
        free = np.zeros(len(v), dtype=bool)
        free[f[bad].reshape(-1)] = True
        free &= ~fixed & ~crease & (degree > 0)
        if not free.any():
            break
        mean = np.zeros_like(v)
        np.add.at(mean, a, v[b])
        mean[free] /= degree[free, None]
        nrm = f_.gradient(v[free], step * 0.01)
        move = mean[free] - v[free]
        move -= (move * nrm).sum(axis=1, keepdims=True) * nrm
        v[free] = project(f_, v[free] + rate * move, step, 1)
    return Mesh(v, f)


def test_relax_retesting_only_moved_faces_gives_the_same_mesh() -> None:
    """Relaxing re-tests only faces next to a vertex that moved (the rest keep their verdict): identical output."""
    from kiln.mesher import relax

    fld = field("box", {"size": [0.6, 0.3, 0.4], "round": 0.05})
    mesh = decimate(fld, dual_contour(fld, 0.02), 300, 0.02)
    rng = np.random.default_rng(3)
    jittered = Mesh(mesh.vertices + rng.normal(0, 0.01, mesh.vertices.shape), mesh.faces)  # plenty of bad faces
    fixed = rng.random(len(mesh.vertices)) < 0.1
    new, old = relax(fld, jittered, fixed, 0.02), _relax_reference(fld, jittered, fixed, 0.02)
    assert np.array_equal(new.vertices, old.vertices) and not np.array_equal(new.vertices, jittered.vertices)
