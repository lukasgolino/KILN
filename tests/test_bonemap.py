"""#21: `godot_bonemap = true` (opt-in): humanoids get a Godot BoneMap on SkeletonProfileHumanoid in their glb's
`.import`, so Godot renames their bones to the profile's; turning it off again takes it back out."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from conftest import arms_text, make_project, write_model
from kiln.build import build
from kiln.godot import find_godot_binary, verify, with_bone_map
from kiln.project import Project, load_project, parse_config
from test_build import GODOT_CONFIG, PROJECT_GODOT
from test_retarget import HERO, KAYKIT

RES = "res://assets/kiln/models/thing.bonemap.tres"
GODOT_WROTE = """\
[remap]

importer="scene"
importer_version=1
type="PackedScene"
uid="uid://hr8b31a75fso"
path="res://.godot/imported/thing.glb-0123.scn"

[deps]

source_file="res://assets/kiln/models/thing.glb"
dest_files=["res://.godot/imported/thing.glb-0123.scn"]

[params]

nodes/root_type=""
animation/fps=30
_subresources={}
gltf/naming_version=2
"""
MAPPED = """_subresources={
"nodes": {
"PATH:Skeleton3D": {
"retarget/bone_map": Resource("res://assets/kiln/models/thing.bonemap.tres")
}
}
}"""
OTHERS = """_subresources={
"materials": {
"red": {
"use_external/enabled": true,
"use_external/path": "res://red.tres"
}
},
"nodes": {
"PATH:Skeleton3D": {
"rest_pose/load_pose": 1,
"retarget/bone_map": Resource("uid://abc", "res://mine.tres")
}
}
}"""


def test_with_bone_map_merges_into_godots_import_settings() -> None:
    on = with_bone_map(GODOT_WROTE, RES, True)
    assert on == GODOT_WROTE.replace("_subresources={}", MAPPED)  # the rest (uid, Godot's settings) stays
    assert with_bone_map(on, RES, True) is None  # already there
    assert with_bone_map(on.replace(f'Resource("{RES}")', f'Resource("uid://xyz", "{RES}")'), RES, True) is None  # as Godot writes it
    assert with_bone_map(on, RES, False) == GODOT_WROTE  # off again: back to what it was
    assert with_bone_map(GODOT_WROTE, RES, False) is None
    # other sub-resource settings stay; someone else's bone map is replaced when on, left alone when off
    others = GODOT_WROTE.replace("_subresources={}", OTHERS)
    assert with_bone_map(others, RES, False) is None
    mine = with_bone_map(others, RES, True)
    assert mine == others.replace('Resource("uid://abc", "res://mine.tres")', f'Resource("{RES}")')
    kept = with_bone_map(mine, RES, False)
    assert kept is not None and '"rest_pose/load_pose": 1\n}' in kept and '"use_external/path": "res://red.tres"' in kept
    assert "bone_map" not in kept
    # no _subresources line yet (a sidecar KILN wrote): added to [params]
    bare = '[remap]\n\nimporter="scene"\ntype="PackedScene"\n\n[params]\n\n'
    assert with_bone_map(bare, RES, True) == bare + MAPPED + "\n"
    later = GODOT_WROTE.replace("_subresources={}\n", "") + "\n[other]\n\nx=1\n"
    added = with_bone_map(later, RES, True)
    assert added is not None and added.index(MAPPED) < added.index("[other]") and added.endswith("[other]\n\nx=1\n")
    assert with_bone_map(GODOT_WROTE.replace("_subresources={}", "_subresources={\n"), RES, True) is None  # unreadable: left alone


def humanoid_project(root: Path, extra: str = "") -> Project:
    project = make_project(root, GODOT_CONFIG + extra)
    (root / "game").mkdir(exist_ok=True)
    (root / "game" / "project.godot").write_text(PROJECT_GODOT)
    for name in ("Rig_Medium_General.glb", "Rig_Medium_MovementBasic.glb"):
        shutil.copy(KAYKIT / name, root / "imports" / name)
    write_model(project, HERO)
    return project


def flag(project: Project, on: bool) -> Project:
    config = project.root / "kiln.toml"
    text = config.read_text().replace("godot_bonemap = true\n", "")
    config.write_text(text + ("godot_bonemap = true\n" if on else ""))
    return load_project(project.root)


def test_bonemap_is_opt_in_and_reversible(tmp_path: Path) -> None:
    project = humanoid_project(tmp_path)
    models = project.output_dir / "models"
    first = build(project)
    assert first.errors == []
    assert not (models / "thing.bonemap.tres").exists() and not (models / "thing.glb.import").exists()  # off: nothing
    assert "godot_bonemap" not in first.manifest["models"]["thing"]
    sidecar = models / "thing.glb.import"
    sidecar.write_text(GODOT_WROTE)  # what Godot writes on import
    again = build(project)
    assert again.written == [] and sidecar.read_text() == GODOT_WROTE  # off: untouched

    on = build(flag(project, True))
    assert on.errors == []
    tres = (models / "thing.bonemap.tres").read_text()
    assert tres.startswith('[gd_resource type="BoneMap" format=3]\n\n[sub_resource type="SkeletonProfileHumanoid" id="SkeletonProfileHumanoid_kiln"]\n')
    assert "uid" not in tres
    for line in ('bone_map/Root = &"root"', 'bone_map/Hips = &"hips"', 'bone_map/LeftUpperLeg = &"upperleg_l"', 'bone_map/RightHand = &"hand_r"'):
        assert line + "\n" in tres
    assert "LeftToes" not in tres  # no toes on this model
    assert sidecar.read_text() == GODOT_WROTE.replace("_subresources={}", MAPPED)
    assert on.manifest["models"]["thing"]["godot_bonemap"] == "models/thing.bonemap.tres"
    assert "models/thing.bonemap.tres" in on.manifest["files"]
    assert build(load_project(project.root)).written == []  # idempotent

    off = build(flag(project, False))
    assert models / "thing.bonemap.tres" in off.removed
    assert not (models / "thing.bonemap.tres").exists() and sidecar.read_text() == GODOT_WROTE
    assert "godot_bonemap" not in off.manifest["models"]["thing"]


def test_bonemap_only_for_humanoid_skeletons(tmp_path: Path) -> None:
    project = make_project(tmp_path, GODOT_CONFIG + "godot_bonemap = true\n")
    (tmp_path / "game").mkdir()
    (tmp_path / "game" / "project.godot").write_text(PROJECT_GODOT)
    write_model(project, arms_text("blob", skin="soft"), "blob")  # a skeleton, not a humanoid
    write_model(project, HERO.replace("name: thing", "name: stiff").replace("animations:", "skin: rigid\nanimations:").split("animations:\n")[0], "stiff")
    result = build(project)
    assert result.errors == [] and not list(project.output_dir.rglob("*.tres")) and not list(project.output_dir.rglob("*.import"))
    outside = make_project(tmp_path / "plain", 'default_style = "fast"\ndefault_palette = "main"\ngodot_bonemap = true\n')  # no Godot project
    write_model(outside, HERO.split("animations:\n")[0])
    assert build(outside).errors == [] and not list(outside.output_dir.rglob("*.tres"))
    findings = parse_config(tomllib.loads('godot_bonemap = "yes"\n'), None)[1]
    assert any("godot_bonemap is true" in f.message for f in findings)


PROBE = """extends SceneTree
# one line: the glb's skeleton (path, bones with parents and world positions mid-clip); a carrier's track paths
func _init() -> void:
	var args := OS.get_cmdline_user_args()
	var scene: Node3D = (load(args[0]) as PackedScene).instantiate()
	root.add_child(scene)
	var sk: Skeleton3D = scene.find_children("*", "Skeleton3D", true, false)[0]
	var ap: AnimationPlayer = scene.find_children("*", "AnimationPlayer", true, false)[0]
	ap.play(args[1])
	ap.seek(float(args[2]), true)
	var bones := []
	for i in sk.get_bone_count():
		var p := sk.global_transform * sk.get_bone_global_pose(i).origin
		bones.append({"name": sk.get_bone_name(i), "parent": sk.get_bone_parent(i), "at": [p.x, p.y, p.z]})
	var library: AnimationLibrary = load(args[3])
	var walk := library.get_animation(&"walk")
	var tracks := []
	for t in walk.get_track_count():
		tracks.append(str(walk.track_get_path(t)))
	print("PROBE ", JSON.stringify({"skeleton": str(scene.get_path_to(sk)), "bones": bones, "tracks": tracks}))
	quit()
