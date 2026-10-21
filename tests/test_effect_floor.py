"""#31: an effect floor: debris bounces, slides and settles instead of falling through, and the JSON carries every
hit so an engine-side player matches the preview."""

from __future__ import annotations

from typing import Any

import pytest

from kiln.effect import MAX_HITS, SETTLE_SPEED, parse, particles, state, to_json


def _effect(**emit: Any) -> Any:
    errors: list[str] = []
    raw = {"floor": 0, "seed": 4, "emit": [{"model": "chip", "count": 8, "at": [0, 0.5, 0], "burst": [2, 3], "gravity": 9.8,
                                            "life": 3, "spin": 120, **emit}]}  # fmt: skip
    effect = parse(raw, lambda message, where: errors.append(message))
    assert effect is not None, errors
    return effect


def test_debris_bounces_and_settles_on_the_floor() -> None:
    effect = _effect()
    for p in particles(effect):
        assert 1 <= len(p.hits) <= MAX_HITS and p.hits[-1][2] == (0.0, 0.0, 0.0)  # every piece ends resting
        heights = [state(effect, p, p.delay + p.life * i / 200) for i in range(201)]
        assert min(s.position[1] for s in heights if s is not None) >= -1e-9  # never below the floor
        rest_age, rest_at, _ = p.hits[-1]
        late = state(effect, p, p.delay + (rest_age + p.life) / 2)
        assert late is not None and late.position.tolist() == pytest.approx(list(rest_at))
        assert late.rotation.tolist() == state(effect, p, p.delay + p.life).rotation.tolist()  # type: ignore[union-attr]  # no more spin
        for (age, _, before), (_, _, after) in zip(p.hits, p.hits[1:], strict=False):
            assert abs(after[1]) <= abs(before[1]) + 1e-9 or after == (0.0, 0.0, 0.0)  # each bounce is lower
    data = to_json(effect, {})
    assert data["floor"] == 0 and "floor hits" in data["motion"] and data["emitters"][0]["bounce"] == 0.3
    assert data["particles"][0]["hits"][0][0] == particles(effect)[0].hits[0][0]


def test_no_floor_no_hits_and_bad_fields() -> None:
    errors: list[str] = []
    plain = parse({"emit": [{"model": "chip", "burst": 2, "gravity": 9.8}]}, lambda m, w: errors.append(m))
    assert plain is not None and all(p.hits == () for p in particles(plain))
    assert "hits" not in to_json(plain, {})["particles"][0] and "floor" not in to_json(plain, {})
    for bad in ({"bounce": 2}, {"friction": -1}, {"settle": "yes"}):
        errors = []
        assert parse({"floor": 0, "emit": [{"model": "chip", **bad}]}, lambda m, w: errors.append(m)) is None and errors
    errors = []
    assert parse({"floor": "ground", "emit": [{"model": "chip"}]}, lambda m, w: errors.append(m)) is None and errors


def test_dead_stop_and_no_settle() -> None:
    dead = _effect(bounce=0)
    assert all(len(p.hits) == 1 for p in particles(dead))  # bounce 0: rests where it lands
    lively = _effect(settle=False, bounce=0.6)
    assert any(len(p.hits) > len(q.hits) for p, q in zip(particles(lively), particles(_effect(bounce=0.6)), strict=True))
    assert SETTLE_SPEED > 0
