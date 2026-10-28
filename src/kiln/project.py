"""`kiln.toml`, project discovery and loading (palettes, styles, models)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from kiln.atlas import AO_STRENGTH
from kiln.notation import MODEL_SUFFIX, NAME_RE, Model, load_model
from kiln.style import Style, load_style
from kiln.vendor.findings import Finding, PaganError
from kiln.vendor.palette import PALETTE_SUFFIX, load_palette_file

CONFIG_NAME = "kiln.toml"
EXPORTS = ("glb", "godot")


@dataclass
class Config:
    default_style: str = "soft_toy"
    default_palette: str | None = None
    output_dir: str = "build"
    preview_dir: str = "previews"
    export: tuple[str, ...] = ("glb",)
    style_version: int = 1
    lint_disable: tuple[str, ...] = ()
    merge_rigid: bool = False  # true: a rigid skin is one skinned mesh (each vertex 100% on its part's bone)
    variant_glbs: bool = True  # false: variants are Godot scenes recolouring the base glb (no glb per variant)
    vertex_colors: bool = False  # true: colours in the vertices, one surface per material preset (fewer draw calls)
    atlas: bool = False  # true: one material per model, colours and presets from small palette textures
    atlas_ao: float = 0.0  # with atlas: strength of the ambient occlusion baked into the vertex colours (0 = none)
    godot_bonemap: bool = False  # true: humanoids get a Godot BoneMap in their glb's .import (bones take the profile's names)


@dataclass
class Project:
    root: Path
    config: Config
    config_path: Path | None
    _styles: dict[str, tuple[Style | None, list[Finding]]] = field(default_factory=dict)
    _palettes: dict[str, tuple[dict[str, str], list[Finding]]] = field(default_factory=dict)

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def styles_dir(self) -> Path:
        return self.root / "styles"

    @property
    def palettes_dir(self) -> Path:
        return self.root / "palettes"

    @property
    def output_dir(self) -> Path:
        return (self.root / self.config.output_dir).resolve()

    @property
    def preview_dir(self) -> Path:
        return (self.root / self.config.preview_dir).resolve()

    def style(self, name: str | None = None) -> tuple[Style | None, list[Finding]]:
        key = name or self.config.default_style
        if key not in self._styles:
            self._styles[key] = load_style(key, self.styles_dir if self.styles_dir.is_dir() else None)
        return self._styles[key]

    def palette(self, name: str | None = None) -> tuple[dict[str, str], list[Finding]]:
        """Colour lookup (names and keys -> hex) for a PAGAN palette file; empty when the project has none."""
        key = name or self.config.default_palette
        if key is None:
            return {}, []
        if key not in self._palettes:
            path = self.palettes_dir / f"{key}{PALETTE_SUFFIX}"
            if not path.is_file():  # KILN's library palettes (its templates' colours)
                from kiln.notation import library_dir

                lib = library_dir() / f"{key}{PALETTE_SUFFIX}"
                path = lib if lib.is_file() else path
            if not path.is_file():
                self._palettes[key] = ({}, [Finding("E004", f"palette {key!r} not found ({path.name} in palettes/)", self.config_path)])
            else:
                try:
                    pal = load_palette_file(path)
                    lookup: dict[str, str] = {}
                    for c in pal.colors.values():
                        lookup[c.key] = c.hex
                        if c.name:
                            lookup[c.name] = c.hex
                    self._palettes[key] = (lookup, [])
                except PaganError as exc:
                    self._palettes[key] = ({}, list(exc.findings))
        return self._palettes[key]

    def model_paths(self) -> list[Path]:
        return sorted(self.models_dir.glob(f"*{MODEL_SUFFIX}")) if self.models_dir.is_dir() else []

    def load(self, path: Path) -> tuple[Model | None, Style | None, list[Finding]]:
        """Parse one model with its style and palette (the model may name its own)."""
        findings: list[Finding] = []
        style_name, palette_name = _peek(path)
        style, sf = self.style(style_name)
        palette, pf = self.palette(palette_name)
        findings += [Finding(f.rule, f.message, f.path or path, f.line, f.where) for f in sf]
        findings += [Finding(f.rule, f.message, f.path or path, f.line, f.where) for f in pf]
        if style is None:
            return None, None, findings
        model, mf = load_model(path, palette, set(style.materials))
        if model is not None and model.animation_library is not None:
            mf += self._library(model)
        return model, style, findings + mf

    def _library(self, model: Model) -> list[Finding]:
        """Copy a model's animation_library's animations into it (a carrier: animations_only). Every part id the clips
        move must be in the model; other ids may differ (a helmet on one loadout, a shield on another): the model's
        extra parts follow their parents, and tracks of carrier parts the model lacks aren't copied."""
        name = model.animation_library
        lib_path = self.models_dir / f"{name}{MODEL_SUFFIX}"

        def bad(message: str) -> list[Finding]:
            return [Finding("E008", message, model.path, None, "animation_library")]

        if not lib_path.is_file():
            return bad(f"animation_library {name!r}: no such model in models/")
        lib, _, found = self.load(lib_path)
        if lib is None or any(f.severity == "error" for f in found):
            return bad(f"animation_library {name!r} has errors: fix it first")
        if not lib.animations_only:
            return bad(f"animation_library {name!r} isn't a clip carrier: give it animations_only: true")
        if lib.skeleton != model.skeleton:
            return bad(f"animation_library {name!r} has another skeleton ({lib.skeleton or 'none'}, here {model.skeleton or 'none'}): give both the same")
        driven: set[str] = set()
        for anim in lib.animations.values():
            if anim.cycle is not None or anim.source is not None:
                driven |= set(lib.ids)  # procedural / imported clips: any carrier id may move
            for pose in anim.poses:
                driven |= set(pose)
        missing = sorted(driven - set(model.ids))
        if missing:
            return bad(f"animation_library {name!r} moves part ids this model doesn't have ({', '.join(missing)}): a clip moves bones "
                       "by id, so add them, or leave them out of the carrier's clips (ids nothing animates may differ)")  # fmt: skip
        mine = set(model.ids)
        model.animations = {k: replace(a, poses=[{i: p for i, p in pose.items() if i in mine} for pose in a.poses]) for k, a in lib.animations.items()}
        model.library_text = lib.text
        return []


