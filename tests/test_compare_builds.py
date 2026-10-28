"""tools/compare_builds.py (#27): the cross-machine report's glb accessor diff and directory report."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np

from kiln.vendor.gltf import Document

_SPEC = importlib.util.spec_from_file_location(
    "compare_builds", Path(__file__).resolve().parent.parent / "tools" / "compare_builds.py"
)
assert _SPEC is not None and _SPEC.loader is not None
cb: Any = importlib.util.module_from_spec(_SPEC)
sys.modules["compare_builds"] = cb  # dataclasses look their module up
_SPEC.loader.exec_module(cb)


def glb(positions: np.ndarray, indices: np.ndarray) -> bytes:
    doc = Document("test")
    pos = doc.accessor(positions.astype(np.float32), bounds=True)
    idx = doc.accessor(indices)
    doc.add("meshes", {"name": "body", "primitives": [{"attributes": {"POSITION": pos}, "indices": idx}]})
    return doc.glb()


POS = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=np.float32)
IDX = np.array([0, 1, 2])


def test_identical_glbs_have_no_accessor_diffs() -> None:
    d = cb.compare_glb(glb(POS, IDX), glb(POS, IDX))
    assert d.json_same and d.accessors == [] and d.note == ""


def test_float_differences_are_labelled_and_measured() -> None:
    moved = POS.copy()
    moved[1, 0] = np.nextafter(np.float32(1), np.float32(2))
    moved[2, 1] = 1.25
    d = cb.compare_glb(glb(POS, IDX), glb(moved, IDX))
    assert [x.label for x in d.accessors] == ["mesh 'body' p0 POSITION"]
    (x,) = d.accessors
    assert (x.count, x.total) == (2, 9)
    assert x.max_abs == 0.25
    assert not d.json_same  # POSITION max changed


def test_count_mismatch_is_noted_not_compared() -> None:
    d = cb.compare_glb(glb(POS, IDX), glb(np.vstack([POS, POS]), np.array([0, 1, 2, 3, 4, 5])))
    assert {x.label: x.note for x in d.accessors} == {
        "mesh 'body' p0 POSITION": "count 3 vs 6",
        "mesh 'body' p0 indices": "count 3 vs 6",
    }


def test_report_lists_identical_different_and_missing(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        (root / "models").mkdir(parents=True)
        (root / "manifest.json").write_text('{"x": 1}\n')
    (a / "models" / "m.glb").write_bytes(glb(POS, IDX))
    (b / "models" / "m.glb").write_bytes(glb(POS * 2, IDX))
    (a / "only_a.tscn").write_text("[node]\n")
    text = cb.report([("x86", a), ("arm", b)])
    assert "| `manifest.json` | identical |" in text
    assert "| `models/m.glb` | **different** |" in text
    assert "| `only_a.tscn` | missing here |" in text
    assert "mesh 'body' p0 POSITION | 2/9 | 1 |" in text
