"""#192: skin_falloff keeps a blended part's surface on its own bone in a soft skin."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model
from test_retarget import HERO

from kiln.lint import lint_paths
from kiln.project import Project

SLEEVE = "  - capsule: { from: [0.16, 1.0, 0], to: [0.24, 0.85, 0], radius: 0.075 }\n    id: upperarm_l\n    mirror: x\n    mirror_id: upperarm_r\n" \
         "    color: blue\n    blend: 0.06\n"


def arm_interior(project: Project, extra: str) -> tuple[np.ndarray, object]:
    text = HERO.split("animations:")[0].replace("rig:\n", SLEEVE + extra + "rig:\n", 1)
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    p = built.painted
    names = [b.name for b in built.skeleton.bones]
    arm = names.index("upperarm_l")
    assert built.joints is not None and built.weights is not None
    w = np.where(built.joints == arm, built.weights, 0).sum(axis=1)
    bone = np.array([p.groups[g].bone for g in p.face_group])
    mine = np.zeros(len(p.vertices), dtype=bool)
    mine[p.faces[bone == "upperarm_l"].reshape(-1)] = True
    other = np.zeros(len(p.vertices), dtype=bool)
    other[p.faces[bone != "upperarm_l"].reshape(-1)] = True
    return w[mine & ~other], built


def test_the_sleeve_follows_its_arm(project: Project) -> None:
    plain, before = arm_interior(project, "")
    assert (plain < 0.9).mean() > 0.5  # blended into the chest: much of the sleeve follows the chest too
    sharp, built = arm_interior(project, "    skin_falloff: 0\n")
    assert sharp.min() > 0.99  # off its colour's border it is the arm's alone
    soft, _ = arm_interior(project, "    skin_falloff: 0.03\n")
    assert plain.mean() < soft.mean() < sharp.mean()  # a falloff fades over to the arm away from the border
    assert np.allclose(built.weights.sum(axis=1), 1) and np.allclose(before.weights.sum(axis=1), 1)  # type: ignore[attr-defined]


def test_only_the_parts_own_painted_surface_changes(project: Project) -> None:
    _, before = arm_interior(project, "")
    _, after = arm_interior(project, "    skin_falloff: 0\n")
    p = after.painted  # type: ignore[attr-defined]
    bone = np.array([p.groups[g].bone for g in p.face_group])
    arm = np.zeros(len(p.vertices), dtype=bool)
    arm[p.faces[np.isin(bone, ["upperarm_l", "upperarm_r"])].reshape(-1)] = True  # the sleeve and its mirror_id twin
    assert np.array_equal(before.joints[~arm], after.joints[~arm]) and np.array_equal(before.weights[~arm], after.weights[~arm])  # type: ignore[attr-defined]


def test_notation(project: Project) -> None:
    for bad in ("-0.1", "1", "soft"):
        _, _, findings = load(project, HERO.split("animations:")[0].replace("rig:\n", SLEEVE + f"    skin_falloff: {bad}\n" + "rig:\n", 1))
        assert any((f.where or "").endswith(".skin_falloff") for f in findings), (bad, findings)
