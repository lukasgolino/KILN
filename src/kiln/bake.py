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
import zlib
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from typing import Any

import numpy as np
from PIL import Image

from kiln.sdf import Array, Field

PADDING = 8  # texels between UV charts: mip levels up to 3 don't bleed between them
GROW = 8  # texels the baked colours are grown past chart borders (into that padding)
CHUNK = 200_000  # texels per field evaluation batch
FLAT = (128, 128, 255)  # a texel no chart covers: the mesh normal as it is


@dataclass
class Layers:
    """What a base colour map on the bake's UVs is made of, per texel (size x size), so every variant's colours can
    be laid in without baking again: the paint group under the texel and the relief layer over it."""

    group: Array  # uint16: index into the painted groups; NO_GROUP where no chart covers the texel
    entry: Array  # int8: the relief entry of the patch on top, -1: bare surface
    along: Array  # uint8: 0 at that patch's root .. 255 at its tip
    shade: Array  # uint8: 255 x the colour multiplier (darker under tips)
    colors: list[tuple[str | None, str | None]]  # per relief entry: (root colour, tip colour) hex; None: the surface's own
    patches: list[int] = dataclass_field(default_factory=list)  # how many patches each relief entry has
    other: Array | None = None  # uint16: the paint group whose colour the texel fades toward (part color_blend); None: no fades
    mix: Array | None = None  # uint8: 255 x how much of that colour (0..0.5)

    def __getstate__(self) -> dict[str, Any]:  # in the mesh cache: mostly runs of one value, so packed (84 MB -> a few at 4096)
        state = dict(self.__dict__)
        for k in PACKED:
            a = state[k]
            if a is not None:
                state[k] = (a.shape, a.dtype.str, zlib.compress(np.ascontiguousarray(a).tobytes(), 1))
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        for k in PACKED:
            if state.get(k) is not None:
                shape, dtype, data = state[k]
                state[k] = np.frombuffer(zlib.decompress(data), dtype=dtype).reshape(shape).copy()
        self.__dict__.update(state)


NO_GROUP = 65535
PACKED = ("group", "entry", "along", "shade", "other", "mix")  # the per-texel arrays of Layers


@dataclass
class Bake:
    uv: Array  # (F, 3, 2) per face corner, 0..1
    tangent: Array  # (F, 3, 4) per face corner: xyz along +u, w = handedness
    png: bytes  # the normal map (RGB)
    size: int  # the map is size x size texels, as asked for
    fit: float = 1.0  # under 1: the charts didn't fit the map and were squeezed in by this much (lint W125)
    layers: Layers | None = None  # a model with relief: what its base colour map is made of (color_png)

    @property
    def width(self) -> int:
        return self.size

    @property
    def height(self) -> int:
        return self.size

    def color_png(self, group_colors: list[str], swap: dict[str, str] | None = None) -> bytes:
        """The base colour map (sRGB PNG) for the painted groups' colours (hex, in group order), `swap` applied to
        them and to the relief colours (a variant)."""
        from kiln import relief
        from kiln.export import srgb_to_linear

        assert self.layers is not None
        swap = swap or {}
        lay = self.layers
        filled = lay.group != NO_GROUP
        table = np.array([list(srgb_to_linear(swap.get(c, c))) for c in group_colors] or [[1.0, 1.0, 1.0]])
        own = np.minimum(lay.group[filled].astype(np.int64), len(table) - 1)
        stamped = relief.Stamp(np.zeros(0), lay.shade[filled] / 255.0, lay.entry[filled].astype(np.int64), lay.along[filled] / 255.0)
        colors = [(swap.get(a, a) if a else a, swap.get(b, b) if b else b) for a, b in lay.colors]
        linear = relief.colour(stamped, table[own], colors)
        if lay.other is not None and lay.mix is not None:  # colours fading across part borders: mixed in OKLab, fur and all
            w = lay.mix[filled] / 255.0
            fading = np.flatnonzero(w > 0)
            toward = np.minimum(lay.other[filled][fading].astype(np.int64), len(table) - 1)
            # toward what the neighbour looks like, fur and all: the mean colour of its group's texels (not its bare paint)
            count = np.maximum(np.bincount(own, minlength=len(table)), 1)[:, None]
            seen = np.stack([np.bincount(own, weights=linear[:, c], minlength=len(table)) for c in range(3)], axis=1) / count
            there = _oklab(seen)[toward]
            linear[fading] = _from_oklab(_oklab(linear[fading]) * (1 - w[fading, None]) + there * w[fading, None])
        srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.maximum(linear, 1e-12) ** (1 / 2.4) - 0.055)
        image = np.zeros((self.size, self.size, 3), dtype=np.uint8)
        image[filled] = np.round(srgb * 255).clip(0, 255).astype(np.uint8)
        image = _grow(image, filled, GROW, empty=(128, 128, 128))
        buf = io.BytesIO()
        Image.fromarray(image, "RGB").save(buf, format="PNG", optimize=False)
        return buf.getvalue()


