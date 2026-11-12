"""#229: relief layers, fur patches lying on the surface in the baked maps (no parts, no triangles)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import load, make_project, ok_model, write_model
from PIL import Image

from kiln import bake as bk
from kiln import relief as rl
from kiln.build import build
from kiln.gltf_check import check_glb
from kiln.mesher import decimate, dual_contour
from kiln.notation import Relief
from kiln.project import Project
from kiln.render import View, render
from kiln.sdf import Field, Geometry
from kiln.vendor.gltf import read_glb

pytestmark = pytest.mark.skipif(not bk.available(), reason="xatlas not installed (kiln-gen[bake])")

MODEL = """\
name: thing
class: creature
normal_map: 256
parts:
  - ellipsoid: { at: [0, 0.5, 0], radii: [0.3, 0.45, 0.25] }
    id: body
    color: wood
  - sphere: { at: [0, 1.05, 0], radius: 0.2 }
    id: head
    color: red
    blend: 0.04
relief:
  - on: [body]
    length: 0.12
    width: 0.08
    lift: 0.01
    density: 1.5
"""
EGG = Field([Geometry("ellipsoid", {"radii": [0.3, 0.5, 0.25]})], margin=0.03)


def egg() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = decimate(EGG, dual_contour(EGG, 0.03), 3000, 0.03)
    n = EGG.gradient(m.vertices, 0.002)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    return m.vertices, m.faces, n[m.faces]


def lower(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    return np.asarray(vertices[faces].mean(axis=1)[:, 1] < 0.1)


def test_notation_defaults_and_the_bare_on_key(project: Project) -> None:
    model, _, findings = load(project, MODEL)
    assert model is not None and not findings, findings
    (layer,) = model.relief
    assert layer.on == ["body"] and (layer.length, layer.width, layer.lift, layer.density) == (0.12, 0.08, 0.01, 1.5)
    assert (layer.kind, layer.flow, layer.tips, layer.seed, layer.color) == ("fur", "down", 3, 1, None)
    model, _, findings = load(project, MODEL.replace("normal_map: 256\n", ""))
    assert model is not None and model.normal_map == 1024  # relief turns the baked maps on


@pytest.mark.parametrize(("old", "new", "where"), [
    ("on: [body]", "on: [tail]", "relief[0].on"),
    ("on: [body]", "on: 3", "relief[0].on"),
    ("length: 0.12", "length: 9", "relief[0].length"),
    ("density: 1.5", "density: 1.5\n    tips: 0", "relief[0].tips"),
    ("density: 1.5", "density: 1.5\n    flow: sideways", "relief[0].flow"),
    ("density: 1.5", "density: 1.5\n    kind: plates", "relief[0].kind"),
    ("density: 1.5", "density: 1.5\n    colour: red", "relief[0].colour"),
    ("density: 1.5", "density: 1.5\n    color: nope", "relief[0].color"),
    ("density: 1.5", "density: 1.5\n    color_to: red", "relief[0].color_to"),
    ("relief:\n  - on: [body]\n    length: 0.12\n    width: 0.08\n    lift: 0.01\n    density: 1.5\n", "relief: fur\n", "relief"),
])  # fmt: skip
def test_notation_errors(project: Project, old: str, new: str, where: str) -> None:
    assert old in MODEL
    _, _, findings = load(project, MODEL.replace(old, new))
    assert any(f.severity == "error" and f.where == where for f in findings), findings


def test_scatter_is_stable_stays_on_its_faces_and_follows_density() -> None:
    v, f, n = egg()
    on = lower(v, f)
    layer = Relief(["body"], length=0.1, width=0.06, fade=0.0)
    a, b = rl.scatter(v, f, n, [on], [layer]), rl.scatter(v, f, n, [on], [layer])
    assert len(a) > 20 and np.array_equal(a.centre, b.centre) and np.array_equal(a.flow, b.flow)
    assert a.centre[:, 1].max() < 0.1 + 0.03  # roots only on the covered faces (the lower part), to a mesh cell
    gap = np.linalg.norm(a.centre[:, None] - a.centre[None], axis=2) + np.eye(len(a)) * 9
    assert gap.min() > 0.5 * np.sqrt(rl.COVER * 0.1 * 0.06)  # spread evenly: no two roots on top of each other
    dense = rl.scatter(v, f, n, [on], [Relief(["body"], length=0.1, width=0.06, fade=0.0, density=3.0)])
    assert 2.2 < len(dense) / len(a) < 3.8
    other = rl.scatter(v, f, n, [on], [Relief(["body"], length=0.1, width=0.06, fade=0.0, seed=2)])
    assert not np.array_equal(other.centre[:5], a.centre[:5])
    # each patch lies in the surface, pointing down it
    assert np.abs((a.flow * a.normal).sum(axis=1)).max() < 1e-9 and np.allclose(np.linalg.norm(a.flow, axis=1), 1.0)
    assert (a.flow[:, 1] < 0).mean() > 0.95


def test_fade_thins_and_shrinks_patches_toward_the_edge() -> None:
    v, f, n = egg()
    on = lower(v, f)
    hard = rl.scatter(v, f, n, [on], [Relief(["body"], length=0.1, width=0.06, fade=0.0, jitter=0.0)])
    soft = rl.scatter(v, f, n, [on], [Relief(["body"], length=0.1, width=0.06, fade=0.25, jitter=0.0)])
    def band(p: rl.Patches) -> np.ndarray:  # the 0.2 m under the edge at y = 0.1
        return np.asarray(p.centre[:, 1] > -0.1)

    assert band(soft).sum() < 0.75 * band(hard).sum()
    assert soft.length[band(soft)].mean() < 0.9 * soft.length[~band(soft)].mean()
    lies = np.sqrt(np.maximum(0.0, 1.0 - hard.normal[:, 1] ** 2)) >= rl.FLOW_LIES  # (where the flow lies in the surface)
    assert lies.sum() > 0.8 * len(lies) and np.allclose(hard.length[lies], 0.1)


def test_no_stepped_patches_where_the_surface_faces_the_flow() -> None:
    """#303: on the bottom of an egg under flow: down (the surface faces the flow) patches thin out and shrink; none
    stands where the flow can't point."""
    v, f, n = egg()
    on = lower(v, f)
    p = rl.scatter(v, f, n, [on], [Relief(["body"], length=0.1, width=0.06, fade=0.0, jitter=0.0)])
    lying = np.sqrt(np.maximum(0.0, 1.0 - p.normal[:, 1] ** 2))
    assert len(p.length) > 50 and lying.min() >= rl.FLOW_FLAT
    facing = lying < rl.FLOW_LIES
    assert facing.any() and p.length[facing].mean() < 0.1


