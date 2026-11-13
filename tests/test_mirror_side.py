"""#363: a `mirror` part written on the negative side of its axis mirrors to the positive side (it used to vanish)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import built_of, make_project

from kiln import jit
from kiln.sdf import Geometry

LEGS = """\
name: thing
parts:
  - box: {{ at: [0, 0.5, 0], size: [0.5, 0.05, 0.5] }}
    color: red
  - box: {{ at: [{x}, 0.25, 0.2], size: [0.05, 0.5, 0.05] }}
    mirror: x
    color: blue
"""


def _span(tmp_path: Path, x: float) -> tuple[np.ndarray, np.ndarray]:
    project = make_project(tmp_path / str(x))
    built = built_of(project, LEGS.format(x=x))
    v = built.painted.vertices[np.unique(built.painted.faces)]
    return v.min(axis=0), v.max(axis=0)


def test_left_and_right_mirror_alike(tmp_path: Path) -> None:
    lo_l, hi_l = _span(tmp_path, -0.2)
    lo_r, hi_r = _span(tmp_path, 0.2)
    assert lo_l[1] < 0.02 and lo_r[1] < 0.02  # the legs reach the floor on both
    np.testing.assert_allclose([lo_l, hi_l], [lo_r, hi_r], atol=0.02)


def test_sides_follow_the_part() -> None:
    left = Geometry("box", {"size": [0.1, 0.1, 0.1], "round": 0.0}, np.array([-0.3, 0.0, 0.2]), mirror=(0, 2))
    assert left.mirror_sides().tolist() == [-1.0, 1.0, 1.0]
    d = left.distance(np.array([[-0.3, 0.0, 0.2], [0.3, 0.0, 0.2], [0.3, 0.0, -0.2], [-0.3, 0.0, -0.2]]))
    assert (d < 0).all()  # the part and its three mirror images


@pytest.mark.skipif(not jit.AVAILABLE, reason="needs numba (kiln[fast])")
def test_compiled_distance_agrees() -> None:
    g = Geometry("box", {"size": [0.1, 0.2, 0.1], "round": 0.0}, np.array([-0.3, 0.1, 0.0]), mirror=(0,))
    rng = np.random.default_rng(3)
    p = rng.uniform(-0.6, 0.6, (jit.MIN_POINTS + 10, 3))
    np.testing.assert_allclose(jit.distance(g, p, False), _numpy(g, p), atol=1e-9)


def _numpy(g: Geometry, p: np.ndarray) -> np.ndarray:
    saved = jit.AVAILABLE
    jit.AVAILABLE = False
    try:
        return g.distance(p)
    finally:
        jit.AVAILABLE = saved
