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


def polygon_2d(p: Array, points: Array, skip: Array | None = None) -> Array:
    """Signed distance from 2D points (N, 2) to a closed polygon (M, 2); negative inside. `skip[i]` leaves the
    edge from point i-1 to point i out of the distance (it still counts for inside/outside)."""
    if skip is not None:
        return _even_odd(p, points, np.roll(points, 1, axis=0), skip)
    return polygons_2d(p, [points])


def _even_odd(p: Array, a: Array, b: Array, skip: Array | None = None) -> Array:
    """Distance to edges a[i] -> b[i] (every edge, a Python loop over them), signed by the even-odd rule."""
    d = np.full(len(p), np.inf)
    sign = np.ones(len(p))
    for i in range(len(a)):
        e = b[i] - a[i]
        w = p - a[i]
        if (skip is None or not skip[i]) and float(e @ e) > 0:  # a zero-length edge adds nothing (and would be NaN)
            t = np.clip((w @ e) / float(e @ e), 0.0, 1.0)
            r = w - t[:, None] * e
            d = np.minimum(d, (r * r).sum(axis=1))
        c1 = p[:, 1] >= a[i][1]
        c2 = p[:, 1] < b[i][1]
        c3 = e[0] * w[:, 1] > e[1] * w[:, 0]
        flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
        sign = np.where(flip, -sign, sign)
    if not np.isfinite(d).all():  # every edge skipped or zero length: the first point stands in
        d = np.minimum(d, ((p - a[0]) ** 2).sum(axis=1))
    return np.sqrt(d) * sign


@dataclass(frozen=True)
class _Outline:
    """Closed loops as oriented edges a -> b (outer loops counter-clockwise, holes clockwise, by even-odd nesting),
    with outward unit normals per edge and per vertex (the sum of its two edges': the sign test at corners)."""

    a: Array
    b: Array
    normal: Array
    a_vertex: Array  # global vertex index of a / b (into vertex_normal)
    b_vertex: Array
    vertex_normal: Array
    lo: Array  # edge boxes
    hi: Array
    simple: bool  # no two edges cross: the nearest edge decides inside/outside


_OUTLINES: dict[bytes, _Outline] = {}


def _area(loop: Array) -> float:
    x, y = loop[:, 0], loop[:, 1]
    return float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2)


def _crossing(a: Array, b: Array) -> bool:
    """Do any two non-adjacent edges intersect?"""
    n = len(a)
    if n > 4000:
        return True  # too many to check: use the even-odd path

    def orient(p: Array, q: Array, r: Array) -> Array:
        return np.asarray((q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0]))

    lo, hi = np.minimum(a, b), np.maximum(a, b)
    for start in range(0, n, 256):
        i = np.arange(start, min(n, start + 256))
        overlap = (lo[i, None, 0] <= hi[None, :, 0]) & (lo[None, :, 0] <= hi[i, None, 0]) & (lo[i, None, 1] <= hi[None, :, 1]) & (lo[None, :, 1] <= hi[i, None, 1])
        shares = np.isclose(a[i, None], a[None]).all(-1) | np.isclose(a[i, None], b[None]).all(-1) | np.isclose(b[i, None], a[None]).all(-1) \
            | np.isclose(b[i, None], b[None]).all(-1)
        ii, jj = np.nonzero(overlap & ~shares & (i[:, None] < np.arange(n)[None, :]))
        if not len(ii):
            continue
        ii = i[ii]
        o1 = orient(a[ii], b[ii], a[jj])
        o2 = orient(a[ii], b[ii], b[jj])
        o3 = orient(a[jj], b[jj], a[ii])
        o4 = orient(a[jj], b[jj], b[ii])
        if ((o1 * o2 <= 0) & (o3 * o4 <= 0)).any():
            return True
    return False


