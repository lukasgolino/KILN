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

import yaml

API_VERSION = 1
Part = dict[str, Any]


def part(shape: str, color: str | None = None, material: str = "default", id: str | None = None, **params: Any) -> Part:  # noqa: A002
    """One part: `part("box", color="wood", at=[0, 0.5, 0], size=[1, 1, 1], round=0.05, blend=0.02)`.
    Part-level options (blend, cut, intersect, mirror, mirror_id, array, shell, twist, noise, pattern, decal, loose,
    hard, bevel, chamfer, segments, fit, keep, uv) may be passed with the shape's own parameters; they are sorted into the
    right place."""
    part_keys = {"blend", "cut", "intersect", "mirror", "mirror_id", "array", "shell", "twist", "noise", "pattern", "decal", "loose",
                 "hard", "bevel", "chamfer", "segments", "fit", "keep", "uv"}  # fmt: skip
    shape_params = {k: v for k, v in params.items() if k not in part_keys}
    out: Part = {shape: shape_params}
    if id is not None:
        out["id"] = id
    if not params.get("cut") and not params.get("intersect"):
        out["color"] = color or "grey"
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


def offset(parts: list[Part], dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> list[Part]:
    """Move parts (their `at`, capsule from/to, tube points)."""
    out = []
    for p in parts:
        q = {k: (dict(v) if isinstance(v, dict) else v) for k, v in p.items()}
        shape = next(k for k in q if isinstance(q[k], dict) and k not in ("array", "noise", "pattern", "decal"))
        s = q[shape]
        for key in ("at", "from", "to"):
            if key in s or (key == "at" and "from" not in s):
                v = list(s.get(key, [0, 0, 0]))
                s[key] = [_r(v[0] + dx), _r(v[1] + dy), _r(v[2] + dz)]
        if "points" in s and shape == "tube":
            s["points"] = [[_r(x + dx), _r(y + dy), _r(z + dz)] for x, y, z in s["points"]]
        out.append(q)
    return out


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


__all__ = ["API_VERSION", "crenellated_wall", "dumps", "fence", "model", "offset", "part", "ring", "stairs", "tower", "tree", "write_model"]
