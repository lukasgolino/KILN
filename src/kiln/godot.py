"""Godot 4 output: a scene per model (the .glb plus the style's materials), a look kit per style (environment +
sun), headless verification and engine renders.

No sidecar files: shaders and the material script live inside the .tscn as sub-resources (Godot writes a `.uid`
file with a random id next to every .gdshader/.gd, which would make builds non-deterministic).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TypeAlias

from kiln.style import TOON_DARKEN, Look, Style

TOON_SHADER = """shader_type spatial;
render_mode specular_disabled;
uniform vec4 albedo : source_color = vec4(1.0);
uniform vec3 emission = vec3(0.0);
uniform int bands = 3;
void fragment() {
\tALBEDO = albedo.rgb * COLOR.rgb;  // COLOR: white unless the glb has vertex colours (vertex_colors = true)
\tEMISSION = emission;
}
void light() {
\tfloat n = clamp((dot(NORMAL, LIGHT) + 0.15) / 1.15, 0.0, 0.999);
\tfloat lit = floor(n * float(bands)) / float(bands - 1);
\tDIFFUSE_LIGHT += vec3(lit) * ATTENUATION * LIGHT_COLOR * 0.9;
}
"""

OUTLINE_SHADER = """shader_type spatial;
render_mode cull_front, unshaded;
uniform float width = 0.012;
uniform vec4 color : source_color = vec4(0.1, 0.08, 0.12, 1.0);
void vertex() {
\tVERTEX += NORMAL * width;
}
void fragment() {
\tALBEDO = color.rgb;
}
"""

APPLY_SCRIPT = """@tool
extends Node3D
# Written by `kiln build`: gives every surface the style's material (toon bands, outlines, rim light).
@export var shader_kind := "standard"
@export var toon_shader: Shader
@export var outline_shader: Shader
@export var bands := 3
@export var outline := 0.0
@export var outline_color := Color(0.1, 0.08, 0.12)
@export var rims: Dictionary = {}
@export var swap: Dictionary = {}  # variant: "rrggbb" (a material's colour, from its name) -> new colour

# Materials are made once and shared by every instance (and every model) with the same source and settings.
static var _shared: Dictionary = {}

