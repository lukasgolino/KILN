"""`kiln preview <model> --vs <ref.glb>`: a model against a reference mesh at one scale, with metrics."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import built_of, run_json, sphere_text, write_model
from kiln.export import Built, to_glb
from kiln.importer import gltf_counts, load_reference
from kiln.preview import compare, facet_regularity, versus_reference
from kiln.project import Project
from test_importer import BOX_FACES, box_glb
from test_mcp import call


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
    assert metrics == _against(built, path)  # deterministic


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
    assert image.width >= 8 * 64 and image.height > 9 * 64


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
    code, again = run_json(["preview", "ball", "--vs", "imports/box.glb", "--ref-height", "0.6"], capsys)
    assert again["compare"] == metrics
    capsys.readouterr()
    from kiln.cli import main

    assert main(["preview", "ball", "--vs", "imports/box.glb"]) == 0
    assert "silhouette IoU" in capsys.readouterr().out


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
