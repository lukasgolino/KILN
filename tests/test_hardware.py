"""Detail that survives every LOD, and hardware parts (CC0 parity M8)."""

from __future__ import annotations

import numpy as np
from conftest import errors_of, ok_model

from kiln.builder import build_model, kept_parts
from kiln.mesher import open_edges
from kiln.project import Project

BARREL = """\
name: thing
class: prop
lod: [600, 250]
parts:
  - lathe: { profile: [[0, 0], [0.26, 0], [0.32, 0.35], [0.26, 0.7], [0, 0.7]] }
    id: body
    color: wood
  - band: { fit: body, at: [0, 0.12, 0], width: 0.05, thickness: 0.012 }
    color: grey
  - band: { fit: body, at: [0, 0.58, 0], width: 0.05, thickness: 0.012 }
    color: grey
  - rivets: { count: 8, around: { center: [0, 0.12, 0], radius: 0.29, axis: y }, size: 0.025 }
    color: black
"""


def colours(built: object) -> dict[str, int]:
    p = built.painted  # type: ignore[attr-defined]
    out: dict[str, int] = {}
    for g in p.face_group:
        name = p.groups[g].color_name.split("#")[0]
        out[name] = out.get(name, 0) + 1
    return out


def test_barrel_keeps_bands_and_rivets_at_every_lod(project: Project) -> None:
    model, style = ok_model(project, BARREL)
    assert len(model.parts) == 1 + 2 + 8
    palette, _ = project.palette(None)
    for budget in (None, 600, 250):
        built = build_model(model, style, budget, palette)
        c = colours(built)
        assert c.get("grey", 0) >= 2 * 8 and c.get("black", 0) >= 8 * 8, (budget, c)  # 2 bands, 8 rivets
        assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0
        assert not built.lost


def test_band_fits_around_the_part(project: Project) -> None:
    model, _ = ok_model(project, BARREL)
    band = model.parts[1].geometry
    # the profile's radius at y = 0.12 is 0.26 + 0.06 * 0.12 / 0.35 (straight sides), widest over the band's width
    r = 0.26 + 0.06 * 0.145 / 0.35
    assert band.params["radius"] - 0.012 == np.float64(band.params["radius"] - 0.012)
    assert abs(band.params["radius"] - 0.012 - r) < 0.006


def test_planks_are_separate_with_gaps(project: Project) -> None:
    text = """\
name: thing
parts:
  - planks: { at: [0, 1, 0], size: [1.0, 2.0, 0.08], count: 5, gap: 0.02, axis: x }
    color: wood
"""
    model, style = ok_model(project, text)
    assert len(model.parts) == 5
    xs = sorted(float(p.geometry.at[0]) for p in model.parts)
    width = (1.0 - 4 * 0.02) / 5
    assert np.allclose(np.diff(xs), width + 0.02)
    assert all(p.geometry.params["size"][0] == width for p in model.parts)
    built = build_model(model, style, palette=project.palette(None)[0])
    assert built.pieces == 5  # five planks, gaps between them


def test_bolt_and_slit(project: Project) -> None:
    text = """\
name: thing
parts:
  - box: { at: [0, 0.5, 0], size: [1, 1, 0.1] }
    color: wood
  - bolt: { at: [0.3, 0.5, 0.06], radius: 0.03, length: 0.03, rotate: [90, 0, 0] }
    color: grey
  - slit: { at: [0, 0.8, 0], size: [0.3, 0.04, 0.3] }
"""
    model, _ = ok_model(project, text)
    assert model.parts[1].geometry.params["sides"] == 6 and model.parts[1].hard is True
    assert model.parts[2].geometry.op == "cut"


def test_hardware_errors(project: Project) -> None:
    base = "name: thing\nparts:\n  - sphere: { radius: 0.3 }\n    id: body\n    color: red\n  - {hw}\n    color: grey\n"
    for hw, message in (("rivets: { count: 4, size: 0.02 }", "rivets:"), ("band: { at: [0, 0, 0], width: 0.05, fit: hoop }", "no earlier part"),
                        ("planks: { size: [0.1, 1, 0.05], count: 9, gap: 0.02 }", "don't fit"), ("bolt: { radius: 0.02 }", "bolt:")):
        assert any(message in f.message for f in errors_of(project, base.replace("{hw}", hw))), hw


def test_small_crisp_details_are_kept(project: Project) -> None:
    text = """\
name: thing
class: prop
parts:
  - sphere: { at: [0, 0.5, 0], radius: 0.5 }
    color: white
  - sphere: { at: [0.15, 0.6, 0.49], radius: 0.008 }
    color: black
  - sphere: { at: [-0.15, 0.6, 0.47], radius: 0.05 }
    color: red
    keep: true
  - sphere: { at: [0, 0.3, 0.47], radius: 0.012 }
    color: grey
    keep: false
"""
    model, style = ok_model(project, text)
    assert kept_parts(model, frozenset()) == {1, 2}
    built = build_model(model, style, 60, project.palette(None)[0])  # a tiny LOD
    c = colours(built)
    assert c.get("black", 0) >= 24 and c.get("red", 0) >= 24


def test_flat_faces_take_few_triangles(project: Project) -> None:
    """Quadric decimation is plane-aware: flat regions end up as few big triangles before curves lose detail."""
    text = "name: thing\nbudget: 400\nparts:\n  - box: { at: [0, 0.5, 0], size: [1, 1, 1], round: 0.1 }\n    color: wood\n"
    model, style = ok_model(project, text)
    built = build_model(model, style, palette=project.palette(None)[0])
    v, f = built.painted.vertices, built.painted.faces
    n = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    area = np.linalg.norm(n, axis=1)
    flat = np.abs(n / area[:, None]).max(axis=1) > 0.999
    assert area[flat].sum() / area.sum() > 0.6 and flat.sum() < 0.3 * len(f)


