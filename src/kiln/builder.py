"""One model -> Built (field, mesh, paint, normals, rig, animations), with a cache in `.kiln-cache/`.

Meshing is the slow step (seconds); the cache key covers everything that changes the result: the model text,
the style, the palette, decal images, imported files and KILN's version.
"""

from __future__ import annotations

import hashlib
import math
import json
import pickle
from pathlib import Path

import numpy as np

from kiln import __version__
from kiln.export import Built
from kiln.hard import HARD_SHAPES, SHELL_SHAPES, HardMesh, HardSpec, Solid, solid, subtract, to_mesh, union
from kiln.hard import corner_normals as hard_corner_normals
from kiln.hard import intersect
from kiln.mesher import Mesh, component_labels, components, decimate, decimate_regions, dual_contour, model_step, simplify_borders
from kiln.notation import ROOT_ID, Decal, Model, Part
from kiln.paint import PaintGroup, Painted, Regions, corner_normals, hard_regions, paint, regions
from kiln.rig import Bone, Skeleton, build_skeleton, soft_weights, tracks
from kiln.sdf import Array, Field, part_thickness
from kiln.style import Style

BUILDER_VERSION = 11  # bump when meshing/painting changes output
BORDER_SCHEDULE = (0.04, 0.06, 0.08, 0.15, 0.3)  # how far borders may stray, x the target edge length, in turn
PRESHAPE = 3  # x the budget: decimate freely to this first, then cut colour borders and keep them
PROTECT = 2.0  # parts thinner than this many budget-sized triangle edges keep their outline
LOST_AREA = 0.25  # a part keeping less of its surface than this through decimation is lost (lint W111)
HARD_SHARE = 0.75  # hard parts may take this much of the budget before they lose detail (bevels, then sides)
KEEP_SIZE = 0.02  # crisp parts smaller than this share of the model are kept at every LOD (rivets, eyes, crests)
KEEP_MIN = 48  # triangles a kept part keeps at least


def field_of(model: Model, step: float) -> Field:
    return Field([p.geometry for p in model.parts], margin=step * 3)


def hard_parts(model: Model, style: Style) -> frozenset[int]:
    """Adding parts made as exact polygons: those asking for it (hard: true, sides, bevel, chamfer, blend: none)
    unless the style says never, and with `hard_surface = "always"` every part that can (the soft-skinned body of a
    character stays smooth: its joints bend by blending)."""
    separate = {pid for pid, e in model.rig.items() if e.separate}
    out = set()
    for i, p in enumerate(model.parts):
        g = p.geometry
        if g.op != "add" or g.shape not in HARD_SHAPES or g.twist or g.noise is not None or (g.shell and g.shape not in SHELL_SHAPES) \
                or g.fit is not None:
            continue
        if p.hard is not None:
            if p.hard:
                out.add(i)
            continue
        if style.hard_surface == "never":
            continue
        asks = p.crisp or p.bevel > 0 or "sides" in g.params
        body = model.skin == "soft" and p.id not in separate
        if asks or (style.hard_surface == "always" and not body):
            out.add(i)
    return frozenset(out)


def kept_parts(model: Model, hard: frozenset[int]) -> frozenset[int]:
    """Smooth parts made as their own small mesh that every reduction keeps (`keep: true`, or small crisp parts:
    rivets, pupils, crests). They sit in the surface around them instead of blending, so a part with a blend only
    goes this way when it asks."""
    separate = {pid for pid, e in model.rig.items() if e.separate} if model.skin != "none" else set()
    adding = [i for i, p in enumerate(model.parts) if p.geometry.op == "add"]
    boxes = [model.parts[i].geometry.bounds() for i in adding]
    lo, hi = np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)
    size = float(np.linalg.norm(hi - lo))
    out = set()
    for i, (blo, bhi) in zip(adding, boxes, strict=True):
        p = model.parts[i]
        if i in hard or p.id in separate or p.keep is False or len(adding) == 1:
            continue
        if p.keep or (p.geometry.blend == 0 and float(np.linalg.norm(bhi - blo)) < KEEP_SIZE * size):
            out.add(i)
    return frozenset(out)


