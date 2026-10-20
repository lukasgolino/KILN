"""KILN spike v2 (throwaway): .kiln.yaml text -> smooth stylised glb.

Signed distance parts (blend/cut/intersect, mirror, array, rotation, noise) -> marching cubes -> decimate ->
project back onto the surface -> split triangles along part borders (clean colour seams) -> one material per
colour/preset -> glb. Style decides resolution, triangle budget and smooth vs flat normals.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import fast_simplification
import numpy as np
import trimesh
import yaml
from skimage.measure import marching_cubes

# --- primitives (Inigo Quilez's distance functions); points (N, 3), +Y up, front +Z ---------------


def sphere(p: np.ndarray, s: dict[str, Any]) -> np.ndarray:
    return np.linalg.norm(p, axis=1) - s["radius"]


def ellipsoid(p: np.ndarray, s: dict[str, Any]) -> np.ndarray:
    r = np.array(s["radii"], float)
    k0 = np.linalg.norm(p / r, axis=1)
    k1 = np.linalg.norm(p / (r * r), axis=1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def capsule(p: np.ndarray, s: dict[str, Any]) -> np.ndarray:
    a, b = np.array(s["from"], float), np.array(s["to"], float)
    pa, ba = p - a, b - a
    h = np.clip((pa @ ba) / (ba @ ba), 0, 1)
    r0 = s.get("radius", 0.1)
    r = r0 + (s.get("radius_to", r0) - r0) * h  # tapered capsules (limbs, horns)
    return np.linalg.norm(pa - h[:, None] * ba, axis=1) - r


def box(p: np.ndarray, s: dict[str, Any]) -> np.ndarray:
    r = s.get("round", 0.0)
    q = np.abs(p) - (np.array(s["size"], float) / 2 - r)
    return np.linalg.norm(np.maximum(q, 0), axis=1) + np.minimum(q.max(axis=1), 0) - r


def cylinder(p: np.ndarray, s: dict[str, Any]) -> np.ndarray:
    r = s.get("round", 0.0)
    d = np.stack([np.linalg.norm(p[:, [0, 2]], axis=1) - s["radius"] + r, np.abs(p[:, 1]) - s["height"] / 2 + r], axis=1)
    return np.minimum(d.max(axis=1), 0) + np.linalg.norm(np.maximum(d, 0), axis=1) - r


def cone(p: np.ndarray, s: dict[str, Any]) -> np.ndarray:  # capped cone along y, base radius r1 at -h/2, r2 at +h/2
    h, r1, r2 = s["height"] / 2, s["radius"], s.get("radius_top", 0.0)
    q = np.stack([np.linalg.norm(p[:, [0, 2]], axis=1), p[:, 1]], axis=1)
    k1, k2 = np.array([r2, h]), np.array([r2 - r1, 2 * h])
    ca = np.stack([q[:, 0] - np.minimum(q[:, 0], np.where(q[:, 1] < 0, r1, r2)), np.abs(q[:, 1]) - h], axis=1)
    t = np.clip(((k1 - q) @ k2) / (k2 @ k2), 0, 1)
    cb = q - k1 + t[:, None] * k2
    sign = np.where((cb[:, 0] < 0) & (ca[:, 1] < 0), -1.0, 1.0)
    return sign * np.sqrt(np.minimum((ca * ca).sum(1), (cb * cb).sum(1)))


def torus(p: np.ndarray, s: dict[str, Any]) -> np.ndarray:  # ring in the xz plane (rotate for others)
    return np.linalg.norm(np.stack([np.linalg.norm(p[:, [0, 2]], axis=1) - s["radius"], p[:, 1]], axis=1), axis=1) - s["thickness"]


SHAPES = {"sphere": sphere, "ellipsoid": ellipsoid, "capsule": capsule, "box": box, "cylinder": cylinder, "cone": cone, "torus": torus}


def rotation(deg: list[float]) -> np.ndarray:
    """Euler degrees [x, y, z], applied x then y then z."""
    x, y, z = np.radians(deg)
    rx = np.array([[1, 0, 0], [0, np.cos(x), -np.sin(x)], [0, np.sin(x), np.cos(x)]])
    ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    rz = np.array([[np.cos(z), -np.sin(z), 0], [np.sin(z), np.cos(z), 0], [0, 0, 1]])
    return rz @ ry @ rx


def noise(p: np.ndarray, scale: float, seed: int) -> np.ndarray:
    """Cheap deterministic 3D noise in about [-1, 1] (sum of rotated sine waves)."""
    rng = np.random.default_rng(seed)
    out = np.zeros(len(p))
    for octave in range(3):
        d = rng.normal(size=(3, 3))
        f = (2.0**octave) / scale
        out += np.sin((p @ d[0]) * f + rng.uniform(0, 6)) * np.sin((p @ d[1]) * f + rng.uniform(0, 6)) / (1.6**octave)
    return out / 1.6


class Part:
    def __init__(self, spec: dict[str, Any], palette: dict[str, str], materials: dict[str, dict[str, float]], index: int) -> None:
        self.kind = next(k for k in spec if k in SHAPES)
        self.shape = spec[self.kind]
        self.at = np.array(self.shape.get("at", [0, 0, 0]), float)
        self.inv = rotation(self.shape["rotate"]).T if "rotate" in self.shape else None
        self.mirror = spec.get("mirror") == "x"
        self.blend = float(spec.get("blend", 0.0))
        self.cut = bool(spec.get("cut", False))
        self.intersect = bool(spec.get("intersect", False))
        array = spec.get("array")
        self.copies = [np.zeros(3)] if not array else [np.array(array["step"], float) * i for i in range(array["count"])]
        self.noise = spec.get("noise")
        self.color = palette.get(spec.get("color", ""), spec.get("color", "#ff00ff"))
        self.material = spec.get("material", "default")
        self.index = index

    def distance(self, p: np.ndarray) -> np.ndarray:
        if self.mirror:
            p = p * np.where(p[:, :1] < 0, -1.0, 1.0) * np.array([1, 0, 0]) + p * np.array([0, 1, 1])  # fold x onto +x
        best = np.full(len(p), np.inf)
        for offset in self.copies:
            q = p - self.at - offset
            if self.inv is not None:
                q = q @ self.inv.T
            best = np.minimum(best, SHAPES[self.kind](q, self.shape))
        if self.noise:
            best = best + self.noise["amount"] * noise(p, self.noise.get("scale", 0.2), self.noise.get("seed", self.index))
        return best


def smin(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    if k <= 0:
        return np.minimum(a, b)
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


class Model:
    def __init__(self, data: dict[str, Any], palette: dict[str, str], materials: dict[str, dict[str, float]]) -> None:
        self.name = data["name"]
        self.cls = data.get("class", "prop")
        self.parts = [Part(s, palette, materials, i) for i, s in enumerate(data["parts"])]
        self.solid = [p for p in self.parts if not p.cut and not p.intersect]

    def field(self, p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(distance, per solid part distances (K, N))."""
        f = np.full(len(p), 1e9)
        parts = []
        for part in self.parts:
            d = part.distance(p)
            if part.cut:
                f = np.maximum(f, -d)
            elif part.intersect:
                f = np.maximum(f, d)
            else:
                f = smin(f, d, part.blend)
                parts.append(d)
        return f, np.array(parts)

    def bounds(self, step: float) -> tuple[np.ndarray, np.ndarray]:
        """Bounding box from sampling a coarse grid around the parts' anchors (spike shortcut)."""
        lo, hi = np.full(3, -3.0), np.full(3, 6.0)
        coarse = 0.08
        axes = [np.arange(lo[i], hi[i], coarse) for i in range(3)]
        grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
        f, _ = self.field(grid)
        inside = grid[f < coarse]
        return inside.min(0) - 2 * coarse, inside.max(0) + 2 * coarse


