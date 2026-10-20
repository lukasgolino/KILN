"""Skeletons, skin weights, cycles, quaternions and tracks."""

from __future__ import annotations

import math

import numpy as np
import pytest

from conftest import arms_text, built_of, ok_model
from kiln.builder import field_of
from kiln.notation import CYCLES, Animation
from kiln.project import Project
from kiln.rig import build_skeleton, expand_cycle, quaternion, skin_matrices, soft_weights, tracks, world_matrices
from kiln.sdf import rotation_matrix

CHAIN = """\
name: thing
class: character
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3 }
    color: red
  - sphere: { at: [0, 0.75, 0], radius: 0.15 }
    id: head
    color: red
  - sphere: { at: [0, 0.95, 0], radius: 0.06 }
    id: hat
    color: blue
  - capsule: { from: [0.2, 0.15, 0], to: [0.2, 0.0, 0], radius: 0.08 }
    id: leg_l
    mirror: x
    mirror_id: leg_r
    blend: 0.05
    color: red
  - capsule: { from: [0.3, 0.4, 0], to: [0.45, 0.25, 0], radius: 0.06 }
    id: arm_l
    mirror: x
    mirror_id: arm_r
    blend: 0.04
    color: red
rig:
  hat: { parent: head, pivot: [0, 0.9, 0] }
  head: { pivot: [0, 0.6, 0], meta: { hitzone: head } }
  leg_l: { pivot: [0.2, 0.15, 0] }
  arm_l: { pivot: [0.3, 0.4, 0] }
skin: soft
"""


def test_skeleton_order_parents_and_pivots(project: Project) -> None:
    model, _ = ok_model(project, CHAIN)
    field = field_of(model, 0.03)
    sk = build_skeleton(model, field)
    names = [b.name for b in sk.bones]
    assert names[0] == "root" and sk.bones[0].parent == -1
    assert set(names) == {"root", "head", "hat", "leg_l", "leg_r", "arm_l", "arm_r"}
    for i, bone in enumerate(sk.bones[1:], start=1):
        assert 0 <= bone.parent < i  # parents first
    hat = sk.bones[sk.index("hat")]
    assert sk.bones[hat.parent].name == "head"
    np.testing.assert_allclose(hat.pivot, [0, 0.9, 0])
    np.testing.assert_allclose(sk.rest_translation(sk.index("hat")), [0, 0.3, 0])
    np.testing.assert_allclose(sk.bones[sk.index("leg_r")].pivot, [-0.2, 0.15, 0])
    assert sk.bones[sk.index("head")].meta == {"hitzone": "head"}


def test_default_pivot_is_the_box_centre(project: Project) -> None:
    text = "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n  - sphere: { at: [0.5, 0.4, 0], radius: 0.1 }\n    id: nub\n    color: red\nskin: rigid\n"
    model, _ = ok_model(project, text)
    sk = build_skeleton(model, field_of(model, 0.03))
    np.testing.assert_allclose(sk.bones[sk.index("nub")].pivot, [0.5, 0.4, 0])


def test_soft_weights_sum_to_one(project: Project) -> None:
    built = built_of(project, CHAIN)
    assert built.joints is not None and built.weights is not None
    j, w = built.joints, built.weights
    assert j.shape == w.shape == (len(built.painted.vertices), 4)
    np.testing.assert_allclose(w.sum(axis=1), 1.0, atol=1e-9)
    assert np.all(j[w == 0] == 0)  # unused influences point at joint 0
    assert np.all(w >= 0) and int(j.max()) < len(built.skeleton.bones)
    # a vertex at the bottom of a foot belongs to the leg
    sk = built.skeleton
    v = built.painted.vertices
    foot = int(np.argmin(np.linalg.norm(v - [0.2, -0.08, 0], axis=1)))
    assert j[foot, 0] == sk.index("leg_l") and w[foot, 0] > 0.75


def test_soft_weights_blend_at_joints(project: Project) -> None:
    model, _ = ok_model(project, CHAIN)
    field = field_of(model, 0.03)
    sk = build_skeleton(model, field)
    joint = np.array([[0.2, 0.17, 0.0]])  # where the leg blends into the body
    j, w = soft_weights(joint, model, field, sk, 0.03)
    used = {int(a) for a, b in zip(j[0], w[0], strict=True) if b > 0.05}
    assert {sk.index("leg_l"), sk.index("root")} <= used


