"""`kiln preview <model> --vs <ref.glb>`: a model against a reference mesh at one scale, with metrics."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import CONFIG, built_of, make_project, run_json, sphere_text, write_model
from kiln.export import Built, to_glb
from kiln.importer import gltf_counts, joint_heights, load_reference
from kiln.preview import TILE_BG, body_bands, compare, distance_row, facet_regularity, screen_ppm, versus_reference, visual_mass
from kiln.project import Project
from test_importer import BOX_FACES, box_glb
from test_mcp import call
from test_retarget import HERO, KAYKIT


def _against(built: Built, path: Path, height: float | None = None) -> dict[str, object]:
    lo, hi = built.bounds()
    ref = load_reference(path, built.style, height, (float(lo[0] + hi[0]) / 2, float(lo[2] + hi[2]) / 2))
    return compare(built, ref, gltf_counts(to_glb(built, "kiln test")), gltf_counts(path))


def test_model_against_its_own_glb(project: Project) -> None:
    built = built_of(project, sphere_text("ball"), "ball")
    path = project.root / "imports" / "ball.glb"
    path.write_bytes(to_glb(built, "kiln test"))
    metrics = _against(built, path)
    assert metrics["iou"] >= 0.99 and metrics["iou_min"] >= 0.98  # type: ignore[operator]
    assert metrics["triangle_ratio"] == 1.0
    mine, theirs = metrics["model"], metrics["reference"]
    assert isinstance(mine, dict) and isinstance(theirs, dict)
    for key in ("triangles", "surfaces", "materials", "colors", "open_edges"):
        assert mine[key] == theirs[key], key
    assert mine["facet_regularity"] == pytest.approx(theirs["facet_regularity"], abs=0.02)
    assert mine["size"] == pytest.approx(theirs["size"], abs=1e-3)
    assert metrics["bands"] == "thirds" and metrics["band_iou"] >= 0.97  # type: ignore[operator]
    assert metrics["mass_ratio"] == pytest.approx(1.0, abs=0.01) and metrics["mass"] == pytest.approx(np.pi / 4, abs=0.03)  # a disc in its box
    screen = metrics["screen_px"]
    assert isinstance(screen, dict) and screen["30 m"]["model"] == pytest.approx(0.6 * 1080 / (60 * np.tan(np.radians(30))), abs=0.2)
    assert screen["60 m"]["model"] == pytest.approx(screen["30 m"]["model"] / 2, abs=0.1) and screen["30 m"]["reference"] == screen["30 m"]["model"]
    assert metrics == _against(built, path)  # deterministic


def test_bands_ignore_proportions(project: Project) -> None:
    """A reference twice the size overlaps badly at one scale, but band by band (each scaled to one height) it's the
    same shape, with the same visual mass."""
    built = built_of(project, sphere_text("ball"), "ball")
    path = project.root / "imports" / "ball.glb"
    path.write_bytes(to_glb(built, "kiln test"))
    metrics = _against(built, path, height=1.2)
    assert metrics["iou"] < 0.5 and metrics["band_iou"] >= 0.95  # type: ignore[operator]
    assert set(metrics["band_ious"]) == {"top", "middle", "bottom"}  # type: ignore[call-overload]
    assert metrics["mass_ratio"] == pytest.approx(1.0, abs=0.02)


def test_humanoid_bands_cut_at_head_and_hips(project: Project) -> None:
    built = built_of(project, HERO.split("animations:")[0])
    for name in ("Knight.glb", "knight_texture.png"):
        shutil.copy(KAYKIT / name, project.root / "imports" / name)
    path = project.root / "imports" / "Knight.glb"
    joints = joint_heights(path)
    assert joints["hips"] == pytest.approx(0.16, abs=0.01) and joints["head"] == pytest.approx(0.49, abs=0.01)  # chibi: half head
    lo, hi = built.bounds()
    ref = load_reference(path, built.style, float(hi[1] - lo[1]), (float(lo[0] + hi[0]) / 2, float(lo[2] + hi[2]) / 2))
    metrics = compare(built, ref, gltf_counts(to_glb(built, "t")), gltf_counts(path), joints)
    assert metrics["bands"] == "humanoid" and set(metrics["band_ious"]) == {"legs", "torso", "head"}
    assert metrics["band_ious"]["head"] > metrics["iou"]  # two round heads match once each is scaled to one height
    assert compare(built, ref, gltf_counts(to_glb(built, "t")), gltf_counts(path))["bands"] == "thirds"  # no reference joints


def test_body_bands_and_visual_mass() -> None:
    method, bands = body_bands({"head": 0.8, "hips": 0.5}, {"head": 0.5, "hips": 0.2})
    assert method == "humanoid" and bands == [("legs", 0.0, 0.5, 0.0, 0.2), ("torso", 0.5, 0.8, 0.2, 0.5), ("head", 0.8, 1.0, 0.5, 1.0)]
    assert body_bands({"head": 0.8, "hips": 0.5}, {"head": 0.2, "hips": 0.5})[0] == "thirds"  # out of order: not usable
    assert body_bands({}, {})[0] == "thirds"
    square = np.zeros((20, 20), dtype=bool)
    square[5:15, 2:8] = True
    assert visual_mass(square) == 1.0 and visual_mass(np.zeros((4, 4), dtype=bool)) == 0.0
    square[5:10, 2:5] = False
    assert visual_mass(square) == pytest.approx(0.75)
    assert screen_ppm(30.0) == pytest.approx(2 * screen_ppm(60.0)) and screen_ppm(30.0) == pytest.approx(31.18, abs=0.01)


def test_different_reference_scores_lower(project: Project) -> None:
    built = built_of(project, sphere_text("ball"), "ball")
    box = box_glb(project.root / "imports" / "box.glb")
    metrics = _against(built, box, height=0.6)
    ref = metrics["reference"]
    assert isinstance(ref, dict)
    assert ref["size"] == pytest.approx([0.6, 0.6, 0.6])
    assert ref["triangles"] == 12 and ref["surfaces"] == 2 and ref["materials"] == 2 and ref["colors"] == 2 and ref["open_edges"] == 0
    views = metrics["iou_views"]
    assert isinstance(views, dict) and views["front"] == pytest.approx(np.pi / 4 / (1 + np.tan(np.radians(10))), abs=0.03)  # a circle in the square (+ the top, at 10 degrees)
    assert 0.4 < metrics["iou"] < 0.85  # type: ignore[operator]
    assert metrics["triangle_ratio"] == pytest.approx(built.triangles / 12, abs=1e-3)


def test_facet_regularity_separates_designed_facets_from_noise(project: Project) -> None:
    v = np.array([[x, y, z] for x, y, z in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))], float)
    assert facet_regularity(v, BOX_FACES) == pytest.approx(1.0)
    built = built_of(project, sphere_text("ball"), "ball")
    assert facet_regularity(built.painted.vertices, built.painted.faces) < 0.3
    rng = np.random.default_rng(1)
    assert facet_regularity(v + rng.normal(0, 0.2, v.shape), BOX_FACES) < 0.2


def test_reference_keeps_its_colours_and_normals(project: Project) -> None:
    ref = load_reference(box_glb(project.root / "imports" / "box.glb"), built_of(project, sphere_text()).style)
    assert sorted(g.color for g in ref.painted.groups) == ["#306ccb", "#e73f38"]  # the file's sRGB colours, not the palette's
    lo, hi = ref.bounds()
    assert lo[1] == pytest.approx(0.0) and hi[1] == pytest.approx(1.0)  # own units, standing on y = 0
    assert ref.normals.shape == (12, 3, 3)


def test_sheet(project: Project) -> None:
    built = built_of(project, sphere_text("ball"), "ball")
    box = box_glb(project.root / "imports" / "box.glb")
    lo, hi = built.bounds()
    ref = load_reference(box, built.style, 0.6, (float(lo[0] + hi[0]) / 2, float(lo[2] + hi[2]) / 2))
    metrics = compare(built, ref, gltf_counts(to_glb(built, "t")), gltf_counts(box))
    image = versus_reference(built, ref, metrics, "box.glb", size=64)
    assert image.width >= 8 * 64 and image.height > 10 * 64
    label, tiles = distance_row(built, ref, size=64)
    assert "60 degree" in label and [n for n, _ in tiles] == ["reference 30 m", "kiln 30 m", "reference 60 m", "kiln 60 m"]
    assert all(t.size == (64, 64) for _, t in tiles)
    painted = [int((np.asarray(t)[..., :3] != TILE_BG[:3]).any(axis=2).sum()) for _, t in tiles]
    assert painted[2] < painted[0] / 2 and painted[3] < painted[1] / 2  # further away = smaller, same upscale
    assert [t.tobytes() for _, t in distance_row(built, ref, size=64)[1]] == [t.tobytes() for _, t in tiles]  # deterministic


def test_cli_vs_reference(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, sphere_text("ball"), "ball")
    box_glb(in_project.root / "imports" / "box.glb")
    code, result = run_json(["preview", "ball", "--vs", "imports/box.glb", "--ref-height", "0.6"], capsys)
    assert code == 0, result
    assert set(result["outputs"]) == {"vs_reference"} and (in_project.root / result["outputs"]["vs_reference"]).is_file()
    metrics = result["compare"]
    assert metrics["file"] == "imports/box.glb" and metrics["ref_height"] == 0.6
    assert set(metrics["iou_views"]) == {"front", "front-left", "left", "back-left", "front above", "left above", "top", "below"}
    assert metrics["reference"]["triangles"] == 12 and metrics["model"]["triangles"] == result["triangles"]
    assert metrics["bands"] == "thirds" and {"band_iou", "band_ious", "mass", "mass_ref", "mass_ratio", "screen_px"} <= set(metrics)
    code, again = run_json(["preview", "ball", "--vs", "imports/box.glb", "--ref-height", "0.6"], capsys)
    assert again["compare"] == metrics
    capsys.readouterr()
    from kiln.cli import main

    assert main(["preview", "ball", "--vs", "imports/box.glb"]) == 0
    out = capsys.readouterr().out
    assert "silhouette IoU" in out and "band IoU (thirds)" in out and "visual mass" in out and "height on screen" in out


def test_cli_vs_errors_and_inspiration(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, sphere_text("ball"), "ball")
    code, result = run_json(["preview", "ball", "--vs", "imports/missing.glb"], capsys)
    assert code == 1 and ".glb or .gltf" in result["findings"][0]["message"]
    code, result = run_json(["preview", "ball", "--ref-height", "2"], capsys)
    assert code == 1 and "--vs" in result["findings"][0]["message"]
    folder = in_project.root / "styles" / "fast" / "inspiration"
    folder.mkdir(parents=True)
    Image.new("RGB", (40, 30), (200, 100, 50)).save(folder / "look.png")
    code, result = run_json(["preview", "ball", "--vs"], capsys)
    assert code == 0 and set(result["outputs"]) == {"vs_inspiration"} and "compare" not in result


def test_mcp_preview_reference(project: Project) -> None:
    write_model(project, sphere_text("ball"), "ball")
    box_glb(project.root / "imports" / "box.glb")
    result, images = call(project, "preview", {"model": "ball", "which": "vs", "reference": "imports/box.glb", "ref_height": 0.6})
    assert result["ok"] and images == 1 and result["compare"]["reference"]["triangles"] == 12
    result, images = call(project, "preview", {"model": "ball", "which": "vs", "reference": "../elsewhere.glb"})
    assert not result["ok"] and "outside" in result["findings"][0]["message"] and images == 0
    result, _ = call(project, "preview", {"model": "ball", "reference": "imports/box.glb"})
    assert not result["ok"]


def test_cli_vs_counts_what_the_build_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#36: `--vs` surfaces/materials follow atlas and merge_rigid, as the built glb does."""
    from conftest import arms_text
    from kiln.build import build

    project = make_project(tmp_path, CONFIG + "atlas = true\nmerge_rigid = true\n")
    monkeypatch.chdir(tmp_path)
    write_model(project, arms_text("hero"), "hero")
    box_glb(project.root / "imports" / "box.glb")
    assert build(project).errors == []
    built_counts = gltf_counts(project.output_dir / "models" / "hero.glb")
    code, result = run_json(["preview", "hero", "--vs", "imports/box.glb", "--ref-height", "0.6"], capsys)
    assert code == 0, result
    model = result["compare"]["model"]
    assert {"surfaces": model["surfaces"], "materials": model["materials"]} == built_counts
    assert built_counts["materials"] == 1  # the atlas: one material for every colour
