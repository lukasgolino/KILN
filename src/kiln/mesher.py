"""Field -> triangle mesh: sparse sampling, dual contouring (sharp edges where the shape has them, smooth
elsewhere), then decimation to a triangle budget with vertices pulled back onto the true surface.

Dual contouring puts one vertex in every grid cell the surface passes through, at the point that best fits the
surface planes measured on the cell's edges (a QEF, regularised towards the edge crossings' centre), and joins
the four cells around every crossed edge into a quad. Unlike marching cubes, a box keeps its corners.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import product

import fast_simplification
import numpy as np

from kiln.sdf import Array, Field

COARSE = 4  # coarse sampling: one in 4 grid points per axis first; only blocks near the surface are refined
MAX_CELLS = 256  # per axis
BAD_TILT_COS = math.cos(math.radians(25))  # a face turned further than this from the surface needs repair
BAD_ASPECT = 8.0  # longest edge squared over twice the area: above this, a sliver
BORDER_TOLERANCE = 0.15  # grid steps: how far a simplified colour border may stray from the exact one (first try)


@dataclass
class Mesh:
    vertices: Array  # (V, 3) float64
    faces: Array  # (F, 3) int64, counter-clockwise seen from outside

    @property
    def triangles(self) -> int:
        return int(len(self.faces))


def grid_step(size: float, resolution: float) -> float:
    """Metres per grid cell: the style's resolution, coarser for big models so a model stays <= MAX_CELLS
    cells across."""
    return max(resolution, size / (MAX_CELLS - 6))


def sample(field: Field, lo: Array, step: float, dims: tuple[int, int, int]) -> Array:
    """Field values on the grid lo + index * step. Coarse first; fine values only in blocks near the surface,
    elsewhere the nearest coarse value (same sign, so no surface is lost)."""
    nx, ny, nz = dims
    axes = [np.arange(n) for n in dims]
    coarse_idx = [np.unique(np.minimum(np.arange(0, n + COARSE - 1, COARSE), n - 1)) for n in dims]
    cg = np.stack(np.meshgrid(*coarse_idx, indexing="ij"), axis=-1).reshape(-1, 3)
    cvals = field.distance(lo + cg * step).reshape([len(c) for c in coarse_idx])
    # a coarse block is near the surface if any corner is within the block's diagonal (+ slack for blends/noise)
    threshold = COARSE * step * math.sqrt(3) * 1.5
    near = np.abs(cvals) < threshold
    block = near[:-1, :-1, :-1] | near[1:, :-1, :-1] | near[:-1, 1:, :-1] | near[:-1, :-1, 1:]
    block |= near[1:, 1:, :-1] | near[1:, :-1, 1:] | near[:-1, 1:, 1:] | near[1:, 1:, 1:]
    # nearest coarse sample for every fine point, then refine the near blocks
    nearest = [np.searchsorted(c, a - COARSE / 2, side="left").clip(0, len(c) - 1) for c, a in zip(coarse_idx, axes, strict=True)]
    values = cvals[np.ix_(*nearest)].astype(float)
    block_of = [np.minimum(a // COARSE, len(c) - 2).clip(0) for c, a in zip(coarse_idx, axes, strict=True)]
    # points on a block's faces belong to the neighbouring blocks too: refine them when any of those is near
    shifted = [np.where((a % COARSE == 0) & (a > 0), np.maximum(b - 1, 0), b) for a, b in zip(axes, block_of, strict=True)]
    refine = np.zeros(dims, dtype=bool)
    for combo in product((False, True), repeat=3):
        refine |= block[np.ix_(*[s if use else b for use, s, b in zip(combo, shifted, block_of, strict=True)])]
    idx = np.argwhere(refine)
    if len(idx):
        values[refine] = field.distance(lo + idx * step)
    return values


GROW = 8  # cells added to a side of the grid the surface reaches
GROW_TRIES = 6


def model_step(field: Field, resolution: float) -> float:
    """Grid step for a model: the style's resolution for a ~1 m model, coarser (by the square root of the size)
    for bigger ones, and never more than MAX_CELLS cells across."""
    lo, hi = field.bounds()
    size = float((hi - lo).max())
    return grid_step(size, resolution * max(size, 1.0) ** 0.5)


def _grid(field: Field, step: float) -> tuple[Array, tuple[int, int, int], Array]:
    """The sampling grid's corner, size and values: the parts' boxes plus a margin, grown on any side the surface
    reaches (smooth unions bulge out of their parts' boxes, by up to a quarter of the blend radius per join)."""
    lo, hi = field.bounds()
    pad_lo, pad_hi = np.full(3, 2.5 * step), np.full(3, 2.5 * step)
    for _ in range(GROW_TRIES):
        corner = lo - pad_lo
        dims = tuple(int(math.ceil(v)) + 1 for v in ((hi + pad_hi - corner) / step))
        values = sample(field, corner, step, dims)  # type: ignore[arg-type]
        grown = False
        for axis in range(3):
            if (values.take([0, 1], axis=axis) < 0).any():
                pad_lo[axis] += GROW * step
                grown = True
            if (values.take([-2, -1], axis=axis) < 0).any():
                pad_hi[axis] += GROW * step
                grown = True
        if not grown:
            break
    return corner, dims, values  # type: ignore[return-value]


def _others(axis: int) -> tuple[int, int]:
    return (1, 2) if axis == 0 else (0, 2) if axis == 1 else (0, 1)


def _cube_edge(axis: int, corner: int) -> int:
    """A cell's edge along `axis` from `corner` (bits x + 2y + 4z): axis * 4 + its offset in the two other axes."""
    u, w = _others(axis)
    return axis * 4 + ((corner >> u) & 1) + 2 * ((corner >> w) & 1)


def _cube_faces() -> list[tuple[list[int], list[int]]]:
    """A cell's six faces: their corners in order around the face, and the edges between them."""
    out = []
    for d in range(3):
        u, w = _others(d)
        for s in (0, 1):
            corners = [(s << d) | (cu << u) | (cw << w) for cu, cw in ((0, 0), (1, 0), (1, 1), (0, 1))]
            pairs = [(corners[k], corners[(k + 1) % 4]) for k in range(4)]
            out.append((corners, [_cube_edge((a ^ b).bit_length() - 1, a & b) for a, b in pairs]))
    return out


def _cube_edge_ends() -> list[tuple[int, int]]:
    """Each of a cell's edges (in `_cube_edge` order): its two corners."""
    out = []
    for axis in range(3):
        u, w = _others(axis)
        for k in range(4):
            low = ((k & 1) << u) | ((k >> 1) << w)
            out.append((low, low | (1 << axis)))
    return out


CUBE_FACES = _cube_faces()
CUBE_EDGE_ENDS = _cube_edge_ends()


def _sheets(code: int) -> tuple[list[int], int]:
    """Which surface sheet each of a cell's 12 edges crosses (-1: none), and which faces (bit k) one sheet crosses
    twice. `code`: bit c = corner c inside, bit 8 + k = face k's inside corners are joined across it (when it has
    four crossings). Crossings pair up on each face (on a face with four, cutting off the corners that aren't
    joined), so every sheet is a loop of edges around the cell: one vertex each keeps two sheets in one cell (a thin
    plate, a narrow gap) apart instead of pinching them."""
    inside = [(code >> c) & 1 for c in range(8)]
    parent = list(range(12))

    def find(i: int) -> int:
        while parent[i] != i:
            i = parent[i]
        return i

    four = []
    for k, (corners, edges) in enumerate(CUBE_FACES):
        crossed = [e for j, e in enumerate(edges) if inside[corners[j]] != inside[corners[(j + 1) % 4]]]
        if len(crossed) == 2:
            parent[find(crossed[0])] = find(crossed[1])
        elif len(crossed) == 4:
            four.append(k)
            joined = (code >> (8 + k)) & 1  # the inside corners are joined: cut off the outside ones
            for j in range(4):
                if inside[corners[j]] != joined:
                    parent[find(edges[j - 1])] = find(edges[j])
    roots: dict[int, int] = {}
    out = []
    for e, (a, b) in enumerate(CUBE_EDGE_ENDS):
        out.append(roots.setdefault(find(e), len(roots)) if inside[a] != inside[b] else -1)
    twice = sum(1 << k for k in four if len({find(e) for e in CUBE_FACES[k][1]}) == 1)
    return out, twice


def _cell_codes(values: Array, cell_idx: Array, flip: Array) -> Array:
    """Every cell's `_sheets` code: corner signs, and for faces with four crossings whether the bilinear surface
    across the face joins the inside corners (the asymptotic decider: from the face's values alone, so both cells
    sharing it agree), the other way round on `flip`ped faces (cells, 6)."""
    corner = np.stack([values[cell_idx[:, 0] + (c & 1), cell_idx[:, 1] + ((c >> 1) & 1), cell_idx[:, 2] + (c >> 2)] for c in range(8)], axis=1)
    inside = corner < 0
    code = (inside.astype(np.int64) << np.arange(8)).sum(axis=1)
    for k, (corners, _) in enumerate(CUBE_FACES):
        a, b, c, d = (corner[:, i] for i in corners)
        ambiguous = (inside[:, corners[0]] == inside[:, corners[2]]) & (inside[:, corners[1]] == inside[:, corners[3]])
        ambiguous &= inside[:, corners[0]] != inside[:, corners[1]]
        denominator = np.where(ambiguous, a + c - b - d, 1.0)
        joined = ambiguous & (((a * c - b * d) / denominator < 0) != flip[:, k])
        code |= joined.astype(np.int64) << (8 + k)
    return code


def _cell_sheets(values: Array, cell_idx: Array) -> Array:
    """Every cell's `_sheets` (cells, 12). Where both cells beside a face have a sheet crossing it twice (a handle of
    the surface smaller than a cell), one vertex for each would give their edge four faces: those faces are read
    the other way round, which splits the sheets."""
    dims = np.array(values.shape)
    face_id = np.stack([(k >> 1) * int(dims.prod()) + np.ravel_multi_index((cell_idx + (k & 1) * np.eye(3, dtype=np.int64)[k >> 1]).T, values.shape)
                        for k in range(6)], axis=1)  # fmt: skip
    flipped = np.zeros(0, dtype=np.int64)
    for _ in range(4):
        codes, code_of = np.unique(_cell_codes(values, cell_idx, np.isin(face_id, flipped)), return_inverse=True)
        table = [_sheets(int(c)) for c in codes]
        sheet = np.array([t[0] for t in table], dtype=np.int64)[code_of.reshape(-1)]
        twice = np.array([t[1] for t in table], dtype=np.int64)[code_of.reshape(-1)]
        ids, count = np.unique(face_id[((twice[:, None] >> np.arange(6)) & 1).astype(bool)], return_counts=True)
        if not (count > 1).any():
            break
        flipped = np.union1d(flipped, ids[count > 1])
    return sheet


CROSSING_TOLERANCE = 0.01  # grid steps: a crossing point further off the surface than this is searched for
CROSSING_STEPS = 4
RIM_TOLERANCE = 0.05  # grid steps: a best-fit point outside its cell this close to the surface is kept there


def _crossings(field: Field, start: Array, edge: Array, f0: Array, f1: Array, t: Array, step: float) -> Array:
    """Where the surface crosses each grid edge (start + t * edge, the ends' values f0 and f1 of opposite signs).
    Between the ends the field is taken as linear, which is exact on a flat surface; next to a sharp rim, though,
    the field outside is the distance to the rim, the guess sits off the surface where the normal is the rim's
    (halfway between its sides), and the best-fit point then cuts the rim off: thin sharp rims came out ragged.
    Guesses off the surface are moved onto it by false position (the Illinois variant)."""
    t, ta, tb, fa, fb = t.copy(), np.zeros_like(t), np.ones_like(t), f0.copy(), f1.copy()
    todo = np.arange(len(t))
    for _ in range(CROSSING_STEPS):
        d = field.distance(start[todo] + t[todo, None] * edge[todo])
        off = np.abs(d) > CROSSING_TOLERANCE * step
        todo, d = todo[off], d[off]
        if not len(todo):
            break
        lower = np.sign(d) == np.sign(fa[todo])
        ta[todo] = np.where(lower, t[todo], ta[todo])
        fa[todo] = np.where(lower, d, fa[todo] / 2)  # Illinois: halve the end that stays, so both ends move
        tb[todo] = np.where(lower, tb[todo], t[todo])
        fb[todo] = np.where(lower, fb[todo] / 2, d)
        t[todo] = ta[todo] + (tb[todo] - ta[todo]) * fa[todo] / (fa[todo] - fb[todo])
    return start + t[:, None] * edge


def dual_contour(field: Field, step: float) -> Mesh:
    lo, dims, values = _grid(field, step)
    nx, ny, nz = dims
    inside = values < 0
    cell_dims = (nx - 1, ny - 1, nz - 1)

    # crossing edges, their surface points and normals
    points_list, normals_list, edges_list, ends_list = [], [], [], []
    for axis in range(3):
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[axis] = slice(0, -1)
        b[axis] = slice(1, None)
        v0, v1 = values[tuple(a)], values[tuple(b)]
        crossing = inside[tuple(a)] != inside[tuple(b)]
        idx = np.argwhere(crossing)
        if not len(idx):
            continue
        f0, f1 = v0[crossing], v1[crossing]
        t = np.clip(f0 / (f0 - f1), 0.0, 1.0)
        unit = np.zeros(3)
        unit[axis] = 1.0
        pts = lo + (idx + t[:, None] * unit) * step
        points_list.append(pts)
        edges_list.append((axis, idx, inside[tuple(a)][crossing]))
        ends_list.append((lo + idx * step, np.broadcast_to(unit * step, pts.shape), f0, f1, t))
    if not points_list:
        return Mesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    begin, edge, f0, f1, t = (np.concatenate(x) for x in zip(*ends_list, strict=True))
    all_points = _crossings(field, begin, edge, f0, f1, t, step)
    all_normals = field.gradient(all_points, step * 0.1)
    offsets = np.cumsum([0] + [len(p) for p in points_list])
    for i in range(len(points_list)):
        points_list[i] = all_points[offsets[i] : offsets[i + 1]]
        normals_list.append(all_normals[offsets[i] : offsets[i + 1]])

    # each crossed edge's four cells (only cells the surface passes through get a vertex: storing just those keeps
    # memory to the surface, not the whole grid)
    edges = []
    for (axis, idx, lower_inside), pts, nrm in zip(edges_list, points_list, normals_list, strict=True):
        others = [d for d in range(3) if d != axis]
        cells = []
        for da, db in ((0, 0), (1, 0), (1, 1), (0, 1)):  # around the edge, in order
            c = idx.copy()
            c[:, others[0]] -= 1 - da
            c[:, others[1]] -= 1 - db
            cells.append(c)
        stacked = np.stack(cells, axis=1)  # (E, 4, 3)
        valid = np.all((stacked >= 0) & (stacked < np.array(cell_dims)), axis=(1, 2))
        stacked, pts, nrm, lower_inside = stacked[valid], pts[valid], nrm[valid], lower_inside[valid]
        flat = np.ravel_multi_index(stacked.reshape(-1, 3).T, cell_dims).reshape(-1, 4)
        edges.append((flat, pts, nrm, lower_inside, axis))
    # one vertex per sheet of the surface in a cell (usually one; two where a thin part or gap is under a cell wide)
    occupied, cell_of = np.unique(np.concatenate([e[0].reshape(-1) for e in edges]), return_inverse=True)
    sheet = _cell_sheets(values, np.stack(np.unravel_index(occupied, cell_dims), axis=1))
    # the crossed edge is, in each of its four cells (in order around it), the cell's edge with these offsets
    local_edge = np.concatenate([np.broadcast_to(axis * 4 + np.array([3, 2, 0, 1]), e.shape).reshape(-1) for e, *_, axis in edges])
    cell_of = cell_of.reshape(-1)
    keys = cell_of * 4 + sheet[cell_of, local_edge]
    vertex_key, compact = np.unique(keys, return_inverse=True)
    compact = compact.reshape(-1)
    active = occupied[vertex_key // 4]
    # accumulate each vertex's QEF from the (up to 12) crossed edges around it
    n = len(vertex_key)
    ata = np.zeros((n, 3, 3))
    atb = np.zeros((n, 3))
    mass = np.zeros((n, 3))
    count = np.zeros(n)
    quads = []
    start = 0
    for flat, pts, nrm, lower_inside, axis in edges:
        local = compact[start : start + flat.size].reshape(-1, 4)
        start += flat.size
        outer = nrm[:, :, None] * nrm[:, None, :]
        dot = (nrm * pts).sum(axis=1)
        for k in range(4):
            np.add.at(ata, local[:, k], outer)
            np.add.at(atb, local[:, k], nrm * dot[:, None])
            np.add.at(mass, local[:, k], pts)
            np.add.at(count, local[:, k], 1.0)
        quads.append((local, lower_inside, axis))

    m = mass / count[:, None]
    a_mat = ata + 0.05 * np.eye(3)
    rhs = atb - np.einsum("nij,nj->ni", ata, m)
    x = m + np.linalg.solve(a_mat, rhs[:, :, None])[:, :, 0]
    cell_idx = np.stack(np.unravel_index(active, cell_dims), axis=1)
    cell_lo = lo + cell_idx * step
    # best-fit points stay in (or just by) their cell, except where one lies on the surface further out: the tip of a
    # thin sharp rim (a roof overhanging its tower) is often beyond the cells whose crossings see both of its sides
    near = np.clip(x, cell_lo - 0.25 * step, cell_lo + 1.25 * step)
    far = np.clip(x, cell_lo - step, cell_lo + 2 * step)
    out = np.flatnonzero((near != far).any(axis=1))
    reach = out[np.abs(field.distance(far[out])) < RIM_TOLERANCE * step] if len(out) else out
    near[reach] = far[reach]
    x = near

    faces = []
    for q, lower_inside, axis in quads:  # (E, 4) vertex indices
        # orient so the normal points from inside to outside: + axis when the lower end is inside
        q = np.where(lower_inside[:, None], q, q[:, ::-1])
        if axis == 1:  # the cyclic order (others[0], others[1]) is left-handed for y
            q = q[:, ::-1]
        # split each quad along its shorter diagonal
        p = x[q]
        d02 = ((p[:, 0] - p[:, 2]) ** 2).sum(axis=1)
        d13 = ((p[:, 1] - p[:, 3]) ** 2).sum(axis=1)
        use02 = d02 <= d13
        t1 = np.where(use02[:, None], q[:, [0, 1, 2]], q[:, [0, 1, 3]])
        t2 = np.where(use02[:, None], q[:, [0, 2, 3]], q[:, [1, 2, 3]])
        faces.extend([t1, t2])
    f = np.concatenate(faces)
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])].astype(np.int64)
    # Along sharp rims a cell's best-fit point can land where its triangles fold over (facing inwards). Those
    # vertices go back to their cell's crossing centre: a slightly softer edge, but a clean surface (folds also
    # stop decimation: it won't collapse edges that would flip a triangle).
    for _ in range(4):
        p = x[f]
        normal = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        folded = (normal * field.gradient(p.mean(axis=1), step * 0.1)).sum(axis=1) < 0
        moved = np.unique(f[folded])
        moved = moved[np.any(x[moved] != m[moved], axis=1)]
        if not len(moved):
            break
        x[moved] = m[moved]
    if len(pinches(x, f)[0]):  # sheets one cell apart can still share an edge on coarse grids: split them
        x, f = unpinch(x, f)
        return remove_unused(Mesh(project(field, x, step * 2), f))
    return Mesh(x, f)


