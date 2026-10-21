"""Imported meshes (a CC0 pack item: Kenney, KayKit, Quaternius, Poly Pizza...) as KILN models.

`source: { file, licence, author, url }` in a model file brings a .glb/.gltf in; the build scales it
(`process.height` / `scale`), stands it on y = 0, snaps every face's colour to the project palette (OKLab, so
mixed packs share one set of colours), applies the style's materials, smoothing and triangle budget, and
credits the author. Static meshes only: skins and animations in the file are ignored.
"""

from __future__ import annotations

import base64
import json
import math
from pathlib import Path
from typing import Any

import fast_simplification
import numpy as np
from PIL import Image

from kiln.export import Built
from kiln.notation import ROOT_ID, Model
from kiln.paint import PaintGroup, Painted
from kiln.rig import Bone, Skeleton
from kiln.sdf import Array, rotation_matrix
from kiln.style import Style
from kiln.vendor.color import distance, rgb_to_oklab
from kiln.vendor.gltf import read_glb

COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
DTYPES = {5126: "<f4", 5123: "<u2", 5125: "<u4", 5121: "u1", 5122: "<i2", 5120: "i1"}


class ImportError_(ValueError):
    pass


def _document(path: Path) -> dict[str, Any]:
    if path.suffix.lower() == ".glb":
        return read_glb(path.read_bytes())[0]
    doc: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return doc


def external_files(path: Path) -> list[str]:
    """The files a .glb/.gltf refers to by relative uri (buffers, textures: Kenney's Textures/colormap.png)."""
    doc = _document(path)
    uris = [item.get("uri", "") for item in [*doc.get("buffers", []), *doc.get("images", [])]]
    return sorted({u for u in uris if u and not u.startswith("data:")})


def missing_files(path: Path) -> list[str]:
    return [u for u in external_files(path) if not (path.parent / u).is_file()]


def _load(path: Path) -> tuple[dict[str, Any], list[bytes]]:
    if path.suffix.lower() == ".glb":
        doc, binary = read_glb(path.read_bytes())
        return doc, [binary]
    doc = json.loads(path.read_text(encoding="utf-8"))
    buffers = []
    for b in doc.get("buffers", []):
        uri = b.get("uri", "")
        if uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            buffers.append((path.parent / uri).read_bytes())
    return doc, buffers


def _accessor(doc: dict[str, Any], buffers: list[bytes], index: int) -> Array:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    n = COMPONENTS[acc["type"]]
    dtype = np.dtype(DTYPES[acc["componentType"]])
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = view.get("byteStride", 0)
    data = buffers[view.get("buffer", 0)]
    if stride and stride != dtype.itemsize * n:
        raw = np.frombuffer(data, dtype=np.uint8, count=stride * (acc["count"] - 1) + dtype.itemsize * n, offset=start)
        rows = np.stack([raw[i * stride : i * stride + dtype.itemsize * n] for i in range(acc["count"])])
        out = rows.view(dtype).reshape(acc["count"], n)
    else:
        out = np.frombuffer(data, dtype=dtype, count=acc["count"] * n, offset=start).reshape(acc["count"], n)
    out = out.astype(np.float64)
    if acc.get("normalized"):
        out = out / float(np.iinfo(dtype).max)
    return out if n > 1 else out[:, 0]


def _node_matrix(node: dict[str, Any]) -> Array:
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    m = np.eye(4)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    rot = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])  # fmt: skip
    m[:3, :3] = rot * np.array(node.get("scale", [1, 1, 1]))[None, :]
    m[:3, 3] = node.get("translation", [0, 0, 0])
    return m


def _texture_image(doc: dict[str, Any], buffers: list[bytes], path: Path, tex_index: int) -> Array | None:
    tex = doc.get("textures", [])[tex_index]
    img = doc.get("images", [])[tex.get("source", 0)]
    try:
        if "bufferView" in img:
            view = doc["bufferViews"][img["bufferView"]]
            data = buffers[view.get("buffer", 0)][view.get("byteOffset", 0) : view.get("byteOffset", 0) + view["byteLength"]]
            import io

            image = Image.open(io.BytesIO(data))
        elif img.get("uri", "").startswith("data:"):
            import io

            image = Image.open(io.BytesIO(base64.b64decode(img["uri"].split(",", 1)[1])))
        else:
            image = Image.open(path.parent / img["uri"])
    except (OSError, KeyError):
        return None
    return np.asarray(image.convert("RGB"), dtype=float) / 255.0