def available() -> bool:
    try:
        import xatlas  # noqa: F401
    except ImportError:
        return False
    return True


PACK_TRIES = 8  # xatlas packs again with fewer texels per metre while the atlas overshoots the size asked for
STALLED = 2  # tries in a row that came out no smaller: the charts' padding alone is that big, lower density won't help
SHRINK = 0.97  # ... aiming this far under the size: the packed size doesn't follow the texel density exactly


def unwrap(vertices: Array, faces: Array, size: int) -> tuple[Array, float]:
    """Unique UVs (F, 3, 2) in a size x size map, and how the atlas fits it (1: it does). Charts are cut and packed by
    xatlas into one atlas, PADDING texels apart, packed again with fewer texels per metre while it comes out bigger
    than the map (#151). The atlas sits in the map's corner, texel for texel, so the padding between charts stays
    whole and what is left over is empty. Many small charts can't fit a small map at any density (their padding
    alone fills it): the tries stop when the atlas stops shrinking, and the smallest one is squeezed into the map
    (fit < 1: the padding and the detail shrink with it; lint W125)."""
    import xatlas

    def packed(resolution: int, texels_per_unit: float) -> Any:
        atlas = xatlas.Atlas()
        atlas.add_mesh(np.ascontiguousarray(vertices, dtype=np.float32), np.ascontiguousarray(faces, dtype=np.uint32))
        atlas.generate(pack_options=_pack(xatlas, resolution, texels_per_unit))
        return atlas

    def extent(atlas: Any) -> float:
        return float(max(atlas.width, atlas.height, 1)) if atlas.atlas_count == 1 else math.inf

    best = atlas = packed(size, 0.0)
    if extent(best) == math.inf:  # several atlases: start from one of any size
        best = atlas = packed(0, 0.0)
    density, misses = float(atlas.texels_per_unit), 0
    for _ in range(PACK_TRIES):
        if extent(best) <= size or misses == STALLED:
            break
        density *= SHRINK * min(1.0, size / extent(atlas))  # always down: the packed size is noisy in the density
        atlas = packed(0, density)
        if extent(atlas) < extent(best):
            best, misses = atlas, 0
        else:
            misses += 1
    if best.atlas_count != 1:
        raise ValueError(f"the mesh's UV charts didn't fit one {size} map; use a bigger normal_map")
    vmap, index, uvs = best[0]
    if not np.array_equal(vmap[index], faces):  # xatlas keeps the faces in order: corners map back one to one
        raise ValueError("xatlas reordered the faces; the normal map can't be matched to the mesh")
    uv = np.asarray(uvs, dtype=np.float64)[index]  # 0..1 across the atlas
    scale = np.minimum(np.array([best.width, best.height]) / size, 1.0)
    return uv * scale, min(1.0, size / extent(best))


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
         strength: float = 1.0, patches: Any = None, face_group: Array | None = None, face_on: Array | None = None,
         fade: Any = None) -> Bake:  # fmt: skip
    """Unwrap the mesh and bake into its tangent frames the normals of each face's own field (`face_field`: an index
    into `fields`, -1: the mesh normal as it is, e.g. exact hard parts). Each texel is filtered (#125): the normals
    at four points a quarter texel around its centre, averaged, each with a gradient step of half a texel, so detail
    finer than a texel blurs out instead of aliasing into streaks and speckles. `strength` scales the map's tilt
    away from the mesh normal (model normal_strength: 0.5 halves it). `patches` (kiln.relief.Patches, with each
    face's paint group in `face_group` and the faces each relief entry covers in `face_on` (entries, F)): a relief
    layer over the surface, tilting the map by the slope of its height (scaled by `strength` too) and kept per texel
    in `Bake.layers` for the base colour map. `fade` (kiln.fade.Fade): colours fading across part borders, kept in
    the layers too."""
    uv, fit = unwrap(vertices, faces, size)
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
    fades: list[tuple[Array, ...]] = []  # texels near a colour border: (texel, point, face, normal)
    reliefs: list[tuple[Array, ...]] = []  # texels a patch may touch: (texel, point, normal, tangent, up, metres per texel, face)
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
            if fade is not None:
                near = fade.touches(centre) & (off <= step)
                fades.append((texel[rows][near], centre[near], f[near], n[near]))
            if patches is not None and len(patches):
                near = patches.touches(centre) & (off <= step)
                reliefs.append((texel[rows][near], centre[near], n[near], t[near], up[near], size_m[near], f[near]))
    filled = np.zeros(width * height, dtype=bool)
    filled[texel] = True
    layers = None
    if (patches is not None or fade is not None) and face_group is not None:
        layers = _relief(patches, reliefs, out, face_group[face], texel, width * height, strength, face_on)
        if fade is not None:
            layers.other = np.zeros(width * height, dtype=np.uint16)
            layers.mix = np.zeros(width * height, dtype=np.uint8)
            if fades:
                tex, point, fface, fnormal = (np.concatenate([r[k] for r in fades]) for k in range(4))
                toward, weight = fade.mix(point, fface, fnormal)
                layers.other[tex] = toward.astype(np.uint16)
                layers.mix[tex] = np.round(weight * 255).astype(np.uint8)
        layers = replace(layers, **{k: getattr(layers, k).reshape(height, width) for k in PACKED if getattr(layers, k) is not None})
    image = np.round((out * 0.5 + 0.5) * 255).clip(0, 255).astype(np.uint8).reshape(height, width, 3)
    del out
    image = _grow(image, filled.reshape(height, width), GROW)
    buf = io.BytesIO()
    Image.fromarray(image, "RGB").save(buf, format="PNG", optimize=False)
    return Bake(uv, tan, buf.getvalue(), size, fit, layers)


