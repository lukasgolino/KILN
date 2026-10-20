from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kiln.builder import build_model
from kiln.cli import main
from kiln.export import Built
from kiln.mesher import Mesh
from kiln.notation import Model, load_model
from kiln.project import Project, load_project
from kiln.style import Style
from pagan.findings import Finding

PALETTE = """\
name: main
colors:
  "0": { hex: "#141414", name: black }
  "1": { hex: "#f4f4f0", name: white }
  "2": { hex: "#e8413c", name: red }
  "3": { hex: "#2f6fd0", name: blue }
  "4": { hex: "#4caf50", name: green }
  "5": { hex: "#8a93a3", name: grey }
  "6": { hex: "#a0663a", name: wood }
  "7": { hex: "#f2c14e", name: gold }
ramps:
  greys: ["0", "5", "1"]
"""

# coarse and cheap: every test model meshes in well under a second
FAST_STYLE = """\
description = "fast test style"
extends = "soft_toy"

[shape]
resolution = 0.03

[budgets]
default = 800
prop = 600
character = 1200
"""

CONFIG = 'default_style = "fast"\ndefault_palette = "main"\n'

SPHERE = """\
name: {name}
parts:
  - sphere: {{ at: [0, 0.3, 0], radius: 0.3 }}
    color: red
"""

ARMS = """\
name: {name}
class: character
parts:
  - capsule: { from: [0, 0.3, 0], to: [0, 0.7, 0], radius: 0.3 }
    color: red
  - capsule: { from: [0.3, 0.6, 0], to: [0.45, 0.35, 0], radius: 0.08 }
    id: arm_l
    mirror: x
    mirror_id: arm_r
    blend: 0.04
    color: blue
rig:
  arm_l: { pivot: [0.3, 0.6, 0] }
skin: {skin}
animations:
  wave: { fps: 8, cycle: { type: wave, arms: [arm_l, arm_r], frames: 4 } }
  hold: { fps: 4, loop: false, poses: [{ arm_l: { rotate: [0, 0, -30] } }, { arm_l: { rotate: [0, 0, -60] } }] }
"""


def make_project(root: Path, config: str = CONFIG) -> Project:
    root.mkdir(parents=True, exist_ok=True)
    (root / "kiln.toml").write_text(config)
    for name in ("models", "palettes", "styles", "decals", "imports"):
        (root / name).mkdir(exist_ok=True)
    (root / "palettes" / "main.pal.yaml").write_text(PALETTE)
    (root / "styles" / "fast.style.toml").write_text(FAST_STYLE)
    return load_project(root)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return make_project(tmp_path)


def write_model(project: Project, text: str, name: str = "thing") -> Path:
    path = project.models_dir / f"{name}.kiln.yaml"
    path.write_text(text)
    return path


def sphere_text(name: str = "thing") -> str:
    return SPHERE.format(name=name)


def arms_text(name: str = "thing", skin: str = "rigid") -> str:
    return ARMS.replace("{name}", name).replace("{skin}", skin)


def load(project: Project, text: str, name: str = "thing") -> tuple[Model | None, Style | None, list[Finding]]:
    """Write a model into the project and parse it (with the project's style and palette)."""
    return project.load(write_model(project, text, name))


def ok_model(project: Project, text: str, name: str = "thing") -> tuple[Model, Style]:
    model, style, findings = load(project, text, name)
    assert model is not None and style is not None, [f.format() for f in findings]
    errors = [f.format() for f in findings if f.severity == "error"]
    assert not errors, errors
    return model, style


def errors_of(project: Project, text: str, name: str = "thing") -> list[Finding]:
    _, _, findings = load(project, text, name)
    return [f for f in findings if f.severity == "error"]


def built_of(project: Project, text: str, name: str = "thing") -> Built:
    model, style = ok_model(project, text, name)
    palette, _ = project.palette(model.palette)
    return build_model(model, style, palette=palette)


def parse(text: str, palette: dict[str, str] | None = None, materials: set[str] | None = None,
          path: Path | None = None) -> tuple[Model | None, list[Finding]]:  # fmt: skip
    """Parse model text without a project (palette names -> hex)."""
    pal = palette if palette is not None else {"red": "#e8413c", "blue": "#2f6fd0", "white": "#f4f4f0", "2": "#e8413c"}
    mats = materials if materials is not None else {"default", "plastic", "metal"}
    if path is None:
        from pagan.yamlio import parse_yaml

        from kiln.notation import parse_model

        return parse_model(parse_yaml(text), None, pal, mats, text)
    path.write_text(text)
    return load_model(path, pal, mats)


def closed(mesh: Mesh) -> bool:
    """Every directed edge has its reverse (watertight and consistently oriented)."""
    return closed_faces(mesh.faces)


def closed_faces(faces: np.ndarray) -> bool:
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    forward = {(int(a), int(b)) for a, b in edges}
    return len(forward) == len(edges) and all((b, a) in forward for a, b in forward)


def signed_volume(vertices: np.ndarray, faces: np.ndarray) -> float:
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)


@pytest.fixture
def in_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A project in tmp_path with the cwd inside it (for CLI tests)."""
    proj = make_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    return proj


def run_json(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)
