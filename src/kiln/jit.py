"""Compiled part distances (optional: `pip install kiln-gen[fast]`, numba). One fused pass per point does what
`Geometry._distance` does with numpy arrays: mirror, copies, rotation, twist, the shape, open side, shell, noise,
and `Field.part_distance`'s box stand-in, without N x 3 temporaries, in parallel over points.

The numpy code stays the reference (and the path for extrudes and fitted shells). The two agree to rounding, not
bit for bit (sums and sines are done in another order), so a project builds identically only on the same path:
pin `kiln-gen[fast]` (or KILN_JIT=0) in a game's requirements. KILN_JIT=0 turns the compiled path off.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from kiln.sdf import Array, Field, Geometry

try:
    if os.environ.get("KILN_JIT", "1") == "0":
        raise ImportError
    from numba import njit, prange

    AVAILABLE = True
except ImportError:  # numpy only
    AVAILABLE = False

SHAPE_IDS = {"sphere": 0, "ellipsoid": 1, "box": 2, "cylinder": 3, "cone": 4, "capsule": 5, "tube": 6, "torus": 7, "wedge": 8, "lathe": 9, "lock": 10}
MIN_POINTS = 64  # fewer points: numpy for one part's distance (the call costs more than it saves)
SERIAL_POINTS = 8192  # a part's distance at fewer points runs on one thread: a parallel call costs ~3 ms however small (#154)
SERIAL_FIELD = 1024  # the same for the whole field (a few us a point, so the pool pays off sooner)
CHUNK = 64  # points per parallel task in the field kernel (each task keeps its own target-union cache)


@dataclass(frozen=True)
class Packed:
    """A part's geometry as flat arrays for the kernel."""

    kind: int
    prm: Array  # shape numbers (layout per shape, see _pack_shape)
    pts: Array  # (M, 3) tube points / lathe profile [r, y, 0]
    aux: Array  # (M,) tube radii per point / lathe: 1 where the edge ending at the point is skipped (on the axis)
    at: Array
    rot: Array  # (3, 3) local -> world (identity if none)
    has_rot: bool
    mirror: Array  # (3,) 1 = folded
    crot: Array  # (C, 3, 3) copies
    cpiv: Array  # (C, 3)
    coff: Array  # (C, 3)
    twist: float  # radians per metre
    open_axis: int  # -1: none
    open_sign: float
    open_plane: float
    shell: float
    shell_in: bool
    noise_amount: float  # 0: none
    noise_dirs: Array  # (3, 2, 3)
    noise_phase: Array  # (3, 2)
    noise_freq: Array  # (3,)
    noise_weight: Array  # (3,)
    noise_total: float
    scale: Array  # (3,) stretch in the part's frame (ones: none)
    has_scale: bool


def set_threads(n: int) -> None:
    """Threads the kernels use in this process (lint's worker processes share the cores)."""
    if AVAILABLE:
        import numba

        numba.set_num_threads(max(1, min(n, int(numba.config.NUMBA_NUM_THREADS))))  # type: ignore[attr-defined]


def supported(g: Geometry) -> bool:
    return AVAILABLE and g.shape in SHAPE_IDS and g.fit is None


def _pack_shape(g: Geometry) -> tuple[Array, Array, Array]:
    s = g.params
    none = np.zeros((1, 3))
    zero = np.zeros(1)
    if g.shape == "sphere":
        return np.array([s["radius"]], float), none, zero
    if g.shape in ("ellipsoid",):
        return np.asarray(s["radii"], float), none, zero
    if g.shape in ("box",):
        return np.array([*s["size"], s["round"]], float), none, zero
    if g.shape == "wedge":
        return np.asarray(s["size"], float), none, zero
    if g.shape == "cylinder":
        return np.array([s["radius"], s["height"], s["round"], s.get("sides") or 0], float), none, zero
    if g.shape == "cone":
        return np.array([s["radius"], s["radius_top"], s["height"], s.get("sides") or 0], float), none, zero
    if g.shape == "capsule":
        return np.array([*s["from"], *s["to"], s["radius"], s["radius_to"]], float), none, zero
    if g.shape == "torus":
        return np.array([s["radius"], s["thickness"], s.get("sides") or 0], float), none, zero
    if g.shape == "tube":
        pts = np.asarray(s["points"], float)
        lengths = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        along = np.concatenate([[0.0], np.cumsum(lengths)]) / max(float(lengths.sum()), 1e-12)
        return np.zeros(1), np.ascontiguousarray(pts), s["radius"] + (s["radius_to"] - s["radius"]) * along
    if g.shape == "lock":  # prm: facing (unit), then the half thickness at every point; aux: the half widths
        from kiln.sdf import lock_profile

        pts, _, half_w, half_t = lock_profile(s)
        facing = np.asarray(s["facing"], float)
        facing = facing / max(float(np.linalg.norm(facing)), 1e-12)
        return np.concatenate([facing, half_t]), np.ascontiguousarray(pts), half_w
    # lathe: the even-odd polygon distance over the profile edges (edge i: point i -> point i-1, as sdf.lathe)
    prof = np.asarray(s["profile"], float)
    on_axis = (prof[:, 0] == 0) & (np.roll(prof[:, 0], 1) == 0)
    pts = np.zeros((len(prof), 3))
    pts[:, :2] = prof
    return np.array([s.get("sides") or 0], float), pts, on_axis.astype(float)


