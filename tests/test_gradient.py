"""#106: gradient: a part's colour going to another, root to tip, in steps."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project

MODEL = """\
name: thing
parts:
  - sphere: {{ at: [0, 0.3, 0], radius: 0.3 }}
    color: red
  - capsule: {{ from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }}
    color: red
    gradient: {gradient}
"""


def test_gradient_becomes_bands(project: Project) -> None:
    model, _, findings = load(project, MODEL.format(gradient="{ to: white, steps: 3 }"))
    assert model is not None, findings
    part = model.parts[1]
    assert [round(p.at, 4) for p in part.patterns] == [0.3333, 0.6667] and all(p.type == "along" for p in part.patterns)
    white = part.patterns[-1].color
    assert part.patterns[-1].color_name == "white" and part.patterns[0].color not in (part.color, white)  # a mix between


def test_gradient_paints_root_to_tip(project: Project) -> None:
    path = write_model(project, MODEL.format(gradient="{ to: white, steps: 3 }"))
    result = lint_paths(project, [path])
    assert not [f for f in result.findings if f.severity == "error"], result.findings
    built = result.built["thing"]
    p = built.painted
    centres = p.vertices[p.faces].mean(axis=1)
    on_capsule = (centres[:, 1] > 0.62) & (np.abs(centres[:, 0]) < 0.06)
    colours = np.array([p.groups[g].color for g in p.face_group])
    low = colours[on_capsule & (centres[:, 1] < 0.66)]
    tip = colours[on_capsule & (centres[:, 1] > 0.86)]
    model = built.model
    assert set(tip) == {model.parts[1].patterns[-1].color}
    assert model.parts[1].patterns[0].color in set(low)


def test_gradient_from_and_axis(project: Project) -> None:
    text = MODEL.format(gradient="{ from: blue, to: white, steps: 2, along: y }").replace("capsule: { from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }",
                                                                                           "box: { at: [0, 0.7, 0], size: [0.1, 0.4, 0.1] }")
    model, _, findings = load(project, text)
    assert model is not None, findings
    part = model.parts[1]
    assert part.color_name == "blue" and len(part.patterns) == 1 and part.patterns[0].at == 0.5


@pytest.mark.parametrize("gradient", ["{ steps: 3 }", "{ to: white, steps: 1 }", "{ to: white, along: sideways }", "{ to: nocolour }"])
def test_bad_gradient(project: Project, gradient: str) -> None:
    _, _, findings = load(project, MODEL.format(gradient=gradient))
    assert any(f.rule in ("E003", "E004") and (f.where or "").startswith("parts[1].gradient") for f in findings), findings


def test_path_gradient_needs_a_path(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white, along: path }").replace("capsule: { from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }",
                                                                      "box: { at: [0, 0.7, 0], size: [0.1, 0.4, 0.1] }")
    _, _, findings = load(project, text)
    assert any(f.rule == "E003" and f.where == "parts[1].gradient" for f in findings)


def test_bad_shape_with_a_gradient_is_an_error_not_a_crash(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white }").replace("to: [0, 0.9, 0], ", "")
    _, _, findings = load(project, text)
    assert any(f.rule == "E003" for f in findings)


def test_cut_part_cant_have_a_gradient(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white }").replace("    color: red\n    gradient", "    cut: true\n    gradient")
    _, _, findings = load(project, text)
    assert any(f.rule == "E003" and f.where == "parts[1].gradient" for f in findings), findings


def test_zero_length_path_is_an_error(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white }").replace("to: [0, 0.9, 0]", "to: [0, 0.5, 0]")
    _, _, findings = load(project, text)
    assert any(f.rule == "E003" and f.where == "parts[1].gradient" for f in findings)


def test_variants_remix_the_bands(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white, steps: 3 }") + "variants:\n  blue_one: { swap: { red: blue } }\n"
    model, _, findings = load(project, text)
    assert model is not None, findings
    mid = model.parts[1].patterns[0]
    swap = model.variants["blue_one"]
    assert swap[mid.color] not in (mid.color, swap["#e8413c"])  # the middle band: a blue-white mix, not left pink


def test_path_bands_follow_a_bent_tube(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white, steps: 4 }").replace(
        "capsule: { from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }", "tube: { points: [[0, 0.5, 0], [0, 0.8, 0], [0.3, 0.8, 0]], radius: 0.05 }")
    path = write_model(project, text)
    built = lint_paths(project, [path]).built["thing"]
    p = built.painted
    centres = p.vertices[p.faces].mean(axis=1)
    colours = np.array([p.groups[g].color for g in p.face_group])
    tip = colours[(centres[:, 0] > 0.27) & (centres[:, 1] > 0.75)]
    assert set(tip) == {built.model.parts[1].patterns[-1].color}  # the far end of the bend is the last band


def test_hard_part_gradient_is_cut_not_refined(project: Project) -> None:
    hard = MODEL.format(gradient="{ to: white, steps: 4, along: y }").replace(
        "capsule: { from: [0, 0.5, 0], to: [0, 0.9, 0], radius: 0.05 }", "box: { at: [0, 0.7, 0], size: [0.1, 0.4, 0.1] }").replace(
        "    gradient", "    blend: none\n    gradient")
    plain = hard.replace("    gradient: { to: white, steps: 4, along: y }\n", "").replace("name: thing", "name: other")
    with_bands = lint_paths(project, [write_model(project, hard)]).built["thing"].triangles
    without = lint_paths(project, [write_model(project, plain, "other")]).built["other"].triangles
    assert with_bands < without + 120  # three exact cuts round the box, not a refined surface


def test_refine_splits_each_long_edge_once_and_uses_every_midpoint() -> None:
    from kiln.paint import refine

    rng = np.random.default_rng(5)
    for _ in range(20):
        v = rng.uniform(-1, 1, (60, 3))
        f = np.array([rng.choice(60, 3, replace=False) for _ in range(80)])
        v2, f2, parent = refine(v, f, rng.random(80) < 0.5, 0.4, lambda x: x)
        mids = v2[len(v):]
        assert len(np.unique(np.round(mids, 12), axis=0)) == len(mids)  # no edge split twice
        assert set(range(len(v), len(v2))) <= set(f2.reshape(-1).tolist())  # every midpoint is in the faces
        assert len(parent) == len(f2) and parent.max() < len(f)


def test_gradient_on_a_turned_mirrored_array(project: Project) -> None:
    text = MODEL.format(gradient="{ to: white, steps: 3 }").replace("    color: red\n    gradient",
                                                                       "    rotate: [0, 0, 20]\n    mirror: x\n    array: { count: 3, around: y }\n    color: red\n    gradient")
    result = lint_paths(project, [write_model(project, text)])
    assert not [f for f in result.findings if f.severity == "error"], result.findings
    colours = {g.color for g in result.built["thing"].painted.groups}
    pats = result.built["thing"].model.parts[1].patterns
    assert {p.color for p in pats} <= colours


def test_painting_reports_progress(project: Project) -> None:
    """#123: long paints say how far they are (lines at most every QUIET_SECONDS, via Phases.within)."""
    from kiln.builder import field_of
    from kiln.mesher import dual_contour
    from kiln.paint import regions

    model, _, findings = load(project, MODEL.format(gradient="{ to: white, steps: 3 }"))
    assert model is not None, findings
    field = field_of(model, 0.02)
    lines: list[str] = []
    regions(dual_contour(field, 0.02), model, field, False, progress=lines.append)
    assert lines[-1] == "painting: patterns of 1/1 parts" and "painting: borders of 1/2 colour groups" in lines