def _outline(loops: list[Array]) -> _Outline:
    key = b"|".join(np.ascontiguousarray(loop, dtype=np.float64).tobytes() for loop in loops)
    if key in _OUTLINES:
        return _OUTLINES[key]
    clean = []
    for loop in loops:
        loop = np.asarray(loop, dtype=np.float64)
        keep = np.any(loop != np.roll(loop, 1, axis=0), axis=1)  # repeated points
        clean.append(loop[keep] if keep.sum() >= 3 else loop)
    a_all, b_all, n_all, av, bv, vn = [], [], [], [], [], []
    base = 0
    for k, loop in enumerate(clean):
        others = [o for m, o in enumerate(clean) if m != k]
        depth = sum(int(_even_odd(loop[:1], o, np.roll(o, 1, axis=0))[0] < 0) for o in others)
        if (_area(loop) > 0) != (depth % 2 == 0):
            loop = loop[::-1]
        a, b = np.roll(loop, 1, axis=0), loop  # edge i: point i-1 -> point i (counter-clockwise for outer loops)
        d = b - a
        length = np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-300)
        n = np.stack([d[:, 1], -d[:, 0]], axis=1) / length  # right of travel = outside
        m = len(loop)
        a_all.append(a)
        b_all.append(b)
        n_all.append(n)
        av.append(base + (np.arange(m) - 1) % m)
        bv.append(base + np.arange(m))
        vn.append(n + np.roll(n, -1, axis=0))  # vertex i ends edge i and starts edge i+1
        base += m
    a, b = np.concatenate(a_all), np.concatenate(b_all)
    out = _Outline(a, b, np.concatenate(n_all), np.concatenate(av), np.concatenate(bv), np.concatenate(vn), np.minimum(a, b), np.maximum(a, b),
                   not _crossing(a, b))  # fmt: skip
    if len(_OUTLINES) > 256:
        _OUTLINES.clear()
    _OUTLINES[key] = out
    return out


def _segment_d2(p: Array, a: Array, b: Array) -> tuple[Array, Array]:
    """Squared distance from points to segments (row by row) and the unclamped parameter along them."""
    e = b - a
    w = p - a
    ee = np.maximum((e * e).sum(axis=-1), 1e-300)
    t = (w * e).sum(axis=-1) / ee
    tc = np.clip(t, 0.0, 1.0)
    r = w - tc[..., None] * e
    return (r * r).sum(axis=-1), t


PAIRS = 2_000_000  # point-edge pairs per batch


