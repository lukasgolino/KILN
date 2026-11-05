"""The compiled distance kernel (#112, kiln[fast]) agrees with the numpy reference for every shape and transform."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from kiln import jit
from kiln.sdf import Copy, Field, Geometry, Noise, rotation_matrix

pytestmark = pytest.mark.skipif(not jit.AVAILABLE, reason="numba not installed (kiln[fast])")

SHAPES: dict[str, tuple[str, dict[str, Any]]] = {
    "sphere": ("sphere", {"radius": 0.4}),
    "ellipsoid": ("ellipsoid", {"radii": [0.5, 0.3, 0.2]}),
    "box": ("box", {"size": [0.6, 0.4, 0.3], "round": 0.05}),
    "cylinder": ("cylinder", {"radius": 0.3, "height": 0.6, "round": 0.02}),
    "octagon": ("cylinder", {"radius": 0.3, "height": 0.6, "round": 0.0, "sides": 8}),
    "cone": ("cone", {"radius": 0.4, "radius_top": 0.1, "height": 0.7}),
    "pyramid": ("cone", {"radius": 0.4, "radius_top": 0.0, "height": 0.7, "sides": 4}),
    "capsule": ("capsule", {"from": [0, -0.3, 0], "to": [0.2, 0.4, 0.1], "radius": 0.1, "radius_to": 0.2}),
    "tube": ("tube", {"points": [[0, 0, 0], [0.3, 0.2, 0], [0.4, 0.5, 0.3]], "radius": 0.1, "radius_to": 0.03}),
    "torus": ("torus", {"radius": 0.4, "thickness": 0.1}),
    "wedge": ("wedge", {"size": [0.6, 0.4, 0.5]}),
    "lock": ("lock", {"points": [[0, 0, 0], [0.1, 0.25, 0.05], [0.15, 0.45, 0.2]], "width": 0.08, "thickness": 0.02, "width_to": 0.0,
                      "thickness_to": 0.006, "facing": [0, 0, 1]}),
    "lathe": ("lathe", {"profile": [[0, -0.4], [0.3, -0.4], [0.2, 0.1], [0.35, 0.3], [0, 0.4]], "smooth": False}),
}


def variants() -> list[dict[str, Any]]:
    turned = {"at": np.array([0.1, -0.05, 0.2]), "rotation": rotation_matrix((20, 35, -10))}
    busy = {**turned, "mirror": (0,), "twist": 40.0, "shell": 0.03, "noise": Noise(0.02, 0.2, 7), "scale": np.array([1.0, 1.4, 0.6])}
    copies = (Copy(np.eye(3), np.zeros(3), np.zeros(3)), Copy(rotation_matrix((0, 90, 0)), np.array([0.1, 0, 0]), np.array([0, 0.2, 0])))
    opened = {**busy, "copies": copies, "open": (1, 1.0), "shell_side": "in"}
    return [{}, turned, busy, opened]


def numpy_path(fn: Any) -> Any:
    jit.AVAILABLE = False
    try:
        return fn()
    finally:
        jit.AVAILABLE = True


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_compiled_matches_numpy(name: str) -> None:
    shape, params = SHAPES[name]
    p = np.random.default_rng(0).uniform(-1, 1, (20_000, 3))
    for kw in variants():
        g = Geometry(shape, params, **kw)
        for filled in (False, True):
            np.testing.assert_allclose(g.distance(p, filled), numpy_path(lambda g=g, filled=filled: g.distance(p, filled)), atol=1e-12)
        field = Field([g], margin=0.01)
        np.testing.assert_allclose(field.part_distance(0, p), numpy_path(lambda field=field: field.part_distance(0, p)), atol=1e-12)


def test_compiled_is_deterministic() -> None:
    g = Geometry("tube", SHAPES["tube"][1], noise=Noise(0.02, 0.2, 3), twist=30.0)
    p = np.random.default_rng(1).uniform(-1, 1, (50_000, 3))
    np.testing.assert_array_equal(g.distance(p), g.distance(p))
