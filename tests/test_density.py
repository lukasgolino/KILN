"""#232 part density: a part's weight on the triangle budget in its surface."""

from __future__ import annotations

import numpy as np
from conftest import load, write_model

from kiln.lint import lint_paths
from kiln.project import Project

MODEL = """\
name: thing
class: creature
budget: 1500
parts:
  - ellipsoid: { at: [0, 0.5, 0], radii: [0.3, 0.45, 0.25] }
    id: body
    color: wood
  - sphere: { at: [0, 1.1, 0], radius: 0.2 }
    id: head
    color: wood
    blend: 0.05
"""


def head_share(project: Project, density: str = "") -> tuple[float, int]:
    built = lint_paths(project, [write_model(project, MODEL + density)]).built["thing"]
    p = built.painted
    centres = p.vertices[p.faces].mean(axis=1)
    return float((centres[:, 1] > 0.95).mean()), len(p.faces)


def test_notation(project: Project) -> None:
    model, _, findings = load(project, MODEL + "    density: 3\n")
    assert model is not None and not findings, findings
    assert [p.density for p in model.parts] == [1.0, 3.0]
    for bad in ("0", "20", "dense"):
        _, _, findings = load(project, MODEL + f"    density: {bad}\n")
        assert [f.where for f in findings] == ["parts[1].density"], (bad, findings)
    _, _, findings = load(project, "normal_map: 256\n" + MODEL + "    density: 2\n    detail: true\n")
    assert any(f.where == "parts[1].density" for f in findings), findings
    mirrored = MODEL.replace("  - sphere: { at: [0, 1.1, 0], radius: 0.2 }\n    id: head", "  - sphere: { at: [0.1, 1.1, 0], radius: 0.2 }\n    id: head\n    mirror: x")
    model, _, findings = load(project, mirrored + "    density: 2\n")
    assert model is not None and [p.density for p in model.parts][1:] == [2.0] * (len(model.parts) - 1), findings


def test_a_dense_part_gets_more_of_the_same_budget(project: Project) -> None:
    plain, total = head_share(project)
    shares = [head_share(project, f"    density: {d}\n") for d in (1.25, 1.5, 2, 3)]
    assert plain < shares[0][0] < shares[1][0] < shares[2][0] < shares[3][0]  # any density above 1 adds, more adds more
    assert shares[3][0] > plain * 1.5
    assert all(abs(n - total) <= total * 0.03 for _, n in shares)  # the total stays the budget
    coarse, _ = head_share(project, "    density: 0.5\n")
    assert coarse < plain * 0.7


def open_edges(faces: np.ndarray) -> int:
    edges = np.sort(np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((counts != 2).sum())


def crease(built: object) -> int:
    """Corners of one vertex whose normals differ by over 3 degrees (a same-colour model: only where the shape folds)."""
    p, n = built.painted, built.normals.reshape(-1, 3)  # type: ignore[attr-defined]
    v = p.faces.reshape(-1)
    order = np.argsort(v, kind="stable")
    vv, nn = v[order], n[order] / np.linalg.norm(n[order], axis=1, keepdims=True)
    same = vv[1:] == vv[:-1]
    return int((same & ((nn[1:] * nn[:-1]).sum(axis=1) < np.cos(np.radians(3)))).sum())


def test_the_mesh_stays_closed_and_smooth_across_a_dense_border(project: Project) -> None:
    plain = lint_paths(project, [write_model(project, MODEL)]).built["thing"]
    dense = lint_paths(project, [write_model(project, MODEL + "    density: 3\n")]).built["thing"]
    assert open_edges(plain.painted.faces) == 0 and open_edges(dense.painted.faces) == 0
    assert len(dense.painted.groups) == len(plain.painted.groups)  # density is no paint border ...
    assert crease(dense) <= crease(plain) + 8  # ... so the neck shades smoothly


def test_density_1_is_the_default_build(project: Project) -> None:
    a = lint_paths(project, [write_model(project, MODEL)]).built["thing"].painted
    b = lint_paths(project, [write_model(project, MODEL + "    density: 1\n")]).built["thing"].painted
    assert np.array_equal(a.vertices, b.vertices) and np.array_equal(a.faces, b.faces)


def test_a_small_dense_part_keeps_its_full_resolution_and_the_rest_take_the_budget(project: Project) -> None:
    """A part asking for more than it has at full resolution keeps all of it (the shaping pass leaves it whole); the
    leftover goes to the rest."""
    small = MODEL.replace("budget: 1500", "budget: 3000").replace("[0, 1.1, 0], radius: 0.2 }", "[0, 0.98, 0], radius: 0.07 }")

    def head(text: str) -> int:
        p = lint_paths(project, [write_model(project, text)]).built["thing"].painted
        assert len(p.faces) > 3000 * 0.95
        return int((p.vertices[p.faces].mean(axis=1)[:, 1] > 0.95).sum())

    full = head(small.replace("budget: 3000", "budget: 200000"))
    plain, three, eight = head(small), head(small + "    density: 3\n"), head(small + "    density: 8\n")
    assert plain <= three <= eight and eight >= full * 0.9


def test_separate_pieces_and_lods_take_their_density(project: Project) -> None:
    from kiln import builder

    rig = "rig:\n  head: { separate: true, pivot: [0, 0.95, 0] }\nskin: rigid\n"
    for parts, tail in ((MODEL, ""), (MODEL, rig)):
        model, style, findings = load(project, parts + "    density: 3\n" + tail)
        assert model is not None and style is not None and not [f for f in findings if f.severity == "error"], findings
        base, _, _ = load(project, parts + tail)
        assert base is not None
        for budget in (None, 600):
            dense, plain = builder.build_model(model, style, budget), builder.build_model(base, style, budget)
            share = [float((b.painted.vertices[b.painted.faces].mean(axis=1)[:, 1] > 0.95).mean()) for b in (dense, plain)]
            assert share[0] > share[1] * 1.2, (tail, budget, share)
