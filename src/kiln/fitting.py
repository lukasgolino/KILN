"""Attachments fitted to CC0 characters (`fit_to:`): a helmet, shield or banner made in KILN around a KayKit (or any
glTF) character's own mesh, exported in one of its bones' space so the game hangs it on that bone.

The target's surface becomes a distance field: its triangles are filed in a grid of cells, and a point's distance is
to the nearest triangle in the cells around it, signed by which side of that triangle it's on. Exact near the
surface, which is all a fitted shell needs; far away it only says "far, outside".
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


def _closest(p: Array, a: Array, b: Array, c: Array) -> Array:
    """Closest points on triangles (a, b, c) to points p, row by row (Ericson, Real-Time Collision Detection 5.1.5)."""
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
    with np.errstate(divide="ignore", invalid="ignore"):
        # edges (each where the face case doesn't apply)
        e_bc = (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0)
        t = np.where(e_bc, (d4 - d3) / ((d4 - d3) + (d5 - d6)), 0)
        out = np.where(e_bc[:, None], b + (c - b) * t[:, None], out)
        e_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
        t = np.where(e_ac, d2 / (d2 - d6), 0)
        out = np.where(e_ac[:, None], a + ac * t[:, None], out)
        e_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
        t = np.where(e_ab, d1 / (d1 - d3), 0)
        out = np.where(e_ab[:, None], a + ab * t[:, None], out)
    # vertices
    out = np.where(((d6 >= 0) & (d5 <= d6))[:, None], c, out)
    out = np.where(((d3 >= 0) & (d4 <= d3))[:, None], b, out)
    out = np.where(((d1 <= 0) & (d2 <= 0))[:, None], a, out)
    return np.asarray(out)


@dataclass
class MeshDistance:
    """A signed distance to a triangle mesh near its surface (see the module docstring): exact distance to the
    nearest triangle among those in the nearby grid cells, signed by that triangle's side."""

    tri: Array  # (T, 3, 3)
    normal: Array  # (T, 3)
    cell_tri: Array  # (K,) triangle index per (cell, triangle) entry, sorted by cell key
    keys: Array  # (K,) sorted cell keys
    lo: Array  # grid origin

    @classmethod
    def build(cls, vertices: Array, faces: Array, region: tuple[Array, Array] | None = None) -> MeshDistance:
        tri = vertices[faces]
        if region is not None:  # only the triangles near the part being fitted
            lo_r, hi_r = region[0] - 2 * CELL, region[1] + 2 * CELL
            keep = (tri.max(axis=1) >= lo_r).all(axis=1) & (tri.min(axis=1) <= hi_r).all(axis=1)
            tri = tri[keep]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-18)
        lo = tri.reshape(-1, 3).min(axis=0) - 2 * CELL if len(tri) else np.zeros(3)
        entries, owners = [], []
        # each triangle in every cell within one cell of it: a point then only reads its own cell
        c0 = np.floor((tri.min(axis=1) - lo) / CELL).astype(np.int64) - 1
        c1 = np.floor((tri.max(axis=1) - lo) / CELL).astype(np.int64) + 1
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
        order = np.argsort(keys, kind="stable")
        return cls(tri, n, owner[order], keys[order], lo)

    def distance(self, p: Array) -> Array:
        far = CELL * 1.5
        best = np.full(len(p), np.inf)
        signed = np.full(len(p), far)
        if not len(self.tri):
            return signed
        cell = np.floor((p - self.lo) / CELL).astype(np.int64)
        keys = (cell[:, 0] * 4096 + cell[:, 1]) * 4096 + cell[:, 2]
        start = np.searchsorted(self.keys, keys, side="left")
        count = np.searchsorted(self.keys, keys, side="right") - start
        for k in range(int(count.max()) if len(count) else 0):
            idx = np.flatnonzero(count > k)
            t = self.cell_tri[start[idx] + k]
            tri = self.tri[t]
            q = _closest(p[idx], tri[:, 0], tri[:, 1], tri[:, 2])
            d = p[idx] - q
            dist = np.sqrt((d * d).sum(axis=1))
            better = dist < best[idx] - 1e-12
            if better.any():
                i = idx[better]
                best[i] = dist[better]
                side = (d[better] * self.normal[t[better]]).sum(axis=1)
                signed[i] = np.where(side < 0, -dist[better], dist[better])
        return np.where(np.isfinite(best), signed, far)


__all__ = ["MeshDistance", "bone_matrix", "bones", "meshes", "read_surface"]