def project(field: Field, vertices: Array, step: float, iterations: int = 2) -> Array:
    """Pull vertices onto the zero surface along the field's gradient (after decimation moved them)."""
    v = vertices
    for _ in range(iterations):
        d = field.distance(v)
        v = v - np.clip(d, -step, step)[:, None] * field.gradient(v, step * 0.1)
    return v


def decimate(field: Field, mesh: Mesh, budget: int, step: float) -> Mesh:
    """Reduce to at most `budget` triangles (quadric edge collapse), then re-project onto the surface."""
    if mesh.triangles <= budget or mesh.triangles == 0:
        return mesh
    v, f = mesh.vertices.astype(np.float64), mesh.faces.astype(np.int32)
    for _ in range(4):  # the simplifier stops after a fixed number of rounds: again while that helps
        before = len(f)
        v, f = fast_simplification.simplify(v, f, target_count=int(budget), agg=6.0)
        if len(f) <= budget * 1.02 or len(f) > before * 0.97:
            break
    v, f = unpinch(np.asarray(v, dtype=np.float64), np.asarray(f, dtype=np.int64))
    v = project(field, v, step * 2)
    (f,) = drop_twins(*merge_coincident(v, f))
    return remove_unused(Mesh(v, f))


def simplify_borders(mesh: Mesh, region: Array, tolerance: float) -> tuple[Mesh, Array]:
    """Thin out the vertices along region borders (full resolution: one every grid step) wherever the border is
    straight enough: a vertex goes if it lies within `tolerance` of the line between its two border neighbours.
    Each removal collapses the vertex into a neighbour along the border, so the border stays on the surface and
    both sides stay joined. Junctions of three regions and anything that would fold a triangle stay."""
    v, f, region = mesh.vertices, mesh.faces.copy(), region.copy()
    alive = np.ones(len(f), dtype=bool)
    for _ in range(12):
        live = np.flatnonzero(alive)
        e = np.concatenate([f[live][:, [0, 1]], f[live][:, [1, 2]], f[live][:, [2, 0]]])
        owner = np.tile(live, 3)
        key = np.sort(e, axis=1)
        order = np.lexsort((key[:, 1], key[:, 0]))
        key, owner = key[order], owner[order]
        pair = np.flatnonzero((key[1:] == key[:-1]).all(axis=1))
        border = key[pair][region[owner[pair]] != region[owner[pair + 1]]]
        if not len(border):
            break
        ends = border.reshape(-1)
        count = np.bincount(ends, minlength=len(v))
        # each border vertex's two border neighbours (only for vertices on exactly two border edges)
        other = np.concatenate([border[:, 1], border[:, 0]])
        by = np.argsort(np.concatenate([border[:, 0], border[:, 1]]), kind="stable")
        verts = np.concatenate([border[:, 0], border[:, 1]])[by]
        nb = other[by]
        start = np.searchsorted(verts, np.arange(len(v)))
        cand = np.flatnonzero(count == 2)
        a, c = nb[start[cand]], nb[start[cand] + 1]
        chord = v[c] - v[a]
        t = np.clip(((v[cand] - v[a]) * chord).sum(1) / np.maximum((chord * chord).sum(1), 1e-18), 0, 1)
        dev = np.linalg.norm(v[cand] - (v[a] + chord * t[:, None]), axis=1)
        ok = dev < tolerance
        cand, a, dev = cand[ok], a[ok], dev[ok]
        if not len(cand):
            break
        # every vertex's faces (CSR): this pass only changes faces around locked vertices, so it stays valid
        corners = f[live].reshape(-1)
        by_vertex = np.argsort(corners, kind="stable")
        first = np.searchsorted(corners[by_vertex], np.arange(len(v) + 1))

        def faces_of(x: int) -> list[int]:
            return [int(i) for i in live[by_vertex[first[x] : first[x + 1]] // 3]]

        locked: set[int] = set()
        removed = 0
        for i in np.lexsort((cand, dev)):
            x, into = int(cand[i]), int(a[i])
            if x in locked or into in locked:
                continue
            fan = faces_of(x)
            ring = {int(y) for fi in fan for y in f[fi]}
            shared = [fi for fi in fan if into in f[fi]]
            # link condition: x and `into` share exactly the two vertices opposite their edge (no pinching)
            ring_into = {int(y) for fi in faces_of(into) for y in f[fi]}
            if len(shared) != 2 or len((ring & ring_into) - {x, into}) != 2:
                continue
            moved = [fi for fi in fan if fi not in shared]
            before = np.cross(v[f[moved, 1]] - v[f[moved, 0]], v[f[moved, 2]] - v[f[moved, 0]])
            after_f = np.where(f[moved] == x, into, f[moved])
            after = np.cross(v[after_f[:, 1]] - v[after_f[:, 0]], v[after_f[:, 2]] - v[after_f[:, 0]])
            norm = np.linalg.norm(before, axis=1) * np.linalg.norm(after, axis=1)
            if np.any((before * after).sum(1) <= 0.2 * norm):
                continue  # would fold or squash a triangle
            f[moved] = after_f
            alive[shared] = False
            locked |= ring | ring_into
            removed += 1
        if not removed:
            break
    keep = np.flatnonzero(alive)
    used, inverse = np.unique(f[keep], return_inverse=True)
    return Mesh(v[used], inverse.reshape(-1, 3).astype(np.int64)), region[keep]


def nearest_part(field: Field, points: Array) -> Array:
    """Index of the solid part whose surface is nearest to each point."""
    adding = [i for i, g in enumerate(field.parts) if g.op == "add"]
    if not adding:
        return np.zeros(len(points), dtype=np.int64)
    d = np.stack([np.abs(field.part_distance(i, points)) for i in adding])
    return np.asarray(adding)[d.argmin(axis=0)]


def relax(field: Field, mesh: Mesh, fixed: Array, step: float, iterations: int = 8, rate: float = 0.5) -> Mesh:
    """Repair what decimation next to locked borders leaves: fans of slivers that tilt and fold (dark wedges
    beside seams). Each round, the free vertices of bad faces (tilted against the surface, or slivers) slide along
    the surface towards the average of their neighbours, then back onto it. Good faces aren't touched, so rims
    and edges keep their shape."""
    v, f = mesh.vertices.copy(), mesh.faces
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e = np.unique(np.sort(e, axis=1), axis=0)
    a, b = np.concatenate([e[:, 0], e[:, 1]]), np.concatenate([e[:, 1], e[:, 0]])
    degree = np.bincount(a, minlength=len(v)).astype(float)
    # vertices on a crease (a cylinder's cap edge, a box's corner) stay: sliding them would round thin parts into
    # points. Only within one part: where two parts meet (next to a border, or a crisp join inside a region) the
    # normal jumps by design. (Normals here use a tiny difference step, so a part right next to the vertex
    # doesn't bend them.)
    normal = field.gradient(v, step * 0.01)
    crease = np.zeros(len(v), dtype=bool)
    part = nearest_part(field, v)
    sharp = (normal[e[:, 0]] * normal[e[:, 1]]).sum(axis=1) < BAD_TILT_COS
    sharp &= ~fixed[e[:, 0]] & ~fixed[e[:, 1]] & (part[e[:, 0]] == part[e[:, 1]])
    crease[e[sharp].reshape(-1)] = True
    for _ in range(iterations):
        p = v[f]
        n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
        area2 = np.linalg.norm(n, axis=1)
        tilt = (n * field.gradient(p.mean(axis=1), step * 0.01)).sum(axis=1) < BAD_TILT_COS * area2
        longest = np.max(np.linalg.norm(p - np.roll(p, 1, axis=1), axis=2), axis=1)
        sliver = longest**2 > BAD_ASPECT * np.maximum(area2, 1e-18)
        bad = tilt | sliver
        free = np.zeros(len(v), dtype=bool)
        free[f[bad].reshape(-1)] = True
        free &= ~fixed & ~crease & (degree > 0)
        if not free.any():
            break
        mean = np.zeros_like(v)
        np.add.at(mean, a, v[b])
        mean[free] /= degree[free, None]
        normal = field.gradient(v[free], step * 0.01)
        move = mean[free] - v[free]
        move -= (move * normal).sum(axis=1, keepdims=True) * normal  # along the surface only
        v[free] = project(field, v[free] + rate * move, step, 1)
    return Mesh(v, f)


def decimate_regions(
    field: Field,
    mesh: Mesh,
    region: Array,
    budget: int,
    step: float,
    border_tolerance: float = BORDER_TOLERANCE,
    fields: list[Field] | None = None,
    region_piece: Array | None = None,
) -> tuple[Mesh, Array]:
    """Like `decimate`, but the borders between regions (paint groups, cut on the full-resolution mesh) are kept
    exactly: the mesh is pulled apart along them, simplified with its open borders locked, and welded back.
    Collapsing edges across a border is what makes seams jagged, pupils polygonal and blends streaky.
    With `fields` and `region_piece` (region -> index into fields) the mesh is several pieces (a body and its
    `separate` helmet) decimated together, each pulled back onto its own surface.
    Returns the mesh and every face's region."""
    if mesh.triangles <= budget or mesh.triangles == 0:
        return mesh, region
    if border_tolerance > 0:
        mesh, region = simplify_borders(mesh, region, step * border_tolerance)
    # one copy of a vertex per region that uses it: borders become open edges
    n_regions = int(region.max()) + 1
    keys = (mesh.faces * n_regions + region[:, None]).reshape(-1)
    unique, inverse = np.unique(keys, return_inverse=True)
    source, vregion = unique // n_regions, unique % n_regions
    cut_v = mesh.vertices[source].astype(np.float64)
    cut_f = inverse.reshape(-1, 3).astype(np.int32)
    # The simplifier stops after a fixed number of rounds, which isn't always enough (a hat's flat brim): run it
    # again on its own result while that still helps.
    v, f = cut_v, cut_f.astype(np.int64)
    mapping = np.arange(len(cut_v))
    for _ in range(4):
        out_v, out_f, collapses = fast_simplification.simplify(
            v, f.astype(np.int32), target_count=int(budget), agg=6.0, return_collapses=True, preserve_border=True
        )
        # replaying the collapses gives which input vertex became which output vertex (same faces, same order);
        # its own positions aren't used: fast-simplification 0.2.0's replay misplaces some vertices by metres
        _, replayed, step_map = fast_simplification.replay_simplification(v, f.astype(np.int32), collapses)
        if not np.array_equal(np.asarray(out_f, dtype=np.int64), np.asarray(replayed, dtype=np.int64)):
            raise RuntimeError("fast-simplification's replay disagrees with its simplify; please report")
        progress = len(out_f) < len(f) * 0.97
        v, f = np.asarray(out_v, dtype=np.float64), np.asarray(out_f, dtype=np.int64)
        mapping = np.asarray(step_map, dtype=np.int64)[mapping]
        if len(f) <= budget * 1.02 or not progress:
            break
    out_region = np.zeros(len(v), dtype=np.int64)
    out_region[mapping] = vregion
    face_region = out_region[f[:, 0]]
    # weld: border vertices survive untouched, one per region copy; join the copies of each source vertex
    kept = np.bincount(mapping, minlength=len(v))[mapping] == 1
    weld = np.arange(len(v))
    if kept.any():
        order = np.lexsort((mapping[kept], source[kept]))
        src, out = source[kept][order], mapping[kept][order]
        first = np.r_[True, src[1:] != src[:-1]]
        weld[out] = out[np.flatnonzero(first)[np.cumsum(first) - 1]]
    # the simplifier can also put a vertex exactly onto a locked border vertex next to it: join those now, while
    # they're at one place (moving one first, as projecting and relaxing do, would leave slivers, and the vertices
    # still at one place no longer joined by an edge: crowded edges, #61)
    f, face_region = drop_twins(*merge_coincident(v, weld[f], face_region))
    used, inverse = np.unique(f, return_inverse=True)
    v, f, face_region = unpinch(v[used], inverse.reshape(-1, 3).astype(np.int64), face_region)
    # borders (vertices shared by faces of two regions) stay exactly where they are; other vertices belong to one
    vertex_region = np.full(len(v), -1)
    np.maximum.at(vertex_region, f.reshape(-1), np.repeat(face_region, 3))
    border = np.zeros(len(v), dtype=bool)
    np.logical_or.at(border, f.reshape(-1), vertex_region[f.reshape(-1)] != np.repeat(face_region, 3))
    if fields is None or region_piece is None:
        v = relax(field, Mesh(project(field, v, step * 2), f), border, step).vertices
    else:
        piece = region_piece[vertex_region]
        for k, piece_field in enumerate(fields):
            mine = piece == k
            v[mine] = project(piece_field, v[mine], step * 2)
        for k, piece_field in enumerate(fields):
            v = relax(piece_field, Mesh(v, f), border | (piece != k), step).vertices
    f, face_region = drop_twins(*merge_coincident(v, f, face_region))
    used, inverse = np.unique(f, return_inverse=True)
    return Mesh(v[used], inverse.reshape(-1, 3).astype(np.int64)), face_region


def merge_coincident(vertices: Array, faces: Array, *extra: Array) -> tuple[Array, ...]:
    """Join the ends of edges of no length and drop the faces that leaves without area. Decimation can leave two
    vertices at one place without joining them; seen as one point (as the crack check sees them), their faces
    pinch (four faces on an edge). Other per-face arrays in `extra` are filtered alike."""
    key = np.round(vertices, 9)
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    e = e[(key[e[:, 0]] == key[e[:, 1]]).all(axis=1) & (e[:, 0] != e[:, 1])]
    if not len(e):
        return (faces, *extra)
    into = np.arange(len(vertices))
    for _ in range(len(e)):  # chains of coincident vertices: until every one points at the chain's lowest
        before = into.copy()
        np.minimum.at(into, e[:, 0], into[e[:, 1]])
        np.minimum.at(into, e[:, 1], into[e[:, 0]])
        if np.array_equal(into, before):
            break
    f = into[faces]
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])
    return (f[keep], *(x[keep] for x in extra))


