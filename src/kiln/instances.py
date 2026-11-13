"""Other models placed in a model (`instances:`, #171): each is that model's own build (its mesh, at its own detail),
moved into place and merged into the scene's mesh after it is built, so previews, the glb, Godot and LODs take it as
any other surface. Its faces move with the part named by `id` (the root by default). Its decals and textures come
along (placed back in its own frame, #295) unless it is scaled; its baked maps don't."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from kiln.export import Built
from kiln.notation import Instance
from kiln.paint import Painted, PaintGroup
from kiln.sdf import Copy, rotation_matrix

if TYPE_CHECKING:
    from kiln.project import Project


class InstanceError(Exception):
    pass


def instance_builds(project: Project, built: Built, seen: tuple[str, ...] = (), share: float = 1.0) -> list[tuple[Instance, Built]]:
    """Each instance's own build (its own instances placed in it), in order; `share` < 1: built at that share of its
    triangles (a scene LOD)."""
    from kiln.builder import build_cached
    from kiln.notation import MODEL_SUFFIX

    out = []
    for inst in built.model.instances:
        if inst.model in seen or inst.model == built.model.name:
            raise InstanceError(f"instances go round in a circle: {' -> '.join((*seen, built.model.name, inst.model))}")
        path = (built.model.path.parent if built.model.path is not None else project.models_dir) / f"{inst.model}{MODEL_SUFFIX}"
        if not path.is_file():
            raise InstanceError(f"instances: no models/{inst.model}{MODEL_SUFFIX}")
        model, style, findings = project.load(path)
        errors = [f for f in findings if f.severity == "error"]
        if model is None or style is None or errors:
            raise InstanceError(f"instances: {inst.model} doesn't load ({errors[0].format() if errors else 'no model'})")
        if model.template or model.terrain is not None or model.scatter is not None:
            raise InstanceError(f"instances: {inst.model} is a {'template' if model.template else 'terrain' if model.terrain else 'scatter'}, not a model to place")
        palette, _ = project.palette(model.palette)
        cache = project.root / ".kiln-cache"
        sub = build_cached(model, style, palette, cache)
        if share < 1.0:
            sub = build_cached(model, style, palette, cache, max(12, int(sub.triangles * share)))
        out.append((inst, place(project, sub, (*seen, built.model.name), share)))
    return out


def place(project: Project, built: Built, seen: tuple[str, ...] = (), share: float = 1.0) -> Built:
    """`built` with its instances merged in (unchanged without any); `share`: a LOD's share of the full triangles."""
    if not built.model.instances:
        return built
    if built.bake is not None:
        raise InstanceError("instances: a model with a normal map or relief can't place other models yet (#295)")
    p = built.painted
    vertices, faces, face_group, face_decal = [p.vertices], [p.faces], [p.face_group], [p.face_decal]
    groups = list(p.groups)
    decals = list(p.decals)
    index = {g: i for i, g in enumerate(groups)}
    normals = [built.normals]
    ao = [built.ao] if built.ao is not None else None
    joints = [built.joints] if built.joints is not None else None
    weights = [built.weights] if built.weights is not None else None
    count = len(p.vertices)
    for inst, sub in instance_builds(project, built, seen, share):
        q = sub.painted
        r = rotation_matrix(inst.rotate)
        vertices.append((q.vertices - sub.origin()) @ r.T * inst.scale + np.asarray(inst.at))  # its origin at `at`, as its glb
        faces.append(q.faces + count)
        remap = []
        for g in q.groups:
            key = PaintGroup(inst.bone, g.color, g.color_name, g.material)
            if key not in index:
                index[key] = len(groups)
                groups.append(key)
            remap.append(index[key])
        face_group.append(np.asarray(remap, dtype=np.int64)[q.face_group] if len(q.face_group) else q.face_group)
        dmap = []
        for d in q.decals:  # (#295) each decal back in the instance's own frame: a rigid copy (not when scaled)
            if abs(inst.scale - 1.0) > 1e-9:
                dmap.append(-1)
                continue
            placed_ = replace(d, copy=_compose(Copy(r, sub.origin(), np.asarray(inst.at, float) - sub.origin()), d.copy))
            if placed_ not in decals:
                decals.append(placed_)
            dmap.append(decals.index(placed_))
        face_decal.append(np.where(q.face_decal >= 0, np.asarray([*dmap, -1], dtype=p.face_decal.dtype)[q.face_decal], -1))
        normals.append(sub.normals @ r.T)
        if ao is not None:
            ao.append(sub.ao if sub.ao is not None else np.ones((len(q.faces), 3)))
        if joints is not None and weights is not None:
            bone = built.skeleton.index(inst.bone)
            j = np.zeros((len(q.vertices), joints[0].shape[1]), dtype=joints[0].dtype)
            j[:, 0] = bone
            w = np.zeros((len(q.vertices), weights[0].shape[1]), dtype=weights[0].dtype)
            w[:, 0] = 1.0
            joints.append(j)
            weights.append(w)
        count += len(q.vertices)
    painted = Painted(np.concatenate(vertices), np.concatenate(faces), np.concatenate(face_group), groups, np.concatenate(face_decal), decals)
    return replace(built, own_triangles=built.own_triangles or built.triangles, painted=painted, normals=np.concatenate(normals), ao=np.concatenate(ao) if ao is not None else None,
                   joints=np.concatenate(joints) if joints is not None else None, weights=np.concatenate(weights) if weights is not None else None)  # fmt: skip


