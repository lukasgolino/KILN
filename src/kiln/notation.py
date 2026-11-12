"""`models/<name>.kiln.yaml`: parse and validate a model (parts, paint, rig, animations, variants).

Every problem becomes a Finding with a rule id, the file, the line and a `where` path, and all of them are
collected (not just the first), as in PAGAN.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np

from kiln.effect import Effect
from kiln.effect import parse as parse_effect
from kiln.hardware import HARDWARE, expand
from kiln.mesher import CELL_LIMIT
from kiln.retarget import REQUIRED, JointMap
from kiln.scatter import Scatter
from kiln.scatter import parse as parse_scatter
from kiln.sdf import (
    HARD_PATH_STEPS,
    IDENTITY,
    PATH_STEPS,
    SHAPES,
    Copy,
    Field,
    Folds,
    Geometry,
    Noise,
    axis_rotation,
    rotation_matrix,
    smooth_path,
    smooth_profile,
)
from kiln.shade import parse as parse_shade
from kiln.terrain import Terrain
from kiln.terrain import parse as parse_terrain
from kiln.uv import AXES as UV_AXES
from kiln.uv import PROJECTIONS, UVSpec
from kiln.vendor.findings import Finding
from kiln.vendor.yamlio import LineMap, YamlError, load_yaml, parse_yaml

MODEL_SUFFIX = ".kiln.yaml"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
ANIMATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")  # imported clips keep their library names (Idle_A)
ROOT_ID = "root"
AXES = {"x": 0, "y": 1, "z": 2}
PATTERNS = ("stripes", "checker", "dots", "band", "pixel")
STATUSES = ("draft", "approved")
SKINS = ("none", "rigid", "soft")
UNIONS = ("whole", "per_bone")
CYCLES = ("walk", "waddle", "run", "sneak", "hop", "bob", "spin", "swing", "breathe", "wave", "chain", "idle")
INTERPOLATIONS = ("linear", "step")

PART_FIELDS = {"id", "color", "material", "emission", "blend", "color_blend", "density", "resolution", "skin_falloff", "cut", "intersect", "mirror", "mirror_id", "array", "at", "rotate",
               "shell", "twist", "scale", "blend_to", "detail", "noise", "pattern", "gradient", "decal", "texture", "loose", "hard", "bevel", "chamfer", "segments", "fit", "keep", "uv", "aim", "attr", "on", "folds"}  # fmt: skip
BEVEL_SHAPES = ("box", "wedge", "cylinder", "cone", "extrude")
OPEN_SIDES = ("x", "-x", "y", "-y", "z", "-z", "+x", "+y", "+z")
ATTR_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
TOP_FIELDS = {"name", "description", "tags", "status", "style_version", "class", "style", "palette", "budget", "resolution", "max_cells", "normal_map", "normal_strength", "relief", "shade", "parts", "instances", "transforms", "textures",
              "rig", "skin", "animations", "variants", "lod", "lint", "source", "process", "template", "extends", "remove", "skeleton", "fit_to", "origin", "effect", "node_prefix",
              "animation_library", "animations_only", "union", "terrain", "scatter"}  # fmt: skip
TERRAIN_TOP = {"name", "description", "tags", "status", "style_version", "class", "style", "palette", "lint", "terrain"}  # a terrain's model fields
SCATTER_TOP = {"name", "description", "tags", "status", "style_version", "class", "style", "palette", "lint", "scatter"}  # a scatter's model fields
# Fields no mesh, paint or skin depends on (#185): the clips (sampled onto the built skeleton), the variants' colour
# swaps (applied at export) and the model's card. A field a builder reads must not be listed here.
NOT_SHAPE = ("animations", "animation_library", "variants", "description", "tags", "status", "shade")


def _as_text(value: Any) -> str:
    """Parsed YAML as one text, whatever it holds (a key or value YAML read as a date, say: findings report those)."""

    def plain(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k): plain(x) for k, x in v.items()}
        if isinstance(v, list | tuple):
            return [plain(x) for x in v]
        return v if v is None or isinstance(v, bool | int | float | str) else str(v)

    return json.dumps(plain(value))


OWN_FIELDS = ("name", "description", "tags", "status", "style_version", "template", "extends", "remove")  # never inherited


@dataclass(frozen=True)
class Pattern:
    type: str
    color: str  # the second colour (hex); the part's own colour is the first
    color_name: str
    size: float
    axis: tuple[float, float, float]
    width: float  # stripes: fraction of each repeat in the second colour; dots: dot diameter as a fraction of size
    at: float = 0.0  # band: where its centre is along the axis (metres); size = its thickness
    frame: str = "model"  # model: axes and positions in model space; part: in the part's own frame (follows rotate/aim)
    mix: tuple[str, str, float] | None = None  # a gradient band: (from, to, t): its colour is their OKLab mix (variants remix it)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)  # stripes, checker, dots: the repeat shifted by this (metres)
    jitter: float = 0.0  # dots: each dot moved up to jitter/2 of a cell each way from its grid place (seeded)
    vary: float = 0.0  # dots: each dot's size varies by up to this share
    seed: int = 0
    pixels: tuple[str, ...] = ()  # pixel: the motif's rows, top first ("#" painted, "." not), tiled round the axis
    repeat: int = 0  # pixel: how many times the motif goes round (0: auto, about square cells at the part's radius)


@dataclass(frozen=True)
class Decal:
    image: Path
    axis: str  # x, -x, y, -y, z, -z: the direction the decal faces (it is projected along it)
    at: tuple[float, float, float]
    size: tuple[float, float]  # width, height in metres on the surface (a texture: one tile)
    project: str = "planar"  # planar: a decal; box, triplanar, cylindrical: a texture tiled over the whole part
    per_copy: bool = False  # on an arrayed part: the decal on every copy, placed as on the first
    copy: tuple[float, ...] | None = None  # a per-copy decal's copy: its rotation (9), pivot (3), offset (3), so points map back


@dataclass(frozen=True)
class OnSurface:
    """`on:` a part placed on the blended surface of earlier parts: `near` snapped onto it, `offset` metres along the
    normal there, the part's own y axis turned to the normal (`align`), then `roll` degrees about it."""

    ids: tuple[str, ...]
    near: tuple[float, float, float]
    offset: float = 0.0
    roll: float = 0.0
    align: bool = True


@dataclass
class Part:
    index: int
    id: str
    geometry: Geometry
    color: str  # hex
    color_name: str
    material: str
    pattern: Pattern | None = None  # the first of `patterns`
    decal: Decal | None = None
    line: int | None = None
    where: str = ""
    twin_of: str | None = None  # mirror_id copies: the id they mirror
    twin_axis: int = 0
    loose: bool = False  # meant to float (flames, bees, rubble): not a W103 floating piece
    hard: bool | None = None  # exact polygons (True), the smooth field (False), or the style decides (None)
    crisp: bool = False  # blend: none (a hard part when the style allows)
    bevel: float = 0.0  # hard edges rounded in `segments` bands (a chamfer: one band)
    segments: int = 2
    fit: tuple[tuple[str, ...], float] | None = None  # a shell wrapping the parts with these ids, this far from them
    cut_only: tuple[str, ...] | None = None  # a cut that only cuts the parts with these ids (#209: several)
    blend_to: tuple[str, ...] | None = None  # blends only into the earlier parts with these ids (crisp against the rest)
    texture: Decal | None = None  # an image tiled over the whole part (project box | cylindrical), under its decal
    detail: bool = False  # only in the baked normal map (grooves, wrinkles, strands), never in the mesh
    color_blend: float = 0.0  # metres: its colour fades into its neighbours' over this distance from their border (base colour map)
    color_blend_set: bool = False  # the part gave color_blend itself (else the style's [shape] color_blend may apply)
    density: float = 1.0  # weight on the triangle budget in its surface (3: three times the triangles per area of the rest)
    fine: float | None = None  # metres: a finer mesh cell in this part's box than the model's (a face), refined onto the surface (#306)
    on: OnSurface | None = None  # placed on the blended surface of earlier parts (resolved once all parts are read)
    skin_falloff: float | None = None  # soft skins: metres over which other bones pull on this part's surface (#192)
    keep: bool | None = None  # survives every reduction (LODs) at full detail; None: small crisp parts do
    uv: UVSpec | None = None  # texture coordinates projected from its shape (kiln.uv)
    patterns: tuple[Pattern, ...] = ()  # painted in order (a later one paints over earlier ones)
    attr: tuple[tuple[str, float], ...] = ()  # named numbers exported per vertex (shader keys: heat, opacity)
    wall: bool = False  # a cut with a colour: it paints the walls it makes (an inked groove, panel lines) (#178)


@dataclass(frozen=True)
class RigEntry:
    pivot: tuple[float, float, float] | None  # None = the part's own centre at its lowest point
    parent: str | None
    meta: tuple[tuple[str, Any], ...] = ()
    separate: bool = False  # soft skins: keep this part a rigid mesh of its own (detachable helmet)
    sockets: tuple[tuple[str, tuple[float, float, float]], ...] = ()  # named points (model space, rest pose)
    under: tuple[str, str, str, float] | None = None  # separate parts: (hex, colour name, material, gap) painted on what it covers
    revealed: tuple[str, ...] = ()  # shown only once one of these parts is gone (a stump cap); separate, hidden by default
    gib: tuple[str, ...] = ()  # this part comes off: also export these ids as one closed piece (models/<name>.gib.<id>.glb); ("*",) = it and its children


@dataclass(frozen=True)
class PartPose:
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)  # degrees, about the part's pivot
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    aim: tuple[float, float, float] | None = None  # model-space point the bone points at (its rotate is solved per frame, #200)
    reach: tuple[float, float, float] | None = None  # two-bone IK: this bone and its child bend so the child's end gets there
    pole: tuple[float, float, float] | None = None  # (reach) model-space point the middle joint bends toward


@dataclass
class Animation:
    name: str
    fps: float
    loop: bool
    interpolation: str
    poses: list[dict[str, PartPose]]  # one dict per frame: part id -> pose (missing = rest)
    cycle: dict[str, Any] | None = None  # expanded into poses once the rig is known
    source: tuple[Path, str, float] | None = None  # (glb, clip, speed): retargeted from a clip library
    retarget: dict[str, dict[str, Any]] | None = None  # imported clips: { keep: {joint: share}, offset: {joint: [x, y, z]} }


@dataclass
class Source:
    """An imported mesh (a CC0 pack item) instead of parts."""

    file: Path
    licence: str
    author: str
    url: str
    height: float | None = None
    scale: float = 1.0
    recolor: str = "auto"  # auto (nearest palette colour) | keep
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)
    original: Path | None = None  # the .fbx/.blend/.obj `file` was converted from (credits name it)


@dataclass
class Relief:
    """A layer of shallow overlapping patches on the surface of some parts, in the baked maps only (kiln.relief)."""

    on: list[str]  # part ids it covers (empty with on_colors: every smooth part)
    kind: str = "fur"
    on_colors: list[str] = field(default_factory=list)  # hex: only faces painted in these colours (#301)
    exclude: list[str] = field(default_factory=list)  # part ids it leaves bare (`except:` in the model, #301)
    length: float = 0.09  # metres along the flow
    width: float = 0.05  # metres across
    lift: float = 0.008  # metres the tip stands off the surface
    density: float = 1.0  # 1: the patches just cover the surface; more: they overlap like roof tiles
    flow: str | tuple[float, float, float] = "down"  # down | up | a direction
    tips: int = 3  # pointed tips along a patch's lower edge
    jitter: float = 0.3  # 0..1 variation of size and angle
    color: str | None = None  # hex; None: the surface's own colour
    color_to: str | None = None  # hex at the tip
    under: float = 0.3  # 0..1: how much darker the surface is just below a tip
    seed: int = 1
    fade: float = 0.06  # metres: patches thin out and shrink over this distance toward the edge of `on`
    displace: bool = False  # also move the mesh by the layer's height: tufts break the silhouette (#261)


@dataclass(frozen=True)
class Instance:
    """Another model placed in this one, as it is built (its own mesh and detail, #171)."""

    model: str
    at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)  # degrees, as a part's
    scale: float = 1.0
    bone: str = ROOT_ID  # the part (bone) it moves with
    line: int | None = None


@dataclass
class Model:
    name: str
    path: Path | None
    description: str = ""
    tags: tuple[str, ...] = ()
    status: str = "draft"
    style_version: int | None = None
    cls: str = "prop"
    style: str | None = None
    palette: str | None = None
    budget: int | None = None
    resolution: float | None = None  # metres per mesh cell for this model, as is (not scaled by size); overrides the style
    max_cells: int | None = None  # mesh grid cells per axis at most; overrides the style
    normal_map: int = 0  # texels across the baked normal map (0: none)
    normal_map_off: bool = False  # the model says normal_map: 0 itself (colour fades then go in the vertices)
    fade_maps: bool = False  # the maps are on only for colour fades (none with relief or a normal_map of its own)
    vertex_fades: bool = False  # colour fades per vertex (COLOR_0) instead of in the base colour map (#262)
    normal_strength: float = 1.0  # the map's tilt away from the mesh normal, scaled
    normal_strength_line: int | None = None  # normal_strength given with no map (yet): E003 unless the style brings one
    bake_parts: list[Geometry] | None = None  # every part's geometry in order, `detail` ones too (the normal map's field)
    detail: list[Geometry] = field(default_factory=list)  # the `detail` parts (only in bake_parts)
    bake_index: list[int] = field(default_factory=list)  # part i is bake_parts[bake_index[i]]
    detail_ids: dict[int, str] = field(default_factory=dict)  # bake_parts index of each detail part -> its id
    relief: list[Relief] = field(default_factory=list)  # surface layers (fur patches) in the baked maps
    shade: dict[str, float] = field(default_factory=dict)  # shade paint over the style's [shade] (kiln.shade), at export
    parts: list[Part] = field(default_factory=list)
    rig: dict[str, RigEntry] = field(default_factory=dict)
    skin: str = "none"
    union: str = "whole"  # per_bone (rigid skins): each bone's parts are their own closed surface, so joints never tear
    animations: dict[str, Animation] = field(default_factory=dict)
    variants: dict[str, dict[str, str]] = field(default_factory=dict)  # name -> {hex: hex}
    lod: tuple[int, ...] = ()
    lint_disable: tuple[str, ...] = ()
    source: Source | None = None
    text: str = ""
    template: bool = False  # a base for `extends` (not built on its own)
    extends: str | None = None
    skeleton: str | None = None  # humanoid: standard joint names, clip retargeting
    joint_map: JointMap | None = None  # skeleton: { map, root_motion }: clips retargeted onto any skeleton
    fit_to: tuple[Path, str, tuple[str, ...]] | None = None  # (glb, bone, meshes): an attachment made around a CC0 character
    origin: str | tuple[float, float, float] | None = None  # base | center | ground | a model-space point: the exported files' origin
    node_prefix: str = ""  # mesh nodes are <prefix><id> children of their parts' nodes (several models in one scene)
    animation_library: str | None = None  # plays this clip carrier's animations (copied in at load); its glb has none
    animations_only: bool = False  # a clip carrier: Godot imports its glb as an AnimationLibrary (no scene)
    library_text: str = ""  # the carrier's source (cache key)
    draft: bool = False  # preview --draft: built for a quick look (rough colour borders, plain hard parts, one reducing pass)
    shape_text: str = ""  # the fields a build's mesh, paint and skin come from, as one text (the mesh cache's key)
    motion_text: str = ""  # the animations, as one text (the cached build's tracks are made again when it changes)
    effect: Effect | None = None  # a burst of other models' meshes (models/<name>.effect.json)
    instances: tuple[Instance, ...] = ()  # other models placed in this one, each its own build (a desk with its props)
    terrain: Terrain | None = None  # a heightfield with splat layers instead of parts (kiln.terrain)
    scatter: Scatter | None = None  # other models placed many times over a surface instead of parts (kiln.scatter)

    @property
    def ids(self) -> list[str]:
        """Part ids in first-use order (root first)."""
        seen = [ROOT_ID]
        for p in self.parts:
            if p.geometry.op == "add" and p.id not in seen:
                seen.append(p.id)
        return seen


class _Ctx:
    def __init__(self, path: Path | None, palette: dict[str, str], materials: set[str]) -> None:
        self.path = path
        self.palette = palette  # name or key -> hex
        self.ramps: dict[str, tuple[str, ...]] = getattr(palette, "ramps", {})  # the palette's ramps: name -> hexes (#205)
        self.materials = materials
        self.findings: list[Finding] = []

    def error(self, rule: str, message: str, line: int | None, where: str) -> None:
        self.findings.append(Finding(rule, message, self.path, line, where))


def _line(data: Any, key: Any = None) -> int | None:
    if isinstance(data, LineMap):
        return data.line_of(key) if key is not None else data.line
    return None


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _vec(v: Any, n: int = 3) -> tuple[float, ...] | None:
    if isinstance(v, list) and len(v) == n and all(_num(x) for x in v):
        return tuple(float(x) for x in v)
    return None


def _point3(v: tuple[float, ...] | None) -> tuple[float, float, float] | None:
    return None if v is None else (v[0], v[1], v[2])


def _check_value(kind: str, v: Any) -> Any:
    """A validated parameter value, or None."""
    if kind == "bool":
        return v if isinstance(v, bool) else None
    if kind == "num":
        return float(v) if _num(v) else None
    if kind == "sides":
        return int(v) if isinstance(v, int) and not isinstance(v, bool) and 3 <= v <= 64 else None
    if kind == "pos":
        return float(v) if _num(v) and v > 0 else None
    if kind == "nonneg":
        return float(v) if _num(v) and v >= 0 else None
    if kind == "vec3":
        return _vec(v)
    if kind == "posvec3":
        vec = _vec(v)
        return vec if vec is not None and min(vec) > 0 else None
    if kind == "points3":
        if isinstance(v, list) and len(v) >= 2 and all(_vec(p) is not None for p in v):
            return [list(_vec(p) or ()) for p in v]
        return None
    if kind == "holes2":
        holes = [_check_value("points2", h) for h in v] if isinstance(v, list) else [None]
        return holes if all(h is not None for h in holes) else None
    if kind in ("points2", "profile"):
        if isinstance(v, list) and len(v) >= 3 and all(_vec(p, 2) is not None for p in v):
            pts = [list(_vec(p, 2) or ()) for p in v]
            if kind == "profile" and any(p[0] < 0 for p in pts):
                return None
            # a repeated point (or an outline closed on its first point) is a zero-length edge: drop it
            pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
            if len(pts) > 1 and pts[-1] == pts[0]:
                pts.pop()
            return pts if len(pts) >= 3 else None
        return None
    return None


