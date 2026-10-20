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


def model_step(field: Field, resolution: float) -> float:
    """Grid step for a model: the style's resolution for a ~1 m model, coarser (by the square root of the size)
    for bigger ones, and never more than MAX_CELLS cells across."""
    lo, hi = field.bounds()
    size = float((hi - lo).max())
    return grid_step(size, resolution * max(size, 1.0) ** 0.5)


def dual_contour(field: Field, step: float) -> Mesh:
    lo, hi = field.bounds()
    lo = lo - 2.5 * step
    dims = tuple(int(math.ceil(v)) + 1 for v in ((hi + 2.5 * step - lo) / step))
    nx, ny, nz = dims
    values = sample(field, lo, step, dims)  # type: ignore[arg-type]
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

    # accumulate each cell's QEF from the (up to 12) crossed edges around it
    n_cells = cell_dims[0] * cell_dims[1] * cell_dims[2]
    ata = np.zeros((n_cells, 3, 3))
    atb = np.zeros((n_cells, 3))
    mass = np.zeros((n_cells, 3))
    count = np.zeros(n_cells)
    quads = []
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
        outer = nrm[:, :, None] * nrm[:, None, :]
        dot = (nrm * pts).sum(axis=1)
        for k in range(4):
            np.add.at(ata, flat[:, k], outer)
            np.add.at(atb, flat[:, k], nrm * dot[:, None])
            np.add.at(mass, flat[:, k], pts)
            np.add.at(count, flat[:, k], 1.0)
        quads.append((flat, lower_inside, axis))

    active = np.flatnonzero(count)
    m = mass[active] / count[active, None]
    a_mat = ata[active] + 0.05 * np.eye(3)
    rhs = atb[active] - np.einsum("nij,nj->ni", ata[active], m)
    x = m + np.linalg.solve(a_mat, rhs[:, :, None])[:, :, 0]
    cell_idx = np.stack(np.unravel_index(active, cell_dims), axis=1)
    cell_lo = lo + cell_idx * step
    x = np.clip(x, cell_lo - 0.25 * step, cell_lo + 1.25 * step)
    vertex_of = np.full(n_cells, -1, dtype=np.int64)
    vertex_of[active] = np.arange(len(active))

    faces = []
    for flat, lower_inside, axis in quads:
        q = vertex_of[flat]  # (E, 4)
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
    keep = (f[:, 0] != f[:, 1]) & (f[:, 1] != f[:, 2]) & (f[:, 0] != f[:, 2])
    return Mesh(x, f[keep].astype(np.int64))


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
    v, f = fast_simplification.simplify(
        mesh.vertices.astype(np.float64), mesh.faces.astype(np.int32), target_count=int(budget), agg=6.0
    )
    v = project(field, np.asarray(v, dtype=np.float64), step * 2)
    return Mesh(v, np.asarray(f, dtype=np.int64))


def remove_unused(mesh: Mesh) -> Mesh:
    used, inverse = np.unique(mesh.faces, return_inverse=True)
    return Mesh(mesh.vertices[used], inverse.reshape(-1, 3).astype(np.int64))


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
