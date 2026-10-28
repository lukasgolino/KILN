"""Terrains (`terrain:` in a model file): a heightfield made of height shapes (hills, ridges, plateaus, noise, paths)
combined in order like parts, painted with up to four splat layers chosen by rules (slope, height, nearness to paths,
noise). A heightfield is 2.5D (one height per (x, z)), so it is sampled on a regular grid (`cell` metres) and meshed as
that grid, not dual-contoured.

The map is centred on the origin: x in [-size_x / 2, size_x / 2], z likewise, heights in metres (+Y up).

Shapes apply in order to the running height H (starting at `base`). Each has a footprint weight p(x, z) in 0..1 (1 at
its core, a smoothstep falloff to 0 at its edge) and a blend:
    add: H += height * p                  subtract: H -= height * p
    max: H += p * (smax(H, height) - H)   min: H += p * (smin(H, height) - H)   set: H += p * (height - H)
(for max / min / set `height` is a level, an absolute height; `smooth` rounds the crease of max / min). A path flattens
the ground along a spline to the ground's own height smoothed along the path, sunk by `depth`.

`Heightfield` is the queryable result (height, normal, slope, splat weights and distance to paths at any (x, z),
bilinear between grid points), the API foliage scattering builds on. `meshes` makes the chunked LOD meshes with skirts.
"""

from __future__ import annotations

import hashlib
import json
import math
import pickle
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from kiln.sdf import Array

FORMAT = 1  # Heightfield cache layout
SHAPES = ("hill", "ridge", "plateau", "noise", "path")
BLENDS = ("add", "subtract", "max", "min", "set")
RULES = ("slope", "height", "path", "noise")
TERRAIN_FIELDS = ("size", "cell", "chunk", "lod", "skirt", "collision", "seed", "base", "shapes", "splat")
SHAPE_FIELDS: dict[str, tuple[str, ...]] = {
    "hill": ("at", "radius", "rotate", "height", "blend", "smooth"),
    "plateau": ("at", "radius", "rotate", "edge", "height", "blend", "smooth"),
    "ridge": ("points", "width", "height", "blend", "smooth"),
    "noise": ("scale", "height", "octaves", "roughness", "ridged", "seed", "blend"),
    "path": ("points", "width", "edge", "depth", "smooth"),
}
LAYER_FIELDS = ("color", "strength", *RULES)
MAX_LAYERS = 4
MAX_SAMPLES = 2049 * 2049  # grid points: a 1 km map at 0.5 m; more would need streaming (not done)
MAX_CHUNK_CELLS = 250  # 16-bit indices: (cells + 1)^2 vertices plus a skirt per chunk
NO_PATH = 1e9  # path distance where there is no path
HELP = ("terrain is { size: [x, z] metres, cell: 0.5, chunk: 32, lod: [64, 160] (distances), seed: 0, base: 0, "
        "shapes: [- hill: { at: [x, z], radius: r, height: h }, - ridge: { points: [[x, z], ...], width: w, height: h }, "
        "- plateau: { at: [x, z], radius: r, edge: e, height: h }, - noise: { scale: m, height: h, octaves: 4 }, "
        "- path: { points: [[x, z], ...], width: w, depth: 0.2 }], splat: [- grass: { color: green }, "
        "- rock: { color: stone, slope: { above: 35 } }] }")  # fmt: skip


@dataclass(frozen=True)
class HeightShape:
    kind: str  # hill | ridge | plateau | noise | path
    blend: str = "add"  # add | subtract | max | min | set (paths: their own flattening)
    height: float = 0.0  # add / subtract: by how much; max / min / set: to what level
    smooth: float = 0.0  # max / min: crease rounding (m); path: smoothing of its height along it (m)
    at: tuple[float, float] = (0.0, 0.0)
    radius: tuple[float, float] = (1.0, 1.0)
    rotate: float = 0.0  # degrees about +Y
    edge: float = 0.0  # plateau / path: falloff width (m)
    points: tuple[tuple[float, float], ...] = ()
    width: float = 0.0  # ridge: falloff distance from its line; path: bed width
    depth: float = 0.0  # path: sunk below the smoothed ground
    scale: float = 1.0  # noise: feature size (m)
    octaves: int = 4
    roughness: float = 0.5  # noise: each octave's amplitude relative to the one before
    ridged: bool = False
    seed: int = 0
    where: str = ""
    line: int | None = None


@dataclass(frozen=True)
class Rule:
    kind: str  # slope | height | path | noise
    above: float | None = None  # slope / height: from here up (degrees / metres)
    below: float | None = None
    within: float = 0.0  # path: metres from a path's centre line
    fade: float = 0.0
    scale: float = 1.0  # noise: patch size (m)
    cover: float = 0.5  # noise: about this fraction of the area
    seed: int = 0


@dataclass(frozen=True)
class SplatLayer:
    name: str
    color: str  # hex
    color_name: str
    rules: tuple[Rule, ...] = ()
    strength: float = 1.0
    where: str = ""
    line: int | None = None


@dataclass(frozen=True)
class Terrain:
    size: tuple[float, float] = (256.0, 256.0)
    cell: float = 0.5
    chunk: float = 32.0
    lod: tuple[float, ...] = (64.0, 160.0)  # camera distances where LOD 1, 2, ... take over
    skirt: float | None = None  # metres; None: from the LODs' largest height error
    collision: int = 1  # HeightMapShape3D samples every `collision` cells; 0: no collision shape
    seed: int = 0
    base: float = 0.0
    shapes: tuple[HeightShape, ...] = ()
    layers: tuple[SplatLayer, ...] = ()

    @property
    def cells(self) -> tuple[int, int]:
        """Grid cells along x and z."""
        return round(self.size[0] / self.cell), round(self.size[1] / self.cell)

    @property
    def chunks(self) -> tuple[int, int]:
        return round(self.size[0] / self.chunk), round(self.size[1] / self.chunk)

    @property
    def chunk_cells(self) -> int:
        return round(self.chunk / self.cell)


# --- parsing ------------------------------------------------------------------------------------------------------

Error = Callable[[str, int | None, str], None]  # (message, line, where)
ColorOf = Callable[[Any, int | None, str], tuple[str, str] | None]  # palette colour -> (hex, name), reporting E004


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _line(data: Any, key: Any = None) -> int | None:
    from kiln.vendor.yamlio import LineMap

    if isinstance(data, LineMap):
        return data.line_of(key) if key is not None else data.line
    return None


def _point(v: Any) -> tuple[float, float] | None:
    if isinstance(v, list) and len(v) == 2 and all(_num(x) for x in v):
        return float(v[0]), float(v[1])
    return None


def _multiple(a: float, b: float) -> bool:
    k = a / b
    return abs(k - round(k)) < 1e-6 and round(k) >= 1


