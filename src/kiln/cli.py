"""`kiln` command line: init, new, lint, build, preview, lineup, gallery, status, mark, style, config, import, pack,
credits, doctor, skill, mcp. Human-readable output by default, `--json` for machines, non-zero exit on errors."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sys
import time
from collections.abc import Sequence
from datetime import date
from importlib.resources import files
from pathlib import Path
from string import Template
from typing import Any

from kiln import __version__
from kiln.godot import find_godot_project
from kiln.importer import external_files, missing_files
from kiln.notation import MODEL_SUFFIX, NAME_RE
from kiln.project import CONFIG_NAME, Project, find_project_root, load_project, parse_config
from kiln.style import STYLE_SUFFIX, builtin_names, load_style, style_summary
from kiln.usage import PROGRESS_ENV, cost_line, peak_gb
from kiln.vendor.findings import Finding, PaganError, display_path

SETTINGS = {
    "default_style": "the style every model uses unless it names its own (kiln style list)",
    "default_palette": "palettes/<name>.pal.yaml (PAGAN format) whose colour names models use",
    "output_dir": "where kiln build writes (inside a Godot project for export godot)",
    "preview_dir": "where previews go",
    "preview_size": "kiln preview's tile size in pixels (64-1024; unset: 220 for the turntable, 400 for --views)",
    "export": 'what kiln build writes: ["glb"] or ["glb", "godot"]',
    "style_version": "the look's version; models made under an older one are flagged (W107)",
    "variant_glbs": "true: a .glb per variant; false: variants are swap tables (Godot: <name>.<variant>.tscn recolours the base)",
    "vertex_colors": "true: colours in the vertices, one surface per material preset (fewer draw calls); needs variant_glbs",
    "atlas": "true: one material per model (palette textures; variants swap the texture): 1 surface, 2 with decals",
    "atlas_ao": "true or a strength 0..1 (with atlas): bake ambient occlusion into the vertex colours",
}


class Output:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def say(self, text: str) -> None:
        if not self.as_json:
            print(text)

    def result(self, data: dict[str, Any]) -> None:
        if self.as_json:
            print(json.dumps({"ok": True, **data}, separators=(",", ":")))

    def failure(self, findings: list[Finding], data: dict[str, Any] | None = None) -> None:
        if self.as_json:
            print(json.dumps({"ok": False, **(data or {}), "findings": [f.to_dict() for f in findings]}, separators=(",", ":")))
        else:
            for f in findings:
                print(f.format())


def _usage(message: str, path: Path | None = None) -> PaganError:
    return PaganError([Finding("E000", message, path)])


def _template(name: str) -> str:
    return files("kiln").joinpath("templates", name).read_text(encoding="utf-8")


def _require_project() -> Project:
    root = find_project_root(Path.cwd())
    if root is None:
        raise _usage(f"no {CONFIG_NAME} here or in any parent folder; run `kiln init` first")
    return load_project(root)


def _model_path(project: Project, name: str) -> Path:
    path = Path(name)
    if path.suffix == ".yaml" and path.is_file():
        return path.resolve()
    candidate = project.models_dir / f"{name}{MODEL_SUFFIX}"
    if not candidate.is_file():
        known = ", ".join(p.name[: -len(MODEL_SUFFIX)] for p in project.model_paths()) or "none"
        raise _usage(f"no model {name!r} (models: {known})")
    return candidate


# --- init / new ----------------------------------------------------------------------------------------------


def _init_output(root: Path, godot: Path | None) -> tuple[str, tuple[str, ...], bool]:
    """`kiln init`'s output_dir and export (#163): inside a Godot project, its assets/kiln with Godot scenes, unless that
    is the KILN folder or under it (the folder gets a .gdignore, #97). Returns (output_dir, export, inside Godot)."""
    if godot is None:
        return "build", ("glb",), False
    target = godot / "assets" / "kiln"
    if target == root or target.is_relative_to(root):
        return "build", ("glb",), False
    try:
        rel = Path(os.path.relpath(target, root)).as_posix()
    except ValueError:  # Windows: another drive or a UNC path
        rel = target.as_posix()
    return rel, ("glb", "godot"), True


def cmd_init(args: argparse.Namespace, out: Output) -> int:
    root = Path(args.dir).resolve()
    if (root / CONFIG_NAME).exists():
        raise _usage(f"{root / CONFIG_NAME} already exists", root / CONFIG_NAME)
    if args.style not in builtin_names():
        raise _usage(f"unknown style {args.style!r}; built-in: {', '.join(builtin_names())}")
    for folder in ("models", "palettes", "styles", "decals", "imports"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    godot = find_godot_project(root.parent)
    output_dir, export, inside = _init_output(root, godot)
    toml_out = '"' + output_dir.replace("\\", "\\\\").replace('"', '\\"') + '"'
    toml_export = "[" + ", ".join(f'"{e}"' for e in export) + "]"
    values = {"style": args.style, "output_dir": toml_out, "export": toml_export,
              "output_pad": " " * max(1, 31 - len(f"output_dir = {toml_out}")), "export_pad": " " * max(1, 31 - len(f"export = {toml_export}")),
              "output_note": "the Godot project's assets/kiln: Godot imports it" if inside else 'put this inside your Godot project, e.g. "../game/assets/kiln"',
              "export_note": "glb + Godot scenes and look kits" if "godot" in export else 'add "godot" for .tscn scenes + look kits (output_dir must be in a Godot project)'}
    (root / CONFIG_NAME).write_text(Template(_template("kiln.toml")).safe_substitute(values), encoding="utf-8")
    (root / "palettes" / "main.pal.yaml").write_text(_template("main.pal.yaml"), encoding="utf-8")
    for doc in ("BRIEF.md", "STYLE.md"):
        if not (root / doc).exists():
            (root / doc).write_text(Template(_template(doc)).safe_substitute(values), encoding="utf-8")
    if not (root / ".gitignore").exists():
        (root / ".gitignore").write_text(_template("gitignore"), encoding="utf-8")
    (root / "styles" / args.style / "inspiration").mkdir(parents=True, exist_ok=True)
    if godot is not None and not (root / ".gdignore").exists():
        (root / ".gdignore").write_text("", encoding="utf-8")  # sources, imports and previews aren't game assets
    out.say(f"created KILN project in {display_path(root)} (style {args.style}); next: kiln new model <name>")
    if godot is not None and inside:
        out.say(f"inside the Godot project {display_path(godot)}: wrote {display_path(root / '.gdignore')}, so Godot skips this folder; "
                f"builds go to \"{output_dir}\" with Godot scenes (output_dir, export in kiln.toml)")
    elif godot is not None:  # the KILN folder holds assets/kiln itself: anything under it is hidden from Godot
        out.say(f"inside the Godot project {display_path(godot)}: wrote {display_path(root / '.gdignore')}, so Godot skips this folder, "
                f"build output included; set output_dir in kiln.toml to a folder Godot sees outside it")
    out.result({"project": display_path(root), "style": args.style, "godot_project": display_path(godot) if godot else None,
                "output_dir": output_dir, "export": list(export)})
    return 0


def cmd_library(args: argparse.Namespace, out: Output) -> int:
    """KILN's template library: bodies, heads, helmets and armour to combine with `extends: [...]`."""
    from kiln.notation import MODEL_SUFFIX as SUFFIX
    from kiln.notation import library_dir
    from kiln.vendor.yamlio import parse_yaml

    items = []
    for path in sorted(library_dir().glob(f"*{SUFFIX}")):
        data = parse_yaml(path.read_text(encoding="utf-8"))
        name = path.name[: -len(SUFFIX)]
        items.append({"name": name, "kind": name.split("_")[0], "description": str(data.get("description", ""))})
        out.say(f"{name:22s} {data.get('description', '')}")
    out.say("combine: `kiln new model <name> --extends body_stocky,head_bearded,helmet_nasal,armour_cape`")
    out.result({"templates": items})
    return 0


def cmd_new(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    name = args.name
    if not NAME_RE.match(name):
        raise _usage("model names are lowercase letters, digits, _ or -")
    path = project.models_dir / f"{name}{MODEL_SUFFIX}"
    if path.exists() and not args.force:
        raise _usage(f"{display_path(path)} already exists (use --force to overwrite)", path)
    if args.extends:  # a character from KILN's library (or the project's templates): body, head, helmet, armour
        from kiln.notation import base_path

        bases = [b.strip() for b in args.extends.split(",") if b.strip()]
        missing = [b for b in bases if not base_path(project.models_dir, b).is_file()]
        if missing:
            raise _usage(f"no template {', '.join(missing)} (see `kiln library`)")
        text = (f"name: {name}\ndescription: {json.dumps(args.description or '')}\nclass: character\nstatus: draft\n"
                f"extends: [{', '.join(bases)}]\n# parts: add your own; remove: [ids] drops a base's parts; variants recolour\n")  # fmt: skip
    else:
        text = Template(_template(f"model_{args.template}.kiln.yaml")).safe_substitute(name=name, description=json.dumps(args.description or ""))
    if args.cls:
        text = re.sub(r"^class: .*$", f"class: {args.cls}", text, count=1, flags=re.M)
    text = text.replace("status: draft\n", f"status: draft\nstyle_version: {project.config.style_version}\n", 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    out.say(f"wrote {display_path(path)} ({args.template}); edit it, then `kiln preview {name}`")
    out.result({"model": display_path(path)})
    return 0


# --- lint / build ----------------------------------------------------------------------------------------------


def _progress_on(out: Output) -> float:
    """Long model builds print their phases (human output only; lint's workers inherit the setting). The start time."""
    if not out.as_json:
        os.environ[PROGRESS_ENV] = "1"
    return time.monotonic()


def cmd_lint(args: argparse.Namespace, out: Output) -> int:
    from kiln.lint import lint_paths

    project = load_project(start=Path(args.paths[0]) if args.paths else None)
    paths = [_model_path(project, p) for p in args.paths] if args.paths else project.model_paths()
    start = _progress_on(out)
    result = lint_paths(project, paths, geometry=not args.fast)
    for f in result.findings:
        out.say(f.format())
    seconds = time.monotonic() - start
    meshed = {n: b for n, b in result.built.items() if b.step_reason}
    if meshed and len(meshed) <= MESH_LINES:  # what each model was meshed at, and why (#223)
        for n, b in meshed.items():
            out.say(f"{n}: {b.triangles} triangles, {b.step * 1000:.3g} mm mesh cells ({b.step_reason})")
    skipped = "; text checks only (--fast): nothing was meshed, so no geometric findings (W101-W103, W111, E013 ...): kiln lint or kiln build runs them" if args.fast else ""
    out.say(f"{len(paths)} models: {len(result.errors)} errors, {len(result.warnings)} warnings ({cost_line(seconds)}){skipped}")
    data = {"models": len(paths), "errors": len(result.errors), "warnings": len(result.warnings), "geometry": not args.fast,
            "findings": [f.to_dict() for f in result.findings], "seconds": round(seconds, 1), "peak_memory_gb": peak_gb(),
            "cells": {n: {"step": b.step, "asked": b.asked_step, "capped": b.step > b.asked_step * (1 + 1e-9), "why": b.step_reason}
                      for n, b in meshed.items()}}  # fmt: skip
    if result.errors:
        if out.as_json:  # human output: the findings are printed above already
            out.failure(result.findings, data)
        return 1
    out.result(data)
    return 0


MESH_LINES = 8  # kiln build names each model's triangles and mesh cell size up to this many models


def cmd_build(args: argparse.Namespace, out: Output) -> int:
    from kiln.build import build
    from kiln.godot import find_godot_binary, res_path, verify

    project = _require_project()
    progress = (lambda s: print(f"kiln: {s}", file=sys.stderr)) if not out.as_json else None
    paths = [_model_path(project, m) for m in args.models] if args.models else None
    start = _progress_on(out)
    result = build(project, progress=progress, paths=paths)
    seconds = time.monotonic() - start
    for f in result.findings:
        out.say(f.format())
    data: dict[str, Any] = {"output_dir": display_path(result.output_dir), "models": result.models,
                            "written": [display_path(p) for p in result.written], "unchanged": result.unchanged,
                            "removed": [display_path(p) for p in result.removed], "findings": [f.to_dict() for f in result.findings]}  # fmt: skip
    if result.errors:
        out.say("build failed: fix the errors above")
        if out.as_json:  # human output: the findings are printed above already
            out.failure(result.findings, data)
        return 1
    out.say(f"built {len(result.models)} models into {display_path(result.output_dir)}: {len(result.written)} written, "
            f"{result.unchanged} unchanged, {len(result.removed)} removed ({cost_line(seconds)})")  # fmt: skip
    data.update(seconds=round(seconds, 1), peak_memory_gb=peak_gb())
    entries = result.manifest.get("models", {})
    meshed = {n: entries[n] for n in result.models if "step" in entries.get(n, {})}
    if meshed and len(meshed) <= MESH_LINES:
        for n, e in meshed.items():
            why = f" ({result.cells[n]})" if n in result.cells else ""
            out.say(f"{n}: {e['triangles']} triangles, {e['step'] * 1000:.3g} mm mesh cells{why}")
    if args.verify_godot:
        godot = find_godot_binary()
        if godot is None or result.godot_root is None:
            finding = Finding("E000", "--verify-godot needs a Godot binary (GODOT=/path) and export \"godot\"")
            out.failure([finding], data)
            return 1
        check = verify(godot, result.godot_root, res_path(result.output_dir / "manifest.json", result.godot_root), result.attachments)
        data["godot"] = {"ok": check.ok, "models": check.models}
        if not check.ok:
            out.say(check.output)
            out.failure([Finding("E000", "Godot verification failed (see output)")], {**data, "godot_output": check.output})
            return 1
        out.say(f"Godot: all {check.models} models load, with their parts, animations and materials")
    out.result(data)
    return 0


# --- previews ----------------------------------------------------------------------------------------------------


def _with_occlusion(project: Project, built: Any) -> Any:
    """Previews show the occlusion the build bakes in (kiln.toml atlas_ao), as the engine does."""
    if project.config.atlas_ao > 0 and built.ao is None:
        from kiln.atlas import ambient_occlusion

        built.ao = ambient_occlusion(built, project.config.atlas_ao)
    return built


def _built(project: Project, name: str) -> Any:
    from kiln.builder import build_cached

    path = _model_path(project, name)
    model, style, findings = project.load(path)
    errors = [f for f in findings if f.severity == "error"]
    if model is None or style is None or errors:
        raise PaganError(errors or findings)
    if model.terrain is not None:
        raise _usage(f"{model.name} is a terrain: `kiln preview {model.name}` shows it (it has no parts, poses or line-up mesh)")
    if model.scatter is not None:
        raise _usage(f"{model.name} is a scatter: `kiln preview {model.name}` shows it (it has no parts, poses or line-up mesh)")
    palette, _ = project.palette(model.palette)
    try:
        return _with_occlusion(project, build_cached(model, style, palette, project.root / ".kiln-cache"))
    except ValueError as exc:
        from kiln.builder import build_error

        raise PaganError([Finding("E009", build_error(exc), path)]) from None


def _terrain_preview(project: Project, args: argparse.Namespace, out: Output) -> int | None:
    """`kiln preview <terrain>`: the terrain sheet (from above and from four sides); None when it isn't a terrain."""
    from kiln import preview as pv
    from kiln.terrain import heightfield_cached

    path = _model_path(project, args.model)
    model, style, findings = project.load(path)
    if model is None or model.terrain is None:
        return None
    errors = [f for f in findings if f.severity == "error"]
    if style is None or errors:
        raise PaganError(errors or findings)
    others = [flag for flag in ("closeup", "pose", "vs", "engine", "detach", "fit", "effect", "variant", "at", "views", "pitch", "size")
              if getattr(args, flag, None) is not None and getattr(args, flag) is not False]  # fmt: skip
    if others:
        raise _usage(f"{model.name} is a terrain: its preview is one sheet (from above and four sides); --{others[0]} doesn't apply")
    palette, _ = project.palette(model.palette)
    field_ = heightfield_cached(model.name, model.terrain, model.text, palette, project.root / ".kiln-cache")
    folder = project.preview_dir / model.name
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "terrain.png"
    pv.terrain_sheet(model, style, field_).save(target)
    out.say(f"{model.name} terrain: {display_path(target)}")
    out.result({"model": model.name, "outputs": {"terrain": display_path(target)}, "terrain": True})
    return 0


def _scatter_preview(project: Project, args: argparse.Namespace, out: Output) -> int | None:
    """`kiln preview <scatter>`: its instances over the surface (from above, two sides, close up); None when it isn't
    a scatter."""
    from kiln import preview as pv
    from kiln import scatter as sc

    path = _model_path(project, args.model)
    model, style, findings = project.load(path)
    if model is None or model.scatter is None:
        return None
    errors = [f for f in findings if f.severity == "error"]
    if style is None or errors:
        raise PaganError(errors or findings)
    others = [flag for flag in ("closeup", "pose", "vs", "engine", "detach", "fit", "effect", "variant", "at", "views", "pitch", "size")
              if getattr(args, flag, None) is not None and getattr(args, flag) is not False]  # fmt: skip
    if others:
        raise _usage(f"{model.name} is a scatter: its preview is one sheet (from above, two sides, close up); --{others[0]} doesn't apply")
    cache = project.root / ".kiln-cache"
    surface, problems = sc.surface_of(project, model.scatter, cache)
    problems += sc.problems(project, model.scatter, surface)
    if surface is None or problems:
        raise PaganError([Finding("E015", message, path, line, where) for message, where, line in problems])
    placed = sc.place(model.scatter, surface)
    sources = {}
    for source in model.scatter.sources:
        name, _, variant = source.partition(".")
        built = _built(project, name)
        sources[source] = (built, built.model.variants.get(variant, {}) if variant else {})
    ground = None  # (vertices, faces, corner normals, corner colours); flat: a plain quad
    if surface.kind == "terrain":
        land, colors = pv.terrain_built(model, style, surface.field)
        ground = (land.painted.vertices, land.painted.faces, land.normals, colors)
    elif surface.kind == "model":
        target = _built(project, model.scatter.onto)
        ground = (target.painted.vertices - target.origin(), target.painted.faces, target.normals, pv.corner_colors(target))
    folder = project.preview_dir / model.name
    folder.mkdir(parents=True, exist_ok=True)
    target_png = folder / "scatter.png"
    pv.scatter_sheet(model, style, placed, ground, sources).save(target_png)
    out.say(f"{model.name} scatter: {display_path(target_png)} ({placed.total} instances)")
    out.result({"model": model.name, "outputs": {"scatter": display_path(target_png)}, "scatter": True, "instances": placed.total})
    return 0


def _times(text: str) -> list[float]:
    """`--at 0,0.1,0.25`: effect times in seconds."""
    try:
        times = [float(t) for t in text.split(",")]
    except ValueError:
        times = []
    if not times or not all(math.isfinite(t) and t >= 0 for t in times):
        raise _usage(f"--at takes times in seconds (>= 0) separated by commas, e.g. 0,0.1,0.25,0.5,1 (got {text!r})")
    return times


def cmd_preview(args: argparse.Namespace, out: Output) -> int:
    from kiln import preview as pv

    project = load_project(start=Path(args.model) if Path(args.model).suffix == ".yaml" else None)
    terrain = _terrain_preview(project, args, out)
    if terrain is not None:
        return terrain
    scattered = _scatter_preview(project, args, out)
    if scattered is not None:
        return scattered
    built = _built(project, args.model)
    name = built.model.name
    folder = project.preview_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Any] = {}
    swap = built.model.variants.get(args.variant) if args.variant else None
    if args.variant and swap is None:
        raise _usage(f"{name} has no variant {args.variant!r} (variants: {', '.join(built.model.variants) or 'none'})")
    size = args.size if args.size is not None else project.config.preview_size
    if size is not None and not 64 <= size <= 1024:
        raise _usage("--size is the tile size in pixels, 64-1024")
    tile = {"size": size} if size is not None else {}
    want_views = args.views is not None or args.pitch is not None
    wanted_any = args.closeup or args.pose or args.vs is not None or args.engine or args.detach or args.fit or args.effect or want_views
    if args.ref_height is not None and not args.vs:
        raise _usage("--ref-height goes with --vs <ref.glb>")
    if args.at is not None and not args.effect:
        raise _usage("--at goes with --effect")
    if args.turntable or not wanted_any:
        path = folder / (f"turntable.{args.variant}.png" if args.variant else "turntable.png")
        pv.turntable(built, swap=swap, **tile).save(path)
        outputs["turntable"] = display_path(path)
    yaws: list[tuple[str, float]] = []
    pitches: list[float] = []
    if want_views:
        try:
            yaws = [pv.heading(v) for v in args.views.split(",")] if args.views else list(pv.HEADINGS)
            pitches = [float(p) for p in args.pitch.split(",")] if args.pitch else [15.0]  # nan fails the range test below
        except ValueError as exc:
            raise _usage(str(exc) if "view" in str(exc) else "--pitch is degrees above the horizon, e.g. 5 or 5,30") from None
        if not all(-89 <= p <= 89 for p in pitches):
            raise _usage("--pitch is between -89 and 89 degrees")
    if want_views and not args.engine and not args.pose:  # with --engine or --pose, the views flags pick theirs
        path = folder / (f"views.{args.variant}.png" if args.variant else "views.png")
        pv.views(built, yaws, pitches, size or 400, swap=swap).save(path)
        outputs["views"] = display_path(path)
    for part in args.closeup or []:
        try:
            path = folder / f"closeup_{part}.png"
            pv.closeup(built, part, **tile).save(path)
            outputs.setdefault("closeup", {})[part] = display_path(path)
        except KeyError:
            raise _usage(f"{name} has no part {part!r} (ids: {', '.join(built.model.ids)}, or a part's number in the file: 0-{len(built.model.parts) - 1})") from None
    pose_views = None
    if want_views:  # --pitch alone: the default views at those pitches; the pitch is in the row label
        named = yaws if args.views else [(n, yaw) for n, yaw, _ in pv.POSE_VIEWS]
        pose_views = [(f"{n} {p:+g}" if len(pitches) > 1 or args.pitch else n, yaw, p) for p in pitches for n, yaw in named]
    try:
        pose_frames = [int(f) for f in args.frame.split(",")] if args.frame else None
    except ValueError:
        raise _usage("--frame is frame numbers, e.g. 3 or 0,4,8") from None
    if pose_frames is not None and not args.pose:
        raise _usage("--frame goes with --pose")
    tracks = {t.name: t for t in built.tracks}
    for anim in args.pose or []:  # check every clip first: no sheet is written when one asks for a frame it lacks
        if anim in tracks and pose_frames is not None and any(not 0 <= f < tracks[anim].frames for f in pose_frames):
            raise _usage(f"--frame: {anim} has frames 0-{tracks[anim].frames - 1} (the frames apply to every --pose)")
    for anim in args.pose or []:
        try:
            path = folder / (f"pose_{anim}.{args.variant}.png" if args.variant else f"pose_{anim}.png")
            pv.filmstrip(built, anim, args.size or 200, pose_views, pose_frames, swap).save(path)
            outputs.setdefault("pose", {})[anim] = display_path(path)
        except KeyError:
            raise _usage(f"{name} has no animation {anim!r} (animations: {', '.join(built.model.animations) or 'none'})") from None
        except ValueError as exc:
            raise _usage(f"--frame: {exc}") from None
    if args.fit:
        try:
            path = folder / "fit.png"
            pv.fitted(built).save(path)
            outputs["fit"] = display_path(path)
        except KeyError:
            raise _usage(f"{name} has no fit_to (an attachment made around a character)") from None
    if args.detach:
        try:
            path = folder / "detach.png"
            pv.detach(built).save(path)
            outputs["detach"] = display_path(path)
        except KeyError:
            raise _usage(f"{name} has no separate parts (rig: {{ <id>: {{ separate: true }} }}, on a skinned model)") from None
    if args.effect:
        effect = built.model.effect
        if effect is None:
            raise _usage(f"{name} has no effect: block")
        pieces = {e.model: built if e.model == name else _built(project, e.model) for e in effect.emitters}
        path = folder / "effect.png"
        try:
            pv.effect_strip(built, pieces, times=_times(args.at) if args.at is not None else None).save(path)
        except ValueError as exc:
            raise _usage(f"{name} effect: {exc}") from None
        outputs["effect"] = display_path(path)
    metrics: dict[str, Any] | None = None
    if args.vs:
        metrics = _compare(project, built, Path(args.vs), args.ref_height, folder, outputs)
    elif args.vs is not None:
        images = pv.inspiration_images(project.styles_dir, built.style.name)
        if not images:
            raise _usage(f"no inspiration images in styles/{built.style.name}/inspiration/ (png, jpg, webp)")
        path = folder / "vs_inspiration.png"
        pv.versus(built, images).save(path)
        outputs["vs_inspiration"] = display_path(path)
    if args.engine:
        outputs["engine"] = _engine_preview(project, built, folder, yaws, pitches, size)
    for key, value in outputs.items():
        for label, path in (value.items() if isinstance(value, dict) else [("", value)]):
            out.say(f"{name} {key}{' ' + label if label else ''}: {path}")
    if metrics is not None:
        for line in pv.compare_summary(metrics):
            out.say(f"{name} vs {metrics['file']}: {line}")
    out.result({"model": name, "outputs": outputs, "triangles": built.triangles, **({"compare": metrics} if metrics else {})})
    return 0


def _compare(project: Project, built: Any, ref_path: Path, ref_height: float | None, folder: Path, outputs: dict[str, Any]) -> dict[str, Any]:
    """`--vs <ref.glb>`: the comparison sheet and metrics."""
    from kiln import preview as pv
    from kiln.export import to_glb
    from kiln.importer import ImportError_, gltf_counts, joint_heights, load_reference

    if ref_path.suffix.lower() not in (".glb", ".gltf") or not ref_path.is_file():
        raise _usage(f"--vs takes a .glb or .gltf file (or nothing: the style's inspiration images); {ref_path} isn't one")
    if ref_height is not None and ref_height <= 0:
        raise _usage("--ref-height is the reference's height in metres (> 0)")
    lo, hi = built.bounds()
    try:
        ref = load_reference(ref_path, built.style, ref_height, (float(lo[0] + hi[0]) / 2, float(lo[2] + hi[2]) / 2))
        ref_counts = gltf_counts(ref_path)
        ref_joints = joint_heights(ref_path) if built.model.skeleton == "humanoid" else {}  # head/hips: humanoid bands
    except (ImportError_, ValueError, KeyError, IndexError, OSError) as exc:
        raise _usage(f"can't read {ref_path}: {exc}") from None
    atlas = None
    if project.config.atlas:  # count what `kiln build` writes: with the atlas, one material (file names don't matter here)
        from kiln.atlas import AtlasUse, layout

        cells = layout([built])
        glow = cells.glow_strength(built)
        atlas = AtlasUse(cells, "palette.png", "material.png", "glow.png" if glow > 0 else None, project.config.atlas_ao, glow)
    counts = gltf_counts(to_glb(built, "kiln", None, project.config.vertex_colors, atlas, merge_rigid=project.config.merge_rigid))
    metrics = {"file": display_path(ref_path), "ref_height": ref_height, **pv.compare(built, ref, counts, ref_counts, ref_joints)}
    path = folder / f"vs_{ref_path.stem}.png"
    pv.versus_reference(built, ref, metrics, ref_path.name).save(path)
    outputs["vs_reference"] = display_path(path)
    return metrics


ENGINE_VIEWS = [("front-left", 45.0), ("back-left", 135.0), ("back-right", 225.0), ("front-right", 315.0)]  # as preview.HEADINGS


def _engine_preview(project: Project, built: Any, folder: Path, yaws: list[tuple[str, float]], pitches: list[float], size: int | None) -> str:
    """`preview --engine`: the model through Godot under its look kit, offscreen (#160), framed and laid out like the
    software views (#162): --views/--pitch/--size apply, the background is the previews' tile colour."""
    from PIL import Image

    from kiln import preview as pv
    from kiln.godot import find_godot_binary, find_godot_project, render_engine

    godot = find_godot_binary()
    root = find_godot_project(project.output_dir)
    manifest = project.output_dir / "manifest.json"
    if godot is None or root is None or not manifest.is_file():
        raise _usage("--engine needs Godot (GODOT=/path), export \"godot\" and a `kiln build` first")
    entry = json.loads(manifest.read_text()).get("models", {}).get(built.model.name)
    looks = json.loads(manifest.read_text()).get("looks", {})
    if entry is None or "godot_scene" not in entry:
        raise _usage("build first: `kiln build`")
    yaws = yaws or ENGINE_VIEWS
    pitches = pitches or [15.0, 50.0]
    tile = size or 400
    centre, half = pv.fit_of(built)
    views = [(yaw, pitch) for pitch in pitches for _, yaw in yaws]
    images, output = render_engine(godot, root, entry["godot_scene"], looks[built.style.name], views, half,
                                   (float(centre[0]), float(centre[1]), float(centre[2])), tile, folder / "engine")  # fmt: skip
    if not images:
        raise _usage(f"Godot couldn't render offscreen: {output[-400:]}")
    tiles = []
    for path in images:
        shot = Image.open(path).convert("RGBA")
        back = Image.new("RGBA", shot.size, pv.TILE_BG)
        tiles.append(Image.alpha_composite(back, shot))
    rows = [(f"{pitch:+g} degrees", [(n, tiles[i * len(yaws) + j]) for j, (n, _) in enumerate(yaws)]) for i, pitch in enumerate(pitches)]
    m = built.model
    path = folder / "engine.png"
    pv.sheet(f"{m.name} in Godot", f"look kit {built.style.name} · {m.cls} · front = +Z", rows).save(path)
    return display_path(path)


def _is_template(path: Path) -> bool:
    try:
        return any(line.split("#")[0].strip() == "template: true" for line in path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False


def _is_terrain(path: Path) -> bool:
    try:
        return any(line.split("#")[0].rstrip() == "terrain:" for line in path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False


def _is_scatter(path: Path) -> bool:
    try:
        return any(line.split("#")[0].rstrip() == "scatter:" for line in path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False


def cmd_lineup(args: argparse.Namespace, out: Output) -> int:
    from kiln import preview as pv

    project = _require_project()
    names = args.models or [p.name[: -len(MODEL_SUFFIX)] for p in project.model_paths() if not _is_template(p) and not _is_terrain(p) and not _is_scatter(p)]
    builts = [_built(project, n) for n in names]
    project.preview_dir.mkdir(parents=True, exist_ok=True)
    path = project.preview_dir / "lineup.png"
    pv.lineup(builts).save(path)
    out.say(f"line-up: {display_path(path)}")
    out.result({"lineup": display_path(path), "models": names})
    return 0


def cmd_gallery(args: argparse.Namespace, out: Output) -> int:
    from kiln import preview as pv
    from kiln.lint import lint_project

    project = _require_project()
    result = lint_project(project)
    builts = [_with_occlusion(project, result.built[n]) for n in sorted(result.built)]
    project.preview_dir.mkdir(parents=True, exist_ok=True)
    path = project.preview_dir / "gallery.png"
    pv.gallery(builts).save(path)
    out.say(f"gallery ({len(builts)} models): {display_path(path)}")
    out.result({"gallery": display_path(path), "models": len(builts)})
    return 0


# --- long-term management ----------------------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace, out: Output) -> int:
    from kiln.notation import load_model

    project = _require_project()
    rows = []
    for path in project.model_paths():
        style_name = None
        model, _, findings = project.load(path)
        if model is None:
            model, _ = load_model(path, {}, set())
        errors = [f for f in findings if f.severity == "error"]
        if model is not None:
            style_name = model.style or project.config.default_style
        stale = model is not None and model.style_version is not None and model.style_version < project.config.style_version
        rows.append({"name": path.name[: -len(MODEL_SUFFIX)], "class": model.cls if model else "?", "status": model.status if model else "?",
                     "style": style_name, "style_version": model.style_version if model else None, "needs_review": stale,
                     "errors": len(errors), "description": model.description if model else ""})  # fmt: skip
    if args.verbose:
        for r in rows:
            flag = " REVIEW (older style)" if r["needs_review"] else ""
            err = f" {r['errors']} errors" if r["errors"] else ""
            out.say(f"{r['name']:<24} {r['class']:<10} {r['status']:<9} {r['style'] or '':<10}{flag}{err}  {r['description']}")
    else:  # one line per state: what needs doing, and to which models
        groups: dict[str, list[str]] = {}
        for r in rows:
            state = ", ".join([*(["errors"] if r["errors"] else []), *(["review (older style)"] if r["needs_review"] else []), str(r["status"])])
            groups.setdefault(state, []).append(str(r["name"]))
        for state, names in sorted(groups.items(), key=lambda g: (g[0] == "approved", -len(g[1]))):
            out.say(f"  [{state}] ({len(names)}): {', '.join(names)}")
        if rows:
            out.say("  (`kiln status -v`: one line per model with class, style and description)")
    out.say(f"{len(rows)} models; project style_version {project.config.style_version}")
    if not args.verbose:
        rows = [{k: v for k, v in r.items() if k != "description"} for r in rows]
    out.result({"models": rows, "style_version": project.config.style_version})
    return 0


def _set_top_level(text: str, key: str, value: str) -> str:
    """Set `key: value` at the top level of a YAML file (a line edit: comments and layout stay)."""
    pattern = re.compile(rf"^{key}:.*$", re.M)
    if pattern.search(text):
        return pattern.sub(f"{key}: {value}", text, count=1)
    name = re.search(r"^name:.*$", text, re.M)
    at = name.end() if name else 0
    return text[:at] + f"\n{key}: {value}" + text[at:]


def cmd_mark(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    changed = []
    for name in args.models:
        path = _model_path(project, name)
        text = path.read_text(encoding="utf-8")
        if args.approved or args.draft:
            text = _set_top_level(text, "status", "approved" if args.approved else "draft")
        if args.current:
            text = _set_top_level(text, "style_version", str(project.config.style_version))
        path.write_text(text, encoding="utf-8")
        changed.append(name)
        out.say(f"marked {name}")
    out.result({"marked": changed})
    return 0


def cmd_style(args: argparse.Namespace, out: Output) -> int:
    project = load_project()
    styles_dir = project.styles_dir if project.styles_dir.is_dir() else None
    if args.style_cmd == "list":
        own = sorted(p.name[: -len(STYLE_SUFFIX)] for p in project.styles_dir.glob(f"*{STYLE_SUFFIX}")) if styles_dir else []
        rows = []
        for name in sorted(set(builtin_names()) | set(own)):
            style, _ = load_style(name, styles_dir)
            rows.append({"name": name, "project": name in own, "description": style.description if style else ""})
            out.say(f"{name:<12} {'(project) ' if name in own else ''}{style.description if style else ''}")
        out.result({"styles": rows, "default": project.config.default_style})
        return 0
    if args.style_cmd == "show":
        style, findings = load_style(args.name or project.config.default_style, styles_dir)
        if style is None:
            raise PaganError(findings)
        summary = style_summary(style)
        if not out.as_json:
            print(style.path.read_text(encoding="utf-8") if style.path else json.dumps(summary, indent=2))
        out.result({"style": summary})
        return 0
    if args.style_cmd == "new":
        if not NAME_RE.match(args.name):
            raise _usage("style names are lowercase letters, digits, _ or -")
        path = project.styles_dir / f"{args.name}{STYLE_SUFFIX}"
        if path.exists():
            raise _usage(f"{display_path(path)} already exists", path)
        base = args.extends
        if base not in builtin_names() and not (project.styles_dir / f"{base}{STYLE_SUFFIX}").is_file():
            raise _usage(f"unknown style {base!r} to extend")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f'description = "{args.description or args.name}"\nextends = "{base}"\nnotes = """\nTODO: shapes, proportions, colours, '
            'materials, lighting. Written from the inspiration images.\n"""\n\n# Override only what differs from the base, e.g.:\n'
            "# [shape]\n# resolution = 0.01\n# [look]\n# saturation = 1.2\n",
            encoding="utf-8",
        )
        (project.styles_dir / args.name / "inspiration").mkdir(parents=True, exist_ok=True)
        out.say(f"wrote {display_path(path)}; put inspiration images in styles/{args.name}/inspiration/ and compare with "
                f"`kiln preview <model> --vs`")  # fmt: skip
        out.result({"style": display_path(path)})
        return 0
    # bump
    project = _require_project()
    assert project.config_path is not None
    text = project.config_path.read_text(encoding="utf-8")
    new = project.config.style_version + 1
    if re.search(r"^style_version\s*=.*$", text, re.M):
        text = re.sub(r"^style_version\s*=\s*\d+", f"style_version = {new}", text, count=1, flags=re.M)
    else:
        text += f"\nstyle_version = {new}\n"
    project.config_path.write_text(text, encoding="utf-8")
    style_md = project.root / "STYLE.md"
    if style_md.is_file():
        style_md.write_text(style_md.read_text(encoding="utf-8").rstrip("\n") + f"\n- v{new} ({date.today().isoformat()}): {args.message}\n", encoding="utf-8")
    out.say(f"style_version {new}: models made under older versions are flagged for review (kiln status, W107)")
    out.result({"style_version": new})
    return 0


def cmd_config(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    assert project.config_path is not None
    cfg = project.config
    values = {"default_style": cfg.default_style, "default_palette": cfg.default_palette, "output_dir": cfg.output_dir,
              "preview_dir": cfg.preview_dir, "export": list(cfg.export), "style_version": cfg.style_version,
              "variant_glbs": cfg.variant_glbs, "vertex_colors": cfg.vertex_colors, "atlas": cfg.atlas, "atlas_ao": cfg.atlas_ao,
              "preview_size": cfg.preview_size}  # fmt: skip
    if args.config_cmd == "show":
        for key, meaning in SETTINGS.items():
            out.say(f"{key:<16} = {json.dumps(values[key]):<24} {meaning}")
        out.result({"settings": values})
        return 0
    if args.key not in SETTINGS:
        raise _usage(f"unknown setting {args.key!r}; settings: {', '.join(SETTINGS)}")
    if args.config_cmd == "get":
        out.say(json.dumps(values[args.key]))
        out.result({"key": args.key, "value": values[args.key]})
        return 0
    import tomllib

    try:
        value = tomllib.loads(f"v = {args.value}")["v"]
    except tomllib.TOMLDecodeError:
        value = args.value
    text = project.config_path.read_text(encoding="utf-8")
    literal = json.dumps(value)
    pattern = re.compile(rf"^{args.key}\s*=\s*[^#\n]*?(\s*#.*)?$", re.M)
    if pattern.search(text):
        text = pattern.sub(lambda m: f"{args.key} = {literal}{m.group(1) or ''}", text, count=1)
    else:
        first_table = re.search(r"^\[", text, re.M)
        at = first_table.start() if first_table else len(text)
        text = text[:at] + f"{args.key} = {literal}\n" + text[at:]
    _, findings = parse_config(tomllib.loads(text), project.config_path)
    if findings:
        raise PaganError(findings)
    project.config_path.write_text(text, encoding="utf-8")
    out.say(f"{args.key}: {json.dumps(values[args.key])} -> {literal}")
    out.result({"key": args.key, "old": values[args.key], "new": value})
    return 0


def _write_imported(project: Project, name: str, file: str, licence: str, author: str, url: str, height: float | None, cls: str,
                    description: str, force: bool) -> Path:  # fmt: skip
    """The model file for an imported mesh (`kiln import`, `kiln pack import`)."""
    path = project.models_dir / f"{name}{MODEL_SUFFIX}"
    if path.exists() and not force:
        raise _usage(f"{display_path(path)} already exists (use --force)", path)
    process = [f"  height: {height}"] if height else ["  scale: 1.0"]
    text = "\n".join([
        f"name: {name}",
        f"description: {json.dumps(description)}",
        f"class: {cls}",
        "status: draft",
        f"style_version: {project.config.style_version}",
        "source:",
        f"  file: {file}",
        f"  licence: {licence}",
        f"  author: {json.dumps(author)}",
        f"  url: {json.dumps(url)}",
        "process:",
        *process,
        "  recolor: auto           # snap colours to the project palette (keep = the file's own colours)",
        "",
    ])  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def cmd_import(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    src = Path(args.file).resolve()
    if not src.is_file() or src.suffix.lower() not in (".glb", ".gltf", ".fbx", ".blend", ".obj"):
        raise _usage(f"{args.file}: need a .glb or .gltf file (or .fbx/.blend/.obj with Blender 4.x)")
    name = args.name or re.sub(r"[^a-z0-9_-]+", "_", src.stem.lower()).strip("_")
    if not NAME_RE.match(name):
        raise _usage("give the model a name: --name tree_big")
    dest_dir = project.root / "imports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    from kiln.blender import BlenderError, converted, needs_blender

    if needs_blender(src):  # converted once into imports/<stem>.glb: the project then builds without Blender
        try:
            glb = converted(src, project.root / ".kiln-cache")
        except BlenderError as exc:
            raise _usage(str(exc), src) from exc
        dest = dest_dir / f"{src.stem}.glb"
        shutil.copyfile(glb, dest)
    elif missing := missing_files(src):
        raise _usage(f"{args.file} refers to {', '.join(missing)}, which isn't next to it: import from the pack's own folder")
    elif src != dest:
        shutil.copy2(src, dest)
        for uri in external_files(src):  # buffers and textures, keeping their relative paths (Textures/...)
            (dest_dir / uri).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src.parent / uri, dest_dir / uri)
    path = _write_imported(project, name, f"imports/{dest.name}", args.licence, args.author or "", args.url or "", args.height, args.cls,
                           args.description or f"imported from {src.name}", args.force)
    out.say(f"imported {src.name} as {display_path(path)}; `kiln preview {name}` to check scale and colours")
    out.result({"model": display_path(path), "file": display_path(dest)})
    return 0


def _pack_error(exc: Exception) -> PaganError:
    return _usage(str(exc))


def cmd_pack(args: argparse.Namespace, out: Output) -> int:
    from kiln import packs

    try:
        if args.pack_cmd == "list":
            return _pack_list(out)
        if args.pack_cmd == "add":
            recipe = packs.load_recipe(args.recipe)
            if not out.as_json:
                print(f"kiln: mirroring {recipe.key} from {recipe.url}", file=sys.stderr)
            mirror, fetched = packs.add(recipe, force=args.force)
            usable = sum(1 for e in mirror.models if "error" not in e)
            out.say(f"{mirror.key}: {'mirrored' if fetched else 'already mirrored'} in {mirror.path} ({usable} models"
                    f"{f', {len(mirror.models) - usable} unreadable' if usable < len(mirror.models) else ''}); `kiln pack search <words>`")  # fmt: skip
            out.result({"pack": mirror.recipe.name, "version": mirror.recipe.version, "path": str(mirror.path), "fetched": fetched,
                        "models": len(mirror.models), "unreadable": len(mirror.models) - usable, "archive_sha256": mirror.archive_sha256})  # fmt: skip
            return 0
        if args.pack_cmd == "search":
            return _pack_search(args, out)
        return _pack_import(args, out)
    except packs.PackError as exc:
        raise _pack_error(exc) from None


def _pack_list(out: Output) -> int:
    from kiln import packs

    mirrored = {m.key: m for m in packs.mirrors()}
    rows: list[dict[str, Any]] = []
    for r in packs.builtin_recipes().values():
        m = mirrored.pop(r.key, None)
        rows.append({"pack": r.name, "version": r.version, "title": r.title, "source": r.source, "licence": r.licence, "url": r.url,
                     "shipped": True, "mirrored": m is not None, "models": len(m.models) if m else None})  # fmt: skip
    for m in mirrored.values():  # from recipe files, or older versions
        r = m.recipe
        rows.append({"pack": r.name, "version": r.version, "title": r.title, "source": r.source, "licence": r.licence, "url": r.url,
                     "shipped": False, "mirrored": True, "models": len(m.models)})  # fmt: skip
    for row in rows:
        state = f"mirrored, {row['models']} models" if row["mirrored"] else "not mirrored (kiln pack add " + row["pack"] + ")"
        out.say(f"{row['pack'] + '@' + row['version']:<52} {row['licence']:<8} {state}")
    out.say(f"cache: {packs.cache_root()}")
    out.result({"packs": rows, "cache": str(packs.cache_root())})
    return 0


def _pack_search(args: argparse.Namespace, out: Output) -> int:
    from kiln import packs

    if args.limit < 1:
        raise _usage("--limit is at least 1")
    hits = packs.search(args.terms, args.pack)
    shown = hits[: args.limit]
    for h in shown:
        e = h.entry
        stats = f"{e['triangles']} tris, {' x '.join(f'{s:g}' for s in e['size'])}" if "triangles" in e else f"unreadable: {e.get('error')}"
        out.say(f"{h.mirror.key:<44} {e['path']:<40} {stats}  [{', '.join(e['tags'])}]")
    if not hits:
        out.say("no models found" + ("" if packs.mirrors() else ": no packs mirrored yet (kiln pack list, kiln pack add <pack>)"))
    elif len(hits) > len(shown):
        out.say(f"{len(hits)} models, first {len(shown)} shown (--limit)")
    data: dict[str, Any] = {"hits": [h.to_dict() for h in shown], "total": len(hits)}
    if args.lineup:
        data["lineup"] = _pack_lineup([h for h in shown if "error" not in h.entry][:LINEUP_MAX])
        out.say(f"line-up: {data['lineup']}")
    out.result(data)
    return 0


LINEUP_MAX = 12  # search hits in a --lineup sheet


def _pack_lineup(hits: list[Any]) -> str:
    """The hits side by side at one scale (each in its file's own units, standing on the ground)."""
    from kiln import preview as pv
    from kiln.importer import ImportError_, load_reference

    root = find_project_root(Path.cwd())
    project = load_project(root) if root is not None else None
    style, findings = project.style() if project is not None else load_style("soft_toy")
    if style is None:
        raise PaganError(findings)
    builts = []
    for h in hits:
        try:
            built = load_reference(h.mirror.file(h.entry), style)
            built.model.name = str(h.entry["name"])  # the tile's label (KayKit's chair.gltf.glb -> chair)
            builts.append(built)
        except (ImportError_, ValueError, KeyError, IndexError, OSError):
            continue
    folder = project.preview_dir if project is not None else Path.cwd()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "pack-search.png"
    pv.lineup(builts).save(path)
    return display_path(path)


def _pack_import(args: argparse.Namespace, out: Output) -> int:
    from kiln import packs

    project = _require_project()
    mirror = packs.find_mirror(args.pack)
    entry = packs.find_model(mirror, args.model)
    name = args.name or re.sub(r"[^a-z0-9_-]+", "_", str(entry["name"]).lower()).strip("_")
    if not NAME_RE.match(name):
        raise _usage("give the model a name: --name tree_big")
    model_path = project.models_dir / f"{name}{MODEL_SUFFIX}"
    if model_path.exists() and not args.force:
        raise _usage(f"{display_path(model_path)} already exists (use --force)", model_path)
    dest, written = packs.copy_into_project(project.root, mirror, entry, force=args.force)
    r = mirror.recipe
    path = _write_imported(project, name, dest.relative_to(project.root).as_posix(), r.licence, r.author, r.homepage or r.url, args.height,
                           args.cls, args.description or f"{entry['path']} from {r.key}", True)  # fmt: skip
    out.say(f"imported {entry['path']} from {r.key} as {display_path(path)} ({len(written)} file{'s' if len(written) > 1 else ''} in {packs.LOCK_NAME}); "
            f"`kiln preview {name}` to check scale and colours")  # fmt: skip
    out.result({"model": display_path(path), "file": display_path(dest), "pack": r.name, "version": r.version, "locked": sorted(written)})
    return 0


def cmd_credits(args: argparse.Namespace, out: Output) -> int:
    from kiln.packs import locked_pack

    project = _require_project()
    rows = []
    for path in project.model_paths():
        model, _, _ = project.load(path)
        if model is not None and model.source is not None:
            credited = model.source.original or model.source.file
            row = {"model": model.name, "file": credited.name, "licence": model.source.licence,
                   "author": model.source.author, "url": model.source.url}  # fmt: skip
            pack = locked_pack(project.root, model.source.file)
            if pack is not None:  # imported with `kiln pack import` (kiln.lock)
                row["pack"] = pack
            rows.append(row)
            out.say(f"{model.name}: {credited.name} by {model.source.author or '?'} ({model.source.licence}) {model.source.url}"
                    f"{f' [{pack}]' if pack else ''}")  # fmt: skip
    if not rows:
        out.say("no imported models: everything was made in KILN")
    out.result({"credits": rows})
    return 0


def cmd_doctor(args: argparse.Namespace, out: Output) -> int:
    from kiln.godot import find_godot_binary

    godot = find_godot_binary()
    from kiln.godot import offscreen_command

    offscreen = offscreen_command()
    display = not isinstance(offscreen, str)  # engine renders run offscreen, never on the desktop (#160)
    how = offscreen if isinstance(offscreen, str) else offscreen.how
    from kiln.blender import blender_version, find_blender

    blender = find_blender()
    blender_ver = blender_version(blender) if blender else None
    info = {"kiln": __version__, "python": sys.version.split()[0], "godot": godot, "display": display, "offscreen": how, "blender": blender, "blender_version": blender_ver}
    out.say(f"kiln {__version__}, Python {info['python']}")
    out.say(f"Godot: {godot or 'not found (set GODOT=/path/to/godot for --verify-godot and --engine)'}")
    out.say(f"Blender: {f'{blender} ({blender_ver})' if blender_ver else 'not found (set BLENDER=/path/to/blender, 4.x, for .fbx/.blend/.obj imports)'}")
    out.say(f"engine renders (preview --engine): {'yes, via ' + how if display else how}")
    out.result(info)
    return 0


def _skill_files() -> list[str]:
    """The skill's files, relative to the skill folder: SKILL.md and every topic."""
    folder = files("kiln").joinpath("skill", "topics")
    return ["SKILL.md", *sorted(f"topics/{e.name}" for e in folder.iterdir() if e.name.endswith(".md"))]


STALE_SKILL_FILES = ("reference.md",)  # written by KILN < 0.14, replaced by topics/


def cmd_docs(args: argparse.Namespace, out: Output) -> int:
    from kiln import topics as docs

    if args.search:
        hits = docs.search(" ".join([*(args.topic or []), *args.search]), limit=args.limit)
        for hit in hits:
            out.say(f"--- {hit.topic} > {hit.heading}\n{hit.text}")
        if not hits:
            out.say("no matches; `kiln docs` lists the topics")
        out.result({"hits": [{"topic": h.topic, "heading": h.heading, "text": h.text} for h in hits]})
        return 0
    if not args.topic:
        listed = docs.topics()
        width = max(len(t.name) for t in listed)
        for t in listed:
            out.say(f"{t.name:<{width}}  ~{t.tokens / 1000:.1f}k tokens  {t.summary}")
        out.say("`kiln docs <topic>` prints one; `kiln docs --search <words>` finds paragraphs.")
        out.result({"topics": [{"name": t.name, "summary": t.summary, "tokens": t.tokens} for t in listed]})
        return 0
    texts = []
    for name in args.topic:
        topic = docs.find(name)
        if topic is None:
            near = docs.close_matches(name)
            hint = f" (did you mean {', '.join(near)}?)" if near else ""
            raise _usage(f"no docs topic {name!r}{hint}; `kiln docs` lists them, `kiln docs --search {name}` searches")
        texts.append(topic.text)
        out.say(topic.text)
    out.result({"topics": [{"name": n.lower(), "text": t} for n, t in zip(args.topic, texts, strict=True)]})
    return 0


def cmd_skill(args: argparse.Namespace, out: Output) -> int:
    target = Path(args.target).resolve() if args.target else (find_project_root(Path.cwd()) or Path.cwd()) / ".claude" / "skills" / "kiln"
    target.mkdir(parents=True, exist_ok=True)
    names = _skill_files()
    for name in names:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files("kiln").joinpath("skill", *name.split("/")).read_text(encoding="utf-8"), encoding="utf-8")
    for name in STALE_SKILL_FILES:
        if (target / name).is_file():
            (target / name).unlink()
    out.say(f"KILN skill installed in {display_path(target)}")
    out.result({"skill": display_path(target), "files": sorted(names)})
    return 0


def cmd_mcp(args: argparse.Namespace, out: Output) -> int:
    try:
        from kiln.mcp_server import serve
    except ImportError:
        raise _usage('the MCP server needs the mcp package: pip install --upgrade kiln-gen') from None
    serve(Path(args.project).resolve() if args.project else Path.cwd(), allow_godot=args.allow_godot)
    return 0


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")
    p = argparse.ArgumentParser(prog="kiln", description="KILN: smooth stylised 3D models written as text, built into glTF.")
    p.add_argument("--version", action="version", version=f"kiln {__version__}")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", parents=[common], help="create a KILN project")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--style", default="soft_toy", help="starting style (kiln style list)")
    s = sub.add_parser("new", parents=[common], help="scaffold a model")
    s.add_argument("kind", choices=["model"])
    s.add_argument("name")
    s.add_argument("--template", choices=["bean", "prop", "empty"], default="empty")
    s.add_argument("--extends", help="comma-separated library templates, e.g. body_stocky,head_bearded,helmet_nasal (see `kiln library`)")
    s.add_argument("--class", dest="cls")
    s.add_argument("--description")
    s.add_argument("--force", action="store_true")
    sub.add_parser("library", parents=[common], help="KILN's templates: bodies, heads, helmets, armour")
    s = sub.add_parser("lint", parents=[common], help="check models (errors and warnings)")
    s.add_argument("paths", nargs="*")
    s.add_argument("--fast", action="store_true", help="text checks only, in a second: notation, colours, rig, animations (no meshing, so no geometric findings)")
    s = sub.add_parser("build", parents=[common], help="build every model (or the ones named) into the output dir")
    s.add_argument("models", nargs="*", help="only these models; the others keep what the last build wrote")
    s.add_argument("--verify-godot", action="store_true", help="load everything in headless Godot afterwards")
    s = sub.add_parser("preview", parents=[common], help="preview sheets for one model (default: turntable)")
    s.add_argument("model")
    s.add_argument("--turntable", action="store_true", help="8 sides x 3 heights (the default sheet when nothing else is asked for)")
    s.add_argument("--views", metavar="V,V,...", help="one sheet of these views: names (front, front-left, left, back, side, 34, ...) or "
                   "degrees (counter-clockwise from the front); default all 8 with --pitch")  # fmt: skip
    s.add_argument("--pitch", metavar="DEG,...", help="with --views: degrees above the horizon, a row each (default 15)")
    s.add_argument("--size", type=int, metavar="PX", help="tile size in pixels (64-1024) for turntable, closeup and views (kiln.toml preview_size)")
    s.add_argument("--closeup", action="append", metavar="PART")
    s.add_argument("--pose", action="append", metavar="ANIMATION")
    s.add_argument("--vs", nargs="?", const="", metavar="REF",
                   help="beside the style's inspiration images; with a .glb/.gltf: against that reference at one scale, with metrics")  # fmt: skip
    s.add_argument("--ref-height", type=float, metavar="METRES", help="scale the --vs reference to this height (default: its own units)")
    s.add_argument("--detach", action="store_true", help="each separate part taken off: what's left, and what it covered")
    s.add_argument("--fit", action="store_true", help="an attachment (fit_to) on its character, and the character without it")
    s.add_argument("--effect", action="store_true", help="the model's effect: block played out (its emitted models over time)")
    s.add_argument("--at", metavar="T,T,...", help="with --effect: a contact sheet at these times (seconds) instead of 8 evenly spaced frames")
    s.add_argument("--frame", metavar="N,N,...", help="with --pose: only these frames (e.g. one, up close with --size)")
    s.add_argument("--engine", action="store_true", help="render through Godot, offscreen (needs a build; Linux: xvfb); --views/--pitch/--size pick its views")
    s.add_argument("--variant")
    s = sub.add_parser("lineup", parents=[common], help="models side by side at one scale")
    s.add_argument("models", nargs="*")
    sub.add_parser("gallery", parents=[common], help="every model in one sheet")
    s = sub.add_parser("status", parents=[common], help="every model: class, status, style, review flags")
    s.add_argument("-v", "--verbose", action="store_true", help="one line per model (class, status, style) with its description")
    s = sub.add_parser("mark", parents=[common], help="set status or style_version")
    s.add_argument("models", nargs="+")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--approved", action="store_true")
    g.add_argument("--draft", action="store_true")
    s.add_argument("--current", action="store_true", help="style_version = the project's")
    s = sub.add_parser("style", parents=[common], help="styles: list, show, new, bump")
    ss = s.add_subparsers(dest="style_cmd", required=True)
    ss.add_parser("list", parents=[common])
    x = ss.add_parser("show", parents=[common])
    x.add_argument("name", nargs="?")
    x = ss.add_parser("new", parents=[common])
    x.add_argument("name")
    x.add_argument("--extends", default="soft_toy")
    x.add_argument("--description")
    x = ss.add_parser("bump", parents=[common])
    x.add_argument("--message", "-m", required=True)
    s = sub.add_parser("config", parents=[common], help="show, get or set kiln.toml settings")
    cs = s.add_subparsers(dest="config_cmd", required=True)
    cs.add_parser("show", parents=[common])
    x = cs.add_parser("get", parents=[common])
    x.add_argument("key")
    x = cs.add_parser("set", parents=[common])
    x.add_argument("key")
    x.add_argument("value")
    s = sub.add_parser("import", parents=[common], help="bring in a .glb/.gltf (e.g. a CC0 pack item) as a model")
    s.add_argument("file")
    s.add_argument("--name")
    s.add_argument("--licence", required=True, help="SPDX id, e.g. CC0-1.0 or CC-BY-4.0")
    s.add_argument("--author")
    s.add_argument("--url")
    s.add_argument("--height", type=float, help="scale so it is this tall (metres)")
    s.add_argument("--class", dest="cls", default="prop")
    s.add_argument("--description")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("pack", parents=[common], help="CC0 packs: mirror (the only network access), search, import with a licence lock")
    ps = s.add_subparsers(dest="pack_cmd", required=True)
    ps.add_parser("list", parents=[common], help="shipped packs and what is mirrored")
    x = ps.add_parser("add", parents=[common], help="download a pack into the cache (~/.cache/kiln/packs)")
    x.add_argument("recipe", help="a shipped pack (kiln pack list) or a recipe file (my-pack.toml)")
    x.add_argument("--force", action="store_true", help="download again even if mirrored")
    x = ps.add_parser("search", parents=[common], help="search mirrored packs by file name and tags")
    x.add_argument("terms", nargs="*")
    x.add_argument("--pack", help="only this pack (name or name@version)")
    x.add_argument("--limit", type=int, default=30)
    x.add_argument("--lineup", action="store_true", help="a line-up sheet of the first hits")
    x = ps.add_parser("import", parents=[common], help="copy a pack model into imports/<pack>/, write its model and kiln.lock")
    x.add_argument("pack", help="name or name@version")
    x.add_argument("model", help="its path in the pack (as search shows it) or its file name")
    x.add_argument("--name")
    x.add_argument("--height", type=float, help="scale so it is this tall (metres)")
    x.add_argument("--class", dest="cls", default="prop")
    x.add_argument("--description")
    x.add_argument("--force", action="store_true", help="replace an existing model and imported files")
    sub.add_parser("credits", parents=[common], help="authors and licences of imported models")
    sub.add_parser("doctor", parents=[common], help="versions, Godot, offscreen rendering")
    s = sub.add_parser("docs", parents=[common], help="the documentation, one topic at a time (list, print, search)")
    s.add_argument("topic", nargs="*", help="topic name(s); none = list the topics")
    s.add_argument("--search", "-s", nargs="+", metavar="WORD", help="print the paragraphs that match these words")
    s.add_argument("--limit", type=int, default=5, help="most paragraphs --search prints (default 5)")
    s = sub.add_parser("skill", parents=[common], help="install the Claude skill")
    s.add_argument("action", choices=["install"])
    s.add_argument("--target")
    s = sub.add_parser("mcp", parents=[common], help="run the MCP server (stdio)")
    s.add_argument("--project")
    s.add_argument("--allow-godot", action="store_true")
    return p


COMMANDS = {"init": cmd_init, "new": cmd_new, "lint": cmd_lint, "build": cmd_build, "preview": cmd_preview, "lineup": cmd_lineup,
            "gallery": cmd_gallery, "status": cmd_status, "mark": cmd_mark, "style": cmd_style, "config": cmd_config,
            "import": cmd_import, "pack": cmd_pack, "credits": cmd_credits, "doctor": cmd_doctor, "skill": cmd_skill, "docs": cmd_docs, "mcp": cmd_mcp, "library": cmd_library}  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    out = Output(args.json)
    try:
        return COMMANDS[args.cmd](args, out)
    except PaganError as exc:
        out.failure(exc.findings)
        return 1


__all__ = ["main", "parser"]
