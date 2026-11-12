"""#205: variants swap whole palette ramps, and lint (W130) / `preview --variant` name colours a variant left that go
with one it swaps (a robe_dark seam on a yellow robe)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import errors_of, make_project, ok_model, run_json, write_model

from kiln.lint import lint_paths, variant_warnings
from kiln.project import Project, load_project

ROBES = """\
name: main
colors:
  "0": { hex: "#141414", name: black }
  "1": { hex: "#f4f4f0", name: white }
  "2": { hex: "#5a2d82", name: robe_dark }
  "3": { hex: "#7b3fb0", name: robe }
  "4": { hex: "#a070d0", name: robe_light }
  "5": { hex: "#9c7a1c", name: gold_dark }
  "6": { hex: "#d9a92b", name: gold }
  "7": { hex: "#f2d36b", name: gold_light }
  "8": { hex: "#8a93a3", name: grey }
  "9": { hex: "#2f6fd0", name: blue }
  "a": { hex: "#e8413c", name: red }
  "b": { hex: "#d94a2a", name: rust }
ramps:
  robes: ["2", "3", "4"]
  golds: ["5", "6", "7"]
  greys: ["0", "8", "1"]
"""

WIZARD = """\
name: thing
parts:
  - sphere: {{ at: [0, 0.3, 0], radius: 0.3 }}
    color: robe
  - box: {{ at: [0, 0.05, 0], size: [0.5, 0.1, 0.5] }}
    color: robe_dark
  - sphere: {{ at: [0, 0.7, 0], radius: 0.1 }}
    color: {third}
variants:
  yellow: {{ swap: {swap} }}
"""


@pytest.fixture
def robes(tmp_path: Path) -> Project:
    project = make_project(tmp_path)
    (project.root / "palettes" / "main.pal.yaml").write_text(ROBES)
    return load_project(project.root)


def _model(swap: str, third: str = "grey") -> str:
    return WIZARD.format(swap=swap, third=third)


def test_a_ramp_swaps_shade_for_shade(robes: Project) -> None:
    model, _ = ok_model(robes, _model("{ robes: golds }"))
    assert model.variants["yellow"] == {"#5a2d82": "#9c7a1c", "#7b3fb0": "#d9a92b", "#a070d0": "#f2d36b"}
    model, _ = ok_model(robes, _model("{ robes: golds, robe_dark: black }"))  # a colour after it overrides one shade
    assert model.variants["yellow"]["#5a2d82"] == "#141414" and model.variants["yellow"]["#7b3fb0"] == "#d9a92b"


def test_a_ramp_needs_a_ramp_of_its_length(robes: Project) -> None:
    for swap in ("{ robes: gold }", "{ robes: nothing }"):
        errors = errors_of(robes, _model(swap))
        assert any(f.rule == "E003" and "ramp" in f.message for f in errors), (swap, errors)
    (robes.root / "palettes" / "main.pal.yaml").write_text(ROBES.replace('golds: ["5", "6", "7"]', 'golds: ["5", "6"]'))
    errors = errors_of(load_project(robes.root), _model("{ robes: golds }"))
    assert any("same length" in f.message for f in errors)


def test_lint_names_the_shade_a_variant_left(robes: Project) -> None:
    path = write_model(robes, _model("{ robe: gold }"))
    found = [f for f in lint_paths(robes, [path], geometry=False).findings if f.rule == "W130"]
    assert len(found) == 1 and "robe_dark" in found[0].message and "ramp robes" in found[0].message, found
    path = write_model(robes, _model("{ robes: golds }"))
    assert not [f for f in lint_paths(robes, [path], geometry=False).findings if f.rule == "W130"]


def test_close_hues_count_and_greys_and_far_hues_dont(robes: Project) -> None:
    palette, _ = robes.palette()
    model, _ = ok_model(robes, _model("{ robes: golds, red: blue }", third="rust"))
    assert not variant_warnings(model, palette)  # red isn't painted: rust goes with nothing swapped
    model, _ = ok_model(robes, _model("{ robes: golds }", third="grey"))
    assert not variant_warnings(model, palette)
    text = _model("{ robes: golds, red: blue }", third="rust").replace("color: robe_dark", "color: red")
    model, _ = ok_model(robes, text)
    found = variant_warnings(model, palette)
    assert len(found) == 1 and "rust" in found[0].message and "close in hue to red" in found[0].message, found


def test_preview_variant_warns(robes: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(robes, _model("{ robe: gold }"))
    monkeypatch.chdir(robes.root)
    code, out = run_json(["preview", "thing", "--variant", "yellow", "--views", "front", "--size", "64"], capsys)
    assert code == 0 and [w["rule"] for w in out["warnings"]] == ["W130"], out


def test_colour_entries_win_over_ramps_in_any_order(robes: Project) -> None:
    model, _ = ok_model(robes, _model("{ robe_dark: black, robes: golds }"))
    assert model.variants["yellow"]["#5a2d82"] == "#141414" and model.variants["yellow"]["#7b3fb0"] == "#d9a92b"


def test_a_shade_two_ramps_share_is_swapped_only_when_named(robes: Project) -> None:
    (robes.root / "palettes" / "main.pal.yaml").write_text(ROBES.replace('robes: ["2", "3", "4"]', 'robes: ["0", "3", "4"]'))
    project = load_project(robes.root)  # black is in robes and greys now
    model, _ = ok_model(project, _model("{ robes: golds }", third="black"))
    assert "#141414" not in model.variants["yellow"] and model.variants["yellow"]["#7b3fb0"] == "#d9a92b"
    assert not [f for f in variant_warnings(model, project.palette()[0]) if "black" in f.message]
    model, _ = ok_model(project, _model("{ robes: golds, black: gold_dark }", third="black"))
    assert model.variants["yellow"]["#141414"] == "#9c7a1c"


def test_a_swap_that_keeps_the_hue_and_a_kept_colour_stay_quiet(robes: Project) -> None:
    palette, _ = robes.palette()
    model, _ = ok_model(robes, _model("{ robe: robe_light }"))
    assert not variant_warnings(model, palette)
    model, _ = ok_model(robes, _model("{ robe: gold, robe_dark: robe_dark }"))
    assert not variant_warnings(model, palette)


def test_ramp_swaps_come_through_extends(robes: Project) -> None:
    write_model(robes, _model("{ robes: golds }").replace("name: thing", "name: base\ntemplate: true"), "base")
    model, _ = ok_model(robes, "name: thing\nextends: base\n")
    assert model.variants["yellow"]["#7b3fb0"] == "#d9a92b"


def test_preview_keeps_quiet_when_disabled_or_clean(robes: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(robes.root)
    write_model(robes, _model("{ robes: golds }"))
    code, out = run_json(["preview", "thing", "--variant", "yellow", "--views", "front", "--size", "64"], capsys)
    assert code == 0 and "warnings" not in out
    write_model(robes, _model("{ robe: gold }") + "lint: { disable: [W130] }\n")
    code, out = run_json(["preview", "thing", "--variant", "yellow", "--views", "front", "--size", "64"], capsys)
    assert code == 0 and "warnings" not in out
