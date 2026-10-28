"""Standard humanoid skeleton and animation retargeting: play CC0 clip libraries (KayKit Character Animations,
Rig_Medium; anything with the same joint names) on KILN characters, and any other skeleton through a joint map
(`skeleton: { map: ... }`: quadrupeds, birds).

A humanoid model names its parts after the standard joints (`hips`, `upperarm_l`, ...). An imported clip is
sampled frame by frame; every joint's change from the clip's own rest pose (in world space) is applied to the KILN
bone after turning the bone onto the clip's rest direction, so each bone points where the clip's bone points: KILN
characters built in an A-pose play T-pose clips correctly. The hips also move, scaled by the ratio of hip heights.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from kiln.sdf import Array
from kiln.vendor.gltf import read_glb

# kiln id, parent kiln id, KayKit Rig_Medium joint, Mixamo bone, Godot SkeletonProfileHumanoid bone
HUMANOID: tuple[tuple[str, str, str, str, str], ...] = (
    ("hips", "root", "hips", "mixamorig:Hips", "Hips"),
    ("spine", "hips", "spine", "mixamorig:Spine", "Spine"),
    ("chest", "spine", "chest", "mixamorig:Spine2", "Chest"),
    ("head", "chest", "head", "mixamorig:Head", "Head"),
    ("upperarm_l", "chest", "upperarm.l", "mixamorig:LeftArm", "LeftUpperArm"),
    ("lowerarm_l", "upperarm_l", "lowerarm.l", "mixamorig:LeftForeArm", "LeftLowerArm"),
    ("hand_l", "lowerarm_l", "hand.l", "mixamorig:LeftHand", "LeftHand"),
    ("upperarm_r", "chest", "upperarm.r", "mixamorig:RightArm", "RightUpperArm"),
    ("lowerarm_r", "upperarm_r", "lowerarm.r", "mixamorig:RightForeArm", "RightLowerArm"),
    ("hand_r", "lowerarm_r", "hand.r", "mixamorig:RightHand", "RightHand"),
    ("upperleg_l", "hips", "upperleg.l", "mixamorig:LeftUpLeg", "LeftUpperLeg"),
    ("lowerleg_l", "upperleg_l", "lowerleg.l", "mixamorig:LeftLeg", "LeftLowerLeg"),
    ("foot_l", "lowerleg_l", "foot.l", "mixamorig:LeftFoot", "LeftFoot"),
    ("upperleg_r", "hips", "upperleg.r", "mixamorig:RightUpLeg", "RightUpperLeg"),
    ("lowerleg_r", "upperleg_r", "lowerleg.r", "mixamorig:RightLeg", "RightLowerLeg"),
    ("foot_r", "lowerleg_r", "foot.r", "mixamorig:RightFoot", "RightFoot"),
)
OPTIONAL: tuple[tuple[str, str, str, str, str], ...] = (
    ("toes_l", "foot_l", "toes.l", "mixamorig:LeftToeBase", "LeftToes"),
    ("toes_r", "foot_r", "toes.r", "mixamorig:RightToeBase", "RightToes"),
)
JOINTS = {row[0]: row for row in HUMANOID + OPTIONAL}
REQUIRED = tuple(row[0] for row in HUMANOID)
CHILD = {"hips": "spine", "spine": "chest", "chest": "head", "upperarm_l": "lowerarm_l", "lowerarm_l": "hand_l",
         "upperarm_r": "lowerarm_r", "lowerarm_r": "hand_r", "upperleg_l": "lowerleg_l", "lowerleg_l": "foot_l",
         "upperleg_r": "lowerleg_r", "lowerleg_r": "foot_r", "foot_l": "toes_l", "foot_r": "toes_r"}  # fmt: skip


@dataclass(frozen=True)
class JointMap:
    """Which clip joint drives which KILN bone. `joints`: KILN bone -> clip joint; `child`: KILN bone -> the KILN bone
    whose direction aims it (onto the clip's direction between the two joints); `root_motion`: the clip joint whose
    movement moves the model (None: rotations only)."""

    joints: dict[str, str]
    child: dict[str, str]
    root_motion: str | None = None


HUMANOID_MAP = JointMap({kid: row[2] for kid, row in JOINTS.items()}, CHILD, "hips")


# --- quaternions (x, y, z, w) -------------------------------------------------------------------------------


def q_mul(a: Array, b: Array) -> Array:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])  # fmt: skip


def q_inv(q: Array) -> Array:
    return np.array([-q[0], -q[1], -q[2], q[3]])


def q_rotate(q: Array, v: Array) -> Array:
    return np.asarray(q_mul(q_mul(q, np.array([v[0], v[1], v[2], 0.0])), q_inv(q))[:3])


def q_between(a: Array, b: Array) -> Array:
    """The shortest rotation turning direction a onto direction b."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    d = float(a @ b)
    if d < -0.999999:
        axis = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0.0, 1.0, 0.0])
        axis /= np.linalg.norm(axis)
        return np.array([axis[0], axis[1], axis[2], 0.0])
    c = np.cross(a, b)
    q = np.array([c[0], c[1], c[2], 1.0 + d])
    return np.asarray(q / np.linalg.norm(q))


