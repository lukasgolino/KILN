"""`kiln lint`: format errors (E) from parsing, and warnings (W) about things that build but look wrong.

Geometric warnings need the model built (meshing is cached, so a second lint is fast).
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path


import numpy as np

from kiln.builder import build_cached, cached, field_of, hard_parts, kept_parts
from kiln.export import Built
from kiln.mesher import crack_groups, open_edges, pinches
from kiln.notation import Model
from kiln.project import Project
from kiln.sdf import Array, part_thickness
from kiln.style import Style
from kiln.vendor.findings import Finding

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
    "W111": "a part was lost when the mesh was reduced to its triangle budget (budget too low)",
    "W112": "a LOD came out well above its triangle target",
    "W113": "a part pokes through another part's shell (eyes through a visor, a head through a helmet)",
    "W114": "a model's joints sit elsewhere than in its animation_library (from kiln build)",
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


CRACKS_SHOWN = 5  # E013 lists this many cracks


def geometry_warnings(built: Built, palette: dict[str, str], project: Project) -> list[Finding]:
    m = built.model
    out: list[Finding] = []

    def warn(rule: str, message: str, line: int | None = None, where: str = "") -> None:
        out.append(Finding(rule, message, m.path, line, where))

    if m.source is None:
        p = built.painted

        def places(pairs: Array, corners: int) -> str:
            """Where these vertex pairs are, grouped (connected ones together): how many, where, on what (the faces
            with at least `corners` of their vertices)."""
            found = []
            groups = crack_groups(pairs)
            for g in groups[:CRACKS_SHOWN]:
                centre = p.vertices[pairs[g]].reshape(-1, 3).mean(axis=0)
                on = np.isin(p.faces, np.unique(pairs[g])).sum(axis=1) >= corners
                names = sorted({f"{p.groups[k].color_name.split('#')[0] or p.groups[k].color_name} ({p.groups[k].bone})" for k in np.unique(p.face_group[on])})
                found.append(f"{len(g)} at [{centre[0]:.3f}, {centre[1]:.3f}, {centre[2]:.3f}] on {', '.join(names[:3])}")
            more = f"; and {len(groups) - CRACKS_SHOWN} more" if len(groups) > CRACKS_SHOWN else ""
            return f"{len(groups)} place(s): {'; '.join(found)}{more}"

        report = "a KILN bug, please report it with the model; meanwhile moving the parts there a little usually helps"
        cracks = open_edges(p.vertices, p.faces)
        if len(cracks):
            warn("E013", f"the mesh has {len(cracks)} open edges (cracks) in {places(cracks, 2)}: {report}")
        crowded, pinched = pinches(p.vertices, p.faces)
        if len(crowded) or len(pinched):
            spots = np.concatenate([crowded, np.stack([pinched, pinched], axis=1)])
            warn("E013", f"the mesh isn't a manifold: {len(crowded)} edge(s) with more than two faces and {len(pinched)} point(s) where "
                 f"two sheets touch, in {places(spots, 1)}: {report}")  # fmt: skip
        for i in built.hidden:
            part = m.parts[i]
            warn("W101", f"part {part.index} ({part.geometry.shape}, {part.color_name}) has no visible surface: later parts cover it or a "
                 "cut removes it; move it out, or make the covering part a shell", part.line, part.where)  # fmt: skip
        for i in built.lost:
            part = m.parts[i]
            warn("W111", f"part {part.index} ({part.geometry.shape}, {part.color_name}) is there at full detail but the triangle budget "
                 f"({m.budget or built.style.budget(m.cls)}) is too low to keep it: raise budget:, or make it thicker", part.line, part.where)  # fmt: skip
        hard = hard_parts(m, built.style)  # exact polygons: no mesh resolution
        kept = kept_parts(m, hard)  # meshed finer: they don't break up
        for k, part in enumerate(m.parts):
            if part.geometry.op != "add" or k in kept or k in hard:
                continue
            t = part_thickness(part.geometry)
            if t is not None and t < 2 * built.step:
                warn("W102", f"this {part.geometry.shape} is {t:.3g} m thick but the mesh resolution here is {built.step:.3g} m: it may break "
                     f"into bits; make it at least {2 * built.step:.3g} m thick", part.line, part.where)  # fmt: skip
        if palette:
            hexes = set(palette.values())
            for part in m.parts:
                if part.geometry.op == "add" and part.color not in hexes:
                    warn("W104", f"colour {part.color} isn't in the palette: use a palette colour name", part.line, f"{part.where}.color")
    if m.source is None:
        for i, j, volume, centre in penetrations(built):
            a, b = m.parts[i], m.parts[j]
            warn("W113", f"part {b.index} ({b.geometry.shape}, {b.color_name}) pokes through the shell of part {a.index} ({a.geometry.shape}, "
                 f"{a.color_name}) around [{centre[0]:.2f}, {centre[1]:.2f}, {centre[2]:.2f}] ({volume * 1e6:.0f} cm3 inside its wall): move or "
                 "shrink it so it stays inside (or outside), or cut it where it meets the wall", b.line, b.where)  # fmt: skip
    if m.fit_to is not None:  # an attachment mustn't sink into the character it's made for
        from kiln.fitting import MeshDistance, read_surface

        pv = built.painted
        surface = MeshDistance.build(*read_surface(m.fit_to[0], m.fit_to[2]), built.bounds())
        depth = surface.distance(pv.vertices[np.unique(pv.faces)])
        inside = depth < -2 * built.step
        if inside.any():
            where = pv.vertices[np.unique(pv.faces)][inside].mean(axis=0)
            warn("W113", f"{int(inside.sum())} points of it are inside {m.fit_to[0].name} (up to {float(-depth.min()) * 100:.1f} cm) around "
                 f"[{where[0]:.2f}, {where[1]:.2f}, {where[2]:.2f}]: move it out, or wrap it with fit: target", None, "fit_to")  # fmt: skip
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
    tol = max(0.01, 0.01 * size)
    grounded = m.origin is not None or abs(float(lo[1])) <= tol  # a model with an explicit `origin` chose its own anchor
    if not grounded and m.parts:  # the mesh may sit up to a cell above the shapes' own bottom (rounded edges, coarse cells)
        from kiln.builder import field_of

        shapes_lo = float(field_of(m, built.step).bounds()[0][1])
        grounded = abs(shapes_lo) <= tol and 0 <= float(lo[1]) - shapes_lo <= 1.5 * built.step
    if not grounded:
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


def penetrations(built: Built) -> list[tuple[int, int, float, Array]]:
    """(shell part, part poking through it, overlap volume in m3, where) for every part whose solid crosses a shell's
    wall and shows outside it next to the wall. Parts sharing the shell's id are its own details (a crest)."""
    m = built.model
    shells = [i for i, p in enumerate(m.parts) if p.geometry.op == "add" and p.geometry.shell]
    if not shells:
        return []
    field = field_of(m, built.step)
    adding = [i for i, p in enumerate(m.parts) if p.geometry.op == "add"]
    pv = built.painted
    centres = pv.vertices[pv.faces].mean(axis=1)
    owner = np.asarray(adding)[np.stack([np.abs(field.part_distance(i, centres)) for i in adding]).argmin(axis=0)]
    step = built.step
    out = []
    for i in shells:
        gi = m.parts[i].geometry
        for j in adding:
            if j == i or m.parts[j].id == m.parts[i].id or m.parts[j].geometry.shell or (gi.fit is not None and any(m.parts[j].geometry is t for t in gi.fit[0])):
                continue  # its own details, other shells, and what it's fitted around (kept a gap away by construction)
            lo = np.maximum(field.boxes[i][0], field.boxes[j][0])
            hi = np.minimum(field.boxes[i][1], field.boxes[j][1])
            if (hi <= lo).any():
                continue
            h = max(step, float(np.prod(hi - lo) / 200_000) ** (1 / 3))
            axes = [np.arange(a + h / 2, b, h) for a, b in zip(lo, hi, strict=True)]
            if any(len(a) == 0 for a in axes):
                continue
            pts = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
            overlap = (m.parts[j].geometry.distance(pts) < 0) & (gi.distance(pts) < 0)
            volume = float(overlap.sum()) * h**3
            if volume < (2 * step) ** 3:
                continue
            mine = centres[owner == j]
            if not len(mine):
                continue
            envelope = gi.distance(mine, filled=True)
            if ((envelope > 0) & (envelope < gi.shell + 2 * step)).any():
                out.append((i, j, volume, pts[overlap].mean(axis=0)))
    return out


