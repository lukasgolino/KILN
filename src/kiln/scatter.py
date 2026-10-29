"""Scatters (`scatter:` in a model file): other models (grass, flowers, rocks, trees) placed many times over a surface
(a flat area, a terrain or another model's top surface) by density, minimum spacing and rules (slope, height,
noise patches, a terrain's splat layers and paths), each instance turned, scaled, leant and tinted at random.

KILN places the instances at build time: every value is rolled with Python's `random.Random` (stable across machines,
unlike numpy's streams), one stream per `place` entry, so editing one entry leaves the others where they were.
`kiln build` writes `models/<name>.scatter.json` (every instance's transform and tint) and, with "godot", a scene of
`MultiMeshInstance3D`s (one per entry, model and chunk; LODs added by its inline script).

The scatter's frame is the surface's: a terrain's map (centred on the origin), a model's exported frame (its glb's:
model space minus its `origin`), or a flat area centred on the origin at y = 0. Put the scatter scene under the
terrain or model it was made for.

Candidates: `density` x the area (m^2, seen from above) points, uniform over the area. A candidate is dropped where the
surface isn't (off a model), else kept with the probability its rules give (multiplied, each a smooth ramp), then
dropped if it is closer than `spacing` to an instance placed before it.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from kiln.sdf import Array
from kiln.terrain import Rule, _parse_rule, _ramp, fbm

FORMAT = 1
SCATTER_FIELDS = ("onto", "size", "seed", "chunk", "place")
RULES = ("slope", "height", "noise", "path", "splat")
PLACE_FIELDS = ("model", "density", "spacing", "scale", "rotate", "tilt", "align", "sink", "tint", "lod", "visible", *RULES)
MAX_CANDIDATES = 1_000_000  # per entry: density x area
MAX_INSTANCES = 200_000  # per scatter (E015 above): the scene and JSON hold every instance
MANY_INSTANCES = 50_000  # per entry (W118 above)
DRAWS = 10  # random numbers per candidate: x, z, keep, yaw, scale, lean, lean direction, shade, tint, pick
HELP = ("scatter is { onto: <terrain or model name> | flat, size: [x, z] (flat: required), seed: 0, chunk: 32, place: [- model: grass "
        "(or [grass, grass.dry]), density: 2 (per m^2), spacing: 0.3, scale: [0.8, 1.2], rotate: 360, tilt: 5, align: 0.5, sink: 0, "
        "tint: { color: gold, amount: 0.3, shade: 0.1 }, slope: { below: 30 }, height: { above: 0 }, noise: { scale: 8, cover: 0.5 }, "
        "splat: [grass], path: { beyond: 2 }, lod: [20, 50], visible: 80] }")  # fmt: skip


@dataclass(frozen=True)
class Tint:
    color: str | None = None  # hex: instances lean towards it by up to `amount`
    color_name: str = ""
    amount: float = 0.0
    shade: float = 0.0  # instances darken by up to this much (0-1)


@dataclass(frozen=True)
class Place:
    models: tuple[str, ...]  # "tree" or "tree.autumn" (a variant), picked evenly
    density: float  # candidates per m^2 of area (seen from above)
    spacing: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)
    rotate: tuple[float, float] = (0.0, 360.0)  # yaw (degrees) about the instance's up
    tilt: float = 0.0  # random lean up to this (degrees)
    align: float = 0.0  # 0: upright, 1: up along the surface normal
    sink: float = 0.0  # metres pushed into the surface
    tint: Tint | None = None
    lod: tuple[float, ...] = ()  # camera distances where the model's lod1, lod2, ... take over
    visible: float = 0.0  # hidden beyond this camera distance (0: always shown)
    rules: tuple[Rule, ...] = ()  # slope, height, noise (kiln.terrain rules)
    path: tuple[float | None, float | None, float] | None = None  # (within, beyond, fade) metres from a terrain path
    splat: tuple[str, ...] = ()  # a terrain's layers: kept with the probability of their summed weight
    where: str = ""
    line: int | None = None


@dataclass(frozen=True)
class Scatter:
    onto: str  # "flat" or a model name (terrain or a model)
    places: tuple[Place, ...]
    size: tuple[float, float] | None = None  # the area (centred on the origin); None: the whole terrain / model
    seed: int = 0
    chunk: float = 32.0

    @property
    def sources(self) -> list[str]:
        """Every model (or model.variant) placed, in first-use order."""
        out: list[str] = []
        for p in self.places:
            out += [m for m in p.models if m not in out]
        return out


# --- parsing ------------------------------------------------------------------------------------------------------

Error = Callable[[str, int | None, str], None]
ColorOf = Callable[[Any, int | None, str], tuple[str, str] | None]


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _line(data: Any, key: Any = None) -> int | None:
    from kiln.vendor.yamlio import LineMap

    if isinstance(data, LineMap):
        return data.line_of(key) if key is not None else data.line
    return None


def _range(v: Any, lo: float, hi: float) -> tuple[float, float] | None:
    if _num(v) and lo <= v <= hi:
        return float(v), float(v)
    if isinstance(v, list) and len(v) == 2 and all(_num(x) and lo <= x <= hi for x in v) and v[0] <= v[1]:
        return float(v[0]), float(v[1])
    return None


def parse(raw: Any, line: int | None, error: Error, color: ColorOf) -> Scatter | None:
    """A `scatter:` block; problems go to error(message, line, where)."""
    from kiln.notation import NAME_RE

    if not isinstance(raw, dict):
        error(HELP, line, "scatter")
        return None
    ok = True

    def bad(message: str, key: str, at: Any = raw) -> None:
        nonlocal ok
        ok = False
        error(message, _line(at, key.split(".")[-1]) or _line(at) or line, f"scatter.{key}")

    unknown = [str(k) for k in raw if k not in SCATTER_FIELDS]
    if unknown:
        bad(f"unknown field(s) {', '.join(unknown)}; allowed: {', '.join(SCATTER_FIELDS)}", unknown[0])
    onto = raw.get("onto")
    if not isinstance(onto, str) or not NAME_RE.match(onto):
        bad("onto is the model to scatter over: a terrain, another model (its top surface) or flat (with size)", "onto")
        onto = "flat"
    size: tuple[float, float] | None = None
    if "size" in raw:
        s = raw["size"]
        if _num(s):
            s = [s, s]
        if isinstance(s, list) and len(s) == 2 and all(_num(v) and 0 < v <= 4096 for v in s):
            size = (float(s[0]), float(s[1]))
        else:
            bad("size is the area [x, z] in metres (or one number for a square), centred on the origin, up to 4096", "size")
    elif onto == "flat":
        bad("a flat scatter needs size: [x, z] metres (the area, centred on the origin)", "onto")
    seed = raw.get("seed", 0)
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        bad("seed is a whole number (same seed, same placement)", "seed")
        seed = 0
    chunk = raw.get("chunk", 32)
    if not _num(chunk) or not 1 <= chunk <= 1024:
        bad("chunk is the cell size in metres (1-1024) the instances are grouped by (one MultiMesh each: culling, LODs), e.g. 32", "chunk")
        chunk = 32
    places = raw.get("place")
    out: list[Place] = []
    if not isinstance(places, list) or not places:
        bad("place is a list of what to scatter: - model: grass, density: 2 (per m^2), ...", "place")
    else:
        for i, item in enumerate(places):
            p = _parse_place(item, i, _line(item) or _line(raw, "place") or line, bad, color)
            if p is not None:
                out.append(p)
    if not ok or len(out) != len(places or []):
        return None
    return Scatter(onto, tuple(out), size, seed, float(chunk))


def _parse_place(item: Any, i: int, line: int | None, bad: Callable[..., None], color: ColorOf) -> Place | None:
    from kiln.notation import NAME_RE

    where = f"place[{i}]"
    if not isinstance(item, dict):
        bad("each place entry is { model: grass, density: 2, ... }", where, item)
        return None
    problems: list[tuple[str, str]] = []
    unknown = [str(k) for k in item if k not in PLACE_FIELDS]
    if unknown:
        problems.append((f"unknown field(s) {', '.join(unknown)}; allowed: {', '.join(PLACE_FIELDS)}", unknown[0]))
    models = item.get("model")
    if isinstance(models, str):
        models = [models]
    names: tuple[str, ...] = ()
    if not isinstance(models, list) or not models or not all(isinstance(m, str) and all(NAME_RE.match(x) for x in m.split(".")) and m.count(".") <= 1
                                                             for m in models) or len(set(models)) != len(models):  # fmt: skip
        problems.append(("model is a model name, name.variant, or a list of them (picked evenly), e.g. [grass, grass.dry]", "model"))
    else:
        names = tuple(models)
    density: Any = item.get("density")
    if not _num(density) or not 0 < density <= 1000:
        problems.append(("density is instances per m^2 (0-1000) before rules and spacing thin them, e.g. 2 for grass, 0.01 for trees", "density"))
        density = 1.0

    def number(key: str, default: float, lo: float, hi: float, text: str) -> float:
        v = item.get(key, default)
        if not _num(v) or not lo <= v <= hi:
            problems.append((text, key))
            return default
        return float(v)

    spacing = number("spacing", 0.0, 0, 1000, "spacing is the least distance in metres to any instance placed before (0: none)")
    scale = _range(item.get("scale", 1.0), 0.001, 1000)
    if scale is None:
        problems.append(("scale is a factor or [lo, hi] (picked evenly), e.g. [0.8, 1.2]", "scale"))
        scale = (1.0, 1.0)
    rot = item.get("rotate", 360)
    rotate = (0.0, float(rot)) if _num(rot) and 0 <= rot <= 360 else _range(rot, -360, 360)
    if rotate is None:
        problems.append(("rotate is the yaw jitter in degrees: 360 (any way round, the default), 0 (none) or [lo, hi]", "rotate"))
        rotate = (0.0, 360.0)
    tilt = number("tilt", 0.0, 0, 90, "tilt is a random lean up to this many degrees (0-90)")
    align = number("align", 0.0, 0, 1, "align is 0 (upright) to 1 (up along the surface's normal)")
    sink = number("sink", 0.0, -100, 100, "sink is how far instances go into the surface, in metres (hides bases on slopes)")
    visible = number("visible", 0.0, 0, 100000, "visible is the camera distance in metres beyond which instances are hidden (0: always)")
    lod = item.get("lod", [])
    if not isinstance(lod, list) or len(lod) > 4 or not all(_num(d) and d > 0 for d in lod) or any(b <= a for a, b in zip(lod, lod[1:], strict=False)):
        problems.append(("lod is up to 4 increasing camera distances in metres where the model's lod1, lod2, ... take over, e.g. [20, 50]", "lod"))
        lod = []
    if visible and lod and visible <= lod[-1]:
        problems.append(("visible must be beyond the last lod distance", "visible"))
    tint = _parse_tint(item.get("tint"), _line(item, "tint") or line, f"scatter.{where}.tint", problems, color) if "tint" in item else None
    rules = []
    for kind in ("slope", "height", "noise"):
        if kind in item:
            rule, problem = _parse_rule(kind, item[kind])
            if problem:
                problems.append((problem, kind))
            elif rule is not None:
                rules.append(rule)
    path = None
    if "path" in item:
        raw = item["path"]
        text = "path is { within: m, beyond: m, fade: 1 }: near a terrain's paths (within metres of a centre line) or away from them (beyond)"
        if not isinstance(raw, dict) or set(raw) - {"within", "beyond", "fade"} or not ({"within", "beyond"} & set(raw)) \
                or not all(_num(raw.get(k, 1.0)) and raw.get(k, 1.0) >= 0 for k in ("within", "beyond", "fade")):  # fmt: skip
            problems.append((text, "path"))
        else:
            within, beyond = raw.get("within"), raw.get("beyond")
            path = (None if within is None else float(within), None if beyond is None else float(beyond), float(raw.get("fade", 1.0)))
    splat: tuple[str, ...] = ()
    if "splat" in item:
        s = item["splat"]
        s = [s] if isinstance(s, str) else s
        if not isinstance(s, list) or not s or not all(isinstance(x, str) for x in s):
            problems.append(("splat is a terrain's layer name or a list of them: kept as often as their weight (1 = always)", "splat"))
        else:
            splat = tuple(s)
    for message, key in problems:
        bad(message, f"{where}.{key}", item)
    if problems:
        return None
    return Place(names, float(density), spacing, scale, rotate, tilt, align, sink, tint, tuple(float(d) for d in lod), visible, tuple(rules), path,
                 splat, f"scatter.{where}", line)  # fmt: skip


def _parse_tint(raw: Any, line: int | None, where: str, problems: list[tuple[str, str]], color: ColorOf) -> Tint | None:
    text = "tint is a shade (0-1: instances darken by up to that much) or { color: <palette colour>, amount: 0-1, shade: 0-1 }"
    if _num(raw):
        if not 0 <= raw <= 1:
            problems.append((text, "tint"))
            return None
        return Tint(shade=float(raw))
    if not isinstance(raw, dict) or set(raw) - {"color", "amount", "shade"} or not all(_num(raw.get(k, 0)) and 0 <= raw.get(k, 0) <= 1 for k in ("amount", "shade")):
        problems.append((text, "tint"))
        return None
    hexed = None
    if "color" in raw:
        hexed = color(raw["color"], line, f"{where}.color")
        if hexed is None:
            return None  # reported (E004)
    amount = float(raw.get("amount", 0.3 if hexed else 0.0))
    return Tint(hexed[0] if hexed else None, hexed[1] if hexed else "", amount, float(raw.get("shade", 0.0)))


# --- surfaces -------------------------------------------------------------------------------------------------------


@dataclass
class Surface:
    """What instances stand on, seen from above: `hit(x, z)` -> (found, y, unit normal)."""

    kind: str  # flat | terrain | model
    lo: tuple[float, float]  # the area's corners (x, z)
    hi: tuple[float, float]
    field: Any = None  # terrain: kiln.terrain.Heightfield
    vertices: Array | None = None  # model: its mesh in the scatter's frame
    faces: Array | None = None
    layers: tuple[str, ...] = ()

    @property
    def area(self) -> float:
        return (self.hi[0] - self.lo[0]) * (self.hi[1] - self.lo[1])

    def hit(self, x: Array, z: Array) -> tuple[Array, Array, Array]:
        n = len(x)
        if self.kind == "flat":
            return np.ones(n, dtype=bool), np.zeros(n), np.tile([0.0, 1.0, 0.0], (n, 1))
        if self.kind == "terrain":
            return np.ones(n, dtype=bool), self.field.height(x, z), self.field.normal(x, z).reshape(n, 3)
        assert self.vertices is not None and self.faces is not None
        return _top_hits(self.vertices, self.faces, x, z)


def _top_hits(vertices: Array, faces: Array, x: Array, z: Array) -> tuple[Array, Array, Array]:
    """For points (x, z): the top-most triangle straight above/below them (a ray from high above), its height and
    normal; found only where that top-most triangle faces up."""
    n = len(x)
    best = np.full(n, -np.inf)
    normal = np.zeros((n, 3))
    if n == 0:
        return np.zeros(0, dtype=bool), best, normal
    order = np.argsort(x, kind="stable")
    xs = x[order]
    tri = vertices[faces]  # (F, 3, 3)
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(fn, axis=1)
    keep = (length > 1e-12) & (np.abs(fn[:, 1]) > 1e-9 * np.maximum(length, 1e-30))  # not degenerate, not vertical
    for f in np.nonzero(keep)[0]:
        a, b, c = tri[f]
        lo = np.searchsorted(xs, min(a[0], b[0], c[0]), "left")
        hi = np.searchsorted(xs, max(a[0], b[0], c[0]), "right")
        if lo >= hi:
            continue
        idx = order[lo:hi]
        pz = z[idx]
        inside = (pz >= min(a[2], b[2], c[2])) & (pz <= max(a[2], b[2], c[2]))
        if not inside.any():
            continue
        idx = idx[inside]
        px, pz = x[idx], z[idx]
        d = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
        w0 = ((b[2] - c[2]) * (px - c[0]) + (c[0] - b[0]) * (pz - c[2])) / d
        w1 = ((c[2] - a[2]) * (px - c[0]) + (a[0] - c[0]) * (pz - c[2])) / d
        w2 = 1 - w0 - w1
        eps = -1e-9
        on = (w0 >= eps) & (w1 >= eps) & (w2 >= eps)
        idx, y = idx[on], (w0 * a[1] + w1 * b[1] + w2 * c[1])[on]
        higher = y > best[idx]
        best[idx[higher]] = y[higher]
        normal[idx[higher]] = fn[f] / length[f]
    found = np.isfinite(best) & (normal[:, 1] > 0)
    return found, np.where(found, best, 0.0), normal


Problem = tuple[str, str, int | None]  # (message, where, line)


def surface_of(project: Any, scatter: Scatter, cache: Path | None) -> tuple[Surface | None, list[Problem]]:
    """The surface a scatter stands on (a terrain's heightfield, a model's built mesh in its exported frame, or a flat
    area) and its area; problems when `onto` isn't something to scatter over."""
    from kiln.builder import build_cached
    from kiln.notation import MODEL_SUFFIX
    from kiln.terrain import heightfield_cached

    size = scatter.size
    if scatter.onto == "flat":
        assert size is not None
        return Surface("flat", (-size[0] / 2, -size[1] / 2), (size[0] / 2, size[1] / 2)), []
    path = project.models_dir / f"{scatter.onto}{MODEL_SUFFIX}"
    if not path.is_file():
        return None, [(f"onto names {scatter.onto}: no models/{scatter.onto}{MODEL_SUFFIX} (a terrain or a model to scatter over, or flat)", "scatter.onto", None)]
    model, style, findings = project.load(path)
    if model is None or style is None or any(f.severity == "error" for f in findings):
        return None, [(f"onto {scatter.onto}: that model has errors (lint it first)", "scatter.onto", None)]
    if model.scatter is not None or model.template or model.animations_only:
        return None, [(f"onto {scatter.onto}: scatter over a terrain or a model with a surface (not a scatter, template or clip carrier)", "scatter.onto", None)]
    palette, _ = project.palette(model.palette)
    if model.terrain is not None:
        field_ = heightfield_cached(model.name, model.terrain, model.text, palette, cache)
        lo, hi = field_.bounds()
        if size is not None and (size[0] > hi[0] - lo[0] + 1e-9 or size[1] > hi[2] - lo[2] + 1e-9):
            return None, [(f"size {size[0]:g} x {size[1]:g} m is larger than the terrain ({hi[0] - lo[0]:g} x {hi[2] - lo[2]:g} m)", "scatter.size", None)]
        x, z = (size[0] / 2, size[1] / 2) if size is not None else (float(hi[0]), float(hi[2]))
        return Surface("terrain", (-x, -z), (x, z), field=field_, layers=tuple(field_.layer_names)), []
    try:
        built = build_cached(model, style, palette, cache)
    except ValueError as exc:
        return None, [(f"onto {scatter.onto}: it doesn't build ({exc})", "scatter.onto", None)]
    vertices = built.painted.vertices - built.origin()  # the glb's frame
    faces = built.painted.faces
    if size is not None:
        lo2, hi2 = (-size[0] / 2, -size[1] / 2), (size[0] / 2, size[1] / 2)
    else:
        used = vertices[np.unique(faces)]
        lo2 = (float(used[:, 0].min()), float(used[:, 2].min()))
        hi2 = (float(used[:, 0].max()), float(used[:, 2].max()))
    return Surface("model", lo2, hi2, vertices=vertices, faces=faces), []


