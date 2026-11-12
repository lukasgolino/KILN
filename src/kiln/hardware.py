"""Hardware parts: the small details CC0 packs use to read as metal or wood (rivets, iron bands, planks, bolts,
slits). Each one is written like a shape but stands for several ordinary parts (hard by default), expanded when
the model is read; every other field of the part (colour, material, id, mirror, ...) goes to each of them."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from kiln.sdf import Geometry, rotation_matrix

HARDWARE = ("rivets", "band", "planks", "bolt", "slit", "garment", "hand", "foot", "eye")
AXES = {"x": 0, "y": 1, "z": 2}
HELP = {
    "rivets": "rivets: { count: 8, along: [[x, y, z], ...] (a path, model space) or around: { center: [x, y, z], radius, axis: y }, size: 0.03 }",
    "band": "band: { at: [x, y, z], radius (or fit: <part id> or [ids]: their surface there; hugs it where it isn't round), width, thickness, axis: y, sides }",
    "planks": "planks: { size: [x, y, z], count, gap, axis: x (side by side along it), jitter: 0.1, seed: 1 } (with at, rotate)",
    "bolt": "bolt: { at: [x, y, z], radius, length, sides: 6 } (a hex head along y; rotate it)",
    "slit": "slit: { at: [x, y, z], size: [w, h, d] } (a cut: visors, arrow slits)",
    "garment": "garment: { fit: [chest, spine, ...] (ids it wraps), gap: 0.008, thickness: 0.02 (two mesh cells or more), from_y, to_y (its hem and top; "
               "default: theirs), hem: 0.015 (a thicker band at the bottom; 0: none), openings: [{ at, size }, ...] (cut through it) }",
    "hand": "hand: { at: [x, y, z] (the wrist), length: 0.2 (wrist to fingertip), width (palm; 0.5 x length), fingers: 4 (1-6), thumb: true, "
            "curl: 30 (degrees per finger, towards the palm), spread: 8 (degrees, fanned), knuckles: 0.04 (bulge), nail: 0 (claw length; 0: none), "
            "nail_color } (with rotate; fingers point -y, the palm faces -x, the thumb +z: a left hand hanging at the side)",
    "foot": "foot: { at: [x, y, z] (the back of the sole, under the ankle), length: 0.26 (heel to toe tip), width (0.42 x length), toes: 5 (1-6), curl: 10 (degrees, down), "
            "spread: 6, nail: 0 (claw length), nail_color, heel: true } (with rotate; toes point +z, the sole down)",
    "eye": "eye: { at: [x, y, z] (on the face's surface), facing: [0, 0, 1] (out of the face), radius: 0.03, depth: 0.4 (the ball's front sits this share "
           "of radius behind the surface), rim: 0.15 (share of radius; 0: none), rim_color, rim_material, rim_emission, in: head (the part(s) it is cut "
           "into; default: every earlier part) } (the part's colour is the ball's)",
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
    return max(_surface_radii(parts, centre, axis, half_width), default=0.0)


def _surface_radii(parts: list[Geometry], centre: np.ndarray, axis: int, half_width: float) -> list[float]:
    """Per direction round the axis (16), the farthest the parts' surface is from it over the band's width."""
    others = [a for a in range(3) if a != axis]
    out = []
    for k in range(16):
        best = 0.0
        for along in (-half_width, 0.0, half_width):
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
        out.append(best)
    return out


def _garment(spec: dict[str, Any], rest: dict[str, Any], earlier: list[tuple[str, Geometry]]) -> tuple[list[dict[str, Any]], str | None]:
    """A layer of clothing (#193): a box over the wrapped parts between from_y and to_y, a shell `thickness` thick
    fitted `gap` off their surface (open where the box ends: hem, neck and cuffs), a second, thicker band at the hem,
    and `openings` cut through the garment alone (a placket, a neckline)."""
    keys = ("fit", "gap", "thickness", "from_y", "to_y", "hem", "openings")
    if any(k not in keys for k in spec):
        return [], HELP["garment"]
    ids = spec.get("fit")
    ids = [ids] if isinstance(ids, str) else ids
    gap, thick, hem = spec.get("gap", 0.008), spec.get("thickness", 0.02), spec.get("hem", 0.015)  # walls under two mesh cells break up (W102)
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids) or not _num(gap) or gap < 0 or not _num(thick) \
            or thick <= 0 or not _num(hem) or hem < 0:
        return [], HELP["garment"]
    wrapped = [g for pid, g in earlier if pid in ids]
    if not wrapped:
        return [], f"garment fit: no earlier part has id {', '.join(ids)} (it wraps parts listed before it)"
    boxes = [g.bounds() for g in wrapped]
    lo, hi = np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)
    y0, y1 = spec.get("from_y", float(lo[1])), spec.get("to_y", float(hi[1]))
    if not _num(y0) or not _num(y1) or y1 <= y0:
        return [], "garment from_y and to_y are its hem's and its top's height in metres (from_y < to_y)"
    room = float(gap) + float(thick) + 0.02  # the box reaches past the wall all round, except at its hem and top
    centre = [(lo[0] + hi[0]) / 2, (y0 + y1) / 2, (lo[2] + hi[2]) / 2]
    size = [float(hi[0] - lo[0]) + 2 * room, float(y1 - y0), float(hi[2] - lo[2]) + 2 * room]
    dropped = [k for k in ("at", "rotate", "hard") if k in rest]
    if dropped:
        return [], f"garment takes no {', '.join(dropped)}: it sits on the parts it fits (from_y, to_y give its extent; it is soft cloth)"
    garment_id = rest.get("id")
    out: list[dict[str, Any]] = [{**rest, "box": {"at": [float(v) for v in centre], "size": size}, "shell": float(thick),
                                   "fit": {"to": list(ids), "gap": float(gap)}}]  # fmt: skip
    if hem > 0:
        band = min(float(hem) * 2, size[1])
        out.append({**rest, "box": {"at": [float(centre[0]), float(y0 + band / 2), float(centre[2])], "size": [size[0], band, size[2]]},
                    "shell": float(thick) * 1.8, "fit": {"to": list(ids), "gap": float(gap)}})  # fmt: skip
    openings = spec.get("openings", [])
    if not isinstance(openings, list):
        return [], HELP["garment"]
    for k, o in enumerate(openings):
        at, osize = (_vec(o.get("at")), _vec(o.get("size"))) if isinstance(o, dict) else (None, None)
        if at is None or osize is None or min(osize) <= 0 or any(key not in ("at", "size") for key in o):
            return [], f"garment openings[{k}] is {{ at: [x, y, z], size: [w, h, d] }} (cut through the garment)"
        if not isinstance(garment_id, str) or garment_id in ids:
            return [], ("garment openings cut the garment alone: give it an id of its own (e.g. id: shirt), not one of the parts it "
                        "fits (the cut would open those too)")  # fmt: skip
        out.append({"box": {"at": at, "size": osize}, "cut": garment_id})
        twin, axis = rest.get("mirror_id"), rest.get("mirror")
        if isinstance(twin, str) and isinstance(axis, str) and axis.lstrip("+-") in AXES:  # the mirrored garment's opening too
            flipped = list(at)
            flipped[AXES[axis.lstrip("+-")]] *= -1
            out.append({"box": {"at": flipped, "size": osize}, "cut": twin})
    return out, None


def expand(kind: str, spec: Any, raw: dict[str, Any], earlier: list[tuple[str, Geometry]]) -> tuple[list[dict[str, Any]], str | None]:
    """The ordinary parts a hardware part stands for, or an error message. `earlier`: (id, geometry) of the adding
    parts before it (for band fit)."""
    if not isinstance(spec, dict):
        return [], f"{kind} takes a mapping: {HELP[kind]}"
    rest = {k: v for k, v in raw.items() if k != kind}
    if kind in ("hand", "foot"):  # soft flesh: blended into the arm or leg
        return _limb_end(kind, spec, rest)
    if kind == "eye":
        return _eye(spec, rest)
    if kind == "garment":  # cloth: a fitted shell (soft), not hard metal
        return _garment(spec, rest, earlier)
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
            ids = [spec["fit"]] if isinstance(spec["fit"], str) else spec["fit"]
            if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
                return [], HELP[kind]
            parts = [g for pid, g in earlier if pid in ids]
            if not parts:
                return [], f"band fit: no earlier part has id {', '.join(map(str, ids))} (the band goes around its surface)"
            radii = _surface_radii(parts, np.asarray(at), AXES[axis], float(width) / 2)
            radius = max(radii)
            if radius <= 0:
                return [], f"band fit: the axis through {at} isn't inside part {', '.join(map(str, ids))}"
            if radius - min(radii) > max(float(thick), 0.005):  # not round (a belt round hips and belly): hug the surface (#316)
                rest.pop("hard", None)
                room = 2 * (radius + float(thick) + 0.02)
                box = {"at": at, "size": [room, float(width), room], "rotate": _axis_rotate(axis)}
                return [{**rest, "box": box, "shell": float(thick), "fit": {"to": ids, "gap": 0.0}}], None
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


LIMB_KEYS = {"hand": ("at", "rotate", "length", "width", "fingers", "thumb", "curl", "spread", "knuckles", "nail", "nail_color"),
             "foot": ("at", "rotate", "length", "width", "toes", "curl", "spread", "knuckles", "nail", "nail_color", "heel")}
FOOT_FRAME = np.array([[0.0, 0.0, -1.0], [1.0, 0.0, 0.0], [0.0, -1.0, 0.0]])  # the hand's frame onto a foot's: fingers -y -> +z, palm -x -> -y


def _finger(base: np.ndarray, along: np.ndarray, bend: np.ndarray, length: float, curl: float, joints: int) -> list[np.ndarray]:
    """Points of a finger from `base`: `joints` bones, each turned `curl / joints` more towards `bend` (radians)."""
    pts, here, d = [base], base.copy(), along / np.linalg.norm(along)
    for k in range(joints):
        t = curl * (k + 0.5) / joints
        step = math.cos(t) * along / np.linalg.norm(along) + math.sin(t) * bend
        d = step / np.linalg.norm(step)
        here = here + d * length / joints
        pts.append(here)
    return pts


def _limb_end(kind: str, spec: dict[str, Any], rest: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """A hand or a foot as ordinary soft parts: a palm (sole), fingers (toes) as smooth tapered tubes curled by
    `curl`, a thumb (heel), nails as cones on the tips. Built in the hand's frame (fingers -y, palm -x, thumb +z),
    then turned by `rotate` (and, for a foot, onto the foot's frame first)."""
    foot = kind == "foot"
    help_ = HELP[kind]
    if any(k not in LIMB_KEYS[kind] for k in spec):
        return [], help_
    at, rotate = _vec(_get(spec, "at", rest.pop("at", [0, 0, 0]))), _vec(_get(spec, "rotate", rest.pop("rotate", [0, 0, 0])))
    length = _get(spec, "length", 0.26 if foot else 0.2)
    width = _get(spec, "width", (0.42 if foot else 0.5) * length if _num(length) else None)
    count = _get(spec, "toes" if foot else "fingers", 5 if foot else 4)
    curl, spread = _get(spec, "curl", 10 if foot else 30), _get(spec, "spread", 6 if foot else 8)
    knuckles, nail = _get(spec, "knuckles", 0.04), _get(spec, "nail", 0.0)
    thumb, heel = _get(spec, "thumb", not foot), _get(spec, "heel", foot)
    if at is None or rotate is None or not _num(length) or length <= 0 or not _num(width) or width <= 0 \
            or not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 6 or not _num(curl) or not -90 <= curl <= 270 \
            or not _num(spread) or not 0 <= spread <= 45 or not _num(knuckles) or knuckles < 0 or not _num(nail) or nail < 0 \
            or not isinstance(thumb, bool) or not isinstance(heel, bool):
        return [], help_
    turn = rotation_matrix((rotate[0], rotate[1], rotate[2])) @ (FOOT_FRAME if foot else np.eye(3))
    origin = np.asarray(at, float)

    def place(p: np.ndarray) -> list[float]:
        return [round(float(v), 6) for v in origin + turn @ p]

    down, palm_side, side = np.array([0.0, -1.0, 0.0]), np.array([-1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
    palm_len = (0.62 if foot else 0.48) * length
    thick = (0.36 if foot else 0.45) * width
    radius = min(width / count * 0.5, thick * 0.6)
    if foot:  # the sole stands on `at`
        origin = origin + turn @ (-palm_side * thick / 2)
    out: list[dict[str, Any]] = []
    mid = down * palm_len / 2
    out.append({**rest, "ellipsoid": {"at": place(mid), "radii": [round(thick / 2, 6), round(palm_len / 2 * 1.08, 6), round(width / 2, 6)],
                                      "rotate": [round(float(v), 6) for v in _euler(turn)]}})
    nails: list[dict[str, Any]] = []
    profile = [1.0, 0.86, 0.76, 0.68, 0.6, 0.55] if foot else [0.9, 1.0, 0.94, 0.76, 0.62, 0.55]  # from the thumb side (+z) out
    finger_len = length - palm_len
    for i in range(count):
        f = (i - (count - 1) / 2) / max(count - 1, 1)  # -0.5 .. 0.5 across the palm
        fan = math.radians(spread) * f * 2
        along = math.cos(fan) * down + math.sin(fan) * side
        base = down * palm_len * 0.92 + side * f * (width - 2 * radius) + palm_side * thick * 0.05
        flen = finger_len * profile[count - 1 - i] if count > 1 else finger_len
        pts = _finger(base, along, palm_side, flen, math.radians(curl), 3)
        tube: dict[str, Any] = {"points": [place(p) for p in pts], "radius": round(radius * (1 + float(knuckles) * 2), 6),
                                "radius_to": round(radius * (0.7 if nail else 0.8), 6), "smooth": True}
        out.append({**rest, "tube": tube})
        if nail:
            nails.append(_nail(pts, palm_side, radius * 0.75, float(nail), place, turn))
    if thumb:
        base = down * palm_len * 0.35 + side * width * 0.5 + palm_side * thick * 0.25
        along = down * 0.55 + side * 0.45 + palm_side * 0.5
        pts = _finger(base, along / np.linalg.norm(along), palm_side, finger_len * 0.75, math.radians(curl) * 0.6, 2)
        out.append({**rest, "tube": {"points": [place(p) for p in pts], "radius": round(radius * 1.2, 6), "radius_to": round(radius * 0.85, 6),
                                     "smooth": True}})
        if nail:
            nails.append(_nail(pts, palm_side, radius * 0.85, float(nail), place, turn))
    if heel:  # a rounded heel at the back of the sole, a little behind the ankle
        out.append({**rest, "sphere": {"at": place(np.array([0.0, palm_len * 0.08, 0.0])), "radius": round(thick * 0.55, 6)}})
    for n in nails:
        part = {k: v for k, v in rest.items() if k not in ("color", "material", "blend")}
        if "nail_color" in spec:
            part["color"] = spec["nail_color"]
        elif "color" in rest:
            part["color"] = rest["color"]
        if "material" in rest and "nail_color" not in spec:
            part["material"] = rest["material"]
        part["blend"] = 0.004
        out.append({**part, **n})
    return out, None


def _nail(pts: list[np.ndarray], palm_side: np.ndarray, radius: float, length: float, place: Any, turn: np.ndarray) -> dict[str, Any]:
    """A claw on a finger's tip: a cone from inside the tip along its last bone, curving a little towards the palm."""
    d = pts[-1] - pts[-2]
    d = d / np.linalg.norm(d)
    tip = pts[-1] + d * length * 0.85 + palm_side * length * 0.25
    base = pts[-1] - d * radius * 0.6 - palm_side * radius * 0.35
    return {"cone": {"aim": [place(base), place(tip)], "radius": round(radius, 6)}}


EYE_KEYS = ("at", "facing", "radius", "depth", "rim", "rim_color", "rim_material", "rim_emission", "in")


def _y_onto(d: np.ndarray) -> np.ndarray:
    """The rotation matrix turning +y onto the unit vector `d` (the shortest turn)."""
    y = np.array([0.0, 1.0, 0.0])
    c = float(y @ d)
    if c > 1 - 1e-12:
        return np.eye(3)
    if c < -1 + 1e-12:
        return np.diag([1.0, -1.0, -1.0])
    v = np.cross(y, d)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    out: np.ndarray = np.eye(3) + k + k @ k / (1 + c)
    return out


def _eye(spec: dict[str, Any], rest: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """A recessed eye: a round socket cut into the face (a short cylinder along `facing`), a ball sunk in it whose
    front sits `depth` x radius behind the surface, and a thin rim lining the socket's edge, seated flush (its outer
    half inside the face), so nothing stands proud of the surface."""
    help_ = HELP["eye"]
    if any(k not in EYE_KEYS for k in spec):
        return [], help_
    at = _vec(_get(spec, "at", rest.pop("at", None)))
    facing = _vec(_get(spec, "facing", [0, 0, 1]))
    radius, depth, rim = _get(spec, "radius", 0.03), _get(spec, "depth", 0.4), _get(spec, "rim", 0.15)
    into = _get(spec, "in")
    into = [into] if isinstance(into, str) else into
    if at is None or facing is None or float(np.linalg.norm(facing)) < 1e-9 or not _num(radius) or radius <= 0 \
            or not _num(depth) or not 0 <= depth <= 2 or not _num(rim) or not 0 <= rim <= 0.5 \
            or (into is not None and (not isinstance(into, list) or not into or not all(isinstance(i, str) for i in into))):
        return [], help_
    rest.pop("rotate", None)
    f = np.asarray(facing, float) / float(np.linalg.norm(facing))
    turn = _y_onto(f)
    rot = [round(float(v), 6) for v in _euler(turn)]
    o = np.asarray(at, float)
    r, sunk = float(radius), float(depth) * float(radius)

    def pt(v: np.ndarray) -> list[float]:
        return [round(float(x), 6) for x in v]

    base = {k: v for k, v in rest.items() if k not in ("color", "material", "emission", "id", "blend")}
    out: list[dict[str, Any]] = []
    back = sunk + r * 0.98  # down to the ball's centre, so its front half fills the socket's floor
    height = back + r  # and out past a curved face
    out.append({**base, "cylinder": {"at": pt(o + f * (height / 2 - back)), "radius": round(r, 6), "height": round(height, 6), "rotate": rot},
                "cut": into if into is not None else True, **({"color": rest["color"]} if "color" in rest else {})})  # walls in the ball's colour
    ball = {k: v for k, v in rest.items() if k != "blend"}
    ball["blend"] = "none"
    out.append({**ball, "sphere": {"at": pt(o - f * (sunk + r * 0.98)), "radius": round(r * 0.98, 6)}})
    if rim:
        ring = {**base, "blend": "none"}
        if "rim_color" in spec:
            ring["color"] = spec["rim_color"]
        elif "color" in rest:
            ring["color"] = rest["color"]
        if "rim_material" in spec:
            ring["material"] = spec["rim_material"]
        if "rim_emission" in spec:
            ring["emission"] = spec["rim_emission"]
        t = r * float(rim) / 2
        out.append({**ring, "torus": {"at": pt(o - f * t * 1.2), "radius": round(r, 6), "thickness": round(t, 6), "rotate": rot}})
    return out, None


def _euler(m: np.ndarray) -> list[float]:
    """Euler degrees [x, y, z] for a rotation matrix, as rotation_matrix reads them (Rz @ Ry @ Rx)."""
    y = math.asin(max(-1.0, min(1.0, -float(m[2, 0]))))
    if abs(math.cos(y)) > 1e-9:
        x, z = math.atan2(float(m[2, 1]), float(m[2, 2])), math.atan2(float(m[1, 0]), float(m[0, 0]))
    else:  # gimbal lock: x and z turn about the same axis
        x, z = 0.0, math.atan2(-float(m[0, 1]), float(m[1, 1]))
    return [round(math.degrees(v), 6) for v in (x, y, z)]


__all__ = ["HARDWARE", "expand"]