def _peek(path: Path, depth: int = 0) -> tuple[str | None, str | None]:
    """The model's own `style:` and `palette:` (read before parsing, since parsing needs both), else its base's."""
    style = palette = base = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.split(":", 1)[1].split("#")[0].strip().strip("'\"") or None if ":" in line else None
            if line.startswith("style:"):
                style = value
            elif line.startswith("palette:"):
                palette = value
            elif line.startswith("extends:"):
                base = value
    except (OSError, UnicodeDecodeError):
        pass
    if base and depth < 8 and (style is None or palette is None):
        from kiln.notation import base_path

        for name in [n.strip().strip("'\"") for n in base.strip("[]").split(",")] if base.startswith("[") else [base]:
            base_style, base_palette = _peek(base_path(path.parent, name), depth + 1)
            style, palette = style or base_style, palette or base_palette
    return style, palette


def parse_config(data: dict[str, Any], path: Path | None) -> tuple[Config, list[Finding]]:
    findings: list[Finding] = []
    cfg = Config()

    def bad(message: str, where: str) -> None:
        findings.append(Finding("E000", message, path, None, where))

    allowed = {"default_style", "default_palette", "output_dir", "preview_dir", "export", "style_version", "variant_glbs", "vertex_colors",
               "atlas", "atlas_ao", "merge_rigid", "godot_bonemap", "lint"}  # fmt: skip
    for key in data:
        if key not in allowed:
            bad(f"unknown setting {key!r}; allowed: {', '.join(sorted(allowed))}", key)
    if "default_style" in data:
        if not isinstance(data["default_style"], str) or not NAME_RE.match(data["default_style"]):
            bad("default_style is a style name (kiln style list)", "default_style")
        else:
            cfg.default_style = data["default_style"]
    if "default_palette" in data:
        if not isinstance(data["default_palette"], str) or not NAME_RE.match(data["default_palette"]):
            bad("default_palette is a palette name (palettes/<name>.pal.yaml, PAGAN's format)", "default_palette")
        else:
            cfg.default_palette = data["default_palette"]
    for key in ("output_dir", "preview_dir"):
        if key in data:
            if not isinstance(data[key], str) or not data[key]:
                bad(f"{key} is a folder path (relative to the project)", key)
            else:
                setattr(cfg, key, data[key])
    if "export" in data:
        ex = data["export"]
        if not isinstance(ex, list) or not ex or any(e not in EXPORTS for e in ex):
            bad(f"export is a list of: {', '.join(EXPORTS)}", "export")
        else:
            cfg.export = tuple(ex)
    if "style_version" in data:
        sv = data["style_version"]
        if not isinstance(sv, int) or isinstance(sv, bool) or sv < 1:
            bad("style_version is a whole number >= 1", "style_version")
        else:
            cfg.style_version = sv
    if "merge_rigid" in data:
        if not isinstance(data["merge_rigid"], bool):
            bad("merge_rigid is true (a rigid skin is one skinned mesh: one draw call) or false (a mesh per part)", "merge_rigid")
        else:
            cfg.merge_rigid = data["merge_rigid"]
    if "godot_bonemap" in data:
        if not isinstance(data["godot_bonemap"], bool):
            bad("godot_bonemap is true (Godot renames humanoids' bones to SkeletonProfileHumanoid's via a BoneMap) or false", "godot_bonemap")
        else:
            cfg.godot_bonemap = data["godot_bonemap"]
    if "variant_glbs" in data:
        if not isinstance(data["variant_glbs"], bool):
            bad("variant_glbs is true (a .glb per variant) or false (variants recolour the base glb's materials)", "variant_glbs")
        else:
            cfg.variant_glbs = data["variant_glbs"]
    if "vertex_colors" in data:
        if not isinstance(data["vertex_colors"], bool):
            bad("vertex_colors is true (colours in the vertices: fewer surfaces) or false (a material per colour)", "vertex_colors")
        else:
            cfg.vertex_colors = data["vertex_colors"]
    if "atlas" in data:
        if not isinstance(data["atlas"], bool):
            bad("atlas is true (one material per model from palette textures) or false (a material per colour)", "atlas")
        else:
            cfg.atlas = data["atlas"]
    if "atlas_ao" in data:
        ao = data["atlas_ao"]
        if isinstance(ao, bool):
            cfg.atlas_ao = AO_STRENGTH if ao else 0.0
        elif isinstance(ao, (int, float)) and 0 <= ao <= 1:
            cfg.atlas_ao = float(ao)
        else:
            bad(f"atlas_ao is true (bake ambient occlusion into the vertex colours; needs atlas = true), false, or its strength "
                f"0..1 (the darkest corner's colour is x (1 - strength); true = {AO_STRENGTH})", "atlas_ao")
    if cfg.atlas and cfg.vertex_colors:
        bad("atlas and vertex_colors are two ways to cut draw calls: set one (atlas = true gives one surface per model)", "atlas")
    if cfg.atlas_ao and not cfg.atlas:
        bad("atlas_ao needs atlas = true", "atlas_ao")
    lint = data.get("lint", {})
    if not isinstance(lint, dict) or any(k != "disable" for k in lint) or not all(isinstance(r, str) and r.startswith("W") for r in lint.get("disable", [])):
        bad("[lint] has disable = [\"W101\", ...] (warnings only)", "lint")
    else:
        cfg.lint_disable = tuple(lint.get("disable", []))
    return cfg, findings


def find_project_root(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for folder in (current, *current.parents):
        if (folder / CONFIG_NAME).is_file():
            return folder
    return None


def load_project(root: Path | None = None, start: Path | None = None) -> Project:
    """The project at `root`, or found from `start` (default: cwd). Without kiln.toml: open mode at the start
    folder with default settings (single files still lint and build)."""
    if root is None:
        found = find_project_root(start or Path.cwd())
        if found is None:
            base = (start or Path.cwd()).resolve()
            base = base.parent if base.is_file() else base
            if base.name == "models":
                base = base.parent
            return Project(base, Config(), None)
        root = found
    path = root / CONFIG_NAME
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PaganError([Finding("E000", f"cannot read {CONFIG_NAME}: {exc.strerror}", path)]) from None
    except tomllib.TOMLDecodeError as exc:
        raise PaganError([Finding("E000", f"invalid TOML: {exc}", path)]) from None
    cfg, findings = parse_config(data, path)
    if findings:
        raise PaganError(findings)
    return Project(root.resolve(), cfg, path)
