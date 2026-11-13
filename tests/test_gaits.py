"""#150: built-in gaits bend knees and elbows on models with lower limbs; run and sneak."""

from __future__ import annotations

import math

import numpy as np
from conftest import load, write_model
from test_retarget import HERO

from kiln.lint import lint_paths
from kiln.project import Project
from kiln.render import posed
from kiln.rig import animation_poses

CYCLES = HERO.split("animations:")[0] + """animations:
  walk: { fps: 12, cycle: { type: walk } }
  run: { fps: 12, cycle: { type: run } }
  sneak: { fps: 12, cycle: { type: sneak } }
"""


def test_a_humanoid_walk_swings_its_legs_and_bends_knees_and_elbows(project: Project) -> None:
    model, _, findings = load(project, CYCLES)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    frames = animation_poses(model.animations["walk"], model)
    assert all({"upperleg_l", "upperleg_r", "upperarm_l", "lowerleg_l", "lowerarm_r"} <= set(f) for f in frames)  # not the hips only
    knee = [f["lowerleg_l"].rotate[0] for f in frames]
    assert min(knee) >= 5 - 1e-9 and max(knee) > 40  # always a little bent, most while swinging forward
    for kind in ("run", "sneak"):
        poses = animation_poses(model.animations[kind], model)
        assert poses[0]["spine"].rotate[0] > 0  # leaning forward (the spine, not the legs with it)


def test_bends_point_the_right_way(project: Project) -> None:
    built = lint_paths(project, [write_model(project, CYCLES)]).built["thing"]
    p = built.painted
    bones = np.array([p.groups[g].bone for g in p.face_group])
    names = [t.name for t in built.tracks]

    def moved(anim: str, part: str) -> float:
        pos, _ = posed(built, names.index(anim), 0)
        m = bones == part
        return float(pos[m].reshape(-1, 3).mean(axis=0)[2] - p.vertices[p.faces[m]].reshape(-1, 3).mean(axis=0)[2])

    assert moved("sneak", "upperleg_l") > 0.02 and moved("sneak", "foot_l") < -0.01  # thighs forward, feet folded back
    assert moved("run", "hand_l") > 0.1 and moved("run", "head") > 0.05  # forearms forward, leaning into it
    assert moved("run", "foot_l") < -0.03


def test_a_model_without_lower_limbs_walks_as_before(project: Project) -> None:
    text = """\
name: thing
parts:
  - sphere: { at: [0, 0.5, 0], radius: 0.3 }
    color: wood
  - capsule: { from: [0.12, 0.3, 0], to: [0.12, 0.05, 0] }
    radius: 0.05
    id: leg_l
    mirror: x
    mirror_id: leg_r
    color: wood
rig:
  leg_l: { pivot: [0.12, 0.3, 0] }
animations:
  walk: { fps: 12, cycle: { type: walk, swing: 24 } }
""".replace("[0.12, 0.05, 0] }\n    radius: 0.05", "[0.12, 0.05, 0], radius: 0.05 }")
    model, _, findings = load(project, text)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    frames = animation_poses(model.animations["walk"], model)
    for i, f in enumerate(frames):
        t = i / len(frames)
        assert math.isclose(f["leg_l"].rotate[0], 24 * math.sin(2 * math.pi * t), abs_tol=1e-9)
        assert set(f) == {"leg_l", "leg_r", "root"} and f["root"].rotate == (0.0, 0.0, 0.0)


def lowest_per_frame(project: Project, text: str, anim: str) -> list[float]:
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    ti = [t.name for t in built.tracks].index(anim)
    rest = built.painted.vertices[np.unique(built.painted.faces)][:, 1].min()
    return [float(posed(built, ti, f)[0].reshape(-1, 3)[:, 1].min() - rest) for f in range(built.tracks[ti].frames)]


def test_feet_stay_on_the_ground(project: Project) -> None:
    for anim in ("walk", "run", "sneak"):
        assert all(abs(d) < 0.012 for d in lowest_per_frame(project, CYCLES, anim)), anim  # no floating, no sinking (soft skin: ~1 cm)