def test_a_patch_rises_to_its_notched_tip_and_shades_the_surface_below() -> None:
    one = rl.Patches(np.zeros((1, 3)), np.array([[0.0, 0.0, 1.0]]), np.array([[0.0, -1.0, 0.0]]), np.array([[1.0, 0.0, 0.0]]),
                     np.array([0.1]), np.array([0.03]), np.array([0.01]), np.array([3]), np.array([0.5]), np.array([0]), [("#804020", "#c08040")])  # fmt: skip
    ys = np.linspace(0.02, -0.16, 181)
    line = np.stack([np.zeros_like(ys), ys, np.zeros_like(ys)], axis=1)  # down the middle tip
    up = np.tile([[0.0, 0.0, 1.0]], (len(line), 1))
    st, moved = rl.stamp(one, line, up, np.array([np.tile([[0.0, -0.001, 0.0]], (len(line), 1))]))
    h = st.height
    assert h[ys > 0].max() == 0 and h[ys < -0.11].max() == 0  # nothing above the root or past the tip
    assert 0.008 < h.max() <= 0.01 and ys[np.argmax(h)] < -0.08  # highest just before the tip
    assert (np.diff(h[(ys < -0.005) & (ys > -0.08)]) > 0).all()  # a steady rise from the root
    assert st.shade[(ys < -0.105) & (ys > -0.12)].min() < 0.75 and st.shade[ys > -0.09].min() == 1.0  # the band under the tip
    assert moved.shape == (1, len(line)) and np.allclose(moved[0][:-1], h[1:], atol=1e-9)
    notch = np.array([[0.01, -0.09, 0.0], [0.0, -0.09, 0.0]])  # between two tips the patch ends sooner
    hn = rl.stamp(one, notch, up[:2])[0].height
    assert hn[0] == 0 and hn[1] > 0.005
    back = rl.stamp(one, line, -up)[0]  # the far side of a thin limb: not touched
    assert back.height.max() == 0 and back.shade.min() == 1.0
    col = rl.colour(st, np.full((len(line), 3), 0.5), one.colors)
    on_patch = st.entry == 0
    assert on_patch.any() and (col[on_patch][-1] > col[on_patch][0]).all()  # the ramp runs lighter to the tip
    assert np.allclose(col[ys > 0.001], 0.5)


