"""#305: `transforms:` turn and move a group of parts (a hunched posture) without retyping them."""

from __future__ import annotations

import numpy as np
from conftest import built_of, errors_of, ok_model

from kiln.project import Project

BASE = """\
name: thing
parts:
  - capsule: {{ from: [0, 0.3, 0], to: [0, 0.9, 0], radius: 0.15 }}
    id: chest
    color: red
  - sphere: {{ at: [0, 1.1, 0], radius: 0.12 }}
    id: head
    color: blue
    blend: 0.03
rig:
  head: {{ pivot: [0, 1.0, 0] }}
{extra}"""


def test_a_group_turns_about_its_pivot(project: Project) -> None:
    model, _ = ok_model(project, BASE.format(extra="transforms:\n  - { ids: [head], rotate: [30, 0, 0], pivot: [0, 0.9, 0] }\n"))
    head = next(p for p in model.parts if p.id == "head").geometry
    a = np.radians(30)
    assert np.allclose(head.at, [0, 0.9 + 0.2 * np.cos(a), 0.2 * np.sin(a)])  # turned forward about the neck
    pivot = model.rig["head"].pivot
    assert pivot is not None and np.allclose(pivot, [0, 0.9 + 0.1 * np.cos(a), 0.1 * np.sin(a)])
    built = built_of(project, BASE.format(extra="transforms:\n  - { ids: [head], rotate: [30, 0, 0], pivot: [0, 0.9, 0] }\n"))
    top = built.painted.vertices[built.painted.vertices[:, 1] > 1.05]
    assert top[:, 2].mean() > 0.05  # the head leans forward in the mesh


def test_transforms_are_checked(project: Project) -> None:
    mirrored = BASE.replace("    color: blue\n", "    color: blue\n    mirror: x\n").replace("at: [0, 1.1, 0]", "at: [0.1, 1.1, 0]")
    bad = [(mirrored, "transforms:\n  - { ids: [head], rotate: [0, 30, 0] }\n", "transforms[0]"),
           (BASE, "transforms:\n  - { ids: [nope], rotate: [10, 0, 0] }\n", "transforms[0].ids"),
           (BASE, "transforms:\n  - { ids: [head], spin: 3 }\n", "transforms[0]")]  # fmt: skip
    for text, extra, where in bad:
        assert any(f.where == where for f in errors_of(project, text.format(extra=extra))), extra
    assert not errors_of(project, mirrored.format(extra="transforms:\n  - { ids: [head], rotate: [20, 0, 0], pivot: [0, 0.9, 0] }\n"))
