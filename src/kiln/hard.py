"""Hard surface: parts as exact polygons (designed facets, crisp creases) instead of a sampled, decimated field.

A hard part is tessellated straight from its shape: `sides` around round shapes, `bevel`/`chamfer` bands along
edges. The model's hard parts are then combined in order with exact CSG on polygons (BSP trees, as in Evan
Wallace's csg.js): adding parts union, `cut` parts subtract, `intersect` parts intersect (cuts and intersects
of any shape apply, tessellated). Every polygon remembers its part, so paint is exact, and its plane, so
normals split on designed edges. The result is welded (T-junctions from the CSG are split), so it's watertight.

Polygons are tuples of points (counter-clockwise seen from outside). Everything is plain float maths in a fixed
order: the same model gives the same mesh, byte for byte.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from kiln.sdf import IDENTITY, SHAPES, Array, Geometry

EPS = 1e-7  # metres: points this close to a plane are on it
WELD = 1e-6  # metres: points this close are the same vertex
DEFAULT_SIDES = 12
Point = tuple[float, float, float]

# shapes the hard path can tessellate (others, and parts with twist or noise, stay soft)
HARD_SHAPES = ("box", "wedge", "cylinder", "cone", "sphere", "ellipsoid", "capsule", "tube", "torus", "lathe", "extrude")
SHELL_SHAPES = ("box", "wedge", "cylinder", "cone", "sphere", "ellipsoid", "lathe")  # hard shells need a simple inward offset


# --- polygons and planes ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Plane:
    normal: Point
    w: float

    def flipped(self) -> Plane:
        return Plane((-self.normal[0], -self.normal[1], -self.normal[2]), -self.w)

    def side(self, p: Point) -> float:
        n = self.normal
        return n[0] * p[0] + n[1] * p[1] + n[2] * p[2] - self.w


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Point, b: Point) -> Point:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a: Point, b: Point) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def plane_of(points: Sequence[Point]) -> Plane | None:
    """The polygon's plane (Newell's method: robust when some points are in a line); None if degenerate."""
    nx = ny = nz = 0.0
    k = len(points)
    for i in range(k):
        a, b = points[i], points[(i + 1) % k]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length < 1e-14:
        return None
    n = (nx / length, ny / length, nz / length)
    c = (sum(p[0] for p in points) / k, sum(p[1] for p in points) / k, sum(p[2] for p in points) / k)
    return Plane(n, _dot(n, c))


@dataclass(frozen=True)
class Polygon:
    points: tuple[Point, ...]
    plane: Plane
    tag: int  # the part it came from

    def flipped(self) -> Polygon:
        return Polygon(tuple(reversed(self.points)), self.plane.flipped(), self.tag)


def polygon(points: Sequence[Point], tag: int) -> Polygon | None:
    pts: list[Point] = []
    for p in points:
        if not pts or max(abs(p[0] - pts[-1][0]), abs(p[1] - pts[-1][1]), abs(p[2] - pts[-1][2])) > EPS:
            pts.append(p)
    while len(pts) > 1 and max(abs(pts[0][i] - pts[-1][i]) for i in range(3)) <= EPS:
        pts.pop()
    if len(pts) < 3:
        return None
    plane = plane_of(pts)
    return Polygon(tuple(pts), plane, tag) if plane is not None else None


Solid = list[Polygon]


def _split(plane: Plane, poly: Polygon, co_front: list[Polygon], co_back: list[Polygon], front: list[Polygon], back: list[Polygon]) -> None:
    sides = [plane.side(p) for p in poly.points]
    types = [0 if abs(s) < EPS else (1 if s > 0 else 2) for s in sides]
    kind = 0
    for t in types:
        kind |= t
    if kind == 0:
        (co_front if _dot(plane.normal, poly.plane.normal) > 0 else co_back).append(poly)
    elif kind == 1:
        front.append(poly)
    elif kind == 2:
        back.append(poly)
    else:
        f: list[Point] = []
        b: list[Point] = []
        k = len(poly.points)
        for i in range(k):
            j = (i + 1) % k
            ti, tj = types[i], types[j]
            vi, vj = poly.points[i], poly.points[j]
            if ti != 2:
                f.append(vi)
            if ti != 1:
                b.append(vi)
            if (ti | tj) == 3:
                v = _lerp(vi, vj, sides[i] / (sides[i] - sides[j]))
                f.append(v)
                b.append(v)
        if len(f) >= 3:
            front.append(Polygon(tuple(f), poly.plane, poly.tag))
        if len(b) >= 3:
            back.append(Polygon(tuple(b), poly.plane, poly.tag))


class _Node:
    __slots__ = ("plane", "front", "back", "polygons")

    def __init__(self) -> None:
        self.plane: Plane | None = None
        self.front: _Node | None = None
        self.back: _Node | None = None
        self.polygons: list[Polygon] = []

    def nodes(self) -> list[_Node]:
        out, stack = [], [self]
        while stack:
            n = stack.pop()
            out.append(n)
            stack += [c for c in (n.front, n.back) if c is not None]
        return out

    def build(self, polygons: list[Polygon]) -> None:
        stack = [(self, polygons)]
        while stack:
            node, polys = stack.pop()
            if not polys:
                continue
            if node.plane is None:
                node.plane = polys[0].plane
            front: list[Polygon] = []
            back: list[Polygon] = []
            for p in polys:
                _split(node.plane, p, node.polygons, node.polygons, front, back)
            if front:
                node.front = node.front or _Node()
                stack.append((node.front, front))
            if back:
                node.back = node.back or _Node()
                stack.append((node.back, back))

    def invert(self) -> None:
        for n in self.nodes():
            n.polygons = [p.flipped() for p in n.polygons]
            assert n.plane is not None or not n.polygons
            if n.plane is not None:
                n.plane = n.plane.flipped()
            n.front, n.back = n.back, n.front

    def clip_polygons(self, polygons: list[Polygon]) -> list[Polygon]:
        """The parts of `polygons` outside this BSP's solid."""
        out: list[Polygon] = []
        stack = [(self, polygons)]
        while stack:
            node, polys = stack.pop()
            if node.plane is None:
                out += polys
                continue
            front: list[Polygon] = []
            back: list[Polygon] = []
            for p in polys:
                _split(node.plane, p, front, back, front, back)
            if node.front is not None:
                stack.append((node.front, front))
            else:
                out += front
            if node.back is not None:
                stack.append((node.back, back))
        return out

    def clip_to(self, other: _Node) -> None:
        for n in self.nodes():
            n.polygons = other.clip_polygons(n.polygons)

    def all_polygons(self) -> list[Polygon]:
        return [p for n in self.nodes() for p in n.polygons]


def _tree(polys: list[Polygon]) -> _Node:
    n = _Node()
    n.build(list(polys))
    return n


def _box(polys: Sequence[Polygon]) -> tuple[Array, Array]:
    pts = np.array([p for poly in polys for p in poly.points])
    return pts.min(axis=0), pts.max(axis=0)


def _overlaps(box: tuple[Array, Array], poly: Polygon) -> bool:
    lo, hi = box
    xs = [p[0] for p in poly.points]
    ys = [p[1] for p in poly.points]
    zs = [p[2] for p in poly.points]
    return not (min(xs) > hi[0] + EPS or max(xs) < lo[0] - EPS or min(ys) > hi[1] + EPS or max(ys) < lo[1] - EPS
                or min(zs) > hi[2] + EPS or max(zs) < lo[2] - EPS)  # fmt: skip


def _flip(polys: list[Polygon]) -> list[Polygon]:
    return [p.flipped() for p in polys]


def _inverted_tree(polys: Solid) -> _Node:
    t = _tree(polys)
    t.invert()
    return t


# The operations follow csg.js (clipTo, invert, build) with each side's tree built from its whole solid: a tree of
# only some of a solid's polygons classifies points by planes that no longer close it, which drops or keeps the
# wrong pieces (cracks). Only the polygons near the other solid are clipped: the rest can't touch it.