def built_files(project: Project) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted((project.output_dir / "models").iterdir())}


def test_build_writes_the_maps_and_one_mapped_material(project: Project, tmp_path: Path) -> None:
    write_model(project, MODEL + "variants:\n  other: { swap: { wood: blue } }\n")
    result = build(project)
    assert not result.errors, result.findings
    files = built_files(project)
    assert {"thing.glb", "thing.normal.png", "thing.color.png", "thing.other.color.png", "thing.other.glb"} <= set(files)
    assert not check_glb(files["thing.glb"])
    doc, _ = read_glb(files["thing.glb"])
    (material,) = doc["materials"]  # both colours are in the map: one material for the preset
    assert material["name"].startswith("default_mapped") and "normalTexture" in material
    assert material["pbrMetallicRoughness"]["baseColorFactor"] == [1.0, 1.0, 1.0, 1.0]
    assert sorted(i["uri"] for i in doc["images"]) == ["thing.color.png", "thing.normal.png"]
    other, _ = read_glb(files["thing.other.glb"])
    assert sorted(i["uri"] for i in other["images"]) == ["thing.normal.png", "thing.other.color.png"]
    entry = result.manifest["models"]["thing"]
    assert entry["color_map"]["png"] == "models/thing.color.png" and entry["color_map"]["size"] == [256, 256]
    assert entry["color_map"]["patches"] > 10 and entry["variants"]["other"]["color_map"]["png"] == "models/thing.other.color.png"
    colour = np.asarray(Image.open(io.BytesIO(files["thing.color.png"])).convert("RGB")).reshape(-1, 3).astype(int)
    swapped = np.asarray(Image.open(io.BytesIO(files["thing.other.color.png"])).convert("RGB")).reshape(-1, 3).astype(int)
    wood, red, blue = np.array([0xA0, 0x66, 0x3A]), np.array([0xE8, 0x41, 0x3C]), np.array([0x2F, 0x6F, 0xD0])
    def near(img: np.ndarray, c: np.ndarray, tol: int = 40) -> np.ndarray:
        return np.asarray(np.abs(img - c).sum(axis=1) < tol)

    assert near(colour, wood).mean() > 0.1 and near(colour, red, 6).mean() > 0.03 and near(colour, blue).mean() == 0
    assert near(swapped, blue).mean() > 0.1 and near(swapped, wood).mean() == 0 and near(swapped, red, 6).mean() > 0.03
    shades = len(np.unique(colour[near(colour, wood, 120)], axis=0))
    assert shades > 20  # lighter tips, darker under them: not one flat colour
    # the same model without the layer: a flatter normal map, no colour map
    plain = make_project(tmp_path / "plain")
    write_model(plain, MODEL.split("relief:")[0])
    assert not build(plain).errors
    flat = built_files(plain)
    assert "thing.color.png" not in flat
    def tilt(png: bytes) -> float:
        return float(np.abs(np.asarray(Image.open(io.BytesIO(png))).astype(int)[:, :, :2] - 128).mean())

    assert tilt(files["thing.normal.png"]) > tilt(flat["thing.normal.png"]) + 2


def test_two_builds_are_identical(tmp_path: Path) -> None:
    out = []
    for name in ("a", "b"):
        project = make_project(tmp_path / name)
        write_model(project, MODEL)
        assert not build(project).errors
        out.append(built_files(project))
    assert out[0].keys() == out[1].keys() and all(out[0][k] == out[1][k] for k in out[0])


def test_preview_shows_the_colour_map(project: Project) -> None:
    from kiln.lint import lint_paths

    text = MODEL.replace("    density: 1.5\n", "    density: 1.5\n    color: blue\n    color_to: green\n")
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    assert built.bake is not None and built.bake.layers is not None
    image = np.asarray(render(built, View(0.0, 10.0), 128).convert("RGB")).astype(int)
    body = image[70:110, 44:84].reshape(-1, 3)
    assert (body[:, 2] > body[:, 0] + 20).mean() > 0.3 or (body[:, 1] > body[:, 0] + 20).mean() > 0.3  # blue-green fur, not wood


