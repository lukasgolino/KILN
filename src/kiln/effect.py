"""Effects (`effect:` on a model): a burst of other models' meshes thrown out with velocities, gravity and drag,
scaled, heated and faded over each piece's life. KILN doesn't play effects; it writes them as JSON next to the glb
(`models/<name>.effect.json`) with every particle already rolled from the seed, so an engine-side player shows
exactly what `kiln preview --effect` shows.

Motion of a particle `age` seconds after its delay, with drag k (1/s) and gravity g (m/s^2, a vector):
    k > 0: x = at + g/k * age + (v - g/k) * (1 - exp(-k age)) / k
    k = 0: x = at + v * age + g * age^2 / 2
It turns about `axis` at `spin` degrees per second; scale/heat/fade are envelopes over life (0..1), linear between keys.

With a `floor` (a height in the effect's frame), a particle that comes down onto it bounces: its vertical speed
reverses times `bounce`, its horizontal speed keeps `friction` of itself, and the motion starts again from there (a
"hit"). Once it is slower than SETTLE_SPEED on the floor (or after MAX_HITS) it rests: no motion, no spin. Every hit
is rolled here and written to the JSON, so players switch segments at the same moments. Without `settle` a particle
keeps bouncing until it can't (bounce 0) or MAX_HITS, then rests too: nothing ever falls through the floor.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from kiln.sdf import Array, axis_rotation

FORMAT = 1
EMIT_FIELDS = ("model", "count", "at", "spread", "delay", "life", "velocity", "burst", "gravity", "drag", "spin", "scale", "heat", "fade",
               "bounce", "friction", "settle")  # fmt: skip
EFFECT_FIELDS = ("emit", "duration", "loop", "seed", "floor")
SETTLE_SPEED = 0.2  # m/s: slower than this on the floor, a settling particle rests
MAX_HITS = 16
HELP = ("effect is { emit: [{ model: spark, count: 12, at: [x, y, z], spread: m, delay: s | [lo, hi], life: s | [lo, hi], "
        "velocity: [x, y, z] | { min: [x, y, z], max: [x, y, z] }, burst: m/s | [lo, hi] (outward, any direction), "
        "gravity: m/s^2 down | [x, y, z], drag: 1/s, spin: deg/s | [lo, hi], scale | heat | fade: v | { 0: v, 0.5: v, 1: v } "
        "(over life), bounce: 0-1, friction: 0-1, settle: true (with a floor) }], floor: y (optional), duration: s, loop: false, "
        "seed: 0 }")  # fmt: skip

Range = tuple[float, float]
Envelope = tuple[tuple[float, float], ...]  # (life fraction, value), sorted


@dataclass(frozen=True)
class Emitter:
    model: str
    count: int = 1
    at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    spread: float = 0.0
    delay: Range = (0.0, 0.0)
    life: Range = (1.0, 1.0)
    velocity: tuple[tuple[float, float, float], tuple[float, float, float]] = ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    burst: Range = (0.0, 0.0)
    gravity: tuple[float, float, float] = (0.0, 0.0, 0.0)
    drag: float = 0.0
    spin: Range = (0.0, 0.0)
    scale: Envelope = ((0.0, 1.0),)
    heat: Envelope = ((0.0, 1.0),)
    fade: Envelope = ((0.0, 1.0),)
    bounce: float = 0.3  # with a floor: vertical speed kept (reversed) at a hit; 0 = stops dead
    friction: float = 0.6  # with a floor: horizontal speed kept at a hit
    settle: bool = True  # with a floor: rest once slow on it


Hit = tuple[float, tuple[float, float, float], tuple[float, float, float]]  # age, position, velocity after the hit


@dataclass(frozen=True)
class Particle:
    emitter: int
    delay: float
    life: float
    at: tuple[float, float, float]
    velocity: tuple[float, float, float]
    axis: tuple[float, float, float]
    spin: float  # degrees per second
    hits: tuple[Hit, ...] = ()  # floor contacts; a hit with velocity (0, 0, 0) and no spin after it = resting


@dataclass(frozen=True)
class Effect:
    emitters: tuple[Emitter, ...]
    duration: float
    loop: bool = False
    seed: int = 0
    floor: float | None = None


def _num(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _vec(v: Any) -> tuple[float, float, float] | None:
    if isinstance(v, list) and len(v) == 3 and all(_num(x) for x in v):
        return (float(v[0]), float(v[1]), float(v[2]))
    return None


def _range(v: Any, low: float = -math.inf) -> Range | None:
    if _num(v) and v >= low:
        return (float(v), float(v))
    if isinstance(v, list) and len(v) == 2 and all(_num(x) and x >= low for x in v) and v[0] <= v[1]:
        return (float(v[0]), float(v[1]))
    return None


def _envelope(v: Any) -> Envelope | None:
    if _num(v):
        return ((0.0, float(v)),)
    if isinstance(v, dict) and v and all(_num(t) and 0 <= t <= 1 and _num(x) for t, x in v.items()):
        return tuple(sorted((float(t), float(x)) for t, x in v.items()))
    return None


def value(env: Envelope, t: float) -> float:
    """An envelope at life fraction t (held before the first key and after the last)."""
    ts = [k for k, _ in env]
    return float(np.interp(t, ts, [x for _, x in env]))


def parse(raw: Any, error: Callable[[str, str], None]) -> Effect | None:
    """An `effect:` block; problems go to error(message, where)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("emit"), list) or not raw["emit"] or any(k not in EFFECT_FIELDS for k in raw):
        error(HELP, "effect")
        return None
    emitters = []
    ok = True
    for i, e in enumerate(raw["emit"]):
        where = f"effect.emit.{i}"
        if not isinstance(e, dict) or not isinstance(e.get("model"), str) or any(k not in EMIT_FIELDS for k in e):
            unknown = [str(k) for k in e if k not in EMIT_FIELDS] if isinstance(e, dict) else []
            error(f"emit needs model: <a model in this project>{'; unknown: ' + ', '.join(unknown) if unknown else ''}. {HELP}", where)
            ok = False
            continue
        problems = []
        count = e.get("count", 1)
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 1000:
            problems.append("count is 1-1000")
        at = _vec(e.get("at", [0, 0, 0]))
        if at is None:
            problems.append("at is [x, y, z]")
        spread = e.get("spread", 0)
        if not _num(spread) or spread < 0:
            problems.append("spread is a radius >= 0 (m)")
        delay, life, burst, spin = _range(e.get("delay", 0), 0), _range(e.get("life", 1), 1e-3), _range(e.get("burst", 0), 0), _range(e.get("spin", 0))
        for name, r in (("delay", delay), ("life", life), ("burst", burst), ("spin", spin)):
            if r is None:
                problems.append(f"{name} is a number or [lo, hi]" + (" (> 0)" if name == "life" else ""))
        vel_raw = e.get("velocity", [0, 0, 0])
        velocity = None
        if isinstance(vel_raw, dict) and set(vel_raw) == {"min", "max"}:
            lo, hi = _vec(vel_raw["min"]), _vec(vel_raw["max"])
            if lo is not None and hi is not None and all(a <= b for a, b in zip(lo, hi, strict=True)):
                velocity = (lo, hi)
        elif (v := _vec(vel_raw)) is not None:
            velocity = (v, v)
        if velocity is None:
            problems.append("velocity is [x, y, z] or { min: [x, y, z], max: [x, y, z] } (m/s)")
        g_raw = e.get("gravity", 0)
        gravity = (0.0, -float(g_raw), 0.0) if _num(g_raw) else _vec(g_raw)
        if gravity is None:
            problems.append("gravity is m/s^2 downwards (9.8) or a vector [x, y, z]")
        drag = e.get("drag", 0)
        if not _num(drag) or drag < 0:
            problems.append("drag is >= 0 (1/s: velocity falls by e every 1/drag seconds)")
        bounce, friction, settle = e.get("bounce", 0.3), e.get("friction", 0.6), e.get("settle", True)
        if not (_num(bounce) and 0 <= bounce <= 1 and _num(friction) and 0 <= friction <= 1 and isinstance(settle, bool)):
            problems.append("bounce and friction are 0-1 (speed kept at a floor hit: vertical, horizontal), settle true or false")
        envs = {k: _envelope(e.get(k, 1)) for k in ("scale", "heat", "fade")}
        problems += [f"{k} is a number or { {0: 0.2, 0.3: 1, 1: 0} } (life fraction 0-1: value)" for k, v in envs.items() if v is None]
        if problems:
            error("emit: " + "; ".join(problems), where)
            ok = False
            continue
        assert at and delay and life and burst and spin and velocity and gravity
        emitters.append(Emitter(e["model"], count, at, float(spread), delay, life, velocity, burst, gravity, float(drag), spin,
                                envs["scale"] or (), envs["heat"] or (), envs["fade"] or (), float(bounce), float(friction), settle))  # fmt: skip
    seed, loop = raw.get("seed", 0), raw.get("loop", False)
    if not isinstance(seed, int) or isinstance(seed, bool) or not isinstance(loop, bool):
        error("seed is a whole number, loop true or false", "effect")
        ok = False
    longest = max((em.delay[1] + em.life[1] for em in emitters), default=1.0)
    duration = raw.get("duration", longest)
    if not _num(duration) or duration <= 0:
        error("duration is seconds > 0 (default: the last particle's end)", "effect.duration")
        ok = False
    floor = raw.get("floor")
    if floor is not None and not _num(floor):
        error("floor is a height y (m, in the effect's frame) that particles bounce on and settle on", "effect.floor")
        ok = False
    if not ok:
        return None
    return Effect(tuple(emitters), float(duration), bool(loop), int(seed), float(floor) if floor is not None else None)


