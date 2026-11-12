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
