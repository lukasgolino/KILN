"""Scatters (#16): `scatter:` models placing other models over a flat area, a terrain or a model's top surface, with
density, spacing, rules, jitter and tint; the JSON, the Godot scene of MultiMeshes, lint, preview and build."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
from conftest import errors_of, make_project, ok_model, run_json, sphere_text, write_model

from kiln.build import build
from kiln.godot import find_godot_binary, verify
from kiln.lint import lint_project
from kiln.project import Project
from kiln.scatter import Scatter, Surface, _top_hits, godot_buffer, mesh_frame, place

GODOT_CONFIG = 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "game/assets/kiln"\nexport = ["glb", "godot"]\n'
PROJECT_GODOT = 'config_version=5\n\n[application]\nconfig/name="kiln test"\n\n[rendering]\nrenderer/rendering_method="mobile"\n'

TUFT = """\
name: tuft
class: nature
lod: [60]
parts:
  - cone: { at: [0, 0, 0], radius: 0.12, height: 0.3 }
    color: green
  - sphere: { at: [0, 0.3, 0], radius: 0.06 }
    color: gold
variants:
  dry: { swap: { green: wood } }
"""

ROCK = """\
name: rock
class: nature
parts:
  - box: { at: [0, 0.4, 0], size: [2, 0.8, 1.4], round: 0.1 }
    color: grey
"""

LAND = """\
name: land
terrain:
  size: [48, 32]
  cell: 0.5
  chunk: 16
  lod: []
  shapes:
    - hill: { at: [-12, 0], radius: 9, height: 5 }
    - path: { points: [[-24, 10], [24, 10]], width: 2, edge: 1, depth: 0.2 }
  splat:
    - grass: { color: green }
    - rock: { color: grey, slope: { above: 30, fade: 4 } }
"""

MEADOW = """\
name: meadow
scatter:
  onto: land
  seed: 3
  chunk: 16
  place:
    - model: rock
      density: 0.01
      spacing: 3
      scale: [0.6, 1.0]
      align: 1
    - model: [tuft, tuft.dry]
      density: 1
      spacing: 0.4
      scale: [0.8, 1.2]
      tilt: 8
      sink: 0.02
      tint: { color: gold, amount: 0.4, shade: 0.15 }
      slope: { below: 30 }
      splat: grass
      path: { beyond: 2 }
      lod: [12]
      visible: 40
"""

PATCH = """\
name: patch
scatter:
  onto: flat
  size: [6, 4]
  seed: 1
  place:
    - model: tuft
      density: 3
      rotate: [0, 90]
"""

MOSS = """\
name: moss
scatter:
  onto: rock
  place:
    - model: tuft
      density: 40
      scale: 0.3
      align: 1
      slope: { below: 20 }
