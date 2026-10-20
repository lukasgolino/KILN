"""Imported meshes: scale, ground, palette snapping, decimation and credits."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from conftest import built_of, ok_model
from kiln.build import build
from kiln.builder import build_model
from kiln.export import to_glb
from kiln.gltf_check import check_glb
from kiln.importer import mesh_normals, nearest_palette, read_mesh
from kiln.project import Project
from pagan.gltf import ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER, Document

BOX_FACES = np.array([
    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7], [0, 1, 5], [0, 5, 4],
    [2, 3, 7], [2, 7, 6], [1, 2, 6], [1, 6, 5], [0, 4, 7], [0, 7, 3],
])  # fmt: skip


def box_glb(path: Path, colors: tuple[tuple[float, float, float], ...] = ((0.8, 0.05, 0.04), (0.03, 0.15, 0.6))) -> Path:
    """A 2 x 2 x 2 box centred on the origin in a node scaled by 0.5 and moved up by 3; the bottom faces in a
    second colour (linear RGB factors, as glTF stores them)."""
    doc = Document("test")
    v = np.array([[x, y, z] for x, y, z in ((-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1), (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))], float)
    pos = doc.accessor(v.astype(np.float32), target=ARRAY_BUFFER, bounds=True)
    bottom = np.all(v[BOX_FACES][:, :, 1] < 0, axis=1)
    prims = []
    for k, sel in enumerate((~bottom, bottom)):
        mat = doc.add("materials", {"pbrMetallicRoughness": {"baseColorFactor": [*colors[k], 1.0], "metallicFactor": 0.0}})
        idx = doc.accessor(BOX_FACES[sel].reshape(-1).astype(np.uint32), target=ELEMENT_ARRAY_BUFFER)
        prims.append({"attributes": {"POSITION": pos}, "indices": idx, "material": mat})
    doc.add("meshes", {"primitives": prims})
    doc.add("nodes", {"mesh": 0, "scale": [0.5, 0.5, 0.5], "translation": [0.0, 3.0, 0.0]})
    doc.json["scenes"] = [{"nodes": [0]}]
    doc.json["scene"] = 0
    path.write_bytes(doc.glb())
    return path


SOURCE = """\
name: crate
class: prop
source: { file: imports/box.glb, licence: CC0-1.0, author: Kenney, url: "https://kenney.nl" }
"""


def test_read_mesh_applies_node_transforms(tmp_path: Path) -> None:
    v, f, cols, kinds = read_mesh(box_glb(tmp_path / "box.glb"))
    assert len(f) == 12 and kinds == ["default"] * 12
    np.testing.assert_allclose(v.min(axis=0), [-0.5, 2.5, -0.5])
    np.testing.assert_allclose(v.max(axis=0), [0.5, 3.5, 0.5])
    assert cols.shape == (12, 3) and np.all((cols >= 0) & (cols <= 1))


def test_nearest_palette() -> None:
    out = nearest_palette(np.array([[0.9, 0.25, 0.25], [0.1, 0.4, 0.8]]), ["#e8413c", "#2f6fd0", "#141414"])
    assert out == ["#e8413c", "#2f6fd0"]


def test_import_scales_grounds_and_snaps(project: Project) -> None:
    box_glb(project.root / "imports" / "box.glb")
    built = built_of(project, SOURCE + "process: { height: 1.5 }\n", "crate")
    lo, hi = built.bounds()
    assert lo[1] == pytest.approx(0.0, abs=1e-9)
    assert hi[1] - lo[1] == pytest.approx(1.5)
    assert hi[0] - lo[0] == pytest.approx(1.5)
    assert sorted(g.color_name for g in built.painted.groups) == ["blue", "red"]
    assert built.skin == "none" and built.tracks == []
    assert check_glb(to_glb(built, "kiln test")) == []


def test_import_scale_and_keep_colours(project: Project) -> None:
    box_glb(project.root / "imports" / "box.glb")
    built = built_of(project, SOURCE + "process: { scale: 2, recolor: keep, rotate: [0, 0, 90] }\n", "crate")
    lo, hi = built.bounds()
    np.testing.assert_allclose(hi - lo, [2.0, 2.0, 2.0], atol=1e-9)
    assert lo[1] == pytest.approx(0.0)
    colours = sorted(g.color for g in built.painted.groups)
    assert colours[0] not in ("#e8413c", "#2f6fd0")  # the file's own colours
    assert all(c.startswith("#") and len(c) == 7 for c in colours)


def test_import_decimates_to_the_budget(project: Project) -> None:
    from kiln.mesher import dual_contour
    from kiln.sdf import Field, Geometry

    mesh = dual_contour(Field([Geometry("sphere", {"radius": 0.5})], margin=0.05), 0.02)
    doc = Document("test")
    pos = doc.accessor(mesh.vertices.astype(np.float32), target=ARRAY_BUFFER, bounds=True)
    idx = doc.accessor(mesh.faces.reshape(-1).astype(np.uint32), target=ELEMENT_ARRAY_BUFFER)
    doc.add("meshes", {"primitives": [{"attributes": {"POSITION": pos}, "indices": idx}]})
    doc.add("nodes", {"mesh": 0})
    (project.root / "imports" / "box.glb").write_bytes(doc.glb())
    model, style = ok_model(project, SOURCE + "budget: 300\n", "crate")
    built = build_model(model, style)
    assert built.triangles <= 360


def test_mesh_normals_smooth_and_flat() -> None:
    v = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]])
    f = np.array([[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])
    flat = mesh_normals(v, f, False, 40.0)
    assert flat.shape == (4, 3, 3)
    np.testing.assert_allclose(flat[0], [[0, 0, -1]] * 3, atol=1e-12)
    smooth = mesh_normals(v, f, True, 179.0)
    np.testing.assert_allclose(np.linalg.norm(smooth, axis=2), 1.0)
    assert not np.allclose(smooth, flat)


def test_import_credits_in_manifest_and_credits_md(project: Project) -> None:
    box_glb(project.root / "imports" / "box.glb")
    (project.models_dir / "crate.kiln.yaml").write_text(SOURCE + "process: { height: 1.0 }\n")
    result = build(project)
    assert result.errors == []
    entry = result.manifest["models"]["crate"]
    assert entry["source"] == {"file": "box.glb", "licence": "CC0-1.0", "author": "Kenney", "url": "https://kenney.nl"}
    credits = (project.output_dir / "CREDITS.md").read_text()
    assert "**crate**: box.glb by Kenney (https://kenney.nl), licence CC0-1.0" in credits
    assert "CREDITS.md" in json.loads((project.output_dir / "manifest.json").read_text())["files"]


def test_read_gltf_with_external_buffer(tmp_path: Path) -> None:
    from pagan.gltf import read_glb

    doc, binary = read_glb(box_glb(tmp_path / "box.glb").read_bytes())
    doc["buffers"] = [{"byteLength": len(binary), "uri": "box.bin"}]
    (tmp_path / "box.bin").write_bytes(binary)
    (tmp_path / "box.gltf").write_text(json.dumps(doc))
    v, f, _, _ = read_mesh(tmp_path / "box.gltf")
    assert len(f) == 12
    np.testing.assert_allclose(v.max(axis=0), [0.5, 3.5, 0.5])