def _compose(outer: Copy, inner: tuple[float, ...] | None) -> tuple[float, ...]:
    """A decal's copy (plain numbers, as Decal keeps it) mapping scene points back through `outer` (the instance's
    placement) and then `inner` (the decal's own per-copy motion, if any) into the frame it was made in."""
    from kiln.paint import _copy_key

    if inner is None:
        return _copy_key(outer)
    k = np.asarray(inner, dtype=float)
    r2, piv2, off2 = k[:9].reshape(3, 3), k[9:12], k[12:15]
    a1, a2 = outer.offset + outer.pivot, off2 + piv2
    rot = outer.rotation @ r2
    # f2(f1(p)) = (p - a1) @ R1 @ R2 + (piv1 - a2) @ R2 + piv2 = (p - o) @ R with pivot 0
    o = a1 - ((outer.pivot - a2) @ r2 + piv2) @ rot.T
    return _copy_key(Copy(rot, np.zeros(3), o))


def joined_pieces(vertices: np.ndarray, faces: np.ndarray, gap: float) -> int:
    """Separate pieces, counting those within about `gap` of each other as one: an instance set against the model
    (a link between two clasp halves) joins them though they share no vertex (#333)."""
    return int(len(np.unique(piece_labels(vertices, faces, gap)[np.unique(faces)])))


def piece_labels(vertices: np.ndarray, faces: np.ndarray, gap: float) -> np.ndarray:
    """Each vertex's piece (a representative vertex index): pieces within about `gap` of each other are one (#173: a
    smooth detail on a hard part, hard parts that touch face to face)."""
    n = len(vertices)
    parent = np.arange(n)

    def find(i: np.ndarray) -> np.ndarray:
        while True:
            up = parent[i]
            if np.array_equal(up, i):
                return i
            parent[i] = parent[up]
            i = parent[i]

    def union(a: np.ndarray, b: np.ndarray) -> None:
        for _ in range(64):  # pointer jumping until settled
            ra, rb = find(a.copy()), find(b.copy())
            differ = ra != rb
            if not differ.any():
                return
            lo, hi = np.minimum(ra[differ], rb[differ]), np.maximum(ra[differ], rb[differ])
            parent[hi] = lo

    used = np.unique(faces)
    for k in range(3):
        union(faces[:, k], faces[:, (k + 1) % 3])
    for shift in (0.0, 0.5):  # vertices in one cell of a grid `gap` wide (and a grid offset by half) join
        cells = np.floor(vertices[used] / gap + shift).astype(np.int64)
        _, inverse = np.unique(cells, axis=0, return_inverse=True)
        first = np.full(inverse.max() + 1, -1)
        first[inverse[::-1]] = used[::-1]
        union(used, first[inverse])
    out = np.arange(n)
    out[used] = find(used.copy())
    return out