def _r(x: float) -> float:
    return round(x, 6) + 0.0


def particles(effect: Effect) -> list[Particle]:
    """Every particle, rolled from the seed (Python's Mersenne Twister: the same on every machine)."""
    rng = random.Random(effect.seed)

    def between(r: Range) -> float:
        return r[0] + (r[1] - r[0]) * rng.random()

    def direction() -> Array:
        z = 2 * rng.random() - 1
        a = 2 * math.pi * rng.random()
        s = math.sqrt(max(0.0, 1 - z * z))
        return np.array([s * math.cos(a), z, s * math.sin(a)])

    out = []
    for k, em in enumerate(effect.emitters):
        for _ in range(em.count):
            delay, life = between(em.delay), between(em.life)
            offset = direction() * em.spread * rng.random() ** (1 / 3)  # uniform in the ball
            out_dir = direction()
            v = np.array([between((lo, hi)) for lo, hi in zip(*em.velocity, strict=True)]) + out_dir * between(em.burst)
            axis, spin = direction(), between(em.spin)
            p = Particle(k, _r(delay), _r(life), tuple(_r(float(a + b)) for a, b in zip(em.at, offset, strict=True)),  # type: ignore[arg-type]
                         tuple(_r(float(x)) for x in v), tuple(_r(float(x)) for x in axis), _r(spin))  # type: ignore[arg-type]
            out.append(replace(p, hits=_hits(em, p, effect.floor)) if effect.floor is not None else p)
    return out


