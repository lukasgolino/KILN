"""The `kiln` command line (run in-process with --json)."""

from __future__ import annotations

import json
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

from conftest import arms_text, make_project, run_json, sphere_text, write_model
from kiln import __version__
from kiln.cli import main
from kiln.project import Project, load_project
from test_importer import box_glb


@pytest.fixture
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.strip() == f"kiln {__version__}"


def test_init_creates_a_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["init", "art", "--style", "toon"], capsys)
    assert code == 0 and result["ok"] and result["style"] == "toon"
    root = in_tmp / "art"
    for rel in ("kiln.toml", "palettes/main.pal.yaml", "BRIEF.md", "STYLE.md", ".gitignore", "models", "decals", "imports",
                "styles/toon/inspiration"):  # fmt: skip
        assert (root / rel).exists(), rel
    project = load_project(root)
    assert project.config.default_style == "toon" and project.config.default_palette == "main"
    assert "toon" in (root / "STYLE.md").read_text()
    palette, findings = project.palette()
    assert findings == [] and palette["red"] == "#e8413c"
    code, result = run_json(["init", "art"], capsys)
    assert code == 1 and result["findings"][0]["rule"] == "E000" and "already exists" in result["findings"][0]["message"]
    code, result = run_json(["init", "other", "--style", "nope"], capsys)
    assert code == 1 and "unknown style" in result["findings"][0]["message"]


