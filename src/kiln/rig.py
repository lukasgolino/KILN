"""Rigs: bones from part ids, skin weights from the field, and animations (poses and procedural cycles).

Every part id is a bone (node) with a pivot; children follow their parents. `skin: rigid` moves each part as
one piece. `skin: soft` makes one skinned mesh whose weights come from each part's distance: a leg blended into
a body bends smoothly at the blend, because KILN knows which shape every point of the surface came from.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from kiln.notation import ROOT_ID, Animation, Model, PartPose
from kiln.retarget import HUMANOID_MAP, JOINTS, default_pivot, load_clip, retarget
from kiln.sdf import IDENTITY, Array, Field, Geometry, rotation_matrix
from kiln.usage import Progress

MAX_INFLUENCES = 4


@dataclass
class Bone:
    name: str
    parent: int  # index, -1 for the root
    pivot: Array  # world position of the joint at rest
    meta: dict[str, object]
    separate: bool
    sockets: dict[str, Array] = field(default_factory=dict)  # name -> model-space point at rest
    end: Array | None = None  # the far end at rest (its limb's axis end, or its box's far end): where `aim` points it (#200)


@dataclass
class Skeleton:
    bones: list[Bone]

    def index(self, name: str) -> int:
        return next(i for i, b in enumerate(self.bones) if b.name == name)

    def rest_translation(self, i: int) -> Array:
        b = self.bones[i]
        return b.pivot - (self.bones[b.parent].pivot if b.parent >= 0 else np.zeros(3))


ENDS = ("hand_l", "hand_r", "foot_l", "foot_r", "toes_l", "toes_r")  # humanoid joints at the end of the limb above


def limb_segment(g: Geometry) -> tuple[Array, Array] | None:
    """The model-space ends of a part's axis (capsule from/to, cylinder or cone height, tube end points), or None
    (other shapes, mirrored or repeated parts)."""
    if g.op != "add" or g.mirror or len(g.copies) != 1 or g.copies[0] is not IDENTITY:
        return None
    if g.shape == "capsule":
        a, b = np.asarray(g.params["from"], float), np.asarray(g.params["to"], float)
    elif g.shape in ("cylinder", "cone"):
        h = float(g.params["height"]) / 2
        a, b = np.array([0.0, -h, 0.0]), np.array([0.0, h, 0.0])
    elif g.shape == "tube":
        pts = np.asarray(g.params["points"], float)
        a, b = pts[0], pts[-1]
    else:
        return None
    r = g.rotation if g.rotation is not None else np.eye(3)
    return g.at + r @ a, g.at + r @ b


def build_skeleton(model: Model, field: Field) -> Skeleton:
    """Root first, then parents before children (glTF needs no order, but previews and tests like it)."""
    ids = model.ids
    humanoid = model.skeleton == "humanoid"

    def box(pid: str) -> tuple[Array, Array]:
        boxes = [field.boxes[i] for i, p in enumerate(model.parts) if p.id == pid and p.geometry.op == "add"]
        return np.min([b[0] for b in boxes], axis=0), np.max([b[1] for b in boxes], axis=0)

    def default_parent(pid: str) -> str:
        if humanoid and pid in JOINTS and JOINTS[pid][1] in ids:
            return JOINTS[pid][1]
        return ROOT_ID

    parent_of: dict[str, str] = {pid: (model.rig[pid].parent or default_parent(pid)) if pid in model.rig else default_parent(pid) for pid in ids[1:]}

    def centre(pid: str) -> Array | None:
        return None if pid == ROOT_ID else (box(pid)[0] + box(pid)[1]) / 2

    def ends(pid: str) -> tuple[Array, Array] | None:
        """A limb's (joint end, far end): its longest capsule/cylinder/cone/tube's axis ends (the centres of a
        capsule's round caps, not the tops of its box), the joint end nearest its parent; None without one."""
        segments = [seg for i, p in enumerate(model.parts) if p.id == pid and (seg := limb_segment(p.geometry)) is not None]
        if not segments:
            return None
        a, b = max(segments, key=lambda seg: float(np.linalg.norm(seg[1] - seg[0])))
        up = centre(parent_of[pid])
        if up is not None and np.linalg.norm(b - up) < np.linalg.norm(a - up):
            a, b = b, a
        return a, b

    def joint_pivot(pid: str) -> Array:
        up = parent_of[pid]
        if pid in ENDS and up != ROOT_ID:  # hands, feet, toes: where the limb above them ends (wrist, ankle), on their box
            limb = ends(up)
            far = limb[1] if limb is not None else default_far(up)
            lo, hi = box(pid)
            return np.clip(far, lo, hi)
        if pid not in ("hips", "spine", "chest", "head"):
            limb = ends(pid)
            if limb is not None:
                return limb[0]
        return default_pivot(pid, box(pid), centre(up))

    def default_far(pid: str) -> Array:
        """The end of a part's box opposite its joint (box limbs)."""
        lo, hi = box(pid)
        mid = (lo + hi) / 2
        axis = int(np.argmax(hi - lo))
        a, b = mid.copy(), mid.copy()
        a[axis], b[axis] = lo[axis], hi[axis]
        near = default_pivot(pid, (lo, hi), centre(parent_of[pid]))
        return b if np.allclose(near, a) else a
    pivots: dict[str, Array] = {ROOT_ID: np.zeros(3)}
    for pid in ids[1:]:
        entry = model.rig.get(pid)
        if entry is not None and entry.pivot is not None:
            pivots[pid] = np.array(entry.pivot, float)
        elif humanoid and pid in JOINTS:  # standard joints: hips' middle, bottoms of spine/chest/head, limbs at their joint
            pivots[pid] = joint_pivot(pid)
        else:  # default: the centre of the part's box
            lo, hi = box(pid)
            pivots[pid] = (lo + hi) / 2
    order = [ROOT_ID]
    while len(order) < len(ids):
        for pid in ids[1:]:
            if pid not in order and parent_of[pid] in order:
                order.append(pid)
    bones = []
    for pid in order:
        entry = model.rig.get(pid)
        parent = -1 if pid == ROOT_ID else order.index(parent_of[pid])
        meta = {k: list(v) if isinstance(v, tuple) else v for k, v in entry.meta} if entry else {}
        sockets = {k: np.array(v, float) for k, v in entry.sockets} if entry else {}
        end = None
        if pid != ROOT_ID:
            limb = ends(pid)
            end = limb[1] if limb is not None else default_far(pid)
        bones.append(Bone(pid, parent, pivots[pid], meta, bool(entry and entry.separate), sockets, end))
    return Skeleton(bones)


def soft_weights(points: Array, model: Model, field: Field, skeleton: Skeleton, step: float, progress: Progress | None = None) -> tuple[Array, Array]:
    """(joints (V, 4) int, weights (V, 4) float) from each bone's parts' distances: softmax with a temperature
    set by the parts' blend radius, so a smooth joint bends where it blends."""
    names = [b.name for b in skeleton.bones]
    d = np.full((len(names), len(points)), np.inf)
    blend = np.full(len(names), step)
    for i, part in enumerate(model.parts):
        if progress is not None:
            progress("skinning: parts done", i, len(model.parts))
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


def own_bone(points: Array, faces: Array, face_bone: Array, joints: Array, weights: Array, falloff: dict[int, float],
             soft: int | None = None) -> tuple[Array, Array]:
    """Parts with `skin_falloff` (#192): a vertex painted with such a part's bone goes over to that bone alone as it
    gets `falloff` metres (straight line) from where its paint meets another bone's (0: at once); that border keeps
    its blend. A sleeve blended into the chest then moves with the arm instead of smearing down the side. Only the
    first `soft` vertices (hard parts' are set apart afterwards)."""
    n = len(points) if soft is None else soft
    corner_bone = np.repeat(face_bone, 3)
    corners = faces.reshape(-1)
    v_bone = np.full(len(points), -1)
    v_bone[corners] = corner_bone
    mixed = np.zeros(len(points), dtype=bool)  # vertices where faces of different bones meet
    np.logical_or.at(mixed, corners, corner_bone != v_bone[corners])
    joints, weights = joints.copy(), weights.copy()
    for bone, f in falloff.items():
        inner = np.flatnonzero((v_bone[:n] == bone) & ~mixed[:n])
        if not len(inner):
            continue
        if f <= 0:
            s = np.ones(len(inner))
        else:  # the distance to this bone's own border (its faces' mixed vertices), chunked both ways (memory)
            touches = np.zeros(len(points), dtype=bool)
            touches[faces[face_bone == bone].reshape(-1)] = True
            border = points[mixed & touches]
            r = np.full(len(inner), np.inf)
            for a in range(0, len(inner), 2048):
                for b in range(0, len(border), 2048):
                    gap = np.linalg.norm(points[inner[a : a + 2048]][:, None, :] - border[None, b : b + 2048], axis=2)
                    r[a : a + 2048] = np.minimum(r[a : a + 2048], gap.min(axis=1))
            s = np.clip(r / f, 0.0, 1.0)
            s = s * s * (3 - 2 * s)  # smoothstep
        mine = joints[inner] == bone
        w = weights[inner] * (1 - s)[:, None]
        w[mine] += np.broadcast_to(s[:, None], mine.shape)[mine]
        missing = np.flatnonzero(~mine.any(axis=1))
        if len(missing):  # the bone wasn't among its four: it takes the weakest slot
            slot = np.argmin(w[missing], axis=1)
            joints[inner[missing], slot] = bone
            w[missing, slot] = s[missing]
        weights[inner] = w / np.maximum(w.sum(axis=1, keepdims=True), 1e-12)
    joints[weights <= 0] = 0  # glTF: unused influences point at joint 0
    weights[weights <= 0] = 0.0
    return joints, weights


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


# Gaits (#150): walk and waddle as before on a model without lower limbs; a humanoid (or a model naming `knees:` /
# `elbows:`) bends them, and with its skeleton the body follows the planted foot. run and sneak are faster / crouched.
GAITS: dict[str, dict[str, float]] = {
    "walk": {"swing": 30.0, "arm_swing": 25.0, "knee": 40.0, "knee_rest": 5.0, "elbow": 20.0, "bounce": 0.02, "lean": 0.0, "crouch": 0.0},
    "waddle": {"swing": 18.0, "arm_swing": 25.0, "knee": 20.0, "knee_rest": 5.0, "elbow": 15.0, "bounce": 0.02, "lean": 0.0, "crouch": 0.0},
    "run": {"swing": 45.0, "arm_swing": 40.0, "knee": 80.0, "knee_rest": 15.0, "elbow": 85.0, "bounce": 0.05, "lean": 10.0, "crouch": 0.0},
    "sneak": {"swing": 20.0, "arm_swing": 10.0, "knee": 30.0, "knee_rest": 5.0, "elbow": 45.0, "bounce": 0.01, "lean": 15.0, "crouch": 15.0},
}  # fmt: skip


def _euler(axis: Array, degrees: float) -> tuple[float, float, float]:
    """PartPose angles (rotation_matrix's x, y, z: R = Rz Ry Rx) of a turn about `axis`."""
    from kiln.sdf import axis_rotation

    return _euler_of(axis_rotation(np.asarray(axis, float), degrees))


def _swing_axis(direction: Array | None) -> Array:
    """The axis a limb pointing along `direction` swings forward/back about: square to it and to the front (+z); x
    for a hanging limb, y for a T-posed arm. Without a direction (no skeleton), x."""
    if direction is None:
        return np.array([1.0, 0.0, 0.0])
    d = np.asarray(direction, float)
    d = d - np.array([0.0, 0.0, d[2]])  # in the body's plane
    axis = np.cross(np.array([0.0, 0.0, 1.0]), d)
    n = float(np.linalg.norm(axis))
    return axis / n if n > 1e-6 else np.array([1.0, 0.0, 0.0])


def _wave(t: float) -> float:
    return math.sin(2 * math.pi * t)


def animation_poses(anim: Animation, model: Model, skeleton: Skeleton | None = None) -> list[dict[str, PartPose]]:
    """Every frame's poses: the explicit ones, the cycle's, or both: with `cycle` and `poses` together the poses
    repeat over the cycle's frames and a part named in a pose follows the pose instead of the cycle (walk legs +
    carrying arms). With the skeleton, gaits keep the planted foot on the ground."""
    if anim.cycle is None:
        frames = anim.poses
    else:
        frames = expand_cycle(anim, model, skeleton)
        if anim.poses:
            frames = [{**frame, **anim.poses[i % len(anim.poses)]} for i, frame in enumerate(frames)]
    return _solve_targets(frames, skeleton) if skeleton is not None else frames


def _euler_of(r: Array) -> tuple[float, float, float]:
    """PartPose angles (rotation_matrix's x, y, z: R = Rz Ry Rx) of a rotation matrix. At y = +-90 degrees x and z
    turn about one axis: all of it goes to z (x = 0), read from entries that hold it exactly, not from rounding
    noise (which flipped a straight-forward arm's roll by 180 degrees, #200)."""
    cos_b = math.hypot(float(r[0, 0]), float(r[1, 0]))
    b = math.atan2(-float(r[2, 0]), cos_b)
    if cos_b < 1e-6:
        return 0.0, math.degrees(b), math.degrees(math.atan2(-float(r[0, 1]), float(r[1, 1])))
    a, c = math.atan2(float(r[2, 1]), float(r[2, 2])), math.atan2(float(r[1, 0]), float(r[0, 0]))
    return math.degrees(a), math.degrees(b), math.degrees(c)


def _arc(u: Array, v: Array) -> Array:
    """The shortest rotation taking direction u to direction v."""
    from kiln.sdf import axis_rotation

    u, v = u / np.linalg.norm(u), v / np.linalg.norm(v)
    axis = np.cross(u, v)
    if np.linalg.norm(axis) < 1e-9:
        if float(u @ v) > 0:
            return np.eye(3)
        axis = np.cross(u, [1.0, 0.0, 0.0] if abs(u[0]) < 0.9 else [0.0, 1.0, 0.0])
    return axis_rotation(axis, math.degrees(math.atan2(float(np.linalg.norm(np.cross(u, v))), float(u @ v))))


def bone_end(skeleton: Skeleton, i: int) -> Array | None:
    """Where bone i points at rest: its only child's joint, else its own far end."""
    children = [j for j, b in enumerate(skeleton.bones) if b.parent == i]
    return skeleton.bones[children[0]].pivot if len(children) == 1 else skeleton.bones[i].end


def bone_ends(skeleton: Skeleton, track: Track, frames: list[int] | None = None) -> dict[str, list[list[float]]]:
    """Each bone's end (where `aim` points it: its only child's joint, else its far end) in model space per frame:
    what a pose put where (#200)."""
    out: dict[str, list[list[float]]] = {}
    for f in frames if frames is not None else range(track.frames):
        mats = skin_matrices(skeleton, track.translation[f], track.rotation[f], track.scale[f])
        for i, b in enumerate(skeleton.bones):
            end = bone_end(skeleton, i)
            if end is not None:
                out.setdefault(b.name, []).append([round(float(v), 4) for v in (mats[i] @ np.append(end, 1.0))[:3]])
    return out


def _solve_targets(frames: list[dict[str, PartPose]], skeleton: Skeleton) -> list[dict[str, PartPose]]:
    """`aim` and `reach` (#200) turned into each frame's rotations, parents first: `aim` turns a bone (the shortest
    way from where its parent leaves it) so it points at a model-space point; `reach` bends a bone and its only
    child (an upper arm and forearm) so the child's end is at the point, the middle joint toward `pole` (default: the
    way the chain bends at rest; a straight leg's knee forward, any other straight chain's joint back)."""
    from dataclasses import replace

    if not any(pp.aim is not None or pp.reach is not None for pose in frames for pp in pose.values()):
        return frames
    bones = skeleton.bones
    children = {i: [j for j, b in enumerate(bones) if b.parent == i] for i in range(len(bones))}
    out = []
    for frame in frames:
        pose = dict(frame)
        rot: dict[int, Array] = {}  # world rotation
        lin: dict[int, Array] = {}  # world rotation x scale (what moves a child's joint)
        pos: dict[int, Array] = {}  # world joint position
        for i, b in enumerate(bones):
            pp = pose.get(b.name, PartPose())
            up_r, up_l, up_p = (rot[b.parent], lin[b.parent], pos[b.parent]) if b.parent >= 0 else (np.eye(3), np.eye(3), np.zeros(3))
            here = up_p + up_l @ (skeleton.rest_translation(i) + np.array(pp.offset))
            target, rest_end = (np.array(pp.aim), bone_end(skeleton, i)) if pp.aim is not None else (None, None)
            if pp.reach is not None:
                goal = np.array(pp.reach)
                kids = children[i]
                tip = bone_end(skeleton, kids[0]) if len(kids) == 1 else None
                if tip is None:  # no single child: point the bone itself there
                    target, rest_end = goal, bone_end(skeleton, i)
                else:
                    k = kids[0]
                    a = float(np.linalg.norm(bones[k].pivot - b.pivot))
                    c = float(np.linalg.norm(tip - bones[k].pivot))
                    to = goal - here
                    d = min(max(float(np.linalg.norm(to)), abs(a - c) + 1e-6), a + c - 1e-6)
                    u = to / max(float(np.linalg.norm(to)), 1e-9)
                    if pp.pole is not None:
                        side = np.array(pp.pole) - here
                    else:
                        line = tip - b.pivot
                        bend = bones[k].pivot - b.pivot
                        bend = bend - line * float(bend @ line) / max(float(line @ line), 1e-12)
                        side = up_r @ bend if np.linalg.norm(bend) > 1e-3 * a else np.array([0.0, 0.0, 1.0 if "leg" in b.name else -1.0])
                    side = side - u * float(side @ u)
                    if np.linalg.norm(side) < 1e-9:
                        side = np.cross(u, [1.0, 0.0, 0.0] if abs(u[0]) < 0.9 else [0.0, 1.0, 0.0])
                    side /= np.linalg.norm(side)
                    cos_a = (a * a + d * d - c * c) / (2 * a * d)
                    joint = here + a * (cos_a * u + math.sqrt(max(0.0, 1 - cos_a * cos_a)) * side)
                    target, rest_end = joint, bones[k].pivot
                    pose[bones[k].name] = replace(pose.get(bones[k].name, PartPose()), rotate=(0.0, 0.0, 0.0), aim=(float(goal[0]), float(goal[1]), float(goal[2])))
            if target is not None and rest_end is not None and np.linalg.norm(target - here) > 1e-9:
                spin = _arc(up_r @ (rest_end - b.pivot), target - here)
                pp = replace(pp, rotate=_euler_of(up_r.T @ spin @ up_r))
                pose[b.name] = pp
            r = rotation_matrix(pp.rotate)
            rot[i], lin[i], pos[i] = up_r @ r, up_l @ (r * np.array(pp.scale)[None, :]), here
        out.append(pose)
    return out


def _planted(thigh: dict[str, float], shin: dict[str, float], pivot: dict[str, Array], parent: dict[str, str],
             child: dict[str, str]) -> float | None:
    """How far the body moves up (< 0: down) so the lower ankle is as high as at rest: each leg's hip -> knee ->
    ankle turned by its thigh and knee angles (about x, in the side view). None without the joints."""
    lifts = []
    for knee, bend in shin.items():
        hip, ankle = parent.get(knee), child.get(knee)
        if hip not in thigh or ankle is None or hip not in pivot or knee not in pivot or ankle not in pivot:
            continue
        from kiln.sdf import rotation_matrix

        upper = rotation_matrix((thigh[hip], 0.0, 0.0)) @ (pivot[knee] - pivot[hip])
        lower = rotation_matrix((thigh[hip] + bend, 0.0, 0.0)) @ (pivot[ankle] - pivot[knee])
        lifts.append(float(pivot[ankle][1] - (pivot[hip][1] + upper[1] + lower[1])))
    return max(lifts) if lifts else None


def expand_cycle(anim: Animation, model: Model, skeleton: Skeleton | None = None) -> list[dict[str, PartPose]]:
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

    humanoid = model.skeleton == "humanoid"

    def listed(key: str, default: list[str], human: list[str]) -> list[str]:
        """What was asked, else KILN's names, else (a humanoid) its joint names."""
        if key in c:
            return [n for n in names(key, []) if n in ids]
        mine = [n for n in default if n in ids]
        return mine if mine or not humanoid else [n for n in human if n in ids]

    legs = listed("legs", ["leg_l", "leg_r"], ["upperleg_l", "upperleg_r"])
    arms = listed("arms", ["arm_l", "arm_r"], ["upperarm_l", "upperarm_r"])
    # lower limbs bend (#150): a humanoid's, unless its legs / arms were listed (then only what `knees:` / `elbows:` name)
    knees = listed("knees", [], ["lowerleg_l", "lowerleg_r"] if "legs" not in c else [])
    elbows = listed("elbows", [], ["lowerarm_l", "lowerarm_r"] if "arms" not in c else [])
    pivot = {b.name: b.pivot for b in skeleton.bones} if skeleton is not None else {}
    parent = {b.name: skeleton.bones[b.parent].name for b in skeleton.bones if b.parent >= 0} if skeleton is not None else {}
    child = {up: b for b, up in parent.items()}

    def phase(limb: str, of: list[str]) -> float:
        """A lower limb moves with the limb it hangs from (its parent, else the same side's, else its place)."""
        up = parent.get(limb)
        if up in of:
            return 0.5 * of.index(up)
        side = next((k for k, n in enumerate(of) if n[-2:] == limb[-2:]), None)
        return 0.5 * (side if side is not None else 0)

    def axis_of(limb: str) -> Array:
        tip = child.get(limb)
        return _swing_axis(pivot[tip] - pivot[limb] if limb in pivot and tip in pivot else None)

    body = str(c.get("body", "root"))
    part = str(c.get("part", "root"))
    axis = {"x": 0, "y": 1, "z": 2}.get(str(c.get("axis", "y")), 1)
    for i in range(frames):
        t = i / frames
        pose: dict[str, PartPose] = {}
        if kind in GAITS:
            g = GAITS[kind]
            swing, crouch = opt("swing", g["swing"]), opt("crouch", g["crouch"])
            # model axes: about +x a hanging tip (foot, hand) goes back, an upright one (head) forward
            thigh = {leg: swing * _wave(t + 0.5 * k) - crouch for k, leg in enumerate(legs)}
            for leg, a in thigh.items():
                pose[leg] = PartPose(rotate=_euler(axis_of(leg), a) if knees else (a, 0.0, 0.0))
            for k, arm in enumerate(arms):
                a = -opt("arm_swing", g["arm_swing"]) * _wave(t + 0.5 * k)
                pose[arm] = PartPose(rotate=_euler(axis_of(arm), a) if elbows else (a, 0.0, 0.0))
            # knees fold (foot back) most while their leg swings forward, a little at rest, more when crouching;
            # elbows hold a bend (forearm forward) that grows as their arm swings forward
            shin: dict[str, float] = {}
            for knee in knees:
                lift = max(0.0, -math.cos(2 * math.pi * (t + phase(knee, legs))))
                shin[knee] = opt("knee", g["knee"]) * lift + 2 * crouch + opt("knee_rest", g["knee_rest"])
                pose[knee] = PartPose(rotate=_euler(axis_of(knee), shin[knee]))
                hip, foot = parent.get(knee), child.get(knee)
                if hip in thigh and foot in ids:  # the foot stays level (soles flat on the ground)
                    pose[foot] = PartPose(rotate=_euler(axis_of(knee), -(thigh[hip] + shin[knee])))
            for elbow in elbows:
                forward = 0.5 + 0.5 * _wave(t + phase(elbow, arms))
                pose[elbow] = PartPose(rotate=_euler(axis_of(elbow), -opt("elbow", g["elbow"]) * (0.4 + 0.6 * forward)))
            roll = opt("roll", 8.0) * _wave(t) if kind == "waddle" else 0.0
            ground = _planted(thigh, shin, pivot, parent, child) if knees and pivot else None
            if ground is None:  # no skeleton (or lower limbs): the old bounce
                rise = opt("bounce", g["bounce"]) * abs(math.sin(2 * math.pi * t))
            else:  # the body follows the lower ankle down to where it was at rest
                rise = ground
            pose[body] = PartPose(offset=(0.0, rise, 0.0), rotate=(0.0, 0.0, roll))
            torso = str(c.get("torso", "spine"))  # the lean bends the upper body forward, not the legs with it
            if torso in ids and torso != body and opt("lean", g["lean"]):
                pose[torso] = PartPose(rotate=(opt("lean", g["lean"]), 0.0, 0.0))
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
            at = pivot.get(arm) if entry is None or entry.pivot is None else np.asarray(entry.pivot)
            side = 1.0 if at is not None and at[0] > 0 else -1.0  # +X = the model's left
            fore = child.get(arm) if humanoid or "elbows" in c else None
            if fore is not None and fore in ids and fore in pivot and arm in pivot:  # (#319) upper arm out, forearm up, waving from the elbow
                def out_angle(a: Array, b: Array, side: float = side) -> float:  # degrees out from hanging down, in the front plane
                    return math.degrees(math.atan2(side * float(b[0] - a[0]), -float(b[1] - a[1])))

                hand = child.get(fore)
                tip = pivot[hand] if hand in pivot else (pivot[fore] + (pivot[fore] - pivot[arm]))
                upper = opt("raise", 80.0) - out_angle(pivot[arm], pivot[fore])  # angles out from straight down, whatever the rest pose
                lower = opt("raise", 80.0) + opt("bend", 75.0) + opt("angle", 20.0) * _wave(t) - out_angle(pivot[fore], tip) - upper
                pose[arm] = PartPose(rotate=(0.0, 0.0, side * upper))
                pose[fore] = PartPose(rotate=(0.0, 0.0, side * lower))
            else:
                pose[arm] = PartPose(rotate=(0.0, 0.0, side * (opt("raise", 150.0) + opt("angle", 20.0) * _wave(t))))
        elif kind == "idle":  # (#150) standing still with life: breathing, a slow sway, a glance aside, arms settling
            chest = str(c.get("chest", next((n for n in ("chest", "spine", "body") if n in ids), "root")))
            head = str(c.get("head", "head"))
            b = opt("breathe", 0.02) * _wave(t)
            sway = opt("sway", 2.0) * _wave(t + 0.25)
            pose[chest] = PartPose(scale=(1 + b / 2, 1 + b, 1 + b / 2), rotate=(0.0, 0.0, sway))
            if head in ids:
                look = opt("look", 10.0) * math.sin(2 * math.pi * t) ** 3  # holds to either side, turns quickly between
                pose[head] = PartPose(rotate=(opt("nod", 2.0) * _wave(t + 0.1), look, -sway))
            for k, arm in enumerate(arms):
                settle = opt("arm_sway", 3.0) * _wave(t + 0.3 + 0.5 * k)
                pose[arm] = PartPose(rotate=_euler(axis_of(arm), settle) if elbows else (settle, 0.0, 0.0))
            for elbow in elbows:
                pose[elbow] = PartPose(rotate=_euler(axis_of(elbow), -opt("elbow", 8.0)))
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
        if anim.source is not None:  # retargeted from a clip library
            path, clip_name, speed = anim.source
            bones = [(b.name, b.parent, b.pivot) for b in skeleton.bones]
            adjust = anim.retarget or {}
            offsets = {k: quaternion(v) for k, v in adjust.get("offset", {}).items()}
            tr_, rot_ = retarget(load_clip(path, clip_name), bones, anim.fps, speed, adjust.get("keep"), offsets, model.joint_map or HUMANOID_MAP)
            out.append(Track(anim.name, anim.fps, anim.loop, anim.interpolation, tr_, rot_, np.ones(tr_.shape)))
            continue
        poses = animation_poses(anim, model, skeleton)
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


__all__ = ["Bone", "Skeleton", "Track", "animation_poses", "build_skeleton", "expand_cycle", "quaternion", "skin_matrices", "soft_weights", "tracks"]
