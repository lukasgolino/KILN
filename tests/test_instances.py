"""#171: other models placed in a model (`instances:`), each its own build at its own detail."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import errors_of, run_json, write_model

from kiln.build import build
from kiln.cli import main
from kiln.gltf_check import read_glb
from kiln.lint import lint_paths
from kiln.project import Project

SCREW = "name: screw\nresolution: 0.004\nparts:\n  - cylinder: { at: [0, 0.01, 0], radius: 0.01, height: 0.02 }\n    color: grey\n"
DESK = """\
name: desk
resolution: 0.03
parts:
  - box: { at: [0, 0.05, 0], size: [1.0, 0.1, 0.6] }
    color: wood
instances:
  - { model: screw, at: [0.2, 0.1, 0] }
  - { model: screw, at: [-0.2, 0.1, 0.1], rotate: [0, 45, 0], scale: 2 }
"""


@pytest.fixture
def desk(project: Project) -> Project:
    write_model(project, SCREW, "screw")
    write_model(project, DESK, "desk")
    return project


def test_instances_keep_their_own_detail(desk: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from kiln.cli import _built

    monkeypatch.chdir(desk.root)
    screw = _built(desk, "screw")
    scene = _built(desk, "desk")
    assert scene.triangles >= 2 * screw.triangles  # both screws, each with all its triangles
    v = scene.painted.vertices
    grey = np.array([scene.painted.groups[g].color == "#8a93a3" for g in scene.painted.face_group])
    tops = v[scene.painted.faces[grey]].reshape(-1, 3)
    assert abs(tops[:, 1].max() - (0.1 + 0.04)) < 2e-3  # the big screw (scale 2) stands 4 cm on the desk top
    assert np.isclose(tops[:, 0].max(), 0.21, atol=2e-3)  # the first screw at x = 0.2, radius 1 cm


def test_the_glb_carries_them(desk: Project) -> None:
    assert not build(desk).errors
    doc, _ = read_glb((desk.output_dir / "models" / "desk.glb").read_bytes())
    assert any(m["name"].startswith("default_grey") for m in doc["materials"])


def test_missing_and_circular_instances(desk: Project, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(desk, DESK.replace("model: screw, at: [0.2", "model: bolt, at: [0.2"), "desk")
    found = [f for f in lint_paths(desk, [desk.models_dir / "desk.kiln.yaml"], geometry=False).findings if f.rule == "E011"]
    assert found and "bolt" in found[0].message
    write_model(desk, SCREW + "instances: [{ model: desk }]\n", "screw")
    write_model(desk, DESK, "desk")
    monkeypatch.chdir(desk.root)
    code, out = run_json(["preview", "desk", "--views", "front", "--size", "64"], capsys)
    assert code != 0 and "circle" in str(out), out
    assert main(["--json", "build", "desk"]) != 0


def test_bad_entries_are_refused(project: Project) -> None:
    for entry in ("[{ model: desk }]", "[{ model: screw, scale: 0 }]", "[{ model: screw, id: nope }]", "{ model: screw }"):
        text = DESK.split("instances:")[0].replace("name: desk", "name: desk") + f"instances: {entry}\n"
        assert any(f.rule == "E003" for f in errors_of(project, text, "desk")), entry
