"""Paint: which part (colour, material, bone) every triangle belongs to, with clean borders.

Triangles that straddle a border are cut along it: for two parts the border is where their distances are
equal, for a pattern where its function crosses zero, for a decal along its rectangle. Cutting (instead of
colouring whole triangles or vertices) keeps every colour border a straight-edged line on the surface, however
coarse the mesh.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, replace

import numpy as np

from kiln.mesher import Mesh
from kiln.notation import Decal, Model, Part, Pattern
from kiln.sdf import Array, Field, Geometry
from kiln.usage import Progress

ScalarFn = Callable[[Array], Array]


def split(vertices: Array, faces: Array, values: Array, selected: Array) -> tuple[Array, Array, Array, Array]:
    """Cut the selected faces along the zero line of `values` (one per vertex, linear along edges).

    Returns (vertices, faces, negative, parent): `negative` marks faces on the < 0 side, `parent` maps every
    output face to its input face. New vertices are shared between neighbouring faces, and a face that isn't
    selected but shares a cut edge is split at the new point too (same side, no T-junction): no cracks. A vertex
    exactly on the line (value 0) is a point of the cut itself: faces only touching the line aren't cut. A NaN value
    is on neither side: callers leave the vertices of unselected faces NaN, so `negative` holds only for the
    selected faces (faces with a NaN corner are never cut)."""
    neg_v = values < 0
    n_neg = neg_v[faces].sum(axis=1)
    has_pos = (values > 0)[faces].any(axis=1)
    whole_neg = (n_neg > 0) & ~has_pos  # every vertex < 0 or on the line
    cut = selected & (n_neg > 0) & has_pos
    idx = np.flatnonzero(cut)
    if not len(idx):
        return vertices, faces, whole_neg, np.arange(len(faces))
    f = faces[idx]
    fn = neg_v[f]
    lone_is_neg = n_neg[idx] == 1
    lone = np.where(lone_is_neg, fn.argmax(axis=1), fn.argmin(axis=1))
    rows = np.arange(len(f))
    t0, t1, t2 = f[rows, lone], f[rows, (lone + 1) % 3], f[rows, (lone + 2) % 3]
    edges = np.concatenate([np.stack([t0, t1], axis=1), np.stack([t0, t2], axis=1)])
    keys = np.sort(edges, axis=1)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    a, b = unique[:, 0], unique[:, 1]
    va, vb = values[a], values[b]
    t = np.clip(va / np.where(va == vb, 1.0, va - vb), 0.0, 1.0)
    on_line = (va == 0) | (vb == 0)  # the cut passes through an end: that vertex, no new point
    at_end = np.where(va == 0, a, b)
    real = np.flatnonzero(~on_line)
    new_points = (vertices[a] + (vertices[b] - vertices[a]) * t[:, None])[real]
    base = len(vertices)
    point_of = np.where(on_line, at_end, 0)
    point_of[real] = base + np.arange(len(real))
    inverse = inverse.reshape(-1)
    m01 = point_of[inverse[: len(f)]]
    m02 = point_of[inverse[len(f) :]]
    # faces left whole but sharing a cut edge: split at the new point (their side doesn't change)
    rest = np.flatnonzero(~cut)
    lookup = {(int(unique[i, 0]), int(unique[i, 1])): base + k for k, i in enumerate(real)}
    out_faces: list[Array] = []
    out_neg: list[Array] = []
    out_parent: list[Array] = []
    whole: Array = rest
    if lookup:
        # only faces with two corners on cut edges can share one (the mesh may be far bigger than the cut, #123)
        ends = np.zeros(len(vertices), dtype=bool)
        ends[a[real]] = ends[b[real]] = True
        near = np.flatnonzero(ends[faces[rest]].sum(axis=1) >= 2)
        fr = faces[rest]
        ek = np.sort(np.stack([fr[near][:, [0, 1]], fr[near][:, [1, 2]], fr[near][:, [2, 0]]], axis=1), axis=2)  # (N, 3, 2)
        flat = ek.reshape(-1, 2)
        # only edges that were cut can match: test cheaply first
        cand = np.isin(flat[:, 0], a[real]) & np.isin(flat[:, 1], b[real])
        mid_flat = np.full(len(flat), -1)
        for k in np.flatnonzero(cand):
            mid_flat[k] = lookup.get((int(flat[k, 0]), int(flat[k, 1])), -1)
        mid = np.full((len(rest), 3), -1)
        mid[near] = mid_flat.reshape(-1, 3)
        touched = (mid >= 0).any(axis=1)
        whole = rest[~touched]
        for r in np.flatnonzero(touched):
            tri = [int(x) for x in fr[r]]
            ring: list[int] = []
            for e in range(3):
                ring.append(tri[e])
                if mid[r, e] >= 0:
                    ring.append(int(mid[r, e]))
            # fan from a corner whose own edges weren't split (exists for 1 or 2 splits; 3: from a new point)
            start = next((j for j in range(len(ring)) if ring[j] in tri and ring[j - 1] in tri), None)
            if start is None:
                start = next(j for j in range(len(ring)) if ring[j] not in tri)
            ring = ring[start:] + ring[:start]
            for j in range(1, len(ring) - 1):
                out_faces.append(np.array([[ring[0], ring[j], ring[j + 1]]]))
                out_neg.append(np.array([whole_neg[rest[r]]]))
                out_parent.append(np.array([rest[r]]))
    out_faces = [faces[whole]] + out_faces
    out_neg = [whole_neg[whole]] + out_neg
    out_parent = [np.asarray(whole, dtype=np.int64)] + out_parent
    out_faces += [np.stack([t0, m01, m02], axis=1), np.stack([m01, t1, t2], axis=1), np.stack([m01, t2, m02], axis=1)]
    out_neg += [lone_is_neg, ~lone_is_neg, ~lone_is_neg]
    out_parent += [idx, idx, idx]
    faces_out, neg_out, parent_out = np.concatenate(out_faces), np.concatenate(out_neg), np.concatenate(out_parent)
    keep = (faces_out[:, 0] != faces_out[:, 1]) & (faces_out[:, 1] != faces_out[:, 2]) & (faces_out[:, 2] != faces_out[:, 0])
    return np.concatenate([vertices, new_points]), faces_out[keep], neg_out[keep], parent_out[keep]


def refine(vertices: Array, faces: Array, selected: Array, max_edge: float, project: Callable[[Array], Array]) -> tuple[Array, Array, Array]:
    """Split every edge of the selected faces that is longer than `max_edge` at its midpoint (moved onto the
    surface by `project`), re-triangulating every face that touches a split edge, so the mesh stays watertight.
    Returns (vertices, faces, parent)."""
    def edge_keys(f: Array) -> Array:
        return np.sort(np.stack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], axis=1), axis=2)  # (F, 3, 2)

    # longest-edge bisection: only each selected face's longest edge splits (neighbours follow), which keeps
    # triangles well shaped instead of multiplying slivers. Only the selected faces and their neighbours are
    # looked at: a pattern refines one part of a mesh of many (#123).
    own = edge_keys(faces[selected])  # (S, 3, 2)
    length = np.linalg.norm(vertices[own[:, :, 0]] - vertices[own[:, :, 1]], axis=2)
    rows = np.arange(len(own))
    longest = length.argmax(axis=1)
    long_edge = length[rows, longest] > max_edge
    if not long_edge.any():
        return vertices, faces, np.arange(len(faces))
    split_keys = np.unique(own[rows, longest][long_edge], axis=0)
    mids = project((vertices[split_keys[:, 0]] + vertices[split_keys[:, 1]]) / 2)
    base = len(vertices)
    # midpoint index for every face edge (-1 = not split): edges as one integer each, looked up in the sorted split
    # ones; only faces with two corners on split edges can hold one
    ends = np.zeros(base, dtype=bool)
    ends[split_keys] = True
    near = np.flatnonzero(ends[faces].sum(axis=1) >= 2)
    keys = edge_keys(faces[near]).reshape(-1, 2)
    code = keys[:, 0].astype(np.int64) * base + keys[:, 1]
    split_code = split_keys[:, 0].astype(np.int64) * base + split_keys[:, 1]  # sorted (np.unique sorts rows)
    at = np.minimum(np.searchsorted(split_code, code), len(split_code) - 1)
    mid = np.full((len(faces), 3), -1, dtype=np.int64)
    mid[near] = np.where(split_code[at] == code, base + at, -1).reshape(-1, 3)
    flags = mid >= 0
    count = flags.sum(axis=1)
    out, parent = [faces[count == 0]], [np.flatnonzero(count == 0)]
    rows = np.flatnonzero(count == 3)
    if len(rows):
        a, b, c = faces[rows, 0], faces[rows, 1], faces[rows, 2]
        m0, m1, m2 = mid[rows, 0], mid[rows, 1], mid[rows, 2]
        out += [np.stack(t, axis=1) for t in ((a, m0, m2), (m0, b, m1), (m2, m1, c), (m0, m1, m2))]
        parent += [rows] * 4
    for n in (1, 2):
        rows = np.flatnonzero(count == n)
        if not len(rows):
            continue
        # rotate so that (1 split) the split edge is edge 0, (2 split) the unsplit edge is edge 2
        key_edge = flags[rows].argmax(axis=1) if n == 1 else (~flags[rows]).argmax(axis=1)
        shift = key_edge if n == 1 else (key_edge + 1) % 3
        r = np.arange(len(rows))
        v = [faces[rows][r, (shift + k) % 3] for k in range(3)]
        m = [mid[rows][r, (shift + k) % 3] for k in range(3)]
        if n == 1:
            out += [np.stack([v[0], m[0], v[2]], axis=1), np.stack([m[0], v[1], v[2]], axis=1)]
            parent += [rows] * 2
        else:
            out += [np.stack([m[0], v[1], m[1]], axis=1), np.stack([v[0], m[0], m[1]], axis=1), np.stack([v[0], m[1], v[2]], axis=1)]
            parent += [rows] * 3
    return np.concatenate([vertices, mids]), np.concatenate(out), np.concatenate(parent)


@dataclass
class Painted:
    vertices: Array
    faces: Array
    face_group: Array  # index into groups
    groups: list[PaintGroup]
    face_decal: Array  # index into decals, -1 = none
    decals: list[Decal]


@dataclass(frozen=True)
class PaintGroup:
    bone: str  # part id (the node or bone the faces belong to)
    color: str  # hex
    color_name: str
    material: str
    part: int = -1  # the part (index) whose own data (`uv:` projection, `attr:` values) these faces carry; -1: none


ON_BORDER = 1e-9  # metres: a vertex this close to a flat pattern's border is on it
MAX_STRIPES = 64  # flat faces: more stripes than this are cut the general way


def _pattern_fn(p: Pattern, geometry: Geometry | None = None) -> ScalarFn:
    """>= 0 where the pattern's second colour goes; `geometry`: the part, for patterns in its own frame."""
    if p.type == "along" and geometry is not None:  # a gradient's band: from `at` (a fraction) on along the path or axis
        return _along_fn(p, geometry)
    if p.frame == "part" and geometry is not None:
        from kiln.uv import local

        model_space = _pattern_fn(p)
        return lambda x: model_space(local(geometry, x))
    axis = np.array(p.axis)
    if p.type == "stripes":
        return lambda x: np.cos(2 * math.pi * (x @ axis) / p.size) - math.cos(math.pi * p.width)
    if p.type == "band":
        return lambda x: p.size / 2 - np.abs(x @ axis - p.at)
    if p.type == "checker":
        return lambda x: np.prod(np.sin(math.pi * x / p.size + 1e-3), axis=1)
    radius = p.width * p.size / 2  # dots

    def dots(x: Array) -> Array:
        q = x / p.size
        return radius - np.linalg.norm((q - np.round(q)) * p.size, axis=1)

    return dots