def parse(raw: Any, line: int | None, error: Error, color: ColorOf) -> Terrain | None:
    """A `terrain:` block; problems go to error(message, line, where)."""
    if not isinstance(raw, dict):
        error(HELP, line, "terrain")
        return None
    ok = True

    def bad(message: str, key: str, at: Any = raw) -> None:
        nonlocal ok
        ok = False
        error(message, _line(at, key.split(".")[-1]) or _line(at) or line, f"terrain.{key}")

    unknown = [str(k) for k in raw if k not in TERRAIN_FIELDS]
    if unknown:
        bad(f"unknown field(s) {', '.join(unknown)}; allowed: {', '.join(TERRAIN_FIELDS)}", unknown[0])
    size = raw.get("size", [256, 256])
    if _num(size):
        size = [size, size]
    sz = _point(size)
    if sz is None or not all(0 < v <= 4096 for v in sz):
        bad("size is [x, z] in metres (or one number for a square), up to 4096", "size")
        sz = (256.0, 256.0)
    cell = raw.get("cell", 0.5)
    if not _num(cell) or not 0.05 <= cell <= 16:
        bad("cell is the grid spacing in metres (0.05-16), e.g. 0.5", "cell")
        cell = 0.5
    chunk = raw.get("chunk", 32)
    if not _num(chunk) or chunk <= 0:
        bad("chunk is the mesh tile size in metres, e.g. 32", "chunk")
        chunk = 32
    lod = raw.get("lod", [64, 160])
    if not isinstance(lod, list) or len(lod) > 4 or not all(_num(d) and d > 0 for d in lod) or any(b <= a for a, b in zip(lod, lod[1:], strict=False)):
        bad("lod is up to 4 increasing camera distances in metres where coarser meshes take over, e.g. [64, 160] ([] for none)", "lod")
        lod = []
    skirt = raw.get("skirt")
    if skirt is not None and (not _num(skirt) or not 0 <= skirt <= 100):
        bad("skirt is how far chunk edges hang down to hide cracks between LODs, in metres (0-100); leave it out for automatic", "skirt")
        skirt = None
    collision = raw.get("collision", 1)
    if collision is False:
        collision = 0
    if collision not in (0, 1, 2, 4, 8) or isinstance(collision, bool):
        bad("collision is 1, 2, 4 or 8 (a HeightMapShape3D sample every that many cells) or false (no collision shape)", "collision")
        collision = 1
    seed = raw.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2**31:
        bad("seed is a whole number (0 or more)", "seed")
        seed = 0
    base = raw.get("base", 0)
    if not _num(base):
        bad("base is the height everything starts from, in metres", "base")
        base = 0
    if ok:  # the grid: cells fit the size, chunks fit the size, LOD steps fit the chunks
        if not (_multiple(sz[0], cell) and _multiple(sz[1], cell)):
            bad(f"size {sz[0]:g} x {sz[1]:g} m isn't a whole number of {cell:g} m cells", "cell")
        elif (sz[0] / cell + 1) * (sz[1] / cell + 1) > MAX_SAMPLES:
            bad(f"{round(sz[0] / cell)} x {round(sz[1] / cell)} cells is too many (up to 2048 x 2048): use bigger cells or a smaller map", "cell")
        elif not (_multiple(sz[0], chunk) and _multiple(sz[1], chunk)):
            bad(f"size {sz[0]:g} x {sz[1]:g} m isn't a whole number of {chunk:g} m chunks", "chunk")
        elif not _multiple(chunk, cell * 2 ** len(lod)):
            bad(f"a chunk must be a whole number of {cell * 2 ** len(lod):g} m (cell x 2^{len(lod)}: each LOD halves the grid)", "chunk")
        elif chunk / cell > MAX_CHUNK_CELLS:
            bad(f"a chunk is at most {MAX_CHUNK_CELLS} cells across ({MAX_CHUNK_CELLS * cell:g} m at this cell)", "chunk")
        elif collision and not (_multiple(sz[0], cell * collision) and _multiple(sz[1], cell * collision)):
            bad(f"collision {collision}: the size must be a whole number of {cell * collision:g} m", "collision")
    shapes = _parse_shapes(raw.get("shapes", []), raw, line, bad)
    layers = _parse_layers(raw.get("splat"), raw, line, bad, color)
    if not ok or shapes is None or layers is None:
        return None
    return Terrain((sz[0], sz[1]), float(cell), float(chunk), tuple(float(d) for d in lod), None if skirt is None else float(skirt), int(collision),
                   int(seed), float(base), shapes, layers)  # fmt: skip


def _parse_shapes(raw: Any, parent: Any, line: int | None, bad: Callable[..., None]) -> tuple[HeightShape, ...] | None:
    if not isinstance(raw, list):
        bad("shapes is a list of height shapes: - hill: { at: [x, z], radius: r, height: h } (hill, ridge, plateau, noise, path)", "shapes", parent)
        return None
    out = []
    failed = False
    for i, item in enumerate(raw):
        where = f"shapes[{i}]"
        if not isinstance(item, dict) or len(item) != 1 or next(iter(item)) not in SHAPES or not isinstance(next(iter(item.values())), dict):
            bad(f"each shape is one of {', '.join(SHAPES)} with its settings, e.g. - hill: {{ at: [0, 0], radius: 20, height: 8 }}", where, item)
            failed = True
            continue
        kind = str(next(iter(item)))
        spec = item[kind]
        shape = _parse_shape(kind, spec, f"{where}.{kind}", _line(item) or line, bad)
        if shape is None:
            failed = True
        else:
            out.append(shape)
    return None if failed else tuple(out)


