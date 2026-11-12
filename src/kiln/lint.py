"""`kiln lint`: format errors (E) from parsing, and warnings (W) about things that build but look wrong.

Geometric warnings need the model built (meshing is cached, so a second lint is fast).
"""

from __future__ import annotations

import math
import multiprocessing
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from kiln.bake import texel_size
from kiln.builder import build_cached, build_error, cached, field_of, hard_parts, kept_parts
from kiln.cover import covers, mostly_covered
from kiln.export import Built
from kiln.jit import set_threads
from kiln.mesher import CELL_LIMIT, crack_groups, mesh_steps, open_edges, pinches
from kiln.notation import Model
from kiln.packs import lock_findings
from kiln.project import Project
from kiln.retarget import JOINTS
from kiln.sdf import Array, Field, Geometry, part_thickness
from kiln.style import MaterialPreset, Style
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
    "W115": "kiln.lock lists a file that isn't in the project any more",
    "W116": "a terrain's splat layer barely shows anywhere (its rules hardly ever hold)",
    "W117": "a terrain's height shape lies off the map (it changes nothing)",
    "W118": "a scatter entry places very many instances (big scene and JSON files)",
    "W119": "a scatter entry places no instances (its rules never hold, or nothing is under it)",
    "W120": "the mesh grid cap (max_cells), not the resolution asked for, set the mesh step (details come out coarser)",
    "W121": "a detail part shows nowhere: the model has no normal_map, or it is thinner than two of the map's texels",
    "W122": "a blend_to part can't melt into a target: it is hard, kept, separate or another bone's piece (they join crisply)",
    "W123": "the built mesh dips a little below y = 0 (blends and meshing push the feet under the ground)",
    "W124": "a part shows only a sliver: nearly all of it is inside other parts (clipped flat or nearly gone)",
    "W125": "the normal map is too small for the mesh's UV charts: they were squeezed in (blurrier detail, less padding)",
    "W126": "a relief layer has no patches: the parts it is on show no smooth, non-glowing surface",
    "W127": "color_blend fades nothing: the part has no border it blends across with a part of another colour",
    "W128": "a round part got so few triangles that it reads as a polygon (many small parts share one budget)",
    "W129": "skin_falloff does nothing here (not a soft skin, or a hard, kept, separate or cutting part)",
    "W130": "a variant leaves a colour as it is that goes with one it swaps (same ramp, or close in hue): a seam in the old colour",
    "W131": "a see-through material (alpha < 1) in an atlas project: the atlas draws every part opaque",
    "W132": "a pose's reach is on a part without exactly one child part: it only points the part there (aim)",
    "W133": "a relief layer's patches are under four texels of the map wide: they blur out",
    "W135": "a limb is fused to another branch of a soft-skinned body at rest, away from its joint: posing it stretches the skin",
    "W134": "colour fades go in the vertex colours here (no baked maps), but the project doesn't export vertex colours",
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


GROUND_DIP = 0.002  # W123: metres below y = 0 a grounded model's built mesh may reach unremarked (or a tenth of a cell)
CAPPED = 1.05  # W120: the grid cap made the mesh cells this much coarser than asked
# The findings that need the built model, so `kiln lint --fast` can't give them (tests check the list against
# geometry_warnings): E009 is the build itself failing.
BUILT_RULES = ("E009", "E013", "W101", "W102", "W103", "W104", "W106", "W108", "W109", "W110", "W111", "W113", "W120", "W121", "W122", "W123",
               "W124", "W125", "W126", "W127", "W128", "W129", "W132", "W133", "W135")  # fmt: skip
CRACKS_SHOWN = 5  # E013 lists this many cracks