def _along_fn(p: Pattern, geometry: Geometry) -> ScalarFn:
    """0 to 1 from the start of the part's path (or the low end of its axis) to the end, minus the band's start."""
    from kiln.sdf import SHAPES
    from kiln.uv import _along, _path, local

    path = _path(geometry)
    if not any(p.axis) and path is not None:
        return lambda x: _along(local(geometry, x), path)[1] - p.at
    a = int(np.argmax(np.abs(p.axis)))
    lo, hi = SHAPES[geometry.shape].bounds(geometry.params)
    span = max(float(hi[a] - lo[a]), 1e-12)
    return lambda x: (local(geometry, x)[:, a] - float(lo[a])) / span - p.at


def _decal_frame(d: Decal) -> tuple[Array, Array, Array]:
    """(facing direction, u axis, v axis) so the image reads correctly when seen from the facing side."""
    sign = -1.0 if d.axis.startswith("-") else 1.0
    a = "xyz".index(d.axis[-1])
    facing = np.zeros(3)
    facing[a] = sign
    up = np.array([0.0, 1.0, 0.0]) if a != 1 else np.array([0.0, 0.0, -sign])
    u = np.cross(up, facing)
    return facing, u / np.linalg.norm(u), up


def decal_uv(d: Decal, points: Array) -> Array:
    """Image coordinates: a decal's 0..1 over its rectangle; a texture's tile coordinates (unbounded: the image
    repeats). Cylindrical: u is the arc length round `axis` (so texels keep their size on any radius), v along it."""
    rel = points - np.array(d.at)
    if d.project == "cylindrical":
        a = "xyz".index(d.axis)
        b, c = (a + 1) % 3, (a + 2) % 3  # y axis: angle from +z towards +x, so the seam is at the back (-z)
        radius = np.hypot(rel[:, b], rel[:, c])
        return np.stack([np.arctan2(rel[:, c], rel[:, b]) * radius / d.size[0], -rel[:, a] / d.size[1]], axis=1)
    if d.project == "box":
        raise ValueError("a box texture's coordinates depend on each face's side: use corner_uv")
    _, u, v = _decal_frame(d)
    return np.stack([(rel @ u) / d.size[0] + 0.5, 0.5 - (rel @ v) / d.size[1]], axis=1)