func _ready() -> void:
\tfor node in find_children("*", "MeshInstance3D", true, false):
\t\tvar mesh_instance := node as MeshInstance3D
\t\tif mesh_instance.mesh == null:
\t\t\tcontinue
\t\tfor i in mesh_instance.mesh.get_surface_count():
\t\t\tvar source := mesh_instance.mesh.surface_get_material(i) as BaseMaterial3D
\t\t\tif source == null or mesh_instance.get_surface_override_material(i) != null:
\t\t\t\tcontinue  # the game's own override (a team colour set before add_child) wins
\t\t\tvar albedo := source.albedo_color
\t\t\tvar hex := source.resource_name.get_slice("#", 1)
\t\t\tif swap.has(hex) and source.albedo_texture == null:
\t\t\t\talbedo = swap[hex]
\t\t\tvar key := "%d|%s|%s|%d|%s|%s|%s" % [source.get_instance_id(), shader_kind, albedo.to_html(), bands, outline, outline_color.to_html(), rims]
\t\t\tif _shared.has(key):
\t\t\t\tmesh_instance.set_surface_override_material(i, _shared[key])
\t\t\t\tcontinue
\t\t\tvar material: Material
\t\t\tif shader_kind == "toon":
\t\t\t\tvar toon := ShaderMaterial.new()
\t\t\t\ttoon.shader = toon_shader
\t\t\t\ttoon.set_shader_parameter("albedo", albedo)
\t\t\t\ttoon.set_shader_parameter("emission", Vector3(source.emission.r, source.emission.g, source.emission.b) * source.emission_energy_multiplier if source.emission_enabled else Vector3.ZERO)
\t\t\t\ttoon.set_shader_parameter("bands", bands)
\t\t\t\tmaterial = toon
\t\t\telse:
\t\t\t\tvar standard := source.duplicate() as BaseMaterial3D
\t\t\t\tstandard.albedo_color = albedo
\t\t\t\tif mesh_instance.mesh.surface_get_format(i) & Mesh.ARRAY_FORMAT_COLOR:
\t\t\t\t\tstandard.vertex_color_use_as_albedo = true  # vertex_colors = true: glTF colours are linear
\t\t\t\tif source.emission_enabled and swap.has(hex):
\t\t\t\t\tstandard.emission = albedo
\t\t\t\tvar rim: float = rims.get(source.resource_name.get_slice("_", 0), 0.0)
\t\t\t\tif rim > 0.0:
\t\t\t\t\tstandard.rim_enabled = true
\t\t\t\t\tstandard.rim = rim
\t\t\t\t\tstandard.rim_tint = 0.6
\t\t\t\tmaterial = standard
\t\t\tif outline > 0.0:
\t\t\t\tvar edge := ShaderMaterial.new()
\t\t\t\tedge.shader = outline_shader
\t\t\t\tedge.set_shader_parameter("width", outline)
\t\t\t\tedge.set_shader_parameter("color", outline_color)
\t\t\t\tmaterial.next_pass = edge
\t\t\t_shared[key] = material
\t\t\tmesh_instance.set_surface_override_material(i, material)
"""


def _swap_lines(text: str, pairs: list[tuple[str, str]]) -> str:
    for old, new in pairs:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


# atlas = true (kiln.toml): the same shader and script, also reading the palette textures (non-atlas output unchanged)
ATLAS_TOON_SHADER = _swap_lines(TOON_SHADER, [
    ("uniform vec3 emission = vec3(0.0);\n", "uniform vec3 emission = vec3(0.0);\n"
     "uniform sampler2D albedo_texture : source_color, filter_nearest, hint_default_white;\n"
     "uniform sampler2D emission_texture : source_color, filter_nearest, hint_default_white;\n"),
    ("\tALBEDO = albedo.rgb * COLOR.rgb;  // COLOR: white unless the glb has vertex colours (vertex_colors = true)\n\tEMISSION = emission;\n",
     "\tALBEDO = albedo.rgb * texture(albedo_texture, UV).rgb * COLOR.rgb;  // COLOR: baked occlusion (atlas_ao) or white\n"
     "\tEMISSION = emission * texture(emission_texture, UV).rgb;\n"),
])  # fmt: skip

ATLAS_SCRIPT = _swap_lines(APPLY_SCRIPT, [
    ('@export var swap: Dictionary = {}  # variant: "rrggbb" (a material\'s colour, from its name) -> new colour\n',
     '@export var swap: Dictionary = {}  # variant: "rrggbb" (a material\'s colour, from its name) -> new colour\n'
     "@export var palette: Texture2D  # variant: its palette texture (the same cells in other colours)\n"
     "@export var glow: Texture2D  # variant: its glow texture\n"
     "@export var rim_texture: Texture2D  # rim light per cell (R: rim, G: tint)\n"),
    ("\t\t\tvar albedo := source.albedo_color\n",
     "\t\t\tvar albedo := source.albedo_color\n"
     '\t\t\tvar atlas := source.resource_name == "atlas"  # the material every non-decal face shares\n'
     "\t\t\tvar albedo_texture := palette if atlas and palette != null else source.albedo_texture\n"
     "\t\t\tvar emission_texture := glow if atlas and glow != null else source.emission_texture\n"),
    ("outline_color.to_html(), rims]\n",
     "outline_color.to_html(), rims]\n"
     "\t\t\tkey += \"|%d\" % (albedo_texture.get_instance_id() if albedo_texture != null else 0)\n"),
    ('\t\t\t\ttoon.set_shader_parameter("albedo", albedo)\n',
     '\t\t\t\ttoon.set_shader_parameter("albedo", albedo)\n'
     '\t\t\t\ttoon.set_shader_parameter("albedo_texture", albedo_texture)\n'
     '\t\t\t\ttoon.set_shader_parameter("emission_texture", emission_texture)\n'),
    ("\t\t\t\tstandard.albedo_color = albedo\n",
     "\t\t\t\tstandard.albedo_color = albedo\n"
     "\t\t\t\tif atlas:\n"
     "\t\t\t\t\tstandard.albedo_texture = albedo_texture\n"
     "\t\t\t\t\tstandard.emission_texture = emission_texture\n"
     "\t\t\t\t\tstandard.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST  # one texel per cell, no mipmaps\n"
     "\t\t\t\t\tif rim_texture != null:\n"
     "\t\t\t\t\t\tstandard.rim_enabled = true\n"
     "\t\t\t\t\t\tstandard.rim = 1.0\n"
     "\t\t\t\t\t\tstandard.rim_tint = 0.6\n"
     "\t\t\t\t\t\tstandard.rim_texture = rim_texture\n"),
])  # fmt: skip


def _toon_light(look: Look) -> str:
    """light() for a toon look with any of the richer keys on (softness, shadow colour, specular, banded shadows)."""
    lines = ["void light() {", "\tfloat n = clamp((dot(NORMAL, LIGHT) + 0.15) / 1.15, 0.0, 0.999);"]
    if look.toon_softness > 0:
        lines += ["\tfloat x = n * float(bands);",
                  "\tfloat edge = floor(x + 0.5);  // the nearest band edge; blend across it over `softness` of a band",
                  "\tfloat lit = clamp(edge - 1.0 + smoothstep(-0.5 * softness, 0.5 * softness, x - edge), 0.0, float(bands - 1)) / float(bands - 1);"]
    else:
        lines.append("\tfloat lit = floor(n * float(bands)) / float(bands - 1);")
    if look.toon_shadows == "band":
        lines.append("\tfloat shadow = LIGHT_IS_DIRECTIONAL ? step(0.5, ATTENUATION) : ATTENUATION;  // received shadows: the darkest band")
    else:
        lines.append("\tfloat shadow = ATTENUATION;")
    lines += ["\tfloat shade = lit * shadow;", "\tDIFFUSE_LIGHT += vec3(shade) * LIGHT_COLOR * 0.9;"]
    if look.toon_shadow_color:
        lines += ["\tif (LIGHT_IS_DIRECTIONAL) {",
                  "\t\tDIFFUSE_LIGHT += shadow_color.rgb * (1.0 - shade);  // the sun's missing light, in the shadow colour",
                  "\t}"]
    if look.toon_specular > 0:
        lines += ["\tvec3 halfway = normalize(LIGHT + VIEW);",
                  "\tfloat blob = step(1.0 - 0.08 * ROUGHNESS * ROUGHNESS, dot(NORMAL, halfway)) * step(0.0, dot(NORMAL, LIGHT));",
                  "\t// a white blob: diffuse light is multiplied by the albedo afterwards (specular_disabled keeps the plain toon's ambient)",
                  "\tDIFFUSE_LIGHT += LIGHT_COLOR * specular * (1.0 - ROUGHNESS) * blob * shadow / max(ALBEDO, vec3(0.05));"]
    return "\n".join(lines) + "\n}\n"


def rich_toon(look: Look) -> bool:
    """Whether the toon shader differs from the plain one (any richer key on)."""
    return look.toon_softness > 0 or bool(look.toon_shadow_color) or look.toon_specular > 0 or look.toon_shadows != "soft"


def toon_shader(look: Look, atlas: bool) -> str:
    """The toon shader for a look: the plain one unless a richer key is on (so existing output doesn't change)."""
    base = ATLAS_TOON_SHADER if atlas else TOON_SHADER
    if not rich_toon(look):
        return base
    head, _ = base.split("void light() {\n", 1)
    uniforms = ""
    if look.toon_softness > 0:
        uniforms += f"uniform float softness = {look.toon_softness:.6g};\n"
    if look.toon_shadow_color:
        uniforms += f"uniform vec4 shadow_color : source_color = {_vec4(look.toon_shadow_color)};\n"
    if look.toon_specular > 0:
        uniforms += f"uniform float specular = {look.toon_specular:.6g};\nuniform float roughness = 0.5;\n"
        if atlas:
            uniforms += "uniform sampler2D roughness_texture : filter_nearest, hint_default_white;\n"
            head = head.replace("\tEMISSION = emission * texture(emission_texture, UV).rgb;\n",
                                "\tEMISSION = emission * texture(emission_texture, UV).rgb;\n\tROUGHNESS = roughness * texture(roughness_texture, UV).g;\n")
        else:
            head = head.replace("\tEMISSION = emission;\n", "\tEMISSION = emission;\n\tROUGHNESS = roughness;\n")
    head = head.replace("uniform int bands = 3;\n", "uniform int bands = 3;\n" + uniforms)
    return head + _toon_light(look)


def outline_shader(look: Look, atlas: bool) -> str:
    """The outline shader: the plain one unless outline_space = "pixels" or outline_color = "darken"."""
    text = OUTLINE_SHADER
    if look.outline_space == "pixels":
        text = _swap_lines(text, [
            ("uniform float width = 0.012;\n", "uniform float width = 2.0;  // pixels\n"),
            ("\tVERTEX += NORMAL * width;\n",
             "\tvec4 clip = PROJECTION_MATRIX * MODELVIEW_MATRIX * vec4(VERTEX, 1.0);\n"
             "\tvec2 away = (PROJECTION_MATRIX * vec4(MODELVIEW_NORMAL_MATRIX * NORMAL, 0.0)).xy * VIEWPORT_SIZE;  // in pixels\n"
             "\tif (length(away) > 1e-6) {\n"
             "\t\tclip.xy += normalize(away) * width * 2.0 / VIEWPORT_SIZE * clip.w;  // constant thickness on screen\n"
             "\t}\n"
             "\tPOSITION = clip;\n"),
        ])  # fmt: skip
    if look.outline_color == "darken":
        texture = "uniform sampler2D albedo_texture : source_color, filter_nearest, hint_default_white;\n" if atlas else ""
        sample = " * texture(albedo_texture, UV).rgb" if atlas else ""
        text = _swap_lines(text, [
            ("uniform vec4 color : source_color = vec4(0.1, 0.08, 0.12, 1.0);\n",
             f"uniform vec4 color : source_color = vec4(1.0);  // the part's own colour, darkened\n{texture}"),
            ("\tALBEDO = color.rgb;\n", f"\tALBEDO = color.rgb{sample} * COLOR.rgb * {TOON_DARKEN:g};\n"),
        ])  # fmt: skip
    return text


def _apply_script(script: str, look: Look, atlas: bool) -> str:
    """The apply script, also feeding the richer toon keys their per-material values (only when they're on)."""
    pairs: list[tuple[str, str]] = []
    if look.shader == "toon" and look.toon_specular > 0:
        line = "\t\t\t\ttoon.set_shader_parameter(\"roughness\", source.roughness)\n"
        if atlas:
            line += "\t\t\t\ttoon.set_shader_parameter(\"roughness_texture\", source.roughness_texture)\n"
        pairs.append(('\t\t\t\ttoon.set_shader_parameter("bands", bands)\n', '\t\t\t\ttoon.set_shader_parameter("bands", bands)\n' + line))
    if look.outline_color == "darken":
        line = '\t\t\t\tedge.set_shader_parameter("color", albedo)  # outline_color = "darken": the part\'s colour\n'
        if atlas:
            line += '\t\t\t\tedge.set_shader_parameter("albedo_texture", albedo_texture)\n'
        pairs.append(('\t\t\t\tedge.set_shader_parameter("color", outline_color)\n', line))
    return _swap_lines(script, pairs) if pairs else script


def res_path(path: Path, godot_root: Path) -> str:
    return "res://" + path.resolve().relative_to(godot_root.resolve()).as_posix()


BONE_MAP_NODE = '"PATH:Skeleton3D"'  # the glTF importer's skeleton for a KILN skin (in _subresources -> "nodes")
BONE_MAP_KEY = '"retarget/bone_map"'


def bone_map_tres(pairs: list[tuple[str, str]]) -> str:
    """A Godot `BoneMap` on `SkeletonProfileHumanoid`: (profile bone, skeleton bone) pairs. No uid in the header and a
    fixed sub-resource id, so the file is the same every build (Godot keeps a resource's uid in its cache)."""
    lines = ['[gd_resource type="BoneMap" format=3]', "", '[sub_resource type="SkeletonProfileHumanoid" id="SkeletonProfileHumanoid_kiln"]',
             "", "[resource]", 'profile = SubResource("SkeletonProfileHumanoid_kiln")']  # fmt: skip
    lines += [f'bone_map/{profile} = &"{bone}"' for profile, bone in pairs]
    return "\n".join(lines) + "\n"


# Godot's variant text (the value of an .import's `_subresources`): dictionaries are parsed, anything else is kept as
# its text. Entries are (key text, value).
_Value: TypeAlias = "str | list[tuple[str, _Value]]"
_Dict: TypeAlias = "list[tuple[str, _Value]]"


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _raw(text: str, i: int) -> int:
    """The end of the value starting at i that isn't a dictionary: up to a `,` `:` `}` or `]` outside brackets/strings."""
    depth = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                return i
            depth -= 1
        elif c in ",:" and depth == 0:
            return i
        i += 1
    return i


def _parse(text: str, i: int) -> tuple[_Value, int]:
    i = _skip(text, i)
    if i >= len(text) or text[i] != "{":
        end = _raw(text, i)
        if end == i:
            raise ValueError(f"no value at {i}")
        return text[i:end].strip(), end
    entries: _Dict = []
    i = _skip(text, i + 1)
    while i < len(text) and text[i] != "}":
        key_end = _raw(text, i)
        key = text[i:key_end].strip()
        i = _skip(text, key_end)
        if i >= len(text) or text[i] != ":":
            raise ValueError(f"expected : at {i}")
        value, i = _parse(text, i + 1)
        entries.append((key, value))
        i = _skip(text, i)
        if i < len(text) and text[i] == ",":
            i = _skip(text, i + 1)
    if i >= len(text):
        raise ValueError("unclosed {")
    return entries, i + 1


def _dump(value: _Value) -> str:
    if isinstance(value, str):
        return value
    if not value:
        return "{}"
    return "{\n" + ",\n".join(f"{k}: {_dump(v)}" for k, v in value) + "\n}"


def _get(d: _Dict, key: str) -> _Value | None:
    return next((v for k, v in d if k == key), None)


def with_bone_map(import_text: str, bone_map_res: str, on: bool) -> str | None:
    """An `.import` (Godot's scene importer settings) with the skeleton's `retarget/bone_map` set to `bone_map_res`
    (`on`) or, when it points there, removed (not `on`); everything else in the file and in `_subresources` stays.
    None when nothing needs to change (or `_subresources` can't be read: it's left as it is)."""
    lines = import_text.splitlines(keepends=True)
    section, start = "", None
    params_end = None
    offset = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and "=" not in stripped:
            if section == "params" and params_end is None:
                params_end = offset
            section = stripped[1:-1]
        elif section == "params" and start is None and line.startswith("_subresources="):
            start = offset + len("_subresources=")
        offset += len(line)
    if start is None:
        if not on:
            return None
        if params_end is None and section != "params":
            body = import_text if import_text.endswith("\n") or not import_text else import_text + "\n"
            return body + ("\n" if body else "") + "[params]\n\n" + _subresources_line([], bone_map_res)
        at = params_end if params_end is not None else len(import_text)
        before = import_text[:at]
        if before and not before.endswith("\n"):
            before += "\n"
        return before + _subresources_line([], bone_map_res) + import_text[at:]
    try:
        tree, end = _parse(import_text, start)
    except ValueError:
        return None
    if not isinstance(tree, list):
        return None
    nodes = _get(tree, '"nodes"')
    skeleton = _get(nodes, BONE_MAP_NODE) if isinstance(nodes, list) else None
    current = _get(skeleton, BONE_MAP_KEY) if isinstance(skeleton, list) else None
    ours = isinstance(current, str) and f'"{bone_map_res}"' in current
    if on == ours:
        return None
    if not on and (not isinstance(nodes, list) or not isinstance(skeleton, list)):
        return None
    value = f'Resource("{bone_map_res}")'
    if on:
        tree = _set_path(tree, ['"nodes"', BONE_MAP_NODE, BONE_MAP_KEY], value)
    else:
        tree = _drop_path(tree, ['"nodes"', BONE_MAP_NODE, BONE_MAP_KEY])
    return import_text[:start] + _dump(tree) + import_text[end:]


def _subresources_line(tree: _Dict, bone_map_res: str) -> str:
    return "_subresources=" + _dump(_set_path(tree, ['"nodes"', BONE_MAP_NODE, BONE_MAP_KEY], f'Resource("{bone_map_res}")')) + "\n"


def _set_path(d: _Dict, keys: list[str], value: str) -> _Dict:
    key, rest = keys[0], keys[1:]
    child = _get(d, key)
    new: _Value = _set_path(child if isinstance(child, list) else [], rest, value) if rest else value
    if child is None:
        return [*d, (key, new)]
    return [(k, new if k == key else v) for k, v in d]


def _drop_path(d: _Dict, keys: list[str]) -> _Dict:
    """`d` without the entry at `keys`; dictionaries left empty on the way go too."""
    key, rest = keys[0], keys[1:]
    out: _Dict = []
    for k, v in d:
        if k != key:
            out.append((k, v))
        elif rest and isinstance(v, list):
            new = _drop_path(v, rest)
            if new:
                out.append((k, new))
    return out


def find_godot_project(start: Path) -> Path | None:
    current = start.resolve()
    for folder in (current, *current.parents):
        if (folder / "project.godot").is_file():
            return folder
    return None


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _color(hex_color: str) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return f"Color({r:.6g}, {g:.6g}, {b:.6g}, 1)"


def _vec4(hex_color: str) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return f"vec4({r:.6g}, {g:.6g}, {b:.6g}, 1.0)"


RIM_SHADER = """shader_type spatial;
render_mode blend_add, unshaded, depth_draw_never, cull_back;
// KILN: the style's rim light ([look] rim_light), drawn over every surface
uniform vec4 color : source_color = vec4(1.0);
uniform float power = 3.0;
uniform float strength = 0.0;

void fragment() {
\tfloat fresnel = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), power);
\tALBEDO = color.rgb * fresnel * strength;
}
"""


def _with_revealed(script: str) -> str:
    """The apply script, also hiding `revealed` parts until the game shows them (only written for models with some)."""
    return _swap_lines(script, [
        ("@export var rims: Dictionary = {}\n",
         "@export var rims: Dictionary = {}\n@export var revealed: Array = []  # node names hidden until the game shows them (stump caps)\n"),
        ("func _ready() -> void:\n",
         "func _ready() -> void:\n"
         "\tfor hidden_name in revealed:\n"
         "\t\tvar hidden := find_child(hidden_name, true, false) as Node3D\n"
         "\t\tif hidden != null:\n"
         "\t\t\thidden.visible = false\n"),
    ])  # fmt: skip


def _with_rim(script: str) -> str:
    """The apply script, also chaining the rim pass (only written for styles with rim_light, so others stay as they were)."""
    return _swap_lines(script, [
        ("@export var rims: Dictionary = {}\n",
         "@export var rims: Dictionary = {}\n@export var rim_shader: Shader\n@export var rim_light := 0.0\n"
         "@export var rim_light_color := Color(1, 1, 1)\n@export var rim_light_power := 3.0\n"),
        ("\t\t\t_shared[key] = material\n",
         "\t\t\tif rim_light > 0.0:\n"
         "\t\t\t\tvar glow_rim := ShaderMaterial.new()\n"
         "\t\t\t\tglow_rim.shader = rim_shader\n"
         "\t\t\t\tglow_rim.set_shader_parameter(\"color\", rim_light_color)\n"
         "\t\t\t\tglow_rim.set_shader_parameter(\"power\", rim_light_power)\n"
         "\t\t\t\tglow_rim.set_shader_parameter(\"strength\", rim_light)\n"
         "\t\t\t\tvar last := material\n"
         "\t\t\t\twhile last.next_pass != null:\n"
         "\t\t\t\t\tlast = last.next_pass\n"
         "\t\t\t\tlast.next_pass = glow_rim\n"
         "\t\t\t_shared[key] = material\n"),
    ])  # fmt: skip


def model_scene(name: str, glb_res: str, style: Style, swap: dict[str, str] | None = None, textures: dict[str, str] | None = None,
                revealed: list[str] | None = None) -> str:
    """`<name>.tscn`: the .glb with the style's materials applied by a small built-in tool script. With `swap`
    (a variant, when variant_glbs is false) the script also recolours: the base glb, other colours. `textures`
    (atlas = true): res:// paths by script property (`palette` and `glow` for a variant, `rim_texture`). `revealed`:
    node names the script hides (parts shown once another is gone)."""
    look = style.look
    rims = ", ".join(f"{_quote(k)}: {v.rim:.6g}" for k, v in sorted(style.materials.items()) if v.rim > 0)
    atlas = textures is not None
    script = _apply_script(ATLAS_SCRIPT if atlas else APPLY_SCRIPT, look, atlas)
    rim = look.rim_light > 0
    keys = sorted(textures or {})
    ext = [f'[ext_resource type="Texture2D" path={_quote((textures or {})[k])} id="{i}_{k}"]' for i, k in enumerate(keys, 2)]
    lines = [
        "[gd_scene format=3]",
        "",
        f'[ext_resource type="PackedScene" path={_quote(glb_res)} id="1_glb"]',
        *ext,
        "",
        '[sub_resource type="Shader" id="Shader_toon"]',
        f"code = {_quote(toon_shader(look, atlas))}",
        "",
        '[sub_resource type="Shader" id="Shader_outline"]',
        f"code = {_quote(outline_shader(look, atlas))}",
        "",
        *(['[sub_resource type="Shader" id="Shader_rim"]', f"code = {_quote(RIM_SHADER)}", ""] if rim else []),
        '[sub_resource type="GDScript" id="GDScript_apply"]',
        f"script/source = {_quote(_with_revealed(_with_rim(script) if rim else script) if revealed else (_with_rim(script) if rim else script))}",
        "",
        f'[node name={_quote(name)} instance=ExtResource("1_glb")]',
        'script = SubResource("GDScript_apply")',
        f"shader_kind = {_quote(look.shader)}",
        'toon_shader = SubResource("Shader_toon")',
        'outline_shader = SubResource("Shader_outline")',
        f"bands = {look.toon_bands}",
        f"outline = {look.outline:.6g}",
        *([] if look.outline_color == "darken" else [f"outline_color = {_color(look.outline_color)}"]),
        f"rims = {{{rims}}}",
        *([f"revealed = [{', '.join(_quote(n) for n in revealed)}]"] if revealed else []),
        *(['rim_shader = SubResource("Shader_rim")', f"rim_light = {look.rim_light:.6g}", f"rim_light_color = {_color(look.rim_light_color)}",
           f"rim_light_power = {look.rim_light_power:.6g}"] if rim else []),  # fmt: skip
        *([f"swap = {{{', '.join(f'{_quote(k[1:])}: {_color(v)}' for k, v in sorted(swap.items()))}}}"] if swap else []),
        *(f'{k} = ExtResource("{i}_{k}")' for i, k in enumerate(keys, 2)),
        f"metadata/kiln_style = {_quote(style.name)}",
        "",
    ]
    return "\n".join(lines)


TONEMAP = {"linear": 0, "filmic": 2, "aces": 3, "agx": 4}


def look_scene(style: Style) -> str:
    """`looks/<style>.tscn`: WorldEnvironment (sky, tonemapper, SSAO, glow, grading, fog) + the sun."""
    look: Look = style.look
    env = [
        '[sub_resource type="ProceduralSkyMaterial" id="Sky_material"]',
        f"sky_top_color = {_color(look.sky_top)}",
        f"sky_horizon_color = {_color(look.sky_horizon)}",
        f"ground_bottom_color = {_color(look.ground)}",
        f"ground_horizon_color = {_color(look.sky_horizon)}",
        "",
        '[sub_resource type="Sky" id="Sky_main"]',
        'sky_material = SubResource("Sky_material")',
        "",
        '[sub_resource type="Environment" id="Environment_main"]',
        "background_mode = 2",
        'sky = SubResource("Sky_main")',
        "ambient_light_source = 3",
        f"ambient_light_energy = {look.ambient:.6g}",
        f"tonemap_mode = {TONEMAP[look.tonemapper]}",
        f"tonemap_exposure = {look.exposure:.6g}",
        f"ssao_enabled = {'true' if look.ssao else 'false'}",
        f"glow_enabled = {'true' if look.glow else 'false'}",
        "adjustment_enabled = true",
        f"adjustment_saturation = {look.saturation:.6g}",
        f"adjustment_contrast = {look.contrast:.6g}",
    ]
    if look.fog > 0:
        env += ["fog_enabled = true", f"fog_density = {look.fog:.6g}", f"fog_light_color = {_color(look.fog_color)}"]
    nodes = [
        "",
        f'[node name={_quote("look_" + style.name)} type="Node3D"]',
        f"metadata/kiln_style = {_quote(style.name)}",
        "",
        '[node name="WorldEnvironment" type="WorldEnvironment" parent="."]',
        'environment = SubResource("Environment_main")',
        "",
        '[node name="Sun" type="DirectionalLight3D" parent="."]',
        f"transform = {_sun_transform(look)}",
        f"light_color = {_color(look.sun_color)}",
        f"light_energy = {look.sun_energy:.6g}",
        f"shadow_enabled = {'true' if look.shadows else 'false'}",
        "",
    ]
    return "\n".join(["[gd_scene format=3]", "", *env, *nodes])


def _sun_transform(look: Look) -> str:
    from kiln.sdf import rotation_matrix

    m = rotation_matrix((look.sun_pitch, look.sun_yaw, 0.0))
    rows = ", ".join(f"{m[r, c]:.6g}" for r in range(3) for c in range(3))  # Godot's text format is row-major
    return f"Transform3D({rows}, 0, 10, 0)"


# --- running Godot -------------------------------------------------------------------------------------


def find_godot_binary() -> str | None:
    candidate = os.environ.get("GODOT")
    if candidate:
        return candidate
    for name in ("godot", "godot4"):
        found = shutil.which(name)
        if found:
            return found
    return None


@dataclass
class GodotCheck:
    ok: bool
    output: str
    models: int = 0


def _sandbox(godot_root: Path, folder_res: str, tmp: Path) -> Path:
    """A throwaway Godot project holding a copy of KILN's output at the same res:// path, so checking and rendering
    never import (and rewrite .import files of) anything else in the game's project."""
    rel = folder_res.removeprefix("res://").strip("/")
    root = tmp / "project"
    shutil.copytree(godot_root / rel, root / rel)  # with the .import settings KILN writes (Godot reimports in the copy)
    renderer = ""
    host = (godot_root / "project.godot").read_text(encoding="utf-8", errors="replace")
    match = re.search(r'^renderer/rendering_method="[^"]*"$', host, re.MULTILINE)
    if match:
        renderer = f"\n[rendering]\n\n{match.group(0)}\n"
    (root / "project.godot").write_text(f'config_version=5\n\n[application]\n\nconfig/name="kiln check"\n{renderer}', encoding="utf-8")
    return root


def _characters(project: Path, attachments: dict[str, Path]) -> str:
    """Copy the characters attachments are fitted to into the sandbox (with the files they refer to); returns the
    res:// path of a JSON file mapping each attachment to its character's scene."""
    from kiln.importer import external_files

    folders: dict[Path, str] = {}
    scenes: dict[str, str] = {}
    for model, source in sorted(attachments.items()):
        if source not in folders:  # one folder per file: KayKit's and Kenney's texture names collide
            folders[source] = f"kiln_characters/{len(folders)}"
            target = project / folders[source]
            target.mkdir(parents=True)
            shutil.copy(source, target / source.name)
            for rel in external_files(source):
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(source.parent / rel, target / rel)
        scenes[model] = f"res://{folders[source]}/{source.name}"
    (project / "kiln_characters.json").write_text(json.dumps(scenes, sort_keys=True), encoding="utf-8")
    return "res://kiln_characters.json"


def _folder(res: str) -> str:
    """The output folder of a res:// path inside it (models/, looks/ or the manifest's own folder)."""
    parent = res.rsplit("/", 1)[0]
    return parent.rsplit("/", 1)[0] if parent.endswith(("/models", "/looks")) else parent


def verify(godot: str, godot_root: Path, manifest_res: str, attachments: dict[str, Path] | None = None, timeout: int = 300) -> GodotCheck:
    """Load everything KILN built in a sandbox copy of the output. `attachments` (model -> the character file it's fitted
    to) also hangs each attachment on its bone of that character (a BoneAttachment3D) and checks it lands where it was
    made."""
    script = files("kiln").joinpath("templates", "godot_verify.gd").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="kiln-verify-") as tmp:
        path = Path(tmp) / "kiln_verify.gd"
        path.write_text(script, encoding="utf-8")
        project = _sandbox(godot_root, _folder(manifest_res), Path(tmp))
        characters = _characters(project, attachments or {})
        try:
            subprocess.run([godot, "--headless", "--path", str(project), "--import"], capture_output=True, text=True, timeout=timeout)
            run = subprocess.run([godot, "--headless", "--path", str(project), "-s", str(path), "--", manifest_res, characters],
                                 capture_output=True, text=True, timeout=timeout)  # fmt: skip
        except (OSError, subprocess.TimeoutExpired) as exc:
            return GodotCheck(False, f"couldn't run Godot: {exc}")
    output = (run.stdout + run.stderr).strip()
    match = re.search(r"KILN_VERIFY_OK (\d+)", run.stdout)
    ok = run.returncode == 0 and match is not None and "SCRIPT ERROR" not in output and "SHADER ERROR" not in output
    return GodotCheck(ok, output, int(match.group(1)) if match else 0)


