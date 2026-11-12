"""Lint W135 (#255): a limb fused to another branch of a soft-skinned body at rest.

On one soft mesh, two parts on bones of different branches (an upper arm and the belly, one leg and the other) that
overlap or blend away from the joint where the limb meets the body are one lump of skin: posing the limb stretches
it. Near the joint (the shoulder, the hip) they are meant to meet, so overlap there is fine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from kiln.sdf import Array

if TYPE_CHECKING:
    from kiln.export import Built
    from kiln.rig import Bone

JOINT_SHARE = 0.4  # overlap within this share of the limb part's reach from its joint is where it meets the body
MAX_POINTS = 12000  # grid points per pair at most
MIN_POINTS = 4  # fused grid points (beyond the joint) before it counts


def _branch_top(bones: list[Bone], child: int, ancestor: int) -> int:
    """The bone on the path from `ancestor` down to `child` whose parent is `ancestor`."""
    while bones[child].parent != ancestor:
        child = bones[child].parent
    return child


def _ancestors(bones: list[Bone], i: int) -> list[int]:
    out = []
    while bones[i].parent >= 0:
        i = bones[i].parent
        out.append(i)
    return out


def _paired(name: str, names: dict[str, int], twins: set[str]) -> bool:
    """A limb has a twin on the other side (arm_l / arm_r, or a mirror_id copy): a torso piece, a head or a hat doesn't."""
    if name in twins:
        return True
    for a, b in (("_l", "_r"), ("_r", "_l"), (".l", ".r"), (".r", ".l"), ("_L", "_R"), ("_R", "_L"), (".L", ".R"), (".R", ".L")):
        if name.endswith(a) and name[: -len(a)] + b in names:
            return True
    return False


def fused_limbs(built: Built) -> list[tuple[str, int | None, str]]:
    """(message, line, where) per fused pair, the deepest first."""
    m = built.model
    if built.skin != "soft" or not built.skeleton.bones:
        return []
    bones = built.skeleton.bones
    names = {b.name: k for k, b in enumerate(bones)}
    parts = [(k, p) for k, p in enumerate(m.parts) if p.geometry.op == "add" and not p.hard and not p.crisp and p.id in names]
    boxes = {k: p.geometry.bounds() for k, p in parts}
    twins = {p.id for p in m.parts if p.twin_of is not None} | {p.twin_of for p in m.parts if p.twin_of is not None}
    step = max(built.step, 1e-3)
    found: list[tuple[float, str, int | None, str]] = []
    seen: set[tuple[str, str]] = set()
    for a in range(len(parts)):
        for b in range(a + 1, len(parts)):
            (ka, pa), (kb, pb) = parts[a], parts[b]
            ia, ib = names[pa.id], names[pb.id]
            if ia == ib or (pa.id, pb.id) in seen:
                continue
            up_a, up_b = _ancestors(bones, ia), _ancestors(bones, ib)
            if ib in up_a:  # pa is on the limb (below pb's bone): the joint is where pa's branch leaves pb's bone
                tops, limb = [_branch_top(bones, ia, ib)], (ka, pa)
            elif ia in up_b:
                tops, limb = [_branch_top(bones, ib, ia)], (kb, pb)
            else:  # two branches (a leg and the other leg): joints where each leaves the bone they share
                common = next((x for x in up_a if x in up_b), None)
                if common is None:
                    continue
                tops = [_branch_top(bones, ia, common), _branch_top(bones, ib, common)]
                limb = (ka, pa) if np.linalg.norm(boxes[ka][1] - boxes[ka][0]) <= np.linalg.norm(boxes[kb][1] - boxes[kb][0]) else (kb, pb)
            if not all(_paired(bones[t].name, names, twins) for t in tops):  # torso pieces, a head, a hat: meant to merge
                continue
            if any(bones[t].parent >= 0 and _paired(bones[bones[t].parent].name, names, twins) for t in tops):
                continue  # within one limb (a shin and its thigh, a foot and its shin): they meet at their joint
            joints = [bones[t].pivot for t in tops]
            reach = max(pa.geometry.blend, pb.geometry.blend, 0.0)
            lo = np.maximum(boxes[ka][0], boxes[kb][0]) - reach
            hi = np.minimum(boxes[ka][1], boxes[kb][1]) + reach
            if (hi <= lo).any():
                continue
            cell = max(step, float(np.prod(hi - lo) / MAX_POINTS) ** (1 / 3))
            axes = [np.arange(lo[d] + cell / 2, hi[d], cell) for d in range(3)]
            if any(len(x) == 0 for x in axes):
                continue
            pts = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
            da, db = pa.geometry.distance(pts), pb.geometry.distance(pts)
            fused = (da < reach) & (db < reach) & ((da < 0) | (db < 0))  # inside one and within the blend of the other
            if not fused.any():
                continue
            far = max(float(np.linalg.norm(c - j, axis=1).max()) for j in joints for c in [_corners(boxes[limb[0]])])
            gap = JOINT_SHARE * far
            dj = np.min([np.linalg.norm(pts - j, axis=1) for j in joints], axis=0)
            away = fused & (dj > gap)
            if int(away.sum()) < MIN_POINTS:
                continue
            k_limb, p_limb = limb
            other = pb if p_limb is pa else pa
            d_limb, d_other = (da, db) if p_limb is pa else (db, da)
            inside = away & (d_limb <= 0)
            depth = float((reach - d_other[inside]).max()) if inside.any() else reach
            where_pt = pts[away][np.argmax(dj[away])]
            seen.add((pa.id, pb.id))
            msg = (f"{p_limb.id} (part {k_limb}) and {other.id} are fused at rest out to {float(dj[away].max()):.2f} m from its joint "
                   f"(near [{where_pt[0]:.2f}, {where_pt[1]:.2f}, {where_pt[2]:.2f}]): one lump of skin, so posing {p_limb.id} stretches it. "
                   f"Move {p_limb.id} about {depth + step:.2f} m clear of {other.id}, or model the limb out from the body (an A-pose)")  # fmt: skip
            found.append((depth, msg, p_limb.line, p_limb.where))
    found.sort(key=lambda f: -f[0])
    return [(msg, line, where) for _, msg, line, where in found]


def _corners(box: tuple[Array, Array]) -> Array:
    lo, hi = box
    return np.array([[(lo, hi)[i][0], (lo, hi)[j][1], (lo, hi)[k][2]] for i in (0, 1) for j in (0, 1) for k in (0, 1)])


__all__ = ["fused_limbs"]
