"""#209: a cut names the parts it cuts (`cut: [ids]`): a recess in a watch case leaves the pad under it alone."""

from __future__ import annotations

import numpy as np
from conftest import built_of, errors_of

from kiln.project import Project

TRAY = """\
name: thing
parts:
  - box: {{ at: [0, 0.05, 0], size: [0.8, 0.1, 0.8] }}
    id: pad
    color: grey
  - box: {{ at: [-0.2, 0.15, 0], size: [0.3, 0.1, 0.3] }}
    id: case
    color: red
  - box: {{ at: [0.2, 0.15, 0], size: [0.3, 0.1, 0.3] }}
    id: lid
    color: blue
  - box: {{ at: [0, 0.12, 0], size: [0.7, 0.1, 0.1] }}
    cut: {cut}
"""


def _grooved(built: object, x: float) -> bool:
    """Is there a surface below the pad's top (y < 0.1) near (x, 0.1, 0): the cut bit into the pad there?"""
    p = built.painted  # type: ignore[attr-defined]
    c = p.vertices[p.faces].mean(axis=1)
    return bool(((np.abs(c[:, 0] - x) < 0.05) & (np.abs(c[:, 2]) < 0.04) & (c[:, 1] < 0.095) & (c[:, 1] > 0.02)).any())


def test_a_cut_keeps_to_the_parts_it_names(project: Project) -> None:
    every = built_of(project, TRAY.format(cut="true"))
    assert _grooved(every, 0.0)  # cut: true bites into the pad between the boxes
    scoped = built_of(project, TRAY.format(cut="[case, lid]"))
    assert not _grooved(scoped, 0.0)  # the pad is whole


def test_unknown_ids_are_named(project: Project) -> None:
    errors = errors_of(project, TRAY.format(cut="[case, nope]"))
    assert any(f.rule == "E003" and "nope" in f.message for f in errors), errors


def test_a_cut_reaching_only_what_it_names_keeps_the_shared_surface(project: Project) -> None:
    from conftest import ok_model

    from kiln.builder import mesh_pieces

    model, _ = ok_model(project, TRAY.format(cut="[case]").replace("[0.7, 0.1, 0.1]", "[0.1, 0.05, 0.1]").replace("at: [0, 0.12, 0]", "at: [-0.2, 0.19, 0]"))
    pieces, n_main = mesh_pieces(model)
    assert len(pieces) == n_main == 1  # the cut is inside the case only: nothing to split off


def test_folded_ids_in_a_cut_list(project: Project) -> None:
    text = TRAY.format(cut="[case, lid]") + "rig:\n  lid: { parent: case, fold: true }\n"
    assert not errors_of(project, text)
