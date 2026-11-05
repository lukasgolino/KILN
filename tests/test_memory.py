"""Many-part models (#110, #108): per-part passes keep running minima, not parts x points arrays; runs report
their time and peak memory, and long model builds say what they are doing."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import run_json, sphere_text, write_model

from kiln import usage
from kiln.cli import main
from kiln.project import Project
from kiln.sdf import Field, Geometry


def test_nearest_matches_argmin_of_the_stack() -> None:
    parts = [Geometry("sphere", {"radius": 0.1 + 0.02 * k}, at=np.array([0.15 * k, 0.0, 0.0])) for k in range(8)]
    field = Field(parts, margin=0.01)
    p = np.random.default_rng(3).uniform(-0.3, 1.4, (5000, 3))
    order = [5, 0, 3, 7, 1]
    for absolute in (True, False):
        d = np.stack([field.part_distance(i, p) for i in order])
        d = np.abs(d) if absolute else d
        which, best = field.nearest(order, p, absolute=absolute)
        np.testing.assert_array_equal(which, d.argmin(axis=0))
        np.testing.assert_array_equal(best, d.min(axis=0))


def test_lint_and_build_report_time_and_memory(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, sphere_text())
    code, result = run_json(["lint"], capsys)
    assert code == 0 and result["seconds"] >= 0
    if usage.peak_gb() is not None:
        assert result["peak_memory_gb"] > 0
    code, result = run_json(["build"], capsys)
    assert code == 0 and "peak_memory_gb" in result and result["seconds"] >= 0
    capsys.readouterr()
    assert main(["build"]) == 0
    assert "peak memory" in capsys.readouterr().out or usage.peak_gb() is None


def test_phases_are_quiet_on_short_builds(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    phase = usage.Phases("thing")
    phase("meshing")
    assert capsys.readouterr().err == ""
    phase.start -= usage.QUIET_SECONDS
    phase("painting 3 parts")
    assert "kiln: thing: painting 3 parts" in capsys.readouterr().err
    monkeypatch.setenv(usage.PROGRESS_ENV, "0")
    quiet = usage.Phases("thing")
    quiet.start -= usage.QUIET_SECONDS
    quiet("meshing")
    assert capsys.readouterr().err == ""
