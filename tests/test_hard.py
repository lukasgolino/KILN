"""Hard surface (CC0 parity M2): exact polygons, sides, bevels and chamfers, exact CSG, crisp creases."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from conftest import built_of, closed_faces, errors_of, ok_model, signed_volume
from kiln.builder import build_model, hard_parts
from kiln.export import to_glb
from kiln.hard import HardSpec, bevelled, intersect, solid, subtract, to_mesh, union
from kiln.hard import _planes_box, _simple_loops
from kiln.lint import geometry_warnings
from kiln.mesher import open_edges, pinches
from kiln.project import Project, load_project
from kiln.sdf import Geometry, cylinder

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"


def mesh_of(shape: str, params: dict[str, object], spec: HardSpec = HardSpec(), at: tuple[float, float, float] = (0, 0, 0)) -> tuple:  # type: ignore[type-arg]
    m = to_mesh(solid(Geometry(shape, dict(params), at=np.array(at, float)), spec, 0))
    return m, len(set(m.face_polygon.tolist()))


def test_chamfered_box_has_26_faces() -> None:
    assert len(bevelled(*_planes_box([1, 1, 1]), 0.1, 1)) == 26
    m, polygons = mesh_of("box", {"size": [1, 1, 1], "round": 0.0}, HardSpec(12, 0.1, 1))
    assert polygons == 26 and closed_faces(m.faces)


def test_eight_sided_cylinder_is_eight_quads_and_two_caps() -> None:
    m, polygons = mesh_of("cylinder", {"radius": 0.5, "height": 1.0, "sides": 8, "round": 0.0})
    assert polygons == 10
    assert m.triangles == 8 * 2 + 2 * 6
    # corners on the radius: the octagon's area
    assert signed_volume(m.vertices, m.faces) == pytest.approx(0.5 * 8 * 0.25 * np.sin(np.pi / 4), rel=1e-7)


@pytest.mark.parametrize("shape,params", [
    ("sphere", {"radius": 0.5, "sides": 10}), ("ellipsoid", {"radii": [0.3, 0.5, 0.2]}), ("torus", {"radius": 0.5, "thickness": 0.1}),
    ("lathe", {"profile": [[0, 0], [0.3, 0], [0.4, 0.5], [0.2, 1], [0, 1]]}), ("wedge", {"size": [1, 0.5, 1]}),
    ("extrude", {"points": [[0, 0], [1, 0], [1, 1], [0.5, 0.4], [0, 1]], "height": 0.2, "round": 0.0}),
    ("capsule", {"from": [0, 0, 0], "to": [0, 1, 0.3], "radius": 0.2, "radius_to": 0.1}),
    ("cone", {"radius": 0.5, "radius_top": 0.0, "height": 1.0, "sides": 4}),
])  # fmt: skip
def test_every_hard_shape_is_closed_and_outward(shape: str, params: dict[str, object]) -> None:
    m, _ = mesh_of(shape, params)
    assert closed_faces(m.faces) and signed_volume(m.vertices, m.faces) > 0


def test_csg_is_exact_and_watertight() -> None:
    box = solid(Geometry("box", {"size": [1, 1, 1], "round": 0.0}), HardSpec(), 0)
    other = solid(Geometry("box", {"size": [1, 1, 1], "round": 0.0}, at=np.array([0.5, 0.5, 0.5])), HardSpec(), 1)
    for op, volume in ((union, 1.875), (subtract, 0.875), (intersect, 0.125)):
        m = to_mesh(op(box, other))
        assert closed_faces(m.faces)
        assert signed_volume(m.vertices, m.faces) == pytest.approx(volume, abs=1e-9)
        assert set(m.face_part.tolist()) == {0, 1}  # every face knows its part
    # coplanar fragments are merged again: a union of two boxes is few triangles
    assert to_mesh(union(box, other)).triangles <= 40


def test_crease_is_kept_at_a_csg_seam(project: Project) -> None:
    text = """\
name: thing
parts:
  - box: { at: [0, 0.25, 0], size: [1, 0.5, 1] }
    color: red
    blend: none
  - box: { at: [0, 0.75, 0], size: [0.4, 0.5, 0.4] }
    color: red
    blend: none