def _box_uv(d: Decal, rel: Array, axis: Array, sign: Array) -> Array:
    """Box-projected tile coordinates of points `rel` (relative to the texture's centre), each from the side
    (axis 0-2, sign) given per point: the image upright and unmirrored seen from that side."""
    out = np.zeros((len(rel), 2))
    for a in range(3):
        for s_ in (1.0, -1.0):
            m = (axis == a) & (sign == s_)
            if m.any():
                _, u, v = _decal_frame(Decal(d.image, ("" if s_ > 0 else "-") + "xyz"[a], d.at, d.size))
                out[m] = np.stack([(rel[m] @ u) / d.size[0], -(rel[m] @ v) / d.size[1]], axis=1)
    return out


def corner_uv(d: Decal, corners: Array) -> Array:
    """(F, 3, 2) image coordinates per face corner. Planar decals: decal_uv. Textures (#184): box picks each face's
    side from its normal; cylindrical wraps the side round its axis (corners kept on one side of the seam, so no face
    smears the image round) and takes faces along the axis flat, as box does."""
    flat = corners.reshape(-1, 3)
    if d.project == "planar":
        return decal_uv(d, flat).reshape(-1, 3, 2)
    rel = corners - np.array(d.at)
    normal = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
    dominant = np.argmax(np.abs(normal), axis=1)
    sign = np.where(normal[np.arange(len(normal)), dominant] >= 0, 1.0, -1.0)
    if d.project == "box":
        return _box_uv(d, rel.reshape(-1, 3), np.repeat(dominant, 3), np.repeat(sign, 3)).reshape(-1, 3, 2)
    a = "xyz".index(d.axis)
    b, c = (a + 1) % 3, (a + 2) % 3
    angle = np.arctan2(rel[..., c], rel[..., b])
    radius = np.hypot(rel[..., b], rel[..., c])
    on_axis = radius < 1e-9 * max(d.size)  # a cone's tip: any angle; left out of the seam test
    spread = np.where(on_axis, np.nan, angle)
    wrap = (np.nanmax(np.where(np.isnan(spread).all(axis=1, keepdims=True), 0.0, spread), axis=1)
            - np.nanmin(np.where(np.isnan(spread).all(axis=1, keepdims=True), 0.0, spread), axis=1)) > np.pi  # fmt: skip
    angle = np.where(wrap[:, None] & (angle < 0), angle + 2 * np.pi, angle)
    uv = np.stack([angle * radius / d.size[0], -rel[..., a] / d.size[1]], axis=-1)
    cap = np.abs(normal[:, a]) >= 0.7
    if cap.any():
        uv[cap] = _box_uv(d, rel[cap].reshape(-1, 3), np.full(cap.sum() * 3, a), np.repeat(np.where(normal[cap, a] >= 0, 1.0, -1.0), 3)).reshape(-1, 3, 2)
    return uv