def _flight(em: Emitter, at: Array, v: Array, age: float) -> tuple[Array, Array]:
    """Position and velocity `age` seconds into one ballistic segment."""
    g, k = np.array(em.gravity), em.drag
    if k > 0:
        decay = math.exp(-k * age)
        return at + g / k * age + (v - g / k) * (1 - decay) / k, g / k + (v - g / k) * decay
    return at + v * age + g * age * age / 2, v + g * age


def _hits(em: Emitter, p: Particle, floor: float) -> tuple[Hit, ...]:
    """Floor contacts of one particle over its life (bisection on the closed-form height: the same everywhere)."""
    hits: list[Hit] = []
    start, at, v = 0.0, np.array(p.at, dtype=float), np.array(p.velocity, dtype=float)
    if at[1] < floor:
        return ()  # starts below the floor: it never meets it from above
    steps = 256
    while len(hits) < MAX_HITS:
        span = p.life - start
        if span <= 1e-9:
            break
        found = None
        prev = 0.0
        for i in range(1, steps + 1):  # first crossing downwards, then bisect it
            t = span * i / steps
            pos, vel = _flight(em, at, v, t)
            if pos[1] < floor and vel[1] < 0:
                lo, hi = prev, t
                for _ in range(48):
                    mid = (lo + hi) / 2
                    if _flight(em, at, v, mid)[0][1] < floor:
                        hi = mid
                    else:
                        lo = mid
                found = hi
                break
            prev = t
        if found is None:
            break
        pos, vel = _flight(em, at, v, found)
        pos[1] = floor
        bounced = np.array([vel[0] * em.friction, -vel[1] * em.bounce, vel[2] * em.friction])
        start += found
        slow = em.settle and float(np.linalg.norm(bounced)) < SETTLE_SPEED
        if slow or len(hits) == MAX_HITS - 1 or abs(bounced[1]) < 1e-6:  # rests (it can't bounce any more, or it's done)
            hits.append((_r(start), tuple(_r(float(x)) for x in pos), (0.0, 0.0, 0.0)))  # type: ignore[arg-type]
            break
        hits.append((_r(start), tuple(_r(float(x)) for x in pos), tuple(_r(float(x)) for x in bounced)))  # type: ignore[arg-type]
        at, v = np.array(hits[-1][1]), np.array(hits[-1][2])
    return tuple(hits)