def geometry_warnings(built: Built, palette: dict[str, str], project: Project) -> list[Finding]:
    m = built.model
    out: list[Finding] = []

    def warn(rule: str, message: str, line: int | None = None, where: str = "") -> None:
        out.append(Finding(rule, message, m.path, line, where))

    if built.skin == "soft":  # limbs fused to the body at rest (#255)
        from kiln.fused import fused_limbs

        for message, line, where in fused_limbs(built)[:3]:
            warn("W135", message, line, where)
    for aname, anim in m.animations.items():  # reach needs a two-part chain (#200)
        for pose in anim.poses:
            for pid, pp in pose.items():
                if pp.reach is not None and pid in {b.name for b in built.skeleton.bones}:
                    i = built.skeleton.index(pid)
                    if sum(b.parent == i for b in built.skeleton.bones) != 1:
                        warn("W132", f"animation {aname}: {pid} has {sum(b.parent == i for b in built.skeleton.bones)} child parts, so reach only "
                             "points it (aim); reach goes on the upper of two parts (upper arm + forearm)", None, f"animations.{aname}")  # fmt: skip
                        break
            else:
                continue
            break

    field: Field | None = None
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
        field = field_of(m, built.step) if m.parts else None

        def named(parts: tuple[int, ...]) -> str:
            shown = [f"part {m.parts[j].index} ({m.parts[j].geometry.shape}, {m.parts[j].color_name})" for j in parts[:3]]
            return ", ".join(shown) + (f" and {len(parts) - 3} more" if len(parts) > 3 else "")

        exact = frozenset(hard_parts(m, built.style))
        hidden_by = covers(m, field, built.step, [i for i in built.hidden if m.parts[i].geometry.op == "add"], exact) if field and built.hidden else {}
        for i in built.hidden:
            part = m.parts[i]
            by = hidden_by[i].by if i in hidden_by else ()
            what = f"{named(by)} cover{'s' if len(by) == 1 else ''} it" if by else "later parts cover it or a cut removes it"
            warn("W101", f"part {part.index} ({part.geometry.shape}, {part.color_name}) has no visible surface: {what}; move it out, or "
                 "make the covering part a shell", part.line, part.where)  # fmt: skip
        for i, c in (mostly_covered(m, field, built.step, built.hidden, exact) if field else {}).items():
            part = m.parts[i]
            warn("W124", f"part {part.index} ({part.geometry.shape}, {part.color_name}) is {c.covered * 100:.0f}% inside {named(c.by)}: only "
                 "a sliver shows (clipped flat or nearly gone); move it out, or make it bigger", part.line, part.where)  # fmt: skip
        for i in built.lost:
            part = m.parts[i]
            warn("W111", f"part {part.index} ({part.geometry.shape}, {part.color_name}) is there at full detail but the triangle budget "
                 f"({m.budget or built.style.budget(m.cls)}) is too low to keep it: raise budget:, or make it thicker", part.line, part.where)  # fmt: skip
        hard = hard_parts(m, built.style)  # exact polygons: no mesh resolution
        kept = kept_parts(m, hard)  # meshed finer: they don't break up
        separate = {pid for pid, e in m.rig.items() if e.separate} if m.skin != "none" else set()
        per_bone = m.union == "per_bone" and m.skin == "rigid"
        for part in m.parts:
            g = part.geometry
            if not g.blend_to:
                continue
            apart = sorted({m.parts[j].id for j in g.blend_to if j in hard or j in kept or m.parts[j].id in separate
                            or (per_bone and m.parts[j].id != part.id)})  # fmt: skip
            if apart:
                warn("W122", f"blend_to {', '.join(apart)}: those parts are meshed apart from this one (hard, kept, separate or another "
                     "bone's piece), so it joins them crisply; make them soft and part of the same piece, or drop blend_to", part.line,
                     f"{part.where}.blend_to")  # fmt: skip
        for k, part in enumerate(m.parts):
            if part.geometry.op != "add" or k in kept or k in hard:
                continue
            t = part_thickness(part.geometry)
            if t is not None and t < 2 * built.step:
                warn("W102", f"this {part.geometry.shape} is {t:.3g} m thick but the mesh resolution here is {built.step:.3g} m: it may break "
                     f"into bits; make it at least {2 * built.step:.3g} m thick", part.line, part.where)  # fmt: skip
        budget = m.budget or built.style.budget(m.cls)
        for k, n, copies in few_triangles(m, built, field, hard | kept) if field else ():
            part = m.parts[k]
            each = f" in each of its {copies} copies" if copies > 1 else ""
            need = FEW_TRIANGLES / max(n, 1)  # how many times the triangles it has
            dense = min(8.0, math.ceil(part.density * need * 2) / 2)
            more = f"give it density: {dense:g}" + (f" (now {part.density:g})" if part.density != 1 else "") if part.density < 8 else ""
            raise_to = f"budget: {int(math.ceil(budget * need / 100) * 100)} (now {budget})"
            warn("W128", f"part {part.index} ({part.geometry.shape}, {part.color_name}) is {n} triangles{each}: it reads as a polygon; "
                 f"{more + ', or ' if more else ''}{raise_to}", part.line, part.where)  # fmt: skip
        for k, part in enumerate(m.parts):
            if part.skin_falloff is None:
                continue
            why = ("the skin isn't soft" if m.skin != "soft" else "it cuts" if part.geometry.op != "add" else "it is hard (exact polygons)"
                   if k in hard else "it is kept (meshed on its own)" if k in kept else "it is separate (meshed on its own)"
                   if part.id in separate else "")  # fmt: skip
            if why:
                warn("W129", f"skin_falloff does nothing here: {why}, so its surface follows its own bone already or isn't skinned; "
                     "drop it", part.line, f"{part.where}.skin_falloff")  # fmt: skip
        if m.detail:
            details = m.detail
            lo, hi = built.bounds()
            texel = texel_size(float((hi - lo).max()), m.normal_map) if m.normal_map else 0.0
            for g in details:
                t = part_thickness(g)
                if not m.normal_map:
                    warn("W121", f"{len(details)} detail part(s) but no normal_map: they show nowhere; add normal_map: 1024")
                    break
                if t is not None and t < 2 * texel:
                    warn("W121", f"a detail {g.shape} is {t:.3g} m thick, under two texels of the {m.normal_map} map ({2 * texel:.3g} m): it "
                         "won't show; make it thicker or the map bigger")  # fmt: skip
        if m.relief and m.normal_map:  # patches narrower than four texels blur out in the map (#261)
            lo, hi = built.bounds()
            texel = texel_size(float((hi - lo).max()), m.normal_map)
            for k, layer in enumerate(m.relief):
                if layer.width < 4 * texel:
                    warn("W133", f"relief layer {k} is {layer.width:.3g} m wide, under four texels of the {m.normal_map} map "
                         f"({4 * texel:.3g} m): its patches blur out; make them wider or the map bigger", None, f"relief[{k}].width")  # fmt: skip
        if built.bake is not None and built.bake.fit < 1.0:
            warn("W125", f"the mesh's UV charts don't fit the {m.normal_map} normal map (the padding between them alone fills it): they "
                 f"were squeezed to {built.bake.fit * 100:.0f}%, so detail blurs and charts can bleed at a distance; use normal_map: "
                 f"{min(4096, m.normal_map * 2)} or more")  # fmt: skip
        if built.bake is not None and built.bake.layers is not None:
            for k, count in enumerate(built.bake.layers.patches):
                if count == 0 and k < len(m.relief):
                    warn("W126", f"relief layer {k + 1} (on {', '.join(m.relief[k].on)}) has no patches: those parts show no smooth surface of "
                         "their own (covered by other parts, hard, glowing or under a decal)")  # fmt: skip
        if any(part.color_blend > 0 and part.color_blend_set for part in m.parts):  # (a style's default may find nothing to fade)
            lay = built.bake.layers if built.bake is not None else None
            if (lay is None or lay.mix is None or not (lay.mix > 0).any()) and built.corner_fade is None:
                first = next(part for part in m.parts if part.color_blend > 0 and part.color_blend_set)
                warn("W127", "color_blend fades nothing here (and still bakes the maps): a fade needs a neighbour of another colour that "
                     "the part joins with a blend (not a crisp seam, a hard or glowing part, or a decal)", first.line, f"{first.where}.color_blend")  # fmt: skip
        if built.asked_step and built.step > built.asked_step * CAPPED:
            cells = m.max_cells or built.style.max_cells
            need = math.ceil(built.step * (cells - 6) / built.asked_step) + 6  # the step is the model's size / (cells - 6)
            fix = f"set max_cells: {need}" if need <= CELL_LIMIT else f"set max_cells: {CELL_LIMIT} (the most), or a coarser resolution"
            warn("W120", f"meshed at {built.step * 1000:.3g} mm, not the {built.asked_step * 1000:.3g} mm asked for: {cells} cells across "
                 f"is the cap; {fix} (slower builds)")  # fmt: skip
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
        shapes_lo = float((field or field_of(m, built.step)).bounds()[0][1])
        grounded = abs(shapes_lo) <= tol and 0 <= float(lo[1]) - shapes_lo <= 1.5 * built.step
    if not grounded:
        warn("W106", f"the lowest point is at y = {float(lo[1]):.3g} m: models stand on y = 0 (feet, wheels, base). Move the parts, "
             "or disable W106 for things that hang or float")  # fmt: skip
    elif m.origin is None and float(lo[1]) < -max(GROUND_DIP, 0.1 * built.step):  # coarse cells round a little anyway
        warn("W123", f"the built mesh dips to y = {float(lo[1]) * 1000:.3g} mm, below the ground (blends and meshing can push it under the "
             "shapes' bottom): set origin: ground to lift the exported mesh onto y = 0, or raise the lowest parts a little")  # fmt: skip
    limits = CLASS_SIZES.get(m.cls)
    if limits and not limits[0] <= size <= limits[1]:
        warn("W108", f"a {m.cls} {size:.3g} m across is unusual (expected {limits[0]:g}-{limits[1]:g} m): units are metres")
    animated = {name for t in built.tracks for name in _moved(m, t.name)}
    for name in sorted(animated):
        entry = m.rig.get(name)
        humanoid_joint = m.skeleton == "humanoid" and name in JOINTS  # the skeleton sets its pivot at the joint (#187)
        if name != "root" and (entry is None or entry.pivot is None) and not humanoid_joint:
            warn("W109", f"part {name!r} is animated but has no rig pivot: it turns about the middle of its box; set rig: {{ {name}: {{ pivot: [x, y, z] }} }}")
    return out


