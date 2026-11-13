"""`kiln lint` warnings W101-W109 and disabling them."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_project, sphere_text, write_model

from kiln.lint import WARNING_RULES, lint_paths, lint_project
from kiln.project import Project
from kiln.vendor.findings import Finding


def lint(project: Project, text: str, name: str = "thing") -> list[Finding]:
    path = write_model(project, text, name)
    return lint_paths(project, [path]).findings


def warnings(findings: list[Finding]) -> list[str]:
    return sorted(f.rule for f in findings if f.severity == "warning")


def test_clean_model_has_no_findings(project: Project) -> None:
    assert lint(project, sphere_text()) == []


def test_w101_covered_part(project: Project) -> None:
    findings = lint(project, sphere_text() + "  - sphere: { at: [0, 0.3, 0], radius: 0.1 }\n    color: white\n")
    assert warnings(findings) == ["W101"]
    f = findings[0]
    assert f.where == "parts[1]" and f.line == 5 and "no visible surface" in f.message


def test_w101_cut_away_part(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0.5, 0.3, 0], radius: 0.05 }\n    color: white\n  - sphere: { at: [0.5, 0.3, 0], radius: 0.15 }\n    cut: true\n"
    assert "W101" in warnings(lint(project, text))


def test_w102_thin_part(project: Project) -> None:
    text = sphere_text() + "  - box: { at: [0, 0.6, 0], size: [0.3, 0.02, 0.3] }\n    color: white\n"
    findings = [f for f in lint(project, text) if f.rule == "W102"]
    assert len(findings) == 1 and findings[0].where == "parts[1]" and "across at its thinnest" in findings[0].message and "hard: true" in findings[0].message


def test_w103_floating_piece(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0, 1.2, 0], radius: 0.1 }\n    color: white\n"
    findings = lint(project, text)
    assert warnings(findings) == ["W103"]
    assert "2 separate pieces" in findings[0].message


def test_w104_hex_colour_not_in_palette(project: Project) -> None:
    findings = lint(project, sphere_text().replace("color: red", "color: '#123456'"))
    assert warnings(findings) == ["W104"]
    assert findings[0].where == "parts[0].color"
    # a hex that is in the palette is fine
    assert lint(project, sphere_text().replace("color: red", "color: '#E8413C'")) == []


def test_w106_not_on_the_ground(project: Project) -> None:
    findings = lint(project, sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]"))
    assert warnings(findings) == ["W106"]
    assert "y = 0.7" in findings[0].message


def test_w107_older_style_version(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\nstyle_version = 2\n')
    findings = lint(project, sphere_text() + "style_version: 1\n")
    assert warnings(findings) == ["W107"]
    assert findings[0].where == "style_version" and "kiln mark" in findings[0].message
    assert lint(project, sphere_text() + "style_version: 2\n") == []


def test_w108_size_for_class(project: Project) -> None:
    text = "name: thing\nclass: character\nparts:\n  - sphere: { at: [0, 0.05, 0], radius: 0.05 }\n    color: red\n"
    findings = lint(project, text)
    assert warnings(findings) == ["W108"]
    assert "character" in findings[0].message and "metres" in findings[0].message


def test_w109_animated_part_without_pivot(project: Project) -> None:
    text = sphere_text() + """\
  - sphere: { at: [0.3, 0.3, 0], radius: 0.1 }
    id: nub
    color: red
skin: rigid
animations:
  turn: { poses: [{ nub: { rotate: [0, 0, 30] } }, {}] }
"""
    findings = lint(project, text)
    assert warnings(findings) == ["W109"]
    assert "'nub'" in findings[0].message
    with_pivot = text.replace("skin: rigid", "rig:\n  nub: { pivot: [0.2, 0.3, 0] }")
    assert lint(project, with_pivot) == []


def test_w109_from_cycles(project: Project) -> None:
    text = sphere_text() + """\
  - sphere: { at: [0, 0.65, 0], radius: 0.1 }
    id: hat
    color: red
    blend: 0.03
skin: rigid
animations:
  swing: { cycle: { type: swing, part: hat, axis: z } }
"""
    assert warnings(lint(project, text)) == ["W109"]


def test_w109_not_for_humanoid_joints(project: Project) -> None:
    """#187: `skeleton: humanoid` puts its joints' pivots at the joints, so animating them needs no rig pivot; a
    non-joint part still does."""
    from test_retarget import HERO

    parts = HERO[: HERO.index("rig:\n")]  # no explicit pivots, no imported clips
    text = parts + """\
  - sphere: { at: [0.3, 1.3, 0], radius: 0.05 }
    id: nub
    color: red
animations:
  look: { poses: [{ head: { rotate: [0, 30, 0] }, upperarm_l: { rotate: [0, 0, 40] }, nub: { rotate: [0, 0, 30] } }, {}] }
