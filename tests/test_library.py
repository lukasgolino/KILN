"""KILN's template library (CC0 parity M4): bodies, heads, helmets and armour combined with `extends: [...]`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import built_of, make_project, ok_model, run_json, write_model
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


HEADS = [t for t in TEMPLATES if t.startswith("head_")]


def _without_hair_id(name: str) -> str:
    """A head template as it was before its hair had an id of its own (#23): every part `head`, no rig."""
    text = (library_dir() / f"{name}{MODEL_SUFFIX}").read_text()
    lines = [ln for ln in text.splitlines() if not ln.startswith("rig:") and not ln.startswith("  hair:")]
    return "\n".join(ln.replace("id: hair", "id: head") for ln in lines).replace(f"name: {name}", "name: old_head") + "\n"


def _built_as(root: Path, bases: str, old_head: str | None = None) -> tuple[bytes, Any]:
    """The glb and manifest entry of `hero` extending `bases` in a fresh project (with the old head template)."""
    from kiln.build import build

    project = make_project(root)
    if old_head is not None:
        write_model(project, _without_hair_id(old_head), "old_head")
    write_model(project, f"name: hero\nclass: character\nextends: [{bases}]\n", "hero")
    result = build(project)
    assert not result.errors, [f.format() for f in result.errors]
    return (project.output_dir / "models" / "hero.glb").read_bytes(), result.manifest["models"]["hero"]


@pytest.mark.parametrize("head", HEADS)
def test_a_head_without_a_helmet_builds_as_before(tmp_path: Path, head: str) -> None:
    """#23: hair has its own id, but without a helmet it folds back into the head: byte-identical output."""
    assert _built_as(tmp_path / "new", head) == _built_as(tmp_path / "old", "old_head", head)


def test_a_body_and_head_with_a_hood_build_as_before(tmp_path: Path) -> None:
    new = _built_as(tmp_path / "new", "body_slim, head_female, armour_hood")
    assert new == _built_as(tmp_path / "old", "body_slim, old_head, armour_hood", "head_female")


def test_a_helmet_hides_the_hair_and_fits_the_skull(project: Project) -> None:
    """#23: under a helmet the hair is its own piece, hidden until the helmet comes off (as KayKit's helmets replace
    hair); the helmet wraps the head without it, so it no longer follows hair lumps."""
    model, _ = ok_model(project, "name: squire\nclass: character\nextends: [body_slim, head_goofy, helmet_kettle]\n", "squire")
    hair = model.rig["hair"]
    assert hair.parent == "head" and hair.revealed == ("helmet",) and hair.separate
    dome = next(p for p in model.parts if p.id == "helmet" and p.geometry.fit is not None)
    assert dome.geometry.fit is not None
    wrapped = {q.id for q in model.parts if any(q.geometry is t for t in dome.geometry.fit[0])}
    assert wrapped == {"head"}
    assert any(p.id == "hair" for p in model.parts)


def test_a_crown_is_worn_over_the_hair(project: Project) -> None:
    model, _ = ok_model(project, "name: queen\nclass: character\nextends: [body_slim, head_female, helmet_crown]\n", "queen")
    assert "hair" not in model.rig and not any(p.id == "hair" for p in model.parts)


FOLD = """name: thing
parts:
  - sphere: {{ at: [0, 1, 0], radius: 0.3 }}
    id: head
    color: red
  - sphere: {{ at: [0, 1.25, 0], radius: 0.2 }}
    id: hair
    color: blue
  - sphere: {{ at: [0, 1.3, 0.1], radius: 0.05 }}
    cut: hair
{extra}rig:
  hair: {{ parent: head, revealed: {revealed}, fold: true }}
"""


def test_fold_takes_the_parent_id_unless_a_revealer_is_there() -> None:
    from conftest import parse

    model, findings = parse(FOLD.format(extra="", revealed="[helmet, hood]"))
    assert model is not None and not findings, [f.format() for f in findings]
    assert {p.id for p in model.parts if p.geometry.op == "add"} == {"head"} and "hair" not in model.rig
    assert model.parts[2].geometry.cut_only == frozenset({0, 1})  # the cut followed the hair into the head
    hood = "  - sphere: { at: [0, 1.3, 0], radius: 0.35 }\n    id: hood\n    color: red\n"
    model, findings = parse(FOLD.format(extra=hood, revealed="[helmet, hood]"))
    assert model is not None and not findings, [f.format() for f in findings]
    assert model.rig["hair"].revealed == ("hood",) and model.rig["hair"].separate  # the missing helmet is dropped
    model, findings = parse(FOLD.format(extra="", revealed="[]"))  # no revealers: always folded (a crown over the hair)
    assert model is not None and not findings and "hair" not in model.rig


def test_fold_needs_a_parent() -> None:
    from conftest import parse

    _, findings = parse(FOLD.format(extra="", revealed="[head]").replace("parent: head, ", ""))
    assert any(f.rule == "E007" and "fold" in f.message for f in findings)