"""
    built = built_of(project, text)
    p = built.painted
    assert closed_faces(np.unique(np.round(p.vertices, 9), axis=0, return_inverse=True)[1].reshape(-1)[p.faces])
    # every corner normal is its face's own (all edges here are 90 degrees: crisp)
    face_n = np.cross(p.vertices[p.faces[:, 1]] - p.vertices[p.faces[:, 0]], p.vertices[p.faces[:, 2]] - p.vertices[p.faces[:, 0]])
    face_n /= np.linalg.norm(face_n, axis=1, keepdims=True)
    assert np.allclose(built.normals, face_n[:, None, :], atol=1e-6)


def test_hard_parts_follow_the_style(project: Project) -> None:
    text = """\
name: thing
parts:
  - box: { at: [0, 0.25, 0], size: [1, 0.5, 1] }
    color: red
  - cylinder: { at: [0, 0.7, 0], radius: 0.2, height: 0.4, sides: 6 }
    color: blue
  - sphere: { at: [0, 1, 0], radius: 0.1 }
    color: red
    noise: { amount: 0.01 }
"""
    model, style = ok_model(project, text)
    assert hard_parts(model, style) == {1}  # auto: only the part asking (sides)
    always = project.style("low_poly")[0]
    assert always is not None and always.hard_surface == "always"
    assert hard_parts(model, always) == {0, 1}  # noise needs the smooth field


def test_hard_and_smooth_parts_mix(project: Project) -> None:
    text = """\
name: thing
parts:
  - sphere: { at: [0, 0.4, 0], radius: 0.4 }
    color: red
  - cylinder: { at: [0, 0.4, 0], radius: 0.15, height: 1.0, sides: 6 }
    color: blue
  - box: { at: [0, 0.4, 0.35], size: [0.2, 0.2, 0.2] }
    cut: true
"""
    built = built_of(project, text)
    assert {g.color_name for g in built.painted.groups} == {"red", "blue"}
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0
    assert built.pieces == 1


def test_demo_trebuchet_hard_is_kenney_sized() -> None:
    project = load_project(DEMO)
    model, _, findings = project.load(DEMO / "models" / "trebuchet.kiln.yaml")
    low_poly = project.style("low_poly")[0]
    assert model is not None and low_poly is not None
    palette, _ = project.palette(model.palette)
    built = build_model(model, low_poly, palette=palette)
    assert built.triangles <= 2000  # Kenney's trebuchet: 1518
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0
    assert {"wood", "wood_dark", "iron"} <= {g.color_name for g in built.painted.groups}
    # byte-identical rebuilds
    again = build_model(model, low_poly, palette=palette)
    assert to_glb(built, "test") == to_glb(again, "test")


def test_sides_shape_the_smooth_field_too() -> None:
    p = {"radius": 1.0, "height": 1.0, "round": 0.0, "sides": 8}
    corner = np.array([[np.sin(np.pi / 8), 0.0, np.cos(np.pi / 8)]])  # a corner direction: on the radius
    side = np.array([[0.0, 0.0, np.cos(np.pi / 8)]])  # the middle of the front side
    assert abs(cylinder(corner, p)[0]) < 1e-9 and abs(cylinder(side, p)[0]) < 1e-9


def test_hard_notation_errors(project: Project) -> None:
    base = "name: thing\nparts:\n  - {shape}\n    color: red\n{extra}"
    cases = [
        ("sphere: { radius: 0.3 }", "    bevel: 0.02\n", "bevel and chamfer work on"),
        ("box: { size: [1, 1, 1] }", "    bevel: 0.02\n    chamfer: 0.02\n", "not both"),
        ("box: { size: [1, 1, 1] }", "    chamfer: 0.6\n", "less than half"),
        ("cylinder: { radius: 0.3, height: 1, sides: 2 }", "", "sides"),
        ("box: { size: [1, 1, 1] }", "    hard: true\n    noise: { amount: 0.01 }\n", "can't twist or have noise"),
        ("box: { size: [1, 1, 1] }", "    segments: 9\n", "segments"),
    ]
    for shape, extra, message in cases:
        found = errors_of(project, base.format(shape=shape, extra=extra))
        assert any(message in f.message for f in found), (shape, extra, [f.message for f in found])


def test_hard_shell_with_an_open_side(project: Project) -> None:
    text = """\
