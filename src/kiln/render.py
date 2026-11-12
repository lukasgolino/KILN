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
from typing import Any

import numpy as np
from PIL import Image

from kiln.export import Built, srgb_to_linear
from kiln.paint import corner_uv, decal_uv
from kiln.rig import skin_matrices
from kiln.sdf import Array, rotation_matrix
from kiln.style import FILMIC_WHITE, TOON_DARKEN, Look

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
    """Godot's Filmic tonemapper (Hable's curve with its exposure bias of 2) at white = FILMIC_WHITE."""
    a, b, c, d, e, f = 0.22, 0.30, 0.10, 0.20, 0.01, 0.30

    def curve(v: Array) -> Array:
        return ((v * (a * v + c * b) + d * e) / (v * (a * v + b) + d * f)) - e / f

    return curve(x * 2.0) / curve(np.array(FILMIC_WHITE * 2.0))


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
    fill: float = 0.0,
) -> Image.Image:
    """One view. `fit` = (centre, half-extent in metres) to frame several renders the same way; default: the
    model's own bounding sphere. `hide`: bones (part ids) left out, e.g. a detached helmet. `revealed` parts (stump caps)
    are left out too, as in the exported scenes, unless a part that reveals them is hidden. `fade`: an opacity per face
    (0..1), drawn as ordered (Bayer 4x4) dithering at the output's pixel scale: what's behind shows through the holes,
    and outlines leave them alone. `colors`: a linear albedo per face corner (F, 3, 3) instead of the paint groups'
    colours (terrains: blended splat layers)."""
    hide = with_unrevealed(built, hide)
    see = np.array([built.style.materials.get(gr.material, built.style.materials["default"]).alpha for gr in built.painted.groups])
    if (see < 1).any():  # see-through presets (glass, #175): dithered at their alpha, as fading pieces are
        face_alpha = see[built.painted.face_group]
        fade = face_alpha if fade is None else fade * face_alpha
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
    hidden = np.array([built.painted.groups[g].bone in hide for g in built.painted.face_group], dtype=bool) if hide else None
    if hidden is not None:
        front &= ~hidden
    tri = np.flatnonzero(front)
    best_depth, best_tri, best_bary, dropped = _raster(sx, sy, sz, tri, res, fade)
    hit = best_tri >= 0
    rgba = np.zeros((res * res, 4))
    rgba[:] = np.array(background) / 255.0
    glow = np.zeros((res * res, 3))  # emissive light (linear) that the look's glow spreads (bloom)
    if hit.any():
        T = best_tri[hit]
        bary = best_bary[hit]
        n = (normals[T] * bary[:, :, None]).sum(axis=1)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        if built.bake is not None and track is None:  # the baked normal map (rest pose only: posed tangents aren't tracked)
            n = _mapped_normals(built.bake, T, bary, n)
        p = built.painted
        groups = p.groups
        g = p.face_group[T]
        albedo_table = np.array([srgb_to_linear(swap.get(gr.color, gr.color)) for gr in groups])
        albedo = albedo_table[g] if colors is None else (colors[T] * bary[:, :, None]).sum(axis=1)
        if colors is None and built.bake is not None and built.bake.layers is not None:  # relief: the base colour map, as the engine samples it
            albedo = _mapped_colours(built.bake, T, bary, [gr.color for gr in groups], swap)
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
                if d.project == "planar":
                    uv = decal_uv(d, rest[m]).clip(0, 0.999999)
                else:  # textures: the glTF's per-corner coordinates, interpolated as the GPU does; they repeat
                    uv = (corner_uv(d, p.vertices[p.faces[T[m]]]) * bary[m][:, :, None]).sum(axis=1)
                    uv = np.mod(uv, 1.0).clip(0, 0.999999)
                tx = (uv[:, 0] * img.shape[1]).astype(int)
                ty = (uv[:, 1] * img.shape[0]).astype(int)
                texel = img[ty, tx]
                lin = np.array([[c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in row] for row in texel[:, :3]])
                albedo[m] = albedo[m] * (1 - texel[:, 3:4]) + lin * texel[:, 3:4]
        lit_albedo = albedo  # what glows: Godot's EMISSION doesn't take COLOR, so no occlusion there
        if built.ao is not None:  # shade paint / occlusion: a multiplier per corner, as COLOR_0 (decals too) in the engine
            albedo = albedo * (built.ao[T] * bary).sum(axis=1)[:, None]
        presets = [built.style.materials.get(gr.material, built.style.materials["default"]) for gr in groups]
        rough = np.array([pr.roughness for pr in presets])[g]
        metal = np.array([pr.metallic for pr in presets])[g]
        emit = np.array([pr.emission for pr in presets])[g]
        if (emit > 0).any():  # as export: a glowing colour's strength capped so it keeps its hue, its lit colour dimmed (#202)
            from kiln.export import GLOW_ALBEDO, GLOW_PEAK

            glowing = emit > 0
            emit = np.where(glowing, np.minimum(emit, GLOW_PEAK / np.maximum(lit_albedo.max(axis=1), 1e-6)), 0.0)
            albedo = np.where(glowing[:, None], albedo * GLOW_ALBEDO, albedo)
        rim = np.array([pr.rim for pr in presets])[g]
        sun = rotation_matrix((look.sun_pitch, look.sun_yaw, 0.0)) @ np.array([0.0, 0.0, -1.0])  # light travel direction
        to_light = -sun / np.linalg.norm(sun)
        ndl = n @ to_light
        sun_col = np.array(srgb_to_linear(look.sun_color)) * look.sun_energy
        sky_top, sky_hor, ground = (np.array(srgb_to_linear(c)) for c in (look.sky_top, look.sky_horizon, look.ground))
        up_amount = n[:, 1:2]
        sky = np.where(up_amount >= 0, sky_hor + (sky_top - sky_hor) * up_amount, sky_hor + (ground - sky_hor) * (-up_amount))
        ambient = sky * look.ambient  # as Godot: ambient_light_energy on the sky (#161)
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
        if fill > 0:  # previews only (#180): a neutral light from the camera, so faces turned away from sun and sky read
            color = color + albedo * fill * np.clip(n @ -forward, 0, None)[:, None]
        color = color + lit_albedo * emit[:, None]
        if look.rim_light > 0:  # the style's added fresnel rim (Godot: a next pass on every material)
            fres = np.power(1 - np.clip(n @ -forward, 0, 1), look.rim_light_power)
            color = color + np.array(srgb_to_linear(look.rim_light_color)) * (look.rim_light * fres)[:, None]
        if look.glow and (emit > 0).any():
            glow[hit] = lit_albedo * emit[:, None] * look.exposure
        rgba[hit, :3] = _to_srgb(_grade(color, look))
        rgba[hit, 3] = 1.0
    image = rgba.reshape(res, res, 4)
    if look.outline > 0 and colors is None:  # (terrains: Godot draws them no outline) the inverted hull, as Godot draws it (#183): back faces pushed out along their normals, drawn where nearer
        if look.outline_space == "pixels":  # pushed out on screen, a constant width in output pixels
            away = np.stack([normals @ right, -(normals @ up)], axis=-1)
            away /= np.maximum(np.linalg.norm(away, axis=-1, keepdims=True), 1e-9)
            hx, hy, hz = sx + away[..., 0] * look.outline * SUPERSAMPLE, sy + away[..., 1] * look.outline * SUPERSAMPLE, sz
        else:
            moved = rel + normals * look.outline
            hx, hy, hz = (moved @ right) * scale + res / 2, res / 2 - (moved @ up) * scale, moved @ forward
        back = (hx[:, 1] - hx[:, 0]) * (hy[:, 2] - hy[:, 0]) - (hx[:, 2] - hx[:, 0]) * (hy[:, 1] - hy[:, 0]) > 0
        if hidden is not None:
            back &= ~hidden
        hull_depth, hull_tri, _, _ = _raster(hx, hy, hz, np.flatnonzero(back), res, fade)  # dithered as its face
        holes = (dropped < best_depth).reshape(res, res)  # dither holes: a faded piece isn't outlined around every hole
        holes = holes | np.roll(holes, 1, 0) | np.roll(holes, -1, 0) | np.roll(holes, 1, 1) | np.roll(holes, -1, 1)
        drawn = (hull_tri >= 0) & (hull_depth < best_depth) & ~holes.reshape(-1)
        flat = image.reshape(-1, 4)
        if look.outline_color == "darken":  # each part's flat colour, darkened (Godot also multiplies in vertex colours and colour maps: #292)
            table = np.array([srgb_to_linear(swap.get(gr.color, gr.color)) for gr in built.painted.groups]) * TOON_DARKEN
            flat[drawn, :3] = _to_srgb(_grade(table[built.painted.face_group[hull_tri[drawn]]], look))
        else:
            flat[drawn, :3] = _to_srgb(_grade(np.array([srgb_to_linear(look.outline_color)]), look))
        flat[drawn, 3] = 1.0
    if glow.any():
        image = _bloom(image, glow.reshape(res, res, 3), max(1, int(res * 0.025)))
    out = Image.fromarray((image * 255 + 0.5).astype(np.uint8), "RGBA")
    return out.resize((size, size), Image.Resampling.BOX)


