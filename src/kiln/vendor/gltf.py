"""A small, deterministic binary glTF 2.0 (`.glb`) writer: just what PAGAN's meshes need.

Same document in, same bytes out: JSON keys are sorted, floats are float32 values written by `repr`,
buffer views are 4-byte aligned and padded with zeros, and nothing depends on time or randomness.
"""

from __future__ import annotations

import json
import struct
from typing import Any

import numpy as np

FLOAT = 5126
UNSIGNED_SHORT = 5123
UNSIGNED_BYTE = 5121
UNSIGNED_INT = 5125
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
NEAREST = 9728
CLAMP_TO_EDGE = 33071
REPEAT = 10497
_TYPES = {1: "SCALAR", 2: "VEC2", 3: "VEC3", 4: "VEC4"}


def f32(value: float) -> float:
    """The float32 value as a Python float (what a reader decodes from the buffer)."""
    return float(np.float32(value))


class Document:
    """A glTF document under construction. Indices returned by the `add_*` methods are glTF indices."""

    def __init__(self, generator: str) -> None:
        self.json: dict[str, Any] = {"asset": {"version": "2.0", "generator": generator}}
        self.bin = bytearray()

    def _list(self, key: str) -> list[Any]:
        return self.json.setdefault(key, [])  # type: ignore[no-any-return]

    def _append(self, key: str, item: dict[str, Any]) -> int:
        items = self._list(key)
        items.append(item)
        return len(items) - 1

    def buffer_view(self, data: bytes, target: int | None = None) -> int:
        while len(self.bin) % 4:
            self.bin.append(0)
        view: dict[str, Any] = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.bin.extend(data)
        return self._append("bufferViews", view)

    def accessor(self, array: np.ndarray, *, target: int | None = None, bounds: bool = False, byte: bool = False) -> int:
        """Store a (count,) or (count, n) array. float -> FLOAT; ints -> UNSIGNED_SHORT when they fit, else
        UNSIGNED_INT (`byte`: UNSIGNED_BYTE, e.g. booleans). `bounds` writes min/max (required for POSITION
        and animation inputs)."""
        array = np.asarray(array)
        components = 1 if array.ndim == 1 else array.shape[1]
        if byte:
            data = np.ascontiguousarray(array, dtype="u1")
            component = UNSIGNED_BYTE
        elif array.dtype.kind == "f":
            data = np.ascontiguousarray(array, dtype="<f4")
            component = FLOAT
        elif array.size == 0 or int(array.max()) < 65535:
            data = np.ascontiguousarray(array, dtype="<u2")
            component = UNSIGNED_SHORT
        else:
            data = np.ascontiguousarray(array, dtype="<u4")
            component = UNSIGNED_INT
        accessor: dict[str, Any] = {
            "bufferView": self.buffer_view(data.tobytes(), target),
            "componentType": component,
            "count": int(data.shape[0]),
            "type": _TYPES[components],
        }
        if bounds and data.shape[0]:
            flat = data.reshape(data.shape[0], components)
            cast = float if component == FLOAT else int
            accessor["min"] = [cast(v) for v in flat.min(axis=0)]
            accessor["max"] = [cast(v) for v in flat.max(axis=0)]
        return self._append("accessors", accessor)

    def image_png(self, png: bytes, name: str) -> int:
        return self._append("images", {"bufferView": self.buffer_view(png), "mimeType": "image/png", "name": name})

    def add(self, key: str, item: dict[str, Any]) -> int:
        return self._append(key, item)

    def glb(self) -> bytes:
        doc = dict(self.json)
        while len(self.bin) % 4:
            self.bin.append(0)
        if self.bin:
            doc["buffers"] = [{"byteLength": len(self.bin)}]
        text = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        text += b" " * (-len(text) % 4)
        chunks = struct.pack("<II", len(text), 0x4E4F534A) + text
        if self.bin:
            chunks += struct.pack("<II", len(self.bin), 0x004E4942) + bytes(self.bin)
        return struct.pack("<III", 0x46546C67, 2, 12 + len(chunks)) + chunks


# --- reading (tests, previews and checks) -------------------------------------------------------

_NUMPY = {FLOAT: "<f4", UNSIGNED_SHORT: "<u2", UNSIGNED_INT: "<u4", UNSIGNED_BYTE: "u1"}


def read_glb(data: bytes) -> tuple[dict[str, Any], bytes]:
    """(JSON document, BIN chunk) of a .glb file."""
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67 or version != 2 or length != len(data):
        raise ValueError("not a glTF 2.0 binary file")
    json_length, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("the first chunk isn't JSON")
    doc = json.loads(data[20 : 20 + json_length].decode("utf-8"))
    rest = 20 + json_length
    binary = b""
    if rest < len(data):
        bin_length, bin_type = struct.unpack_from("<II", data, rest)
        if bin_type != 0x004E4942:
            raise ValueError("the second chunk isn't BIN")
        binary = data[rest + 8 : rest + 8 + bin_length]
    return doc, binary