def _parse_shape(kind: str, spec: dict[str, Any], where: str, line: int | None, bad: Callable[..., None]) -> HeightShape | None:
    problems = []
    unknown = [str(k) for k in spec if k not in SHAPE_FIELDS[kind]]
    if unknown:
        problems.append((f"unknown field(s) {', '.join(unknown)} on a {kind}; allowed: {', '.join(SHAPE_FIELDS[kind])}", unknown[0]))

    def number(key: str, default: float | None, lo: float, hi: float, text: str) -> float:
        v = spec.get(key, default)
        if v is None or not _num(v) or not lo <= v <= hi:
            problems.append((f"{kind} {key} {text}", key))
            return lo if default is None else default
        return float(v)

    values: dict[str, Any] = {"kind": kind, "where": where, "line": line}
    blend = spec.get("blend", "add")
    if kind != "path":
        allowed = ("add", "subtract") if kind == "noise" else BLENDS
        if blend not in allowed:
            problems.append((f"{kind} blend is {', '.join(allowed)} (add / subtract: by height; max / min / set: to height, a level)", "blend"))
        else:
            values["blend"] = blend
        values["height"] = number("height", None, -1000, 1000, "is metres (required): how much (add, subtract) or the level (max, min, set)")
    if kind in ("hill", "plateau"):
        at = _point(spec.get("at"))
        if at is None:
            problems.append((f"{kind} at is its centre [x, z] in metres (required)", "at"))
        else:
            values["at"] = at
        r = spec.get("radius")
        radius = (float(r), float(r)) if isinstance(r, int | float) and _num(r) else _point(r)
        if radius is None or min(radius) <= 0:
            problems.append((f"{kind} radius is metres, or [x, z] for an oval (required)", "radius"))
        else:
            values["radius"] = radius
        values["rotate"] = number("rotate", 0.0, -360, 360, "is degrees about +Y")
    if kind == "plateau":
        default_edge = min(values.get("radius", (3.0, 3.0))) / 3
        values["edge"] = number("edge", default_edge, 0, 1000, "is the width of its sloping rim in metres")
    if kind in ("ridge", "path"):
        pts = spec.get("points")
        points = [_point(p) for p in pts] if isinstance(pts, list) else []
        if len(points) < 2 or any(p is None for p in points) or any(p == q for p, q in zip(points, points[1:], strict=False)):
            problems.append((f"{kind} points is a list of 2+ different [x, z] points (a smooth curve through them)", "points"))
        else:
            values["points"] = tuple(p for p in points if p is not None)
        if kind == "ridge":
            values["width"] = number("width", None, 1e-3, 1000, "is metres from its line to where it meets the ground (required)")
        else:
            values["width"] = number("width", 3.0, 0.1, 100, "is its flat bed's width in metres")
            values["edge"] = number("edge", values["width"], 0, 100, "is the width of its banks in metres")
            values["depth"] = number("depth", 0.2, -10, 10, "is how far it sinks below the ground around it, in metres")
            values["smooth"] = number("smooth", 12.0, 0, 1000, "is how far along it its height is smoothed, in metres")
    if kind in ("hill", "plateau", "ridge"):
        values["smooth"] = number("smooth", 0.0, 0, 100, "rounds the crease of blend max / min, in metres")
    if kind == "noise":
        values["scale"] = number("scale", None, 0.1, 10000, "is the size of its biggest bumps in metres (required)")
        octaves = spec.get("octaves", 4)
        if not isinstance(octaves, int) or isinstance(octaves, bool) or not 1 <= octaves <= 8:
            problems.append(("noise octaves is 1-8 (finer detail layers)", "octaves"))
        else:
            values["octaves"] = octaves
        values["roughness"] = number("roughness", 0.5, 0, 1, "is 0-1: each finer octave's strength relative to the last")
        ridged = spec.get("ridged", False)
        if not isinstance(ridged, bool):
            problems.append(("noise ridged is true or false (sharp crests)", "ridged"))
        else:
            values["ridged"] = ridged
        seed = spec.get("seed", 0)
        if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed < 2**31:
            problems.append(("noise seed is a whole number (added to the terrain's seed)", "seed"))
        else:
            values["seed"] = seed
    for message, key in problems:
        bad(message, f"{where}.{key}", spec)
    return None if problems else HeightShape(**values)


def _parse_layers(raw: Any, parent: Any, line: int | None, bad: Callable[..., None], color: ColorOf) -> tuple[SplatLayer, ...] | None:
    from kiln.notation import NAME_RE

    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_LAYERS:
        bad(f"splat is a list of 1-{MAX_LAYERS} layers, the first everywhere and each later one painted over by its rules: "
            "- grass: { color: green }, - rock: { color: stone, slope: { above: 35 } }", "splat", parent)  # fmt: skip
        return None
    out = []
    failed = False
    names: set[str] = set()
    for i, item in enumerate(raw):
        where = f"splat[{i}]"
        if not isinstance(item, dict) or len(item) != 1 or not isinstance(next(iter(item.values())), dict):
            bad("each splat layer is - <name>: { color: <palette colour>, slope / height / path / noise rules }", where, item)
            failed = True
            continue
        name = str(next(iter(item)))
        spec = item[name]
        lline = _line(item) or line
        problems: list[tuple[str, str]] = []
        if not NAME_RE.match(name) or name in names:
            problems.append(("a layer name is lowercase letters, digits, _ or - and used once", ""))
        names.add(name)
        unknown = [str(k) for k in spec if k not in LAYER_FIELDS]
        if unknown:
            problems.append((f"unknown field(s) {', '.join(unknown)}; allowed: {', '.join(LAYER_FIELDS)}", unknown[0]))
        hexed = color(spec.get("color"), _line(spec, "color") or lline, f"terrain.{where}.{name}.color") if "color" in spec else None
        if "color" not in spec:
            problems.append(("a layer needs color: <palette colour>", "color"))
        strength = spec.get("strength", 1.0)
        if not _num(strength) or not 0 <= strength <= 1:
            problems.append(("strength is 0-1: how opaque the layer is where its rules hold", "strength"))
            strength = 1.0
        rules = []
        for kind in RULES:
            if kind not in spec:
                continue
            rule, problem = _parse_rule(kind, spec[kind])
            if problem:
                problems.append((problem, kind))
            elif rule is not None:
                rules.append(rule)
        if i == 0 and rules:
            problems.append(("the first layer covers everything under the others: it takes no rules (put them on a later layer)", rules[0].kind))
        for message, key in problems:
            bad(message, f"{where}.{name}{'.' + key if key else ''}", spec)
        if problems or hexed is None:
            failed = True
            continue
        out.append(SplatLayer(name, hexed[0], hexed[1], tuple(rules), float(strength), f"terrain.{where}.{name}", lline))
    return None if failed else tuple(out)


def _parse_rule(kind: str, raw: Any) -> tuple[Rule | None, str]:
    if kind == "path":
        if _num(raw):
            raw = {"within": raw}
        if not isinstance(raw, dict) or set(raw) - {"within", "fade"} or not _num(raw.get("within")) or raw["within"] <= 0 \
                or not _num(raw.get("fade", 1.0)) or raw.get("fade", 1.0) < 0:  # fmt: skip
            return None, "path is { within: metres from a path's centre line, fade: 1 } (or just the metres)"
        return Rule("path", within=float(raw["within"]), fade=float(raw.get("fade", 1.0))), ""
    if kind == "noise":
        if not isinstance(raw, dict) or set(raw) - {"scale", "cover", "fade", "seed"} or not _num(raw.get("scale")) or raw["scale"] <= 0:
            return None, "noise is { scale: patch size in metres, cover: 0-1 (about that much of the area), fade: 0.1, seed: 0 }"
        cover, fade, seed = raw.get("cover", 0.5), raw.get("fade", 0.1), raw.get("seed", 0)
        if not _num(cover) or not 0 <= cover <= 1 or not _num(fade) or not 0 <= fade <= 1 or not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
            return None, "noise cover and fade are 0-1, seed a whole number"
        return Rule("noise", scale=float(raw["scale"]), cover=float(cover), fade=float(fade), seed=seed), ""
    unit, default_fade = ("degrees", 4.0) if kind == "slope" else ("metres", 1.0)
    text = f"{kind} is {{ above: {unit}, below: {unit}, fade: {default_fade:g} }} (one or both bounds)"
    if not isinstance(raw, dict) or set(raw) - {"above", "below", "fade"} or not ({"above", "below"} & set(raw)):
        return None, text
    above, below, fade = raw.get("above"), raw.get("below"), raw.get("fade", default_fade)
    if any(v is not None and not _num(v) for v in (above, below)) or not _num(fade) or fade < 0:
        return None, text
    if kind == "slope" and any(v is not None and not 0 <= v <= 90 for v in (above, below)):
        return None, "slope bounds are degrees, 0-90"
    if above is not None and below is not None and below <= above:
        return None, f"{kind}: below must be more than above (a band between them)"
    return Rule(kind, above=None if above is None else float(above), below=None if below is None else float(below), fade=float(fade)), ""


