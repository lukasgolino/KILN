"""One model -> Built (field, mesh, paint, normals, rig, animations), with a cache in `.kiln-cache/`.

Meshing is the slow step (seconds); the cache key covers everything that changes the result: the model text,
the style's shape settings and the triangle budget, the palette, decal and texture images, imported files and
KILN's version. A style's look and materials are not in it: exports read them from the style at hand.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from kiln import __version__
from kiln.export import Built
from kiln.hard import HARD_SHAPES, SHELL_SHAPES, HardMesh, HardSpec, Solid, intersect, solid, subtract, to_mesh, union
from kiln.hard import corner_normals as hard_corner_normals
from kiln.mesher import (
    Mesh,
    component_labels,
    components,
    decimate,
    decimate_regions,
    dual_contour,
    mesh_cells,
    simplify_borders,
)
from kiln.notation import ROOT_ID, Decal, Model, Part
from kiln.paint import Painted, PaintGroup, Regions, corner_normals, hard_regions, paint, regions
from kiln.rig import Bone, Skeleton, build_skeleton, soft_weights, tracks
from kiln.sdf import Array, Field, Geometry, part_thickness
from kiln.style import SHAPE_KEYS, Style
from kiln.usage import MANY_PARTS, Phases, Progress

BUILDER_VERSION = 18  # bump when meshing/painting changes output
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
        if g.op != "add" or g.shape not in HARD_SHAPES or g.twist or g.noise is not None or g.scale is not None or g.blend_to is not None or (g.shell and g.shape not in SHELL_SHAPES) \
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


def _hard_cut_applies(g: Geometry, include: frozenset[int]) -> bool:
    """A cut or intersect that is made in polygons on the piece `include`."""
    return g.shape in HARD_SHAPES and not g.twist and g.noise is None and g.scale is None and not (g.shell and g.shape not in SHELL_SHAPES) \
        and (g.cut_only is None or bool(g.cut_only & include))  # fmt: skip


def _hard_steps(model: Model, include: frozenset[int]) -> list[int]:
    """The parts one piece's hard solid is made of, in order: its adding parts, and every later hard cut or intersect
    that reaches it."""
    out: list[int] = []
    for i, p in enumerate(model.parts):
        g = p.geometry
        if (i in include) if g.op == "add" else (bool(out) and _hard_cut_applies(g, include)):
            out.append(i)
    return out


def _hard_solid(model: Model, style: Style, include: frozenset[int], level: int, tick: Any = None) -> Solid:
    """The hard parts of one piece combined in order: adding parts unite; every later cut or intersect applies
    (`tick()` after each one)."""
    acc: Solid = []
    for i in _hard_steps(model, include):
        p = model.parts[i]
        g = p.geometry
        if g.op == "add":
            acc = union(acc, solid(g, hard_spec(p, style, level), i))
        elif acc:
            other = solid(g, hard_spec(p, style, level), i)
            acc = subtract(acc, other) if g.op == "cut" else intersect(acc, other)
        if tick is not None:
            tick()
    return acc


def hard_joins(model: Model, pieces: list[frozenset[int]]) -> int:
    """How many solids build_hard joins per detail level, over all pieces: the total of its progress counter."""
    return sum(len(_hard_steps(model, include)) for include in pieces)


DRAFT_HARD_LEVEL = 2  # preview --draft: hard parts without bevels or bands (hard_spec levels), made once
HARD_GROWTH = 1.0  # time against joins done, as a power: about linear since trees are made where clips reach (#214; 2 before)
ROUND_SHAPES = frozenset({"cylinder", "cone", "capsule", "tube", "lathe", "torus", "sphere", "ellipsoid"})


def _spec_key(part: Part, spec: HardSpec) -> tuple[int, float, int]:
    """What of a HardSpec changes this part's solid: bevel bands only with a bevel, sides only on round shapes."""
    sides = int(part.geometry.params.get("sides") or spec.sides)  # as hard.local_polys reads it
    return (sides if part.geometry.shape in ROUND_SHAPES else 0, spec.bevel, spec.segments if spec.bevel else 0)