@dataclass
class Regions:
    """A mesh cut along the borders between paint groups, with every face's group."""

    mesh: Mesh
    owner: Array  # (F,) index into groups
    groups: list[PaintGroup]
    part_group: dict[int, int]  # adding part index -> group
    pattern_groups: dict[int, tuple[int, ...]]  # group -> its patterns' colour groups


def regions(mesh: Mesh, model: Model, field: Field, rigged: bool, include: list[int] | None = None, protect: frozenset[int] = frozenset(),
            progress: Progress | None = None) -> Regions:  # fmt: skip
    """Cut the mesh into paint groups (one per bone + colour + material) and patterns. Done on the full-resolution
    mesh, so the borders are smooth curves that decimation then keeps (mesher.decimate_regions). `protect`ed parts
    (thin ones the budget would erase) get their own group, so decimation keeps their outline too."""
    vertices, faces = mesh.vertices, mesh.faces
    adding = [i for i, part in enumerate(model.parts) if part.geometry.op == "add" and (include is None or i in include)]
    groups, group_index, part_group = _groups(model, adding, rigged, protect)
    members = [[i for i in adding if part_group[i] == g] for g in range(len(groups))]

    later = {i: [j for j in range(i + 1, len(model.parts)) if model.parts[j].geometry.op != "add" and _cuts(model, j, i)] for i in adding}
    # borders between parts follow their smooth shapes: noise roughens the surface, not the colour edges on it (#100)
    # (`owners`; the mesh's own field, noise and all, still places new vertices on the surface)
    owners = Field([replace(g, noise=None) for g in field.parts], field.margin, field.active) if any(g.noise for g in field.parts) else field

    def group_distances(points: Array) -> Array:
        if not len(points):
            return np.zeros((len(groups), 0))
        # a part's surface counts only where the cuts after it left it (a door in a cut archway isn't the wall's)
        removers = {j: owners.part_distance(j, points) for j in sorted({j for js in later.values() for j in js})}
        # a running minimum per group (parts x points would not fit for many-part models)
        out = np.full((len(groups), len(points)), np.inf)
        for g, m in enumerate(members):
            for i in m:
                d = owners.part_distance(i, points)
                for j in later[i]:
                    d = np.maximum(d, -removers[j] if model.parts[j].geometry.op == "cut" else removers[j])
                np.minimum(out[g], d, out=out[g])
        return out

    def margins(d: Array) -> Array:
        """Row g becomes group g's distance minus the nearest of groups g+1.. (in place: a suffix minimum, so each
        group's border costs one pass, not a minimum over all the later groups, #123)."""
        nearest = np.full(d.shape[1], np.inf)
        for g in range(len(d) - 1, -1, -1):
            own = d[g].copy()
            d[g] -= nearest
            np.minimum(nearest, own, out=nearest)
        return d

    margin = margins(group_distances(vertices))
    owner = np.full(len(faces), -1)
    for g in range(len(groups)):
        unclaimed = owner < 0
        if not unclaimed.any():
            break
        if g == len(groups) - 1:
            owner[unclaimed] = g
            break
        n_before = len(vertices)
        vertices, faces, negative, parent = split(vertices, faces, margin[g], unclaimed)
        owner = owner[parent]
        if len(vertices) > n_before:
            margin = np.concatenate([margin, margins(group_distances(vertices[n_before:]))], axis=1)
        owner[(owner < 0) & negative] = g
        if progress is not None:
            progress("painting: borders, colour groups done", g + 1, len(groups))
    vertices, faces, owner, pattern_groups = _patterns(vertices, faces, owner, model, adding, groups, group_index, part_group,
                                                      lambda x: _project(field, x), progress=progress)  # fmt: skip
    # `under`: what a detachable (separate) part covers is painted (hair under a helmet), seen once it falls off
    if rigged and include is not None:
        for pid, entry in sorted(model.rig.items()):
            if not entry.separate or entry.under is None or any(model.parts[i].id == pid for i in include):
                continue
            covering = [i for i, part in enumerate(model.parts) if part.geometry.op == "add" and part.id == pid]
            if not covering:
                continue
            hexc, name, material, gap = entry.under

            def under_values(x: Array, covering: list[int] = covering, gap: float = gap) -> Array:
                per = []
                for i in covering:  # its solid shape, minus what later cuts take away (a face opening)
                    d = owners.parts[i].distance(x, filled=True)
                    for j in range(i + 1, len(model.parts)):
                        g = model.parts[j].geometry
                        if g.op == "cut" and _cuts(model, j, i):
                            d = np.maximum(d, -owners.part_distance(j, x))
                        elif g.op == "intersect":
                            d = np.maximum(d, owners.part_distance(j, x))
                    per.append(d)
                return np.min(per, axis=0) - gap

            sel = np.ones(len(faces), dtype=bool)
            vertices, faces, negative, parent = split(vertices, faces, under_values(vertices), sel)
            owner = owner[parent]
            changed = negative & (owner >= 0)
            for g in sorted(set(owner[changed].tolist())):
                alt = PaintGroup(groups[g].bone, hexc, f"{name}#under_{pid}", material)
                if alt not in group_index:
                    group_index[alt] = len(groups)
                    groups.append(alt)
                owner[changed & (owner == g)] = group_index[alt]
    return Regions(Mesh(vertices, faces), owner, groups, part_group, pattern_groups)


