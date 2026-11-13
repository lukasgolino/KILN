"""Shade paint (#231): the hand-painted look baked into the vertex colours, in every colour mode: darker in crevices
(`cavity`), lighter on top (`top`), a little darker underneath (`under`).

It is one grey multiplier per vertex in COLOR_0 (glTF multiplies COLOR_0 into the base colour, Godot's materials use
it as albedo), the same channel `atlas_ao` uses; previews multiply it in too. Vertex colours in Godot are 8-bit, so a
multiplier can't go above 1: `top` is relative, the top keeps the base colour and the rest darkens towards the
bottom (a side by `top`, the underside by `top` and `under`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from kiln.sdf import Array

if TYPE_CHECKING:
    from kiln.export import Built

FIELDS = ("cavity", "top", "under")
SLENDER = 12.0  # a triangle whose longest edge squared is this many times its doubled area is a sliver (#335)
LIMIT = 0.9  # each term at most: a multiplier of 0.1 is already near black


@dataclass(frozen=True)
class Shade:
    cavity: float = 0.0  # x the field's occlusion (0..1): crevices darker
    top: float = 0.0  # surfaces not facing up darker by up to this (the top keeps its colour)
    under: float = 0.0  # surfaces facing down darker by up to this, on top of `top`

    @property
    def on(self) -> bool:
        return self.cavity > 0 or self.top > 0 or self.under > 0

    def over(self, values: dict[str, float]) -> Shade:
        """This shade with some fields replaced (a model's `shade:` over its style's [shade])."""
        return Shade(**{k: float(values.get(k, getattr(self, k))) for k in FIELDS})


def parse(raw: Any, toml: bool = False) -> tuple[dict[str, float], str | None]:
    """A `shade:` mapping (model) or [shade] table (style, `toml`) -> its fields, or an error message."""
    example = "[shade] cavity = 0.25, top = 0.12, under = 0.1" if toml else "shade: { cavity: 0.25, top: 0.12, under: 0.1 }"
    if not isinstance(raw, dict):
        return {}, f"shade is a mapping of cavity, top and under (each 0 to {LIMIT:g}), e.g. {example}"
    unknown = sorted(str(k) for k in raw if k not in FIELDS)
    if unknown:
        return {}, f"unknown shade field {unknown[0]!r}: shade has cavity, top and under (each 0 to {LIMIT:g}), e.g. {example}"
    out: dict[str, float] = {}
    for key, value in raw.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= LIMIT:
            return {}, f"shade {key} is 0 (off) to {LIMIT:g}, e.g. {example}"
        out[str(key)] = float(value)
    return out, None


def effective(built: Built, atlas_ao: float = 0.0) -> Shade:
    """The model's shade: its style's [shade], the model's `shade:` over it; kiln.toml atlas_ao is a cavity strength
    (with both, the larger)."""
    shade = built.style.shade.over(built.model.shade)
    return Shade(max(shade.cavity, atlas_ao), shade.top, shade.under) if atlas_ao > shade.cavity else shade


def shading(built: Built, atlas_ao: float = 0.0) -> Array | None:
    """(F, 3) multipliers in (0, 1] per face corner, or None when the model has no shade. Per corner, not per vertex:
    `top` and `under` follow the corner's normal, so a hard edge keeps a flat top at its colour right to the edge."""
    from kiln.atlas import ambient_occlusion

    shade = effective(built, atlas_ao)
    if not shade.on:
        return None
    faces = built.painted.faces
    mult = ambient_occlusion(built, shade.cavity)[faces] if shade.cavity > 0 else np.ones(faces.shape)
    if shade.cavity > 0 and len(faces):  # (#335) a long thin triangle (a hard flank's fan) would smear its corners' occlusion across
        tri = built.painted.vertices[faces]  # itself in a streak: it takes their mean, evenly
        edges = np.linalg.norm(tri[:, [1, 2, 0]] - tri, axis=2)
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        slender = edges.max(axis=1) ** 2 > SLENDER * np.maximum(area, 1e-18)
        mult[slender] = mult[slender].mean(axis=1, keepdims=True)
    if shade.top > 0 or shade.under > 0:
        ny = built.normals[..., 1] / np.maximum(np.linalg.norm(built.normals, axis=2), 1e-12)
        mult = mult * (1.0 - shade.top * (1.0 - np.maximum(ny, 0.0))) * (1.0 - shade.under * np.maximum(-ny, 0.0))
    return np.round(mult, 4)


def texel_shade(built: Built, atlas_ao: float = 0.0) -> Shade | None:
    """The shade to paint per texel into the base colour map (#266), or None: then COLOR_0 carries it as usual. A model
    with a colour map keeps each texel's height and occlusion, so crevices between relief patches darken too."""
    bake = built.bake
    if bake is None or not getattr(bake, "shaded", False):
        return None
    shade = effective(built, atlas_ao)
    if not shade.on or (shade.cavity > 0 and bake.layers.occ is None):  # built before the cavity was asked: per vertex
        return None
    return shade


__all__ = ["FIELDS", "Shade", "effective", "parse", "shading", "texel_shade"]
