"""Shapes, transforms and combination of the signed distance field."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from kiln.sdf import IDENTITY, SHAPES, Copy, Field, Geometry, Noise, axis_rotation, noise, rotation_matrix, smooth_max, smooth_min


def d(shape: str, params: dict[str, Any], *points: tuple[float, float, float]) -> np.ndarray:
    full = {**SHAPES[shape].defaults, **params}
    return SHAPES[shape].fn(np.array(points, float), full)


def test_sphere_distance() -> None:
    np.testing.assert_allclose(d("sphere", {"radius": 1.0}, (0, 0, 0), (2, 0, 0), (0, 1, 0)), [-1, 1, 0])


def test_ellipsoid_surface_and_sign() -> None:
    v = d("ellipsoid", {"radii": [1.0, 0.5, 0.25]}, (0, 0, 0), (1, 0, 0), (0, 0.5, 0), (0, 0, 0.25), (2, 0, 0))
    assert v[0] == pytest.approx(-0.25)  # the exact centre is inside, not on the surface
    assert v[4] > 0
    np.testing.assert_allclose(v[1:4], 0, atol=1e-9)


def test_box_keeps_its_size_when_rounded() -> None:
    for r in (0.0, 0.1):
        v = d("box", {"size": [2.0, 1.0, 0.5], "round": r}, (1, 0, 0), (0, 0.5, 0), (0, 0, 0.25), (0, 0, 0), (3, 0, 0))
        np.testing.assert_allclose(v[:3], 0, atol=1e-9)
        assert v[3] < 0
        assert v[4] == pytest.approx(2.0)
    # a rounded corner is cut off: the sharp corner is outside
    corner = d("box", {"size": [2.0, 2.0, 2.0], "round": 0.2}, (1, 1, 1))
    assert corner[0] > 0


def test_cylinder() -> None:
    v = d("cylinder", {"radius": 0.5, "height": 2.0}, (0.5, 0, 0), (0, 1, 0), (0, 0, 0), (0, 2, 0), (1, 0, 0))
    np.testing.assert_allclose(v, [0, 0, -0.5, 1, 0.5], atol=1e-9)


def test_cone_narrows_to_the_top() -> None:
    p = {"radius": 1.0, "radius_top": 0.0, "height": 2.0}
    v = d("cone", p, (1, -1, 0), (0, 1, 0), (0, -0.5, 0), (0.9, 0.9, 0))
    np.testing.assert_allclose(v[:2], 0, atol=1e-9)
    assert v[2] < 0 and v[3] > 0


def test_capsule_with_taper() -> None:
    p = {"from": [0, 0, 0], "to": [0, 1, 0], "radius": 0.2, "radius_to": 0.1}
    v = d("capsule", p, (0.2, 0, 0), (0.1, 1, 0), (0, -0.2, 0), (0, 0.5, 0), (1, 0.5, 0))
    np.testing.assert_allclose(v[:3], 0, atol=1e-9)
    assert v[3] < 0 and v[4] > 0


def test_tube_follows_its_points() -> None:
    p = {"points": [[0, 0, 0], [1, 0, 0], [1, 1, 0]], "radius": 0.1, "radius_to": 0.1}
    v = d("tube", p, (0.5, 0, 0), (1, 0.5, 0), (0.5, 0.1, 0), (0.5, 0.5, 0))
    np.testing.assert_allclose(v[:3], [-0.1, -0.1, 0], atol=1e-9)
    assert v[3] > 0


def test_torus_ring_in_xz() -> None:
    v = d("torus", {"radius": 1.0, "thickness": 0.2}, (1, 0, 0), (0, 0, 1.2), (0, 0, 0), (1, 0.2, 0))
    np.testing.assert_allclose(v, [-0.2, 0, 0.8, 0], atol=1e-9)


def test_lathe_spins_a_profile() -> None:
    p = {"profile": [[0, 0], [1, 0], [1, 1], [0, 1]]}  # a cylinder r 1, y 0..1
    v = d("lathe", p, (0, 0.5, 0), (0.5, 0.5, 0.5), (2, 0.5, 0), (0, 0.5, 1))
    assert v[0] == pytest.approx(-0.5)  # on the axis: deep inside (the profile's r = 0 edge isn't surface)
    assert v[1] == pytest.approx(-0.5, abs=0.21)
    assert v[2] == pytest.approx(1.0)
    assert v[3] == pytest.approx(0.0, abs=1e-9)


def test_extrude_outline_and_height() -> None:
    p = {"points": [[-1, -1], [1, -1], [1, 1], [-1, 1]], "height": 0.5, "round": 0.0}
    v = d("extrude", p, (0, 0, 0), (0, 0.25, 0), (1, 0, 0), (0, 1, 0), (0, 0, 2))
    np.testing.assert_allclose(v, [-0.25, 0, 0, 0.75, 1], atol=1e-9)


def test_wedge_is_a_roof() -> None:
    p = {"size": [2.0, 1.0, 1.0]}
    v = d("wedge", p, (0, 0.49, 0), (0, 0.45, 0.45), (0, -0.45, 0.3), (0, 0, 0))
    assert v[0] < 0  # the ridge
    assert v[1] > 0  # above a slope
    assert v[2] < 0  # low down, near the side: inside
    assert v[3] < 0


def test_shape_bounds_contain_the_surface() -> None:
    for name, params in (
        ("sphere", {"radius": 0.4}), ("box", {"size": [1, 2, 3]}), ("cone", {"radius": 1, "height": 2}),
        ("capsule", {"from": [0, 0, 0], "to": [1, 1, 0], "radius": 0.2, "radius_to": 0.2}),
        ("torus", {"radius": 1, "thickness": 0.2}),
    ):  # fmt: skip
        full = {**SHAPES[name].defaults, **params}
        lo, hi = SHAPES[name].bounds(full)
        rng = np.random.default_rng(0)
        pts = rng.uniform(lo - 1, hi + 1, size=(4000, 3))
        inside = SHAPES[name].fn(pts, full) < 0
        assert np.all(pts[inside] >= lo - 1e-9) and np.all(pts[inside] <= hi + 1e-9), name


def test_rotation_matrix_order_and_orthonormal() -> None:
    np.testing.assert_allclose(rotation_matrix((0, 0, 90)) @ [1, 0, 0], [0, 1, 0], atol=1e-12)
    np.testing.assert_allclose(rotation_matrix((90, 0, 0)) @ [0, 1, 0], [0, 0, 1], atol=1e-12)
    np.testing.assert_allclose(rotation_matrix((0, 90, 0)) @ [0, 0, 1], [1, 0, 0], atol=1e-12)
    # x first, then y: x 90 takes y to z, then y 90 takes z to x
    np.testing.assert_allclose(rotation_matrix((90, 90, 0)) @ [0, 1, 0], [1, 0, 0], atol=1e-12)
    m = rotation_matrix((17, -40, 123))
    np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-12)
    assert np.linalg.det(m) == pytest.approx(1.0)


def test_axis_rotation_matches_euler() -> None:
    np.testing.assert_allclose(axis_rotation(np.array([0.0, 1.0, 0.0]), 90), rotation_matrix((0, 90, 0)), atol=1e-12)


def test_copy_round_trip() -> None:
    c = Copy(rotation_matrix((10, 20, 30)), np.array([0.5, 0, 0]), np.array([1.0, 2.0, 3.0]))
    p = np.random.default_rng(1).normal(size=(20, 3))
    np.testing.assert_allclose(c.to_local(c.to_world(p)), p, atol=1e-12)
    np.testing.assert_allclose(IDENTITY.to_world(p), p)


def test_mirror_folds_and_bounds_cover_both_sides() -> None:
    g = Geometry("sphere", {"radius": 0.1}, at=np.array([0.5, 0.0, 0.0]), mirror=(0,))
    v = g.distance(np.array([[0.5, 0, 0], [-0.5, 0, 0], [0, 0, 0]]))
    np.testing.assert_allclose(v, [-0.1, -0.1, 0.4], atol=1e-12)
    lo, hi = g.bounds()
    np.testing.assert_allclose(lo, [-0.6, -0.1, -0.1])
    np.testing.assert_allclose(hi, [0.6, 0.1, 0.1])


def test_array_copies_and_bounds() -> None:
    copies = tuple(Copy(np.eye(3), np.zeros(3), np.array([0.5 * i, 0, 0])) for i in range(3))
    g = Geometry("sphere", {"radius": 0.1}, copies=copies)
    v = g.distance(np.array([[0.0, 0, 0], [0.5, 0, 0], [1.0, 0, 0], [0.25, 0, 0]]))
    np.testing.assert_allclose(v, [-0.1, -0.1, -0.1, 0.15], atol=1e-12)
    lo, hi = g.bounds()
    np.testing.assert_allclose(lo, [-0.1, -0.1, -0.1])
    np.testing.assert_allclose(hi, [1.1, 0.1, 0.1])


def test_ring_array_rotates_about_its_centre() -> None:
    copies = tuple(Copy(axis_rotation(np.array([0.0, 1.0, 0.0]), 90.0 * i), np.zeros(3), np.zeros(3)) for i in range(4))
    g = Geometry("sphere", {"radius": 0.1}, at=np.array([1.0, 0, 0]), copies=copies)
    v = g.distance(np.array([[1.0, 0, 0], [0, 0, 1.0], [-1.0, 0, 0], [0, 0, -1.0]]))
    np.testing.assert_allclose(v, -0.1, atol=1e-9)


def test_shell_and_twist() -> None:
    g = Geometry("sphere", {"radius": 1.0}, shell=0.1)
    np.testing.assert_allclose(g.distance(np.array([[0.0, 0, 0], [1.0, 0, 0]])), [0.9, -0.1], atol=1e-12)
    t = Geometry("box", {"size": [1.0, 1.0, 1.0], "round": 0.0}, twist=90.0)
    assert t.distance(np.array([[0.0, 0.0, 0.0]]))[0] < 0


def test_noise_is_deterministic_and_bounded() -> None:
    p = np.random.default_rng(2).uniform(-1, 1, size=(500, 3))
    a = noise(p, Noise(0.01, 0.2, 7))
    np.testing.assert_array_equal(a, noise(p, Noise(0.01, 0.2, 7)))
    assert np.abs(a).max() <= 1.0
    assert not np.array_equal(a, noise(p, Noise(0.01, 0.2, 8)))


def test_smooth_min_and_max() -> None:
    a, b = np.array([0.0, 1.0, -1.0]), np.array([0.0, 0.0, 2.0])
    np.testing.assert_array_equal(smooth_min(a, b, 0.0), np.minimum(a, b))
    s = smooth_min(a, b, 0.5)
    assert np.all(s <= np.minimum(a, b))
    assert s[0] == pytest.approx(-0.125)  # equal values: k / 4 below
    assert s[2] == pytest.approx(-1.0)  # far apart: plain min
    np.testing.assert_allclose(smooth_max(a, b, 0.5), -smooth_min(-a, -b, 0.5))


def test_field_cut_and_intersect() -> None:
    big = Geometry("sphere", {"radius": 1.0})
    hole = Geometry("sphere", {"radius": 0.5}, op="cut")
    f = Field([big, hole], margin=0.01)
    v = f.distance(np.array([[0.0, 0, 0], [0.75, 0, 0]]))
    assert v[0] > 0 and v[1] < 0
    inter = Field([big, Geometry("box", {"size": [4.0, 0.2, 4.0], "round": 0.0}, op="intersect")], margin=0.01)
    v = inter.distance(np.array([[0.0, 0, 0], [0.0, 0.5, 0]]))
    assert v[0] < 0 and v[1] > 0
    lo, hi = f.bounds()  # cuts don't grow the bounds
    np.testing.assert_allclose(hi, [1, 1, 1])


def test_field_far_shortcut_keeps_the_sign_and_the_surface() -> None:
    g = Geometry("sphere", {"radius": 0.2})
    f = Field([g], margin=0.01)
    far = f.part_distance(0, np.array([[3.0, 0, 0], [0, 5.0, 0]]))
    np.testing.assert_allclose(far, [2.81, 4.81])  # box distance + margin: positive, never near zero
    near = np.array([[0.2, 0, 0], [0, 0.1, 0]])
    np.testing.assert_array_equal(f.part_distance(0, near), g.distance(near))


def test_gradient_is_unit_and_outward() -> None:
    f = Field([Geometry("sphere", {"radius": 1.0})], margin=0.01)
    p = np.array([[1.0, 0, 0], [0, 0, -1.0], [0.6, 0.8, 0]])
    np.testing.assert_allclose(f.gradient(p, 1e-4), p, atol=1e-6)