# --- noise and curves -----------------------------------------------------------------------------------------------

_GRADIENTS = np.array([[1, 0], [-1, 0], [0, 1], [0, -1], [0.70710678, 0.70710678], [-0.70710678, 0.70710678],
                       [0.70710678, -0.70710678], [-0.70710678, -0.70710678]])  # fmt: skip


def _hash(ix: Array, iz: Array, seed: int) -> Array:
    """A well-mixed 32-bit hash of integer lattice points (integer arithmetic only: the same on every machine)."""
    m = np.uint64(0xFFFFFFFF)
    h = (ix.astype(np.int64).astype(np.uint64) * np.uint64(0x8DA6B343)) ^ (iz.astype(np.int64).astype(np.uint64) * np.uint64(0xD8163841))
    h = (h ^ np.uint64((seed * 0x9E3779B1) & 0xFFFFFFFF)) & m
    h ^= h >> np.uint64(16)
    h = (h * np.uint64(0x7FEB352D)) & m
    h ^= h >> np.uint64(15)
    h = (h * np.uint64(0x846CA68B)) & m
    h ^= h >> np.uint64(16)
    return h


def gradient_noise(x: Array, z: Array, seed: int) -> Array:
    """2D gradient (Perlin) noise in about [-1, 1], one unit per lattice cell."""
    fx, fz = np.floor(x), np.floor(z)
    ix, iz = fx.astype(np.int64), fz.astype(np.int64)
    tx, tz = x - fx, z - fz
    out = np.zeros(np.shape(x))
    ux = tx * tx * tx * (tx * (tx * 6 - 15) + 10)
    uz = tz * tz * tz * (tz * (tz * 6 - 15) + 10)
    for dx in (0, 1):
        for dz in (0, 1):
            g = _GRADIENTS[(_hash(ix + dx, iz + dz, seed) & np.uint64(7)).astype(np.intp)]
            dot = g[..., 0] * (tx - dx) + g[..., 1] * (tz - dz)
            out += dot * (ux if dx else 1 - ux) * (uz if dz else 1 - uz)
    return np.asarray(out * 1.4142135, dtype=float)


def fbm(x: Array, z: Array, scale: float, octaves: int, roughness: float, seed: int, ridged: bool = False) -> Array:
    """Fractal noise in about [-1, 1]: `octaves` layers of gradient noise, each twice as fine and `roughness` as strong."""
    total = np.zeros(np.shape(x))
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        f = 2.0**o / scale
        n = gradient_noise(x * f + 17.17 * o, z * f - 31.31 * o, seed * 16 + o)
        if ridged:
            n = 1 - 2 * np.abs(n)
        total += amp * n
        norm += amp
        amp *= roughness
    return np.asarray(total / max(norm, 1e-9), dtype=float)


def spline(points: tuple[tuple[float, float], ...], spacing: float) -> Array:
    """A Catmull-Rom curve through `points`, sampled about every `spacing` metres: (n, 2)."""
    p = np.array(points, dtype=float)
    if len(p) == 2:
        n = max(1, math.ceil(float(np.linalg.norm(p[1] - p[0])) / spacing))
        t = np.linspace(0, 1, n + 1)[:, None]
        return np.asarray(p[0] + (p[1] - p[0]) * t, dtype=float)
    ext = np.concatenate([[2 * p[0] - p[1]], p, [2 * p[-1] - p[-2]]])
    out = [p[:1]]
    for k in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[k - 1], ext[k], ext[k + 1], ext[k + 2]
        n = max(1, math.ceil(float(np.linalg.norm(p2 - p1)) / spacing))
        t = np.linspace(0, 1, n + 1)[1:, None]
        out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t**2 + (3 * p1 - p0 - 3 * p2 + p3) * t**3))
    return np.concatenate(out)


def _smoothstep(t: Array) -> Array:
    t = np.clip(t, 0.0, 1.0)
    return np.asarray(t * t * (3 - 2 * t), dtype=float)


def _ramp(x: Array, fade: float) -> Array:
    """0 below -fade/2, 1 above +fade/2, smooth between (a hard step at fade 0)."""
    if fade <= 0:
        return (x >= 0).astype(float)
    return _smoothstep(x / fade + 0.5)


# --- the heightfield -----------------------------------------------------------------------------------------------


@dataclass
class Heightfield:
    """A terrain sampled on its grid: heights[iz, ix] at x = x0 + ix * cell, z = z0 + iz * cell; the distance to the
    nearest path's centre line and the splat weights (one per layer, summing to 1) at every grid point. Queries take
    any (x, z) (arrays) and interpolate bilinearly; points off the map clamp to its edge."""

    terrain: Terrain
    heights: Array  # (nz + 1, nx + 1) float64
    path_distance: Array  # (nz + 1, nx + 1) float32, NO_PATH where there is no path
    weights: Array  # (nz + 1, nx + 1, layers) float32
    shapes_outside: tuple[int, ...] = field(default=())  # shapes whose footprint misses the map (lint W117)

    @property
    def x0(self) -> float:
        return -self.terrain.size[0] / 2

    @property
    def z0(self) -> float:
        return -self.terrain.size[1] / 2

    @property
    def cell(self) -> float:
        return self.terrain.cell

    @property
    def layer_names(self) -> list[str]:
        return [layer.name for layer in self.terrain.layers]

    def _sample(self, grid: Array, x: Array, z: Array) -> Array:
        x, z = np.asarray(x, dtype=float), np.asarray(z, dtype=float)
        nz, nx = grid.shape[0] - 1, grid.shape[1] - 1
        gx = np.clip((x - self.x0) / self.cell, 0, nx)
        gz = np.clip((z - self.z0) / self.cell, 0, nz)
        ix = np.minimum(np.floor(gx).astype(np.intp), nx - 1)
        iz = np.minimum(np.floor(gz).astype(np.intp), nz - 1)
        tx, tz = gx - ix, gz - iz
        if grid.ndim == 3:
            tx, tz = tx[..., None], tz[..., None]
        a, b, c, d = grid[iz, ix], grid[iz, ix + 1], grid[iz + 1, ix], grid[iz + 1, ix + 1]
        return np.asarray((a * (1 - tx) + b * tx) * (1 - tz) + (c * (1 - tx) + d * tx) * tz, dtype=float)

    def height(self, x: Array | float, z: Array | float) -> Array:
        """Ground height (m) at (x, z)."""
        return self._sample(self.heights, np.asarray(x), np.asarray(z))

    def normal(self, x: Array | float, z: Array | float) -> Array:
        """Unit ground normal at (x, z): (..., 3)."""
        return _normals(self._sample(grid_gradient(self.heights, self.cell), np.asarray(x), np.asarray(z)))

    def slope(self, x: Array | float, z: Array | float) -> Array:
        """Ground slope at (x, z) in degrees (0 = flat)."""
        n = self.normal(x, z)
        return np.asarray(np.degrees(np.arccos(np.clip(n[..., 1], -1, 1))), dtype=float)

    def splat(self, x: Array | float, z: Array | float) -> Array:
        """Splat layer weights at (x, z): (..., layers), in the order of `layer_names`, summing to 1."""
        return self._sample(self.weights, np.asarray(x), np.asarray(z))

    def distance_to_path(self, x: Array | float, z: Array | float) -> Array:
        """Metres from (x, z) to the nearest path's centre line (NO_PATH far from any path)."""
        return self._sample(self.path_distance, np.asarray(x), np.asarray(z))

    def distance(self, points: Array) -> Array:
        """The heightfield as a distance field: y - height(x, z) for (n, 3) points (> 0 above the ground). A bound,
        not the exact distance, on slopes."""
        p = np.asarray(points, dtype=float)
        return np.asarray(p[..., 1] - self.height(p[..., 0], p[..., 2]), dtype=float)

    def bounds(self) -> tuple[Array, Array]:
        return (np.array([self.x0, float(self.heights.min()), self.z0]),
                np.array([-self.x0, float(self.heights.max()), -self.z0]))  # fmt: skip

    def colors(self) -> Array:
        """Every grid point's blended layer colour, linear RGB: (nz + 1, nx + 1, 3) float32."""
        from kiln.export import srgb_to_linear

        table = np.array([srgb_to_linear(layer.color) for layer in self.terrain.layers], dtype=np.float32)
        return np.asarray(self.weights @ table, dtype=np.float32)


