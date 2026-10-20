"""Palettes: the colors a sprite may use, keyed by single characters, grouped into shading ramps.

A key is any one Unicode letter or digit, so a palette isn't limited to 0-9a-zA-Z. KEY_ORDER is the
recommended order to take keys in: ASCII first, then letters that don't look like ASCII ones.
"""

from __future__ import annotations

import re
import string
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kiln.vendor.findings import Finding, PaganError, has_errors
from kiln.vendor.yamlio import LineMap, YamlError, load_yaml

TRANSPARENT = "."
# Latin-1 letters, then Greek letters that can't be mistaken for Latin ones (no Α/A, ο/o, ...).
_LATIN1 = "àáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿßÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞ"
_GREEK = "αβγδεζηθλμξπρσςτφχψωΓΔΘΛΞΠΣΦΨΩ"
KEY_ORDER = string.digits + string.ascii_lowercase + string.ascii_uppercase + _LATIN1 + _GREEK
KEY_HELP = "one letter or digit: 0-9, a-z, A-Z, then any other single Unicode letter (à-ÿ, À-Þ, ß, α-ω, Γ, Δ, ...)"


def is_key(text: str) -> bool:
    """A valid palette key: one Unicode letter or digit (never "." or whitespace)."""
    return len(text) == 1 and text.isalnum()
PALETTE_SUFFIX = ".pal.yaml"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_FIELDS = ("name", "description", "colors", "ramps", "variants", "base_variant")
_VARIANT_FIELDS = ("ramp_swap", "key_swap", "tags")
_COLOR_FIELDS = ("hex", "name")

# error(rule, message, line, where)
ErrorFn = Callable[[str, str, int | None, str | None], None]


@dataclass(frozen=True)
class Color:
    key: str
    hex: str  # normalized lowercase "#rrggbb"
    name: str | None = None

    @property
    def rgb(self) -> tuple[int, int, int]:
        return (int(self.hex[1:3], 16), int(self.hex[3:5], 16), int(self.hex[5:7], 16))


@dataclass(frozen=True)
class PaletteVariant:
    """A recolour every asset using the palette gets (or only assets with one of `tags`)."""

    name: str
    ramp_swap: dict[str, str]
    key_swap: dict[str, str]
    tags: tuple[str, ...] = ()  # empty = every asset

    def applies_to(self, asset_tags: tuple[str, ...]) -> bool:
        return not self.tags or any(t in asset_tags for t in self.tags)

    def spec(self) -> dict[str, Any]:
        """The same recolour as an asset's own `variants:` entry."""
        return {"ramp_swap": dict(self.ramp_swap), "key_swap": dict(self.key_swap)}


@dataclass(frozen=True)
class Palette:
    name: str | None  # None for an unnamed inline palette
    colors: dict[str, Color]  # in source order
    ramps: dict[str, tuple[str, ...]]  # shadow -> highlight
    path: Path | None = None
    variants: dict[str, PaletteVariant] = field(default_factory=dict)  # palette-wide recolours, by name
    base_variant: str | None = None  # what the base colours are called on assets that get palette variants


def _line(data: Any, key: Any = None) -> int | None:
    if isinstance(data, LineMap):
        return data.line_of(key) if key is not None else data.line
    return None