def test_quaternion_of_known_rotations() -> None:
    np.testing.assert_allclose(quaternion((0, 0, 0)), [0, 0, 0, 1])
    s = math.sqrt(0.5)
    np.testing.assert_allclose(quaternion((90, 0, 0)), [s, 0, 0, s], atol=1e-9)
    np.testing.assert_allclose(quaternion((0, 90, 0)), [0, s, 0, s], atol=1e-9)
    np.testing.assert_allclose(quaternion((0, 0, -90)), [0, 0, -s, s], atol=1e-9)
    q = quaternion((180, 0, 0))
    np.testing.assert_allclose(np.abs(q), [1, 0, 0, 0], atol=1e-9)
    for angles in ((30, 40, 50), (170, -20, 95), (-120, 80, 10)):
        q = quaternion(angles)
        x, y, z, w_ = q
        m = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w_), 2 * (x * z + y * w_)],
                      [2 * (x * y + z * w_), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w_)],
                      [2 * (x * z - y * w_), 2 * (y * z + x * w_), 1 - 2 * (x * x + y * y)]])  # fmt: skip
        np.testing.assert_allclose(m, rotation_matrix(angles), atol=1e-8)


@pytest.mark.parametrize("cycle", CYCLES)
def test_cycles_expand_to_poses(project: Project, cycle: str) -> None:
    model, _ = ok_model(project, CHAIN)
    spec = {"type": cycle, "frames": 6, "part": "head"}
    poses = expand_cycle(Animation("x", 12.0, True, "linear", [], spec), model)
    assert len(poses) == 6
    moved = {name for pose in poses for name in pose}
    assert moved and moved <= set(model.ids)
    changing = [name for name in moved if len({repr(p.get(name)) for p in poses}) > 1]
    assert changing, cycle
    expected = {"walk": {"leg_l", "leg_r", "arm_l", "arm_r", "root"}, "waddle": {"leg_l", "leg_r", "root"}, "wave": {"arm_r"}}
    if cycle in ("hop", "bob", "spin", "swing", "breathe"):
        assert moved == {"head"}
    else:
        assert expected[cycle] <= moved


def test_spin_turns_a_full_circle(project: Project) -> None:
    model, _ = ok_model(project, CHAIN)
    poses = expand_cycle(Animation("x", 12.0, True, "linear", [], {"type": "spin", "part": "hat", "frames": 4, "axis": "y"}), model)
    assert [p["hat"].rotate for p in poses] == [(0, 0, 0), (0, 90, 0), (0, 180, 0), (0, 270, 0)]


def test_tracks_hold_rest_and_poses(project: Project) -> None:
    model, _ = ok_model(project, arms_text())
    sk = build_skeleton(model, field_of(model, 0.03))
    out = {t.name: t for t in tracks(model, sk)}
    assert set(out) == {"wave", "hold"}
    hold = out["hold"]
    assert hold.frames == 2 and not hold.loop and hold.fps == 4
    arm = sk.index("arm_l")
    np.testing.assert_allclose(hold.rotation[1, arm], quaternion((0, 0, -60)))
    np.testing.assert_allclose(hold.rotation[:, sk.index("arm_r")], [[0, 0, 0, 1]] * 2)  # not posed: rest
    np.testing.assert_allclose(hold.translation[0, arm], sk.rest_translation(arm))
    np.testing.assert_allclose(hold.scale, 1.0)


def test_skin_matrices_are_identity_at_rest(project: Project) -> None:
    model, _ = ok_model(project, CHAIN)
    sk = build_skeleton(model, field_of(model, 0.03))
    n = len(sk.bones)
    rest = np.array([sk.rest_translation(i) for i in range(n)])
    rot = np.tile([0.0, 0.0, 0.0, 1.0], (n, 1))
    mats = skin_matrices(sk, rest, rot, np.ones((n, 3)))
    np.testing.assert_allclose(mats, np.tile(np.eye(4), (n, 1, 1)), atol=1e-12)
    world = world_matrices(sk, rest, rot, np.ones((n, 3)))
    np.testing.assert_allclose(world[sk.index("hat"), :3, 3], [0, 0.9, 0])


def test_children_follow_their_parents(project: Project) -> None:
    model, _ = ok_model(project, CHAIN)
    sk = build_skeleton(model, field_of(model, 0.03))
    n = len(sk.bones)
    tr = np.array([sk.rest_translation(i) for i in range(n)])
    rot = np.tile([0.0, 0.0, 0.0, 1.0], (n, 1))
    head = sk.index("head")
    rot[head] = quaternion((0, 0, 90))
    mats = skin_matrices(sk, tr, rot, np.ones((n, 3)))
    hat_top = mats[sk.index("hat")] @ [0, 1.0, 0, 1]  # 0.4 above the head pivot
    np.testing.assert_allclose(hat_top[:3], [-0.4, 0.6, 0], atol=1e-9)


def test_soft_weights_are_vec4_with_few_bones(project: Project) -> None:
    built = built_of(project, arms_text(skin="soft"))
    assert len(built.skeleton.bones) == 3
    assert built.joints is not None and built.weights is not None
    assert built.joints.shape == built.weights.shape == (len(built.painted.vertices), 4)
    np.testing.assert_allclose(built.weights.sum(axis=1), 1.0, atol=1e-9)
    assert np.all(built.weights[:, 3] == 0) and np.all(built.joints[:, 3] == 0)
