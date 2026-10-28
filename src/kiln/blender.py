"""Optional Blender for .fbx/.blend/.obj imports: the `blender` binary (on PATH or `BLENDER=`, any 4.x) exports the
file as a glb, which then takes the normal glb import path. Nothing else in KILN needs Blender.

The glb is cached in `<project>/.kiln-cache/blender/<key>/<stem>.glb`, keyed on the source's sha256 (and, for .obj,
its .mtl files and their texture maps), the Blender version and `SCRIPT_VERSION`, so a rebuild doesn't run Blender
again. Blender's glTF exporter gives the same bytes run to run for the same input and version (tested).
"""

from __future__ import annotations

import functools
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

CONVERT_SUFFIXES = (".fbx", ".blend", ".obj")
SCRIPT_VERSION = 1  # bump when SCRIPT's export changes (it's in the cache key)
MIN_MAJOR = 4
TIMEOUT = 600.0
TAIL = 15  # lines of Blender's output in a failure message

# Runs inside Blender: argv after "--" is (source, glb). +Y up (glTF), modifiers applied, skins, animations, the
# active vertex colours; textures as they come (AUTO keeps PNG/JPEG).
SCRIPT = r"""
import sys
import bpy

src, out = sys.argv[sys.argv.index("--") + 1 :][:2]
ext = src.rsplit(".", 1)[-1].lower()
if ext == "blend":
    bpy.ops.wm.open_mainfile(filepath=src, load_ui=False)
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if ext == "fbx":
        bpy.ops.import_scene.fbx(filepath=src)
    else:
        bpy.ops.wm.obj_import(filepath=src)
props = {p.identifier for p in bpy.ops.export_scene.gltf.get_rna_type().properties}
kw = dict(filepath=out, export_format="GLB", export_yup=True, export_apply=True, export_skins=True,
          export_animations=True, export_image_format="AUTO")
if "export_vertex_color" in props:  # 4.2+
    kw["export_vertex_color"] = "ACTIVE"
elif "export_colors" in props:  # 4.0, 4.1
    kw["export_colors"] = True
bpy.ops.export_scene.gltf(**kw)
"""

HOW = "install Blender 4.x and put `blender` on PATH or set BLENDER=/path/to/blender (or convert the file to .glb yourself)"


class BlenderError(ValueError):
    pass


def needs_blender(path: Path) -> bool:
    return path.suffix.lower() in CONVERT_SUFFIXES


def find_blender() -> str | None:
    candidate = os.environ.get("BLENDER")
    if candidate:
        return candidate
    return shutil.which("blender")


@functools.cache
def blender_version(binary: str) -> str | None:
    """'4.2.3' from `blender --version`, None if it doesn't run."""
    try:
        run = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Blender (\d+\.\d+(?:\.\d+)?)", run.stdout)
    return match.group(1) if match else None


def _sidecars(path: Path) -> list[Path]:
    """Files an .obj pulls in that change its glb: its .mtl files and their texture maps."""
    if path.suffix.lower() != ".obj":
        return []
    out: list[Path] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("mtllib "):
            mtl = path.parent / line[7:].strip()
            if mtl.is_file():
                out.append(mtl)
                for mline in mtl.read_text(encoding="utf-8", errors="replace").splitlines():
                    words = mline.split()
                    if words and words[0].lower().startswith(("map_", "bump", "disp", "norm")) and len(words) > 1:
                        tex = mtl.parent / words[-1]
                        if tex.is_file():
                            out.append(tex)
    return out


def cache_key(path: Path, version: str) -> str:
    h = hashlib.sha256()
    h.update(f"{version}\n{SCRIPT_VERSION}\n".encode())
    h.update(hashlib.sha256(path.read_bytes()).digest())
    for extra in _sidecars(path):
        h.update(extra.name.encode() + hashlib.sha256(extra.read_bytes()).digest())
    return h.hexdigest()[:32]


def _tail(text: str) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return "\n".join(lines[-TAIL:])


def converted(path: Path, cache_dir: Path) -> Path:
    """The glb Blender exports for `path` (.fbx/.blend/.obj), from the cache when it's there."""
    binary = find_blender()
    if binary is None:
        raise BlenderError(f"{path.name}: .fbx/.blend/.obj imports need Blender, which wasn't found: {HOW}")
    version = blender_version(binary)
    if version is None:
        raise BlenderError(f"{path.name}: {binary} doesn't run as Blender (`{binary} --version` failed): {HOW}")
    if int(version.split(".")[0]) < MIN_MAJOR:
        raise BlenderError(f"{path.name}: Blender {version} is too old for KILN's glTF export: {HOW}")
    out = cache_dir / "blender" / cache_key(path, version) / f"{path.stem}.glb"
    if out.is_file():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".glb", dir=out.parent)  # parallel lint workers: rename is atomic
    os.close(fd)
    tmp = Path(tmp_name)
    cmd = [binary, "-b", "--factory-startup", "--disable-autoexec", "--python-exit-code", "1", "--python-expr", SCRIPT, "--", str(path), str(tmp)]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        tmp.unlink(missing_ok=True)
        raise BlenderError(f"{path.name}: Blender didn't run: {exc}") from exc
    if run.returncode != 0 or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        tail = _tail(run.stderr) or _tail(run.stdout)
        raise BlenderError(f"{path.name}: Blender {version} couldn't convert it to glb (exit {run.returncode}):\n{tail}")
    tmp.replace(out)
    return out


__all__ = ["CONVERT_SUFFIXES", "SCRIPT_VERSION", "BlenderError", "blender_version", "cache_key", "converted", "find_blender", "needs_blender"]