def drop_twins(faces: Array, *extra: Array) -> tuple[Array, ...]:
    """Remove pairs of faces on the same three vertices facing opposite ways: zero-volume fins that decimation can
    leave on thin parts; they make the mesh non-manifold (four faces on one edge). Other per-face arrays in
    `extra` are filtered alike."""
    key = np.sort(faces, axis=1)
    order = np.lexsort((key[:, 2], key[:, 1], key[:, 0]))
    k = key[order]
    same = np.flatnonzero((k[1:] == k[:-1]).all(axis=1))
    drop = np.zeros(len(faces), dtype=bool)
    for i in same:
        a, b = order[i], order[i + 1]
        if drop[a] or drop[b]:
            continue
        # opposite winding: b is a's vertices in reverse cyclic order
        fa, fb = faces[a].tolist(), faces[b].tolist()
        rot = fa.index(fb[0])
        if [fa[rot], fa[(rot - 1) % 3], fa[(rot - 2) % 3]] == fb:
            drop[a] = drop[b] = True
    keep = ~drop
    return (faces[keep], *(x[keep] for x in extra))


def open_edges(vertices: Array, faces: Array) -> Array:
    """Edges (pairs of vertex indices) with a face on one side only: cracks in what should be a closed surface.
    Vertices at the same place count as one (colour borders may duplicate them)."""
    if not len(faces):
        return np.zeros((0, 2), dtype=np.int64)
    _, first, inverse = np.unique(np.round(vertices, 9), axis=0, return_index=True, return_inverse=True)
    f = first[inverse.reshape(-1)][faces]
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
    e = e[e[:, 0] != e[:, 1]]
    fwd = e[:, 0] * len(vertices) + e[:, 1]
    rev = e[:, 1] * len(vertices) + e[:, 0]
    return np.asarray(e[~np.isin(fwd, rev)])