def problems(project: Any, scatter: Scatter, surface: Surface | None) -> list[Problem]:
    """What can't be scattered: unknown or unsuitable models and variants, more LODs than a model has, terrain-only
    rules elsewhere, unknown splat layers, too many candidates."""
    from kiln.notation import MODEL_SUFFIX

    out: list[Problem] = []
    for k, p in enumerate(scatter.places):
        where = f"scatter.place[{k}]"
        for source in p.models:
            name, _, variant = source.partition(".")
            path = project.models_dir / f"{name}{MODEL_SUFFIX}"
            if not path.is_file():
                out.append((f"model {name}: no models/{name}{MODEL_SUFFIX}", f"{where}.model", p.line))
                continue
            model, _, findings = project.load(path)
            if model is None or any(f.severity == "error" for f in findings):
                out.append((f"model {name} has errors (lint it first)", f"{where}.model", p.line))
                continue
            if model.terrain is not None or model.scatter is not None or model.template or model.animations_only:
                out.append((f"model {name} is a terrain, scatter, template or clip carrier: scatter ordinary models", f"{where}.model", p.line))
            elif model.rig or model.skin != "none" or model.skeleton is not None:
                out.append((f"model {name} has a rig: scatter static models (one mesh; MultiMesh instances don't animate)", f"{where}.model", p.line))
            if variant and variant not in model.variants:
                known = ", ".join(sorted(model.variants)) or "none"
                out.append((f"model {name} has no variant {variant} (variants: {known})", f"{where}.model", p.line))
            if len(p.lod) > len(model.lod):
                out.append((f"lod has {len(p.lod)} distances but model {name} has {len(model.lod)} LODs (its lod: budgets)", f"{where}.lod", p.line))
        if surface is not None and surface.kind != "terrain" and (p.path is not None or p.splat):
            out.append(("path and splat rules need a terrain under them (onto: <terrain>)", f"{where}.{'path' if p.path is not None else 'splat'}", p.line))
        if surface is not None and surface.kind == "terrain":
            unknown = [s for s in p.splat if s not in surface.layers]
            if unknown:
                out.append((f"splat names {', '.join(unknown)}: the terrain's layers are {', '.join(surface.layers)}", f"{where}.splat", p.line))
            if p.path is not None and not any(s.kind == "path" for s in surface.field.terrain.shapes):
                out.append(("path rule: the terrain has no paths", f"{where}.path", p.line))
        if surface is not None:
            n = round(p.density * surface.area)
            if n > MAX_CANDIDATES:
                out.append((f"density {p.density:g} over {surface.area:.0f} m^2 is {n} candidates (at most {MAX_CANDIDATES}): lower the density or "
                            "scatter a smaller size", f"{where}.density", p.line))  # fmt: skip
    return list(dict.fromkeys(out))  # a model named twice (tree, tree.autumn): once