def union(a: Solid, b: Solid) -> Solid:
    if not a or not b:
        return a + b
    box_a, box_b = _box(a), _box(b)
    near_a = [p for p in a if _overlaps(box_b, p)]
    near_b = [p for p in b if _overlaps(box_a, p)]
    if not near_a or not near_b:
        return a + b
    far = [p for p in a if not _overlaps(box_b, p)] + [p for p in b if not _overlaps(box_a, p)]
    ta, tb = _tree(a), _tree(b)
    kept_a = tb.clip_polygons(near_a)  # a.clipTo(b)
    kept_b = ta.clip_polygons(near_b)  # b.clipTo(a)
    kept_b = _flip(ta.clip_polygons(_flip(kept_b)))  # b.invert(); b.clipTo(a); b.invert(): coplanar faces once
    return far + kept_a + kept_b


def subtract(a: Solid, b: Solid) -> Solid:
    if not a or not b:
        return a
    box_b, box_a = _box(b), _box(a)
    near_a = [p for p in a if _overlaps(box_b, p)]
    near_b = [p for p in b if _overlaps(box_a, p)]
    if not near_a or not near_b:
        return a
    far = [p for p in a if not _overlaps(box_b, p)]
    ta_inv, tb = _inverted_tree(a), _tree(b)
    kept_a = tb.clip_polygons(_flip(near_a))  # a.invert(); a.clipTo(b)
    kept_b = ta_inv.clip_polygons(near_b)  # b.clipTo(a)
    kept_b = _flip(ta_inv.clip_polygons(_flip(kept_b)))  # b.invert(); b.clipTo(a); b.invert()
    return far + _flip(kept_a + kept_b)  # a.build(b.allPolygons()); a.invert()


def intersect(a: Solid, b: Solid) -> Solid:
    if not a or not b:
        return []
    box_b, box_a = _box(b), _box(a)
    near_a = [p for p in a if _overlaps(box_b, p)]
    near_b = [p for p in b if _overlaps(box_a, p)]
    if not near_a or not near_b:
        return []
    ta_inv, tb_inv = _inverted_tree(a), _inverted_tree(b)
    kept_b = ta_inv.clip_polygons(near_b)  # a.invert(); b.clipTo(a)
    kept_b = _flip(kept_b)  # b.invert()
    kept_a = tb_inv.clip_polygons(_flip(near_a))  # a.clipTo(b)
    kept_b = ta_inv.clip_polygons(kept_b)  # b.clipTo(a)
    return _flip(kept_a + kept_b)  # a.build(b.allPolygons()); a.invert()


# --- convex shapes from planes (with bevels) -----------------------------------------------------------------


def _clip_convex(polys: list[tuple[Array, int]], n: Array, d: float, index: int) -> list[tuple[Array, int]]:
    """Keep the part of a convex polyhedron (faces as point arrays + plane index) where n.x <= d, capping the cut."""
    out: list[tuple[Array, int]] = []
    cap: list[Array] = []
    for pts, idx in polys:
        s = pts @ n - d
        if (s <= EPS).all():
            out.append((pts, idx))
            cap += [p for p, v in zip(pts, s, strict=True) if abs(v) <= EPS]
            continue
        if (s >= -EPS).all():
            continue
        kept: list[Array] = []
        k = len(pts)
        for i in range(k):
            j = (i + 1) % k
            if s[i] <= EPS:
                kept.append(pts[i])
            if (s[i] < -EPS and s[j] > EPS) or (s[i] > EPS and s[j] < -EPS):
                p = pts[i] + (pts[j] - pts[i]) * (s[i] / (s[i] - s[j]))
                kept.append(p)
                cap.append(p)
            elif abs(s[i]) <= EPS:
                cap.append(pts[i])
        if len(kept) >= 3:
            out.append((np.array(kept), idx))
    if len(cap) >= 3:
        c = np.unique(np.round(np.array(cap), 9), axis=0)
        if len(c) >= 3:
            centre = c.mean(axis=0)
            u = c[0] - centre
            u -= (u @ n) * n
            u /= max(float(np.linalg.norm(u)), 1e-15)
            v = np.cross(n, u)
            angle = np.arctan2((c - centre) @ v, (c - centre) @ u)
            out.append((c[np.argsort(angle)], index))  # counter-clockwise about n (outward)
    return out


def convex(normals: Array, offsets: Array) -> list[tuple[Array, int]]:
    """The convex polyhedron {x : normals @ x <= offsets} as faces (points, plane index)."""
    big = float(np.abs(offsets).max()) * 4 + 1.0
    cube = []
    for axis in range(3):
        for sign in (-1.0, 1.0):
            n = np.zeros(3)
            n[axis] = sign
            cube.append(n)
    faces: list[tuple[Array, int]] = []
    # start from a big cube: its faces as squares
    for k, n in enumerate(cube):
        a = np.roll(n, 1)
        b = np.cross(n, a)
        sq = np.array([n * big + (a * sa + b * sb) * big for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        faces.append((sq, -1 - k))
    for i, (n, d) in enumerate(zip(normals, offsets, strict=True)):
        faces = _clip_convex(faces, n, float(d), i)
    if any(idx < 0 for _, idx in faces):
        raise ValueError("a hard shape is unbounded (internal error)")
    return faces


def _unit(v: Array) -> Array:
    return np.asarray(v / np.linalg.norm(v))


def bevelled(normals: Array, offsets: Array, radius: float, segments: int) -> list[tuple[Array, int]]:
    """The convex shape with every edge and corner rounded by `radius` in `segments` flat bands (1 = a chamfer):
    the shape shrunk by `radius`, grown back by a ball cut to those bands. Its flat faces stay where they were."""
    if radius <= 0:
        return convex(normals, offsets)
    core = convex(normals, offsets - radius)
    points = np.concatenate([p for p, _ in core])
    # which faces meet at each edge and corner of the core
    _, index = _weld(points, 1e-7)
    vertex_faces: dict[int, set[int]] = {}
    edge_faces: dict[tuple[int, int], set[int]] = {}
    pos = 0
    for pts, idx in core:
        ids = [int(i) for i in index[pos : pos + len(pts)]]
        pos += len(pts)
        for k, v in enumerate(ids):
            vertex_faces.setdefault(v, set()).add(idx)
            w = ids[(k + 1) % len(ids)]
            if v != w:
                edge_faces.setdefault((min(v, w), max(v, w)), set()).add(idx)
    edges = {(min(f), max(f)) for f in edge_faces.values() if len(f) == 2}
    extra: list[Array] = []
    s = segments
    for a, b in sorted(edges):
        for i in range(1, s + 1):
            extra.append(_unit(normals[a] * i + normals[b] * (s + 1 - i)))
    for key in sorted(vertex_faces):
        around = sorted(vertex_faces[key])
        if len(around) < 3:
            continue
        ns = normals[around]
        centre = _unit(ns.sum(axis=0))
        extra.append(centre)
        if s >= 2:
            # bands between the corner's middle and each pair of its faces
            for x in range(len(around)):
                for y in range(x + 1, len(around)):
                    if (min(around[x], around[y]), max(around[x], around[y])) in edges:
                        for i in range(1, s):
                            extra.append(_unit(centre * i + _unit(ns[x] + ns[y]) * (s - i)))
    all_n = np.concatenate([normals, np.array(extra)]) if extra else normals
    # merge (near) duplicate directions
    keep: list[int] = []
    for i in range(len(all_n)):
        if all(float(all_n[i] @ all_n[j]) < 1 - 1e-9 for j in keep):
            keep.append(i)
    all_n = all_n[keep]
    h = (points @ all_n.T).max(axis=0) + radius
    return convex(all_n, h)


def _around(sides: int) -> Array:
    """Outward side normals in the xz plane, the first facing +z (front)."""
    a = 2 * np.pi * np.arange(sides) / sides
    return np.stack([np.sin(a), np.zeros(sides), np.cos(a)], axis=1)


def _planes_box(size: Sequence[float]) -> tuple[Array, Array]:
    n = np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]], float)
    h = np.array([size[0], size[0], size[1], size[1], size[2], size[2]], float) / 2
    return n, h