"""
    w109 = [f.message for f in lint(project, text) if f.rule == "W109"]
    assert len(w109) == 1 and "'nub'" in w109[0]


def test_disable_in_kiln_toml(tmp_path: Path) -> None:
    project = make_project(tmp_path, 'default_style = "fast"\ndefault_palette = "main"\n[lint]\ndisable = ["W106"]\n')
    assert lint(project, sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]")) == []


def test_disable_per_model(project: Project) -> None:
    text = sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]") + "lint: { disable: [W106] }\n"
    assert lint(project, text) == []


def test_errors_are_never_disabled(project: Project) -> None:
    text = sphere_text().replace("color: red", "color: mauve") + "lint: { disable: [E004] }\n"
    assert [f.rule for f in lint(project, text)] == ["E004"]


def test_e009_nothing_to_mesh(project: Project) -> None:
    text = sphere_text() + "  - sphere: { at: [0, 0.3, 0], radius: 0.5 }\n    cut: true\n"
    findings = lint(project, text)
    assert [f.rule for f in findings] == ["E009"]
    assert "no surface" in findings[0].message


def test_lint_without_geometry_skips_meshing(project: Project) -> None:
    path = write_model(project, sphere_text().replace("at: [0, 0.3, 0]", "at: [0, 1.0, 0]"))
    result = lint_paths(project, [path], geometry=False)
    assert result.findings == [] and result.built == {}
    assert "thing" in result.models


def test_lint_project_collects_every_model(project: Project) -> None:
    write_model(project, sphere_text("a"), "a")
    write_model(project, sphere_text("b").replace("color: red", "color: mauve"), "b")
    result = lint_project(project)
    assert sorted(result.models) == ["a"] and sorted(result.built) == ["a"]
    assert [f.rule for f in result.errors] == ["E004"]
    assert result.errors[0].path == project.models_dir / "b.kiln.yaml"


def test_second_lint_uses_the_cache(project: Project) -> None:
    write_model(project, sphere_text())
    lint_project(project)
    cached = list((project.root / ".kiln-cache").glob("thing.base.*.pickle"))
    assert len(cached) == 1
    lint_project(project)
    assert list((project.root / ".kiln-cache").glob("thing.base.*.pickle")) == cached
    write_model(project, sphere_text().replace("radius: 0.3", "radius: 0.29"))
    lint_project(project)
    after = list((project.root / ".kiln-cache").glob("thing.base.*.pickle"))
    assert len(after) == 1 and after != cached  # old entry replaced


@pytest.mark.parametrize("rule", sorted(WARNING_RULES))
def test_every_warning_is_documented(rule: str) -> None:
    assert rule.startswith("W1") and WARNING_RULES[rule]


def test_w106_catches_a_few_centimetres(project: Project) -> None:
    text = "name: thing\nparts:\n  - capsule: { from: [0, 0.06, 0], to: [0, 0.5, 0], radius: 0.1 }\n    color: red\n"
    assert "W106" in warnings(lint(project, text))  # 4 cm under the ground (the old bean template)


def test_w110_patterns_over_budget(project: Project) -> None:
    text = ("name: thing\nbudget: 200\nparts:\n  - box: { at: [0, 0.5, 0], size: [1, 1, 1], round: 0.05 }\n    color: red\n"
            "    pattern: { type: stripes, color: blue, size: 0.06, axis: y }\n")  # fmt: skip
    assert "W110" in warnings(lint(project, text))


def test_budget_is_met_when_painting_adds_triangles(project: Project) -> None:
    text = ("name: thing\nbudget: 1500\nparts:\n  - sphere: { at: [0, 0.5, 0], radius: 0.5 }\n    color: red\n"
            "  - sphere: { at: [0.2, 0.8, 0.3], radius: 0.12 }\n    color: blue\n"
            "  - sphere: { at: [-0.2, 0.8, 0.3], radius: 0.12 }\n    color: blue\n")  # fmt: skip
    write_model(project, text)
    result = lint_paths(project, project.model_paths())
    assert result.built["thing"].triangles <= 1500 * 1.05


def test_w106_allows_a_rounded_bottom_at_coarse_resolution(project: Project) -> None:
    # LOOSE #33: a rounded extrude standing on y = 0 meshes a cell or so above it
    text = ("name: thing\nparts:\n  - extrude: { points: [[-0.5, -0.1], [0.5, -0.1], [0.5, 0.1], [-0.5, 0.1]], height: 1, round: 0.08,"
            " at: [0, 0.5, 0] }\n    color: red\n")  # fmt: skip
    assert "W106" not in warnings(lint(project, text))
    assert "W106" not in warnings(lint(project, text.replace("parts:", "origin: center\nparts:").replace("[0, 0.5, 0]", "[0, 0.8, 0]")))


def test_w123_a_small_dip_below_the_ground_and_origin_ground(project: Project) -> None:
    """#101: a few millimetres under y = 0 is under W106's tolerance; W123 says so, and origin: ground lifts the export."""
    from kiln.export import to_glb
    from kiln.gltf_check import accessor
    from kiln.vendor.gltf import read_glb

    text = "name: thing\nparts:\n  - box: { at: [0, 0.245, 0], size: [0.5, 0.5, 0.5] }\n    color: red\n"  # 5 mm under
    found = warnings(lint(project, text))
    assert "W123" in found and "W106" not in found
    path = write_model(project, text.replace("parts:", "origin: ground\nparts:"))
    result = lint_paths(project, [path])
    assert "W123" not in warnings(result.findings)
    built = result.built["thing"]
    assert built.origin()[0] == 0 and built.origin()[2] == 0 and built.origin()[1] < -0.002
    doc, binary = read_glb(to_glb(built, "kiln"))
    lows = [accessor(doc, binary, p["attributes"]["POSITION"])[:, 1].min() for m in doc["meshes"] for p in m["primitives"]]
    root = doc["nodes"][doc["scenes"][0]["nodes"][0]]
    assert abs(min(lows) + root.get("translation", [0, 0, 0])[1]) < 1e-6  # the lowest point lands on y = 0
    assert warnings(lint(project, sphere_text())) == []  # standing on y = 0: no W123


