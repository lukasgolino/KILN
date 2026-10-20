"""`.kiln.yaml` parsing: valid models and every error rule (with a line and a helpful message)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from conftest import arms_text, errors_of, load, ok_model, parse, sphere_text
from kiln.notation import ROOT_ID
from kiln.project import Project
from pagan.findings import Finding


def rules(findings: list[Finding]) -> list[str]:
    return [f.rule for f in findings]


def only(findings: list[Finding], rule: str) -> Finding:
    hits = [f for f in findings if f.rule == rule]
    assert hits, [f.format() for f in findings]
    return hits[0]


def test_minimal_model_parses(project: Project) -> None:
    model, style = ok_model(project, sphere_text())
    assert model.name == "thing"
    assert model.cls == "prop" and model.status == "draft" and model.skin == "none"
    assert style.name == "fast"
    part = model.parts[0]
    assert part.id == ROOT_ID and part.color == "#e8413c" and part.color_name == "red" and part.material == "default"
    assert part.geometry.shape == "sphere"
    np.testing.assert_allclose(part.geometry.at, [0, 0.3, 0])
    assert model.ids == [ROOT_ID]


def test_full_model_parses(project: Project) -> None:
    text = """\
name: thing
description: a test
tags: [a, b]
status: approved
style_version: 1
class: character
budget: 500
lod: [200]
lint: { disable: [W106] }
parts:
  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4], round: 0.05 }
    color: wood
    material: wood
    pattern: { type: stripes, color: black, size: 0.1, axis: y, width: 0.3 }
  - cylinder: { radius: 0.05, height: 0.6, rotate: [0, 0, 90] }
    at: [0, 0.2, 0]
    cut: true
    blend: 0.01
  - sphere: { radius: 0.05 }
    at: [0.1, 0.45, 0]
    id: knob
    array: { count: 3, step: [0, 0, 0.1] }
    shell: 0.01
    noise: { amount: 0.002, scale: 0.05, seed: 3 }
    color: "#123456"
  - torus: { radius: 0.1, thickness: 0.02 }
    at: [0, 0.4, 0]
    id: ring
    array: { count: 4, around: y, center: [0, 0, 0] }
    twist: 10
    color: gold
    material: metal
rig:
  knob: { pivot: [0.1, 0.4, 0], meta: { hitzone: head, damage: 2 } }
  ring: { parent: knob, separate: true }
animations:
  spin: { fps: 10, cycle: { type: spin, part: ring, frames: 6 } }
  nod: { loop: false, interpolation: step, poses: [{ knob: { offset: [0, 0.01, 0], scale: 1.1 } }, {}] }
variants:
  night: { swap: { wood: blue, "#123456": black } }
"""
    model, _ = ok_model(project, text)
    assert model.description == "a test" and model.tags == ("a", "b") and model.status == "approved"
    assert model.cls == "character" and model.budget == 500 and model.lod == (200,) and model.lint_disable == ("W106",)
    assert [p.geometry.op for p in model.parts] == ["add", "cut", "add", "add"]
    assert model.parts[0].pattern is not None and model.parts[0].pattern.color == "#141414"
    assert model.parts[1].geometry.rotation is not None
    assert len(model.parts[2].geometry.copies) == 3 and model.parts[2].color == "#123456"
    assert len(model.parts[3].geometry.copies) == 4
    assert model.ids == [ROOT_ID, "knob", "ring"]
    assert model.skin == "rigid"  # a rig without skin: means rigid
    assert model.rig["knob"].meta == (("damage", 2), ("hitzone", "head"))
    assert model.rig["ring"].parent == "knob" and model.rig["ring"].separate
    assert model.animations["spin"].cycle is not None
    nod = model.animations["nod"]
    assert not nod.loop and nod.interpolation == "step" and len(nod.poses) == 2
    assert nod.poses[0]["knob"].scale == (1.1, 1.1, 1.1)
    assert model.variants["night"] == {"#a0663a": "#2f6fd0", "#123456": "#141414"}


def test_every_shape_parses() -> None:
    text = """\
