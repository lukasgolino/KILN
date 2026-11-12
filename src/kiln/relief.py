"""Relief layers (#229): shallow overlapping patches (fur) lying on a model's surface, in its baked maps only.

A `relief:` entry scatters patches over the faces of the parts it names. Each patch is a small flat tile in the
surface: its root at the scattered point, running `length` along the flow, `width` across, rising from 0 at the root
to `lift` at a notched tip. The layer is a height over the surface (the highest patch at each point, so patches
overlap like roof tiles) that tilts the normal map, and a colour: the patch's own ramp, lighter toward the tip, with a
darker band on the surface just under each tip. Nothing is added to the mesh.

Everything is evaluated at 3D points (the bake's texel centres), so UV seams don't show.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from kiln.sdf import Array

if TYPE_CHECKING:
    from kiln.notation import Relief

NOTCH = 0.35  # how far (in patch lengths) the notches between a patch's tips cut back from its tip line
ROUND = 0.25  # the outer tips are this much shorter than the middle one (a rounded lower edge)
EDGE = 0.06  # patch lengths over which the height falls from the tip to the surface under it (not a vertical cliff)
SIDE = 0.15  # half widths over which the height falls off at a patch's sides
SHADOW = 0.3  # patch lengths the darker band reaches below a tip
TIP_LIGHT = 0.08  # how much lighter a patch is at its tip than at its root
COVER = 0.6  # the share of its length x width box a patch covers (notches, rounded tip): density 1 just covers the surface
SPACING = 0.7  # scattered roots are at least this x sqrt(a patch's share of the surface) apart
CANDIDATES = 6  # scatter: points tried per patch wanted
SHRINK = 0.5  # a patch at the very edge of its region is this size (`fade`)
FACING = 0.2  # a patch shows only where the surface faces its own way (dot of the normals): not on the far side of a thin limb
KINDS = ("fur", "scales", "feathers", "shingles")  # a patch's outline: notched tips, a round lobe, one point and a rib, a straight edge
ANGLE = 25.0  # degrees a patch's flow turns either way at jitter 1
FLOW_FLAT = 0.1  # the flow's length in the surface under which no patch is kept (it faces the flow: no way to point)
FLOW_LIES = 0.35  # ... and over which patches are whole (the surface within ~20 degrees of facing the flow: a fade)
FLOWS = {"down": (0.0, -1.0, 0.0), "up": (0.0, 1.0, 0.0)}
MAX_PATCHES = 60_000  # per model: each patch is one pass over the texels near it (20 000 take about 15 s)


@dataclass
class Patches:
    """The patches of every relief entry of a model, in order."""

    centre: Array  # (N, 3) roots
    normal: Array  # (N, 3) the surface normal at the root
    flow: Array  # (N, 3) unit, in the surface: root -> tip
    side: Array  # (N, 3) unit, in the surface: across
    length: Array  # (N,)
    half: Array  # (N,) half the width
    lift: Array  # (N,)
    tips: Array  # (N,) notched tips per patch
    under: Array  # (N,) 0..1 darkening below the tip
    entry: Array  # (N,) which relief entry (index)
    colors: list[tuple[str | None, str | None]] = field(default_factory=list)  # per entry: (colour, tip colour) hex, None: the surface's
    kinds: list[int] = field(default_factory=list)  # per entry: KINDS index (fur, scales, feathers, shingles); none: fur

    def select(self, keep: Array) -> Patches:
        """The patches where `keep` (N,) is true, the per-entry lists as they are."""
        return Patches(self.centre[keep], self.normal[keep], self.flow[keep], self.side[keep], self.length[keep], self.half[keep],
                       self.lift[keep], self.tips[keep], self.under[keep], self.entry[keep], self.colors, self.kinds)  # fmt: skip

    def __len__(self) -> int:
        return len(self.centre)

    @property
    def reach(self) -> float:
        """No patch touches a point further than this from its root."""
        return self.reach_of(np.arange(len(self)))

    def reach_of(self, which: Array) -> float:
        """... for the patches at these indices."""
        if not len(which):
            return 0.0
        return float(np.sqrt((self.length[which] * (1 + SHADOW)) ** 2 + self.half[which] ** 2).max())

    def touches(self, points: Array) -> Array:
        """Whether each point is near enough to some patch to be under it (by grid cell: a quick, generous test)."""
        from kiln.fade import near_cells

        return near_cells(points, self.centre, self.reach) if len(self) else np.zeros(len(points), dtype=bool)


@dataclass
class Stamp:
    """The layer at some points."""

    height: Array  # (M,) metres over the surface
    shade: Array  # (M,) 0..1 colour multiplier (the band under tips)
    entry: Array  # (M,) the relief entry of the patch on top, -1: bare surface
    along: Array  # (M,) 0 at that patch's root .. 1 at its tip


def scatter(vertices: Array, faces: Array, normals: Array, face_on: list[Array], entries: list[Relief], face_axis: Array | None = None) -> Patches:
    """Patches for every entry: `face_on[k]` marks the faces entry k covers; `normals` are per face corner (F, 3, 3).
    Roots are scattered evenly (a point is kept when no kept root is nearer than the spacing), from a generator
    seeded by the entry, so a model builds the same patches everywhere."""
    parts: list[list[Array]] = [[] for _ in range(10)]
    colors: list[tuple[str | None, str | None]] = []
    kinds: list[int] = []
    asked = 0
    covered = np.any(np.stack(face_on), axis=0) if face_on else np.zeros(len(faces), dtype=bool)  # every layer's faces
    for k, (on, r) in enumerate(zip(face_on, entries, strict=True)):
        colors.append((r.color, r.color_to))
        kinds.append(KINDS.index(r.kind) if r.kind in KINDS else 0)
        idx = np.flatnonzero(on)
        if not len(idx):
            continue
        rng = np.random.RandomState(r.seed)
        tri = vertices[faces[idx]]
        area = 0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        total = float(area.sum())
        each = COVER * r.length * r.width / r.density  # surface per patch
        want = max(1, round(total / each))
        asked += want
        if asked > MAX_PATCHES:
            raise ValueError(f"relief: {asked} patches or more (at most {MAX_PATCHES}): make the patches longer or wider, or lower the density")
        pick = np.searchsorted(np.cumsum(area) / total, rng.random_sample(want * CANDIDATES)).clip(0, len(idx) - 1)
        a, b = rng.random_sample(len(pick)), rng.random_sample(len(pick))
        flip = a + b > 1
        a, b = np.where(flip, 1 - a, a), np.where(flip, 1 - b, b)
        bary = np.stack([1 - a - b, a, b], axis=1)
        points = (tri[pick] * bary[:, :, None]).sum(axis=1)
        normal = (normals[idx[pick]] * bary[:, :, None]).sum(axis=1)
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        size = 1 + r.jitter * (rng.random_sample(len(pick)) - 0.5)
        turn = np.radians(ANGLE) * r.jitter * (rng.random_sample(len(pick)) * 2 - 1)
        chance = rng.random_sample(len(pick))
        # the fade runs toward where the fur ends, not toward a neighbouring layer's faces (an upper arm's layer meeting
        # the forearm's left a bare band at the elbow, #302)
        edge = _edge_distance(vertices, faces, covered, points) if r.fade > 0 else np.full(len(pick), np.inf)
        full = np.clip(edge / r.fade, 0.0, 1.0) if r.fade > 0 else np.ones(len(pick))
        # where the surface faces along the flow (a shoulder's top under flow: down) the flow barely lies in it: its
        # direction swings or falls back to one fixed axis, a stepped streak of patches all pointing one way; there the
        # patches thin out and shrink as they do toward an edge (#303)
        if r.flow == "along" and face_axis is not None:  # each face's own part's axis, out from the body (#261)
            wanted = face_axis[idx[pick]]
            wanted = np.where((np.linalg.norm(wanted, axis=1) > 1e-9)[:, None], wanted, np.asarray(FLOWS["down"], dtype=float))
        else:
            wanted = np.tile(np.asarray(FLOWS.get(r.flow, FLOWS["down"]) if isinstance(r.flow, str) else r.flow, dtype=float), (len(pick), 1))
        wanted = wanted / np.linalg.norm(wanted, axis=1, keepdims=True)
        lying = np.linalg.norm(wanted - normal * (normal * wanted).sum(axis=1)[:, None], axis=1)
        full = full * np.clip((lying - FLOW_FLAT) / (FLOW_LIES - FLOW_FLAT), 0.0, 1.0)
        keep = _spaced(points, SPACING * float(np.sqrt(each)), want, chance <= full)
        points, normal, size, turn, full = points[keep], normal[keep], size[keep], turn[keep], full[keep]
        size = size * (SHRINK + (1 - SHRINK) * full)
        wanted = wanted[keep]
        flow = wanted - normal * (normal * wanted).sum(axis=1)[:, None]
        flat = np.linalg.norm(flow, axis=1) < 1e-3  # the surface faces along the flow (a crown): any direction in it
        spare = np.cross(normal, np.where(np.abs(normal[:, :1]) < 0.9, [[1.0, 0.0, 0.0]], [[0.0, 0.0, 1.0]]))
        flow = np.where(flat[:, None], spare, flow)
        flow /= np.linalg.norm(flow, axis=1, keepdims=True)
        side = np.cross(normal, flow)
        flow, side = (flow * np.cos(turn)[:, None] + side * np.sin(turn)[:, None],
                      side * np.cos(turn)[:, None] - flow * np.sin(turn)[:, None])  # fmt: skip
        n = len(points)
        for store, value in zip(parts, (points, normal, flow, side, r.length * size, 0.5 * r.width * size, np.full(n, r.lift) * size,
                                        np.full(n, r.tips), np.full(n, r.under), np.full(n, k)), strict=True):  # fmt: skip
            store.append(value)
    if not parts[0]:
        zero, none = np.zeros((0, 3)), np.zeros(0)
        return Patches(zero, zero, zero, zero, none, none, none, none.astype(np.int64), none, none.astype(np.int64), colors, kinds)
    c = [np.concatenate(p) for p in parts]
    return Patches(c[0], c[1], c[2], c[3], c[4], c[5], c[6], c[7].astype(np.int64), c[8], c[9].astype(np.int64), colors, kinds)


def _edge_distance(vertices: Array, faces: Array, on: Array, points: Array) -> Array:
    """How far each point is from the edge of the covered faces (the vertices they share with other faces)."""
    inside = np.zeros(len(vertices), dtype=bool)
    outside = np.zeros(len(vertices), dtype=bool)
    inside[faces[on].reshape(-1)] = True
    outside[faces[~on].reshape(-1)] = True
    border = vertices[inside & outside]
    out = np.full(len(points), np.inf)
    if not len(border):
        return out
    for s in range(0, len(points), 2048):
        d = points[s : s + 2048, None, :] - border[None, :, :]
        out[s : s + 2048] = np.sqrt((d * d).sum(axis=2).min(axis=1))
    return out


def _spaced(points: Array, spacing: float, want: int, allowed: Array) -> Array:
    """Indices of up to `want` points, in order, none nearer than `spacing` to one kept before it."""
    cell = np.floor(points / spacing).astype(np.int64)
    grid: dict[tuple[int, int, int], list[int]] = {}
    kept: list[int] = []
    near = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)]
    limit = spacing * spacing
    for i in np.flatnonzero(allowed):
        if len(kept) >= want:
            break
        cx, cy, cz = (int(v) for v in cell[i])
        p = points[i]
        clear = True
        for dx, dy, dz in near:
            for j in grid.get((cx + dx, cy + dy, cz + dz), ()):
                d = points[j] - p
                if float(d @ d) < limit:
                    clear = False
                    break
            if not clear:
                break
        if clear:
            kept.append(int(i))
            grid.setdefault((cx, cy, cz), []).append(int(i))
    return np.asarray(kept, dtype=np.int64)


class Index:
    """Points in a grid, to find the ones near each patch."""

    def __init__(self, points: Array, cell: float) -> None:
        self.cell = max(cell, 1e-6)
        ijk = np.floor(points / self.cell).astype(np.int64)
        self.low = ijk.min(axis=0) - 1 if len(points) else np.zeros(3, dtype=np.int64)
        self.dims = (ijk.max(axis=0) - self.low + 2) if len(points) else np.ones(3, dtype=np.int64)
        key = self._key(ijk)
        self.order = np.argsort(key, kind="stable")
        self.keys = key[self.order]

    def _key(self, ijk: Array) -> Array:
        rel = ijk - self.low
        return np.asarray((rel[..., 0] * self.dims[1] + rel[..., 1]) * self.dims[2] + rel[..., 2])

    def near(self, centre: Array) -> Array:
        """Indices of the points in the 27 cells around a centre."""
        base = np.floor(centre / self.cell).astype(np.int64)
        shifts = np.stack(np.meshgrid([-1, 0, 1], [-1, 0, 1], [-1, 0, 1], indexing="ij"), axis=-1).reshape(-1, 3)
        cells = base + shifts
        ok = ((cells >= self.low) & (cells < self.low + self.dims)).all(axis=1)
        keys = self._key(cells[ok])
        lo = np.searchsorted(self.keys, keys, side="left")
        hi = np.searchsorted(self.keys, keys, side="right")
        spans = [self.order[a:b] for a, b in zip(lo, hi, strict=True) if b > a]
        return np.concatenate(spans) if spans else np.zeros(0, dtype=np.int64)


def stamp(patches: Patches, points: Array, normals: Array, offsets: Array | None = None, allowed: Array | None = None) -> tuple[Stamp, Array]:
    """The layer at `points` (M, 3) on a surface with unit `normals` there, and its height at each of the points
    moved by `offsets` (K, M, 3) (for slopes; small against a patch): (K, M). `allowed` (entries, M): the points each
    entry's patches may touch (the faces of the parts it is `on`); default: all."""
    m = len(points)
    height = np.zeros(m)
    shade = np.zeros(m)
    entry = np.full(m, -1, dtype=np.int64)
    along = np.zeros(m)
    moved = np.zeros((0 if offsets is None else len(offsets), m))
    if not len(patches) or not m:
        return Stamp(height, 1.0 - shade, entry, along), moved
    reach, index, last, mine = 0.0, None, -1, np.zeros(0, dtype=np.int64)
    for i in np.argsort(patches.entry, kind="stable"):  # entry by entry: each with its own reach, over its own points
        k = int(patches.entry[i])
        if index is None or k != last:
            last = k
            mine = np.flatnonzero(allowed[k]) if allowed is not None else np.arange(m)
            reach = patches.reach_of(np.flatnonzero(patches.entry == k))
            index = Index(points[mine], reach)
        near = mine[index.near(patches.centre[i])]
        if not len(near):
            continue
        d = points[near] - patches.centre[i]
        near = near[((d * d).sum(axis=1) < reach * reach) & (normals[near] @ patches.normal[i] > FACING)]
        if not len(near):
            continue
        d = points[near] - patches.centre[i]
        h, tip, u, inside = _profile(patches, i, d)
        dark = np.where(inside & (u > tip) & (h < 0.6 * patches.lift[i]), np.clip(1 - (u - tip) / SHADOW, 0, 1) ** 2 * patches.under[i], 0.0)
        shade[near] = np.maximum(shade[near], dark)
        top = h > height[near]
        height[near[top]] = h[top]
        entry[near[top]] = patches.entry[i]
        along[near[top]] = np.clip(u[top] / np.maximum(tip[top], 1e-6), 0, 1)
        for k in range(len(moved)):
            assert offsets is not None
            hk = _profile(patches, i, d + offsets[k][near])[0]
            moved[k][near] = np.maximum(moved[k][near], hk)
    shade = np.where(height > 0, shade * np.clip(1 - height / np.maximum(patches.lift.max(), 1e-9), 0, 1), shade)
    return Stamp(height, 1.0 - shade, entry, along), moved


