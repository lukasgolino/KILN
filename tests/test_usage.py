"""Progress lines on long model builds (kiln.usage.Phases): throttling, ETAs, long-build warnings."""

from __future__ import annotations

import pytest
from conftest import ok_model, write_model

from kiln.project import Project


def test_progress_has_an_eta_and_a_long_phase_says_so_at_once(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#221: done/total with the time left, and a phase projected past LONG_SECONDS says so at once (once), with what
    would make it faster, even before QUIET_SECONDS."""
    from kiln import usage

    now = [100.0]
    monkeypatch.setattr("kiln.usage.time.monotonic", lambda: now[0])
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    phase = usage.Phases("thing")
    phase("meshing")
    now[0] = 102.0
    phase.progress("meshing: samples", 1, 100, "coarser cells")  # 2 s for 1 %: about 198 s left
    now[0] = 104.0
    phase.progress("meshing: samples", 2, 100, "coarser cells")  # said already: quiet until QUIET_SECONDS
    now[0] = 115.0
    phase.progress("meshing: samples", 10, 100, "coarser cells")
    lines = [line.split(": ", 2)[2] for line in capsys.readouterr().err.splitlines()]
    assert lines == ["meshing: samples 1/100, about 3 min left: a long build; coarser cells (2 s)",
                     "meshing: samples 10/100, about 2 min left (15 s)"]


def test_short_phases_stay_quiet_and_big_models_speak_at_once(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from kiln import usage

    now = [100.0]
    monkeypatch.setattr("kiln.usage.time.monotonic", lambda: now[0])
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    small = usage.Phases("small")
    small("meshing")
    now[0] = 103.0
    small.progress("meshing: samples", 50, 100)  # 6 s in all: nothing
    assert capsys.readouterr().err == ""
    big = usage.Phases("big")
    big.loud = True
    big("meshing 536 parts")
    assert capsys.readouterr().err == "kiln: big: meshing 536 parts (0 s)\n"


def test_the_heartbeat_counts_the_time_left_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """#221: between progress calls the heartbeat repeats the last count with the time left from now, not a stale one."""
    from kiln import usage

    now = [100.0]
    monkeypatch.setattr("kiln.usage.time.monotonic", lambda: now[0])
    phase = usage.Phases("thing")
    phase("reducing")
    now[0] = 160.0
    phase.progress("reducing: passes done", 1, 5)  # 60 s a pass: 240 s left
    now[0] = 220.0
    assert phase._counted() == "reducing: passes done 1/5, about 3 min left"
    now[0] = 500.0
    assert phase._counted() == "reducing: passes done 1/5, past the estimate"
    phase("skinning")
    assert phase._counted() is None



def test_each_counter_has_its_own_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Earlier work in a phase (borders before patterns, the last mesh piece before the next) doesn't count towards
    the next counter's rate: 60 s of borders, then patterns at 1 s a part, is about 38 s left, not 41 min."""
    from kiln import usage

    now = [100.0]
    monkeypatch.setattr("kiln.usage.time.monotonic", lambda: now[0])
    phase = usage.Phases("thing")
    phase("painting")
    for k in range(1, 61):
        now[0] = 100.0 + k
        phase.progress("painting: borders", k, 60)
    phase.progress("painting: patterns", 0, 40)
    now[0] += 2.0
    phase.progress("painting: patterns", 2, 40)
    assert phase._counted() == "painting: patterns 2/40, about 38 s left"
    phase.progress("painting: patterns", 0, 40)  # the count went back (the next piece): a new clock
    assert phase._counted() is None


def test_a_model_with_many_parts_says_each_phase_at_once(project: Project, monkeypatch: pytest.MonkeyPatch,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    """#221: a model with MANY_PARTS parts or more prints its phases at once; the first names parts and cell size."""
    from kiln import usage
    from kiln.lint import lint_paths

    monkeypatch.setattr("kiln.builder.MANY_PARTS", 2)
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    text = "name: two\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n" \
           "  - sphere: { at: [0.2, 0.5, 0], radius: 0.1 }\n    color: red\n    blend: 0.05\n"
    lint_paths(project, [write_model(project, text, "two")])
    lines = capsys.readouterr().err.splitlines()
    assert lines and lines[0].startswith("kiln: two: meshing 2 parts at 30 mm cells (style fast resolution 30 mm) (")


def test_hard_parts_are_their_own_phase_and_a_hard_only_model_meshes_nothing(project: Project, monkeypatch: pytest.MonkeyPatch,
                                                                             capsys: pytest.CaptureFixture[str]) -> None:
    """#174: joining hard parts says so (it was "meshing", and "meshed ...: 0 triangles" for a model of hard parts
    only); the meshing phase counts the parts it meshes and is only there with something to mesh."""
    from kiln import usage
    from kiln.lint import lint_paths

    monkeypatch.setattr("kiln.builder.MANY_PARTS", 2)
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    boxes = "  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: red\n    hard: true\n" \
            "  - box: { at: [0.2, 0.5, 0], size: [0.3, 0.3, 0.3] }\n    color: red\n    hard: true\n"
    lint_paths(project, [write_model(project, "name: crates\nparts:\n" + boxes, "crates")])
    lines = [line.split(": ", 2)[2] for line in capsys.readouterr().err.splitlines()]
    assert lines and lines[0].startswith("joining 2 hard parts (")
    assert not any(line.startswith(("meshing", "meshed")) for line in lines)

    ball = "  - sphere: { at: [0, 0.9, 0], radius: 0.2 }\n    color: red\n"
    lint_paths(project, [write_model(project, "name: mixed\nparts:\n" + boxes + ball, "mixed")])
    lines = [line.split(": ", 2)[2] for line in capsys.readouterr().err.splitlines()]
    starts = [line.split(" (")[0].split(" at ")[0] for line in lines]
    assert starts[0] == "joining 2 hard parts" and starts.index("joining 2 hard parts") < starts.index("meshing 1 part") < starts.index("meshed")


def test_time_left_for_a_step_whose_items_cost_more_and_more(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """#174: with growth 2 (joining hard parts: every join clips against all joined so far) half the count done is a
    quarter of the time, not half."""
    from kiln import usage

    clock = [0.0]
    monkeypatch.setattr("kiln.usage.time.monotonic", lambda: clock[0])
    monkeypatch.setenv(usage.PROGRESS_ENV, "1")
    phase = usage.Phases("m")
    phase("joining 40 hard parts")
    clock[0] = 20.0
    phase.progress("joining hard parts: joined", 20, 40, "fewer", 2.0)  # 20 s for a quarter of the work: 60 s left
    assert capsys.readouterr().err.splitlines()[-1] == "kiln: m: joining hard parts: joined 20/40, about 60 s left (20 s)"


def test_hard_join_counter_runs_over_all_pieces_and_says_a_level_made_again(project: Project) -> None:
    """#174: one counter per detail level over every piece, cuts counted; over budget, the next level says so."""
    from kiln import builder

    text = "name: cut\nclass: prop\nparts:\n  - cylinder: { at: [0, 0.05, 0], radius: 0.05, height: 0.1 }\n    color: red\n    bevel: 0.01\n" \
           "  - box: { at: [0.2, 0.05, 0], size: [0.1, 0.1, 0.1] }\n    color: red\n    hard: true\n" \
           "  - box: { at: [0, 0.1, 0], size: [0.04, 0.04, 0.04] }\n    cut: true\n    hard: true\n"
    model, style = ok_model(project, text, "cut")
    hard = sorted(builder.hard_parts(model, style))
    pieces = [frozenset({hard[0]}), frozenset({hard[1]})]  # as two pieces: the cut reaches both
    said: list[tuple[str, int, int]] = []
    builder.build_hard(model, style, builder.field_of(model, 0.01), pieces, 1e9, False, lambda *a: said.append(a))
    assert said == [("joining hard parts: joined", k, 4) for k in (1, 2, 3, 4)]
    said.clear()
    builder.build_hard(model, style, builder.field_of(model, 0.01), pieces, 1, False, lambda *a: said.append(a))
    assert said[:4] == [("joining hard parts: joined", k, 4) for k in (1, 2, 3, 4)]
    assert said[4] == ("joining hard parts again with less detail (try 2): joined", 1, 4)
