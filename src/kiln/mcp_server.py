"""`kiln mcp`: KILN as an MCP server, for agents without the Claude skill or a shell.

One server serves one KILN project. Tools return the same JSON as the matching CLI command with `--json` (they
run the CLI handlers with stdout captured), so the CLI, the skill and MCP share one contract. Errors are results
(`ok: false` + `findings`). Nothing reads or writes outside the project, its output dir and its preview dir.
Previews come back as images the model can look at.

Needs the optional extra: `pip install "kiln[mcp]"`.
"""

from __future__ import annotations

import io
import json
import os
import threading
from collections.abc import Callable
from contextlib import redirect_stdout
from datetime import date
from functools import wraps
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, ParamSpec, TypeVar

from mcp.server.mcpserver import Image, MCPServer
from mcp.types import ToolAnnotations
from PIL import Image as PILImage

from kiln import __version__
from kiln.notation import MODEL_SUFFIX, NAME_RE
from kiln.project import CONFIG_NAME, Project, find_project_root, load_project
from kiln.style import STYLE_SUFFIX
from kiln.vendor.findings import Finding, PaganError

MAX_SOURCE_BYTES = 2_000_000
MAX_IMAGE_SIDE = 1568
MAX_IMAGE_BYTES = 1_500_000
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
OVERWRITE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = """\
KILN turns text into smooth stylised 3D game models: parts (spheres, capsules, rounded boxes, ...) that blend like
clay, painted from a palette, rigged and animated, built into glTF and Godot scenes. Read the workflow first
(resource kiln://workflow; notation: kiln://reference). Call `status` and `read_docs` before making anything.
Loop: `scaffold` -> `write_model` (lints + shows a turntable) -> fix -> LOOK at `preview` images -> report.
Units are metres, +Y up, models face +Z and stand on y = 0. Colours come from the palette. `build` writes the game's
files; only after the owner approved.
"""

P = ParamSpec("P")
R = TypeVar("R")


def _failure(findings: list[Finding]) -> dict[str, Any]:
    return {"ok": False, "findings": [f.to_dict() for f in findings]}


def _error(message: str) -> PaganError:
    return PaganError([Finding("E000", message)])


def _results(fn: Callable[P, R]) -> Callable[P, R | dict[str, Any]]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except PaganError as exc:
            return _failure(exc.findings)

    return wrapper


def _check_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise _error(f"invalid name {name!r}: lowercase letters, digits, '_' or '-'")


def _check_text(text: str) -> None:
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise _error("source text is over 2 MB")


class Kiln:
    def __init__(self, root: Path, allow_godot: bool = False) -> None:
        self.root = root.resolve()
        self.allow_godot = allow_godot
        self._lock = threading.Lock()

    def project(self) -> Project:
        return load_project(self.root)

    def cli(self, *argv: str) -> dict[str, Any]:
        from kiln.cli import main

        buffer = io.StringIO()
        with self._lock:
            previous = os.getcwd()
            os.chdir(self.root)
            try:
                with redirect_stdout(buffer):
                    code = main(["--json", *argv])
            except SystemExit as exc:
                return _failure([Finding("E000", f"invalid arguments for `kiln {' '.join(argv)}` (exit {exc.code})")])
            finally:
                os.chdir(previous)
        text = buffer.getvalue().strip()
        try:
            data = json.loads(text) if text else {"ok": code == 0}
        except ValueError:
            data = {"ok": code == 0, "output": text}
        return data if isinstance(data, dict) else {"ok": code == 0, "result": data}

    def model_path(self, name: str) -> Path:
        _check_name(name)
        return self.root / "models" / f"{name}{MODEL_SUFFIX}"

    def inside(self, path: str) -> Path:
        project = self.project()
        resolved = (self.root / path).resolve()
        roots = [self.root, project.output_dir, project.preview_dir]
        if not any(resolved == r or resolved.is_relative_to(r) for r in roots):
            raise _error(f"{path} is outside the KILN project")
        return resolved