HAND = """\
name: thing
parts:
  - sphere: { at: [0, 1, 0], radius: 0.2 }
    color: wood
  - hand: { at: [0.3, 0.8, 0], length: 0.2, fingers: 4, nail: 0.02, nail_color: black }
    color: wood
    mirror: x
"""


def test_hand_expands_to_soft_parts_and_mirrors(project: Project) -> None:
    model, style = ok_model(project, HAND)
    # sphere + palm, 4 fingers, thumb, 5 nails (each mirrored)
    assert len(model.parts) == 1 + 1 + 4 + 1 + 5
    assert all(not p.hard for p in model.parts[1:])
    built = build_model(model, style, palette=project.palette(None)[0])
    xs = built.painted.vertices[:, 0]
    assert float(xs.min()) < -0.3 and float(xs.max()) > 0.3  # both hands
    assert colours(built).get("black", 0) > 0  # the nails keep their own colour


def test_fingers_hang_down_from_the_wrist(project: Project) -> None:
    model, _ = ok_model(project, HAND.replace("    mirror: x\n", ""))
    tubes = [p for p in model.parts if p.geometry.shape == "tube"]
    assert len(tubes) == 5
    for t in tubes:
        pts = np.asarray(t.geometry.params["points"], float)
        assert pts[-1][1] < 0.8 - 0.05  # below the wrist


def test_foot_stands_on_its_at(project: Project) -> None:
    text = "name: thing\nparts:\n  - foot: { at: [0, 0, 0], length: 0.26, toes: 5 }\n    color: wood\n"
    model, style = ok_model(project, text)
    assert len(model.parts) == 1 + 5 + 1  # sole, toes, heel
    built = build_model(model, style, palette=project.palette(None)[0])
    v = built.painted.vertices
    assert abs(float(v[:, 1].min())) < 0.02  # the sole on the ground
    assert float(v[:, 2].max()) > 0.12  # toes point +z


def test_hand_and_foot_errors(project: Project) -> None:
    base = "name: thing\nparts:\n  - {hw}\n    color: wood\n"
    for hw in ("hand: { fingers: 9 }", "hand: { toes: 3 }", "foot: { length: -1 }", "foot: { spread: 90 }", "hand: { thumb: 2 }"):
        errs = errors_of(project, base.replace("{hw}", hw))
        assert any("E003" in f.format() for f in errs), (hw, [f.format() for f in errs])


EYE = """\
name: thing
parts:
  - sphere: { at: [0, 0.5, 0], radius: 0.25 }
    id: head
    color: white
  - eye: { at: [0.09, 0.56, 0.217], facing: [0.36, 0.24, 0.9], radius: 0.05, rim: 0.2, rim_color: red, in: head }
    color: black
    mirror: x
"""


def test_eye_is_a_socket_a_sunk_ball_and_a_flush_rim(project: Project) -> None:
    model, style = ok_model(project, EYE)
    socket, ball, rim = model.parts[1:]
    assert socket.geometry.op == "cut" and ball.crisp and rim.geometry.shape == "torus"
    built = build_model(model, style, palette=project.palette(None)[0])
    c = colours(built)
    assert c.get("black", 0) > 20 and c.get("red", 0) > 10
    v = built.painted.vertices
    r = np.linalg.norm(v - np.array([0.0, 0.5, 0.0]), axis=1)
    assert float(r.max()) < 0.25 + 0.006  # nothing proud of the face


def test_eye_errors(project: Project) -> None:
    base = "name: thing\nparts:\n  - sphere: { radius: 0.3 }\n    color: white\n  - {hw}\n    color: black\n"
    for hw in ("eye: { radius: 0.03 }", "eye: { at: [0, 0, 0.3], facing: [0, 0, 0] }", "eye: { at: [0, 0, 0.3], rim: 2 }", "eye: { at: [0, 0, 0.3], iris: 1 }"):
        errs = errors_of(project, base.replace("{hw}", hw))
        assert any("E003" in f.format() for f in errs), (hw, [f.format() for f in errs])


def test_a_belt_hugs_hips_and_belly(project: Project) -> None:
    """#316: band fit round a surface that isn't round (hips and a belly in front) hugs it as a fitted shell, not a
    cylinder sized to the farthest point (a flange at the back); a barrel keeps its exact iron band."""
    text = """\
name: thing
parts:
  - ellipsoid: { at: [0, 0.5, 0], radii: [0.2, 0.25, 0.14] }
    id: hips
    color: wood
  - sphere: { at: [0, 0.55, 0.08], radius: 0.13 }
    id: belly
    color: wood
  - band: { fit: [hips, belly], at: [0, 0.55, 0], width: 0.05, thickness: 0.012 }
    color: black
"""
    model, style = ok_model(project, text)
    belt = model.parts[2]
    assert belt.geometry.fit is not None and belt.geometry.shell == 0.012 and not belt.hard
    built = build_model(model, style, palette=project.palette(None)[0])
    p = built.painted
    black = np.isin(p.face_group, [g for g, grp in enumerate(p.groups) if grp.color == "#141414"])
    v = p.vertices[np.unique(p.faces[black])]
    assert float(v[:, 2].min()) > -0.14 - 0.012 - 0.02  # no flange at the back
    model, _ = ok_model(project, BARREL)
    assert model.parts[1].geometry.shape == "cylinder" and model.parts[1].hard
