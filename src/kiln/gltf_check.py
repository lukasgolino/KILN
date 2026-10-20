"""Read and check KILN's .glb files (tests, previews, `kiln build` self-checks).

A subset of the Khronos validator's rules, plus skins: what KILN writes must pass. The real validator (npm
`gltf-validator`) is run on the demo in development; this keeps the same rules in the test suite.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from kiln.vendor.gltf import FLOAT, UNSIGNED_BYTE, UNSIGNED_INT, UNSIGNED_SHORT, read_glb

COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_NUMPY = {FLOAT: "<f4", UNSIGNED_SHORT: "<u2", UNSIGNED_INT: "<u4", UNSIGNED_BYTE: "u1"}
_SIZES = {FLOAT: 4, UNSIGNED_SHORT: 2, UNSIGNED_INT: 4, UNSIGNED_BYTE: 1}


def accessor(doc: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    acc = doc["accessors"][index]
    view = doc["bufferViews"][acc["bufferView"]]
    n = COMPONENTS[acc["type"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    array = np.frombuffer(binary, dtype=np.dtype(_NUMPY[acc["componentType"]]), count=acc["count"] * n, offset=start)
    return array.reshape(acc["count"], n) if n > 1 else array


def validate(doc: dict[str, Any], binary: bytes) -> list[str]:
    problems: list[str] = []
    if doc.get("asset", {}).get("version") != "2.0":
        problems.append("asset.version must be 2.0")
    for i, view in enumerate(doc.get("bufferViews", [])):
        if view.get("byteOffset", 0) % 4:
            problems.append(f"bufferViews[{i}] isn't 4-byte aligned")
        if view.get("byteOffset", 0) + view["byteLength"] > len(binary):
            problems.append(f"bufferViews[{i}] runs past the buffer")
    positions = {p["attributes"]["POSITION"] for m in doc.get("meshes", []) for p in m["primitives"]}
    inputs = {s["input"] for a in doc.get("animations", []) for s in a["samplers"]}
    for i, acc in enumerate(doc.get("accessors", [])):
        view = doc["bufferViews"][acc["bufferView"]]
        needed = acc["count"] * COMPONENTS[acc["type"]] * _SIZES[acc["componentType"]]
        if needed > view["byteLength"]:
            problems.append(f"accessors[{i}] needs {needed} bytes, its view has {view['byteLength']}")
        if (i in positions or i in inputs) and ("min" not in acc or "max" not in acc):
            problems.append(f"accessors[{i}] needs min and max")
        if "min" in acc and acc["count"]:
            values = accessor(doc, binary, i).reshape(acc["count"], -1)
            if [float(v) for v in values.min(axis=0)] != acc["min"] or [float(v) for v in values.max(axis=0)] != acc["max"]:
                problems.append(f"accessors[{i}] min/max don't match its data")
    joints_of_skin = {i: len(s["joints"]) for i, s in enumerate(doc.get("skins", []))}
    for m, mesh in enumerate(doc.get("meshes", [])):
        for p, prim in enumerate(mesh["primitives"]):
            attrs = prim["attributes"]
            counts = {doc["accessors"][a]["count"] for a in attrs.values()}
            if len(counts) != 1:
                problems.append(f"meshes[{m}].primitives[{p}] attributes have different counts")
            idx = accessor(doc, binary, prim["indices"])
            if idx.size % 3 or (idx.size and int(idx.max()) >= min(counts)):
                problems.append(f"meshes[{m}].primitives[{p}] indices are out of range or not triangles")
            normals = accessor(doc, binary, attrs["NORMAL"])
            if len(normals) and not np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-3):
                problems.append(f"meshes[{m}].primitives[{p}] normals aren't unit length")
            for key in ("JOINTS_0", "WEIGHTS_0"):
                if key in attrs and doc["accessors"][attrs[key]]["type"] != "VEC4":
                    problems.append(f"meshes[{m}].primitives[{p}] {key} must be VEC4")
            if "WEIGHTS_0" in attrs:
                w = accessor(doc, binary, attrs["WEIGHTS_0"])
                j = accessor(doc, binary, attrs["JOINTS_0"])
                if not np.allclose(w.sum(axis=1), 1.0, atol=2e-3):
                    problems.append(f"meshes[{m}].primitives[{p}] weights don't sum to 1")
                if np.any(j[w == 0] != 0):
                    problems.append(f"meshes[{m}].primitives[{p}] unused joints must be 0")
                users = [n for n in doc.get("nodes", []) if n.get("mesh") == m and "skin" in n]
                if users and int(j.max()) >= joints_of_skin[users[0]["skin"]]:
                    problems.append(f"meshes[{m}].primitives[{p}] joint index out of range")
    nodes = doc.get("nodes", [])
    parents: dict[int, int] = {}
    for i, node in enumerate(nodes):
        for child in node.get("children", []):
            if child in parents or child == i or child >= len(nodes):
                problems.append(f"nodes[{i}] child {child} is invalid or has two parents")
            parents[child] = i
        if "skin" in node and (parents.get(i) is not None or any(k in node for k in ("translation", "rotation", "scale"))):
            problems.append(f"nodes[{i}] is skinned: it must be a root without a transform")
    for s, skin in enumerate(doc.get("skins", [])):
        if "inverseBindMatrices" in skin and doc["accessors"][skin["inverseBindMatrices"]]["count"] != len(skin["joints"]):
            problems.append(f"skins[{s}] needs one inverse bind matrix per joint")
    for a, anim in enumerate(doc.get("animations", [])):
        for c, ch in enumerate(anim["channels"]):
            sampler = anim["samplers"][ch["sampler"]]
            times = accessor(doc, binary, sampler["input"])
            if doc["accessors"][sampler["output"]]["count"] != len(times):
                problems.append(f"animations[{a}].channels[{c}] value count != key count")
            if len(times) > 1 and not np.all(np.diff(times) > 0):
                problems.append(f"animations[{a}].channels[{c}] key times must increase")
    return problems


def check_glb(data: bytes) -> list[str]:
    doc, binary = read_glb(data)
    return validate(doc, binary)


__all__ = ["accessor", "check_glb", "read_glb", "validate"]