def test_godot_scene_reads_the_colour_map_in_the_toon_shader(tmp_path: Path) -> None:
    (tmp_path / "project.godot").write_text("config_version=5\n")
    config = 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "../assets/kiln"\nexport = ["glb", "godot"]\n'
    project = make_project(tmp_path / "art", config)
    write_model(project, MODEL)
    write_model(project, MODEL.split("relief:")[0].replace("name: thing", "name: plain"), "plain")
    assert not build(project).errors
    models = project.output_dir / "models"
    assert "color_texture" in (models / "thing.tscn").read_text() and "color_texture" not in (models / "plain.tscn").read_text()


def test_patches_stay_on_the_parts_they_are_on(project: Project) -> None:
    """A head next to a furred body, not in `on`: no patch, no shade, on any of its texels (roots apart, the tiles
    themselves must not spill over)."""
    from kiln.lint import lint_paths

    text = MODEL.replace("    density: 1.5\n", "    density: 1.5\n    fade: 0\n    color: blue\n")
    result = lint_paths(project, [write_model(project, text)])
    built = result.built["thing"]
    lay = built.bake.layers
    face, texel, _ = bk._texels(built.bake.uv, built.bake.size, built.bake.size)
    red = np.array([g.color == "#e8413c" for g in built.painted.groups])[built.painted.face_group[face]]
    entry, shade = lay.entry.reshape(-1)[texel], lay.shade.reshape(-1)[texel]
    assert red.sum() > 500 and (entry[red] == -1).all() and (shade[red] == 255).all()
    assert (entry[~red] == 0).mean() > 0.5  # and the body is furred
    assert lay.patches == [sum(lay.patches)] and lay.patches[0] > 10 and not [f for f in result.findings if f.rule == "W126"]


def test_a_layer_with_no_surface_warns_and_glowing_parts_stay_bare(project: Project) -> None:
    from kiln.lint import lint_paths

    style = project.root / "styles" / "fast.style.toml"
    style.write_text(style.read_text() + "\n[materials.lamp]\nemission = 2.0\n")
    from kiln.project import load_project

    proj = load_project(project.root)
    text = MODEL.replace("    id: head\n    color: red\n", "    id: head\n    color: red\n    material: lamp\n")
    text += "  - on: [head]\n    length: 0.05\n    width: 0.03\n"
    result = lint_paths(proj, [write_model(proj, text)])
    assert result.built["thing"].bake.layers.patches[1] == 0
    assert [f.rule for f in result.findings if f.rule == "W126"] == ["W126"]


def test_normal_strength_goes_with_relief_and_scales_it(project: Project, tmp_path: Path) -> None:
    def tilt(strength: str, root: Path) -> float:
        proj = make_project(root)
        write_model(proj, MODEL.replace("normal_map: 256\n", "normal_map: 256\n" + strength))
        result = build(proj)
        assert not result.errors, result.findings
        png = (proj.output_dir / "models" / "thing.normal.png").read_bytes()
        return float(np.abs(np.asarray(Image.open(io.BytesIO(png))).astype(int)[:, :, :2] - 128).mean())

    full, half = tilt("", tmp_path / "a"), tilt("normal_strength: 0.5\n", tmp_path / "b")
    assert half < 0.8 * full
    model, _, findings = load(project, MODEL.replace("normal_map: 256\n", "normal_strength: 0.5\n"))  # relief brings the map
    assert model is not None and not findings and model.normal_strength == 0.5


def test_variant_scenes_whatever_the_colour_mode(tmp_path: Path) -> None:
    (tmp_path / "project.godot").write_text("config_version=5\n")
    config = ('default_style = "fast"\ndefault_palette = "main"\noutput_dir = "../assets/kiln"\nexport = ["glb", "godot"]\n'
              "vertex_colors = true\nvariant_glbs = false\n")  # fmt: skip
    project = make_project(tmp_path / "art", config)
    write_model(project, MODEL + "variants:\n  other: { swap: { wood: blue } }\n")
    result = build(project)
    assert not result.errors, result.findings
    models = project.output_dir / "models"
    assert (models / "thing.other.tscn").is_file() and "thing.other.glb" in (models / "thing.other.tscn").read_text()
    assert result.manifest["models"]["thing"]["variants"]["other"]["color_map"]["png"] == "models/thing.other.color.png"


