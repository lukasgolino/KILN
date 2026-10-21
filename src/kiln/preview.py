"""Preview sheets an agent (or a person) looks at: turntable, closeup, animation filmstrip, line-up at a common
scale, gallery, the model beside the style's inspiration images, and the model against a reference mesh (a CC0
pack item) with metrics: silhouette IoU, triangles, surfaces, materials, colours, facet regularity, open edges."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from kiln.export import Built
from kiln.mesher import open_edges
from kiln.render import View, render, silhouette
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


def fitted(built: Built, size: int = 240) -> Image.Image:
    """An attachment (`fit_to`) on the character it was made for, and the character without it."""
    from dataclasses import replace

    from kiln.builder import _merge
    from kiln.importer import load_reference

    fit = built.model.fit_to
    if fit is None:
        raise KeyError("no fit_to")
    target = load_reference(fit[0], built.style, ground=False)
    painted, normals = _merge([built.painted, target.painted], [built.normals, target.normals], [], [])
    both = replace(built, painted=painted, normals=normals, skin="none", tracks=[], joints=None, weights=None)
    lo, hi = built.bounds()
    near = ((lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 1.5)
    rows = [(f"on {fit[0].stem} ({fit[1]})", [(n, render(both, View(yaw, 15.0), size, fit=near, background=TILE_BG)) for n, yaw in HEADINGS[::2]]),
            ("without it", [(n, render(target, View(yaw, 15.0), size, fit=near, background=TILE_BG)) for n, yaw in HEADINGS[::2]])]
    return sheet(f"{built.model.name} fitted", f"made around {fit[0].name}, exported in the space of its bone {fit[1]!r}", rows)


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


# --- against a reference mesh ------------------------------------------------------------------------------------

# opposite orthographic views have mirrored silhouettes, so four headings cover the horizon
COMPARE_VIEWS = [("front", View(0.0, 10.0)), ("front-left", View(45.0, 10.0)), ("left", View(90.0, 10.0)),
                 ("back-left", View(135.0, 10.0)), ("front above", View(0.0, 50.0)), ("left above", View(90.0, 50.0)),
                 ("top", View(0.0, 90.0)), ("below", View(30.0, -30.0))]  # fmt: skip
MASK_SIZE = 256
FACET_ANGLE = 2.0  # degrees: neighbours closer than this are one flat facet


def _shared_fit(a: Built, b: Built) -> tuple[Array, float]:
    """One framing for both: same pixels per metre, same ground."""
    (alo, ahi), (blo, bhi) = a.bounds(), b.bounds()
    lo, hi = np.minimum(alo, blo), np.maximum(ahi, bhi)
    return (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 1.08


def _corners(built: Built) -> Array:
    return np.asarray(built.painted.vertices[built.painted.faces])


def facet_regularity(vertices: Array, faces: Array) -> float:
    """Share of the surface area (0..1) in triangles that have an edge neighbour facing the same way (within
    FACET_ANGLE): parts of flat facets of two or more triangles. Designed low poly (quads, n-gons) is near 1;
    a smooth or noisily decimated mesh, where every triangle tilts a little, is near 0."""
    if not len(faces):
        return 0.0
    tri = vertices[faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(cross, axis=1)
    area = norm / 2
    unit = cross / np.maximum(norm, 1e-300)[:, None]
    _, weld = np.unique(np.round(vertices, 6), axis=0, return_inverse=True)
    f = weld.reshape(-1)[faces]
    e = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    face = np.tile(np.arange(len(faces)), 3)
    keep = (e[:, 0] != e[:, 1]) & (area[face] > 0)
    e, face = e[keep], face[keep]
    key = e[:, 0] * (int(f.max()) + 1) + e[:, 1]
    order = np.lexsort((face, key))
    key, face = key[order], face[order]
    same = key[1:] == key[:-1]
    fa, fb = face[:-1][same], face[1:][same]
    flat = (unit[fa] * unit[fb]).sum(axis=1) >= math.cos(math.radians(FACET_ANGLE))
    coplanar = np.zeros(len(faces), dtype=bool)
    coplanar[fa[flat]] = True
    coplanar[fb[flat]] = True
    total = float(area.sum())
    return float(area[coplanar].sum()) / total if total > 0 else 0.0


def mesh_stats(built: Built, counts: dict[str, int]) -> dict[str, Any]:
    """Triangles, `counts` (surfaces, materials: from the glTF), colours (distinct base colours on faces), facet
    regularity, open edges and size (metres) of a built model or a loaded reference."""
    p = built.painted
    lo, hi = built.bounds()
    return {"triangles": built.triangles, **counts, "colors": len({p.groups[int(g)].color for g in np.unique(p.face_group)}),
            "facet_regularity": round(facet_regularity(p.vertices, p.faces), 4),
            "open_edges": int(len(open_edges(p.vertices, p.faces))), "size": [round(float(x), 4) for x in hi - lo]}  # fmt: skip


def _masks(built: Built, ref: Built) -> list[tuple[str, Array, Array]]:
    fit = _shared_fit(built, ref)
    a, b = _corners(built), _corners(ref)
    return [(name, silhouette(a, view, MASK_SIZE, fit), silhouette(b, view, MASK_SIZE, fit)) for name, view in COMPARE_VIEWS]


def compare(built: Built, ref: Built, counts: dict[str, int], ref_counts: dict[str, int]) -> dict[str, Any]:
    """Metrics of a model against a reference at one scale: silhouette IoU per view (8 views, binary masks at the
    same framing), its mean and minimum, triangle ratio (model / reference) and both meshes' stats."""
    views = {}
    for name, a, b in _masks(built, ref):
        union = int((a | b).sum())
        views[name] = round(int((a & b).sum()) / union, 4) if union else 1.0
    stats, ref_stats = mesh_stats(built, counts), mesh_stats(ref, ref_counts)
    return {"iou": round(float(np.mean(list(views.values()))), 4), "iou_min": min(views.values()), "iou_views": views,
            "triangle_ratio": round(stats["triangles"] / max(ref_stats["triangles"], 1), 4), "model": stats, "reference": ref_stats}  # fmt: skip


