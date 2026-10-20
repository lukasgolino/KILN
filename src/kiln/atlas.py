"""Palette atlas (kiln.toml `atlas = true`): one material per model. Every (colour, material preset) pair gets a cell
in small textures: the colour (`<name>.palette.png`), roughness and metal (`<name>.material.png`, glTF: G = roughness,
B = metallic), glow (`<name>.glow.png`, only when a preset glows) and, for Godot, rim light (`<name>.rim.png`). Faces
point their UVs at their cell's centre; samplers are NEAREST without mipmaps, so cells never bleed. A variant is
another palette (and glow) texture with the same layout: no mesh change.

`atlas_ao = true` also bakes ambient occlusion per vertex (COLOR_0, a multiplier): from the model's distance field
(sampled a few steps along the normal), or from the mesh's concavity for imported models.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from kiln.sdf import Array, Field

if TYPE_CHECKING:
    from kiln.export import Built

CELL = 4  # pixels per cell side (a multiple of 4: GPU block compression keeps a cell one colour)
COLUMNS = 16
AO_STEPS = 5
AO_RADIUS = 0.04  # x the model's bounding-box diagonal: how far occluders count
AO_STRENGTH = 0.65  # darkest multiplier = 1 - AO_STRENGTH
RIM_TINT = 0.6  # Godot rim_tint (as the non-atlas scenes)


@dataclass(frozen=True)
class Atlas:
    cells: tuple[tuple[str, str], ...]  # (base colour hex, material preset), sorted

    @property
    def columns(self) -> int:
        return min(len(self.cells), COLUMNS) or 1

    @property
    def rows(self) -> int:
        return max(1, math.ceil(len(self.cells) / COLUMNS))

    @property
    def size(self) -> tuple[int, int]:
        return self.columns * CELL, self.rows * CELL

    def index(self, color: str, preset: str) -> int:
        return self.cells.index((color, preset))

    def pixel(self, i: int) -> tuple[int, int]:
        """Top-left pixel of cell i."""
        return (i % COLUMNS) * CELL, (i // COLUMNS) * CELL

    def uv(self, i: int) -> tuple[float, float]:
        """The centre of cell i (glTF UVs: origin top left, v down)."""
        w, h = self.size
        x, y = self.pixel(i)
        return (x + CELL / 2) / w, (y + CELL / 2) / h

    def uvs(self, cells: Array) -> Array:
        return np.array([self.uv(int(c)) for c in cells], dtype=np.float64).reshape(-1, 2)

    def _png(self, values: list[tuple[int, int, int]]) -> bytes:
        image = Image.new("RGB", self.size, (0, 0, 0))
        for i, rgb in enumerate(values):
            x, y = self.pixel(i)
            image.paste(rgb, (x, y, x + CELL, y + CELL))
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=False)
        return buf.getvalue()

    def palette_png(self, swap: dict[str, str]) -> bytes:
        return self._png([_rgb(swap.get(c, c)) for c, _ in self.cells])

    def material_png(self, built: Built) -> bytes:
        presets = built.style.materials
        return self._png([(0, _byte(p.roughness), _byte(p.metallic)) for p in (presets.get(m, presets["default"]) for _, m in self.cells)])

    def glow_strength(self, built: Built) -> float:
        """The largest emission of any cell's preset (0: no glow texture). It becomes the emissive strength; texels
        hold colour x emission / strength."""
        presets = built.style.materials
        return max((presets.get(m, presets["default"]).emission for _, m in self.cells), default=0.0)

    def glow_png(self, built: Built, swap: dict[str, str]) -> bytes:
        presets = built.style.materials
        strength = self.glow_strength(built)
        values = []
        for c, m in self.cells:
            e = presets.get(m, presets["default"]).emission / strength
            values.append(tuple(_encode(_decode(v) * e) for v in _rgb(swap.get(c, c))))
        return self._png(values)  # type: ignore[arg-type]

    def has_rim(self, built: Built) -> bool:
        presets = built.style.materials
        return any(presets.get(m, presets["default"]).rim > 0 for _, m in self.cells)

    def rim_png(self, built: Built) -> bytes:
        """Godot's rim texture: R = rim (x the material's rim 1.0), G = tint (x rim_tint)."""
        presets = built.style.materials
        return self._png([(_byte(presets.get(m, presets["default"]).rim), 255, 0) for _, m in self.cells])


@dataclass(frozen=True)
class AtlasUse:
    """What a glb needs to use an atlas: the layout and its textures' URIs (relative to the glb)."""

    atlas: Atlas
    palette: str
    material: str
    glow: str | None = None  # set when a preset glows
    ao: bool = False
    glow_strength: float = 0.0


