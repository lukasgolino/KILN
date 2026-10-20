"""`kiln.toml`, project discovery and loading (palettes, styles, models)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kiln.notation import MODEL_SUFFIX, NAME_RE, Model, load_model
from kiln.style import Style, load_style
from pagan.findings import Finding, PaganError
from pagan.palette import PALETTE_SUFFIX, load_palette_file

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
        return model, style, findings + mf


def _peek(path: Path) -> tuple[str | None, str | None]:
    """The model's own `style:` and `palette:` (read before parsing, since parsing needs both)."""
    style = palette = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("style:"):
                style = line.split(":", 1)[1].split("#")[0].strip().strip("'\"") or None
            elif line.startswith("palette:"):
                palette = line.split(":", 1)[1].split("#")[0].strip().strip("'\"") or None
    except (OSError, UnicodeDecodeError):
        pass
    return style, palette


def parse_config(data: dict[str, Any], path: Path | None) -> tuple[Config, list[Finding]]:
    findings: list[Finding] = []
    cfg = Config()

    def bad(message: str, where: str) -> None:
        findings.append(Finding("E000", message, path, None, where))

    allowed = {"default_style", "default_palette", "output_dir", "preview_dir", "export", "style_version", "lint"}
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
