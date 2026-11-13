"""Python building blocks for generator scripts: repetitive structures (walls with merlons, fences, stairs, rings
of things, trees, towers, crowds of variants) written out as ordinary `.kiln.yaml` models.

An agent writes a short script with these when a model has many regular parts, runs it, and the result is a
plain model file that `kiln lint` and `kiln preview` treat like any other. Covered by versioning: API_VERSION.

    from kiln.api import model, part, crenellated_wall, write_model
    parts = crenellated_wall(length=6, height=3, thickness=1, color="stone")
    write_model("models/wall.kiln.yaml", model("wall", parts, cls="building"))
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import numpy as np
import yaml

API_VERSION = 1
Part = dict[str, Any]


def part(shape: str, color: str | None = None, material: str = "default", id: str | None = None, **params: Any) -> Part:  # noqa: A002
    """One part: `part("box", color="wood", at=[0, 0.5, 0], size=[1, 1, 1], round=0.05, blend=0.02)`.
    Part-level options (blend, cut, intersect, mirror, mirror_id, array, shell, twist, noise, pattern, decal, loose,
    hard, bevel, chamfer, segments, fit, keep, uv, attr, aim) may be passed with the shape's own parameters; they are sorted into the
    right place."""
    part_keys = {"blend", "blend_to", "cut", "intersect", "mirror", "mirror_id", "array", "shell", "twist", "scale", "noise", "pattern",
                 "gradient", "decal", "texture", "loose",
                 "hard", "bevel", "chamfer", "segments", "fit", "keep", "uv", "attr", "aim"}  # fmt: skip
    if "from_" in params:  # `from` is a Python keyword (#206)
        params["from"] = params.pop("from_")
    shape_params = {k: v for k, v in params.items() if k not in part_keys}
    out: Part = {shape: shape_params}
    if id is not None:
        out["id"] = id
    if not params.get("cut") and not params.get("intersect"):
        out["color"] = color or "grey"
        out["material"] = material
    elif params.get("cut") and color is not None:  # a cut's colour paints the walls it makes (#178, #344)
        out["color"] = color
        if material != "default":
            out["material"] = material
    for key in sorted(part_keys & params.keys()):
        out[key] = params[key]
    return out


def _r(v: float) -> float:
    return round(float(v), 4)


def ring(count: int, radius: float, y: float, make: Any, start_angle: float = 0.0) -> list[Part]:
    """`make(x, y, z, angle_degrees)` -> Part, called for `count` points on a horizontal circle."""
    parts = []
    for i in range(count):
        a = math.radians(start_angle + 360.0 * i / count)
        parts.append(make(_r(radius * math.sin(a)), _r(y), _r(radius * math.cos(a)), _r(math.degrees(a))))
    return parts


def crenellated_wall(length: float, height: float, thickness: float, color: str = "stone", material: str = "stone",
                     merlon: float = 0.5, gap: float = 0.4, round_edges: float = 0.03, noise: float = 0.0) -> list[Part]:  # fmt: skip
    """A wall along x centred on 0, standing on y = 0, with merlons on top."""
    extra: dict[str, Any] = {"noise": {"amount": noise, "scale": 0.3}} if noise else {}
    parts = [part("box", color, material, at=[0, _r(height / 2), 0], size=[_r(length), _r(height), _r(thickness)], round=round_edges, **extra)]
    count = max(1, int((length + gap) // (merlon + gap)))
    span = count * merlon + (count - 1) * gap
    first = -span / 2 + merlon / 2
    parts.append(part("box", color, material, at=[_r(first), _r(height + merlon / 2), 0], size=[_r(merlon), _r(merlon), _r(thickness)],
                      round=round_edges, array={"count": count, "step": [_r(merlon + gap), 0, 0]}, **extra))  # fmt: skip
    return parts


def fence(length: float, posts: int, height: float = 1.0, color: str = "wood", material: str = "wood", rails: int = 2) -> list[Part]:
    """Posts along x with horizontal rails."""
    step = length / max(posts - 1, 1)
    parts = [part("box", color, material, at=[_r(-length / 2), _r(height / 2), 0], size=[0.08, _r(height), 0.08], round=0.015,
                  array={"count": posts, "step": [_r(step), 0, 0]})]  # fmt: skip
    for k in range(rails):
        y = height * (0.35 + 0.45 * k / max(rails - 1, 1))
        parts.append(part("box", color, material, at=[0, _r(y), 0.05], size=[_r(length), 0.06, 0.03], round=0.01))
    return parts


def stairs(steps: int, width: float, rise: float, run: float, color: str = "stone", material: str = "stone") -> list[Part]:
    """Steps going up towards -z from z = 0."""
    return [part("box", color, material, at=[0, _r(rise * (i + 0.5)), _r(-run * (i + 0.5))], size=[_r(width), _r(rise), _r(run)], round=0.01)
            for i in range(steps)]  # fmt: skip


def tower(radius: float, height: float, color: str = "stone", roof_color: str = "red", material: str = "stone") -> list[Part]:
    """A round tower with a cone roof."""
    return [
        part("cylinder", color, material, at=[0, _r(height / 2), 0], radius=_r(radius), height=_r(height), round=0.03),
        part("cone", roof_color, "paint", at=[0, _r(height + radius * 0.6), 0], radius=_r(radius * 1.2), radius_top=0.0, height=_r(radius * 1.2)),
    ]


def tree(height: float = 3.0, crown: float = 1.0, seed: int = 1, bark: str = "brown", leaves: str = "green", blobs: int = 4) -> list[Part]:
    """A trunk and a lumpy crown of blended spheres (deterministic for a seed)."""
    rng = random.Random(seed)
    trunk_top = height - crown
    trunk: dict[str, Any] = {"from": [0, 0, 0], "to": [0, _r(trunk_top), 0], "radius": _r(crown * 0.18), "radius_to": _r(crown * 0.1)}
    parts = [part("capsule", bark, "wood", **trunk)]
    parts.append(part("sphere", leaves, "leaf", at=[0, _r(trunk_top + crown * 0.6), 0], radius=_r(crown * 0.75), noise={"amount": _r(crown * 0.05), "scale": _r(crown * 0.4), "seed": seed}))
    for _ in range(blobs - 1):
        a = rng.uniform(0, 2 * math.pi)
        r = crown * rng.uniform(0.35, 0.6)
        parts.append(part("sphere", leaves, "leaf", at=[_r(r * math.sin(a)), _r(trunk_top + crown * rng.uniform(0.3, 0.9)), _r(r * math.cos(a))],
                          radius=_r(crown * rng.uniform(0.35, 0.55)), blend=_r(crown * 0.2)))  # fmt: skip
    return parts


SHAPE_SKIP = ("array", "noise", "pattern", "gradient", "decal", "texture", "fit", "uv", "attr", "aim", "scale", "on")
AXES = "xyz"


def _shape_key(p: Part) -> str:
    return next(k for k in p if isinstance(p[k], dict) and k not in SHAPE_SKIP)


def _copy(p: Part) -> Part:
    import copy

    return copy.deepcopy(p)


def _reflect_part(p: Part, axis: int) -> Part:
    """The part mirrored across the plane through 0 square to `axis` (what `mirror:` makes), written out."""
    from kiln.hardware import _euler
    from kiln.sdf import rotation_matrix

    q = _copy(p)
    q.pop("mirror", None)
    if "mirror_id" in q:
        q["id"] = q.pop("mirror_id")
    flip = np.eye(3)
    flip[axis, axis] = -1.0

    def pt(v: list[float]) -> list[float]:
        w = list(map(float, v))
        w[axis] = -w[axis]
        return [_r(c) for c in w]

    s = q[_shape_key(q)]
    for key in ("at", "from", "to", "facing"):
        if key in s:
            s[key] = pt(s[key])
    if "at" in q:
        q["at"] = pt(q["at"])
    if "points" in s:
        s["points"] = [pt(v) for v in s["points"]]
    if "aim" in q:
        q["aim"] = [pt(v) for v in q["aim"]]
    for holder in (s, q):
        if "rotate" in holder:
            m = flip @ rotation_matrix(tuple(map(float, holder["rotate"]))) @ flip  # type: ignore[arg-type]
            holder["rotate"] = [_r(v) for v in _euler(m)]
    if isinstance(q.get("array"), dict) and "center" in q["array"]:
        q["array"]["center"] = pt(q["array"]["center"])
    for key in ("decal", "texture"):
        d = q.get(key)
        if isinstance(d, dict):
            if "at" in d:
                d["at"] = pt(d["at"])
            if isinstance(d.get("axis"), str) and d["axis"].lstrip("-") == AXES[axis]:
                d["axis"] = d["axis"][1:] if d["axis"].startswith("-") else "-" + d["axis"]
    return q


def _unmirror(parts: list[Part]) -> list[Part]:
    """Mirrored parts written out as two (a mirror is about the model's origin: moved or turned, the copy must come
    along explicitly)."""
    out: list[Part] = []
    for p in parts:
        m = p.get("mirror")
        if not m:
            out.append(p)
            continue
        names = [m] if isinstance(m, str) else list(m)
        first = _copy(p)
        first.pop("mirror", None)
        twin_id = first.pop("mirror_id", None)
        copies = [first]
        for name in names:
            axis = AXES.index(name.lstrip("+-"))
            more = []
            for c in copies:
                twin = _reflect_part({**c, "mirror_id": twin_id} if twin_id else c, axis)
                more.append(twin)
            copies += more
        out += copies
    return out


def transform(parts: list[Part], rotate: tuple[float, float, float] | list[float] = (0.0, 0.0, 0.0), about: tuple[float, float, float] | list[float] = (0.0, 0.0, 0.0),
              translate: tuple[float, float, float] | list[float] = (0.0, 0.0, 0.0), cut_only: list[str] | None = None) -> list[Part]:  # fmt: skip
    """Parts turned by `rotate` (Euler degrees, as a part's rotate) about the point `about`, then moved by `translate`:
    positions (at, from/to, points, aim, array centre, decal and texture centres), each part's own rotation and lock
    facing, decal axes (an axis that no longer lies along x, y or z is an error). Mirrored parts are written out as
    pairs first (a mirror is about the model's origin). `cut_only`: unscoped cuts cut only these ids (a placed group's
    holes don't cut the rest of a scene)."""
    from kiln.hardware import _euler
    from kiln.sdf import rotation_matrix

    rot = rotation_matrix(tuple(map(float, rotate)))  # type: ignore[arg-type]
    c, t = np.asarray(about, float), np.asarray(translate, float)
    turned = bool(np.abs(rot - np.eye(3)).max() > 1e-12)
    moves_mirror = any(p.get("mirror") for p in parts) and (turned or bool(np.abs(t).max() > 0))
    src = _unmirror(parts) if moves_mirror else [_copy(p) for p in parts]

    def pt(v: list[float]) -> list[float]:
        w = rot @ (np.asarray(v, float) - c) + c + t
        return [_r(float(x)) for x in w]

    def vec(v: list[float]) -> list[float]:
        return [_r(float(x)) for x in rot @ np.asarray(v, float)]

    out = []
    for q in src:
        s = q[_shape_key(q)]
        if "from" in s or "points" in s:
            for key in ("from", "to"):
                if key in s:
                    s[key] = pt(s[key])
            if "points" in s:
                s["points"] = [pt(v) for v in s["points"]]
            if "facing" in s:
                s["facing"] = vec(s["facing"])
            if "at" in s:
                s["at"] = pt(s["at"])
        else:
            holder = q if "at" in q else s  # a part-level at (lathes) moves instead of a second, shape-level one
            holder["at"] = pt(holder.get("at", [0, 0, 0]))
            if turned:
                own = rotation_matrix(tuple(map(float, holder.get("rotate", s.get("rotate", [0, 0, 0])))))  # type: ignore[arg-type]
                target = q if "rotate" in q else s
                target["rotate"] = [_r(v) for v in _euler(rot @ own)]
        if "aim" in q:
            q["aim"] = [pt(v) for v in q["aim"]]
        arr = q.get("array")
        if isinstance(arr, dict):
            if "center" in arr:
                arr["center"] = pt(arr["center"])
            if turned and isinstance(arr.get("around"), str):
                axis = np.zeros(3)
                axis[AXES.index(arr["around"])] = 1.0
                if np.abs(np.abs(rot @ axis) - axis).max() > 1e-6:
                    raise ValueError(f"transform: an array round {arr['around']} can't turn off its axis; turn about that axis or write the copies out")
        for key in ("decal", "texture"):
            d = q.get(key)
            if isinstance(d, dict):
                if "at" in d:
                    d["at"] = pt(d["at"])
                if turned and isinstance(d.get("axis"), str):
                    name = d["axis"]
                    v = np.zeros(3)
                    v[AXES.index(name.lstrip("-"))] = -1.0 if name.startswith("-") else 1.0
                    w = rot @ v
                    k = int(np.argmax(np.abs(w)))
                    if abs(abs(w[k]) - 1.0) > 1e-6:
                        raise ValueError(f"transform: a {key} facing {name} no longer faces along x, y or z after the turn")
                    d["axis"] = ("-" if w[k] < 0 else "") + AXES[k]
        if cut_only is not None and q.get("cut") is True:
            q["cut"] = list(cut_only)
        out.append(q)
    return out


def offset(parts: list[Part], dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> list[Part]:
    """Move parts (positions, part-level at, array centres, decal and texture centres; mirrored parts written out as
    pairs, since a mirror is about the model's origin): `transform(parts, translate=(dx, dy, dz))`."""
    return transform(parts, translate=(dx, dy, dz))


def surface_point(profile: list[list[float]], y: float, angle: float, at: tuple[float, float, float] | list[float] = (0.0, 0.0, 0.0)) -> tuple[list[float], list[float]]:
    """A point on a lathe's surface (its `profile` of [radius, y] pairs; a cone: [[radius, -h/2], [radius_top, h/2]])
    at height `y` (its own frame) and `angle` degrees round y (0 = +z, 90 = +x), and the outward normal there, both in
    model space (`at`: the part's at). For a ring of tiles on a cone: put each `at` the point and aim it along the
    normal (#206)."""
    pts = sorted(((float(r), float(h)) for r, h in profile), key=lambda q: q[1])
    for (r0, y0), (r1, y1) in zip(pts, pts[1:], strict=False):
        if y0 <= y <= y1 and y1 > y0:
            u = (y - y0) / (y1 - y0)
            radius, slope = r0 + (r1 - r0) * u, (r1 - r0) / (y1 - y0)
            break
    else:
        raise ValueError(f"surface_point: y = {y} is outside the profile ({pts[0][1]} to {pts[-1][1]})")
    a = math.radians(angle)
    out = np.array([math.sin(a), 0.0, math.cos(a)])
    normal = out - np.array([0.0, slope, 0.0])  # the profile leans by `slope` (radius per height): the normal leans back
    normal /= np.linalg.norm(normal)
    point = np.asarray(at, float) + out * radius + np.array([0.0, y, 0.0])
    return [_r(float(v)) for v in point], [_r(float(v)) for v in normal]


def model(name: str, parts: list[Part], cls: str = "prop", description: str = "", **fields: Any) -> dict[str, Any]:
    """A model as a dict (add rig=, skin=, animations=, variants=, style=, palette= ...)."""
    out: dict[str, Any] = {"name": name, "description": description, "class": cls, "status": "draft"}
    out.update(fields)
    out["parts"] = parts
    return out


def _flow(value: Any) -> str:
    text = str(yaml.safe_dump(value, default_flow_style=True, width=10_000, sort_keys=False))
    return text.removesuffix("\n").removesuffix("\n...").strip()  # scalars end with a document-end marker


def dumps(data: dict[str, Any]) -> str:
    """Readable YAML: top-level keys in blocks, each part's shape as one flow line (the notation's usual look)."""
    lines = []
    for key, value in data.items():
        if key == "parts":
            lines.append("parts:")
            for p in value:
                items = list(p.items())
                first_key, first_val = items[0]
                lines.append(f"  - {first_key}: {_flow(first_val)}")
                lines += [f"    {k}: {_flow(v)}" for k, v in items[1:]]
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {k}: {_flow(v)}" for k, v in value.items()]
        else:
            lines.append(f"{key}: {_flow(value)}")
    return "\n".join(lines) + "\n"


def write_model(path: str | Path, data: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(data), encoding="utf-8")
    return path


__all__ = ["API_VERSION", "crenellated_wall", "dumps", "fence", "model", "offset", "part", "ring", "stairs", "surface_point", "tower", "transform", "tree",
           "write_model"]