def _cuts(model: Model, j: int, i: int) -> bool:
    """Does part j (a cut or intersect) apply to part i?"""
    only = model.parts[j].geometry.cut_only
    return only is None or i in only


def _groups(model: Model, adding: list[int], rigged: bool, protect: frozenset[int]) -> tuple[list[PaintGroup], dict[PaintGroup, int], dict[int, int]]:
    """Parts that paint the same way (and move with the same bone) are one group: no cuts between them."""
    group_index: dict[PaintGroup, int] = {}
    groups: list[PaintGroup] = []
    part_group: dict[int, int] = {}
    for i in adding:
        part = model.parts[i]
        key = PaintGroup(part.id if rigged else "root", part.color, part.color_name, part.material)
        own_data = part.uv is not None or bool(part.attr)
        if part.pattern is not None or part.decal is not None or part.texture is not None or own_data or i in protect:
            key = PaintGroup(key.bone, key.color, f"{key.color_name}#{i}", key.material, i if own_data else -1)  # its own group
        if key not in group_index:
            group_index[key] = len(groups)
            groups.append(key)
        part_group[i] = group_index[key]
    return groups, group_index, part_group


def hard_regions(mesh: Mesh, face_part: Array, model: Model, rigged: bool) -> Regions:
    """Paint groups of a hard mesh: every polygon knows its part, so no cutting is needed (patterns still are)."""
    adding = sorted({int(i) for i in face_part})
    groups, group_index, part_group = _groups(model, adding, rigged, frozenset())
    owner = np.array([part_group[int(i)] for i in face_part], dtype=np.int64).reshape(-1)
    vertices, faces, owner, pattern_groups = _patterns(mesh.vertices, mesh.faces, owner, model, adding, groups, group_index, part_group,
                                                      lambda x: x, flat=True)  # flat faces: new points are already on them  # fmt: skip
    return Regions(Mesh(vertices, faces), owner, groups, part_group, pattern_groups)