def hard_spec(part: Part, style: Style, level: int = 0) -> HardSpec:
    """How finely a hard part is made (a shape's `round` is a chamfer). Lower `level`s of detail (LODs, tight
    budgets) turn bevels into chamfers, then drop them, then halve the sides of round shapes."""
    g = part.geometry
    sides = int(g.params.get("sides") or style.hard_sides)
    bevel, segments = part.bevel, part.segments
    if not bevel and g.shape in ("box", "cylinder", "extrude") and float(g.params.get("round", 0.0)) > 0:
        bevel, segments = float(g.params["round"]), 1
    if level >= 1:
        segments = 1
    if level >= 2:
        bevel = 0.0
    if level >= 3:
        sides = max(min(sides, 6), sides >> (level - 2))
    return HardSpec(sides, bevel, segments)


def _hard_solid(model: Model, style: Style, include: frozenset[int], level: int) -> Solid:
    """The hard parts of one piece combined in order: adding parts unite; every later cut or intersect applies."""
    acc: Solid = []
    for i, p in enumerate(model.parts):
        g = p.geometry
        if g.op == "add":
            if i in include:
                acc = union(acc, solid(g, hard_spec(p, style, level), i))
        elif acc and g.shape in HARD_SHAPES and not g.twist and g.noise is None and not (g.shell and g.shape not in SHELL_SHAPES) \
                and (g.cut_only is None or bool(g.cut_only & include)):
            other = solid(g, hard_spec(p, style, level), i)
            acc = subtract(acc, other) if g.op == "cut" else intersect(acc, other)
    return acc


def build_hard(model: Model, style: Style, field: Field, pieces: list[frozenset[int]], budget: float, rigged: bool) -> tuple[list[Regions], list[HardMesh]]:
    """Every piece's hard parts as a mesh (fewer details while they'd go over `budget`), cut into paint groups."""
    meshes: list[HardMesh] = []
    for level in range(5):
        meshes = [to_mesh(_hard_solid(model, style, include, level)) for include in pieces]
        if sum(m.triangles for m in meshes) <= budget or level == 4:
            break
    out = []
    for include, mesh in zip(pieces, meshes, strict=True):
        part = mesh.face_part.copy()
        # faces a cut made (a hole's walls) belong to the part they're in
        foreign = ~np.isin(part, sorted(include))
        if foreign.any():
            centres = mesh.vertices[mesh.faces[foreign]].mean(axis=1)
            own = sorted(include)
            d = np.stack([field.part_distance(i, centres) for i in own])
            part[foreign] = np.asarray(own)[d.argmin(axis=0)]
        out.append(hard_regions(Mesh(mesh.vertices, mesh.faces), part, model, rigged))
    return out, meshes


