"""CC0 packs: recipes, mirroring (from file:// archives made here: no test touches the network), index, search,
`kiln pack import` and the kiln.lock checks in lint/build."""

from __future__ import annotations

import hashlib
import json
import socket
import zipfile
from pathlib import Path
from typing import Any

import pytest

from conftest import run_json, sphere_text, write_model
from kiln import packs
from kiln.packs import PackError, Recipe
from kiln.project import Project
from kiln.vendor.gltf import read_glb
from test_importer import box_glb

LICENCE = "Some Pack (1.0)\n\nLicense: (Creative Commons Zero, CC0)\nhttp://creativecommons.org/publicdomain/zero/1.0/\n"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Fail any internet connection (unix sockets stay: lint's process pool uses them); the pack cache in tmp."""
    real = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> None:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            raise AssertionError(f"a test tried to reach the network: {address}")
        real(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    cache = tmp_path / "cache"
    monkeypatch.setenv(packs.CACHE_ENV, str(cache))
    return cache


def make_archive(tmp: Path, licence: str = LICENCE, extra: dict[str, bytes] | None = None) -> Path:
    """A pack zip as GitHub serves them (one top folder): two glbs, a .gltf with its .bin, a .gltf naming a shared
    texture by name only (Quaternius), one whose .bin is missing, a licence file and files outside the models folder."""
    src = tmp / "src"
    src.mkdir()
    crate = box_glb(src / "crate.glb").read_bytes()
    doc, binary = read_glb(crate)
    doc["buffers"][0]["uri"] = "barrel.bin"
    gltf = json.dumps(doc).encode()
    doc2 = json.loads(gltf)
    doc2["images"] = [{"uri": "colormap.png"}]
    doc2["buffers"][0]["uri"] = "sign.bin"
    doc3 = json.loads(gltf)
    doc3["buffers"][0]["uri"] = "nothing.bin"
    files = {
        "Pack-abc/models/Props/crate.glb": crate,
        "Pack-abc/models/Props/Crate_Big.glb": crate,
        "Pack-abc/models/Props/barrel.gltf": gltf,
        "Pack-abc/models/Props/barrel.bin": binary,
        "Pack-abc/models/Signs/sign_post.gltf": json.dumps(doc2).encode(),
        "Pack-abc/models/Signs/sign.bin": binary,
        "Pack-abc/models/Signs/broken.gltf": json.dumps(doc3).encode(),
        "Pack-abc/Textures/colormap.png": b"\x89PNG not really",
        "Pack-abc/LICENSE.txt": licence.encode(),
        "Pack-abc/fbx/crate.fbx": b"not kept",
        **(extra or {}),
    }
    path = tmp / "pack.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def recipe_for(archive: Path, **over: Any) -> Recipe:
    data: dict[str, Any] = {"name": "test-pack", "version": "1.0", "url": archive.as_uri(), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                            "licence": "CC0-1.0", "author": "Someone", "homepage": "https://example.org/pack", "strip": 1, "models": "models",
                            "licence_file": "LICENSE.txt", "textures": "Textures", "tags": ["Town"], **over}  # fmt: skip
    return packs.parse_recipe({k: v for k, v in data.items() if v is not None})


def recipe_file(path: Path, recipe: Recipe) -> Path:
    lines = []
    for k, v in recipe.to_dict().items():
        lines.append(f"{k} = {json.dumps(v)}")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_shipped_recipes_are_cc0_pinned_and_parse() -> None:
    recipes = packs.builtin_recipes()
    assert {r.source for r in recipes.values()} == {"kenney", "kaykit", "quaternius"}
    for r in recipes.values():
        assert r.licence == "CC0-1.0" and r.sha256 and r.licence_file and r.url.startswith("https://") and r.homepage.startswith("https://")
        assert packs.load_recipe(r.name) == r == packs.load_recipe(r.key)
    with pytest.raises(PackError, match="no pack"):
        packs.load_recipe("synty-anything")
    with pytest.raises(PackError, match="ships as version"):
        packs.load_recipe(f"{next(iter(recipes))}@0.0")


@pytest.mark.parametrize(("over", "message"), [
    ({"licence": "CC-BY-4.0"}, "must be CC0-1.0"),
    ({"name": "Bad Name"}, "name is"),
    ({"url": "ftp://x"}, "url is"),
    ({"sha256": "abc"}, "sha256"),
    ({"models": "../up"}, "path inside"),
    ({"strip": -1}, "strip"),
    ({"colour": "red"}, "unknown field"),
])  # fmt: skip
def test_bad_recipes(over: dict[str, Any], message: str) -> None:
    with pytest.raises(PackError, match=message):
        packs.parse_recipe({"name": "p", "version": "1", "url": "https://x/p.zip", **over})


def test_cache_location(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert packs.cache_root() == tmp_path / "cache"
    monkeypatch.delenv(packs.CACHE_ENV)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    assert packs.cache_root() == tmp_path / "xdg" / "kiln" / "packs"
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    assert packs.cache_root() == tmp_path / "home" / ".cache" / "kiln" / "packs"


def test_add_mirrors_and_indexes(tmp_path: Path, no_network: Path) -> None:
    recipe = recipe_for(make_archive(tmp_path))
    mirror, fetched = packs.add(recipe)
    assert fetched and mirror.path == no_network / "test-pack@1.0"
    kept = sorted(p.relative_to(mirror.path / "files").as_posix() for p in (mirror.path / "files").rglob("*") if p.is_file())
    assert kept == ["LICENSE.txt", "models/Props/Crate_Big.glb", "models/Props/barrel.bin", "models/Props/barrel.gltf", "models/Props/crate.glb",
                    "models/Signs/broken.gltf", "models/Signs/colormap.png", "models/Signs/sign.bin", "models/Signs/sign_post.gltf"]  # fmt: skip
    by_path = {e["path"]: e for e in mirror.models}
    assert list(by_path) == sorted(by_path)
    crate = by_path["Props/crate.glb"]
    assert crate["name"] == "crate" and crate["tags"] == ["props", "town"] and crate["triangles"] == 12 and crate["size"] == [1.0, 1.0, 1.0]
    assert by_path["Props/barrel.gltf"]["bytes"] == sum((mirror.models_dir / "Props" / f).stat().st_size for f in ("barrel.gltf", "barrel.bin"))
    assert by_path["Signs/sign_post.gltf"]["tags"] == ["signs", "town"] and "triangles" in by_path["Signs/sign_post.gltf"]
    assert "nothing.bin" in by_path["Signs/broken.gltf"]["error"] and "triangles" not in by_path["Signs/broken.gltf"]
    # kept unless forced; forced: byte-identical index (deterministic)
    index = (mirror.path / "index.json").read_bytes()
    assert packs.add(recipe)[1] is False
    assert packs.add(recipe, force=True)[1] is True
    assert (mirror.path / "index.json").read_bytes() == index
    assert [m.key for m in packs.mirrors()] == ["test-pack@1.0"]


def test_add_checks_the_hash_and_the_licence(tmp_path: Path, no_network: Path) -> None:
    archive = make_archive(tmp_path)
    with pytest.raises(PackError, match="sha256"):
        packs.add(recipe_for(archive, sha256="0" * 64))
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(PackError, match="doesn't say CC0"):
        packs.add(recipe_for(make_archive(other, licence="All rights reserved")))
    with pytest.raises(PackError, match="no LICENCE.md"):
        packs.add(recipe_for(archive, licence_file="LICENCE.md"))
    assert packs.mirrors() == [] and not [p for p in no_network.iterdir() if not p.name.startswith(".add-")]
    assert not list(no_network.glob(".add-*"))  # temporary download folders are removed


def test_add_refuses_unsafe_archives(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="unsafe path"):
        packs.add(recipe_for(make_archive(tmp_path, extra={"Pack-abc/models/../../evil.glb": b"x"})))
    with pytest.raises(PackError, match="not a zip|isn't a zip"):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"html login page")
        packs.add(recipe_for(bad))


def test_add_uses_the_fetcher(tmp_path: Path) -> None:
    archive = make_archive(tmp_path)
    seen: list[str] = []

    def fetch(url: str, dest: Path) -> None:
        seen.append(url)
        dest.write_bytes(archive.read_bytes())

    packs.add(recipe_for(archive, url="https://example.org/pack.zip"), fetch=fetch)
    assert seen == ["https://example.org/pack.zip"]


def test_search(tmp_path: Path) -> None:
    packs.add(recipe_for(make_archive(tmp_path)))

    def names(terms: list[str], pack: str | None = None) -> list[str]:
        return [str(h.entry["name"]) for h in packs.search(terms, pack)]

    assert names(["crate"]) == ["crate", "Crate_Big"]  # the whole name, then a word of it
    assert names(["CRATE", "big"]) == ["Crate_Big"]  # every term must match
    assert names(["signs"]) == ["broken", "sign_post"]  # a folder (category) tag
    assert names(["town", "barrel"]) == ["barrel"]
    assert names(["knight"]) == [] and names(["crate"], pack="other") == []
    assert len(names([])) == 5 and names(["crate"], pack="test-pack@1.0") == ["crate", "Crate_Big"]


def test_cli_add_search_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rfile = recipe_file(tmp_path / "my-pack.toml", recipe_for(make_archive(tmp_path)))
    code, result = run_json(["pack", "add", str(rfile)], capsys)
    assert code == 0 and result["fetched"] and result["models"] == 5 and result["unreadable"] == 1
    code, result = run_json(["pack", "search", "crate", "--limit", "1"], capsys)
    assert code == 0 and result["total"] == 2 and [h["path"] for h in result["hits"]] == ["Props/crate.glb"]
    assert result["hits"][0]["triangles"] == 12 and result["hits"][0]["pack"] == "test-pack"
    code, result = run_json(["pack", "list"], capsys)
    rows = {r["pack"]: r for r in result["packs"]}
    assert rows["test-pack"]["mirrored"] and not rows["test-pack"]["shipped"]
    assert all(r["shipped"] and not r["mirrored"] for k, r in rows.items() if k != "test-pack")
    code, result = run_json(["pack", "add", "no-such-pack"], capsys)
    assert code == 1 and "no pack" in result["findings"][0]["message"]


def test_search_lineup(tmp_path: Path, in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    packs.add(recipe_for(make_archive(tmp_path)))
    code, result = run_json(["pack", "search", "crate", "--lineup"], capsys)
    assert code == 0 and result["lineup"] == "previews/pack-search.png" and (in_project.root / "previews/pack-search.png").is_file()


def test_pack_import_lock_build_and_credits(tmp_path: Path, in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    root = in_project.root
    packs.add(recipe_for(make_archive(tmp_path)))
    code, result = run_json(["pack", "import", "test-pack", "sign_post", "--height", "1.5"], capsys)
    assert code == 0 and result["model"] == "models/sign_post.kiln.yaml"
    assert result["locked"] == ["imports/test-pack/colormap.png", "imports/test-pack/sign.bin", "imports/test-pack/sign_post.gltf"]
    lock = json.loads((root / "kiln.lock").read_text())["files"]
    entry = lock["imports/test-pack/sign_post.gltf"]
    assert entry["pack"] == "test-pack" and entry["version"] == "1.0" and entry["licence"] == "CC0-1.0" and entry["file"] == "models/Signs/sign_post.gltf"
    assert entry["sha256"] == hashlib.sha256((root / "imports/test-pack/sign_post.gltf").read_bytes()).hexdigest() and entry["url"].startswith("file://")
    text = (root / "models/sign_post.kiln.yaml").read_text()
    assert "file: imports/test-pack/sign_post.gltf" in text and "licence: CC0-1.0" in text and '"https://example.org/pack"' in text
    # an existing model, or a broken pack entry, is refused; --force replaces
    assert run_json(["pack", "import", "test-pack", "sign_post"], capsys)[0] == 1
    assert "nothing.bin" in run_json(["pack", "import", "test-pack", "broken"], capsys)[1]["findings"][0]["message"]
    assert "ambiguous" not in run_json(["pack", "import", "test-pack", "Props/crate.glb"], capsys)[1].get("findings", [{}])[0].get("message", "")
    code, result = run_json(["build"], capsys)
    assert code == 0, result
    assert "from pack test-pack@1.0" in (in_project.output_dir / "CREDITS.md").read_text()
    manifest = json.loads((in_project.output_dir / "manifest.json").read_text())
    assert manifest["models"]["sign_post"]["source"]["pack"] == "test-pack@1.0" and "pack" in manifest["models"]["crate"]["source"]
    code, result = run_json(["credits"], capsys)
    assert {r["model"]: r.get("pack") for r in result["credits"]} == {"crate": "test-pack@1.0", "sign_post": "test-pack@1.0"}
    # a changed file fails the build (E014), as does a licence the lock doesn't have
    (root / "imports/test-pack/sign.bin").write_bytes(b"changed")
    code, result = run_json(["build"], capsys)
    assert code == 1 and ("E014", "imports/test-pack/sign.bin") in [(f["rule"], f["where"]) for f in result["findings"]]
    assert run_json(["pack", "import", "test-pack", "sign_post", "--force"], capsys)[0] == 0
    assert run_json(["build"], capsys)[0] == 0
    path = root / "models/sign_post.kiln.yaml"
    path.write_text(path.read_text().replace("licence: CC0-1.0", "licence: CC-BY-4.0"))
    code, result = run_json(["lint", "--fast"], capsys)
    assert code == 1 and [(f["rule"], f["where"]) for f in result["findings"]] == [("E014", "source.licence")]
    path.write_text(path.read_text().replace("licence: CC-BY-4.0", "licence: CC0-1.0"))
    # a lock entry that isn't CC0 is an error; a listed file that's gone is a warning
    data = json.loads((root / "kiln.lock").read_text())
    data["files"]["imports/test-pack/crate.glb"]["licence"] = "CC-BY-NC-4.0"
    data["files"]["imports/test-pack/gone.glb"] = {**data["files"]["imports/test-pack/sign.bin"], "file": "models/gone.glb"}
    (root / "kiln.lock").write_text(json.dumps(data))
    code, result = run_json(["lint", "--fast"], capsys)
    assert code == 1 and sorted((f["rule"], f["where"]) for f in result["findings"]) == [
        ("E014", "imports/test-pack/crate.glb"), ("E014", "source.licence"), ("W115", "imports/test-pack/gone.glb")]  # crate's model: CC0 != the lock's
    (root / "kiln.lock").write_text("{not json")
    code, result = run_json(["lint", "--fast"], capsys)
    assert code == 1 and result["findings"][0]["rule"] == "E014" and "isn't a KILN lock file" in result["findings"][0]["message"]


def test_projects_without_a_lock_are_unchanged(tmp_path: Path, in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """Local `kiln import` writes no lock and gets no lock checks; its model file is what it always was."""
    box = box_glb(tmp_path / "box.glb")
    code, _ = run_json(["import", str(box), "--licence", "CC-BY-4.0", "--author", "Someone", "--height", "1"], capsys)
    assert code == 0 and not (in_project.root / "kiln.lock").exists()
    assert (in_project.root / "models/box.kiln.yaml").read_text() == (
        'name: box\ndescription: "imported from box.glb"\nclass: prop\nstatus: draft\nstyle_version: 1\nsource:\n  file: imports/box.glb\n'
        '  licence: CC-BY-4.0\n  author: "Someone"\n  url: ""\nprocess:\n  height: 1.0\n'
        "  recolor: auto           # snap colours to the project palette (keep = the file's own colours)\n"
    )
    write_model(in_project, sphere_text("ball"), "ball")
    code, result = run_json(["build"], capsys)
    assert code == 0 and not any(f["rule"] in ("E014", "W115") for f in result["findings"])
    credits = (in_project.output_dir / "CREDITS.md").read_text()
    assert "- **box**: box.glb by Someone, licence CC-BY-4.0\n" in credits and "pack" not in credits
    assert "pack" not in json.loads((in_project.output_dir / "manifest.json").read_text())["models"]["box"]["source"]


def test_mcp_pack_tools(tmp_path: Path, project: Project) -> None:
    pytest.importorskip("mcp")
    from test_mcp import call

    packs.add(recipe_for(make_archive(tmp_path)))
    result, images = call(project, "pack_search", {"terms": ["barrel"], "lineup": True})
    assert result["ok"] and [h["name"] for h in result["hits"]] == ["barrel"] and images == 1
    result, _ = call(project, "pack_import", {"pack": "test-pack", "model": "barrel", "height": 1.0})
    assert result["ok"] and result["locked"] == ["imports/test-pack/barrel.bin", "imports/test-pack/barrel.gltf"]
    result, _ = call(project, "pack_list")
    assert any(r["pack"] == "test-pack" and r["mirrored"] for r in result["packs"])
