"""Which parts cover a part's own surface (#98): W101 names them, W124 flags a part that shows only a sliver.

A part's own surface is sampled (a grid over its box, each point moved onto the surface along the gradient) and
each sample tested against the other adding parts of the same piece: covered where it is deeper inside one of them
than the blend between them, and no cut on that part opens it again (a helmet's eye slit).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from kiln.notation import Model
from kiln.sdf import Array, Field, Geometry

GRID = 12  # samples per axis over the part's box, before moving them onto its surface
MOSTLY = 0.97  # W124: this much of a part's own surface inside other parts (only a sliver shows)


@dataclass(frozen=True)
class Cover:
    covered: float  # fraction of the part's own surface inside other parts
    by: tuple[int, ...]  # the covering parts, most first


def surface_samples(g: Geometry, step: float) -> Array:
    """Points on the part's own surface: a GRID^3 lattice over its box, moved onto the surface by Newton steps."""
    lo, hi = g.bounds()
    pad = 0.1 * float((hi - lo).max()) + step
    axes = [np.linspace(lo[k] - pad, hi[k] + pad, GRID) for k in range(3)]
    p = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    eps = step * 0.05
    for _ in range(8):
        d = g.distance(p)
        grad = np.stack([(g.distance(p + e) - g.distance(p - e)) / (2 * eps) for e in np.eye(3) * eps], axis=1)
        norm2 = np.maximum((grad * grad).sum(axis=1, keepdims=True), 1e-12)
        p = p - d[:, None] * grad / norm2
    return p[np.abs(g.distance(p)) < eps]


def _pieces(model: Model) -> dict[int, str]:
    """Each adding part's piece: `separate` parts (skinned models) are meshed apart and cover nothing else."""
    separate = {pid for pid, e in model.rig.items() if e.separate} if model.skin != "none" else set()
    return {i: (p.id if p.id in separate else "") for i, p in enumerate(model.parts) if p.geometry.op == "add"}


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
