"""The retro post pass (#358, #365, #366): the frame drawn at a low resolution, snapped to a fixed palette with
ordered dithering.

One method, written twice: a Godot canvas shader for the look kit and (previews) numpy. Per block of the low-res
frame: sample the screen once at the block's centre, find the two nearest palette colours c1, c2 (sRGB distance),
project the colour onto c1 -> c2 for t, and draw c2 where the pattern's threshold for that cell is below
t x strength, else c1. Two-colour ordered dithering reads right for black-and-white and small palettes, where
"add noise, then round" bands. The pattern decides the texture: Bayer matrices, halftone dots, lines, cross-hatching
or noise.

Every setting is a shader uniform (the style's values are the material's starting values), so a game can tune the
look at runtime through the Retro node's script (`RETRO_SCRIPT`).

The pattern is fixed to the screen by default; `dither_space = "world"` (#367, Godot Forward+ only) fixes it to
surfaces through a depth-reading pass in the 3D render (`WORLD_SHADER`). Previews always draw screen space.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from kiln.style import Look

SPACES = ("screen", "world")  # [look] dither_space; the shaders' `space` is the index
PATTERNS = ("bayer4", "bayer8", "none", "halftone", "lines", "hatch", "noise")  # the shader's `pattern` is the index
MAX_COLORS = 16
LINE_ORDER = (0, 2, 1, 3)  # which of 4 rows fill first (lines pattern)

BAYER2 = np.array([[0, 2], [3, 1]])


def bayer(n: int) -> np.ndarray:
    """The n x n Bayer index matrix (n a power of two), values 0 .. n*n - 1."""
    m = BAYER2
    while m.shape[0] < n:
        m = np.block([[4 * m, 4 * m + 2], [4 * m + 3, 4 * m + 1]])
    return m


def _ranked(raw: np.ndarray) -> np.ndarray:
    """A tile's cells numbered in order of `raw` (ties by Bayer order), as Bayer indices are: every tone fills exactly
    its share of cells."""
    n = raw.shape[0]
    order = np.lexsort((bayer(n).flatten(), raw.flatten()))
    ranks = np.empty(n * n, dtype=int)
    ranks[order] = np.arange(n * n)
    return ranks.reshape(n, n)


def _halftone() -> np.ndarray:
    """8 x 8 tile of round dots on a 45-degree grid (two dots per tile), growing from their centres."""
    i = np.arange(8) + 0.5
    x, y = i[None, :], i[:, None]
    u, v = (x + y) / 8, (x - y) / 8
    fu, fv = u - np.floor(u) - 0.5, v - np.floor(v) - 0.5
    return _ranked(np.sqrt(fu * fu + fv * fv))


def _hatch() -> np.ndarray:
    """4 x 4 tile: one diagonal family of lines fills first, then the crossing one."""
    i = np.arange(4)
    x, y = i[None, :], i[:, None]
    a, b = (x + y) % 4, (x - y) % 4
    da, db = np.minimum(a, 4 - a), np.minimum(b, 4 - b)
    return _ranked(np.where(da == 0, 0, np.where(db == 0, 10, 20)) + da + db)


TILES = {"bayer4": bayer(4), "bayer8": bayer(8), "halftone": _halftone(), "hatch": _hatch()}  # index tiles


def threshold(pattern: str, cx: np.ndarray, cy: np.ndarray) -> np.ndarray:
    """Each cell's threshold in (0, 1] for low-res cell coordinates (integer arrays, broadcast together): c2 is drawn
    where threshold < t x strength, so low thresholds fill first as the colour moves from c1 to c2. 1.0 = never."""
    cx, cy = np.broadcast_arrays(np.asarray(cx), np.asarray(cy))
    if pattern in TILES:
        tile = TILES[pattern]
        n = tile.shape[0]
        out: np.ndarray = (tile[cy % n, cx % n] + 0.5) / (n * n)
        return out
    if pattern == "none":
        return np.ones(cx.shape)
    if pattern == "lines":  # horizontal bands, a row at a time
        rows: np.ndarray = (np.array(LINE_ORDER)[cy % 4] + 0.5) / 4
        return rows
    if pattern == "noise":  # interleaved gradient noise (Jimenez 2014): blue-noise-like, no texture
        f = 0.06711056 * cx + 0.00583715 * cy
        g = 52.9829189 * (f - np.floor(f))
        return np.clip(g - np.floor(g), 0.001, 0.999)
    raise ValueError(f"unknown pattern {pattern!r}")


def thresholds(dither: str) -> np.ndarray:
    """One period of a Bayer pattern as a matrix ("none": 1 x 1)."""
    n = {"bayer4": 4, "bayer8": 8, "none": 1}[dither]
    i = np.arange(n)
    return threshold(dither, i[None, :], i[:, None])


def block_size(height: float, look: Look) -> tuple[float, float]:
    """(width, height) of one low-res pixel, in output pixels, for an output `height` pixels tall. Never under one output
    pixel: a screen or tile shorter than `post_lines` shows its own pixels (smaller blocks would skip dither cells)."""
    h = height / min(look.post_lines, height)
    return h * look.pixel_aspect, h


def _float(v: float) -> str:
    """A GLSL float literal ("1" is an int: Godot won't put it in a float array)."""
    text = f"{v:.6g}"
    return text if any(c in text for c in ".e") else text + ".0"


def rgb(hex_color: str) -> tuple[float, float, float]:
    return (int(hex_color[1:3], 16) / 255, int(hex_color[3:5], 16) / 255, int(hex_color[5:7], 16) / 255)


def material_params(look: Look) -> list[str]:
    """The ShaderMaterial's `shader_parameter/...` lines: the style's settings as the uniforms' starting values."""
    colors = [rgb(c) for c in look.post_colors] + [(0.0, 0.0, 0.0)] * (MAX_COLORS - len(look.post_colors))
    vectors = ", ".join(f"{_float(r)}, {_float(g)}, {_float(b)}" for r, g, b in colors)
    return [
        f"shader_parameter/lines = {_float(look.post_lines)}",
        f"shader_parameter/pixel_aspect = {_float(look.pixel_aspect)}",
        f"shader_parameter/strength = {_float(look.dither_strength)}",
        f"shader_parameter/pattern = {PATTERNS.index(look.dither)}",
        f"shader_parameter/count = {len(look.post_colors)}",
        f"shader_parameter/colors = PackedVector3Array({vectors})",
        f"shader_parameter/space = {SPACES.index(look.dither_space)}",
    ]


def world_params(look: Look) -> list[str]:
    """The World pass's `shader_parameter/...` lines: the canvas pass's settings (but `space`) and the look's exposure."""
    return [*(line for line in material_params(look) if "/space " not in line), f"shader_parameter/exposure = {_float(look.exposure)}"]


PATTERN_GLSL = f"""const float BAYER4[16] = float[16]({", ".join(_float(v) for v in bayer(4).flatten())});
const float BAYER8[64] = float[64]({", ".join(_float(v) for v in bayer(8).flatten())});
const float HALFTONE[64] = float[64]({", ".join(_float(v) for v in _halftone().flatten())});
const float HATCH[16] = float[16]({", ".join(_float(v) for v in _hatch().flatten())});
const float LINE_ORDER[4] = float[4]({", ".join(_float(v) for v in LINE_ORDER)});

float threshold(vec2 cell) {{
\tif (pattern == 0) {{
\t\tivec2 a = ivec2(mod(cell, 4.0));
\t\treturn (BAYER4[a.y * 4 + a.x] + 0.5) / 16.0;
\t}}
\tif (pattern == 1) {{
\t\tivec2 a = ivec2(mod(cell, 8.0));
\t\treturn (BAYER8[a.y * 8 + a.x] + 0.5) / 64.0;
\t}}
\tif (pattern == 3) {{
\t\tivec2 a = ivec2(mod(cell, 8.0));
\t\treturn (HALFTONE[a.y * 8 + a.x] + 0.5) / 64.0;
\t}}
\tif (pattern == 4) {{
\t\treturn (LINE_ORDER[int(mod(cell.y, 4.0))] + 0.5) / 4.0;
\t}}
\tif (pattern == 5) {{
\t\tivec2 a = ivec2(mod(cell, 4.0));
\t\treturn (HATCH[a.y * 4 + a.x] + 0.5) / 16.0;
\t}}
\tif (pattern == 6) {{
\t\tfloat f = 0.06711056 * cell.x + 0.00583715 * cell.y;
\t\tfloat g = 52.9829189 * (f - floor(f));
\t\treturn clamp(g - floor(g), 0.001, 0.999);
\t}}
\treturn 1.0;  // none
}}
"""

# Both passes snap a colour the same way: the two nearest palette colours (sRGB distance), c2 where the threshold is
# below the colour's projection onto c1 -> c2 (x strength), else c1. A threshold of 1.0 never dithers (nearest colour).
QUANTISE_GLSL = f"""vec3 quantise(vec3 p, float threshold) {{
\tint n = clamp(count, 1, {MAX_COLORS});
\tint i1 = 0;
\tint i2 = 0;
\tfloat d1 = 1e9;
\tfloat d2 = 1e9;
\tfor (int i = 0; i < n; i++) {{
\t\tvec3 e = p - colors[i];
\t\tfloat d = dot(e, e);
\t\tif (d < d1) {{
\t\t\td2 = d1; i2 = i1; d1 = d; i1 = i;
\t\t}} else if (d < d2) {{
\t\t\td2 = d; i2 = i;
\t\t}}
\t}}
\tvec3 c1 = colors[i1];
\tvec3 c2 = colors[i2];
\tvec3 span = c2 - c1;
\tfloat t = n > 1 ? clamp(dot(p - c1, span) / max(dot(span, span), 1e-9), 0.0, 1.0) : 0.0;
\treturn threshold < t * strength ? c2 : c1;
}}
"""

SHADER = f"""shader_type canvas_item;
render_mode unshaded;

// KILN's retro pass ([look] post = "retro"): every setting is a uniform; the look kit's material holds the style's
// values and the Retro node's script changes them at runtime. The screen texture is sRGB while
// rendering/viewport/hdr_2d is off (Godot's default); the retro looks need it off.
uniform sampler2D screen : hint_screen_texture, filter_nearest;
uniform float lines = 200.0;
uniform float pixel_aspect = 1.0;
uniform float strength = 1.0;
uniform int pattern = 0;  // {", ".join(f"{i} {p}" for i, p in enumerate(PATTERNS))}
uniform int count = 2;
uniform vec3 colors[{MAX_COLORS}];
uniform int space = 0;  // {", ".join(f"{i} {p}" for i, p in enumerate(SPACES))} (the World pass has dithered the frame: snap only)

{PATTERN_GLSL}
{QUANTISE_GLSL}
void fragment() {{
\tvec2 screen_px = 1.0 / SCREEN_PIXEL_SIZE;
\tfloat bh = screen_px.y / min(lines, screen_px.y);  // never under one screen pixel
\tvec2 block = vec2(bh * pixel_aspect, bh);
\tvec2 cell = floor(SCREEN_UV * screen_px / block);
\tvec2 uv = clamp((cell + 0.5) * block / screen_px, vec2(0.0), vec2(1.0));
\tvec4 sampled = texture(screen, uv);
\tCOLOR = vec4(quantise(sampled.rgb, space == 1 ? 1.0 : threshold(cell)), step(0.5, sampled.a));  // a game's screen is opaque; engine previews keep their transparent background
}}
"""

# World space (#367): canvas shaders can't read depth, so a full-screen quad in the 3D pass does the dithering. It is
# drawn first among transparent surfaces (they land on top, and the canvas pass snaps them to the palette undithered)
# and follows whichever camera renders through the camera matrices. Per block of the canvas pass's grid it rebuilds the
# block centre's world position from the depth buffer, takes the pattern cell there and quantises the block-centre
# colour as the canvas pass would: the screen texture here is linear before tonemapping, so it goes through exposure and
# sRGB as a linear tonemapper does (the retro looks' tonemapper; others come out approximate), and the palette colour
# goes back the same way, then the canvas pass's snap lands on it. Pattern cells lie on the surface's dominant-axis
# plane (triplanar; the normal from the depth of the nearer neighbours, so faces come out flat), sized to a block's
# footprint there rounded up to a power of two metres: nested grids, never finer than a block, stepping (not swimming)
# with distance. The sky takes cells on a cube of view directions.
WORLD_SHADER = f"""shader_type spatial;
render_mode unshaded, depth_draw_never, depth_test_disabled, cull_disabled, fog_disabled, shadows_disabled;

// KILN's retro pass, world space ([look] dither_space = "world"): see kiln/post.py.
uniform sampler2D screen : hint_screen_texture, filter_nearest;
uniform sampler2D depth : hint_depth_texture, filter_nearest;
uniform float lines = 200.0;
uniform float pixel_aspect = 1.0;
uniform float strength = 1.0;
uniform int pattern = 0;
uniform int count = 2;
uniform vec3 colors[{MAX_COLORS}];
uniform float exposure = 1.0;  // the look's tonemap_exposure

{PATTERN_GLSL}
{QUANTISE_GLSL}
void vertex() {{
\tPOSITION = vec4(VERTEX.xy, 0.5, 1.0);  // the quad (2 x 2) covers the screen whatever the camera
}}

vec3 to_srgb(vec3 c) {{  // as Godot's tonemapper writes the frame
\treturn mix(1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, 12.92 * c, lessThan(c, vec3(0.0031308)));
}}

vec3 to_linear(vec3 c) {{
\treturn mix(pow((c + 0.055) / 1.055, vec3(2.4)), c / 12.92, lessThan(c, vec3(0.04045)));
}}

float depth_at(vec2 uv) {{
\treturn textureLod(depth, uv, 0.0).r;
}}

vec3 view_at(vec2 uv, float d, mat4 inv_projection) {{
\tvec4 v = inv_projection * vec4(uv * 2.0 - 1.0, d, 1.0);  // Forward+ depth (other renderers keep screen space)
\treturn v.xyz / v.w;
}}

vec2 face(vec3 a, vec3 p) {{  // the plane of a's dominant axis
\tif (a.x >= a.y && a.x >= a.z) {{
\t\treturn p.zy;
\t}}
\treturn a.y >= a.z ? p.xz : p.xy;
}}

void fragment() {{
\tvec2 px = 1.0 / VIEWPORT_SIZE;
\tfloat bh = VIEWPORT_SIZE.y / min(lines, VIEWPORT_SIZE.y);  // the canvas pass's blocks
\tvec2 block = vec2(bh * pixel_aspect, bh);
\tvec2 uv = clamp((floor(SCREEN_UV * VIEWPORT_SIZE / block) + 0.5) * block * px, vec2(0.0), vec2(1.0));
\tfloat d = depth_at(uv);
\tvec3 c = view_at(uv, d, INV_PROJECTION_MATRIX);
\tfloat block_ndc = 2.0 * bh * max(pixel_aspect, 1.0) * px.y;  // a block's longer side, in NDC units
\tbool ortho = PROJECTION_MATRIX[3][3] == 1.0;
\tbool sky = c.z <= view_at(uv, 0.0, INV_PROJECTION_MATRIX).z * 0.999;  // nothing drawn here but the background
\tvec2 cell;
\tif (sky && !ortho) {{
\t\tvec3 dir = normalize(mat3(INV_VIEW_MATRIX) * c);
\t\tvec3 a = abs(dir);
\t\tfloat size = exp2(ceil(log2(2.0 * block_ndc / abs(PROJECTION_MATRIX[1][1]))));  // cube-face units per block, x 2 at the edges
\t\tcell = floor(face(a, dir / max(a.x, max(a.y, a.z))) / size);
\t}} else {{
\t\tvec3 l = view_at(uv - vec2(px.x, 0.0), depth_at(uv - vec2(px.x, 0.0)), INV_PROJECTION_MATRIX);
\t\tvec3 r = view_at(uv + vec2(px.x, 0.0), depth_at(uv + vec2(px.x, 0.0)), INV_PROJECTION_MATRIX);
\t\tvec3 u = view_at(uv - vec2(0.0, px.y), depth_at(uv - vec2(0.0, px.y)), INV_PROJECTION_MATRIX);
\t\tvec3 b = view_at(uv + vec2(0.0, px.y), depth_at(uv + vec2(0.0, px.y)), INV_PROJECTION_MATRIX);
\t\tvec3 dx = abs(c.z - l.z) < abs(r.z - c.z) ? c - l : r - c;  // the nearer neighbour: no normals across edges
\t\tvec3 dy = abs(c.z - u.z) < abs(b.z - c.z) ? c - u : b - c;
\t\tvec3 a = abs(mat3(INV_VIEW_MATRIX) * cross(dx, dy));
\t\tvec2 du = abs(face(a, mat3(INV_VIEW_MATRIX) * dx)) * block.x;  // a block's extent on the face plane, per axis
\t\tvec2 dv = abs(face(a, mat3(INV_VIEW_MATRIX) * dy)) * block.y;
\t\tvec2 size = exp2(ceil(log2(max(du + dv, vec2(1e-6)))));  // metres, per axis: long cells where the surface recedes
\t\tcell = floor(face(a, (INV_VIEW_MATRIX * vec4(c, 1.0)).xyz) / size);
\t}}
\tvec4 sampled = textureLod(screen, uv, 0.0);
\tvec3 p = to_srgb(clamp(sampled.rgb * exposure, vec3(0.0), vec3(1.0)));
\tALBEDO = to_linear(quantise(p, threshold(cell))) / exposure;
}}
"""

# The look kit's Retro CanvasLayer script: the runtime API games (and the retro room's dev panel) use instead of
# setting uniforms by name.
RETRO_SCRIPT = f"""extends CanvasLayer
## KILN's retro pass. Change the look at runtime: set_enabled, set_lines, set_pixel_aspect, set_strength,
## set_pattern, set_palette, set_space; get_settings returns them all.

const PATTERNS := [{", ".join(f'"{p}"' for p in PATTERNS)}]
const SPACES := [{", ".join(f'"{p}"' for p in SPACES)}]
const MAX_COLORS := {MAX_COLORS}


func _material() -> ShaderMaterial:
	return $Pass.material


func _set_both(parameter: String, value: Variant) -> void:  # a setting the World pass reads too
	_material().set_shader_parameter(parameter, value)
	$World.material_override.set_shader_parameter(parameter, value)


func _ready() -> void:
	if not world_supported():
		_material().set_shader_parameter("space", 0)
	_show_world()


## World space reads the depth and screen textures in the 3D pass: Forward+ only (Mobile and Compatibility keep screen space).
func world_supported() -> bool:
	return RenderingServer.get_current_rendering_method() == "forward_plus"


func _show_world() -> void:
	$World.visible = visible and _material().get_shader_parameter("space") == 1


func set_enabled(on: bool) -> void:
	visible = on
	_show_world()


func is_enabled() -> bool:
	return visible


func set_lines(value: float) -> void:
	_set_both("lines", maxf(value, 1.0))


func set_pixel_aspect(value: float) -> void:
	_set_both("pixel_aspect", maxf(value, 0.05))


func set_strength(value: float) -> void:
	_set_both("strength", clampf(value, 0.0, 1.0))


func set_pattern(pattern_name: String) -> void:
	var index := PATTERNS.find(pattern_name)
	if index >= 0:
		_set_both("pattern", index)


## "screen" (the pattern fixed to the screen) or "world" (fixed to the surfaces: needs the depth buffer).
func set_space(space_name: String) -> void:
	var index := SPACES.find(space_name)
	if index == 1 and not world_supported():
		push_warning("KILN retro: world-space dither needs Forward+; keeping screen space")
		return
	if index >= 0:
		_material().set_shader_parameter("space", index)
		_show_world()


func set_palette(palette: PackedColorArray) -> void:
	var vectors := PackedVector3Array()
	for colour in palette.slice(0, MAX_COLORS):
		vectors.append(Vector3(colour.r, colour.g, colour.b))
	var count := vectors.size()
	while vectors.size() < MAX_COLORS:
		vectors.append(Vector3.ZERO)
	_set_both("colors", vectors)
	_set_both("count", count)


func get_palette() -> PackedColorArray:
	var vectors: PackedVector3Array = _material().get_shader_parameter("colors")
	var count: int = _material().get_shader_parameter("count")
	var palette := PackedColorArray()
	for i in mini(count, vectors.size()):
		palette.append(Color(vectors[i].x, vectors[i].y, vectors[i].z))
	return palette


func get_settings() -> Dictionary:
	var material := _material()
	return {{
		"enabled": visible,
		"lines": material.get_shader_parameter("lines"),
		"pixel_aspect": material.get_shader_parameter("pixel_aspect"),
		"strength": material.get_shader_parameter("strength"),
		"pattern": PATTERNS[material.get_shader_parameter("pattern")],
		"space": SPACES[material.get_shader_parameter("space")],
		"palette": get_palette(),
	}}
"""


def shader(look: Look) -> str:
    """The look kit's canvas shader: the same text for every look (the settings are the material's)."""
    del look
    return SHADER


def retro(image: np.ndarray, look: Look) -> np.ndarray:
    """The same pass on an sRGB float image (H, W, 3 or 4, 0..1), as the shader draws it on a screen that size.
    Alpha is snapped to 0 or 1 at 0.5 (previews composite on their tile background)."""
    h, w = image.shape[:2]
    bw, bh = block_size(h, look)
    ys, xs = np.arange(h) + 0.5, np.arange(w) + 0.5  # pixel centres, as SCREEN_UV * screen size
    cy, cx = np.floor(ys / bh).astype(int), np.floor(xs / bw).astype(int)
    sy = np.clip(((cy + 0.5) * bh).astype(int), 0, h - 1)  # the block centre's pixel (nearest filter)
    sx = np.clip(((cx + 0.5) * bw).astype(int), 0, w - 1)
    sampled = image[sy[:, None], sx[None, :]]
    p = sampled[..., :3]
    pal = np.array([rgb(c) for c in look.post_colors])
    d = ((p[..., None, :] - pal) ** 2).sum(axis=-1)
    order = np.argsort(d, axis=-1, kind="stable")
    i1 = order[..., 0]
    i2 = order[..., 1] if len(pal) > 1 else i1
    c1, c2 = pal[i1], pal[i2]
    span = c2 - c1
    t = np.clip(((p - c1) * span).sum(-1) / np.maximum((span * span).sum(-1), 1e-9), 0, 1) if len(pal) > 1 else np.zeros(p.shape[:2])
    cell_thr = threshold(look.dither, cx[None, :], cy[:, None])
    out: np.ndarray = np.array(sampled, dtype=np.float64)
    if out.shape[-1] == 4:  # alpha snapped as the shader does: no half-covered, off-palette edge pixels
        out[..., 3] = (out[..., 3] >= 0.5).astype(np.float64)
    out[..., :3] = np.where((cell_thr < t * look.dither_strength)[..., None], c2, c1)
    return out
