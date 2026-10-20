"""Rigs: bones from part ids, skin weights from the field, and animations (poses and procedural cycles).

Every part id is a bone (node) with a pivot; children follow their parents. `skin: rigid` moves each part as
one piece. `skin: soft` makes one skinned mesh whose weights come from each part's distance: a leg blended into
a body bends smoothly at the blend, because KILN knows which shape every point of the surface came from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from kiln.notation import ROOT_ID, Animation, Model, PartPose
from kiln.sdf import Array, Field, rotation_matrix

MAX_INFLUENCES = 4


@dataclass
class Bone:
    name: str
    parent: int  # index, -1 for the root
    pivot: Array  # world position of the joint at rest
    meta: dict[str, object]
    separate: bool


@dataclass
class Skeleton:
    bones: list[Bone]

    def index(self, name: str) -> int:
        return next(i for i, b in enumerate(self.bones) if b.name == name)

    def rest_translation(self, i: int) -> Array:
        b = self.bones[i]
        return b.pivot - (self.bones[b.parent].pivot if b.parent >= 0 else np.zeros(3))


def build_skeleton(model: Model, field: Field) -> Skeleton:
    """Root first, then parents before children (glTF needs no order, but previews and tests like it)."""
    ids = model.ids
    pivots: dict[str, Array] = {ROOT_ID: np.zeros(3)}
    for pid in ids[1:]:
        entry = model.rig.get(pid)
        if entry is not None and entry.pivot is not None:
            pivots[pid] = np.array(entry.pivot, float)
        else:  # default: the centre of the part's box
            boxes = [field.boxes[i] for i, p in enumerate(model.parts) if p.id == pid and p.geometry.op == "add"]
            lo = np.min([b[0] for b in boxes], axis=0)
            hi = np.max([b[1] for b in boxes], axis=0)
            pivots[pid] = (lo + hi) / 2
    parent_of: dict[str, str] = {pid: (model.rig[pid].parent or ROOT_ID) if pid in model.rig else ROOT_ID for pid in ids[1:]}
    order = [ROOT_ID]
    while len(order) < len(ids):
        for pid in ids[1:]:
            if pid not in order and parent_of[pid] in order:
                order.append(pid)
    bones = []
    for pid in order:
        entry = model.rig.get(pid)
        parent = -1 if pid == ROOT_ID else order.index(parent_of[pid])
        bones.append(Bone(pid, parent, pivots[pid], dict(entry.meta) if entry else {}, bool(entry and entry.separate)))
    return Skeleton(bones)


def soft_weights(points: Array, model: Model, field: Field, skeleton: Skeleton, step: float) -> tuple[Array, Array]:
    """(joints (V, 4) int, weights (V, 4) float) from each bone's parts' distances: softmax with a temperature
    set by the parts' blend radius, so a smooth joint bends where it blends."""
    names = [b.name for b in skeleton.bones]
    d = np.full((len(names), len(points)), np.inf)
    blend = np.full(len(names), step)
    for i, part in enumerate(model.parts):
        if part.geometry.op != "add":
            continue
        b = names.index(part.id)
        d[b] = np.minimum(d[b], field.part_distance(i, points))
        blend[b] = max(blend[b], part.geometry.blend)
    tau = np.maximum(blend / 3, 2 * step)[:, None]
    logits = -(d - d.min(axis=0)) / tau
    w = np.exp(np.maximum(logits, -50))
    order = np.argsort(-w, axis=0, kind="stable")[:MAX_INFLUENCES].T  # (V, 4)
    top = np.take_along_axis(w.T, order, axis=1)
    top[top < 0.02] = 0.0  # no faint pull from far bones (a body shouldn't twitch when an arm moves)
    top /= top.sum(axis=1, keepdims=True)
    order[top == 0] = 0  # glTF: unused influences point at joint 0
    if order.shape[1] < MAX_INFLUENCES:  # fewer bones than influences: glTF still needs VEC4
        pad = MAX_INFLUENCES - order.shape[1]
        order = np.pad(order, ((0, 0), (0, pad)))
        top = np.pad(top, ((0, 0), (0, pad)))
    return order.astype(np.int64), top


# --- animations -----------------------------------------------------------------------------------------------


def quaternion(degrees: tuple[float, float, float]) -> Array:
    """(x, y, z, w) of rotation_matrix(degrees)."""
    m = rotation_matrix(degrees)
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    out = np.array(q)
    return np.round(out / np.linalg.norm(out), 9)


def _wave(t: float) -> float:
    return math.sin(2 * math.pi * t)


