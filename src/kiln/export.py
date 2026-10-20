"""Built model -> binary glTF (.glb): materials from the style, one primitive per material, part nodes or a
skinned mesh, animations. Deterministic (PAGAN's writer: sorted JSON, float32, aligned buffers)."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

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


def srgb_to_linear(hex_color: str) -> list[float]:
    out = []
    for i in (1, 3, 5):
        c = int(hex_color[i : i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


def gltf_name(name: str, loop: bool) -> str:
    """Godot's importer loops animations named `<name>-loop` and strips the suffix."""
    return f"{name}-loop" if loop else name


class _Writer:
    def __init__(self, built: Built, swap: dict[str, str], generator: str, vertex_colors: bool = False) -> None:
        self.b = built
        self.swap = swap
        self.vertex_colors = vertex_colors
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
        if self.vertex_colors:  # colours in the vertices: one primitive per material preset (fewer draw calls)
            presets = self.b.style.materials
            keys = [k if k[3] >= 0 or presets.get(k[2], presets["default"]).emission > 0 else (WHITE, "vertex", k[2], -1) for k in keys]
        order = sorted(set(keys))
        index = {k: i for i, k in enumerate(order)}
        keys_arr = np.array([index[k] for k in keys]) if keys else np.zeros(0, dtype=int)
        palette = sorted(set(face_color))
        color_id = np.array([palette.index(c) for c in face_color]) if face_color else np.zeros(0, dtype=int)
        for m, key in enumerate(order):
            mask = keys_arr == m
            sel = faces_idx[mask]
            corners = p.faces[sel].reshape(-1)
            normals = self.b.normals[sel].reshape(-1, 3)
            colors = np.repeat(color_id[mask], 3).astype(float)[:, None]
            rows = np.concatenate([corners[:, None].astype(float), np.round(normals, 5), colors], axis=1)
            unique, inverse = np.unique(rows, axis=0, return_inverse=True)
            vidx = unique[:, 0].astype(np.int64)
            pos = p.vertices[vidx] - origin
            nrm = unique[:, 1:4]
            nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
            attributes = {
                "POSITION": self.doc.accessor(pos.astype(np.float32), target=ARRAY_BUFFER, bounds=True),
                "NORMAL": self.doc.accessor(nrm.astype(np.float32), target=ARRAY_BUFFER),
            }
            if key[1] == "vertex":
                rgb = np.array([srgb_to_linear(palette[int(c)]) for c in unique[:, 4]], dtype=np.float32)
                attributes["COLOR_0"] = self.doc.accessor(rgb, target=ARRAY_BUFFER)
            if key[3] >= 0:
                uv = decal_uv(p.decals[key[3]], p.vertices[vidx])
                attributes["TEXCOORD_0"] = self.doc.accessor(uv.astype(np.float32), target=ARRAY_BUFFER)
            if skinned:
                assert self.b.joints is not None and self.b.weights is not None
                attributes["JOINTS_0"] = self.doc.accessor(self.b.joints[vidx].astype(np.uint16), target=ARRAY_BUFFER)
                attributes["WEIGHTS_0"] = self.doc.accessor(self.b.weights[vidx].astype(np.float32), target=ARRAY_BUFFER)
            indices = self.doc.accessor(inverse.reshape(-1).astype(np.uint32), target=ELEMENT_ARRAY_BUFFER)
            prims.append({"attributes": attributes, "indices": indices, "material": self.material(key[0], key[1], key[2], key[3])})
        return prims

    def write(self) -> bytes:
        b, sk, p = self.b, self.b.skeleton, self.b.painted
        nodes: list[dict[str, Any]] = []
        bone_faces = {i: np.flatnonzero(np.array([p.groups[g].bone == bone.name for g in p.face_group])) for i, bone in enumerate(sk.bones)}
        for i, bone in enumerate(sk.bones):
            node: dict[str, Any] = {"name": bone.name}
            t = sk.rest_translation(i)
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
                nodes.append({"name": f"{b.model.name}_mesh", "mesh": mesh, "skin": skin})
                scene_nodes.append(len(nodes) - 1)
            for i in rigid:
                if len(bone_faces[i]):
                    nodes[i]["mesh"] = self.doc.add("meshes", {"name": sk.bones[i].name, "primitives": self.primitives(bone_faces[i], sk.bones[i].pivot, False)})
        else:
            for i, bone in enumerate(sk.bones):
                if len(bone_faces[i]):
                    nodes[i]["mesh"] = self.doc.add("meshes", {"name": bone.name if b.skin != "none" else b.model.name,
                                                               "primitives": self.primitives(bone_faces[i], bone.pivot, False)})  # fmt: skip
        for node in nodes:
            self.doc.add("nodes", node)
        self.doc.json["scenes"] = [{"name": b.model.name, "nodes": scene_nodes}]
        self.doc.json["scene"] = 0
        for track in b.tracks:
            self.animation(track)
        return self.doc.glb()

    def animation(self, track: Track) -> None:
        frames = track.frames
        times = np.arange(frames, dtype=np.float64) / track.fps
        tr, rot, sc = track.translation, track.rotation, track.scale
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


def to_glb(built: Built, generator: str, swap: dict[str, str] | None = None, vertex_colors: bool = False) -> bytes:
    return _Writer(built, swap or {}, generator, vertex_colors).write()


__all__ = ["Built", "ROOT_ID", "gltf_name", "srgb_to_linear", "to_glb"]