def build_hard(model: Model, style: Style, field: Field, pieces: list[frozenset[int]], budget: float, rigged: bool,
               progress: Progress | None = None) -> tuple[list[Regions], list[HardMesh]]:  # fmt: skip
    """Every piece's hard parts as a mesh (fewer details while they'd go over `budget`), cut into paint groups."""
    meshes: list[HardMesh] = []
    specs = None
    total = hard_joins(model, pieces)
    tries = 0
    for level in ((DRAFT_HARD_LEVEL,) if model.draft else range(5)):  # a draft: plain shapes at once, whatever the budget
        level_specs = [_spec_key(p, hard_spec(p, style, level)) for p in model.parts]
        if level_specs == specs:  # this level details nothing less: same meshes, try the next (#207)
            continue
        specs = level_specs
        # one counter over all pieces; a level made again with less detail (over budget) says so and counts afresh
        label = "joining hard parts: joined" if tries == 0 else f"joining hard parts again with less detail (try {tries + 1}): joined"
        tries += 1
        done = 0

        def tick() -> None:
            nonlocal done
            done += 1
            if progress is not None:
                progress(label, done, total)  # noqa: B023 (called within this level)

        meshes = [to_mesh(_hard_solid(model, style, include, level, tick)) for include in pieces]
        if sum(m.triangles for m in meshes) <= budget:
            break
    out = []
    for include, mesh in zip(pieces, meshes, strict=True):
        part = mesh.face_part.copy()
        # faces a cut made (a hole's walls) belong to the part they're in
        foreign = ~np.isin(part, sorted(include))
        if foreign.any():
            centres = mesh.vertices[mesh.faces[foreign]].mean(axis=1)
            own = sorted(include)
            part[foreign] = np.asarray(own)[field.nearest(own, centres, absolute=False)[0]]
        out.append(hard_regions(Mesh(mesh.vertices, mesh.faces), part, model, rigged))
    return out, meshes


def build_error(exc: ValueError) -> str:
    """A build failure as a finding's message (#170): KILN's own ValueErrors say what to fix and pass as they are; one
    raised inside a library (numpy's "zero-size array ..." and the like) is a KILN bug, said so, with where it came from."""
    package = Path(__file__).resolve().parent
    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if Path(f.filename).resolve().is_relative_to(package)]
    if not frames or (ours and ours[-1] is frames[-1]):
        return str(exc)
    where = f" in {Path(ours[-1].filename).name}:{ours[-1].lineno}" if ours else ""
    return (f"internal error while building{where} ({type(exc).__name__}: {exc}); this is a KILN bug: please report it with "
            "the model file (https://github.com/lukasgolino/kiln/issues)")


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
    step, asked, reason = mesh_cells(field, model, style)
    with Phases(model.name) as phase:  # its heartbeat stops with the build, however it ends
        phase.loud = len(model.parts) >= MANY_PARTS  # a big model's build is rarely short: say each phase at once (#221)
        built = _build_meshed(model, style, budget, step, asked, phase, reason)
        built.step_reason = reason
        return built