SPLAT_SHOWN = 0.005  # W116: a layer covering less of the map than this


def terrain_warnings(model: Model, palette: dict[str, str], cache: Path) -> list[Finding]:
    """A terrain's warnings: shapes off the map (W117), splat layers that barely show (W116), colours off the palette."""
    from kiln.terrain import heightfield_cached

    t = model.terrain
    assert t is not None
    field_ = heightfield_cached(model.name, t, model.text, palette, cache)
    out = []
    for k in field_.shapes_outside:
        s = t.shapes[k]
        out.append(Finding("W117", f"this {s.kind} is off the map (x and z run from {-t.size[0] / 2:g} to {t.size[0] / 2:g}, {-t.size[1] / 2:g} to "
                           f"{t.size[1] / 2:g}): move it onto the map or remove it", model.path, s.line, f"terrain.{s.where}"))  # fmt: skip
    cover = field_.weights.reshape(-1, len(t.layers)).mean(axis=0)
    for layer, c in zip(t.layers, cover, strict=True):
        if c < SPLAT_SHOWN:
            out.append(Finding("W116", f"splat layer {layer.name} covers {float(c) * 100:.2f}% of the map: loosen its rules (lower slope above, "
                               "wider height band, larger path within, more noise cover) or remove it", model.path, layer.line, layer.where))  # fmt: skip
    hexes = set(palette.values())
    for layer in t.layers:
        if palette and layer.color not in hexes:
            out.append(Finding("W104", f"colour {layer.color} isn't in the palette: use a palette colour name", model.path, layer.line, f"{layer.where}.color"))
    return out