def _planes_wedge(size: Sequence[float]) -> tuple[Array, Array]:
    w, h, d = (float(v) for v in size)
    n, off = _planes_box(size)
    keep = [0, 1, 3]  # x sides and the floor; the top is the ridge
    slope = np.array([[0.0, d / 2, h], [0.0, d / 2, -h]])
    slope /= np.linalg.norm(slope, axis=1, keepdims=True)
    # both slopes pass through the ridge (y = h/2, z = 0)
    return np.concatenate([n[keep], slope]), np.concatenate([off[keep], slope[:, 1] * h / 2])


def _planes_prism(radius_bottom: float, radius_top: float, height: float, sides: int) -> tuple[Array, Array]:
    """A regular prism / frustum / pyramid with its corners on the circles (radius) at y = -height/2 and +height/2."""
    c = math.cos(math.pi / sides)
    a, b, h = radius_bottom * c, radius_top * c, height / 2  # apothems
    radial = _around(sides)
    # side plane through (a, -h) and (b, h) in (apothem, y): normal (2h, a - b)
    ny = a - b
    nr = 2 * h
    length = math.hypot(nr, ny)
    sides_n = radial * (nr / length)
    sides_n[:, 1] = ny / length
    side_off = np.full(sides, (nr * a + ny * -h) / length)
    n = [np.array([[0.0, -1.0, 0.0]])]
    off = [np.array([h])]
    if radius_top > 0:
        n.append(np.array([[0.0, 1.0, 0.0]]))
        off.append(np.array([h]))
    return np.concatenate([sides_n, *n]), np.concatenate([side_off, *off])


# --- other shapes, tessellated directly -----------------------------------------------------------------------


def _lathe_polys(profile: Sequence[Sequence[float]], sides: int) -> list[list[Point]]:
    """A closed (r, y) outline spun around y in `sides` steps (corners on the true radius)."""
    prof = [(float(r), float(y)) for r, y in profile]
    # orient the outline so its outside is to the right of travel ((r, y): counter-clockwise)
    area = sum(prof[i][0] * prof[(i + 1) % len(prof)][1] - prof[(i + 1) % len(prof)][0] * prof[i][1] for i in range(len(prof)))
    if area < 0:
        prof.reverse()
    angles = [2 * math.pi * (k + 0.5) / sides for k in range(sides)]
    ring = [(math.sin(a), math.cos(a)) for a in angles]
    polys: list[list[Point]] = []
    k = len(prof)
    for i in range(k):
        (r0, y0), (r1, y1) = prof[i], prof[(i + 1) % k]
        if r0 == 0 and r1 == 0:
            continue
        for j in range(sides):
            (s0, c0), (s1, c1) = ring[j], ring[(j + 1) % sides]
            # up the outside (counter-clockwise in (r, y)), and z -> x (counter-clockwise from above): faces outwards
            polys.append([(r0 * s0, y0, r0 * c0), (r0 * s1, y0, r0 * c1), (r1 * s1, y1, r1 * c1), (r1 * s0, y1, r1 * c0)])
    return polys


def _sphere_profile(radius: float, sides: int) -> list[list[float]]:
    rings = max(2, sides // 2)
    out = [[0.0, -radius]]
    for j in range(1, rings):
        t = -math.pi / 2 + math.pi * j / rings
        out.append([radius * math.cos(t), radius * math.sin(t)])
    out.append([0.0, radius])
    return out


def _capsule_profile(length: float, ra: float, rb: float, sides: int) -> list[list[float]]:
    """(r, y) outline of a capsule from y = 0 (radius ra) to y = length (radius rb), arcs joined on their tangents."""
    phi = math.asin(max(-1.0, min(1.0, (ra - rb) / length))) if length > 0 else 0.0
    per = max(2, sides // 2) / math.pi  # arc samples per radian
    out: list[list[float]] = []
    n0 = max(1, round((phi + math.pi / 2) * per))
    for j in range(n0 + 1):
        t = -math.pi / 2 + (phi + math.pi / 2) * j / n0
        out.append([max(ra * math.cos(t), 0.0), ra * math.sin(t)])
    n1 = max(1, round((math.pi / 2 - phi) * per))
    for j in range(n1 + 1):
        t = phi + (math.pi / 2 - phi) * j / n1
        out.append([max(rb * math.cos(t), 0.0), length + rb * math.sin(t)])
    out[0][0] = 0.0
    out[-1][0] = 0.0
    return out  # up the outside; it closes back down the axis


INSET_SHARE = 0.9  # of the room a vertex has before it meets the outline moving towards it


def inset_limits(pts: list[tuple[float, float]]) -> list[float]:
    """Per vertex of a counter-clockwise outline, the most an inset may move it before the mitred outline folds over
    itself: the vertex travels along its bisector (by d / cos(half angle)) while the edge it heads for comes towards
    it by d along that edge's normal, so they meet at d = distance / (vertex travel + edge travel, both per unit d,
    measured along the bisector). Thin sections (font serifs, hairlines) get small limits; elsewhere the limit is far
    above any bevel."""
    k = len(pts)
    out = []
    for i in range(k):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % k]
        e0 = (p1[0] - p0[0], p1[1] - p0[1])
        e1 = (p2[0] - p1[0], p2[1] - p1[1])
        l0, l1 = math.hypot(*e0), math.hypot(*e1)
        if l0 == 0 or l1 == 0:
            out.append(math.inf)
            continue
        n0 = (-e0[1] / l0, e0[0] / l0)
        n1 = (-e1[1] / l1, e1[0] / l1)
        m = (n0[0] + n1[0], n0[1] + n1[1])
        dotn = 1 + n0[0] * n1[0] + n0[1] * n1[1]
        travel = math.hypot(*m) / max(dotn, 0.2)  # how far the vertex moves per unit of inset (as _offset_outline)
        length = math.hypot(*m)
        if length < 1e-12:
            out.append(math.inf)
            continue
        dx, dy = m[0] / length, m[1] / length
        room = math.inf
        for j in range(k):
            if j in (i, (i - 1) % k):  # the two edges at this vertex
                continue
            (ax, ay), (bx, by) = pts[j], pts[(j + 1) % k]
            ex, ey = bx - ax, by - ay
            denom = dx * ey - dy * ex
            if abs(denom) < 1e-15:
                continue
            t = ((ax - p1[0]) * ey - (ay - p1[1]) * ex) / denom  # along the bisector
            u = ((ax - p1[0]) * dy - (ay - p1[1]) * dx) / denom  # along the edge
            if t > 1e-12 and -1e-9 <= u <= 1 + 1e-9:
                facing = abs(dx * -ey + dy * ex) / math.hypot(ex, ey)  # bisector . the edge's normal
                room = min(room, t / (travel + 1.0 / max(facing, 0.2)))
        out.append(INSET_SHARE * room)
    return out


def _segment_gaps(a: Array, b: Array) -> Array:
    """Distances between every pair of segments a[i]-b[i] and a[j]-b[j] (0 where they cross)."""

    def orient(p: Array, q: Array, r: Array) -> Array:
        return np.asarray((q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1]) - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0]), float)

    def to_segment(p: Array, s0: Array, s1: Array) -> Array:
        e = s1 - s0
        t = np.clip(((p - s0) * e).sum(axis=-1) / np.maximum((e * e).sum(axis=-1), 1e-300), 0.0, 1.0)
        return np.asarray(np.linalg.norm(p - (s0 + t[..., None] * e), axis=-1))

    p, q, r, s = a[:, None], b[:, None], a[None, :], b[None, :]
    d1, d2, d3, d4 = orient(r, s, p), orient(r, s, q), orient(p, q, r), orient(p, q, s)
    cross = ((d1 > 0) != (d2 > 0)) & ((d3 > 0) != (d4 > 0))
    gap = np.minimum(np.minimum(to_segment(p, r, s), to_segment(q, r, s)), np.minimum(to_segment(r, p, q), to_segment(s, p, q)))
    return np.where(cross, 0.0, gap)


