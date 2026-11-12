"""Other models placed in a model (`instances:`, #171): each is that model's own build (its mesh, at its own detail),
moved into place and merged into the scene's mesh after it is built, so previews, the glb, Godot and LODs take it as
any other surface. Its faces move with the part named by `id` (the root by default). An instance's decals and baked
maps aren't carried over (its colours are)."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from kiln.export import Built
from kiln.notation import Instance
from kiln.paint import Painted, PaintGroup
from kiln.sdf import rotation_matrix

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
        face_decal.append(np.full(len(q.faces), -1, dtype=p.face_decal.dtype))
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
    painted = Painted(np.concatenate(vertices), np.concatenate(faces), np.concatenate(face_group), groups, np.concatenate(face_decal), list(p.decals))
    return replace(built, painted=painted, normals=np.concatenate(normals), ao=np.concatenate(ao) if ao is not None else None,
                   joints=np.concatenate(joints) if joints is not None else None, weights=np.concatenate(weights) if weights is not None else None)  # fmt: skip
