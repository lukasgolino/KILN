"""Compares demo builds from different machines (#27, measure only): which files differ from the reference build and,
for .glb files, which accessors (by mesh/attribute) differ and by how much. Writes a Markdown report. Used by the
`cross-machine` workflow; it always exits 0 (it measures, it doesn't gate).

Run from the repo root: `python tools/compare_builds.py REF_NAME=REF_DIR NAME=DIR [NAME=DIR ...] [--out report.md]`.
"""

from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from kiln.gltf_check import accessor
from kiln.vendor.gltf import read_glb

TEXT = {".json", ".tscn", ".tres", ".import", ".gd", ".txt", ".cfg", ".md"}
DIFF_LINES = 12


@dataclass
class AccessorDiff:
    label: str
    count: int = 0  # differing values (components, not elements)
    total: int = 0
    max_abs: float = 0.0
    note: str = ""  # set when the accessors can't be compared value by value


@dataclass
class GlbDiff:
    json_same: bool = True
    json_keys: list[str] = field(default_factory=list)  # top-level keys whose JSON (minus accessors) differs
    accessors: list[AccessorDiff] = field(default_factory=list)
    note: str = ""


def accessor_labels(doc: dict[str, Any]) -> dict[int, str]:
    """Readable names for accessors: `mesh 'body' p0 POSITION`, `skin 0 inverseBindMatrices`, ..."""
    labels: dict[int, str] = {}
    for m, mesh in enumerate(doc.get("meshes", [])):
        name = mesh.get("name", str(m))
        for p, prim in enumerate(mesh.get("primitives", [])):
            for attr, index in prim.get("attributes", {}).items():
                labels.setdefault(index, f"mesh '{name}' p{p} {attr}")
            if "indices" in prim:
                labels.setdefault(prim["indices"], f"mesh '{name}' p{p} indices")
            for t, target in enumerate(prim.get("targets", [])):
                for attr, index in target.items():
                    labels.setdefault(index, f"mesh '{name}' p{p} target{t} {attr}")
    for s, skin in enumerate(doc.get("skins", [])):
        if "inverseBindMatrices" in skin:
            labels.setdefault(skin["inverseBindMatrices"], f"skin '{skin.get('name', s)}' inverseBindMatrices")
    for a, anim in enumerate(doc.get("animations", [])):
        name = anim.get("name", str(a))
        targets = {
            ch["sampler"]: f"{ch['target'].get('node')}.{ch['target'].get('path')}" for ch in anim.get("channels", [])
        }
        for s, sampler in enumerate(anim.get("samplers", [])):
            labels.setdefault(sampler["input"], f"anim '{name}' times")
            labels.setdefault(sampler["output"], f"anim '{name}' {targets.get(s, s)}")
    for i in range(len(doc.get("accessors", []))):
        labels.setdefault(i, f"accessor {i}")
    return labels


def _structure(doc: dict[str, Any]) -> dict[str, Any]:
    """The document without the accessors and buffer layout, whose differences the accessor comparison reports."""
    return {k: v for k, v in doc.items() if k not in ("accessors", "bufferViews", "buffers")}


def compare_glb(a: bytes, b: bytes) -> GlbDiff:
    """How glb `b` differs from glb `a`."""
    out = GlbDiff()
    try:
        doc_a, bin_a = read_glb(a)
        doc_b, bin_b = read_glb(b)
    except ValueError as exc:
        out.note = f"unreadable: {exc}"
        return out
    sa, sb = _structure(doc_a), _structure(doc_b)
    out.json_keys = sorted(k for k in set(sa) | set(sb) if sa.get(k) != sb.get(k))
    out.json_same = not out.json_keys and doc_a.get("accessors") == doc_b.get("accessors")
    acc_a, acc_b = doc_a.get("accessors", []), doc_b.get("accessors", [])
    if len(acc_a) != len(acc_b):
        out.note = f"{len(acc_a)} vs {len(acc_b)} accessors"
        return out
    labels = accessor_labels(doc_a)
    for i, (x, y) in enumerate(zip(acc_a, acc_b)):
        label = labels[i]
        layout = ("count", "type", "componentType")
        if any(x.get(k) != y.get(k) for k in layout):
            shape = ", ".join(f"{k} {x.get(k)} vs {y.get(k)}" for k in layout if x.get(k) != y.get(k))
            out.accessors.append(AccessorDiff(label, note=shape))
            continue
        va = accessor(doc_a, bin_a, i).astype(np.float64)
        vb = accessor(doc_b, bin_b, i).astype(np.float64)
        differs = va != vb
        n = int(np.count_nonzero(differs))
        if n:
            delta = np.abs(va - vb)
            out.accessors.append(AccessorDiff(label, count=n, total=int(va.size), max_abs=float(delta.max())))
    return out


