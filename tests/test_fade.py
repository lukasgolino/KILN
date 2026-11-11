"""#230: part color_blend, colours that fade across part borders in the base colour map."""

from __future__ import annotations

import io

import numpy as np
import pytest
from conftest import load, write_model
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
    edge = np.array([[[0.0, -1.0, 0.0], [0.0, 1.0, 0.0]]])  # one border edge along y; groups 0 and 1 either side, 2 elsewhere
    fade = Fade(edge, np.array([[0, 1]]), np.array([0.1]), ["#111111", "#222222", "#333333"])
    xs = np.array([0.0, 0.025, 0.05, 0.1, 0.2])
    points = np.stack([xs, np.zeros_like(xs), np.zeros_like(xs)], axis=1)
    other, weight = fade.mix(points, np.zeros(len(xs), dtype=np.int64))
    assert weight[0] == 0.5 and (np.diff(weight) <= 0).all() and weight[3] == 0 and weight[4] == 0
    assert 0.2 < weight[1] < 0.35 and (other[:3] == 1).all()
    back, w2 = fade.mix(-points, np.ones(len(xs), dtype=np.int64))  # the other side fades toward the first group
    assert (back[:3] == 0).all() and np.allclose(w2, weight)
    _, none = fade.mix(points, np.full(len(xs), 2))  # a colour that isn't on this border: untouched
    assert (none == 0).all()
    assert fade.touches(points)[:4].all() and len(fade.ends) == 20  # a 2 m edge with a 0.1 m reach: 20 pieces, none missed
    assert not fade.touches(np.array([[0.5, 0.0, 0.0]]))[0]


def colours(png: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB")).reshape(-1, 3).astype(int)


def near(img: np.ndarray, c: np.ndarray, tol: int = 8) -> np.ndarray:
    return np.asarray(np.abs(img - c).sum(axis=1) < tol)


def test_build_fades_the_belly_and_keeps_the_head_border_crisp(project: Project) -> None:
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


def test_without_color_blend_nothing_changes(project: Project) -> None:
    built = lint_paths(project, [write_model(project, MODEL.replace("    color_blend: 0.08\n", ""))]).built["thing"]
    assert built.bake is not None and built.bake.layers is None  # no colour map: materials per colour as before
    faded = lint_paths(project, [write_model(project, MODEL)]).built["thing"]
    lay = faded.bake.layers
    assert lay is not None and lay.mix is not None and lay.other is not None and (lay.mix > 0).sum() > 300 and lay.mix.max() <= 128
    assert built.bake.png == faded.bake.png  # the normal map is the same
