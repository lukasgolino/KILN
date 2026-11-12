"""The compiled distance kernel (#112, kiln-gen[fast]) agrees with the numpy reference for every shape and transform."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from kiln import jit
from kiln.sdf import Copy, Field, Geometry, Noise, rotation_matrix

pytestmark = pytest.mark.skipif(not jit.AVAILABLE, reason="numba not installed (kiln-gen[fast])")

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


def test_compiled_blend_to_matches_numpy() -> None:
    body = Geometry("sphere", {"radius": 0.3})
    lock = {"from": [-0.05, 0.25, 0], "to": [-0.05, 0.5, 0], "radius": 0.04, "radius_to": 0.04}
    parts = [body, Geometry("capsule", lock, blend=0.04, blend_to=frozenset({0})),
             Geometry("capsule", {**lock, "from": [0.05, 0.25, 0], "to": [0.05, 0.5, 0]}, blend=0.04, blend_to=frozenset({0})),
             Geometry("box", {"size": [0.2, 0.2, 0.2], "round": 0.0}, at=np.array([0.0, -0.3, 0.0]), op="cut"),
             Geometry("capsule", {**lock, "from": [0, -0.25, 0.1], "to": [0, -0.5, 0.1]}, blend=0.03, blend_to=frozenset({0}))]
    field = Field(parts, margin=0.01)
    p = np.random.default_rng(2).uniform(-0.6, 0.6, (50_000, 3))
    np.testing.assert_allclose(field.distance(p), numpy_path(lambda: field.distance(p)), atol=1e-12)


def test_compiled_many_blend_to_parts_match_numpy() -> None:
    """#220: hundreds of flush tufts melting into body parts by id, each into its own growing set (every earlier part
    with that id, earlier tufts included), mirrored, with a cut and an intersect among them: compiled and numpy agree.
    Tubes, not locks: a lock's distance underestimates away from it, where the two paths' box skips differ (#238)."""
    from kiln import sdf

    def geom(shape: str, params: dict[str, Any], **kw: Any) -> Geometry:
        return Geometry(shape, {**sdf.SHAPES[shape].defaults, **params}, **kw)

    rng = np.random.default_rng(5)
    parts = [geom("ellipsoid", {"radii": [0.2, 0.4, 0.15]}, at=np.array([0.0, 1.0, 0.0])),
             geom("capsule", {"from": [0.1, 0.6, 0], "to": [0.15, 0.1, 0], "radius": 0.07, "radius_to": 0.06}, blend=0.04, mirror=(0,))]
    for k in range(120):
        a, y = rng.uniform(0, 2 * np.pi), rng.uniform(0.2, 1.3)
        r = 0.16 if y > 0.65 else 0.08
        base = np.array([r * np.cos(a) + (0.12 if y < 0.65 else 0.0), y, r * np.sin(a)])
        tip = base + np.array([0.0, -0.08, 0.0]) + rng.normal(0, 0.01, 3)
        targets = frozenset(range(len(parts))) if k % 3 else frozenset({0, 1})
        parts.append(geom("tube", {"points": [base.tolist(), ((base + tip) / 2).tolist(), tip.tolist()], "radius": 0.012, "radius_to": 0.004},
                          blend=0.012, blend_to=targets, mirror=(0,) if k % 2 else ()))
        if k == 60:
            parts.append(geom("sphere", {"radius": 0.05}, at=np.array([0.0, 1.2, 0.15]), op="cut", blend=0.01))
    parts.append(geom("box", {"size": [2.0, 1.5, 2.0], "round": 0.0}, at=np.array([0.0, 0.8, 0.0]), op="intersect"))
    field = Field(parts, margin=0.03)
    p = rng.uniform([-0.4, 0.0, -0.3], [0.4, 1.5, 0.3], (20_000, 3))
    full = field.evaluate(p, with_parts=False)[0]  # no part skipped at all: the skip rule's meaning, not only agreement
    np.testing.assert_allclose(field.distance(p), full, atol=1e-12)
    np.testing.assert_allclose(numpy_path(lambda: field.distance(p)), full, atol=1e-12)


def test_serial_and_parallel_kernels_agree_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    """#154: small point sets run on one thread (a parallel call costs milliseconds however small); same numbers."""
    parts = [Geometry("ellipsoid", {"radii": [0.3, 0.4, 0.2]}),
             Geometry("tube", SHAPES["tube"][1], blend=0.03, blend_to=frozenset({0}), noise=Noise(0.01, 0.2, 3)),
             Geometry("sphere", {"radius": 0.1}, at=np.array([0.0, 0.3, 0.1]), op="cut", blend=0.02)]
    field = Field(parts, margin=0.02)
    p = np.random.default_rng(3).uniform(-0.6, 0.6, (3000, 3))
    few = p[:500]  # under SERIAL_FIELD, over one CHUNK: the serial field kernel and its one cache; 3000 < SERIAL_POINTS
    assert len(few) < jit.SERIAL_FIELD and len(few) > jit.CHUNK and len(p) < jit.SERIAL_POINTS
    serial_field, serial_part = field.distance(few), field.part_distance(1, p)
    monkeypatch.setattr(jit, "SERIAL_POINTS", 0)
    monkeypatch.setattr(jit, "SERIAL_FIELD", 0)
    np.testing.assert_array_equal(field.distance(few), serial_field)
    np.testing.assert_array_equal(field.part_distance(1, p), serial_part)


@pytest.mark.parametrize("absolute", [True, False])
@pytest.mark.parametrize("count", [500, 30_000])  # the one-thread kernel and the parallel one
def test_compiled_nearest_matches_the_part_loop(absolute: bool, count: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """#199: Field.nearest in one compiled pass gives the same parts and distances as one part_distance at a time
    (ties to the earlier part), for a subset in any order with a part twice, and extrudes among them (parts the kernel
    can't do: passed in, a block of points at a time)."""
    square = {"points": [[0, 0], [0.3, 0], [0.3, 0.2], [0, 0.2]], "height": 0.2, "round": 0.0, "holes": []}
    parts = [Geometry(*SHAPES[n]) for n in ("sphere", "capsule", "lock", "box", "torus")]
    parts.append(Geometry("extrude", square, at=np.array([0.1, 0.0, -0.1])))
    parts.append(Geometry("sphere", {"radius": 0.4}))  # the same as the first: ties
    parts.append(Geometry("extrude", square, at=np.array([-0.4, 0.2, 0.3])))
    field = Field(parts, margin=0.02)
    assert jit.MIN_POINTS <= 500 < jit.SERIAL_FIELD <= 30_000
    monkeypatch.setattr(jit, "NEAREST_PASSED", 2 * 200)  # blocks of 200 points (64 at least): several, and a short last one
    p = np.random.default_rng(4).uniform(-1, 1, (count, 3))
    chosen = [6, 7, 3, 5, 0, 2, 3, 4]  # not in order, the extrudes not first, the box twice, the capsule left out
    which, best = field.nearest(chosen, p, absolute)
    expect = numpy_path(lambda: Field(parts, margin=0.02).nearest(chosen, p, absolute))
    ref = np.full(len(p), np.inf), np.zeros(len(p), np.int64)
    for k, i in enumerate(chosen):  # the reference: compiled per-part distances, the old loop
        d = field.part_distance(i, p)
        d = np.abs(d) if absolute else d
        better = d < ref[0]
        ref[0][better], ref[1][better] = d[better], k
    np.testing.assert_array_equal(which, ref[1])
    np.testing.assert_array_equal(best, ref[0])
    assert (which == expect[0]).mean() > 0.999  # numpy's own shapes agree to rounding


def test_locks_and_ellipsoids_agree_in_both_paths() -> None:
    """#238: a lock's (and an ellipsoid's) distance ran short away from it, so the compiled kernel skipped it by its
    box where the numpy path still blended it in: the two disagreed (and numpy's answer depended on batch size)."""
    from conftest import parse

    from kiln.builder import field_of

    locks = "".join(f"  - lock: {{ points: [[{0.012 * k - 0.24:.3f}, 0.5, 0.2], [{0.012 * k - 0.24:.3f}, 0.8, 0.35]], width: 0.06, thickness: 0.015, "
                    f"width_to: 0 }}\n    color: red\n    blend: 0.03\n    blend_to: [body]\n" for k in range(40))  # fmt: skip
    model, findings = parse("name: m\nparts:\n  - ellipsoid: { at: [0, 0.5, 0], radii: [0.25, 0.4, 0.2] }\n    id: body\n    color: red\n" + locks)
    assert model is not None, findings
    field = field_of(model, 0.01)
    p = np.random.default_rng(3).uniform([-0.6, -0.1, -0.5], [0.6, 1.2, 0.8], (20000, 3))
    compiled = field.distance(p)
    jit.AVAILABLE = False
    try:
        plain = field.distance(p)
        small = np.concatenate([field.distance(p[k : k + 97]) for k in range(0, len(p), 97)])
    finally:
        jit.AVAILABLE = True
    assert np.abs(compiled - plain).max() < 1e-6 and np.abs(plain - small).max() < 1e-6


@pytest.mark.parametrize("shape", ["cone: { at: [0, 0.4, 0], radius: 0.3, radius_top: 0.12, height: 0.8 }",
                                   "cylinder: { at: [0.1, 0.4, 0], radius: 0.25, height: 0.6 }",
                                   "cylinder: { at: [0.1, 0.4, 0], radius: 0.25, height: 0.6 }\n    rotate: [20, 30, 10]",
                                   "cone: { at: [0.3, 0.4, 0], radius: 0.2, radius_top: 0.1, height: 0.6 }\n    array: { count: 3, around: y }",
                                   "cylinder: { at: [0, 0.4, 0], radius: 0.25, height: 0.6 }\n    scale: [1, 1.5, 0.8]"])  # fmt: skip
def test_folds_in_the_compiled_path_match_numpy(shape: str) -> None:
    """#281: the fold term in the kernel, the same as sdf.folds per copy, before the shell."""
    from conftest import parse

    from kiln.builder import field_of

    model, findings = parse(f"name: m\nparts:\n  - {shape}\n    color: red\n    folds: {{ count: 7, depth: 0.03, from_y: 0.0, to_y: 0.8, sharp: 0.6 }}\n"
                            "    shell: 0.02\n    mirror: x\n")  # fmt: skip
    assert model is not None, findings
    field = field_of(model, 0.01)
    assert jit.supported(field.parts[0])
    p = np.random.default_rng(5).uniform([-0.5, -0.1, -0.5], [0.5, 1.0, 0.5], (20000, 3))
    compiled = field.distance(p)
    jit.AVAILABLE = False
    try:
        plain = field.distance(p)
    finally:
        jit.AVAILABLE = True
    assert np.abs(compiled - plain).max() < 1e-9


def test_scaled_parts_agree_in_both_paths() -> None:
    """#238 review: scaled parts' distances run short outside their box too (any shape)."""
    from conftest import parse

    from kiln.builder import field_of

    spheres = "".join(f"  - sphere: {{ at: [{0.015 * k - 0.3:.3f}, 0.5, 0.22], radius: 0.03 }}\n    scale: [1, 4, 1]\n    color: red\n    blend: 0.03\n"
                      for k in range(40))  # fmt: skip
    model, findings = parse("name: m\nparts:\n  - ellipsoid: { at: [0, 0.5, 0], radii: [0.25, 0.4, 0.2] }\n    color: red\n" + spheres)
    assert model is not None, findings
    field = field_of(model, 0.01)
    p = np.random.default_rng(4).uniform([-0.6, -0.1, -0.5], [0.6, 1.2, 0.8], (20000, 3))
    compiled = field.distance(p)
    jit.AVAILABLE = False
    try:
        plain = field.distance(p)
    finally:
        jit.AVAILABLE = True
    assert np.abs(compiled - plain).max() < 1e-6