KIND_HELP = {
    "num": "a number", "pos": "a number > 0", "nonneg": "a number >= 0", "vec3": "[x, y, z]",
    "posvec3": "[x, y, z], each > 0", "points3": "a list of 2+ points [x, y, z]",
    "points2": "a list of 3+ different points [x, z]", "bool": "true or false",
    "holes2": "a list of outlines, each 3+ different points [x, z] (inside the outline: even-odd)",
    "profile": "a list of 3+ different points [r, y] with r >= 0", "sides": "a whole number of sides (3-64)",
}  # fmt: skip


def _color(ctx: _Ctx, raw: Any, line: int | None, where: str) -> tuple[str, str] | None:
    """(hex, name) of a palette colour name/key, or a literal "#rrggbb" (lint warns about those)."""
    if isinstance(raw, int) and not isinstance(raw, bool):
        raw = str(raw)
    if isinstance(raw, str):
        if raw in ctx.palette:
            return ctx.palette[raw], raw
        if re.fullmatch(r"#[0-9a-fA-F]{6}", raw):
            return raw.lower(), raw.lower()
    known = ", ".join(sorted(k for k in ctx.palette if len(k) > 1)) or "none"
    ctx.error("E004", f"unknown colour {raw!r}: use a palette colour name ({known}) or \"#rrggbb\"", line, where)
    return None


def _parse_copies(ctx: _Ctx, raw: Any, line: int | None, where: str) -> tuple[Copy, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("count"), int) or isinstance(raw.get("count"), bool) or not 1 <= raw["count"] <= 256:
        ctx.error("E003", "array needs count (1-256) and step: [x, y, z] (in a row) or around: x|y|z (in a ring)", line, where)
        return None
    count = raw["count"]
    if "around" in raw:
        bad = [k for k in raw if k not in ("count", "around", "center", "angle")]
        axis = raw["around"]
        center = _vec(raw.get("center", [0, 0, 0]))
        angle = raw.get("angle", 360)
        vector = _vec(axis) if isinstance(axis, list) else None
        if bad or (vector is None and not (isinstance(axis, str) and axis in AXES)) or (vector is not None and not any(vector)) or center is None \
                or not _num(angle):
            ctx.error("E003", "a ring array is { count, around: x|y|z or a direction [x, y, z], center: [x, y, z], angle: 360 }", line, where)
            return None
        unit = np.zeros(3)
        if vector is not None:
            unit = np.array(vector) / float(np.linalg.norm(vector))
        else:
            unit[AXES[axis]] = 1.0
        stepdeg = float(angle) / count if abs(float(angle)) >= 360 else float(angle) / max(count - 1, 1)
        return tuple(Copy(axis_rotation(unit, stepdeg * i), np.array(center), np.zeros(3)) for i in range(count))
    step = _vec(raw.get("step"))
    bad = [k for k in raw if k not in ("count", "step")]
    if step is None or bad:
        ctx.error("E003", "a row array is { count, step: [x, y, z] }", line, where)
        return None
    return tuple(Copy(np.eye(3), np.zeros(3), np.array(step) * i) for i in range(count))


def _parse_part(ctx: _Ctx, raw: Any, index: int, line: int | None) -> list[Part]:
    where = f"parts[{index}]"
    if isinstance(raw, dict) and True in raw and "on" not in raw:  # YAML 1.1 reads a bare `on:` key as true
        raw["on"] = raw.pop(True)
        if isinstance(raw, LineMap) and True in raw.key_lines:
            raw.key_lines["on"] = raw.key_lines.pop(True)
    if not isinstance(raw, dict):
        ctx.error("E003", "each part is a mapping: - sphere: { at: [0, 1, 0], radius: 0.3 }", line, where)
        return []
    shapes = [k for k in raw if k in SHAPES]
    if len(shapes) != 1:
        ctx.error("E003", f"each part needs exactly one shape: {', '.join(SHAPES)}", line, where)
        return []
    kind = shapes[0]
    unknown = [k for k in raw if k not in PART_FIELDS and k != kind]
    if unknown:
        ctx.error("E002", f"unknown part field(s) {', '.join(map(str, unknown))}; allowed: {kind}, {', '.join(sorted(PART_FIELDS))}", line, where)
    spec = raw[kind]
    swhere = f"{where}.{kind}"
    if not isinstance(spec, dict):
        ctx.error("E003", f"{kind} takes a mapping: {SHAPES[kind].help}", line, swhere)
        return []
    sdef = SHAPES[kind]
    params: dict[str, Any] = dict(sdef.defaults)
    ok = True
    for key, value in spec.items():
        if key in ("at", "rotate", "aim") or (kind == "extrude" and key in PATH_KEYS + TEXT_KEYS):
            continue
        if key not in sdef.fields:
            ctx.error("E002", f"{kind} has no field {key!r}; it takes {sdef.help}, plus at and rotate", _line(spec, key) or line, f"{swhere}.{key}")
            ok = False
            continue
        checked = _check_value(sdef.fields[key], value)
        if checked is None:
            ctx.error("E003", f"{kind} {key} must be {KIND_HELP[sdef.fields[key]]}", _line(spec, key) or line, f"{swhere}.{key}")
            ok = False
            continue
        params[key] = checked
    if kind == "extrude" and ("path" in spec or "text" in spec):
        loops = _parse_path(ctx, spec, line, swhere)
        if loops is None:
            ok = False
        elif sum(k in spec for k in ("points", "path", "text")) > 1 or "holes" in spec:
            ctx.error("E003", "an extrude has points (+ holes), path or text, only one", line, swhere)
            ok = False
        else:
            loops.sort(key=lambda lp: -abs(_loop_area(lp)))
            params["points"], params["holes"] = loops[0], loops[1:]
    aim_raw = spec.get("aim", raw.get("aim"))
    aim = None
    if aim_raw is not None:
        aim = _parse_aim(aim_raw)
        if aim is None:
            ctx.error("E003", "aim points the shape's own y axis from one point to another: aim: [[x, y, z], [x, y, z]] or "
                      "{ from, to, roll: degrees }; it sits halfway, and a missing height is the distance", line, f"{swhere}.aim")  # fmt: skip
            ok = False
        elif "at" in spec or "at" in raw:
            ctx.error("E003", "a part has at or aim (which puts it halfway between its two points), not both", line, f"{swhere}.aim")
            ok = False
        elif "height" in sdef.fields and "height" not in spec:
            params["height"] = aim[3]
    on = None
    if "on" in raw:
        on = _parse_on(raw["on"])
        if on is None:
            ctx.error("E003", "on places the part on the blended surface of earlier parts: on: { part: body, near: [x, y, z] } (+ offset: "
                      "metres along the normal, roll: degrees, align: false keeps its own turn); part may be a list of ids", line,
                      f"{where}.on")  # fmt: skip
            ok = False
        elif "at" in spec or "at" in raw or aim_raw is not None:
            ctx.error("E003", "a part placed with on has no at or aim (on puts it on the surface at near)", line, f"{where}.on")
            ok = False
        elif "array" in raw:
            ctx.error("E003", "on places one part: its array copies wouldn't follow the surface; write a part per spot (or mirror_id)",
                      line, f"{where}.on")  # fmt: skip
            ok = False
    missing = [k for k in sdef.required if k not in params and k not in spec]  # a bad value was reported already
    if missing:
        ctx.error("E003", f"{kind} needs {', '.join(missing)} ({sdef.help})", line, swhere)
        ok = False
    if kind == "lathe" and "profile" in params and params.get("smooth", True):
        if "smooth" not in spec:
            params["hard_profile"] = params["profile"]  # hard lathes keep the outline's corners unless asked
        params["profile"] = smooth_profile(params["profile"])
    if kind in ("capsule", "tube") and "radius" in params:
        params.setdefault("radius_to", params["radius"])
    if kind == "lock" and "width" in params and "thickness" in params:
        params.setdefault("width_to", params["width"])
        params.setdefault("thickness_to", params["thickness"])
        if params.get("facing") is not None and max(abs(v) for v in params["facing"]) == 0:
            ctx.error("E003", "lock facing is a direction [x, y, z], not [0, 0, 0]", line, f"{swhere}.facing")
            ok = False
    if kind in ("box", "cylinder", "extrude") and ok:
        limit = min(params["size"]) / 2 if kind == "box" else (min(params["radius"], params["height"] / 2) if kind == "cylinder" else params["height"] / 2)
        if params["round"] > limit:
            ctx.error("E003", f"round {params['round']} is bigger than half the {kind}'s smallest side ({limit:g})", line, f"{swhere}.round")
            ok = False
    at_raw = spec.get("at", raw.get("at", [0, 0, 0]))
    at = _vec(at_raw)
    if at is None:
        ctx.error("E003", "at must be [x, y, z] in metres (the shape's centre)", line, f"{swhere}.at")
        ok = False
    rot_raw = spec.get("rotate", raw.get("rotate"))
    rotation = None
    if rot_raw is not None:
        rot = _vec(rot_raw)
        if rot is None:
            ctx.error("E003", "rotate must be [x, y, z] degrees", line, f"{swhere}.rotate")
            ok = False
        elif any(rot):
            rotation = rotation_matrix((rot[0], rot[1], rot[2]))
    if aim is not None and ok:  # the aim turns the (already rotated) shape: rotate spins it in its own frame first
        at = aim[0]
        rotation = aim[1] if rotation is None else aim[1] @ rotation

    op = "add"
    cut_only = None
    for flag in ("cut", "intersect"):
        if flag in raw:
            named = [raw[flag]] if isinstance(raw[flag], str) else raw[flag] if isinstance(raw[flag], list) and raw[flag] else None
            if flag == "cut" and named is not None and all(isinstance(n, str) and NAME_RE.match(n) for n in named):
                cut_only = tuple(named)  # cuts only the parts with these ids (a helmet's face opening, not the face; a tray's own bins)
                op = flag if op == "add" else "conflict"
            elif not isinstance(raw[flag], bool):
                ctx.error("E003", f"{flag} must be true or false" + (" (cut may also name the part ids it cuts: cut: lid or cut: [case, lid])"
                                                                     if flag == "cut" else ""), line, f"{where}.{flag}")  # fmt: skip
                ok = False
            elif raw[flag]:
                op = flag if op == "add" else "conflict"
    if op == "conflict":
        ctx.error("E003", "a part can cut or intersect, not both", line, where)
        ok = False
    blend = raw.get("blend", 0.0)
    crisp = blend == "none"
    if crisp:
        blend = 0.0
    if not _num(blend) or blend < 0 or blend > 1:
        ctx.error("E003", "blend is the smooth-join radius in metres (0 = a crisp seam), e.g. 0.04, or none (a hard part: exact polygons)", line, f"{where}.blend")
        ok = False
    color_blend = raw.get("color_blend", 0.0)
    if not _num(color_blend) or not 0 <= float(color_blend) <= 0.5:
        ctx.error("E003", "color_blend is the distance in metres over which the part's colour fades into its neighbours' (0 to 0.5; 0: a crisp "
                  "border), e.g. 0.05", line, f"{where}.color_blend")  # fmt: skip
        ok = False
        color_blend = 0.0
    density = raw.get("density", 1.0)
    if not _num(density) or not 0.25 <= float(density) <= 8:
        ctx.error("E003", "density weighs the triangle budget on the part's surface: 0.25 to 8 (1 as the rest; 3: three times the "
                  "triangles per area, e.g. a face; 0.5: coarser)", line, f"{where}.density")  # fmt: skip
        ok = False
        density = 1.0
    fine = raw.get("resolution")
    if fine is not None and (not _num(fine) or not 0.0005 <= float(fine) <= 0.5):
        ctx.error("E003", "a part's resolution is a finer mesh cell inside its box, in metres (e.g. 0.004 for a face; pair it with "
                  "density so the budget keeps the triangles)", line, f"{where}.resolution")  # fmt: skip
        ok = False
        fine = None
    skin_falloff = raw.get("skin_falloff")
    if skin_falloff is not None and (not _num(skin_falloff) or not 0 <= float(skin_falloff) <= 0.5):
        ctx.error("E003", "skin_falloff is how far (metres) other bones pull on this part's surface in a soft skin: 0 (only its own bone) "
                  "to 0.5, e.g. 0.01 for a sleeve that shouldn't drag the chest along", line, f"{where}.skin_falloff")  # fmt: skip
        ok = False
        skin_falloff = None
    detail = raw.get("detail", False)
    if not isinstance(detail, bool):
        ctx.error("E003", "detail is true (the part only shapes the baked normal map: model normal_map) or false", line, f"{where}.detail")
        ok = False
    if detail is True and density != 1:
        ctx.error("E003", "density spends mesh triangles: a detail part is only in the normal map and has none", line, f"{where}.density")
        ok = False
    if detail is True and color_blend:
        ctx.error("E003", "color_blend fades a part's colour: a detail part is only in the normal map and has none", line, f"{where}.color_blend")
        ok = False
        detail = False
    blend_to = None
    if "blend_to" in raw:
        b_raw = raw["blend_to"]
        b_ids = [b_raw] if isinstance(b_raw, str) else b_raw
        if not isinstance(b_ids, list) or not b_ids or not all(isinstance(x, str) and NAME_RE.match(x) for x in b_ids) or op != "add" \
                or crisp or not _num(blend) or not blend:
            ctx.error("E003", "blend_to names the earlier parts this one melts into (by id), e.g. blend_to: torso or [torso, back], with "
                      "blend: its radius; it meets every other part crisply (fur locks that melt into the body, grooves between them)",
                      line, f"{where}.blend_to")  # fmt: skip
            ok = False
        else:
            blend_to = tuple(str(x) for x in b_ids)
    shell, shell_side, open_side = raw.get("shell", 0.0), "both", None
    if isinstance(shell, dict):
        sh = shell
        open_side = sh.get("open")
        shell = sh.get("thickness")
        shell_side = sh.get("side", "in")
        if any(k not in ("thickness", "side", "open") for k in sh) or shell_side not in ("in", "both") or sh.get("open") not in (None, *OPEN_SIDES):
            ctx.error("E003", "shell is { thickness: metres, side: in|both, open: -y } (open: the side left open, showing the rim)", line, f"{where}.shell")
            ok = False
    if not _num(shell) or shell < 0:
        ctx.error("E003", "shell is the wall thickness in metres (a hollow shape), e.g. 0.02, or { thickness, side, open }", line, f"{where}.shell")
        ok = False
        shell = 0.0
    twist = raw.get("twist", 0.0)
    if not _num(twist):
        ctx.error("E003", "twist is degrees per metre about the shape's y axis", line, f"{where}.twist")
        ok = False
    scale = None
    if "scale" in raw:
        s_raw = raw["scale"]
        s_vec = [s_raw] * 3 if _num(s_raw) else _vec(s_raw)
        if s_vec is None or min(s_vec) <= 0:
            ctx.error("E003", "scale stretches the part in its own frame: scale: [x, y, z] (each > 0) or one number, e.g. [1, 1, 0.4] "
                      "to flatten it", line, f"{where}.scale")  # fmt: skip
            ok = False
        elif any(v != 1 for v in s_vec):
            scale = np.array(s_vec, float)
    noise = None
    if "noise" in raw:
        n = raw["noise"]
        if not isinstance(n, dict) or not _num(n.get("amount")) or not _num(n.get("scale", 0.2)) or n.get("scale", 0.2) <= 0 \
                or any(k not in ("amount", "scale", "seed") for k in n) or not isinstance(n.get("seed", 0), int):
            ctx.error("E003", "noise is { amount: metres (e.g. 0.01), scale: metres per bump (e.g. 0.2), seed: int }", line, f"{where}.noise")
            ok = False
        else:
            noise = Noise(float(n["amount"]), float(n.get("scale", 0.2)), int(n.get("seed", index)))
    fold = None
    if "folds" in raw:
        fr = raw["folds"]
        keys = ("count", "depth", "from_y", "to_y", "sharp", "bunch")
        good = isinstance(fr, dict) and not any(k not in keys for k in fr) and isinstance(fr.get("count"), int) and not isinstance(fr.get("count"), bool) \
            and 2 <= fr["count"] <= 48 and _num(fr.get("depth")) and 0 < fr["depth"] <= 0.1 and all(_num(fr.get(k, 0.0)) for k in ("from_y", "to_y")) \
            and "from_y" in fr and "to_y" in fr and fr["to_y"] > fr["from_y"] and _num(fr.get("sharp", 0.5)) and 0 <= fr.get("sharp", 0.5) <= 1 and isinstance(fr.get("bunch", False), bool)
        if not good:
            ctx.error("E003", "folds is { count: 12 (2-48), depth: metres (e.g. 0.02, at most 0.1), from_y: the hem's height, to_y: where they fade out "
                      "(model space, from_y < to_y), sharp: 0-1 (0.5), bunch: false (true: rings along the axis, bunched cloth) }: cloth folds round "
                      "the part's own y axis (a capsule's or tube's own axis)", line, f"{where}.folds")  # fmt: skip
            ok = False
        else:
            fold = Folds(int(fr["count"]), float(fr["depth"]), float(fr["from_y"]), float(fr["to_y"]), float(fr.get("sharp", 0.5)),
                         bool(fr.get("bunch", False)))
    mirror_raw = raw.get("mirror")
    mirror: tuple[int, ...] = ()
    if mirror_raw is not None:
        names = [mirror_raw] if isinstance(mirror_raw, str) else mirror_raw
        if not isinstance(names, list) or not names or any(m not in AXES for m in names):
            ctx.error("E003", "mirror is x, y, z or a list of them (the part is copied to the other side of 0)", line, f"{where}.mirror")
            ok = False
        else:
            mirror = tuple(sorted({AXES[m] for m in names}))
    copies = _parse_copies(ctx, raw.get("array"), line, f"{where}.array") if "array" in raw else None
    if "array" in raw and copies is None:
        ok = False

    part_id = raw.get("id", ROOT_ID)
    if not isinstance(part_id, str) or not NAME_RE.match(part_id):
        ctx.error("E003", "id must be lowercase letters, digits, _ or - (e.g. arm_l)", line, f"{where}.id")
        ok = False
    mirror_id = raw.get("mirror_id")
    if mirror_id is not None:
        if not isinstance(mirror_id, str) or not NAME_RE.match(mirror_id) or mirror_id == part_id:
            ctx.error("E003", "mirror_id names the mirrored copy (e.g. arm_r for arm_l); it needs mirror: x", line, f"{where}.mirror_id")
            ok = False
        elif len(mirror) != 1:
            ctx.error("E003", "mirror_id needs exactly one mirror axis (mirror: x)", line, f"{where}.mirror_id")
            ok = False

    color = ("#ff00ff", "#ff00ff")
    material = "default"
    pattern = decal = texture = None
    patterns: tuple[Pattern, ...] = ()
    if op != "add" and "emission" in raw:
        ctx.error("E003", "emission makes a part glow: a cut has no surface of its own", line, f"{where}.emission")
        ok = False
    if op == "add":
        c = _color(ctx, raw.get("color"), line, f"{where}.color") if "color" in raw else None
        if "color" not in raw:
            ctx.error("E004", "a part needs a color (a palette colour name)", line, f"{where}.color")
        if c is None:
            ok = False
        else:
            color = c
        material = raw.get("material", "default")
        if not isinstance(material, str) or material not in ctx.materials:
            ctx.error("E005", f"unknown material {material!r}; the style has: {', '.join(sorted(ctx.materials))}", line, f"{where}.material")
            ok = False
        elif "emission" in raw:  # its own glow strength (#202): the preset with that emission ("glow@0.6")
            emission = raw["emission"]
            if not _num(emission) or not 0 <= float(emission) <= 20:
                ctx.error("E003", "emission is this part's glow strength (0 to 20; its colour x it), over its material preset's, e.g. 0.6",
                          line, f"{where}.emission")  # fmt: skip
                ok = False
            else:
                material = f"{material}@{float(emission):g}"
        if "pattern" in raw:
            listed = raw["pattern"] if isinstance(raw["pattern"], list) and raw["pattern"] else [raw["pattern"]]
            parsed = [_parse_pattern(ctx, r, line, f"{where}.pattern" + (f"[{k}]" if len(listed) > 1 else "")) for k, r in enumerate(listed)]
            patterns = tuple(q for q in parsed if q is not None)
            # a second dots pattern on the same grid hides under the first (#194): one without its own offset or seed
            # sits half a cell over, and draws its own random dots
            seen = 0
            shifted = []
            for k, (q, r) in enumerate(zip(parsed, listed, strict=True)):
                if q is None:
                    continue
                if q.type == "dots":
                    if seen and isinstance(r, dict) and "offset" not in r:  # each its own place: 1/2, 1/3 ... of a cell along x, y, z
                        frac = [(seen * a) % 1.0 for a in (0.5, 0.6180339887, 0.3819660113)]
                        q = replace(q, offset=(q.size * frac[0], q.size * frac[1], q.size * frac[2]))
                    if isinstance(r, dict) and "seed" not in r:
                        q = replace(q, seed=k)
                    seen += 1
                shifted.append(q)
            patterns = tuple(shifted)
            pattern = patterns[0] if patterns else None
            ok = ok and len(patterns) == len(listed)
        if "gradient" in raw and ok:  # (needs the shape's numbers: only when they parsed)
            steps = _parse_gradient(ctx, raw["gradient"], kind, params, color, line, f"{where}.gradient")
            if steps is None:
                ok = False
            else:
                color, bands = steps
                patterns = bands + patterns  # patterns paint over the gradient
                pattern = patterns[0]
        if "decal" in raw:
            decal = _parse_decal(ctx, raw["decal"], line, f"{where}.decal")
            ok = ok and decal is not None
            if decal is not None and decal.per_copy and "array" not in raw:
                ctx.error("E003", "decal per_copy puts it on every copy of an array: this part has no array (a mirror's other side is "
                          "its mirror image: use mirror_id for a decal there)", line, f"{where}.decal")  # fmt: skip
                ok = False
        if "texture" in raw:
            texture = _parse_texture(ctx, raw["texture"], line, f"{where}.texture", at)
            ok = ok and texture is not None
            if texture is not None and texture.project == "cylindrical" and ((mirror and mirror_id is None) or copies):
                ctx.error("E003", "a cylindrical texture wraps round one axis: it can't follow mirror or array copies (use mirror_id, "
                          "or project: box)", line, f"{where}.texture")  # fmt: skip
                ok = False
    else:
        for paint in ("color", "material", "pattern", "gradient", "decal", "texture", "id"):
            if paint in raw and not (op == "cut" and paint in ("color", "material")):
                ctx.error("E003", f"a {op} part removes material: it has no {paint}" + (" (a cut's color paints the walls it makes)" if op == "cut" else ""),
                          line, f"{where}.{paint}")  # fmt: skip
                ok = False
        if op == "cut" and "color" in raw:  # paints the walls it makes (#178)
            c = _color(ctx, raw["color"], line, f"{where}.color")
            material = raw.get("material", "default")
            if not isinstance(material, str) or material not in ctx.materials:
                ctx.error("E005", f"unknown material {material!r}; the style has: {', '.join(sorted(ctx.materials))}", line, f"{where}.material")
                ok = False
            if c is None:
                ok = False
            else:
                color = c
        elif op == "cut" and "material" in raw:
            ctx.error("E003", "a cut's material goes with its color (the walls it paints)", line, f"{where}.material")
            ok = False
    loose = raw.get("loose", False)
    if not isinstance(loose, bool):
        ctx.error("E003", "loose must be true or false (true: this part may float free; lint W103 ignores it)", line, f"{where}.loose")
        ok = False
    hard = raw.get("hard")
    if hard is not None and not isinstance(hard, bool):
        ctx.error("E003", "hard is true (exact polygons: crisp edges, designed facets) or false (the smooth field)", line, f"{where}.hard")
        ok = False
    bevel, chamfer, segments = raw.get("bevel", 0.0), raw.get("chamfer", 0.0), raw.get("segments", 2)
    for key, value in (("bevel", bevel), ("chamfer", chamfer)):
        if not _num(value) or value < 0:
            ctx.error("E003", f"{key} is the width of the band cut along a hard part's edges in metres, e.g. 0.02", line, f"{where}.{key}")
            ok = False
    if not isinstance(segments, int) or isinstance(segments, bool) or not 1 <= segments <= 4:
        ctx.error("E003", "segments is how many flat bands make a bevel (1-4; a chamfer is 1)", line, f"{where}.segments")
        ok = False
    if ok and bevel and chamfer:
        ctx.error("E003", "a part has bevel (rounded bands) or chamfer (one flat band), not both", line, where)
        ok = False
    if ok and (bevel or chamfer) and kind not in BEVEL_SHAPES:
        ctx.error("E003", f"bevel and chamfer work on {', '.join(BEVEL_SHAPES)} (round shapes: use sides)", line, where)
        ok = False
    if ok and (bevel or chamfer):
        limit = (min(params["size"]) if kind in ("box", "wedge") else min(2 * params["radius"], params["height"]) if kind in ("cylinder", "cone")
                 else params["height"]) / 2  # fmt: skip
        if max(bevel, chamfer) >= limit:
            ctx.error("E003", f"{'bevel' if bevel else 'chamfer'} {max(bevel, chamfer):g} must be less than half the {kind}'s smallest side ({limit:g})",
                      line, where)  # fmt: skip
            ok = False
    asks_hard = crisp or bool(bevel or chamfer) or "sides" in spec
    if ok and (hard is True or (hard is None and asks_hard)) and any(q.type == "pixel" for q in patterns):
        ctx.error("E003", "a pixel pattern goes on a smooth part (its cells are cut into the surface); drop hard / sides / bevel / blend: none, "
                  "or use a texture", line, f"{where}.pattern")  # fmt: skip
        ok = False
    if ok and (hard is True or (hard is None and asks_hard)) and (twist or noise is not None or fold is not None or scale is not None):
        ctx.error("E003", "a hard part (sides, bevel, chamfer, blend: none or hard: true) can't twist, scale or have noise or folds: those need the "
                  "smooth field",
                  line, where)  # fmt: skip
        ok = False
    keep = raw.get("keep")
    if keep is not None and not isinstance(keep, bool):
        ctx.error("E003", "keep is true (this detail survives every LOD at full detail) or false", line, f"{where}.keep")
        ok = False
    uv = None
    if "uv" in raw:
        u_raw = raw["uv"]
        u_map = {"project": u_raw} if isinstance(u_raw, str) else u_raw if isinstance(u_raw, dict) else {}
        u_scale = u_map.get("scale", [1, 1])
        if u_map.get("project") not in PROJECTIONS or u_map.get("axis", "y") not in UV_AXES or any(k not in ("project", "axis", "scale") for k in u_map) \
                or not (isinstance(u_scale, list) and len(u_scale) == 2 and all(_num(v) and v != 0 for v in u_scale)) or op != "add":
            ctx.error("E003", f"uv projects texture coordinates from the part's shape: uv: {'|'.join(PROJECTIONS)}, or "
                      "{ project: cylindrical, axis: y, scale: [1, 4] } (on an adding part)", line, f"{where}.uv")  # fmt: skip
            ok = False
        else:
            uv = UVSpec(str(u_map["project"]), UV_AXES[u_map.get("axis", "y")], (float(u_scale[0]), float(u_scale[1])))
    attr: tuple[tuple[str, float], ...] = ()
    if "attr" in raw:
        a_raw = raw["attr"]
        if not isinstance(a_raw, dict) or not a_raw or not all(isinstance(k, str) and ATTR_RE.match(k) and _num(v) for k, v in a_raw.items()) \
                or op != "add":
            ctx.error("E003", "attr is named numbers a shader reads per vertex: attr: { heat: 0.9 } (names: lower case letters, digits, _; "
                      "on an adding part)", line, f"{where}.attr")  # fmt: skip
            ok = False
        else:
            attr = tuple(sorted((str(k), float(v)) for k, v in a_raw.items()))
    fit = None
    if "fit" in raw:
        f_raw = raw["fit"]
        f_to = f_raw if isinstance(f_raw, str | list) else f_raw.get("to") if isinstance(f_raw, dict) else None
        f_ids = [f_to] if isinstance(f_to, str) else f_to if isinstance(f_to, list) and f_to and all(isinstance(x, str) for x in f_to) else None
        f_gap = f_raw.get("gap", 0.01) if isinstance(f_raw, dict) else 0.01
        if (isinstance(f_raw, dict) and any(k not in ("to", "gap") for k in f_raw)) or f_ids is None or not _num(f_gap) \
                or float(f_gap) < 0 or not shell or op != "add":
            ctx.error("E003", "fit wraps a shell around other parts: fit: head, or { to: [chest, spine], gap: 0.01 }, on a part with shell: "
                      "{ thickness, open } (its own shape says how far it reaches)", line, f"{where}.fit")  # fmt: skip
            ok = False
        else:
            fit = (tuple(str(x) for x in f_ids), float(f_gap))
    if fit is not None and fold is not None:
        ctx.error("E003", "folds shape a part's own surface: a fitted shell's wall follows the parts it wraps; fold those, or drop fit",
                  line, f"{where}.folds")  # fmt: skip
        ok = False
    if not ok:
        return []
    open_axis = None
    if open_side is not None:
        open_axis = (AXES[open_side[-1]], -1.0 if open_side.startswith("-") else 1.0)
    if kind in ("tube", "lock") and params.pop("smooth", False):  # a curve through the points, as short straight pieces;
        exact = hard is True or raw.get("blend") == "none" or "sides" in spec or bool(bevel or chamfer)  # fewer for exact
        params["points"] = smooth_path(params["points"], HARD_PATH_STEPS if exact else PATH_STEPS)  # polygons (a union of pieces)
    if fold is not None and kind == "capsule":  # round its own axis (#315)
        fold = replace(fold, axis=(tuple(map(float, params["from"])), tuple(map(float, params["to"]))))  # type: ignore[arg-type]
    elif fold is not None and kind == "tube":  # round its ends' line (a trouser leg)
        fold = replace(fold, axis=(tuple(map(float, params["points"][0])), tuple(map(float, params["points"][-1]))))  # type: ignore[arg-type]
    geom = Geometry(kind, params, np.array(at), rotation, mirror if mirror_id is None else (), copies or (IDENTITY,),
                    op, float(blend), float(shell), float(twist), noise, str(shell_side), open_axis, scale=scale, folds=fold)  # fmt: skip
    hard_fields = {"hard": hard, "crisp": crisp, "bevel": float(bevel or chamfer), "segments": 1 if chamfer else int(segments), "fit": fit,
                   "keep": keep, "cut_only": cut_only, "blend_to": blend_to, "detail": detail, "uv": uv, "patterns": patterns, "attr": attr,
                   "texture": texture, "color_blend": float(color_blend), "color_blend_set": "color_blend" in raw, "density": float(density), "fine": None if fine is None else float(fine), "on": on,
                   "skin_falloff": None if skin_falloff is None else float(skin_falloff), "wall": op == "cut" and "color" in raw}  # fmt: skip
    parts = [Part(index, str(part_id), geom, color[0], color[1], material, pattern, decal, line, where, loose=bool(loose), **hard_fields)]
    if mirror_id is not None:
        mirrored = _reflect(geom, mirror[0])
        twin_decal = decal
        if decal is not None:
            at_m = list(decal.at)
            at_m[mirror[0]] = -at_m[mirror[0]]
            axis_m = decal.axis if decal.axis.lstrip("-") != "xyz"[mirror[0]] else (decal.axis[1:] if decal.axis.startswith("-") else "-" + decal.axis)
            twin_decal = replace(decal, axis=axis_m, at=(at_m[0], at_m[1], at_m[2]))  # (per_copy and the rest kept)
        twin_fields = dict(hard_fields)
        if texture is not None:  # the tiling's centre mirrored too
            t_at = list(texture.at)
            t_at[mirror[0]] = -t_at[mirror[0]]
            twin_fields["texture"] = Decal(texture.image, texture.axis, (t_at[0], t_at[1], t_at[2]), texture.size, texture.project)
        parts.append(Part(index, str(mirror_id), mirrored, color[0], color[1], material, pattern, twin_decal, line, where, str(part_id), mirror[0],
                          bool(loose), **twin_fields))  # fmt: skip
    return parts