def q_slerp(a: Array, b: Array, t: float) -> Array:
    d = float(a @ b)
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        q = a + (b - a) * t
    else:
        th = math.acos(d)
        q = (math.sin((1 - t) * th) * a + math.sin(t * th) * b) / math.sin(th)
    return np.asarray(q / np.linalg.norm(q))


# --- reading a clip ---------------------------------------------------------------------------------------------


@dataclass
class Clip:
    name: str
    duration: float
    names: list[str]  # every node
    parent: list[int]  # -1 = scene root
    rest_t: Array  # (N, 3)
    rest_r: Array  # (N, 4)
    channels: dict[tuple[int, str], tuple[Array, Array, str]]  # (node, path) -> (times, values, interpolation)

    def local(self, t: float) -> tuple[Array, Array]:
        """Every node's local translation and rotation at time t (seconds)."""
        tr, rot = self.rest_t.copy(), self.rest_r.copy()
        for (node, path), (times, values, interp) in self.channels.items():
            if path not in ("translation", "rotation"):
                continue
            k = int(np.searchsorted(times, t, side="right")) - 1
            if k < 0:
                v = values[0]
            elif k >= len(times) - 1:
                v = values[-1]
            elif interp == "STEP":
                v = values[k]
            else:
                f = (t - times[k]) / max(times[k + 1] - times[k], 1e-9)
                v = q_slerp(values[k], values[k + 1], f) if path == "rotation" else values[k] + (values[k + 1] - values[k]) * f
            (rot if path == "rotation" else tr)[node] = v
        return tr, rot

    def world(self, tr: Array, rot: Array) -> tuple[Array, Array]:
        """World positions and rotations (scale ignored: rigs are unscaled)."""
        n = len(self.names)
        wp, wr = np.zeros((n, 3)), np.zeros((n, 4))
        done = np.zeros(n, dtype=bool)
        for i in range(n):
            chain = []
            j = i
            while j >= 0 and not done[j]:
                chain.append(j)
                j = self.parent[j]
            for k in reversed(chain):
                p = self.parent[k]
                if p < 0:
                    wp[k], wr[k] = tr[k], rot[k]
                else:
                    wp[k] = wp[p] + q_rotate(wr[p], tr[k])
                    wr[k] = q_mul(wr[p], rot[k])
                done[k] = True
        return wp, wr

    def index(self, name: str) -> int:
        return self.names.index(name)