def _profile(patches: Patches, i: int, d: Array) -> tuple[Array, Array, Array, Array]:
    """One patch at offsets `d` from its root: (height, the tip line's place along the patch there, place along the
    patch in lengths, whether the point is within the patch's width)."""
    u = d @ patches.flow[i] / patches.length[i]
    v = d @ patches.side[i] / patches.half[i]
    inside = np.abs(v) <= 1
    kind = patches.kinds[int(patches.entry[i])] if patches.kinds else 0
    w = np.clip(np.abs(v), 0, 1)
    if kind == 1:  # scales: one round lobe
        tip = np.sqrt(np.clip(1 - w * w, 0, 1))
    elif kind == 2:  # feathers: one point down the middle
        tip = np.sqrt(np.clip(1 - w, 0, 1))
    elif kind == 3:  # shingles: a straight lower edge, the corners just rounded
        tip = 1 - 0.15 * w**6
    else:  # fur: notched, pointed tips
        phase = (np.clip(v, -1, 1) + 1) * 0.5 * patches.tips[i]
        tooth = 1 - np.abs(2 * (phase - np.floor(phase)) - 1)  # 1 at the middle of each tip, 0 in the notches
        tip = (1 - NOTCH * (1 - tooth)) * (1 - ROUND * v * v)
    rise = np.clip(u / np.maximum(tip, 1e-6), 0, 1) ** 1.5
    fall = np.clip((tip - u) / EDGE, 0, 1) * np.clip((1 - np.abs(v)) / SIDE, 0, 1)
    h = np.where(inside & (u > 0), patches.lift[i] * rise * fall, 0.0)
    if kind == 2:  # a feather's rib: the middle stands highest
        h = h * (0.7 + 0.3 * (1 - w))
    return h, tip, u, inside


def colour(stamped: Stamp, base: Array, colors: list[tuple[str | None, str | None]]) -> Array:
    """Linear RGB (M, 3) of the layer over the surface colours `base` (M, 3, linear): each patch its entry's ramp
    (root colour to tip colour) or the surface's own colour, a little lighter toward the tip; darker under tips."""
    from kiln.export import srgb_to_linear

    out = base.copy()
    for k, (root, tip) in enumerate(colors):
        mine = stamped.entry == k
        if not mine.any():
            continue
        t = stamped.along[mine][:, None]
        if root is not None:
            a = np.array(srgb_to_linear(root))
            b = np.array(srgb_to_linear(tip)) if tip is not None else a
            out[mine] = a * (1 - t) + b * t
        out[mine] = out[mine] * (1 + TIP_LIGHT * (t - 0.5))
    return np.asarray(np.clip(out * stamped.shade[:, None], 0.0, 1.0))


__all__ = ["Index", "Patches", "Stamp", "colour", "scatter", "stamp"]
