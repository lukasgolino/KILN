"""Normal maps baked from the distance field (#111): detail without triangles.

The mesh gets unique UVs (xatlas, `pip install kiln-gen[bake]`), tangents (written into the glb, so the engine decodes
the map with exactly the basis it was baked with), and a tangent-space normal map: every texel's normal is the
field's gradient at the surface point under it (the mesh point moved onto the field's surface), so fine detail
the mesh is too coarse for, and `detail: true` parts that never reach the mesh, show in the lighting.

Conventions (glTF): UV origin top-left (v down), tangent along +u, bitangent = cross(normal, tangent) * w pointing
up the image (-v), the map's green channel up (OpenGL style, as Godot reads it).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from kiln.sdf import Array, Field

PADDING = 8  # texels between UV charts: mip levels up to 3 don't bleed between them
GROW = 8  # texels the baked colours are grown past chart borders (into that padding)
CHUNK = 200_000  # texels per field evaluation batch
FLAT = (128, 128, 255)  # a texel no chart covers: the mesh normal as it is


@dataclass
class Bake:
    uv: Array  # (F, 3, 2) per face corner, 0..1
    tangent: Array  # (F, 3, 4) per face corner: xyz along +u, w = handedness
    png: bytes  # the normal map (RGB)
    size: int  # the map is size x size texels, as asked for

    @property
    def width(self) -> int:
        return self.size

    @property
    def height(self) -> int:
        return self.size


def available() -> bool:
    try:
        import xatlas  # noqa: F401
    except ImportError:
        return False
    return True


PACK_TRIES = 8  # xatlas packs again with fewer texels per metre while the atlas overshoots the size asked for
SHRINK = 0.97  # ... aiming this far under the size: the packed size doesn't follow the texel density exactly


def unwrap(vertices: Array, faces: Array, size: int) -> Array:
    """Unique UVs (F, 3, 2) in a size x size map: charts cut and packed by xatlas into one atlas, PADDING texels
    apart, packed again with fewer texels per metre while it comes out bigger than the map (#151). The atlas sits in
    the map's corner, texel for texel, so the padding between charts stays whole and what is left over is empty."""
    import xatlas

    atlas = xatlas.Atlas()
    atlas.add_mesh(np.ascontiguousarray(vertices, dtype=np.float32), np.ascontiguousarray(faces, dtype=np.uint32))
    atlas.generate(pack_options=_pack(xatlas, size, 0.0))
    for _ in range(PACK_TRIES):
        if atlas.atlas_count == 1 and max(atlas.width, atlas.height) <= size:
            break
        tpu = float(atlas.texels_per_unit) * SHRINK * size / max(atlas.width, atlas.height, 1)
        atlas = xatlas.Atlas()
        atlas.add_mesh(np.ascontiguousarray(vertices, dtype=np.float32), np.ascontiguousarray(faces, dtype=np.uint32))
        atlas.generate(pack_options=_pack(xatlas, 0, tpu))
    if atlas.atlas_count != 1:
        raise ValueError(f"the mesh's UV charts didn't fit one {size} map; use a bigger normal_map")
    vmap, index, uvs = atlas[0]
    if not np.array_equal(vmap[index], faces):  # xatlas keeps the faces in order: corners map back one to one
        raise ValueError("xatlas reordered the faces; the normal map can't be matched to the mesh")
    uv = np.asarray(uvs, dtype=np.float64)[index]  # 0..1 across the atlas
    # an atlas still bigger than the map after every try is squeezed into it (the padding shrinks with it)
    return uv * np.minimum(np.array([atlas.width, atlas.height]) / size, 1.0)


def _pack(xatlas: Any, size: int, texels_per_unit: float) -> Any:
    pack = xatlas.PackOptions()
    pack.resolution = size
    pack.texels_per_unit = texels_per_unit
    pack.padding = PADDING
    pack.bilinear = True
    return pack


def tangents(vertices: Array, faces: Array, uv: Array, normals: Array) -> Array:
    """(F, 3, 4) per-corner tangents: dp/du accumulated over the faces around each (vertex, UV) pair, made square to
    the corner normal; w says whether cross(normal, tangent) runs up the image (+1) or down (-1)."""
    p = vertices[faces]
    e1, e2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    d1, d2 = uv[:, 1] - uv[:, 0], uv[:, 2] - uv[:, 0]
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(det) > 1e-20, 1.0 / np.where(np.abs(det) > 1e-20, det, 1.0), 0.0)
    t_face = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) * r[:, None]  # dp/du
    up_face = -(e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) * r[:, None]  # -dp/dv: up the image
    # corners sharing a vertex and its UV (one chart) share a tangent
    key = np.concatenate([faces.reshape(-1, 1).astype(np.float64), np.round(uv.reshape(-1, 2), 7)], axis=1)
    _, slot = np.unique(key, axis=0, return_inverse=True)
    slot = slot.reshape(-1)
    t_acc = np.zeros((slot.max() + 1, 3))
    u_acc = np.zeros_like(t_acc)
    np.add.at(t_acc, slot, np.repeat(t_face, 3, axis=0))
    np.add.at(u_acc, slot, np.repeat(up_face, 3, axis=0))
    n = normals.reshape(-1, 3)
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    t = t_acc[slot]
    t = t - n * (n * t).sum(axis=1, keepdims=True)
    length = np.linalg.norm(t, axis=1, keepdims=True)
    fallback = np.cross(n, np.where(np.abs(n[:, :1]) < 0.9, [[1.0, 0.0, 0.0]], [[0.0, 1.0, 0.0]]))  # no UV direction: any square one
    t = np.where(length > 1e-12, t / np.maximum(length, 1e-12), fallback / np.maximum(np.linalg.norm(fallback, axis=1, keepdims=True), 1e-12))
    w = np.where((np.cross(n, t) * u_acc[slot]).sum(axis=1) < 0, -1.0, 1.0)
    return np.concatenate([t, w[:, None]], axis=1).reshape(-1, 3, 4)