name: thing
parts:
  - sphere: { at: [0, 0.3, 0], radius: 0.3, sides: 12 }
    shell: { thickness: 0.03, open: -y }
    color: grey
    hard: true
"""
    built = built_of(project, text)
    p = built.painted
    assert len(open_edges(p.vertices, p.faces)) == 0
    # a bowl: nothing below its centre, and the rim (inside wall) is there
    assert p.vertices[:, 1].min() == pytest.approx(0.3, abs=1e-9)
    radii = np.linalg.norm(p.vertices - [0, 0.3, 0], axis=1)
    assert 0.25 < radii.min() < 0.28


def test_planar_merge_survives_an_outline_that_does_not_close() -> None:
    # LOOSE #45: a patch with a back-to-back sliver pair (from a rotated 4-sided cone on an aimed blade) left an open
    # outline chain; looking up its end crashed lint with a KeyError
    from kiln.hard import _outline_points, _retriangulate

    tris = [[3, 1, 0], [3, 0, 1], [3, 0, 2]]
    v = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.3, 0.0, 0.3]]
    normal = np.array([0.0, 1.0, 0.0])
    assert _outline_points(tris, v, normal) == (set(), {0, 1, 2, 3})
    assert _retriangulate(tris, v, normal, set()) is None  # left as it is


def test_hard_lathe_shell_opens_its_end(project: Project) -> None:
    # LOOSE #44: a hollow lathe helmet (profile anywhere on the axis) came out shattered: lathes weren't shell shapes,
    # and `open: -y` cut at local y = 0 instead of the profile's bottom
    text = """\
name: thing
parts:
  - lathe: { profile: [[0, 1.94], [0.065, 1.935], [0.12, 1.895], [0.14, 1.83], [0.142, 1.765], [0, 1.765]], sides: 12 }
    shell: { thickness: 0.012, open: -y }
    color: grey
    hard: true
"""
    built = built_of(project, text)
    p = built.painted
    assert len(open_edges(p.vertices, p.faces)) == 0
    assert p.vertices[:, 1].min() == pytest.approx(1.765 + 0.012, abs=1e-6)  # only the end wall is gone
    inner = np.hypot(p.vertices[:, 0], p.vertices[:, 2])[np.abs(p.vertices[:, 1] - 1.777) < 1e-6]
    assert inner.min() == pytest.approx(0.142 - 0.012, abs=0.005)  # the rim: an inside wall at the open end
    palette, _ = project.palette(built.model.palette)
    assert not [f for f in geometry_warnings(built, palette, project) if f.rule == "W102"]  # exact polygons: no resolution


def test_union_of_near_coplanar_facets_stays_closed() -> None:
    # #2: a faceted skull, a jaw box and faceted hair cracked open (8 open edges at the back of the head): each
    # union's BSP trees were built from only the polygons near the other solid, which classify points wrongly
    from kiln.hard import to_mesh as mesh

    parts = [Geometry("ellipsoid", {"radii": (0.088, 0.108, 0.102), "sides": 8}, at=np.array([0, 1.73, -0.008])),
             Geometry("box", {"size": (0.142, 0.1, 0.15), "round": 0.0}, at=np.array([0, 1.625, 0.02])),
             Geometry("ellipsoid", {"radii": (0.092, 0.09, 0.098), "sides": 8}, at=np.array([0, 1.76, -0.025]))]  # fmt: skip
    acc: list = []  # type: ignore[type-arg]
    for k, g in enumerate(parts):
        acc = union(acc, solid(g, HardSpec(8, 0.0, 1), k))
    m = mesh(acc)
    assert len(open_edges(m.vertices, m.faces)) == 0 and closed_faces(m.faces)
    cut = subtract(acc, solid(Geometry("box", {"size": (0.3, 0.05, 0.3), "round": 0.0}, at=np.array([0, 1.76, -0.025])), HardSpec(), 9))
    m = mesh(cut)
    assert len(open_edges(m.vertices, m.faces)) == 0
    kept = intersect(acc, solid(Geometry("sphere", {"radius": 0.1, "sides": 8}, at=np.array([0, 1.7, 0])), HardSpec(8, 0.0, 1), 9))
    m = mesh(kept)
    assert len(open_edges(m.vertices, m.faces)) == 0 and len(m.faces)


def test_bands_on_a_hard_lathe_cost_only_their_cuts(project: Project) -> None:
    # #12: three bands on a stepped hard lathe came out at ~30x the budget: they were cut the soft way (refined first)
    text = """\