def pack(g: Geometry) -> Packed:
    cached = getattr(g, "_packed", None)
    if cached is not None:
        return cached
    prm, pts, aux = _pack_shape(g)
    mirror = np.zeros(3)
    for axis in g.mirror:
        mirror[axis] = 1.0
    crot = np.stack([c.rotation for c in g.copies]).astype(float)
    cpiv = np.stack([c.pivot for c in g.copies]).astype(float)
    coff = np.stack([c.offset for c in g.copies]).astype(float)
    dirs, phase, freq, weight, total, amount = np.zeros((3, 2, 3)), np.zeros((3, 2)), np.zeros(3), np.zeros(3), 1.0, 0.0
    if g.noise is not None:  # the same stream as sdf.noise
        rng = np.random.default_rng(g.noise.seed)
        total = 0.0
        for octave in range(3):
            dirs[octave] = rng.normal(size=(2, 3))
            phase[octave] = rng.uniform(0.0, 2 * math.pi, size=2)
            freq[octave] = (2.0**octave) / g.noise.scale
            weight[octave] = 1.0 / (1.8**octave)
            total += weight[octave]
        amount = g.noise.amount
    packed = Packed(SHAPE_IDS[g.shape], np.ascontiguousarray(prm, dtype=float), pts, np.ascontiguousarray(aux, dtype=float),
                    np.asarray(g.at, float), np.eye(3) if g.rotation is None else np.ascontiguousarray(g.rotation, dtype=float),
                    g.rotation is not None, mirror, crot, cpiv, coff, math.radians(g.twist) if g.twist else 0.0,
                    -1 if g.open is None else int(g.open[0]), 0.0 if g.open is None else float(g.open[1]),
                    g.open_plane() if g.open is not None else 0.0, float(g.shell), g.shell_side == "in", float(amount),
                    dirs, phase, freq, weight, float(total), np.ones(3) if g.scale is None else np.asarray(g.scale, float),
                    g.scale is not None)  # fmt: skip
    object.__setattr__(g, "_packed", packed)
    return packed


def _table(geoms: list[Geometry]) -> tuple[Any, ...]:
    """Every part's Packed arrays concatenated (offsets per part), as the kernels take them."""
    ks = [pack(g) for g in geoms]

    def offsets(lengths: list[int]) -> Array:
        return np.concatenate([[0], np.cumsum(lengths)]).astype(np.int64)

    return (np.array([k.kind for k in ks], np.int64), np.concatenate([k.prm for k in ks]), offsets([len(k.prm) for k in ks]),
            np.concatenate([k.pts for k in ks]), np.concatenate([k.aux for k in ks]), offsets([len(k.pts) for k in ks]),
            np.stack([k.at for k in ks]), np.stack([k.rot for k in ks]), np.array([k.has_rot for k in ks]), np.stack([k.mirror for k in ks]),
            np.concatenate([k.crot for k in ks]), np.concatenate([k.cpiv for k in ks]), np.concatenate([k.coff for k in ks]),
            offsets([len(k.crot) for k in ks]), np.array([k.twist for k in ks]), np.array([k.open_axis for k in ks], np.int64),
            np.array([k.open_sign for k in ks]), np.array([k.open_plane for k in ks]), np.array([k.shell for k in ks]),
            np.array([k.shell_in for k in ks]), np.array([k.noise_amount for k in ks]), np.stack([k.noise_dirs for k in ks]),
            np.stack([k.noise_phase for k in ks]), np.stack([k.noise_freq for k in ks]), np.stack([k.noise_weight for k in ks]),
            np.array([k.noise_total for k in ks]), np.stack([k.scale for k in ks]), np.array([k.has_scale for k in ks]))  # fmt: skip