# --- placing --------------------------------------------------------------------------------------------------------


@dataclass
class Group:
    """One entry's instances of one model (or variant), sorted by chunk."""

    place: int  # index into scatter.places
    source: str  # model or model.variant
    transforms: Array  # (n, 12): x, y, z, then the model's x, y, z axes (scale included) in the scatter's frame
    colors: Array | None  # (n, 3) linear RGB multipliers, None when the entry has no tint
    chunks: list[tuple[int, int, int, int]] = field(default_factory=list)  # (ix, iz, first, count)

    @property
    def node(self) -> str:
        return f"p{self.place}_{self.source.replace('.', '_')}"

    @property
    def model(self) -> str:
        return self.source.split(".")[0]

    @property
    def variant(self) -> str | None:
        return self.source.split(".")[1] if "." in self.source else None


@dataclass
class Placed:
    scatter: Scatter
    surface: Surface
    groups: list[Group]
    candidates: list[int]  # per entry
    counts: list[int]  # per entry: instances placed

    @property
    def total(self) -> int:
        return sum(self.counts)


def candidates(scatter: Scatter, area: float) -> list[int]:
    return [round(p.density * area) for p in scatter.places]


def _rotation_to(up: Array) -> Array:
    """(n, 3, 3) rotations taking +Y onto the unit vectors `up` (the shortest turn)."""
    n = len(up)
    y = np.array([0.0, 1.0, 0.0])
    axis = np.cross(np.broadcast_to(y, up.shape), up)
    s = np.linalg.norm(axis, axis=1)
    c = up[:, 1]
    k = np.where(s[:, None] > 1e-12, axis / np.maximum(s, 1e-12)[:, None], np.array([1.0, 0.0, 0.0]))
    kx, ky, kz = k[:, 0], k[:, 1], k[:, 2]
    zero = np.zeros(n)
    kmat = np.stack([np.stack([zero, -kz, ky], 1), np.stack([kz, zero, -kx], 1), np.stack([-ky, kx, zero], 1)], 1)
    eye = np.broadcast_to(np.eye(3), (n, 3, 3))
    return np.asarray(eye + s[:, None, None] * kmat + (1 - c)[:, None, None] * (kmat @ kmat), dtype=float)


