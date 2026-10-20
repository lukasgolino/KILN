"""Dual contouring, decimation and connected pieces."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from conftest import closed, signed_volume
from kiln.mesher import MAX_CELLS, Mesh, components, decimate, dual_contour, grid_step, model_step, remove_unused
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
