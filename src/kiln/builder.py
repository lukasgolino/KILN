"""One model -> Built (field, mesh, paint, normals, rig, animations), with a cache in `.kiln-cache/`.

Meshing is the slow step (seconds); the cache key covers everything that changes the result: the model text,
the style, the palette, decal images, imported files and KILN's version.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np

from kiln import __version__
from kiln.export import Built
from kiln.mesher import Mesh, components, decimate, dual_contour, model_step
from kiln.notation import ROOT_ID, Model
from kiln.paint import corner_normals, paint
from kiln.rig import Bone, Skeleton, build_skeleton, soft_weights, tracks
from kiln.sdf import Field
from kiln.style import Style

BUILDER_VERSION = 1  # bump when meshing/painting changes output


def field_of(model: Model, step: float) -> Field:
    return Field([p.geometry for p in model.parts], margin=step * 3)


def build_model(model: Model, style: Style, budget: int | None = None, palette: dict[str, str] | None = None) -> Built:
    if model.source is not None:
        from kiln.importer import build_imported

        return build_imported(model, style, palette)
    field = field_of(model, 0.01)
    step = model_step(field, style.resolution)
    field = field_of(model, step)
    mesh = dual_contour(field, step)
    if mesh.triangles == 0:
        raise ValueError("the model has no surface (everything cut away, or all parts are cuts)")
    target = budget or model.budget or style.budget(model.cls)
    mesh = decimate(field, mesh, target, step)
    pieces = components(mesh)
    rigged = model.skin != "none"
    painted = paint(mesh, model, field, rigged)
    normals = corner_normals(painted, field, step, style.smooth, style.sharp_angle)
    skeleton = build_skeleton(model, field) if rigged else Skeleton([Bone(ROOT_ID, -1, np.zeros(3), {}, False)])
    joints = weights = None
    if model.skin == "soft":
        joints, weights = soft_weights(painted.vertices, model, field, skeleton, step)
    return Built(model, style, painted, normals, skeleton, model.skin, joints, weights, tracks(model, skeleton) if rigged else [], step, pieces)


def cache_key(model: Model, style: Style, palette: dict[str, str], budget: int | None = None) -> str:
    h = hashlib.sha256()
    h.update(json.dumps([__version__, BUILDER_VERSION, model.text, style.text, sorted(palette.items()), budget]).encode())
    for part in model.parts:
        if part.decal is not None:
            h.update(part.decal.image.read_bytes())
    if model.source is not None:
        h.update(model.source.file.read_bytes())
    return h.hexdigest()[:32]


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
