"""Normal maps baked from the distance field (#111): detail without triangles.

The mesh gets unique UVs (xatlas, `pip install kiln[bake]`), tangents (written into the glb, so the engine decodes
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

import numpy as np
from PIL import Image

from kiln.sdf import Array, Field

PADDING = 4  # texels between UV charts (and how far the map is grown past their borders)
GROW = 8  # texels the baked colours are grown past chart borders (mip levels and filtering stay clean)
CHUNK = 200_000  # texels per field evaluation batch
FLAT = (128, 128, 255)  # a texel no chart covers: the mesh normal as it is


@dataclass
class Bake:
    uv: Array  # (F, 3, 2) per face corner, 0..1
    tangent: Array  # (F, 3, 4) per face corner: xyz along +u, w = handedness
    png: bytes  # the normal map (RGB)
    size: int


def available() -> bool:
    try:
        import xatlas  # noqa: F401
    except ImportError:
        return False
    return True


def unwrap(vertices: Array, faces: Array, size: int) -> Array:
    """Unique UVs (F, 3, 2): charts cut and packed by xatlas for a size x size map, PADDING texels apart."""
    import xatlas

    atlas = xatlas.Atlas()
    atlas.add_mesh(np.ascontiguousarray(vertices, dtype=np.float32), np.ascontiguousarray(faces, dtype=np.uint32))
    pack = xatlas.PackOptions()
    pack.resolution = size
    pack.padding = PADDING
    pack.bilinear = True
    atlas.generate(pack_options=pack)
    vmap, index, uvs = atlas[0]
    if not np.array_equal(vmap[index], faces):  # xatlas keeps the faces in order: corners map back one to one
        raise ValueError("xatlas reordered the faces; the normal map can't be matched to the mesh")
    return np.asarray(uvs, dtype=np.float64)[index]


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


def _texels(uv: Array, size: int) -> tuple[Array, Array, Array]:
    """(face, texel index, barycentrics) for every texel centre inside a face, in UV space."""
    q = uv * size - 0.5  # texel centres at integer coordinates
    lo = np.floor(q.min(axis=1)).astype(np.int64).clip(0, size - 1)
    hi = np.ceil(q.max(axis=1)).astype(np.int64).clip(0, size - 1)
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
        tex_out.append((y * size + x)[inside])
        bary_out.append(np.stack([l0, l1, l2], axis=1)[inside])
        start = end
    return np.concatenate(faces_out), np.concatenate(tex_out), np.concatenate(bary_out)


def bake(field: Field, vertices: Array, faces: Array, normals: Array, size: int, step: float) -> Bake:
    """Unwrap the mesh, and bake the field's normals into a size x size map in its tangent frames."""
    uv = unwrap(vertices, faces, size)
    tan = tangents(vertices, faces, uv, normals)
    face, texel, bary = _texels(uv, size)
    # one texel, one face: the last face wins where charts' edges share texels (all faces are in order: stable)
    _, last = np.unique(texel[::-1], return_index=True)
    keep = len(texel) - 1 - last
    face, texel, bary = face[keep], texel[keep], bary[keep]
    out = np.zeros((size * size, 3))
    for s in range(0, len(face), CHUNK):
        f, b = face[s : s + CHUNK], bary[s : s + CHUNK]
        p = (vertices[faces[f]] * b[:, :, None]).sum(axis=1)
        n = (normals[f] * b[:, :, None]).sum(axis=1)
        t = (tan[f, :, :3] * b[:, :, None]).sum(axis=1)
        w = np.where((tan[f, :, 3] * b).sum(axis=1) < 0, -1.0, 1.0)
        n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        t = t - n * (n * t).sum(axis=1, keepdims=True)
        t = t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
        up = np.cross(n, t) * w[:, None]
        # the surface point under the texel: the mesh point moved onto the field (not further than two cells)
        q = p.copy()
        for _ in range(3):
            d = field.distance(q)
            g = field.gradient(q, step * 0.1)
            q = q - np.clip(d, -2 * step, 2 * step)[:, None] * g
        hi = field.gradient(q, max(step * 0.05, 1e-4))
        far = np.abs(field.distance(q)) > step  # no surface near: the mesh normal
        local = np.stack([(hi * t).sum(axis=1), (hi * up).sum(axis=1), (hi * n).sum(axis=1)], axis=1)
        local[far] = (0.0, 0.0, 1.0)
        local[:, 2] = np.maximum(local[:, 2], 0.05)  # never facing away from the surface
        local /= np.linalg.norm(local, axis=1, keepdims=True)
        out[texel[s : s + CHUNK]] = local
    filled = np.zeros(size * size, dtype=bool)
    filled[texel] = True
    image = np.round((out * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8).reshape(size, size, 3)
    image = _grow(image, filled.reshape(size, size), GROW)
    buf = io.BytesIO()
    Image.fromarray(image, "RGB").save(buf, format="PNG", optimize=False)
    return Bake(uv, tan, buf.getvalue(), size)


def _grow(image: Array, filled: Array, steps: int) -> Array:
    """Spread chart colours `steps` texels past their borders (each empty texel: the mean of its filled neighbours);
    texels further out are flat."""
    img = image.astype(np.float64)
    done = filled.copy()
    for _ in range(steps):
        acc = np.zeros_like(img)
        cnt = np.zeros(done.shape)
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            shifted = np.roll(np.roll(done, dy, axis=0), dx, axis=1)
            acc += np.roll(np.roll(img * done[..., None], dy, axis=0), dx, axis=1)
            cnt += shifted
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