@dataclass(frozen=True)
class State:
    position: Array
    rotation: Array  # 3x3
    scale: float
    heat: float
    fade: float


def state(effect: Effect, p: Particle, t: float) -> State | None:
    """A particle at effect time t, or None before its delay or after its life."""
    em = effect.emitters[p.emitter]
    age = t - p.delay
    if age < 0 or age > p.life:
        return None
    start, at, v, resting = 0.0, np.array(p.at, dtype=float), np.array(p.velocity, dtype=float), False
    for hit_age, hit_at, hit_v in p.hits:  # the segment since the last floor hit
        if hit_age > age:
            break
        start, at, v = hit_age, np.array(hit_at), np.array(hit_v)
        resting = hit_v == (0.0, 0.0, 0.0)  # it stays put and stops turning
    pos = at if resting else _flight(em, at, v, age - start)[0]
    life = age / p.life
    rot = axis_rotation(np.array(p.axis), p.spin * (start if resting else age))
    return State(pos, rot, value(em.scale, life), value(em.heat, life), value(em.fade, life))


def to_json(effect: Effect, files: dict[str, dict[str, str]]) -> dict[str, Any]:
    """The effect file: emitters (with each model's files from `files`), then every particle."""

    def env(e: Envelope) -> list[list[float]]:
        return [[_r(t), _r(x)] for t, x in e]

    emitters = []
    for em in effect.emitters:
        emitters.append({"model": em.model, **files.get(em.model, {}), "count": em.count, "gravity": [_r(x) for x in em.gravity],
                         "drag": _r(em.drag), "scale": env(em.scale), "heat": env(em.heat), "fade": env(em.fade),
                         **({"bounce": _r(em.bounce), "friction": _r(em.friction), "settle": em.settle} if effect.floor is not None else {})})  # fmt: skip
    return {
        "format": FORMAT,
        "duration": _r(effect.duration),
        "loop": effect.loop,
        "seed": effect.seed,
        "motion": "k = drag > 0: x = at + g/k*age + (velocity - g/k)*(1 - exp(-k*age))/k; k = 0: x = at + velocity*age + g*age^2/2; "
                  "rotation = spin degrees/s * age about axis; age = time - delay, alive while 0 <= age <= life; "
                  "scale/heat/fade: linear between [life fraction, value] keys"
                  + ("; floor hits: at each [age, position, velocity] in a particle's hits the motion starts again from that position "
                     "and velocity (age counted from the hit); a hit with velocity [0, 0, 0] = resting there, no more spin" if effect.floor is not None else ""),  # fmt: skip
        **({"floor": _r(effect.floor)} if effect.floor is not None else {}),
        "emitters": emitters,
        "particles": [{"emitter": p.emitter, "delay": p.delay, "life": p.life, "at": list(p.at), "velocity": list(p.velocity),
                       "axis": list(p.axis), "spin": p.spin, **({"hits": [[h[0], list(h[1]), list(h[2])] for h in p.hits]} if effect.floor is not None else {})}
                      for p in particles(effect)],  # fmt: skip
    }


__all__ = ["Effect", "Emitter", "Particle", "State", "parse", "particles", "state", "to_json", "value"]
