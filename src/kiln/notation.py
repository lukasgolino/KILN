"""`models/<name>.kiln.yaml`: parse and validate a model (parts, paint, rig, animations, variants).

Every problem becomes a Finding with a rule id, the file, the line and a `where` path, and all of them are
collected (not just the first), as in PAGAN.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from kiln.hardware import HARDWARE, expand
from kiln.retarget import REQUIRED
from kiln.sdf import IDENTITY, SHAPES, Copy, Geometry, Noise, axis_rotation, rotation_matrix, smooth_profile
from kiln.uv import AXES as UV_AXES
from kiln.uv import PROJECTIONS, UVSpec
from kiln.vendor.findings import Finding
from kiln.vendor.yamlio import LineMap, YamlError, load_yaml, parse_yaml

MODEL_SUFFIX = ".kiln.yaml"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
ROOT_ID = "root"
AXES = {"x": 0, "y": 1, "z": 2}
PATTERNS = ("stripes", "checker", "dots", "band")
STATUSES = ("draft", "approved")
SKINS = ("none", "rigid", "soft")
CYCLES = ("walk", "waddle", "hop", "bob", "spin", "swing", "breathe", "wave", "chain")
INTERPOLATIONS = ("linear", "step")

PART_FIELDS = {"id", "color", "material", "blend", "cut", "intersect", "mirror", "mirror_id", "array", "at", "rotate",
               "shell", "twist", "noise", "pattern", "decal", "loose", "hard", "bevel", "chamfer", "segments", "fit", "keep", "uv"}  # fmt: skip
BEVEL_SHAPES = ("box", "wedge", "cylinder", "cone", "extrude")
OPEN_SIDES = ("x", "-x", "y", "-y", "z", "-z", "+x", "+y", "+z")
TOP_FIELDS = {"name", "description", "tags", "status", "style_version", "class", "style", "palette", "budget", "parts", "rig",
              "skin", "animations", "variants", "lod", "lint", "source", "process", "template", "extends", "remove", "skeleton", "fit_to", "origin"}  # fmt: skip
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


@dataclass(frozen=True)
class Decal:
    image: Path
    axis: str  # x, -x, y, -y, z, -z: the direction the decal faces (it is projected along it)
    at: tuple[float, float, float]
    size: tuple[float, float]  # width, height in metres on the surface


@dataclass
class Part:
    index: int
    id: str
    geometry: Geometry
    color: str  # hex
    color_name: str
    material: str
    pattern: Pattern | None = None
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
    cut_only: str | None = None  # a cut that only cuts the parts with this id
    keep: bool | None = None  # survives every reduction (LODs) at full detail; None: small crisp parts do
    uv: UVSpec | None = None  # texture coordinates projected from its shape (kiln.uv)


@dataclass(frozen=True)
class RigEntry:
    pivot: tuple[float, float, float] | None  # None = the part's own centre at its lowest point
    parent: str | None
    meta: tuple[tuple[str, Any], ...] = ()
    separate: bool = False  # soft skins: keep this part a rigid mesh of its own (detachable helmet)
    sockets: tuple[tuple[str, tuple[float, float, float]], ...] = ()  # named points (model space, rest pose)
    under: tuple[str, str, str, float] | None = None  # separate parts: (hex, colour name, material, gap) painted on what it covers


@dataclass(frozen=True)
class PartPose:
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0)  # degrees, about the part's pivot
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass
class Animation:
    name: str
    fps: float
    loop: bool
    interpolation: str
    poses: list[dict[str, PartPose]]  # one dict per frame: part id -> pose (missing = rest)
    cycle: dict[str, Any] | None = None  # expanded into poses once the rig is known
    source: tuple[Path, str, float] | None = None  # (glb, clip, speed): retargeted from a clip library


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
    parts: list[Part] = field(default_factory=list)
    rig: dict[str, RigEntry] = field(default_factory=dict)
    skin: str = "none"
    animations: dict[str, Animation] = field(default_factory=dict)
    variants: dict[str, dict[str, str]] = field(default_factory=dict)  # name -> {hex: hex}
    lod: tuple[int, ...] = ()
    lint_disable: tuple[str, ...] = ()
    source: Source | None = None
    text: str = ""
    template: bool = False  # a base for `extends` (not built on its own)
    extends: str | None = None
    skeleton: str | None = None  # humanoid: standard joint names, clip retargeting
    fit_to: tuple[Path, str, tuple[str, ...]] | None = None  # (glb, bone, meshes): an attachment made around a CC0 character
    origin: str | tuple[float, float, float] | None = None  # base | center | a model-space point: the exported files' origin

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
        if bad or axis not in AXES or center is None or not _num(angle):
            ctx.error("E003", "a ring array is { count, around: x|y|z, center: [x, y, z], angle: 360 }", line, where)
            return None
        unit = np.zeros(3)
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
        if key in ("at", "rotate"):
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

    op = "add"
    cut_only = None
    for flag in ("cut", "intersect"):
        if flag in raw:
            if flag == "cut" and isinstance(raw[flag], str) and NAME_RE.match(raw[flag]):
                cut_only = raw[flag]  # cuts only the parts with this id (a helmet's face opening, not the face)
                op = flag if op == "add" else "conflict"
            elif not isinstance(raw[flag], bool):
                ctx.error("E003", f"{flag} must be true or false" + (" (cut may also name the part id it cuts)" if flag == "cut" else ""), line, f"{where}.{flag}")
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
    noise = None
    if "noise" in raw:
        n = raw["noise"]
        if not isinstance(n, dict) or not _num(n.get("amount")) or not _num(n.get("scale", 0.2)) or n.get("scale", 0.2) <= 0 \
                or any(k not in ("amount", "scale", "seed") for k in n) or not isinstance(n.get("seed", 0), int):
            ctx.error("E003", "noise is { amount: metres (e.g. 0.01), scale: metres per bump (e.g. 0.2), seed: int }", line, f"{where}.noise")
            ok = False
        else:
            noise = Noise(float(n["amount"]), float(n.get("scale", 0.2)), int(n.get("seed", index)))
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
    pattern = decal = None
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
        if "pattern" in raw:
            pattern = _parse_pattern(ctx, raw["pattern"], line, f"{where}.pattern")
            ok = ok and pattern is not None
        if "decal" in raw:
            decal = _parse_decal(ctx, raw["decal"], line, f"{where}.decal")
            ok = ok and decal is not None
    else:
        for paint in ("color", "material", "pattern", "decal", "id"):
            if paint in raw:
                ctx.error("E003", f"a {op} part removes material: it has no {paint}", line, f"{where}.{paint}")
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
    if ok and (hard is True or (hard is None and asks_hard)) and (twist or noise is not None):
        ctx.error("E003", "a hard part (sides, bevel, chamfer, blend: none or hard: true) can't twist or have noise: those need the smooth field",
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
    if not ok:
        return []
    open_axis = None
    if open_side is not None:
        open_axis = (AXES[open_side[-1]], -1.0 if open_side.startswith("-") else 1.0)
    geom = Geometry(kind, params, np.array(at), rotation, mirror if mirror_id is None else (), copies or (IDENTITY,),
                    op, float(blend), float(shell), float(twist), noise, str(shell_side), open_axis)  # fmt: skip
    hard_fields = {"hard": hard, "crisp": crisp, "bevel": float(bevel or chamfer), "segments": 1 if chamfer else int(segments), "fit": fit,
                   "keep": keep, "cut_only": cut_only, "uv": uv}  # fmt: skip
    parts = [Part(index, str(part_id), geom, color[0], color[1], material, pattern, decal, line, where, loose=bool(loose), **hard_fields)]
    if mirror_id is not None:
        mirrored = _reflect(geom, mirror[0])
        twin_decal = decal
        if decal is not None:
            at_m = list(decal.at)
            at_m[mirror[0]] = -at_m[mirror[0]]
            axis_m = decal.axis if decal.axis.lstrip("-") != "xyz"[mirror[0]] else (decal.axis[1:] if decal.axis.startswith("-") else "-" + decal.axis)
            twin_decal = Decal(decal.image, axis_m, (at_m[0], at_m[1], at_m[2]), decal.size)
        parts.append(Part(index, str(mirror_id), mirrored, color[0], color[1], material, pattern, twin_decal, line, where, str(part_id), mirror[0],
                          bool(loose), **hard_fields))  # fmt: skip
    return parts


def _reflect(g: Geometry, axis: int) -> Geometry:
    """The part mirrored across 0 on `axis`, as a separate part (mirror_id). The local frame stays the same and
    the reflection goes into the placement (a reflection matrix instead of a rotation), so every shape works."""
    flip = np.eye(3)
    flip[axis, axis] = -1.0
    rotation = flip @ (g.rotation if g.rotation is not None else np.eye(3))
    copies = tuple(c if c is IDENTITY else Copy(flip @ c.rotation @ flip, c.pivot @ flip, c.offset @ flip) for c in g.copies)
    return Geometry(g.shape, g.params, g.at @ flip, rotation, (), copies, g.op, g.blend, g.shell, g.twist, g.noise, g.shell_side, g.open)


def _parse_pattern(ctx: _Ctx, raw: Any, line: int | None, where: str) -> Pattern | None:
    if not isinstance(raw, dict) or raw.get("type") not in PATTERNS:
        ctx.error("E003", f"pattern is {{ type: {'|'.join(PATTERNS)}, color, size (metres), axis: x|y|z }}", line, where)
        return None
    bad = [k for k in raw if k not in ("type", "color", "size", "axis", "width", "at")]
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
    if problems or c is None:
        if problems:
            ctx.error("E003", "pattern: " + "; ".join(problems), line, where)
        return None
    unit = [0.0, 0.0, 0.0]
    unit[AXES[axis]] = 1.0
    return Pattern(str(raw["type"]), c[0], c[1], float(size), (unit[0], unit[1], unit[2]), float(width), float(at))


def _parse_decal(ctx: _Ctx, raw: Any, line: int | None, where: str) -> Decal | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("image"), str):
        ctx.error("E003", "decal is { image: decals/logo.png, axis: z, at: [x, y, z], size: [w, h] }", line, where)
        return None
    axis = raw.get("axis", "z")
    at, size = _vec(raw.get("at")), _vec(raw.get("size"), 2)
    bad = [k for k in raw if k not in ("image", "axis", "at", "size")]
    if axis not in ("x", "-x", "y", "-y", "z", "-z") or at is None or size is None or min(size) <= 0 or bad:
        ctx.error("E003", "decal: axis x|-x|y|-y|z|-z (the way it faces), at: [x, y, z] (its centre), size: [w, h] metres", line, where)
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    image = (base / raw["image"]).resolve()
    if not image.is_file():
        ctx.error("E011", f"decal image {raw['image']} not found (paths are relative to the project folder)", line, f"{where}.image")
        return None
    return Decal(image, str(axis), (at[0], at[1], at[2]), (size[0], size[1]))


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
        if not isinstance(spec, dict) or any(k not in ("pivot", "parent", "meta", "separate", "sockets", "under") for k in spec):
            ctx.error("E007", "a rig entry is { pivot: [x, y, z], parent: id, meta: { key: value }, separate: true|false, sockets: { name: [x, y, z] }, "
                      "under: { color, material, gap } }", rline, where)  # fmt: skip
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
                                     tuple(sorted((k, (v[0], v[1], v[2])) for k, v in sockets.items() if v is not None)), under)  # fmt: skip
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
            out[twin] = RigEntry(pivot, parent, e.meta, e.separate, tuple(sockets), e.under)
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
        if not isinstance(change, dict) or any(k not in ("offset", "rotate", "scale") for k in change):
            ctx.error("E008", "a part's pose is { offset: [x, y, z] metres, rotate: [x, y, z] degrees, scale: s | [x, y, z] }", line, pwhere)
            return None
        offset = _vec(change.get("offset", [0, 0, 0]))
        rotate = _vec(change.get("rotate", [0, 0, 0]))
        sc = change.get("scale", 1.0)
        scale = (float(sc),) * 3 if _num(sc) else _vec(sc)
        if offset is None or rotate is None or scale is None or min(scale) <= 0:
            ctx.error("E008", "offset and rotate are [x, y, z]; scale is a number or [x, y, z] (> 0)", line, pwhere)
            return None
        out[str(part_id)] = PartPose((offset[0], offset[1], offset[2]), (rotate[0], rotate[1], rotate[2]), (scale[0], scale[1], scale[2]))
    return out


def _parse_import(ctx: _Ctx, name: str, spec: dict[str, Any], line: int | None, where: str, humanoid: bool) -> Animation | None:
    """An animation retargeted from a clip library: { import: imports/Rig_Medium_General.glb, clip: Idle_A }."""
    bad = [k for k in spec if k not in ("import", "clip", "fps", "loop", "speed")]
    fps, loop, speed = spec.get("fps", 30), spec.get("loop", True), spec.get("speed", 1.0)
    if bad or not isinstance(spec.get("import"), str) or not isinstance(spec.get("clip"), str) or not _num(fps) or not 0 < fps <= 120 \
            or not isinstance(loop, bool) or not _num(speed) or speed <= 0:
        ctx.error("E008", "an imported animation is { import: imports/clips.glb, clip: Walking_A, fps: 30, loop: true, speed: 1 }", line, where)
        return None
    if not humanoid:
        ctx.error("E008", "imported clips play on humanoids: add skeleton: humanoid (and name the parts after its joints)", line, where)
        return None
    base = ctx.path.parent.parent if ctx.path is not None else Path.cwd()
    file = (base / spec["import"]).resolve()
    if not file.is_file():
        ctx.error("E008", f"animation file {spec['import']} not found (paths are relative to the project)", line, f"{where}.import")
        return None
    from kiln.retarget import clip_names

    try:
        names = clip_names(file)
    except Exception as exc:  # noqa: BLE001 - any unreadable file is the same mistake
        ctx.error("E008", f"can't read {spec['import']}: {exc}", line, f"{where}.import")
        return None
    if spec["clip"] not in names:
        ctx.error("E008", f"{spec['import']} has no clip {spec['clip']!r} (it has: {', '.join(names)})", line, f"{where}.clip")
        return None
    return Animation(name, float(fps), loop, "linear", [], None, (file, str(spec["clip"]), float(speed)))


def _parse_animations(ctx: _Ctx, raw: Any, ids: set[str], line: int | None, humanoid: bool = False) -> dict[str, Animation]:
    out: dict[str, Animation] = {}
    if raw is None:
        return out
    if not isinstance(raw, dict):
        ctx.error("E008", "animations maps names to { fps, loop, poses: [...] } or { cycle: { type: walk, ... } }", line, "animations")
        return out
    for name, spec in raw.items():
        aline = _line(raw, name) or line
        where = f"animations.{name}"
        if not isinstance(name, str) or not NAME_RE.match(name):
            ctx.error("E008", "animation names are lowercase letters, digits, _ or -", aline, where)
            continue
        if isinstance(spec, dict) and "import" in spec:
            imported = _parse_import(ctx, name, spec, aline, where, humanoid)
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
            ctx.error("E008", "animation fields: fps (1-120), loop (true/false), interpolation (linear|step), poses or cycle", aline, where)
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
            named = [v for k, v in cycle.items() if k in ("legs", "arms", "parts", "part", "body", "head")]
            flat = [x for v in named for x in (v if isinstance(v, list) else [v])]
            unknown = [x for x in flat if x not in ids]
            if unknown:
                ctx.error("E008", f"cycle names unknown part id(s) {', '.join(map(str, unknown))} (ids: {', '.join(sorted(ids))})", aline, f"{where}.cycle")
                continue
            out[name] = Animation(name, float(fps), loop, interp, poses, dict(cycle))
    return out


def parse_model(data: Any, path: Path | None, palette: dict[str, str], materials: set[str], text: str = "") -> tuple[Model | None, list[Finding]]:
    ctx = _Ctx(path, palette, materials)
    if not isinstance(data, dict):
        ctx.error("E001", "a model file is a mapping (name, parts, ...)", None, None or "")
        return None, ctx.findings
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
    origin = data.get("origin")
    if origin is not None:
        if origin in ("base", "center"):
            model.origin = str(origin)
        elif isinstance(origin, list) and len(origin) == 3 and all(isinstance(v, int | float) and not isinstance(v, bool) for v in origin):
            model.origin = (float(origin[0]), float(origin[1]), float(origin[2]))
        else:
            ctx.error("E003", "origin is base (bottom centre of the model's box), center (its middle) or a point [x, y, z]: the exported mesh's "
                      "origin, e.g. center for debris that spins", _line(data, "origin"), "origin")  # fmt: skip
        if "fit_to" in data:
            ctx.error("E003", "an attachment (fit_to) is exported in its bone's space: drop origin", _line(data, "origin"), "origin")
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

    if "source" in data:
        if "parts" in data:
            ctx.error("E003", "a model has parts (made in KILN) or source (an imported mesh), not both", _line(data, "source"), "source")
        model.source = _parse_source(ctx, data["source"], data.get("process"), _line(data, "source"))
    else:
        raw_parts = data.get("parts")
        if not isinstance(raw_parts, list) or not raw_parts:
            ctx.error("E003", "parts must be a non-empty list, e.g. - sphere: { at: [0, 0.5, 0], radius: 0.5 }", _line(data, "parts"), "parts")
        else:
            for i, raw in enumerate(raw_parts):
                pline = _line(raw) or _line(data, "parts")
                kinds = [k for k in raw if k in HARDWARE] if isinstance(raw, dict) else []
                if not kinds:
                    model.parts.extend(_parse_part(ctx, raw, i, pline))
                    continue
                if len(kinds) > 1 or any(k in SHAPES for k in raw):
                    ctx.error("E003", f"each part needs exactly one shape: {', '.join(SHAPES)}, or one hardware part: {', '.join(HARDWARE)}", pline, f"parts[{i}]")
                    continue
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
            for part in model.parts:
                if part.cut_only is not None:
                    part.geometry.cut_only = frozenset(i for i, q in enumerate(model.parts) if q.id == part.cut_only and q.geometry.op == "add")
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
                targets = tuple(q.geometry for q in model.parts if q.id in wanted and q.id != part.id and q.geometry.op == "add" and q.fit is None)
                if not targets:
                    if not model.template:  # a template (a helmet) may fit parts another template brings (a head)
                        ctx.error("E003", f"fit: no other part has id {', '.join(part.fit[0])} (it wraps the parts with those ids)", part.line,
                                  f"{part.where}.fit")  # fmt: skip
                    continue
                part.geometry.fit = (targets, part.fit[1])
    ids = set(model.ids) if model.parts else {ROOT_ID}
    model.rig = _mirror_rig(_parse_rig(ctx, data.get("rig"), ids, _line(data, "rig"), model.template), model.parts)
    skeleton = data.get("skeleton")
    if skeleton is not None:
        missing = [j for j in REQUIRED if j not in ids]
        if skeleton != "humanoid":
            ctx.error("E007", "skeleton is humanoid (parts named after the standard joints: hips, spine, chest, head, upperarm_l, ...)",
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
    model.animations = _parse_animations(ctx, data.get("animations"), ids, _line(data, "animations"), model.skeleton is not None)
    if model.animations and model.skin == "none":
        ctx.error("E008", "animations move parts: give the model a rig (pivots and parents) or skin: rigid", _line(data, "animations"), "animations")
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
            for a, b in spec["swap"].items():
                ca = _color(ctx, a, vline, f"variants.{vname}.swap")
                cb = _color(ctx, b, vline, f"variants.{vname}.swap")
                if ca and cb:
                    swap[ca[0]] = cb[0]
            model.variants[str(vname)] = swap
    return model, ctx.findings


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
    if not file.is_file() or file.suffix.lower() not in (".glb", ".gltf"):
        ctx.error("E010", f"source file {raw['file']} not found or not .glb/.gltf (paths are relative to the project)", line, "source.file")
        return None
    licence = raw.get("licence")
    if not isinstance(licence, str) or not licence:
        ctx.error("E010", "source needs licence (an SPDX id: CC0-1.0, CC-BY-4.0, ...) so credits and checks work", line, "source.licence")
        return None
    src = Source(file, licence, str(raw.get("author", "")), str(raw.get("url", "")))
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