def _keep_probability(p: Place, surface: Surface, x: Array, y: Array, z: Array, normal: Array, seed: int, k: int) -> Array:
    prob = np.ones(len(x))
    slope = np.degrees(np.arccos(np.clip(normal[:, 1], -1, 1)))
    for rule in p.rules:
        if rule.kind in ("slope", "height"):
            value = slope if rule.kind == "slope" else y
            if rule.above is not None:
                prob *= _ramp(value - rule.above, rule.fade)
            if rule.below is not None:
                prob *= _ramp(rule.below - value, rule.fade)
        else:  # noise patches: the same lattice noise as terrain splats
            n = (fbm(x, z, rule.scale, 3, 0.5, seed * 104729 + rule.seed + 7 * k + 1) + 1) / 2
            prob *= _ramp(n - (1 - rule.cover), rule.fade)
    if p.path is not None:
        d = surface.field.distance_to_path(x, z)
        within, beyond, fade = p.path
        if within is not None:
            prob *= _ramp(within - d, fade)
        if beyond is not None:
            prob *= _ramp(d - beyond, fade)
    if p.splat:
        w = surface.field.splat(x, z).reshape(len(x), -1)
        prob *= np.clip(sum(w[:, surface.layers.index(name)] for name in p.splat), 0.0, 1.0)
    return prob


