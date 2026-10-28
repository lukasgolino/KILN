"""Outlines filled by the nonzero rule (how fonts are drawn): overlapping contours of a glyph join instead of cutting
holes into each other, as even-odd would. Used for `extrude: { text: ... }`; plain SVG `path:` keeps even-odd.

Outlines that don't overlap (and whose holes sit inside an outline of the opposite winding) fill the same either way
and are returned as they are. Otherwise each outer contour minus its own holes is extruded into a thin prism, the
prisms are unioned with the hard-surface CSG, and the union's top face gives the new outlines. A contour that crosses
itself is first split at its crossings into loops that don't (`untangle`), keeping every point's winding number."""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

Loop = list[list[float]]  # [[x, y], ...]


def _area(loop: Loop) -> float:
    return sum(loop[i - 1][0] * loop[i][1] - loop[i][0] * loop[i - 1][1] for i in range(len(loop))) / 2


def _box(loop: Loop) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    return min(xs), min(ys), max(xs), max(ys)


def _boxes_meet(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _segments_cross(p: list[float], q: list[float], r: list[float], s: list[float]) -> bool:
    def orient(a: list[float], b: list[float], c: list[float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1, d2, d3, d4 = orient(r, s, p), orient(r, s, q), orient(p, q, r), orient(p, q, s)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)) and 0 not in (d1, d2, d3, d4)


def _loops_cross(a: Loop, b: Loop) -> bool:
    for i in range(len(a)):
        p, q = a[i - 1], a[i]
        for j in range(len(b)):
            if _segments_cross(p, q, b[j - 1], b[j]):
                return True
    return False


def _inside(point: list[float], loop: Loop) -> bool:
    x, y = point
    inside = False
    j = len(loop) - 1
    for i in range(len(loop)):
        xi, yi, xj, yj = loop[i][0], loop[i][1], loop[j][0], loop[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _depth(k: int, loops: list[Loop]) -> int:
    return sum(_inside(loops[k][0], loop) for j, loop in enumerate(loops) if j != k)


def _crossing(p: list[float], q: list[float], r: list[float], s: list[float]) -> list[float]:
    """Where segment p-q crosses segment r-s (they're known to cross)."""
    d = (q[0] - p[0]) * (s[1] - r[1]) - (q[1] - p[1]) * (s[0] - r[0])
    t = ((r[0] - p[0]) * (s[1] - r[1]) - (r[1] - p[1]) * (s[0] - r[0])) / d
    return [p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]


def untangle(loop: Loop) -> list[Loop]:
    """A contour that crosses itself (a font's 8 drawn as one outline) as loops that don't, each going the way its
    part of the contour went, so every point keeps its winding number: at a crossing the contour is cut into the
    stretch between the two visits and the rest, both closed at the crossing point (repeated until none cross)."""
    k = len(loop)
    for i in range(k):
        for j in range(i + 2, k):
            if (j + 1) % k == i:  # the closing pair of neighbouring edges
                continue
            p, q, r, s = loop[i], loop[(i + 1) % k], loop[j], loop[(j + 1) % k]
            if _segments_cross(p, q, r, s):
                at = _crossing(p, q, r, s)
                inner = [at, *loop[i + 1 : j + 1]]
                outer = [at, *loop[j + 1 :], *loop[: i + 1]]
                return [*untangle(inner), *untangle(outer)]
    return [loop]


def needs_union(loops: list[Loop]) -> bool:
    """True when even-odd and nonzero would fill these outlines differently: contours that cross, or one inside
    another with the same winding (overlapping strokes), or a hole winding the same way as what it's in."""
    boxes = [_box(loop) for loop in loops]
    signs = [_area(loop) > 0 for loop in loops]
    for i in range(len(loops)):
        for j in range(i + 1, len(loops)):
            if _boxes_meet(boxes[i], boxes[j]) and _loops_cross(loops[i], loops[j]):
                return True
    for k in range(len(loops)):
        containers = [j for j in range(len(loops)) if j != k and _boxes_meet(boxes[j], boxes[k]) and _inside(loops[k][0], loops[j])]
        if containers:
            parent = min(containers, key=lambda j: abs(_area(loops[j])))
            if signs[parent] == signs[k]:
                return True
    return False


def nonzero(loops: list[Loop]) -> list[Loop]:
    """The outlines of the region the loops fill by the nonzero rule (as non-overlapping outlines + holes)."""
    loops = [loop for loop in loops if len(loop) >= 3 and abs(_area(loop)) > 1e-14]
    parts = [untangle(loop) for loop in loops]
    tangled = any(len(each) > 1 for each in parts)
    if tangled:  # loops start just after their crossing point, so the nesting tests below don't sample on an edge
        loops = [lp[1:] + lp[:1] for each in parts for lp in each if len(lp) >= 3 and abs(_area(lp)) > 1e-14]
    if not tangled and (len(loops) < 2 or not needs_union(loops)):
        return loops
    from kiln.hard import Solid, _extrude_polys, polygon, subtract, to_mesh, union

    outer_sign = _area(max(loops, key=lambda loop: abs(_area(loop)))) > 0
    outers = [k for k, loop in enumerate(loops) if (_area(loop) > 0) == outer_sign]
    holes: dict[int, list[int]] = defaultdict(list)
    for k, loop in enumerate(loops):
        if k in outers:
            continue
        containers = [j for j in outers if _inside(loop[0], loops[j])]
        if containers:
            holes[min(containers, key=lambda j: abs(_area(loops[j])))].append(k)
        else:
            outers.append(k)  # a lone contour of the other winding is filled too (nonzero)

    def prism(loop: Loop, height: float) -> Solid:
        return [q for q in (polygon(pts, 0) for pts in _extrude_polys(loop, height, 0.0, 1)) if q]

    solid: Solid = []
    for k in outers:
        piece = prism(loops[k], 1.0)
        for h in holes.get(k, []):
            piece = subtract(piece, prism(loops[h], 1.2))
        solid = union(solid, piece)
    mesh = to_mesh(solid)
    top = [f for f in mesh.faces if np.all(np.abs(mesh.vertices[f, 1] - 0.5) < 1e-9)]
    count: dict[tuple[int, int], int] = defaultdict(int)
    for a, b, c in top:
        for u, w in ((a, b), (b, c), (c, a)):
            count[(int(u), int(w))] += 1
    boundary = [(u, w) for (u, w) in count if (w, u) not in count]
    nxt: dict[int, list[int]] = defaultdict(list)
    for u, w in boundary:
        nxt[u].append(w)
    out: list[Loop] = []
    used: set[tuple[int, int]] = set()
    for u, w in sorted(boundary):
        if (u, w) in used:
            continue
        loop_ids = [u]
        used.add((u, w))
        cur = w
        while cur != u:
            loop_ids.append(cur)
            choices = [v for v in nxt[cur] if (cur, v) not in used]
            if not choices:
                break
            used.add((cur, choices[0]))
            cur = choices[0]
        pts = [[float(mesh.vertices[i, 0]), float(mesh.vertices[i, 2])] for i in loop_ids]
        straight = [pts[i] for i in range(len(pts)) if not _collinear(pts[i - 1], pts[i], pts[(i + 1) % len(pts)])]
        if len(straight) >= 3:
            out.append(straight)
    return sorted(out, key=lambda loop: -abs(_area(loop)))


def _collinear(a: list[float], b: list[float], c: list[float]) -> bool:
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return abs(cross) <= 1e-12 * max(1.0, math.hypot(c[0] - a[0], c[1] - a[1]))