name: shapes
parts:
  - sphere: { radius: 0.1 }
    color: red
  - ellipsoid: { radii: [0.1, 0.2, 0.1] }
    color: red
  - box: { size: [0.1, 0.1, 0.1] }
    color: red
  - cylinder: { radius: 0.1, height: 0.2 }
    color: red
  - cone: { radius: 0.1, height: 0.2, radius_top: 0.02 }
    color: red
  - capsule: { from: [0, 0, 0], to: [0, 1, 0], radius: 0.1 }
    color: red
  - tube: { points: [[0, 0, 0], [0, 1, 0], [1, 1, 0]], radius: 0.1, radius_to: 0.05 }
    color: red
  - torus: { radius: 0.2, thickness: 0.05 }
    color: red
  - lathe: { profile: [[0, 0], [0.2, 0], [0.1, 0.4], [0, 0.4]] }
    color: red
  - extrude: { points: [[0, 0], [1, 0], [0, 1]], height: 0.1 }
    color: red
  - wedge: { size: [1, 0.5, 1] }
    color: red
"""
    model, findings = parse(text)
    assert findings == []
    assert model is not None
    assert len(model.parts) == 11
    assert model.parts[5].geometry.params["radius_to"] == 0.1  # capsule taper defaults to no taper


def test_mirror_id_makes_a_mirrored_twin_with_its_rig(project: Project) -> None:
    model, _ = ok_model(project, arms_text())
    ids = [p.id for p in model.parts]
    assert ids == [ROOT_ID, "arm_l", "arm_r"]
    left, right = model.parts[1], model.parts[2]
    assert left.geometry.mirror == () and right.geometry.mirror == ()
    assert right.twin_of == "arm_l" and right.twin_axis == 0
    p = np.array([[0.4, 0.5, 0.0], [-0.4, 0.5, 0.0]])
    np.testing.assert_allclose(left.geometry.distance(p), right.geometry.distance(p[::-1]), atol=1e-12)
    assert left.geometry.distance(p[:1])[0] < 0 < left.geometry.distance(p[1:])[0]
    assert model.rig["arm_r"].pivot == (-0.3, 0.6, 0.0)
    assert model.rig["arm_l"].pivot == (0.3, 0.6, 0.0)


def test_mirror_id_twins_follow_twin_parents(project: Project) -> None:
    text = """\
name: thing
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    color: red
  - capsule: { from: [0.3, 0.4, 0], to: [0.5, 0.4, 0], radius: 0.05 }
    id: arm_l
    mirror: x
    mirror_id: arm_r
    color: red
  - sphere: { at: [0.55, 0.4, 0], radius: 0.06 }
    id: hand_l
    mirror: x
    mirror_id: hand_r
    color: white
rig:
  arm_l: { pivot: [0.3, 0.4, 0] }
  hand_l: { pivot: [0.5, 0.4, 0], parent: arm_l }
"""
    model, _ = ok_model(project, text)
    assert model.rig["hand_r"].parent == "arm_r"
    assert model.rig["hand_r"].pivot == (-0.5, 0.4, 0.0)


def test_mirror_without_id_folds_in_place() -> None:
    model, findings = parse("name: m\nparts:\n  - sphere: { at: [0.3, 0, 0], radius: 0.1 }\n    mirror: [x, z]\n    color: red\n")
    assert findings == [] and model is not None
    assert model.parts[0].geometry.mirror == (0, 2)


def test_e001_not_a_mapping(tmp_path: Path) -> None:
    _, findings = parse("- just a list\n", path=tmp_path / "x.kiln.yaml")
    assert rules(findings) == ["E001"]
    _, findings = parse("name: [unclosed\n", path=tmp_path / "x.kiln.yaml")
    assert rules(findings) == ["E001"]


def test_e002_unknown_fields(project: Project) -> None:
    text = """\
name: thing
colour: red
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3, raduis: 1 }
    color: red
    colour: blue