def polygons_2d(p: Array, loops: list[Array]) -> Array:
    """Signed distance to closed loops (outlines with holes: even-odd, a loop inside another is a hole); negative
    inside. Each point only measures the edges that can be nearest to it: points are binned in tiles, and a tile
    keeps the edges no farther from its box than its centre's nearest edge plus its half diagonal. The nearest
    edge (or corner) then gives the sign, for outlines whose edges don't cross (else the even-odd loop)."""
    o = _outline(loops)
    n, m = len(p), len(o.a)
    if not n:
        return np.zeros(0)
    if not o.simple or n * m < 50_000:
        return _even_odd(p, o.a, o.b)
    lo, hi = p.min(axis=0), p.max(axis=0)
    g = int(np.clip(math.sqrt(n / 64), 1, 128))
    cell = np.maximum((hi - lo) / g, 1e-9)
    tx = np.minimum(((p - lo) / cell).astype(np.int64), g - 1)
    tile = tx[:, 0] * g + tx[:, 1]
    tiles, tile_of = np.unique(tile, return_inverse=True)
    t_lo = lo + np.stack([tiles // g, tiles % g], axis=1) * cell
    t_hi = t_lo + cell
    centre = (t_lo + t_hi) / 2
    half = float(np.linalg.norm(cell)) / 2
    cand_rows = []
    step = max(1, PAIRS // max(m, 1))
    for s0 in range(0, len(tiles), step):
        c = centre[s0 : s0 + step]
        d2, _ = _segment_d2(c[:, None, :], o.a[None], o.b[None])
        bound = np.sqrt(d2.min(axis=1)) + half
        gap = np.maximum(np.maximum(o.lo[None] - t_hi[s0 : s0 + step, None], t_lo[s0 : s0 + step, None] - o.hi[None]), 0.0)
        cand_rows.append(np.linalg.norm(gap, axis=2) <= bound[:, None] + 1e-12)
    cand = np.concatenate(cand_rows)
    count = cand.sum(axis=1)
    flat = np.nonzero(cand)[1]
    offset = np.concatenate([[0], np.cumsum(count)])[:-1]
    out = np.empty(n)
    order = np.argsort(tile_of, kind="stable")
    per = count[tile_of[order]]
    ends = np.cumsum(per)
    s0 = 0
    while s0 < n:
        s1 = int(np.searchsorted(ends, (ends[s0 - 1] if s0 else 0) + PAIRS, side="right"))
        s1 = min(max(s1, s0 + 1), n)
        pts = order[s0:s1]
        k = per[s0:s1]
        start = np.concatenate([[0], np.cumsum(k)])[:-1]
        pi = np.repeat(np.arange(len(pts)), k)
        ei = flat[offset[tile_of[pts]][pi] + np.arange(len(pi)) - start[pi]]
        q = p[pts][pi]
        d2, t = _segment_d2(q, o.a[ei], o.b[ei])
        best = np.minimum.reduceat(d2, start)
        hit = np.flatnonzero(d2 <= best[pi])
        first = hit[np.unique(pi[hit], return_index=True)[1]]
        e, tt = ei[first], t[first]
        normal = np.where((tt <= 0)[:, None], o.vertex_normal[o.a_vertex[e]],
                          np.where((tt >= 1)[:, None], o.vertex_normal[o.b_vertex[e]], o.normal[e]))  # fmt: skip
        foot = o.a[e] + np.clip(tt, 0.0, 1.0)[:, None] * (o.b[e] - o.a[e])
        side = ((p[pts] - foot) * normal).sum(axis=1)
        out[pts] = np.sqrt(best) * np.where(side > 0, 1.0, -1.0)
        s0 = s1
    return out


def _round_extrude(d2: Array, y: Array, half: float, r: float) -> Array:
    """Extrude a 2D distance along y (height 2*half), edges rounded by r (size kept)."""
    w = np.stack([d2 + r, np.abs(y) - half + r], axis=1)
    return np.minimum(w.max(axis=1), 0.0) + np.linalg.norm(np.maximum(w, 0.0), axis=1) - r


def radial(p: Array, s: dict[str, Any]) -> Array:
    """Distance from the y axis; with `sides`, the regular polygon's own measure (corners on the radius, the first
    side facing +z), so a `sides: 8` cylinder is an octagonal prism."""
    n = s.get("sides")
    if not n:
        return np.linalg.norm(p[:, [0, 2]], axis=1)
    a = 2 * np.pi * np.arange(int(n)) / int(n)
    return (p[:, [0, 2]] @ np.stack([np.sin(a), np.cos(a)])).max(axis=1) / math.cos(math.pi / int(n))


# --- shapes (local frame) -----------------------------------------------------------------------------


def sphere(p: Array, s: dict[str, Any]) -> Array:
    return np.linalg.norm(p, axis=1) - s["radius"]


def ellipsoid(p: Array, s: dict[str, Any]) -> Array:
    r = np.asarray(s["radii"], float)
    k0 = np.linalg.norm(p / r, axis=1)
    k1 = np.linalg.norm(p / (r * r), axis=1)
    # at the exact centre the formula gives 0 (on the surface): it is the deepest point inside
    return np.where(k1 > 1e-12, k0 * (k0 - 1.0) / np.maximum(k1, 1e-12), -float(r.min()))


def box(p: Array, s: dict[str, Any]) -> Array:
    r = s["round"]
    q = np.abs(p) - (np.asarray(s["size"], float) / 2 - r)
    return np.linalg.norm(np.maximum(q, 0.0), axis=1) + np.minimum(q.max(axis=1), 0.0) - r


def cylinder(p: Array, s: dict[str, Any]) -> Array:
    return _round_extrude(radial(p, s) - s["radius"], p[:, 1], s["height"] / 2, s["round"])


def cone(p: Array, s: dict[str, Any]) -> Array:
    """Capped cone along y: `radius` at the bottom (-height/2), `radius_top` at the top."""
    h, r1, r2 = s["height"] / 2, s["radius"], s["radius_top"]
    q = np.stack([radial(p, s), p[:, 1]], axis=1)
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
    ring = radial(p, s) - s["radius"]
    return np.sqrt(ring * ring + p[:, 1] * p[:, 1]) - s["thickness"]


def smooth_profile(points: list[list[float]], rounds: int = 3) -> list[list[float]]:
    """Chaikin corner cutting on a closed outline; points on the axis (r = 0) stay put, so the shape stays closed."""
    pts = [list(p) for p in points]
    for _ in range(rounds):
        out: list[list[float]] = []
        n = len(pts)
        for i in range(n):
            prev, cur, nxt = pts[i - 1], pts[i], pts[(i + 1) % n]
            if cur[0] == 0.0:
                out.append(cur)
                continue
            out.append([0.75 * cur[0] + 0.25 * prev[0], 0.75 * cur[1] + 0.25 * prev[1]])
            out.append([0.75 * cur[0] + 0.25 * nxt[0], 0.75 * cur[1] + 0.25 * nxt[1]])
        pts = out
    return pts


def lathe(p: Array, s: dict[str, Any]) -> Array:
    """A 2D profile [[r, y], ...] (r >= 0) spun around the y axis: vases, bottles, towers, chess pieces."""
    prof = np.asarray(s["profile"], float)
    # profile edges lying on the axis aren't surface (the axis is inside the solid); points exactly on the axis
    # are nudged off it so inside/outside is decided by the profile, not by a tie on that edge
    on_axis = (prof[:, 0] == 0) & (np.roll(prof[:, 0], 1) == 0)
    q = np.stack([np.maximum(radial(p, s), 1e-9), p[:, 1]], axis=1)
    return polygon_2d(q, prof, on_axis if on_axis.any() else None)


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
    "sphere": ShapeDef(sphere, {"radius": "pos", "sides": "sides"}, ("radius",), {}, lambda s: _sym(np.full(3, s["radius"])),
                       "radius, sides (hard parts)"),
    "ellipsoid": ShapeDef(ellipsoid, {"radii": "posvec3", "sides": "sides"}, ("radii",), {}, lambda s: _sym(np.asarray(s["radii"], float)),
                          "radii: [x, y, z], sides (hard parts)"),
    "box": ShapeDef(box, {"size": "posvec3", "round": "nonneg"}, ("size",), {"round": 0.0}, lambda s: _sym(np.asarray(s["size"], float) / 2),
                    "size: [x, y, z], round (edge radius, size kept)"),
    "cylinder": ShapeDef(cylinder, {"radius": "pos", "height": "pos", "round": "nonneg", "sides": "sides"}, ("radius", "height"), {"round": 0.0},
                         lambda s: _sym(np.array([s["radius"], s["height"] / 2, s["radius"]])), "radius, height (along y), round, sides (8: an octagon)"),
    "cone": ShapeDef(cone, {"radius": "pos", "radius_top": "nonneg", "height": "pos", "sides": "sides"}, ("radius", "height"), {"radius_top": 0.0},
                     lambda s: _sym(np.array([max(s["radius"], s["radius_top"]), s["height"] / 2, max(s["radius"], s["radius_top"])])),
                     "radius (bottom), radius_top, height (along y), sides (4: a pyramid)"),
    "capsule": ShapeDef(capsule, {"from": "vec3", "to": "vec3", "radius": "pos", "radius_to": "pos", "sides": "sides"}, ("from", "to", "radius"), {},
                        _bounds_capsule, "from: [x, y, z], to: [x, y, z], radius, radius_to (taper), sides (hard parts)"),
    "tube": ShapeDef(tube, {"points": "points3", "radius": "pos", "radius_to": "pos", "sides": "sides"}, ("points", "radius"), {}, _bounds_tube,
                     "points: [[x, y, z], ...] (2+), radius, radius_to (taper), sides (hard parts)"),
    "torus": ShapeDef(torus, {"radius": "pos", "thickness": "pos", "sides": "sides"}, ("radius", "thickness"), {},
                      lambda s: _sym(np.array([s["radius"] + s["thickness"], s["thickness"], s["radius"] + s["thickness"]])),
                      "radius (ring), thickness (tube radius), sides; ring in the xz plane"),
    "lathe": ShapeDef(lathe, {"profile": "profile", "smooth": "bool", "sides": "sides"}, ("profile",), {"smooth": True}, _bounds_lathe,
                      "profile: [[r, y], ...] outline spun around y (closed; points on the axis have r = 0), smooth: true|false, sides"),
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
    shell_side: str = "both"  # both: the wall is centred on the surface (shell: t); in: inside it (the outside stays put)
    open: tuple[int, float] | None = None  # (axis, sign): the shell's open side (local frame), showing its rim
    fit: tuple[tuple[Any, ...], float] | None = None  # (parts or a mesh's distance, gap): the shell wraps their surface
    cut_only: frozenset[int] | None = None  # cuts: only these adding parts (indices); None = everything before it

    def distance(self, p: Array, filled: bool = False) -> Array:
        """Signed distance; `filled`: a shell counts as solid (what it covers), its open side still open. A fitted
        shell is a wall `gap` away from its parts' surface, as thick as the shell, wherever its own shape (solid) is."""
        if self.fit is not None:
            own = self._distance(p, True)
            parts, gap = self.fit
            dt = np.min([g.distance(p) for g in parts], axis=0)
            wall = dt - gap - self.shell if filled else np.maximum(gap - dt, dt - gap - self.shell)
            return np.asarray(np.maximum(own, wall))
        return self._distance(p, filled)

    def _distance(self, p: Array, filled: bool) -> Array:
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
            d = fn(q, self.params)
            if self.open is not None:  # each copy is shelled and opened in its own frame
                d = d if filled else self._shelled(d)
                d = np.maximum(d, self.open[1] * q[:, self.open[0]])
            best = np.minimum(best, d)
        if self.shell and self.open is None and not filled:
            best = self._shelled(best)
        if self.noise is not None:
            best = best + self.noise.amount * noise(p, self.noise)
        return best

    def _shelled(self, d: Array) -> Array:
        if not self.shell:
            return d
        return np.maximum(d, -d - self.shell) if self.shell_side == "in" else np.abs(d) - self.shell

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
        pad = (self.shell if self.shell_side == "both" else 0.0) + (self.noise.amount if self.noise else 0.0)
        return points.min(axis=0) - pad, points.max(axis=0) + pad


def thickness(shape: str, p: dict[str, Any]) -> float | None:
    """A shape's thinnest dimension in metres (None: no simple answer)."""
    if shape == "sphere":
        return 2 * float(p["radius"])
    if shape in ("capsule", "tube"):
        return 2 * min(float(p["radius"]), float(p["radius_to"]))
    if shape == "torus":
        return 2 * float(p["thickness"])
    if shape in ("box", "wedge"):
        return min(float(v) for v in p["size"])
    if shape == "ellipsoid":
        return 2 * min(float(v) for v in p["radii"])
    if shape == "cylinder":
        return min(2 * float(p["radius"]), float(p["height"]))
    if shape in ("cone", "extrude"):
        return float(p["height"])
    return None


def part_thickness(g: Geometry) -> float | None:
    """A part's thinnest dimension: its shape's, or its shell's wall (twice the shell when centred on the surface)."""
    t = thickness(g.shape, g.params)
    if g.shell:
        wall = g.shell * (2 if g.shell_side == "both" and g.fit is None else 1)
        t = wall if t is None else min(t, wall)
    return t


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


BATCH = 262_144  # points per field evaluation


class Field:
    """Parts combined in order. `evaluate` returns the surface distance and every adding part's own distance
    (used to paint each part's colour). Far from a part's box, its distance is replaced by the distance to the
    box plus the padding: a stand-in that keeps every sign and never changes the result near the surface,
    but skips most of the work."""

    def __init__(self, parts: list[Geometry], margin: float, active: frozenset[int] | None = None) -> None:
        self.parts = parts
        self.margin = margin
        self.boxes = [g.bounds() for g in parts]
        self.active = active  # the adding parts that make up this surface (None = all); cuts always apply

    def only(self, active: list[int]) -> Field:
        """The same parts (same indices), but only these adding ones form the surface: a `separate` helmet is its
        own closed mesh instead of fusing with the head."""
        return Field(self.parts, self.margin, frozenset(active))

    def _counts(self, i: int) -> bool:
        g = self.parts[i]
        if g.op == "cut" and g.cut_only is not None and self.active is not None:
            return bool(g.cut_only & self.active)  # a cut aimed at other parts (a helmet's opening, not the face)
        return g.op != "add" or self.active is None or i in self.active

    def bounds(self) -> tuple[Array, Array]:
        adding = [b for i, (g, b) in enumerate(zip(self.parts, self.boxes, strict=True)) if g.op == "add" and self._counts(i)]
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
            if not self._counts(i):
                if with_parts:
                    per_part.append(self.part_distance(i, p))
                continue
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
        """The surface distance. Big point sets go in batches (memory) split into octants, and in each octant a part
        whose box is out of reach (beyond the surface so far by more than its blend) is skipped."""
        if len(p) < 4096:
            return self._distance(p)
        out = np.empty(len(p))
        mid = (p.min(axis=0) + p.max(axis=0)) / 2
        octant = ((p > mid) * np.array([1, 2, 4])).sum(axis=1)
        for k in range(8):
            idx = np.flatnonzero(octant == k)
            for i in range(0, len(idx), BATCH):
                part = idx[i : i + BATCH]
                out[part] = self._distance(p[part])
        return out

    def _distance(self, p: Array) -> Array:
        f = np.full(len(p), 1e9)
        if not len(p):
            return f
        lo_p, hi_p = p.min(axis=0), p.max(axis=0)
        for i, g in enumerate(self.parts):
            if not self._counts(i):
                continue
            if g.op != "intersect":
                lo, hi = self.boxes[i]
                gap = float(np.linalg.norm(np.maximum(np.maximum(lo - hi_p, lo_p - hi), 0.0))) - 1e-6  # <= its distance
                if gap > 0 and gap >= (float(f.max()) if g.op == "add" else float((-f).max())) + g.blend:
                    continue
            d = self.part_distance(i, p)
            if g.op == "cut":
                f = smooth_max(f, -d, g.blend)
            elif g.op == "intersect":
                f = smooth_max(f, d, g.blend)
            else:
                f = smooth_min(f, d, g.blend)
        return f

    def gradient(self, p: Array, eps: float) -> Array:
        """Unit surface normals at p (central differences)."""
        offsets = np.eye(3) * eps
        stacked = np.concatenate([p + o for o in offsets] + [p - o for o in offsets])
        d = self.distance(stacked).reshape(6, len(p))
        g = (d[:3] - d[3:]).T
        n = np.linalg.norm(g, axis=1, keepdims=True)
        return np.asarray(g / np.maximum(n, 1e-12))