def scatter_findings(project: Project, model: Model, cache: Path, geometry: bool) -> list[Finding]:
    """A scatter's problems (E015: what it places or stands on) and, with geometry, its placement's warnings: very many
    instances (W118), none (W119), more than the scene holds (E015)."""
    from kiln import scatter as sc

    s = model.scatter
    assert s is not None
    surface, found = sc.surface_of(project, s, cache)
    found += sc.problems(project, s, surface)
    out = [Finding("E015", message, model.path, line, where) for message, where, line in found]
    if out or surface is None or not geometry:
        return out
    placed = sc.place(s, surface)
    for k, (p, n) in enumerate(zip(s.places, placed.counts, strict=True)):
        if n > sc.MANY_INSTANCES:
            out.append(Finding("W118", f"{n} instances of {', '.join(p.models)}: lower the density, add spacing or scatter a smaller size "
                               f"(more than {sc.MANY_INSTANCES} make big scenes and JSON)", model.path, p.line, f"scatter.place[{k}]"))  # fmt: skip
        elif n == 0:
            out.append(Finding("W119", f"no instances of {', '.join(p.models)} (from {placed.candidates[k]} candidates): raise the density or loosen "
                               "its rules (slope, height, noise cover, splat, path)", model.path, p.line, f"scatter.place[{k}]"))  # fmt: skip
    if placed.total > sc.MAX_INSTANCES:
        out.append(Finding("E015", f"{placed.total} instances (at most {sc.MAX_INSTANCES}): lower densities, add spacing or scatter a smaller size",
                           model.path, _line_of(model), "scatter.place"))  # fmt: skip
    return out