def _relief(patches: Any, reliefs: list[tuple[Array, ...]], out: Array, group: Array, texel: Array, count: int, strength: float,
            face_on: Array | None) -> Layers:  # fmt: skip
    """Lay the relief over the baked normals `out` (tangent space, per texel, changed in place) and return what the
    colour map needs. The layer's height tilts each normal by its slope along the tangent and the bitangent (central
    differences between the points a texel either side), scaled by `strength` as the rest of the map is. An entry's
    patches touch only texels of the faces it covers (`face_on`)."""
    from kiln import relief

    colors = list(patches.colors) if patches is not None else []
    lay = Layers(np.full(count, NO_GROUP, dtype=np.uint16), np.full(count, -1, dtype=np.int8), np.zeros(count, dtype=np.uint8),
                 np.full(count, 255, dtype=np.uint8), colors,
                 [int((patches.entry == k).sum()) for k in range(len(colors))])  # fmt: skip
    lay.group[texel] = np.minimum(group, NO_GROUP - 1).astype(np.uint16)
    if patches is None or not reliefs or not len(patches):
        return lay
    tex, point, normal, tangent, up, metres, face = (np.concatenate([r[k] for r in reliefs]) for k in range(7))
    d = metres[:, None]
    allowed = face_on[:, face] if face_on is not None else None
    stamped, moved = relief.stamp(patches, point, normal, np.stack([tangent * d, -tangent * d, up * d, -up * d]), allowed)
    slope = np.stack([moved[0] - moved[1], moved[2] - moved[3]], axis=1) / (2 * d) * strength
    local = out[tex].astype(np.float64)
    local[:, :2] = local[:, :2] / np.maximum(local[:, 2:3], 0.05) - slope
    local[:, 2] = 1.0
    local /= np.linalg.norm(local, axis=1, keepdims=True)
    local[:, 2] = np.maximum(local[:, 2], 0.05)
    out[tex] = local / np.linalg.norm(local, axis=1, keepdims=True)
    lay.entry[tex] = stamped.entry.astype(np.int8)
    lay.along[tex] = np.round(stamped.along * 255).astype(np.uint8)
    lay.shade[tex] = np.round(stamped.shade * 255).astype(np.uint8)
    return lay


def _oklab(linear: Array) -> Array:
    """Linear RGB (N, 3) -> OKLab."""
    lms = np.cbrt(linear @ np.array([[0.4122214708, 0.2119034982, 0.0883024619], [0.5363325363, 0.6806995451, 0.2817188376],
                                     [0.0514459929, 0.1073969566, 0.6299787005]]))  # fmt: skip
    return np.asarray(lms @ np.array([[0.2104542553, 1.9779984951, 0.0259040371], [0.7936177850, -2.4285922050, 0.7827717662],
                                      [-0.0040720468, 0.4505937099, -0.8086757660]]))  # fmt: skip


def _from_oklab(lab: Array) -> Array:
    """OKLab (N, 3) -> linear RGB, clipped to the gamut."""
    lms = (lab @ np.array([[1.0, 1.0, 1.0], [0.3963377774, -0.1055613458, -0.0894841775], [0.2158037573, -0.0638541728, -1.2914855480]])) ** 3
    rgb = lms @ np.array([[4.0767416621, -1.2684380046, -0.0041960863], [-3.3077115913, 2.6097574011, -0.7034186147],
                          [0.2309699292, -0.3413193965, 1.7076147010]])  # fmt: skip
    return np.asarray(np.clip(rgb, 0.0, 1.0))


def _grow(image: Array, filled: Array, steps: int, empty: tuple[int, int, int] = FLAT) -> Array:
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
    img[~done] = empty
    return np.round(img).astype(np.uint8)


def texel_size(extent: float, size: int) -> float:
    """Metres per texel, roughly: a model's surface spread over the map (charts fill about half of it)."""
    return extent * math.sqrt(2.0) / size


__all__ = ["FLAT", "PADDING", "Bake", "available", "bake", "tangents", "texel_size", "unwrap"]