PATH_KEYS = ("path", "path_scale", "path_tolerance")
TEXT_KEYS = ("text", "font", "text_size", "text_align", "letter_spacing", "line_spacing", "font_axes")


def _loop_area(loop: list[list[float]]) -> float:
    return sum(loop[i - 1][0] * loop[i][1] - loop[i][0] * loop[i - 1][1] for i in range(len(loop))) / 2


def _parse_path(ctx: _Ctx, spec: dict[str, Any], line: int | None, where: str) -> list[list[list[float]]] | None:
    """An extrude's SVG `path` (or `text` in a `font`) as outlines [[x, z], ...] (the biggest one becomes `points`,
    the rest `holes`)."""
    from kiln.svgpath import PathError, outlines

    if "text" in spec:
        d = _text_path(ctx, spec, line, where)
        if d is None:
            return None
        scale, tol = 1.0, spec.get("path_tolerance", 0.002)
        where = f"{where}.text"
    else:
        d, scale, tol = spec["path"], spec.get("path_scale", 1.0), spec.get("path_tolerance", 0.002)
        where = f"{where}.path"
    if not isinstance(d, str) or not _num(scale) or scale == 0 or not _num(tol) or tol <= 0:
        ctx.error("E003", "path is SVG path data (\"M 0 0 L 1 0 Q 1 1 0 1 Z\"; y runs down, onto z); path_scale: metres per path unit "
                  "(a 1000-unit font em at 0.001), path_tolerance: metres a curve may be off (0.002)", line, where)  # fmt: skip
        return None
    try:
        loops = outlines(d, float(scale), float(tol))
    except PathError as e:
        ctx.error("E003", f"{where.rsplit('.', 1)[1]}: {e}", line, where)
        return None
    out = [[[x, y] for x, y in loop] for loop in loops]
    if "text" in spec:  # fonts fill nonzero: overlapping contours of a glyph join (SVG paths keep even-odd)
        from kiln.fillrule import nonzero

        out = nonzero(out)
    return out


def _text_path(ctx: _Ctx, spec: dict[str, Any], line: int | None, where: str) -> str | None:
    from kiln.fonttext import ALIGN, FontError, text_path

    text, font = spec.get("text"), spec.get("font")
    size, align = spec.get("text_size", 0.1), spec.get("text_align", "center")
    letter, rows = spec.get("letter_spacing", 0.0), spec.get("line_spacing", 1.2)
    axes = spec.get("font_axes")
    if axes is not None and not (isinstance(axes, dict) and axes and all(isinstance(k, str) and len(k) == 4 and _num(v) for k, v in axes.items())):
        ctx.error("E003", "font_axes picks a variable font's instance: { wght: 900 } (4-letter axis tags: wght, wdth, slnt, opsz, ...)", line, f"{where}.font_axes")
        return None
    if (not isinstance(text, str) or not text.strip() or not isinstance(font, str) or not _num(size) or size <= 0 or align not in ALIGN
            or not _num(letter) or not _num(rows) or rows <= 0 or any(k in spec for k in ("path", "path_scale"))):  # fmt: skip
        ctx.error("E003", "text: \"KILN\" (\\n for more lines) with font: fonts/sign.ttf (a .ttf or .otf, relative to the project "
                  "folder), text_size: metres per em (0.1), text_align: left|center|right, letter_spacing: metres (0), "
                  "line_spacing: ems (1.2); not with path", line, f"{where}.text")  # fmt: skip
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    file = (base / font).resolve()
    if not file.is_file():
        ctx.error("E011", f"font {font} not found (paths are relative to the project folder)", line, f"{where}.font")
        return None
    try:
        return text_path(file, text, float(size), str(align), float(letter), float(rows), {k: float(v) for k, v in axes.items()} if axes else None)
    except FontError as e:
        ctx.error("E003", str(e), line, f"{where}.font")
        return None


def _parse_aim(raw: Any) -> tuple[tuple[float, ...], np.ndarray, float, float] | None:
    """(midpoint, rotation taking +y to from->to (then rolled about it), roll, length) of an `aim`."""
    if isinstance(raw, list) and len(raw) == 2:
        raw = {"from": raw[0], "to": raw[1]}
    if not isinstance(raw, dict) or any(k not in ("from", "to", "roll") for k in raw):
        return None
    a, b, roll = _vec(raw.get("from")), _vec(raw.get("to")), raw.get("roll", 0)
    if a is None or b is None or not _num(roll):
        return None
    d = np.subtract(b, a)
    length = float(np.linalg.norm(d))
    if length <= 1e-9:
        return None
    d = d / length
    y = np.array([0.0, 1.0, 0.0])
    axis = np.cross(y, d)
    if np.linalg.norm(axis) < 1e-9:
        turn = np.eye(3) if d[1] > 0 else axis_rotation(np.array([1.0, 0.0, 0.0]), 180.0)
    else:
        turn = axis_rotation(axis, math.degrees(math.acos(max(-1.0, min(1.0, float(d[1]))))))
    if roll:
        turn = axis_rotation(d, float(roll)) @ turn
    mid = tuple(float(v) for v in (np.add(a, b) / 2))
    return mid, np.round(turn, 12), float(roll), length