def _line_of(model: Model) -> int | None:
    return model.scatter.places[0].line if model.scatter is not None and model.scatter.places else None


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
    owner = np.asarray(adding)[field.nearest(adding, centres)[0]]
    step = built.step
    out = []
    for i in shells:
        gi = m.parts[i].geometry
        for j in adding:
            if j == i or m.parts[j].id == m.parts[i].id or m.parts[j].geometry.shell or (gi.fit is not None and any(m.parts[j].geometry is t for t in gi.fit[0])) \
                    or (m.parts[j].id in m.rig and m.parts[i].id in m.rig[m.parts[j].id].revealed):
                continue  # its own details, other shells, what it's fitted around (kept a gap away by construction), what it hides (hair)
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
    return {name for pose in poses for name, pp in pose.items() if any(pp.rotate) or pp.aim is not None or pp.reach is not None}


def _build_job(job: tuple[Model, Style, dict[str, str], Path]) -> Built | str:
    try:
        return build_cached(*job)
    except ValueError as exc:
        return build_error(exc)


WORKER_MEMORY = 0.7  # GB a worker may need for a big model (measured: up to ~0.6); more workers than RAM allows thrash
CELL_MEMORY = 36e-9  # GB per mesh grid cell (measured: a 2.4 m character at 4 mm, 79M cells, peaks at ~2.8 GB)


def job_memory(model: Model, style: Style) -> float:
    """GB meshing a model may need: fine grids (max_cells, resolution) take far more than the default."""
    if model.source is not None or not model.parts:
        return WORKER_MEMORY
    try:
        field = field_of(model, 0.01)
        step, _ = mesh_steps(field, model, style)
        lo, hi = field.bounds()
        cells = float(np.prod((hi - lo) / step + 6))
    except (ValueError, FloatingPointError):
        return WORKER_MEMORY
    return max(WORKER_MEMORY, 0.3 + cells * CELL_MEMORY)