def expand_cycle(anim: Animation, model: Model) -> list[dict[str, PartPose]]:
    """Procedural cycles -> poses. Each cycle has a few readable options (see the reference)."""
    c = anim.cycle or {}
    kind = c["type"]
    frames = int(c.get("frames", 8))
    out: list[dict[str, PartPose]] = []

    def opt(key: str, default: float) -> float:
        v = c.get(key, default)
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else default

    def names(key: str, default: list[str]) -> list[str]:
        v = c.get(key, default)
        return [v] if isinstance(v, str) else list(v)

    ids = set(model.ids)
    legs = [n for n in names("legs", ["leg_l", "leg_r"]) if n in ids]
    arms = [n for n in names("arms", ["arm_l", "arm_r"]) if n in ids]
    body = str(c.get("body", "root"))
    part = str(c.get("part", "root"))
    axis = {"x": 0, "y": 1, "z": 2}.get(str(c.get("axis", "y")), 1)
    for i in range(frames):
        t = i / frames
        pose: dict[str, PartPose] = {}
        if kind in ("walk", "waddle"):
            swing = opt("swing", 30.0 if kind == "walk" else 18.0)
            for k, leg in enumerate(legs):
                pose[leg] = PartPose(rotate=(swing * _wave(t + 0.5 * k), 0.0, 0.0))
            for k, arm in enumerate(arms):
                pose[arm] = PartPose(rotate=(-opt("arm_swing", 25.0) * _wave(t + 0.5 * k), 0.0, 0.0))
            bounce = opt("bounce", 0.02) * abs(math.sin(2 * math.pi * t))
            roll = opt("roll", 8.0) * _wave(t) if kind == "waddle" else 0.0
            pose[body] = PartPose(offset=(0.0, bounce, 0.0), rotate=(0.0, 0.0, roll))
        elif kind == "hop":
            height = opt("height", 0.2)
            y = height * math.sin(math.pi * t)
            squash = opt("squash", 0.1) * (1.0 if i == 0 else 0.0)
            pose[part] = PartPose(offset=(0.0, y, 0.0), scale=(1 + squash / 2, 1 - squash, 1 + squash / 2))
        elif kind == "bob":
            pose[part] = PartPose(offset=(0.0, opt("amount", 0.05) * _wave(t), 0.0))
        elif kind == "spin":
            rot = [0.0, 0.0, 0.0]
            rot[axis] = 360.0 * t * (1 if opt("direction", 1) >= 0 else -1)
            pose[part] = PartPose(rotate=(rot[0], rot[1], rot[2]))
        elif kind == "swing":
            rot = [0.0, 0.0, 0.0]
            rot[axis] = opt("angle", 20.0) * _wave(t)
            pose[part] = PartPose(rotate=(rot[0], rot[1], rot[2]))
        elif kind == "breathe":
            s = opt("amount", 0.03) * _wave(t)
            pose[part] = PartPose(scale=(1 - s / 2, 1 + s, 1 - s / 2))
        elif kind == "chain":  # a travelling wave along a chain of parts: flags, tails, tentacles, ropes
            links = names("parts", [i for i in model.ids if i != "root"])  # default: every part id in file order
            for k, link in enumerate(links):
                rot = [0.0, 0.0, 0.0]
                rot[axis] = opt("angle", 15.0) * _wave(t - opt("phase", 0.15) * k)
                pose[link] = PartPose(rotate=(rot[0], rot[1], rot[2]))
        elif kind == "wave":
            arm = arms[-1] if arms else part
            entry = model.rig.get(arm)
            side = 1.0 if entry is not None and entry.pivot is not None and entry.pivot[0] > 0 else -1.0  # +X = the model's left
            raise_deg = opt("raise", 150.0)
            pose[arm] = PartPose(rotate=(0.0, 0.0, side * (raise_deg + opt("angle", 20.0) * _wave(t))))
        out.append(pose)
    return out


@dataclass
class Track:
    """Per-bone keyframes of one animation (frames at i / fps)."""

    name: str
    fps: float
    loop: bool
    interpolation: str
    translation: Array  # (frames, bones, 3)
    rotation: Array  # (frames, bones, 4) xyzw
    scale: Array  # (frames, bones, 3)

    @property
    def frames(self) -> int:
        return int(self.translation.shape[0])


def tracks(model: Model, skeleton: Skeleton) -> list[Track]:
    out = []
    n = len(skeleton.bones)
    rest = np.array([skeleton.rest_translation(i) for i in range(n)])
    for anim in model.animations.values():
        poses = anim.poses if anim.cycle is None else expand_cycle(anim, model)
        tr = np.repeat(rest[None], len(poses), axis=0)
        rot = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (len(poses), n, 1))
        sc = np.ones((len(poses), n, 3))
        for f, pose in enumerate(poses):
            for name, pp in pose.items():
                b = skeleton.index(name)
                tr[f, b] = rest[b] + np.array(pp.offset)
                rot[f, b] = quaternion(pp.rotate)
                sc[f, b] = np.array(pp.scale)
        out.append(Track(anim.name, anim.fps, anim.loop, anim.interpolation, tr, rot, sc))
    return out


def _quat_matrix(q: Array) -> Array:
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])  # fmt: skip


def world_matrices(skeleton: Skeleton, translation: Array, rotation: Array, scale: Array) -> Array:
    """(bones, 4, 4) world transforms for one frame of local TRS."""
    n = len(skeleton.bones)
    out = np.zeros((n, 4, 4))
    for i, bone in enumerate(skeleton.bones):
        local = np.eye(4)
        local[:3, :3] = _quat_matrix(rotation[i]) * scale[i][None, :]
        local[:3, 3] = translation[i]
        out[i] = local if bone.parent < 0 else out[bone.parent] @ local
    return out


def skin_matrices(skeleton: Skeleton, translation: Array, rotation: Array, scale: Array) -> Array:
    """World transform x inverse bind (rest pivot) per bone: what moves a rest-pose vertex."""
    world = world_matrices(skeleton, translation, rotation, scale)
    for i, bone in enumerate(skeleton.bones):
        inv_bind = np.eye(4)
        inv_bind[:3, 3] = -bone.pivot
        world[i] = world[i] @ inv_bind
    return world


__all__ = ["Bone", "Skeleton", "Track", "build_skeleton", "expand_cycle", "quaternion", "skin_matrices", "soft_weights", "tracks"]
