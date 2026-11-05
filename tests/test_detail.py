"""Mesh detail settings (#103): style and model max_cells / resolution / scale_with_size, lint W120, the step reported."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import load, sphere_text, write_model

from kiln.build import build
from kiln.lint import lint_paths
from kiln.mesher import MAX_CELLS, mesh_steps
from kiln.project import Project
from kiln.sdf import Field, Geometry
from kiln.style import load_style


def detailed(extra: str) -> str:
    return sphere_text().replace("parts:\n", extra + "parts:\n")


def test_style_detail_settings(tmp_path: Path) -> None:
    (tmp_path / "fine.style.toml").write_text('extends = "soft_toy"\n[shape]\nmax_cells = 640\nscale_with_size = false\n')
    style, findings = load_style("fine", tmp_path)
    assert style is not None, findings
    assert (style.max_cells, style.scale_with_size) == (640, False)
    default, _ = load_style("soft_toy")
    assert default is not None and (default.max_cells, default.scale_with_size) == (MAX_CELLS, True)


@pytest.mark.parametrize(("text", "where"), [("[shape]\nmax_cells = 4096\n", "shape.max_cells"), ("[shape]\nmax_cells = 32\n", "shape.max_cells"),
                                             ("[shape]\nscale_with_size = 1\n", "shape.scale_with_size")])  # fmt: skip
def test_bad_style_detail_settings(tmp_path: Path, text: str, where: str) -> None:
    (tmp_path / "bad.style.toml").write_text(text)
    style, findings = load_style("bad", tmp_path)
    assert style is None and findings[0].where == where


def test_model_detail_settings(project: Project) -> None:
    model, _, findings = load(project, detailed("resolution: 0.004\nmax_cells: 700\n"))
    assert model is not None, findings
    assert (model.resolution, model.max_cells) == (0.004, 700)


@pytest.mark.parametrize("extra", ["resolution: 0.5\n", "resolution: true\n", "max_cells: 2000\n", "max_cells: 100.5\n"])
def test_bad_model_detail_settings(project: Project, extra: str) -> None:
    _, _, findings = load(project, detailed(extra))
    assert any(f.rule == "E003" and f.where == extra.split(":")[0] for f in findings)


def test_mesh_steps(project: Project) -> None:
    style, _ = load_style("soft_toy")
    assert style is not None
    tall = Field([Geometry("box", {"size": [0.5, 2.5, 0.5]})], margin=0.01)
    model, _, _ = load(project, sphere_text())
    assert model is not None
    step, asked = mesh_steps(tall, model, style)  # 8 mm x sqrt(2.5) = 12.6 mm: coarser than the cap's 10 mm
    assert step == asked == pytest.approx(0.008 * 2.5**0.5)
    model.resolution = 0.004  # as is: not scaled by size
    step, asked = mesh_steps(tall, model, style)
    assert asked == 0.004 and step == pytest.approx(0.01)  # the cap decides
    model.max_cells = 700
    assert mesh_steps(tall, model, style) == (0.004, 0.004)
    model.resolution = None
    unscaled = type(style)(**{**style.__dict__, "scale_with_size": False, "max_cells": 1024})
    assert mesh_steps(tall, model, unscaled) == (0.008, 0.008)


def test_w120_names_the_cells_needed(project: Project) -> None:
    path = write_model(project, detailed("resolution: 0.005\nmax_cells: 64\n"))
    found = [f for f in lint_paths(project, [path]).findings if f.rule == "W120"]
    assert len(found) == 1 and "set max_cells: " in found[0].message
    need = int(found[0].message.split("set max_cells: ")[1].split()[0])
    path = write_model(project, detailed(f"resolution: 0.005\nmax_cells: {need}\n"))
    assert not [f for f in lint_paths(project, [path]).findings if f.rule == "W120"]
    path = write_model(project, sphere_text())  # the defaults never trip it on a ~1 m model
    assert not [f for f in lint_paths(project, [path]).findings if f.rule == "W120"]


def test_build_reports_the_step(project: Project) -> None:
    write_model(project, detailed("resolution: 0.02\n"))
    result = build(project)
    assert result.manifest["models"]["thing"]["step"] == 0.02


def test_split_distance_matches_one_batch() -> None:
    parts = [Geometry("sphere", {"radius": 0.2}, at=np.array([x, 0.0, 0.0])) for x in np.linspace(-2, 2, 12)]
    field = Field(parts, margin=0.01)
    p = np.random.default_rng(1).uniform(-2.5, 2.5, (50_000, 3)) * [1, 0.2, 0.2]
    np.testing.assert_array_equal(field.distance(p), field._distance(p))


def test_lint_workers_are_sized_for_fine_grids(project: Project) -> None:
    from kiln.lint import WORKER_MEMORY, job_memory

    model, style, _ = load(project, sphere_text())
    assert model is not None and style is not None
    assert job_memory(model, style) == WORKER_MEMORY
    model.resolution, model.max_cells = 0.001, 1024
    assert job_memory(model, style) > 4 * WORKER_MEMORY