def _moved(m: Model, anim: str) -> set[str]:
    a = m.animations[anim]
    from kiln.rig import animation_poses

    poses = animation_poses(a, m)
    return {name for pose in poses for name, pp in pose.items() if any(pp.rotate)}


def _build_job(job: tuple[Model, Style, dict[str, str], Path]) -> Built | str:
    try:
        return build_cached(*job)
    except ValueError as exc:
        return str(exc)


WORKER_MEMORY = 0.7  # GB a worker may need for a big model (measured: up to ~0.6); more workers than RAM allows thrash


def _jobs() -> int:
    """KILN_JOBS, else every core, but no more workers than the free memory carries."""
    try:
        asked = int(os.environ.get("KILN_JOBS", "0"))
    except ValueError:
        asked = 0
    if asked > 0:
        return asked
    cores = os.cpu_count() or 1
    try:
        with open("/proc/meminfo", encoding="ascii") as fh:
            info = dict(line.split(":", 1) for line in fh)
        free_gb = int(info["MemAvailable"].split()[0]) / 1024**2
        return max(1, min(cores, int(free_gb / WORKER_MEMORY)))
    except (OSError, KeyError, ValueError):
        return cores


def build_all(jobs: list[tuple[Model, Style, dict[str, str], Path]]) -> list[Built | str]:
    """Build (or load from the cache) several models, in parallel processes when there are several to mesh.
    Each model is built exactly as alone, so the output doesn't depend on the number of processes (KILN_JOBS)."""
    todo = [k for k, (m, st, pal, cache) in enumerate(jobs) if not cached(m, st, pal, cache)]
    workers = min(_jobs(), len(todo))
    out: list[Built | str | None] = [None] * len(jobs)
    if workers > 1:
        method = "forkserver" if sys.platform.startswith("linux") else "spawn"
        try:
            with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context(method)) as pool:
                for k, built in zip(todo, pool.map(_build_job, [jobs[k] for k in todo]), strict=True):
                    out[k] = built
        except BrokenProcessPool:  # a worker died (out of memory): build the rest one at a time
            pass
    return [o if o is not None else _build_job(jobs[k]) for k, o in enumerate(out)]


