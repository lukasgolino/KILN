"""#64: imported clips on non-humanoid skeletons through a joint map (`skeleton: { map, root_motion }`), against a
small synthetic quadruped clip file (other joint names, IK/pole bones) written here."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from conftest import built_of, errors_of, ok_model, run_json, write_model
from kiln.export import Built
from kiln.project import Project
from kiln.retarget import load_clip, q_mul, q_rotate
from kiln.rig import world_matrices
from kiln.vendor.gltf import Document

# name, parent, rest translation (local): a horse-ish armature along +Z, IK and pole bones beside the joints
JOINTS: list[tuple[str, int, tuple[float, float, float]]] = [
    ("Armature", -1, (0.0, 0.0, 0.0)),
    ("Torso", 0, (0.0, 1.0, 0.0)),
    ("Torso2", 1, (0.0, 0.0, 0.0)),
    ("Neck1", 2, (0.0, 0.1, 0.5)),
    ("Head", 3, (0.0, 0.4, 0.2)),
    ("FrontUpperLeg.L", 2, (0.2, -0.1, 0.4)),
    ("FrontLowerLeg.L", 5, (0.0, -0.4, 0.0)),
    ("Tail1", 2, (0.0, 0.1, -0.5)),
    ("IK_Foot.L", 0, (0.2, 0.0, 0.4)),
    ("Pole.L", 0, (0.2, 0.4, 0.8)),
]
TURNS = {"Neck1": ((1.0, 0.0, 0.0), -30.0), "FrontUpperLeg.L": ((1.0, 0.0, 0.0), 45.0), "Tail1": ((0.0, 1.0, 0.0), 40.0),
         "IK_Foot.L": ((0.0, 0.0, 1.0), 90.0), "Pole.L": ((0.0, 1.0, 0.0), 120.0)}  # fmt: skip


def axis_angle(axis: tuple[float, float, float], degrees: float) -> np.ndarray:
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    h = math.radians(degrees) / 2
    return np.array([*(a * math.sin(h)), math.cos(h)])


def quadruped_glb(ik: bool = True) -> bytes:
    """One clip, Walk (1 s): the torso walks 1 m forward, the neck dips, the leg swings, the tail wags; the IK and pole
    bones (when `ik`) jump about, as they do in real libraries."""
    doc = Document("test")
    for i, (name, _, at) in enumerate(JOINTS):
        node: dict[str, Any] = {"name": name, "translation": list(at)}
        kids = [k for k, row in enumerate(JOINTS) if row[1] == i]
        if kids:
            node["children"] = kids
        doc.add("nodes", node)
    doc.add("scenes", {"nodes": [0]})
    doc.json["scene"] = 0
    times = doc.accessor(np.array([0.0, 1.0], np.float32), bounds=True)
    samplers: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []

    def key(node: int, path: str, values: np.ndarray) -> None:
        samplers.append({"input": times, "output": doc.accessor(values.astype(np.float32)), "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": node, "path": path}})

    names = [row[0] for row in JOINTS]
    key(names.index("Torso"), "translation", np.array([[0.0, 1.0, 0.0], [0.0, 1.0, 1.0]]))
    for name, (axis, degrees) in TURNS.items():
        if ik or name in ("Neck1", "FrontUpperLeg.L", "Tail1"):
            key(names.index(name), "rotation", np.array([[0.0, 0.0, 0.0, 1.0], axis_angle(axis, degrees)]))
    if ik:
        key(names.index("IK_Foot.L"), "translation", np.array([[0.2, 0.0, 0.4], [3.0, 2.0, 1.0]]))
    doc.add("animations", {"name": "Walk", "samplers": samplers, "channels": channels})
    return doc.glb()


HORSE = """name: thing
class: creature
skin: rigid
parts:
  - box: { at: [0, 0.5, 0], size: [0.3, 0.2, 0.6] }
    id: body
    color: wood
  - box: { at: [0, 0.64, 0], size: [0.2, 0.04, 0.2] }
    id: saddle
    color: red
  - capsule: { from: [0, 0.55, 0.3], to: [0, 0.75, 0.4], radius: 0.05 }
    id: neck
    color: wood
  - sphere: { at: [0, 0.8, 0.45], radius: 0.08 }
    id: head
    color: wood
  - capsule: { from: [0.1, 0.45, 0.25], to: [0.12, 0.25, 0.28], radius: 0.03 }
    id: leg_l
    color: wood
  - capsule: { from: [0.12, 0.25, 0.28], to: [0.12, 0.05, 0.28], radius: 0.025 }
    id: shin_l
    color: wood
  - capsule: { from: [0, 0.55, -0.3], to: [0, 0.45, -0.45], radius: 0.02 }
    id: tail
    color: black
rig:
  body: { pivot: [0, 0.5, 0] }
  saddle: { pivot: [0, 0.62, 0], parent: body }
  neck: { pivot: [0, 0.55, 0.3], parent: body }
  head: { pivot: [0, 0.75, 0.4], parent: neck }
  leg_l: { pivot: [0.1, 0.45, 0.25], parent: body }
  shin_l: { pivot: [0.12, 0.25, 0.28], parent: leg_l }
  tail: { pivot: [0, 0.55, -0.3], parent: body }