def test_progress_within_a_phase_is_throttled(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from kiln import usage

    now = [100.0]
    monkeypatch.setattr("kiln.usage.time.monotonic", lambda: now[0])
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    phase = usage.Phases("thing")
    for t, what in [(5, "a"), (11, "b"), (15, "c"), (22, "d"), (30, "e")]:
        now[0] = 100.0 + t
        phase.within(what)
    assert [line.split(": ")[2] for line in capsys.readouterr().err.splitlines()] == ["b (11 s)", "d (22 s)"]


def test_a_long_phase_keeps_saying_so(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#99: a phase that runs on repeats itself every QUIET_SECONDS (a heartbeat), and stops with the build."""
    import time

    from kiln import usage

    monkeypatch.setattr("kiln.usage.QUIET_SECONDS", 0.2)
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    with usage.Phases("thing") as phase:
        phase("reducing to 100 triangles")
        time.sleep(0.75)
    time.sleep(0.3)  # nothing after the build ended
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) >= 2 and all(line.startswith("kiln: thing: reducing to 100 triangles (") for line in lines)


def test_slow_runs_without_the_fast_extra_say_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln import jit
    from kiln.usage import cost_line

    monkeypatch.setattr(jit, "AVAILABLE", False)
    assert "kiln[fast]" in cost_line(25.0) and "kiln[fast]" not in cost_line(5.0)
    monkeypatch.setattr(jit, "AVAILABLE", True)
    assert "kiln[fast]" not in cost_line(25.0)