def test_humanoid_names_without_the_skeleton_and_listed_limbs_keep_the_old_walk(project: Project) -> None:
    plain = CYCLES.replace("skeleton: humanoid\n", "")
    model, _, _ = load(project, plain)
    assert model is not None
    assert all(set(f) <= {"root"} for f in animation_poses(model.animations["walk"], model))  # nothing named leg_l: as before
    listed = CYCLES.replace("walk: { fps: 12, cycle: { type: walk } }", "walk: { fps: 12, cycle: { type: walk, legs: [upperleg_l, upperleg_r], arms: [] } }")
    model, _, _ = load(project, listed)
    assert model is not None
    moved = {n for f in animation_poses(model.animations["walk"], model) for n in f}
    assert "lowerarm_l" not in moved and "lowerleg_l" not in moved  # listed limbs: no default bends


def test_a_t_posed_arm_swings_forward_and_back(project: Project) -> None:
    tpose = CYCLES.replace("capsule: { from: [0.2, 1.02, 0], to: [0.24, 0.8, 0], radius: 0.055 }", "capsule: { from: [0.2, 1.02, 0], to: [0.45, 1.02, 0], radius: 0.055 }") \
        .replace("capsule: { from: [0.24, 0.8, 0], to: [0.26, 0.6, 0], radius: 0.048 }", "capsule: { from: [0.45, 1.02, 0], to: [0.65, 1.02, 0], radius: 0.048 }") \
        .replace("sphere: { at: [0.265, 0.55, 0], radius: 0.05 }", "sphere: { at: [0.7, 1.02, 0], radius: 0.05 }") \
        .replace("lowerarm_l: { pivot: [0.24, 0.8, 0] }", "lowerarm_l: { pivot: [0.45, 1.02, 0] }").replace("hand_l: { pivot: [0.26, 0.6, 0] }", "hand_l: { pivot: [0.65, 1.02, 0] }")
    built = lint_paths(project, [write_model(project, tpose)]).built["thing"]
    p = built.painted
    hand = np.array([p.groups[g].bone for g in p.face_group]) == "hand_l"
    ti = [t.name for t in built.tracks].index("run")
    z = [float(posed(built, ti, f)[0][hand].reshape(-1, 3).mean(axis=0)[2]) for f in range(built.tracks[ti].frames)]
    assert max(z) - min(z) > 0.3  # the hand sweeps forward and back, not a twist in place


def test_wave_raises_a_humanoids_arm(project: Project) -> None:
    model, _, _ = load(project, CYCLES.replace("  walk: { fps: 12, cycle: { type: walk } }", "  hi: { fps: 8, cycle: { type: wave } }"))
    assert model is not None
    assert all(set(f) == {"upperarm_r"} for f in animation_poses(model.animations["hi"], model))


def test_idle_breathes_sways_glances_and_settles(project: Project) -> None:
    """#150: an idle cycle with life: the chest breathes and sways, the head looks aside, arms and elbows settle."""
    text = HERO.split("animations:")[0] + "animations:\n  idle: { fps: 8, cycle: { type: idle, frames: 24 } }\n"
    model, _, findings = load(project, text)
    assert model is not None and not [f for f in findings if f.severity == "error"], findings
    frames = animation_poses(model.animations["idle"], model)
    assert len(frames) == 24
    chest = [f["chest"].scale[1] for f in frames]
    look = [f["head"].rotate[1] for f in frames]
    assert max(chest) > 1.01 and min(chest) < 0.99 and max(look) > 8 and min(look) < -8
    assert all({"upperarm_l", "upperarm_r", "lowerarm_l"} <= set(f) for f in frames)


def test_a_humanoid_wave_holds_the_arm_out_and_bends_the_elbow(project: Project) -> None:
    """#319: the upper arm out to the side (not straight up by the head), the forearm up, waving from the elbow."""
    text = HERO.split("animations:")[0] + "animations:\n  wave: { fps: 12, cycle: { type: wave } }\n"
    built = lint_paths(project, [write_model(project, text)]).built["thing"]
    sk = built.skeleton
    pos, _ = posed(built, [t.name for t in built.tracks].index("wave"), 0)
    p = built.painted
    bones = np.array([p.groups[g].bone for g in p.face_group])

    def centre(part: str) -> np.ndarray:
        return np.asarray(pos[bones == part].reshape(-1, 3).mean(axis=0))

    shoulder = sk.bones[sk.index("upperarm_r")].pivot
    elbow, hand = centre("lowerarm_r"), centre("hand_r")
    upper = centre("upperarm_r") - shoulder
    assert -40 < math.degrees(math.atan2(upper[1], abs(upper[0]))) < 20  # out to the side near shoulder height (raise 80), not up by the head
    assert hand[1] > elbow[1] + 0.1 and hand[1] > shoulder[1]  # forearm up