class _Spacing:
    """Instances placed so far on a grid of `cell` metres (at least the largest spacing): who is too close."""

    def __init__(self, cell: float) -> None:
        self.cell = max(cell, 1e-6)
        self.grid: dict[tuple[int, int], list[tuple[float, float, float]]] = {}
        self.used = True  # whether anything checks spacing after the current entry

    def add(self, x: float, z: float, spacing: float) -> None:
        self.grid.setdefault((math.floor(x / self.cell), math.floor(z / self.cell)), []).append((x, z, spacing))

    def free(self, x: float, z: float, spacing: float) -> bool:
        cx, cz = math.floor(x / self.cell), math.floor(z / self.cell)
        for i in (cx - 1, cx, cx + 1):
            for j in (cz - 1, cz, cz + 1):
                for ox, oz, os_ in self.grid.get((i, j), ()):
                    need = max(spacing, os_)
                    if (ox - x) ** 2 + (oz - z) ** 2 < need * need:
                        return False
        return True


def place(scatter: Scatter, surface: Surface) -> Placed:
    """Every instance of every entry, rolled from the seed."""
    from kiln.export import srgb_to_linear

    widest = max(p.spacing for p in scatter.places)
    spacing = _Spacing(widest)
    spacing.used = any(p.spacing > 0 for p in scatter.places[1:])
    groups: list[Group] = []
    counts, cands = [], candidates(scatter, surface.area)
    (x0, z0), (x1, z1) = surface.lo, surface.hi
    for k, p in enumerate(scatter.places):
        n = cands[k]
        rng = random.Random(f"kiln-scatter:{scatter.seed}:{k}")
        u = np.array([rng.random() for _ in range(n * DRAWS)], dtype=float).reshape(n, DRAWS)
        x = x0 + (x1 - x0) * u[:, 0]
        z = z0 + (z1 - z0) * u[:, 1]
        found, y, normal = surface.hit(x, z)
        prob = _keep_probability(p, surface, x, y, z, normal, scatter.seed, k)
        idx = np.nonzero(found & (u[:, 2] < prob))[0]
        if p.spacing > 0:
            kept = []
            for i in idx:
                xi, zi = float(x[i]), float(z[i])
                if spacing.free(xi, zi, p.spacing):
                    spacing.add(xi, zi, p.spacing)
                    kept.append(i)
            idx = np.array(kept, dtype=np.intp)
        elif spacing.used:  # later entries keep their spacing from these too
            for i in idx:
                spacing.add(float(x[i]), float(z[i]), 0.0)
        counts.append(len(idx))
        if not len(idx):
            continue
        uu, n_hat = u[idx], normal[idx]
        up = np.array([0.0, 1.0, 0.0]) * (1 - p.align) + n_hat * p.align
        up /= np.linalg.norm(up, axis=1)[:, None]
        lean = np.radians(p.tilt * uu[:, 5])
        heading = 2 * math.pi * uu[:, 6]
        lean_dir = np.stack([np.cos(heading) * np.sin(lean), np.cos(lean), np.sin(heading) * np.sin(lean)], axis=1)
        turn = _rotation_to(up) @ _rotation_to(lean_dir)  # lean in the up's own frame, then up onto the surface
        yaw = np.radians(p.rotate[0] + (p.rotate[1] - p.rotate[0]) * uu[:, 3])
        cy, sy = np.cos(yaw), np.sin(yaw)
        zero, one = np.zeros(len(idx)), np.ones(len(idx))
        ry = np.stack([np.stack([cy, zero, sy], 1), np.stack([zero, one, zero], 1), np.stack([-sy, zero, cy], 1)], 1)
        scale = p.scale[0] + (p.scale[1] - p.scale[0]) * uu[:, 4]
        basis = turn @ ry * scale[:, None, None]
        at = np.stack([x[idx], y[idx] - p.sink, z[idx]], axis=1)
        transforms = np.concatenate([at, basis[:, :, 0], basis[:, :, 1], basis[:, :, 2]], axis=1)
        colors = None
        if p.tint is not None:
            t = p.tint
            target = np.array(srgb_to_linear(t.color) if t.color else [1.0, 1.0, 1.0])
            mix = (t.amount * uu[:, 8])[:, None]
            colors = (1 - mix) + mix * target
            colors *= (1 - t.shade * uu[:, 7])[:, None]
        pick = np.minimum((uu[:, 9] * len(p.models)).astype(int), len(p.models) - 1)
        cx = np.clip(np.floor((x[idx] - x0) / scatter.chunk), 0, None).astype(int)
        cz = np.clip(np.floor((z[idx] - z0) / scatter.chunk), 0, None).astype(int)
        for m, source in enumerate(p.models):
            sel = np.nonzero(pick == m)[0]
            if not len(sel):
                continue
            order = sel[np.lexsort((sel, cx[sel], cz[sel]))]  # by chunk (z rows, then x), draw order within
            g = Group(k, source, np.round(transforms[order], 4) + 0.0, None if colors is None else np.round(colors[order], 4) + 0.0)
            first = 0
            keys = list(zip(cz[order].tolist(), cx[order].tolist(), strict=True))
            while first < len(keys):
                last = first
                while last < len(keys) and keys[last] == keys[first]:
                    last += 1
                g.chunks.append((keys[first][1], keys[first][0], first, last - first))
                first = last
            groups.append(g)
    return Placed(scatter, surface, groups, cands, counts)