def grid_gradient(h: Array, cell: float) -> Array:
    """(dh/dx, dh/dz) at every grid point (central differences, one-sided at the edges): (nz + 1, nx + 1, 2)."""
    return np.stack([np.gradient(h, cell, axis=1), np.gradient(h, cell, axis=0)], axis=-1)


def _normals(grad: Array) -> Array:
    n = np.stack([-grad[..., 0], np.ones(grad.shape[:-1]), -grad[..., 1]], axis=-1)
    return np.asarray(n / np.linalg.norm(n, axis=-1, keepdims=True), dtype=float)


def _polyline_distance(line: Array, xs: Array, zs: Array, reach: float, best: Array, along: Array | None = None) -> bool:
    """Lower `best` (a grid over xs x zs) to each point's distance from the polyline, only within `reach` of it; with
    `along`, also record the arc length of the nearest point. Returns whether any grid point was within reach."""
    seg = np.diff(line, axis=0)
    lengths = np.linalg.norm(seg, axis=1)
    start = np.concatenate([[0.0], np.cumsum(lengths)])
    cell = float(xs[1] - xs[0]) if len(xs) > 1 else 1.0
    touched = False
    for k in range(len(seg)):
        a, d, length = line[k], seg[k], lengths[k]
        if length <= 0:
            continue
        lo = np.minimum(a, a + d) - reach
        hi = np.maximum(a, a + d) + reach
        i0, i1 = max(0, int(math.floor((lo[0] - xs[0]) / cell))), min(len(xs), int(math.ceil((hi[0] - xs[0]) / cell)) + 1)
        j0, j1 = max(0, int(math.floor((lo[1] - zs[0]) / cell))), min(len(zs), int(math.ceil((hi[1] - zs[0]) / cell)) + 1)
        if i0 >= i1 or j0 >= j1:
            continue
        touched = True
        px = xs[i0:i1][None, :] - a[0]
        pz = zs[j0:j1][:, None] - a[1]
        t = np.clip((px * d[0] + pz * d[1]) / (length * length), 0.0, 1.0)
        dist = np.hypot(px - t * d[0], pz - t * d[1])
        window = best[j0:j1, i0:i1]
        closer = dist < window
        window[closer] = dist[closer]
        if along is not None:
            along[j0:j1, i0:i1][closer] = (start[k] + t * length)[closer]
    return touched


def _smax(a: Array, b: Array | float, k: float) -> Array:
    if k <= 0:
        return np.asarray(np.maximum(a, b), dtype=float)
    h = np.maximum(k - np.abs(a - b), 0.0) / k
    return np.asarray(np.maximum(a, b) + h * h * k * 0.25, dtype=float)


def _smin(a: Array, b: Array | float, k: float) -> Array:
    return -_smax(-a, -np.asarray(b), k)


def _bilinear(h: Array, x0: float, z0: float, cell: float, pts: Array) -> Array:
    nz, nx = h.shape[0] - 1, h.shape[1] - 1
    gx = np.clip((pts[:, 0] - x0) / cell, 0, nx)
    gz = np.clip((pts[:, 1] - z0) / cell, 0, nz)
    ix = np.minimum(np.floor(gx).astype(np.intp), nx - 1)
    iz = np.minimum(np.floor(gz).astype(np.intp), nz - 1)
    tx, tz = gx - ix, gz - iz
    return np.asarray((h[iz, ix] * (1 - tx) + h[iz, ix + 1] * tx) * (1 - tz) + (h[iz + 1, ix] * (1 - tx) + h[iz + 1, ix + 1] * tx) * tz, dtype=float)


def _footprint(shape: HeightShape, xs: Array, zs: Array, cell: float) -> tuple[Array, Array] | None:
    """(weight p, row/column window) of a hill or plateau; None when it misses the map."""
    rx, rz = shape.radius
    reach = max(rx, rz) + (shape.edge if shape.kind == "plateau" else 0.0)
    cx, cz = shape.at
    i0, i1 = np.searchsorted(xs, cx - reach), np.searchsorted(xs, cx + reach, side="right")
    j0, j1 = np.searchsorted(zs, cz - reach), np.searchsorted(zs, cz + reach, side="right")
    if i0 >= i1 or j0 >= j1:
        return None
    px, pz = xs[i0:i1][None, :] - cx, zs[j0:j1][:, None] - cz
    c, s = math.cos(math.radians(shape.rotate)), math.sin(math.radians(shape.rotate))
    u, v = c * px - s * pz, s * px + c * pz
    dn = np.hypot(u / rx, v / rz)  # 1 on the oval
    if shape.kind == "hill":
        p = _smoothstep(1 - dn)
    else:
        outside = (dn - 1) * min(rx, rz)  # metres past the top's rim (exact for circles)
        p = np.where(dn <= 1, 1.0, _smoothstep(1 - outside / shape.edge) if shape.edge > 0 else 0.0)
    return np.asarray(p, dtype=float), np.array([j0, j1, i0, i1])


def _apply(h: Array, p: Array, shape: HeightShape) -> None:
    """Blend a shape with weight p into the height window h (in place)."""
    if shape.blend == "add":
        h += shape.height * p
    elif shape.blend == "subtract":
        h -= shape.height * p
    elif shape.blend == "max":
        h += p * (_smax(h, shape.height, shape.smooth) - h)
    elif shape.blend == "min":
        h += p * (_smin(h, shape.height, shape.smooth) - h)
    else:
        h += p * (shape.height - h)


