"""KILN's template library (CC0 parity M4): bodies, heads, helmets and armour combined with `extends: [...]`."""

from __future__ import annotations

import pytest

from conftest import built_of, ok_model, run_json, write_model
from kiln.lint import lint_project
from kiln.mesher import open_edges
from kiln.notation import MODEL_SUFFIX, library_dir
from kiln.project import Project

TEMPLATES = sorted(p.name[: -len(MODEL_SUFFIX)] for p in library_dir().glob(f"*{MODEL_SUFFIX}"))
CAST = {
    "peasant": "body_stocky, head_young",
    "knight": "body_big, head_stern, helmet_great, armour_breastplate, armour_pauldrons, armour_gauntlets",
    "elder": "body_slim, head_old, armour_hood",
    "warrior": "body_stocky, head_bearded, helmet_nasal, armour_cape",
    "fool": "body_slim, head_goofy, helmet_kettle",
    "queen": "body_slim, head_female, helmet_crown",
}


def test_the_library_has_every_kind() -> None:
    kinds = {t.split("_")[0] for t in TEMPLATES}
    assert kinds == {"body", "head", "helmet", "armour"}
    assert sum(t.startswith("head_") for t in TEMPLATES) >= 6 and sum(t.startswith("helmet_") for t in TEMPLATES) >= 6
    assert sum(t.startswith("body_") for t in TEMPLATES) >= 3 and sum(t.startswith("armour_") for t in TEMPLATES) >= 5


@pytest.mark.parametrize("name", TEMPLATES)
def test_each_template_parses(project: Project, name: str) -> None:
    text = (library_dir() / f"{name}{MODEL_SUFFIX}").read_text()
    model, _ = ok_model(project, text, name)  # the library's palette is found without copying it
    assert model.template


def test_a_cast_built_only_from_templates(project: Project) -> None:
    for name, bases in CAST.items():
        write_model(project, f"name: {name}\nclass: character\nextends: [{bases}]\n", name)
    errors = [f.format() for f in lint_project(project).findings if f.severity == "error"]
    assert not errors, errors
    knight = built_of(project, f"name: knight\nclass: character\nextends: [{CAST['knight']}]\n", "knight")
    assert knight.model.skeleton == "humanoid" and {"helmet", "breastplate", "pauldron_r", "gauntlet_l"} <= set(knight.model.ids)
    assert len(open_edges(knight.painted.vertices, knight.painted.faces)) == 0
    assert next(b for b in knight.skeleton.bones if b.name == "helmet").separate


def test_library_and_new_extends(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(["library"], capsys)
    assert code == 0 and {t["name"] for t in data["templates"]} == set(TEMPLATES)
    code, _ = run_json(["new", "model", "hero", "--extends", "body_slim,head_female,helmet_crown"], capsys)
    assert code == 0 and "extends: [body_slim, head_female, helmet_crown]" in (in_project.models_dir / "hero.kiln.yaml").read_text()
    code, _ = run_json(["new", "model", "nope", "--extends", "body_wobbly"], capsys)
    assert code != 0


def test_a_helmet_doesnt_float_the_head(project: Project) -> None:
    """The neck joins head and body: without it a helmet (a slightly different grid) could leave the head a separate piece."""
    built = built_of(project, "name: squire\nclass: character\nstyle: soft_toy\nextends: [body_slim, head_young, helmet_kettle]\n", "squire")
    assert built.pieces == 1


@pytest.mark.parametrize("helmet", ["helmet_great", "helmet_crown"])
def test_hair_stays_inside_helmets(project: Project, helmet: str) -> None:
    write_model(project, f"name: royal\nclass: character\nextends: [body_stocky, head_young, {helmet}]\n", "royal")
    findings = lint_project(project).findings
    assert not [f.format() for f in findings if f.rule in ("W103", "W113")]
