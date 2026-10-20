"""Style profiles: everything that makes a game's models look like one game.

A style decides how shapes become meshes (smooth or faceted, how fine), the triangle budget per size class,
the material presets (roughness, metal, glow) and the look kit (shader, outlines, lighting, sky, grading).
KILN ships presets (`kiln style list`); a project adds its own in `styles/<name>.style.toml`, usually
`extends`-ing a preset, often written from inspiration images.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

from kiln.vendor.findings import Finding

STYLE_SUFFIX = ".style.toml"
SHADERS = ("standard", "toon")
HARD_MODES = ("auto", "always", "never")
TONEMAPPERS = ("linear", "filmic", "aces", "agx")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class MaterialPreset:
    roughness: float = 0.5
    metallic: float = 0.0
    emission: float = 0.0  # glow strength (multiplies the part's colour)
    rim: float = 0.0  # soft-light rim (Godot: rim), 0..1


@dataclass(frozen=True)
class Look:
    shader: str = "standard"
    toon_bands: int = 3
    outline: float = 0.0  # metres; 0 = no outline
    outline_color: str = "#1a1420"
    tonemapper: str = "filmic"
    exposure: float = 1.0
    saturation: float = 1.0
    contrast: float = 1.0
    ssao: bool = True
    glow: bool = False
    ambient: float = 0.9
    sky_top: str = "#4f8fe0"
    sky_horizon: str = "#bcd7f2"
    ground: str = "#9fb98a"
    sun_pitch: float = -48.0
    sun_yaw: float = 30.0
    sun_energy: float = 1.1
    sun_color: str = "#fff6e8"
    shadows: bool = True
    fog: float = 0.0  # density; 0 = none
    fog_color: str = "#c8d8e8"


@dataclass(frozen=True)
class Style:
    name: str
    description: str
    smooth: bool
    sharp_angle: float  # degrees: crisper edges than this keep flat normals in smooth styles
    resolution: float  # metres per grid cell for a ~1 m model
    budgets: dict[str, int]
    materials: dict[str, MaterialPreset]
    look: Look
    notes: str = ""  # proportions and shape language, for the agent
    path: Path | None = None
    text: str = ""  # for cache keys
    hard_surface: str = "auto"  # auto: parts asking for it (sides, bevel, blend: none); always: every part that can; never
    hard_sides: int = 12  # sides of round hard shapes that don't say

    def budget(self, cls: str) -> int:
        return self.budgets.get(cls, self.budgets.get("default", 4000))


SHAPE_KEYS = {"smooth": bool, "sharp_angle": float, "resolution": float, "hard_surface": str, "hard_sides": int}
LOOK_TYPES: dict[str, type] = {k: type(v) for k, v in Look().__dict__.items()}


def builtin_dir() -> Path:
    return Path(str(files("kiln").joinpath("styles")))


def builtin_names() -> list[str]:
    return sorted(p.name[: -len(STYLE_SUFFIX)] for p in builtin_dir().glob(f"*{STYLE_SUFFIX}"))


def find_style_file(name: str, project_styles: Path | None) -> Path | None:
    if project_styles is not None:
        own = project_styles / f"{name}{STYLE_SUFFIX}"
        if own.is_file():
            return own
    builtin = builtin_dir() / f"{name}{STYLE_SUFFIX}"
    return builtin if builtin.is_file() else None


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _raw(name: str, project_styles: Path | None, seen: tuple[str, ...], findings: list[Finding]) -> tuple[dict[str, Any], str, Path | None]:
    path = find_style_file(name, project_styles)
    if path is None:
        known = ", ".join(builtin_names() + (sorted(p.name[: -len(STYLE_SUFFIX)] for p in project_styles.glob(f"*{STYLE_SUFFIX}")) if project_styles and project_styles.is_dir() else []))
        findings.append(Finding("E006", f"unknown style {name!r} (styles: {known})"))
        return {}, "", None
    text = path.read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        findings.append(Finding("E006", f"invalid TOML: {exc}", path))
        return {}, text, path
    parent = data.pop("extends", None)
    if parent is not None:
        if not isinstance(parent, str) or parent in seen or (parent == name and path.parent == builtin_dir()):
            findings.append(Finding("E006", f"extends must name another style (no cycles): {parent!r}", path, None, "extends"))
            return data, text, path
        # a project style may extend the built-in preset of the same name
        base_dir = project_styles if parent != name else None
        base, base_text, _ = _raw(parent, base_dir, (*seen, name), findings)
        data = _merge(base, data)
        text = base_text + "\n" + text
    return data, text, path


def load_style(name: str, project_styles: Path | None = None) -> tuple[Style | None, list[Finding]]:
    findings: list[Finding] = []
    data, text, path = _raw(name, project_styles, (), findings)
    if findings and path is None:
        return None, findings

    def bad(message: str, where: str) -> None:
        findings.append(Finding("E006", message, path, None, where))

    unknown = [k for k in data if k not in ("description", "notes", "shape", "budgets", "materials", "look")]
    if unknown:
        bad(f"unknown field(s) {', '.join(unknown)}; allowed: description, notes, extends, [shape], [budgets], [materials], [look]", unknown[0])
    shape = data.get("shape", {})
    for key in shape:
        if key not in SHAPE_KEYS:
            bad(f"unknown [shape] field {key!r}; allowed: {', '.join(SHAPE_KEYS)}", f"shape.{key}")
    smooth = shape.get("smooth", True)
    sharp = shape.get("sharp_angle", 40.0)
    resolution = shape.get("resolution", 0.008)
    if not isinstance(smooth, bool):
        bad("smooth is true (smooth shading) or false (faceted low-poly)", "shape.smooth")
    if not isinstance(sharp, int | float) or not 0 <= sharp <= 180:
        bad("sharp_angle is degrees (0-180)", "shape.sharp_angle")
    if not isinstance(resolution, int | float) or not 0.001 <= resolution <= 0.2:
        bad("resolution is metres per grid cell (0.001-0.2), e.g. 0.008", "shape.resolution")
    hard_surface = shape.get("hard_surface", "auto")
    hard_sides = shape.get("hard_sides", 12)
    if hard_surface not in HARD_MODES:
        bad("hard_surface is auto (parts with sides, bevel, chamfer or blend: none), always (every part that can) or never", "shape.hard_surface")
    if not isinstance(hard_sides, int) or isinstance(hard_sides, bool) or not 3 <= hard_sides <= 64:
        bad("hard_sides is how many sides round hard shapes get (3-64), e.g. 12", "shape.hard_sides")
    budgets = data.get("budgets", {})
    if not isinstance(budgets, dict) or not all(isinstance(v, int) and not isinstance(v, bool) and v >= 12 for v in budgets.values()):
        bad("budgets maps size classes to triangle counts (>= 12), e.g. character = 8000", "budgets")
        budgets = {}
    materials: dict[str, MaterialPreset] = {"default": MaterialPreset()}
    for mname, spec in data.get("materials", {}).items():
        if not isinstance(spec, dict) or any(k not in ("roughness", "metallic", "emission", "rim") for k in spec) \
                or not all(isinstance(v, int | float) and not isinstance(v, bool) and v >= 0 for v in spec.values()):
            bad("a material is { roughness = 0..1, metallic = 0..1, emission = 0.., rim = 0..1 }", f"materials.{mname}")
            continue
        materials[mname] = MaterialPreset(**{k: float(v) for k, v in spec.items()})
    look_raw = data.get("look", {})
    look_values: dict[str, Any] = {}
    for key, value in look_raw.items():
        if key not in LOOK_TYPES:
            bad(f"unknown [look] field {key!r}; allowed: {', '.join(LOOK_TYPES)}", f"look.{key}")
            continue
        expected = LOOK_TYPES[key]
        if expected is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            bad(f"[look] {key} must be a {expected.__name__}", f"look.{key}")
            continue
        if isinstance(value, str) and key.endswith(("color", "top", "horizon", "ground")) and not HEX.match(value):
            bad(f"[look] {key} must be \"#rrggbb\"", f"look.{key}")
            continue
        look_values[key] = value
    look = Look(**look_values)
    if look.shader not in SHADERS:
        bad(f"[look] shader is {' or '.join(SHADERS)}", "look.shader")
    if look.tonemapper not in TONEMAPPERS:
        bad(f"[look] tonemapper is one of {', '.join(TONEMAPPERS)}", "look.tonemapper")
    if any(f.severity == "error" for f in findings):
        return None, findings
    style = Style(name, str(data.get("description", "")), bool(smooth), float(sharp), float(resolution), dict(budgets), materials, look,
                  str(data.get("notes", "")), path, text, str(hard_surface), int(hard_sides))  # fmt: skip
    return style, findings


def style_summary(style: Style) -> dict[str, Any]:
    return {
        "name": style.name,
        "description": style.description,
        "smooth": style.smooth,
        "resolution": style.resolution,
        "hard_surface": style.hard_surface,
        "budgets": style.budgets,
        "materials": sorted(style.materials),
        "shader": style.look.shader,
        "outline": style.look.outline,
        "notes": style.notes,
        "path": str(style.path) if style.path else None,
    }


__all__ = ["Look", "MaterialPreset", "Style", "builtin_names", "load_style", "style_summary"]
