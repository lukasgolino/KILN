"""CC0 asset packs: recipes shipped with KILN (`kiln/recipes/*.toml`), mirrored into a per-user cache shared between
games, indexed (file name, the pack's tags and folders, triangles, size) and searched; `kiln.lock` in a project records
every file it imported from a pack (pack, version, URL, sha256, licence) so builds can check them.

Only `add` (an explicit `kiln pack add`) touches the network; search, import and builds read the local cache.
Mirror layout: `<cache>/<pack>@<version>/files/...` (the archive's model folder, its licence file and the textures the
models refer to), `pack.json` (the recipe and the archive's sha256), `index.json` (one entry per model, sorted).
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
import tomllib
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any

from kiln import __version__
from kiln.vendor.findings import Finding

CC0 = "CC0-1.0"
LOCK_NAME = "kiln.lock"
CACHE_ENV = "KILN_PACK_CACHE"
MODEL_SUFFIXES = (".glb", ".gltf")
MAX_UNPACKED = 4 << 30  # bytes: refuse archives that unpack to more (zip bombs)
PACK_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RECIPE_FIELDS = ("name", "version", "title", "source", "author", "homepage", "url", "sha256", "licence", "licence_file", "strip", "models",
                 "textures", "tags")  # fmt: skip
CC0_MARKERS = ("CC0", "publicdomain/zero")
NOT_TAGS = {"gltf", "glb", "models", "assets", "gltf format", "glb format"}  # folder names that say nothing about a model


class PackError(ValueError):
    pass


@dataclass(frozen=True)
class Recipe:
    """How to get one pack: where its archive is (and its sha256), its licence, and what to keep from it."""

    name: str
    version: str
    url: str
    licence: str = CC0
    title: str = ""
    source: str = ""  # kenney, kaykit, quaternius
    author: str = ""
    homepage: str = ""
    sha256: str | None = None
    licence_file: str | None = None  # in the archive (after strip): must say CC0
    strip: int = 0  # leading folders to drop from archive paths
    models: str = ""  # the folder holding the models; folders below it are categories (tags)
    textures: str | None = None  # a shared texture folder: copied next to the models that refer to its files by name
    tags: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {k: getattr(self, k) for k in RECIPE_FIELDS}
        out["tags"] = list(self.tags)
        return {k: v for k, v in out.items() if v is not None}


def _safe_rel(value: str) -> bool:
    return not value.startswith("/") and "\\" not in value and ".." not in value.split("/") and ":" not in value


def parse_recipe(data: dict[str, Any], where: str = "recipe") -> Recipe:
    unknown = sorted(set(data) - set(RECIPE_FIELDS))
    if unknown:
        raise PackError(f"{where}: unknown field(s) {', '.join(unknown)}; allowed: {', '.join(RECIPE_FIELDS)}")
    name, version, url = data.get("name"), data.get("version"), data.get("url")
    if not isinstance(name, str) or not PACK_NAME_RE.match(name):
        raise PackError(f"{where}: name is lower-case letters, digits and dashes (kenney-mini-dungeon)")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise PackError(f"{where}: version is letters, digits, dots, dashes (1.0)")
    if not isinstance(url, str) or not url.startswith(("https://", "http://", "file://")):
        raise PackError(f"{where}: url is the archive's https:// (or file://) address")
    licence = data.get("licence", CC0)
    if licence != CC0:
        raise PackError(f"{where}: licence is {licence!r}; packs must be {CC0} (other licences need credits and checks KILN doesn't make)")
    sha = data.get("sha256")
    if sha is not None and (not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha)):
        raise PackError(f"{where}: sha256 is 64 lower-case hex digits")
    strip = data.get("strip", 0)
    if not isinstance(strip, int) or isinstance(strip, bool) or strip < 0:
        raise PackError(f"{where}: strip is a whole number of leading folders (0, 1, ...)")
    texts = {k: data.get(k) for k in ("title", "source", "author", "homepage", "licence_file", "models", "textures")}
    for k, v in texts.items():
        if v is not None and not isinstance(v, str):
            raise PackError(f"{where}: {k} is text")
    for k in ("licence_file", "models", "textures"):
        v = texts[k]
        if v and not _safe_rel(v):
            raise PackError(f"{where}: {k} is a path inside the archive (no '..', no leading '/')")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) and t for t in tags):
        raise PackError(f"{where}: tags is a list of words")
    return Recipe(name, version, url, licence, str(texts["title"] or ""), str(texts["source"] or ""), str(texts["author"] or ""),
                  str(texts["homepage"] or ""), sha, texts["licence_file"] or None, strip, str(texts["models"] or "").strip("/"),
                  (texts["textures"] or "").strip("/") or None, tuple(t.lower() for t in tags))  # fmt: skip


def builtin_recipes() -> dict[str, Recipe]:
    out = {}
    for item in sorted(files("kiln").joinpath("recipes").iterdir(), key=lambda i: i.name):
        if item.name.endswith(".toml"):
            recipe = parse_recipe(tomllib.loads(item.read_text(encoding="utf-8")), item.name)
            out[recipe.name] = recipe
    return out


def load_recipe(spec: str) -> Recipe:
    """A shipped recipe by name (`name` or `name@version`), or a recipe file (`path/to/pack.toml`)."""
    if spec.endswith(".toml"):
        path = Path(spec)
        if not path.is_file():
            raise PackError(f"{spec}: no such recipe file")
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise PackError(f"{spec}: {exc}") from None
        return parse_recipe(data, spec)
    name, _, version = spec.partition("@")
    recipes = builtin_recipes()
    if name not in recipes:
        raise PackError(f"no pack {name!r}; shipped packs: {', '.join(recipes)} (or give a recipe file: my-pack.toml)")
    if version and recipes[name].version != version:
        raise PackError(f"{name} ships as version {recipes[name].version}, not {version}")
    return recipes[name]


def cache_root() -> Path:
    """Where mirrors live: $KILN_PACK_CACHE, else $XDG_CACHE_HOME/kiln/packs, else ~/.cache/kiln/packs."""
    if os.environ.get(CACHE_ENV):
        return Path(os.environ[CACHE_ENV]).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base).expanduser() / "kiln" / "packs"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


Fetcher = Callable[[str, Path], None]


def download(url: str, dest: Path) -> None:
    """The one network access in KILN (`kiln pack add`)."""
    request = urllib.request.Request(url, headers={"User-Agent": f"kiln/{__version__}"})
    with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as out:  # noqa: S310 (recipes are http(s)/file)
        shutil.copyfileobj(response, out, 1 << 20)


@dataclass
class Mirror:
    recipe: Recipe
    path: Path
    archive_sha256: str
    models: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.recipe.key

    @property
    def models_dir(self) -> Path:
        return self.path / "files" / self.recipe.models if self.recipe.models else self.path / "files"

    def file(self, entry: dict[str, Any]) -> Path:
        return self.models_dir / str(entry["path"])


def _extract(recipe: Recipe, archive: Path, dest: Path) -> None:
    from kiln.importer import external_files

    prefix = f"{recipe.models}/" if recipe.models else ""
    tex_prefix = f"{recipe.textures}/" if recipe.textures else None
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile:
        raise PackError(f"{recipe.key}: the download isn't a zip archive") from None
    textures: dict[str, zipfile.ZipInfo] = {}
    with zf:
        total = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            parts = info.filename.split("/")
            if len(parts) <= recipe.strip:
                continue
            rel = "/".join(parts[recipe.strip :])
            if not _safe_rel(rel):
                raise PackError(f"{recipe.key}: unsafe path in the archive: {info.filename}")
            if tex_prefix and rel.startswith(tex_prefix) and "/" not in rel[len(tex_prefix) :]:
                textures[rel[len(tex_prefix) :]] = info
            if not (rel.startswith(prefix) or rel == recipe.licence_file):
                continue
            total += info.file_size
            if total > MAX_UNPACKED:
                raise PackError(f"{recipe.key}: the archive unpacks to more than {MAX_UNPACKED >> 30} GB")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
        if recipe.licence_file:
            lic = dest / recipe.licence_file
            if not lic.is_file():
                raise PackError(f"{recipe.key}: the archive has no {recipe.licence_file} (the recipe's licence_file)")
            text = lic.read_text(encoding="utf-8", errors="replace")
            if not any(m in text for m in CC0_MARKERS):
                raise PackError(f"{recipe.key}: {recipe.licence_file} doesn't say CC0; not mirroring it")
        root = dest / recipe.models if recipe.models else dest
        if not root.is_dir():
            raise PackError(f"{recipe.key}: the archive has no folder {recipe.models or '(root)'} (the recipe's models)")
        if textures:  # shared textures (Quaternius' Textures/) copied next to the models that use them
            for model in sorted(p for p in root.rglob("*") if p.suffix.lower() in MODEL_SUFFIXES):
                for uri in external_files(model):
                    target = model.parent / uri
                    if target.exists() or not _safe_rel(uri) or Path(uri).name not in textures:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(textures[Path(uri).name]) as src, target.open("wb") as out:
                        shutil.copyfileobj(src, out, 1 << 20)


def index_models(recipe: Recipe, models_dir: Path) -> list[dict[str, Any]]:
    """One entry per .glb/.gltf below `models_dir`, sorted by path: name, tags (the recipe's and the folders it sits
    in), triangles, size (file units, the scene's box), bytes (with the buffers and textures it refers to), sha256."""
    from kiln.importer import external_files, mesh_summary

    out = []
    for path in sorted((p for p in models_dir.rglob("*") if p.is_file() and p.suffix.lower() in MODEL_SUFFIXES), key=lambda p: p.relative_to(models_dir).as_posix()):
        rel = path.relative_to(models_dir).as_posix()
        folders = [f.lower() for f in rel.split("/")[:-1] if f.lower() not in NOT_TAGS]
        name = path.name
        while Path(name).suffix.lower() in MODEL_SUFFIXES:  # KayKit's chair.gltf.glb
            name = name[: -len(Path(name).suffix)]
        entry: dict[str, Any] = {"path": rel, "name": name, "tags": sorted(set(recipe.tags) | set(folders)), "sha256": sha256_file(path)}
        try:
            extra = external_files(path)
            missing = [u for u in extra if not (path.parent / u).is_file()]
            if missing:
                raise PackError(f"refers to {', '.join(missing)}, which isn't in the pack")
            triangles, size = mesh_summary(path)
            entry["triangles"] = triangles
            entry["size"] = [round(float(s), 4) for s in size]
            entry["bytes"] = path.stat().st_size + sum((path.parent / u).stat().st_size for u in extra)
        except (ValueError, KeyError, IndexError, OSError, TypeError) as exc:
            entry["error"] = str(exc) or type(exc).__name__
        out.append(entry)
    return out


def _dump(data: Any) -> str:
    return json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def add(recipe: Recipe, fetch: Fetcher = download, force: bool = False, root: Path | None = None) -> tuple[Mirror, bool]:
    """Mirror a pack into the cache (download, check sha256 and licence, unpack, index). (mirror, whether it was
    fetched now); an existing mirror is kept unless `force`."""
    root = root or cache_root()
    target = root / recipe.key
    if not force:
        existing = read_mirror(target)
        if existing is not None:
            return existing, False
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=".add-") as tmp:
        archive = Path(tmp) / "archive.zip"
        try:
            fetch(recipe.url, archive)
        except OSError as exc:
            raise PackError(f"{recipe.key}: download of {recipe.url} failed: {exc}") from None
        digest = sha256_file(archive)
        if recipe.sha256 and digest != recipe.sha256:
            raise PackError(f"{recipe.key}: {recipe.url} has sha256 {digest}, the recipe pins {recipe.sha256}: the upstream file changed "
                            "(check it and update the recipe) or the download is broken")  # fmt: skip
        staging = Path(tmp) / "mirror"
        _extract(recipe, archive, staging / "files")
        models = index_models(recipe, staging / "files" / recipe.models if recipe.models else staging / "files")
        (staging / "pack.json").write_text(_dump({"recipe": recipe.to_dict(), "archive_sha256": digest}), encoding="utf-8")
        (staging / "index.json").write_text(_dump({"pack": recipe.name, "version": recipe.version, "models": models}), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    mirror = read_mirror(target)
    assert mirror is not None
    return mirror, True


def read_mirror(path: Path) -> Mirror | None:
    try:
        pack = json.loads((path / "pack.json").read_text(encoding="utf-8"))
        index = json.loads((path / "index.json").read_text(encoding="utf-8"))
        recipe = parse_recipe(dict(pack["recipe"]), str(path / "pack.json"))
        return Mirror(recipe, path, str(pack["archive_sha256"]), list(index["models"]))
    except (OSError, ValueError, KeyError, TypeError, PackError):
        return None


def mirrors(root: Path | None = None) -> list[Mirror]:
    root = root or cache_root()
    if not root.is_dir():
        return []
    found = (read_mirror(p) for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith("."))
    return [m for m in found if m is not None]


def find_mirror(spec: str, root: Path | None = None) -> Mirror:
    """A mirrored pack by `name` or `name@version`."""
    name, _, version = spec.partition("@")
    found = [m for m in mirrors(root) if m.recipe.name == name and (not version or m.recipe.version == version)]
    if not found:
        raise PackError(f"pack {spec} isn't mirrored; `kiln pack add {spec}` first (`kiln pack list` shows what is)")
    if len(found) > 1:
        raise PackError(f"several versions of {name} are mirrored ({', '.join(m.key for m in found)}): name one, e.g. {found[-1].key}")
    return found[0]


def find_model(mirror: Mirror, model: str) -> dict[str, Any]:
    """A model in a mirror by its path in the index or by its (unique) file name, with or without extension."""
    want = model.lower()
    for key in ("path", "name"):
        hits = [e for e in mirror.models if str(e[key]).lower() == want or (key == "path" and Path(str(e[key])).name.lower() == want)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise PackError(f"{model} is ambiguous in {mirror.key}: {', '.join(str(e['path']) for e in hits)}")
    raise PackError(f"{mirror.key} has no model {model!r} (`kiln pack search --pack {mirror.recipe.name}` lists them)")


@dataclass(frozen=True)
class Hit:
    mirror: Mirror
    entry: dict[str, Any]
    score: int

    def to_dict(self) -> dict[str, Any]:
        e = self.entry
        out = {"pack": self.mirror.recipe.name, "version": self.mirror.recipe.version, "path": e["path"], "name": e["name"], "tags": e["tags"],
               "score": self.score, "file": str(self.mirror.file(e))}  # fmt: skip
        out.update({k: e[k] for k in ("triangles", "size", "bytes", "error") if k in e})
        return out


def _term_score(term: str, entry: dict[str, Any]) -> int:
    name = str(entry["name"]).lower()
    if term == name:
        return 4
    if term in re.split(r"[^a-z0-9]+", name):
        return 3
    if term in name:
        return 2
    return 1 if any(term in t for t in entry["tags"]) else 0


def search(terms: list[str], pack: str | None = None, root: Path | None = None) -> list[Hit]:
    """Models whose file name or tags contain every term (case-insensitive), best first: the whole name scores 4, a
    word of it 3, part of it 2, a tag 1. No terms: every model."""
    words = [t.lower() for term in terms for t in term.split() if t]
    hits = []
    for m in mirrors(root):
        if pack and pack not in (m.recipe.name, m.key):
            continue
        for e in m.models:
            scores = [_term_score(t, e) for t in words]
            if all(scores):
                hits.append(Hit(m, e, sum(scores)))
    return sorted(hits, key=lambda h: (-h.score, h.mirror.key, str(h.entry["path"])))


# --- kiln.lock ------------------------------------------------------------------------------------------------

LOCK_KEYS = ("pack", "version", "url", "sha256", "licence", "file")


def read_lock(project_root: Path) -> dict[str, dict[str, str]] | None:
    """kiln.lock's files (project-relative path -> pack, version, url, sha256, licence, file in the pack), None
    without a lock. Raises PackError if it can't be read."""
    path = project_root / LOCK_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data["files"]
        if not isinstance(entries, dict):
            raise TypeError
        out = {}
        for rel, e in entries.items():
            if not isinstance(e, dict) or any(not isinstance(e.get(k), str) for k in LOCK_KEYS):
                raise PackError(f"{LOCK_NAME}: entry {rel} needs {', '.join(LOCK_KEYS)} (text)")
            out[str(rel)] = {k: str(e[k]) for k in LOCK_KEYS}
        return out
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, PackError):
            raise
        raise PackError(f"{LOCK_NAME} isn't a KILN lock file ({type(exc).__name__}: {exc}); restore it from version control") from None


def write_lock(project_root: Path, entries: dict[str, dict[str, str]]) -> None:
    (project_root / LOCK_NAME).write_text(_dump({"lock_version": 1, "files": dict(sorted(entries.items()))}), encoding="utf-8")


def lock_findings(project_root: Path, sources: list[tuple[Path, Path, str]]) -> list[Finding]:
    """kiln.lock checks: every listed file must still have its sha256 (E014) and be CC0 (E014); a model whose source is a
    locked file must keep the lock's licence (E014); a listed file that's gone is W115. `sources` = (model file,
    source file, source licence) per imported model. Files without a lock entry (`kiln import` of local files) aren't
    checked. No kiln.lock: no findings."""
    lock_path = project_root / LOCK_NAME
    try:
        lock = read_lock(project_root)
    except PackError as exc:
        return [Finding("E014", str(exc), lock_path)]
    if lock is None:
        return []
    out = []
    for rel, e in sorted(lock.items()):
        if e["licence"] != CC0:
            out.append(Finding("E014", f"{rel} is licensed {e['licence']} in the lock; pack imports must be {CC0}: remove the model and its files", lock_path, None, rel))
        path = project_root / rel
        if not _safe_rel(rel) or not path.is_file():
            out.append(Finding("W115", f"{rel} is in the lock (from {e['pack']}@{e['version']}) but not in the project: re-import it, or remove its "
                               "entry from kiln.lock", lock_path, None, rel))  # fmt: skip
            continue
        if sha256_file(path) != e["sha256"]:
            out.append(Finding("E014", f"{rel} changed since it was imported from {e['pack']}@{e['version']} (sha256 differs): restore it, or re-import "
                               f"the model using it with `kiln pack import {e['pack']}@{e['version']} <model> --force`", lock_path, None, rel))  # fmt: skip
    root = project_root.resolve()
    for model_path, source, licence in sources:
        try:
            rel = source.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        if rel in lock and licence != lock[rel]["licence"]:
            out.append(Finding("E014", f"source licence is {licence} but {rel} came from {lock[rel]['pack']}@{lock[rel]['version']} as "
                               f"{lock[rel]['licence']}: use {lock[rel]['licence']}", model_path, None, "source.licence"))  # fmt: skip
    return out


def locked_pack(project_root: Path, source: Path) -> str | None:
    """`pack@version` a model's source file came from, if kiln.lock lists it (None without a lock or entry)."""
    try:
        lock = read_lock(project_root)
        rel = source.resolve().relative_to(project_root.resolve()).as_posix()
    except (PackError, ValueError):
        return None
    if lock is None or rel not in lock:
        return None
    return f"{lock[rel]['pack']}@{lock[rel]['version']}"


def copy_into_project(project_root: Path, mirror: Mirror, entry: dict[str, Any], force: bool = False) -> tuple[Path, dict[str, dict[str, str]]]:
    """Copy a mirrored model and the files it refers to into `imports/<pack>/` (keeping their relative folders) and
    record them in kiln.lock. Returns (the model file, the lock entries written). An existing different file is an
    error unless `force`."""
    from kiln.importer import external_files

    if "error" in entry:
        raise PackError(f"{entry['path']} in {mirror.key} can't be imported: {entry['error']}")
    src = mirror.file(entry)
    dest_dir = project_root / "imports" / mirror.recipe.name
    pack_root = mirror.path / "files"
    copies = [(src, dest_dir / src.name)]
    for uri in external_files(src):
        if not _safe_rel(posixpath.normpath(uri)) or posixpath.normpath(uri).startswith("../"):
            raise PackError(f"{entry['path']} refers to {uri}, outside its folder; import it by hand with `kiln import`")
        copies.append((src.parent / uri, dest_dir / uri))
    lock = read_lock(project_root) or {}
    written = {}
    for a, b in copies:
        digest = sha256_file(a)
        if b.is_file() and sha256_file(b) != digest and not force:
            raise PackError(f"{b.relative_to(project_root).as_posix()} already exists with other content (use --force to replace it)")
        rel = b.relative_to(project_root).as_posix()
        written[rel] = {"pack": mirror.recipe.name, "version": mirror.recipe.version, "url": mirror.recipe.url, "sha256": digest,
                        "licence": mirror.recipe.licence, "file": a.relative_to(pack_root).as_posix()}  # fmt: skip
    for a, b in copies:
        b.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a, b)
    lock.update(written)
    write_lock(project_root, lock)
    return copies[0][1], written


__all__ = ["CACHE_ENV", "CC0", "LOCK_NAME", "Hit", "Mirror", "PackError", "Recipe", "add", "builtin_recipes", "cache_root", "copy_into_project", "download",
           "find_mirror", "find_model", "index_models", "load_recipe", "lock_findings", "locked_pack", "mirrors", "parse_recipe", "read_lock", "read_mirror",
           "search", "sha256_file", "write_lock"]  # fmt: skip