def _patterns(
    vertices: Array, faces: Array, owner: Array, model: Model, adding: list[int], groups: list[PaintGroup], group_index: dict[PaintGroup, int],
    part_group: dict[int, int], project: Callable[[Array], Array], flat: bool = False, progress: Progress | None = None,
) -> tuple[Array, Array, Array, dict[int, tuple[int, ...]]]:
    """Patterns: a second colour cut into each patterned part's own faces (several: in order, each over the last).
    `flat`: the faces are exact polygons (hard parts), so bands and stripes are cut along their border planes as they
    are, without refining: no extra triangles beyond the cuts."""
    pattern_groups: dict[int, tuple[int, ...]] = {}
    patterned = [i for i in adding if model.parts[i].patterns]
    for i in adding:
        part = model.parts[i]
        g = part_group[i]
        if progress is not None and part.patterns:
            progress("painting: patterns, parts done", patterned.index(i), len(patterned))
        # this part's faces, followed through every cut: its patterns' colour groups are shared with other parts that
        # paint the same colours (every tuft with the same gradient), so "owner in own" would take theirs too (#131)
        mine = owner == g
        for pat in part.patterns:
            fn = _pattern_fn(pat, part.geometry)
            own = [g, *pattern_groups.get(g, ())]  # a later pattern paints over the earlier ones' colours too
            if not mine.any():
                break
            borders = _border_planes(pat, vertices[np.unique(faces[mine])], part.geometry) if flat else None
            if borders is not None:
                for value in borders:
                    d = _own_values(value, vertices, faces, mine)
                    vertices, faces, _, parent = split(vertices, faces, np.where(np.abs(d) < ON_BORDER, 0.0, d), mine)
                    owner, mine = owner[parent], mine[parent]
                inside = mine.copy()  # every face is now on one side of every border
                inside[mine] = fn(vertices[faces[mine]].mean(axis=1)) >= -ON_BORDER
                owner = _paint_alt(owner, own, inside, pat, part, g, groups, group_index, pattern_groups)
                continue
            # A pattern needs edges shorter than its repeat (or a stripe could fall between vertices), then short edges
            # along its borders to cut them cleanly; areas between borders stay coarse (the budget). A gradient's band
            # runs one way (its coordinate only grows along the part), so its border pass is enough.
            passes = [(pat.size / 2 if pat.type != "band" else pat.size, False), (pat.size / 4, True)]
            for limit, border_only in passes[1:] if pat.type == "along" else passes:
                for _ in range(12):
                    sel = mine.copy()
                    values = _own_values(fn, vertices, faces, sel)[faces[sel]]  # the part's faces only (#123)
                    if border_only:
                        sel[sel] = (values.min(axis=1) < 0) & (values.max(axis=1) >= 0)
                    elif pat.type == "band":
                        sel[sel] = values.max(axis=1) > -pat.size  # only near the band
                    if not sel.any():
                        break
                    n_before = len(faces)
                    vertices, faces, parent = refine(vertices, faces, sel, limit, project)
                    owner, mine = owner[parent], mine[parent]
                    if len(faces) == n_before:
                        break
            vertices, faces, negative, parent = split(vertices, faces, _own_values(fn, vertices, faces, mine), mine)
            owner, mine = owner[parent], mine[parent]
            owner = _paint_alt(owner, own, mine & ~negative, pat, part, g, groups, group_index, pattern_groups)
    return vertices, faces, owner, pattern_groups