def grad(model: Model, v: np.ndarray, eps: float) -> np.ndarray:
    g = np.zeros_like(v)
    for i in range(3):
        e = np.zeros(3)
        e[i] = eps
        g[:, i] = model.field(v + e)[0] - model.field(v - e)[0]
    n = np.linalg.norm(g, axis=1, keepdims=True)
    return g / np.maximum(n, 1e-12)


def split_by_owner(v: np.ndarray, f: np.ndarray, dists: np.ndarray) -> tuple[np.ndarray, list[tuple[int, np.ndarray]]]:
    """Cut triangles along the border between two parts (where their distances are equal), so every colour
    border is a clean line on the surface. Returns (vertices, [(owner, faces)])."""
    owner = dists.argmin(axis=0)
    verts = list(v)
    edge_cache: dict[tuple[int, int, int, int], int] = {}

    def cut(i: int, j: int, a: int, b: int) -> int:
        key = (min(i, j), max(i, j), min(a, b), max(a, b))
        if key not in edge_cache:
            gi, gj = dists[a, i] - dists[b, i], dists[a, j] - dists[b, j]
            t = gi / (gi - gj) if gi != gj else 0.5
            verts.append(v[i] + (v[j] - v[i]) * np.clip(t, 0, 1))
            edge_cache[key] = len(verts) - 1
        return edge_cache[key]

    out: dict[int, list[list[int]]] = {}
    for tri in f:
        o = owner[tri]
        if o[0] == o[1] == o[2]:
            out.setdefault(int(o[0]), []).append(list(tri))
            continue
        kinds = sorted(set(o.tolist()))
        if len(kinds) > 2:  # three parts meet in one triangle: majority (rare, tiny)
            vals, counts = np.unique(o, return_counts=True)
            out.setdefault(int(vals[counts.argmax()]), []).append(list(tri))
            continue
        a, b = kinds
        # rotate so the lone vertex comes first
        lone = next(k for k in range(3) if (o == o[k]).sum() == 1)
        t = [tri[(lone + k) % 3] for k in range(3)]
        side_lone, side_pair = int(o[(lone) % 3]), int(o[(lone + 1) % 3])
        m1, m2 = cut(t[0], t[1], a, b), cut(t[0], t[2], a, b)
        out.setdefault(side_lone, []).append([t[0], m1, m2])
        out.setdefault(side_pair, []).append([m1, t[1], t[2]])
        out.setdefault(side_pair, []).append([m1, t[2], m2])
    return np.array(verts), [(k, np.array(fs)) for k, fs in sorted(out.items())]


