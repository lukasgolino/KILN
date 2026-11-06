"""Which parts cover a part's own surface (#98): W101 names them, W124 flags a part that shows only a sliver.

A part's own surface is sampled (a grid over its box, each point moved onto the surface along the gradient) and
each sample tested against the other adding parts of the same piece: covered where it is deeper inside one of them
than the blend between them, and no cut on that part opens it again (a helmet's eye slit).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from kiln.builder import mesh_pieces
from kiln.notation import Model
from kiln.sdf import IDENTITY, Array, Field, Geometry

GRID = 12  # samples per axis over the part's box, before moving them onto its surface
MOSTLY = 0.97  # W124: this much of a part's own surface inside other parts (only a sliver shows)


@dataclass(frozen=True)
class Cover:
    covered: float  # fraction of the part's own surface inside other parts
    by: tuple[int, ...]  # the covering parts, most first


def surface_samples(g: Geometry, step: float) -> Array:
    """Points on the part's own surface: a GRID^3 lattice over one copy's box, moved onto its surface by Newton steps,
    then carried to every copy and mirror image (one lattice over a whole ring or row would leave most copies bare)."""
    one = replace(g, copies=(IDENTITY,), mirror=())
    lo, hi = one.bounds()
    pad = 0.1 * float((hi - lo).max()) + step
    axes = [np.linspace(lo[k] - pad, hi[k] + pad, GRID) for k in range(3)]
    p = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    eps = step * 0.05
    for _ in range(8):
        d = one.distance(p)
        grad = np.stack([(one.distance(p + e) - one.distance(p - e)) / (2 * eps) for e in np.eye(3) * eps], axis=1)
        norm2 = np.maximum((grad * grad).sum(axis=1, keepdims=True), 1e-12)
        p = p - d[:, None] * grad / norm2
    p = p[np.abs(one.distance(p)) < eps]
    points = np.concatenate([c.to_world(p) for c in g.copies]) if len(p) else p
    for axis in g.mirror:
        flipped = points.copy()
        flipped[:, axis] = -flipped[:, axis]
        points = np.concatenate([points, flipped])
    return points[np.abs(g.distance(points)) < eps] if len(points) else points  # copies that overlap hide some


def _pieces(model: Model) -> dict[int, int]:
    """Each adding part's piece, as the builder meshes them (separate parts, fitted shells, per_bone bones apart)."""
    pieces, _ = mesh_pieces(model)
    return {i: k for k, inc in enumerate(pieces) for i in inc}


def covers(model: Model, field: Field, step: float, parts: list[int], exact: frozenset[int] = frozenset()) -> dict[int, Cover]:
    """Cover of each of `parts` (adding parts) by the other adding parts of its piece. `exact`: hard parts, meshed as
    their tessellation rather than their distance field, so they are left out of the test (either way)."""
    piece = {i: p for i, p in _pieces(model).items() if i not in exact}
    tol = 0.1 * step
    out: dict[int, Cover] = {}
    for i in parts:
        if i not in piece:
            continue
        points = surface_samples(field.parts[i], step)
        if len(points) < 20:
            continue
        lo, hi = field.boxes[i]
        inside = np.zeros(len(points), dtype=bool)
        counts: dict[int, int] = {}
        for j, pj in piece.items():
            blo, bhi = field.boxes[j]
            if j == i or pj != piece[i] or np.any(blo > hi + step) or np.any(bhi < lo - step):
                continue
            # within a blend radius inside, the part still bulges the surface out (and owns the paint there)
            cover = field.part_distance(j, points) < -(tol + max(field.parts[i].blend, field.parts[j].blend))
            for c in range(j + 1, len(model.parts)):  # what a later cut takes from j (an eye slit) doesn't cover
                g = model.parts[c].geometry
                if g.op == "cut" and (g.cut_only is None or j in g.cut_only):
                    cover &= field.part_distance(c, points) > tol
                elif g.op == "intersect":
                    cover &= field.part_distance(c, points) < -tol
            if cover.any():
                counts[j] = int(cover.sum())
                inside |= cover
        by = tuple(sorted(counts, key=lambda j: (-counts[j], j)))
        out[i] = Cover(float(inside.mean()), by)
    return out


def mostly_covered(model: Model, field: Field, step: float, hidden: tuple[int, ...], exact: frozenset[int] = frozenset()) -> dict[int, Cover]:
    """W124 candidates: adding parts (not shells, separate, revealed or hard ones, not already hidden) that show only a sliver."""
    rig = model.rig if model.skin != "none" else {}
    skip = {pid for pid, e in rig.items() if e.separate or e.revealed}
    parts = [i for i, p in enumerate(model.parts) if p.geometry.op == "add" and not p.geometry.shell and p.id not in skip and i not in hidden]
    return {i: c for i, c in covers(model, field, step, parts, exact).items() if c.covered >= MOSTLY}


__all__ = ["MOSTLY", "Cover", "covers", "mostly_covered", "surface_samples"]
