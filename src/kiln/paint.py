"""Paint: which part (colour, material, bone) every triangle belongs to, with clean borders.

Triangles that straddle a border are cut along it: for two parts the border is where their distances are
equal, for a pattern where its function crosses zero, for a decal along its rectangle. Cutting (instead of
colouring whole triangles or vertices) keeps every colour border a straight-edged line on the surface, however
coarse the mesh.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from kiln.mesher import Mesh
from kiln.notation import Decal, Model, Part, Pattern
from kiln.sdf import Array, Field

ScalarFn = Callable[[Array], Array]


def split(vertices: Array, faces: Array, values: Array, selected: Array) -> tuple[Array, Array, Array, Array]:
    """Cut the selected faces along the zero line of `values` (one per vertex, linear along edges).

    Returns (vertices, faces, negative, parent): `negative` marks faces on the < 0 side, `parent` maps every
    output face to its input face. New vertices are shared between neighbouring faces, and a face that isn't
    selected but shares a cut edge is split at the new point too (same side, no T-junction): no cracks."""
    neg_v = values < 0
    n_neg = neg_v[faces].sum(axis=1)
    cut = selected & (n_neg > 0) & (n_neg < 3)
    idx = np.flatnonzero(cut)
    if not len(idx):
        return vertices, faces, n_neg == 3, np.arange(len(faces))
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
    new_points = vertices[a] + (vertices[b] - vertices[a]) * t[:, None]
    base = len(vertices)
    inverse = inverse.reshape(-1)
    m01 = base + inverse[: len(f)]
    m02 = base + inverse[len(f) :]
    # faces left whole but sharing a cut edge: split at the new point (their side doesn't change)
    rest = np.flatnonzero(~cut)
    lookup = {(int(x), int(y)): base + i for i, (x, y) in enumerate(unique)}
    out_faces: list[Array] = []
    out_neg: list[Array] = []
    out_parent: list[Array] = []
    whole: Array = rest
    if lookup:
        fr = faces[rest]
        ek = np.sort(np.stack([fr[:, [0, 1]], fr[:, [1, 2]], fr[:, [2, 0]]], axis=1), axis=2)  # (R, 3, 2)
        flat = ek.reshape(-1, 2)
        # only edges that were cut can match: test cheaply first
        cand = np.isin(flat[:, 0], a) & np.isin(flat[:, 1], b)
        mid_flat = np.full(len(flat), -1)
        for k in np.flatnonzero(cand):
            mid_flat[k] = lookup.get((int(flat[k, 0]), int(flat[k, 1])), -1)
        mid = mid_flat.reshape(-1, 3)
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
                out_neg.append(np.array([n_neg[rest[r]] == 3]))
                out_parent.append(np.array([rest[r]]))
    out_faces = [faces[whole]] + out_faces
    out_neg = [n_neg[whole] == 3] + out_neg
    out_parent = [np.asarray(whole, dtype=np.int64)] + out_parent
    out_faces += [np.stack([t0, m01, m02], axis=1), np.stack([m01, t1, t2], axis=1), np.stack([m01, t2, m02], axis=1)]
    out_neg += [lone_is_neg, ~lone_is_neg, ~lone_is_neg]
    out_parent += [idx, idx, idx]
    return np.concatenate([vertices, new_points]), np.concatenate(out_faces), np.concatenate(out_neg), np.concatenate(out_parent)


def refine(vertices: Array, faces: Array, selected: Array, max_edge: float, project: Callable[[Array], Array]) -> tuple[Array, Array, Array]:
    """Split every edge of the selected faces that is longer than `max_edge` at its midpoint (moved onto the
    surface by `project`), re-triangulating every face that touches a split edge, so the mesh stays watertight.
    Returns (vertices, faces, parent)."""
    e = np.stack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]], axis=1)  # (F, 3, 2)
    keys = np.sort(e, axis=2).reshape(-1, 2)
    length = np.linalg.norm(vertices[keys[:, 0]] - vertices[keys[:, 1]], axis=1)
    # longest-edge bisection: only each selected face's longest edge splits (neighbours follow), which keeps
    # triangles well shaped instead of multiplying slivers
    longest = np.zeros((len(faces), 3), dtype=bool)
    longest[np.arange(len(faces)), length.reshape(-1, 3).argmax(axis=1)] = True
    long_edge = (length > max_edge) & np.repeat(selected, 3) & longest.reshape(-1)
    if not long_edge.any():
        return vertices, faces, np.arange(len(faces))
    split_keys = np.unique(keys[long_edge], axis=0)
    mids = project((vertices[split_keys[:, 0]] + vertices[split_keys[:, 1]]) / 2)
    base = len(vertices)
    # midpoint index for every face edge (-1 = not split)
    lookup = {(int(a), int(b)): base + i for i, (a, b) in enumerate(split_keys)}
    mid = np.array([lookup.get((int(a), int(b)), -1) for a, b in keys]).reshape(-1, 3)
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


def _pattern_fn(p: Pattern) -> ScalarFn:
    """>= 0 where the pattern's second colour goes."""
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
    _, u, v = _decal_frame(d)
    rel = points - np.array(d.at)
    return np.stack([(rel @ u) / d.size[0] + 0.5, 0.5 - (rel @ v) / d.size[1]], axis=1)


@dataclass
class Regions:
    """A mesh cut along the borders between paint groups, with every face's group."""

    mesh: Mesh
    owner: Array  # (F,) index into groups
    groups: list[PaintGroup]
    part_group: dict[int, int]  # adding part index -> group
    pattern_groups: dict[int, int]  # group -> its pattern's second-colour group


