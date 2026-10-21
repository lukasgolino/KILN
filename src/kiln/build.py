"""`kiln build`: lint, then build every model into the output dir: .glb (+ variants and LODs), Godot scenes and
look kits, manifest.json and CREDITS.md. Only changed files are rewritten; files from the previous build that
aren't produced any more are removed."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from kiln import __version__
from kiln.atlas import CELL, Atlas, AtlasUse, layout
from kiln.builder import build_cached
from kiln.effect import to_json
from kiln.retarget import HUMANOID, OPTIONAL
from kiln.export import Built, attr_names, gltf_name, to_glb, uv_channel
from kiln.godot import find_godot_project, look_scene, model_scene, res_path
from kiln.lint import LintResult, lint_paths, lint_project
from kiln.notation import MODEL_SUFFIX, Model
from kiln.rig import animation_poses
from kiln.project import Project
from kiln.style import Style
from kiln.vendor.findings import Finding

MANIFEST = "manifest.json"
CREDITS = "CREDITS.md"


@dataclass
class BuildResult:
    output_dir: Path
    models: list[str] = field(default_factory=list)
    written: list[Path] = field(default_factory=list)
    unchanged: int = 0
    removed: list[Path] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    godot_root: Path | None = None
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]


def _write(path: Path, data: bytes, result: BuildResult) -> None:
    if path.is_file() and path.read_bytes() == data:
        result.unchanged += 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    result.written.append(path)


def _f(v: float) -> float:
    return round(float(v), 5)


def model_entry(built: Built, out: Path, glb: Path) -> dict[str, Any]:
    m: Model = built.model
    lo, hi = built.bounds()
    sk = built.skeleton
    parts = {}
    p = built.painted
    face_bone = np.array([sk.index(g.bone) for g in p.groups] or [0])[p.face_group]
    for i, bone in enumerate(sk.bones):
        chain, k = [bone.name], bone.parent
        while k >= 0:
            chain.insert(0, sk.bones[k].name)
            k = sk.bones[k].parent
        parts[bone.name] = {
            "parent": sk.bones[bone.parent].name if bone.parent >= 0 else "",
            "pivot": [_f(v) for v in bone.pivot],
            "meta": bone.meta,
            "separate": bone.separate,
            "node_path": "/".join(chain),  # glTF node names from the root (Godot soft skins: bones of the Skeleton3D)
        }
        if bone.sockets:
            parts[bone.name]["sockets"] = {
                name: {"position": [_f(v) for v in point], "offset": [_f(v) for v in point - bone.pivot], "node": f"{bone.name}_{name}"}
                for name, point in sorted(bone.sockets.items())
            }
        faces = p.faces[face_bone == i]
        if len(faces):  # the part's box in model space, rest pose (hit zones)
            v = p.vertices[np.unique(faces)]
            parts[bone.name]["aabb"] = {"min": [_f(x) for x in v.min(axis=0)], "max": [_f(x) for x in v.max(axis=0)]}
    animations = {}
    for t in built.tracks:
        animations[t.name] = {"gltf_name": gltf_name(t.name, t.loop), "fps": t.fps, "frames": t.frames, "loop": t.loop,
                              "interpolation": t.interpolation, "duration": _f(t.frames / t.fps)}  # fmt: skip
        poses = animation_poses(m.animations[t.name], m) if t.name in m.animations else []
        first = poses[0] if poses else {}
        start = {pid: {"rotate": [_f(v) for v in pose.rotate], "offset": [_f(v) for v in pose.offset]}
                 for pid, pose in sorted(first.items()) if max(map(abs, (*pose.rotate, *pose.offset))) > 1e-4}  # fmt: skip
        if start:  # where its first frame puts parts (e.g. an arm built level, cocked at the start)
            animations[t.name]["start"] = start
        source = m.animations[t.name].source if t.name in m.animations else None
        if source is not None:  # retargeted from a clip library
            animations[t.name]["clip"] = {"file": source[0].name, "clip": source[1]}
    entry: dict[str, Any] = {
        "glb": glb.relative_to(out).as_posix(),
        "description": m.description,
        "tags": list(m.tags),
        "status": m.status,
        "style_version": m.style_version,
        "class": m.cls,
        "style": built.style.name,
        "triangles": built.triangles,
        "bounds": {"min": [_f(v) for v in lo], "max": [_f(v) for v in hi]},
        "size": [_f(v) for v in hi - lo],
        "skin": built.skin,
        "parts": parts,
        "animations": animations,
        "colors": sorted({g.color for g in built.painted.groups}),
    }
    if m.source is not None:
        entry["source"] = {"file": m.source.file.name, "licence": m.source.licence, "author": m.source.author, "url": m.source.url}
    if m.origin is not None:  # the glb's origin in model space (everything else here is model space): glb = model - origin
        entry["origin"] = [_f(v) for v in built.origin()]
    if m.fit_to is not None:  # an attachment: hang it on this bone of that character (the glb is in the bone's space)
        entry["attach"] = {"file": m.fit_to[0].name, "bone": m.fit_to[1]}
    if m.skeleton == "humanoid":  # the standard names of its joints, for engines' retargeting (Godot: SkeletonProfileHumanoid)
        entry["humanoid"] = {kid: {"kaykit": kk, "mixamo": mx, "godot": gd} for kid, _, kk, mx, gd in HUMANOID + OPTIONAL if kid in parts}
    return entry


def atlas_entry(atlas: Atlas, files: dict[str, str], ao: bool) -> dict[str, Any]:
    """Manifest `atlas`: the textures (paths in the output dir) and where every colour sits in them."""
    w, h = atlas.size
    cells = [{"color": c, "material": m, "uv": [_f(v) for v in atlas.uv(i)], "pixel": list(atlas.pixel(i))} for i, (c, m) in enumerate(atlas.cells)]
    return {**files, "size": [w, h], "cell": CELL, "cells": cells, "ao": ao}


def build(project: Project, only_valid: bool = True, progress: Callable[[str], None] | None = None, paths: list[Path] | None = None) -> BuildResult:
    """Build every model (or only the models at `paths`: the rest keep what the last build wrote) into the output dir."""
    out = project.output_dir
    result = BuildResult(out)
    lint: LintResult = lint_project(project) if paths is None else lint_paths(project, paths)
    result.findings = list(lint.findings)
    if lint.errors and only_valid:
        return result
    godot_root = None
    if "godot" in project.config.export:
        godot_root = find_godot_project(out)
        if godot_root is None:
            result.findings.append(Finding("E000", f'export includes "godot" but {out} isn\'t inside a Godot project (no project.godot above it); '
                                           "point output_dir into your Godot project, e.g. ../game/assets/kiln", project.config_path))  # fmt: skip
            return result
        result.godot_root = godot_root
    produced: set[Path] = set()
    generator = f"kiln {__version__}"
    models: dict[str, Any] = {}
    styles_used: dict[str, Style] = {}
    cache = project.root / ".kiln-cache"
    manifest_path = out / MANIFEST
    old: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            old = dict(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            old = {}
    previous = [str(f) for f in old.get("files", [])] if isinstance(old.get("files"), list) else []
    if paths is not None:  # a partial build: the other models' entries and files stay as they are
        rebuilt = {p.name[: -len(MODEL_SUFFIX)] for p in paths}
        existing = {p.name[: -len(MODEL_SUFFIX)] for p in project.model_paths()}
        kept = {k: v for k, v in dict(old.get("models") or {}).items() if k not in rebuilt and k in existing}
        models.update(kept)
        for rel in previous:
            top = rel.split("/")[0]
            stem = rel.split("/")[-1].split(".")[0]
            if top == "models" and stem in kept:
                produced.add((out / rel).resolve())

    def write(path: Path, data: bytes) -> None:
        _write(path, data, result)
        produced.add(path.resolve())

    for name, (model, style) in sorted(lint.models.items()):
        if progress:
            progress(f"building {name}")
        palette, _ = project.palette(model.palette)
        built = build_cached(model, style, palette, cache)
        glb = out / "models" / f"{name}.glb"
        lod_builts = [(k, budget, build_cached(model, style, palette, cache, budget)) for k, budget in enumerate(model.lod, start=1) if budget < built.triangles]
        atlas: AtlasUse | None = None
        atlas_files: dict[str, dict[str, str]] = {}  # "" (base) or variant -> texture kind -> path in models/
        if project.config.atlas:  # one layout for the model and its LODs; a texture set per variant
            cells = layout([built, *(b for _, _, b in lod_builts)])
            glow = cells.glow_strength(built)
            for vname, swap in [("", {}), *sorted(model.variants.items())]:
                stem = f"{name}.{vname}" if vname else name
                atlas_files[vname] = {"palette": f"{stem}.palette.png"}
                write(out / "models" / f"{stem}.palette.png", cells.palette_png(swap))
                if glow > 0:
                    atlas_files[vname]["glow"] = f"{stem}.glow.png"
                    write(out / "models" / f"{stem}.glow.png", cells.glow_png(built, swap))
            atlas_files[""]["material"] = f"{name}.material.png"
            write(out / "models" / f"{name}.material.png", cells.material_png(built))
            if godot_root is not None and cells.has_rim(built):  # Godot's rim light per cell (glTF has no rim)
                atlas_files[""]["rim"] = f"{name}.rim.png"
                write(out / "models" / f"{name}.rim.png", cells.rim_png(built))
            atlas = AtlasUse(cells, atlas_files[""]["palette"], atlas_files[""]["material"], atlas_files[""].get("glow"),
                             project.config.atlas_ao, glow)  # fmt: skip
        write(glb, to_glb(built, generator, None, project.config.vertex_colors, atlas))
        entry = model_entry(built, out, glb)
        uv_parts = sorted({built.model.parts[g.part].id for g in built.painted.groups if g.part >= 0 and built.model.parts[g.part].uv is not None})
        if uv_parts:  # projected texture coordinates (parts' uv:)
            entry["uv"] = {"set": f"TEXCOORD_{uv_channel(built, atlas)}", "parts": uv_parts}
        names = attr_names(built)
        if names:  # per-vertex numbers (parts' attr:): custom glTF attributes, the first also in COLOR_0's alpha
            entry["attributes"] = {name: {"gltf": f"_{name.upper()}", "color_alpha": k == 0} for k, name in enumerate(names)}
        if atlas is not None:
            entry["atlas"] = atlas_entry(atlas.atlas, {k: f"models/{v}" for k, v in sorted(atlas_files[""].items())}, atlas.ao)
        variants: dict[str, dict[str, Any]] = {}
        for vname, swap in sorted(model.variants.items()):
            variants[vname] = {"swap": dict(sorted(swap.items()))}
            vatlas = None
            if atlas is not None:  # a texture swap: same mesh, same cells, other colours
                vatlas = AtlasUse(atlas.atlas, atlas_files[vname]["palette"], atlas.material, atlas_files[vname].get("glow"), atlas.ao, atlas.glow_strength)
                variants[vname].update({k: f"models/{v}" for k, v in sorted(atlas_files[vname].items())})
            if project.config.variant_glbs:
                vpath = out / "models" / f"{name}.{vname}.glb"
                write(vpath, to_glb(built, generator, swap, project.config.vertex_colors, vatlas))
                variants[vname]["glb"] = vpath.relative_to(out).as_posix()
        if variants:
            entry["variants"] = variants
        lods = []
        disabled = set(project.config.lint_disable) | set(model.lint_disable)
        for k, budget, lod_built in lod_builts:
            if lod_built.triangles > budget * 1.25 and "W112" not in disabled:
                result.findings.append(Finding("W112", f"lod {k} came out at {lod_built.triangles} triangles for a target of {budget}: colour "
                                               "borders and small parts need more; raise the target or drop this LOD", model.path, None, "lod"))  # fmt: skip
            for i in lod_built.lost if "W111" not in disabled else ():
                part = model.parts[i]
                result.findings.append(Finding("W111", f"lod {k} ({budget} triangles) loses part {part.index} ({part.geometry.shape}, "
                                               f"{part.color_name})", model.path, part.line, part.where))  # fmt: skip
            lpath = out / "models" / f"{name}.lod{k}.glb"
            write(lpath, to_glb(lod_built, generator, None, project.config.vertex_colors, atlas, built.origin()))
            lods.append({"glb": lpath.relative_to(out).as_posix(), "triangles": lod_built.triangles})
        if lods:
            entry["lods"] = lods
        if godot_root is not None:
            scene = out / "models" / f"{name}.tscn"
            models_dir = out / "models"
            rim = {"rim_texture": res_path(models_dir / atlas_files[""]["rim"], godot_root)} if "rim" in atlas_files.get("", {}) else {}
            write(scene, model_scene(name, res_path(glb, godot_root), style, None, rim if atlas else None).encode())
            entry["godot_scene"] = res_path(scene, godot_root)
            recolourable = project.config.variant_glbs or not project.config.vertex_colors  # vertex colours: swap table only
            for vname, swap in sorted(model.variants.items()) if recolourable else ():  # a scene per variant: its glb, or the base recoloured
                vscene = out / "models" / f"{name}.{vname}.tscn"
                if atlas is not None:  # the base glb with the variant's textures
                    textures = {**rim, **{k: res_path(models_dir / v, godot_root) for k, v in atlas_files[vname].items()}}
                    write(vscene, model_scene(name, res_path(glb, godot_root), style, swap, textures).encode())
                else:
                    vglb = out / variants[vname]["glb"] if "glb" in variants[vname] else glb
                    write(vscene, model_scene(name, res_path(vglb, godot_root), style, None if "glb" in variants[vname] else swap).encode())
                variants[vname]["godot_scene"] = res_path(vscene, godot_root)
            entry["glb_res"] = res_path(glb, godot_root)
        styles_used[style.name] = style
        models[name] = entry
        result.models.append(name)
    for name, (model, _) in sorted(lint.models.items()):  # effects: after every model, so emitters can name any of them
        if model.effect is None or name not in models:
            continue
        missing = sorted({e.model for e in model.effect.emitters} - set(models))
        if missing:
            result.findings.append(Finding("E011", f"effect emits {', '.join(missing)}: no such model in this project (or it didn't build)",
                                           model.path, None, "effect"))  # fmt: skip
            continue
        emitted = {e.model: {k: models[e.model][k] for k in ("glb", "godot_scene", "origin") if k in models[e.model]} for e in model.effect.emitters}
        path = out / "models" / f"{name}.effect.json"
        write(path, (json.dumps(to_json(model.effect, emitted), indent=1) + "\n").encode())
        models[name]["effect"] = path.relative_to(out).as_posix()
    looks: dict[str, str] = {}
    if godot_root is not None and paths is not None:  # the kept models' looks
        kept_styles = {str(e.get("style")) for k, e in models.items() if k not in result.models}
        for sname, res in dict(old.get("looks") or {}).items():
            if sname in kept_styles and sname not in styles_used:
                looks[sname] = res
                produced.add((out / "looks" / f"{sname}.tscn").resolve())
    if godot_root is not None:
        for sname, style in sorted(styles_used.items()):
            path = out / "looks" / f"{sname}.tscn"
            write(path, look_scene(style).encode())
            looks[sname] = res_path(path, godot_root)
    credits = [{"model": k, **e["source"]} for k, e in sorted(models.items()) if isinstance(e.get("source"), dict)]
    if credits:
        lines = ["# Credits", "", "Models made from other people's work (written by `kiln build` from each model's `source:`).", ""]
        for c in sorted(credits, key=lambda c: c["model"]):
            who = f" by {c['author']}" if c["author"] else ""
            url = f" ({c['url']})" if c["url"] else ""
            lines.append(f"- **{c['model']}**: {c['file']}{who}{url}, licence {c['licence']}")
        write(out / CREDITS, ("\n".join(lines) + "\n").encode())
    manifest: dict[str, Any] = {"generator": generator, "units": "metres", "up": "+Y", "front": "+Z", "models": models}
    if looks:
        manifest["looks"] = looks
    files = sorted(p.relative_to(out).as_posix() for p in produced)
    manifest["files"] = [*files, MANIFEST]
    write(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode())
    result.manifest = manifest
    for rel in previous:
        path = (out / rel).resolve()
        if path not in produced and path.is_file() and path.is_relative_to(out) and path.suffix in (".glb", ".tscn", ".json", ".md", ".png"):
            path.unlink()
            result.removed.append(path)
            sidecar = path.with_name(path.name + ".import")
            if sidecar.is_file():
                sidecar.unlink()
    return result


__all__ = ["BuildResult", "build", "model_entry"]
