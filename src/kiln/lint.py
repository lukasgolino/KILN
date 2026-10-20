"""`kiln lint`: format errors (E) from parsing, and warnings (W) about things that build but look wrong.

Geometric warnings need the model built (meshing is cached, so a second lint is fast).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from kiln.builder import build_cached, field_of
from kiln.export import Built
from kiln.notation import Model
from kiln.project import Project
from kiln.style import Style
from pagan.findings import Finding

WARNING_RULES = {
    "W101": "a part has no visible surface (covered by later parts, or cut away)",
    "W102": "a part is thinner than the style's mesh resolution (it may break up)",
    "W103": "the model is in several separate pieces (floating parts)",
    "W104": "a colour isn't from the project's palette",
    "W106": "the model doesn't stand on y = 0 (the origin is at its feet)",
    "W107": "made under an older style_version",
    "W108": "the model's size is unusual for its class (metres!)",
    "W109": "an animated part has no rig pivot (it turns about its box centre)",
    "W110": "the model is well over its triangle budget (patterns need many small triangles)",
}

CLASS_SIZES = {  # (min, max) of the largest side in metres: catches cm-vs-m mistakes
    "character": (0.2, 4.0), "creature": (0.1, 12.0), "prop": (0.02, 6.0), "vehicle": (0.5, 30.0),
    "machine": (0.3, 30.0), "building": (1.0, 200.0), "nature": (0.05, 60.0), "hero": (0.2, 6.0),
}  # fmt: skip


@dataclass
class LintResult:
    findings: list[Finding] = field(default_factory=list)
    models: dict[str, tuple[Model, Style]] = field(default_factory=dict)
    built: dict[str, Built] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]


def _thickness(part_params: dict[str, object], shape: str) -> float | None:
    p = part_params
    if shape == "sphere":
        return 2 * float(p["radius"])  # type: ignore[arg-type]
    if shape in ("capsule", "tube"):
        return 2 * min(float(p["radius"]), float(p["radius_to"]))  # type: ignore[arg-type]
    if shape == "torus":
        return 2 * float(p["thickness"])  # type: ignore[arg-type]
    if shape in ("box", "wedge", "ellipsoid"):
        key = "size" if shape != "ellipsoid" else "radii"
        scale = 1.0 if shape != "ellipsoid" else 2.0
        return scale * min(float(v) for v in p[key])  # type: ignore[attr-defined]
    if shape == "cylinder":
        return min(2 * float(p["radius"]), float(p["height"]))  # type: ignore[arg-type]
    if shape == "cone":
        return float(p["height"])  # type: ignore[arg-type]
    return None


def geometry_warnings(built: Built, palette: dict[str, str], project: Project) -> list[Finding]:
    m = built.model
    out: list[Finding] = []

    def warn(rule: str, message: str, line: int | None = None, where: str = "") -> None:
        out.append(Finding(rule, message, m.path, line, where))

    if m.source is None:
        field_ = field_of(m, built.step)
        verts = built.painted.vertices
        adding = [i for i, p in enumerate(m.parts) if p.geometry.op == "add"]
        if adding and len(verts):
            d = np.array([field_.part_distance(i, verts) for i in adding])
            near = np.abs(d) < built.step * 1.5
            for k, i in enumerate(adding):
                part = m.parts[i]
                if not near[k].any():
                    warn("W101", f"part {part.index} ({part.geometry.shape}, {part.color_name}) has no visible surface: later parts cover it or a "
                         "cut removes it; move it out, or make the covering part a shell", part.line, part.where)  # fmt: skip
        for part in m.parts:
            if part.geometry.op != "add":
                continue
            t = _thickness(part.geometry.params, part.geometry.shape)
            if t is not None and t < 2 * built.step:
                warn("W102", f"this {part.geometry.shape} is {t:.3g} m thick but the mesh resolution here is {built.step:.3g} m: it may break "
                     f"into bits; make it at least {2 * built.step:.3g} m thick", part.line, part.where)  # fmt: skip
        if palette:
            hexes = set(palette.values())
            for part in m.parts:
                if part.geometry.op == "add" and part.color not in hexes:
                    warn("W104", f"colour {part.color} isn't in the palette: use a palette colour name", part.line, f"{part.where}.color")
    budget = m.budget or built.style.budget(m.cls)
    if m.source is None and built.triangles > budget * 1.25:
        patterned = sum(1 for p in m.parts if p.pattern is not None)
        why = f"its {patterned} pattern(s) need edges shorter than their repeat" if patterned else "fine details and colour borders"
        warn("W110", f"{built.triangles} triangles for a budget of {budget}: {why}. Use bigger pattern repeats, fewer patterns, model "
             "the details as parts, or raise budget:")  # fmt: skip
    if built.pieces > 1:
        warn("W103", f"the model is {built.pieces} separate pieces: a floating part, or a gap between parts that should touch")
    lo, hi = built.bounds()
    size = float((hi - lo).max())
    if abs(float(lo[1])) > max(0.01, 0.01 * size):
        warn("W106", f"the lowest point is at y = {float(lo[1]):.3g} m: models stand on y = 0 (feet, wheels, base). Move the parts, "
             "or disable W106 for things that hang or float")  # fmt: skip
    limits = CLASS_SIZES.get(m.cls)
    if limits and not limits[0] <= size <= limits[1]:
        warn("W108", f"a {m.cls} {size:.3g} m across is unusual (expected {limits[0]:g}-{limits[1]:g} m): units are metres")
    animated = {name for t in built.tracks for name in _moved(m, t.name)}
    for name in sorted(animated):
        entry = m.rig.get(name)
        if name != "root" and (entry is None or entry.pivot is None):
            warn("W109", f"part {name!r} is animated but has no rig pivot: it turns about the middle of its box; set rig: {{ {name}: {{ pivot: [x, y, z] }} }}")
    return out


def _moved(m: Model, anim: str) -> set[str]:
    a = m.animations[anim]
    if a.cycle is not None:
        from kiln.rig import expand_cycle

        poses = expand_cycle(a, m)
    else:
        poses = a.poses
    return {name for pose in poses for name, pp in pose.items() if any(pp.rotate)}


def lint_paths(project: Project, paths: list[Path], geometry: bool = True) -> LintResult:
    result = LintResult()
    cache = project.root / ".kiln-cache"
    for path in paths:
        model, style, findings = project.load(path)
        keep = list(findings)
        if model is not None and style is not None and not any(f.severity == "error" for f in findings):
            if model.style_version is not None and model.style_version < project.config.style_version:
                keep.append(Finding("W107", f"made under style_version {model.style_version}; the project is at {project.config.style_version}: "
                                    "check it still fits, then `kiln mark <model> --current`", path, None, "style_version"))  # fmt: skip
            if geometry:
                palette, _ = project.palette(model.palette)
                try:
                    built = build_cached(model, style, palette, cache)
                except ValueError as exc:
                    keep.append(Finding("E009", str(exc), path, None, "parts"))
                else:
                    result.built[model.name] = built
                    keep += geometry_warnings(built, palette, project)
            if not any(f.severity == "error" for f in keep):
                result.models[model.name] = (model, style)
        disabled = set(project.config.lint_disable) | set(model.lint_disable if model else ())
        result.findings += [f for f in keep if not (f.severity == "warning" and f.rule in disabled)]
    return result


def lint_project(project: Project, geometry: bool = True) -> LintResult:
    return lint_paths(project, project.model_paths(), geometry)


__all__ = ["CLASS_SIZES", "LintResult", "WARNING_RULES", "geometry_warnings", "lint_paths", "lint_project"]