def build_model(model: Model, style: Style, budget: int | None = None, palette: dict[str, str] | None = None) -> Built:
    if model.source is not None:
        from kiln.importer import build_imported

        return build_imported(model, style, palette)
    field = field_of(model, 0.01)
    for part in model.parts:
        lo, hi = part.geometry.bounds()
        probe = np.array([lo, hi, (lo + hi) / 2])
        if not (np.isfinite(lo).all() and np.isfinite(hi).all() and np.isfinite(part.geometry.distance(probe)).all()):
            raise ValueError(f"{part.where} ({part.geometry.shape}) has no valid surface (its numbers give NaN); check its points")
    step = model_step(field, style.resolution)
    field = field_of(model, step)
    target = budget or model.budget or style.budget(model.cls)
    rigged = model.skin != "none"
    hard = hard_parts(model, style)
    # `separate` parts (a detachable helmet) are meshed on their own: their own closed surface, not fused into the
    # body, so detaching one leaves no hole. The rest is the main piece.
    separate = sorted(pid for pid, entry in model.rig.items() if entry.separate) if rigged else []
    adding = [i for i, p in enumerate(model.parts) if p.geometry.op == "add"]
    # fitted shells (armour wrapping a body, a gap away) are their own pieces too: meshed with what they wrap, the thin
    # air gap between the two surfaces would tear both
    fitted = sorted({model.parts[i].id for i in adding if model.parts[i].geometry.fit is not None and model.parts[i].id not in separate})
    own = set(separate) | set(fitted)
    all_pieces = [[i for i in adding if model.parts[i].id not in own]]
    all_pieces += [[i for i in adding if model.parts[i].id == pid] for pid in [*separate, *fitted]]
    # hard parts are exact polygons, made first: what they leave of the budget goes to the smooth parts
    hard_pieces = [frozenset(i for i in inc if i in hard) for inc in all_pieces]
    hard_pieces = [inc for inc in hard_pieces if inc]
    any_soft = any(i not in hard for i in adding)
    hard_cut, hard_meshes = build_hard(model, style, field, hard_pieces, target * (HARD_SHARE if any_soft else 1.0), rigged) if hard_pieces else ([], [])
    hard_triangles = sum(r.mesh.triangles for r in hard_cut)
    kept = kept_parts(model, hard)
    groups_of = [[i for i in inc if i not in hard and i not in kept] for inc in all_pieces]
    pieces = [(include, field.only(include)) for include in groups_of if include]
    meshes = [dual_contour(f, step) for _, f in pieces]
    kept_cut, kept_hidden = _kept(model, style, field, sorted(kept), step, target, meshes, rigged)
    kept_triangles = sum(len(p.faces) for p, _ in kept_cut)
    if sum(m.triangles for m in meshes) + hard_triangles + kept_triangles == 0:
        raise ValueError("the model has no surface (everything cut away, or all parts are cuts)")
    live = [(include, f, mesh) for (include, f), mesh in zip(pieces, meshes, strict=True) if mesh.triangles]
    taken = hard_triangles + kept_triangles
    soft_target = max(target - taken, int(target * (1 - HARD_SHARE))) if taken else target
    hidden: tuple[int, ...] = ()
    lost: tuple[int, ...] = ()
    painted: Painted | None = None
    normals = np.zeros((0, 3, 3))
    if live:
        # thin parts the budget's triangle size would erase (plates, wheels, posts) keep their outline like a colour
        area = sum(_area(mesh.vertices, mesh.faces) for _, _, mesh in live)
        edge = math.sqrt(4 * area / (math.sqrt(3) * soft_target))
        protect = frozenset(i for i in adding if (t := part_thickness(model.parts[i].geometry)) is not None
                            and t < PROTECT * edge)  # fmt: skip
        full_areas = [_areas(f, mesh.vertices, mesh.faces, include, step) for include, f, mesh in live]  # (W101, W111)
        # First shape the surface freely (triangles go where the shape needs them: wheels stay round), then cut the colour
        # borders into that and keep them through the rest (seams stay clean)
        total = sum(mesh.triangles for _, _, mesh in live)
        live = [(include, f, decimate(f, mesh, max(200, round(PRESHAPE * soft_target * mesh.triangles / total)), step)) for include, f, mesh in live]
        cut, region_piece = _join([regions(mesh, model, f, rigged, include, protect) for include, f, mesh in live])
        fields = [f for _, f, _ in live]
        painted, normals, hidden, lost = _decimate(model, style, fields, cut, region_piece, step, soft_target, [inc for inc, _, _ in live], full_areas)
    floating = 1
    if groups_of[0] and painted is not None:  # separate parts may float
        main_faces = np.flatnonzero(region_piece[painted.face_group] == 0)
        floating = _pieces(model, field, Mesh(painted.vertices, painted.faces[main_faces]), step)
    hidden = tuple(sorted({*hidden, *kept_hidden}))
    if kept_cut:
        painted, normals = _merge([painted] if painted is not None else [], [normals] if len(normals) else [],
                                  [p for p, _ in kept_cut], [n for _, n in kept_cut])  # fmt: skip
    n_soft = len(painted.vertices) if painted is not None else 0
    if hard_cut:
        hard_painted = [paint(r, model) for r in hard_cut]
        hard_normals = [hard_corner_normals(HardMesh(hp.vertices, hp.faces, hp.face_group, _face_normals(hp), np.zeros(0, np.int64)),
                                            style.smooth, style.sharp_angle) for hp in hard_painted]  # fmt: skip
        painted, normals = _merge([painted] if painted is not None else [], [normals] if len(normals) else [], hard_painted, hard_normals)
        hidden = tuple(sorted({*hidden, *(i for inc, m in zip(hard_pieces, hard_meshes, strict=True) for i in inc if i not in set(m.face_part.tolist()))}))
        if hard_pieces[0] <= frozenset(all_pieces[0]):  # the main piece has hard parts: they may float too
            soft_points = painted.vertices[:n_soft] if n_soft else np.zeros((0, 3))
            floating = _hard_floating(model, field, hard_meshes[0], soft_points, groups_of[0], step, floating)
    assert painted is not None
    skeleton = build_skeleton(model, field) if rigged else Skeleton([Bone(ROOT_ID, -1, np.zeros(3), {}, False)])
    joints = weights = None
    if model.skin == "soft":
        joints, weights = soft_weights(painted.vertices, model, field, skeleton, step)
        if len(painted.vertices) > n_soft:  # hard parts don't bend: each vertex follows its own part's bone
            names = [b.name for b in skeleton.bones]
            bone = np.zeros(len(painted.vertices), dtype=np.int64)
            hard_faces = np.flatnonzero(painted.faces.max(axis=1) >= n_soft)
            for fi in hard_faces:
                bone[painted.faces[fi]] = names.index(painted.groups[painted.face_group[fi]].bone)
            joints[n_soft:] = 0
            weights[n_soft:] = 0.0
            joints[n_soft:, 0] = bone[n_soft:]
            weights[n_soft:, 0] = 1.0
    return Built(model, style, painted, normals, skeleton, model.skin, joints, weights, tracks(model, skeleton) if rigged else [], step,
                 floating, hidden, lost)  # fmt: skip