def compare_summary(metrics: dict[str, Any]) -> list[str]:
    m, r = metrics["model"], metrics["reference"]
    pairs = " · ".join(f"{k.replace('_', ' ')} {m[k]} vs {r[k]}" for k in ("surfaces", "materials", "colors", "facet_regularity", "open_edges"))
    return [f"silhouette IoU {metrics['iou']:.3f} (min {metrics['iou_min']:.3f}) · triangles {m['triangles']} vs {r['triangles']} "
            f"(x{metrics['triangle_ratio']:.2f})", pairs]  # fmt: skip


def _head_fit(built: Built, ref: Built) -> tuple[Array, float]:
    """The top fifth of both (a character's head region)."""
    (alo, ahi), (blo, bhi) = built.bounds(), ref.bounds()
    top, bottom = float(max(ahi[1], bhi[1])), float(min(alo[1], blo[1]))
    cut = top - (top - bottom) / 5
    v = np.concatenate([built.painted.vertices[np.unique(built.painted.faces)], ref.painted.vertices[np.unique(ref.painted.faces)]])
    v = v[v[:, 1] >= cut]
    lo, hi = v.min(axis=0), v.max(axis=0)
    return (lo + hi) / 2, max(float(np.linalg.norm(hi - lo)) / 2 * 1.15, built.step * 8)


def versus_reference(built: Built, ref: Built, metrics: dict[str, Any], label: str, size: int = 180) -> Image.Image:
    """Reference and model in paired rows at one scale (turntable from below, eye level, above), their head regions
    (top fifth) close up, and the silhouette difference in each metric view."""
    fit = _shared_fit(built, ref)
    rows: list[tuple[str, list[tuple[str, Image.Image]]]] = []
    for pitch, height in ((-20.0, "from below"), (15.0, "eye level"), (50.0, "from above")):
        for who, b in (("reference", ref), ("kiln", built)):
            rows.append((f"{who}, {height} ({pitch:+g} degrees)", [(n, render(b, View(yaw, pitch), size, fit=fit, background=TILE_BG)) for n, yaw in HEADINGS]))
    head = _head_fit(built, ref)
    for who, b in (("reference", ref), ("kiln", built)):
        rows.append((f"{who}, top fifth close up", [(n, render(b, View(yaw, 15.0), size, fit=head, background=TILE_BG)) for n, yaw in HEADINGS]))
    diff = []
    for name, mine, theirs in _masks(built, ref):
        im = np.zeros((MASK_SIZE, MASK_SIZE, 4), dtype=np.uint8)
        im[:] = TILE_BG
        im[mine & theirs] = (120, 124, 136, 255)
        im[mine & ~theirs] = (220, 60, 50, 255)
        im[theirs & ~mine] = (50, 110, 220, 255)
        tile = Image.fromarray(im, "RGBA").resize((size, size), Image.Resampling.NEAREST)
        diff.append((f"{name} {metrics['iou_views'][name]:.2f}", tile))
    rows.append(("silhouettes: grey both, red kiln only, blue reference only (IoU per view)", diff))
    return sheet(f"{built.model.name} vs {label}", " | ".join(compare_summary(metrics)), rows)


__all__ = ["closeup", "compare", "compare_summary", "detach", "facet_regularity", "filmstrip", "gallery", "inspiration_images", "lineup",
           "mesh_stats", "sheet", "turntable", "versus", "versus_reference"]