def _folds(pts: list[tuple[float, float]], moved: list[tuple[float, float]]) -> list[set[int]]:
    """Where an inset outline folds over itself, as groups of vertices: the ends of an edge that turned around, or
    of two non-neighbouring edges that cross or come within WELD of each other (and weren't that close before)."""
    k = len(pts)
    a0, a = np.asarray(pts, float), np.asarray(moved, float)
    b0, b = np.roll(a0, -1, axis=0), np.roll(a, -1, axis=0)
    turned = (((b - a) * (b0 - a0)).sum(axis=1) <= 0) & (((b0 - a0) ** 2).sum(axis=1) > 0)
    groups = [{int(u), (int(u) + 1) % k} for u in np.flatnonzero(turned)]
    near = (_segment_gaps(a, b) < WELD) & (_segment_gaps(a0, b0) >= WELD)
    for u, w in zip(*(x.tolist() for x in np.nonzero(np.triu(near, 2))), strict=True):
        if (w + 1) % k != u:  # not the closing pair of neighbours
            groups.append({u, (u + 1) % k, w, (w + 1) % k})
    return groups


def _unfolded(pts: list[tuple[float, float]], each: list[float]) -> list[float]:
    """Per-vertex insets lowered where the inset outline would still fold. The limits of `inset_limits` hold for one
    vertex moving against still edges; neighbours clamped to different depths can still sweep their edges across
    each other (thin joins, where a glyph's overlapping contours were united), and two sides of a bar can meet. The
    vertices of each fold take the smallest inset among them (halved once they agree), until the outline is clean;
    vertices away from folds keep theirs, and outlines that don't fold are unchanged."""
    each = list(each)
    for _ in range(64):
        groups = _folds(pts, _offset_outline(pts, each))
        if not groups:
            return each
        for group in groups:
            low = min(each[v] for v in group)
            agree = all(math.isclose(each[v], low, rel_tol=1e-12, abs_tol=1e-15) for v in group)
            for v in group:
                each[v] = low / 2 if agree else low
    for group in _folds(pts, _offset_outline(pts, each)):
        for v in group:
            each[v] = 0.0
    return each


def _offset_outline(pts: list[tuple[float, float]], d: float | Sequence[float]) -> list[tuple[float, float]]:
    """A counter-clockwise outline moved inwards by d (mitred corners); d may be one value per vertex."""
    out = []
    k = len(pts)
    each = [float(d)] * k if isinstance(d, int | float) else [float(v) for v in d]
    for i in range(k):
        d = each[i]
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % k]
        e0 = (p1[0] - p0[0], p1[1] - p0[1])
        e1 = (p2[0] - p1[0], p2[1] - p1[1])
        l0, l1 = math.hypot(*e0), math.hypot(*e1)
        n0 = (-e0[1] / l0, e0[0] / l0)  # left of travel = inside for counter-clockwise
        n1 = (-e1[1] / l1, e1[0] / l1)
        m = (n0[0] + n1[0], n0[1] + n1[1])
        dotn = 1 + n0[0] * n1[0] + n0[1] * n1[1]
        scale = d / max(dotn, 0.2)
        out.append((p1[0] + m[0] * scale, p1[1] + m[1] * scale))
    return out