name: thing
budget: 600
parts:
  - lathe: { profile: [[0, 0], [0.3, 0], [0.3, 0.2], [0.25, 0.2], [0.25, 0.5], [0.28, 0.5], [0.28, 0.6], [0.2, 0.6], [0.2, 0.9], [0, 0.9]], sides: 10, smooth: false }
    hard: true
    color: grey
    pattern:
      - { type: band, color: red, size: 0.2, at: 0.1, axis: y }
      - { type: band, color: blue, size: 0.1, at: 0.55, axis: y }
      - { type: band, color: white, size: 0.3, at: 0.75, axis: y }
"""
    for extra, limit in (("", 200), ("      - { type: stripes, color: black, size: 0.1, width: 0.5, axis: x }\n", 2000)):
        p = built_of(project, text + extra).painted
        assert len(p.faces) < limit and len(open_edges(p.vertices, p.faces)) == 0
        v = p.vertices[p.faces]
        assert (np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1) > 1e-10).all()  # no slivers
        c = v.mean(axis=1)
        colour = np.array([p.groups[g].color_name.split("#")[0] for g in p.face_group])
        if not extra:  # the bands sit on the profile's steps: the top cap is in the last one
            assert set(colour[c[:, 1] < 0.2]) == {"red"} and set(colour[(c[:, 1] > 0.5) & (c[:, 1] < 0.6)]) == {"blue"}
            assert set(colour[c[:, 1] > 0.6]) == {"white"} and set(colour[(c[:, 1] > 0.21) & (c[:, 1] < 0.49)]) == {"grey"}
        else:  # stripes across x over everything, cut along their planes
            on = np.cos(2 * np.pi * c[:, 0] / 0.1) - np.cos(np.pi * 0.5) > 1e-6
            assert on.any() and set(colour[on]) == {"black"} and "black" not in set(colour[~on])


@pytest.mark.parametrize("edge", ["bevel: 0.02", "chamfer: 0.02", "chamfer: 0.02\n    offset_shrink: true"])
def test_bevel_on_a_thin_outline_stays_closed(project: Project, edge: str) -> None:
    """#28: a bevel wider than half of a thin section (a font serif) is clamped there instead of cracking (E013)."""
    from kiln.hard import inset_limits

    outline = "[[0, 0], [0.4, 0], [0.4, 0.015], [0.3, 0.015], [0.3, 0.6], [0.1, 0.6], [0.1, 0.015], [0, 0.015]]"
    offset = ", offset: -0.04" if "offset_shrink" in edge else ""
    text = f"name: thing\nclass: prop\nparts:\n  - extrude: {{ points: {outline}, height: 0.3{offset} }}\n    color: \"#aa3322\"\n    {edge.split(chr(10))[0]}\n"
    built = built_of(project, text)
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0
    limits = inset_limits([(0, 0), (0.4, 0), (0.4, 0.015), (0.3, 0.015), (0.3, 0.6), (0.1, 0.6), (0.1, 0.015), (0, 0.015)])
    assert max(limits[:4]) < 0.0075 < min(limits[4:6])  # the 15 mm foot limits its corners; the stem doesn't
    square = inset_limits([(0, 0), (1, 0), (1, 1), (0, 1)])
    assert min(square) > 0.3  # ordinary shapes never clamp a normal bevel