def _parse_on(raw: Any) -> OnSurface | None:
    if not isinstance(raw, dict) or any(k not in ("part", "near", "offset", "roll", "align") for k in raw):
        return None
    ids = raw.get("part")
    ids = [ids] if isinstance(ids, str) else ids
    near, offset, roll, align = _vec(raw.get("near")), raw.get("offset", 0.0), raw.get("roll", 0.0), raw.get("align", True)
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids) or near is None or not _num(offset) \
            or not _num(roll) or not isinstance(align, bool):
        return None
    return OnSurface(tuple(ids), (float(near[0]), float(near[1]), float(near[2])), float(offset), float(roll), align)


def _place_on(ctx: _Ctx, model: Model, done: set[int]) -> None:
    """Resolve `on:` in order (a part may sit on one placed before it): walk `near` onto the blended surface of the
    named earlier parts (cuts before it apply; detail parts are only in the normal map, so not), then move and turn
    the part; its mirror_id twin follows. Parts in `done` were placed already (before a hardware part read them)."""
    for k, part in enumerate(model.parts):
        on = part.on
        if on is None or part.twin_of is not None or k in done:
            continue
        done.add(k)
        earlier = [q for q in model.parts[:k] if not q.detail]
        active = frozenset(j for j, q in enumerate(earlier) if q.id in on.ids and q.geometry.op == "add")
        if not active:
            if not model.template:  # a template may sit its parts on another template's (a helmet's spikes on a head)
                ctx.error("E003", f"on: no earlier part has id {', '.join(on.ids)} (a part sits on parts listed before it)", part.line,
                          f"{part.where}.on")  # fmt: skip
            continue
        field = Field([q.geometry for q in earlier], 0.05, active)
        p = np.array([on.near], dtype=float)
        lo, hi = field.bounds()
        eps = max(1e-5, float(np.linalg.norm(hi - lo)) * 1e-5)
        for _ in range(64):  # walk onto the surface along the field's gradient
            d = field.distance(p)
            p = p - d[:, None] * field.gradient(p, eps)
            if abs(float(d[0])) < 1e-7:
                break
        normal = field.gradient(p, eps)[0]
        if abs(float(field.distance(p)[0])) > 1e-4 or not np.isfinite(normal).all():
            ctx.error("E003", f"on: the walk from near {list(on.near)} along the field doesn't settle on the surface of {', '.join(on.ids)}; "
                      "start it just outside the spot", part.line, f"{part.where}.on")  # fmt: skip
            continue
        g = part.geometry
        g.at = p[0] + normal * on.offset
        if on.align:
            turn = _parse_aim({"from": [0, 0, 0], "to": normal.tolist(), "roll": on.roll})
            assert turn is not None
            g.rotation = turn[1] if g.rotation is None else turn[1] @ g.rotation
        g.at = np.round(g.at, 9)
        for twin in model.parts:
            if twin.twin_of == part.id:
                r = _reflect(g, twin.twin_axis)
                twin.geometry.at, twin.geometry.rotation, twin.geometry.copies = r.at, r.rotation, r.copies


RELIEF_FIELDS = {"on", "on_colors", "except", "displace", "kind", "length", "width", "lift", "density", "flow", "tips", "jitter", "color", "color_to", "under", "seed", "fade"}
RELIEF_RANGES = {"length": (0.005, 2.0, "metres along the flow"), "width": (0.005, 2.0, "metres across the flow"),
                 "lift": (0.0005, 0.1, "metres the tip stands off the surface"), "density": (0.1, 6.0, "1 just covers the surface, more overlaps"),
                 "jitter": (0.0, 1.0, "variation of size and angle"), "under": (0.0, 1.0, "how much darker the surface is under a tip"),
                 "fade": (0.0, 2.0, "metres over which patches thin out toward the edge of `on`")}  # fmt: skip
RELIEF_KINDS = ("fur", "scales", "feathers", "shingles")
RELIEF_MAP = 1024  # the baked maps' size when a model has relief but no normal_map


def _parse_relief(ctx: _Ctx, data: dict[str, Any], model: Model) -> None:
    """`relief:` a list of surface layers; each needs `on` (ids of parts it covers). Turns the baked maps on."""
    raw = data.get("relief")
    if raw is None:
        return
    line = _line(data, "relief")
    example = "relief:\n  - { on: [body], length: 0.09, width: 0.05, lift: 0.008 }"
    if model.source is not None or not model.parts:
        ctx.error("E003", "relief lies on a KILN model's parts: an imported mesh (source) has none", line, "relief")
        return
    if not isinstance(raw, list) or not raw or not all(isinstance(r, dict) for r in raw):
        ctx.error("E003", f"relief is a list of layers, e.g.\n{example}", line, "relief")
        return
    ids = {p.id for p in model.parts if not p.hard}
    for k, entry in enumerate(raw):
        where = f"relief[{k}]"
        eline = _line(entry) or line
        ok = True
        if True in entry and "on" not in entry:  # YAML 1.1 reads a bare `on` key as the boolean true
            entry["on"] = entry.pop(True)
        for key in sorted(str(key) for key in set(entry) - RELIEF_FIELDS):
            ctx.error("E003", f"unknown relief field {key!r}: a layer has {', '.join(sorted(RELIEF_FIELDS))}", eline, f"{where}.{key}")
            ok = False
        on = entry.get("on", [] if "on_colors" in entry else None)
        on = [on] if isinstance(on, str) else on
        if not isinstance(on, list) or not (on or "on_colors" in entry) or not all(isinstance(i, str) for i in on):
            ctx.error("E003", "relief on: the ids of the parts the layer covers, e.g. on: [body, upperleg_l, upperleg_r] "
                      "(or on_colors: [fur] for the faces painted in those colours)", eline, f"{where}.on")  # fmt: skip
            continue
        excluded = entry.get("except", [])
        excluded = [excluded] if isinstance(excluded, str) else excluded
        if not isinstance(excluded, list) or not all(isinstance(i, str) for i in excluded):
            ctx.error("E003", "relief except: the ids of parts the layer leaves bare, e.g. except: [face, chest]", eline, f"{where}.except")
            continue
        missing = [i for i in [*on, *excluded] if i not in ids]
        if missing:
            ctx.error("E003", f"relief on: no smooth part has id {', '.join(missing)} (ids: {', '.join(sorted(ids)) or 'none'}; a mirrored "
                      "part's twin has its own mirror_id)", eline, f"{where}.on")  # fmt: skip
            ok = False
        if entry.get("kind", "fur") not in RELIEF_KINDS:
            ctx.error("E003", "relief kind is fur (notched, pointed tips), scales (round), feathers (one point, a rib) or shingles "
                      "(a straight edge)", eline, f"{where}.kind")  # fmt: skip
            ok = False
        if not isinstance(entry.get("displace", False), bool):
            ctx.error("E003", "relief displace is true or false (true: the mesh moves out by the layer too)", eline, f"{where}.displace")
            ok = False
        layer = Relief(list(on), exclude=list(excluded), kind=str(entry.get("kind", "fur")), displace=entry.get("displace") is True)
        raw_colors = entry.get("on_colors", [])
        raw_colors = [raw_colors] if isinstance(raw_colors, str) else raw_colors
        if not isinstance(raw_colors, list):
            ctx.error("E003", "relief on_colors: palette colours, e.g. on_colors: [fur, fur_dark]", eline, f"{where}.on_colors")
            ok = False
        else:
            for c in raw_colors:
                found = _color(ctx, c, eline, f"{where}.on_colors")
                if found is None:
                    ok = False
                else:
                    layer.on_colors.append(found[0])
        for key, (lo, hi, what) in RELIEF_RANGES.items():
            value = entry.get(key, getattr(layer, key))
            if not _num(value) or not lo <= float(value) <= hi:
                ctx.error("E003", f"relief {key} is {what}: {lo:g} to {hi:g} (default {getattr(layer, key):g})", eline, f"{where}.{key}")
                ok = False
            else:
                setattr(layer, key, float(value))
        for key, lo, hi, what in (("tips", 1, 12, "pointed tips along a patch's lower edge"), ("seed", 0, 2**31 - 1, "a whole number: another seed, other patches")):
            value = entry.get(key, getattr(layer, key))
            if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
                ctx.error("E003", f"relief {key} is {what} ({lo} to {hi})", eline, f"{where}.{key}")
                ok = False
            else:
                setattr(layer, key, value)
        flow = entry.get("flow", "down")
        if flow in ("down", "up", "along"):
            layer.flow = flow
        elif isinstance(flow, list) and len(flow) == 3 and all(_num(v) for v in flow) and any(float(v) != 0 for v in flow):
            layer.flow = (float(flow[0]), float(flow[1]), float(flow[2]))
        else:
            ctx.error("E003", "relief flow is the way the patches point, root to tip: down, up, along (each part's own axis, out from the "
                      "body), or a direction [x, y, z]", eline, f"{where}.flow")  # fmt: skip
            ok = False
        for key in ("color", "color_to"):
            if key in entry:
                found = _color(ctx, entry[key], eline, f"{where}.{key}")
                if found is None:
                    ok = False
                else:
                    setattr(layer, key, found[0])
        if layer.color_to is not None and layer.color is None:
            ctx.error("E003", "relief color_to (the tip colour) goes with color (the root colour)", eline, f"{where}.color_to")
            ok = False
        if ok:
            model.relief.append(layer)
    if model.relief and not model.normal_map:
        model.normal_map = RELIEF_MAP


def _fades(raw_parts: Any) -> bool:
    """Whether some part asks for a colour fade (which brings the baked maps), before the parts are parsed."""
    return isinstance(raw_parts, list) and any(isinstance(p, dict) and _num(p.get("color_blend")) and float(p["color_blend"]) > 0 for p in raw_parts)


def _soft_colours(ctx: _Ctx, data: dict[str, Any], model: Model) -> None:
    """Parts with color_blend need the base colour map (the fade is per texel): the baked maps come on."""
    for p in model.parts:
        if p.color_blend > 0 and (p.geometry.op != "add" or p.hard or p.crisp):
            what = "a cut has no colour of its own" if p.geometry.op != "add" else "a hard part keeps crisp borders"
            ctx.error("E003", f"color_blend fades a smooth adding part's colour into its neighbours': {what}", p.line, f"{p.where}.color_blend")
    if not any(p.color_blend > 0 for p in model.parts):
        return
    if model.source is not None:
        return
    if model.normal_map_off and not model.relief:  # no maps asked: the fade goes in the vertex colours (#262)
        model.vertex_fades = True
    elif not model.normal_map:
        model.normal_map = RELIEF_MAP
        model.fade_maps = True


def apply_style(model: Model, color_blend: float, hard: frozenset[int] = frozenset(), can_bake: bool = True) -> list[Finding]:
    """A style's [shape] color_blend (#262): every smooth adding part that blends into an earlier part of another colour,
    doesn't set its own and isn't made hard (`hard`: builder.hard_parts) fades that far; the baked maps come on when one
    does (as for a part's own color_blend), unless baking isn't installed (`can_bake`: then the default is left off).
    Then a normal_strength with no map is an error."""
    if not can_bake and model.fade_maps:  # no baking installed: the fades go in the vertex colours instead (#262)
        model.normal_map, model.fade_maps, model.vertex_fades = 0, False, True
    if color_blend > 0 and model.source is None and can_bake and not model.normal_map_off:
        for k, p in enumerate(model.parts):
            g = p.geometry
            if p.color_blend_set or g.op != "add" or g.blend <= 0 or p.hard or p.crisp or p.detail or k in hard:
                continue
            earlier = [q for j, q in enumerate(model.parts[:k]) if q.geometry.op == "add" and not q.detail
                       and (g.blend_to is None or j in g.blend_to)]  # fmt: skip
            if any(q.color != p.color for q in earlier):  # a border to fade across (a one-colour model bakes nothing)
                p.color_blend = color_blend
        if any(p.color_blend > 0 for p in model.parts) and not model.normal_map:
            model.normal_map, model.fade_maps = RELIEF_MAP, True
    if model.normal_strength_line is not None and not model.normal_map:
        return [Finding("E003", "normal_strength goes with normal_map (the map it scales)", model.path, model.normal_strength_line or None,
                        "normal_strength")]  # fmt: skip
    return []


def _split_detail(ctx: _Ctx, model: Model) -> None:
    """`detail` parts leave the mesh: the model keeps them only in bake_parts (all parts in order, for the normal map),
    and the other parts' part numbers (cut_only, blend_to) are renumbered without them."""

    model.bake_parts = [p.geometry for p in model.parts]
    model.detail = [p.geometry for p in model.parts if p.detail]
    model.detail_ids = {k: p.id for k, p in enumerate(model.parts) if p.detail}
    keep = [k for k, p in enumerate(model.parts) if not p.detail]
    model.bake_index = keep
    new = {old: n for n, old in enumerate(keep)}

    def renumber(s: frozenset[int] | None) -> frozenset[int] | None:
        return None if s is None else frozenset(new[j] for j in s if j in new)

    parts = []
    for k in keep:
        part = model.parts[k]
        g = part.geometry
        if g.cut_only is not None or g.blend_to is not None:  # a copy: bake_parts keeps the original numbering
            part.geometry = replace(g, cut_only=renumber(g.cut_only), blend_to=renumber(g.blend_to))
        parts.append(part)
    for p in model.parts:
        if p.detail and p.hard:
            ctx.error("E003", "a detail part is only in the normal map: it can't be hard", p.line, f"{p.where}.detail")
    if not any(p.geometry.op == "add" for p in parts):
        ctx.error("E009", "every adding part is a detail part: the mesh needs at least one", None, "parts")
    model.parts = parts


def _reflect(g: Geometry, axis: int) -> Geometry:
    """The part mirrored across 0 on `axis`, as a separate part (mirror_id). The local frame stays the same and
    the reflection goes into the placement (a reflection matrix instead of a rotation), so every shape works."""
    flip = np.eye(3)
    flip[axis, axis] = -1.0
    rotation = flip @ (g.rotation if g.rotation is not None else np.eye(3))
    copies = tuple(c if c is IDENTITY else Copy(flip @ c.rotation @ flip, c.pivot @ flip, c.offset @ flip) for c in g.copies)
    return Geometry(g.shape, g.params, g.at @ flip, rotation, (), copies, g.op, g.blend, g.shell, g.twist, g.noise, g.shell_side, g.open,
                    scale=g.scale, blend_to=g.blend_to, folds=g.folds)


def _parse_pattern(ctx: _Ctx, raw: Any, line: int | None, where: str) -> Pattern | None:
    if not isinstance(raw, dict) or raw.get("type") not in PATTERNS:
        ctx.error("E003", f"pattern is {{ type: {'|'.join(PATTERNS)}, color, size (metres), axis: x|y|z }}", line, where)
        return None
    bad = [k for k in raw if k not in ("type", "color", "size", "axis", "width", "at", "frame", "offset", "jitter", "vary", "seed", "rows", "image",
                                       "repeat")]  # fmt: skip
    size, width = raw.get("size", 0.1), raw.get("width", 0.5)
    axis = raw.get("axis", "y")
    c = _color(ctx, raw.get("color"), line, f"{where}.color")
    at = raw.get("at", 0.0)
    problems = [f"unknown field(s) {', '.join(map(str, bad))}"] if bad else []
    if not _num(size) or size <= 0:
        problems.append("size must be > 0 (metres per repeat; band: its thickness)")
    if not _num(width) or not 0 < width < 1:
        problems.append("width must be between 0 and 1")
    if axis not in AXES:
        problems.append("axis must be x, y or z")
    if not _num(at):
        problems.append("at is one number: the band's centre in metres along the axis (not [x, y, z])")
    frame = raw.get("frame", "model")
    if frame not in ("model", "part"):
        problems.append("frame is model (axes in model space) or part (the part's own frame: follows rotate and aim)")
    offset = _vec(raw.get("offset", [0, 0, 0]))
    jitter, vary, seed = raw.get("jitter", 0.0), raw.get("vary", 0.0), raw.get("seed", 0)
    if offset is None:
        problems.append("offset is [x, y, z] metres: the repeat shifted (a second dots pattern between the first's dots)")
    if not _num(jitter) or not 0 <= jitter <= 1 or not _num(vary) or not 0 <= vary <= 1:
        problems.append("jitter and vary are 0 to 1: dots moved and sized at random by up to that share")
    elif (jitter or vary) and raw["type"] != "dots":
        problems.append("jitter and vary are for dots")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 2**31 - 1:
        problems.append("seed is a whole number, 0 to 2147483647")
    if "offset" in raw and raw["type"] == "band":
        problems.append("offset moves a repeat (stripes, checker, dots); a band is placed by at")
    pixels: tuple[str, ...] = ()
    repeat = raw.get("repeat", "auto")
    if raw["type"] == "pixel":
        pixels, why = _pixel_rows(ctx, raw, line, where)
        if why:
            problems.append(why)
        if repeat == "auto":
            repeat = 0
        elif not isinstance(repeat, int) or isinstance(repeat, bool) or not 1 <= repeat <= 256:
            problems.append("repeat is how many times the motif goes round (1-256), or auto (about square cells)")
    else:
        repeat = 0
        if any(k in raw for k in ("rows", "image", "repeat")):
            problems.append("rows, image and repeat are for type: pixel")
    if problems or c is None or (raw["type"] == "pixel" and not pixels):
        if problems:
            ctx.error("E003", "pattern: " + "; ".join(problems), line, where)
        return None
    unit = [0.0, 0.0, 0.0]
    unit[AXES[axis]] = 1.0
    assert offset is not None
    if raw["type"] == "pixel" and "frame" not in raw:
        frame = "part"  # round the part's own axis (a hat band round the hat, wherever it sits)
    return Pattern(str(raw["type"]), c[0], c[1], float(size), (unit[0], unit[1], unit[2]), float(width), float(at), str(frame),
                   offset=(offset[0], offset[1], offset[2]), jitter=float(jitter), vary=float(vary), seed=int(seed), pixels=pixels,
                   repeat=int(repeat))  # fmt: skip


def _pixel_rows(ctx: _Ctx, raw: dict[str, Any], line: int | None, where: str) -> tuple[tuple[str, ...], str | None]:
    """A pixel pattern's motif: `rows` as given, or an image's pixels (alpha over half painted; an image without
    transparency: its dark pixels), top row first."""
    if ("rows" in raw) == ("image" in raw):
        return (), "a pixel pattern takes rows: [\"#..#\", \".##.\"] (# painted) or image: path.png, one of them"
    if "rows" in raw:
        rows = raw["rows"]
        if not isinstance(rows, list) or not rows or not all(isinstance(r, str) and r for r in rows) or len({len(r) for r in rows}) != 1 \
                or len(rows) > 64 or len(rows[0]) > 256:
            return (), "rows is a list of equal-length strings (up to 64 rows of 256): . or space is bare, any other character painted"
        return tuple("".join("#" if ch not in ". " else "." for ch in r) for r in rows), None
    if not isinstance(raw["image"], str):
        return (), "image is a path to a small PNG (relative to the project folder)"
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    path = (base / raw["image"]).resolve()
    if not path.is_file():
        ctx.error("E011", f"pattern image {raw['image']} not found (paths are relative to the project folder)", line, f"{where}.image")
        return (), ""
    from PIL import Image

    img = np.asarray(Image.open(path).convert("RGBA"))
    if img.shape[0] > 64 or img.shape[1] > 256:
        return (), f"image {raw['image']} is {img.shape[1]}x{img.shape[0]}: a pixel motif is at most 256x64"
    if (img[:, :, 3] > 127).all():  # no transparency: the dark pixels are the motif
        mask = img[:, :, :3].astype(float) @ np.array([0.299, 0.587, 0.114]) < 128
    else:
        mask = img[:, :, 3] > 127
    return tuple("".join("#" if m else "." for m in row) for row in mask), None