def _kept(model: Model, style: Style, field: Field, kept: list[int], step: float, target: int, others: list[Mesh],
          rigged: bool) -> tuple[list[tuple[Painted, Array]], list[int]]:  # fmt: skip
    """Each kept part as its own mesh: reduced only to its share of the budget, never below KEEP_MIN triangles.
    Also the kept parts with no surface at all."""
    out = []
    hidden = []
    total = sum(_area(m.vertices, m.faces) for m in others)
    for i in kept:
        f = field.only([i])
        t = part_thickness(model.parts[i].geometry)
        fine = min(step, max(t / 6, step / 4)) if t else step  # small enough to show it, however small it is
        mesh = dual_contour(f, fine)
        if not mesh.triangles:
            hidden.append(i)
            continue
        share = _area(mesh.vertices, mesh.faces) / max(total, 1e-12)
        mesh = decimate(f, mesh, max(KEEP_MIN, round(2 * share * target)), fine)
        painted = paint(regions(mesh, model, f, rigged, [i]), model)
        out.append((painted, corner_normals(painted, f, fine, style.smooth, style.sharp_angle)))
    return out, hidden


def _face_normals(p: Painted) -> Array:
    v, f = p.vertices, p.faces
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    return np.asarray(n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-18))


def _merge(soft: list[Painted], soft_normals: list[Array], hard: list[Painted], hard_normals: list[Array]) -> tuple[Painted, Array]:
    """One Painted from several (soft first): groups and decals merged by value."""
    groups: list[PaintGroup] = []
    decals: list[Decal] = []
    vertices, faces, face_group, face_decal = [], [], [], []
    base = 0
    for p in [*soft, *hard]:
        gmap = []
        for g in p.groups:
            if g not in groups:
                groups.append(g)
            gmap.append(groups.index(g))
        dmap = []
        for d in p.decals:
            if d not in decals:
                decals.append(d)
            dmap.append(decals.index(d))
        vertices.append(p.vertices)
        faces.append(p.faces + base)
        face_group.append(np.asarray(gmap, dtype=np.int64)[p.face_group] if len(p.face_group) else p.face_group)
        face_decal.append(np.where(p.face_decal >= 0, np.asarray(dmap + [-1], dtype=np.int64)[p.face_decal], -1))
        base += len(p.vertices)
    merged = Painted(np.concatenate(vertices), np.concatenate(faces), np.concatenate(face_group), groups, np.concatenate(face_decal), decals)
    return merged, np.concatenate([*soft_normals, *hard_normals])