"""
    findings = errors_of(project, text)
    assert rules(findings) == ["E002", "E002", "E002"]
    top = findings[0]
    assert top.line == 2 and top.where == "colour" and "allowed:" in top.message
    part = next(f for f in findings if f.where == "parts[0]")
    assert part.line == 4 and "colour" in part.message
    shape = next(f for f in findings if f.where == "parts[0].sphere.raduis")
    assert "sphere has no field 'raduis'" in shape.message and "radius" in shape.message


@pytest.mark.parametrize(
    ("part", "where", "words"),
    [
        ("sphere: { radius: -1 }", "parts[0].sphere.radius", "a number > 0"),
        ("box: { size: [1, 1] }", "parts[0].box.size", "[x, y, z], each > 0"),
        ("box: { size: [0.2, 0.2, 0.2], round: 0.5 }", "parts[0].box.round", "bigger than half"),
        ("sphere: { radius: 1, at: [0, 1] }", "parts[0].sphere.at", "at must be [x, y, z]"),
        ("sphere: { radius: 1, rotate: 90 }", "parts[0].sphere.rotate", "degrees"),
        ("capsule: { from: [0, 0, 0], radius: 0.1 }", "parts[0].capsule", "needs to"),
        ("lathe: { profile: [[-1, 0], [1, 0], [1, 1]] }", "parts[0].lathe.profile", "r >= 0"),
        ("sphere: { radius: 1 }\n    blend: 2", "parts[0].blend", "smooth-join radius"),
        ("sphere: { radius: 1 }\n    shell: -1", "parts[0].shell", "wall thickness"),
        ("sphere: { radius: 1 }\n    mirror: w", "parts[0].mirror", "mirror is x, y, z"),
        ("sphere: { radius: 1 }\n    array: { count: 0, step: [1, 0, 0] }", "parts[0].array", "count (1-256)"),
        ("sphere: { radius: 1 }\n    array: { count: 3, around: w }", "parts[0].array", "ring array"),
        ("sphere: { radius: 1 }\n    noise: { scale: 1 }", "parts[0].noise", "amount"),
        ("sphere: { radius: 1 }\n    id: Arm", "parts[0].id", "lowercase"),
        ("sphere: { radius: 1 }\n    mirror_id: other", "parts[0].mirror_id", "exactly one mirror axis"),
        ("sphere: { radius: 1 }\n    pattern: { type: zigzag }", "parts[0].pattern", "stripes|checker|dots|band"),
        ("sphere: { radius: 1 }\n    pattern: { type: dots, color: blue, width: 2 }", "parts[0].pattern", "width 0..1"),
        ("sphere: { radius: 1 }\n    cut: yes please", "parts[0].cut", "true or false"),
        ("sphere: { radius: 1 }\n    cut: true\n    intersect: true", "parts[0]", "not both"),
        ("sphere: { radius: 1 }\n    sphere2: 1\n    box: { size: [1, 1, 1] }", "parts[0]", "exactly one shape"),
    ],
)
def test_e003_bad_part_values(part: str, where: str, words: str) -> None:
    color = "" if "cut: true" in part else "\n    color: red"
    model, findings = parse(f"name: thing\nparts:\n  - sphere: {{ at: [0, 0, 0], radius: 0.2 }}\n    color: red\n  - {part}{color}\n".replace("parts[0]", "x"))
    hits = [f for f in findings if f.rule == "E003"]
    assert hits, [f.format() for f in findings]
    f = hits[0]
    assert f.where == where.replace("parts[0]", "parts[1]")
    assert words in f.message, f.message
    assert f.line == 5


def test_e003_cut_parts_have_no_paint() -> None:
    _, findings = parse("name: m\nparts:\n  - sphere: { radius: 1 }\n    color: red\n  - sphere: { radius: 0.5 }\n    cut: true\n    color: red\n")
    f = only(findings, "E003")
    assert f.where == "parts[1].color" and "removes material" in f.message


@pytest.mark.parametrize(
    ("field", "where"),
    [
        ("name: Thing", "name"), ("tags: nope", "tags"), ("status: done", "status"), ("style_version: 0", "style_version"),
        ("class: Big Thing", "class"), ("budget: 5", "budget"), ("lod: [5]", "lod"), ("lint: { enable: [W101] }", "lint"),
        ("variants: { night: { swop: {} } }", "variants.night"), ("style: Fancy!", "style"),
    ],
)  # fmt: skip
def test_e003_bad_top_level_values(field: str, where: str) -> None:
    text = f"name: thing\n{field}\nparts:\n  - sphere: {{ radius: 0.2 }}\n    color: red\n"
    if field.startswith("name:"):
        text = text.replace("name: thing\n", "")
    _, findings = parse(text)
    f = only(findings, "E003")
    assert f.where == where
    assert f.message


def test_e003_name_must_match_the_file(tmp_path: Path) -> None:
    _, findings = parse("name: other\nparts:\n  - sphere: { radius: 0.2 }\n    color: red\n", path=tmp_path / "thing.kiln.yaml")
    f = only(findings, "E003")
    assert f.line == 1 and "thing.kiln.yaml" in f.message


def test_e003_parts_missing() -> None:
    _, findings = parse("name: thing\n")
    assert only(findings, "E003").where == "parts"


def test_e004_unknown_and_missing_colour(project: Project) -> None:
    findings = errors_of(project, "name: thing\nparts:\n  - sphere: { radius: 0.2 }\n    color: mauve\n  - sphere: { radius: 0.2 }\n")
    assert rules(findings) == ["E004", "E004"]
    assert findings[0].line == 3 and findings[0].where == "parts[0].color"
    assert "mauve" in findings[0].message and "red" in findings[0].message  # lists the palette's names
    assert findings[1].where == "parts[1].color" and "needs a color" in findings[1].message


def test_e004_palette_keys_and_hex_work(project: Project) -> None:
    model, _ = ok_model(project, "name: thing\nparts:\n  - sphere: { radius: 0.2 }\n    color: 2\n  - sphere: { radius: 0.1 }\n    color: '#ABCDEF'\n")
    assert model.parts[0].color == "#e8413c"
    assert model.parts[1].color == "#abcdef"


def test_e004_variant_colours(project: Project) -> None:
    findings = errors_of(project, sphere_text() + "variants:\n  night: { swap: { red: mauve } }\n")
    f = only(findings, "E004")
    assert f.where == "variants.night.swap"


def test_e004_missing_palette(tmp_path: Path) -> None:
    from conftest import make_project

    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "nope"\n')
    _, _, findings = load(project, sphere_text())
    assert "E004" in rules(findings)
    assert any("palette 'nope' not found" in f.message for f in findings)


def test_e005_unknown_material(project: Project) -> None:
    findings = errors_of(project, "name: thing\nparts:\n  - sphere: { radius: 0.2 }\n    color: red\n    material: velvet\n")
    f = only(findings, "E005")
    assert f.line == 3 and f.where == "parts[0].material"
    assert "velvet" in f.message and "plastic" in f.message


RIG_BASE = """\
name: thing
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    color: red
  - sphere: { at: [0.3, 0.5, 0], radius: 0.1 }
    id: a
    color: red
  - sphere: { at: [-0.3, 0.5, 0], radius: 0.1 }
    id: b
    color: red