def _jobs(memory: float = WORKER_MEMORY) -> int:
    """KILN_JOBS, else every core, but no more workers than the free memory carries (`memory` GB each)."""
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
        return max(1, min(cores, int(free_gb / memory)))
    except (OSError, KeyError, ValueError):
        return cores


def build_all(jobs: list[tuple[Model, Style, dict[str, str], Path]]) -> list[Built | str]:
    """Build (or load from the cache) several models, in parallel processes when there are several to mesh.
    Each model is built exactly as alone, so the output doesn't depend on the number of processes (KILN_JOBS)."""
    todo = [k for k, (m, st, pal, cache) in enumerate(jobs) if not cached(m, st, pal, cache)]
    need = max((job_memory(jobs[k][0], jobs[k][1]) for k in todo), default=WORKER_MEMORY)  # sized for the biggest
    workers = min(_jobs(need), len(todo))
    out: list[Built | str | None] = [None] * len(jobs)
    if workers > 1:
        method = "forkserver" if sys.platform.startswith("linux") else "spawn"
        try:
            threads = max(1, (os.cpu_count() or 1) // workers)  # compiled kernels (kiln-gen[fast]): the cores shared out
            with ProcessPoolExecutor(workers, mp_context=multiprocessing.get_context(method), initializer=set_threads, initargs=(threads,)) as pool:
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
        if model is not None and style is not None and not any(f.severity == "error" for f in keep):
            if model.style_version is not None and model.style_version < project.config.style_version:
                keep.append(Finding("W107", f"made under style_version {model.style_version}; the project is at {project.config.style_version}: "
                                    "check it still fits, then `kiln mark <model> --current`", path, None, "style_version"))  # fmt: skip
            palette, _ = project.palette(model.palette)
            keep += variant_warnings(model, palette)
            if model.vertex_fades and not project.config.vertex_colors:  # #262
                first = next((p for p in model.parts if p.color_blend > 0), None)
                keep.append(Finding("W134", "color_blend fades per vertex here (the model has no baked maps"
                                    + (": normal_map: 0" if model.normal_map_off else ": baking isn't installed, pip install \"kiln-gen[bake]\"")
                                    + "), but the project draws a material per colour (or an atlas), so the borders stay crisp in the glb: "
                                    "set vertex_colors = true in kiln.toml, or let the model bake its maps", path,
                                    first.line if first else None, f"{first.where}.color_blend" if first else "parts"))  # fmt: skip
            if project.config.atlas:  # one opaque material per model: glass can't be see-through there (#175)
                see = sorted({p.material for p in model.parts if p.geometry.op == "add" and style.materials.get(p.material, MaterialPreset()).alpha < 1})
                if see:
                    keep.append(Finding("W131", f"{', '.join(see)} {'is' if len(see) == 1 else 'are'} see-through (alpha < 1), but atlas = true draws "
                                        "every part with one opaque material: make the glass its own model, or drop atlas", path, None, "parts"))  # fmt: skip
        loaded.append((path, model, style, palette, keep))
    names = {p.name.split(".")[0] for p in project.model_paths()}
    for path, model, _, _, keep in loaded:  # an effect's emitters are other models in the project
        missing = sorted({e.model for e in model.effect.emitters} - names) if model is not None and model.effect is not None else []
        if missing:
            keep.append(Finding("E011", f"effect emits {', '.join(missing)}: no models/<name>.kiln.yaml for it", path, None, "effect"))
        placed = sorted({i.model for i in model.instances} - names) if model is not None else []
        if placed:  # (#171)
            keep.append(Finding("E011", f"instances place {', '.join(placed)}: no models/<name>.kiln.yaml for it", path, None, "instances"))
    # templates are bases, not models: checked as text only
    meshed = [k for k, (_, m, st, _, keep) in enumerate(loaded)
              if geometry and m and st and not m.template and m.terrain is None and m.scatter is None and not any(f.severity == "error" for f in keep)]  # fmt: skip
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
        if geometry and model is not None and model.terrain is not None and not any(f.severity == "error" for f in keep):
            keep += terrain_warnings(model, palette, cache)
        if model is not None and model.scatter is not None and not any(f.severity == "error" for f in keep):
            keep += scatter_findings(project, model, cache, geometry)
        if model is not None and style is not None and not any(f.severity == "error" for f in keep) and not model.template:
            result.models[model.name] = (model, style)
        disabled = set(project.config.lint_disable) | set(model.lint_disable if model else ())
        seen = set(result.findings)  # a broken palette's errors come with every model using it: once is enough
        result.findings += [f for f in keep if not (f.severity == "warning" and f.rule in disabled) and f not in seen]
    # kiln.lock (pack imports): checked whole, whichever models are linted; no lock, no findings
    sources = [(p, m.source.file, m.source.licence) for p, m, _, _, _ in loaded if m is not None and m.source is not None]
    result.findings += [f for f in lock_findings(project.root, sources) if not (f.severity == "warning" and f.rule in project.config.lint_disable)]
    return result


def lint_project(project: Project, geometry: bool = True) -> LintResult:
    return lint_paths(project, project.model_paths(), geometry)



FEW_TRIANGLES = 48  # a round part's visible surface with fewer reads as a polygon (a sphere: about 8 sides)
MOSTLY_SHOWN = 0.5  # ... when at least this much of its own surface shows (a pupil inside an eye needs few)


KIN_HUE = 15.0  # degrees: an unswapped colour this close in hue to a swapped one (both coloured) goes with it
KIN_CHROMA = 0.04  # OKLab chroma below which a colour is a grey (no hue to match)


def variant_warnings(model: Model, palette: dict[str, str], only: str | None = None) -> list[Finding]:
    """W130 (#205): colours the model paints that a variant leaves as they are, though they go with a colour it swaps:
    the same palette ramp (robe and robe_dark), or close in hue. A missed shade gives a seam in the old colour."""
    from kiln.vendor.color import hex_to_rgb, rgb_to_oklab

    used: list[str] = []
    for part in model.parts:
        if part.geometry.op != "add":
            continue
        for c in (part.color, *(pat.color for pat in part.patterns if pat.mix is None)):
            if c not in used:
                used.append(c)
    names: dict[str, str] = {}  # hex -> its colour name (a key only when it has none)
    for name, hx in palette.items():
        if hx not in names or len(names[hx]) == 1 < len(name):
            names[hx] = name
    ramps: dict[str, tuple[str, ...]] = getattr(palette, "ramps", {})

    def hue(hx: str) -> tuple[float, float]:
        lab = rgb_to_oklab(hex_to_rgb(hx))
        return math.hypot(lab[1], lab[2]), math.degrees(math.atan2(lab[2], lab[1]))

    def same_ramp(a: str, c: str) -> str | None:  # a ramp both are in, but not a shade shared by several ramps (outlines)
        shared = {hx for hx in (a, c) if sum(hx in r for r in ramps.values()) > 1}
        return None if shared else next((r for r, hexes in ramps.items() if a in hexes and c in hexes), None)

    def close_hue(a: str, c: str) -> bool:
        (ca, ha), (cc, hc) = hue(a), hue(c)
        return ca > KIN_CHROMA and cc > KIN_CHROMA and abs((ha - hc + 180) % 360 - 180) < KIN_HUE

    def kin(a: str, b: str) -> bool:
        return a == b or same_ramp(a, b) is not None or close_hue(a, b)

    out: list[Finding] = []
    for vname, swap in model.variants.items():
        if only is not None and vname != only:
            continue
        changed = [a for a, b in swap.items() if a in used and not kin(a, b)]  # (to a shade of its own: the hue stays)
        for c in used:
            if c in swap:
                continue
            why = ""
            for a in changed:
                ramp = same_ramp(a, c)
                if ramp:
                    why = f"it is in ramp {ramp} with {names.get(a, a)}, which it swaps"
                    break
                if close_hue(a, c):
                    why = f"it is close in hue to {names.get(a, a)}, which it swaps"
                    break
            if why:
                out.append(Finding("W130", f"variant {vname} leaves {names.get(c, c)} as it is, but {why}: swap it too, or swap "
                                   "whole palette ramps by name (`swap: { robes: golds }`); to keep it, map it to itself "
                                   f"(`{names.get(c, c)}: {names.get(c, c)}`)", model.path, None, f"variants.{vname}.swap"))  # fmt: skip
    return out


def _round_area(g: Geometry) -> float | None:
    """The surface area of a round shape as written (None: not round, or stretched)."""
    if g.scale is not None or g.shell:
        return None
    s = g.params
    if g.shape == "sphere":
        return 4 * math.pi * float(s["radius"]) ** 2
    if g.shape == "ellipsoid":
        a, b, c = (float(x) for x in s["radii"])
        q = 1.6075  # Knud Thomsen's approximation (within about 1%)
        return float(4 * math.pi * (((a * b) ** q + (a * c) ** q + (b * c) ** q) / 3) ** (1 / q))
    if g.shape == "capsule":  # a cone frustum's side and two half spheres (radius_to defaults to radius)
        r1, r2 = float(s["radius"]), float(s.get("radius_to", s["radius"]))
        h = float(np.linalg.norm(np.subtract(s["to"], s["from"])))
        return float(math.pi * (r1 + r2) * math.hypot(h, r1 - r2) + 2 * math.pi * (r1**2 + r2**2))
    if g.shape == "torus":
        return 4 * math.pi**2 * float(s["radius"]) * float(s["thickness"])
    return None


def _copies(g: Geometry, area: float) -> int:
    """How many separate copies a part makes: its array's, x 2 per mirror axis it doesn't straddle (a centred part
    mirrored is one shape)."""
    size = math.sqrt(area / (4 * math.pi))  # its radius, roughly
    apart = sum(1 for axis in g.mirror if abs(float(g.at[axis])) > size)
    return int(len(g.copies) * 2**apart)


def few_triangles(m: Model, built: Built, field: Field, exact: frozenset[int] | set[int]) -> list[tuple[int, int, int]]:
    """Round soft parts that show most of their surface on too few triangles (#167): (part, triangles per copy, copies)."""
    p = built.painted
    adding = [i for i, part in enumerate(m.parts) if part.geometry.op == "add" and not part.detail]
    round_parts = {i: a for i in adding if i not in exact and i not in built.hidden and i not in built.lost
                   and (a := _round_area(m.parts[i].geometry)) is not None}  # fmt: skip
    if not round_parts or not len(p.faces):
        return []
    corners = p.vertices[p.faces]
    area = np.linalg.norm(np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0]), axis=1) / 2
    # a coarse triangle's centre sits well inside the round surface it cuts across: allow half its longest edge
    longest = np.linalg.norm(corners - np.roll(corners, 1, axis=1), axis=2).max(axis=1)
    owner, dist = field.nearest(adding, corners.mean(axis=1))
    on = dist < np.maximum(built.step, longest / 2)
    count = np.bincount(owner[on], minlength=len(adding))
    shown = np.bincount(owner[on], weights=area[on], minlength=len(adding))
    out = []
    for j, i in enumerate(adding):
        if i not in round_parts:
            continue
        copies = _copies(m.parts[i].geometry, round_parts[i])
        per = int(count[j]) // copies
        if 0 < per < FEW_TRIANGLES and shown[j] / copies >= MOSTLY_SHOWN * round_parts[i]:
            out.append((i, per, copies))
    return out

__all__ = ["BUILT_RULES", "CLASS_SIZES", "LintResult", "WARNING_RULES", "geometry_warnings", "lint_paths", "lint_project"]