def build(model: Model, style: dict[str, Any]) -> trimesh.Scene:
    lo, hi = model.bounds(0.05)
    size = float((hi - lo).max())
    step = max(style["resolution"] * max(size, 1.0), size / 220)
    axes = [np.arange(lo[i], hi[i] + step, step) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    field = model.field(grid)[0].reshape([len(a) for a in axes])
    v, f, _, _ = marching_cubes(field, 0.0, spacing=(step, step, step))
    v += lo
    budget = style["budgets"].get(model.cls, 5000)
    if len(f) > budget:
        v, f = fast_simplification.simplify(v, f, target_reduction=1 - budget / len(f))
    for _ in range(2):  # pull decimated vertices back onto the true surface
        d = model.field(v)[0]
        v = v - d[:, None] * grad(model, v, step * 0.25)
    dists = model.field(v)[1]
    v, groups = split_by_owner(v, f, dists)
    normals = grad(model, v, step * 0.25)
    scene = trimesh.Scene()
    by_material: dict[tuple[str, str], list[np.ndarray]] = {}
    for owner, faces in groups:
        part = model.solid[owner]
        by_material.setdefault((part.color, part.material), []).append(faces)
    for (color, mat), chunks in sorted(by_material.items()):
        faces = np.concatenate(chunks)
        used = np.unique(faces)
        remap = np.full(len(v), -1)
        remap[used] = np.arange(len(used))
        preset = style["materials"].get(mat, {})
        srgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        rgb = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]  # glTF factors are linear
        material = trimesh.visual.material.PBRMaterial(
            name=f"{mat}_{color[1:]}", baseColorFactor=[*rgb, 1.0], roughnessFactor=preset.get("roughness", 0.5),
            metallicFactor=preset.get("metallic", 0.0), emissiveFactor=[c * preset.get("emission", 0.0) for c in rgb],
        )
        if style["smooth"]:
            mesh = trimesh.Trimesh(v[used], remap[faces], vertex_normals=normals[used], process=False)
        else:  # faceted: every triangle its own vertices, flat normals
            tri = v[faces].reshape(-1, 3)
            mesh = trimesh.Trimesh(tri, np.arange(len(tri)).reshape(-1, 3), process=False)
            mesh.vertex_normals = np.repeat(mesh.face_normals, 3, axis=0)
        mesh.visual = trimesh.visual.TextureVisuals(material=material)
        scene.add_geometry(mesh, geom_name=f"{model.name}_{mat}_{color[1:]}")
    return scene


if __name__ == "__main__":
    source, style_file, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    style = yaml.safe_load(style_file.read_text())
    doc = yaml.safe_load(source.read_text())
    palette = doc["palette"]
    out.mkdir(parents=True, exist_ok=True)
    for data in doc["models"]:
        if len(sys.argv) > 4 and data["name"] not in sys.argv[4:]:
            continue
        model = Model(data, palette, style["materials"])
        scene = build(model, style)
        scene.export(out / f"{model.name}.glb")
        tris = sum(len(g.faces) for g in scene.geometry.values())
        print(f"{model.name}: {tris} triangles, {len(scene.geometry)} materials")
