"""#200: pose bones by where they should point: `aim` (a model-space point) and `reach` (two-bone IK, `pole`)."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import built_of, errors_of, run_json, write_model

from kiln.export import Built
from kiln.project import Project
from kiln.rig import bone_end, skin_matrices

ARM = """\
name: thing
class: character
parts:
  - capsule: {{ from: [0, 0.3, 0], to: [0, 0.9, 0], radius: 0.15 }}
    color: red
  - capsule: {{ from: [0.2, 0.8, 0], to: [0.5, 0.8, 0], radius: 0.04 }}
    id: upper
    color: blue
  - capsule: {{ from: [0.5, 0.8, 0], to: [0.8, 0.8, 0], radius: 0.035 }}
    id: lower
    color: green
rig:
  upper: {{ pivot: [0.2, 0.8, 0] }}
  lower: {{ pivot: [0.5, 0.8, 0], parent: upper }}
animations:
  pose: {{ fps: 4, poses: [{pose}] }}
"""


def _world(built: Built, name: str, point: np.ndarray, frame: int = 0) -> np.ndarray:
    """Where a rest-pose point of bone `name` is at the animation's frame."""
    t = built.tracks[0]
    sk = built.skeleton
    m = skin_matrices(sk, t.translation[frame], t.rotation[frame], t.scale[frame])[sk.index(name)]
    return np.asarray((m @ np.append(point, 1.0))[:3], float)


def _tip(built: Built, name: str) -> np.ndarray:
    sk = built.skeleton
    end = bone_end(sk, sk.index(name))
    assert end is not None
    return _world(built, name, end)


def test_aim_points_a_bone_at_a_point(project: Project) -> None:
    built = built_of(project, ARM.format(pose="{ upper: { aim: [0.2, 1.5, 0.3] } }"))
    pivot = built.skeleton.bones[built.skeleton.index("upper")].pivot
    tip = _tip(built, "upper")
    want = np.array([0.2, 1.5, 0.3]) - pivot
    got = tip - pivot
    assert np.degrees(np.arccos(got @ want / np.linalg.norm(got) / np.linalg.norm(want))) < 0.5
    assert abs(np.linalg.norm(got) - 0.3) < 1e-6  # turned, not stretched


def test_reach_puts_the_childs_end_on_the_point(project: Project) -> None:
    goal = np.array([0.45, 1.2, 0.1])
    built = built_of(project, ARM.format(pose=f"{{ upper: {{ reach: [{goal[0]}, {goal[1]}, {goal[2]}] }} }}"))
    assert np.linalg.norm(_tip(built, "lower") - goal) < 1e-3
    elbow = _world(built, "upper", built.skeleton.bones[built.skeleton.index("lower")].pivot)
    assert elbow[2] < 0  # a straight arm's elbow bends back by default


def test_pole_picks_the_side_the_joint_bends_to(project: Project) -> None:
    goal = [0.45, 1.2, 0.1]
    built = built_of(project, ARM.format(pose=f"{{ upper: {{ reach: {goal}, pole: [0.4, 0.8, 1.0] }} }}"))
    elbow = _world(built, "upper", built.skeleton.bones[built.skeleton.index("lower")].pivot)
    assert elbow[2] > 0 and np.linalg.norm(_tip(built, "lower") - np.array(goal)) < 1e-3


def test_out_of_reach_stretches_toward_it(project: Project) -> None:
    built = built_of(project, ARM.format(pose="{ upper: { reach: [0.2, 3.0, 0] } }"))
    tip = _tip(built, "lower")
    assert abs(tip[0] - 0.2) < 1e-3 and abs(tip[1] - (0.8 + 0.6)) < 1e-3  # straight up, at full length


@pytest.mark.parametrize("pose", ["{ upper: { aim: [0, 1, 0], rotate: [0, 0, 10] } }", "{ upper: { pole: [0, 1, 0] } }",
                                  "{ upper: { aim: [0, 1] } }", "{ upper: { aim: [0, 1, 0], reach: [0, 1, 0] } }"])  # fmt: skip
def test_bad_targets_are_refused(project: Project, pose: str) -> None:
    assert any(f.rule == "E008" for f in errors_of(project, ARM.format(pose=pose))), pose