def render_engine(godot: str, godot_root: Path, scene_res: str, look_res: str, views: list[tuple[float, float]], radius: float,
                  centre_y: float, size: int, out_dir: Path, timeout: int = 300) -> tuple[list[Path], str]:  # fmt: skip
    """Render a model scene under its look kit through Godot (needs a display). Returns (PNGs, output)."""
    script = files("kiln").joinpath("templates", "godot_views.gd").read_text(encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="kiln-views-") as tmp:
        path = Path(tmp) / "kiln_views.gd"
        path.write_text(script, encoding="utf-8")
        pairs = [f"{yaw:g}:{pitch:g}" for yaw, pitch in views]
        project = _sandbox(godot_root, _folder(scene_res), Path(tmp))
        try:
            subprocess.run([godot, "--headless", "--path", str(project), "--import"], capture_output=True, text=True, timeout=timeout)
            run = subprocess.run([godot, "--path", str(project), "-s", str(path), "--", scene_res, look_res, str(out_dir), str(size),
                                  f"{radius:g}", f"{centre_y:g}", *pairs], capture_output=True, text=True, timeout=timeout)  # fmt: skip
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [], f"couldn't run Godot: {exc}"
    output = (run.stdout + run.stderr).strip()
    images = [out_dir / f"engine_{i:02d}.png" for i in range(len(views))]
    if "KILN_VIEWS_OK" not in run.stdout or not all(p.is_file() for p in images):
        return [], output
    return images, output


__all__ = ["ATLAS_SCRIPT", "ATLAS_TOON_SHADER", "GodotCheck", "bone_map_tres", "find_godot_binary", "find_godot_project", "look_scene", "model_scene",
           "outline_shader", "render_engine", "res_path", "rich_toon", "toon_shader", "verify", "with_bone_map"]