PATH_SHAPES = ("tube", "capsule", "lock")  # gradient along: path (from the first point to the last)


def _mix(a: str, b: str, t: float) -> str:
    """Two hex colours mixed in OKLab (t = 0: a, 1: b)."""
    from kiln.vendor.color import hex_to_rgb, oklab_to_rgb, rgb_to_hex, rgb_to_oklab

    la, lb = rgb_to_oklab(hex_to_rgb(a)), rgb_to_oklab(hex_to_rgb(b))
    return rgb_to_hex(oklab_to_rgb((la[0] + (lb[0] - la[0]) * t, la[1] + (lb[1] - la[1]) * t, la[2] + (lb[2] - la[2]) * t)))


def _parse_gradient(ctx: _Ctx, raw: Any, kind: str, params: dict[str, Any], color: tuple[str, str], line: int | None,
                    where: str) -> tuple[tuple[str, str], tuple[Pattern, ...]] | None:  # fmt: skip
    """A gradient as `steps` bands: the part's colour (or `from`) at the start, `to` at the end, mixed in OKLab between,
    along the shape's path or one of its axes (its own frame)."""
    usage = ("gradient is { to: colour, from: colour (default: the part's), steps: 2-16 (default 3), along: path|x|y|z } "
             "(path: tube, capsule and lock, from their first point to the last; default path for those, else y)")
    if not isinstance(raw, dict) or "to" not in raw or any(k not in ("to", "from", "steps", "along") for k in raw):
        ctx.error("E003", usage, line, where)
        return None
    to = _color(ctx, raw["to"], line, f"{where}.to")
    start = _color(ctx, raw["from"], line, f"{where}.from") if "from" in raw else color
    steps = raw.get("steps", 3)
    along = raw.get("along", "path" if kind in PATH_SHAPES else "y")
    if not isinstance(steps, int) or isinstance(steps, bool) or not 2 <= steps <= 16 or along not in ("path", "x", "y", "z") \
            or (along == "path" and kind not in PATH_SHAPES):
        ctx.error("E003", usage, line, where)
        return None
    if to is None or start is None:
        return None
    if along == "path":
        pts = np.asarray(params["points"] if kind != "capsule" else [params["from"], params["to"]], float)
        length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
        axis = (0.0, 0.0, 0.0)
        if length < 1e-6:
            ctx.error("E003", "gradient along path: the path has no length (its points are all in one place); use along: x|y|z", line, where)
            return None
    else:
        lo, hi = SHAPES[kind].bounds(params)
        a = AXES[along]
        length = float(hi[a] - lo[a])
        unit = [0.0, 0.0, 0.0]
        unit[a] = 1.0
        axis = (unit[0], unit[1], unit[2])
    bands = tuple(Pattern("along", _mix(start[0], to[0], k / (steps - 1)), f"{start[1]}_to_{to[1]}_{k}" if k < steps - 1 else to[1],
                          max(length / steps, 0.005), axis, 0.5, k / steps, "part", (start[0], to[0], k / (steps - 1)))
                  for k in range(1, steps))  # fmt: skip
    return start, bands


def _parse_decal(ctx: _Ctx, raw: Any, line: int | None, where: str) -> Decal | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("image"), str):
        ctx.error("E003", "decal is { image: decals/logo.png, axis: z, at: [x, y, z], size: [w, h] or texel: metres per pixel }", line, where)
        return None
    axis = raw.get("axis", "z")
    at, size = _vec(raw.get("at")), _vec(raw.get("size"), 2) if "size" in raw else None
    texel, per_copy = raw.get("texel"), raw.get("per_copy", False)
    bad = [k for k in raw if k not in ("image", "axis", "at", "size", "texel", "per_copy")]
    sized = ("size" in raw) != ("texel" in raw) and (size is not None and min(size) > 0 if "size" in raw else _num(texel) and float(texel or 0) > 0)
    if axis not in ("x", "-x", "y", "-y", "z", "-z") or at is None or not sized or bad or not isinstance(per_copy, bool):
        ctx.error("E003", "decal: axis x|-x|y|-y|z|-z (the way it faces), at: [x, y, z] (its centre), size: [w, h] metres or texel: "
                  "metres per image pixel (one of them), per_copy: true (on every copy of an array)", line, where)  # fmt: skip
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    image = (base / raw["image"]).resolve()
    if not image.is_file():
        ctx.error("E011", f"decal image {raw['image']} not found (paths are relative to the project folder)", line, f"{where}.image")
        return None
    if size is None:  # from the image's pixels: the same texel size on every prop (#211)
        from PIL import Image

        with Image.open(image) as img:
            size = (img.width * float(texel or 0), img.height * float(texel or 0))
    return Decal(image, str(axis), (at[0], at[1], at[2]), (size[0], size[1]), per_copy=bool(per_copy))


TEXTURE_KEYS = ("image", "motif", "project", "size", "texel", "at", "axis")
MOTIF_KEYS = ("images", "count", "scale", "rotate", "seed", "pixels")


def _motif_tile(ctx: _Ctx, raw: Any, line: int | None, where: str) -> str | None:
    """A motif print (#312): `count` stamps from `images` (PNGs with alpha, several colours) scattered over one tile,
    each turned up to `rotate` degrees and scaled within `scale` (a share of the tile), wrapping round its edges so it
    tiles without seams; seeded. Written once to .kiln-cache/motifs/ (named by its content); returns its path from the
    project folder, for the texture to tile."""
    import hashlib

    from PIL import Image, UnidentifiedImageError

    form = ("motif is { images: [decals/flower.png, decals/leaf.png] (stamps with alpha), count: 12 (stamps per tile), scale: [0.15, 0.25] "
            "(a stamp's size, share of the tile), rotate: 180 (degrees, either way), seed: 1, pixels: 256 (the tile) }, with the texture's "
            "size: [w, h] or texel")  # fmt: skip
    if not isinstance(raw, dict) or [k for k in raw if k not in MOTIF_KEYS]:
        ctx.error("E003", form, line, where)
        return None
    images, count, scale = raw.get("images"), raw.get("count", 12), raw.get("scale", [0.15, 0.25])
    turn, seed, pixels = raw.get("rotate", 180), raw.get("seed", 1), raw.get("pixels", 256)
    if not isinstance(images, list) or not images or not all(isinstance(i, str) for i in images) or not isinstance(count, int) \
            or isinstance(count, bool) or not 1 <= count <= 400 or not (isinstance(scale, list) and len(scale) == 2 and all(_num(v) for v in scale)
                                                                    and 0 < scale[0] <= scale[1] <= 1) \
            or not _num(turn) or not 0 <= turn <= 180 or not isinstance(seed, int) or not isinstance(pixels, int) or not 32 <= pixels <= 2048:
        ctx.error("E003", form, line, where)
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    stamps = []
    for k, name in enumerate(images):
        path = (base / name).resolve()
        try:
            with Image.open(path) as im:
                stamps.append(im.convert("RGBA"))
        except (OSError, UnidentifiedImageError):
            ctx.error("E011", f"motif image {name} not found or not a PNG (paths are relative to the project folder)", line, f"{where}.images[{k}]")
            return None
    digest = hashlib.sha256(repr((images, count, scale, turn, seed, pixels)).encode())
    for st in stamps:
        digest.update(st.tobytes())
    out = base / ".kiln-cache" / "motifs" / f"{digest.hexdigest()[:20]}.png"
    if not out.is_file():
        rng = np.random.default_rng(seed)
        canvas = Image.new("RGBA", (3 * pixels, 3 * pixels), (0, 0, 0, 0))  # the tile and its eight neighbours
        for _ in range(count):
            st = stamps[int(rng.integers(len(stamps)))]
            side = max(2, int(round(pixels * float(rng.uniform(scale[0], scale[1])))))
            stamp = st.resize((side, max(2, int(round(side * st.height / st.width)))), Image.Resampling.LANCZOS)
            stamp = stamp.rotate(float(rng.uniform(-turn, turn)), resample=Image.Resampling.BICUBIC, expand=True)
            x, y = int(rng.integers(pixels)), int(rng.integers(pixels))
            for dx in (0, pixels, 2 * pixels):  # in every copy, so the middle tile repeats without seams
                for dy in (0, pixels, 2 * pixels):
                    left, top = x + dx - stamp.width // 2, y + dy - stamp.height // 2
                    if left >= 0 and top >= 0 and left + stamp.width <= 3 * pixels and top + stamp.height <= 3 * pixels:
                        canvas.alpha_composite(stamp, (left, top))
        tile = canvas.crop((pixels, pixels, 2 * pixels, 2 * pixels))
        out.parent.mkdir(parents=True, exist_ok=True)
        tile.save(out)
    return str(out.relative_to(base))


def _parse_texture(ctx: _Ctx, raw: Any, line: int | None, where: str, part_at: tuple[float, ...] | None = None) -> Decal | None:
    """`texture: { image, project: box | cylindrical, size: [w, h] | texel: m, at, axis }`: an image tiled over the
    whole part (#184): box faces take it from the side they face, cylindrical wraps it round `axis` through `at`."""
    form = ("texture is { image: textures/x.png, project: box | triplanar | cylindrical, size: [w, h] (metres per tile) or texel: m (per pixel), "
            "at: [x, y, z] (default: the part's centre), axis: x|y|z (cylindrical) }")
    if isinstance(raw, dict) and "motif" in raw and "image" not in raw:  # a print scattered from stamps (#312)
        image_rel = _motif_tile(ctx, raw["motif"], line, f"{where}.motif")
        if image_rel is None:
            return None
        raw = {**{k: v for k, v in raw.items() if k != "motif"}, "image": image_rel}
    if not isinstance(raw, dict) or not isinstance(raw.get("image"), str) or [k for k in raw if k not in TEXTURE_KEYS]:
        ctx.error("E003", form, line, where)
        return None
    project, axis = raw.get("project", "box"), raw.get("axis", "y")
    at = _vec(raw["at"]) if "at" in raw else (part_at or (0.0, 0.0, 0.0))  # default: the part's own centre
    if project not in ("box", "cylindrical", "triplanar") or axis not in ("x", "y", "z") or at is None or ("size" in raw) == ("texel" in raw):
        ctx.error("E003", form + "; give size or texel, not both", line, where)
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    image = (base / raw["image"]).resolve()
    if not image.is_file():
        ctx.error("E011", f"texture image {raw['image']} not found (paths are relative to the project folder)", line, f"{where}.image")
        return None
    if "size" in raw:
        size = _vec(raw["size"], 2)
    else:
        texel = raw["texel"]
        from PIL import Image, UnidentifiedImageError

        try:
            with Image.open(image) as im:
                w, h = im.size
        except (OSError, UnidentifiedImageError):
            ctx.error("E011", f"texture image {raw['image']} isn't an image KILN can read (PNG)", line, f"{where}.image")
            return None
        size = (float(texel) * w, float(texel) * h) if isinstance(texel, (int, float)) and not isinstance(texel, bool) and texel > 0 else None
    if size is None or min(size) <= 0:
        ctx.error("E003", form + "; size and texel are positive", line, where)
        return None
    return Decal(image, str(axis), (at[0], at[1], at[2]), (size[0], size[1]), str(project))


def _parse_rig(ctx: _Ctx, raw: Any, ids: set[str], line: int | None, template: bool = False) -> dict[str, RigEntry]:
    rig: dict[str, RigEntry] = {}
    if raw is None:
        return rig
    if not isinstance(raw, dict):
        ctx.error("E007", "rig maps part ids to { pivot: [x, y, z], parent: id, meta: {...}, separate: true }", line, "rig")
        return rig
    for part_id, spec in raw.items():
        rline = _line(raw, part_id) or line
        where = f"rig.{part_id}"
        if part_id not in ids:
            if not template:  # a template's rig may name parts another template brings
                ctx.error("E007", f"rig: no part has id {part_id!r} (ids: {', '.join(sorted(ids))})", rline, where)
            continue
        spec = spec if spec is not None else {}
        if not isinstance(spec, dict) or any(k not in ("pivot", "parent", "meta", "separate", "sockets", "under", "revealed", "gib", "fold") for k in spec):
            ctx.error("E007", "a rig entry is { pivot: [x, y, z], parent: id, meta: { key: value }, separate: true|false, sockets: { name: [x, y, z] }, "
                      "under: { color, material, gap }, revealed: [ids], fold: true, gib: true | [ids] }", rline, where)  # fmt: skip
            continue
        pivot = _vec(spec["pivot"]) if "pivot" in spec else None
        if "pivot" in spec and pivot is None:
            ctx.error("E007", "pivot must be [x, y, z] metres (the joint: shoulder, hip, hinge)", rline, f"{where}.pivot")
            continue
        parent = spec.get("parent")
        if parent is not None and ((parent not in ids and not template) or parent == part_id):
            ctx.error("E007", f"parent must be another part id ({', '.join(sorted(ids))})", rline, f"{where}.parent")
            continue
        meta = spec.get("meta", {})

        def plain(v: Any) -> bool:
            return isinstance(v, str | bool) or _num(v)

        if not isinstance(meta, dict) or not all(isinstance(k, str) and (plain(v) or (isinstance(v, list) and all(plain(x) for x in v)))
                                                 for k, v in meta.items()):  # fmt: skip
            ctx.error("E007", "meta maps names to plain values or flat lists, e.g. { hitzone: head, damage: 2, seat: [0, 1.5, 0] }",
                      rline, f"{where}.meta")  # fmt: skip
            continue
        meta = {k: tuple(v) if isinstance(v, list) else v for k, v in meta.items()}
        separate = spec.get("separate", False)
        if not isinstance(separate, bool):
            ctx.error("E007", "separate must be true or false", rline, f"{where}.separate")
            continue
        revealed = spec.get("revealed", [])
        if isinstance(revealed, str):
            revealed = [revealed]
        if not isinstance(revealed, list) or not all(isinstance(r, str) and (r in ids or template) and r not in (part_id, ROOT_ID) for r in revealed):
            ctx.error("E007", f"revealed lists the parts whose loss shows this one (a stump cap under an arm): revealed: [arm_l] "
                      f"(ids: {', '.join(sorted(i for i in ids if i not in (part_id, ROOT_ID)))})", rline, f"{where}.revealed")  # fmt: skip
            continue
        if revealed and separate is False and "separate" in spec:
            ctx.error("E007", "a revealed part is its own piece (separate): drop separate: false", rline, f"{where}.separate")
            continue
        fold = spec.get("fold", False)
        if not isinstance(fold, bool) or (fold and parent in (None, ROOT_ID)):
            ctx.error("E007", "fold: true folds a part into its parent while none of its revealed parts is in the model (hair under a "
                      "helmet, on a head without one): { parent: head, revealed: [helmet], fold: true }", rline, f"{where}.fold")  # fmt: skip
            continue
        separate = separate or bool(revealed)
        raw_gib = spec.get("gib", False)
        gib: tuple[str, ...] = ()
        if raw_gib is True:
            gib = ("*",)
        elif isinstance(raw_gib, list) and raw_gib and all(isinstance(g, str) and (g in ids or template) and g != ROOT_ID for g in raw_gib):
            gib = tuple(dict.fromkeys([str(part_id), *(str(g) for g in raw_gib)]))
        elif raw_gib is not False:
            ctx.error("E007", "gib exports the part as a closed piece that comes off: gib: true (it and the parts hanging from it) or "
                      f"gib: [ids] (ids: {', '.join(sorted(i for i in ids if i != ROOT_ID))})", rline, f"{where}.gib")  # fmt: skip
            continue
        raw_sockets = spec.get("sockets", {})
        sockets = {k: _vec(v) for k, v in raw_sockets.items()} if isinstance(raw_sockets, dict) else None
        if sockets is None or any(not isinstance(k, str) or not NAME_RE.match(k) or v is None for k, v in sockets.items()):
            ctx.error("E007", "sockets name points on the part (model space, as built): { tip: [0, 2.4, 0.3], load: [0, 1.1, -1.2] }",
                      rline, f"{where}.sockets")  # fmt: skip
            continue
        under = None
        if "under" in spec:
            u = spec["under"]
            c = _color(ctx, u.get("color"), rline, f"{where}.under.color") if isinstance(u, dict) else None
            gap: Any = u.get("gap", 0.02) if isinstance(u, dict) else None
            mat = u.get("material", "default") if isinstance(u, dict) else None
            if not isinstance(u, dict) or any(k not in ("color", "material", "gap") for k in u) or c is None or not _num(gap) or float(gap) < 0 \
                    or mat not in ctx.materials or not separate:
                ctx.error("E007", "under paints what a separate part covers (hair under a helmet): under: { color: hair, material: default, gap: 0.02 } "
                          "on a rig entry with separate: true", rline, f"{where}.under")  # fmt: skip
                continue
            under = (c[0], c[1], str(mat), float(gap))
        rig[str(part_id)] = RigEntry((pivot[0], pivot[1], pivot[2]) if pivot else None,
                                     None if parent in (None, ROOT_ID) else str(parent), tuple(sorted(meta.items())), separate,
                                     tuple(sorted((k, (v[0], v[1], v[2])) for k, v in sockets.items() if v is not None)), under,
                                     tuple(str(r) for r in revealed), gib)  # fmt: skip
    for part_id in rig:
        seen = [part_id]
        parent = rig[part_id].parent
        while parent is not None:
            if parent in seen:
                ctx.error("E007", f"rig parents form a cycle: {' -> '.join([*seen, parent])}", _line(raw, part_id) or line, f"rig.{part_id}")
                break
            seen.append(parent)
            parent = rig[parent].parent if parent in rig else None
    return rig