def _build_meshed(model: Model, style: Style, budget: int | None, step: float, asked: float, phase: Phases, reason: str) -> Built:
    field = field_of(model, step)
    target = budget or model.budget or style.budget(model.cls)
    rigged = model.skin != "none"
    hard = hard_parts(model, style)
    all_pieces, n_main = mesh_pieces(model)
    adding = [i for i, p in enumerate(model.parts) if p.geometry.op == "add"]
    per_bone = model.union == "per_bone" and model.skin == "rigid"
    # hard parts are exact polygons, made first: what they leave of the budget goes to the smooth parts
    hard_pieces = [frozenset(i for i in inc if i in hard) for inc in all_pieces]
    hard_pieces = [inc for inc in hard_pieces if inc]
    any_soft = any(i not in hard for i in adding)
    def hinted(hint: str, growth: float = 1.0) -> Progress:  # a phase's counter, with what would make it faster
        return lambda what, done, total: phase.progress(what, done, total, hint, growth)

    hard_cut: list[Regions] = []
    hard_meshes: list[HardMesh] = []
    if hard_pieces:  # its own phase (#174): exact polygons joined one by one, whatever the cell size
        phase(f"joining {len(hard)} hard part{'s' * (len(hard) != 1)}")
        hard_cut, hard_meshes = build_hard(model, style, field, hard_pieces, target * (HARD_SHARE if any_soft else 1.0), rigged,
                                           hinted("fewer hard parts, or fewer sides on round ones, join faster", HARD_GROWTH))  # fmt: skip
    hard_triangles = sum(r.mesh.triangles for r in hard_cut)
    kept = kept_parts(model, hard)
    groups_of = [[i for i in inc if i not in hard and i not in kept] for inc in all_pieces]
    pieces = [(include, field.only(include)) for include in groups_of if include]
    smooth = sum(len(g) for g in groups_of) + len(kept)  # the adding parts meshed here: not hard ones, not cuts
    meshing = hinted("a coarser resolution or fewer parts meshes faster")
    if pieces or kept:  # a model of hard parts only has nothing to mesh: no phase, no "0 triangles" (#174)
        phase(f"meshing {smooth} part{'s' * (smooth != 1)} at {step * 1000:.3g} mm cells ({reason})")
    meshes = [dual_contour(f, step, meshing) for _, f in pieces]
    if pieces:
        phase(f"meshed at {step * 1000:.3g} mm: {sum(m.triangles for m in meshes)} triangles")
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
        if not model.draft:
            live = [(include, f, decimate(f, mesh, max(200, round(PRESHAPE * soft_target * mesh.triangles / total)), step)) for include, f, mesh in live]
        phase(f"painting {len(adding)} parts")
        cut, region_piece = _join([regions(mesh, model, f, rigged, include, protect, hinted("fewer gradient or pattern parts paint faster"), model.draft)
                                   for include, f, mesh in live])  # fmt: skip
        fields = [f for _, f, _ in live]
        phase(f"reducing to {soft_target} triangles")
        painted, normals, hidden, lost = _decimate(model, style, fields, cut, region_piece, step, soft_target, [inc for inc, _, _ in live], full_areas,
                                                   hinted("a coarser resolution (fewer raw triangles) reduces faster"))  # fmt: skip
    floating = 1
    if groups_of[0] and painted is not None and not per_bone:  # separate parts may float
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
        if not per_bone and hard_pieces[0] <= frozenset(all_pieces[0]):  # the main piece has hard parts: they may float too
            soft_points = painted.vertices[:n_soft] if n_soft else np.zeros((0, 3))
            floating = _hard_floating(model, field, hard_meshes[0], soft_points, groups_of[0], step, floating)
    assert painted is not None
    if per_bone:
        main_ids = {model.parts[i].id for inc in all_pieces[:n_main] for i in inc}
        floating = _touching_pieces(model, field, painted, main_ids, step)
    skeleton = build_skeleton(model, field) if rigged else Skeleton([Bone(ROOT_ID, -1, np.zeros(3), {}, False)])
    joints = weights = None
    if model.skin == "soft":
        phase("skinning")
        joints, weights = soft_weights(painted.vertices, model, field, skeleton, step, hinted("skin: rigid or fewer parts skins faster"))
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
    built = Built(model, style, painted, normals, skeleton, model.skin, joints, weights, tracks(model, skeleton) if rigged else [], step,
                  floating, hidden, lost, asked)  # fmt: skip
    if model.normal_map:
        size = model.normal_map if budget is None else max(256, model.normal_map // 2)  # a LOD: its own, smaller map
        built.bake = bake_normals(model, built, step, [inc for inc in groups_of if inc], kept, size)
    return built


def bake_normals(model: Model, built: Built, step: float, soft_pieces: list[list[int]], kept: frozenset[int], size: int) -> Any:
    """The model's normal map. Each face is baked with its own piece's field, as it was meshed (a separate helmet's
    opening, a bone's own surface), plus the detail parts: those with the id of one of the piece's parts, and every
    detail cut. Kept parts get their own field; hard parts (exact polygons) keep their mesh normals."""
    from kiln import bake

    if not bake.available():
        raise ValueError("normal_map needs xatlas for the UVs: pip install \"kiln-gen[bake]\"")
    geoms = model.bake_parts if model.bake_parts is not None else [p.geometry for p in model.parts]
    to_bake = model.bake_index if model.bake_parts is not None else list(range(len(model.parts)))  # model.parts -> geoms
    full = Field(geoms, margin=step * 3)
    pieces = [*soft_pieces, *([i] for i in sorted(kept))]
    piece_ids = [{model.parts[i].id for i in inc} for inc in pieces]
    homes: dict[int, list[int]] = {k: [] for k in range(len(pieces))}
    for i, pid in sorted(model.detail_ids.items()):  # an adding detail part: in the pieces with its id, else the first
        if geoms[i].op != "add":
            continue  # detail cuts apply everywhere (as cuts do), unless they name what they cut
        for k in [k for k, ids in enumerate(piece_ids) if pid in ids] or [0]:
            homes[k].append(i)
    fields = [full.only([to_bake[i] for i in inc] + homes[k]) for k, inc in enumerate(pieces)]
    p = built.painted
    centres = p.vertices[p.faces].mean(axis=1)
    adding = [i for i, q in enumerate(model.parts) if q.geometry.op == "add"]
    owner = np.asarray(adding)[field_of(model, step).nearest(adding, centres)[0]] if adding else np.zeros(len(p.faces), np.int64)
    piece_of = {i: k for k, inc in enumerate(pieces) for i in inc}
    face_field = np.array([piece_of.get(int(i), -1) for i in owner], dtype=np.int64)  # hard parts: -1
    return bake.bake(fields, face_field, p.vertices, p.faces, built.normals, size, step, model.normal_strength)


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


def _touching_pieces(model: Model, field: Field, painted: Painted, ids: set[str], step: float) -> int:
    """W103 for `union: per_bone`: the bones' surfaces overlap without being joined, so pieces are counted by touch.
    Each connected piece of the surface (of the parts with these ids) is on some parts; two pieces touch where one's
    vertices are near or inside the other's parts. Pieces only on `loose: true` parts don't count."""
    faces = painted.faces[np.isin(np.array([g.bone for g in painted.groups] or [""], dtype=object)[painted.face_group], sorted(ids))]
    if not len(faces):
        return 1
    labels = component_labels(Mesh(painted.vertices, faces))
    used = np.unique(faces)
    adding = [i for i, p in enumerate(model.parts) if p.geometry.op == "add" and p.id in ids]
    comps = sorted(set(labels[used].tolist()))
    comp_of = np.searchsorted(comps, labels[used])
    on: list[set[int]] = [set() for _ in comps]
    near: list[Array] = [np.zeros(len(adding), dtype=bool) for _ in comps]  # per piece: the parts it touches
    for k, i in enumerate(adding):  # one part at a time: parts x vertices would not fit for many-part models
        d = field.part_distance(i, painted.vertices[used])
        for c in np.unique(comp_of[np.abs(d) < step]).tolist():
            on[c].add(i)
        for c in np.unique(comp_of[d < step * 1.5]).tolist():
            near[c][k] = True
    keep = [k for k, parts in enumerate(on) if parts and not all(model.parts[i].loose for i in parts)]
    group = {k: k for k in keep}

    def find(k: int) -> int:
        while group[k] != k:
            k = group[k]
        return k

    for a in keep:
        for b in keep:
            if a < b and (any(near[a][adding.index(i)] for i in on[b]) or any(near[b][adding.index(i)] for i in on[a])):
                group[find(a)] = find(b)
    return max(1, len({find(k) for k in keep}))


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
    owner, best = field.nearest(include, p.mean(axis=1))
    on = best < step
    return np.bincount(owner[on], weights=area[on], minlength=len(include))


def _join(cuts: list[Regions]) -> tuple[Regions, Array]:
    """One Regions from the pieces' (body, separate parts), and each paint group's piece."""
    groups: list[PaintGroup] = []
    piece_of: list[int] = []
    vertices, faces, owner = [], [], []
    part_group: dict[int, int] = {}
    pattern_groups: dict[int, tuple[int, ...]] = {}
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
        pattern_groups.update({remap[a]: tuple(remap[x] for x in b) for a, b in cut.pattern_groups.items()})
        base += len(cut.mesh.vertices)
    mesh = Mesh(np.concatenate(vertices), np.concatenate(faces))
    return Regions(mesh, np.concatenate(owner), groups, part_group, pattern_groups), np.asarray(piece_of)


def _decimate(
    model: Model, style: Style, fields: list[Field], cut: Regions, region_piece: Array, step: float, target: int, includes: list[list[int]],
    full_areas: list[Array], progress: Progress | None = None,
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

    for k, share in enumerate(() if model.draft else BORDER_SCHEDULE):
        if progress is not None:
            progress("reducing: passes done", k, len(BORDER_SCHEDULE))
        mesh, owner = simplify_borders(mesh, owner, max(step * 0.15, edge * share))
        mesh, owner, painted = attempt(goal if k else goal * 3)
        if k >= 2 and len(painted.faces) <= target * 1.05:
            break
    else:
        if model.draft:  # a quick look: one pass, borders as they are; over budget is fine
            mesh, owner, painted = attempt(goal)
        for _ in range(0 if model.draft else 2):
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


def mesh_pieces(model: Model) -> tuple[list[list[int]], int]:
    """The adding parts meshed together, as lists of part indices, and how many of them are the main surface (one, or
    one per bone with union: per_bone); the rest are separate parts and fitted shells."""
    rigged = model.skin != "none"
    # `separate` parts (a detachable helmet) are meshed on their own: their own closed surface, not fused into the
    # body, so detaching one leaves no hole. The rest is the main piece.
    separate = sorted(pid for pid, entry in model.rig.items() if entry.separate) if rigged else []
    adding = [i for i, p in enumerate(model.parts) if p.geometry.op == "add"]
    # fitted shells (armour wrapping a body, a gap away) are their own pieces too: meshed with what they wrap, the thin
    # air gap between the two surfaces would tear both
    fitted = sorted({model.parts[i].id for i in adding if model.parts[i].geometry.fit is not None and model.parts[i].id not in separate})
    own = set(separate) | set(fitted)
    main = [i for i in adding if model.parts[i].id not in own]
    # union: per_bone (rigid skins): each bone's parts are one closed surface; neighbouring bones' surfaces overlap
    # instead of being cut along where they meet, so turning a joint can't open the mesh (#50)
    per_bone = model.union == "per_bone" and model.skin == "rigid"
    bones = [pid for pid in model.ids if any(model.parts[i].id == pid for i in main)] if per_bone else []
    all_pieces = [[i for i in main if model.parts[i].id == pid] for pid in bones] if per_bone else [main]
    n_main = len(all_pieces)
    all_pieces += [[i for i in adding if model.parts[i].id == pid] for pid in [*separate, *fitted]]
    return all_pieces, n_main


STYLE_KEYED = ("name", *SHAPE_KEYS, "budgets")  # the Style fields a build depends on (budgets: the one that applies)


def shape_key(model: Model, style: Style, budget: int | None = None) -> list[Any]:
    """What of a style a build depends on: its [shape] settings and the triangle budget that applies to this model
    (the asked one, the model's own, or the style's for its class). Not its [look] or [materials] (the exporters
    read those from the style at hand), nor its description and notes, so a look-only edit keeps the built meshes
    (#174). A new Style field a builder reads goes in STYLE_KEYED (tests/test_api.py lists every field)."""
    return [style.name, *(getattr(style, k) for k in SHAPE_KEYS), budget or model.budget or style.budget(model.cls)]


def cache_key(model: Model, style: Style, palette: dict[str, str], budget: int | None = None) -> str:
    h = hashlib.sha256()
    # the model's shape fields, not its text: comments, layout, its card, its variants and its animations (their tracks
    # are sampled again on a cache hit, see motion_key) leave the meshes alone (#185)
    text = model.shape_text or model.text
    h.update(json.dumps([__version__, BUILDER_VERSION, text, shape_key(model, style, budget), sorted(palette.items()), budget]).encode())
    for part in model.parts:
        if part.decal is not None:
            h.update(part.decal.image.read_bytes())
        if part.texture is not None:
            h.update(part.texture.image.read_bytes())
        if part.geometry.shape == "extrude":  # outlines from a font file aren't in the model text
            h.update(json.dumps([part.geometry.params.get("points"), part.geometry.params.get("holes")]).encode())
    if model.fit_to is not None:  # the character it's fitted to
        h.update(model.fit_to[0].read_bytes())
    if model.draft:
        h.update(f"draft {model.resolution}".encode())  # a draft is its own build, at its own cell size
    if model.source is not None:
        from kiln.importer import external_files

        h.update(motion_key(model).encode())  # an imported model's clips are part of its build

        h.update(model.source.file.read_bytes())
        for uri in external_files(model.source.file):  # its buffers and textures too
            other = model.source.file.parent / uri
            h.update(uri.encode() + (other.read_bytes() if other.is_file() else b"missing"))
    return h.hexdigest()[:32]


def motion_key(model: Model) -> str:
    """What a build's animation tracks come from, besides its skeleton: the model's animations (or its clip
    carrier's) and the clip files they are retargeted from."""
    h = hashlib.sha256()
    own = model.motion_text if model.shape_text else model.text  # a model made without its parsed fields: its text
    h.update(json.dumps([__version__, BUILDER_VERSION, own, model.library_text]).encode())
    for anim in model.animations.values():  # retargeted clips
        if anim.source is not None:
            h.update(anim.source[0].read_bytes())
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
    cached_build: Built | None = None
    if path.is_file():
        try:
            with path.open("rb") as fh:
                loaded = pickle.load(fh)  # noqa: S301 - our own cache file
            if isinstance(loaded, Built) and isinstance(loaded.motion_key, str):
                cached_build = loaded
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, TypeError):
            pass  # an unreadable cache file: build again
    if cached_build is not None:
        built = cached_build
        built.model = model  # fresh paths/text; geometry is identical by the key
        built.style = style  # and today's look and materials: the key leaves them out
        if model.source is None and model.skin != "none":  # an animation edit: only the tracks are made again (#185)
            motion = motion_key(model)
            if built.motion_key != motion:
                built.tracks = tracks(model, built.skeleton)
                built.motion_key = motion
                _store(built, path)
        if not built.step_reason and model.source is None:  # cached before builds kept it
            built.step_reason = mesh_cells(field_of(model, built.step), model, style)[2]
        return built
    built = build_model(model, style, budget, palette)
    built.motion_key = motion_key(model)
    cache_dir.mkdir(parents=True, exist_ok=True)
    for old in cache_dir.glob(f"{prefix}*.pickle"):
        old.unlink(missing_ok=True)
    _store(built, path)
    return built


def _store(built: Built, path: Path) -> None:
    tmp = path.with_suffix(f".{os.getpid()}.tmp")  # its own: lint's processes may store the same model at once
    with tmp.open("wb") as fh:
        pickle.dump(built, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


__all__ = ["BUILDER_VERSION", "Mesh", "build_cached", "build_model", "cache_key", "field_of"]
