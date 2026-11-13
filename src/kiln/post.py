"""The retro post pass (#358): the frame drawn at a low resolution, snapped to a fixed palette with ordered dithering.

One method, written twice: a Godot canvas shader for the look kit and (previews) numpy. Per block of the low-res
frame: sample the screen once at the block's centre, find the two nearest palette colours c1, c2 (sRGB distance),
project the colour onto c1 -> c2 for t, and draw c2 where the Bayer threshold is below t x strength, else c1. Two-colour
ordered dithering reads right for black-and-white and small palettes, where "add noise, then round" bands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from kiln.style import Look

BAYER2 = np.array([[0, 2], [3, 1]])


def bayer(n: int) -> np.ndarray:
    """The n x n Bayer index matrix (n a power of two), values 0 .. n*n - 1."""
    m = BAYER2
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return m


DITHER_SIZE = {"bayer4": 4, "bayer8": 8, "none": 0}


def thresholds(dither: str) -> np.ndarray:
    """Per-cell thresholds in (0, 1): (index + 0.5) / n^2; one cell of 1.0 (never dither) for "none"."""
    n = DITHER_SIZE[dither]
    if n == 0:
        return np.ones((1, 1))
    return (bayer(n) + 0.5) / (n * n)


def block_size(height: float, look: Look) -> tuple[float, float]:
    """(width, height) of one low-res pixel, in output pixels, for an output `height` pixels tall."""
    h = height / look.post_lines
    return h * look.pixel_aspect, h


def shader(look: Look) -> str:
    """The look kit's canvas shader: a full-screen ColorRect on a CanvasLayer over the game."""
    colors = [tuple(int(c[i : i + 2], 16) / 255 for i in (1, 3, 5)) for c in look.post_colors]
    padded = colors + [(0.0, 0.0, 0.0)] * (16 - len(colors))
    table = ", ".join(f"vec3({r:.6g}, {g:.6g}, {b:.6g})" for r, g, b in padded)
    thr = thresholds(look.dither)
    n = thr.shape[0]
    cells = ", ".join(f"{v:.6g}" for v in thr.flatten())
    return f"""shader_type canvas_item;
render_mode unshaded;

// KILN: the style's retro pass ([look] post = "retro"): {look.post_lines} lines, {len(colors)} colours, {look.dither}
uniform sampler2D screen : hint_screen_texture, filter_nearest;
uniform float lines = {look.post_lines:.6g};
uniform float pixel_aspect = {look.pixel_aspect:.6g};
uniform float strength = {look.dither_strength:.6g};
const int COUNT = {len(colors)};
const vec3 COLORS[16] = vec3[16]({table});
const int N = {n};
const float THRESHOLDS[{n * n}] = float[{n * n}]({cells});

void fragment() {{
\tvec2 screen_px = 1.0 / SCREEN_PIXEL_SIZE;
\tfloat bh = screen_px.y / lines;
\tvec2 block = vec2(bh * pixel_aspect, bh);
\tvec2 cell = floor(SCREEN_UV * screen_px / block);
\tvec2 uv = clamp((cell + 0.5) * block / screen_px, vec2(0.0), vec2(1.0));
\tvec4 sampled = texture(screen, uv);\n\tvec3 p = sampled.rgb;
\tint i1 = 0;
\tint i2 = 0;
\tfloat d1 = 1e9;
\tfloat d2 = 1e9;
\tfor (int i = 0; i < COUNT; i++) {{
\t\tvec3 e = p - COLORS[i];
\t\tfloat d = dot(e, e);
\t\tif (d < d1) {{
\t\t\td2 = d1; i2 = i1; d1 = d; i1 = i;
\t\t}} else if (d < d2) {{
\t\t\td2 = d; i2 = i;
\t\t}}
\t}}
\tvec3 c1 = COLORS[i1];
\tvec3 c2 = COLORS[i2];
\tvec3 span = c2 - c1;
\tfloat t = COUNT > 1 ? clamp(dot(p - c1, span) / max(dot(span, span), 1e-9), 0.0, 1.0) : 0.0;
\tivec2 at = ivec2(mod(cell, float(N)));
\tfloat threshold = THRESHOLDS[at.y * N + at.x];
\tCOLOR = vec4(threshold < t * strength ? c2 : c1, sampled.a);  // a game's screen is opaque; engine previews keep their transparent background
}}
"""


def retro(image: np.ndarray, look: Look) -> np.ndarray:
    """The same pass on an sRGB float image (H, W, 3 or 4, 0..1), as the shader draws it on a screen that size.
    Alpha is kept as sampled (previews composite on their tile background)."""
    h, w = image.shape[:2]
    bw, bh = block_size(h, look)
    ys, xs = np.arange(h) + 0.5, np.arange(w) + 0.5  # pixel centres, as SCREEN_UV * screen size
    cy, cx = np.floor(ys / bh).astype(int), np.floor(xs / bw).astype(int)
    sy = np.clip(((cy + 0.5) * bh).astype(int), 0, h - 1)  # the block centre's pixel (nearest filter)
    sx = np.clip(((cx + 0.5) * bw).astype(int), 0, w - 1)
    sampled = image[sy[:, None], sx[None, :]]
    p = sampled[..., :3]
    pal = np.array([[int(c[i : i + 2], 16) / 255 for i in (1, 3, 5)] for c in look.post_colors])
    d = ((p[..., None, :] - pal) ** 2).sum(axis=-1)
    order = np.argsort(d, axis=-1, kind="stable")
    i1 = order[..., 0]
    i2 = order[..., 1] if len(pal) > 1 else i1
    c1, c2 = pal[i1], pal[i2]
    span = c2 - c1
    t = np.clip(((p - c1) * span).sum(-1) / np.maximum((span * span).sum(-1), 1e-9), 0, 1) if len(pal) > 1 else np.zeros(p.shape[:2])
    thr = thresholds(look.dither)
    n = thr.shape[0]
    cell_thr = thr[(cy % n)[:, None], (cx % n)[None, :]]
    out: np.ndarray = np.array(sampled, dtype=np.float64)
    out[..., :3] = np.where((cell_thr < t * look.dither_strength)[..., None], c2, c1)
    return out
