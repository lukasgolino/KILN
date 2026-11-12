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


GRAD = """\
name: thing
parts:
  - box: {{ at: [0, 0.3, 0], size: [0.4, 0.6, 0.4] }}
    color: {a}
    gradient: {{ to: {t}, steps: 3 }}
  - sphere: {{ at: [0, 0.8, 0], radius: 0.15 }}
    color: {b}
    blend: 0.05
"""


def _grad(project: Project, a: str, t: str, b: str) -> Built:
    write_model(project, GRAD.format(a=a, t=t, b=b))
    model, style, _ = project.load(project.models_dir / "thing.kiln.yaml")
    assert model is not None and style is not None
    palette, _ = project.palette(model.palette)
    return builder.build_cached(model, style, palette, project.root / ".kiln-cache")


def _colours(b: Built) -> list[tuple[str, str]]:
    return sorted((g.color, g.color_name) for g in b.painted.groups)


@pytest.mark.parametrize(("first", "then"), [(("red", "blue", "gold"), ("green", "blue", "gold")),  # gradient bands are mixes
                                             (("red", "blue", "gold"), ("red", "blue", "blue"))])  # a hex shared with a to:  # fmt: skip
def test_gradients_come_back_as_a_cold_build(project: Project, first: tuple[str, str, str], then: tuple[str, str, str]) -> None:
    import shutil

    _grad(project, *first)
    warm = _grad(project, *then)
    shutil.rmtree(project.root / ".kiln-cache")
    assert _colours(warm) == _colours(_grad(project, *then))


def test_a_palette_edit_of_a_gradient_colour(project: Project) -> None:
    import shutil

    _grad(project, "red", "wood", "gold")
    pal = project.root / "palettes" / "main.pal.yaml"
    pal.write_text(pal.read_text().replace("#a0663a", "#123456"))
    from kiln.project import load_project

    fresh = load_project(project.root)
    warm = _grad(fresh, "red", "wood", "gold")
    shutil.rmtree(fresh.root / ".kiln-cache")
    assert _colours(warm) == _colours(_grad(load_project(fresh.root), "red", "wood", "gold"))


def test_one_pickle_per_model(project: Project) -> None:
    for a in ("red", "green", "white", "gold"):
        _build(project, a, "blue", "wood")
    assert len(list((project.root / ".kiln-cache").glob("thing.base.*.pickle"))) == 1