def read_mesh(path: Path) -> tuple[Array, Array, Array, list[str]]:
    """(vertices (V, 3), faces (F, 3), face colours (F, 3) sRGB 0..1, face material kinds) in the file's scene."""
    missing = missing_files(path)
    if missing:
        raise ImportError_(f"{path.name} refers to {', '.join(missing)}, which isn't next to it (keep the pack's folders, "
                           "e.g. imports/Textures/; `kiln import` copies them)")  # fmt: skip
    doc, buffers = _load(path)
    scene = doc.get("scenes", [{}])[doc.get("scene", 0)] if doc.get("scenes") else {"nodes": list(range(len(doc.get("nodes", []))))}
    verts, faces, colors, kinds = [], [], [], []
    count = 0
    images: dict[int, Array | None] = {}

    def visit(index: int, parent: Array) -> None:
        nonlocal count
        node = doc["nodes"][index]
        world = parent @ _node_matrix(node)
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]]["primitives"]:
                if prim.get("mode", 4) != 4:
                    continue
                pos = _accessor(doc, buffers, prim["attributes"]["POSITION"])
                idx = _accessor(doc, buffers, prim["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in prim else np.arange(len(pos)).reshape(-1, 3)
                wpos = (np.concatenate([pos, np.ones((len(pos), 1))], axis=1) @ world.T)[:, :3]
                if np.linalg.det(world[:3, :3]) < 0:
                    idx = idx[:, ::-1]
                mat = doc.get("materials", [])[prim["material"]] if "material" in prim else {}
                pbr = mat.get("pbrMetallicRoughness", {})
                factor = np.array(pbr.get("baseColorFactor", [1, 1, 1, 1])[:3])
                factor = np.where(factor <= 0.0031308, factor * 12.92, 1.055 * np.power(np.clip(factor, 0, 1), 1 / 2.4) - 0.055)  # linear -> sRGB
                face_col = np.repeat(factor[None, :], len(idx), axis=0)
                if "COLOR_0" in prim["attributes"]:
                    vc = _accessor(doc, buffers, prim["attributes"]["COLOR_0"])[:, :3]
                    vc = np.where(vc <= 0.0031308, vc * 12.92, 1.055 * np.power(np.clip(vc, 0, 1), 1 / 2.4) - 0.055)
                    face_col = face_col * vc[idx].mean(axis=1)
                tex = pbr.get("baseColorTexture")
                if tex is not None and "TEXCOORD_0" in prim["attributes"]:
                    if tex["index"] not in images:
                        images[tex["index"]] = _texture_image(doc, buffers, path, tex["index"])
                    image = images[tex["index"]]
                    if image is not None:
                        uv = _accessor(doc, buffers, prim["attributes"]["TEXCOORD_0"])[idx].mean(axis=1) % 1.0
                        h, w = image.shape[:2]
                        texel = image[(uv[:, 1] * h).astype(int).clip(0, h - 1), (uv[:, 0] * w).astype(int).clip(0, w - 1)]
                        face_col = face_col * texel
                kind = "metal" if pbr.get("metallicFactor", 1.0 if "metallicRoughnessTexture" in pbr else 0.0) > 0.5 else "default"
                verts.append(wpos)
                faces.append(idx + count)
                colors.append(face_col)
                kinds.extend([kind] * len(idx))
                count += len(wpos)
        for child in node.get("children", []):
            visit(child, world)

    for root in scene.get("nodes", []):
        visit(root, np.eye(4))
    if not verts:
        raise ImportError_(f"{path.name} has no triangle meshes")
    return np.concatenate(verts), np.concatenate(faces), np.concatenate(colors), kinds


def joint_heights(path: Path, names: tuple[str, ...] = ("head", "hips")) -> dict[str, float]:
    """Heights of the scene's nodes with these names (case-insensitive, after a `prefix:` such as `mixamorig:`) as
    fractions of the mesh's height (0 = its bottom, 1 = its top): a rigged reference's head and hips, for `--vs` bands."""
    v, f, _, _ = read_mesh(path)
    used = v[np.unique(f)]
    lo, span = float(used[:, 1].min()), float(np.ptp(used[:, 1]))
    doc, _ = _load(path)
    scene = doc.get("scenes", [{}])[doc.get("scene", 0)] if doc.get("scenes") else {"nodes": list(range(len(doc.get("nodes", []))))}
    found: dict[str, float] = {}

    def visit(index: int, parent: Array) -> None:
        node = doc["nodes"][index]
        world = parent @ _node_matrix(node)
        key = str(node.get("name", "")).rsplit(":", 1)[-1].lower()
        if key in names and key not in found and span > 0:
            found[key] = (float(world[1, 3]) - lo) / span
        for child in node.get("children", []):
            visit(child, world)

    for root in scene.get("nodes", []):
        visit(root, np.eye(4))
    return found


def nearest_palette(colors: Array, palette_hex: list[str]) -> list[str]:
    """Each colour's nearest palette colour (OKLab distance)."""
    labs = [rgb_to_oklab((int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))) for h in palette_hex]
    out = []
    cache: dict[tuple[int, int, int], str] = {}
    for c in colors:
        rgb = (int(round(c[0] * 255)), int(round(c[1] * 255)), int(round(c[2] * 255)))
        if rgb not in cache:
            lab = rgb_to_oklab(rgb)
            cache[rgb] = palette_hex[min(range(len(labs)), key=lambda i: distance(lab, labs[i]))]
        out.append(cache[rgb])
    return out


def build_imported(model: Model, style: Style, palette: dict[str, str] | None = None) -> Built:
    src = model.source
    assert src is not None
    v, f, cols, kinds = read_mesh(src.file)
    if any(src.rotate):
        v = v @ rotation_matrix(src.rotate).T
    scale = src.scale
    if src.height is not None:
        span = float(v[:, 1].max() - v[:, 1].min())
        scale = src.height / span if span > 0 else 1.0
    v = v * scale
    v[:, 1] -= v[:, 1].min()
    hexes = list(dict.fromkeys((palette or {}).values()))
    if src.recolor == "auto" and hexes:
        face_hex = nearest_palette(cols, hexes)
    else:
        face_hex = ["#%02x%02x%02x" % tuple(int(round(c * 255)) for c in col) for col in cols]
    names = {h: n for n, h in (palette or {}).items() if len(n) > 1}
    keys = sorted({(h, k) for h, k in zip(face_hex, kinds, strict=True)})
    groups = [PaintGroup(ROOT_ID, h, names.get(h, h), k) for h, k in keys]
    face_group = np.array([keys.index((h, k)) for h, k in zip(face_hex, kinds, strict=True)])
    budget = model.budget or style.budget(model.cls)
    if len(f) > budget * 1.2:
        v, f, face_group = _decimate_groups(v, f, face_group, budget)
    painted = Painted(v, f, face_group, groups, np.full(len(f), -1), [])
    normals = mesh_normals(v, f, style.smooth, style.sharp_angle)
    skeleton = Skeleton([Bone(ROOT_ID, -1, np.zeros(3), {}, False)])
    size = float(np.ptp(v, axis=0).max())
    return Built(model, style, painted, normals, skeleton, "none", None, None, [], max(size / 200, 0.002), 1)


def _decimate_groups(v: Array, f: Array, group: Array, budget: int) -> tuple[Array, Array, Array]:
    """Decimate each colour separately (borders kept, so no cracks between colours)."""
    out_v, out_f, out_g = [], [], []
    base = 0
    total = len(f)
    for g in np.unique(group):
        sel = f[group == g]
        used, inv = np.unique(sel, return_inverse=True)
        sub_v, sub_f = v[used], inv.reshape(-1, 3)
        target = max(12, int(budget * len(sel) / total))
        if len(sub_f) > target:
            sub_v, sub_f = fast_simplification.simplify(sub_v, sub_f.astype(np.int32), target_count=target, preserve_border=True)
        out_v.append(np.asarray(sub_v, float))
        out_f.append(np.asarray(sub_f, np.int64) + base)
        out_g.append(np.full(len(sub_f), g))
        base += len(sub_v)
    return np.concatenate(out_v), np.concatenate(out_f), np.concatenate(out_g)


def mesh_normals(v: Array, f: Array, smooth: bool, sharp_angle: float) -> Array:
    """Per-corner normals from the mesh itself (area-weighted vertex normals, split where sharper than the limit)."""
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    unit = fn / np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    flat = np.repeat(unit[:, None, :], 3, axis=1)
    if not smooth:
        return flat
    # weld by position so separately-coloured pieces still share normals
    keys = np.round(v, 5)
    _, weld = np.unique(keys, axis=0, return_inverse=True)
    weld = weld.reshape(-1)
    vn = np.zeros((weld.max() + 1, 3))
    for k in range(3):
        np.add.at(vn, weld[f[:, k]], fn)
    vn /= np.maximum(np.linalg.norm(vn, axis=1, keepdims=True), 1e-12)
    corner = vn[weld[f]]
    agree = (corner * unit[:, None, :]).sum(axis=2) >= math.cos(math.radians(sharp_angle))
    return np.where(agree[:, :, None], corner, flat)


def _scene_primitives(doc: dict[str, Any]) -> list[tuple[dict[str, Any], Array]]:
    """(triangle primitive, world matrix) per mesh instance in the scene, in `read_mesh`'s order."""
    scene = doc.get("scenes", [{}])[doc.get("scene", 0)] if doc.get("scenes") else {"nodes": list(range(len(doc.get("nodes", []))))}
    out: list[tuple[dict[str, Any], Array]] = []

    def visit(index: int, parent: Array) -> None:
        node = doc["nodes"][index]
        world = parent @ _node_matrix(node)
        if "mesh" in node:
            out.extend((prim, world) for prim in doc["meshes"][node["mesh"]]["primitives"] if prim.get("mode", 4) == 4)
        for child in node.get("children", []):
            visit(child, world)

    for root in scene.get("nodes", []):
        visit(root, np.eye(4))
    return out


def gltf_counts(source: Path | bytes) -> dict[str, int]:
    """Surfaces (triangle primitives drawn: draw calls) and distinct materials they use, over the scene of a
    .glb/.gltf file or of glb bytes (what `to_glb` writes)."""
    prims = _scene_primitives(read_glb(source)[0] if isinstance(source, bytes) else _document(source))
    return {"surfaces": len(prims), "materials": len({p.get("material", -1) for p, _ in prims})}


def read_normals(path: Path) -> Array:
    """Per-corner normals (F, 3, 3) of `read_mesh(path)`'s faces: the file's own (NORMAL), flat where it has none."""
    doc, buffers = _load(path)
    out = []
    for prim, world in _scene_primitives(doc):
        pos = _accessor(doc, buffers, prim["attributes"]["POSITION"])
        idx = _accessor(doc, buffers, prim["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in prim else np.arange(len(pos)).reshape(-1, 3)
        if np.linalg.det(world[:3, :3]) < 0:
            idx = idx[:, ::-1]
        if "NORMAL" in prim["attributes"]:
            n = _accessor(doc, buffers, prim["attributes"]["NORMAL"]) @ np.linalg.inv(world[:3, :3])  # inverse transpose
            corner = n[idx]
        else:
            w = (np.concatenate([pos, np.ones((len(pos), 1))], axis=1) @ world.T)[:, :3][idx]
            fn = np.cross(w[:, 1] - w[:, 0], w[:, 2] - w[:, 0])
            corner = np.repeat(fn[:, None, :], 3, axis=1)
        out.append(corner / np.maximum(np.linalg.norm(corner, axis=2, keepdims=True), 1e-12))
    return np.concatenate(out) if out else np.zeros((0, 3, 3))


def load_reference(path: Path, style: Style, height: float | None = None, centre_xz: tuple[float, float] | None = None,
                   ground: bool = True) -> Built:  # fmt: skip
    """A .glb/.gltf as it is (a reference to compare against): its own colours (textures sampled per face) and
    normals, no decimation; scaled to `height` metres (default: the file's units), standing on y = 0 (unless not
    `ground`: where it is), its box centred on `centre_xz` if given."""
    v, f, cols, kinds = read_mesh(path)
    if height is not None:
        span = float(v[:, 1].max() - v[:, 1].min())
        v = v * (height / span if span > 0 else 1.0)
    used = v[np.unique(f)]
    lo, hi = used.min(axis=0), used.max(axis=0)
    shift = np.array([0.0, -lo[1] if ground else 0.0, 0.0])
    if centre_xz is not None:
        shift[[0, 2]] = np.array(centre_xz) - (lo[[0, 2]] + hi[[0, 2]]) / 2
    v = v + shift
    face_hex = ["#%02x%02x%02x" % tuple(int(round(c * 255)) for c in col) for col in np.clip(cols, 0, 1)]
    keys = sorted(set(zip(face_hex, kinds, strict=True)))
    lookup = {k: i for i, k in enumerate(keys)}
    groups = [PaintGroup(ROOT_ID, h, h, k) for h, k in keys]
    face_group = np.array([lookup[k] for k in zip(face_hex, kinds, strict=True)], dtype=np.int64)
    painted = Painted(v, f, face_group, groups, np.full(len(f), -1), [])
    skeleton = Skeleton([Bone(ROOT_ID, -1, np.zeros(3), {}, False)])
    size = float((hi - lo).max())
    return Built(Model(path.stem, path), style, painted, read_normals(path), skeleton, "none", None, None, [], max(size / 200, 0.002), 1)


__all__ = ["ImportError_", "build_imported", "external_files", "gltf_counts", "joint_heights", "load_reference", "mesh_normals", "missing_files", "nearest_palette",
           "read_mesh", "read_normals"]