"""


def scatter_project(tmp_path: Path, config: str = GODOT_CONFIG) -> Project:
    project = make_project(tmp_path, config)
    (tmp_path / "game").mkdir(exist_ok=True)
    (tmp_path / "game" / "project.godot").write_text(PROJECT_GODOT)
    for text, name in ((TUFT, "tuft"), (ROCK, "rock"), (LAND, "land"), (MEADOW, "meadow"), (PATCH, "patch"), (MOSS, "moss")):
        write_model(project, text, name)
    return project


def surface_of(project: Project, name: str) -> tuple[Scatter, Surface]:
    from kiln.scatter import surface_of as find

    model, _ = ok_model(project, (project.models_dir / f"{name}.kiln.yaml").read_text(), name)
    assert model.scatter is not None
    surface, problems = find(project, model.scatter, project.root / ".kiln-cache")
    assert surface is not None and not problems, problems
    return model.scatter, surface


# --- notation ---------------------------------------------------------------------------------------------------------


def test_parses_a_scatter(project: Project) -> None:
    model, _ = ok_model(project, MEADOW, "meadow")
    s = model.scatter
    assert s is not None and model.cls == "scatter" and model.parts == []
    assert s.onto == "land" and s.seed == 3 and s.chunk == 16 and s.size is None
    assert s.sources == ["rock", "tuft", "tuft.dry"]
    rock, tuft = s.places
    assert rock.spacing == 3 and rock.scale == (0.6, 1.0) and rock.align == 1 and rock.rotate == (0.0, 360.0)
    assert tuft.models == ("tuft", "tuft.dry") and tuft.splat == ("grass",) and tuft.path == (None, 2.0, 1.0)
    assert tuft.tint is not None and tuft.tint.color == "#f2c14e" and tuft.tint.amount == 0.4 and tuft.tint.shade == 0.15
    assert [r.kind for r in tuft.rules] == ["slope"] and tuft.lod == (12.0,) and tuft.visible == 40


@pytest.mark.parametrize(("change", "where", "text"), [
    (("  onto: land\n", "  onto: Land!\n"), "scatter.onto", "onto is"),
    (("  seed: 3\n", "  seed: 3\n  colour: red\n"), "scatter.colour", "unknown field"),
    (("  chunk: 16\n", "  chunk: 0\n"), "scatter.chunk", "chunk is"),
    (("density: 0.01", "density: -1"), "scatter.place[0].density", "density is"),
    (("model: rock", "model: [rock, rock]"), "scatter.place[0].model", "model is"),
    (("spacing: 3\n", "spacing: 3\n      size: 2\n"), "scatter.place[0].size", "unknown field"),
    (("align: 1", "align: 2"), "scatter.place[0].align", "align is"),
    (("scale: [0.6, 1.0]", "scale: [1.0, 0.6]"), "scatter.place[0].scale", "scale is"),
    (("tilt: 8", "tilt: 120"), "scatter.place[1].tilt", "tilt is"),
    (("color: gold, amount", "color: mauve, amount"), "scatter.place[1].tint.color", "unknown colour"),
    (("amount: 0.4", "amount: 4"), "scatter.place[1].tint", "tint is"),
    (("path: { beyond: 2 }", "path: { far: 2 }"), "scatter.place[1].path", "path is"),
    (("lod: [12]", "lod: [12, 6]"), "scatter.place[1].lod", "increasing"),
    (("visible: 40", "visible: 10"), "scatter.place[1].visible", "beyond the last lod"),
    (("slope: { below: 30 }", "slope: { below: 300 }"), "scatter.place[1].slope", "0-90"),
])  # fmt: skip
def test_scatter_errors_say_where(project: Project, change: tuple[str, str], where: str, text: str) -> None:
    assert change[0] in MEADOW
    errors = errors_of(project, MEADOW.replace(change[0], change[1]), "meadow")
    assert any(f.where == where and text in f.message and f.line for f in errors), [f.format() for f in errors]


def test_a_scatter_has_no_parts_and_flat_needs_a_size(project: Project) -> None:
    errors = errors_of(project, MEADOW.replace("scatter:\n", "skin: soft\nscatter:\n"), "meadow")
    assert any(f.where == "skin" and "a scatter has no skin" in f.message for f in errors)
    errors = errors_of(project, PATCH.replace("  size: [6, 4]\n", ""), "patch")
    assert any(f.where == "scatter.onto" and "needs size" in f.message for f in errors)


# --- placing ----------------------------------------------------------------------------------------------------------


def test_flat_placement_is_seeded_and_bounded(project: Project) -> None:
    write_model(project, TUFT, "tuft")
    write_model(project, PATCH, "patch")
    scatter, surface = surface_of(project, "patch")
    a, b = place(scatter, surface), place(scatter, surface)
    assert a.candidates == [72] and a.counts == [72]  # 3 per m^2 over 24 m^2, no rules or spacing
    g = a.groups[0]
    assert np.array_equal(g.transforms, b.groups[0].transforms)
    assert (np.abs(g.transforms[:, 0]) <= 3).all() and (np.abs(g.transforms[:, 2]) <= 2).all() and (g.transforms[:, 1] == 0).all()
    basis = g.transforms[:, 3:12].reshape(-1, 3, 3)  # rows: the model's x, y, z axes
    assert np.allclose(basis[:, 1], [0, 1, 0])  # upright, unscaled
    yaw = np.degrees(np.arctan2(basis[:, 0, 2], basis[:, 0, 0])) % 360  # x axis = (cos, 0, -sin): yaw = -atan2
    assert ((360 - yaw) % 360 <= 90 + 1e-6).all()  # rotate: [0, 90]
    other = place(Scatter(scatter.onto, scatter.places, scatter.size, seed=2), surface)
    assert not np.array_equal(other.groups[0].transforms, g.transforms)
    assert g.chunks == [(0, 0, 0, 72)] and g.colors is None


def test_terrain_rules_spacing_tint_and_variants(project: Project) -> None:
    for text, name in ((TUFT, "tuft"), (ROCK, "rock"), (LAND, "land"), (MEADOW, "meadow")):
        write_model(project, text, name)
    scatter, surface = surface_of(project, "meadow")
    placed = place(scatter, surface)
    assert placed.candidates == [15, 1536]
    rocks = [g for g in placed.groups if g.place == 0]
    tufts = [g for g in placed.groups if g.place == 1]
    assert [g.source for g in tufts] == ["tuft", "tuft.dry"] and all(len(g.transforms) > 50 for g in tufts)
    field_ = surface.field
    every = np.concatenate([g.transforms for g in placed.groups])
    xz = every[:, [0, 2]]
    spacing = np.array([3.0] * sum(len(g.transforms) for g in rocks) + [0.4] * sum(len(g.transforms) for g in tufts))
    d = np.linalg.norm(xz[:, None] - xz[None], axis=-1) + np.eye(len(xz)) * 1e9
    assert (d >= np.maximum(spacing[:, None], spacing[None]) - 1e-3).all()  # the larger spacing of any pair
    for g in tufts:
        x, z = g.transforms[:, 0], g.transforms[:, 2]
        assert np.allclose(g.transforms[:, 1], field_.height(x, z) - 0.02, atol=1e-3)  # on the ground, sunk
        assert (field_.slope(x, z) < 30 + 4).all() and (field_.distance_to_path(x, z) > 2 - 0.5).all()
        assert g.colors is not None and (g.colors <= 1).all() and (g.colors >= 0.85 * 0.6 - 1e-6).all()
        assert [c[:2] for c in g.chunks] == sorted({c[:2] for c in g.chunks}, key=lambda c: (c[1], c[0]))
        assert sum(c[3] for c in g.chunks) == len(g.transforms)
    for g in rocks:  # align 1: up along the ground's normal
        up = g.transforms[:, 6:9] / np.linalg.norm(g.transforms[:, 6:9], axis=1)[:, None]
        assert np.allclose(up, field_.normal(g.transforms[:, 0], g.transforms[:, 2]), atol=1e-3)


def test_editing_one_entry_keeps_the_others(project: Project) -> None:
    for text, name in ((TUFT, "tuft"), (ROCK, "rock"), (LAND, "land")):
        write_model(project, text, name)
    write_model(project, MEADOW.replace("spacing: 3", "spacing: 0"), "meadow")
    before = place(*surface_of(project, "meadow"))
    write_model(project, MEADOW.replace("spacing: 3", "spacing: 0").replace("tilt: 8", "tilt: 20"), "meadow")
    after = place(*surface_of(project, "meadow"))
    assert np.array_equal(before.groups[0].transforms, after.groups[0].transforms)  # the rocks
    assert np.array_equal(before.groups[1].transforms[:, :3], after.groups[1].transforms[:, :3])  # same spots, other lean


def test_top_hits_find_the_top_surface() -> None:
    v = np.array([[-1, 1, -1], [1, 1, -1], [-1, 1, 1], [1, 1, 1], [-1, 0, -1], [1, 0, -1], [-1, 0, 1], [1, 0, 1]], dtype=float)
    faces = np.array([[0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6]])  # a top facing up over a bottom facing down
    found, y, n = _top_hits(v, faces, np.array([0.0, 0.5, 3.0]), np.array([0.0, -0.5, 0.0]))
    assert list(found) == [True, True, False] and list(y[:2]) == [1.0, 1.0] and np.allclose(n[:2], [0, 1, 0])
    found, _, _ = _top_hits(v[[4, 5, 6, 7]], np.array([[0, 1, 2], [1, 3, 2]]), np.array([0.0]), np.array([0.0]))
    assert list(found) == [False]  # only a downward face: nothing to stand on


def test_moss_sits_on_the_rocks_top(project: Project) -> None:
    for text, name in ((TUFT, "tuft"), (ROCK, "rock"), (MOSS, "moss")):
        write_model(project, text, name)
    scatter, surface = surface_of(project, "moss")
    assert surface.kind == "model" and surface.lo[0] == pytest.approx(-1, abs=0.05) and surface.hi[1] == pytest.approx(0.7, abs=0.05)
    placed = place(scatter, surface)
    t = placed.groups[0].transforms
    assert len(t) > 20 and np.allclose(t[:, 1], 0.8, atol=0.02)  # the flat top (slope < 20 leaves the rounded rim)


def test_godot_buffer_rows() -> None:
    t = np.array([[1.0, 2.0, 3.0, 0, 0, -2, 0, 2, 0, 2, 0, 0]])  # yawed 90 degrees, scale 2
    frame = np.eye(4)
    frame[:3, 3] = [0, 0.5, 0]
    rows = godot_buffer(t, frame, np.array([[0.5, 0.6, 0.7]]))
    assert rows.tolist() == [[0, 0, 2, 1, 0, 2, 0, 3, -2, 0, 0, 3, 0.5, 0.6, 0.7, 1]]


# --- build -------------------------------------------------------------------------------------------------------------


def test_build_writes_scatters(tmp_path: Path) -> None:
    project = scatter_project(tmp_path)
    result = build(project)
    assert result.errors == [], [f.format() for f in result.findings]
    models = project.output_dir / "models"
    for name in ("meadow", "patch", "moss"):
        assert (models / f"{name}.scatter.json").is_file() and (models / f"{name}.tscn").is_file()
    entry = result.manifest["models"]["meadow"]
    assert entry["class"] == "scatter" and entry["scatter"] == "models/meadow.scatter.json" and entry["onto"] == "land"
    assert entry["godot_scene"] == "res://assets/kiln/models/meadow.tscn" and "glb" not in entry
    data = json.loads((models / "meadow.scatter.json").read_text())
    assert data["format"] == 1 and data["onto"] == {"kind": "terrain", "model": "land"} and data["area"] == {"min": [-24, -16], "max": [24, 16]}
    groups = {g["node"]: g for g in data["groups"]}
    assert sorted(groups) == ["p0_rock", "p1_tuft", "p1_tuft_dry"] and entry["instances"] == {k: g["count"] for k, g in groups.items()}
    dry = groups["p1_tuft_dry"]
    assert dry["model"] == "tuft" and dry["variant"] == "dry" and dry["godot_scene"] == "res://assets/kiln/models/tuft.dry.tscn"
    assert dry["lods"] == ["models/tuft.lod1.glb"] and dry["lod_distances"] == [12] and dry["visible"] == 40 and len(dry["colors"]) == dry["count"]
    scene = (models / "meadow.tscn").read_text()
    assert scene.count('type="MultiMeshInstance3D"') == sum(len(g["chunks"]) for g in data["groups"])
    assert 'path="res://assets/kiln/models/tuft.lod1.glb"' in scene and "use_colors = true" in scene and ".gd\"" not in scene
    counts = [int(n) for n in re.findall(r"instance_count = (\d+)", scene)]
    assert sum(counts) == sum(g["count"] for g in data["groups"])
    first = data["groups"][0]
    buffer = re.search(r"buffer = PackedFloat32Array\(([^)]*)\)", scene)
    assert buffer is not None
    row = [float(v) for v in buffer.group(1).split(", ")[:12]]
    t = first["instances"][0]
    assert row[3] == pytest.approx(t[0], abs=1e-4) and row[7] == pytest.approx(t[1], abs=1e-4) and row[11] == pytest.approx(t[2], abs=1e-4)
    # deterministic: a second build writes nothing
    again = build(project)
    assert again.written == [] and again.errors == []


def test_scatter_without_godot_writes_json_only(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    for text, name in ((TUFT, "tuft"), (PATCH, "patch")):
        write_model(project, text, name)
    result = build(project)
    assert result.errors == [], [f.format() for f in result.findings]
    files = sorted(p.name for p in (project.output_dir / "models").iterdir())
    assert "patch.scatter.json" in files and "patch.tscn" not in files
    data = json.loads((project.output_dir / "models" / "patch.scatter.json").read_text())
    assert data["onto"] == {"kind": "flat"} and data["groups"][0]["glb"] == "models/tuft.glb" and "godot_scene" not in data["groups"][0]


def test_removed_scatter_files_go(tmp_path: Path) -> None:
    project = scatter_project(tmp_path)
    assert build(project).errors == []
    (project.models_dir / "patch.kiln.yaml").unlink()
    result = build(project)
    assert not (project.output_dir / "models" / "patch.scatter.json").exists() and not (project.output_dir / "models" / "patch.tscn").exists()
    assert "patch" not in result.manifest["models"]


def test_mesh_frame_needs_one_static_mesh(tmp_path: Path) -> None:
    project = scatter_project(tmp_path)
    assert build(project).errors == []
    frame, why = mesh_frame((project.output_dir / "models" / "tuft.glb").read_bytes(), [0.0, 0.25, 0.0])
    assert frame is not None and why == "" and frame[:3, 3].tolist() == [0.0, 0.25, 0.0]


# --- lint ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("change", "where", "text"), [
    (("model: rock", "model: boulder"), "scatter.place[0].model", "no models/boulder"),
    (("model: [tuft, tuft.dry]", "model: [tuft, tuft.wet]"), "scatter.place[1].model", "no variant wet"),
    (("model: rock", "model: land"), "scatter.place[0].model", "is a terrain"),
    (("model: rock", "model: thing"), "scatter.place[0].model", "has a rig"),
    (("lod: [12]", "lod: [12, 20]"), "scatter.place[1].lod", "has 1 LODs"),
    (("splat: grass", "splat: sand"), "scatter.place[1].splat", "the terrain's layers are grass, rock"),
    (("onto: land", "onto: nowhere"), "scatter.onto", "no models/nowhere"),
    (("density: 0.01", "density: 900"), "scatter.place[0].density", "candidates"),
])  # fmt: skip
def test_lint_scatter_problems(tmp_path: Path, change: tuple[str, str], where: str, text: str) -> None:
    from conftest import arms_text

    project = scatter_project(tmp_path)
    write_model(project, arms_text("thing"), "thing")
    write_model(project, MEADOW.replace(change[0], change[1]), "meadow")
    findings = [f for f in lint_project(project).findings if f.rule == "E015"]
    assert any(f.where == where and text in f.message for f in findings), [f.format() for f in findings]


def test_lint_path_rules_need_a_terrain(tmp_path: Path) -> None:
    project = scatter_project(tmp_path)
    write_model(project, PATCH.replace("rotate: [0, 90]", "splat: grass"), "patch")
    findings = [f for f in lint_project(project).findings if f.rule == "E015"]
    assert any(f.where == "scatter.place[0].splat" and "need a terrain" in f.message for f in findings)


def test_lint_warns_about_none_and_many(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import kiln.scatter as sc

    project = scatter_project(tmp_path)
    write_model(project, PATCH.replace("rotate: [0, 90]", "height: { above: 5 }"), "patch")
    monkeypatch.setattr(sc, "MANY_INSTANCES", 100)
    findings = lint_project(project).findings
    assert any(f.rule == "W119" and f.where == "scatter.place[0]" and "patch" in str(f.path) for f in findings)
    assert any(f.rule == "W118" and f.where == "scatter.place[1]" and "meadow" in str(f.path) for f in findings)
    assert not any(f.rule == "E015" for f in findings)


# --- preview / CLI ------------------------------------------------------------------------------------------------------


def test_preview_a_scatter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from PIL import Image

    scatter_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    for name in ("meadow", "moss", "patch"):
        code, result = run_json(["preview", name], capsys)
        assert code == 0, result
        assert result["outputs"] == {"scatter": f"previews/{name}/scatter.png"} and result["scatter"] is True and result["instances"] > 0
        assert Image.open(tmp_path / result["outputs"]["scatter"]).width >= 600
    code, result = run_json(["preview", "meadow", "--pose", "walk"], capsys)
    assert code == 1 and "is a scatter" in result["findings"][0]["message"]
    code, result = run_json(["lineup"], capsys)
    assert code == 0 and "meadow" not in result["models"] and "land" not in result["models"]


# --- Godot ----------------------------------------------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_loads_scatters(tmp_path: Path) -> None:
    project = scatter_project(tmp_path)
    write_model(project, sphere_text("ball"), "ball")
    result = build(project)
    godot = find_godot_binary()
    assert godot is not None and result.godot_root is not None and result.errors == []
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
    assert check.models == 7  # tuft, rock, land, ball and the scatters meadow, patch, moss
    # the checks bite: an instance moved in the JSON, and a colour changed
    path = project.output_dir / "models" / "meadow.scatter.json"
    data = json.loads(path.read_text())
    data["groups"][1]["instances"][3][0] += 0.5
    path.write_text(json.dumps(data))
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert not check.ok and "meadow p1_tuft/" in check.output and "instance" in check.output
    data["groups"][1]["instances"][3][0] -= 0.5
    data["groups"][1]["colors"][0][1] += 0.2
    path.write_text(json.dumps(data))
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert not check.ok and "colour is" in check.output


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_loads_a_toon_scatter(tmp_path: Path) -> None:
    from kiln.project import load_project

    project = scatter_project(tmp_path)
    style = tmp_path / "styles" / "fast.style.toml"
    style.write_text(style.read_text().replace('"soft_toy"', '"toon"'))
    result = build(load_project(project.root))
    godot = find_godot_binary()
    assert godot is not None and result.godot_root is not None and result.errors == []
    check = verify(godot, result.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
