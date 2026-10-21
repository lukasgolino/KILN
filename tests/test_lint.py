"""`kiln lint` warnings W101-W109 and disabling them."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_project, sphere_text, write_model
from kiln.lint import WARNING_RULES, lint_paths, lint_project
from kiln.project import Project
from kiln.vendor.findings import Finding


def lint(project: Project, text: str, name: str = "thing") -> list[Finding]:
    path = write_model(project, text, name)
    return lint_paths(project, [path]).findings


def warnings(findings: list[Finding]) -> list[str]:
    return sorted(f.rule for f in findings if f.severity == "warning")


def test_clean_model_has_no_findings(project: Project) -> None:
    assert lint(project, sphere_text()) == []


def test_w101_covered_part(project: Project) -> None:
    findings = lint(project, sphere_text() + "  - sphere: { at: [0, 0.3, 0], radius: 0.1 }\n    color: white\n")
    assert warnings(findings) == ["W101"]
    f = findings[0]
    assert f.where == "parts[1]" and f.line == 5 and "no visible surface" in f.message


def test_w101_cut_away_part(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0.5, 0.3, 0], radius: 0.05 }\n    color: white\n  - sphere: { at: [0.5, 0.3, 0], radius: 0.15 }\n    cut: true\n"
    assert "W101" in warnings(lint(project, text))


def test_w102_thin_part(project: Project) -> None:
    text = sphere_text() + "  - box: { at: [0, 0.6, 0], size: [0.3, 0.02, 0.3] }\n    color: white\n"
    findings = [f for f in lint(project, text) if f.rule == "W102"]
    assert len(findings) == 1 and findings[0].where == "parts[1]" and "thick" in findings[0].message


def test_w103_floating_piece(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0, 1.2, 0], radius: 0.1 }\n    color: white\n"
    findings = lint(project, text)
    assert warnings(findings) == ["W103"]
    assert "2 separate pieces" in findings[0].message


def test_w104_hex_colour_not_in_palette(project: Project) -> None:
    findings = lint(project, sphere_text().replace("color: red", "color: '#123456'"))
    assert warnings(findings) == ["W104"]
    assert findings[0].where == "parts[0].color"
    # a hex that is in the palette is fine
    assert lint(project, sphere_text().replace("color: red", "color: '#E8413C'")) == []


def test_w106_not_on_the_ground(project: Project) -> None:
    findings = lint(project, sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]"))
    assert warnings(findings) == ["W106"]
    assert "y = 0.7" in findings[0].message


def test_w107_older_style_version(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\nstyle_version = 2\n')
    findings = lint(project, sphere_text() + "style_version: 1\n")
    assert warnings(findings) == ["W107"]
    assert findings[0].where == "style_version" and "kiln mark" in findings[0].message
    assert lint(project, sphere_text() + "style_version: 2\n") == []


def test_w108_size_for_class(project: Project) -> None:
    text = "name: thing\nclass: character\nparts:\n  - sphere: { at: [0, 0.05, 0], radius: 0.05 }\n    color: red\n"
    findings = lint(project, text)
    assert warnings(findings) == ["W108"]
    assert "character" in findings[0].message and "metres" in findings[0].message


def test_w109_animated_part_without_pivot(project: Project) -> None:
    text = sphere_text() + """\
  - sphere: { at: [0.3, 0.3, 0], radius: 0.1 }
    id: nub
    color: red
skin: rigid
animations:
  turn: { poses: [{ nub: { rotate: [0, 0, 30] } }, {}] }
"""
    findings = lint(project, text)
    assert warnings(findings) == ["W109"]
    assert "'nub'" in findings[0].message
    with_pivot = text.replace("skin: rigid", "rig:\n  nub: { pivot: [0.2, 0.3, 0] }")
    assert lint(project, with_pivot) == []


def test_w109_from_cycles(project: Project) -> None:
    text = sphere_text() + """\
  - sphere: { at: [0, 0.65, 0], radius: 0.1 }
    id: hat
    color: red
    blend: 0.03
skin: rigid
animations:
  swing: { cycle: { type: swing, part: hat, axis: z } }