def test_preview_pose_json_gives_bone_ends(project: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(project, ARM.format(pose="{ upper: { reach: [0.45, 1.2, 0.1] } }"))
    monkeypatch.chdir(project.root)
    code, out = run_json(["preview", "thing", "--pose", "pose", "--size", "64"], capsys)
    assert code == 0, out
    ends = out["ends"]["pose"]
    assert np.linalg.norm(np.array(ends["lower"][0]) - np.array([0.45, 1.2, 0.1])) < 2e-3


TURNED = """\
name: thing
class: character
parts:
  - capsule: { from: [0, 0.3, 0], to: [0, 0.9, 0], radius: 0.15 }
    id: chest
    color: red
  - capsule: { from: [0.2, 0.8, 0], to: [0.5, 0.8, 0], radius: 0.04 }
    id: arm
    color: blue
rig:
  chest: { pivot: [0, 0.3, 0] }
  arm: { pivot: [0.2, 0.8, 0], parent: chest }
animations:
  pose: { fps: 4, poses: [{ chest: { rotate: [0, YAW, 0] }, arm: { aim: [0.3, 0.8, 1.5] } }] }
"""


@pytest.mark.parametrize("yaw", [0, 30, 45, -60, -90])
def test_aim_under_a_turned_parent_keeps_the_arm_upright(project: Project, yaw: int) -> None:
    a = np.radians(yaw)  # the arm's joint once the chest turns, and a point straight ahead of it (a quarter turn about y)
    pivot = np.array([0.2 * np.cos(a), 0.8, -0.2 * np.sin(a)])
    goal = pivot + np.array([0.0, 0.0, 1.0])
    built = built_of(project, TURNED.replace("YAW", str(yaw)).replace("[0.3, 0.8, 1.5]", f"[{goal[0]:.9f}, {goal[1]:.9f}, {goal[2]:.9f}]"))
    sk = built.skeleton
    t = built.tracks[0]
    from kiln.rig import world_matrices

    arm = world_matrices(sk, t.translation[0], t.rotation[0], t.scale[0])[sk.index("arm")][:3, :3]
    assert arm @ np.array([0.0, 1.0, 0.0]) @ np.array([0.0, 1.0, 0.0]) > 0.9  # not rolled over (#200 review)
    tip = _tip(built, "arm")
    want = goal - pivot
    assert np.degrees(np.arccos((tip - pivot) @ want / np.linalg.norm(tip - pivot) / np.linalg.norm(want))) < 0.5


def test_reach_inside_a_cycle_follows_the_moving_root(project: Project) -> None:
    goal = [0.45, 1.2, 0.1]
    text = ARM.format(pose=f"{{ upper: {{ reach: {goal} }} }}").replace(
        "  pose: { fps: 4, poses:", "  pose: { fps: 4, cycle: { type: bob, parts: [root], amount: 0.1 }, poses:")
    built = built_of(project, text)
    for f in range(built.tracks[0].frames):
        sk = built.skeleton
        end = bone_end(sk, sk.index("lower"))
        assert end is not None
        assert np.linalg.norm(_world(built, "lower", end, f) - np.array(goal)) < 2e-3, f


def test_lint_says_when_reach_only_aims(project: Project) -> None:
    from kiln.lint import lint_paths

    path = write_model(project, ARM.format(pose="{ lower: { reach: [0.6, 1.0, 0] } }"))
    found = [f for f in lint_paths(project, [path]).findings if f.rule == "W132"]
    assert len(found) == 1 and "lower" in found[0].message


@pytest.mark.parametrize("b", [90.0, -90.0])
def test_euler_at_the_gimbal_reads_the_turn_back(b: float) -> None:
    from kiln.rig import _euler_of
    from kiln.sdf import rotation_matrix

    rng = np.random.default_rng(1)
    for c in (-150.0, -45.0, 10.0, 120.0):
        r = rotation_matrix((0.0, b, c)) + rng.normal(0, 1e-13, (3, 3))  # rounding noise where cos(y) = 0
        assert np.abs(rotation_matrix(_euler_of(r)) - r).max() < 1e-6, c