def text_summary(a: bytes, b: bytes) -> str:
    """A short unified diff of two text files (first lines only, with the number of changed lines)."""
    lines = list(
        difflib.unified_diff(
            a.decode("utf-8", "replace").splitlines(), b.decode("utf-8", "replace").splitlines(), lineterm="", n=0
        )
    )
    changed = sum(1 for line in lines if line[:1] in "+-" and not line.startswith(("+++", "---")))
    body = "\n".join(lines[2 : 2 + DIFF_LINES]) + ("\n..." if len(lines) > 2 + DIFF_LINES else "")
    return f"{changed} changed lines\n\n```diff\n{body}\n```"


def files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def describe(rel: str, a: bytes, b: bytes) -> str:
    """Markdown details for one differing file."""
    if rel.endswith(".glb"):
        d = compare_glb(a, b)
        parts = [f"glb sizes {len(a)} vs {len(b)} bytes"]
        if d.note:
            parts.append(d.note)
        if d.json_keys:
            parts.append("JSON differs in: " + ", ".join(d.json_keys))
        if d.accessors:
            rows = ["| accessor | differing values | max abs diff |", "|---|---|---|"]
            for x in d.accessors:
                rows.append(
                    f"| {x.label} | {x.note} |  |" if x.note else f"| {x.label} | {x.count}/{x.total} | {x.max_abs:.3g} |"
                )
            parts.append("\n".join(rows))
        elif not d.note:
            parts.append("all accessor values equal (bytes differ elsewhere)")
        return "\n\n".join(parts)
    if Path(rel).suffix in TEXT:
        return text_summary(a, b)
    return f"binary, sizes {len(a)} vs {len(b)} bytes"


def report(builds: list[tuple[str, Path]]) -> str:
    """Markdown report comparing every build with the first one."""
    (ref_name, ref), others = builds[0], builds[1:]
    ref_files = files(ref)
    names = sorted(ref_files.union(*(files(d) for _, d in others)))
    status: dict[tuple[str, str], str] = {}
    details: list[str] = []
    for name, root in others:
        for rel in names:
            pa, pb = ref / rel, root / rel
            if not pa.is_file() or not pb.is_file():
                status[rel, name] = "missing here" if pa.is_file() else "extra here"
                continue
            a, b = pa.read_bytes(), pb.read_bytes()
            if a == b:
                status[rel, name] = "identical"
                continue
            status[rel, name] = "**different**"
            details.append(f"#### `{rel}`: {ref_name} vs {name}\n\n{describe(rel, a, b)}\n")
    differing = sum(1 for v in status.values() if v != "identical")
    out = [
        "## Cross-machine build comparison (#27)",
        "",
        f"Reference: **{ref_name}**. {len(names)} files; {differing} file/machine pairs not identical.",
        "",
        "| file | " + " | ".join(n for n, _ in others) + " |",
        "|---|" + "---|" * len(others),
    ]
    out += [f"| `{rel}` | " + " | ".join(status[rel, n] for n, _ in others) + " |" for rel in names]
    if details:
        out += ["", "### Differences", "", *details]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    out_path: Path | None = None
    builds: list[tuple[str, Path]] = []
    args = iter(argv)
    for arg in args:
        if arg == "--out":
            out_path = Path(next(args))
        else:
            name, _, path = arg.partition("=")
            builds.append((name, Path(path)))
    try:
        missing = [n for n, p in builds if not p.is_dir()]
        text = report([(n, p) for n, p in builds if p.is_dir()]) if len(builds) - len(missing) >= 2 else ""
        if missing:
            text = f"Missing builds (job failed or artifact absent): {', '.join(missing)}\n\n" + text
    except Exception as exc:  # measure only: never fail the workflow
        text = f"comparison failed: {exc!r}\n"
    print(text)
    if out_path is not None:
        out_path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