def _own_values(fn: ScalarFn, vertices: Array, faces: Array, sel: Array) -> Array:
    """`fn` at the vertices of the selected faces, NaN elsewhere (neither side of a border: those faces aren't cut).
    A pattern only ever looks at its own part's faces; evaluating it over the whole mesh made many-part models slow."""
    out = np.full(len(vertices), np.nan)
    mask = np.zeros(len(vertices), dtype=bool)
    mask[faces[sel]] = True
    used = np.flatnonzero(mask)
    if len(used):
        out[used] = fn(vertices[used])
    return out


def _paint_alt(owner: Array, own: list[int], faces: Array, pat: Pattern, part: Part, g: int, groups: list[PaintGroup],
               group_index: dict[PaintGroup, int], pattern_groups: dict[int, tuple[int, ...]]) -> Array:  # fmt: skip
    """`faces` take the pattern's colour (a paint group of the part's bone)."""
    alt = PaintGroup(groups[g].bone, pat.color, pat.color_name, part.material, groups[g].part)
    if alt not in group_index:
        group_index[alt] = len(groups)
        groups.append(alt)
    if group_index[alt] not in own:
        pattern_groups[g] = (*pattern_groups.get(g, ()), group_index[alt])
    owner = owner.copy()
    owner[faces] = group_index[alt]
    return owner


def _border_planes(pat: Pattern, points: Array, geometry: Geometry | None = None) -> list[Callable[[Array], Array]] | None:
    """A model-space band's or stripes' borders across `points` as linear functions (zero on a border), or None for
    patterns whose borders aren't planes. A gradient band along an axis of a plain part (one copy, no mirror or twist)
    has one plane: its own function."""
    if pat.type == "along" and any(pat.axis) and geometry is not None and len(geometry.copies) == 1 and not geometry.mirror \
            and not geometry.twist:  # fmt: skip
        return [_along_fn(pat, geometry)]
    if pat.frame == "part" or pat.type not in ("band", "stripes"):
        return None
    axis = np.array(pat.axis, float)
    if pat.type == "band":
        levels = [pat.at - pat.size / 2, pat.at + pat.size / 2]
    else:  # cos(2 pi t / size) = cos(pi width): t = size * (n +- width / 2)
        t = points @ axis
        first, last = math.floor(float(t.min()) / pat.size) - 1, math.ceil(float(t.max()) / pat.size) + 1
        if last - first > MAX_STRIPES:
            return None
        levels = sorted({pat.size * (n + sgn * pat.width / 2) for n in range(first, last + 1) for sgn in (-1, 1)})
    def plane(c: float) -> Callable[[Array], Array]:
        return lambda x: np.asarray(x @ axis - c)

    return [plane(c) for c in levels]


def paint(painted: Regions, model: Model) -> Painted:
    """Decals on top of the paint groups (cut after decimation: their borders are straight)."""
    vertices, faces, owner = painted.mesh.vertices, painted.mesh.faces, painted.owner
    groups, part_group, pattern_groups = painted.groups, painted.part_group, painted.pattern_groups
    adding = [i for i, part in enumerate(model.parts) if part.geometry.op == "add"]
    # decals: cut along the rectangle, then mark the faces inside that face the decal's way
    decals: list[Decal] = []
    face_decal = np.full(len(faces), -1)
    for i in adding:
        part = model.parts[i]
        if part.decal is None or i not in part_group:  # (another piece's part)
            continue
        d = part.decal
        g = part_group[i]
        own = {g, *pattern_groups.get(g, ())}
        facing, _, _ = _decal_frame(d)
        for column, bound in ((0, 0.0), (0, 1.0), (1, 0.0), (1, 1.0)):
            sel = np.isin(owner, list(own))
            uv = decal_uv(d, vertices)
            values = uv[:, column] - bound if bound == 0.0 else bound - uv[:, column]
            vertices, faces, _, parent = split(vertices, faces, values, sel)
            owner, face_decal = owner[parent], face_decal[parent]
        centroid = vertices[faces].mean(axis=1)
        uvc = decal_uv(d, centroid)
        normal = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]], vertices[faces[:, 2]] - vertices[faces[:, 0]])
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
        depth = np.abs((centroid - np.array(d.at)) @ facing)
        inside = (uvc >= 0).all(axis=1) & (uvc <= 1).all(axis=1) & (normal @ facing > 0.25) & (depth < max(d.size))
        mark = inside & np.isin(owner, list(own)) & (face_decal < 0)
        face_decal[mark] = len(decals)
        decals.append(d)
    # textures: every face of the part's own group not under its decal (its pattern colours paint over it); one entry
    # per texture: the side (box) or the wrap (cylindrical) is worked out per face (corner_uv)
    for i in adding:
        part = model.parts[i]
        if part.texture is None or i not in part_group:
            continue
        free = (owner == part_group[i]) & (face_decal < 0)
        if free.any():
            face_decal[free] = len(decals)
            decals.append(part.texture)
    return Painted(vertices, faces, owner, groups, face_decal, decals)