def read_accessor(doc: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    accessor = doc["accessors"][index]
    view = doc["bufferViews"][accessor["bufferView"]]
    components = {v: k for k, v in _TYPES.items()}[accessor["type"]] if accessor["type"] in _TYPES.values() else 16
    dtype = np.dtype(_NUMPY[accessor["componentType"]])
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    array = np.frombuffer(binary, dtype=dtype, count=accessor["count"] * components, offset=start)
    return array.reshape(accessor["count"], components) if components > 1 else array


def validate(doc: dict[str, Any], binary: bytes) -> list[str]:
    """The glTF 2.0 rules PAGAN's files must meet (a subset of the Khronos validator's checks)."""
    problems: list[str] = []
    if doc.get("asset", {}).get("version") != "2.0":
        problems.append("asset.version must be 2.0")
    buffers = doc.get("buffers", [])
    if binary and (len(buffers) != 1 or buffers[0].get("byteLength", 0) > len(binary)):
        problems.append("one buffer whose byteLength fits the BIN chunk")
    sizes = {FLOAT: 4, UNSIGNED_SHORT: 2, UNSIGNED_INT: 4, UNSIGNED_BYTE: 1}
    for i, view in enumerate(doc.get("bufferViews", [])):
        if view.get("byteOffset", 0) % 4:
            problems.append(f"bufferViews[{i}] isn't 4-byte aligned")
        if view.get("byteOffset", 0) + view["byteLength"] > len(binary):
            problems.append(f"bufferViews[{i}] runs past the buffer")
    position_accessors = {
        p["attributes"]["POSITION"] for m in doc.get("meshes", []) for p in m["primitives"] if "POSITION" in p["attributes"]
    }
    input_accessors = {s["input"] for a in doc.get("animations", []) for s in a["samplers"]}
    for i, accessor in enumerate(doc.get("accessors", [])):
        view = doc["bufferViews"][accessor["bufferView"]]
        components = {v: k for k, v in _TYPES.items()}[accessor["type"]]
        needed = accessor["count"] * components * sizes[accessor["componentType"]]
        if needed > view["byteLength"]:
            problems.append(f"accessors[{i}] needs {needed} bytes, its view has {view['byteLength']}")
        if (i in position_accessors or i in input_accessors) and ("min" not in accessor or "max" not in accessor):
            problems.append(f"accessors[{i}] needs min and max")
        if "min" in accessor and accessor["count"]:
            values = read_accessor(doc, binary, i).reshape(accessor["count"], components)
            if [float(v) for v in values.min(axis=0)] != [float(v) for v in accessor["min"]] or [
                float(v) for v in values.max(axis=0)
            ] != [float(v) for v in accessor["max"]]:
                problems.append(f"accessors[{i}] min/max don't match its data")
    for m, mesh in enumerate(doc.get("meshes", [])):
        for p, primitive in enumerate(mesh["primitives"]):
            counts = {doc["accessors"][a]["count"] for a in primitive["attributes"].values()}
            if len(counts) != 1:
                problems.append(f"meshes[{m}].primitives[{p}] attributes have different counts")
            if "indices" in primitive:
                indices = read_accessor(doc, binary, primitive["indices"])
                if indices.size % 3 or (indices.size and int(indices.max()) >= min(counts)):
                    problems.append(f"meshes[{m}].primitives[{p}] indices are out of range or not triangles")
    nodes = doc.get("nodes", [])
    parents: dict[int, int] = {}
    for i, node in enumerate(nodes):
        for child in node.get("children", []):
            if child in parents or child == i or child >= len(nodes):
                problems.append(f"nodes[{i}] child {child} is invalid or has two parents")
            parents[child] = i
    for a, animation in enumerate(doc.get("animations", [])):
        for c, channel in enumerate(animation["channels"]):
            sampler = animation["samplers"][channel["sampler"]]
            times = read_accessor(doc, binary, sampler["input"])
            values = doc["accessors"][sampler["output"]]["count"]
            if sampler.get("interpolation", "LINEAR") != "CUBICSPLINE" and values != len(times):
                problems.append(f"animations[{a}].channels[{c}] has {values} values for {len(times)} times")
            if len(times) > 1 and not np.all(np.diff(times) > 0):
                problems.append(f"animations[{a}].channels[{c}] key times must increase")
    return problems