def _triangulate_2d(pts: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """Ear clipping of a simple counter-clockwise polygon."""
    idx = list(range(len(pts)))
    tris: list[tuple[int, int, int]] = []

    def cross(o: int, a: int, b: int) -> float:
        return (pts[a][0] - pts[o][0]) * (pts[b][1] - pts[o][1]) - (pts[a][1] - pts[o][1]) * (pts[b][0] - pts[o][0])

    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= 1e-15:
                continue
            if any(cross(a, b, p) >= 0 and cross(b, c, p) >= 0 and cross(c, a, p) >= 0 for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append((idx[0], idx[1], idx[2]))
    return tris


def _extrude_polys(points: Sequence[Sequence[float]], height: float, bevel: float, segments: int, offset: float = 0.0) -> list[list[Point]]:
    """`offset` grows the outline (mitred corners; < 0 shrinks it)."""
    # (u, v) = (z, x): counter-clockwise in (u, v) is counter-clockwise seen from above (+y)
    uv = [(float(p[1]), float(p[0])) for p in points]
    area = sum(uv[i][0] * uv[(i + 1) % len(uv)][1] - uv[(i + 1) % len(uv)][0] * uv[i][1] for i in range(len(uv)))
    if area < 0:
        uv.reverse()
    if offset:  # a shrink is clamped like a bevel's inset: thin sections stay (thinner) instead of folding over
        uv = _offset_outline(uv, _unfolded(uv, [min(-offset, lim) for lim in inset_limits(uv)]) if offset < 0 else -offset)
    h = height / 2
    # rings from the bottom cap up to the top cap: (inset, y)
    rings: list[tuple[float, float]] = []
    if bevel > 0:
        s = max(1, segments)
        for j in range(s + 1):
            a = (math.pi / 2) * j / s
            rings.append((bevel * (1 - math.sin(a)), -h + bevel * (1 - math.cos(a))))
        rings += [(inset, -y) for inset, y in reversed(rings)]
    else:
        rings = [(0.0, -h), (0.0, h)]
    # Thin sections (font serifs, hairlines) can't take the full bevel: each vertex insets at most its own limit, so
    # the bevel flattens there instead of the outline folding over itself (cracks).
    limits = inset_limits(uv) if bevel > 0 else []
    for _ in range(64):  # every ring clean (smaller rings use the same per-vertex limits, so the bands don't cross)
        lowered = False
        for inset in sorted({inset for inset, _ in rings if inset}):
            wanted = [min(inset, lim) for lim in limits]
            for v, got in enumerate(_unfolded(uv, wanted)):
                if got < wanted[v]:
                    limits[v], lowered = got, True
        if not lowered:
            break
    insets = [[min(inset, lim) for lim in limits] if inset else [0.0] * len(uv) for inset, _ in rings]
    outlines = [[(x, y, z) for z, x in (_offset_outline(uv, each) if any(each) else uv)] for each, (_, y) in zip(insets, rings, strict=True)]
    polys: list[list[Point]] = []
    k = len(uv)
    for (lo, lo_in), (hi, hi_in) in zip(zip(outlines[:-1], insets[:-1], strict=True), zip(outlines[1:], insets[1:], strict=True), strict=True):
        for i in range(k):
            j = (i + 1) % k
            if math.isclose(lo_in[i], lo_in[j], abs_tol=1e-12) and math.isclose(hi_in[i], hi_in[j], abs_tol=1e-12):
                polys.append([lo[i], lo[j], hi[j], hi[i]])  # parallel edges: a flat quad
            else:  # a clamped vertex bends the band: two triangles keep every face flat
                polys.append([lo[i], lo[j], hi[j]])
                polys.append([lo[i], hi[j], hi[i]])
    convex_outline = all(
        (uv[(i + 1) % k][0] - uv[i][0]) * (uv[(i + 2) % k][1] - uv[(i + 1) % k][1])
        - (uv[(i + 1) % k][1] - uv[i][1]) * (uv[(i + 2) % k][0] - uv[(i + 1) % k][0]) >= -1e-12
        for i in range(k)
    )
    top, bottom = outlines[-1], outlines[0]
    if convex_outline:
        polys.append(list(top))
        polys.append(list(reversed(bottom)))
    else:
        flat = [(p[2], p[0]) for p in top]
        for a, b, c in _triangulate_2d(flat):
            polys.append([top[a], top[b], top[c]])
            polys.append([bottom[c], bottom[b], bottom[a]])
    return polys


def _torus_polys(radius: float, thickness: float, sides: int) -> list[list[Point]]:
    around = sides
    tube = max(4, sides // 2)
    polys: list[list[Point]] = []
    for i in range(around):
        a0, a1 = 2 * math.pi * (i + 0.5) / around, 2 * math.pi * (i + 1.5) / around
        for j in range(tube):
            t0, t1 = 2 * math.pi * j / tube, 2 * math.pi * (j + 1) / tube

            def pt(a: float, t: float) -> Point:
                r = radius + thickness * math.cos(t)
                return (r * math.sin(a), thickness * math.sin(t), r * math.cos(a))

            polys.append([pt(a1, t0), pt(a0, t0), pt(a0, t1), pt(a1, t1)])
    return polys


# --- a part as a solid ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class HardSpec:
    sides: int = DEFAULT_SIDES
    bevel: float = 0.0
    segments: int = 2  # bevel bands; a chamfer is 1


def _oriented(polys: list[list[Point]]) -> list[list[Point]]:
    """Outward-facing: if the polygons enclose a negative volume, every one is reversed."""
    volume = 0.0
    for poly in polys:
        a = poly[0]
        for b, c in zip(poly[1:-1], poly[2:], strict=True):
            volume += _dot(a, _cross(b, c))
    return [list(reversed(p)) for p in polys] if volume < 0 else polys


def local_polys(shape: str, p: dict[str, object], spec: HardSpec) -> list[list[Point]]:
    """The shape in its own frame as polygons (counter-clockwise from outside)."""
    sides = int(p.get("sides") or spec.sides)  # type: ignore[call-overload]
    bevel, seg = spec.bevel, spec.segments
    planes: tuple[Array, Array] | None = None
    if shape == "box":
        planes = _planes_box(p["size"])  # type: ignore[arg-type]
    elif shape == "wedge":
        planes = _planes_wedge(p["size"])  # type: ignore[arg-type]
    elif shape == "cylinder":
        planes = _planes_prism(float(p["radius"]), float(p["radius"]), float(p["height"]), sides)  # type: ignore[arg-type]
    elif shape == "cone":
        planes = _planes_prism(float(p["radius"]), float(p["radius_top"]), float(p["height"]), sides)  # type: ignore[arg-type]
    if planes is not None:
        faces = bevelled(planes[0], planes[1], bevel, seg) if bevel > 0 else convex(*planes)
        return [[(float(x), float(y), float(z)) for x, y, z in pts] for pts, _ in faces]
    if shape == "sphere":
        return _oriented(_lathe_polys(_sphere_profile(float(p["radius"]), sides), sides))  # type: ignore[arg-type]
    if shape == "ellipsoid":
        r = [float(v) for v in p["radii"]]  # type: ignore[attr-defined]
        unit = _lathe_polys(_sphere_profile(1.0, sides), sides)
        return _oriented([[(x * r[0], y * r[1], z * r[2]) for x, y, z in poly] for poly in unit])
    if shape == "lathe":
        prof = p.get("hard_profile") or p["profile"]
        return _oriented(_lathe_polys(prof, sides))  # type: ignore[arg-type]
    if shape == "torus":
        return _oriented(_torus_polys(float(p["radius"]), float(p["thickness"]), sides))  # type: ignore[arg-type]
    if shape == "extrude":
        return _oriented(_extrude_polys(p["points"], float(p["height"]), bevel, seg, float(p.get("offset", 0.0))))  # type: ignore[arg-type]
    raise ValueError(f"{shape} has no hard tessellation")


def _capsule_solid(a: Array, b: Array, ra: float, rb: float, sides: int, tag: int) -> Solid:
    axis = b - a
    length = float(np.linalg.norm(axis))
    polys = _oriented(_lathe_polys(_capsule_profile(length, ra, rb, sides), sides))
    # local y -> the segment's direction
    y = axis / length if length > 0 else np.array([0.0, 1.0, 0.0])
    helper = np.array([1.0, 0.0, 0.0]) if abs(y[0]) < 0.9 else np.array([0.0, 0.0, 1.0])
    x = np.cross(y, helper)
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    m = np.stack([x, y, z], axis=1)
    return _place(polys, m, a, tag)


def _place(polys: list[list[Point]], m: Array, t: Array, tag: int) -> Solid:
    if not polys:
        return []
    flip = float(np.linalg.det(m)) < 0
    lengths = [len(p) for p in polys]
    moved = (np.array([q for p in polys for q in p], float) @ m.T + t).tolist()
    out: Solid = []
    pos = 0
    for k in lengths:
        pts_t = [(q[0], q[1], q[2]) for q in moved[pos : pos + k]]
        pos += k
        if flip:
            pts_t.reverse()
        made = polygon(pts_t, tag)
        if made is not None:
            out.append(made)
    return out


def _union_all(solids: list[Solid]) -> Solid:
    out: Solid = []
    for s in solids:
        out = union(out, s)
    return out


def _halfspace(axis: int, lo: Array, hi: Array, tag: int) -> Solid:
    """A box covering [lo, hi] but only the positive side of `axis` (for mirror folds)."""
    lo2 = lo.copy()
    lo2[axis] = 0.0
    size = np.maximum(hi - lo2, 1e-6)
    centre = (hi + lo2) / 2
    faces = convex(*_planes_box(size))
    return _place([[(float(x), float(y), float(z)) for x, y, z in pts] for pts, _ in faces], np.eye(3), centre, tag)


def _inside(point: Array, loop: Array) -> bool:
    """Even-odd: is the 2D point inside the closed loop?"""
    x, y = float(point[0]), float(point[1])
    inside = False
    j = len(loop) - 1
    for i in range(len(loop)):
        xi, yi, xj, yj = loop[i][0], loop[i][1], loop[j][0], loop[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def solid(g: Geometry, spec: HardSpec, tag: int) -> Solid:
    """A part's solid in model space: shape, placement, copies and mirror folds."""
    if g.shape in ("capsule", "tube"):
        if g.shape == "capsule":
            pts = [np.asarray(g.params["from"], float), np.asarray(g.params["to"], float)]
            radii = [float(g.params["radius"]), float(g.params["radius_to"])]
        else:
            pts = [np.asarray(q, float) for q in g.params["points"]]
            lengths = np.linalg.norm(np.diff(np.array(pts), axis=0), axis=1)
            along = np.concatenate([[0.0], np.cumsum(lengths)]) / max(float(lengths.sum()), 1e-12)
            radii = [float(g.params["radius"]) + (float(g.params["radius_to"]) - float(g.params["radius"])) * float(t) for t in along]
        sides = int(g.params.get("sides") or spec.sides)
        local_solid = _union_all([_capsule_solid(pts[i], pts[i + 1], radii[i], radii[i + 1], sides, tag) for i in range(len(pts) - 1)])
        local_pts = [list(poly.points) for poly in local_solid]
    else:
        local_pts = local_polys(g.shape, g.params, spec)
    holes = g.params.get("holes") if g.shape == "extrude" else None
    if holes:  # more outlines, by nesting (even-odd): inside one = a hole cut through (its edges stay sharp), outside = an island
        offset, height = float(g.params.get("offset", 0.0)), float(g.params["height"])
        loops = [g.params["points"], *holes]
        arrays = [np.asarray(lp, dtype=float) for lp in loops]
        depth = [sum(int(_inside(a[0], b)) for k, b in enumerate(arrays) if k != j) for j, a in enumerate(arrays)]
        body: Solid = [q for q in (polygon(pts, tag) for pts in local_pts) if q]  # the biggest outline (depth 0)
        for j in sorted(range(1, len(loops)), key=lambda k: depth[k]):
            if depth[j] % 2 == 0:  # an island (or one inside a hole): bevelled like the main outline
                piece = [q for q in (polygon(pts, tag) for pts in local_polys("extrude", {**g.params, "points": loops[j]}, spec)) if q]
                body = union(body, piece)
            else:
                cutter = _oriented(_extrude_polys(loops[j], height + 0.02, 0.0, 1, -offset))
                body = subtract(body, [q for q in (polygon(pts, tag) for pts in cutter) if q])
        local_pts = [list(poly.points) for poly in body]
    m = g.rotation if g.rotation is not None else np.eye(3)
    placed = _place(local_pts, m, g.at, tag)
    if g.shell:  # a wall inside the surface, or centred on it (side: both); open: one side cut away, showing the rim
        outer = (_shrunk(g, spec, tag, -g.shell) if g.shell_side == "both" else []) or placed
        inner = _shrunk(g, spec, tag, g.shell)
        placed = subtract(outer, inner) if inner else outer
        if g.open is not None:
            axis, sign = g.open
            lo, hi = SHAPES[g.shape].bounds(g.params)
            lo, hi = lo - g.shell - 1.0, hi + g.shell + 1.0
            if sign > 0:
                hi[axis] = g.open_plane()
            else:
                lo[axis] = g.open_plane()
            keep = convex(*_planes_box((hi - lo).tolist()))
            box = _place([[(float(x), float(y), float(z)) for x, y, z in pts] for pts, _ in keep], np.eye(3), (lo + hi) / 2, tag)
            box = _place([list(q.points) for q in box], m, g.at, tag)
            placed = intersect(placed, box)
    copies = []
    for c in g.copies:
        if c is IDENTITY:
            copies.append(placed)
        else:
            moved = [[(float(x), float(y), float(z)) for x, y, z in c.to_world(np.array(poly.points))] for poly in placed]
            copies.append([q for q in (polygon(pts, tag) for pts in moved) if q])
    out = _union_all(copies) if len(copies) > 1 else copies[0]
    for axis in g.mirror:
        lo, hi = _box(out)
        span = np.maximum(np.abs(lo), np.abs(hi)) + 1.0
        half = intersect(out, _halfspace(axis, -span, span, tag))
        flip = np.eye(3)
        flip[axis, axis] = -1.0
        mirrored = _place([list(poly.points) for poly in half], flip, np.zeros(3), tag)
        out = union(half, mirrored)
    return out


def _shrunk(g: Geometry, spec: HardSpec, tag: int, t: float) -> Solid:
    """The inside of a hard shell: the shape moved inwards by t (shapes with a simple inward offset)."""
    p = dict(g.params)
    if g.shape in ("box", "wedge"):
        p["size"] = [max(float(v) - 2 * t, 1e-4) for v in p["size"]]
    elif g.shape in ("cylinder", "cone"):
        p["radius"] = max(float(p["radius"]) - t, 1e-4)
        if g.shape == "cone" and float(p["radius_top"]) > 0:
            p["radius_top"] = max(float(p["radius_top"]) - t, 1e-4)
        p["height"] = max(float(p["height"]) - 2 * t, 1e-4)
    elif g.shape == "sphere":
        p["radius"] = max(float(p["radius"]) - t, 1e-4)
    elif g.shape == "ellipsoid":
        p["radii"] = [max(float(v) - t, 1e-4) for v in p["radii"]]
    elif g.shape == "lathe":  # the (r, y) outline moved inwards; points on the axis stay on it
        prof = [(float(r), float(y)) for r, y in (p.get("hard_profile") or p["profile"])]
        area = sum(prof[i][0] * prof[(i + 1) % len(prof)][1] - prof[(i + 1) % len(prof)][0] * prof[i][1] for i in range(len(prof)))
        if area < 0:
            prof.reverse()
        moved = _offset_outline(prof, t)
        p["hard_profile"] = p["profile"] = [[0.0 if r0 == 0 else max(r, 0.0), y] for (r0, _), (r, y) in zip(prof, moved, strict=True)]
    else:
        return []
    m = g.rotation if g.rotation is not None else np.eye(3)
    return _place(local_polys(g.shape, p, HardSpec(spec.sides, max(spec.bevel - t, 0.0), spec.segments)), m, g.at, tag)


# --- the model's hard solid -> a welded triangle mesh -------------------------------------------------------------


@dataclass
class HardMesh:
    vertices: Array  # (V, 3)
    faces: Array  # (F, 3)
    face_part: Array  # (F,) part index (polygon tag)
    face_normal: Array  # (F, 3) the polygon's plane normal (exact; triangles of one polygon share it)
    face_polygon: Array  # (F,) which polygon each triangle came from

    @property
    def triangles(self) -> int:
        return int(len(self.faces))


def _weld(points: Array, tol: float) -> tuple[Array, Array]:
    """Merge points closer than tol: (unique points, index per input point). Deterministic: the first of a
    cluster (in input order) is kept."""
    cell = tol * 4
    pts = points.tolist()
    keys = np.floor(points / cell).astype(np.int64).tolist()
    table: dict[tuple[int, int, int], list[int]] = {}
    out_index = [0] * len(pts)
    kept: list[int] = []
    for i, (p, k) in enumerate(zip(pts, keys, strict=True)):
        found = -1
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for j in table.get((k[0] + dx, k[1] + dy, k[2] + dz), ()):
                        q = pts[kept[j]]
                        if abs(q[0] - p[0]) <= tol and abs(q[1] - p[1]) <= tol and abs(q[2] - p[2]) <= tol:
                            found = j
                            break
                    if found >= 0:
                        break
                if found >= 0:
                    break
            if found >= 0:
                break
        if found < 0:
            found = len(kept)
            kept.append(i)
            table.setdefault((k[0], k[1], k[2]), []).append(found)
        out_index[i] = found
    return points[kept], np.asarray(out_index, dtype=np.int64)


def _on_edges(vertices: Array, edges: list[tuple[int, int]]) -> dict[tuple[int, int], list[int]]:
    """Vertices lying inside other edges (T-junctions), found through a grid of cells."""
    if not edges:
        return {}
    v = vertices.tolist()
    lengths = [math.dist(v[a], v[b]) for a, b in edges]
    cell = max(sorted(lengths)[len(lengths) // 2], WELD * 10)
    grid: dict[tuple[int, int, int], list[int]] = {}
    for i, p in enumerate(v):
        grid.setdefault((math.floor(p[0] / cell), math.floor(p[1] / cell), math.floor(p[2] / cell)), []).append(i)
    out: dict[tuple[int, int], list[int]] = {}
    for (a, b), length in zip(edges, lengths, strict=True):
        pa, pb = v[a], v[b]
        lo = [math.floor((min(pa[k], pb[k]) - WELD) / cell) for k in range(3)]
        hi = [math.floor((max(pa[k], pb[k]) + WELD) / cell) for k in range(3)]
        d = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
        dd = length * length
        if dd <= 0:
            continue
        for x in range(lo[0], hi[0] + 1):
            for y in range(lo[1], hi[1] + 1):
                for z in range(lo[2], hi[2] + 1):
                    for c in grid.get((x, y, z), ()):
                        if c == a or c == b:
                            continue
                        p = v[c]
                        t = ((p[0] - pa[0]) * d[0] + (p[1] - pa[1]) * d[1] + (p[2] - pa[2]) * d[2]) / dd
                        if t <= 1e-9 or t >= 1 - 1e-9:
                            continue
                        if max(abs(pa[k] + d[k] * t - p[k]) for k in range(3)) <= WELD:
                            out.setdefault((a, b), []).append(c)
    return out


def to_mesh(polys: Solid) -> HardMesh:
    if not polys:
        return HardMesh(np.zeros((0, 3)), np.zeros((0, 3), np.int64), np.zeros(0, np.int64), np.zeros((0, 3)), np.zeros(0, np.int64))
    flat = np.array([p for poly in polys for p in poly.points])
    vertices, index = _weld(flat, WELD)
    loops: list[list[int]] = []
    pos = 0
    for poly in polys:
        loop = [int(i) for i in index[pos : pos + len(poly.points)]]
        pos += len(poly.points)
        loop = [v for k, v in enumerate(loop) if v != loop[k - 1]]
        loops.append(loop)
    # T-junctions: a vertex lying on another polygon's edge splits that edge (or the mesh has cracks)
    edges = sorted({(min(l[k], l[(k + 1) % len(l)]), max(l[k], l[(k + 1) % len(l)])) for l in loops for k in range(len(l))})
    on_edge = _on_edges(vertices, edges)
    faces: list[tuple[int, int, int]] = []
    face_poly: list[int] = []
    for pi, loop in enumerate(loops):
        full: list[int] = []
        inserted = False
        for k in range(len(loop)):
            u, w = loop[k], loop[(k + 1) % len(loop)]
            full.append(u)
            extra = on_edge.get((min(u, w), max(u, w)))
            if extra:
                inserted = True
                dvec = vertices[w] - vertices[u]
                full += sorted(set(extra), key=lambda x: float((vertices[x] - vertices[u]) @ dvec))
        for sub in _simple_loops(full):
            tris = _fan(sub, vertices, polys[pi].plane.normal, inserted)
            if tris is None:  # needs a middle point
                c = len(vertices)
                vertices = np.concatenate([vertices, vertices[sub].mean(axis=0, keepdims=True)])
                tris = [(c, sub[k], sub[(k + 1) % len(sub)]) for k in range(len(sub))]
            faces += tris
            face_poly += [pi] * len(tris)
    f = np.array(faces, dtype=np.int64).reshape(-1, 3)
    fp = np.array(face_poly, dtype=np.int64)
    tags = np.array([polys[i].tag for i in fp], dtype=np.int64)
    normals = np.array([polys[i].plane.normal for i in fp], float).reshape(-1, 3)
    f, tags, normals, fp = _merge_planar(vertices, f, tags, normals, fp)
    used, inverse = np.unique(f, return_inverse=True)
    return HardMesh(vertices[used], inverse.reshape(-1, 3).astype(np.int64), tags, normals, fp)


def _simple_loops(loop: list[int]) -> list[list[int]]:
    """A polygon's outline split where it visits a point twice, keeping the pieces with three or more points. A CSG
    sliver thinner than WELD can have one of its own corners on its opposite edge: that edge, split there like any
    T-junction, folds the outline back over itself, and fanning it whole gives two faces back to back (#67). The
    pieces of fewer than three points are the folds (an edge out and back): no area, so they go."""
    out: list[list[int]] = []
    stack: list[int] = []
    for x in loop + loop[:1]:
        if x in stack:
            k = stack.index(x)
            piece = stack[k:]
            del stack[k + 1 :]
            if len(piece) >= 3:
                out.append(piece)
        else:
            stack.append(x)
    return out


def _merge_planar(vertices: Array, faces: Array, tags: Array, normals: Array, poly: Array) -> tuple[Array, Array, Array, Array]:
    """The CSG cuts polygons into many pieces along other solids' planes. Every flat patch (connected faces of one
    part on one plane) is triangulated again from its outline (holes bridged in), dropping the points that every
    patch using them has in a straight line: the same surface, watertight, with far fewer triangles."""
    probe = HardMesh(vertices, faces, tags, normals, poly)
    patch = _patches(probe)
    order = np.argsort(patch, kind="stable")
    bounds = np.flatnonzero(np.r_[True, patch[order][1:] != patch[order][:-1], True])
    v = vertices.tolist()
    members_of = [order[bounds[k] : bounds[k + 1]] for k in range(len(bounds) - 1)]
    # a point can go if, in every patch that uses it, it's inside the patch or on a straight stretch of its outline
    keep_point: set[int] = set()
    for members in members_of:
        tris = faces[members].tolist()
        keep_point |= _outline_points(tris, v, normals[members[0]])[1] if len(members) > 1 else {x for t in tris for x in t}
    # a patch that can't be redone keeps all its points, so its neighbours must keep them too: repeat until settled
    while True:
        new_faces: list[list[int]] = []
        new_from: list[int] = []
        failed: set[int] = set()
        for members in members_of:
            tris = faces[members].tolist()
            redone = _retriangulate(tris, v, normals[members[0]], keep_point) if len(members) > 1 else None
            if redone is None or len(redone) > len(tris):
                failed |= {x for t in tris for x in t}
                redone = tris
            new_faces += redone
            new_from += [int(members[0])] * len(redone)
        if failed <= keep_point:
            break
        keep_point |= failed
    src = np.asarray(new_from, dtype=np.int64)
    out = np.asarray(new_faces, dtype=np.int64).reshape(-1, 3)
    # stable output order: by the first face each patch came from
    keep = np.argsort(src, kind="stable")
    return out[keep], tags[src][keep], normals[src][keep], poly[src][keep]


def _project2(normal: Array, v: list[list[float]], ids: set[int]) -> dict[int, tuple[float, float]]:
    """2D coordinates in the patch's plane, counter-clockwise seen from outside."""
    n = normal.tolist()
    axis = max(range(3), key=lambda i: abs(n[i]))
    a0, a1 = (axis + 1) % 3, (axis + 2) % 3  # cyclic: counter-clockwise seen from +axis
    flip = n[axis] < 0
    return {i: ((v[i][a0], v[i][a1]) if not flip else (v[i][a1], v[i][a0])) for i in ids}


def _boundary(tris: list[list[int]]) -> dict[int, int] | None:
    directed = {(t[i], t[(i + 1) % 3]) for t in tris for i in range(3)}
    edges = sorted((a, b) for a, b in directed if (b, a) not in directed)
    boundary = dict(edges)
    # None: the outline touches itself, or doesn't close (a patch whose edges only meet other patches' at T-points)
    return boundary if len(boundary) == len(edges) and set(boundary.values()) == set(boundary) else None


def _outline_points(tris: list[list[int]], v: list[list[float]], normal: Array) -> tuple[set[int], set[int]]:
    """(points on straight stretches of the patch's outline, its corners). Points inside the patch are neither."""
    boundary = _boundary(tris)
    if boundary is None:
        pts = {x for t in tris for x in t}
        return set(), pts
    prev = {b: a for a, b in boundary.items()}
    straight: set[int] = set()
    corners: set[int] = set()
    for b, c in boundary.items():
        (straight if _in_line(v, prev[b], b, c) else corners).add(b)
    return straight, corners


def _in_line(v: list[list[float]], a: int, b: int, c: int) -> bool:
    """Is point b within WELD of the line through a and c? The same test in every patch sharing the three points
    (a test in each patch's own projection, or one tighter than the weld, can call a point the CSG left a hair off a
    shared edge a corner on both sides: each side then cuts the same zero-area ear, two faces back to back, #60)."""
    pa, pb, pc = v[a], v[b], v[c]
    d = (pc[0] - pa[0], pc[1] - pa[1], pc[2] - pa[2])
    e = (pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2])
    cr = _cross(d, e)
    return _dot(cr, cr) <= WELD * WELD * max(_dot(d, d), 1e-24)


def _retriangulate(tris: list[list[int]], v: list[list[float]], normal: Array, keep_point: set[int]) -> list[list[int]] | None:
    """A flat patch's triangles made again from its outline (and holes, bridged into it): ear clipping. Points in
    a straight line go unless some other patch needs them (`keep_point`)."""
    boundary = _boundary(tris)
    if boundary is None:
        return None
    pts2 = _project2(normal, v, set(boundary))

    def cross(o: int, a: int, b: int) -> float:
        return (pts2[a][0] - pts2[o][0]) * (pts2[b][1] - pts2[o][1]) - (pts2[a][1] - pts2[o][1]) * (pts2[b][0] - pts2[o][0])

    scale = max(max(abs(c) for c in pts2[i]) for i in boundary) or 1.0
    eps = 1e-12 * scale * scale
    loops: list[list[int]] = []
    left = set(boundary)
    while left:
        start = min(left)
        loop = [start]
        left.discard(start)
        while True:
            nxt = boundary[loop[-1]]
            if nxt == start:
                break
            if nxt not in left:
                return None
            loop.append(nxt)
            left.discard(nxt)
        # points in a line go (all at once: taking them one by one would decide differently in each patch), unless
        # some patch needs them
        straight = {loop[k] for k in range(len(loop)) if _in_line(v, loop[k - 1], loop[k], loop[(k + 1) % len(loop)])}
        loop = [x for x in loop if x in keep_point or x not in straight]
        if len(loop) < 3:
            return None
        loops.append(loop)

    def area(loop: list[int]) -> float:
        return sum(pts2[loop[k]][0] * pts2[loop[(k + 1) % len(loop)]][1] - pts2[loop[(k + 1) % len(loop)]][0] * pts2[loop[k]][1]
                   for k in range(len(loop))) / 2  # fmt: skip

    outer = [lp for lp in loops if area(lp) > 0]
    holes = [lp for lp in loops if area(lp) <= 0]
    if len(outer) != 1:
        return None
    ring = outer[0]
    all_edges = [(lp[k], lp[(k + 1) % len(lp)]) for lp in loops for k in range(len(lp))]

    def crosses(p: int, q: int) -> bool:
        """Does segment p-q cross any outline edge (other than at p or q)?"""
        for a, b in all_edges:
            if a in (p, q) or b in (p, q):
                continue
            d1, d2 = cross(p, q, a), cross(p, q, b)
            d3, d4 = cross(a, b, p), cross(a, b, q)
            if ((d1 > eps and d2 < -eps) or (d1 < -eps and d2 > eps)) and ((d3 > eps and d4 < -eps) or (d3 < -eps and d4 > eps)):
                return True
            if abs(d1) <= eps and abs(d2) <= eps:  # collinear overlap
                lo = min(pts2[p][0], pts2[q][0]), min(pts2[p][1], pts2[q][1])
                hi = max(pts2[p][0], pts2[q][0]), max(pts2[p][1], pts2[q][1])
                for x in (a, b):
                    if lo[0] - 1e-12 <= pts2[x][0] <= hi[0] + 1e-12 and lo[1] - 1e-12 <= pts2[x][1] <= hi[1] + 1e-12:
                        return True
        return False

    for hole in sorted(holes, key=lambda lp: -max(pts2[i][0] for i in lp)):
        m_at = max(range(len(hole)), key=lambda k: (pts2[hole[k]][0], -hole[k]))
        m = hole[m_at]
        best = None
        for k, cand in enumerate(ring):
            dist = (pts2[cand][0] - pts2[m][0]) ** 2 + (pts2[cand][1] - pts2[m][1]) ** 2
            if best is not None and dist >= best[0]:
                continue
            if cand == m or crosses(m, cand):
                continue
            # the bridge must leave the ring's corner on its inside
            prev, nxt = ring[k - 1], ring[(k + 1) % len(ring)]
            convex = cross(prev, cand, nxt) > 0
            inside = (cross(prev, cand, m) >= -eps and cross(cand, nxt, m) >= -eps) if convex else not (cross(prev, cand, m) < -eps and cross(cand, nxt, m) < -eps)
            if inside:
                best = (dist, k)
        if best is None:
            return None
        k = best[1]
        rotated = hole[m_at:] + hole[:m_at]
        ring = ring[: k + 1] + rotated + [m, ring[k]] + ring[k + 1 :]
        all_edges += [(ring[k], m), (m, ring[k])]
    out: list[list[int]] = []
    guard = 0
    while len(ring) > 3 and guard < 100000:
        guard += 1
        for k in range(len(ring)):
            a, b, c = ring[k - 1], ring[k], ring[(k + 1) % len(ring)]
            if a == c or cross(a, b, c) <= eps or _in_line(v, a, b, c):
                continue
            if any(p not in (a, b, c) and cross(a, b, p) >= -eps and cross(b, c, p) >= -eps and cross(c, a, p) >= -eps for p in ring):
                continue
            out.append([a, b, c])
            ring.pop(k)
            break
        else:
            return None
    if len(ring) == 3:
        if cross(ring[0], ring[1], ring[2]) <= eps or _in_line(v, ring[0], ring[1], ring[2]):
            return None
        out.append(list(ring))
    return out


def _fan(loop: list[int], v: Array, normal: Point, inserted: bool) -> list[tuple[int, int, int]] | None:
    """Triangles of a convex polygon (possibly with extra points along its edges) without zero-area slivers:
    a fan from a corner whose two edges carry no extra points, else None."""
    k = len(loop)
    if not inserted:
        return [(loop[0], loop[i], loop[i + 1]) for i in range(1, k - 1)]
    p = [tuple(v[i].tolist()) for i in loop]

    def straight(i: int) -> bool:
        a, b, c = p[i - 1], p[i], p[(i + 1) % k]
        cr = _cross(_sub(b, a), _sub(c, b))
        span = _sub(c, a)
        return math.sqrt(_dot(cr, cr)) <= 1e-12 * max(_dot(span, span), 1e-24) + 1e-14

    for i in range(k):
        if straight(i) or straight((i - 1) % k) or straight((i + 1) % k):
            continue
        order = [(i + j) % k for j in range(k)]
        tris = [(order[0], order[j], order[j + 1]) for j in range(1, k - 1)]
        if all(_dot(_cross(_sub(p[b], p[a]), _sub(p[c], p[a])), normal) > 1e-14 for a, b, c in tris):
            return [(loop[a], loop[b], loop[c]) for a, b, c in tris]
    return None


def _patches(mesh: HardMesh) -> Array:
    """Each face's flat patch (the polygon it belongs to, after any cutting): neighbours sharing an edge, part and
    plane are one patch."""
    f = mesh.faces
    parent = np.arange(len(f))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    owner = np.tile(np.arange(len(f)), 3)
    key = np.sort(e, axis=1)
    order = np.lexsort((key[:, 1], key[:, 0]))
    key, owner = key[order], owner[order]
    same = np.flatnonzero((key[1:] == key[:-1]).all(axis=1))
    a, b = owner[same], owner[same + 1]
    flat = ((mesh.face_normal[a] * mesh.face_normal[b]).sum(axis=1) > 1 - 1e-9) & (mesh.face_part[a] == mesh.face_part[b])
    for x, y in zip(a[flat], b[flat], strict=True):
        rx, ry = find(int(x)), find(int(y))
        if rx != ry:
            parent[max(rx, ry)] = min(rx, ry)
    return np.array([find(i) for i in range(len(f))])


def corner_normals(mesh: HardMesh, smooth: bool, sharp_angle: float) -> Array:
    """(F, 3, 3): each face's polygon normal; smooth styles blend it with neighbouring faces of the same part that
    turn less than `sharp_angle`, weighted by their flat patch's area: big faces stay flat, bevel bands between them
    shade round, designed edges stay crisp."""
    flat = np.repeat(mesh.face_normal[:, None, :], 3, axis=1)
    if not smooth or not len(mesh.faces):
        return flat
    cos_limit = math.cos(math.radians(sharp_angle))
    f = mesh.faces
    v = mesh.vertices
    area = np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1) / 2
    patch = _patches(mesh)
    patch_area = np.bincount(patch, weights=area, minlength=len(f))
    # per vertex: the patches around it (each counted once)
    order = np.argsort(f.reshape(-1), kind="stable")
    corner_vertex = f.reshape(-1)[order]
    starts = np.searchsorted(corner_vertex, np.arange(len(v) + 1))
    out = flat.copy()
    for vert in range(len(v)):
        corners = order[starts[vert] : starts[vert + 1]]
        if len(corners) < 2:
            continue
        fids = corners // 3
        patches, first = np.unique(patch[fids], return_index=True)
        if len(patches) < 2:
            continue
        normals = mesh.face_normal[fids[first]]
        parts = mesh.face_part[fids[first]]
        weight = patch_area[patches]
        for c, fi in zip(corners, fids, strict=True):
            mine = (parts == mesh.face_part[fi]) & (normals @ mesh.face_normal[fi] >= cos_limit)
            acc = (normals[mine] * weight[mine, None]).sum(axis=0)
            length = float(np.linalg.norm(acc))
            if length > 0:
                out[fi, c % 3] = acc / length
    return out


__all__ = ["HARD_SHAPES", "HardMesh", "HardSpec", "Polygon", "corner_normals", "intersect", "solid", "subtract", "to_mesh", "union"]
