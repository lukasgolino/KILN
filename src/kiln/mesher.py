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


def dual_contour(field: Field, step: float) -> Mesh:
    lo, dims, values = _grid(field, step)
    nx, ny, nz = dims
    inside = values < 0
    cell_dims = (nx - 1, ny - 1, nz - 1)

    # crossing edges, their surface points and normals
    points_list, normals_list, edges_list = [], [], []
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
    if not points_list:
        return Mesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    all_points = np.concatenate(points_list)
    all_normals = field.gradient(all_points, step * 0.1)
    offsets = np.cumsum([0] + [len(p) for p in points_list])
    for i in range(len(points_list)):
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
    active, compact = np.unique(np.concatenate([e[0].reshape(-1) for e in edges]), return_inverse=True)
    compact = compact.reshape(-1)
    # accumulate each cell's QEF from the (up to 12) crossed edges around it
    n = len(active)
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
    x = np.clip(x, cell_lo - 0.25 * step, cell_lo + 1.25 * step)

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
    v = project(field, np.asarray(v, dtype=np.float64), step * 2)
    (f,) = drop_twins(np.asarray(f, dtype=np.int64))
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
    f, face_region = drop_twins(weld[f], face_region)
    used, inverse = np.unique(f, return_inverse=True)
    v, f = v[used], inverse.reshape(-1, 3).astype(np.int64)
    # borders (vertices shared by faces of two regions) stay exactly where they are; other vertices belong to one
    vertex_region = np.full(len(v), -1)
    np.maximum.at(vertex_region, f.reshape(-1), np.repeat(face_region, 3))
    border = np.zeros(len(v), dtype=bool)
    np.logical_or.at(border, f.reshape(-1), vertex_region[f.reshape(-1)] != np.repeat(face_region, 3))
    if fields is None or region_piece is None:
        return relax(field, Mesh(project(field, v, step * 2), f), border, step), face_region
    piece = region_piece[vertex_region]
    for k, piece_field in enumerate(fields):
        mine = piece == k
        v[mine] = project(piece_field, v[mine], step * 2)
    for k, piece_field in enumerate(fields):
        v = relax(piece_field, Mesh(v, f), border | (piece != k), step).vertices
    return Mesh(v, f), face_region



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
