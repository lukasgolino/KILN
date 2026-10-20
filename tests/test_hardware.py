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
