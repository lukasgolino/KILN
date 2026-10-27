"""Attachments fitted to CC0 characters (`fit_to:`): a helmet, shield or banner made in KILN around a KayKit (or any
glTF) character's own mesh, exported in one of its bones' space so the game hangs it on that bone.

The target's surface becomes a distance field: its triangles are filed in a grid of cells, and a point's distance is
to the nearest triangle in the cells around it. CC0 meshes are often several pieces, some inside others (a face
inside a helmet), so each connected piece is read on its own, signed by the pseudo-normal of its nearest feature
(face, edge or corner: right at concave edges too), and the pieces combine as a union. Exact near the surface, which
is all a fitted shell needs; far away it only says "far": inside if the cell is cut off from outside by a piece.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from kiln.sdf import Array

CELL = 0.03  # grid cell; distances beyond about one cell read as `CELL * 1.5`, outside


def _node_matrix(node: dict[str, Any]) -> Array:
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]), float)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])  # fmt: skip
    s = np.array(node.get("scale", [1, 1, 1]), float)
    m = np.eye(4)
    m[:3, :3] = r * s[None, :]
    m[:3, 3] = t
    return m


def _worlds(doc: dict[str, Any]) -> dict[int, Array]:
    """Every node's rest world matrix."""
    out: dict[int, Array] = {}
    nodes = doc.get("nodes", [])

    def visit(i: int, parent: Array) -> None:
        out[i] = parent @ _node_matrix(nodes[i])
        for c in nodes[i].get("children", []):
            visit(c, out[i])

    scene = doc.get("scenes", [{}])[doc.get("scene", 0)] if doc.get("scenes") else {"nodes": list(range(len(nodes)))}
    for root in scene.get("nodes", []):
        visit(root, np.eye(4))
    return out


def bones(path: Path) -> list[str]:
    from kiln.importer import _document

    doc = _document(path)
    joints = {j for s in doc.get("skins", []) for j in s.get("joints", [])}
    return [str(doc["nodes"][j].get("name", "")) for j in sorted(joints)]


def meshes(path: Path) -> list[str]:
    from kiln.importer import _document

    return [str(m.get("name", f"mesh{i}")) for i, m in enumerate(_document(path).get("meshes", []))]


def bone_matrix(path: Path, bone: str) -> Array:
    """The bone's rest world matrix in the file's scene."""
    from kiln.importer import _document

    doc = _document(path)
    worlds = _worlds(doc)
    for i, n in enumerate(doc.get("nodes", [])):
        if n.get("name") == bone and i in worlds:
            return worlds[i]
    raise KeyError(bone)