def distance(g: Geometry, p: Array, filled: bool = False, box: tuple[Array, Array, float] | None = None) -> Array:
    """The part's signed distance at p (as Geometry.distance); with `box` = (lo, hi, pad), points outside the padded
    box get the box distance + pad instead (as Field.part_distance)."""
    table = getattr(g, "_jit_table", None)
    if table is None:
        table = _table([g])
        object.__setattr__(g, "_jit_table", table)
    out = np.empty(len(p))
    lo, hi, pad = box if box is not None else (np.zeros(3), np.zeros(3), -1.0)
    kernel = _part_serial if len(p) < SERIAL_POINTS else _part_kernel
    kernel(np.ascontiguousarray(p, dtype=float), out, table, filled, np.asarray(lo, float), np.asarray(hi, float), float(pad))
    return out


@dataclass(frozen=True)
class FieldTable:
    table: tuple[Any, ...]  # the compiled parts (ones the kernel can't do get a stand-in, never evaluated)
    op: Array  # (P,) 0 add, 1 cut, 2 intersect
    counts: Array  # (P,) bool: the part takes part in this surface (Field._counts)
    blend: Array
    lo: Array  # (P, 3) boxes
    hi: Array
    pad: Array  # margin + blend (part_distance's stand-in)
    numpy_parts: tuple[int, ...]  # parts the kernel can't do (extrude, fit): their distances are passed in
    target_set: Array  # (P,) blend_to parts: their set of targets (-1: none, or none that count here: a crisp join)
    set_off: Array  # (S + 1,) set s is the parts set_idx[set_off[s]:set_off[s + 1]]
    set_idx: Array
    has_targets: Array  # (P,) bool: blend_to given


def field_table(field: Field) -> FieldTable:
    cached: FieldTable | None = getattr(field, "_jit_table", None)
    if cached is not None:
        return cached
    from kiln.sdf import Geometry

    parts = field.parts
    numpy_parts = tuple(i for i, g in enumerate(parts) if not supported(g))
    sets: dict[tuple[int, ...], int] = {}
    target_set = np.full(len(parts), -1, np.int64)
    for i in range(len(parts)):
        targets = tuple(field._targets(i))
        if targets:
            target_set[i] = sets.setdefault(targets, len(sets))
    members = sorted(sets, key=lambda k: sets[k])
    set_off = np.concatenate([[0], np.cumsum([len(m) for m in members])]).astype(np.int64)
    set_idx = np.array([j for m in members for j in m] or [0], np.int64)
    geoms = [Geometry("sphere", {"radius": 1.0}) if i in numpy_parts else g for i, g in enumerate(parts)]
    out = FieldTable(_table(geoms), np.array([{"add": 0, "cut": 1}.get(g.op, 2) for g in parts], np.int64),
                     np.array([field._counts(i) for i in range(len(parts))], dtype=bool), np.array([g.blend for g in parts], float),
                     np.array([b[0] for b in field.boxes], float).reshape(-1, 3), np.array([b[1] for b in field.boxes], float).reshape(-1, 3),
                     np.array([field.margin + g.blend for g in parts], float), numpy_parts, target_set, set_off, set_idx,
                     np.array([g.blend_to is not None for g in parts], dtype=bool))  # fmt: skip
    object.__setattr__(field, "_jit_table", out)
    return out


def field_distance(field: Field, p: Array) -> Array:
    """Field._distance in one compiled pass per point: the parts in order, each skipped where its box alone shows it
    can't change the result (the rule the numpy batches use, per point)."""
    t = field_table(field)
    p = np.ascontiguousarray(p, dtype=float)
    pre = np.zeros((max(len(t.numpy_parts), 1), len(p)))
    slot = np.full(len(field.parts), -1, np.int64)
    for k, i in enumerate(t.numpy_parts):
        if t.counts[i]:
            pre[k] = field.part_distance(i, p)
        slot[i] = k
    out = np.empty(len(p))
    kernel = _field_serial if len(p) < SERIAL_FIELD else _field_kernel
    kernel(p, out, t.table, t.op, t.counts, t.blend, t.lo, t.hi, t.pad, pre, slot, t.target_set, t.set_off, t.set_idx, t.has_targets)
    return out