skeleton:
  map:
    body: Torso2
    neck: { joint: Neck1, child: head }
    head: Head
    leg_l: { joint: FrontUpperLeg.L, child: shin_l }
    shin_l: FrontLowerLeg.L
    tail: Tail1
  root_motion: Torso
animations:
  walk: { import: imports/quadruped.glb, clip: Walk }
"""


@pytest.fixture
def clips(project: Project) -> Project:
    (project.root / "imports" / "quadruped.glb").write_bytes(quadruped_glb())
    (project.root / "imports" / "quadruped_no_ik.glb").write_bytes(quadruped_glb(ik=False))
    return project


def walk(built: Built) -> Any:
    return next(t for t in built.tracks if t.name == "walk")


def test_mapped_bones_turn_as_the_clip_turns_them(clips: Project) -> None:
    built = built_of(clips, HORSE)
    sk = built.skeleton
    names = [b.name for b in sk.bones]
    t = walk(built)
    clip = load_clip(clips.root / "imports" / "quadruped.glb", "Walk")
    assert t.frames == 31
    for f in range(t.frames):
        world = world_matrices(sk, t.translation[f], t.rotation[f], t.scale[f])
        wp, _ = clip.world(*clip.local(f / t.fps))
        # aimed bones point where the clip's do (the KILN leg is built slanted, the clip's straight down)
        for bone, child, joint, child_joint in (("neck", "head", "Neck1", "Head"), ("leg_l", "shin_l", "FrontUpperLeg.L", "FrontLowerLeg.L")):
            mine = world[names.index(child)][:3, 3] - world[names.index(bone)][:3, 3]
            theirs = wp[clip.index(child_joint)] - wp[clip.index(joint)]
            cos = float(mine @ theirs / np.linalg.norm(mine) / np.linalg.norm(theirs))
            assert np.degrees(np.arccos(min(1.0, cos))) < 0.5, (f, bone)
        # a mapped bone without a child turns by the clip's world-space turn (the tail wags 40 degrees about y)
        turned = world[names.index("tail")][:3, :3] @ np.array([0.0, 0.0, -1.0])
        expected = q_rotate(axis_angle((0.0, 1.0, 0.0), 40.0 * f / 30), np.array([0.0, 0.0, -1.0]))
        assert np.allclose(turned, expected, atol=1e-6), f
        # an unmapped bone follows its parent: the saddle turns and moves with the body
        assert np.allclose(world[names.index("saddle")][:3, :3], world[names.index("body")][:3, :3], atol=1e-9)
        assert np.allclose(t.translation[f, names.index("saddle")], t.translation[0, names.index("saddle")])
    # the leg swung 45 degrees forward/back by the end: its far end moved off the rest direction
    first = world_matrices(sk, t.translation[0], t.rotation[0], t.scale[0])
    last = world_matrices(sk, t.translation[-1], t.rotation[-1], t.scale[-1])
    leg, shin = names.index("leg_l"), names.index("shin_l")
    d0 = first[shin][:3, 3] - first[leg][:3, 3]
    d1 = last[shin][:3, 3] - last[leg][:3, 3]
    assert np.degrees(np.arccos(d0 @ d1 / np.linalg.norm(d0) / np.linalg.norm(d1))) == pytest.approx(45, abs=0.5)


def test_root_motion_scales_by_height_and_defaults_to_none(clips: Project) -> None:
    built = built_of(clips, HORSE)
    names = [b.name for b in built.skeleton.bones]
    t = walk(built)
    body = names.index("body")
    # Torso walks 1 m at 1 m height; the KILN body's pivot is 0.5 m up: 0.5 m
    assert t.translation[-1, body] - t.translation[0, body] == pytest.approx([0.0, 0.0, 0.5], abs=1e-6)
    assert t.translation[15, body, 2] - t.translation[0, body, 2] == pytest.approx(0.25, abs=1e-6)
    others = [i for i in range(len(names)) if i != body]
    assert np.allclose(t.translation[:, others], t.translation[0:1, others])  # only the body moves; bones keep their length
    still = walk(built_of(clips, HORSE.replace("  root_motion: Torso\n", "")))
    assert np.allclose(still.translation, still.translation[0:1])  # no root_motion: rotations only
    assert np.allclose(still.rotation, t.rotation)
    mapped = walk(built_of(clips, HORSE.replace("body: Torso2", "body: Torso")))  # the joint mapped itself: the same
    assert np.allclose(mapped.translation, t.translation) and np.allclose(mapped.rotation, t.rotation)


def test_ik_and_pole_bones_are_ignored(clips: Project) -> None:
    with_ik = walk(built_of(clips, HORSE))
    without = walk(built_of(clips, HORSE.replace("imports/quadruped.glb", "imports/quadruped_no_ik.glb")))
    assert np.array_equal(with_ik.rotation, without.rotation) and np.array_equal(with_ik.translation, without.translation)


def test_keep_and_offset_on_mapped_bones(clips: Project) -> None:
    plain = walk(built_of(clips, HORSE))
    held = built_of(clips, HORSE.replace("clip: Walk }", "clip: Walk, retarget: { keep: { tail: 0 }, offset: { neck: [0, 0, 10] } } }"))
    names = [b.name for b in held.skeleton.bones]
    h = walk(held)
    tail, neck = names.index("tail"), names.index("neck")
    assert all(abs(abs(float(h.rotation[f, tail] @ h.rotation[0, tail])) - 1) < 1e-9 for f in range(h.frames))
    angle = np.degrees(2 * np.arccos(min(1.0, abs(float(h.rotation[0, neck] @ plain.rotation[0, neck])))))
    assert angle == pytest.approx(10, abs=0.5)
    assert np.allclose(h.rotation[:, names.index("leg_l")], plain.rotation[:, names.index("leg_l")])
    bad = HORSE.replace("clip: Walk }", "clip: Walk, retarget: { keep: { upperarm: 0.5 } } }")
    assert any("retarget is" in f.message and "mapped bone" in f.message for f in errors_of(clips, bad))


@pytest.mark.parametrize(("change", "message", "where"), [
    (("body: Torso2", "bodyy: Torso2"), "unknown bone 'bodyy'", "skeleton.map.bodyy"),
    (("body: Torso2", "root: Torso2"), "unknown bone 'root'", "skeleton.map.root"),
    (("head: Head", "head: Heda"), "'Heda', which imports/quadruped.glb doesn't have (did you mean Head", "animations.walk"),
    (("root_motion: Torso", "root_motion: Torsoo"), "skeleton.root_motion names joint 'Torsoo'", "animations.walk"),
    (("child: head }", "child: tail }"), "child 'tail' isn't below 'neck'", "skeleton.map.neck.child"),
    (("child: head }", "child: nose }"), "child 'nose' isn't a bone", "skeleton.map.neck.child"),
    (("    head: Head\n", ""), "child 'head' isn't mapped", "skeleton.map.neck.child"),
    (("neck: { joint: Neck1, child: head }", "neck: { joint: Neck1, aim: head }"), "a mapped bone is", "skeleton.map.neck"),
    (("  root_motion: Torso\n", "  root_motion: Torso\n  humanoid: true\n"), "it takes no map", "skeleton"),
    (("  root_motion: Torso\n", "  root_motion: [Torso]\n"), "root_motion names the clip joint", "skeleton.root_motion"),
])  # fmt: skip
def test_map_findings(clips: Project, change: tuple[str, str], message: str, where: str) -> None:
    assert change[0] in HORSE
    found = errors_of(clips, HORSE.replace(*change))
    assert any(message in f.message and f.where == where for f in found), [f.format() for f in found]


def test_imported_clips_still_need_a_humanoid_or_a_map(clips: Project) -> None:
    text = HORSE[: HORSE.index("skeleton:\n")] + HORSE[HORSE.index("animations:\n") :]
    assert any(f.rule == "E008" and "skeleton: humanoid" in f.message and "map" in f.message for f in errors_of(clips, text))


def test_a_map_alone_changes_nothing_else(clips: Project) -> None:
    """The map only drives imported clips: same skeleton, skin and posed clips as without it."""
    posed = HORSE.replace("  walk: { import: imports/quadruped.glb, clip: Walk }\n", "  nod: { poses: [{ neck: { rotate: [20, 0, 0] } }] }\n")
    with_map = built_of(clips, posed)
    plain = built_of(clips, posed[: posed.index("skeleton:\n")] + posed[posed.index("animations:\n") :])
    assert [(b.name, b.parent, tuple(b.pivot)) for b in with_map.skeleton.bones] == [(b.name, b.parent, tuple(b.pivot)) for b in plain.skeleton.bones]
    assert with_map.skin == plain.skin == "rigid"
    assert np.array_equal(with_map.tracks[0].rotation, plain.tracks[0].rotation)
    model, _ = ok_model(clips, HORSE)
    assert model.joint_map is not None and model.joint_map.root_motion == "Torso" and model.joint_map.child == {"neck": "head", "leg_l": "shin_l"}


def test_lint_and_pose_preview_on_a_quadruped(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    (in_project.root / "imports" / "quadruped.glb").write_bytes(quadruped_glb())
    write_model(in_project, HORSE)
    code, result = run_json(["lint", "thing"], capsys)
    assert code == 0 and result["errors"] == 0, result["findings"]
    code, result = run_json(["preview", "thing", "--pose", "walk"], capsys)
    assert code == 0, result
    assert (in_project.root / result["outputs"]["pose"]["walk"]).is_file()


def test_q_mul_identity_is_exact() -> None:
    """Humanoid root motion skips the parent's axes when they're unturned: identity products are exact anyway."""
    q = axis_angle((0.3, 0.5, 0.1), 33.0)
    assert np.array_equal(q_mul(np.array([0.0, 0.0, 0.0, 1.0]), q), q)
