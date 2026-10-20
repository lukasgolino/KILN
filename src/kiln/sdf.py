"""Signed distance functions: KILN's shapes and how parts combine into one surface.

Every part is a shape (in its own local frame) moved by `at` + `rotate`, optionally mirrored, repeated, rounded,
hollowed or roughened, and then combined with what came before it: smooth union (`blend`), `cut` or
`intersect`. Distances are in metres; negative inside. +Y is up, the model's front faces +Z.

Shapes follow Inigo Quilez's distance functions (iquilezles.org/articles/distfunctions).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

Array = np.ndarray
Vec3 = tuple[float, float, float]
ShapeFn = Callable[[Array, dict[str, Any]], Array]
BoundsFn = Callable[[dict[str, Any]], tuple[Array, Array]]


# --- 2D helpers -------------------------------------------------------------------------------------


def polygon_2d(p: Array, points: Array) -> Array:
    """Signed distance from 2D points (N, 2) to a closed polygon (M, 2); negative inside."""
    d = ((p - points[0]) ** 2).sum(axis=1)
    sign = np.ones(len(p))
    j = len(points) - 1
    for i in range(len(points)):
        e = points[j] - points[i]
        w = p - points[i]
        t = np.clip((w @ e) / float(e @ e), 0.0, 1.0)
        b = w - t[:, None] * e
        d = np.minimum(d, (b * b).sum(axis=1))
        c1 = p[:, 1] >= points[i][1]
        c2 = p[:, 1] < points[j][1]
        c3 = e[0] * w[:, 1] > e[1] * w[:, 0]
        flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
        sign = np.where(flip, -sign, sign)
        j = i
    return np.sqrt(d) * sign


def _round_extrude(d2: Array, y: Array, half: float, r: float) -> Array:
    """Extrude a 2D distance along y (height 2*half), edges rounded by r (size kept)."""
    w = np.stack([d2 + r, np.abs(y) - half + r], axis=1)
    return np.minimum(w.max(axis=1), 0.0) + np.linalg.norm(np.maximum(w, 0.0), axis=1) - r


# --- shapes (local frame) -----------------------------------------------------------------------------


def sphere(p: Array, s: dict[str, Any]) -> Array:
    return np.linalg.norm(p, axis=1) - s["radius"]


def ellipsoid(p: Array, s: dict[str, Any]) -> Array:
    r = np.asarray(s["radii"], float)
    k0 = np.linalg.norm(p / r, axis=1)
    k1 = np.linalg.norm(p / (r * r), axis=1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-12)


def box(p: Array, s: dict[str, Any]) -> Array:
    r = s["round"]
    q = np.abs(p) - (np.asarray(s["size"], float) / 2 - r)
    return np.linalg.norm(np.maximum(q, 0.0), axis=1) + np.minimum(q.max(axis=1), 0.0) - r


def cylinder(p: Array, s: dict[str, Any]) -> Array:
    radial = np.linalg.norm(p[:, [0, 2]], axis=1) - s["radius"]
    return _round_extrude(radial, p[:, 1], s["height"] / 2, s["round"])


def cone(p: Array, s: dict[str, Any]) -> Array:
    """Capped cone along y: `radius` at the bottom (-height/2), `radius_top` at the top."""
    h, r1, r2 = s["height"] / 2, s["radius"], s["radius_top"]
    q = np.stack([np.linalg.norm(p[:, [0, 2]], axis=1), p[:, 1]], axis=1)
    k1 = np.array([r2, h])
    k2 = np.array([r2 - r1, 2 * h])
    ca = np.stack([q[:, 0] - np.minimum(q[:, 0], np.where(q[:, 1] < 0, r1, r2)), np.abs(q[:, 1]) - h], axis=1)
    t = np.clip(((k1 - q) @ k2) / float(k2 @ k2), 0.0, 1.0)
    cb = q - k1 + t[:, None] * k2
    sign = np.where((cb[:, 0] < 0) & (ca[:, 1] < 0), -1.0, 1.0)
    return sign * np.sqrt(np.minimum((ca * ca).sum(axis=1), (cb * cb).sum(axis=1)))


def _segment(p: Array, a: Array, b: Array, ra: float, rb: float) -> Array:
    pa, ba = p - a, b - a
    h = np.clip((pa @ ba) / max(float(ba @ ba), 1e-12), 0.0, 1.0)
    return np.linalg.norm(pa - h[:, None] * ba, axis=1) - (ra + (rb - ra) * h)


def capsule(p: Array, s: dict[str, Any]) -> Array:
    return _segment(p, np.asarray(s["from"], float), np.asarray(s["to"], float), s["radius"], s["radius_to"])


def tube(p: Array, s: dict[str, Any]) -> Array:
    """A rounded polyline (rope, branch, rail), radius going linearly from `radius` to `radius_to`."""
    pts = np.asarray(s["points"], float)
    lengths = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    along = np.concatenate([[0.0], np.cumsum(lengths)]) / max(float(lengths.sum()), 1e-12)
    radii = s["radius"] + (s["radius_to"] - s["radius"]) * along
    d = np.full(len(p), np.inf)
    for i in range(len(pts) - 1):
        d = np.minimum(d, _segment(p, pts[i], pts[i + 1], float(radii[i]), float(radii[i + 1])))
    return d


def torus(p: Array, s: dict[str, Any]) -> Array:
    """A ring in the xz plane (rotate it for others)."""
    ring = np.linalg.norm(p[:, [0, 2]], axis=1) - s["radius"]
    return np.sqrt(ring * ring + p[:, 1] * p[:, 1]) - s["thickness"]


def lathe(p: Array, s: dict[str, Any]) -> Array:
    """A 2D profile [[r, y], ...] (r >= 0) spun around the y axis: vases, bottles, towers, chess pieces."""
    q = np.stack([np.linalg.norm(p[:, [0, 2]], axis=1), p[:, 1]], axis=1)
    return polygon_2d(q, np.asarray(s["profile"], float))


def extrude(p: Array, s: dict[str, Any]) -> Array:
    """A 2D outline [[x, z], ...] (seen from above) extruded along y: floor plans, shields, signs, stars."""
    d2 = polygon_2d(p[:, [0, 2]], np.asarray(s["points"], float))
    return _round_extrude(d2, p[:, 1], s["height"] / 2, s["round"])


def wedge(p: Array, s: dict[str, Any]) -> Array:
    """A roof: a box whose top narrows to a ridge along x (cross-section: a triangle in the yz plane)."""
    w, h, d = (float(v) for v in s["size"])
    n = np.array([h, d / 2]) / math.hypot(h, d / 2)  # outward normal of the sloped faces (z, y)
    slope = n[0] * np.abs(p[:, 2]) + n[1] * (p[:, 1] - h / 2)
    flat = dict(s, round=0.0)
    return np.maximum(box(p, flat), slope)


@dataclass(frozen=True)
class ShapeDef:
    fn: ShapeFn
    fields: dict[str, str]  # name -> kind: num, pos (>0), nonneg, vec3, posvec3, points3, points2, profile
    required: tuple[str, ...]
    defaults: dict[str, Any]
    bounds: BoundsFn
    help: str


def _sym(half: Array) -> tuple[Array, Array]:
    return -half, half


def _bounds_capsule(s: dict[str, Any]) -> tuple[Array, Array]:
    a, b = np.asarray(s["from"], float), np.asarray(s["to"], float)
    r = max(s["radius"], s["radius_to"])
    return np.minimum(a, b) - r, np.maximum(a, b) + r


def _bounds_tube(s: dict[str, Any]) -> tuple[Array, Array]:
    pts = np.asarray(s["points"], float)
    r = max(s["radius"], s["radius_to"])
    return pts.min(axis=0) - r, pts.max(axis=0) + r


def _bounds_lathe(s: dict[str, Any]) -> tuple[Array, Array]:
    prof = np.asarray(s["profile"], float)
    r = float(np.abs(prof[:, 0]).max())
    return np.array([-r, prof[:, 1].min(), -r]), np.array([r, prof[:, 1].max(), r])


def _bounds_extrude(s: dict[str, Any]) -> tuple[Array, Array]:
    pts = np.asarray(s["points"], float)
    h = s["height"] / 2
    return np.array([pts[:, 0].min(), -h, pts[:, 1].min()]), np.array([pts[:, 0].max(), h, pts[:, 1].max()])


SHAPES: dict[str, ShapeDef] = {
    "sphere": ShapeDef(sphere, {"radius": "pos"}, ("radius",), {}, lambda s: _sym(np.full(3, s["radius"])), "radius"),
    "ellipsoid": ShapeDef(ellipsoid, {"radii": "posvec3"}, ("radii",), {}, lambda s: _sym(np.asarray(s["radii"], float)), "radii: [x, y, z]"),
    "box": ShapeDef(box, {"size": "posvec3", "round": "nonneg"}, ("size",), {"round": 0.0}, lambda s: _sym(np.asarray(s["size"], float) / 2),
                    "size: [x, y, z], round (edge radius, size kept)"),
    "cylinder": ShapeDef(cylinder, {"radius": "pos", "height": "pos", "round": "nonneg"}, ("radius", "height"), {"round": 0.0},
                         lambda s: _sym(np.array([s["radius"], s["height"] / 2, s["radius"]])), "radius, height (along y), round"),
    "cone": ShapeDef(cone, {"radius": "pos", "radius_top": "nonneg", "height": "pos"}, ("radius", "height"), {"radius_top": 0.0},
                     lambda s: _sym(np.array([max(s["radius"], s["radius_top"]), s["height"] / 2, max(s["radius"], s["radius_top"])])),
                     "radius (bottom), radius_top, height (along y)"),
    "capsule": ShapeDef(capsule, {"from": "vec3", "to": "vec3", "radius": "pos", "radius_to": "pos"}, ("from", "to", "radius"), {},
                        _bounds_capsule, "from: [x, y, z], to: [x, y, z], radius, radius_to (taper)"),
    "tube": ShapeDef(tube, {"points": "points3", "radius": "pos", "radius_to": "pos"}, ("points", "radius"), {}, _bounds_tube,
                     "points: [[x, y, z], ...] (2+), radius, radius_to (taper)"),
    "torus": ShapeDef(torus, {"radius": "pos", "thickness": "pos"}, ("radius", "thickness"), {},
                      lambda s: _sym(np.array([s["radius"] + s["thickness"], s["thickness"], s["radius"] + s["thickness"]])),
                      "radius (ring), thickness (tube radius); ring in the xz plane"),
    "lathe": ShapeDef(lathe, {"profile": "profile"}, ("profile",), {}, _bounds_lathe, "profile: [[r, y], ...] spun around y"),
    "extrude": ShapeDef(extrude, {"points": "points2", "height": "pos", "round": "nonneg"}, ("points", "height"), {"round": 0.0},
                        _bounds_extrude, "points: [[x, z], ...] outline seen from above, height (along y), round"),
    "wedge": ShapeDef(wedge, {"size": "posvec3"}, ("size",), {}, lambda s: _sym(np.asarray(s["size"], float) / 2),
                      "size: [x, y, z]; ridge along x at the top (a roof)"),
}


# --- transforms -----------------------------------------------------------------------------------------


def rotation_matrix(degrees: Vec3) -> Array:
    """Euler degrees [x, y, z], applied x first, then y, then z (all about the part's own centre)."""
    x, y, z = (math.radians(v) for v in degrees)
    cx, sx, cy, sy, cz, sz = math.cos(x), math.sin(x), math.cos(y), math.sin(y), math.cos(z), math.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return np.round(rz @ ry @ rx, 12)


def axis_rotation(axis: Array, degrees: float) -> Array:
    a = axis / np.linalg.norm(axis)
    t = math.radians(degrees)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.round(np.eye(3) + math.sin(t) * k + (1 - math.cos(t)) * (k @ k), 12)


@dataclass(frozen=True)
class Copy:
    """One repeat of a part: a rigid motion applied to the part (rotation about `pivot`, then `offset`)."""

    rotation: Array
    pivot: Array
    offset: Array

    def to_local(self, p: Array) -> Array:
        """Map world points into the frame of the original part (the inverse motion)."""
        return (p - self.offset - self.pivot) @ self.rotation + self.pivot

    def to_world(self, p: Array) -> Array:
        return (p - self.pivot) @ self.rotation.T + self.pivot + self.offset


IDENTITY = Copy(np.eye(3), np.zeros(3), np.zeros(3))


@dataclass(frozen=True)
class Noise:
    amount: float
    scale: float
    seed: int


def noise(p: Array, n: Noise) -> Array:
    """Deterministic smooth 3D noise in about [-1, 1]: a few octaves of products of sine waves along fixed random
    directions (seeded), so rocks and bark look lumpy without textures."""
    rng = np.random.default_rng(n.seed)
    out = np.zeros(len(p))
    total = 0.0
    for octave in range(3):
        dirs = rng.normal(size=(2, 3))
        phase = rng.uniform(0.0, 2 * math.pi, size=2)
        f = (2.0**octave) / n.scale
        w = 1.0 / (1.8**octave)
        out += w * np.sin(p @ dirs[0] * f + phase[0]) * np.sin(p @ dirs[1] * f + phase[1])
        total += w
    return out / total


# --- parts and the combined field ---------------------------------------------------------------------------


@dataclass
class Geometry:
    """The geometric half of a part (paint lives in notation.Part)."""

    shape: str
    params: dict[str, Any]
    at: Array = field(default_factory=lambda: np.zeros(3))
    rotation: Array | None = None  # local -> world
    mirror: tuple[int, ...] = ()  # axes folded (0 = x)
    copies: tuple[Copy, ...] = (IDENTITY,)
    op: str = "add"  # add | cut | intersect
    blend: float = 0.0
    shell: float = 0.0
    twist: float = 0.0  # degrees per metre about the local y axis
    noise: Noise | None = None

    def distance(self, p: Array) -> Array:
        if self.mirror:
            p = p.copy()
            for axis in self.mirror:
                p[:, axis] = np.abs(p[:, axis])
        fn = SHAPES[self.shape].fn
        best = np.full(len(p), np.inf)
        for copy in self.copies:
            q = copy.to_local(p) - self.at if copy is not IDENTITY else p - self.at
            if self.rotation is not None:
                q = q @ self.rotation
            if self.twist:
                angle = np.radians(self.twist) * q[:, 1]
                c, s = np.cos(angle), np.sin(angle)
                q = np.stack([c * q[:, 0] - s * q[:, 2], q[:, 1], s * q[:, 0] + c * q[:, 2]], axis=1)
            best = np.minimum(best, fn(q, self.params))
        if self.shell:
            best = np.abs(best) - self.shell
        if self.noise is not None:
            best = best + self.noise.amount * noise(p, self.noise)
        return best

    def bounds(self) -> tuple[Array, Array]:
        """World bounding box (expanded for noise/twist), mirror and copies included."""
        lo, hi = SHAPES[self.shape].bounds(self.params)
        if self.twist:
            r = float(np.linalg.norm(np.maximum(np.abs(lo), np.abs(hi))[[0, 2]]))
            lo, hi = np.array([-r, lo[1], -r]), np.array([r, hi[1], r])
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        if self.rotation is not None:
            corners = corners @ self.rotation.T
        corners = corners + self.at
        points = np.concatenate([copy.to_world(corners) for copy in self.copies])
        for axis in self.mirror:
            flipped = points.copy()
            flipped[:, axis] = -flipped[:, axis]
            points = np.concatenate([points, flipped])
        pad = self.shell + (self.noise.amount if self.noise else 0.0)
        return points.min(axis=0) - pad, points.max(axis=0) + pad


def box_distance(p: Array, lo: Array, hi: Array) -> Array:
    """Distance to an axis-aligned box (0 inside): a cheap lower bound for points far from a part."""
    q = np.maximum(np.maximum(lo - p, p - hi), 0.0)
    return np.linalg.norm(q, axis=1)


def smooth_min(a: Array, b: Array, k: float) -> Array:
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def smooth_max(a: Array, b: Array, k: float) -> Array:
    return -smooth_min(-a, -b, k)


class Field:
    """Parts combined in order. `evaluate` returns the surface distance and every adding part's own distance
    (used to paint each part's colour). Far from a part's box, its distance is replaced by the distance to the
    box (a lower bound), which never changes the result near the surface but skips most of the work."""

    def __init__(self, parts: list[Geometry], margin: float) -> None:
        self.parts = parts
        self.margin = margin
        self.boxes = [g.bounds() for g in parts]

    def bounds(self) -> tuple[Array, Array]:
        adding = [b for g, b in zip(self.parts, self.boxes, strict=True) if g.op == "add"]
        if not adding:
            return np.zeros(3), np.zeros(3)
        lo = np.min([b[0] for b in adding], axis=0)
        hi = np.max([b[1] for b in adding], axis=0)
        return lo, hi

    def part_distance(self, i: int, p: Array) -> Array:
        g, (lo, hi) = self.parts[i], self.boxes[i]
        pad = self.margin + g.blend
        near = np.all((p >= lo - pad) & (p <= hi + pad), axis=1)
        d = box_distance(p, lo, hi) + pad
        if near.any():
            d[near] = g.distance(p[near])
        return d

    def evaluate(self, p: Array, with_parts: bool = True) -> tuple[Array, list[Array]]:
        f = np.full(len(p), 1e9)
        per_part: list[Array] = []
        for i, g in enumerate(self.parts):
            d = self.part_distance(i, p)
            if g.op == "cut":
                f = smooth_max(f, -d, g.blend)
            elif g.op == "intersect":
                f = smooth_max(f, d, g.blend)
            else:
                f = smooth_min(f, d, g.blend)
            if with_parts:
                per_part.append(d)
        return f, per_part

    def distance(self, p: Array) -> Array:
        return self.evaluate(p, with_parts=False)[0]

    def gradient(self, p: Array, eps: float) -> Array:
        """Unit surface normals at p (central differences)."""
        offsets = np.eye(3) * eps
        stacked = np.concatenate([p + o for o in offsets] + [p - o for o in offsets])
        d = self.distance(stacked).reshape(6, len(p))
        g = (d[:3] - d[3:]).T
        n = np.linalg.norm(g, axis=1, keepdims=True)
        return np.asarray(g / np.maximum(n, 1e-12))