def _normalize_key(raw: Any) -> str | None:
    """YAML reads an unquoted 5 as an int; accept digits 0-9 as keys anyway."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and 0 <= raw <= 9:
        return str(raw)
    if isinstance(raw, str):
        return raw
    return None


def parse_palette(
    data: Any, path: Path | None = None, *, expected_name: str | None = None, inline: bool = False
) -> tuple[Palette | None, list[Finding]]:
    """Validate palette data (a palette file's content, or a sprite's inline palette).

    Returns the palette (None if there were errors) and all findings.
    """
    findings: list[Finding] = []

    def error(rule: str, message: str, line: int | None, where: str | None = None) -> None:
        findings.append(Finding(rule, message, path, line, where))

    if not isinstance(data, dict):
        error("E001", "palette must be a mapping with a 'colors' section", _line(data))
        return None, findings

    for field in data:
        if field not in _FIELDS:
            error("E001", f"unknown field {field!r}; allowed fields: {', '.join(_FIELDS)}", _line(data, field))

    name = data.get("name")
    if name is None and not inline:
        error("E001", "missing required field 'name'", _line(data))
    elif name is not None:
        if not isinstance(name, str) or not NAME_RE.match(name):
            error("E001", "name must be lowercase letters, digits, '_' or '-'", _line(data, "name"), "name")
        elif expected_name is not None and name != expected_name:
            error(
                "E005",
                f"name {name!r} doesn't match the file name; expected {expected_name!r}",
                _line(data, "name"),
                "name",
            )

    colors: dict[str, Color] = {}
    raw_colors = data.get("colors")
    if raw_colors is None:
        error("E001", "missing required field 'colors'", _line(data))
    elif not isinstance(raw_colors, dict) or not raw_colors:
        error("E001", "'colors' must be a non-empty mapping of key -> color", _line(data, "colors"), "colors")
    else:
        for raw_key, raw_value in raw_colors.items():
            line = _line(raw_colors, raw_key)
            key = _normalize_key(raw_key)
            where = f"colors.{key if key is not None else raw_key}"
            if key == TRANSPARENT:
                error("E005", "'.' is reserved for transparent and can't be a palette color", line, where)
                continue
            if key is None or not is_key(key):
                error("E005", f"color key {raw_key!r} must be {KEY_HELP}", line, where)
                continue
            if key in colors:
                error("E005", f"duplicate color key {key!r}", line, where)
                continue
            color = _parse_color(key, raw_value, line, where, error)
            if color is not None:
                colors[key] = color

    # Keys written in the colors section, valid or not; invalid ones were already reported above.
    declared = {k for k in map(_normalize_key, raw_colors)} if isinstance(raw_colors, dict) else set()
    ramps: dict[str, tuple[str, ...]] = {}
    raw_ramps = data.get("ramps")
    if raw_ramps is not None:
        if not isinstance(raw_ramps, dict):
            error("E005", "'ramps' must be a mapping of ramp name -> list of color keys", _line(data, "ramps"), "ramps")
        else:
            for ramp_name, entries in raw_ramps.items():
                line = _line(raw_ramps, ramp_name)
                where = f"ramps.{ramp_name}"
                if not isinstance(ramp_name, str):
                    error("E005", f"ramp name {ramp_name!r} must be text", line, where)
                    continue
                if not isinstance(entries, list) or not entries:
                    error("E005", "a ramp must be a non-empty list of color keys, shadow -> highlight", line, where)
                    continue
                keys: list[str] = []
                for entry in entries:
                    key = _normalize_key(entry)
                    if key is None or key not in colors:
                        if key is None or key not in declared:
                            error("E005", f"ramp uses unknown color key {entry!r}", line, where)
                        continue
                    if key in keys:
                        error("E005", f"color key {key!r} appears twice in the ramp", line, where)
                        continue
                    keys.append(key)
                ramps[ramp_name] = tuple(keys)

    variants = _parse_palette_variants(data.get("variants"), _line(data, "variants"), colors, ramps, error)
    base_variant = data.get("base_variant")
    bline = _line(data, "base_variant")
    if base_variant is not None:
        if not isinstance(base_variant, str) or not NAME_RE.match(base_variant):
            error("E006", "base_variant must be a variant name (lowercase letters, digits, '_' or '-')", bline, "base_variant")
        elif base_variant in variants:
            error("E006", f"base_variant {base_variant!r} is also a variant's name; rename one", bline, "base_variant")
        elif "variants" not in data:
            error("E006", "base_variant names the base colours among the palette's variants; add variants or remove it", bline, "base_variant")
    if inline and ("variants" in data or base_variant is not None):
        error("E006", "inline palettes can't have variants; use the asset's own variants", _line(data, "variants") or bline, "variants")

    if has_errors(findings):
        return None, findings
    return Palette(name=name, colors=colors, ramps=ramps, path=path, variants=variants, base_variant=base_variant), findings


def _parse_palette_variants(
    raw: Any, line: int | None, colors: dict[str, Color], ramps: dict[str, tuple[str, ...]], error: ErrorFn
) -> dict[str, PaletteVariant]:
    """`variants: { arctic: { ramp_swap: { grass: snow }, key_swap: { "5": "ε" }, tags: [world] } }`.

    Recolours within this palette that every asset using it gets (only those with one of `tags`, if given),
    so one palette pass reaches a whole set of assets. An asset's own variant of the same name wins.
    """
    variants: dict[str, PaletteVariant] = {}
    if raw is None:
        return variants
    if not isinstance(raw, dict) or not raw:
        error("E006", "variants must map a variant name to { ramp_swap, key_swap, tags }", line, "variants")
        return variants
    for name, spec in raw.items():
        vline = _line(raw, name) or line
        where = f"variants.{name}"
        if not isinstance(name, str) or not NAME_RE.match(name):
            error("E006", "variant name must be lowercase letters, digits, '_' or '-'", vline, where)
            continue
        if not isinstance(spec, dict):
            error("E006", "a palette variant is { ramp_swap: {...}, key_swap: {...}, tags: [...] }", vline, where)
            continue
        ok = True
        for key in spec:
            if key not in _VARIANT_FIELDS:
                hint = " (a palette variant recolours within this palette)" if key == "palette" else ""
                error("E006", f"unknown palette variant field {key!r}; allowed: {', '.join(_VARIANT_FIELDS)}{hint}", vline, where)
                ok = False
        if ok and not ("ramp_swap" in spec or "key_swap" in spec):
            error("E006", "a palette variant needs ramp_swap and/or key_swap (and optionally tags)", vline, where)
            continue
        ramp_swap: dict[str, str] = {}
        raw_ramps = spec.get("ramp_swap", {})
        if not isinstance(raw_ramps, dict):
            error("E006", "ramp_swap must map ramp -> ramp, e.g. { grass: snow }", vline, f"{where}.ramp_swap")
            ok = False
            raw_ramps = {}
        for src, dst in raw_ramps.items():
            unknown = [r for r in (src, dst) if not isinstance(r, str) or r not in ramps]
            if unknown:
                error("E006", f"ramp_swap: unknown ramp {unknown[0]!r}", vline, f"{where}.ramp_swap")
                ok = False
            elif len(ramps[src]) != len(ramps[dst]):
                error(
                    "E006",
                    f"ramp_swap: {src!r} has {len(ramps[src])} colors but {dst!r} has {len(ramps[dst])}; "
                    "ramps must be the same length",
                    vline,
                    f"{where}.ramp_swap",
                )
                ok = False
            else:
                ramp_swap[src] = dst
        key_swap: dict[str, str] = {}
        raw_keys = spec.get("key_swap", {})
        if not isinstance(raw_keys, dict):
            error("E006", 'key_swap must map key -> key, e.g. { "5": "a" }', vline, f"{where}.key_swap")
            ok = False
            raw_keys = {}
        for src, dst in raw_keys.items():
            src_key, dst_key = _normalize_key(src), _normalize_key(dst)
            if src_key is None or dst_key is None or src_key not in colors or dst_key not in colors:
                bad = src if src_key is None or src_key not in colors else dst
                error("E006", f"key_swap: unknown key {bad!r}", vline, f"{where}.key_swap")
                ok = False
            else:
                key_swap[src_key] = dst_key
        tags = spec.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            error("E006", "tags must be a list of asset tags, e.g. [world]", vline, f"{where}.tags")
            ok = False
            tags = []
        if ok:
            variants[name] = PaletteVariant(name, ramp_swap, key_swap, tuple(tags))
    return variants


def _parse_color(key: str, raw: Any, line: int | None, where: str, error: ErrorFn) -> Color | None:
    color_name: Any = None
    if isinstance(raw, str):
        hex_value: Any = raw
    elif isinstance(raw, dict):
        for field in raw:
            if field not in _COLOR_FIELDS:
                error("E001", f"unknown color field {field!r}; allowed: hex, name", line, where)
        hex_value = raw.get("hex")
        color_name = raw.get("name")
    elif raw is None:
        error(
            "E005",
            'color is empty. If you wrote an unquoted hex like #aabbcc, YAML treats "#" as a comment; '
            'quote it: "#aabbcc"',
            line,
            where,
        )
        return None
    else:
        error("E005", 'color must be "#rrggbb" or { hex: "#rrggbb", name: ... }', line, where)
        return None

    if hex_value is None:
        error(
            "E005",
            'missing hex. If you wrote hex: #aabbcc without quotes, YAML treats "#" as a comment; '
            'write hex: "#aabbcc"',
            line,
            f"{where}.hex",
        )
        return None
    if not isinstance(hex_value, str) or not _HEX_RE.match(hex_value):
        error("E005", f'bad hex {hex_value!r}; expected "#rrggbb"', line, f"{where}.hex")
        return None
    if color_name is not None and not isinstance(color_name, str):
        error("E005", "color name must be text", line, f"{where}.name")
        return None
    return Color(key=key, hex=hex_value.lower(), name=color_name)


def palette_name_from_path(path: Path) -> str | None:
    if path.name.endswith(PALETTE_SUFFIX):
        return path.name[: -len(PALETTE_SUFFIX)]
    return None


def load_palette_file(path: Path) -> Palette:
    """Load and validate a palette file. Raises PaganError with findings on any error."""
    try:
        data = load_yaml(path)
    except YamlError as exc:
        raise PaganError([Finding("E001", exc.message, path, exc.line)]) from None
    palette, findings = parse_palette(data, path, expected_name=palette_name_from_path(path))
    if palette is None:
        raise PaganError(findings)
    return palette