def _moving_average(values: Array, window: int) -> Array:
    if window <= 1 or len(values) < 3:
        return values
    pad = np.concatenate([np.full(window, values[0]), values, np.full(window, values[-1])])
    c = np.concatenate([[0.0], np.cumsum(pad)])
    out = (c[2 * window + 1 :] - c[: -2 * window - 1]) / (2 * window + 1)
    return np.asarray(out[: len(values)], dtype=float)


def compute(terrain: Terrain) -> Heightfield:
    """Sample the terrain on its grid: heights, then path distances and splat weights."""
    nx, nz = terrain.cells
    cell = terrain.cell
    xs = -terrain.size[0] / 2 + cell * np.arange(nx + 1)
    zs = -terrain.size[1] / 2 + cell * np.arange(nz + 1)
    h = np.full((nz + 1, nx + 1), terrain.base, dtype=float)
    paths = np.full((nz + 1, nx + 1), NO_PATH, dtype=float)
    outside = []
    for k, shape in enumerate(terrain.shapes):
        if shape.kind == "noise":
            for j0 in range(0, nz + 1, 256):  # in bands of rows: bounded memory on big maps
                j1 = min(nz + 1, j0 + 256)
                gx, gz = np.meshgrid(xs, zs[j0:j1])
                n = fbm(gx, gz, shape.scale, shape.octaves, shape.roughness, terrain.seed * 7919 + shape.seed, shape.ridged)
                h[j0:j1] += (shape.height if shape.blend == "add" else -shape.height) * n
            continue
        if shape.kind in ("hill", "plateau"):
            found = _footprint(shape, xs, zs, cell)
            if found is None:
                outside.append(k)
                continue
            p, (j0, j1, i0, i1) = found
            _apply(h[j0:j1, i0:i1], p, shape)
            continue
        line = spline(shape.points, cell)
        if shape.kind == "ridge":
            best = np.full(h.shape, np.inf)
            if not _polyline_distance(line, xs, zs, shape.width, best):
                outside.append(k)
                continue
            near = np.isfinite(best)
            window = h[near]
            _apply(window, _smoothstep(1 - best[near] / shape.width), shape)
            h[near] = window
            continue
        # a path: flatten to the ground's height smoothed along it, sunk by depth
        reach = shape.width / 2 + shape.edge
        best = np.full(h.shape, np.inf)
        along = np.zeros(h.shape)
        if not _polyline_distance(line, xs, zs, max(reach, cell), best, along):
            outside.append(k)
            continue
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))])
        ground = _bilinear(h, xs[0], zs[0], cell, line)
        step = float(arc[-1]) / max(len(arc) - 1, 1)
        span = max(1, int(round(shape.smooth / 2 / max(step, 1e-9))))
        level = _moving_average(_moving_average(ground, span), span) - shape.depth
        near = np.isfinite(best)
        d = best[near]
        p = np.where(d <= shape.width / 2, 1.0, _smoothstep(1 - (d - shape.width / 2) / shape.edge) if shape.edge > 0 else 0.0)
        target = np.interp(along[near], arc, level)
        h[near] += p * (target - h[near])
        paths = np.minimum(paths, np.where(np.isfinite(best), best, NO_PATH))
    field = Heightfield(terrain, h, paths.astype(np.float32), np.zeros((nz + 1, nx + 1, len(terrain.layers)), dtype=np.float32), tuple(outside))
    field.weights = _weights(field, xs, zs)
    return field


def _weights(field: Heightfield, xs: Array, zs: Array) -> Array:
    """Splat weights: each layer's opacity (its rules multiplied, times strength) painted over the layers before it."""
    t = field.terrain
    h = field.heights
    slope = np.degrees(np.arccos(np.clip(_normals(grid_gradient(h, t.cell))[..., 1], -1, 1)))
    out = np.zeros(h.shape + (len(t.layers),), dtype=np.float32)
    out[..., 0] = 1.0
    for k, layer in enumerate(t.layers[1:], start=1):
        alpha = np.full(h.shape, layer.strength)
        for rule in layer.rules:
            if rule.kind in ("slope", "height"):
                value = slope if rule.kind == "slope" else h
                if rule.above is not None:
                    alpha *= _ramp(value - rule.above, rule.fade)
                if rule.below is not None:
                    alpha *= _ramp(rule.below - value, rule.fade)
            elif rule.kind == "path":
                alpha *= _ramp(rule.within - field.path_distance, rule.fade)
            else:
                gx, gz = np.meshgrid(xs, zs)
                n = (fbm(gx, gz, rule.scale, 3, 0.5, t.seed * 104729 + rule.seed + 7 * k) + 1) / 2
                alpha *= _ramp(n - (1 - rule.cover), rule.fade)
        a = alpha.astype(np.float32)[..., None]
        out *= 1 - a
        out[..., k] += a[..., 0]
    return out


# --- meshes ----------------------------------------------------------------------------------------------------------


@dataclass
class ChunkMesh:
    """One chunk at one LOD, in the chunk's own space (its centre at the origin, heights as they are)."""

    ix: int  # chunk column (along x)
    iz: int  # chunk row (along z)
    centre: tuple[float, float]  # (x, z) of the chunk's centre on the map
    vertices: Array  # (n, 3) float32
    normals: Array  # (n, 3) float32
    colors: Array  # (n, 4) uint8 (linear RGB)
    uvs: Array  # (n, 2) float32: the splat map's texture coordinates
    faces: Array  # (m, 3) uint16 / uint32


