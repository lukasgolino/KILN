"""#230: part color_blend, colours that fade across part borders in the base colour map."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from conftest import load, make_project, write_model
from PIL import Image

from kiln import bake as bk
from kiln.build import build
from kiln.fade import Fade
from kiln.lint import lint_paths
from kiln.project import Project
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
  - ellipsoid: { at: [0, 0.48, 0.13], radii: [0.18, 0.25, 0.15] }
    id: belly
    color: gold
    blend: 0.05
    color_blend: 0.08
  - sphere: { at: [0, 1.05, 0], radius: 0.2 }
    id: head
    color: red
    blend: 0.04
"""
WOOD, GOLD, RED = (np.array(c) for c in ((0xA0, 0x66, 0x3A), (0xF2, 0xC1, 0x4E), (0xE8, 0x41, 0x3C)))


def test_notation(project: Project) -> None:
    model, _, findings = load(project, MODEL)
    assert model is not None and not findings, findings
    assert [p.color_blend for p in model.parts] == [0.0, 0.08, 0.0]
    model, _, findings = load(project, MODEL.replace("normal_map: 256\n", ""))
    assert model is not None and model.normal_map == 1024  # the fade is in the base colour map: the baked maps come on
    for bad in ("-0.1", "2", "soft"):
        _, _, findings = load(project, MODEL.replace("color_blend: 0.08", f"color_blend: {bad}"))
        assert any(f.where == "parts[1].color_blend" for f in findings), findings


def test_the_mix_runs_straight_through_the_border_and_ends_at_the_reach() -> None:
    edge = np.array([[[0.0, -1.0, 0.0], [0.0, 1.0, 0.0]]])  # one border edge along y: part 0 (group 0) and part 1 (group 1) meet
    up = np.array([[0.0, 0.0, 1.0]])
    fade = Fade(edge, np.array([[0, 1]]), np.array([[0, 1]]), up, np.array([0.1]), np.array([0, 1, 2]))  # faces 0, 1, 2: parts 0, 1, 2
    xs = np.array([0.0, 0.025, 0.05, 0.1, 0.2])
    points = np.stack([xs, np.zeros_like(xs), np.zeros_like(xs)], axis=1)
    ups = np.tile(up, (len(xs), 1))
    other, weight = fade.mix(points, np.zeros(len(xs), dtype=np.int64), ups)
    assert weight[0] == 0.5 and (np.diff(weight) <= 0).all() and weight[3] == 0 and weight[4] == 0
    assert 0.2 < weight[1] < 0.35 and (other[:3] == 1).all()
    back, w2 = fade.mix(-points, np.ones(len(xs), dtype=np.int64), ups)  # the other side fades toward the first group
    assert (back[:3] == 0).all() and np.allclose(w2, weight)
    _, none = fade.mix(points, np.full(len(xs), 2), ups)  # a third part passing near the border: untouched
    assert (none == 0).all()
    _, far_side = fade.mix(points, np.zeros(len(xs), dtype=np.int64), -ups)  # the back of a thin part: untouched
    assert (far_side == 0).all()
    assert fade.touches(points)[:4].all() and len(fade.ends) == 20  # a 2 m edge with a 0.1 m reach: 20 pieces, none missed
    assert not fade.touches(np.array([[0.5, 0.0, 0.0]]))[0]


def colours(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).reshape(-1, 3).astype(int)


def near(img: np.ndarray, c: np.ndarray, tol: int = 8) -> np.ndarray:
    return np.asarray(np.abs(img - c).sum(axis=1) < tol)


def test_build_fades_the_belly_only_toward_the_body(project: Project) -> None:
    write_model(project, MODEL + "variants:\n  other: { swap: { gold: blue } }\n")
    result = build(project)
    assert not result.errors, result.findings
    models = project.output_dir / "models"
    img = colours((models / "thing.color.png").read_bytes())
    pure = near(img, WOOD) | near(img, GOLD) | near(img, RED) | near(img, np.array([128, 128, 128]))
    between = img[~pure]
    assert len(between) > 300  # a band of mixed colours ...
    lo, hi = np.minimum(WOOD, GOLD) - 12, np.maximum(WOOD, GOLD) + 12
    assert ((between >= lo) & (between <= hi)).all(axis=1).mean() > 0.9  # ... between the belly's and the body's, none toward red
    assert near(img, GOLD).sum() > 200 and near(img, WOOD).sum() > 1000 and near(img, RED).sum() > 300
    doc, _ = read_glb((models / "thing.glb").read_bytes())
    assert [m["name"].split("#")[0] for m in doc["materials"]] == ["default_mapped"]
    swapped = colours((models / "thing.other.color.png").read_bytes())
    assert near(swapped, GOLD).sum() == 0 and near(swapped, np.array([0x2F, 0x6F, 0xD0])).sum() > 200