def nearest(field: Field, parts: list[int], p: Array, absolute: bool = True) -> tuple[Array, Array]:
    """Field.nearest in one compiled pass (#199): per point, the position in `parts` of the part whose
    part_distance (absolute, unless not) is smallest, ties to the earlier one, and that distance."""
    t = field_table(field)
    p = np.ascontiguousarray(p, dtype=float)
    idx = np.asarray(parts, np.int64)
    numpy_here = [i for i in parts if i in t.numpy_parts]
    pre = np.zeros((max(len(numpy_here), 1), len(p)))
    slot = np.full(len(field.parts), -1, np.int64)
    for k, i in enumerate(numpy_here):
        pre[k] = field.part_distance(i, p)
        slot[i] = k
    which = np.zeros(len(p), np.int64)
    best = np.full(len(p), np.inf)
    kernel = _nearest_serial if len(p) < SERIAL_FIELD else _nearest_kernel
    kernel(p, idx, absolute, t.table, t.lo, t.hi, t.pad, pre, slot, which, best)
    return which, best


if AVAILABLE:  # module-level functions: numba caches them on disk (nested ones it compiles again every run)
    @njit(cache=True, inline="always")
    def radial(x: float, z: float, sides: float) -> float:
        n = int(sides)
        if n == 0:
            return math.sqrt(x * x + z * z)
        best = -math.inf
        for k in range(n):
            a = 2 * math.pi * k / n
            v = x * math.sin(a) + z * math.cos(a)
            if v > best:
                best = v
        return best / math.cos(math.pi / n)

    @njit(cache=True, inline="always")
    def box3(x: float, y: float, z: float, sx: float, sy: float, sz: float, r: float) -> float:
        qx = abs(x) - (sx / 2 - r)
        qy = abs(y) - (sy / 2 - r)
        qz = abs(z) - (sz / 2 - r)
        ox, oy, oz = max(qx, 0.0), max(qy, 0.0), max(qz, 0.0)
        return math.sqrt(ox * ox + oy * oy + oz * oz) + min(max(qx, max(qy, qz)), 0.0) - r

    @njit(cache=True, inline="always")
    def round_extrude(d2: float, y: float, half: float, r: float) -> float:
        w0 = d2 + r
        w1 = abs(y) - half + r
        a, b = max(w0, 0.0), max(w1, 0.0)
        return min(max(w0, w1), 0.0) + math.sqrt(a * a + b * b) - r

    @njit(cache=True, inline="always")
    def segment(x: float, y: float, z: float, ax: float, ay: float, az: float, bx: float, by: float, bz: float, ra: float, rb: float) -> float:
        px, py, pz = x - ax, y - ay, z - az
        ex, ey, ez = bx - ax, by - ay, bz - az
        h = (px * ex + py * ey + pz * ez) / max(ex * ex + ey * ey + ez * ez, 1e-12)
        h = min(max(h, 0.0), 1.0)
        dx, dy, dz = px - h * ex, py - h * ey, pz - h * ez
        return math.sqrt(dx * dx + dy * dy + dz * dz) - (ra + (rb - ra) * h)

    @njit(cache=True)
    def shape(kind: int, x: float, y: float, z: float, prm: Any, pts: Any, aux: Any) -> float:
        if kind == 0:
            return math.sqrt(x * x + y * y + z * z) - prm[0]
        if kind == 1:
            rx, ry, rz = prm[0], prm[1], prm[2]
            k0 = math.sqrt((x / rx) ** 2 + (y / ry) ** 2 + (z / rz) ** 2)
            k1 = math.sqrt((x / (rx * rx)) ** 2 + (y / (ry * ry)) ** 2 + (z / (rz * rz)) ** 2)
            if k1 > 1e-12:
                return k0 * (k0 - 1.0) / k1
            return -min(rx, min(ry, rz))
        if kind == 2:
            return box3(x, y, z, prm[0], prm[1], prm[2], prm[3])
        if kind == 3:
            return round_extrude(radial(x, z, prm[3]) - prm[0], y, prm[1] / 2, prm[2])
        if kind == 4:
            h, r1, r2 = prm[2] / 2, prm[0], prm[1]
            q0, q1 = radial(x, z, prm[3]), y
            k2x, k2y = r2 - r1, 2 * h
            ca0 = q0 - min(q0, r1 if q1 < 0 else r2)
            ca1 = abs(q1) - h
            t = ((r2 - q0) * k2x + (h - q1) * k2y) / (k2x * k2x + k2y * k2y)
            t = min(max(t, 0.0), 1.0)
            cb0 = q0 - r2 + t * k2x
            cb1 = q1 - h + t * k2y
            sign = -1.0 if (cb0 < 0 and ca1 < 0) else 1.0
            return sign * math.sqrt(min(ca0 * ca0 + ca1 * ca1, cb0 * cb0 + cb1 * cb1))
        if kind == 5:
            return segment(x, y, z, prm[0], prm[1], prm[2], prm[3], prm[4], prm[5], prm[6], prm[7])
        if kind == 6:
            d = math.inf
            for i in range(len(pts) - 1):
                d = min(d, segment(x, y, z, pts[i, 0], pts[i, 1], pts[i, 2], pts[i + 1, 0], pts[i + 1, 1], pts[i + 1, 2], aux[i], aux[i + 1]))
            return d
        if kind == 7:
            ring = radial(x, z, prm[2]) - prm[0]
            return math.sqrt(ring * ring + y * y) - prm[1]
        if kind == 8:
            w, hh, dd = prm[0], prm[1], prm[2]
            norm = math.hypot(hh, dd / 2)
            slope = (hh / norm) * abs(z) + (dd / 2 / norm) * (y - hh / 2)
            return max(box3(x, y, z, w, hh, dd, 0.0), slope)
        if kind == 10:  # lock: an elliptical section along the path (sdf.lock)
            fx, fy, fz = prm[0], prm[1], prm[2]
            d = math.inf
            for i in range(len(pts) - 1):
                ex, ey, ez = pts[i + 1, 0] - pts[i, 0], pts[i + 1, 1] - pts[i, 1], pts[i + 1, 2] - pts[i, 2]
                length = math.sqrt(ex * ex + ey * ey + ez * ez)
                if length < 1e-12:
                    continue
                tx, ty, tz = ex / length, ey / length, ez / length
                fd = fx * tx + fy * ty + fz * tz
                vx, vy, vz = fx - fd * tx, fy - fd * ty, fz - fd * tz
                vn = math.sqrt(vx * vx + vy * vy + vz * vz)
                if vn < 1e-6:  # facing along the segment: as sdf.lock_frame
                    ax, ay, az = (1.0, 0.0, 0.0) if abs(tx) < 0.9 else (0.0, 1.0, 0.0)
                    vx, vy, vz = ty * az - tz * ay, tz * ax - tx * az, tx * ay - ty * ax
                    vn = math.sqrt(vx * vx + vy * vy + vz * vz)
                vx, vy, vz = vx / vn, vy / vn, vz / vn
                ux, uy, uz = vy * tz - vz * ty, vz * tx - vx * tz, vx * ty - vy * tx
                wx, wy, wz = x - pts[i, 0], y - pts[i, 1], z - pts[i, 2]
                h = min(max((wx * tx + wy * ty + wz * tz) / length, 0.0), 1.0)
                rx, ry, rz = wx - h * length * tx, wy - h * length * ty, wz - h * length * tz
                rw = aux[i] + (aux[i + 1] - aux[i]) * h
                rt = prm[3 + i] + (prm[4 + i] - prm[3 + i]) * h
                rc = min(rw, rt)
                a, b, c = rx * ux + ry * uy + rz * uz, rx * vx + ry * vy + rz * vz, rx * tx + ry * ty + rz * tz
                k0 = math.sqrt((a / rw) ** 2 + (b / rt) ** 2 + (c / rc) ** 2)
                k1 = math.sqrt((a / (rw * rw)) ** 2 + (b / (rt * rt)) ** 2 + (c / (rc * rc)) ** 2)
                d = min(d, k0 * (k0 - 1.0) / k1 if k1 > 1e-12 else -rc)
            return d
        # lathe: even-odd over the profile, edge i from point i to point i-1
        px, py = max(radial(x, z, prm[0]), 1e-9), y
        m = len(pts)
        d2 = math.inf
        sign = 1.0
        for i in range(m):
            ax, ay = pts[i, 0], pts[i, 1]
            bx, by = pts[i - 1, 0], pts[i - 1, 1]
            ex, ey = bx - ax, by - ay
            wx, wy = px - ax, py - ay
            ee = ex * ex + ey * ey
            if aux[i] == 0.0 and ee > 0:
                t = min(max((wx * ex + wy * ey) / ee, 0.0), 1.0)
                rx, ry = wx - t * ex, wy - t * ey
                d2 = min(d2, rx * rx + ry * ry)
            c1 = py >= ay
            c2 = py < by
            c3 = ex * wy > ey * wx
            if (c1 and c2 and c3) or (not c1 and not c2 and not c3):
                sign = -sign
        if d2 == math.inf:
            d2 = (px - pts[0, 0]) ** 2 + (py - pts[0, 1]) ** 2
        return math.sqrt(d2) * sign

    @njit(cache=True)
    def shelled(d: float, shell: float, shell_in: bool) -> float:
        if shell == 0.0:
            return d
        if shell_in:
            return max(d, -d - shell)
        return abs(d) - shell

    @njit(cache=True)
    def part_at(i: int, x: float, y: float, z: float, filled: bool, t: Any) -> float:
        (kind, prm_all, prm_off, pts_all, aux_all, pts_off, at, rot, has_rot, mirror, crot, cpiv, coff, cop_off, twist, open_axis, open_sign,
         open_plane, shell, shell_in, namount, ndirs, nphase, nfreq, nweight, ntotal, scale, has_scale) = t  # fmt: skip
        prm = prm_all[prm_off[i] : prm_off[i + 1]]
        pts = pts_all[pts_off[i] : pts_off[i + 1]]
        aux = aux_all[pts_off[i] : pts_off[i + 1]]
        if mirror[i, 0] != 0.0:
            x = abs(x)
        if mirror[i, 1] != 0.0:
            y = abs(y)
        if mirror[i, 2] != 0.0:
            z = abs(z)
        sh, s_in, oa = shell[i], shell_in[i], open_axis[i]
        shrink = min(scale[i, 0], min(scale[i, 1], scale[i, 2])) if has_scale[i] else 1.0
        best = math.inf
        for c in range(cop_off[i], cop_off[i + 1]):
            # Copy.to_local: (p - offset - pivot) @ R + pivot, then - at
            ux, uy, uz = x - coff[c, 0] - cpiv[c, 0], y - coff[c, 1] - cpiv[c, 1], z - coff[c, 2] - cpiv[c, 2]
            lx = ux * crot[c, 0, 0] + uy * crot[c, 1, 0] + uz * crot[c, 2, 0] + cpiv[c, 0] - at[i, 0]
            ly = ux * crot[c, 0, 1] + uy * crot[c, 1, 1] + uz * crot[c, 2, 1] + cpiv[c, 1] - at[i, 1]
            lz = ux * crot[c, 0, 2] + uy * crot[c, 1, 2] + uz * crot[c, 2, 2] + cpiv[c, 2] - at[i, 2]
            if has_rot[i]:
                r = rot[i]
                lx, ly, lz = (lx * r[0, 0] + ly * r[1, 0] + lz * r[2, 0], lx * r[0, 1] + ly * r[1, 1] + lz * r[2, 1],
                              lx * r[0, 2] + ly * r[1, 2] + lz * r[2, 2])  # fmt: skip
            if twist[i] != 0.0:
                a = twist[i] * ly
                ca, sa = math.cos(a), math.sin(a)
                lx, lz = ca * lx - sa * lz, sa * lx + ca * lz
            if has_scale[i]:
                lx, ly, lz = lx / scale[i, 0], ly / scale[i, 1], lz / scale[i, 2]
            d = shape(kind[i], lx, ly, lz, prm, pts, aux)
            if has_scale[i]:
                d = d * shrink
            if oa >= 0:
                if not filled:
                    d = shelled(d, sh, s_in)
                coord = lx if oa == 0 else (ly if oa == 1 else lz)
                d = max(d, open_sign[i] * (coord - open_plane[i]) * shrink)
            best = min(best, d)
        if sh != 0.0 and oa < 0 and not filled:
            best = shelled(best, sh, s_in)
        if namount[i] != 0.0:
            acc = 0.0
            for o in range(3):
                s0 = (x * ndirs[i, o, 0, 0] + y * ndirs[i, o, 0, 1] + z * ndirs[i, o, 0, 2]) * nfreq[i, o] + nphase[i, o, 0]
                s1 = (x * ndirs[i, o, 1, 0] + y * ndirs[i, o, 1, 1] + z * ndirs[i, o, 1, 2]) * nfreq[i, o] + nphase[i, o, 1]
                acc += nweight[i, o] * math.sin(s0) * math.sin(s1)
            best = best + namount[i] * (acc / ntotal[i])
        return best

    @njit(cache=True, inline="always")
    def smin(a: float, b: float, k: float) -> float:
        if k <= 0:
            return min(a, b)
        h = min(max(0.5 + 0.5 * (b - a) / k, 0.0), 1.0)
        return b * (1 - h) + a * h - k * h * (1 - h)

    @njit(cache=True, inline="always")
    def part_point(n: int, p: Any, t: Any, filled: bool, lo: Any, hi: Any, pad: float) -> float:
        x, y, z = p[n, 0], p[n, 1], p[n, 2]
        if pad >= 0.0:  # Field.part_distance's stand-in far from the part's box
            qx, qy, qz = max(lo[0] - x, x - hi[0]), max(lo[1] - y, y - hi[1]), max(lo[2] - z, z - hi[2])
            if qx > pad or qy > pad or qz > pad:
                ox, oy, oz = max(qx, 0.0), max(qy, 0.0), max(qz, 0.0)
                return math.sqrt(ox * ox + oy * oy + oz * oz) + pad
        return part_at(0, x, y, z, filled, t)

    @njit(cache=True, parallel=True)
    def part_kernel(p: Any, out: Any, t: Any, filled: bool, lo: Any, hi: Any, pad: float) -> None:
        for n in prange(len(p)):
            out[n] = part_point(n, p, t, filled, lo, hi, pad)

    @njit(cache=True)
    def part_serial(p: Any, out: Any, t: Any, filled: bool, lo: Any, hi: Any, pad: float) -> None:
        for n in range(len(p)):
            out[n] = part_point(n, p, t, filled, lo, hi, pad)

    @njit(cache=True, inline="always")
    def stood_in(i: int, n: int, x: float, y: float, z: float, t: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any) -> float:
        """Field.part_distance at one point: passed in (numpy parts), the box stand-in far away, else the part."""
        if slot[i] >= 0:
            return pre[slot[i], n]
        qx, qy, qz = max(lo[i, 0] - x, x - hi[i, 0]), max(lo[i, 1] - y, y - hi[i, 1]), max(lo[i, 2] - z, z - hi[i, 2])
        if qx > pad[i] or qy > pad[i] or qz > pad[i]:
            ox, oy, oz = max(qx, 0.0), max(qy, 0.0), max(qz, 0.0)
            return math.sqrt(ox * ox + oy * oy + oz * oz) + pad[i]
        return part_at(i, x, y, z, False, t)

    @njit(cache=True, inline="always")
    def target_distance(s: int, n: int, x: float, y: float, z: float, t: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any,
                        set_off: Any, set_idx: Any, cache: Any, stamp: Any) -> float:  # fmt: skip
        """The union of target set s at the point (crisp), worked out once per point (stamp[s] == n: cached)."""
        if stamp[s] == n:
            return cache[s]
        best = math.inf
        for m in range(set_off[s], set_off[s + 1]):
            best = min(best, stood_in(set_idx[m], n, x, y, z, t, lo, hi, pad, pre, slot))
        cache[s] = best
        stamp[s] = n
        return best

    @njit(cache=True, parallel=True)
    def field_kernel(p: Any, out: Any, t: Any, op: Any, counts: Any, blend: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any,
                     target_set: Any, set_off: Any, set_idx: Any, has_targets: Any) -> None:  # fmt: skip
        n_sets = max(len(set_off) - 1, 1)
        chunks = (len(p) + CHUNK - 1) // CHUNK
        for c in prange(chunks):  # the target-union cache is per chunk of points (one allocation, not one per point)
            cache = np.empty(n_sets)
            stamp = np.full(n_sets, -1, np.int64)
            for n in range(c * CHUNK, min((c + 1) * CHUNK, len(p))):
                out[n] = field_point(n, p, t, op, counts, blend, lo, hi, pad, pre, slot, target_set, set_off, set_idx, has_targets, cache, stamp)

    @njit(cache=True)
    def field_serial(p: Any, out: Any, t: Any, op: Any, counts: Any, blend: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any,
                     target_set: Any, set_off: Any, set_idx: Any, has_targets: Any) -> None:  # fmt: skip
        n_sets = max(len(set_off) - 1, 1)
        cache = np.empty(n_sets)
        stamp = np.full(n_sets, -1, np.int64)
        for n in range(len(p)):
            out[n] = field_point(n, p, t, op, counts, blend, lo, hi, pad, pre, slot, target_set, set_off, set_idx, has_targets, cache, stamp)

    @njit(cache=True, inline="always")
    def field_point(n: int, p: Any, t: Any, op: Any, counts: Any, blend: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any,
                    target_set: Any, set_off: Any, set_idx: Any, has_targets: Any, cache: Any, stamp: Any) -> float:  # fmt: skip
        x, y, z = p[n, 0], p[n, 1], p[n, 2]
        f = 1e9
        for i in range(len(op)):
            if not counts[i]:
                continue
            qx, qy, qz = max(lo[i, 0] - x, x - hi[i, 0]), max(lo[i, 1] - y, y - hi[i, 1]), max(lo[i, 2] - z, z - hi[i, 2])
            ox, oy, oz = max(qx, 0.0), max(qy, 0.0), max(qz, 0.0)
            box = math.sqrt(ox * ox + oy * oy + oz * oz)
            k = blend[i]
            blended = target_set[i] >= 0
            if op[i] != 2:  # out of reach: the part can't change f here (its distance is at least its box's)
                gap = box - 1e-6
                if gap > 0 and gap >= (f if op[i] == 0 else -f) + k:
                    # a blend_to part too: it joins as min(f, smin(max(t, f), d, k)), and with d >= gap >= f + k
                    # that is f whatever its targets' union t is (smin grows with both, smin(f, d, k) = f), #220
                    continue
            if slot[i] >= 0:
                d = pre[slot[i], n]
            elif qx > pad[i] or qy > pad[i] or qz > pad[i]:
                d = box + pad[i]
            else:
                d = part_at(i, x, y, z, False, t)
            if op[i] == 1:
                f = -smin(-f, d, k)
            elif op[i] == 2:
                f = -smin(-f, -d, k)
            elif has_targets[i]:  # blend_to: melts into its targets only; a crisp join with the rest
                if blended:
                    tt = target_distance(target_set[i], n, x, y, z, t, lo, hi, pad, pre, slot, set_off, set_idx, cache, stamp)
                    f = min(f, smin(max(tt, f), d, k))
                else:
                    f = min(f, d)
            else:
                f = smin(f, d, k)
        return f

    @njit(cache=True, inline="always")
    def nearest_point(n: int, p: Any, idx: Any, absolute: bool, t: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any, which: Any,
                      best: Any) -> None:  # fmt: skip
        x, y, z = p[n, 0], p[n, 1], p[n, 2]
        for k in range(len(idx)):
            d = stood_in(idx[k], n, x, y, z, t, lo, hi, pad, pre, slot)
            if absolute:
                d = abs(d)
            if d < best[n]:  # ties: the earlier part (as argmin)
                best[n] = d
                which[n] = k

    @njit(cache=True, parallel=True)
    def nearest_kernel(p: Any, idx: Any, absolute: bool, t: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any, which: Any,
                       best: Any) -> None:  # fmt: skip
        for n in prange(len(p)):
            nearest_point(n, p, idx, absolute, t, lo, hi, pad, pre, slot, which, best)

    @njit(cache=True)
    def nearest_serial(p: Any, idx: Any, absolute: bool, t: Any, lo: Any, hi: Any, pad: Any, pre: Any, slot: Any, which: Any,
                       best: Any) -> None:  # fmt: skip
        for n in range(len(p)):
            nearest_point(n, p, idx, absolute, t, lo, hi, pad, pre, slot, which, best)

    _part_kernel: Any = part_kernel
    _nearest_kernel: Any = nearest_kernel
    _nearest_serial: Any = nearest_serial
    _part_serial: Any = part_serial
    _field_serial: Any = field_serial
    _field_kernel: Any = field_kernel

__all__ = ["AVAILABLE", "MIN_POINTS", "SHAPE_IDS", "distance", "field_distance", "field_table", "nearest", "pack", "set_threads", "supported"]