# --- files ---------------------------------------------------------------------------------------------------------


def _r(v: float) -> float:
    return round(float(v), 4) + 0.0


def to_json(placed: Placed, files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The scatter file: where it scatters and, per group (entry x model), its files, settings, chunks and instances."""
    s = placed.scatter
    surface = placed.surface
    groups = []
    for g in placed.groups:
        p = s.places[g.place]
        groups.append({
            "node": g.node, "place": g.place, "model": g.model, **({"variant": g.variant} if g.variant else {}), **files.get(g.source, {}),
            "count": len(g.transforms), "lod_distances": [_r(d) for d in p.lod], "visible": _r(p.visible),
            "chunks": [{"node": f"chunk_{ix}_{iz}", "first": first, "count": count} for ix, iz, first, count in g.chunks],
            "instances": g.transforms.tolist(), **({"colors": g.colors.tolist()} if g.colors is not None else {}),
        })  # fmt: skip
    return {
        "format": FORMAT,
        "seed": s.seed,
        "onto": {"kind": surface.kind, **({"model": s.onto} if surface.kind != "flat" else {})},
        "area": {"min": [_r(v) for v in surface.lo], "max": [_r(v) for v in surface.hi]},
        "chunk": _r(s.chunk),
        "transform": "an instance is [x, y, z, ax, ay, az, bx, by, bz, cx, cy, cz]: the model's origin (its feet) at (x, y, z) and its x, y, z "
                     "axes (scale included) a, b, c in the scatter's frame; colors (with a tint) are linear RGB multipliers (instance colours)",
        "groups": groups,
    }  # fmt: skip


def mesh_frame(glb: bytes, origin: list[float] | None) -> tuple[Array | None, str]:
    """The (4, 4) transform from a single-mesh glb's mesh node to the model's own space (the node's transforms, then
    the model's `origin` shift back), or (None, why) when the glb has several meshes or a skin."""
    from kiln.vendor.gltf import read_glb

    doc, _ = read_glb(glb)
    if doc.get("skins"):
        return None, "it has a skin (scatter static models)"
    nodes = doc.get("nodes", [])
    meshed = [i for i, n in enumerate(nodes) if "mesh" in n]
    if len(meshed) != 1:
        return None, f"it has {len(meshed)} mesh nodes (scatter models made of one mesh: no rig)"
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    m = np.eye(4)
    i: int | None = meshed[0]
    while i is not None:
        m = _trs(nodes[i]) @ m
        i = parent.get(i)
    shift = np.eye(4)
    if origin:
        shift[:3, 3] = origin
    return shift @ m, ""


def _trs(node: dict[str, Any]) -> Array:
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    x, y, z, w = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])  # fmt: skip
    m = np.eye(4)
    m[:3, :3] = r * np.array(node.get("scale", [1.0, 1.0, 1.0]))[None, :]
    m[:3, 3] = node.get("translation", [0.0, 0.0, 0.0])
    return m


