"""Colours that fade across part borders (#230, part `color_blend`), per texel of the base colour map.

The mesh keeps its crisp colour border. Within `color_blend` of it (the straight distance to the nearest border
edge), each point's colour is a mix of its own colour and the colour across that edge: half and half on the border
itself, so both sides meet in the same colour, and all its own at `color_blend`. Only the two parts that meet at
an edge fade there, and only where their surface faces the way the border does (not the far side of a thin part). (Not the difference of the two
parts' distances: a shallow patch lying on a body, a belly or a muzzle, is near the body everywhere and would fade
all over.)
"""

from __future__ import annotations

import numpy as np

from kiln.sdf import Array


def near_cells(points: Array, anchors: Array, cell: float) -> Array:
    """Whether each point is in a grid cell (of size `cell`) next to one holding an anchor: a quick, generous
    "within `cell` of some anchor"."""
    if not len(anchors) or not len(points):
        return np.zeros(len(points), dtype=bool)
    shifts = np.stack(np.meshgrid([-1, 0, 1], [-1, 0, 1], [-1, 0, 1], indexing="ij"), axis=-1).reshape(-1, 3)
    mine = (np.floor(anchors / cell).astype(np.int64)[:, None, :] + shifts[None, :, :]).reshape(-1, 3)
    theirs = np.floor(points / cell).astype(np.int64)
    low = np.minimum(mine.min(axis=0), theirs.min(axis=0))
    dims = np.maximum(mine.max(axis=0), theirs.max(axis=0)) - low + 1

    def key(ijk: Array) -> Array:
        rel = ijk - low
        return np.asarray((rel[:, 0] * dims[1] + rel[:, 1]) * dims[2] + rel[:, 2])

    return np.asarray(np.isin(key(theirs), np.unique(key(mine))))


FACING = 0.2  # a border fades the surface that faces its way (dot of the normals): not the back of a thin part


class Fade:
    """The colour borders of a mesh that fade: per border edge its two ends (E, 2, 3), the paint groups (E, 2) and
    the parts (E, 2) on its two sides, the surface normal there (E, 3) and how far the fade reaches from it (E,);
    `face_part` is each face's part."""

    def __init__(self, ends: Array, groups: Array, parts: Array, normals: Array, reach: Array, face_part: Array) -> None:
        pieces = np.maximum(np.ceil(np.linalg.norm(ends[:, 1] - ends[:, 0], axis=1) / np.maximum(reach, 1e-9)), 1).astype(np.int64)
        which = np.repeat(np.arange(len(ends)), pieces)  # long edges in pieces no longer than their reach: the grids below rely on it
        k = np.arange(len(which)) - np.repeat(np.cumsum(pieces) - pieces, pieces)
        a, b = ends[which, 0], ends[which, 1]
        n = pieces[which][:, None]
        self.ends = np.stack([a + (b - a) * (k[:, None] / n), a + (b - a) * ((k[:, None] + 1) / n)], axis=1)
        self.groups = groups[which]
        self.parts = parts[which]
        self.normals = normals[which]
        self.reaches = reach[which]
        self.reach = float(reach.max()) if len(reach) else 0.0
        self.face_part = face_part

    def touches(self, points: Array) -> Array:
        if self.reach <= 0:
            return np.zeros(len(points), dtype=bool)
        return near_cells(points, self.ends.reshape(-1, 3), self.reach)

    def mix(self, points: Array, faces: Array, normals: Array) -> tuple[Array, Array]:
        """Per point (on face `faces`, with unit surface `normals`): (the paint group whose colour it fades toward,
        how much of that colour: 0..0.5). No fade: weight 0."""
        from kiln.relief import Index

        other = np.zeros(len(points), dtype=np.int64)
        weight = np.zeros(len(points))
        if self.reach <= 0 or not len(points):
            return other, weight
        nearest = np.full(len(points), np.inf)
        mine = self.face_part[faces]
        index = Index(points, self.reach * 2)  # (a piece is no longer than its reach: its middle's cells hold all it touches)
        for e in range(len(self.ends)):
            a, b = self.ends[e]
            near = index.near((a + b) * 0.5)
            pa, pb = self.parts[e]
            near = near[((mine[near] == pa) | (mine[near] == pb)) & (normals[near] @ self.normals[e] > FACING)]
            if not len(near):
                continue
            ab = b - a
            t = np.clip((points[near] - a) @ ab / max(float(ab @ ab), 1e-18), 0.0, 1.0)
            d = np.linalg.norm(points[near] - (a + t[:, None] * ab), axis=1) / self.reaches[e]  # in reaches: the nearest edge in its own terms
            better = d < nearest[near]
            near, d = near[better], d[better]
            nearest[near] = d
            other[near] = np.where(mine[near] == pa, self.groups[e][1], self.groups[e][0])
        t = np.clip(nearest, 0.0, 1.0)
        weight = 0.5 * (1 - t) ** 2  # a straight ramp through the border (no band of the half-way colour), easing out at the reach
        return other, weight


__all__ = ["Fade", "near_cells"]
