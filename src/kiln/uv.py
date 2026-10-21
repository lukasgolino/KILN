"""Texture coordinates projected from a part's own shape (`uv:` on a part): for scrolling textures, dissolves and
flames that a shader runs along. Projections work in the part's local frame (its `at`, `rotate`, `twist`, mirror
and copies undone), so they follow the part however it is placed.

- cylindrical: u around the axis (0..1, seam at -z), v along it over the part's box (0 bottom, 1 top)
- spherical: u around the axis, v from the bottom pole (0) to the top (1)
- box: each face from its dominant direction, in metres / the box's largest side (even texel density)
- along: like cylindrical, but tubes and capsules follow their path (v = distance along it, 0..1)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from kiln.sdf import IDENTITY, SHAPES, Array, Geometry

PROJECTIONS = ("cylindrical", "spherical", "box", "along")
AXES = {"x": 0, "y": 1, "z": 2}


@dataclass(frozen=True)
class UVSpec:
    project: str
    axis: int = 1
    scale: tuple[float, float] = (1.0, 1.0)


def local(g: Geometry, p: Array) -> Array:
    """Points in the part's local frame (the copy nearest to each point)."""
    if g.mirror:
        p = p.copy()
        for axis in g.mirror:
            p[:, axis] = np.abs(p[:, axis])
    fn = SHAPES[g.shape].fn
    best_d = np.full(len(p), np.inf)
    best_q = np.zeros_like(p)
    for copy in g.copies:
        q = copy.to_local(p) - g.at if copy is not IDENTITY else p - g.at
        if g.rotation is not None:
            q = q @ g.rotation
        if g.twist:
            angle = np.radians(g.twist) * q[:, 1]
            c, s = np.cos(angle), np.sin(angle)
            q = np.stack([c * q[:, 0] - s * q[:, 2], q[:, 1], s * q[:, 0] + c * q[:, 2]], axis=1)
        d = np.abs(fn(q, g.params)) if len(g.copies) > 1 else np.zeros(len(p))
        closer = d < best_d
        best_d[closer] = d[closer]
        best_q[closer] = q[closer]
    return best_q


def _around(q: Array, axis: int) -> Array:
    a, b = {0: (1, 2), 1: (0, 2), 2: (0, 1)}[axis]
    return np.asarray(np.arctan2(q[:, a], q[:, b]) / (2 * math.pi) + 0.5)


def _path(g: Geometry) -> Array | None:
    if g.shape == "tube":
        return np.array(g.params["points"], dtype=float)
    if g.shape == "capsule":
        return np.array([g.params["from"], g.params["to"]], dtype=float)
    return None


def _along(q: Array, path: Array) -> tuple[Array, Array]:
    """(u around, v along) for points near a polyline: nearest segment, distance along it over the total length."""
    seg = np.diff(path, axis=0)
    length = np.linalg.norm(seg, axis=1)
    total = max(float(length.sum()), 1e-12)
    start = np.concatenate([[0.0], np.cumsum(length)])[:-1]
    best = np.full(len(q), np.inf)
    v = np.zeros(len(q))
    u = np.zeros(len(q))
    for i in range(len(seg)):
        d = seg[i] / max(length[i], 1e-12)
        t = np.clip((q - path[i]) @ d, 0.0, length[i])
        foot = path[i] + t[:, None] * d
        r = q - foot
        dist = np.linalg.norm(r, axis=1)
        closer = dist < best
        best[closer] = dist[closer]
        v[closer] = (start[i] + t[closer]) / total
        ref = np.array([0.0, 1.0, 0.0]) if abs(d[1]) < 0.9 else np.array([1.0, 0.0, 0.0])
        e1 = np.cross(d, ref)
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        u[closer] = np.arctan2(r[closer] @ e1, r[closer] @ e2) / (2 * math.pi) + 0.5
    return u, v


def project(g: Geometry, spec: UVSpec, corners: Array) -> Array:
    """UVs (F, 3, 2) for triangles `corners` (F, 3, 3) on part `g`; faces that cross the seam are unwrapped."""
    flat = corners.reshape(-1, 3)
    q = local(g, flat)
    lo, hi = (np.asarray(x, dtype=float) for x in SHAPES[g.shape].bounds(g.params))
    size = np.maximum(hi - lo, 1e-9)
    a = spec.axis
    wraps = True
    if spec.project == "box":
        qf = q.reshape(-1, 3, 3)
        n = np.cross(qf[:, 1] - qf[:, 0], qf[:, 2] - qf[:, 0])
        dominant = np.repeat(np.argmax(np.abs(n), axis=1), 3)
        others = np.array([[1, 2], [0, 2], [0, 1]])[dominant]
        rel = (q - lo) / float(size.max())
        rows = np.arange(len(q))
        uv = np.stack([rel[rows, others[:, 0]], rel[rows, others[:, 1]]], axis=1)
        wraps = False
    elif spec.project == "along" and (path := _path(g)) is not None:
        u, v = _along(q, path)
        uv = np.stack([u, v], axis=1)
    elif spec.project == "spherical":
        centre = (lo + hi) / 2
        r = q - centre
        cos = np.clip(r[:, a] / np.maximum(np.linalg.norm(r, axis=1), 1e-12), -1.0, 1.0)
        uv = np.stack([_around(r, a), 1.0 - np.arccos(cos) / math.pi], axis=1)
    else:  # cylindrical (and along on shapes without a path)
        centre = (lo + hi) / 2
        uv = np.stack([_around(q - centre, a), (q[:, a] - lo[a]) / size[a]], axis=1)
    uv = uv.reshape(-1, 3, 2)
    if wraps:  # a face spanning the seam: lift its small u values past 1
        u = uv[:, :, 0]
        cross = (u.max(axis=1) - u.min(axis=1)) > 0.5
        u[cross] = np.where(u[cross] < 0.5, u[cross] + 1.0, u[cross])
    return np.asarray(uv * np.array(spec.scale))


__all__ = ["AXES", "PROJECTIONS", "UVSpec", "local", "project"]
