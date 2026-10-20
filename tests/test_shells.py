"""Shells, fitted shells and penetration (CC0 parity M3)."""

from __future__ import annotations

import numpy as np

from conftest import built_of, errors_of, ok_model
from kiln.builder import field_of
from kiln.lint import geometry_warnings, penetrations
from kiln.project import Project

GREAT_HELM = """\
name: thing
class: character
parts:
  - capsule: { from: [0, 0.25, 0], to: [0, 0.8, 0], radius: 0.25 }
    color: red
  - sphere: { at: [0, 1.18, 0], radius: 0.22 }
    id: head
    color: white
    blend: 0.05
  - sphere: { at: [0.1, 1.24, 0.27], radius: 0.07 }
    id: head
    mirror: x
    color: black
  - cylinder: { at: [0, 0.99, 0], radius: 0.33, height: 0.92 }
    id: helm
    color: grey
    shell: { thickness: 0.03, open: -y }
  - box: { at: [0, 1.24, 0.3], size: [0.4, 0.04, 0.2] }
    cut: true
rig:
  head: { pivot: [0, 0.95, 0] }
  helm: { parent: head }
skin: rigid
lint: { disable: [W103] }
"""


def test_eyes_through_a_visor_are_flagged_until_moved_inside(project: Project) -> None:
    built = built_of(project, GREAT_HELM)
    found = [f for f in geometry_warnings(built, {}, project) if f.rule == "W113"]
    assert len(found) == 1 and "part 2 (sphere, black)" in found[0].message and "part 3" in found[0].message
    inside = GREAT_HELM.replace("at: [0.1, 1.24, 0.27], radius: 0.07", "at: [0.08, 1.22, 0.2], radius: 0.04")
    assert not penetrations(built_of(project, inside))


def test_open_shell_shows_a_rim_of_its_thickness(project: Project) -> None:
    text = "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: grey\n    shell: { thickness: 0.04, open: -y }\n"
    built = built_of(project, text)
    v = built.painted.vertices[np.unique(built.painted.faces)]
    rim = v[np.abs(v[:, 1] - 0.3) < 0.005]  # the cut through the centre
    r = np.linalg.norm(rim[:, [0, 2]], axis=1)
    assert r.max() > 0.29 and r.min() < 0.27  # outer surface at 0.3, inner at 0.26: a visible wall
    assert v[:, 1].min() > 0.29  # nothing below the open side


def test_fitted_helmet_wraps_the_head(project: Project) -> None:
    text = """\
name: thing
class: character
parts:
  - ellipsoid: { at: [0, 1.2, 0], radii: [0.2, 0.25, 0.22] }
    id: head
    color: white
  - sphere: { at: [0, 1.05, 0], radius: 0.5 }
    id: helmet
    color: grey
    shell: { thickness: 0.03, open: -y }
    fit: { to: head, gap: 0.01 }
rig:
  helmet: { separate: true }
skin: soft
lint: { disable: [W106] }
"""
    model, _ = ok_model(project, text)
    built = built_of(project, text)
    p = built.painted
    helmet = np.array([p.groups[g].bone == "helmet" for g in p.face_group])
    pts = p.vertices[np.unique(p.faces[helmet])]
    head = field_of(model, built.step).part_distance(0, pts)
    # every helmet point lies in the wall: between the gap and the gap plus the thickness from the head
    assert head.min() > 0.01 - 2 * built.step and head.max() < 0.04 + 2 * built.step
    assert pts[:, 1].min() < 1.1  # it comes down the sides of the head (to its own shape's open side)


def test_fit_needs_a_shell_and_a_target(project: Project) -> None:
    base = "name: thing\nparts:\n  - sphere: { radius: 0.3 }\n    id: head\n    color: red\n  - sphere: { radius: 0.4 }\n    color: grey\n{extra}"
    assert any("fit wraps a shell" in f.message for f in errors_of(project, base.replace("{extra}", "    fit: head\n")))
    no_target = base.replace("{extra}", "    shell: { thickness: 0.02 }\n    fit: hat\n")
    assert any("no other part has id 'hat'" in f.message for f in errors_of(project, no_target))
