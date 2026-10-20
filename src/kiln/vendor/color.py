"""Perceptual color maths: sRGB <-> OKLab / OKLCh (Björn Ottosson's OKLab), distances, gamut mapping."""

from __future__ import annotations

import math

RGB = tuple[int, int, int]
Lab = tuple[float, float, float]


def _to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c: float) -> float:
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def rgb_to_oklab(rgb: RGB) -> Lab:
    r, g, b = (_to_linear(v / 255) for v in rgb)
    l_ = math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def _oklab_to_linear(lab: Lab) -> tuple[float, float, float]:
    L, a, b = lab
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
        -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
        -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_,
    )


def _in_gamut(linear: tuple[float, float, float]) -> bool:
    return all(-1e-4 <= v <= 1 + 1e-4 for v in linear)


def oklab_to_rgb(lab: Lab) -> RGB:
    """Convert to sRGB; out-of-gamut colors keep lightness and hue and lose chroma until they fit."""
    L = min(1.0, max(0.0, lab[0]))
    a, b = lab[1], lab[2]
    linear = _oklab_to_linear((L, a, b))
    if not _in_gamut(linear):
        lo, hi = 0.0, 1.0
        for _ in range(24):
            mid = (lo + hi) / 2
            if _in_gamut(_oklab_to_linear((L, a * mid, b * mid))):
                lo = mid
            else:
                hi = mid
        linear = _oklab_to_linear((L, a * lo, b * lo))
    return tuple(round(min(1.0, max(0.0, _to_srgb(min(1.0, max(0.0, v))))) * 255) for v in linear)  # type: ignore[return-value]


def to_lch(lab: Lab) -> tuple[float, float, float]:
    L, a, b = lab
    return (L, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360)


def from_lch(L: float, C: float, h: float) -> Lab:
    return (L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h)))


def distance(x: Lab, y: Lab) -> float:
    """Euclidean distance in OKLab (~ perceptual difference; 0.02 is barely visible)."""
    return math.dist(x, y)


def hex_to_rgb(value: str) -> RGB:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def rgb_to_hex(rgb: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)