def layout(builts: list[Built]) -> Atlas:
    """The cells every non-decal face of these builds (a model and its LODs) needs, so they share textures."""
    cells: set[tuple[str, str]] = set()
    for b in builts:
        p = b.painted
        used = np.unique(p.face_group[p.face_decal < 0])
        cells.update((p.groups[int(g)].color, p.groups[int(g)].material) for g in used)
    return Atlas(tuple(sorted(cells)))


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)


def _byte(v: float) -> int:
    return int(round(min(max(v, 0.0), 1.0) * 255))


def _decode(v: int) -> float:
    c = v / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _encode(c: float) -> int:
    s = c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return _byte(s)


# --- ambient occlusion -------------------------------------------------------------------------------------


def vertex_normals(built: Built) -> Array:
    """Per vertex: the mean of its corner normals (unit)."""
    p = built.painted
    acc = np.zeros_like(p.vertices, dtype=np.float64)
    np.add.at(acc, p.faces.reshape(-1), built.normals.reshape(-1, 3))
    return np.asarray(acc / np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12))


def ambient_occlusion(built: Built) -> Array:
    """(V,) multipliers in [1 - AO_STRENGTH, 1] for every painted vertex (unused vertices get 1)."""
    p = built.painted
    ao = np.ones(len(p.vertices))
    used = np.unique(p.faces)
    if not len(used):
        return ao
    m = built.model
    occlusion = _cavity(built, used) if m.source is not None or not m.parts else _field_occlusion(built, used)
    ao[used] = 1.0 - AO_STRENGTH * np.clip(occlusion, 0.0, 1.0)
    return np.round(ao, 4)  # rounded: the same multiplier whatever float noise the field adds


def _field_occlusion(built: Built, used: Array) -> Array:
    """Classic SDF occlusion: step out along the normal; where the field grows slower than the distance walked,
    something is near. Near steps weigh most (1/2^i)."""
    p = built.painted
    points, normals = p.vertices[used], vertex_normals(built)[used]
    lo, hi = points.min(axis=0), points.max(axis=0)
    radius = max(AO_RADIUS * float(np.linalg.norm(hi - lo)), built.step * 2)
    field = Field([part.geometry for part in built.model.parts], margin=built.step * 3)
    steps = radius * np.arange(1, AO_STEPS + 1) / AO_STEPS
    stacked = np.concatenate([points] + [points + normals * s for s in steps])
    d = field.distance(stacked).reshape(AO_STEPS + 1, len(points))
    weights = 0.5 ** np.arange(1, AO_STEPS + 1)
    weights /= weights.sum()
    occ = np.zeros(len(points))
    for i, s in enumerate(steps):
        occ += weights[i] * np.clip((s - (d[i + 1] - d[0])) / s, 0.0, 1.0)
    return occ


def _cavity(built: Built, used: Array) -> Array:
    """Imported meshes (no field): concavity from the neighbours' mean position against the normal."""
    p = built.painted
    v, f = p.vertices, p.faces
    total = np.zeros_like(v, dtype=np.float64)
    count = np.zeros(len(v))
    for a, b in ((0, 1), (1, 2), (2, 0)):
        np.add.at(total, f[:, a], v[f[:, b]])
        np.add.at(total, f[:, b], v[f[:, a]])
        np.add.at(count, f[:, a], 1)
        np.add.at(count, f[:, b], 1)
    mean = total[used] / np.maximum(count[used], 1)[:, None]
    offset = mean - v[used]
    edge = np.maximum(np.linalg.norm(offset, axis=1), 1e-12)
    depth = (offset * vertex_normals(built)[used]).sum(axis=1) / edge  # > 0: neighbours above the vertex (a dent)
    return np.asarray(np.clip(depth, 0.0, 1.0))


__all__ = ["CELL", "RIM_TINT", "Atlas", "AtlasUse", "ambient_occlusion", "layout", "vertex_normals"]