def test_commands_need_a_project(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for args in (["new", "model", "x"], ["build"], ["status"], ["config", "show"]):
        code, result = run_json(args, capsys)
        assert code == 1 and "kiln init" in result["findings"][0]["message"], args


@pytest.mark.parametrize("template", ["bean", "prop", "empty"])
def test_new_model_templates_lint_clean(in_project: Project, capsys: pytest.CaptureFixture[str], template: str) -> None:
    shipped = files("kiln").joinpath("templates", "main.pal.yaml").read_text(encoding="utf-8")
    (in_project.palettes_dir / "main.pal.yaml").write_text(shipped)  # the templates use the starter palette's names
    code, result = run_json(["new", "model", "guy", "--template", template, "--description", "a guy"], capsys)
    assert code == 0 and result["model"] == "models/guy.kiln.yaml"
    text = (in_project.models_dir / "guy.kiln.yaml").read_text()
    assert "name: guy" in text and 'description: "a guy"' in text and "style_version: 1" in text
    code, result = run_json(["lint", "guy"], capsys)
    assert code == 0, result
    assert result["errors"] == 0 and result["warnings"] == 0, result["findings"]


def test_new_model_options(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run_json(["new", "model", "rock", "--class", "nature"], capsys)
    assert code == 0
    assert "class: nature" in (in_project.models_dir / "rock.kiln.yaml").read_text()
    code, result = run_json(["new", "model", "rock"], capsys)
    assert code == 1 and "--force" in result["findings"][0]["message"]
    assert run_json(["new", "model", "rock", "--force", "--template", "prop"], capsys)[0] == 0
    code, result = run_json(["new", "model", "Rock"], capsys)
    assert code == 1 and "lowercase" in result["findings"][0]["message"]


def test_lint_reports_errors_and_warnings(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, sphere_text("good").replace("at: [0, 0.3, 0]", "at: [0, 1, 0]"), "good")
    write_model(in_project, sphere_text("bad").replace("color: red", "color: mauve"), "bad")
    code, result = run_json(["lint"], capsys)
    assert code == 1 and not result["ok"]
    assert result["models"] == 2 and result["errors"] == 1 and result["warnings"] == 1
    assert sorted(f["rule"] for f in result["findings"]) == ["E004", "W106"]
    e004 = next(f for f in result["findings"] if f["rule"] == "E004")
    assert e004["line"] == 3 and e004["where"] == "parts[0].color"  # the part's line
    code, result = run_json(["lint", "good"], capsys)
    assert code == 0 and result["warnings"] == 1
    code, result = run_json(["lint", "--fast", "good"], capsys)
    assert code == 0 and result["warnings"] == 0
    code, result = run_json(["lint", "nope"], capsys)
    assert code == 1 and "no model 'nope'" in result["findings"][0]["message"]


def test_lint_human_output(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, sphere_text().replace("color: red", "color: mauve"))
    assert main(["lint"]) == 1
    out = capsys.readouterr().out
    assert out.count("models/thing.kiln.yaml:3: error E004 [parts[0].color]") == 1
    assert "1 models: 1 errors, 0 warnings" in out


def test_lint_a_file_path_in_open_mode(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = in_tmp / "thing.kiln.yaml"
    path.write_text(sphere_text().replace("color: red", "color: '#ff0000'"))
    code, result = run_json(["lint", "--fast", str(path)], capsys)
    assert code == 0 and result["models"] == 1


def test_build(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, arms_text("hero"), "hero")
    code, result = run_json(["build"], capsys)
    assert code == 0 and result["models"] == ["hero"]
    assert sorted(result["written"]) == ["build/manifest.json", "build/models/hero.glb"]
    code, result = run_json(["build"], capsys)
    assert code == 0 and result["written"] == [] and result["unchanged"] == 2
    code, result = run_json(["build", "--verify-godot"], capsys)
    assert code == 1 and "export" in result["findings"][0]["message"]
    write_model(in_project, sphere_text().replace("color: red", "color: mauve"))
    code, result = run_json(["build"], capsys)
    assert code == 1 and result["findings"][0]["rule"] == "E004"


@pytest.mark.slow
def test_preview(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, arms_text("hero") + "variants:\n  blue: { swap: { red: blue } }\n", "hero")
    code, result = run_json(["preview", "hero", "--closeup", "arm_l", "--pose", "hold", "--turntable", "--variant", "blue"], capsys)
    assert code == 0, result
    outputs = result["outputs"]
    assert outputs["turntable"] == "previews/hero/turntable.blue.png"
    assert outputs["closeup"] == {"arm_l": "previews/hero/closeup_arm_l.png"}
    assert outputs["pose"] == {"hold": "previews/hero/pose_hold.png"}
    for rel in ("previews/hero/turntable.blue.png", "previews/hero/closeup_arm_l.png", "previews/hero/pose_hold.png"):
        assert (in_project.root / rel).is_file()


def test_preview_errors(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, arms_text("hero"), "hero")
    code, result = run_json(["preview", "hero", "--closeup", "tail"], capsys)
    assert code == 1 and "no part 'tail'" in result["findings"][0]["message"]
    code, result = run_json(["preview", "hero", "--pose", "dance"], capsys)
    assert code == 1 and "no animation 'dance'" in result["findings"][0]["message"]
    code, result = run_json(["preview", "hero", "--variant", "gold"], capsys)
    assert code == 1 and "no variant 'gold'" in result["findings"][0]["message"]
    code, result = run_json(["preview", "hero", "--vs"], capsys)
    assert code == 1 and "inspiration" in result["findings"][0]["message"]
    code, result = run_json(["preview", "hero", "--engine"], capsys)
    assert code == 1 and "--engine" in result["findings"][0]["message"]
    write_model(in_project, sphere_text("bad").replace("color: red", "color: mauve"), "bad")
    code, result = run_json(["preview", "bad"], capsys)
    assert code == 1 and result["findings"][0]["rule"] == "E004"


@pytest.mark.slow
def test_lineup_and_gallery(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, sphere_text("ball"), "ball")
    write_model(in_project, arms_text("hero"), "hero")
    code, result = run_json(["lineup"], capsys)
    assert code == 0 and result["models"] == ["ball", "hero"] and (in_project.root / result["lineup"]).is_file()
    code, result = run_json(["lineup", "ball"], capsys)
    assert code == 0 and result["models"] == ["ball"]
    code, result = run_json(["gallery"], capsys)
    assert code == 0 and result["models"] == 2 and (in_project.root / result["gallery"]).is_file()


def test_status_and_mark(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, sphere_text("ball") + "description: a ball\nstyle_version: 1\n", "ball")
    write_model(in_project, sphere_text("bad").replace("color: red", "color: mauve"), "bad")
    (in_project.root / "kiln.toml").write_text((in_project.root / "kiln.toml").read_text() + "style_version = 2\n")
    code, result = run_json(["status"], capsys)
    assert code == 0 and result["style_version"] == 2
    rows = {r["name"]: r for r in result["models"]}
    assert rows["ball"] == {"name": "ball", "class": "prop", "status": "draft", "style": "fast", "style_version": 1,
                            "needs_review": True, "errors": 0, "description": "a ball"}  # fmt: skip
    assert rows["bad"]["errors"] == 1
    code, result = run_json(["mark", "ball", "--approved", "--current"], capsys)
    assert code == 0 and result["marked"] == ["ball"]
    text = (in_project.models_dir / "ball.kiln.yaml").read_text()
    assert "status: approved" in text and "style_version: 2" in text and "description: a ball" in text
    code, result = run_json(["status"], capsys)
    ball = next(r for r in result["models"] if r["name"] == "ball")
    assert ball["status"] == "approved" and not ball["needs_review"]
    code, _ = run_json(["mark", "ball", "--draft"], capsys)
    assert "status: draft" in (in_project.models_dir / "ball.kiln.yaml").read_text()
    code, result = run_json(["mark", "nope", "--approved"], capsys)
    assert code == 1


def test_mark_adds_missing_keys_after_the_name(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    write_model(in_project, "# comment\n" + sphere_text("ball"), "ball")
    assert run_json(["mark", "ball", "--approved", "--current"], capsys)[0] == 0
    lines = (in_project.models_dir / "ball.kiln.yaml").read_text().splitlines()
    assert lines[:2] == ["# comment", "name: ball"]
    assert sorted(lines[2:4]) == ["status: approved", "style_version: 1"]
    assert run_json(["lint", "ball"], capsys)[0] == 0


def test_style_list_show_new_bump(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["style", "list"], capsys)
    assert code == 0 and result["default"] == "fast"
    rows = {r["name"]: r for r in result["styles"]}
    assert rows["fast"]["project"] and not rows["soft_toy"]["project"] and "toon" in rows
    code, result = run_json(["style", "show"], capsys)
    assert code == 0 and result["style"]["name"] == "fast" and result["style"]["resolution"] == 0.03
    code, result = run_json(["style", "show", "low_poly"], capsys)
    assert code == 0 and result["style"]["smooth"] is False
    code, result = run_json(["style", "show", "nope"], capsys)
    assert code == 1 and result["findings"][0]["rule"] == "E006"
    code, result = run_json(["style", "new", "dusk", "--extends", "toon", "--description", "dusky"], capsys)
    assert code == 0 and result["style"] == "styles/dusk.style.toml"
    assert (in_project.root / "styles" / "dusk" / "inspiration").is_dir()
    code, result = run_json(["style", "show", "dusk"], capsys)
    assert code == 0 and result["style"]["description"] == "dusky" and result["style"]["shader"] == "toon"
    assert run_json(["style", "new", "dusk"], capsys)[0] == 1
    assert run_json(["style", "new", "x", "--extends", "nope"], capsys)[0] == 1
    (in_project.root / "STYLE.md").write_text("# Style\n\n## Changelog\n\n- v1: first version.\n")
    code, result = run_json(["style", "bump", "-m", "darker nights"], capsys)
    assert code == 0 and result["style_version"] == 2
    assert load_project(in_project.root).config.style_version == 2
    assert "- v2 (" in (in_project.root / "STYLE.md").read_text() and "darker nights" in (in_project.root / "STYLE.md").read_text()
    code, result = run_json(["style", "bump", "-m", "again"], capsys)
    assert result["style_version"] == 3
    assert (in_project.root / "kiln.toml").read_text().count("style_version") == 1


def test_config_show_get_set(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["config", "show"], capsys)
    assert code == 0 and result["settings"]["default_style"] == "fast" and result["settings"]["export"] == ["glb"]
    code, result = run_json(["config", "get", "default_palette"], capsys)
    assert code == 0 and result["value"] == "main"
    code, result = run_json(["config", "set", "export", '["glb", "godot"]'], capsys)
    assert code == 0 and result["old"] == ["glb"] and result["new"] == ["glb", "godot"]
    code, result = run_json(["config", "set", "output_dir", "out"], capsys)
    assert code == 0 and result["new"] == "out"
    code, result = run_json(["config", "set", "style_version", "4"], capsys)
    assert code == 0
    data = tomllib.loads((in_project.root / "kiln.toml").read_text())
    assert data["export"] == ["glb", "godot"] and data["output_dir"] == "out" and data["style_version"] == 4


def test_config_keeps_comments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    make_project(tmp_path, 'default_style = "fast"   # the look\ndefault_palette = "main"\n\n[lint]\ndisable = []\n')
    monkeypatch.chdir(tmp_path)
    assert run_json(["config", "set", "default_style", "toon"], capsys)[0] == 0
    assert run_json(["config", "set", "preview_dir", "pv"], capsys)[0] == 0
    text = (tmp_path / "kiln.toml").read_text()
    assert 'default_style = "toon"   # the look' in text
    assert text.index('preview_dir = "pv"') < text.index("[lint]")
    assert tomllib.loads(text)["lint"] == {"disable": []}


@pytest.mark.parametrize(
    ("key", "value"),
    [("export", "fbx"), ("export", "[]"), ("style_version", "0"), ("default_style", "Not A Name"), ("output_dir", '""')],
)
def test_config_set_rejects_bad_values(in_project: Project, capsys: pytest.CaptureFixture[str], key: str, value: str) -> None:
    before = (in_project.root / "kiln.toml").read_text()
    code, result = run_json(["config", "set", key, value], capsys)
    assert code == 1 and result["findings"][0]["rule"] == "E000"
    assert (in_project.root / "kiln.toml").read_text() == before


def test_config_unknown_key(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["config", "get", "colour"], capsys)
    assert code == 1 and "unknown setting" in result["findings"][0]["message"]


def test_import_and_credits(in_project: Project, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    outside = tmp_path / "downloads"
    outside.mkdir()
    box_glb(outside / "Big Crate.glb")
    code, result = run_json(["credits"], capsys)
    assert code == 0 and result["credits"] == []
    code, result = run_json(["import", str(outside / "Big Crate.glb"), "--licence", "CC0-1.0", "--author", "Kenney",
                             "--url", "https://kenney.nl", "--height", "1.2"], capsys)  # fmt: skip
    assert code == 0, result
    assert result["model"] == "models/big_crate.kiln.yaml" and result["file"] == "imports/Big Crate.glb"
    assert (in_project.root / "imports" / "Big Crate.glb").is_file()
    code, result = run_json(["lint", "big_crate"], capsys)
    assert code == 0 and result["warnings"] == 0, result["findings"]
    code, result = run_json(["credits"], capsys)
    assert result["credits"] == [{"model": "big_crate", "file": "Big Crate.glb", "licence": "CC0-1.0", "author": "Kenney", "url": "https://kenney.nl"}]
    code, result = run_json(["build"], capsys)
    assert code == 0
    manifest = json.loads((in_project.output_dir / "manifest.json").read_text())
    assert manifest["models"]["big_crate"]["size"][1] == pytest.approx(1.2)
    assert (in_project.output_dir / "CREDITS.md").is_file()
    code, result = run_json(["import", str(outside / "Big Crate.glb"), "--licence", "CC0-1.0"], capsys)
    assert code == 1 and "--force" in result["findings"][0]["message"]
    code, result = run_json(["import", str(outside / "missing.glb"), "--licence", "CC0-1.0"], capsys)
    assert code == 1 and ".glb or .gltf" in result["findings"][0]["message"]


def test_doctor(in_tmp: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, result = run_json(["doctor"], capsys)
    assert code == 0 and result["kiln"] == __version__ and "python" in result and "display" in result


def test_skill_install(in_project: Project, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shipped = sorted(item.name for item in files("kiln").joinpath("skill").iterdir() if item.name.endswith(".md"))
    code, result = run_json(["skill", "install"], capsys)
    assert code == 0 and result["skill"] == ".claude/skills/kiln" and result["files"] == shipped
    target = in_project.root / ".claude" / "skills" / "kiln"
    assert target.is_dir()
    for name in shipped:
        assert (target / name).read_text() == files("kiln").joinpath("skill", name).read_text()
    code, result = run_json(["skill", "install", "--target", str(tmp_path / "elsewhere")], capsys)
    assert code == 0 and (tmp_path / "elsewhere").is_dir()