def _mirror_rig(rig: dict[str, RigEntry], parts: list[Part]) -> dict[str, RigEntry]:
    """A rig entry for arm_l also rigs its mirror_id twin (pivot mirrored, parent's twin if it has one)."""
    twins = {p.twin_of: (p.id, p.twin_axis) for p in parts if p.twin_of is not None}
    out = dict(rig)
    for src, (twin, axis) in twins.items():
        if src in rig and twin not in rig:
            e = rig[src]
            pivot = None
            if e.pivot is not None:
                pv = list(e.pivot)
                pv[axis] = -pv[axis]
                pivot = (pv[0], pv[1], pv[2])
            parent = twins[e.parent][0] if e.parent in twins else e.parent
            sockets = []
            for name, point in e.sockets:
                q = list(point)
                q[axis] = -q[axis]
                sockets.append((name, (q[0], q[1], q[2])))
            revealed = tuple(twins[r][0] if r in twins else r for r in e.revealed)
            gib = tuple(twins[g][0] if g in twins else g for g in e.gib)
            out[twin] = RigEntry(pivot, parent, e.meta, e.separate, tuple(sockets), e.under, revealed, gib)
    return out


def _pose(ctx: _Ctx, raw: Any, ids: set[str], line: int | None, where: str) -> dict[str, PartPose] | None:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        ctx.error("E008", "a pose maps part ids to { offset: [x, y, z], rotate: [x, y, z], scale: s | [x, y, z] }", line, where)
        return None
    out: dict[str, PartPose] = {}
    for part_id, change in raw.items():
        pwhere = f"{where}.{part_id}"
        if part_id not in ids:
            ctx.error("E008", f"unknown part id {part_id!r} (ids: {', '.join(sorted(ids))})", line, pwhere)
            return None
        if not isinstance(change, dict) or any(k not in ("offset", "rotate", "scale", "aim", "reach", "pole") for k in change):
            ctx.error("E008", "a part's pose is { offset: [x, y, z] metres, rotate: [x, y, z] degrees, scale: s | [x, y, z] }, or instead of "
                      "rotate aim: [x, y, z] (point it there) / reach: [x, y, z] (two-bone IK, pole: [x, y, z])", line, pwhere)  # fmt: skip
            return None
        targets = {k: _vec(change[k]) for k in ("aim", "reach", "pole") if k in change}
        if any(v is None for v in targets.values()):
            ctx.error("E008", "aim, reach and pole are model-space points [x, y, z] (metres)", line, pwhere)
            return None
        if len({"aim", "reach", "rotate"} & set(change)) > 1 or ("pole" in change and "reach" not in change) or (targets and part_id == ROOT_ID):
            ctx.error("E008", "a part's pose takes one of rotate, aim and reach (pole goes with reach); the root has none", line, pwhere)
            return None
        offset = _vec(change.get("offset", [0, 0, 0]))
        rotate = _vec(change.get("rotate", [0, 0, 0]))
        sc = change.get("scale", 1.0)
        scale = (float(sc),) * 3 if _num(sc) else _vec(sc)
        if offset is None or rotate is None or scale is None or min(scale) <= 0:
            ctx.error("E008", "offset and rotate are [x, y, z]; scale is a number or [x, y, z] (> 0)", line, pwhere)
            return None
        aim, reach, pole = (_point3(targets.get(k)) for k in ("aim", "reach", "pole"))
        out[str(part_id)] = PartPose((offset[0], offset[1], offset[2]), (rotate[0], rotate[1], rotate[2]), (scale[0], scale[1], scale[2]),
                                     aim=aim, reach=reach, pole=pole)  # fmt: skip
    return out


def _as_glb(ctx: _Ctx, file: Path, rule: str, line: int | None, where: str) -> Path | None:
    """`file`, or for .fbx/.blend/.obj the glb Blender exports of it (cached in .kiln-cache/blender/)."""
    from kiln.blender import BlenderError, converted, needs_blender

    if not needs_blender(file):
        return file
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    try:
        return converted(file, base / ".kiln-cache")
    except BlenderError as exc:
        ctx.error(rule, str(exc), line, where)
        return None


def _parse_import(ctx: _Ctx, name: str, spec: dict[str, Any], line: int | None, where: str, humanoid: bool,
                  joint_map: JointMap | None = None) -> Animation | None:  # fmt: skip
    """An animation retargeted from a clip library: { import: imports/Rig_Medium_General.glb, clip: Idle_A }."""
    bad = [k for k in spec if k not in ("import", "clip", "fps", "loop", "speed", "retarget")]
    fps, loop, speed = spec.get("fps", 30), spec.get("loop", True), spec.get("speed", 1.0)
    if bad or not isinstance(spec.get("import"), str) or not isinstance(spec.get("clip"), str) or not _num(fps) or not 0 < fps <= 120 \
            or not isinstance(loop, bool) or not _num(speed) or speed <= 0:
        ctx.error("E008", "an imported animation is { import: imports/clips.glb, clip: Walking_A, fps: 30, loop: true, speed: 1, "
                  "retarget: { keep: { upperarm: 0.35 }, offset: { upperarm_l: [0, 0, -12] } } }", line, where)  # fmt: skip
        return None
    adjust = _parse_retarget(ctx, spec.get("retarget"), line, f"{where}.retarget", joint_map)
    if "retarget" in spec and adjust is None:
        return None
    if not humanoid and joint_map is None:
        ctx.error("E008", "imported clips play on humanoids: add skeleton: humanoid (and name the parts after its joints), or map "
                  "the bones onto the clip's joints: skeleton: { map: { body: Torso, ... } }", line, where)  # fmt: skip
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    file = (base / spec["import"]).resolve()
    if not file.is_file():
        ctx.error("E008", f"animation file {spec['import']} not found (paths are relative to the project)", line, f"{where}.import")
        return None
    glb = _as_glb(ctx, file, "E008", line, f"{where}.import")
    if glb is None:
        return None
    file = glb
    from kiln.retarget import clip_names

    try:
        names = clip_names(file)
    except Exception as exc:  # noqa: BLE001 - any unreadable file is the same mistake
        ctx.error("E008", f"can't read {spec['import']}: {exc}", line, f"{where}.import")
        return None
    if spec["clip"] not in names:
        ctx.error("E008", f"{spec['import']} has no clip {spec['clip']!r} (it has: {', '.join(names)})", line, f"{where}.clip")
        return None
    if joint_map is not None and not _check_joints(ctx, joint_map, file, spec["import"], line, where):
        return None
    return Animation(name, float(fps), loop, "linear", [], None, (file, str(spec["clip"]), float(speed)), adjust)


def _check_joints(ctx: _Ctx, joint_map: JointMap, file: Path, shown: str, line: int | None, where: str) -> bool:
    """Every joint a skeleton map names is in the clip file (a typo would leave its bone still)."""
    import difflib

    from kiln.retarget import joint_names

    have = joint_names(file)
    named = [(f"skeleton.map.{bone}", joint) for bone, joint in joint_map.joints.items()]
    if joint_map.root_motion is not None:
        named.append(("skeleton.root_motion", joint_map.root_motion))
    ok = True
    for at, joint in named:
        if joint not in have:
            near = difflib.get_close_matches(joint, have, 3, 0.5)
            hint = f"did you mean {', '.join(near)}?" if near else f"its joints: {', '.join(have[:40])}{', ...' if len(have) > 40 else ''}"
            ctx.error("E008", f"{at} names joint {joint!r}, which {shown} doesn't have ({hint}): map the bone onto one of the clip's joints",
                      line, where)  # fmt: skip
            ok = False
    return ok


def _parse_skeleton_map(ctx: _Ctx, raw: dict[str, Any], model: Model, line: int | None) -> JointMap | None:
    """`skeleton: { map: { body: Torso2, neck: { joint: Neck1, child: head } }, root_motion: Torso }`: which clip joint
    drives each KILN bone, which KILN bone aims it (its child), and the clip joint whose movement moves the model."""
    usage = ("skeleton is humanoid, or { map: { <bone id>: <clip joint> | { joint: <clip joint>, child: <bone id> } }, root_motion: <clip joint> } "
             "for any other skeleton (a humanoid uses its standard table; it takes no map)")  # fmt: skip
    mapping = raw.get("map")
    if any(k not in ("map", "root_motion") for k in raw) or not isinstance(mapping, dict) or not mapping:
        ctx.error("E007", usage, line, "skeleton")
        return None
    ids = set(model.ids)
    parent_of = {pid: (model.rig[pid].parent if pid in model.rig else None) or ROOT_ID for pid in ids if pid != ROOT_ID}

    def below(child: str, bone: str) -> bool:  # child is a descendant of bone in the KILN hierarchy
        seen: set[str] = set()
        while child in parent_of and child not in seen:
            seen.add(child)
            child = parent_of[child]
            if child == bone:
                return True
        return False

    joints: dict[str, str] = {}
    children: dict[str, str] = {}
    ok = True
    for bone, spec in mapping.items():
        where = f"skeleton.map.{bone}"
        mline = _line(mapping, bone) or line
        if not isinstance(bone, str) or bone == ROOT_ID or (bone not in ids and not model.template):
            ctx.error("E007", f"skeleton.map: unknown bone {bone!r}: map part ids (bones: {', '.join(sorted(ids - {ROOT_ID}))})", mline, where)
            ok = False
            continue
        if isinstance(spec, str) and spec:
            joints[bone] = spec
            continue
        if not isinstance(spec, dict) or any(k not in ("joint", "child") for k in spec) or not isinstance(spec.get("joint"), str) \
                or not spec["joint"] or ("child" in spec and not isinstance(spec["child"], str)):
            ctx.error("E007", f"a mapped bone is a clip joint name or {{ joint: <clip joint>, child: <bone id> }} (e.g. {bone}: {{ joint: Neck1, child: head }})",
                      mline, where)  # fmt: skip
            ok = False
            continue
        joints[bone] = spec["joint"]
        if "child" in spec:
            children[bone] = spec["child"]
    for bone, child in children.items():
        where = f"skeleton.map.{bone}.child"
        mline = _line(mapping, bone) or line
        if model.template:
            continue
        if child not in ids or child == ROOT_ID:
            ctx.error("E007", f"child {child!r} isn't a bone (bones: {', '.join(sorted(ids - {ROOT_ID}))})", mline, where)
            ok = False
        elif not below(child, bone):
            ctx.error("E007", f"child {child!r} isn't below {bone!r} in the rig: name one of its descendants (give rig: {{ {child}: {{ parent: ... }} }} "
                      "if the hierarchy is off)", mline, where)  # fmt: skip
            ok = False
        elif child not in joints:
            ctx.error("E007", f"child {child!r} isn't mapped: the aim runs from {bone}'s joint to its child's, so map {child} too", mline, where)
            ok = False
    root_motion = raw.get("root_motion")
    if root_motion is not None and (not isinstance(root_motion, str) or not root_motion):
        ctx.error("E007", "root_motion names the clip joint whose movement moves the model (e.g. root_motion: Torso)", _line(raw, "root_motion") or line,
                  "skeleton.root_motion")  # fmt: skip
        ok = False
    if not ok:
        return None
    return JointMap(joints, children, root_motion)


def _parse_retarget(ctx: _Ctx, raw: Any, line: int | None, where: str, joint_map: JointMap | None = None) -> dict[str, dict[str, Any]] | None:
    """`retarget: { keep: { upperarm: 0.35, lowerleg: 0.5 }, offset: { upperarm_l: [-12, 0, -12] } }`: per joint (a
    joint name, or its base name for both sides), the share of the clip's turn away from rest it keeps, and a fixed
    turn (degrees, model axes) added to it. For clips made for another body type (chibi clips on adult bodies)."""
    from kiln.retarget import JOINTS

    if raw is None:
        return None
    bones = set(JOINTS) if joint_map is None else set(joint_map.joints)
    bases = {n[:-2] for n in bones if n.endswith(("_l", "_r"))}
    kind = "a humanoid joint" if joint_map is None else "a mapped bone"
    usage = (f"retarget is {{ keep: {{ <joint>: share 0-2 }}, offset: {{ <joint>: [x, y, z] degrees }} }}; a joint is {kind} "
             f"name or a base name for both sides ({', '.join(sorted(bases))})")  # fmt: skip
    if not isinstance(raw, dict) or not raw or any(k not in ("keep", "offset") for k in raw):
        ctx.error("E008", usage, line, where)
        return None
    keep, offset = raw.get("keep", {}), raw.get("offset", {})
    known = bones | bases
    if not (isinstance(keep, dict) and all(k in known and _num(v) and 0 <= v <= 2 for k, v in keep.items())
            and isinstance(offset, dict) and all(k in known and isinstance(v, list) and len(v) == 3 and all(_num(x) for x in v) for k, v in offset.items())):  # fmt: skip
        ctx.error("E008", usage, line, where)
        return None
    return {"keep": {str(k): float(v) for k, v in keep.items()}, "offset": {str(k): tuple(float(x) for x in v) for k, v in offset.items()}}


def _parse_animations(ctx: _Ctx, raw: Any, ids: set[str], line: int | None, humanoid: bool = False,
                      joint_map: JointMap | None = None) -> dict[str, Animation]:  # fmt: skip
    out: dict[str, Animation] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        ctx.error("E008", "animations maps names to { fps, loop, poses: [...] } or { cycle: { type: walk, ... } }", line, "animations")
        return out
    for name, spec in raw.items():
        aline = _line(raw, name) or line
        where = f"animations.{name}"
        if not isinstance(name, str) or not ANIMATION_RE.match(name):
            ctx.error("E008", "animation names are letters, digits, _ or - (e.g. walk, Idle_A)", aline, where)
            continue
        twin = next((k for k in out if k.lower() == name.lower()), None)
        if twin is not None:  # the same file name on case-insensitive systems (previews), and easily confused
            ctx.error("E008", f"animations {twin!r} and {name!r} differ only in case: rename one", aline, where)
            continue
        if isinstance(spec, dict) and "import" in spec:
            imported = _parse_import(ctx, name, spec, aline, where, humanoid, joint_map)
            if imported is not None:
                out[name] = imported
            continue
        if not isinstance(spec, dict) or ("poses" not in spec and "cycle" not in spec):
            ctx.error("E008", "an animation has poses: [...], cycle: { type: ... }, or both (poses then override the cycle per part)", aline, where)
            continue
        bad = [k for k in spec if k not in ("fps", "loop", "interpolation", "poses", "cycle")]
        fps = spec.get("fps", 12)
        loop = spec.get("loop", True)
        interp = spec.get("interpolation", "linear")
        if bad or not _num(fps) or not 0 < fps <= 120 or not isinstance(loop, bool) or interp not in INTERPOLATIONS:
            hint = ""
            if "frames" in bad:  # (#318) a cycle's frame count goes inside it
                hint = ": frames goes inside the cycle, e.g. walk: { cycle: { type: walk, frames: 16 } }; a poses animation has one frame per pose"
            ctx.error("E008", "animation fields: fps (1-120), loop (true/false), interpolation (linear|step), poses or cycle" + hint, aline, where)
            continue
        poses: list[dict[str, PartPose]] = []
        if "poses" in spec:
            raw_poses = spec["poses"]
            if not isinstance(raw_poses, list) or not raw_poses:
                ctx.error("E008", "poses is a list of poses (one per frame): - { arm_r: { rotate: [0, 0, -60] } }", aline, f"{where}.poses")
                continue
            parsed = [_pose(ctx, p, ids, _line(p) or aline, f"{where}.poses[{i}]") for i, p in enumerate(raw_poses)]
            if any(p is None for p in parsed):
                continue
            poses = [p for p in parsed if p is not None]
        if "cycle" not in spec:
            out[name] = Animation(name, float(fps), loop, interp, poses)
        else:
            cycle = spec["cycle"]
            if not isinstance(cycle, dict) or cycle.get("type") not in CYCLES:
                ctx.error("E008", f"cycle needs type: {'|'.join(CYCLES)} (see the reference for each one's options)", aline, f"{where}.cycle")
                continue
            named = [v for k, v in cycle.items() if k in ("legs", "arms", "parts", "part", "body", "head", "chest", "elbows")]
            flat = [x for v in named for x in (v if isinstance(v, list) else [v])]
            unknown = [x for x in flat if x not in ids]
            if unknown:
                ctx.error("E008", f"cycle names unknown part id(s) {', '.join(map(str, unknown))} (ids: {', '.join(sorted(ids))})", aline, f"{where}.cycle")
                continue
            out[name] = Animation(name, float(fps), loop, interp, poses, dict(cycle))
    return out


def _relined(src: Any, items: dict[Any, Any]) -> dict[Any, Any]:
    """`items` as a mapping that keeps `src`'s source lines (a LineMap when `src` is one)."""
    if not isinstance(src, LineMap):
        return dict(items)
    out = LineMap()
    out.update(items)
    out.line, out.key_lines, out.value_spans = src.line, dict(src.key_lines), dict(src.value_spans)
    return out


