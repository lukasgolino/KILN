"""Built model -> binary glTF (.glb): materials from the style, one primitive per material, part nodes or a
skinned mesh, animations. Deterministic (PAGAN's writer: sorted JSON, float32, aligned buffers)."""

from __future__ import annotations

import io
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from PIL import Image

from kiln.atlas import AtlasUse, ambient_occlusion
from kiln.notation import ROOT_ID, Model
from kiln.paint import Painted, decal_uv
from kiln.rig import Skeleton, Track
from kiln.sdf import Array
from kiln.style import Style
from kiln.vendor.gltf import ARRAY_BUFFER, CLAMP_TO_EDGE, ELEMENT_ARRAY_BUFFER, NEAREST, Document

LINEAR = 9729
WHITE = "#ffffff"
LINEAR_MIPMAP_LINEAR = 9987


@dataclass
class Built:
    """Everything the exporters and previews need from one built model."""

    model: Model
    style: Style
    painted: Painted
    normals: Array  # (F, 3, 3) per corner
    skeleton: Skeleton
    skin: str  # none | rigid | soft
    joints: Array | None  # (V, 4) soft skins
    weights: Array | None
    tracks: list[Track]
    step: float
    pieces: int
    hidden: tuple[int, ...] = ()  # adding parts with no visible surface even at full resolution (lint W101)
    lost: tuple[int, ...] = ()  # adding parts visible at full resolution that decimation removed (lint W111)

    @property
    def triangles(self) -> int:
        return int(len(self.painted.faces))

    def bounds(self) -> tuple[Array, Array]:
        v = self.painted.vertices[np.unique(self.painted.faces)]
        return v.min(axis=0), v.max(axis=0)

    def origin(self) -> Array:
        """The model-space point the exported files put at their origin (the model's `origin:`; none: the model's own)."""
        o = self.model.origin
        if o is None:
            return np.zeros(3)
        if isinstance(o, tuple):
            return np.array(o, dtype=float)
        lo, hi = self.bounds()
        mid = (lo + hi) / 2
        return np.array([mid[0], lo[1], mid[2]]) if o == "base" else mid