def test_without_color_blend_there_is_no_colour_map_and_the_normal_map_is_the_same(project: Project) -> None:
    built = lint_paths(project, [write_model(project, MODEL.replace("    color_blend: 0.08\n", ""))]).built["thing"]
    assert built.bake is not None and built.bake.layers is None  # no colour map: materials per colour as before
    faded = lint_paths(project, [write_model(project, MODEL)]).built["thing"]
    lay = faded.bake.layers
    assert lay is not None and lay.mix is not None and lay.other is not None and (lay.mix > 0).sum() > 300 and lay.mix.max() <= 128
    assert built.bake.png == faded.bake.png  # the normal map is the same


def mixed(project: Project, text: str) -> tuple[int, list[str]]:
    result = lint_paths(project, [write_model(project, text)])
    lay = result.built["thing"].bake.layers
    return (0 if lay is None or lay.mix is None else int((lay.mix > 0).sum())), [f.rule for f in result.findings]


def test_a_crisp_seam_a_glowing_part_and_a_same_coloured_neighbour_do_not_fade(project: Project) -> None:
    assert mixed(project, MODEL)[0] > 300 and "W127" not in mixed(project, MODEL)[1]
    # the belly set on with a crisp seam: its border stays sharp, and lint says the fade does nothing
    count, rules = mixed(project, MODEL.replace("    blend: 0.05\n    color_blend", "    blend: 0\n    color_blend"))
    assert count == 0 and "W127" in rules
    count, rules = mixed(project, MODEL.replace("    color: gold\n", "    color: wood\n"))  # the body's own colour
    assert count == 0 and "W127" in rules
    style = project.root / "styles" / "fast.style.toml"
    style.write_text(style.read_text() + "\n[materials.lamp]\nemission = 2.0\n")
    from kiln.project import load_project

    glowing = MODEL.replace("    color: gold\n", "    color: gold\n    material: lamp\n")
    count, rules = mixed(load_project(project.root), glowing)
    assert count == 0 and "W127" in rules


def test_a_part_that_does_not_ask_stays_sharp_next_to_one_that_fades(project: Project) -> None:
    """A nose on a fading muzzle: the nose joins with a crisp seam, so none of its texels (or the muzzle's toward
    it) are mixed."""
    text = MODEL + "  - sphere: { at: [0, 0.5, 0.29], radius: 0.05 }\n    id: nose\n    color: black\n"
    result = lint_paths(project, [write_model(project, text)])
    built = result.built["thing"]
    lay = built.bake.layers
    face, texel, _ = bk._texels(built.bake.uv, built.bake.size, built.bake.size)
    group = built.painted.face_group[face]
    black = [k for k, g in enumerate(built.painted.groups) if g.color == "#141414"]
    is_black = np.isin(group, black)
    mix, other = lay.mix.reshape(-1)[texel], lay.other.reshape(-1)[texel]
    assert is_black.sum() > 30 and (mix[is_black] == 0).all()
    assert not np.isin(other[mix > 0], black).any() and (mix > 0).sum() > 300


def test_notation_refuses_color_blend_where_it_cannot_work(project: Project) -> None:
    for extra in ("    detail: true\n", "    hard: true\n"):
        _, _, findings = load(project, MODEL.replace("    color_blend: 0.08\n", "    color_blend: 0.08\n" + extra))
        assert any(f.rule == "E003" and f.where == "parts[1].color_blend" for f in findings), (extra, findings)
    _, _, findings = load(project, MODEL + "  - sphere: { at: [0, 0.5, 0.3], radius: 0.05 }\n    cut: true\n    color_blend: 0.05\n")
    assert any(f.rule == "E003" and f.where == "parts[3].color_blend" for f in findings), findings
    model, _, findings = load(project, MODEL.replace("normal_map: 256\n", "normal_strength: 0.5\n"))  # the fade brings the map
    assert model is not None and not findings and model.normal_strength == 0.5
    _, _, findings = load(project, MODEL.replace("normal_map: 256\n", "normal_strength: 0.5\n").replace("color_blend: 0.08", "color_blend: 0"))
    assert any(f.where == "normal_strength" for f in findings)


def test_under_fur_the_fade_goes_toward_the_fur_colour(project: Project, tmp_path: Path) -> None:
    def woody(text: str, root: Path) -> float:
        proj = make_project(root)
        write_model(proj, text + "relief:\n  - on: [body]\n    length: 0.1\n    width: 0.06\n    density: 3\n    color: blue\n    fade: 0\n")
        assert not build(proj).errors
        img = colours((proj.output_dir / "models" / "thing.color.png").read_bytes())
        return float(near(img, WOOD, 60).mean())  # the body's bare paint, showing

    # the body is blue fur: the belly's fade must not pull the bare wood colour through it
    assert woody(MODEL, tmp_path / "a") <= woody(MODEL.replace("    color_blend: 0.08\n", ""), tmp_path / "b") + 0.002