def _fold_unrevealed(data: dict[Any, Any]) -> dict[Any, Any]:
    """A built model's rig entries with `fold: true` and none of their `revealed` parts in the model (hair hidden by a
    helmet, on a head without one; no `revealed`: always): their parts take the parent's id, as if they had no id of
    their own, and the entry goes. Where some revealers are there, the missing ones are dropped. Templates are left as
    written."""
    rig = data.get("rig")
    raw_parts = data.get("parts")
    if data.get("template") is True or not isinstance(rig, dict) or not isinstance(raw_parts, list):
        return data
    folding = {k: v for k, v in rig.items() if isinstance(v, dict) and v.get("fold") is True}
    if not folding:
        return data
    present = {p.get(k) for p in raw_parts if isinstance(p, dict) for k in ("id", "mirror_id")}
    into: dict[Any, Any] = {}
    kept: dict[Any, Any] = {}
    for key, spec in folding.items():
        revealed = spec.get("revealed")
        names = [revealed] if isinstance(revealed, str) else [] if revealed is None else revealed
        parent = spec.get("parent")
        if not isinstance(names, list) or not isinstance(parent, str) or parent == key:
            continue  # _parse_rig reports it
        there = [r for r in names if r in present]
        if there:
            kept[key] = _relined(spec, {**spec, "revealed": there})
        else:
            into[key] = parent
    for key in into:  # a chain (a folded part's parent folded too) ends at the first id that stays
        seen = {key}
        while into[key] in into and into[key] not in seen:
            seen.add(into[key])
            into[key] = into[into[key]]
    if not into and not kept:
        return data

    def ref(v: Any) -> Any:
        if isinstance(v, str):
            return into.get(v, v)
        return [into.get(x, x) if isinstance(x, str) else x for x in v] if isinstance(v, list) else v

    def part(raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        changed = dict(raw)
        if raw.get("id") in into:
            changed["id"] = into[raw["id"]]
        if isinstance(raw.get("cut"), str | list):  # (cut: [hair, head] too, #209)
            changed["cut"] = ref(raw["cut"])
        if "fit" in raw:
            changed["fit"] = _relined(raw["fit"], {**raw["fit"], "to": ref(raw["fit"].get("to"))}) if isinstance(raw["fit"], dict) else ref(raw["fit"])
        for kind in HARDWARE:
            if isinstance(raw.get(kind), dict) and "fit" in raw[kind]:
                changed[kind] = _relined(raw[kind], {**raw[kind], "fit": ref(raw[kind]["fit"])})
        return _relined(raw, changed) if changed != raw else raw

    new_rig = {}
    for key, raw_spec in rig.items():
        if key in into:
            continue
        entry: Any = kept.get(key, raw_spec)
        if isinstance(entry, dict) and entry.get("parent") in into:
            entry = _relined(entry, {**entry, "parent": into[entry["parent"]]})
        new_rig[key] = entry
    out = {k: v for k, v in data.items() if k != "rig" or new_rig}
    if new_rig:
        out["rig"] = _relined(rig, new_rig)
    out["parts"] = [part(p) for p in raw_parts]
    return _relined(data, out)



def parse_model(data: Any, path: Path | None, palette: dict[str, str], materials: set[str], text: str = "") -> tuple[Model | None, list[Finding]]:
    ctx = _Ctx(path, palette, materials)
    if not isinstance(data, dict):
        ctx.error("E001", "a model file is a mapping (name, parts, ...)", None, None or "")
        return None, ctx.findings
    data = _fold_unrevealed(data)
    unknown = [k for k in data if k not in TOP_FIELDS]
    if unknown:
        ctx.error("E002", f"unknown field(s) {', '.join(map(str, unknown))}; allowed: {', '.join(sorted(TOP_FIELDS))}", _line(data, unknown[0]), str(unknown[0]))
    name = data.get("name")
    expected = path.name[: -len(MODEL_SUFFIX)] if path is not None and path.name.endswith(MODEL_SUFFIX) else None
    if not isinstance(name, str) or not NAME_RE.match(name):
        ctx.error("E003", "name must be lowercase letters, digits, _ or - (and match the file name)", _line(data, "name"), "name")
        name = expected or "model"
    elif expected is not None and name != expected:
        ctx.error("E003", f"name {name!r} must match the file name ({expected}{MODEL_SUFFIX})", _line(data, "name"), "name")
    model = Model(name=str(name), path=path, text=text)
    # after `extends`: what the model is made of, whatever its comments and layout
    model.shape_text = _as_text({k: v for k, v in data.items() if k not in NOT_SHAPE})
    model.motion_text = _as_text(data.get("animations"))
    template = data.get("template", False)
    if not isinstance(template, bool):
        ctx.error("E003", "template is true or false (true: a base other models extend; it isn't built itself)", _line(data, "template"), "template")
    else:
        model.template = template
    model.extends = data.get("extends") if isinstance(data.get("extends"), str) else None
    model.description = str(data.get("description", ""))
    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        ctx.error("E003", "tags is a list of words", _line(data, "tags"), "tags")
    else:
        model.tags = tuple(tags)
    status = data.get("status", "draft")
    if status not in STATUSES:
        ctx.error("E003", "status is draft or approved (approved = the owner looked at it)", _line(data, "status"), "status")
    else:
        model.status = str(status)
    sv = data.get("style_version")
    if sv is not None and (not isinstance(sv, int) or isinstance(sv, bool) or sv < 1):
        ctx.error("E003", "style_version is a whole number (the project's style_version when this was made)", _line(data, "style_version"), "style_version")
    else:
        model.style_version = sv
    cls = data.get("class", "prop")
    if not isinstance(cls, str) or not NAME_RE.match(cls):
        ctx.error("E003", "class is a size class from the style's budgets (character, prop, building, ...)", _line(data, "class"), "class")
    else:
        model.cls = cls
    for key in ("style", "palette"):
        v = data.get(key)
        if v is not None and (not isinstance(v, str) or not NAME_RE.match(v)):
            ctx.error("E003", f"{key} is a name ({key}s/<name>...)", _line(data, key), key)
        else:
            setattr(model, key, v)
    budget = data.get("budget")
    if budget is not None and (not isinstance(budget, int) or isinstance(budget, bool) or not 12 <= budget <= 500_000):
        ctx.error("E003", "budget is a triangle count (12-500000); it overrides the style's budget for the class", _line(data, "budget"), "budget")
    else:
        model.budget = budget
    resolution = data.get("resolution")
    if resolution is not None and (not isinstance(resolution, int | float) or isinstance(resolution, bool) or not 0.001 <= resolution <= 0.2):
        ctx.error("E003", "resolution is metres per mesh cell for this model (0.001-0.2), used as is: e.g. 0.004 for a 2.4 m hero; "
                  "overrides the style's", _line(data, "resolution"), "resolution")  # fmt: skip
    else:
        model.resolution = None if resolution is None else float(resolution)
    max_cells = data.get("max_cells")
    if max_cells is not None and (not isinstance(max_cells, int) or isinstance(max_cells, bool) or not 64 <= max_cells <= CELL_LIMIT):
        ctx.error("E003", f"max_cells is mesh grid cells per axis at most (64-{CELL_LIMIT}), e.g. 768; overrides the style's",
                  _line(data, "max_cells"), "max_cells")  # fmt: skip
    else:
        model.max_cells = max_cells
    normal_map = data.get("normal_map", 0)
    if normal_map not in (0, 256, 512, 1024, 2048, 4096):
        ctx.error("E003", "normal_map is the baked normal map's size in texels: 256, 512, 1024, 2048 or 4096 (0: none); detail then comes from "
                  "the shapes, not triangles (needs kiln-gen[bake])", _line(data, "normal_map"), "normal_map")  # fmt: skip
    else:
        model.normal_map = int(normal_map)
        model.normal_map_off = "normal_map" in data and normal_map == 0
    strength = data.get("normal_strength", 1.0)
    if not _num(strength) or not 0 <= float(strength) <= 4:
        ctx.error("E003", "normal_strength scales the baked normal map's tilt: 0 (flat) to 4, 1 as baked (0.5: softer grooves)",
                  _line(data, "normal_strength"), "normal_strength")  # fmt: skip
    else:
        model.normal_strength = float(strength)
        if "normal_strength" in data and not model.normal_map and "relief" not in data and not _fades(data.get("parts")):
            model.normal_strength_line = _line(data, "normal_strength") or 0  # no map yet: the style may still bring one (apply_style)
    if "shade" in data:
        shade, shade_error = parse_shade(data["shade"])
        if shade_error:
            ctx.error("E003", shade_error, _line(data, "shade"), "shade")
        model.shade = shade
    prefix = data.get("node_prefix")
    if prefix is not None:
        if isinstance(prefix, str) and PREFIX_RE.match(prefix):
            model.node_prefix = prefix
        else:
            ctx.error("E003", "node_prefix is up to 32 letters, digits, _ or - (e.g. Knight_): mesh nodes become Knight_<id>",
                      _line(data, "node_prefix"), "node_prefix")  # fmt: skip
    origin = data.get("origin")
    if origin is not None:
        if origin in ("base", "center", "ground"):
            model.origin = str(origin)
        elif isinstance(origin, list) and len(origin) == 3 and all(isinstance(v, int | float) and not isinstance(v, bool) for v in origin):
            model.origin = (float(origin[0]), float(origin[1]), float(origin[2]))
        else:
            ctx.error("E003", "origin is base (bottom centre of the model's box), center (its middle), ground ([0, lowest point, 0]: the built "
                      "mesh lifted onto y = 0) or a point [x, y, z]: the exported mesh's origin, e.g. center for debris that spins",
                      _line(data, "origin"), "origin")  # fmt: skip
        if "fit_to" in data:
            ctx.error("E003", "an attachment (fit_to) is exported in its bone's space: drop origin", _line(data, "origin"), "origin")
    if "effect" in data:
        model.effect = parse_effect(data["effect"], lambda message, where: ctx.error("E003", message, _line(data, "effect"), where))
    lod = data.get("lod", [])
    if not isinstance(lod, list) or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 12 for n in lod):
        ctx.error("E003", "lod is a list of smaller triangle budgets, e.g. [2000, 600]", _line(data, "lod"), "lod")
    else:
        model.lod = tuple(lod)
    lint = data.get("lint", {})
    if not isinstance(lint, dict) or any(k != "disable" for k in lint) or not all(isinstance(r, str) for r in lint.get("disable", [])):
        ctx.error("E003", "lint is { disable: [W101, ...] }", _line(data, "lint"), "lint")
    else:
        model.lint_disable = tuple(lint.get("disable", []))

    if "terrain" in data:  # a heightfield, not parts: only the model's identity, style and palette go with it
        others = [str(k) for k in data if k not in TERRAIN_TOP]
        if others:
            ctx.error("E003", f"a terrain has no {', '.join(others)}: only {', '.join(sorted(TERRAIN_TOP))}", _line(data, others[0]), others[0])
        if "class" not in data:
            model.cls = "terrain"
        model.terrain = parse_terrain(data["terrain"], _line(data, "terrain"), lambda message, line, where: ctx.error("E003", message, line, where),
                                      lambda raw, line, where: _color(ctx, raw, line, where))  # fmt: skip
        if model.terrain is None and not any(f.severity == "error" for f in ctx.findings):
            ctx.error("E003", "terrain: see the problems above", _line(data, "terrain"), "terrain")
        return model, ctx.findings
    if "scatter" in data:  # other models placed over a surface, not parts: only identity, style and palette go with it
        others = [str(k) for k in data if k not in SCATTER_TOP]
        if others:
            ctx.error("E003", f"a scatter has no {', '.join(others)}: only {', '.join(sorted(SCATTER_TOP))}", _line(data, others[0]), others[0])
        if "class" not in data:
            model.cls = "scatter"
        model.scatter = parse_scatter(data["scatter"], _line(data, "scatter"), lambda message, line, where: ctx.error("E003", message, line, where),
                                      lambda raw, line, where: _color(ctx, raw, line, where))  # fmt: skip
        if model.scatter is None and not any(f.severity == "error" for f in ctx.findings):
            ctx.error("E003", "scatter: see the problems above", _line(data, "scatter"), "scatter")
        return model, ctx.findings
    if "source" in data:
        if "parts" in data:
            ctx.error("E003", "a model has parts (made in KILN) or source (an imported mesh), not both", _line(data, "source"), "source")
        model.source = _parse_source(ctx, data["source"], data.get("process"), _line(data, "source"))
        if model.normal_map:
            ctx.error("E003", "normal_map bakes from a KILN model's shapes: an imported mesh (source) has none", _line(data, "normal_map"), "normal_map")
    else:
        raw_parts = data.get("parts")
        if not isinstance(raw_parts, list) or not raw_parts:
            ctx.error("E003", "parts must be a non-empty list, e.g. - sphere: { at: [0, 0.5, 0], radius: 0.5 }", _line(data, "parts"), "parts")
        else:
            named = data.get("textures", {})  # model-level textures used by name (#320)
            if not isinstance(named, dict) or not all(isinstance(v, dict) for v in named.values()):
                ctx.error("E003", "textures maps names to textures, e.g. textures: { print: { image: textures/print.png, project: box, texel: 0.004 } }; "
                          "a part then writes texture: print", _line(data, "textures"), "textures")  # fmt: skip
                named = {}
            for i, raw in enumerate(raw_parts):
                if isinstance(raw, dict) and isinstance(raw.get("texture"), str):
                    if raw["texture"] in named:
                        raw["texture"] = dict(named[raw["texture"]])
                    else:
                        ctx.error("E003", f"texture {raw['texture']!r} isn't one of the model's textures: ({', '.join(named) or 'none'}); a texture "
                                  "is { image, project, size | texel } or a name from textures:", _line(raw) or _line(data, "parts"), f"parts[{i}].texture")  # fmt: skip
                        raw.pop("texture")
            placed: set[int] = set()  # parts placed with on: already
            for i, raw in enumerate(raw_parts):
                pline = _line(raw) or _line(data, "parts")
                kinds = [k for k in raw if k in HARDWARE] if isinstance(raw, dict) else []
                if not kinds:
                    model.parts.extend(_parse_part(ctx, raw, i, pline))
                    continue
                if len(kinds) > 1 or any(k in SHAPES for k in raw):
                    ctx.error("E003", f"each part needs exactly one shape: {', '.join(SHAPES)}, or one hardware part: {', '.join(HARDWARE)}", pline, f"parts[{i}]")
                    continue
                if "on" in raw or True in raw:
                    ctx.error("E003", f"on places shapes, not hardware: give the {kinds[0]} its at (or put it on a shape placed with on)",
                              pline, f"parts[{i}].on")  # fmt: skip
                    continue
                _place_on(ctx, model, placed)  # hardware reads the parts before it: place them first
                earlier = [(p.id, p.geometry) for p in model.parts if p.geometry.op == "add"]
                subs, problem = expand(kinds[0], raw[kinds[0]], dict(raw), earlier)
                if problem is not None:
                    ctx.error("E003", problem, pline, f"parts[{i}].{kinds[0]}")
                    continue
                for sub in subs:
                    model.parts.extend(_parse_part(ctx, sub, i, pline))
            if model.parts and not any(p.geometry.op == "add" for p in model.parts):
                ctx.error("E009", "the model has no adding parts (only cut/intersect)", _line(data, "parts"), "parts")
            if "fit_to" in data:
                model.fit_to = _parse_fit_to(ctx, data["fit_to"], _line(data, "fit_to"))
            for k, part in enumerate(model.parts):
                if part.blend_to is not None:
                    names = set(part.blend_to)
                    if part.twin_of is not None:  # a mirrored copy melts into the mirrored parts (the right side's, not the left's)
                        names = {next((q.id for q in model.parts if q.twin_of == n), n) for n in names}
                    before = {q.id for q in model.parts[:k] if q.geometry.op == "add" and not q.detail}  # (detail parts aren't in the mesh)
                    missing = sorted(n for n in names if n not in before)
                    if missing:
                        ctx.error("E003", f"blend_to {', '.join(missing)}: no earlier part has that id (blend into parts listed before this one)",
                                  part.line, f"{part.where}.blend_to")  # fmt: skip
                    part.geometry.blend_to = frozenset(j for j, q in enumerate(model.parts[:k]) if q.id in names and q.geometry.op == "add"
                                                       and not q.detail)  # fmt: skip
            for part in model.parts:
                if part.cut_only is not None:
                    known = {q.id for q in model.parts if q.geometry.op == "add"}
                    missing = [n for n in part.cut_only if n not in known]
                    if missing:
                        ctx.error("E003", f"cut names {', '.join(missing)}: no part has that id (ids: {', '.join(sorted(known))})", part.line, f"{part.where}.cut")
                    part.geometry.cut_only = frozenset(i for i, q in enumerate(model.parts) if q.id in part.cut_only and q.geometry.op == "add")
            for part in model.parts:
                if part.fit is None:
                    continue
                if part.fit[0] == ("target",):
                    if model.fit_to is None:
                        ctx.error("E003", "fit: target wraps the character named by fit_to: { file, bone } (add that first)", part.line, f"{part.where}.fit")
                        continue
                    from kiln.fitting import MeshDistance, read_surface

                    surface = MeshDistance.build(*read_surface(model.fit_to[0], model.fit_to[2]), part.geometry.bounds())
                    part.geometry.fit = ((surface,), part.fit[1])
                    continue
                wanted = set(part.fit[0])
                if part.twin_of is not None:  # a mirrored copy wraps the mirrored parts (the right arm, not the left)
                    wanted = {next((q.id for q in model.parts if q.twin_of == to), to) for to in wanted}
                k = next(j for j, q in enumerate(model.parts) if q is part)
                # the parts with those ids, itself and later shells aside: an earlier fitted shell may be wrapped in turn
                # (a shirt over trousers, #193), and a part may wrap parts of its own id (a sleeve on the arm's bone)
                targets = tuple(q.geometry for j, q in enumerate(model.parts) if q.id in wanted and q is not part and q.geometry.op == "add"
                                and (q.fit is None or j < k) and not (q.id == part.id and q.fit is not None) and not q.detail)  # fmt: skip
                if not targets:
                    if not model.template:  # a template (a helmet) may fit parts another template brings (a head)
                        ctx.error("E003", f"fit: no other part has id {', '.join(part.fit[0])} (it wraps the parts with those ids)", part.line,
                                  f"{part.where}.fit")  # fmt: skip
                    continue
                part.geometry.fit = (targets, part.fit[1])
            _place_on(ctx, model, placed)  # after fit: a part may sit on a fitted shell
            if any(p.detail for p in model.parts):
                _split_detail(ctx, model)
    _parse_relief(ctx, data, model)
    _soft_colours(ctx, data, model)
    ids = set(model.ids) if model.parts else {ROOT_ID}
    model.rig = _mirror_rig(_parse_rig(ctx, data.get("rig"), ids, _line(data, "rig"), model.template), model.parts)
    if "instances" in data:  # (after the parts: `id` names one)
        model.instances = _parse_instances(ctx, data["instances"], _line(data, "instances"), model)
    if "transforms" in data:  # (last: the parts as placed, fitted and rigged)
        _apply_transforms(ctx, data["transforms"], _line(data, "transforms"), model)
    skeleton = data.get("skeleton")
    if isinstance(skeleton, dict):
        model.joint_map = _parse_skeleton_map(ctx, skeleton, model, _line(data, "skeleton"))
    elif skeleton is not None:
        missing = [j for j in REQUIRED if j not in ids]
        if skeleton != "humanoid":
            ctx.error("E007", "skeleton is humanoid (parts named after the standard joints: hips, spine, chest, head, upperarm_l, ...) "
                      "or { map: { <bone id>: <clip joint>, ... }, root_motion: <clip joint> } (clips on any other skeleton)",
                      _line(data, "skeleton"), "skeleton")  # fmt: skip
        elif missing and not model.template:
            ctx.error("E007", f"a humanoid needs parts with ids {', '.join(missing)} (standard joints; mirror_id makes the _r side)",
                      _line(data, "skeleton"), "skeleton")  # fmt: skip
        else:
            model.skeleton = "humanoid"
    skin = data.get("skin", "soft" if model.skeleton else "rigid" if model.rig else "none")
    if skin not in SKINS:
        ctx.error("E007", "skin is none (static), rigid (each part moves as one piece) or soft (blended joints bend)", _line(data, "skin"), "skin")
    else:
        model.skin = str(skin)
    union = data.get("union")
    if union is not None:
        if union not in UNIONS:
            ctx.error("E007", "union is whole (all parts one surface) or per_bone (each bone's parts their own closed surface)", _line(data, "union"), "union")
        elif union == "per_bone" and model.skin != "rigid":
            ctx.error("E007", "union: per_bone needs skin: rigid (a soft skin bends where parts blend, so it stays one surface)", _line(data, "union"), "union")
        else:
            model.union = str(union)
    model.animations = _parse_animations(ctx, data.get("animations"), ids, _line(data, "animations"), model.skeleton is not None, model.joint_map)
    if model.animations and model.skin == "none":
        ctx.error("E008", "animations move parts: give the model a rig (pivots and parents) or skin: rigid", _line(data, "animations"), "animations")
    library = data.get("animation_library")
    if library is not None:
        if not isinstance(library, str) or not NAME_RE.match(library) or library == model.name:
            ctx.error("E008", "animation_library names another model (a clip carrier with animations_only: true)", _line(data, "animation_library"),
                      "animation_library")  # fmt: skip
        elif model.animations:
            ctx.error("E008", "a model plays its animation_library's clips: drop its own animations (or the library)", _line(data, "animations"),
                      "animations")  # fmt: skip
        elif model.skin == "none":
            ctx.error("E008", "animation_library: the model needs a rig (or skin: rigid) to play clips", _line(data, "animation_library"),
                      "animation_library")  # fmt: skip
        else:
            model.animation_library = library
    only = data.get("animations_only")
    if only is not None:
        if not isinstance(only, bool):
            ctx.error("E003", "animations_only is true or false", _line(data, "animations_only"), "animations_only")
        elif only and (not model.animations or library is not None):
            ctx.error("E008", "animations_only: a clip carrier for other models' animation_library: it needs its own animations",
                      _line(data, "animations_only"), "animations_only")  # fmt: skip
        else:
            model.animations_only = only
    variants = data.get("variants", {})
    if not isinstance(variants, dict):
        ctx.error("E003", "variants maps names to { swap: { colour: colour } }", _line(data, "variants"), "variants")
    else:
        for vname, spec in variants.items():
            vline = _line(variants, vname)
            if not isinstance(vname, str) or not NAME_RE.match(vname) or not isinstance(spec, dict) or set(spec) != {"swap"} or not isinstance(spec["swap"], dict):
                ctx.error("E003", "a variant is { swap: { red: green, ... } } (palette colours)", vline, f"variants.{vname}")
                continue
            swap = {}
            from_ramps: dict[str, str] = {}  # whole ramps first: a colour entry wins over them, wherever it is written (#205)
            for a, b in spec["swap"].items():
                if isinstance(a, str) and a not in ctx.palette and a in ctx.ramps:  # a whole ramp: shade for shade
                    if not isinstance(b, str) or b in ctx.palette or b not in ctx.ramps or len(ctx.ramps[b]) != len(ctx.ramps[a]):
                        ctx.error("E003", f"{a} is a palette ramp ({len(ctx.ramps[a])} colours): swap it for another ramp of the same "
                                  f"length (ramps: {', '.join(f'{n} ({len(r)})' for n, r in ctx.ramps.items())})", vline, f"variants.{vname}.swap")  # fmt: skip
                        continue
                    shared = {hx for n, r in ctx.ramps.items() if n != a for hx in r}  # (an outline black in two ramps: name it to swap it)
                    from_ramps.update({x: y for x, y in zip(ctx.ramps[a], ctx.ramps[b], strict=True) if x not in shared})
                    continue
                ca = _color(ctx, a, vline, f"variants.{vname}.swap")
                cb = _color(ctx, b, vline, f"variants.{vname}.swap")
                if ca and cb:
                    swap[ca[0]] = cb[0]
            swap = {**from_ramps, **swap}
            for part in model.parts:  # gradient bands: the mix of the swapped ends
                for pat in part.patterns:
                    if pat.mix is not None and pat.color not in swap:
                        a, b, t = pat.mix
                        mixed = _mix(swap.get(a, a), swap.get(b, b), t)
                        if mixed != pat.color:
                            swap[pat.color] = mixed
            model.variants[str(vname)] = swap
    return model, ctx.findings