def test_darken_outlines_take_the_colour_from_the_map() -> None:
    from dataclasses import replace

    from kiln.godot import model_scene
    from kiln.style import load_style

    style, _ = load_style("soft_toy")
    assert style is not None
    style = replace(style, look=replace(style.look, shader="toon", outline=0.01, outline_color="darken"))
    scene = model_scene("thing", "res://thing.glb", style, color_map=True)
    assert scene.count("texture(color_texture, UV)") == 2 and scene.count("color_texture") == 6  # toon and outline: uniform, sample, set
    assert "color_texture" not in model_scene("thing", "res://thing.glb", style)


def test_too_many_patches_is_an_error() -> None:
    v, f, n = egg()
    with pytest.raises(ValueError, match="patches"):
        rl.scatter(v, f, n, [np.ones(len(f), dtype=bool)], [Relief(["body"], length=0.005, width=0.005, density=6.0)])


def test_layers_pack_small_in_the_cache(project: Project) -> None:
    import pickle

    from kiln.lint import lint_paths

    lay = lint_paths(project, [write_model(project, MODEL)]).built["thing"].bake.layers
    packed = pickle.dumps(lay)
    back = pickle.loads(packed)  # noqa: S301
    assert len(packed) < 0.5 * (lay.group.nbytes + lay.entry.nbytes + lay.along.nbytes + lay.shade.nbytes)
    assert all(np.array_equal(getattr(lay, k), getattr(back, k)) for k in ("group", "entry", "along", "shade")) and back.patches == lay.patches


@pytest.mark.parametrize("select", ["on_colors: [wood]", "on: [body, head]\n    except: [head]", "on_colors: wood\n    on: [body, head]"])
def test_relief_by_colour_or_with_except(project: Project, select: str) -> None:
    """#301: a layer picks its faces by painted colour (on_colors) or leaves ids bare (except), no extra bones."""
    from kiln.lint import lint_paths

    text = MODEL.replace("  - on: [body]\n", f"  - {select}\n").replace("    density: 1.5\n", "    density: 1.5\n    fade: 0\n")
    result = lint_paths(project, [write_model(project, text)])
    assert not result.errors, result.findings
    built = result.built["thing"]
    lay = built.bake.layers
    face, texel, _ = bk._texels(built.bake.uv, built.bake.size, built.bake.size)
    red = np.array([g.color == "#e8413c" for g in built.painted.groups])[built.painted.face_group[face]]
    entry = lay.entry.reshape(-1)[texel]
    assert red.sum() > 500 and (entry[red] == -1).all() and (entry[~red] == 0).mean() > 0.5


def test_relief_selection_errors(project: Project) -> None:
    from conftest import errors_of

    for select, where in (("except: [nope]", "relief[0].on"), ("on_colors: [mauve]", "relief[0].on_colors"), ("on: []", "relief[0].on")):
        text = MODEL.replace("  - on: [body]\n", f"  - on: [body]\n    {select}\n" if not select.startswith("on:") else f"  - {select}\n")
        assert any(f.where == where for f in errors_of(project, text)), select


def _one(kind: int) -> rl.Patches:
    return rl.Patches(np.zeros((1, 3)), np.array([[0.0, 0.0, 1.0]]), np.array([[0.0, -1.0, 0.0]]), np.array([[1.0, 0.0, 0.0]]),
                      np.array([0.1]), np.array([0.03]), np.array([0.01]), np.array([3]), np.array([0.5]), np.array([0]),
                      [(None, None)], [kind])  # fmt: skip


def test_kinds_draw_their_own_outlines() -> None:
    """#261: scales a round lobe, feathers one point, shingles a straight edge, fur notched tips."""
    side = np.array([[0.027, -0.05, 0.0]])  # 0.9 of the half width out, half way down the patch
    middle = np.array([[0.0, -0.085, 0.0]])  # near the tip line in the middle
    h = {k: (rl._profile(_one(k), 0, side)[0][0], rl._profile(_one(k), 0, middle)[0][0]) for k in range(4)}
    assert h[3][0] > 0 and h[1][0] == 0.0 and h[2][0] == 0.0  # at the side, low down: only shingles (straight edge) still cover
    assert h[1][1] > 0 and h[2][1] > 0  # scales and feathers reach far down the middle