"""
    assert warnings(lint(project, text)) == ["W109"]


def test_disable_in_kiln_toml(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\n[lint]\ndisable = ["W106"]\n')
    assert lint(project, sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]")) == []


def test_disable_per_model(project: Project) -> None:
    text = sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]") + "lint: { disable: [W106] }\n"
    assert lint(project, text) == []


def test_errors_are_never_disabled(project: Project) -> None:
    text = sphere_text().replace("color: red", "color: mauve") + "lint: { disable: [E004] }\n"
    assert [f.rule for f in lint(project, text)] == ["E004"]


def test_e009_nothing_to_mesh(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0, 0.3, 0], radius: 0.5 }\n    cut: true\n"
    findings = lint(project, text)
    assert [f.rule for f in findings] == ["E009"]
    assert "no surface" in findings[0].message


def test_lint_without_geometry_skips_meshing(project: Project) -> None:
    path = write_model(project, sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]"))
    result = lint_paths(project, [path], geometry=False)
    assert result.findings == [] and result.built == {}
    assert "thing" in result.models


def test_lint_project_collects_every_model(project: Project) -> None:
    write_model(project, sphere_text("a"), "a")
    write_model(project, sphere_text("b").replace("color: red", "color: mauve"), "b")
    result = lint_project(project)
    assert sorted(result.models) == ["a"] and sorted(result.built) == ["a"]
    assert [f.rule for f in result.errors] == ["E004"]
    assert result.errors[0].path == project.models_dir / "b.kiln.yaml"


def test_second_lint_uses_the_cache(project: Project) -> None:
    write_model(project, sphere_text())
    lint_project(project)
    cached = list((project.root / ".kiln-cache").glob("thing.base.*.pickle"))
    assert len(cached) == 1
    lint_project(project)
    assert list((project.root / ".kiln-cache").glob("thing.base.*.pickle")) == cached
    write_model(project, sphere_text().replace("radius: 0.3", "radius: 0.29"))
    lint_project(project)
    after = list((project.root / ".kiln-cache").glob("thing.base.*.pickle"))
    assert len(after) == 1 and after != cached  # old entry replaced


@pytest.mark.parametrize("rule", sorted(WARNING_RULES))
def test_every_warning_is_documented(rule: str) -> None:
    assert rule.startswith("W1") and WARNING_RULES[rule]


def test_w106_catches_a_few_centimetres(project: Project) -> None:
    text = "name: thing\nparts:\n  - capsule: { from: [0, 0.06, 0], to: [0, 0.5, 0], radius: 0.1 }\n    color: red\n"
    assert "W106" in warnings(lint(project, text))  # 4 cm under the ground (the old bean template)


def test_w110_patterns_over_budget(project: Project) -> None:
    text = ("name: thing\nbudget: 200\nparts:\n  - box: { at: [0, 0.5, 0], size: [1, 1, 1], round: 0.05 }\n    color: red\n"
            "    pattern: { type: stripes, color: blue, size: 0.06, axis: y }\n")  # fmt: skip
    assert "W110" in warnings(lint(project, text))


def test_budget_is_met_when_painting_adds_triangles(project: Project) -> None:
    text = ("name: thing\nbudget: 1500\nparts:\n  - sphere: { at: [0, 0.5, 0], radius: 0.5 }\n    color: red\n"
            "  - sphere: { at: [0.2, 0.8, 0.3], radius: 0.12 }\n    color: blue\n"
            "  - sphere: { at: [-0.2, 0.8, 0.3], radius: 0.12 }\n    color: blue\n")  # fmt: skip
    write_model(project, text)
    result = lint_paths(project, project.model_paths())
    assert result.built["thing"].triangles <= 1500 * 1.05


def test_w106_allows_a_rounded_bottom_at_coarse_resolution(project: Project) -> None:
    # LOOSE #33: a rounded extrude standing on y = 0 meshes a cell or so above it
    text = ("name: thing\nparts:\n  - extrude: { points: [[-0.5, -0.1], [0.5, -0.1], [0.5, 0.1], [-0.5, 0.1]], height: 1, round: 0.08,"
            " at: [0, 0.5, 0] }\n    color: red\n")  # fmt: skip
    assert "W106" not in warnings(lint(project, text))
    assert "W106" not in warnings(lint(project, text.replace("parts:", "origin: center\nparts:").replace("[0, 0.5, 0]", "[0, 0.8, 0]")))