def regions(mesh: Mesh, model: Model, field: Field, rigged: bool, include: list[int] | None = None, protect: frozenset[int] = frozenset()) -> Regions:
    """Cut the mesh into paint groups (one per bone + colour + material) and patterns. Done on the full-resolution
    mesh, so the borders are smooth curves that decimation then keeps (mesher.decimate_regions). `protect`ed parts
    (thin ones the budget would erase) get their own group, so decimation keeps their outline too."""
    vertices, faces = mesh.vertices, mesh.faces
    adding = [i for i, part in enumerate(model.parts) if part.geometry.op == "add" and (include is None or i in include)]
    groups, group_index, part_group = _groups(model, adding, rigged, protect)
    members = [[i for i in adding if part_group[i] == g] for g in range(len(groups))]

    later = {i: [j for j in range(i + 1, len(model.parts)) if model.parts[j].geometry.op != "add" and _cuts(model, j, i)] for i in adding}

    def group_distances(points: Array) -> Array:
        if not len(points):
            return np.zeros((len(groups), 0))
        # a part's surface counts only where the cuts after it left it (a door in a cut archway isn't the wall's)
        removers = {j: field.part_distance(j, points) for j in sorted({j for js in later.values() for j in js})}
        per_part = {}
        for i in adding:
            d = field.part_distance(i, points)
            for j in later[i]:
                d = np.maximum(d, -removers[j] if model.parts[j].geometry.op == "cut" else removers[j])
            per_part[i] = d
        return np.array([np.min([per_part[i] for i in m], axis=0) for m in members])

    dist = group_distances(vertices)
    owner = np.full(len(faces), -1)
    for g in range(len(groups)):
        unclaimed = owner < 0
        if not unclaimed.any():
            break
        if g == len(groups) - 1:
            owner[unclaimed] = g
            break
        rest = dist[g + 1 :].min(axis=0)
        values = dist[g] - rest
        n_before = len(vertices)
        vertices, faces, negative, parent = split(vertices, faces, values, unclaimed)
        owner = owner[parent]
        if len(vertices) > n_before:
            dist = np.concatenate([dist, group_distances(vertices[n_before:])], axis=1)
        owner[(owner < 0) & negative] = g
    vertices, faces, owner, pattern_groups = _patterns(vertices, faces, owner, model, adding, groups, group_index, part_group,
                                                      lambda x: _project(field, x))  # fmt: skip
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
                    d = field.parts[i].distance(x, filled=True)
                    for j in range(i + 1, len(model.parts)):
                        g = model.parts[j].geometry
                        if g.op == "cut" and _cuts(model, j, i):
                            d = np.maximum(d, -field.part_distance(j, x))
                        elif g.op == "intersect":
                            d = np.maximum(d, field.part_distance(j, x))
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
        if part.pattern is not None or part.decal is not None or i in protect:
            key = PaintGroup(key.bone, key.color, f"{key.color_name}#{i}", key.material)  # its own group
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
                                                      lambda x: x)  # flat faces: new points are already on them  # fmt: skip
    return Regions(Mesh(vertices, faces), owner, groups, part_group, pattern_groups)


def _patterns(
    vertices: Array, faces: Array, owner: Array, model: Model, adding: list[int], groups: list[PaintGroup], group_index: dict[PaintGroup, int],
    part_group: dict[int, int], project: Callable[[Array], Array],
) -> tuple[Array, Array, Array, dict[int, int]]:
    """Patterns: a second colour cut into each patterned part's own faces."""
    pattern_groups: dict[int, int] = {}
    for i in adding:
        part = model.parts[i]
        if part.pattern is None:
            continue
        g = part_group[i]
        fn = _pattern_fn(part.pattern)
        sel = owner == g
        if not sel.any():
            continue
        # A pattern needs edges shorter than its repeat (or a stripe could fall between vertices), then short edges
        # along its borders to cut them cleanly; areas between borders stay coarse (the budget).
        pat = part.pattern
        for limit, border_only in ((pat.size / 2 if pat.type != "band" else pat.size, False), (pat.size / 4, True)):
            for _ in range(12):
                values = fn(vertices)[faces]
                sel = owner == g
                if border_only:
                    sel &= (values.min(axis=1) < 0) & (values.max(axis=1) >= 0)
                elif pat.type == "band":
                    sel &= values.max(axis=1) > -pat.size  # only near the band
                if not sel.any():
                    break
                n_before = len(faces)
                vertices, faces, parent = refine(vertices, faces, sel, limit, project)
                owner = owner[parent]
                if len(faces) == n_before:
                    break
        sel = owner == g
        vertices, faces, negative, parent = split(vertices, faces, fn(vertices), sel)
        owner = owner[parent]
        alt = PaintGroup(groups[g].bone, part.pattern.color, part.pattern.color_name, part.material)
        if alt not in group_index:
            group_index[alt] = len(groups)
            groups.append(alt)
        pattern_groups[g] = group_index[alt]
        owner[(owner == g) & ~negative] = group_index[alt]
    return vertices, faces, owner, pattern_groups


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
        own = {g, pattern_groups.get(g, g)}
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
    # surface, not the triangle, keeps big decimated triangles smooth.
    centre = v[f].mean(axis=1, keepdims=True)
    inset = field.gradient((v[f] + (centre - v[f]) * 0.15).reshape(-1, 3), step * 0.25).reshape(-1, 3, 3)
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


__all__ = ["PaintGroup", "Painted", "Part", "Regions", "corner_normals", "decal_uv", "hard_regions", "paint", "regions", "split"]