def srgb_to_linear(hex_color: str) -> list[float]:
    out = []
    for i in (1, 3, 5):
        c = int(hex_color[i : i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def gltf_name(name: str, loop: bool) -> str:
    """Godot's importer loops animations named `<name>-loop` and strips the suffix."""
    return f"{name}-loop" if loop else name


def face_uvs(built: Built) -> Array | None:
    """(F, 3, 2) corner UVs from the parts' `uv:` projections (zero elsewhere), or None when no part has one."""
    p = built.painted
    with_uv = [g for g, group in enumerate(p.groups) if group.part >= 0 and built.model.parts[group.part].uv is not None]
    if not with_uv:
        return None
    from kiln.uv import project

    out = np.zeros((len(p.faces), 3, 2))
    for g in with_uv:
        part = built.model.parts[p.groups[g].part]
        sel = np.flatnonzero(p.face_group == g)
        if len(sel) and part.uv is not None:
            out[sel] = project(part.geometry, part.uv, p.vertices[p.faces[sel]])
    return out


def attr_names(built: Built) -> list[str]:
    """The `attr:` names the model's parts use (sorted: the first also goes in COLOR_0's alpha)."""
    return sorted({name for part in built.model.parts for name, _ in part.attr})


def face_attrs(built: Built) -> dict[str, Array]:
    """name -> (F,) value per face (0 where the part doesn't set it)."""
    p = built.painted
    out = {name: np.zeros(len(p.faces)) for name in attr_names(built)}
    for g, group in enumerate(p.groups):
        if group.part < 0:
            continue
        sel = p.face_group == g
        for name, value in built.model.parts[group.part].attr:
            out[name][sel] = value
    return out


def uv_channel(built: Built, atlas: AtlasUse | None) -> int:
    """Projected UVs go in TEXCOORD_0 (Godot UV), or TEXCOORD_1 (UV2) when a palette atlas or decal uses the first."""
    return 1 if atlas is not None or bool((built.painted.face_decal >= 0).any()) else 0


class _Writer:
    def __init__(self, built: Built, swap: dict[str, str], generator: str, vertex_colors: bool = False, atlas: AtlasUse | None = None,
                 origin: Array | None = None) -> None:
        self.origin = np.zeros(3) if origin is None else origin
        self.b = built
        self.face_uv = face_uvs(built)
        self.face_attr = face_attrs(built)
        self.uv_set = uv_channel(built, atlas)
        self.swap = swap
        self.vertex_colors = vertex_colors
        self.atlas = atlas
        self.atlas_material: int | None = None
        self.ao: Array | None = ambient_occlusion(built) if atlas is not None and atlas.ao else None
        self.doc = Document(generator)
        self.materials: dict[tuple[str, str, int], int] = {}
        self.textures: dict[tuple[int, str], int] = {}
        self.sampler: dict[bool, int] = {}

    def color(self, hex_color: str) -> str:
        return self.swap.get(hex_color, hex_color)

    def material(self, color: str, color_name: str, preset_name: str, decal: int) -> int:
        """`color` is already swapped (variants)."""
        key = (color, preset_name, decal)
        if key in self.materials:
            return self.materials[key]
        preset = self.b.style.materials.get(preset_name, self.b.style.materials["default"])
        rgb = srgb_to_linear(color)
        pbr: dict[str, Any] = {"baseColorFactor": [*rgb, 1.0], "metallicFactor": preset.metallic, "roughnessFactor": preset.roughness}
        # name: <preset>_<colour name>[_decal<n>]#<rrggbb>; the hex lets Godot variant scenes find what to recolour
        mat: dict[str, Any] = {"name": f"{preset_name}_{color_name.split('#')[0].lstrip('#')}", "pbrMetallicRoughness": pbr}
        if decal >= 0:
            pbr["baseColorFactor"] = [1.0, 1.0, 1.0, 1.0]
            pbr["baseColorTexture"] = {"index": self.texture(decal, color)}
            mat["name"] += f"_decal{decal}"
        mat["name"] += color
        if preset.emission > 0:
            strength = preset.emission
            mat["emissiveFactor"] = rgb
            if strength != 1.0:
                mat["extensions"] = {"KHR_materials_emissive_strength": {"emissiveStrength": strength}}
                self.doc.json.setdefault("extensionsUsed", [])
                if "KHR_materials_emissive_strength" not in self.doc.json["extensionsUsed"]:
                    self.doc.json["extensionsUsed"].append("KHR_materials_emissive_strength")
        self.materials[key] = self.doc.add("materials", mat)
        return self.materials[key]

    def nearest_sampler(self) -> int:
        if True not in self.sampler:
            self.sampler[True] = self.doc.add("samplers", {"magFilter": NEAREST, "minFilter": NEAREST, "wrapS": CLAMP_TO_EDGE, "wrapT": CLAMP_TO_EDGE})
        return self.sampler[True]

    def uri_texture(self, uri: str, name: str) -> dict[str, Any]:
        img = self.doc.add("images", {"uri": uri, "name": name})
        return {"index": self.doc.add("textures", {"sampler": self.nearest_sampler(), "source": img})}

    def shared_material(self) -> int:
        """The atlas material: colour, roughness/metal and glow from textures (UVs at each face's cell)."""
        if self.atlas_material is not None:
            return self.atlas_material
        a = self.atlas
        assert a is not None
        pbr: dict[str, Any] = {"baseColorTexture": self.uri_texture(a.palette, "palette"), "metallicFactor": 1.0, "roughnessFactor": 1.0,
                               "metallicRoughnessTexture": self.uri_texture(a.material, "material")}  # fmt: skip
        mat: dict[str, Any] = {"name": "atlas", "pbrMetallicRoughness": pbr}
        if a.glow is not None:
            mat["emissiveTexture"] = self.uri_texture(a.glow, "glow")
            mat["emissiveFactor"] = [1.0, 1.0, 1.0]
            if a.glow_strength != 1.0:
                mat["extensions"] = {"KHR_materials_emissive_strength": {"emissiveStrength": a.glow_strength}}
                self.doc.json.setdefault("extensionsUsed", [])
                if "KHR_materials_emissive_strength" not in self.doc.json["extensionsUsed"]:
                    self.doc.json["extensionsUsed"].append("KHR_materials_emissive_strength")
        self.atlas_material = self.doc.add("materials", mat)
        return self.atlas_material

    def texture(self, decal: int, base_color: str) -> int:
        key = (decal, base_color)
        if key in self.textures:
            return self.textures[key]
        d = self.b.painted.decals[decal]
        image = Image.open(d.image).convert("RGBA")
        backdrop = Image.new("RGBA", image.size, tuple(int(base_color[i : i + 2], 16) for i in (1, 3, 5)) + (255,))
        backdrop.alpha_composite(image)
        buf = io.BytesIO()
        backdrop.convert("RGB").save(buf, format="PNG", optimize=False)
        pixel_art = max(image.size) <= 256
        if pixel_art not in self.sampler:
            filt = NEAREST if pixel_art else LINEAR
            self.sampler[pixel_art] = self.doc.add("samplers", {"magFilter": filt, "minFilter": filt if pixel_art else LINEAR_MIPMAP_LINEAR,
                                                                "wrapS": CLAMP_TO_EDGE, "wrapT": CLAMP_TO_EDGE})  # fmt: skip
        img = self.doc.image_png(buf.getvalue(), f"decal{decal}_{base_color[1:]}")
        self.textures[key] = self.doc.add("textures", {"sampler": self.sampler[pixel_art], "source": img})
        return self.textures[key]

    def primitives(self, faces_idx: Array, origin: Array, skinned: bool) -> list[dict[str, Any]]:
        """Primitives for a subset of faces (one per material), positions relative to `origin`."""
        p = self.b.painted
        prims = []
        # one primitive per material: (colour after swaps, preset, decal); groups that only differ in name merge
        names: dict[str, str] = {}
        for g in p.groups:
            names.setdefault(g.color, g.color_name.split("#")[0])
        keys = [(self.color(p.groups[g].color), names[p.groups[g].color], p.groups[g].material, int(dec))
                for g, dec in zip(p.face_group[faces_idx], p.face_decal[faces_idx], strict=True)]  # fmt: skip
        face_color = [k[0] for k in keys]
        if self.atlas is not None:  # one primitive for every non-decal face; the mesh doesn't depend on the swap
            atlas = self.atlas.atlas
            groups = p.groups
            keys = [("", "atlas", "", -1) if int(dec) < 0 else (groups[g].color, names[groups[g].color], groups[g].material, int(dec))
                    for g, dec in zip(p.face_group[faces_idx], p.face_decal[faces_idx], strict=True)]  # fmt: skip
            face_color = [str(atlas.index(groups[g].color, groups[g].material)) if int(dec) < 0 else "" for g, dec in
                          zip(p.face_group[faces_idx], p.face_decal[faces_idx], strict=True)]  # fmt: skip
        elif self.vertex_colors:  # colours in the vertices: one primitive per material preset (fewer draw calls)
            presets = self.b.style.materials
            keys = [k if k[3] >= 0 or presets.get(k[2], presets["default"]).emission > 0 else (WHITE, "vertex", k[2], -1) for k in keys]
        order = sorted(set(keys))
        index = {k: i for i, k in enumerate(order)}
        keys_arr = np.array([index[k] for k in keys]) if keys else np.zeros(0, dtype=int)
        palette = sorted(set(face_color))
        color_id = np.array([palette.index(c) for c in face_color]) if face_color else np.zeros(0, dtype=int)
        if self.atlas is not None:  # the cell number itself
            color_id = np.array([int(c) if c else -1 for c in face_color], dtype=int)
        for m, key in enumerate(order):
            mask = keys_arr == m
            sel = faces_idx[mask]
            corners = p.faces[sel].reshape(-1)
            normals = self.b.normals[sel].reshape(-1, 3)
            colors = np.repeat(color_id[mask], 3).astype(float)[:, None]
            rows = np.concatenate([corners[:, None].astype(float), np.round(normals, 5), colors], axis=1)
            if self.face_uv is not None:  # projected UVs split vertices along their seams
                rows = np.concatenate([rows, np.round(self.face_uv[sel].reshape(-1, 2), 6)], axis=1)
            attr_col = rows.shape[1]
            for name in self.face_attr:  # and attributes along part borders
                rows = np.concatenate([rows, np.repeat(self.face_attr[name][sel], 3)[:, None]], axis=1)
            unique, inverse = np.unique(rows, axis=0, return_inverse=True)
            vidx = unique[:, 0].astype(np.int64)
            pos = p.vertices[vidx] - origin
            nrm = unique[:, 1:4]
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
            attributes = {
                "POSITION": self.doc.accessor(pos.astype(np.float32), target=ARRAY_BUFFER, bounds=True),
                "NORMAL": self.doc.accessor(nrm.astype(np.float32), target=ARRAY_BUFFER),
            }
            color = None  # COLOR_0 (written later, with alpha, when the model has attr:)
            if self.vertex_colors and self.atlas is None:  # every surface carries its colours (glow ones keep their own material too)
                color = np.array([srgb_to_linear(palette[int(c)]) for c in unique[:, 4]], dtype=np.float32)
                if not self.face_attr:
                    attributes["COLOR_0"] = self.doc.accessor(color, target=ARRAY_BUFFER)
            shared = self.atlas is not None and key[3] < 0
            if shared:
                assert self.atlas is not None
                attributes["TEXCOORD_0"] = self.doc.accessor(self.atlas.atlas.uvs(unique[:, 4]).astype(np.float32), target=ARRAY_BUFFER)
            if self.ao is not None:  # baked occlusion: a grey multiplier (glTF multiplies COLOR_0 into the base colour)
                color = np.repeat(self.ao[vidx][:, None], 3, axis=1).astype(np.float32)
                if not self.face_attr:
                    attributes["COLOR_0"] = self.doc.accessor(color, target=ARRAY_BUFFER)
            if key[3] >= 0:
                uv = decal_uv(p.decals[key[3]], p.vertices[vidx])
                attributes["TEXCOORD_0"] = self.doc.accessor(uv.astype(np.float32), target=ARRAY_BUFFER)
            if self.face_uv is not None:
                attributes[f"TEXCOORD_{self.uv_set}"] = self.doc.accessor(unique[:, 5:7].astype(np.float32), target=ARRAY_BUFFER)
            for k, name in enumerate(self.face_attr):
                values = unique[:, attr_col + k].astype(np.float32)
                attributes[f"_{name.upper()}"] = self.doc.accessor(values, target=ARRAY_BUFFER)
                if k == 0:  # the first also in COLOR_0's alpha (Godot: COLOR.a), over the colours or white
                    rgb = color if color is not None else np.ones((len(unique), 3), dtype=np.float32)
                    attributes["COLOR_0"] = self.doc.accessor(np.concatenate([rgb, values[:, None]], axis=1), target=ARRAY_BUFFER)
            if skinned:
                assert self.b.joints is not None and self.b.weights is not None
                attributes["JOINTS_0"] = self.doc.accessor(self.b.joints[vidx].astype(np.uint16), target=ARRAY_BUFFER)
                attributes["WEIGHTS_0"] = self.doc.accessor(self.b.weights[vidx].astype(np.float32), target=ARRAY_BUFFER)
            indices = self.doc.accessor(inverse.reshape(-1).astype(np.uint32), target=ELEMENT_ARRAY_BUFFER)
            material = self.shared_material() if shared else self.material(self.color(key[0]) if self.atlas else key[0], key[1], key[2], key[3])
            prims.append({"attributes": attributes, "indices": indices, "material": material})
        return prims

    def write(self) -> bytes:
        b, sk, p = self.b, self.b.skeleton, self.b.painted
        nodes: list[dict[str, Any]] = []
        bone_faces = {i: np.flatnonzero(np.array([p.groups[g].bone == bone.name for g in p.face_group])) for i, bone in enumerate(sk.bones)}
        for i, bone in enumerate(sk.bones):
            node: dict[str, Any] = {"name": bone.name}
            t = sk.rest_translation(i) - (self.origin if i == 0 else 0)
            if np.any(t):
                node["translation"] = [float(np.float32(v)) for v in t]
            extras = {"kiln_part": bone.name, **bone.meta}
            node["extras"] = extras
            nodes.append(node)
        for i, bone in enumerate(sk.bones):
            kids = [j for j, other in enumerate(sk.bones) if other.parent == i]
            if kids:
                nodes[i]["children"] = kids
        for i, bone in enumerate(sk.bones):  # sockets: empty child nodes that move with the part (Godot: markers)
            for name, point in sorted(bone.sockets.items()):
                nodes[i].setdefault("children", []).append(len(nodes))
                nodes.append({"name": f"{bone.name}_{name}", "translation": [float(np.float32(v)) for v in point - bone.pivot],
                              "extras": {"kiln_socket": name, "kiln_part": bone.name}})  # fmt: skip
        prefix = b.model.node_prefix

        def put_mesh(i: int, mesh: int) -> None:
            """A part's mesh: on its node, or with node_prefix on a child node <prefix><id> (the part's node stays the bone)."""
            if not prefix:
                nodes[i]["mesh"] = mesh
                return
            nodes[i].setdefault("children", []).append(len(nodes))
            nodes.append({"name": f"{prefix}{sk.bones[i].name}", "mesh": mesh, "extras": {"kiln_part": sk.bones[i].name}})

        scene_nodes = [0]
        if b.skin == "soft":
            rigid = [i for i, bone in enumerate(sk.bones) if bone.separate]
            soft_faces = np.flatnonzero(~np.isin(np.array([sk.index(p.groups[g].bone) for g in p.face_group]), rigid))
            if len(soft_faces):
                mesh = self.doc.add("meshes", {"name": b.model.name, "primitives": self.primitives(soft_faces, np.zeros(3), True)})
                # Godot's importer gives the Skeleton3D node the extras of the last joint it processes (a soldier's
                # skeleton said hitzone: eye). An unweighted last joint carrying the model's own extras fixes that.
                marker = len(nodes)
                nodes.append({"name": "kiln_skeleton", "extras": {"kiln_model": b.model.name, "kiln_skeleton": True}})
                nodes[0].setdefault("children", []).append(marker)
                ibm = np.zeros((len(sk.bones) + 1, 4, 4), dtype=np.float32)
                for i, bone in enumerate([*sk.bones, sk.bones[0]]):  # the marker sits on the root
                    m = np.eye(4)
                    m[:3, 3] = -bone.pivot
                    ibm[i] = m.T  # glTF matrices are column-major
                view = self.doc.buffer_view(np.ascontiguousarray(ibm, dtype="<f4").tobytes())
                ibm_acc = self.doc.add("accessors", {"bufferView": view, "componentType": 5126, "count": len(sk.bones) + 1, "type": "MAT4"})
                skin = self.doc.add("skins", {"joints": [*range(len(sk.bones)), marker], "skeleton": 0, "inverseBindMatrices": ibm_acc})
                nodes.append({"name": f"{prefix}mesh" if prefix else f"{b.model.name}_mesh", "mesh": mesh, "skin": skin})
                scene_nodes.append(len(nodes) - 1)
            for i in rigid:
                if len(bone_faces[i]):
                    put_mesh(i, self.doc.add("meshes", {"name": sk.bones[i].name, "primitives": self.primitives(bone_faces[i], sk.bones[i].pivot, False)}))
        else:
            for i, bone in enumerate(sk.bones):
                if len(bone_faces[i]):
                    put_mesh(i, self.doc.add("meshes", {"name": bone.name if b.skin != "none" else b.model.name,
                                                        "primitives": self.primitives(bone_faces[i], bone.pivot, False)}))  # fmt: skip
        if b.model.fit_to is not None:  # an attachment: everything in the target bone's space (hang it on that bone)
            from kiln.fitting import bone_matrix

            inverse = np.linalg.inv(bone_matrix(b.model.fit_to[0], b.model.fit_to[1]))
            nodes.append({"name": f"{b.model.name}_on_{b.model.fit_to[1]}", "matrix": [float(np.float32(v)) for v in inverse.T.reshape(-1)],
                          "children": scene_nodes, "extras": {"kiln_attach": b.model.fit_to[1]}})  # fmt: skip
            scene_nodes = [len(nodes) - 1]
        for node in nodes:
            self.doc.add("nodes", node)
        self.doc.json["scenes"] = [{"name": b.model.name, "nodes": scene_nodes}]
        self.doc.json["scene"] = 0
        for track in b.tracks if b.model.animation_library is None else ():  # a library's clips: in its own glb
            self.animation(track)
        return self.doc.glb()

    def animation(self, track: Track) -> None:
        frames = track.frames
        times = np.arange(frames, dtype=np.float64) / track.fps
        tr, rot, sc = track.translation.copy(), track.rotation, track.scale
        tr[:, 0] -= self.origin  # the root carries the model's origin shift
        if track.loop:  # close the loop: the first pose again at the end
            times = np.append(times, frames / track.fps)
            tr, rot, sc = (np.concatenate([a, a[:1]]) for a in (tr, rot, sc))
        if frames == 1:
            times = np.array([0.0])
            tr, rot, sc = tr[:1], rot[:1], sc[:1]
        t_acc = self.doc.accessor(times.astype(np.float32), bounds=True)
        interp = "STEP" if track.interpolation == "step" else "LINEAR"
        samplers, channels = [], []
        for bone in range(tr.shape[1]):
            for path, data in (("translation", tr[:, bone]), ("rotation", rot[:, bone]), ("scale", sc[:, bone])):
                samplers.append({"input": t_acc, "output": self.doc.accessor(data.astype(np.float32)), "interpolation": interp})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": bone, "path": path}})
        self.doc.add("animations", {"name": gltf_name(track.name, track.loop), "samplers": samplers, "channels": channels})


def to_glb(built: Built, generator: str, swap: dict[str, str] | None = None, vertex_colors: bool = False, atlas: AtlasUse | None = None,
           origin: Array | None = None, merge_rigid: bool = False) -> bytes:
    """`atlas`: one material from the palette textures it names (kiln.toml atlas = true); `swap` then only recolours
    decals (the palette texture carries the variant's colours). `origin`: the model-space point at the glb's origin
    (default `built.origin()`; LODs pass the full model's so every level lines up). `merge_rigid`: a rigid skin is
    one skinned mesh (every vertex fully on its part's bone; `separate` parts stay their own nodes)."""
    origin = built.origin() if origin is None else origin
    if merge_rigid and built.skin == "rigid":
        built = rigid_as_one(built)
    return _Writer(built, swap or {}, generator, vertex_colors, atlas, origin).write()


def rigid_as_one(built: Built) -> Built:
    """A rigid skin as a soft one whose every vertex follows only its own part's bone: the same look and motion in one
    skinned mesh (one draw call). Vertices shared by two parts (colour borders) are split, one copy per bone."""
    p, sk = built.painted, built.skeleton
    group_bone = np.array([sk.index(g.bone) for g in p.groups] or [0], dtype=np.int64)
    corner_bone = np.repeat(group_bone[p.face_group], 3)
    keys = np.stack([p.faces.reshape(-1), corner_bone], axis=1)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    faces = inverse.reshape(-1, 3).astype(np.int64)
    joints = np.zeros((len(unique), 4), dtype=np.int64)
    joints[:, 0] = unique[:, 1]
    weights = np.zeros((len(unique), 4))
    weights[:, 0] = 1.0
    painted = replace(p, vertices=p.vertices[unique[:, 0]], faces=faces)
    return replace(built, painted=painted, skin="soft", joints=joints, weights=weights)


__all__ = ["Built", "ROOT_ID", "gltf_name", "rigid_as_one", "srgb_to_linear", "to_glb"]