def _image(path: Path) -> Image | None:
    if not path.is_file():
        return None
    image: PILImage.Image = PILImage.open(path)
    image.load()
    longest = max(image.size)
    if longest > MAX_IMAGE_SIDE:
        f = MAX_IMAGE_SIDE / longest
        image = image.resize((max(1, round(image.width * f)), max(1, round(image.height * f))), PILImage.Resampling.LANCZOS)
    data = io.BytesIO()
    image.convert("RGB").save(data, format="PNG")
    if data.tell() > MAX_IMAGE_BYTES:
        image = image.convert("RGB")
        data = io.BytesIO()
        image.save(data, format="JPEG", quality=85)
        return Image(data=data.getvalue(), format="jpeg")
    return Image(data=data.getvalue(), format="png")


def _with_images(result: dict[str, Any], paths: list[Path]) -> list[Any]:
    images = [i for i in (_image(p) for p in paths) if i is not None]
    return [result, *images]


def _paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [p for v in value.values() for p in _paths(v)]
    return []


def create_server(root: Path, allow_godot: bool = False) -> MCPServer:
    kiln = Kiln(root, allow_godot)
    server = MCPServer(name="kiln", title="KILN", version=__version__, instructions=INSTRUCTIONS)

    @server.tool(annotations=READ)
    def status() -> dict[str, Any]:
        """Every model (class, status, style, needs-review flags, errors) and the project's style version. Call first."""
        return kiln.cli("status")

    @server.tool(annotations=READ)
    def read_docs() -> dict[str, Any]:
        """BRIEF.md (what the game needs, decisions) and STYLE.md (how models must look): the project's memory."""
        return {"ok": True, **{n: (kiln.root / n).read_text(encoding="utf-8") if (kiln.root / n).is_file() else None for n in ("BRIEF.md", "STYLE.md")}}

    @server.tool(annotations=OVERWRITE)
    @_results
    def write_doc(doc: Literal["BRIEF.md", "STYLE.md"], text: str) -> dict[str, Any]:
        """Replace BRIEF.md or STYLE.md (keep their sections; append to logs rather than rewriting history)."""
        _check_text(text)
        (kiln.root / doc).write_text(text, encoding="utf-8")
        return {"ok": True, "written": doc}

    @server.tool(annotations=WRITE)
    def log_feedback(note: str) -> dict[str, Any]:
        """Append a dated line to BRIEF.md's decisions log (what the owner asked for or decided)."""
        path = kiln.root / "BRIEF.md"
        text = path.read_text(encoding="utf-8") if path.is_file() else "# Art brief\n"
        path.write_text(text.rstrip("\n") + f"\n- {date.today().isoformat()}: {note}\n", encoding="utf-8")
        return {"ok": True}

    @server.tool(annotations=READ)
    def config_show() -> dict[str, Any]:
        """kiln.toml settings with their meanings."""
        return kiln.cli("config", "show")

    @server.tool(annotations=WRITE)
    def config_set(key: str, value: str) -> dict[str, Any]:
        """Set a kiln.toml setting (value in TOML syntax, e.g. '"toon"' or '["glb", "godot"]'); validated first."""
        return kiln.cli("config", "set", key, value)

    @server.tool(annotations=READ)
    def style_list() -> dict[str, Any]:
        """Built-in and project styles (soft_toy, low_poly, toon, clay, diorama, ...)."""
        return kiln.cli("style", "list")

    @server.tool(annotations=READ)
    @_results
    def style_show(name: str | None = None) -> dict[str, Any]:
        """A style's settings and notes (shapes, proportions, materials, look kit), plus its TOML text when it's a file."""
        result = kiln.cli("style", "show", *([name] if name else []))
        path = result.get("style", {}).get("path")
        if path and Path(path).is_file():
            result["text"] = Path(path).read_text(encoding="utf-8")
        return result

    @server.tool(annotations=OVERWRITE)
    @_results
    def style_write(name: str, text: str) -> dict[str, Any]:
        """Write styles/<name>.style.toml (usually `extends` a preset and overrides a few values; see kiln://reference)."""
        _check_name(name)
        _check_text(text)
        path = kiln.root / "styles" / f"{name}{STYLE_SUFFIX}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        result = kiln.cli("style", "show", name)
        return {**result, "written": path.relative_to(kiln.root).as_posix()}

    @server.tool(annotations=WRITE)
    def scaffold(name: str, template: Literal["bean", "prop", "empty"] = "empty", model_class: str | None = None, description: str = "") -> dict[str, Any]:
        """Create models/<name>.kiln.yaml from a template (bean = rigged character with walk/idle)."""
        argv = ["new", "model", name, "--template", template, "--description", description]
        if model_class:
            argv += ["--class", model_class]
        return kiln.cli(*argv)

    @server.tool(annotations=READ)
    @_results
    def read_model(name: str) -> dict[str, Any]:
        """The text of models/<name>.kiln.yaml."""
        path = kiln.model_path(name)
        if not path.is_file():
            raise _error(f"no model {name!r}; `status` lists them")
        return {"ok": True, "name": name, "text": path.read_text(encoding="utf-8")}

    @server.tool(annotations=OVERWRITE, structured_output=False)
    def write_model(name: str, text: str, preview: bool = True) -> list[Any]:
        """Write models/<name>.kiln.yaml, lint it and (if it's valid and preview is true) return its turntable to look at."""
        try:
            _check_text(text)
            path = kiln.model_path(name)
        except PaganError as exc:
            return [_failure(exc.findings)]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        result = kiln.cli("lint", str(path))
        if not result.get("ok") or not preview:
            return [result]
        shown = kiln.cli("preview", name)
        files_ = [kiln.root / p for p in _paths(shown.get("outputs", {}))]
        return _with_images({"lint": result, "preview": shown}, files_)

    @server.tool(annotations=READ)
    def lint(models: list[str] | None = None) -> dict[str, Any]:
        """Lint every model (or the named ones): errors and warnings with lines and fixes."""
        return kiln.cli("lint", *(models or []))

    @server.tool(annotations=READ, structured_output=False)
    def preview(
        model: str,
        which: Literal["turntable", "closeup", "pose", "vs", "engine"] = "turntable",
        part: str | None = None,
        animation: str | None = None,
        variant: str | None = None,
    ) -> list[Any]:
        """Render a preview sheet and return it as an image: turntable (8 sides x 3 heights), closeup on a part, an
        animation's frames (pose), the model beside the style's inspiration images (vs), or Godot's own render (engine)."""
        argv = ["preview", model]
        if which == "closeup":
            if not part:
                return [{"ok": False, "findings": [{"rule": "E000", "message": "closeup needs part"}]}]
            argv += ["--closeup", part]
        elif which == "pose":
            if not animation:
                return [{"ok": False, "findings": [{"rule": "E000", "message": "pose needs animation"}]}]
            argv += ["--pose", animation]
        elif which == "vs":
            argv += ["--vs"]
        elif which == "engine":
            if not kiln.allow_godot:
                return [{"ok": False, "findings": [{"rule": "E000", "message": "engine previews need the server started with --allow-godot"}]}]
            argv += ["--engine"]
        else:
            argv += ["--turntable"]
        if variant:
            argv += ["--variant", variant]
        result = kiln.cli(*argv)
        return _with_images(result, [kiln.root / p for p in _paths(result.get("outputs", {}))])

    @server.tool(annotations=READ, structured_output=False)
    def lineup(models: list[str] | None = None) -> list[Any]:
        """Models side by side at one scale with a 1 m bar: check sizes and that they belong together."""
        result = kiln.cli("lineup", *(models or []))
        return _with_images(result, [kiln.root / result["lineup"]] if result.get("lineup") else [])

    @server.tool(annotations=READ, structured_output=False)
    def gallery() -> list[Any]:
        """Every model in one sheet."""
        result = kiln.cli("gallery")
        return _with_images(result, [kiln.root / result["gallery"]] if result.get("gallery") else [])

    @server.tool(annotations=WRITE)
    def build(verify_godot: bool = False) -> dict[str, Any]:
        """Build every model into the output dir (glb, Godot scenes, look kits, manifest). verify_godot loads it all in
        headless Godot (server needs --allow-godot)."""
        if verify_godot and not kiln.allow_godot:
            return {"ok": False, "findings": [{"rule": "E000", "message": "verify_godot needs the server started with --allow-godot"}]}
        return kiln.cli("build", *(["--verify-godot"] if verify_godot else []))

    @server.tool(annotations=WRITE)
    def mark(models: list[str], approved: bool | None = None, current: bool = False) -> dict[str, Any]:
        """Set status (approved: true/false = draft) and/or style_version to the project's (current)."""
        argv = ["mark", *models]
        if approved is not None:
            argv.append("--approved" if approved else "--draft")
        if current:
            argv.append("--current")
        return kiln.cli(*argv)

    @server.tool(annotations=WRITE)
    def style_bump(note: str) -> dict[str, Any]:
        """Raise the project's style_version (logged in STYLE.md); older models get flagged for review."""
        return kiln.cli("style", "bump", "--message", note)

    @server.tool(annotations=WRITE)
    @_results
    def import_model(file: str, licence: str, name: str | None = None, author: str = "", url: str = "", height: float | None = None,
                     model_class: str = "prop") -> dict[str, Any]:  # fmt: skip
        """Import a .glb/.gltf already inside the project (e.g. a CC0 pack item in imports/) as a model, with its licence."""
        path = kiln.inside(file)
        argv = ["import", str(path), "--licence", licence, "--class", model_class]
        for flag, value in (("--name", name), ("--author", author), ("--url", url)):
            if value:
                argv += [flag, value]
        if height:
            argv += ["--height", str(height)]
        return kiln.cli(*argv)

    @server.resource("kiln://workflow", mime_type="text/markdown", description="How to make and maintain models with KILN")
    def workflow() -> str:
        return files("kiln").joinpath("skill", "SKILL.md").read_text(encoding="utf-8")

    @server.resource("kiln://reference", mime_type="text/markdown", description="The KILN notation, every field")
    def reference() -> str:
        return files("kiln").joinpath("skill", "reference.md").read_text(encoding="utf-8")

    @server.prompt(description="Make a new 3D model")
    def make_model(request: str) -> str:
        return (
            f"Make this model: {request}\nFollow kiln://workflow: read_docs, status, style_show; plan the parts on paper (sizes in "
            "metres); scaffold; write_model; LOOK at the turntable and fix proportions; closeup the face/hit zones; lineup with "
            "existing models; then report and ask the owner to approve."
        )

    @server.prompt(description="Change the look of the whole game")
    def change_the_look(request: str) -> str:
        return (
            f"Change the look: {request}\nPrefer editing the style (style_show, style_write: look kit, materials, shape) and the "
            "palette, which change every model at once. If models must change, style_bump and go through the flagged ones. "
            "Check with gallery and lineup, then log_feedback."
        )

    @server.prompt(description="Review a model against the style")
    def review_model(name: str) -> str:
        return (
            f"Review {name}: read_model, lint, preview (turntable, closeups, poses, vs), lineup with approved models, and compare "
            "with STYLE.md. List concrete problems (proportions, scale, colours, materials, floating parts) and fix them if asked."
        )

    return server


def serve(project: Path, allow_godot: bool = False) -> int:
    root = find_project_root(project)
    if root is None:
        raise _error(f"no {CONFIG_NAME} at or above {project}; run `kiln init` first or pass --project")
    create_server(root, allow_godot).run("stdio")
    return 0


__all__ = ["Kiln", "create_server", "serve"]