def read_surface(path: Path, only: tuple[str, ...] = ()) -> tuple[Array, Array]:
    """(vertices, faces) of the file's meshes at rest (all, or the named ones), in its scene's space."""
    from kiln.importer import _accessor, _load

    doc, buffers = _load(path)
    worlds = _worlds(doc)
    verts, faces = [], []
    count = 0
    for i, node in enumerate(doc.get("nodes", [])):
        if "mesh" not in node or i not in worlds:
            continue
        mesh = doc["meshes"][node["mesh"]]
        if only and mesh.get("name") not in only:
            continue
        world = worlds[i]
        for prim in mesh["primitives"]:
            if prim.get("mode", 4) != 4:
                continue
            pos = _accessor(doc, buffers, prim["attributes"]["POSITION"])
            idx = _accessor(doc, buffers, prim["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in prim else np.arange(len(pos)).reshape(-1, 3)
            verts.append((np.concatenate([pos, np.ones((len(pos), 1))], axis=1) @ world.T)[:, :3])
            faces.append(idx + count)
            count += len(pos)
    if not verts:
        raise KeyError(", ".join(only) or "no meshes")
    return np.concatenate(verts), np.concatenate(faces)


def _closest(p: Array, a: Array, b: Array, c: Array) -> tuple[Array, Array]:
    """Closest points on triangles (a, b, c) to points p, row by row (Ericson, Real-Time Collision Detection 5.1.5),
    and which feature each lies on: 0 the face, 1-3 the edges ab, bc, ca, 4-6 the corners a, b, c."""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(1), (ac * ap).sum(1)
    bp = p - b
    d3, d4 = (ab * bp).sum(1), (ac * bp).sum(1)
    cp = p - c
    d5, d6 = (ab * cp).sum(1), (ac * cp).sum(1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = np.where(np.abs(va + vb + vc) < 1e-30, 1e-30, va + vb + vc)
    v, w = vb / denom, vc / denom
    out = a + ab * v[:, None] + ac * w[:, None]  # inside the face
    feature = np.zeros(len(p), np.int64)
    with np.errstate(divide="ignore", invalid="ignore"):
        # edges (each where the face case doesn't apply)
        for sel, start, edge, t, code in (
            ((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0), b, c - b, (d4 - d3) / ((d4 - d3) + (d5 - d6)), 2),
            ((vb <= 0) & (d2 >= 0) & (d6 <= 0), a, ac, d2 / (d2 - d6), 3),
            ((vc <= 0) & (d1 >= 0) & (d3 <= 0), a, ab, d1 / (d1 - d3), 1),
        ):
            out = np.where(sel[:, None], start + edge * np.where(sel, t, 0)[:, None], out)
            feature = np.where(sel, code, feature)
    # vertices
    for sel, corner, code in (((d6 >= 0) & (d5 <= d6), c, 6), ((d3 >= 0) & (d4 <= d3), b, 5), ((d1 <= 0) & (d2 <= 0), a, 4)):
        out = np.where(sel[:, None], corner, out)
        feature = np.where(sel, code, feature)
    return np.asarray(out), feature


def _pieces(faces: Array, count: int) -> Array:
    """Connected piece per face (faces sharing a vertex are one piece), numbered in order of first face."""
    parent = list(range(count))

    def root(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b, c in faces.tolist():
        ra, rb, rc = root(a), root(b), root(c)
        parent[rb] = ra
        parent[root(rc)] = ra
    roots = np.array([root(a) for a in faces[:, 0].tolist()], np.int64)
    _, first, label = np.unique(roots, return_index=True, return_inverse=True)
    return np.argsort(np.argsort(first))[label.ravel()]


def _pseudo_normals(tri: Array, faces: Array) -> Array:
    """(T, 7, 3): per triangle the pseudo-normals of its face, edges ab, bc, ca and corners a, b, c (Baerentzen &
    Aanaes 2005: an edge's is the sum of its faces' normals, a corner's their sum weighted by the angle there), on
    the welded `faces`, so the side of a point nearest an edge or corner of a closed piece is always right."""
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-18)
    corner = np.zeros((int(faces.max()) + 1 if len(faces) else 0, 3))
    for k in range(3):
        u, w = tri[:, (k + 1) % 3] - tri[:, k], tri[:, (k + 2) % 3] - tri[:, k]
        cos = (u * w).sum(1) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(w, axis=1), 1e-18)
        np.add.at(corner, faces[:, k], np.arccos(np.clip(cos, -1, 1))[:, None] * n)
    pairs = np.sort(np.stack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=1), axis=2)  # (T, 3, 2)
    _, edge = np.unique(pairs.reshape(-1, 2), axis=0, return_inverse=True)
    edge = edge.reshape(-1, 3)
    summed = np.zeros((int(edge.max()) + 1 if len(edge) else 0, 3))
    np.add.at(summed, edge.ravel(), np.repeat(n, 3, axis=0))
    return np.concatenate([n[:, None], summed[edge], corner[faces]], axis=1)


def _enclosed(filed: Array) -> Array:
    """Cells not filed and not reachable from the box's border through other such cells: deep inside."""
    free = ~filed
    out = np.zeros_like(filed)
    for axis in range(3):
        for end in (0, -1):
            idx: list[Any] = [slice(None)] * 3
            idx[axis] = end
            out[tuple(idx)] = free[tuple(idx)]
    while True:
        grown = out.copy()
        grown[1:] |= out[:-1]
        grown[:-1] |= out[1:]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        grown[:, :, 1:] |= out[:, :, :-1]
        grown[:, :, :-1] |= out[:, :, 1:]
        grown &= free
        if (grown == out).all():
            return np.asarray(free & ~out)
        out = grown


@dataclass
class MeshDistance:
    """A signed distance to a triangle mesh near its surface (see the module docstring): per connected piece the exact
    distance to its nearest triangle among those in the nearby grid cells, signed by that feature's pseudo-normal; the
    pieces combine as a union (min). Far from every piece it reads `far`: negative in cells deep inside a piece."""

    tri: Array  # (T, 3, 3)
    pseudo: Array  # (T, 7, 3) pseudo-normals per feature (see `_closest`)
    piece: Array  # (T,) connected piece of each triangle
    cell_tri: Array  # (K,) triangle index per (cell, triangle) entry, sorted by cell key, then piece
    keys: Array  # (K,) sorted cell keys
    lo: Array  # grid origin
    inside: Array  # (X, Y, Z) cells deep inside a piece (more than a cell from all its triangles)

    @classmethod
    def build(cls, vertices: Array, faces: Array, region: tuple[Array, Array] | None = None) -> MeshDistance:
        # CC0 meshes have seams (vertices repeated with other normals or UVs): weld by position for the topology
        _, weld = np.unique(np.round(vertices, 6), axis=0, return_inverse=True)
        welded = weld.ravel()[faces]
        tri = vertices[faces]
        pseudo = _pseudo_normals(tri, welded)
        piece = _pieces(welded, int(welded.max()) + 1) if len(faces) else np.zeros(0, np.int64)
        lo = tri.reshape(-1, 3).min(axis=0) - 2 * CELL if len(tri) else np.zeros(3)
        c0 = np.floor((tri.min(axis=1) - lo) / CELL).astype(np.int64) - 1
        c1 = np.floor((tri.max(axis=1) - lo) / CELL).astype(np.int64) + 1
        inside = np.zeros(tuple(c1.max(axis=0) + 2) if len(tri) else (1, 1, 1), bool)
        for k in range(int(piece.max()) + 1 if len(piece) else 0):  # each piece's cells cut off from outside it
            sel = piece == k
            b0, b1 = c0[sel].min(axis=0) - 1, c1[sel].max(axis=0) + 1
            filed = np.zeros(tuple(b1 - b0 + 1), bool)
            for a, b in zip((c0[sel] - b0).tolist(), (c1[sel] - b0).tolist(), strict=True):
                filed[a[0]:b[0] + 1, a[1]:b[1] + 1, a[2]:b[2] + 1] = True
            inside[b0[0]:b1[0] + 1, b0[1]:b1[1] + 1, b0[2]:b1[2] + 1] |= _enclosed(filed)
        if region is not None:  # only the triangles near the part being fitted
            lo_r, hi_r = region[0] - 2 * CELL, region[1] + 2 * CELL
            keep = (tri.max(axis=1) >= lo_r).all(axis=1) & (tri.min(axis=1) <= hi_r).all(axis=1)
            tri, pseudo, piece, c0, c1 = tri[keep], pseudo[keep], piece[keep], c0[keep], c1[keep]
        entries, owners = [], []
        # each triangle in every cell within one cell of it: a point then only reads its own cell
        span = c1 - c0 + 1
        for dx in range(int(span[:, 0].max()) if len(tri) else 0):
            for dy in range(int(span[:, 1].max())):
                for dz in range(int(span[:, 2].max())):
                    sel = (dx < span[:, 0]) & (dy < span[:, 1]) & (dz < span[:, 2])
                    c = c0[sel] + np.array([dx, dy, dz])
                    entries.append((c[:, 0] * 4096 + c[:, 1]) * 4096 + c[:, 2])
                    owners.append(np.flatnonzero(sel))
        keys = np.concatenate(entries) if entries else np.zeros(0, np.int64)
        owner = np.concatenate(owners) if owners else np.zeros(0, np.int64)
        order = np.lexsort((owner, piece[owner], keys))  # a point meets its cell's pieces one after another
        return cls(tri, pseudo, piece, owner[order], keys[order], lo, inside)

    def distance(self, p: Array) -> Array:
        far = CELL * 1.5
        out = np.full(len(p), np.inf)
        cell = np.floor((p - self.lo) / CELL).astype(np.int64)
        within = ((cell >= 0) & (cell < np.array(self.inside.shape))).all(axis=1)
        deep = np.zeros(len(p), bool)
        deep[within] = self.inside[tuple(cell[within].T)]
        if not len(self.tri):
            return np.where(deep, -far, far)
        keys = (cell[:, 0] * 4096 + cell[:, 1]) * 4096 + cell[:, 2]
        start = np.searchsorted(self.keys, keys, side="left")
        count = np.searchsorted(self.keys, keys, side="right") - start
        best = np.full(len(p), np.inf)  # nearest so far in the piece being read
        signed = np.zeros(len(p))
        current = np.full(len(p), -1)
        for k in range(int(count.max()) if len(count) else 0):
            idx = np.flatnonzero(count > k)
            t = self.cell_tri[start[idx] + k]
            done = (self.piece[t] != current[idx]) & np.isfinite(best[idx])  # a piece read: the union takes it
            i = idx[done]
            out[i] = np.minimum(out[i], signed[i])
            best[i] = np.inf
            current[idx] = self.piece[t]
            tri = self.tri[t]
            q, feature = _closest(p[idx], tri[:, 0], tri[:, 1], tri[:, 2])
            d = p[idx] - q
            dist = np.sqrt((d * d).sum(axis=1))
            better = dist < best[idx] - 1e-12
            if better.any():
                i = idx[better]
                best[i] = dist[better]
                side = (d[better] * self.pseudo[t[better], feature[better]]).sum(axis=1)
                signed[i] = np.where(side < 0, -dist[better], dist[better])
        last = np.isfinite(best)
        out[last] = np.minimum(out[last], signed[last])
        out = np.where(np.isfinite(out), out, far)
        return np.where(deep, np.minimum(out, -far), out)


__all__ = ["MeshDistance", "bone_matrix", "bones", "meshes", "read_surface"]
