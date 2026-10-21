"""SVG path data ("M 0 0 L 1 0 Q 1 1 0 1 Z") flattened to closed outlines, for `extrude: { path: ... }`: logos,
lettering from a font's outlines, sign shapes drawn in a vector editor. Curves become straight segments no more
than `tolerance` from the curve. SVG's y runs down; it maps to the extrude's z, so `rotate: [90, 0, 0]` stands
the shape up reading the right way from the front."""

from __future__ import annotations

import math
import re

Point = tuple[float, float]
TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtZzAa]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


class PathError(ValueError):
    pass


def _quad(p0: Point, p1: Point, p2: Point, tol: float) -> list[Point]:
    dd = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
    n = max(1, min(64, math.ceil(math.sqrt(dd / (4 * tol))))) if dd > 0 else 1
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
    return out


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, tol: float) -> list[Point]:
    dd = max(math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1]), math.hypot(p1[0] - 2 * p2[0] + p3[0], p1[1] - 2 * p2[1] + p3[1]))
    n = max(1, min(64, math.ceil(math.sqrt(3 * dd / (4 * tol))))) if dd > 0 else 1
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t**3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def _arc(p0: Point, rx: float, ry: float, phi_deg: float, large: bool, sweep: bool, p1: Point, tol: float) -> list[Point]:
    """SVG elliptical arc (endpoint form, SVG 1.1 appendix F.6)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(phi_deg)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx, cy = cp * cx1 - sp * cy1 + (p0[0] + p1[0]) / 2, sp * cx1 + cp * cy1 + (p0[1] + p1[1]) / 2

    def angle(ux: float, uy: float, vx: float, vy: float) -> float:
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    t1 = angle(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = angle((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    r = max(rx, ry)
    step = 2 * math.acos(max(-1.0, min(1.0, 1 - tol / r))) if tol < r else math.pi / 2
    n = max(1, min(128, math.ceil(abs(dt) / max(step, 1e-6))))
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        out.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
    out[-1] = p1
    return out


def outlines(d: str, scale: float = 1.0, tolerance: float = 0.002) -> list[list[Point]]:
    """Closed outlines (each subpath; an unclosed one is closed) in path units x `scale`; `tolerance` in the
    same scaled units (metres)."""
    tokens = TOKEN.findall(d)
    if re.sub(TOKEN, "", d).strip(" ,\t\n\r"):
        raise PathError("path has characters that aren't SVG path commands or numbers")
    tol = tolerance / scale if scale else tolerance
    loops: list[list[Point]] = []
    cur: list[Point] = []
    pos: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    last_ctrl: Point | None = None
    last_cmd = ""
    i = 0
    cmd = ""

    def close() -> None:
        nonlocal cur
        pts = [p for k, p in enumerate(cur) if k == 0 or math.hypot(p[0] - cur[k - 1][0], p[1] - cur[k - 1][1]) > 1e-12]
        if len(pts) > 1 and math.hypot(pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1]) <= 1e-12:
            pts.pop()
        if len(pts) >= 3:
            loops.append([(x * scale, y * scale) for x, y in pts])
        cur = []

    while i < len(tokens):
        t = tokens[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                close()
                pos = start
                last_ctrl, last_cmd = None, "Z"
                continue
        elif not cmd or cmd in "Zz":
            raise PathError("path must start with M (move to)")
        n = ARGS[cmd.upper()]
        args = tokens[i : i + n]
        if len(args) < n or any(a.isalpha() for a in args):
            raise PathError(f"{cmd} needs {n} numbers")
        v = [float(a) for a in args]
        i += n
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = pos if rel else (0.0, 0.0)
        if c == "M":
            if cur:
                close()
            pos = (ox + v[0], oy + v[1])
            start = pos
            cur = [pos]
            cmd = "l" if rel else "L"  # further pairs are line-tos
            last_ctrl = None
        elif c == "L":
            pos = (ox + v[0], oy + v[1])
            cur.append(pos)
            last_ctrl = None
        elif c == "H":
            pos = ((pos[0] if rel else 0.0) + v[0], pos[1])
            cur.append(pos)
            last_ctrl = None
        elif c == "V":
            pos = (pos[0], (pos[1] if rel else 0.0) + v[0])
            cur.append(pos)
            last_ctrl = None
        elif c in "CS":
            if c == "C":
                c1 = (ox + v[0], oy + v[1])
                rest = v[2:]
            else:
                c1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl and last_cmd in "CS" else pos
                rest = v
            c2, end = (ox + rest[0], oy + rest[1]), (ox + rest[2], oy + rest[3])
            cur.extend(_cubic(pos, c1, c2, end, tol))
            pos, last_ctrl = end, c2
        elif c in "QT":
            if c == "Q":
                c1 = (ox + v[0], oy + v[1])
                end = (ox + v[2], oy + v[3])
            else:
                c1 = (2 * pos[0] - last_ctrl[0], 2 * pos[1] - last_ctrl[1]) if last_ctrl and last_cmd in "QT" else pos
                end = (ox + v[0], oy + v[1])
            cur.extend(_quad(pos, c1, end, tol))
            pos, last_ctrl = end, c1
        elif c == "A":
            end = (ox + v[5], oy + v[6])
            cur.extend(_arc(pos, v[0], v[1], v[2], bool(v[3]), bool(v[4]), end, tol))
            pos, last_ctrl = end, None
        if not cur:
            cur = [start]
        last_cmd = c
    if cur:
        close()
    if not loops:
        raise PathError("path has no closed outline with 3+ different points")
    return loops


__all__ = ["PathError", "outlines"]