BODY = "name: thing\nparts:\n  - sphere: { at: [0, 0.5, 0], radius: 0.5 }\n    color: red\n"


def test_w101_names_the_covering_part(project: Project) -> None:
    """#98: W101 says which part covers the hidden one."""
    text = BODY.replace("parts:\n", "parts:\n  - sphere: { at: [0, 0.5, 0.1], radius: 0.1 }\n    color: blue\n")
    found = [f for f in lint(project, text) if f.rule == "W101"]
    assert len(found) == 1 and "part 1 (sphere, red) covers it" in found[0].message


@pytest.mark.parametrize(("extra", "expected"), [
    ("  - sphere: { at: [0, 0.5, 0.305], radius: 0.2 }\n    color: blue\n", True),  # a 5 mm cap of it shows
    ("  - sphere: { at: [0.15, 0.85, 0.35], radius: 0.08 }\n    color: white\n", False),  # an eye, about half in
])  # fmt: skip
def test_w124_a_part_that_shows_only_a_sliver(project: Project, extra: str, expected: bool) -> None:
    findings = lint(project, BODY.replace("parts:", "resolution: 0.01\nparts:") + extra)
    w124 = [f for f in findings if f.rule == "W124"]
    assert bool(w124) == expected, findings
    if expected:
        assert "part 1 (sphere, blue) is" in w124[0].message and "inside part 0 (sphere, red)" in w124[0].message


def test_cover_counts_what_a_cut_opens(project: Project) -> None:
    from conftest import load

    from kiln.builder import field_of
    from kiln.cover import covers

    eye = "  - sphere: { at: [0, 0.5, 0.42], radius: 0.06 }\n    color: white\n"
    slit = "  - box: { at: [0, 0.5, 0.5], size: [0.4, 0.05, 0.3] }\n    cut: true\n"
    cover = []
    for text in (BODY + eye + slit, BODY + eye):
        model, _, findings = load(project, text)
        assert model is not None, findings
        cover.append(covers(model, field_of(model, 0.01), 0.01, [1])[1].covered)
    assert cover[0] < cover[1] - 0.1  # the slit cut into the body shows more of the eye


def test_cover_keeps_to_the_builders_pieces(project: Project) -> None:
    """union: per_bone meshes each bone apart: an arm deep in the chest is its own surface, not covered by it."""
    from conftest import load

    from kiln.builder import field_of
    from kiln.cover import covers

    text = ("name: thing\nskin: rigid\nUNION:parts:\n  - sphere: { at: [0, 0.5, 0], radius: 0.5 }\n    id: chest\n    color: red\n"
            "  - sphere: { at: [0, 0.5, 0.3], radius: 0.15 }\n    id: arm\n    color: blue\n"
            "rig:\n  arm: { pivot: [0, 0.5, 0.3] }\n")  # fmt: skip
    for union, covered in (("", True), ("union: per_bone\n", False)):
        model, _, findings = load(project, text.replace("UNION:", union))
        assert model is not None, findings
        c = covers(model, field_of(model, 0.01), 0.01, [1])
        assert (c[1].covered > 0.9) == covered, (union, c)