def _texels(uv: Array, width: int, height: int | None = None) -> tuple[Array, Array, Array]:
    """(face, texel index, barycentrics) for every texel centre inside a face, in UV space."""
    height = width if height is None else height
    dims = np.array([width, height])
    q = uv * dims - 0.5  # texel centres at integer coordinates
    lo = np.floor(q.min(axis=1)).astype(np.int64).clip(0, dims - 1)
    hi = np.ceil(q.max(axis=1)).astype(np.int64).clip(0, dims - 1)
    w, h = hi[:, 0] - lo[:, 0] + 1, hi[:, 1] - lo[:, 1] + 1
    faces_out, tex_out, bary_out = [], [], []
    count = w * h
    start = 0
    while start < len(uv):
        end = start + max(1, int(np.searchsorted(np.cumsum(count[start:]), CHUNK * 4)))
        f = np.repeat(np.arange(start, end), count[start:end])
        k = np.arange(len(f)) - np.repeat(np.cumsum(count[start:end]) - count[start:end], count[start:end])
        x = lo[f, 0] + k % w[f]
        y = lo[f, 1] + k // w[f]
        a, b, c = q[f, 0], q[f, 1], q[f, 2]
        v0, v1 = b - a, c - a
        pt = np.stack([x, y], axis=1) - a
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) > 1e-12
        den = np.where(ok, den, 1.0)
        l1 = (pt[:, 0] * v1[:, 1] - v1[:, 0] * pt[:, 1]) / den
        l2 = (v0[:, 0] * pt[:, 1] - pt[:, 0] * v0[:, 1]) / den
        l0 = 1.0 - l1 - l2
        inside = ok & (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        faces_out.append(f[inside])
        tex_out.append((y * width + x)[inside])
        bary_out.append(np.stack([l0, l1, l2], axis=1)[inside])
        start = end
    return np.concatenate(faces_out), np.concatenate(tex_out), np.concatenate(bary_out)


def _surface_point(field: Field, p: Array, step: float) -> tuple[Array, Array]:
    """(surface point, |distance| left) near each p: two Newton steps along the gradient, at most two cells each, each
    step's distance the mean of the gradient's six samples (one evaluation set per step)."""
    q = p.copy()
    eps = max(step * 0.05, 1e-4)
    offsets = np.eye(3) * eps
    for _ in range(2):
        stacked = np.concatenate([q + o for o in offsets] + [q - o for o in offsets])
        d = field.distance(stacked).reshape(6, len(q))
        g = (d[:3] - d[3:]).T
        g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-12)
        f = d.mean(axis=0)  # the distance at q, to O(eps^2)
        q = q - np.clip(f, -2 * step, 2 * step)[:, None] * g
    return q, np.abs(field.distance(q))


SUPERSAMPLE = ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25))  # texel offsets (tangent, bitangent) averaged