"""


@pytest.mark.parametrize(
    ("rig", "where", "words"),
    [
        ("rig: [a]", "rig", "maps part ids"),
        ("rig:\n  c: { pivot: [0, 0, 0] }", "rig.c", "no part has id 'c'"),
        ("rig:\n  a: { pivit: [0, 0, 0] }", "rig.a", "a rig entry is"),
        ("rig:\n  a: { pivot: [0, 0] }", "rig.a.pivot", "pivot must be"),
        ("rig:\n  a: { parent: a }", "rig.a.parent", "another part id"),
        ("rig:\n  a: { parent: zz }", "rig.a.parent", "another part id"),
        ("rig:\n  a: { meta: { x: [1, 2] } }", "rig.a.meta", "plain values"),
        ("rig:\n  a: { separate: 1 }", "rig.a.separate", "true or false"),
        ("rig:\n  a: { parent: b }\n  b: { parent: a }", "rig.a", "cycle: a -> b -> a"),
        ("skin: floppy", "skin", "none (static)"),
    ],
)
def test_e007_rig_problems(project: Project, rig: str, where: str, words: str) -> None:
    findings = errors_of(project, RIG_BASE + rig + "\n")
    f = only(findings, "E007")
    assert f.where == where
    assert words in f.message, f.message
    assert f.line is not None


def test_e007_cycle_reports_its_line(project: Project) -> None:
    findings = errors_of(project, RIG_BASE + "rig:\n  a: { parent: b }\n  b: { parent: a }\n")
    cycles = [f for f in findings if "cycle" in f.message]
    assert {f.line for f in cycles} == {12, 13}


@pytest.mark.parametrize(
    ("anims", "where", "words"),
    [
        ("animations: [x]", "animations", "maps names"),
        ("animations:\n  Bad: { poses: [{}] }", "animations.Bad", "lowercase"),
        ("animations:\n  x: { fps: 12 }", "animations.x", "one of them"),
        ("animations:\n  x: { fps: 500, poses: [{}] }", "animations.x", "fps (1-120)"),
        ("animations:\n  x: { poses: [] }", "animations.x.poses", "a list of poses"),
        ("animations:\n  x: { poses: [{ zz: { rotate: [0, 0, 1] } }] }", "animations.x.poses[0].zz", "unknown part id 'zz'"),
        ("animations:\n  x: { poses: [{ a: { turn: [0, 0, 1] } }] }", "animations.x.poses[0].a", "offset: [x, y, z]"),
        ("animations:\n  x: { poses: [{ a: { scale: 0 } }] }", "animations.x.poses[0].a", "(> 0)"),
        ("animations:\n  x: { cycle: { type: moonwalk } }", "animations.x.cycle", "walk|waddle"),
        ("animations:\n  x: { cycle: { type: walk, legs: [a, leg_q] } }", "animations.x.cycle", "leg_q"),
    ],
)
def test_e008_animation_problems(project: Project, anims: str, where: str, words: str) -> None:
    findings = errors_of(project, RIG_BASE + "skin: rigid\n" + anims + "\n")
    f = only(findings, "E008")
    assert f.where == where
    assert words in f.message, f.message
    assert f.line is not None


def test_e008_animations_need_a_rig(project: Project) -> None:
    findings = errors_of(project, RIG_BASE + "animations:\n  x: { poses: [{ a: { rotate: [0, 0, 10] } }] }\n")
    f = only(findings, "E008")
    assert f.where == "animations" and "rig" in f.message


def test_e009_only_cuts(project: Project) -> None:
    findings = errors_of(project, "name: thing\nparts:\n  - sphere: { radius: 0.2 }\n    cut: true\n")
    f = only(findings, "E009")
    assert f.where == "parts" and f.line == 2


def test_e010_source_problems(project: Project) -> None:
    findings = errors_of(project, "name: thing\nsource: { file: imports/missing.glb, licence: CC0-1.0 }\n")
    f = only(findings, "E010")
    assert f.where == "source.file" and "missing.glb" in f.message
    (project.root / "imports" / "tree.glb").write_bytes(b"glTF")
    findings = errors_of(project, "name: thing\nsource: { file: imports/tree.glb }\n")
    assert only(findings, "E010").where == "source.licence"
    findings = errors_of(project, "name: thing\nsource: imports/tree.glb\n")
    assert only(findings, "E010").where == "source"
    findings = errors_of(project, "name: thing\nsource: { file: imports/tree.glb, licence: CC0-1.0, owner: me }\n")
    assert only(findings, "E002").where == "source"
    findings = errors_of(project, "name: thing\nsource: { file: imports/tree.glb, licence: CC0-1.0 }\nprocess: { height: -1 }\n")
    assert only(findings, "E003").where == "process.height"
    findings = errors_of(project, "name: thing\nsource: { file: imports/tree.glb, licence: CC0-1.0 }\nparts: []\n")
    assert only(findings, "E003").where == "source"


def test_source_with_process(project: Project) -> None:
    (project.root / "imports" / "tree.glb").write_bytes(b"glTF")
    model, _ = ok_model(project, "name: thing\nsource: { file: imports/tree.glb, licence: CC0-1.0, author: Kenney, url: x }\n"
                                 "process: { height: 2, recolor: keep, rotate: [0, 90, 0] }\n")  # fmt: skip
    src = model.source
    assert src is not None
    assert src.file == (project.root / "imports" / "tree.glb").resolve()
    assert (src.licence, src.author, src.url, src.height, src.recolor, src.rotate) == ("CC0-1.0", "Kenney", "x", 2.0, "keep", (0.0, 90.0, 0.0))


def test_e011_missing_decal_image(project: Project) -> None:
    text = sphere_text() + "    decal: { image: decals/logo.png, axis: z, at: [0, 0.3, 0.3], size: [0.2, 0.2] }\n"
    findings = errors_of(project, text)
    f = only(findings, "E011")
    assert f.where == "parts[0].decal.image" and "decals/logo.png" in f.message and f.line == 3


def test_decal_parses_and_mirrors(project: Project) -> None:
    from PIL import Image

    Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(project.root / "decals" / "logo.png")
    text = """\
name: thing
parts:
  - sphere: { at: [0.2, 0.3, 0], radius: 0.1 }
    id: ear_l
    mirror: x
    mirror_id: ear_r
    color: red
    decal: { image: decals/logo.png, axis: x, at: [0.3, 0.3, 0], size: [0.1, 0.1] }
"""
    model, _ = ok_model(project, text)
    left, right = model.parts[0].decal, model.parts[1].decal
    assert left is not None and right is not None
    assert left.axis == "x" and right.axis == "-x"
    assert right.at == (-0.3, 0.3, 0.0)
    bad = errors_of(project, text.replace("axis: x", "axis: w"))
    assert only(bad, "E003").where == "parts[0].decal"


def test_all_findings_are_collected(project: Project) -> None:
    text = """\
name: thing
parts:
  - sphere: { radius: -1 }
    color: red
  - sphere: { radius: 0.2 }
    color: mauve
  - sphere: { radius: 0.2 }
    color: red
    material: velvet
"""
    assert rules(errors_of(project, text)) == ["E003", "E004", "E005"]
