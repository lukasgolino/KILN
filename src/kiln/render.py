"""A small software renderer for previews: no engine, no GPU, no display.

Orthographic camera at any heading and elevation, per-pixel normals, the style's sun and sky light, soft
specular, glow, decals, toon bands and outlines, a filmic tone curve and saturation: close enough to the Godot
look kit for an agent (or a person) to judge shapes, proportions, colours and poses. `kiln preview --engine`
renders through Godot itself when exact lighting matters.

Rasterising is vectorised: every triangle's covered pixels are generated at once and the nearest one per
pixel wins (a z-buffer by sorting).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

from kiln.export import Built, srgb_to_linear
from kiln.paint import decal_uv
from kiln.rig import skin_matrices
from kiln.sdf import Array, rotation_matrix
from kiln.style import TOON_DARKEN, Look

SUPERSAMPLE = 2
BAYER = (np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) + 0.5) / 16  # ordered-dither thresholds


@dataclass(frozen=True)
class View:
    yaw: float = 30.0  # degrees: 0 = looking at the model's front (+Z), 90 = from its left (+X)
    pitch: float = 20.0  # degrees above the horizon (negative = from below)


def camera_basis(view: View) -> tuple[Array, Array, Array]:
    """(right, up, forward-into-screen) world vectors."""
    yaw, pitch = math.radians(view.yaw), math.radians(view.pitch)
    eye_dir = np.array([math.sin(yaw) * math.cos(pitch), math.sin(pitch), math.cos(yaw) * math.cos(pitch)])  # towards the camera
    forward = -eye_dir
    world_up = np.array([0.0, 1.0, 0.0]) if abs(view.pitch) < 89.0 else np.array([0.0, 0.0, -1.0 if view.pitch > 0 else 1.0])
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    return right, up, forward


def posed(built: Built, track: int | None, frame: int) -> tuple[Array, Array]:
    """(vertices per face corner (F, 3, 3), normals per corner (F, 3, 3)) at an animation frame (or at rest)."""
    p = built.painted
    corners = p.vertices[p.faces]
    normals = built.normals
    if track is None or not built.tracks:
        return corners, normals
    t = built.tracks[track]
    f = frame % t.frames
    mats = skin_matrices(built.skeleton, t.translation[f], t.rotation[f], t.scale[f])
    sk = built.skeleton
    if built.skin == "soft" and built.joints is not None and built.weights is not None:
        bone_of_face = np.array([sk.index(p.groups[g].bone) for g in p.face_group])
        separate = np.array([sk.bones[i].separate for i in range(len(sk.bones))])
        j, w = built.joints, built.weights
        m = (mats[j] * w[:, :, None, None]).sum(axis=1)  # (V, 4, 4)
        m_corner = m[p.faces]  # (F, 3, 4, 4)
        rigid = separate[bone_of_face]
        if rigid.any():
            m_corner[rigid] = mats[bone_of_face[rigid]][:, None]
    else:
        bone_of_face = np.array([sk.index(p.groups[g].bone) for g in p.face_group])
        m_corner = np.repeat(mats[bone_of_face][:, None], 3, axis=1)
    homo = np.concatenate([corners, np.ones(corners.shape[:2] + (1,))], axis=2)
    out = np.einsum("fcij,fcj->fci", m_corner, homo)[:, :, :3]
    rot = m_corner[:, :, :3, :3]
    nrm = np.einsum("fcij,fcj->fci", rot, normals)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=2, keepdims=True), 1e-12)
    return out, nrm


def _filmic(x: Array) -> Array:
    """A gentle filmic curve (Hable's, white point 6), close to Godot's Filmic tonemapper."""
    a, b, c, d, e, f = 0.22, 0.30, 0.10, 0.20, 0.01, 0.30

    def curve(v: Array) -> Array:
        return ((v * (a * v + c * b) + d * e) / (v * (a * v + b) + d * f)) - e / f

    white = 6.0
    return curve(x * 2.0) / curve(np.array(white))


def _to_srgb(x: Array) -> Array:
    x = np.clip(x, 0.0, 1.0)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


def with_unrevealed(built: Built, hide: frozenset[str] = frozenset()) -> frozenset[str]:
    """`hide` plus every `revealed` part none of whose revealers is in it: they start hidden in the game."""
    waiting = {pid for pid, entry in built.model.rig.items() if entry.revealed and not set(entry.revealed) & hide}
    return hide | waiting


def render(
    built: Built,
    view: View,
    size: int = 384,
    track: int | None = None,
    frame: int = 0,
    swap: dict[str, str] | None = None,
    fit: tuple[Array, float] | None = None,
    background: tuple[int, int, int, int] = (0, 0, 0, 0),
    hide: frozenset[str] = frozenset(),
    fade: Array | None = None,
    colors: Array | None = None,
) -> Image.Image:
    """One view. `fit` = (centre, half-extent in metres) to frame several renders the same way; default: the
    model's own bounding sphere. `hide`: bones (part ids) left out, e.g. a detached helmet. `revealed` parts (stump caps)
    are left out too, as in the exported scenes, unless a part that reveals them is hidden. `fade`: an opacity per face
    (0..1), drawn as ordered (Bayer 4x4) dithering at the output's pixel scale: what's behind shows through the holes,
    and outlines leave them alone. `colors`: a linear albedo per face corner (F, 3, 3) instead of the paint groups'
    colours (terrains: blended splat layers)."""
    hide = with_unrevealed(built, hide)
    look: Look = built.style.look
    swap = swap or {}
    corners, normals = posed(built, track, frame)
    if fit is None:
        lo, hi = corners.reshape(-1, 3).min(axis=0), corners.reshape(-1, 3).max(axis=0)
        centre = (lo + hi) / 2
        half = float(np.linalg.norm(hi - lo)) / 2 * 1.08
    else:
        centre, half = fit
    res = size * SUPERSAMPLE
    scale = res / (2 * half)
    right, up, forward = camera_basis(view)
    rel = corners - centre
    sx = (rel @ right) * scale + res / 2
    sy = res / 2 - (rel @ up) * scale
    sz = rel @ forward  # depth: larger = further
    # back-face culling (meshes are closed)
    area = (sx[:, 1] - sx[:, 0]) * (sy[:, 2] - sy[:, 0]) - (sx[:, 2] - sx[:, 0]) * (sy[:, 1] - sy[:, 0])
    front = area < 0
    if hide:
        front &= ~np.array([built.painted.groups[g].bone in hide for g in built.painted.face_group], dtype=bool)
    tri = np.flatnonzero(front)
    x0 = np.floor(sx[tri].min(axis=1)).astype(int).clip(0, res - 1)
    x1 = np.ceil(sx[tri].max(axis=1)).astype(int).clip(0, res - 1)
    y0 = np.floor(sy[tri].min(axis=1)).astype(int).clip(0, res - 1)
    y1 = np.ceil(sy[tri].max(axis=1)).astype(int).clip(0, res - 1)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    counts = w * h
    best_depth = np.full(res * res, np.inf)
    best_tri = np.full(res * res, -1)
    best_bary = np.zeros((res * res, 3))
    dropped = np.full(res * res, np.inf)  # nearest depth per pixel at which a faded face was dithered away
    chunk = 4_000_000
    start = 0
    while start < len(tri):
        cum = np.cumsum(counts[start:])
        end = start + max(1, int(np.searchsorted(cum, chunk)))
        sel = np.arange(start, min(end, len(tri)))
        start = sel[-1] + 1
        reps = counts[sel]
        t_idx = np.repeat(sel, reps)
        offsets = np.arange(int(reps.sum())) - np.repeat(np.cumsum(reps) - reps, reps)
        px = x0[t_idx] + offsets % w[t_idx]
        py = y0[t_idx] + offsets // w[t_idx]
        T = tri[t_idx]
        cx, cy = px + 0.5, py + 0.5
        ax, ay, bx, by, qx, qy = sx[T, 0], sy[T, 0], sx[T, 1], sy[T, 1], sx[T, 2], sy[T, 2]
        denom = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
        denom = np.where(np.abs(denom) < 1e-12, 1e-12, denom)
        l0 = ((by - qy) * (cx - qx) + (qx - bx) * (cy - qy)) / denom
        l1 = ((qy - ay) * (cx - qx) + (ax - qx) * (cy - qy)) / denom
        l2 = 1 - l0 - l1
        inside = (l0 >= -1e-6) & (l1 >= -1e-6) & (l2 >= -1e-6)
        px, py, T, l0, l1, l2 = px[inside], py[inside], T[inside], l0[inside], l1[inside], l2[inside]
        depth = l0 * sz[T, 0] + l1 * sz[T, 1] + l2 * sz[T, 2]
        if fade is not None:
            keep = BAYER[(py // SUPERSAMPLE) % 4, (px // SUPERSAMPLE) % 4] < fade[T]
            np.minimum.at(dropped, py[~keep] * res + px[~keep], depth[~keep])
            px, py, T, l0, l1, l2, depth = px[keep], py[keep], T[keep], l0[keep], l1[keep], l2[keep], depth[keep]
        if not len(px):  # nothing in this chunk covers a pixel centre (all off screen in a close framing)
            continue
        pix = py * res + px
        order = np.lexsort((depth, pix))
        pix, depth = pix[order], depth[order]
        first = np.concatenate([[True], pix[1:] != pix[:-1]])
        pix, depth = pix[first], depth[first]
        T, bary = T[order][first], np.stack([l0, l1, l2], axis=1)[order][first]
        better = depth < best_depth[pix]
        pix = pix[better]
        best_depth[pix] = depth[better]
        best_tri[pix] = T[better]
        best_bary[pix] = bary[better]
    hit = best_tri >= 0
    rgba = np.zeros((res * res, 4))
    rgba[:] = np.array(background) / 255.0
    glow = np.zeros((res * res, 3))  # emissive light (linear) that the look's glow spreads (bloom)
    if hit.any():
        T = best_tri[hit]
        bary = best_bary[hit]
        n = (normals[T] * bary[:, :, None]).sum(axis=1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        p = built.painted
        groups = p.groups
        g = p.face_group[T]
        albedo_table = np.array([srgb_to_linear(swap.get(gr.color, gr.color)) for gr in groups])
        albedo = albedo_table[g] if colors is None else (colors[T] * bary[:, :, None]).sum(axis=1)
        dec = p.face_decal[T]
        if (dec >= 0).any():
            world = (corners[T] * bary[:, :, None]).sum(axis=1)
            rest = (p.vertices[p.faces[T]] * bary[:, :, None]).sum(axis=1)
            del world
            for k, d in enumerate(p.decals):
                m = dec == k
                if not m.any():
                    continue
                img = np.asarray(Image.open(d.image).convert("RGBA"), dtype=float) / 255.0
                uv = decal_uv(d, rest[m]).clip(0, 0.999999)
                tx = (uv[:, 0] * img.shape[1]).astype(int)
                ty = (uv[:, 1] * img.shape[0]).astype(int)
                texel = img[ty, tx]
                lin = np.array([[c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in row] for row in texel[:, :3]])
                albedo[m] = albedo[m] * (1 - texel[:, 3:4]) + lin * texel[:, 3:4]
        presets = [built.style.materials.get(gr.material, built.style.materials["default"]) for gr in groups]
        rough = np.array([pr.roughness for pr in presets])[g]
        metal = np.array([pr.metallic for pr in presets])[g]
        emit = np.array([pr.emission for pr in presets])[g]
        rim = np.array([pr.rim for pr in presets])[g]
        sun = rotation_matrix((look.sun_pitch, look.sun_yaw, 0.0)) @ np.array([0.0, 0.0, -1.0])  # light travel direction
        to_light = -sun / np.linalg.norm(sun)
        ndl = n @ to_light
        sun_col = np.array(srgb_to_linear(look.sun_color)) * look.sun_energy
        sky_top, sky_hor, ground = (np.array(srgb_to_linear(c)) for c in (look.sky_top, look.sky_horizon, look.ground))
        up_amount = n[:, 1:2]
        sky = np.where(up_amount >= 0, sky_hor + (sky_top - sky_hor) * up_amount, sky_hor + (ground - sky_hor) * (-up_amount))
        ambient = sky * look.ambient * 0.55
        if look.shader == "toon":
            bands = max(2, look.toon_bands)
            lit = toon_lit(ndl, bands, look.toon_softness)
            diffuse = albedo * (ambient + sun_col * lit[:, None] * 0.9)
            if look.toon_shadow_color:  # the sun's missing light, in the shadow colour (no cast shadows here)
                diffuse = diffuse + albedo * np.array(srgb_to_linear(look.toon_shadow_color)) * (1 - lit)[:, None]
            if look.toon_specular > 0:
                half_v = to_light - forward
                half_v /= np.linalg.norm(half_v)
                blob = ((n @ half_v) >= 1 - 0.08 * rough**2) & (ndl >= 0)
                strength = look.toon_specular * (1 - rough) * blob
                diffuse = diffuse + sun_col * strength[:, None] * np.minimum(albedo / 0.05, 1.0)  # Godot: / max(albedo, 0.05) * albedo
            color = diffuse
        else:
            diffuse = albedo * (1 - metal[:, None] * 0.6) * (ambient + sun_col * np.clip(ndl, 0, None)[:, None])
            view_dir = -forward
            half_v = to_light + view_dir
            half_v /= np.linalg.norm(half_v)
            shin = 2.0 / np.maximum(rough**4, 1e-3)
            spec_strength = (1 - rough) ** 2 * 0.6
            spec = spec_strength * np.power(np.clip(n @ half_v, 0, 1), np.minimum(shin, 2000)) * (ndl > 0)
            spec_col = np.where(metal[:, None] > 0.5, albedo, 1.0)
            rim_term = rim[:, None] * np.power(1 - np.clip(n @ view_dir, 0, 1), 3)[:, None] * sky
            color = diffuse + spec[:, None] * spec_col * sun_col + rim_term
        color = color + albedo * emit[:, None]
        if look.rim_light > 0:  # the style's added fresnel rim (Godot: a next pass on every material)
            fres = np.power(1 - np.clip(n @ -forward, 0, 1), look.rim_light_power)
            color = color + np.array(srgb_to_linear(look.rim_light_color)) * (look.rim_light * fres)[:, None]
        if look.glow and (emit > 0).any():
            glow[hit] = albedo * emit[:, None] * look.exposure
        color = color * look.exposure
        color = _filmic(color) if look.tonemapper != "linear" else color
        lum = (color * np.array([0.2126, 0.7152, 0.0722])).sum(axis=1, keepdims=True)
        color = lum + (color - lum) * look.saturation
        color = (color - 0.18) * look.contrast + 0.18
        rgba[hit, :3] = _to_srgb(color)
        rgba[hit, 3] = 1.0
    image = rgba.reshape(res, res, 4)
    if look.outline > 0:
        width = look.outline * SUPERSAMPLE / 2 if look.outline_space == "pixels" else look.outline * scale  # edges mark both sides
        edge_colors: Array | None = None
        if look.outline_color == "darken":  # each part's own colour, darkened (linear, as the Godot outline shader)
            dark = np.zeros((res * res, 3))
            if hit.any():
                dark[hit] = albedo_table[built.painted.face_group[best_tri[hit]]] * TOON_DARKEN
            edge_colors = _to_srgb(dark).reshape(res, res, 3)
        image = _outline(image, best_depth.reshape(res, res), max(1, int(round(width))), look.outline_color, (dropped < best_depth).reshape(res, res), edge_colors)
    if glow.any():
        image = _bloom(image, glow.reshape(res, res, 3), max(1, int(res * 0.025)))
    out = Image.fromarray((image * 255 + 0.5).astype(np.uint8), "RGBA")
    return out.resize((size, size), Image.Resampling.BOX)


def toon_lit(ndl: Array, bands: int, softness: float = 0.0) -> Array:
    """The toon shader's light amount (0..1) from n.l: `bands` hard steps, or with `softness` each step blended over
    that fraction of a band around its edge (the Godot shader's maths)."""
    n = np.clip((ndl + 0.15) / 1.15, 0, 0.999)
    if softness <= 0:
        return np.floor(n * bands) / (bands - 1)
    x = n * bands
    edge = np.floor(x + 0.5)
    t = np.clip((x - edge + 0.5 * softness) / softness, 0.0, 1.0)
    return np.clip(edge - 1 + t * t * (3 - 2 * t), 0, bands - 1) / (bands - 1)


def _blur(x: Array, radius: int) -> Array:
    """Three box blurs along each image axis (close to a gaussian of sigma ~ radius)."""
    for axis in (0, 1):
        for _ in range(3):
            pad = [(0, 0)] * x.ndim
            pad[axis] = (radius + 1, radius)
            c = np.cumsum(np.pad(x, pad), axis=axis)
            hi = np.take(c, np.arange(2 * radius + 1, c.shape[axis]), axis=axis)
            lo = np.take(c, np.arange(0, c.shape[axis] - 2 * radius - 1), axis=axis)
            x = (hi - lo) / (2 * radius + 1)
    return x


def _bloom(image: Array, glow: Array, radius: int) -> Array:
    """Emissive light spread over its surroundings (Godot's glow, roughly), also onto a transparent background."""
    halo = _blur(glow, radius) * 0.8 + _blur(glow, radius * 3) * 0.6
    srgb = image[..., :3]
    lin = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    alpha = image[..., 3:4]
    premult = lin * alpha + halo
    out_alpha = np.clip(alpha + (halo * np.array([0.2126, 0.7152, 0.0722])).sum(axis=-1, keepdims=True) * 2, 0, 1)
    out = image.copy()
    out[..., :3] = _to_srgb(premult / np.maximum(out_alpha, 1e-6))
    out[..., 3:4] = out_alpha
    return out


def _outline(image: Array, depth: Array, width: int, hex_color: str, dropped: Array | None = None, colors: Array | None = None) -> Array:
    """Silhouette and depth-step edges, `width` pixels. None at or next to `dropped` pixels (dither holes): a faded
    piece would otherwise be outlined around every hole. `colors` (sRGB per pixel): outline colours instead of
    `hex_color`, each outline pixel taking the nearest surface's within `width` (as an inverted hull in front)."""
    solid = np.isfinite(depth)
    d = np.where(solid, depth, 1e9)
    edge = np.zeros_like(solid)
    span = float(np.ptp(d[solid])) if solid.any() else 1.0
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        shifted = np.roll(np.roll(d, dy, axis=0), dx, axis=1)
        edge |= np.abs(shifted - d) > max(span * 0.04, 1e-6)
    edge &= solid | np.roll(solid, 1, axis=0) | np.roll(solid, -1, axis=0) | np.roll(solid, 1, axis=1) | np.roll(solid, -1, axis=1)
    holes = dropped if dropped is not None else np.zeros_like(solid)
    edge &= ~(holes | np.roll(holes, 1, 0) | np.roll(holes, -1, 0) | np.roll(holes, 1, 1) | np.roll(holes, -1, 1))
    grown = edge.copy()
    for _ in range(width - 1):
        grown = grown | np.roll(grown, 1, 0) | np.roll(grown, -1, 0) | np.roll(grown, 1, 1) | np.roll(grown, -1, 1)
    grown &= ~holes
    out = image.copy()
    if colors is not None:
        near, col_map = d.copy(), colors.copy()
        for _ in range(width):
            for axis, step in ((0, 1), (0, -1), (1, 1), (1, -1)):
                nd, nc = np.roll(near, step, axis), np.roll(col_map, step, axis)
                closer = nd < near
                near, col_map = np.where(closer, nd, near), np.where(closer[..., None], nc, col_map)
        out[grown, :3] = col_map[grown]
    else:
        out[grown, :3] = np.array([int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)])
    out[grown, 3] = 1.0
    return out


def silhouette(corners: Array, view: View, size: int, fit: tuple[Array, float]) -> Array:
    """Binary coverage mask (size, size) of triangles (F, 3, 3) under the same camera and framing as `render`,
    sampled at pixel centres, both windings (no culling: a reference's winding may be inconsistent)."""
    centre, half = fit
    scale = size / (2 * half)
    right, up, _ = camera_basis(view)
    rel = corners - centre
    sx = (rel @ right) * scale + size / 2
    sy = size / 2 - (rel @ up) * scale
    x0 = np.ceil(sx.min(axis=1) - 0.5).astype(int).clip(0, size)
    x1 = np.floor(sx.max(axis=1) - 0.5).astype(int).clip(-1, size - 1)
    y0 = np.ceil(sy.min(axis=1) - 0.5).astype(int).clip(0, size)
    y1 = np.floor(sy.max(axis=1) - 0.5).astype(int).clip(-1, size - 1)
    w, h = np.maximum(x1 - x0 + 1, 0), np.maximum(y1 - y0 + 1, 0)
    counts = w * h
    tri = np.flatnonzero(counts > 0)
    mask = np.zeros(size * size, dtype=bool)
    start = 0
    while start < len(tri):
        cum = np.cumsum(counts[tri[start:]])
        sel = tri[start : start + max(1, int(np.searchsorted(cum, 4_000_000)))]
        start += len(sel)
        reps = counts[sel]
        t = np.repeat(sel, reps)
        offsets = np.arange(int(reps.sum())) - np.repeat(np.cumsum(reps) - reps, reps)
        px = x0[t] + offsets % w[t]
        py = y0[t] + offsets // w[t]
        cx, cy = px + 0.5, py + 0.5
        ax, ay, bx, by, qx, qy = sx[t, 0], sy[t, 0], sx[t, 1], sy[t, 1], sx[t, 2], sy[t, 2]
        denom = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
        ok = np.abs(denom) > 1e-12
        denom = np.where(ok, denom, 1.0)
        l0 = ((by - qy) * (cx - qx) + (qx - bx) * (cy - qy)) / denom
        l1 = ((qy - ay) * (cx - qx) + (ax - qx) * (cy - qy)) / denom
        inside = ok & (l0 >= -1e-9) & (l1 >= -1e-9) & (1 - l0 - l1 >= -1e-9)
        mask[py[inside] * size + px[inside]] = True
    return mask.reshape(size, size)


__all__ = ["View", "camera_basis", "posed", "render", "silhouette"]