def _hard_floating(model: Model, field: Field, mesh: HardMesh, soft_points: Array, soft_main: list[int], step: float, soft_pieces: int) -> int:
    """W103 with hard parts: each connected hard piece that doesn't touch the smooth surface (or is all `loose`
    parts) counts as one more piece. Touching: a smooth-surface point is near or inside the piece's parts, or one of
    its corners is near or inside the smooth surface."""
    if not mesh.triangles:
        return soft_pieces
    labels = component_labels(Mesh(mesh.vertices, mesh.faces))
    soft = field.only(soft_main) if soft_main else None
    extra = 0
    for label in sorted(set(labels[np.unique(mesh.faces)].tolist())):
        verts = np.flatnonzero(labels == label)
        parts = {int(i) for i in mesh.face_part[np.isin(mesh.faces, verts).any(axis=1)]}
        if all(model.parts[i].loose for i in parts):
            continue
        if soft is not None and ((soft.distance(mesh.vertices[verts]) < step * 1.5).any()
                                 or any((field.part_distance(i, soft_points) < step * 1.5).any() for i in sorted(parts))):  # fmt: skip
            continue
        extra += 1
    return max(1, extra) if soft is None else soft_pieces + extra


def _pieces(model: Model, field: Field, mesh: Mesh, step: float) -> int:
    """Connected pieces of the main mesh, not counting pieces made only of `loose: true` parts (lint W103)."""
    if not any(p.loose for p in model.parts):
        return components(mesh)
    labels = component_labels(mesh)[np.unique(mesh.faces)]
    points = mesh.vertices[np.unique(mesh.faces)]
    solid = [i for i, p in enumerate(model.parts) if p.geometry.op == "add" and not p.loose]
    near = np.zeros(len(points), dtype=bool)
    for i in solid:
        near |= np.abs(field.part_distance(i, points)) < step * 2
    return max(1, len(np.unique(labels[near])))


def _area(vertices: Array, faces: Array) -> float:
    p = vertices[faces]
    return float(np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1).sum() / 2)


def _areas(field: Field, vertices: Array, faces: Array, include: list[int], step: float) -> Array:
    """Surface area per part (in `include` order): each triangle counts for the part whose surface its centre is on."""
    if not len(faces) or not include:
        return np.zeros(len(include))
    p = vertices[faces]
    area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
    d = np.abs(np.stack([field.part_distance(i, p.mean(axis=1)) for i in include]))
    owner = d.argmin(axis=0)
    on = d.min(axis=0) < step
    return np.bincount(owner[on], weights=area[on], minlength=len(include))


def _join(cuts: list[Regions]) -> tuple[Regions, Array]:
    """One Regions from the pieces' (body, separate parts), and each paint group's piece."""
    groups: list[PaintGroup] = []
    piece_of: list[int] = []
    vertices, faces, owner = [], [], []
    part_group: dict[int, int] = {}
    pattern_groups: dict[int, int] = {}
    base = 0
    for k, cut in enumerate(cuts):
        remap = []
        for g in cut.groups:
            if g not in groups:
                groups.append(g)
                piece_of.append(k)
            remap.append(groups.index(g))
        vertices.append(cut.mesh.vertices)
        faces.append(cut.mesh.faces + base)
        owner.append(np.asarray(remap)[cut.owner])
        part_group.update({i: remap[g] for i, g in cut.part_group.items()})
        pattern_groups.update({remap[a]: remap[b] for a, b in cut.pattern_groups.items()})
        base += len(cut.mesh.vertices)
    mesh = Mesh(np.concatenate(vertices), np.concatenate(faces))
    return Regions(mesh, np.concatenate(owner), groups, part_group, pattern_groups), np.asarray(piece_of)


