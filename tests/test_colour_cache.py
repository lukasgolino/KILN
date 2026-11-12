"""#246: a colour-only edit (the same parts sharing colours, the same patterns) reuses the cached meshes, recoloured."""

from __future__ import annotations

import pytest
from conftest import write_model

from kiln import builder
from kiln.export import Built
from kiln.project import Project

TWO = """\
name: thing
parts:
  - sphere: {{ at: [0, 0.3, 0], radius: 0.3 }}
    color: {a}
    pattern: {{ type: stripes, color: {c}, size: 0.05 }}
  - sphere: {{ at: [0, 0.75, 0], radius: 0.18 }}
    color: {b}
    blend: 0.05
"""


@pytest.fixture
def counted(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = builder.build_model

    def counting(*a: object, **k: object) -> object:
        calls.append(1)
        return real(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(builder, "build_model", counting)
    return calls


def _build(project: Project, a: str, b: str, c: str) -> Built:
    write_model(project, TWO.format(a=a, b=b, c=c))
    model, style, _ = project.load(project.models_dir / "thing.kiln.yaml")
    assert model is not None and style is not None
    palette, _ = project.palette(model.palette)
    return builder.build_cached(model, style, palette, project.root / ".kiln-cache")


def test_a_recolour_reuses_the_meshes(project: Project, counted: list[int]) -> None:
    first = _build(project, "red", "blue", "gold")
    again = _build(project, "green", "blue", "white")  # red -> green, gold -> white: the same partition
    assert len(counted) == 1  # built once
    assert (again.painted.faces == first.painted.faces).all()
    colours = {g.color for g in again.painted.groups}
    assert "#4caf50" in colours and "#f4f4f0" in colours and "#e8413c" not in colours and "#f2c14e" not in colours
    assert any(g.color_name.split("#")[0] == "green" for g in again.painted.groups)


def test_swapping_two_colours_moves_each(project: Project, counted: list[int]) -> None:
    first = _build(project, "red", "blue", "gold")
    swapped = _build(project, "blue", "red", "gold")
    assert len(counted) == 1
    exchange = {"#e8413c": "#2f6fd0", "#2f6fd0": "#e8413c"}
    assert [g.color for g in swapped.painted.groups] == [exchange.get(g.color, g.color) for g in first.painted.groups]


def test_merging_colours_builds_again(project: Project, counted: list[int]) -> None:
    _build(project, "red", "blue", "gold")
    _build(project, "red", "red", "gold")  # two parts now share a colour: the paint borders change
    assert len(counted) == 2