def _parse_instances(ctx: _Ctx, raw: Any, line: int | None, model: Model) -> tuple[Instance, ...]:
    """instances: [{ model: screw, at: [x, y, z], rotate: [x, y, z], scale: 1, id: tray }, ...] (#171)."""
    usage = "instances is a list of { model: <name>, at: [x, y, z], rotate: [x, y, z] degrees, scale: s, id: <part it moves with> }"
    if not isinstance(raw, list):
        ctx.error("E003", usage, line, "instances")
        return ()
    out = []
    ids = set(model.ids)
    for k, item in enumerate(raw):
        where = f"instances[{k}]"
        iline = _line(item) or line
        if not isinstance(item, dict) or any(key not in ("model", "at", "rotate", "scale", "id") for key in item) \
                or not isinstance(item.get("model"), str) or not NAME_RE.match(item["model"]):  # fmt: skip
            ctx.error("E003", usage, iline, where)
            continue
        if item["model"] == model.name:
            ctx.error("E003", "a model can't place itself", iline, f"{where}.model")
            continue
        at, rotate = _vec(item.get("at", [0, 0, 0])), _vec(item.get("rotate", [0, 0, 0]))
        scale = item.get("scale", 1.0)
        bone = item.get("id", ROOT_ID)
        if at is None or rotate is None or not _num(scale) or float(scale) <= 0:
            ctx.error("E003", "at and rotate are [x, y, z]; scale is a number > 0", iline, where)
            continue
        if bone not in ids:
            ctx.error("E003", f"id {bone!r}: the part it moves with (ids: {', '.join(sorted(ids))})", iline, f"{where}.id")
            continue
        out.append(Instance(item["model"], (at[0], at[1], at[2]), (rotate[0], rotate[1], rotate[2]), float(scale), str(bone), iline))
    return tuple(out)


def _apply_transforms(ctx: _Ctx, raw: Any, line: int | None, model: Model) -> None:
    """transforms: [{ ids: [chest, head, arm_l, arm_r], rotate: [x, y, z], pivot: [x, y, z], move: [x, y, z] }, ...]:
    each turns the parts with these ids about `pivot` (degrees, as a part's rotate), then moves them, in order: a
    hunched rest posture without retyping every part (#305). Their rig pivots and sockets go with them."""
    usage = "transforms is a list of { ids: [part ids], rotate: [x, y, z] degrees, pivot: [x, y, z], move: [x, y, z] }"
    if not isinstance(raw, list):
        ctx.error("E003", usage, line, "transforms")
        return
    known = set(model.ids)
    for k, item in enumerate(raw):
        where = f"transforms[{k}]"
        tline = _line(item) or line
        ids = item.get("ids") if isinstance(item, dict) else None
        ids = [ids] if isinstance(ids, str) else ids
        if not isinstance(item, dict) or any(key not in ("ids", "rotate", "pivot", "move") for key in item) \
                or not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):  # fmt: skip
            ctx.error("E003", usage, tline, where)
            continue
        missing = [i for i in ids if i not in known]
        if missing:
            ctx.error("E003", f"transforms: no part has id {', '.join(missing)} (ids: {', '.join(sorted(known))})", tline, f"{where}.ids")
            continue
        rot, piv, mov = (_vec(item.get(key, [0, 0, 0])) for key in ("rotate", "pivot", "move"))
        if rot is None or piv is None or mov is None:
            ctx.error("E003", "rotate, pivot and move are [x, y, z]", tline, where)
            continue
        r = rotation_matrix((rot[0], rot[1], rot[2]))
        pivot, move = np.asarray(piv, float), np.asarray(mov, float)
        # a mirrored part is drawn on both sides of x = 0: it can only follow a transform that keeps x = 0 a mirror
        keeps_mirror = abs(r[0, 1]) < 1e-9 and abs(r[0, 2]) < 1e-9 and abs(r[1, 0]) < 1e-9 and abs(r[2, 0]) < 1e-9 \
            and abs(pivot[0]) < 1e-9 and abs(move[0]) < 1e-9  # fmt: skip
        chosen = [part for part in model.parts if part.id in ids]
        if not keeps_mirror and any(0 in part.geometry.mirror for part in chosen):
            ctx.error("E003", "transforms: a part with mirror: x can only turn about x and move in y and z (it is drawn on both sides "
                      "of x = 0); give each side its own id (mirror_id) to pose them apart", tline, where)  # fmt: skip
            continue

        def moved(x: Any, r: Any = r, pivot: Any = pivot, move: Any = move) -> Any:
            return r @ (np.asarray(x, float) - pivot) + pivot + move

        for part in chosen:
            g = part.geometry
            if len(g.copies) == 1 and g.copies[0] is IDENTITY:
                g.at = moved(g.at)
                g.rotation = r if g.rotation is None else r @ g.rotation
            else:  # an array: each copy then the transform, about the copy's own pivot
                g.copies = tuple(Copy(r @ c.rotation, c.pivot, r @ (c.pivot + c.offset - pivot) + pivot + move - c.pivot) for c in g.copies)
        for pid in ids:
            entry = model.rig.get(pid)
            if entry is not None:
                model.rig[pid] = replace(entry, pivot=None if entry.pivot is None else tuple(moved(entry.pivot).tolist()),
                                         sockets=tuple((n, tuple(moved(q).tolist())) for n, q in entry.sockets))  # fmt: skip


def _parse_fit_to(ctx: _Ctx, raw: Any, line: int | None) -> tuple[Path, str, tuple[str, ...]] | None:
    """fit_to: { file: imports/Knight.glb, bone: head, meshes: [Knight_Head] }: the model is an attachment made in that
    character's space (parts can `fit: target`), exported in the bone's space."""
    if not isinstance(raw, dict) or not isinstance(raw.get("file"), str) or not isinstance(raw.get("bone"), str) \
            or any(k not in ("file", "bone", "meshes") for k in raw) or not isinstance(raw.get("meshes", []), list):
        ctx.error("E010", "fit_to is { file: imports/Knight.glb, bone: head, meshes: [Knight_Head] } (meshes: which to fit around; default all)",
                  line, "fit_to")  # fmt: skip
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    file = (base / raw["file"]).resolve()
    if not file.is_file():
        ctx.error("E010", f"fit_to file {raw['file']} not found (paths are relative to the project)", line, "fit_to.file")
        return None
    glb = _as_glb(ctx, file, "E010", line, "fit_to.file")
    if glb is None:
        return None
    file = glb
    from kiln.fitting import bones, meshes

    known_bones, known_meshes = bones(file), meshes(file)
    if raw["bone"] not in known_bones:
        ctx.error("E010", f"{raw['file']} has no bone {raw['bone']!r} (bones: {', '.join(known_bones)})", line, "fit_to.bone")
        return None
    wanted = tuple(str(m) for m in raw.get("meshes", []))
    unknown = [m for m in wanted if m not in known_meshes]
    if unknown:
        ctx.error("E010", f"{raw['file']} has no mesh {', '.join(unknown)} (meshes: {', '.join(known_meshes)})", line, "fit_to.meshes")
        return None
    return file, str(raw["bone"]), wanted


def _parse_source(ctx: _Ctx, raw: Any, process: Any, line: int | None) -> Source | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("file"), str):
        ctx.error("E010", "source is { file: imports/tree.glb, licence: CC0-1.0, author: ..., url: ... }", line, "source")
        return None
    bad = [k for k in raw if k not in ("file", "licence", "author", "url")]
    if bad:
        ctx.error("E002", f"unknown source field(s) {', '.join(map(str, bad))}; allowed: file, licence, author, url", line, "source")
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    file = (base / raw["file"]).resolve()
    if not file.is_file() or file.suffix.lower() not in (".glb", ".gltf", ".fbx", ".blend", ".obj"):
        ctx.error("E010", f"source file {raw['file']} not found or not .glb/.gltf (.fbx/.blend/.obj with Blender 4.x; paths are relative to "
                  "the project)", line, "source.file")  # fmt: skip
        return None
    licence = raw.get("licence")
    if not isinstance(licence, str) or not licence:
        ctx.error("E010", "source needs licence (an SPDX id: CC0-1.0, CC-BY-4.0, ...) so credits and checks work", line, "source.licence")
        return None
    glb = _as_glb(ctx, file, "E010", line, "source.file")
    if glb is None:
        return None
    src = Source(glb, licence, str(raw.get("author", "")), str(raw.get("url", "")), original=None if glb == file else file)
    if process is not None:
        if not isinstance(process, dict) or any(k not in ("height", "scale", "recolor", "rotate") for k in process):
            ctx.error("E003", "process is { height: metres | scale: factor, recolor: auto|keep, rotate: [x, y, z] }", line, "process")
            return None
        if "height" in process:
            if not _num(process["height"]) or process["height"] <= 0:
                ctx.error("E003", "process height is metres (> 0)", line, "process.height")
                return None
            src.height = float(process["height"])
        if "scale" in process:
            if not _num(process["scale"]) or process["scale"] <= 0:
                ctx.error("E003", "process scale is a factor (> 0)", line, "process.scale")
                return None
            src.scale = float(process["scale"])
        if process.get("recolor", "auto") not in ("auto", "keep"):
            ctx.error("E003", "recolor is auto (snap to the palette) or keep", line, "process.recolor")
            return None
        src.recolor = str(process.get("recolor", "auto"))
        if "rotate" in process:
            rot = _vec(process["rotate"])
            if rot is None:
                ctx.error("E003", "process rotate is [x, y, z] degrees", line, "process.rotate")
                return None
            src.rotate = (rot[0], rot[1], rot[2])
    return src


def _read(path: Path) -> tuple[Any, str, list[Finding]]:
    try:
        text = path.read_text(encoding="utf-8")
        return parse_yaml(text), text, []
    except (OSError, UnicodeDecodeError) as exc:
        return None, "", [Finding("E001", f"cannot read file: {exc}", path)]
    except YamlError as exc:
        return None, "", [Finding("E001", exc.message, path, exc.line)]


def library_dir() -> Path:
    """KILN's own templates (heads, bodies, helmets, armour) and their palette, found when a project has no model
    of that name."""
    from importlib.resources import files

    return Path(str(files("kiln").joinpath("library")))


def base_path(models: Path, name: str) -> Path:
    own = models / f"{name}{MODEL_SUFFIX}"
    if own.is_file():
        return own
    lib = library_dir() / f"{name}{MODEL_SUFFIX}"
    return lib if lib.is_file() else own


def _combine(base: dict[str, Any], data: dict[str, Any], remove: list[str]) -> dict[str, Any]:
    """`data` on top of `base`: base parts first (minus `remove`), rig/animations/variants merged by name (data's
    win), other fields inherited unless set, except identity."""
    merged: dict[str, Any] = {k: v for k, v in base.items() if k not in OWN_FIELDS}
    base_parts: list[Any] = base["parts"] if isinstance(base.get("parts"), list) else []
    kept = [p for p in base_parts if not (isinstance(p, dict) and (p.get("id") in remove or p.get("mirror_id") in remove))]
    gone = set(remove) | {p.get("mirror_id") for p in base_parts if isinstance(p, dict) and p.get("id") in remove}
    for key, value in data.items():
        if key in ("rig", "animations", "variants") and isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        elif key == "parts" and isinstance(value, list):
            merged[key] = kept + value
        else:
            merged[key] = value
    if "parts" not in data and base_parts:
        merged["parts"] = kept
    if isinstance(merged.get("rig"), dict):
        merged["rig"] = {k: v for k, v in merged["rig"].items() if k not in gone}
    return merged


def resolve_extends(path: Path, data: Any, text: str, seen: tuple[Path, ...] = ()) -> tuple[Any, str, list[Finding]]:
    """A model with `extends: <base>` (or a list of bases, combined in order: a body, a head, a helmet) merged onto
    its bases (`template: true` models in the same folder, or KILN's library): the bases' parts come first, minus
    `remove: [ids]`, then the model's own; rig entries, animations and variants merge by name (the model's win);
    every other field is inherited unless the model sets it, except its own identity (name, description, tags,
    status, style_version, template). Returns (data, text of the whole family)."""
    raw = data.get("extends") if isinstance(data, dict) else None
    names = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) and raw and all(isinstance(n, str) for n in raw) else None
    if names is None:
        if isinstance(data, dict) and "extends" in data:
            return data, text, [Finding("E012", "extends is the name of a template model (models/<name>.kiln.yaml or KILN's library), or a list of them",
                                        path, _line(data, "extends"), "extends")]  # fmt: skip
        return data, text, []
    line = _line(data, "extends")
    combined: dict[str, Any] | None = None
    texts = []
    for name in names:
        bpath = base_path(path.parent, name)
        if bpath.resolve() in seen or bpath.resolve() == path.resolve():
            return data, text, [Finding("E012", f"extends forms a loop: {' -> '.join(p.stem for p in (*seen, path))} -> {bpath.name}", path, line, "extends")]
        if not bpath.is_file():
            return data, text, [Finding("E012", f"extends: no model {name!r} ({bpath.name}) in {path.parent.name}/ or KILN's library (`kiln library`)",
                                        path, line, "extends")]  # fmt: skip
        base, base_text, findings = _read(bpath)
        if findings:
            return data, text, [Finding(f.rule, f"in the base {bpath.name}: {f.message}", path, line, "extends") for f in findings]
        base, base_text, findings = resolve_extends(bpath, base, base_text, (*seen, path.resolve()))
        if findings:
            return data, text, [Finding(f.rule, f"in the base {bpath.name}: {f.message}", path, line, "extends") for f in findings]
        if not isinstance(base, dict) or base.get("template") is not True:
            return data, text, [Finding("E012", f"{bpath.name} isn't a template: add template: true to it (templates aren't built on their own)",
                                        path, line, "extends")]  # fmt: skip
        combined = base if combined is None else _combine(combined, base, [])
        texts.append(base_text)
    assert combined is not None
    remove = data.get("remove", [])
    if not isinstance(remove, list) or not all(isinstance(r, str) for r in remove):
        return data, text, [Finding("E012", "remove is a list of the base's part ids to leave out", path, _line(data, "remove"), "remove")]
    found = {p.get(k) for p in (combined.get("parts") or []) if isinstance(p, dict) for k in ("id", "mirror_id")}
    findings = []
    missing = [r for r in remove if r not in found]
    if missing:
        findings.append(Finding("E012", f"remove: the base has no part id {', '.join(missing)}", path, _line(data, "remove"), "remove"))
    return _combine(combined, data, remove), "\n---\n".join([*texts, text]), findings


def load_model(path: Path, palette: dict[str, str], materials: set[str]) -> tuple[Model | None, list[Finding]]:
    data, text, findings = _read(path)
    if findings:
        return None, findings
    own = data
    data, text, findings = resolve_extends(path, data, text)
    if findings:
        return None, findings
    model, more = parse_model(data, path, palette, materials, text)
    if model is not None and isinstance(own, dict):
        model.extends = own.get("extends") if isinstance(own.get("extends"), str) else None
    return model, more


__all__ = ["Animation", "Decal", "Model", "Part", "PartPose", "Pattern", "RigEntry", "Source", "load_model", "load_yaml", "parse_model"]