@pytest.mark.parametrize("bevel", [0.02, 0.03, 0.04])
def test_bevel_wider_than_a_bar_stays_closed(project: Project, bevel: float) -> None:
    """#66: an H whose 50 mm bar takes a bevel of half its width or more: the bar's two sides met (each vertex's own
    limit only looks along its bisector, into the stems), the cap couldn't be triangulated (E013)."""
    from kiln.hard import _folds, _offset_outline, _unfolded, inset_limits

    outline: list[list[float]] = [[0, 0], [0.1, 0], [0.1, 0.3], [0.4, 0.3], [0.4, 0], [0.5, 0], [0.5, 0.7], [0.4, 0.7], [0.4, 0.35], [0.1, 0.35], [0.1, 0.7], [0, 0.7]]
    text = f"name: thing\nclass: prop\nparts:\n  - extrude: {{ points: {outline}, height: 0.2 }}\n    color: \"#aa3322\"\n    bevel: {bevel}\n"
    built = built_of(project, text)
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0 and built.pieces == 1
    uv = [(float(z), float(x)) for x, z in outline]
    uv = uv[::-1] if sum(uv[i - 1][0] * uv[i][1] - uv[i][0] * uv[i - 1][1] for i in range(len(uv))) < 0 else uv
    wanted = [min(bevel, lim) for lim in inset_limits(uv)]
    each = _unfolded(uv, wanted)
    assert not _folds(uv, _offset_outline(uv, each))
    lowered = {(x, z) for (z, x), w, e in zip(uv, wanted, each, strict=True) if e < w}
    assert bool(lowered) == (bevel > 0.025)  # only a bevel past half the bar folds
    assert all(0.1 <= x <= 0.4 for x, _ in lowered)  # the bar and the stems' sides facing it, not the outside
    square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    assert _unfolded(square, [0.1] * 4) == [0.1] * 4  # outlines that don't fold keep their insets


# Cinzel Black's L (OFL; overlaps removed), as the outline: the shape whose union with crossing straps cracked in 0.7.1
SERIF_L = [[0.46715, -0.33144], [0.41287, 0.0], [-0.42287, 0.0], [-0.42287, -0.01429], [-0.40429, -0.01429], [-0.36983, -0.02089], [-0.34072, -0.04072], [-0.32054, -0.06982], [-0.31286, -0.10429], [-0.31286, -0.89573], [-0.32054, -0.9302], [-0.34072, -0.9593], [-0.36983, -0.97913], [-0.40429, -0.98573], [-0.42287, -0.98573], [-0.42287, -1.00002], [0.09, -1.00002], [0.09, -0.98573], [0.07143, -0.98573], [0.03697, -0.97913], [0.00786, -0.9593], [-0.01232, -0.9302], [-0.02, -0.89573], [-0.02, -0.07286], [0.15572, -0.07286], [0.2004, -0.07627], [0.24302, -0.08651], [0.28358, -0.10357], [0.33911, -0.14107], [0.38715, -0.19215], [0.41414, -0.23334], [0.43604, -0.27977], [0.45287, -0.33144]]


@pytest.mark.parametrize("extra", ["", "bevel", "straps"])
def test_serif_letter_with_crossing_hard_straps_stays_closed(project: Project, extra: str) -> None:
    """#30 (fixed by 0.8.0's whole-solid BSP trees, #2): a hard serif letter unioned with hard boxes crossing it,
    bevelled and chamfered, with a second strap and a cut biting into its side, is closed and one piece."""
    letter_edge = "\n    bevel: 0.0065\n    segments: 2" if extra else ""
    box_edge = "\n    chamfer: 0.01" if extra else ""
    text = f"""name: thing
class: prop
parts:
  - extrude: {{ points: {SERIF_L}, height: 0.34, at: [-0.0221, 0, -0.17], rotate: [90, 0, 0] }}
    color: "#2e2f33"
    hard: true{letter_edge}
  - box: {{ at: [-0.1886, 0.8, 0], size: [0.3169, 0.07, 0.49] }}
    color: "#1d1d20"
    hard: true{box_edge}
"""
    if extra == "straps":
        text += """  - box: { at: [-0.25, 0.6, 0], size: [0.07, 0.6, 0.49] }
    color: "#1d1d20"
    hard: true
    chamfer: 0.01
  - box: { at: [-0.335, 0.6531, 0.22], size: [0.0753, 0.0449, 0.088], rotate: [9.0956, 11.5489, 103.1887] }
    cut: true
"""
    built = built_of(project, text)
    assert len(open_edges(built.painted.vertices, built.painted.faces)) == 0
    assert built.pieces == 1