def pinches(vertices: Array, faces: Array) -> tuple[Array, Array]:
    """Where a closed surface isn't a manifold: edges (vertex pairs) with more than two faces, and other vertices whose
    faces don't form one fan (two sheets touching at a point). Vertices at the same place count as one."""
    if not len(faces):
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0, dtype=np.int64)
    _, first, inverse = np.unique(np.round(vertices, 9), axis=0, return_index=True, return_inverse=True)
    f = first[inverse.reshape(-1)][faces]
    f = f[(f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 2] != f[:, 0])]
    label, crowded = _fans(vertices, f, False)
    fans = np.bincount(f.reshape(-1)[np.unique(label)], minlength=len(vertices))
    return crowded, np.setdiff1d(np.flatnonzero(fans > 1), crowded)  # (a crowded edge's ends have several fans too)


POCKET_FACES = 16  # a piece this small cut off a bigger one by `unpinch` is a pocket of folded faces: it goes


def unpinch(vertices: Array, faces: Array, *extra: Array) -> tuple[Array, ...]:
    """Split every vertex whose faces form several fans (the simplifier doesn't check that an edge's two ends share
    only the vertices across it, so on thin parts and in narrow gaps it can join the two sides: an edge with four
    faces, or two sheets touching at a vertex) into one vertex per fan, each moved halfway towards the middle of its
    own fan so that pulling it back onto the surface puts it on its own side. A collapse that folded a few faces in
    on themselves leaves them a closed pocket of their own: pockets are dropped. Other per-face arrays in `extra` are
    filtered alike."""
    if not len(faces):
        return (vertices, faces, *extra)
    label, _ = _fans(vertices, faces, True)
    roots = np.unique(label)
    owner = faces.reshape(-1)[roots]
    if len(np.unique(owner)) == len(roots):
        return (vertices, faces, *extra)
    order = np.lexsort((roots, owner))
    first = np.r_[True, owner[order][1:] != owner[order][:-1]]
    vertex_of = np.empty(len(roots), dtype=np.int64)
    vertex_of[order[first]] = owner[order[first]]
    vertex_of[order[~first]] = len(vertices) + np.arange(int((~first).sum()))
    new_faces = vertex_of[np.searchsorted(roots, label)].reshape(-1, 3)
    split = np.zeros(len(vertices), dtype=bool)
    split[owner[order[~first]]] = True
    v = np.concatenate([vertices, vertices[owner[order[~first]]]])
    # every fan of a split vertex: towards the middle of the other corners of its faces
    corner = np.flatnonzero(split[faces.reshape(-1)])
    mine = new_faces.reshape(-1)[corner]
    rows = new_faces[corner // 3]
    total = np.zeros_like(v)
    count = np.zeros(len(v))
    np.add.at(total, mine, v[rows].sum(axis=1) - v[mine])
    np.add.at(count, mine, 2.0)
    moved = np.unique(mine)
    v[moved] += (total[moved] / count[moved, None] - v[moved]) * 0.5
    # the pieces each connected piece fell into: all but the biggest go if they're pockets
    was = _join(len(vertices), faces[:, :2].reshape(-1), faces[:, 1:].reshape(-1))[faces[:, 0]]
    now = _join(len(v), new_faces[:, :2].reshape(-1), new_faces[:, 1:].reshape(-1))[new_faces[:, 0]]
    piece, of_face, size = np.unique(now, return_inverse=True, return_counts=True)
    source = np.zeros(len(piece), dtype=np.int64)
    source[of_face] = was
    biggest = np.zeros(int(was.max()) + 1, dtype=np.int64)
    np.maximum.at(biggest, source, size)
    keep = ((size >= POCKET_FACES) | (size == biggest[source]))[of_face]
    return (v, new_faces[keep], *(x[keep] for x in extra))


def _fans(vertices: Array, f: Array, pair_crowded: bool) -> tuple[Array, Array]:
    """Every face corner's fan (the lowest corner in it) and the edges with more than two faces. Two faces on an edge
    join their corners at both ends, so a vertex's corners joined that way are one fan; with `pair_crowded`, the
    faces on a crowded edge pair up too (`_pair_crowded`)."""
    # half-edge k of face i runs from corner 3i + k to corner 3i + (k + 1) % 3
    corner = np.arange(f.size).reshape(-1, 3)
    start, end = f.reshape(-1), np.roll(f, -1, axis=1).reshape(-1)
    next_corner = np.roll(corner, -1, axis=1).reshape(-1)
    key = np.minimum(start, end) * len(vertices) + np.maximum(start, end)
    order = np.argsort(key, kind="stable")
    _, first_of, count = np.unique(key[order], return_index=True, return_counts=True)
    many = count > 2
    crowded = np.sort(np.stack([start[order[first_of[many]]], end[order[first_of[many]]]], axis=1), axis=1)
    pair = first_of[count == 2]
    h1, h2 = order[pair], order[pair + 1]
    ok = start[h1] == end[h2]  # opposite directions
    h1, h2 = h1[ok], h2[ok]
    a, b = np.concatenate([h1, next_corner[h1]]), np.concatenate([next_corner[h2], h2])
    label = _join(f.size, a, b)
    if pair_crowded and many.any():
        extra_a, extra_b = [a], [b]
        for i, n in zip(first_of[many], count[many], strict=True):
            half = order[i : i + n]
            at_a = np.where(start[half] == start[half[0]], half, next_corner[half])  # each face's corner at either end
            at_b = np.where(start[half] == start[half[0]], next_corner[half], half)
            k = _pair_crowded(label, start, half, at_a, at_b)
            extra_a += [at_a[k[:, 0]], at_b[k[:, 0]]]
            extra_b += [at_a[k[:, 1]], at_b[k[:, 1]]]
        label = _join(f.size, np.concatenate(extra_a), np.concatenate(extra_b))
    return label, crowded


def _join(n: int, a: Array, b: Array) -> Array:
    """Connected groups of n items joined pairwise (a[i] with b[i]): each item's lowest member."""
    label = np.arange(n)
    while True:
        before = label
        lowest = np.minimum(label[a], label[b])
        label = label.copy()
        np.minimum.at(label, a, lowest)
        np.minimum.at(label, b, lowest)
        label = label[label]
        if np.array_equal(label, before):
            return label


def _pair_crowded(label: Array, start: Array, half: Array, at_a: Array, at_b: Array) -> Array:
    """The faces on one crowded edge (its half-edges `half`) in pairs (indices into `half`). Around an end of the edge,
    the faces form open fans that each begin and end on the edge (a collapse joined two vertices that shared a
    neighbour besides the ones across their edge): the two faces ending one fan pair up, which splits that end back
    into one vertex per fan. Without such an end, all of them are joined (the edge stays crowded)."""
    forward = start[half] == start[half[0]]
    for at in (at_a, at_b):
        fan = label[at]
        order = np.argsort(fan, kind="stable")
        same = fan[order]
        if len(half) % 2 == 0 and (same[0::2] == same[1::2]).all() and (same[1:-1:2] != same[2::2]).all():
            k = order.reshape(-1, 2)
            if (forward[k[:, 0]] != forward[k[:, 1]]).all():
                return k
    n = len(half)
    return np.stack([np.zeros(n - 1, dtype=np.int64), np.arange(1, n)], axis=1)


def crack_groups(edges: Array) -> list[Array]:
    """Open edges (from `open_edges`) grouped into connected cracks, biggest first (ties: lowest vertex first)."""
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        parent.setdefault(i, i)
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in edges.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    roots = np.array([find(int(a)) for a in edges[:, 0]], dtype=np.int64) if len(edges) else np.zeros(0, np.int64)
    groups = [np.flatnonzero(roots == r) for r in np.unique(roots)]
    return sorted(groups, key=lambda g: (-len(g), int(edges[g].min())))


def remove_unused(mesh: Mesh) -> Mesh:
    used, inverse = np.unique(mesh.faces, return_inverse=True)
    return Mesh(mesh.vertices[used], inverse.reshape(-1, 3).astype(np.int64))


def component_labels(mesh: Mesh) -> Array:
    """A connected-piece label per vertex (unused vertices get their own)."""
    n = len(mesh.vertices)
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    for a, b in np.concatenate([mesh.faces[:, [0, 1]], mesh.faces[:, [1, 2]]]):
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    return np.array([find(i) for i in range(n)])


def components(mesh: Mesh) -> int:
    """Number of connected pieces (floating parts are usually a modelling mistake)."""
    n = len(mesh.vertices)
    parent = np.arange(n)

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = int(parent[i])
        return i

    for a, b in np.concatenate([mesh.faces[:, [0, 1]], mesh.faces[:, [1, 2]]]):
        ra, rb = find(int(a)), find(int(b))
        if ra != rb:
            parent[ra] = rb
    used = np.unique(mesh.faces)
    return len({find(int(i)) for i in used})