def test_flow_along_follows_a_lying_arm(project: Project) -> None:
    from kiln.lint import lint_paths

    text = """\
name: thing
class: creature
normal_map: 256
parts:
  - ellipsoid: { at: [0, 0.5, 0], radii: [0.2, 0.35, 0.18] }
    id: body
    color: wood
  - capsule: { from: [0.15, 0.6, 0], to: [0.75, 0.6, 0], radius: 0.07 }
    id: arm
    color: wood
    blend: 0.04
relief:
  - on: [arm]
    flow: along
    length: 0.08
    width: 0.05
"""
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    p = built.relief_patches
    out = p.centre[:, 0] > 0.35  # the arm, away from the body
    assert out.sum() > 10 and (p.flow[out][:, 0] > 0.7).mean() > 0.8  # pointing along the arm, out to the hand


def test_displace_moves_the_mesh_out(project: Project) -> None:
    from kiln.lint import lint_paths

    flat = lint_paths(project, [write_model(project, MODEL.replace("name: thing", "name: flat").replace("    lift: 0.01\n", "    lift: 0.03\n"), "flat")]).built["flat"]
    text = MODEL.replace("name: thing", "name: tufty").replace("    lift: 0.01\n", "    lift: 0.03\n    displace: true\n")
    tufty = lint_paths(project, [write_model(project, text, "tufty")]).built["tufty"]
    def widest(b: Any) -> float:  # the body's widest point (below the head)
        v = b.painted.vertices
        return float(np.linalg.norm(v[v[:, 1] < 0.7][:, [0, 2]], axis=1).max())

    assert widest(tufty) > widest(flat) + 0.005


def test_lods_stamp_the_full_builds_patches(project: Project) -> None:
    from kiln.builder import build_cached

    model, style = ok_model(project, MODEL.replace("normal_map: 256\n", "normal_map: 256\nlod: [400]\n"))
    palette, _ = project.palette(model.palette)
    cache = project.root / ".kiln-cache"
    full = build_cached(model, style, palette, cache)
    lod = build_cached(model, style, palette, cache, 400)
    assert full.relief_patches is not None and lod.relief_patches is full.relief_patches or np.array_equal(lod.relief_patches.centre, full.relief_patches.centre)


def test_narrow_patches_warn(project: Project) -> None:
    from kiln.lint import lint_paths

    text = MODEL.replace("    width: 0.08\n", "    width: 0.006\n").replace("    length: 0.12\n", "    length: 0.02\n")
    found = [f for f in lint_paths(project, [write_model(project, text)]).findings if f.rule == "W133"]
    assert len(found) == 1 and found[0].where == "relief[0].width"


def test_scatter_previews_read_the_colour_map(project: Project) -> None:
    """#349: a placed relief model in a scatter sheet shows its colour map (sampled at the corners), not flat paint."""
    from kiln.export import srgb_to_linear
    from kiln.lint import lint_paths
    from kiln.preview import corner_colors

    built = lint_paths(project, [write_model(project, MODEL)]).built["thing"]
    assert built.bake is not None and built.bake.layers is not None
    c = corner_colors(built).reshape(-1, 3)
    flat = np.array([srgb_to_linear(g.color) for g in built.painted.groups])
    off = np.min([np.abs(c - f).sum(axis=1) for f in flat], axis=0) > 0.02
    assert off.mean() > 0.05  # fur colours and shading show


def test_gibs_keep_their_fur(project: Project) -> None:
    """#349: a gib of a relief model gets a quarter-size map with the layers on its parts; one without fur gets none."""
    from kiln.build import gib_models

    text = MODEL.replace("normal_map: 256", "normal_map: 1024") + "rig:\n  body: { gib: [body] }\n  head: { gib: [head] }\n"
    model, _ = ok_model(project, text)
    gibs = dict(gib_models(model))
    assert gibs["body"].normal_map == 256 and [r.on for r in gibs["body"].relief] == [["body"]]
    assert gibs["head"].normal_map == 0 and not gibs["head"].relief
    from kiln.build import build
    from kiln.vendor.gltf import read_glb

    write_model(project, text)
    assert not build(project).errors
    doc, _ = read_glb((project.output_dir / "models" / "thing.gib.body.glb").read_bytes())
    assert len(doc.get("images", [])) == 2  # its normal map and its colour map, embedded