def test_cover_samples_every_copy(project: Project) -> None:
    import numpy as np
    from conftest import load

    from kiln.builder import field_of
    from kiln.cover import surface_samples

    ring = BODY + "  - sphere: { at: [0.6, 0.5, 0], radius: 0.04 }\n    color: blue\n    array: { count: 8, around: y, center: [0, 0.5, 0] }\n"
    model, _, findings = load(project, ring)
    assert model is not None, findings
    points = surface_samples(field_of(model, 0.01).parts[1], 0.01)
    angles = np.round(np.degrees(np.arctan2(points[:, 2], points[:, 0])) / 45) % 8
    assert len(set(angles.tolist())) == 8 and len(points) > 8 * 100  # every bead of the ring, densely


def test_w123_names_the_part_that_dips(project: Project) -> None:
    """#195: W123 says which part is under the ground and by how much."""
    text = ("name: thing\nparts:\n  - box: { at: [0, 0.6, 0], size: [0.5, 0.5, 0.5] }\n    color: red\n"
            "  - sphere: { at: [0.1, 0.195, 0], radius: 0.2 }\n    id: foot\n    color: red\n    blend: 0.05\n")  # fmt: skip
    result = lint_paths(project, [write_model(project, text)])
    w = [f for f in result.findings if f.rule == "W123"]
    assert w and "under foot" in w[0].message and w[0].where == "parts[1]", [f.format() for f in result.findings]


def test_w136_a_band_that_misses_its_part(project: Project) -> None:
    """#326: a band placed off the part paints nothing: W136 says so (and where `at` is measured from)."""
    base = "name: thing\nparts:\n  - cylinder: { at: [0, 0.5, 0], radius: 0.2, height: 1.0 }\n    color: red\n    pattern: { type: band, color: blue, axis: y, at: AT, size: 0.1 }\n"
    hit = warnings(lint(project, base.replace("AT", "0.5")))
    miss = lint_paths(project, [write_model(project, base.replace("AT", "1.6"))]).findings
    assert "W136" not in hit and any(f.rule == "W136" and "measured from" in f.message for f in miss), [f.format() for f in miss]


def test_e016_a_big_part_that_vanishes_is_an_error(project: Project) -> None:
    """#324: a part a tenth of the model or more lost to the budget breaks the model: an error, not W111."""
    text = ("name: thing\nbudget: 40\nparts:\n  - sphere: { at: [0, 0.5, 0], radius: 0.4 }\n    color: red\n"
            "  - capsule: { from: [0.5, 0.1, 0], to: [0.5, 0.9, 0], radius: 0.012 }\n    color: blue\n")  # fmt: skip
    found = lint_paths(project, [write_model(project, text)]).findings
    assert any(f.rule == "E016" and f.severity == "error" for f in found), [f.format() for f in found]


def test_w137_off_palette_pixel_art_with_variants(project: Project) -> None:
    from PIL import Image

    (project.root / "textures").mkdir(exist_ok=True)
    Image.new("RGBA", (8, 8), (12, 200, 200, 255)).save(project.root / "textures" / "odd.png")
    text = ("name: thing\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: red\n"
            "    texture: { image: textures/odd.png, project: box, texel: 0.05 }\nVARIANTS")  # fmt: skip
    with_variants = lint_paths(project, [write_model(project, text.replace("VARIANTS", "variants:\n  b: { swap: { red: blue } }\n"))], geometry=False)
    without = lint_paths(project, [write_model(project, text.replace("VARIANTS", ""))], geometry=False)
    assert "W137" in warnings(with_variants.findings) and "W137" not in warnings(without.findings)


def test_w138_emission_above_its_colours_cap(project: Project) -> None:
    text = "name: thing\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: white\n    material: glow\n    emission: 3\n"
    assert "W138" in warnings(lint_paths(project, [write_model(project, text)], geometry=False).findings)
    assert "W138" not in warnings(lint_paths(project, [write_model(project, text.replace("emission: 3", "emission: 0.5"))], geometry=False).findings)


def test_w139_bevels_dropped_for_the_budget_step_by_step(project: Project) -> None:
    """#334: under budget pressure bevels go a few parts at a time, the smallest first, and lint says what keeps them."""
    parts = "".join(f"  - box: {{ at: [{x * 0.5}, 0.2, 0], size: [{0.1 + 0.08 * x}, 0.4, 0.3] }}\n    color: red\n    bevel: 0.02\n    segments: 3\n" for x in range(4))
    roomy = lint_paths(project, [write_model(project, "name: thing\nbudget: 20000\nparts:\n" + parts)])
    assert "W139" not in warnings(roomy.findings)
    tight = lint_paths(project, [write_model(project, "name: thing\nbudget: 300\nparts:\n" + parts)])  # chamfered: 368
    w = [f for f in tight.findings if f.rule == "W139"]
    assert w and "keeps them" in w[0].message, [f.format() for f in tight.findings]
    built = tight.built["thing"]
    assert built.hard_note is not None and built.hard_note[0] < built.hard_note[1]  # some kept theirs: not all at once