SCATTER_SCRIPT = """@tool
extends Node3D
# Written by `kiln build`: gives every MultiMesh its model's mesh with the materials the model's own scene sets up (the
# style's look; tinted groups let instance colours through) and adds the model's LODs, each shown between its distances.
@export var sources: Array = []  # per source: the model's (or variant's) scene
@export var lods: Array = []  # per source: its LOD glbs [lod1, lod2, ...]
@export var lod_margin := 2.0  # metres of overlap between LODs

func _ready() -> void:
\tvar meshes := {}
\tfor group in get_children():
\t\tif not group.has_meta("kiln_source"):
\t\t\tcontinue
\t\tvar k: int = group.get_meta("kiln_source")
\t\tvar ranges: Array = group.get_meta("kiln_lod_ranges", [0.0])
\t\tvar far: float = group.get_meta("kiln_visible", 0.0)
\t\tvar tinted: bool = group.get_meta("kiln_tinted", false)
\t\tfor chunk in group.get_children():
\t\t\tvar base := chunk as MultiMeshInstance3D
\t\t\tif base == null or base.multimesh == null or base.has_meta("kiln_lod"):
\t\t\t\tcontinue
\t\t\tfor lod in ranges.size():
\t\t\t\tvar key := "%d/%d/%s" % [k, lod, tinted]
\t\t\t\tif not meshes.has(key):
\t\t\t\t\tmeshes[key] = _mesh(k, lod, tinted, meshes)
\t\t\t\tvar node := base
\t\t\t\tif lod > 0:
\t\t\t\t\tnode = MultiMeshInstance3D.new()
\t\t\t\t\tnode.name = "%s_lod%d" % [base.name, lod]
\t\t\t\t\tnode.set_meta("kiln_lod", lod)
\t\t\t\t\tnode.multimesh = base.multimesh.duplicate()
\t\t\t\t\tgroup.add_child(node)
\t\t\t\tnode.multimesh.mesh = meshes[key]
\t\t\t\tnode.visibility_range_begin = ranges[lod] if lod > 0 else 0.0
\t\t\t\tnode.visibility_range_begin_margin = lod_margin if lod > 0 else 0.0
\t\t\t\tnode.visibility_range_end = ranges[lod + 1] if lod + 1 < ranges.size() else far
\t\t\t\tnode.visibility_range_end_margin = lod_margin if lod + 1 < ranges.size() else 0.0

func _first_mesh(node: Node) -> MeshInstance3D:
\tfor found in node.find_children("*", "MeshInstance3D", true, false):
\t\tif (found as MeshInstance3D).mesh != null:
\t\t\treturn found
\treturn null

# LOD 0: the model's scene, briefly in the tree so its script gives the surfaces the style's materials. LOD k: the
# LOD glb's surfaces take LOD 0's material for the same source material (by name).
func _mesh(k: int, lod: int, tinted: bool, meshes: Dictionary) -> Mesh:
\tvar scene: PackedScene = sources[k] if lod == 0 else lods[k][lod - 1]
\tvar holder := scene.instantiate()
\tif lod == 0:
\t\tadd_child(holder)
\tvar source := _first_mesh(holder)
\tif source == null:
\t\tholder.free()
\t\treturn null
\tvar mesh := source.mesh.duplicate() as Mesh
\tvar by_name: Dictionary = meshes.get("names/%d/%s" % [k, tinted], {})
\tvar by_index: Array = meshes.get("order/%d/%s" % [k, tinted], [])
\tfor i in mesh.get_surface_count():
\t\tvar own := source.mesh.surface_get_material(i)
\t\tvar material: Material = source.get_surface_override_material(i)
\t\tif lod > 0:  # LOD 0's material for the same source material, else for the same surface (a variant's own glb)
\t\t\tif own != null and by_name.has(own.resource_name):
\t\t\t\tmaterial = by_name[own.resource_name]
\t\t\telif i < by_index.size():
\t\t\t\tmaterial = by_index[i]
\t\tif material == null:
\t\t\tmaterial = own
\t\tif tinted and material is BaseMaterial3D and not (material as BaseMaterial3D).vertex_color_use_as_albedo:
\t\t\tmaterial = material.duplicate()
\t\t\t(material as BaseMaterial3D).vertex_color_use_as_albedo = true  # instance colours multiply vertex colours
\t\tif lod == 0:
\t\t\tby_index.append(material)
\t\t\tif own != null:
\t\t\t\tby_name[own.resource_name] = material
\t\tmesh.surface_set_material(i, material)
\tmeshes["names/%d/%s" % [k, tinted]] = by_name
\tmeshes["order/%d/%s" % [k, tinted]] = by_index
\tif lod == 0:
\t\tremove_child(holder)
\tholder.free()
\treturn mesh
"""