def lint_paths(project: Project, paths: list[Path], geometry: bool = True) -> LintResult:
    result = LintResult()
    cache = project.root / ".kiln-cache"
    loaded = []
    for path in paths:
        model, style, findings = project.load(path)
        keep = list(findings)
        palette: dict[str, str] = {}
        if model is not None and style is not None and not any(f.severity == "error" for f in findings):
            if model.style_version is not None and model.style_version < project.config.style_version:
                keep.append(Finding("W107", f"made under style_version {model.style_version}; the project is at {project.config.style_version}: "
                                    "check it still fits, then `kiln mark <model> --current`", path, None, "style_version"))  # fmt: skip
            palette, _ = project.palette(model.palette)
        loaded.append((path, model, style, palette, keep))
    names = {p.name.split(".")[0] for p in project.model_paths()}
    for path, model, _, _, keep in loaded:  # an effect's emitters are other models in the project
        missing = sorted({e.model for e in model.effect.emitters} - names) if model is not None and model.effect is not None else []
        if missing:
            keep.append(Finding("E011", f"effect emits {', '.join(missing)}: no models/<name>.kiln.yaml for it", path, None, "effect"))
    # templates are bases, not models: checked as text only
    meshed = [k for k, (_, m, st, _, keep) in enumerate(loaded) if geometry and m and st and not m.template and not any(f.severity == "error" for f in keep)]
    builds = dict(zip(meshed, build_all([(loaded[k][1], loaded[k][2], loaded[k][3], cache) for k in meshed]), strict=True))  # type: ignore[misc]
    for k, (path, model, style, palette, keep) in enumerate(loaded):
        if k in builds:
            built = builds[k]
            if isinstance(built, str):
                keep.append(Finding("E009", built, path, None, "parts"))
            else:
                assert model is not None
                result.built[model.name] = built
                keep += geometry_warnings(built, palette, project)
        if model is not None and style is not None and not any(f.severity == "error" for f in keep) and not model.template:
            result.models[model.name] = (model, style)
        disabled = set(project.config.lint_disable) | set(model.lint_disable if model else ())
        result.findings += [f for f in keep if not (f.severity == "warning" and f.rule in disabled)]
    return result


def lint_project(project: Project, geometry: bool = True) -> LintResult:
    return lint_paths(project, project.model_paths(), geometry)


__all__ = ["CLASS_SIZES", "LintResult", "WARNING_RULES", "geometry_warnings", "lint_paths", "lint_project"]
