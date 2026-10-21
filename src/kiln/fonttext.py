"""Text set in a font file (.ttf / .otf) as SVG path data, for `extrude: { text: ..., font: ... }`: each glyph's
outline from the font, placed by its advance width. Coordinates follow svgpath's convention (x right, y down onto
the extrude's z): the first line's baseline is y = 0, later lines go down by `line_spacing` ems. No kerning or
shaping (ligatures, right-to-left): fine for signs and labels, not for running text."""

from __future__ import annotations

from pathlib import Path

ALIGN = ("left", "center", "right")


class FontError(ValueError):
    pass


def text_path(font: Path, text: str, size: float, align: str = "center", letter_spacing: float = 0.0, line_spacing: float = 1.2,
              axes: dict[str, float] | None = None) -> str:  # fmt: skip
    """SVG path data in metres for `text` at `size` metres per em, each line aligned about x = 0. `axes` picks a
    variable font's instance (e.g. {"wght": 900}); without it the font's default instance is used."""
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.ttLib import TTFont, TTLibError

    try:
        tt = TTFont(str(font), lazy=not axes, fontNumber=0)
        if axes:
            if "fvar" not in tt:
                raise FontError(f"font {font.name} isn't a variable font: font_axes needs one (or use a static font of that weight)")
            known = {a.axisTag: (a.minValue, a.maxValue) for a in tt["fvar"].axes}
            for tag, value in axes.items():
                if tag not in known:
                    raise FontError(f"font {font.name} has no axis {tag!r} (axes: {', '.join(sorted(known))})")
                if not known[tag][0] <= value <= known[tag][1]:
                    raise FontError(f"font {font.name}: {tag} {value:g} is outside {known[tag][0]:g}-{known[tag][1]:g}")
            from fontTools.varLib import instancer

            tt = instancer.instantiateVariableFont(tt, dict(axes))  # overlaps kept: the extrude fills nonzero
        cmap = tt.getBestCmap() or {}
        glyphs = tt.getGlyphSet()
        em = float(tt["head"].unitsPerEm)
    except (OSError, TTLibError, KeyError, AssertionError) as e:
        raise FontError(f"can't read font {font.name}: {e}") from e
    missing = sorted({ch for ch in text if ch != "\n" and ord(ch) not in cmap and not ch.isspace()})
    if missing:
        raise FontError(f"font {font.name} has no glyph for {''.join(missing)!r}")
    k = size / em
    pen = SVGPathPen(glyphs)
    for row, line in enumerate(text.split("\n")):
        names = [cmap.get(ord(ch)) for ch in line]
        widths = [glyphs[n].width if n is not None else em / 4 for n in names]
        spacing = letter_spacing / k
        total = sum(widths) + spacing * max(0, len(line) - 1)
        x = {"left": 0.0, "center": -total / 2, "right": -total}[align]
        baseline = row * line_spacing * em
        for name, width in zip(names, widths, strict=True):
            if name is not None:
                # font units, y up -> metres, y down
                glyphs[name].draw(TransformPen(pen, (k, 0, 0, -k, x * k, baseline * k)))
            x += width + spacing
    return str(pen.getCommands())


__all__ = ["ALIGN", "FontError", "text_path"]