def bake(fields: list[Field], face_field: Array, vertices: Array, faces: Array, normals: Array, size: int, step: float,
         strength: float = 1.0) -> Bake:  # fmt: skip
    """Unwrap the mesh and bake into its tangent frames the normals of each face's own field (`face_field`: an index
    into `fields`, -1: the mesh normal as it is, e.g. exact hard parts). Each texel is filtered (#125): the normals
    at four points a quarter texel around its centre, averaged, each with a gradient step of half a texel, so detail
    finer than a texel blurs out instead of aliasing into streaks and speckles. `strength` scales the map's tilt
    away from the mesh normal (model normal_strength: 0.5 halves it)."""
    uv = unwrap(vertices, faces, size)
    width = height = size
    tan = tangents(vertices, faces, uv, normals)
    corners = vertices[faces]
    area = np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1)
    duv = uv * np.array([width, height])  # (F, 3, 2): per face corner
    e1, e2 = duv[:, 1] - duv[:, 0], duv[:, 2] - duv[:, 0]
    texels = np.abs(e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])  # twice the face's area in texels, as `area` is in m^2
    metres = np.minimum(np.sqrt(area / np.maximum(texels, 1e-12)), 4 * step)  # per face: metres per texel (slivers: capped)
    face, texel, bary = _texels(uv, width, height)
    # one texel, one face: the last face wins where charts' edges share texels (all faces are in order: stable)
    _, last = np.unique(texel[::-1], return_index=True)
    keep = len(texel) - 1 - last
    face, texel, bary = face[keep], texel[keep], bary[keep]
    out = np.zeros((width * height, 3), dtype=np.float32)
    out[:, 2] = 1.0
    owner = np.asarray(face_field)[face]
    for k, field in enumerate(fields):
        mine = np.flatnonzero(owner == k)
        for s in range(0, len(mine), CHUNK):
            rows = mine[s : s + CHUNK]
            f, b = face[rows], bary[rows]
            p = (vertices[faces[f]] * b[:, :, None]).sum(axis=1)
            n = (normals[f] * b[:, :, None]).sum(axis=1)
            t = (tan[f, :, :3] * b[:, :, None]).sum(axis=1)
            w = np.where((tan[f, :, 3] * b).sum(axis=1) < 0, -1.0, 1.0)
            n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            t = t - n * (n * t).sum(axis=1, keepdims=True)
            t = t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
            up = np.cross(n, t) * w[:, None]
            size_m = metres[f]
            centre, off = _surface_point(field, p, step)
            h = np.maximum(size_m * 0.5, 1e-4)[:, None]
            hi = np.zeros_like(p)
            for a, c in SUPERSAMPLE:  # around the surface point, in the mesh's tangent plane: a quarter texel is close enough
                q = centre + (t * a + up * c) * size_m[:, None]
                g = np.stack([field.distance(q + e * h) - field.distance(q - e * h) for e in np.eye(3)], axis=1)
                hi += g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-12)
            hi /= np.maximum(np.linalg.norm(hi, axis=1, keepdims=True), 1e-12)
            local = np.stack([(hi * t).sum(axis=1), (hi * up).sum(axis=1), (hi * n).sum(axis=1)], axis=1)
            local[:, :2] *= strength
            local[off > step] = (0.0, 0.0, 1.0)  # no surface near: the mesh normal
            local[:, 2] = np.maximum(local[:, 2], 0.05)  # never facing away from the surface
            local /= np.linalg.norm(local, axis=1, keepdims=True)
            out[texel[rows]] = local
    filled = np.zeros(width * height, dtype=bool)
    filled[texel] = True
    image = np.round((out * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8).reshape(height, width, 3)
    del out
    image = _grow(image, filled.reshape(height, width), GROW)
    buf = io.BytesIO()
    Image.fromarray(image, "RGB").save(buf, format="PNG", optimize=False)
    return Bake(uv, tan, buf.getvalue(), size)


def _grow(image: Array, filled: Array, steps: int) -> Array:
    """Spread chart colours `steps` texels past their borders (each empty texel: the mean of its filled neighbours,
    no wrapping round the map's edges); texels further out are flat."""
    img = image.astype(np.float32)
    done = filled.copy()
    h, w = done.shape
    for _ in range(steps):
        acc = np.zeros_like(img)
        cnt = np.zeros(done.shape, dtype=np.float32)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ys, yd = (slice(0, h - 1), slice(1, h)) if dy == 1 else (slice(1, h), slice(0, h - 1)) if dy == -1 else (slice(0, h), slice(0, h))
            xs, xd = (slice(0, w - 1), slice(1, w)) if dx == 1 else (slice(1, w), slice(0, w - 1)) if dx == -1 else (slice(0, w), slice(0, w))
            acc[yd, xd] += img[ys, xs] * done[ys, xs, None]
            cnt[yd, xd] += done[ys, xs]
        new = ~done & (cnt > 0)
        if not new.any():
            break
        img[new] = acc[new] / cnt[new][:, None]
        done |= new
    img[~done] = FLAT
    return np.round(img).astype(np.uint8)


def texel_size(extent: float, size: int) -> float:
    """Metres per texel, roughly: a model's surface spread over the map (charts fill about half of it)."""
    return extent * math.sqrt(2.0) / size


__all__ = ["FLAT", "PADDING", "Bake", "available", "bake", "tangents", "texel_size", "unwrap"]
