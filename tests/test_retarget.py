"""Standard humanoid skeleton and clip retargeting (CC0 parity M5), against KayKit's CC0 Rig_Medium clips."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from conftest import built_of, errors_of, ok_model, write_model
from kiln.build import build
from kiln.project import Project
from kiln.retarget import JOINTS, load_clip, q_rotate
from kiln.rig import world_matrices

KAYKIT = Path(__file__).resolve().parent / "fixtures" / "kaykit"

HERO = """name: thing
class: character
skeleton: humanoid
parts:
  - ellipsoid: { at: [0, 0.62, 0], radii: [0.17, 0.12, 0.12] }
    id: hips
    color: blue
  - capsule: { from: [0, 0.7, 0], to: [0, 0.85, 0], radius: 0.15 }
    id: spine
    color: red
    blend: 0.03
  - capsule: { from: [0, 0.88, 0], to: [0, 1.05, 0], radius: 0.17 }
    id: chest
    color: red
    blend: 0.03
  - sphere: { at: [0, 1.3, 0], radius: 0.17 }
    id: head
    color: white
    blend: 0.03
  - sphere: { at: [0.06, 1.33, 0.15], radius: 0.025 }
    id: head
    mirror: x
    color: grey
  - capsule: { from: [0.2, 1.02, 0], to: [0.24, 0.8, 0], radius: 0.055 }
    id: upperarm_l
    mirror: x
    mirror_id: upperarm_r
    color: red
    blend: 0.02
  - capsule: { from: [0.24, 0.8, 0], to: [0.26, 0.6, 0], radius: 0.048 }
    id: lowerarm_l
    mirror: x
    mirror_id: lowerarm_r
    color: white
    blend: 0.02
  - sphere: { at: [0.265, 0.55, 0], radius: 0.05 }
    id: hand_l
    mirror: x
    mirror_id: hand_r
    color: white
    blend: 0.02
  - capsule: { from: [0.09, 0.58, 0], to: [0.09, 0.33, 0], radius: 0.07 }
    id: upperleg_l
    mirror: x
    mirror_id: upperleg_r
    color: blue
    blend: 0.02
  - capsule: { from: [0.09, 0.33, 0], to: [0.09, 0.1, 0], radius: 0.06 }
    id: lowerleg_l
    mirror: x
    mirror_id: lowerleg_r
    color: blue
    blend: 0.02
  - box: { at: [0.09, 0.04, 0.04], size: [0.11, 0.08, 0.2], round: 0.03 }
    id: foot_l
    mirror: x
    mirror_id: foot_r
    color: grey
    blend: 0.02
rig:
  upperarm_l: { pivot: [0.2, 1.02, 0] }
  lowerarm_l: { pivot: [0.24, 0.8, 0] }
  hand_l: { pivot: [0.26, 0.6, 0] }
  upperleg_l: { pivot: [0.09, 0.58, 0] }
  lowerleg_l: { pivot: [0.09, 0.33, 0] }
  foot_l: { pivot: [0.09, 0.1, 0] }
animations:
  walk: { import: imports/Rig_Medium_MovementBasic.glb, clip: Walking_A }
  idle: { import: imports/Rig_Medium_General.glb, clip: Idle_A }
  death: { import: imports/Rig_Medium_General.glb, clip: Death_A, loop: false }
"""


@pytest.fixture
def clips(project: Project) -> Project:
    for name in ("Rig_Medium_General.glb", "Rig_Medium_MovementBasic.glb"):
        shutil.copy(KAYKIT / name, project.root / "imports" / name)
    return project


def test_humanoid_plays_kaykit_clips_with_bones_where_the_clip_puts_them(clips: Project) -> None:
    built = built_of(clips, HERO)
    sk = built.skeleton
    names = [b.name for b in sk.bones]
    assert {t.name for t in built.tracks} == {"walk", "idle", "death"}
    for anim, file, clip_name in (("walk", "Rig_Medium_MovementBasic.glb", "Walking_A"), ("death", "Rig_Medium_General.glb", "Death_A")):
        t = next(t for t in built.tracks if t.name == anim)
        clip = load_clip(KAYKIT / file, clip_name)
        worst = 0.0
        for f in range(0, t.frames, 4):
            world = world_matrices(sk, t.translation[f], t.rotation[f], t.scale[f])
            wp, _ = clip.world(*clip.local(min(f / t.fps, clip.duration)))
            for bone, child in (("upperarm_l", "lowerarm_l"), ("lowerarm_r", "hand_r"), ("upperleg_l", "lowerleg_l"), ("lowerleg_r", "foot_r"),
                                ("spine", "chest")):
                b, c = names.index(bone), names.index(child)
                mine = world[c][:3, 3] - world[b][:3, 3]
                theirs = wp[clip.index(JOINTS[child][2])] - wp[clip.index(JOINTS[bone][2])]
                cos = float(mine @ theirs / np.linalg.norm(mine) / np.linalg.norm(theirs))
                worst = max(worst, float(np.degrees(np.arccos(min(1.0, cos)))))
        assert worst < 3.0, (anim, worst)  # every limb points where the clip's does
        # bones keep their length (no broken limbs): only the hips move
        moved = np.abs(t.translation - t.translation[0][None]).max(axis=(0, 2))
        assert set(np.flatnonzero(moved > 1e-9)) <= {names.index("hips")}
    death = next(t for t in built.tracks if t.name == "death")
    assert not death.loop and death.translation[-1, names.index("hips"), 1] < death.translation[0, names.index("hips"), 1] - 0.2  # falls


def test_humanoid_defaults_and_manifest(clips: Project) -> None:
    write_model(clips, HERO)
    build(clips)
    manifest = json.loads((clips.output_dir / "manifest.json").read_text())
    entry = manifest["models"]["thing"]
    assert entry["skin"] == "soft"
    assert entry["humanoid"]["upperarm_l"] == {"kaykit": "upperarm.l", "mixamo": "mixamorig:LeftArm", "godot": "LeftUpperArm"}
    assert entry["animations"]["walk"]["clip"] == {"file": "Rig_Medium_MovementBasic.glb", "clip": "Walking_A"}
    assert entry["parts"]["lowerarm_l"]["parent"] == "upperarm_l"  # parents come from the standard hierarchy


def test_humanoid_errors(clips: Project) -> None:
    no_legs = HERO.split("  - capsule: { from: [0.09, 0.58, 0]")[0] + "rig: {}\n"
    assert any("upperleg_l" in f.message for f in errors_of(clips, no_legs))
    wrong_clip = HERO.replace("clip: Walking_A", "clip: Moonwalk")
    assert any("no clip 'Moonwalk'" in f.message and "Walking_A" in f.message for f in errors_of(clips, wrong_clip))
    not_humanoid = HERO.replace("skeleton: humanoid\n", "")
    assert any("skeleton: humanoid" in f.message for f in errors_of(clips, not_humanoid))
    missing = HERO.replace("imports/Rig_Medium_General.glb, clip: Idle_A", "imports/nope.glb, clip: Idle_A")
    assert any("not found" in f.message for f in errors_of(clips, missing))


def test_q_rotate() -> None:
    q = np.array([0.0, 0.0, np.sin(np.pi / 4), np.cos(np.pi / 4)])  # 90 degrees about z
    assert np.allclose(q_rotate(q, np.array([1.0, 0.0, 0.0])), [0.0, 1.0, 0.0])