def _project(field: Field, points: Array) -> Array:
    step = 0.002
    for _ in range(2):
        points = points - field.distance(points)[:, None] * field.gradient(points, step)
    return points


def corner_normals(painted: Painted, field: Field, step: float, smooth: bool, sharp_angle: float) -> Array:
    """A normal per face corner (F, 3, 3): the surface's smooth normal, or the face's own where the surface turns
    sharper than `sharp_angle` (crisp box edges in smooth styles); faceted styles use face normals everywhere."""
    v, f = painted.vertices, painted.faces
    face_n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    face_n /= np.maximum(np.linalg.norm(face_n, axis=1, keepdims=True), 1e-12)
    flat = np.repeat(face_n[:, None, :], 3, axis=1)
    if not smooth:
        return flat
    vn = field.gradient(v, step * 0.25)[f]  # (F, 3, 3)
    # the surface's normal a little way into the face from each corner: on a crisp edge (a box's corner, a crisp
    # seam between parts) it's the face's own side, elsewhere the same as at the corner. Judging sharpness by the
    # surface, not the triangle, keeps big decimated triangles smooth. A point on the face lies under a curved
    # surface (the face is its chord), and next to a crisp edge (a shell's rim) nearer the other side, whose normal
    # it then has (dark wedges along rims): so it's taken half a step off the face, outside a convex edge or inside
    # a concave one, whichever normal is nearer the face's own.
    centre = v[f].mean(axis=1, keepdims=True)
    on_face = (v[f] + (centre - v[f]) * 0.15).reshape(-1, 3)
    away = np.repeat(face_n, 3, axis=0) * step * 0.5
    outer, inner = field.gradient(on_face + away, step * 0.25), field.gradient(on_face - away, step * 0.25)
    pick_outer = (outer * away).sum(axis=1) >= (inner * away).sum(axis=1)
    inset = np.where(pick_outer[:, None], outer, inner).reshape(-1, 3, 3)
    # on a crisp edge the field's normal is the bisector: half the edge's angle away from each face
    cos_limit = math.cos(math.radians(sharp_angle / 2))
    agree = (vn * inset).sum(axis=2) >= cos_limit
    normals = np.where(agree[:, :, None], vn, inset)
    # on a border between paint groups the surface usually creases (an eye on a head, a hoop on a barrel) and the
    # field's normal there is a blend of both sides: each side gets the average of its own faces' normals instead
    g = painted.face_group
    corner_group = np.repeat(g, 3)
    lo = np.full(len(v), np.iinfo(np.int64).max)
    hi = np.full(len(v), -1)
    np.minimum.at(lo, f.reshape(-1), corner_group)
    np.maximum.at(hi, f.reshape(-1), corner_group)
    border = (lo != hi)[f]  # (F, 3)
    if border.any():
        weighted = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])  # area-weighted
        key = f.reshape(-1) * (int(g.max()) + 1) + corner_group
        unique, inverse = np.unique(key, return_inverse=True)
        side = np.zeros((len(unique), 3))
        np.add.at(side, inverse, np.repeat(weighted, 3, axis=0))
        side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-12)
        normals = np.where(border[:, :, None], side[inverse].reshape(-1, 3, 3), normals)
    return normals


__all__ = ["PaintGroup", "Painted", "Part", "Regions", "corner_normals", "corner_uv", "decal_uv", "hard_regions", "paint", "regions", "split"]
