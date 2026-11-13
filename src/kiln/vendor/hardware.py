"""Hardware palettes: the colours a real machine could show, and how many at once.

A palette with `hardware: cga | atari-st | atari-st-mono` is checked against that machine (E004 in KILN; PAGAN lint also warns about CGA sets, W015), so art made
with it (2D sprites, or a 3D game's retro post pass in KILN) could have been drawn on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from kiln.vendor.color import distance, hex_to_rgb, rgb_to_oklab

# The 16 RGBI colours of a CGA card (dark yellow is the monitor's brown).
CGA_COLORS = (
    "#000000", "#0000aa", "#00aa00", "#00aaaa", "#aa0000", "#aa00aa", "#aa5500", "#aaaaaa",
    "#555555", "#5555ff", "#55ff55", "#55ffff", "#ff5555", "#ff55ff", "#ffff55", "#ffffff",
)
# 320x200 4-colour modes: a free background colour plus one of these fixed sets of three.
CGA_SETS: dict[str, tuple[str, str, str]] = {
    "palette 0 low (green/red/brown)": ("#00aa00", "#aa0000", "#aa5500"),
    "palette 0 high (green/red/yellow)": ("#55ff55", "#ff5555", "#ffff55"),
    "palette 1 low (cyan/magenta/grey)": ("#00aaaa", "#aa00aa", "#aaaaaa"),
    "palette 1 high (cyan/magenta/white)": ("#55ffff", "#ff55ff", "#ffffff"),
    "mode 5 low (cyan/red/grey)": ("#00aaaa", "#aa0000", "#aaaaaa"),
    "mode 5 high (cyan/red/white)": ("#55ffff", "#ff5555", "#ffffff"),
}
# Atari ST: 3 bits per channel (512 colours), shown as round(n * 255 / 7).
ST_LEVELS = tuple(round(n * 255 / 7) for n in range(8))


def _st_colors() -> tuple[str, ...]:
    return tuple(f"#{r:02x}{g:02x}{b:02x}" for r in ST_LEVELS for g in ST_LEVELS for b in ST_LEVELS)


@dataclass(frozen=True)
class Hardware:
    name: str
    description: str
    colors: tuple[str, ...]  # every colour the machine can show, lowercase "#rrggbb"
    max_colors: int  # how many at once
    starter: tuple[tuple[str, str], ...]  # (hex, name) for `pagan new palette --hardware`
    starter_ramps: tuple[tuple[str, tuple[int, ...]], ...]  # (ramp name, indices into starter)

    def can_show(self, hex_value: str) -> bool:
        return hex_value.lower() in self._set

    @cached_property
    def _set(self) -> frozenset[str]:
        return frozenset(self.colors)

    @cached_property
    def _labs(self) -> list[tuple[float, float, float]]:
        return [rgb_to_oklab(hex_to_rgb(c)) for c in self.colors]

    def nearest(self, hex_value: str) -> str:
        """The colour this machine can show that looks closest (Oklab distance; the first of equals)."""
        lab = rgb_to_oklab(hex_to_rgb(hex_value[:7]))
        best = min(range(len(self.colors)), key=lambda i: distance(lab, self._labs[i]))
        return self.colors[best]


HARDWARE: dict[str, Hardware] = {
    "cga": Hardware(
        "cga",
        "IBM CGA, 320x200: 4 colours from the 16 RGBI colours (a background + one fixed set of three)",
        CGA_COLORS,
        4,
        (("#000000", "black"), ("#55ffff", "cyan"), ("#ff55ff", "magenta"), ("#ffffff", "white")),
        (("cyan", (0, 1, 3)), ("magenta", (0, 2, 3))),
    ),
    "atari-st": Hardware(
        "atari-st",
        "Atari ST, 320x200: 16 colours from 512 (3 bits per channel)",
        _st_colors(),
        16,
        (
            ("#000000", "black"), ("#242449", "night"), ("#49496d", "slate"), ("#9292b6", "mist"),
            ("#ffffff", "white"), ("#492400", "earth"), ("#924900", "rust"), ("#db9249", "sand"),
            ("#ffdbb6", "skin"), ("#004900", "pine"), ("#249224", "grass"), ("#92db49", "leaf"),
            ("#002492", "sea"), ("#2492db", "sky"), ("#920000", "blood"), ("#ffdb00", "gold"),
        ),
        (
            ("grey", (0, 1, 2, 3, 4)), ("warm", (5, 6, 7, 8)), ("green", (9, 10, 11)), ("blue", (12, 13)),
        ),
    ),
    "atari-st-mono": Hardware(
        "atari-st-mono",
        "Atari ST high resolution, 640x400: black and white",
        ("#000000", "#ffffff"),
        2,
        (("#000000", "black"), ("#ffffff", "white")),
        (("mono", (0, 1)),),
    ),
}
HARDWARE_HELP = ", ".join(HARDWARE)


def cga_set(hexes: list[str]) -> str | None:
    """The CGA mode these colours fit: 640x200 (black + any one colour), or 320x200 (a background + a fixed set of
    three); None if neither."""
    unique = list(dict.fromkeys(h.lower() for h in hexes))
    if len(unique) <= 2 and "#000000" in unique:
        return "640x200 (black + one colour)"
    for label, fixed in CGA_SETS.items():
        rest = [h for h in unique if h not in fixed]
        if len(rest) <= 1:
            return label
    return None