def _lod_error(h: Array, step: int) -> float:
    """The largest height difference along grid lines between the full grid and every `step`-th point joined linearly."""
    if step == 1:
        return 0.0
    worst = 0.0
    for grid in (h, h.T):
        rows = grid[::step]  # grid lines kept at this LOD
        k = np.arange(rows.shape[1])
        lo = (k // step) * step
        hi = np.minimum(lo + step, rows.shape[1] - 1)
        t = np.where(hi > lo, (k - lo) / np.maximum(hi - lo, 1), 0.0)
        approx = rows[:, lo] * (1 - t) + rows[:, hi] * t
        worst = max(worst, float(np.abs(approx - rows).max()))
    return worst


def skirt_depth(field: Heightfield) -> float:
    """How far chunk edges hang down: the given `skirt`, else twice the coarsest LOD's height error plus a cell."""
    t = field.terrain
    if t.skirt is not None:
        return t.skirt
    return round(2 * _lod_error(field.heights, 2 ** len(t.lod)) + t.cell, 3)


def meshes(field: Heightfield, lod: int) -> list[ChunkMesh]:
    """Every chunk's mesh at a LOD (0 = every grid point; each LOD halves the points), with a skirt hanging from its edges
    so neighbours at other LODs never show cracks."""
    t = field.terrain
    step = 2**lod
    cc = t.chunk_cells
    n = cc // step + 1  # vertices per side
    cnx, cnz = t.chunks
    grad = grid_gradient(field.heights, t.cell)
    colors = field.colors()
    skirt = skirt_depth(field)
    nzp, nxp = field.heights.shape
    # one chunk's triangles (the same for all): quads split from (x0, z0) to (x1, z1), counter-clockwise seen from above
    q = np.arange(n * n).reshape(n, n)
    a, b, c, d = q[:-1, :-1].ravel(), q[:-1, 1:].ravel(), q[1:, :-1].ravel(), q[1:, 1:].ravel()
    top = np.concatenate([np.stack([a, c, b], axis=1), np.stack([b, c, d], axis=1)])
    ring = np.concatenate([q[0, :-1], q[:-1, -1], q[-1, :0:-1], q[:0:-1, 0]])  # around the edge: +x along z0, +z, -x, -z
    low = n * n + np.arange(len(ring))
    nxt = np.roll(np.arange(len(ring)), -1)
    sides = np.concatenate([np.stack([ring, ring[nxt], low], axis=1), np.stack([ring[nxt], low[nxt], low], axis=1)])
    faces = np.concatenate([top, sides]).astype(np.uint16 if n * n + len(ring) < 65535 else np.uint32)
    out = []
    for iz in range(cnz):
        for ix in range(cnx):
            gi = ix * cc + np.arange(0, cc + 1, step)
            gj = iz * cc + np.arange(0, cc + 1, step)
            jj, ii = np.meshgrid(gj, gi, indexing="ij")
            cx = -t.size[0] / 2 + (ix + 0.5) * t.chunk
            cz = -t.size[1] / 2 + (iz + 0.5) * t.chunk
            x = (-t.size[0] / 2 + ii * t.cell - cx).ravel()
            z = (-t.size[1] / 2 + jj * t.cell - cz).ravel()
            y = field.heights[jj, ii].ravel()
            verts = np.stack([x, y, z], axis=1)
            nrm = _normals(grad[jj, ii]).reshape(-1, 3)
            col = colors[jj, ii].reshape(-1, 3)
            uv = np.stack([((ii + 0.5) / nxp).ravel(), ((jj + 0.5) / nzp).ravel()], axis=1)
            hang = verts[ring] - np.array([0.0, skirt, 0.0])
            verts = np.concatenate([verts, hang])
            nrm = np.concatenate([nrm, nrm[ring]])
            col = np.concatenate([col, col[ring]])
            uv = np.concatenate([uv, uv[ring]])
            rgba = np.concatenate([np.clip(np.round(col * 255), 0, 255), np.full((len(col), 1), 255.0)], axis=1).astype(np.uint8)
            out.append(ChunkMesh(ix, iz, (cx, cz), verts.astype(np.float32), nrm.astype(np.float32), rgba, uv.astype(np.float32), faces))
    return out


def splat_png(field: Heightfield) -> bytes:
    """The splat map: one pixel per grid point (row = z, top = -z), RGB = the weights of layers 2-4 (0-255); layer 1 is
    what is left (1 - r - g - b). Rounded so the four always sum to 255."""
    import io

    from PIL import Image

    w = field.weights
    rgb = np.zeros(w.shape[:2] + (3,), dtype=np.uint8)
    if w.shape[2] > 1:
        q = np.round(w[..., 1:] * 255).astype(np.int32)
        total = q.sum(axis=-1)
        over = np.maximum(total - 255, 0)  # rounding up past 255: take it off the largest
        top = q.argmax(axis=-1)
        np.put_along_axis(q, top[..., None], np.take_along_axis(q, top[..., None], axis=-1) - over[..., None], axis=-1)
        rgb[..., : w.shape[2] - 1] = q.astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(rgb, "RGB").save(buf, format="PNG", optimize=False)
    return buf.getvalue()


# --- cache -------------------------------------------------------------------------------------------------------------


def cache_key(text: str, palette: dict[str, str]) -> str:
    from kiln import __version__

    h = hashlib.sha256(json.dumps([__version__, FORMAT, text, sorted(palette.items())]).encode())
    return h.hexdigest()[:32]


def heightfield_cached(name: str, terrain: Terrain, text: str, palette: dict[str, str], cache_dir: Path | None) -> Heightfield:
    """`compute`, kept in `.kiln-cache/<name>.terrain.<key>.pickle` (keyed by the model text and palette)."""
    if cache_dir is None:
        return compute(terrain)
    prefix = f"{name}.terrain."
    path = cache_dir / f"{prefix}{cache_key(text, palette)}.pickle"
    if path.is_file():
        try:
            with path.open("rb") as fh:
                found = pickle.load(fh)  # noqa: S301 - our own cache file
            if isinstance(found, Heightfield):
                found.terrain = terrain
                return found
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, TypeError):
            pass
    field_ = compute(terrain)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for old in cache_dir.glob(f"{prefix}*.pickle"):
        old.unlink(missing_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        pickle.dump(field_, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
    return field_


def load(project: Any, name: str) -> Heightfield:
    """The heightfield of the terrain model `name` in a project (`kiln.project.Project`), from the build cache when it can:
    what foliage scattering and other tools query (height, normal, slope, splat, distance_to_path)."""
    from kiln.notation import MODEL_SUFFIX

    model, _, findings = project.load(project.models_dir / f"{name}{MODEL_SUFFIX}")
    errors = [f for f in findings if f.severity == "error"]
    if model is None or errors or model.terrain is None:
        raise ValueError(f"{name}: not a terrain model" + (f" ({errors[0].format()})" if errors else ""))
    palette, _ = project.palette(model.palette)
    return heightfield_cached(name, model.terrain, model.text, palette, project.root / ".kiln-cache")


# --- files -----------------------------------------------------------------------------------------------------------


def chunks_glb(name: str, chunks: list[ChunkMesh], generator: str) -> bytes:
    """One LOD's chunks as a .glb: a root node `name` with a node `chunk_<ix>_<iz>` per chunk at its centre (so
    engines measure LOD distances from there), each with one primitive: POSITION, NORMAL, TEXCOORD_0 (the splat map),
    COLOR_0 (the blended layer colours, for engines without the splat shader) and the material `terrain`."""
    from kiln.vendor.gltf import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, Document

    doc = Document(generator)
    material = doc.add("materials", {"name": "terrain", "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.0,
                                                                                  "roughnessFactor": 1.0}})  # fmt: skip
    children = []
    for c in chunks:
        colour = doc.accessor(c.colors, target=ARRAY_BUFFER, byte=True)
        doc.json["accessors"][colour]["normalized"] = True
        attributes = {"POSITION": doc.accessor(c.vertices, target=ARRAY_BUFFER, bounds=True), "NORMAL": doc.accessor(c.normals, target=ARRAY_BUFFER),
                      "TEXCOORD_0": doc.accessor(c.uvs, target=ARRAY_BUFFER), "COLOR_0": colour}  # fmt: skip
        primitive = {"attributes": attributes, "indices": doc.accessor(c.faces.ravel(), target=ELEMENT_ARRAY_BUFFER), "material": material}
        mesh = doc.add("meshes", {"name": f"chunk_{c.ix}_{c.iz}", "primitives": [primitive]})
        children.append(doc.add("nodes", {"name": f"chunk_{c.ix}_{c.iz}", "mesh": mesh, "translation": [float(c.centre[0]), 0.0, float(c.centre[1])]}))
    root = doc.add("nodes", {"name": name, "children": children})
    doc.json["scenes"] = [{"nodes": [root]}]
    doc.json["scene"] = 0
    return doc.glb()


def probes(field: Heightfield) -> list[list[float]]:
    """A few [x, z, height] points (the centre and around it, on grid points): checks compare an engine's collision there."""
    t = field.terrain
    nx, nz = t.cells
    out = []
    for fx, fz in ((0.5, 0.5), (0.25, 0.25), (0.75, 0.3), (0.3, 0.75), (0.8, 0.8)):
        ix, iz = round(nx * fx), round(nz * fz)
        out.append([round(field.x0 + ix * t.cell, 4), round(field.z0 + iz * t.cell, 4), round(float(field.heights[iz, ix]), 4)])
    return out


SPLAT_SHADER = """shader_type spatial;
render_mode specular_disabled;
// KILN terrain: palette colours blended by the splat map (R, G, B = layers 2-4; layer 1 is the rest)
uniform sampler2D splat : hint_default_black, filter_linear, repeat_disable;
uniform vec4 color_0 : source_color = vec4(1.0);
uniform vec4 color_1 : source_color = vec4(1.0);
uniform vec4 color_2 : source_color = vec4(1.0);
uniform vec4 color_3 : source_color = vec4(1.0);
void fragment() {
\tvec3 w = texture(splat, UV).rgb;
\tfloat rest = clamp(1.0 - w.r - w.g - w.b, 0.0, 1.0);
\tALBEDO = color_0.rgb * rest + color_1.rgb * w.r + color_2.rgb * w.g + color_3.rgb * w.b;
\tROUGHNESS = 1.0;
}
"""

TOON_LIGHT = """uniform int bands = 3;
void light() {
\tfloat n = clamp((dot(NORMAL, LIGHT) + 0.15) / 1.15, 0.0, 0.999);
\tfloat lit = floor(n * float(bands)) / float(bands - 1);
\tDIFFUSE_LIGHT += vec3(lit) * ATTENUATION * LIGHT_COLOR * 0.9;
}
"""

TERRAIN_SCRIPT = """@tool
extends Node3D
# Written by `kiln build`: gives every chunk the splat material and shows each LOD between its distances.
@export var material: Material
@export var lod_ranges: Array = []  # LOD k shows from lod_ranges[k] to lod_ranges[k + 1] metres (the last: no end)
@export var lod_margin := 4.0  # metres of overlap between LODs (no flicker at the switch)

func _ready() -> void:
\tfor k in lod_ranges.size():
\t\tvar lod := get_node_or_null("lod%d" % k)
\t\tif lod == null:
\t\t\tcontinue
\t\tfor node in lod.find_children("*", "MeshInstance3D", true, false):
\t\t\tvar chunk := node as MeshInstance3D
\t\t\tif chunk.mesh == null:
\t\t\t\tcontinue
\t\t\tfor i in chunk.mesh.get_surface_count():
\t\t\t\tchunk.set_surface_override_material(i, material)
\t\t\tif lod_ranges.size() > 1:
\t\t\t\tchunk.visibility_range_begin = lod_ranges[k]
\t\t\t\tchunk.visibility_range_begin_margin = lod_margin if k > 0 else 0.0
\t\t\t\tchunk.visibility_range_end = lod_ranges[k + 1] if k + 1 < lod_ranges.size() else 0.0
\t\t\t\tchunk.visibility_range_end_margin = lod_margin if k + 1 < lod_ranges.size() else 0.0
"""


def _heights_text(values: Array) -> str:
    return ", ".join(f"{v:.6g}" for v in np.round(values.astype(np.float64), 4).ravel())


def godot_scene(name: str, field: Heightfield, glb_res: list[str], splat_res: str, style: Any) -> str:
    """`<name>.tscn`: the LOD glbs (chunks shown by distance), the splat material (palette colours from the splat
    map; the style's toon bands if it has them) and a StaticBody3D with a HeightMapShape3D (inline: no .tres sidecar)
    scaled to the grid (uniformly: heights are stored divided by the sample spacing)."""
    from kiln.godot import _color, _quote

    t = field.terrain
    toon = style.look.shader == "toon"
    shader = SPLAT_SHADER + (TOON_LIGHT if toon else "")
    lines = ["[gd_scene format=3]", ""]
    lines += [f'[ext_resource type="PackedScene" path={_quote(res)} id="{k + 1}_lod{k}"]' for k, res in enumerate(glb_res)]
    lines += [f'[ext_resource type="Texture2D" path={_quote(splat_res)} id="{len(glb_res) + 1}_splat"]', ""]
    lines += ['[sub_resource type="Shader" id="Shader_splat"]', f"code = {_quote(shader)}", ""]
    colours = [layer.color for layer in t.layers]
    colours += [colours[0]] * (MAX_LAYERS - len(colours))
    lines += ['[sub_resource type="ShaderMaterial" id="Material_splat"]', 'shader = SubResource("Shader_splat")',
              f'shader_parameter/splat = ExtResource("{len(glb_res) + 1}_splat")',
              *(f"shader_parameter/color_{k} = {_color(c)}" for k, c in enumerate(colours)),
              *([f"shader_parameter/bands = {style.look.toon_bands}"] if toon else []), ""]  # fmt: skip
    lines += ['[sub_resource type="GDScript" id="GDScript_terrain"]', f"script/source = {_quote(TERRAIN_SCRIPT)}", ""]
    if t.collision:
        step = t.collision
        grid = field.heights[::step, ::step]
        spacing = t.cell * step
        lines += ['[sub_resource type="HeightMapShape3D" id="Shape_height"]', f"map_width = {grid.shape[1]}", f"map_depth = {grid.shape[0]}",
                  f"map_data = PackedFloat32Array({_heights_text(grid / spacing)})", ""]  # fmt: skip
    ranges = [0.0, *t.lod][: len(glb_res)]
    lines += [f"[node name={_quote(name)} type=\"Node3D\"]", 'script = SubResource("GDScript_terrain")', 'material = SubResource("Material_splat")',
              f"lod_ranges = [{', '.join(f'{r:.6g}' for r in ranges)}]", f"metadata/kiln_style = {_quote(style.name)}", ""]  # fmt: skip
    for k in range(len(glb_res)):
        lines += [f'[node name="lod{k}" parent="." instance=ExtResource("{k + 1}_lod{k}")]', ""]
    if t.collision:
        s = f"{t.cell * t.collision:.6g}"
        lines += ['[node name="Collision" type="StaticBody3D" parent="."]', "", '[node name="Shape" type="CollisionShape3D" parent="Collision"]',
                  f"transform = Transform3D({s}, 0, 0, 0, {s}, 0, 0, 0, {s}, 0, 0, 0)", 'shape = SubResource("Shape_height")', ""]  # fmt: skip
    return "\n".join(lines)


__all__ = ["ChunkMesh", "HeightShape", "Heightfield", "Rule", "SplatLayer", "Terrain", "chunks_glb", "compute", "fbm", "godot_scene", "probes", "heightfield_cached", "load", "meshes",
           "parse", "skirt_depth", "splat_png"]  # fmt: skip
