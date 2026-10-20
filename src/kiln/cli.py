"""`kiln` command line: init, new, lint, build, preview, lineup, gallery, status, mark, style, config, import,
credits, doctor, skill, mcp. Human-readable output by default, `--json` for machines, non-zero exit on errors."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
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
from kiln.vendor.findings import Finding, PaganError, display_path

SETTINGS = {
    "default_style": "the style every model uses unless it names its own (kiln style list)",
    "default_palette": "palettes/<name>.pal.yaml (PAGAN format) whose colour names models use",
    "output_dir": "where kiln build writes (inside a Godot project for export godot)",
    "preview_dir": "where previews go",
    "export": 'what kiln build writes: ["glb"] or ["glb", "godot"]',
    "style_version": "the look's version; models made under an older one are flagged (W107)",
    "variant_glbs": "true: a .glb per variant; false: variants are swap tables (Godot: <name>.<variant>.tscn recolours the base)",
    "vertex_colors": "true: colours in the vertices, one surface per material preset (fewer draw calls); needs variant_glbs",
    "atlas": "true: one material per model (palette textures; variants swap the texture): 1 surface, 2 with decals",
    "atlas_ao": "true (with atlas): bake ambient occlusion into the vertex colours",
}


class Output:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def say(self, text: str) -> None:
        if not self.as_json:
            print(text)

    def result(self, data: dict[str, Any]) -> None:
        if self.as_json:
            print(json.dumps({"ok": True, **data}, indent=2))

    def failure(self, findings: list[Finding], data: dict[str, Any] | None = None) -> None:
        if self.as_json:
            print(json.dumps({"ok": False, **(data or {}), "findings": [f.to_dict() for f in findings]}, indent=2))
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


def cmd_init(args: argparse.Namespace, out: Output) -> int:
    root = Path(args.dir).resolve()
    if (root / CONFIG_NAME).exists():
        raise _usage(f"{root / CONFIG_NAME} already exists", root / CONFIG_NAME)
    if args.style not in builtin_names():
        raise _usage(f"unknown style {args.style!r}; built-in: {', '.join(builtin_names())}")
    for folder in ("models", "palettes", "styles", "decals", "imports"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    values = {"style": args.style}
    (root / CONFIG_NAME).write_text(Template(_template("kiln.toml")).safe_substitute(values), encoding="utf-8")
    (root / "palettes" / "main.pal.yaml").write_text(_template("main.pal.yaml"), encoding="utf-8")
    for doc in ("BRIEF.md", "STYLE.md"):
        if not (root / doc).exists():
            (root / doc).write_text(Template(_template(doc)).safe_substitute(values), encoding="utf-8")
    if not (root / ".gitignore").exists():
        (root / ".gitignore").write_text(_template("gitignore"), encoding="utf-8")
    (root / "styles" / args.style / "inspiration").mkdir(parents=True, exist_ok=True)
    godot = find_godot_project(root.parent)
    if godot is not None and not (root / ".gdignore").exists():
        (root / ".gdignore").write_text("", encoding="utf-8")  # sources, imports and previews aren't game assets
    out.say(f"created KILN project in {display_path(root)} (style {args.style}); next: kiln new model <name>")
    if godot is not None:
        out.say(f"inside the Godot project {display_path(godot)}: wrote .gdignore; set output_dir to a folder Godot sees, e.g. ../assets/kiln")
    out.result({"project": display_path(root), "style": args.style, "godot_project": display_path(godot) if godot else None})
    return 0


def cmd_new(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    name = args.name
    if not NAME_RE.match(name):
        raise _usage("model names are lowercase letters, digits, _ or -")
    path = project.models_dir / f"{name}{MODEL_SUFFIX}"
    if path.exists() and not args.force:
        raise _usage(f"{display_path(path)} already exists (use --force to overwrite)", path)
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


def cmd_lint(args: argparse.Namespace, out: Output) -> int:
    from kiln.lint import lint_paths

    project = load_project(start=Path(args.paths[0]) if args.paths else None)
    paths = [_model_path(project, p) for p in args.paths] if args.paths else project.model_paths()
    result = lint_paths(project, paths, geometry=not args.fast)
    for f in result.findings:
        out.say(f.format())
    out.say(f"{len(paths)} models: {len(result.errors)} errors, {len(result.warnings)} warnings")
    data = {"models": len(paths), "errors": len(result.errors), "warnings": len(result.warnings),
            "findings": [f.to_dict() for f in result.findings]}  # fmt: skip
    if result.errors:
        if out.as_json:  # human output: the findings are printed above already
            out.failure(result.findings, data)
        return 1
    out.result(data)
    return 0


def cmd_build(args: argparse.Namespace, out: Output) -> int:
    from kiln.build import build
    from kiln.godot import find_godot_binary, res_path, verify

    project = _require_project()
    progress = (lambda s: print(f"kiln: {s}", file=sys.stderr)) if not out.as_json else None
    result = build(project, progress=progress)
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
            f"{result.unchanged} unchanged, {len(result.removed)} removed")  # fmt: skip
    if args.verify_godot:
        godot = find_godot_binary()
        if godot is None or result.godot_root is None:
            finding = Finding("E000", "--verify-godot needs a Godot binary (GODOT=/path) and export \"godot\"")
            out.failure([finding], data)
            return 1
        check = verify(godot, result.godot_root, res_path(result.output_dir / "manifest.json", result.godot_root))
        data["godot"] = {"ok": check.ok, "models": check.models}
        if not check.ok:
            out.say(check.output)
            out.failure([Finding("E000", "Godot verification failed (see output)")], {**data, "godot_output": check.output})
            return 1
        out.say(f"Godot: all {check.models} models load, with their parts, animations and materials")
    out.result(data)
    return 0


# --- previews ----------------------------------------------------------------------------------------------------


def _built(project: Project, name: str) -> Any:
    from kiln.builder import build_cached

    path = _model_path(project, name)
    model, style, findings = project.load(path)
    errors = [f for f in findings if f.severity == "error"]
    if model is None or style is None or errors:
        raise PaganError(errors or findings)
    palette, _ = project.palette(model.palette)
    try:
        return build_cached(model, style, palette, project.root / ".kiln-cache")
    except ValueError as exc:
        raise PaganError([Finding("E009", str(exc), path)]) from None


def cmd_preview(args: argparse.Namespace, out: Output) -> int:
    from kiln import preview as pv

    project = load_project(start=Path(args.model) if Path(args.model).suffix == ".yaml" else None)
    built = _built(project, args.model)
    name = built.model.name
    folder = project.preview_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Any] = {}
    swap = built.model.variants.get(args.variant) if args.variant else None
    if args.variant and swap is None:
        raise _usage(f"{name} has no variant {args.variant!r} (variants: {', '.join(built.model.variants) or 'none'})")
    wanted_any = args.closeup or args.pose or args.vs or args.engine or args.detach
    if args.turntable or not wanted_any:
        path = folder / (f"turntable.{args.variant}.png" if args.variant else "turntable.png")
        pv.turntable(built, swap=swap).save(path)
        outputs["turntable"] = display_path(path)
    for part in args.closeup or []:
        try:
            path = folder / f"closeup_{part}.png"
            pv.closeup(built, part).save(path)
            outputs.setdefault("closeup", {})[part] = display_path(path)
        except KeyError:
            raise _usage(f"{name} has no part {part!r} (ids: {', '.join(built.model.ids)}, or a part's number in the file: 0-{len(built.model.parts) - 1})") from None
    for anim in args.pose or []:
        try:
            path = folder / f"pose_{anim}.png"
            pv.filmstrip(built, anim).save(path)
            outputs.setdefault("pose", {})[anim] = display_path(path)
        except KeyError:
            raise _usage(f"{name} has no animation {anim!r} (animations: {', '.join(built.model.animations) or 'none'})") from None
    if args.detach:
        try:
            path = folder / "detach.png"
            pv.detach(built).save(path)
            outputs["detach"] = display_path(path)
        except KeyError:
            raise _usage(f"{name} has no separate parts (rig: {{ <id>: {{ separate: true }} }}, on a skinned model)") from None
    if args.vs:
        images = pv.inspiration_images(project.styles_dir, built.style.name)
        if not images:
            raise _usage(f"no inspiration images in styles/{built.style.name}/inspiration/ (png, jpg, webp)")
        path = folder / "vs_inspiration.png"
        pv.versus(built, images).save(path)
        outputs["vs_inspiration"] = display_path(path)
    if args.engine:
        outputs["engine"] = _engine_preview(project, built, folder)
    for key, value in outputs.items():
        for label, path in (value.items() if isinstance(value, dict) else [("", value)]):
            out.say(f"{name} {key}{' ' + label if label else ''}: {path}")
    out.result({"model": name, "outputs": outputs, "triangles": built.triangles})
    return 0


def _engine_preview(project: Project, built: Any, folder: Path) -> str:
    from PIL import Image

    from kiln.godot import find_godot_binary, find_godot_project, render_engine, res_path

    godot = find_godot_binary()
    root = find_godot_project(project.output_dir)
    manifest = project.output_dir / "manifest.json"
    if godot is None or root is None or not manifest.is_file():
        raise _usage("--engine needs Godot (GODOT=/path), export \"godot\" and a `kiln build` first")
    entry = json.loads(manifest.read_text()).get("models", {}).get(built.model.name)
    looks = json.loads(manifest.read_text()).get("looks", {})
    if entry is None or "godot_scene" not in entry:
        raise _usage("build first: `kiln build`")
    lo, hi = built.bounds()
    radius = float(((hi - lo) ** 2).sum() ** 0.5) / 2
    views = [(30.0, 15.0), (120.0, 15.0), (210.0, 15.0), (300.0, 15.0), (30.0, 60.0), (30.0, -20.0)]
    images, output = render_engine(godot, root, entry["godot_scene"], looks[built.style.name], views, radius, float((lo[1] + hi[1]) / 2), 320, folder / "engine")
    if not images:
        raise _usage(f"Godot couldn't render (needs a display): {output[-400:]}")
    sheet = Image.new("RGB", (320 * 3, 320 * 2))
    for i, path in enumerate(images):
        sheet.paste(Image.open(path).convert("RGB"), ((i % 3) * 320, (i // 3) * 320))
    path = folder / "engine.png"
    sheet.save(path)
    return display_path(path)


def _is_template(path: Path) -> bool:
    try:
        return any(line.split("#")[0].strip() == "template: true" for line in path.read_text(encoding="utf-8").splitlines())
    except (OSError, UnicodeDecodeError):
        return False


def cmd_lineup(args: argparse.Namespace, out: Output) -> int:
    from kiln import preview as pv

    project = _require_project()
    names = args.models or [p.name[: -len(MODEL_SUFFIX)] for p in project.model_paths() if not _is_template(p)]
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
    builts = [result.built[n] for n in sorted(result.built)]
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
    for r in rows:
        flag = " REVIEW (older style)" if r["needs_review"] else ""
        err = f" {r['errors']} errors" if r["errors"] else ""
        out.say(f"{r['name']:<24} {r['class']:<10} {r['status']:<9} {r['style'] or '':<10}{flag}{err}  {r['description']}")
    out.say(f"{len(rows)} models; project style_version {project.config.style_version}")
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
            print((style.path.read_text(encoding="utf-8") if style.path else json.dumps(summary, indent=2)))
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
              "variant_glbs": cfg.variant_glbs, "vertex_colors": cfg.vertex_colors, "atlas": cfg.atlas, "atlas_ao": cfg.atlas_ao}  # fmt: skip
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


def cmd_import(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    src = Path(args.file).resolve()
    if not src.is_file() or src.suffix.lower() not in (".glb", ".gltf"):
        raise _usage(f"{args.file}: need a .glb or .gltf file")
    name = args.name or re.sub(r"[^a-z0-9_-]+", "_", src.stem.lower()).strip("_")
    if not NAME_RE.match(name):
        raise _usage("give the model a name: --name tree_big")
    dest_dir = project.root / "imports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    missing = missing_files(src)
    if missing:
        raise _usage(f"{args.file} refers to {', '.join(missing)}, which isn't next to it: import from the pack's own folder")
    if src != dest:
        shutil.copy2(src, dest)
        for uri in external_files(src):  # buffers and textures, keeping their relative paths (Textures/...)
            (dest_dir / uri).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src.parent / uri, dest_dir / uri)
    path = project.models_dir / f"{name}{MODEL_SUFFIX}"
    if path.exists() and not args.force:
        raise _usage(f"{display_path(path)} already exists (use --force)", path)
    process = [f"  height: {args.height}"] if args.height else ["  scale: 1.0"]
    text = "\n".join([
        f"name: {name}",
        f"description: {json.dumps(args.description or f'imported from {src.name}')}",
        f"class: {args.cls}",
        "status: draft",
        f"style_version: {project.config.style_version}",
        "source:",
        f"  file: imports/{src.name}",
        f"  licence: {args.licence}",
        f"  author: {json.dumps(args.author or '')}",
        f"  url: {json.dumps(args.url or '')}",
        "process:",
        *process,
        "  recolor: auto           # snap colours to the project palette (keep = the file's own colours)",
        "",
    ])  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    out.say(f"imported {src.name} as {display_path(path)}; `kiln preview {name}` to check scale and colours")
    out.result({"model": display_path(path), "file": display_path(dest)})
    return 0


def cmd_credits(args: argparse.Namespace, out: Output) -> int:
    project = _require_project()
    rows = []
    for path in project.model_paths():
        model, _, _ = project.load(path)
        if model is not None and model.source is not None:
            rows.append({"model": model.name, "file": model.source.file.name, "licence": model.source.licence,
                         "author": model.source.author, "url": model.source.url})  # fmt: skip
            out.say(f"{model.name}: {model.source.file.name} by {model.source.author or '?'} ({model.source.licence}) {model.source.url}")
    if not rows:
        out.say("no imported models: everything was made in KILN")
    out.result({"credits": rows})
    return 0


def cmd_doctor(args: argparse.Namespace, out: Output) -> int:
    from kiln.godot import find_godot_binary

    godot = find_godot_binary()
    display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or sys.platform in ("win32", "darwin"))
    info = {"kiln": __version__, "python": sys.version.split()[0], "godot": godot, "display": display}
    out.say(f"kiln {__version__}, Python {info['python']}")
    out.say(f"Godot: {godot or 'not found (set GODOT=/path/to/godot for --verify-godot and --engine)'}")
    out.say(f"display: {'yes' if display else 'no (preview --engine needs one; the built-in renderer does not)'}")
    out.result(info)
    return 0


def cmd_skill(args: argparse.Namespace, out: Output) -> int:
    target = Path(args.target).resolve() if args.target else (find_project_root(Path.cwd()) or Path.cwd()) / ".claude" / "skills" / "kiln"
    target.mkdir(parents=True, exist_ok=True)
    source = files("kiln").joinpath("skill")
    names = []
    for item in source.iterdir():
        if item.name.endswith(".md"):
            (target / item.name).write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
            names.append(item.name)
    out.say(f"KILN skill installed in {display_path(target)}")
    out.result({"skill": display_path(target), "files": sorted(names)})
    return 0


def cmd_mcp(args: argparse.Namespace, out: Output) -> int:
    try:
        from kiln.mcp_server import serve
    except ImportError:
        raise _usage('the MCP server needs the optional extra: pip install "kiln[mcp]"') from None
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
    s.add_argument("--class", dest="cls")
    s.add_argument("--description")
    s.add_argument("--force", action="store_true")
    s = sub.add_parser("lint", parents=[common], help="check models (errors and warnings)")
    s.add_argument("paths", nargs="*")
    s.add_argument("--fast", action="store_true", help="skip geometric checks (no meshing)")
    s = sub.add_parser("build", parents=[common], help="build every model into the output dir")
    s.add_argument("--verify-godot", action="store_true", help="load everything in headless Godot afterwards")
    s = sub.add_parser("preview", parents=[common], help="preview sheets for one model (default: turntable)")
    s.add_argument("model")
    s.add_argument("--turntable", action="store_true")
    s.add_argument("--closeup", action="append", metavar="PART")
    s.add_argument("--pose", action="append", metavar="ANIMATION")
    s.add_argument("--vs", action="store_true", help="beside the style's inspiration images")
    s.add_argument("--detach", action="store_true", help="each separate part taken off: what's left, and what it covered")
    s.add_argument("--engine", action="store_true", help="render through Godot (needs a display and a build)")
    s.add_argument("--variant")
    s = sub.add_parser("lineup", parents=[common], help="models side by side at one scale")
    s.add_argument("models", nargs="*")
    sub.add_parser("gallery", parents=[common], help="every model in one sheet")
    sub.add_parser("status", parents=[common], help="every model: class, status, style, review flags")
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
    sub.add_parser("credits", parents=[common], help="authors and licences of imported models")
    sub.add_parser("doctor", parents=[common], help="versions, Godot, display")
    s = sub.add_parser("skill", parents=[common], help="install the Claude skill")
    s.add_argument("action", choices=["install"])
    s.add_argument("--target")
    s = sub.add_parser("mcp", parents=[common], help="run the MCP server (stdio)")
    s.add_argument("--project")
    s.add_argument("--allow-godot", action="store_true")
    return p


COMMANDS = {"init": cmd_init, "new": cmd_new, "lint": cmd_lint, "build": cmd_build, "preview": cmd_preview, "lineup": cmd_lineup,
            "gallery": cmd_gallery, "status": cmd_status, "mark": cmd_mark, "style": cmd_style, "config": cmd_config,
            "import": cmd_import, "credits": cmd_credits, "doctor": cmd_doctor, "skill": cmd_skill, "mcp": cmd_mcp}  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    out = Output(args.json)
    try:
        return COMMANDS[args.cmd](args, out)
    except PaganError as exc:
        out.failure(exc.findings)
        return 1


__all__ = ["main", "parser"]
