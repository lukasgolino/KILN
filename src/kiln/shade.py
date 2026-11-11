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
    """(V,) multipliers in (0, 1] per painted vertex (unused vertices get 1), or None when the model has no shade."""
    from kiln.atlas import ambient_occlusion, vertex_normals

    shade = effective(built, atlas_ao)
    if not shade.on:
        return None
    mult = ambient_occlusion(built, shade.cavity) if shade.cavity > 0 else np.ones(len(built.painted.vertices))
    if shade.top > 0 or shade.under > 0:
        used = np.unique(built.painted.faces)
        ny = vertex_normals(built)[used, 1]
        mult[used] *= (1.0 - shade.top * (1.0 - np.maximum(ny, 0.0))) * (1.0 - shade.under * np.maximum(-ny, 0.0))
    return np.round(mult, 4)


__all__ = ["FIELDS", "Shade", "effective", "parse", "shading"]
