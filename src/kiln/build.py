"""`kiln build`: lint, then build every model into the output dir: .glb (+ variants and LODs), Godot scenes and
look kits, manifest.json and CREDITS.md. Only changed files are rewritten; files from the previous build that
aren't produced any more are removed."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kiln import __version__
from kiln.builder import build_cached
from kiln.export import Built, gltf_name, to_glb
from kiln.godot import find_godot_project, look_scene, model_scene, res_path
from kiln.lint import LintResult, lint_project
from kiln.notation import Model
from kiln.project import Project
from kiln.style import Style
from pagan.findings import Finding

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
    for i, bone in enumerate(sk.bones):
        parts[bone.name] = {
            "parent": sk.bones[bone.parent].name if bone.parent >= 0 else "",
            "pivot": [_f(v) for v in bone.pivot],
            "meta": bone.meta,
            "separate": bone.separate,
        }
    animations = {}
    for t in built.tracks:
        animations[t.name] = {"gltf_name": gltf_name(t.name, t.loop), "fps": t.fps, "frames": t.frames, "loop": t.loop,
                              "interpolation": t.interpolation, "duration": _f(t.frames / t.fps)}  # fmt: skip
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
    return entry


def build(project: Project, only_valid: bool = True, progress: Callable[[str], None] | None = None) -> BuildResult:
    out = project.output_dir
    result = BuildResult(out)
    lint: LintResult = lint_project(project)
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
    credits: list[dict[str, str]] = []
    cache = project.root / ".kiln-cache"

    def write(path: Path, data: bytes) -> None:
        _write(path, data, result)
        produced.add(path.resolve())

    for name, (model, style) in sorted(lint.models.items()):
        if progress:
            progress(f"building {name}")
        palette, _ = project.palette(model.palette)
        built = build_cached(model, style, palette, cache)
        glb = out / "models" / f"{name}.glb"
        write(glb, to_glb(built, generator))
        entry = model_entry(built, out, glb)
        variants = {}
        for vname, swap in sorted(model.variants.items()):
            vpath = out / "models" / f"{name}.{vname}.glb"
            write(vpath, to_glb(built, generator, swap))
            variants[vname] = {"glb": vpath.relative_to(out).as_posix(), "swap": dict(sorted(swap.items()))}
        if variants:
            entry["variants"] = variants
        lods = []
        for k, budget in enumerate(model.lod, start=1):
            if budget >= built.triangles:
                continue
            lod_built = build_cached(model, style, palette, cache, budget)
            lpath = out / "models" / f"{name}.lod{k}.glb"
            write(lpath, to_glb(lod_built, generator))
            lods.append({"glb": lpath.relative_to(out).as_posix(), "triangles": lod_built.triangles})
        if lods:
            entry["lods"] = lods
        if godot_root is not None:
            scene = out / "models" / f"{name}.tscn"
            write(scene, model_scene(name, res_path(glb, godot_root), style).encode())
            entry["godot_scene"] = res_path(scene, godot_root)
            entry["glb_res"] = res_path(glb, godot_root)
        styles_used[style.name] = style
        if model.source is not None:
            credits.append({"model": name, "file": model.source.file.name, "licence": model.source.licence,
                            "author": model.source.author, "url": model.source.url})  # fmt: skip
        models[name] = entry
        result.models.append(name)
    looks = {}
    if godot_root is not None:
        for sname, style in sorted(styles_used.items()):
            path = out / "looks" / f"{sname}.tscn"
            write(path, look_scene(style).encode())
            looks[sname] = res_path(path, godot_root)
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
    manifest_path = out / MANIFEST
    previous: list[str] = []
    if manifest_path.is_file():
        try:
            previous = list(json.loads(manifest_path.read_text(encoding="utf-8")).get("files", []))
        except (OSError, ValueError, AttributeError):
            previous = []
    write(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode())
    result.manifest = manifest
    for rel in previous:
        path = (out / rel).resolve()
        if path not in produced and path.is_file() and path.is_relative_to(out) and path.suffix in (".glb", ".tscn", ".json", ".md"):
            path.unlink()
            result.removed.append(path)
            sidecar = path.with_name(path.name + ".import")
            if sidecar.is_file():
                sidecar.unlink()
    return result


__all__ = ["BuildResult", "build", "model_entry"]