"""


def probe(godot: str, game: Path) -> dict[str, Any]:
    # Godot notices a changed .import by its modification time in whole seconds: one rewritten within the second of
    # the last import (only in a test this fast) would be skipped
    for sidecar in game.rglob("*.glb.import"):
        stamp = sidecar.stat().st_mtime + 2
        os.utime(sidecar, (stamp, stamp))
    (game / "probe.gd").write_text(PROBE)
    subprocess.run([godot, "--headless", "--path", str(game), "--import"], capture_output=True, text=True, timeout=300)
    run = subprocess.run([godot, "--headless", "--path", str(game), "-s", "probe.gd", "--", "res://assets/kiln/models/thing.glb", "walk", "0.4",
                          "res://assets/kiln/models/anims.glb"], capture_output=True, text=True, timeout=300)  # fmt: skip
    line = next((ln for ln in run.stdout.splitlines() if ln.startswith("PROBE ")), None)
    assert line is not None, run.stdout[-2000:] + run.stderr[-2000:]
    data: dict[str, Any] = json.loads(line[len("PROBE ") :])
    return data


@pytest.mark.slow
@pytest.mark.skipif(find_godot_binary() is None, reason="needs a Godot 4 binary (GODOT=/path)")
def test_godot_renames_the_bones_and_still_plays_the_clips(tmp_path: Path) -> None:
    project = humanoid_project(tmp_path)
    carrier = HERO.replace("name: thing", "name: anims") + "animations_only: true\n"  # a humanoid clip carrier too
    write_model(project, carrier, "anims")
    write_model(project, HERO.replace("name: thing", "name: user").split("animations:\n")[0] + "animation_library: anims\n", "user")
    godot = find_godot_binary()
    assert godot is not None
    game = tmp_path / "game"
    assert build(project).errors == []
    plain = probe(godot, game)
    on = build(flag(project, True))
    assert on.errors == [] and on.godot_root is not None
    mapped = probe(godot, game)
    names = {b["name"] for b in mapped["bones"]}
    assert {"Root", "Hips", "Spine", "Chest", "Head", "LeftUpperLeg", "RightLowerArm", "LeftFoot"} <= names
    assert "kiln_skeleton" in names and "hips" not in names  # unmapped bones keep their names
    # same skeleton (count, hierarchy), and the clip puts every bone where it did before
    assert [b["parent"] for b in mapped["bones"]] == [b["parent"] for b in plain["bones"]]
    profile = {"root": "Root", **{k: v["godot"] for k, v in on.manifest["models"]["thing"]["humanoid"].items()}}
    before = {profile.get(b["name"], b["name"]): b["at"] for b in plain["bones"]}
    for bone in mapped["bones"]:
        assert bone["at"] == pytest.approx(before[bone["name"]], abs=1e-3), bone["name"]
    assert mapped["skeleton"] != plain["skeleton"]  # Godot renames the skeleton node too (GeneralSkeleton)
    assert any(t.endswith(":Hips") for t in mapped["tracks"]) and not any(t.endswith(":hips") for t in mapped["tracks"])
    check = verify(godot, on.godot_root, "res://assets/kiln/manifest.json")
    assert check.ok, check.output[-3000:]
    assert build(load_project(project.root)).written == []  # Godot's rewritten sidecars still have it
    off = build(flag(project, False))
    assert off.errors == [] and not list(game.rglob("*.bonemap.tres"))
    back = probe(godot, game)
    assert [b["name"] for b in back["bones"]] == [b["name"] for b in plain["bones"]] and back["tracks"] == plain["tracks"]
