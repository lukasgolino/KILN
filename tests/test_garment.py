"""#193: garment, a layer of clothing fitted to earlier parts."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project

TORSO = """\
name: thing
resolution: 0.008
budget: 6000
parts:
  - capsule: { from: [0, 0.6, 0], to: [0, 1.2, 0], radius: 0.22 }
    id: body
    color: wood
  - garment: { fit: [body], gap: 0.01, from_y: 0.75, to_y: 1.3, hem: 0.015, openings: [{ at: [0, 1.05, 0.25], size: [0.14, 0.25, 0.12] }] }
    id: shirt
    color: blue
"""


def test_it_expands_to_a_fitted_shell_a_hem_and_a_cut(project: Project) -> None:
    model, _, findings = load(project, TORSO)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    shirt = [p for p in model.parts if p.id == "shirt"]
    assert len(shirt) == 2 and all(p.geometry.shell > 0 and p.geometry.fit is not None for p in shirt)  # the layer and its hem
    assert shirt[1].geometry.shell > shirt[0].geometry.shell  # the hem is thicker
    opening = model.parts[-1]
    assert opening.geometry.op == "cut" and opening.cut_only == ("shirt",)


def test_it_builds_a_layer_off_the_body(project: Project) -> None:
    built = lint_paths(project, [write_model(project, TORSO)]).built["thing"]
    p = built.painted
    names = [g.color_name.split("#")[0] for g in p.groups]
    v = p.vertices[np.unique(p.faces[p.face_group == names.index("blue")])]
    radius = np.linalg.norm(v[:, [0, 2]], axis=1)
    middle = (v[:, 1] > 0.85) & (v[:, 1] < 1.15)
    assert float(np.median(radius[middle])) > 0.22 + 0.01  # outside the body by about the gap and the wall
    assert v[:, 1].min() > 0.74 and v[:, 1].max() < 1.31  # between its hem and its top
    body = p.vertices[p.faces[p.face_group == names.index("wood")]].mean(axis=1)  # face centres
    front = (np.abs(body[:, 0]) < 0.05) & (np.abs(body[:, 1] - 1.05) < 0.1) & (body[:, 2] > 0.18)
    assert front.any()  # the body shows through the opening ...
    assert (body[:, 1] < 0.74).any()  # ... and below the hem


def test_errors(project: Project) -> None:
    for bad, why in (("fit: [nobody]", "no earlier part"), ("fit: [body], from_y: 1.3, to_y: 0.8", "from_y < to_y"),
                     ("fit: [body], openings: [{ at: [0, 1, 0] }]", "openings[0]"), ("fit: [body], colour: red", "garment: {")):
        _, _, findings = load(project, TORSO.replace("fit: [body], gap: 0.01, from_y: 0.75, to_y: 1.3, hem: 0.015, openings: [{ at: [0, 1.05, 0.25], size: [0.14, 0.25, 0.12] }]", bad))
        assert any(why in f.message for f in findings), (bad, findings)
    _, _, findings = load(project, TORSO.replace("    id: shirt\n", ""))
    assert any("give it an id" in f.message for f in findings), findings


def test_a_sleeve_on_a_rigged_arm_skins_to_the_arm(project: Project) -> None:
    from test_retarget import HERO

    sleeve = "  - garment: { fit: [upperarm_l], gap: 0.006, thickness: 0.02, hem: 0 }\n    id: upperarm_l\n    mirror: x\n    mirror_id: upperarm_r\n" \
             "    color: blue\nFALLOFF"

    def arm_weight(falloff: str) -> float:
        text = HERO.split("animations:")[0].replace("rig:\n", sleeve.replace("FALLOFF", falloff) + "rig:\n", 1)
        built = lint_paths(project, [write_model(project, text.replace("name: thing\n", "name: thing\nresolution: 0.008\nbudget: 8000\n", 1))]).built["thing"]
        p = built.painted
        arm = [b.name for b in built.skeleton.bones].index("upperarm_l")
        blue = [g for g, grp in enumerate(p.groups) if grp.color_name.split("#")[0] == "blue" and grp.bone == "upperarm_l"]
        v = np.unique(p.faces[np.isin(p.face_group, blue)])
        assert built.joints is not None and built.weights is not None and len(v)
        return float(np.median(np.where(built.joints[v] == arm, built.weights[v], 0).sum(axis=1)))

    assert arm_weight("") > 0.6  # the sleeve is the arm's bone (its id): mostly the arm's, blending at the shoulder
    assert arm_weight("    skin_falloff: 0\n") > 0.95  # and wholly with skin_falloff


def test_a_shirt_over_trousers_and_a_mirrored_garment(project: Project) -> None:
    layered = TORSO.replace("  - garment:", "  - garment: { fit: [body], gap: 0.01, from_y: 0.5, to_y: 0.9, hem: 0 }\n    id: trousers\n    color: wood\n  - garment:", 1) \
        .replace("fit: [body], gap: 0.01, from_y: 0.75", "fit: [body, trousers], gap: 0.01, from_y: 0.75", 1)
    model, _, findings = load(project, layered)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    shirt = next(p for p in model.parts if p.id == "shirt")
    assert shirt.geometry.fit is not None and len(shirt.geometry.fit[0]) == 2  # the trousers' wall is wrapped too
    mirrored = TORSO.replace("    id: shirt\n", "    id: shirt\n    mirror: x\n    mirror_id: shirt_r\n").replace("at: [0, 1.05, 0.25]", "at: [0.1, 1.05, 0.25]")
    model, _, findings = load(project, mirrored)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    cuts = {(p.cut_only or ("",))[0]: list(p.geometry.at) for p in model.parts if p.geometry.op == "cut"}
    assert set(cuts) == {"shirt", "shirt_r"} and cuts["shirt"][0] == -cuts["shirt_r"][0]


def test_an_id_clash_with_openings_and_dropped_fields_are_errors(project: Project) -> None:
    _, _, findings = load(project, TORSO.replace("    id: shirt\n", "    id: body\n"))
    assert any("not one of the parts it fits" in f.message for f in findings), findings
    for extra in ("    rotate: [0, 10, 0]\n", "    hard: true\n"):
        _, _, findings = load(project, TORSO.replace("    id: shirt\n", "    id: shirt\n" + extra))
        assert any("garment takes no" in f.message for f in findings), (extra, findings)


def test_w113_quiet_on_openings_and_worn_parts_but_not_a_real_poke(project: Project) -> None:
    """#313: a head through a garment's open neck, an arm in its own sleeve through the side: intended. A spike through
    the shirt's wall still warns."""
    head = "  - sphere: { at: [0, 1.42, 0], radius: 0.16 }\n    id: head\n    color: wood\n    blend: 0.03\n"
    arm = ("  - capsule: { from: [0.12, 1.12, 0], to: [0.55, 0.95, 0], radius: 0.07 }\n    id: arm\n    color: wood\n    blend: 0.03\n"
           "  - garment: { fit: [arm], gap: 0.008, thickness: 0.02, hem: 0 }\n    id: sleeve\n    color: blue\n")  # fmt: skip
    text = TORSO.replace("  - garment:", head + arm + "  - garment:", 1)
    rules = [f for f in lint_paths(project, [write_model(project, text)]).findings if f.rule == "W113"]
    assert not rules, [f.format() for f in rules]
    spike = "  - cone: { aim: [[0.1, 0.85, 0.1], [0.2, 0.85, 0.4]], radius: 0.04 }\n    color: wood\n"
    rules = [f for f in lint_paths(project, [write_model(project, text + spike)]).findings if f.rule == "W113"]
    assert rules, "a cone through the shirt's front wall"