def _accessor(doc: dict[str, Any], binary: bytes, index: int) -> Array:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    count = acc["count"]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if acc["componentType"] != 5126:
        raise ValueError("animation data must be float")
    stride = view.get("byteStride", 4 * width)
    raw = np.frombuffer(binary, dtype=np.float32, count=(count - 1) * stride // 4 + width, offset=start)
    return np.asarray(np.lib.stride_tricks.as_strided(raw, (count, width), (stride, 4)), dtype=float).copy()


@lru_cache(maxsize=16)
def _document(path: Path, mtime: float) -> tuple[dict[str, Any], bytes]:
    return read_glb(path.read_bytes())


def clip_names(path: Path) -> list[str]:
    doc, _ = _document(path, path.stat().st_mtime)
    return [str(a.get("name", f"animation{i}")) for i, a in enumerate(doc.get("animations", []))]


def joint_names(path: Path) -> list[str]:
    """Every node's name in a clip file (its joints, and whatever else it holds)."""
    doc, _ = _document(path, path.stat().st_mtime)
    return [str(n.get("name", "")) for n in doc.get("nodes", [])]


def load_clip(path: Path, name: str) -> Clip:
    doc, binary = _document(path, path.stat().st_mtime)
    nodes = doc["nodes"]
    parent = [-1] * len(nodes)
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    rest_t = np.array([n.get("translation", [0.0, 0.0, 0.0]) for n in nodes], float)
    rest_r = np.array([n.get("rotation", [0.0, 0.0, 0.0, 1.0]) for n in nodes], float)
    anims = {str(a.get("name", f"animation{i}")): a for i, a in enumerate(doc.get("animations", []))}
    if name not in anims:
        raise KeyError(name)
    a = anims[name]
    channels: dict[tuple[int, str], tuple[Array, Array, str]] = {}
    duration = 0.0
    for ch in a["channels"]:
        target = ch["target"]
        if "node" not in target:
            continue
        s = a["samplers"][ch["sampler"]]
        times = _accessor(doc, binary, s["input"])[:, 0]
        values = _accessor(doc, binary, s["output"])
        channels[(int(target["node"]), str(target["path"]))] = (times, values, str(s.get("interpolation", "LINEAR")))
        duration = max(duration, float(times[-1]))
    return Clip(name, duration, [str(n.get("name", "")) for n in nodes], parent, rest_t, rest_r, channels)


# --- retargeting ------------------------------------------------------------------------------------------------


def _per_bone(values: dict[str, Any], name: str) -> Any:
    """A joint's own entry, else its side-less base name's (upperarm for upperarm_l and upperarm_r)."""
    if name in values:
        return values[name]
    return values.get(name[:-2]) if name.endswith(("_l", "_r")) else None


def mover(joints: JointMap, clip: Clip) -> tuple[str, int] | None:
    """The KILN bone the root motion moves (and the clip joint mapped to it): the bone mapped to the `root_motion`
    joint, else the one mapped to its nearest mapped descendant in the clip (breadth first); None without one."""
    if joints.root_motion is None or joints.root_motion not in clip.names:
        return None
    by_joint: dict[str, str] = {}
    for kid, name in joints.joints.items():
        by_joint.setdefault(name, kid)
    queue = [clip.index(joints.root_motion)]
    while queue:
        node = queue.pop(0)
        if clip.names[node] in by_joint:
            return by_joint[clip.names[node]], node
        queue.extend(i for i, p in enumerate(clip.parent) if p == node)
    return None


def retarget(clip: Clip, bones: list[tuple[str, int, Array]], fps: float, speed: float = 1.0,
             keep: dict[str, float] | None = None, offset: dict[str, Array] | None = None,
             joints: JointMap = HUMANOID_MAP) -> tuple[Array, Array]:  # fmt: skip
    """(translation, rotation) per frame and bone for KILN bones (name, parent index, rest pivot), root first,
    parents before children. Bones that aren't in the joint map (humanoid joints by default; or have no joint in the
    clip) follow their parent. `keep` scales a joint's turn away from its rest (by joint or base name; children
    follow), `offset` adds a fixed turn (a quaternion, model axes) to it: clips made for another body type. The bone
    `mover` finds moves by the `root_motion` joint's movement, scaled by the ratio of its rest height to the joint's
    (for humanoids: the hips)."""
    frames = max(1, int(round(clip.duration / speed * fps)) + 1)
    n = len(bones)
    rest_local = np.array([pivot - (bones[p][2] if p >= 0 else np.zeros(3)) for _, p, pivot in bones])
    joint = {}
    for b, (name, _, _) in enumerate(bones):
        mapped = joints.joints.get(name)
        if mapped is not None and mapped in clip.names:
            joint[b] = clip.index(mapped)
    rest_wp, rest_wr = clip.world(clip.rest_t, clip.rest_r)
    # the turn putting each KILN bone onto the clip's rest direction (bones with no child: their parent's turn)
    by_name = {name: b for b, (name, _, _) in enumerate(bones)}
    align = [np.array([0.0, 0.0, 0.0, 1.0]) for _ in range(n)]
    for b, (name, parent, pivot) in enumerate(bones):
        child = joints.child.get(name)
        if b in joint and child in by_name and by_name[child] in joint:
            mine = bones[by_name[child]][2] - pivot
            theirs = rest_wp[joint[by_name[child]]] - rest_wp[joint[b]]
            if np.linalg.norm(mine) > 1e-9 and np.linalg.norm(theirs) > 1e-9:
                align[b] = q_between(mine, theirs)
                continue
        if parent >= 0:
            align[b] = align[parent]
    moving = mover(joints, clip)
    hips = by_name.get(moving[0]) if moving is not None else None  # the bone that moves (humanoids: the hips)
    source = clip.index(joints.root_motion) if moving is not None and joints.root_motion is not None else -1  # moves it
    scale = 1.0
    if hips is not None and hips in joint and rest_wp[source][1] > 1e-6:
        scale = float(bones[hips][2][1] / rest_wp[source][1])
    out_t = np.repeat(rest_local[None], frames, axis=0)
    out_r = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (frames, n, 1))
    ident = np.array([0.0, 0.0, 0.0, 1.0])
    keeps = [_per_bone(keep or {}, name) for name, _, _ in bones]
    offsets = [_per_bone(offset or {}, name) for name, _, _ in bones]
    rest_local_r = [q_mul(q_inv(align[p]) if p >= 0 else ident, align[b]) for b, (_, p, _) in enumerate(bones)]
    for f in range(frames):
        wp, wr = clip.world(*clip.local(min(f / fps * speed, clip.duration)))
        world = [ident.copy() for _ in range(n)]  # as the clip turns it
        placed = [ident.copy() for _ in range(n)]  # after keep/offset (children follow their adjusted parents)
        for b, (name, parent, _) in enumerate(bones):
            parent_world = world[parent] if parent >= 0 else ident
            parent_placed = placed[parent] if parent >= 0 else ident
            if b in joint:
                delta = q_mul(wr[joint[b]], q_inv(rest_wr[joint[b]]))
                world[b] = q_mul(delta, align[b])
                local = q_mul(q_inv(parent_world), world[b])
                if keeps[b] is not None:  # the share of the turn away from rest
                    away = q_mul(q_inv(rest_local_r[b]), local)
                    local = q_mul(rest_local_r[b], q_slerp(ident, away / np.linalg.norm(away), keeps[b]))
                if offsets[b] is not None:  # a fixed turn in model axes, on top
                    turned = q_mul(offsets[b], q_mul(parent_placed, local))
                    local = q_mul(q_inv(parent_placed), turned)
                local = local / np.linalg.norm(local)
                placed[b] = q_mul(parent_placed, local)
                out_r[f, b] = local
            else:
                world[b] = parent_world
                placed[b] = parent_placed
        if hips is not None and hips in joint:
            move = (wp[source] - rest_wp[source]) * scale
            up = bones[hips][1]
            if up >= 0 and np.any(placed[up] != ident):  # a moving parent: its axes
                move = q_rotate(q_inv(placed[up]), move)
            out_t[f, hips] = rest_local[hips] + move
    # one hemisphere per bone over time (smooth interpolation between frames)
    for f in range(1, frames):
        flip = (out_r[f] * out_r[f - 1]).sum(axis=1) < 0
        out_r[f, flip] *= -1
    return out_t, out_r


def default_pivot(name: str, box: tuple[Array, Array], parent_centre: Array | None) -> Array:
    """Where a humanoid joint goes on its part: the hips' middle; spine, chest and head at their bottom; a limb at
    the end of its long side nearest its parent."""
    lo, hi = box
    centre = (lo + hi) / 2
    if name == "hips":
        return np.asarray(centre)
    if name in ("spine", "chest", "head"):
        return np.array([centre[0], lo[1], centre[2]])
    axis = int(np.argmax(hi - lo))
    a, b = centre.copy(), centre.copy()
    a[axis], b[axis] = lo[axis], hi[axis]
    if parent_centre is None:
        return np.asarray(a)
    return np.asarray(a if np.linalg.norm(a - parent_centre) <= np.linalg.norm(b - parent_centre) else b)


__all__ = ["HUMANOID", "HUMANOID_MAP", "JOINTS", "REQUIRED", "Clip", "JointMap", "clip_names", "default_pivot", "joint_names", "load_clip", "mover", "retarget"]