# #60: points the CSG leaves a hair (1e-10 m) off an edge two flat patches share were corners on both sides, so each
# patch cut the same zero-area ear: two faces back to back on a chord (an edge with four faces, E013)
SLIVER_MODELS = [
    """\
name: thing
class: prop
style: low_poly
parts:
  - sphere: {at: [0.215, 1.445, 0], radius: 0.092, sides: 8}
    color: '#c8b48c'
  - cone: {aim: [[0.215, 1.455, 0], [0.245, 1.165, 0.0]], radius: 0.085, radius_top: 0.07, sides: 8}
    color: '#c8b48c'
lint: {disable: [W106]}
""",
    """\
name: thing
class: prop
style: low_poly
parts:
  - cone: {radius: 0.03, radius_top: 0.035, height: 0.7335, sides: 6}
    color: "#5a4030"
    aim: [[0.0, -0.3, 0.13], [0.0, 0.42, 0.27]]
  - cone: {radius: 0.05, radius_top: 0.065, height: 0.14, sides: 6}
    color: "#202020"
    aim: [[0, 0.36, 0.26], [0, 0.5, 0.285]]
  - ellipsoid: {at: [0, 0.52, 0.29], radii: [0.06, 0.035, 0.06], sides: 6}
    color: "#ff8020"
lint: {disable: [W106]}
""",
]


@pytest.mark.parametrize("text", SLIVER_MODELS, ids=["sphere_cone", "cones_ellipsoid"])
def test_shared_edges_of_flat_patches_get_no_sliver_pairs(project: Project, text: str) -> None:
    model, style = ok_model(project, text)
    assert style.hard_surface == "always"
    built = built_of(project, text)
    p = built.painted
    crowded, pinched = pinches(p.vertices, p.faces)
    assert len(crowded) == 0 and len(pinched) == 0
    assert len(open_edges(p.vertices, p.faces)) == 0
    assert not [f for f in geometry_warnings(built, {}, project) if f.rule == "E013"]


# #67: a CSG sliver thinner than WELD between interlocked links had a corner on its own opposite edge; splitting that
# edge there folded its outline over itself and fanning it gave two faces back to back (four on one edge, E013)
CHAIN = """\
name: thing
class: prop
style: low_poly
lint: {disable: [W106, W110]}
parts:
  - torus: {at: [0.0013, 0.140, -0.0001], radius: 0.052, thickness: 0.015, rotate: [90, -5.65, 0], sides: 8}
    color: '#808080'
    hard: true
  - torus: {at: [-0.0006, 0.218, 0.0025], radius: 0.052, thickness: 0.015, rotate: [90, -4.63, 90], sides: 8}
    color: '#808080'
    hard: true
  - torus: {at: [-0.0017, 0.296, 0.0002], radius: 0.052, thickness: 0.015, rotate: [90, -9.6, 0], sides: 8}
    color: '#808080'
    hard: true
  - torus: {at: [0.002, 0.374, -0.0014], radius: 0.052, thickness: 0.015, rotate: [90, -5.94, 90], sides: 8}
    color: '#808080'
    hard: true
  - torus: {at: [0.002, 0.452, 0.0018], radius: 0.052, thickness: 0.015, rotate: [90, -10.6, 0], sides: 8}
    color: '#808080'
    hard: true
  - torus: {at: [-0.002, 0.530, -0.0013], radius: 0.052, thickness: 0.015, rotate: [90, -9.6, 90], sides: 8}
    color: '#808080'
    hard: true
"""


def test_interlocked_links_leave_no_folded_slivers(project: Project) -> None:
    built = built_of(project, CHAIN)
    p = built.painted
    crowded, pinched = pinches(p.vertices, p.faces)
    assert len(crowded) == 0 and len(pinched) == 0
    assert len(open_edges(p.vertices, p.faces)) == 0
    assert not [f for f in geometry_warnings(built, {}, project) if f.rule == "E013"]


def test_outlines_split_where_they_visit_a_point_twice() -> None:
    assert _simple_loops([1, 2, 3, 4]) == [[1, 2, 3, 4]]
    assert _simple_loops([5, 6, 5, 7]) == []  # a sliver folded onto one edge: no area
    assert _simple_loops([1, 2, 3, 1, 4, 5]) == [[1, 2, 3], [1, 4, 5]]
    assert _simple_loops([1, 2]) == []
