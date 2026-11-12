"""#255: lint W135, a limb fused to the body at rest (away from its joint)."""

from __future__ import annotations

from conftest import write_model

from kiln.lint import lint_paths
from kiln.project import Project

BODY = """\
name: thing
class: creature
parts:
  - ellipsoid: {{ at: [0, 0.6, 0], radii: [0.25, 0.4, 0.2] }}
    color: red
  - capsule: {{ from: [{x}, 0.95, 0], to: [{x2}, 0.45, 0], radius: 0.06 }}
    id: arm_l
    color: red
    blend: 0.03
    mirror: x
    mirror_id: arm_r
rig:
  arm_l: {{ pivot: [{x}, 0.95, 0] }}
skin: soft
"""


def rules(project: Project, x: float, x2: float) -> list[str]:
    result = lint_paths(project, [write_model(project, BODY.format(x=x, x2=x2))])
    return [f.rule for f in result.findings]


def test_an_arm_hanging_into_the_belly_warns(project: Project) -> None:
    assert "W135" in rules(project, 0.24, 0.24)  # straight down through the side of the body


def test_an_arm_held_out_does_not(project: Project) -> None:
    assert "W135" not in rules(project, 0.24, 0.55)  # an A-pose: it meets the body only at the shoulder


def test_torso_pieces_and_a_head_are_meant_to_merge(project: Project) -> None:
    belly = "  - sphere: { at: [0, 0.75, 0.12], radius: 0.15 }\n    id: belly\n    color: red\n    blend: 0.05\n"
    text = BODY.format(x=0.24, x2=0.55).replace("rig:\n", belly + "rig:\n  belly: { pivot: [0, 0.45, 0] }\n")
    result = lint_paths(project, [write_model(project, text)])
    assert not [f for f in result.findings if f.severity == "error"], [f.format() for f in result.findings]
    assert "W135" not in [f.rule for f in result.findings], [f.format() for f in result.findings]