def _grade(color: Array, look: Look) -> Array:
    """Linear colours (N, 3) through the look's exposure, tone curve, saturation and contrast, as Godot's
    environment does to everything drawn (the unshaded outline too)."""
    color = color * look.exposure
    color = _filmic(color) if look.tonemapper != "linear" else color
    lum = (color * np.array([0.2126, 0.7152, 0.0722])).sum(axis=1, keepdims=True)
    color = lum + (color - lum) * look.saturation
    return (color - 0.18) * look.contrast + 0.18


def _raster(sx: Array, sy: Array, sz: Array, tri: Array, res: int, fade: Array | None = None) -> tuple[Array, Array, Array, Array]:
    """The nearest of triangles `tri` (screen x, y and depth per corner) at each pixel centre of a res x res image:
    (depth, triangle, barycentrics, dropped: the nearest depth at which a faded face was dithered away)."""
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
    return best_depth, best_tri, best_bary, dropped


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


def _mapped_colours(bake: Any, faces: Array, bary: Array, group_colors: list[str], swap: dict[str, str]) -> Array:
    """Per pixel: the base colour map's colour (linear) at the interpolated UV, nearest texel."""
    from io import BytesIO

    key = tuple(sorted(swap.items()))
    cache = bake.__dict__.setdefault("_colours", {})
    if key not in cache:
        cache.clear()  # one decoded map at a time
        cache[key] = np.asarray(Image.open(BytesIO(bake.color_png(group_colors, swap))).convert("RGB"), dtype=np.uint8)
    image = cache[key]
    uv = (bake.uv[faces] * bary[:, :, None]).sum(axis=1)
    h, w = image.shape[:2]
    px = np.clip((uv * [w, h]).astype(np.int64), 0, [w - 1, h - 1])
    c = image[px[:, 1], px[:, 0]].astype(np.float64) / 255.0
    return np.asarray(np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4))


