"""Preview sheets an agent (or a person) looks at: turntable, closeup, animation filmstrip, line-up at a common
scale, gallery, and the model beside the style's inspiration images."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from kiln.export import Built
from kiln.render import View, render
from kiln.sdf import Array

BG = (32, 33, 40)
TEXT = (230, 232, 238)
DIM = (150, 155, 168)
TILE_BG = (214, 224, 236, 255)
HEADINGS = [("front", 0.0), ("front-left", 45.0), ("left", 90.0), ("back-left", 135.0), ("back", 180.0),
            ("back-right", 225.0), ("right", 270.0), ("front-right", 315.0)]  # fmt: skip
INSPIRATION_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size)


def sheet(title: str, subtitle: str, rows: list[tuple[str, list[tuple[str, Image.Image]]]], gap: int = 10) -> Image.Image:
    """Rows of labelled tiles under a title."""
    title_font, label_font = _font(20), _font(13)
    tile_w = max((im.width for _, row in rows for _, im in row), default=64)
    tile_h = max((im.height for _, row in rows for _, im in row), default=64)
    cols = max((len(row) for _, row in rows), default=1)
    width = max(cols * (tile_w + gap) + gap, 640)
    height = 64 + len(rows) * (tile_h + 40) + gap
    out = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(out)
    draw.text((gap, 10), title, fill=TEXT, font=title_font)
    draw.text((gap, 36), subtitle, fill=DIM, font=label_font)
    y = 64
    for label, row in rows:
        draw.text((gap, y), label, fill=DIM, font=label_font)
        y += 18
        for i, (name, im) in enumerate(row):
            x = gap + i * (tile_w + gap)
            out.paste(im, (x, y), im if im.mode == "RGBA" else None)
            draw.text((x + 4, y + im.height - 16), name, fill=(40, 40, 52), font=label_font)
        y += tile_h + 22
    return out


def _fit(built: Built) -> tuple[Array, float]:
    lo, hi = built.bounds()
    return (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 1.08


def turntable(built: Built, size: int = 220, swap: dict[str, str] | None = None) -> Image.Image:
    fit = _fit(built)
    rows = []
    for pitch, label in ((-20.0, "from below (-20 degrees)"), (15.0, "eye level (+15)"), (50.0, "from above (+50)")):
        rows.append((label, [(n, render(built, View(yaw, pitch), size, swap=swap, fit=fit, background=TILE_BG)) for n, yaw in HEADINGS]))
    m = built.model
    return sheet(f"{m.name} turntable", f"style {built.style.name} · {built.triangles} triangles · {m.cls} · front = +Z", rows)


def closeup(built: Built, part_id: str, size: int = 260) -> Image.Image:
    """One part (bone) filling the view, in place: what a close camera (a kill cam, a dialogue shot) sees."""
    p = built.painted
    faces = np.array([p.groups[g].bone == part_id for g in p.face_group])
    if built.skin == "none" or part_id.isdigit():  # no bones, or a part by its number in the file: the parts' own boxes
        chosen = [q for q in built.model.parts if (q.index == int(part_id) if part_id.isdigit() else q.id == part_id)]
        boxes = [q.geometry.bounds() for q in chosen if q.geometry.op == "add"]
        if not boxes:
            raise KeyError(part_id)
        lo, hi = np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)
    else:
        if not faces.any():
            raise KeyError(part_id)
        v = p.vertices[p.faces[faces]].reshape(-1, 3)
        lo, hi = v.min(axis=0), v.max(axis=0)
    fit = ((lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) / 2 * 1.3, built.step * 8))
    rows = []
    for pitch in (-15.0, 15.0, 45.0):
        rows.append((f"{part_id} in place, {pitch:+g} degrees", [(n, render(built, View(yaw, pitch), size, fit=fit, background=TILE_BG)) for n, yaw in HEADINGS[::2] + HEADINGS[1::2][:2]]))
    return sheet(f"{built.model.name} closeup: {part_id}", "framed on the part; other parts may cover it, as in the game", rows)


def detach(built: Built, size: int = 220) -> Image.Image:
    """Every detachable (`separate`) part taken off in turn: the whole model without it from four sides, and a
    closeup of what it covered (the surface the game shows once it falls off)."""
    p = built.painted
    separate = [b.name for b in built.skeleton.bones if b.separate]
    if not separate:
        raise KeyError("no separate parts")
    fit = _fit(built)
    rows = []
    for bone in separate:
        mine = np.array([p.groups[g].bone == bone for g in p.face_group], dtype=bool)
        v = p.vertices[p.faces[mine]].reshape(-1, 3)
        lo, hi = v.min(axis=0), v.max(axis=0)
        near = ((lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) / 2 * 1.4, built.step * 8))
        hidden = frozenset({bone})
        tiles = [(n, render(built, View(yaw, 15.0), size, fit=fit, background=TILE_BG, hide=hidden)) for n, yaw in HEADINGS[::2]]
        tiles += [(f"close {n}", render(built, View(yaw, 30.0), size, fit=near, background=TILE_BG, hide=hidden)) for n, yaw in HEADINGS[::2]]
        rows.append((f"without {bone}", tiles))
    return sheet(f"{built.model.name} detached", "each separate part off in turn: no holes, and the surface under it is what the game shows", rows)


def filmstrip(built: Built, animation: str, size: int = 200) -> Image.Image:
    names = [t.name for t in built.tracks]
    if animation not in names:
        raise KeyError(animation)
    k = names.index(animation)
    t = built.tracks[k]
    lo, hi = built.bounds()
    centre = (lo + hi) / 2
    half = float(np.linalg.norm(hi - lo)) / 2 * 1.3
    fit = (centre, half)
    rows = []
    for label, view in (("3/4 front", View(30.0, 12.0)), ("side", View(90.0, 5.0))):
        rows.append((label, [(f"{i}", render(built, view, size, track=k, frame=i, fit=fit, background=TILE_BG)) for i in range(t.frames)]))
    loop = "loops" if t.loop else "plays once"
    return sheet(f"{built.model.name} · {animation}", f"{t.frames} frames at {t.fps:g} fps ({t.frames / t.fps:.2f} s), {loop}, {t.interpolation}", rows)


def lineup(builts: list[Built], height_px: int = 480) -> Image.Image:
    """Models side by side at one scale (pixels per metre), standing on one ground line, with a 1 m bar."""
    if not builts:
        return sheet("line-up", "no models", [])
    margin = 24
    tallest = max(float(b.bounds()[1][1]) for b in builts)
    ppm = (height_px - margin - 30) / max(tallest, 0.5)
    tiles: list[tuple[str, Image.Image]] = []
    for b in builts:
        lo, hi = b.bounds()
        label_px = int(_font(13).getlength(b.model.name)) + 12
        width_px = max(int(float(max(hi[0] - lo[0], hi[2] - lo[2])) * 1.15 * ppm) + 24, label_px)
        side = max(height_px, width_px)
        half = side / ppm / 2
        centre = np.array([(lo[0] + hi[0]) / 2, half - margin / ppm, (lo[2] + hi[2]) / 2])  # ground `margin` px above the bottom
        full = render(b, View(25.0, 8.0), side, fit=(centre, half), background=TILE_BG)
        left = (side - width_px) // 2
        tiles.append((b.model.name, full.crop((left, side - height_px, left + width_px, side))))
    gap = 6
    width = 70 + sum(t.width + gap for _, t in tiles) + 10
    out = Image.new("RGB", (width, height_px + 80), BG)
    draw = ImageDraw.Draw(out)
    draw.text((10, 10), "line-up", fill=TEXT, font=_font(20))
    draw.text((10, 36), f"same scale: {ppm:.0f} px per metre, all standing on one ground line", fill=DIM, font=_font(13))
    top = 64
    ground = top + height_px - margin
    x = 70
    for name, tile in tiles:
        out.paste(tile, (x, top), tile)
        draw.text((x + 4, top + 4), name, fill=(40, 40, 52), font=_font(13))
        x += tile.width + gap
    draw.line([(10, ground), (width - 10, ground)], fill=(120, 124, 136), width=1)
    draw.line([(40, ground), (40, ground - ppm)], fill=TEXT, width=3)
    for k in range(11):
        y = ground - ppm * k / 10
        draw.line([(34 if k % 5 else 28, y), (46 if k % 5 else 52, y)], fill=TEXT, width=1)
    draw.text((26, ground - ppm - 18), "1 m", fill=TEXT, font=_font(13))
    return out


def gallery(builts: list[Built], size: int = 200) -> Image.Image:
    cols = 6
    tiles = [(b.model.name, render(b, View(30.0, 18.0), size, background=TILE_BG)) for b in builts]
    rows = [("", tiles[i : i + cols]) for i in range(0, len(tiles), cols)]
    return sheet("gallery", f"{len(builts)} models", rows)


def inspiration_images(styles_dir: Path, style: str) -> list[Path]:
    folder = styles_dir / style / "inspiration"
    return sorted(p for p in folder.glob("*") if p.suffix.lower() in INSPIRATION_SUFFIXES) if folder.is_dir() else []


def versus(built: Built, images: list[Path], size: int = 320) -> Image.Image:
    """The model beside the style's inspiration images (same height)."""
    tiles = [("kiln", render(built, View(30.0, 15.0), size, background=TILE_BG)), ("kiln back", render(built, View(200.0, 15.0), size, background=TILE_BG))]
    for path in images[:6]:
        im = Image.open(path).convert("RGBA")
        im.thumbnail((size * 2, size))
        tile = Image.new("RGBA", (size, size), TILE_BG)
        tile.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
        tiles.append((path.stem[:18], tile))
    return sheet(f"{built.model.name} vs inspiration", f"style {built.style.name}: does it look like it belongs?", [("", tiles)])


__all__ = ["closeup", "filmstrip", "gallery", "inspiration_images", "lineup", "sheet", "turntable", "versus"]