def _floats(values: Array) -> str:
    return ", ".join(f"{v:.6g}" for v in np.asarray(values, dtype=np.float64).ravel())


def godot_buffer(transforms: Array, frame: Array, colors: Array | None) -> Array:
    """MultiMesh buffer rows: each instance's transform times the mesh frame, as Godot stores a Transform3D (the 3 x 4
    matrix row by row), then its colour (RGBA) when tinted."""
    n = len(transforms)
    basis = np.stack([transforms[:, 3:6], transforms[:, 6:9], transforms[:, 9:12]], axis=2)  # columns a, b, c
    m = np.zeros((n, 3, 4))
    m[:, :, :3] = basis @ frame[:3, :3]
    m[:, :, 3] = (basis @ frame[:3, 3]) + transforms[:, :3]
    rows = m.reshape(n, 12)
    if colors is not None:
        rows = np.concatenate([rows, colors, np.ones((n, 1))], axis=1)
    return rows


def godot_scene(name: str, placed: Placed, sources: dict[str, tuple[str, list[str], Array]]) -> str:
    """`<name>.tscn`: a Node3D per group (entry x model) holding a MultiMeshInstance3D per chunk (instance transforms and
    colours inline), the meshes given by the inline script from the models' own scenes. `sources`: model or
    model.variant -> (scene res path, LOD glb res paths, mesh frame)."""
    from kiln.godot import _quote

    order = [s for s in placed.scatter.sources if any(g.source == s for g in placed.groups)]
    lines = ["[gd_scene format=3]", ""]
    ext: dict[str, str] = {}
    n = 0
    for s in order:
        scene, lods, _ = sources[s]
        for res, kind in [(scene, "scene"), *((r, f"lod{k + 1}") for k, r in enumerate(lods))]:
            n += 1
            ext[res] = f"{n}_{s.replace('.', '_')}_{kind}"
            lines.append(f'[ext_resource type="PackedScene" path={_quote(res)} id="{ext[res]}"]')
    lines += ["", '[sub_resource type="GDScript" id="GDScript_scatter"]', f"script/source = {_quote(SCATTER_SCRIPT)}", ""]
    ids = []
    for g in placed.groups:
        frame = sources[g.source][2]
        rows = godot_buffer(g.transforms, frame, g.colors)
        for ix, iz, first, count in g.chunks:
            ident = f"MultiMesh_{g.node}_{ix}_{iz}"
            ids.append(ident)
            lines += [f'[sub_resource type="MultiMesh" id="{ident}"]', "transform_format = 1", *(["use_colors = true"] if g.colors is not None else []),
                      f"instance_count = {count}", f"buffer = PackedFloat32Array({_floats(rows[first:first + count])})", ""]  # fmt: skip
    src = ", ".join(f'ExtResource("{ext[sources[s][0]]}")' for s in order)
    lod = ", ".join("[" + ", ".join(f'ExtResource("{ext[r]}")' for r in sources[s][1]) + "]" for s in order)
    lines += [f'[node name={_quote(name)} type="Node3D"]', 'script = SubResource("GDScript_scatter")', f"sources = [{src}]", f"lods = [{lod}]",
              f"metadata/kiln_scatter = {_quote(placed.scatter.onto)}", ""]  # fmt: skip
    for g in placed.groups:
        p = placed.scatter.places[g.place]
        ranges = ", ".join(f"{v:.6g}" for v in (0.0, *p.lod))
        lines += [f'[node name={_quote(g.node)} type="Node3D" parent="."]', f"metadata/kiln_source = {order.index(g.source)}",
                  f"metadata/kiln_lod_ranges = [{ranges}]", f"metadata/kiln_visible = {p.visible:.6g}",
                  f"metadata/kiln_tinted = {'true' if g.colors is not None else 'false'}", ""]  # fmt: skip
        for ix, iz, _, _ in g.chunks:
            lines += [f'[node name="chunk_{ix}_{iz}" type="MultiMeshInstance3D" parent={_quote(g.node)}]',
                      f'multimesh = SubResource("MultiMesh_{g.node}_{ix}_{iz}")', ""]  # fmt: skip
    return "\n".join(lines)


__all__ = ["Group", "Place", "Placed", "Scatter", "Surface", "Tint", "candidates", "godot_buffer", "godot_scene", "mesh_frame", "parse", "place", "to_json"]
