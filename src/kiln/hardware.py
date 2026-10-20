"""Hardware parts: the small details CC0 packs use to read as metal or wood (rivets, iron bands, planks, bolts,
slits). Each one is written like a shape but stands for several ordinary parts (hard by default), expanded when
the model is read; every other field of the part (colour, material, id, mirror, ...) goes to each of them."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kiln.sdf import Geometry, rotation_matrix

HARDWARE = ("rivets", "band", "planks", "bolt", "slit")
AXES = {"x": 0, "y": 1, "z": 2}
HELP = {
    "rivets": "rivets: { count: 8, along: [[x, y, z], ...] (a path, model space) or around: { center: [x, y, z], radius, axis: y }, size: 0.03 }",
    "band": "band: { at: [x, y, z], radius (or fit: <part id>: its surface there), width, thickness, axis: y, sides }",
    "planks": "planks: { size: [x, y, z], count, gap, axis: x (side by side along it), jitter: 0.1, seed: 1 } (with at, rotate)",
    "bolt": "bolt: { at: [x, y, z], radius, length, sides: 6 } (a hex head along y; rotate it)",
    "slit": "slit: { at: [x, y, z], size: [w, h, d] } (a cut: visors, arrow slits)",
}


def _get(d: dict[str, Any], key: str, default: Any = None) -> Any:
    return d.get(key, default)


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _vec(v: Any) -> list[float] | None:
    return [float(x) for x in v] if isinstance(v, list) and len(v) == 3 and all(_num(x) for x in v) else None


def _axis_rotate(axis: str) -> list[float]:
    """Euler degrees turning the y axis onto `axis`."""
    return {"x": [0.0, 0.0, -90.0], "y": [0.0, 0.0, 0.0], "z": [90.0, 0.0, 0.0]}[axis]


def _surface_radius(parts: list[Geometry], centre: np.ndarray, axis: int, half_width: float) -> float:
    """How far the parts' surface is from the axis line through `centre`: the most, over a ring of directions and
    the band's width (so a band sits on a barrel's bulge)."""
    others = [a for a in range(3) if a != axis]
    best = 0.0
    for along in (-half_width, 0.0, half_width):
        for k in range(16):
            t = 2 * math.pi * k / 16
            direction = np.zeros(3)
            direction[others[0]], direction[others[1]] = math.cos(t), math.sin(t)
            base = centre.copy()
            base[axis] += along
            radii = np.linspace(0.0, 4.0, 801)  # 5 mm steps out to 4 m
            pts = base + radii[:, None] * direction
            d = np.min([g.distance(pts) for g in parts], axis=0)
            outside = np.flatnonzero(d > 0)
            if len(outside) and outside[0] > 0:
                i = int(outside[0])
                # between the last inside sample and the first outside one
                r0, r1, d0, d1 = radii[i - 1], radii[i], d[i - 1], d[i]
                best = max(best, float(r0 + (r1 - r0) * (-d0) / (d1 - d0)))
    return best


def expand(kind: str, spec: Any, raw: dict[str, Any], earlier: list[tuple[str, Geometry]]) -> tuple[list[dict[str, Any]], str | None]:
    """The ordinary parts a hardware part stands for, or an error message. `earlier`: (id, geometry) of the adding
    parts before it (for band fit)."""
    if not isinstance(spec, dict):
        return [], f"{kind} takes a mapping: {HELP[kind]}"
    rest = {k: v for k, v in raw.items() if k != kind}
    rest.setdefault("hard", True)
    at = _vec(_get(spec, "at", rest.pop("at", [0, 0, 0])))
    rotate = _vec(_get(spec, "rotate", rest.pop("rotate", [0, 0, 0])))
    if at is None or rotate is None:
        return [], f"{kind}: at and rotate are [x, y, z]"
    turn = rotation_matrix((rotate[0], rotate[1], rotate[2]))

    def place(local: list[float]) -> list[float]:
        return [float(v) for v in np.asarray(at) + turn @ np.asarray(local)]

    if kind == "rivets":
        count, size = _get(spec, "count"), _get(spec, "size", 0.03)
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 256 or not _num(size) or size <= 0 \
                or ("along" in spec) == ("around" in spec) or any(k not in ("count", "along", "around", "size", "sides") for k in spec):
            return [], HELP[kind]
        if "along" in spec:
            path = spec["along"]
            if not isinstance(path, list) or len(path) < 2 or any(_vec(p) is None for p in path):
                return [], "rivets along is a path of 2+ points [x, y, z] (model space)"
            pts = np.array([_vec(p) for p in path], float)
            seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
            total = float(seg.sum())
            cum = np.concatenate([[0.0], np.cumsum(seg)])
            where = [total * k / max(count - 1, 1) for k in range(count)] if count > 1 else [total / 2]
            spots = []
            for s in where:
                i = min(int(np.searchsorted(cum, s, side="right")) - 1, len(seg) - 1)
                f = (s - cum[i]) / seg[i] if seg[i] > 0 else 0.0
                spots.append([float(v) for v in pts[i] + (pts[i + 1] - pts[i]) * f])
        else:
            ring = spec["around"]
            centre = _vec(_get(ring, "center")) if isinstance(ring, dict) else None
            if centre is None or not _num(_get(ring, "radius")) or _get(ring, "axis", "y") not in AXES:
                return [], "rivets around is { center: [x, y, z], radius, axis: x|y|z }"
            a = AXES[_get(ring, "axis", "y")]
            o = [k for k in range(3) if k != a]
            spots = []
            for k in range(count):
                t = 2 * math.pi * k / count
                p = list(centre)
                p[o[0]] += float(ring["radius"]) * math.sin(t)
                p[o[1]] += float(ring["radius"]) * math.cos(t)
                spots.append(p)
        sides = _get(spec, "sides", 6)
        return [{**rest, "sphere": {"at": p, "radius": float(size) / 2, "sides": sides}} for p in spots], None
    if kind == "band":
        width, thick, axis = _get(spec, "width"), _get(spec, "thickness", 0.01), _get(spec, "axis", "y")
        if not _num(width) or width <= 0 or not _num(thick) or thick <= 0 or axis not in AXES \
                or any(k not in ("at", "rotate", "radius", "fit", "width", "thickness", "axis", "sides") for k in spec):
            return [], HELP[kind]
        if "fit" in spec:
            parts = [g for pid, g in earlier if pid == spec["fit"]]
            if not parts:
                return [], f"band fit: no earlier part has id {spec['fit']!r} (the band goes around its surface)"
            radius = _surface_radius(parts, np.asarray(at), AXES[axis], float(width) / 2)
            if radius <= 0:
                return [], f"band fit: the axis through {at} isn't inside part {spec['fit']!r}"
        elif _num(_get(spec, "radius")) and spec["radius"] > 0:
            radius = float(spec["radius"])
        else:
            return [], "band needs radius, or fit: <part id> (around that part's surface)"
        cyl: dict[str, Any] = {"at": at, "radius": radius + float(thick), "height": float(width), "rotate": _axis_rotate(axis)}
        if "sides" in spec:
            cyl["sides"] = spec["sides"]
        return [{**rest, "cylinder": cyl}], None
    if kind == "planks":
        size, count, gap, axis = _vec(_get(spec, "size")), _get(spec, "count"), _get(spec, "gap", 0.01), _get(spec, "axis", "x")
        jitter, seed = _get(spec, "jitter", 0.0), _get(spec, "seed", 0)
        if size is None or min(size) <= 0 or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 64 or not _num(gap) \
                or gap < 0 or axis not in AXES or not _num(jitter) or not 0 <= jitter < 1 or not isinstance(seed, int) \
                or any(k not in ("at", "rotate", "size", "count", "gap", "axis", "jitter", "seed") for k in spec):
            return [], HELP[kind]
        a = AXES[axis]
        width = (size[a] - gap * (count - 1)) / count
        if width <= 0:
            return [], f"planks: {count} planks with {gap} m gaps don't fit in {size[a]} m"
        others = [k for k in range(3) if k != a]
        length_axis = max(others, key=lambda k: size[k])  # planks run along the longer remaining side
        rng = np.random.default_rng(seed)
        out = []
        for i in range(count):
            local = [0.0, 0.0, 0.0]
            local[a] = -size[a] / 2 + width / 2 + i * (width + gap)
            dims = list(size)
            dims[a] = width
            cut = float(rng.uniform(0.0, jitter)) * size[length_axis]
            dims[length_axis] = size[length_axis] - cut
            local[length_axis] = cut / 2 * (1 if rng.uniform() < 0.5 else -1)
            box: dict[str, Any] = {"at": place(local), "size": dims}
            if any(rotate):
                box["rotate"] = rotate
            part = {**rest, "box": box}
            part.setdefault("chamfer", round(min(width, dims[length_axis], min(size)) * 0.08, 6))
            out.append(part)
        return out, None
    if kind == "bolt":
        radius, length = _get(spec, "radius"), _get(spec, "length")
        if not _num(radius) or radius <= 0 or not _num(length) or length <= 0 or any(k not in ("at", "rotate", "radius", "length", "sides") for k in spec):
            return [], HELP[kind]
        cyl = {"at": at, "radius": float(radius), "height": float(length), "sides": _get(spec, "sides", 6)}
        if any(rotate):
            cyl["rotate"] = rotate
        return [{**rest, "cylinder": cyl}], None
    # slit
    size = _vec(_get(spec, "size"))
    if size is None or min(size) <= 0 or any(k not in ("at", "rotate", "size") for k in spec):
        return [], HELP[kind]
    rest.pop("hard", None)
    box = {"at": at, "size": size}
    if any(rotate):
        box["rotate"] = rotate
    return [{**{k: v for k, v in rest.items() if k not in ("color", "material")}, "box": box, "cut": True}], None


__all__ = ["HARDWARE", "expand"]