def _mapped_normals(bake: Any, faces: Array, bary: Array, n: Array) -> Array:
    """Per pixel: the normal map's normal (sampled at the interpolated UV, nearest texel) in the interpolated frame."""
    from io import BytesIO

    image = getattr(bake, "_decoded", None)
    if image is None:  # kept as bytes (a 4096 map: 50 MB), decoded per pixel sampled
        image = np.asarray(Image.open(BytesIO(bake.png)).convert("RGB"), dtype=np.uint8)
        bake._decoded = image
    uv = (bake.uv[faces] * bary[:, :, None]).sum(axis=1)
    h, w = image.shape[:2]
    px = np.clip((uv * [w, h]).astype(np.int64), 0, [w - 1, h - 1])
    local = image[px[:, 1], px[:, 0]].astype(np.float64) / 255.0 * 2.0 - 1.0
    t = (bake.tangent[faces, :, :3] * bary[:, :, None]).sum(axis=1)
    w = np.where((bake.tangent[faces, :, 3] * bary).sum(axis=1) < 0, -1.0, 1.0)
    t = t - n * (n * t).sum(axis=1, keepdims=True)
    t /= np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
    up = np.cross(n, t) * w[:, None]
    out = local[:, :1] * t + local[:, 1:2] * up + local[:, 2:3] * n
    return np.asarray(out / np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-12))


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