def _decimate(
    model: Model, style: Style, fields: list[Field], cut: Regions, region_piece: Array, step: float, target: int, includes: list[list[int]],
    full_areas: list[Array],
) -> tuple[Painted, Array, tuple[int, ...], tuple[int, ...]]:
    """Decimate every piece together to the budget, paint decals, and work out normals and hidden/lost parts per
    piece (each on its own surface)."""
    # Colour borders are kept, so they cost triangles; next to a full-detail border every triangle is tiny, so the
    # borders can only be thinned once the surface around them is coarser. So: decimate (borders locked), thin the
    # borders, decimate again... Borders may stray from the exact curve by a fraction of the target triangle size
    # (more while over budget); only then are triangles taken from the surfaces between them.
    edge = math.sqrt(4 * _area(cut.mesh.vertices, cut.mesh.faces) / (math.sqrt(3) * target))  # a typical edge at the budget
    mesh, owner = cut.mesh, cut.owner
    goal = target

    def attempt(goal: int) -> tuple[Mesh, Array, Painted]:
        decimated, face_owner = decimate_regions(fields[0], mesh, owner, goal, step, 0, fields, region_piece)
        painted = paint(Regions(decimated, face_owner, cut.groups, cut.part_group, cut.pattern_groups), model)
        return decimated, face_owner, painted

    for k, share in enumerate(BORDER_SCHEDULE):
        mesh, owner = simplify_borders(mesh, owner, max(step * 0.15, edge * share))
        mesh, owner, painted = attempt(goal if k else goal * 3)
        if k >= 2 and len(painted.faces) <= target * 1.05:
            break
    else:
        for _ in range(2):
            goal = max(int(goal * target / len(painted.faces) * 0.95), int(target * 0.3))
            mesh, owner, painted = attempt(goal)
            if len(painted.faces) <= target * 1.05 or goal <= target * 0.3:
                break  # or the extra triangles come from patterns and borders themselves (lint W110 says so)
    normals = np.zeros((len(painted.faces), 3, 3))
    hidden: list[int] = []
    lost: list[int] = []
    face_piece = region_piece[painted.face_group]
    for k, (field, include) in enumerate(zip(fields, includes, strict=True)):
        mine = face_piece == k
        sub = Painted(painted.vertices, painted.faces[mine], painted.face_group[mine], painted.groups, painted.face_decal[mine], painted.decals)
        normals[mine] = corner_normals(sub, field, step, style.smooth, style.sharp_angle)
        full = full_areas[k]
        final = _areas(field, painted.vertices, painted.faces[mine], include, step)
        hidden += [i for i, a in zip(include, full, strict=True) if a == 0]
        lost += [i for i, a, b in zip(include, full, final, strict=True) if a > 0 and b < a * LOST_AREA]
    return painted, normals, tuple(sorted(hidden)), tuple(sorted(lost))


def cache_key(model: Model, style: Style, palette: dict[str, str], budget: int | None = None) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([__version__, BUILDER_VERSION, model.text, style.text, sorted(palette.items()), budget]).encode())
    for part in model.parts:
        if part.decal is not None:
            h.update(part.decal.image.read_bytes())
    if model.fit_to is not None:  # the character it's fitted to
        h.update(model.fit_to[0].read_bytes())
    for anim in model.animations.values():  # retargeted clips
        if anim.source is not None:
            h.update(anim.source[0].read_bytes())
    if model.source is not None:
        from kiln.importer import external_files

        h.update(model.source.file.read_bytes())
        for uri in external_files(model.source.file):  # its buffers and textures too
            other = model.source.file.parent / uri
            h.update(uri.encode() + (other.read_bytes() if other.is_file() else b"missing"))
    return h.hexdigest()[:32]


def _cache_file(model: Model, style: Style, palette: dict[str, str], cache_dir: Path, budget: int | None = None) -> Path:
    return cache_dir / f"{model.name}.{budget or 'base'}.{cache_key(model, style, palette, budget)}.pickle"


def cached(model: Model, style: Style, palette: dict[str, str], cache_dir: Path | None, budget: int | None = None) -> bool:
    return cache_dir is not None and _cache_file(model, style, palette, cache_dir, budget).is_file()


def build_cached(model: Model, style: Style, palette: dict[str, str], cache_dir: Path | None, budget: int | None = None) -> Built:
    if cache_dir is None:
        return build_model(model, style, budget, palette)
    key = cache_key(model, style, palette, budget)
    prefix = f"{model.name}.{budget or 'base'}."
    path = cache_dir / f"{prefix}{key}.pickle"
    if path.is_file():
        try:
            with path.open("rb") as fh:
                built = pickle.load(fh)  # noqa: S301 - our own cache file
            if isinstance(built, Built):
                built.model = model  # fresh paths/text; geometry is identical by the key
                return built
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, TypeError):
            pass
    built = build_model(model, style, budget, palette)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for old in cache_dir.glob(f"{prefix}*.pickle"):
        old.unlink(missing_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        pickle.dump(built, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
    return built


__all__ = ["BUILDER_VERSION", "Mesh", "build_cached", "build_model", "cache_key", "field_of"]
