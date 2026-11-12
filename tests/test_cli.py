"""The `kiln` command line (run in-process with --json)."""

from __future__ import annotations

import json
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest
from conftest import arms_text, make_project, ok_model, run_json, sphere_text, write_model
from test_importer import box_glb

from kiln import __version__
from kiln.cli import main
from kiln.project import Project, load_project


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
    assert project.config.output_dir == "build" and project.config.export == ("glb",)  # not in a Godot project (#163)
    assert result["output_dir"] == "build" and result["export"] == ["glb"]
    for line in (root / "kiln.toml").read_text().splitlines():
        if line.startswith(("output_dir", "export")):
            assert line.index("#") == 31, line  # the comments stay aligned
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
    assert result["geometry"] is True
    code, result = run_json(["lint", "--fast", "good"], capsys)
    assert code == 0 and result["warnings"] == 0 and result["geometry"] is False  # (#186) it says nothing was meshed
    assert main(["lint", "--fast", "good"]) == 0
    assert "--fast: the findings that need the built model were not looked for (E009, E013, W101-W104, W106, W108-W111, W113, W120-W129, W132, W133, W135)" \
        in capsys.readouterr().out  # fmt: skip
    code, result = run_json(["lint", "--fast", "bad"], capsys)  # a failing fast lint says so too
    assert code == 1 and result["ok"] is False and result["geometry"] is False
    assert main(["lint", "--fast", "bad"]) == 1
    assert "--fast: the findings that need the built model" in capsys.readouterr().out
    assert main(["lint", "good"]) == 0
    printed = capsys.readouterr().out
    assert "were not looked for" not in printed and printed.index("static checks:") < printed.index("W106")  # (#186) static first
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
    assert outputs["pose"] == {"hold": "previews/hero/pose_hold.blue.png"}  # in the variant's colours (#219)
    for rel in ("previews/hero/turntable.blue.png", "previews/hero/closeup_arm_l.png", "previews/hero/pose_hold.blue.png"):
        assert (in_project.root / rel).is_file()


def test_preview_draft(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#222: a quick look: its own stamped sheets (previews/<name>/draft/), its own cached build (coarser cells, rough
    paint, plain hard parts), the real build's cache untouched; not where it means nothing."""
    import pickle

    from PIL import Image

    text = arms_text("hero", "soft").replace("rig:\n", "  - cylinder: { at: [0, 0.95, 0], radius: 0.1, height: 0.1 }\n    color: blue\n    bevel: 0.01\n"
                                             "  - sphere: { at: [0, 0.3, 0.3], radius: 0.12 }\n    color: red\n    pattern: { type: stripes, color: blue, size: 0.03 }\nrig:\n")  # fmt: skip
    write_model(in_project, text, "hero")
    cache = in_project.root / ".kiln-cache"
    code, result = run_json(["preview", "hero", "--draft", "--pose", "hold", "--turntable", "--closeup", "arm_l"], capsys)
    assert code == 0, result
    assert result["draft"] is True and result["outputs"]["turntable"] == "previews/hero/draft/turntable.png"
    assert result["outputs"]["pose"] == {"hold": "previews/hero/draft/pose_hold.png"}
    assert not (in_project.root / "previews/hero/turntable.png").exists()
    stamp = (120, 60, 10)  # every sheet of a draft is stamped, whatever its kind
    sheets = [result["outputs"]["turntable"], result["outputs"]["pose"]["hold"], result["outputs"]["closeup"]["arm_l"]]
    for rel in sheets:
        image = Image.open(in_project.root / rel).convert("RGB")
        assert image.getpixel((image.width - 6, 8)) == stamp, rel
    (first,) = list((cache / "draft").glob("hero.base.*.pickle"))
    assert not list(cache.glob("hero.base.*.pickle"))  # the build's cache: nothing written
    made = first.stat().st_mtime_ns
    code, result = run_json(["preview", "hero", "--draft"], capsys)  # again: the cached draft
    assert code == 0 and first.stat().st_mtime_ns == made
    with first.open("rb") as fh:
        draft = pickle.load(fh)  # noqa: S301 (our own cache file)
    code, result = run_json(["preview", "hero"], capsys)
    assert code == 0 and result["outputs"]["turntable"] == "previews/hero/turntable.png" and "draft" not in result
    real = Image.open(in_project.root / "previews/hero/turntable.png").convert("RGB")
    assert real.getpixel((real.width - 6, 8)) != stamp
    (full,) = list(cache.glob("hero.base.*.pickle"))
    with full.open("rb") as fh:
        built = pickle.load(fh)  # noqa: S301
    assert draft.model.draft and not built.model.draft and first.is_file()  # the full preview left the draft's
    assert draft.step == pytest.approx(built.step * 3) and draft.step_reason.startswith("draft: 3 x the build's")
    names = [{g.color_name for g in b.painted.groups} for b in (draft, built)]
    assert draft.triangles > 0 and {n.split("#")[0] for n in names[0]} == {n.split("#")[0] for n in names[1]}  # the same colours
    top = [int((b.painted.vertices[:, 1] > 0.89).sum()) for b in (draft, built)]  # the cylinder on top: bevelled in the build
    assert 0 < top[0] < top[1]
    write_model(in_project, text.replace("radius: 0.08", "radius: 0.09"), "hero")  # an edit: a new draft replaces the old one
    code, result = run_json(["preview", "hero", "--draft"], capsys)
    assert code == 0 and not first.exists() and len(list((cache / "draft").glob("hero.base.*.pickle"))) == 1
    for flags in (["--engine"], ["--vs"], ["--fit"], ["--effect"]):
        code, result = run_json(["preview", "hero", "--draft", *flags], capsys)
        assert code == 1 and "--draft is a quick look" in result["findings"][0]["message"], flags


def test_no_draft_of_an_imported_model(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#222 review: nothing is meshed for an imported model, so --draft says so instead of writing the same sheet."""
    from test_importer import SOURCE, box_glb

    box_glb(in_project.root / "imports" / "box.glb")
    write_model(in_project, SOURCE, "crate")
    code, result = run_json(["preview", "crate", "--draft"], capsys)
    assert code == 1 and "imported model" in result["findings"][0]["message"]
    assert not (in_project.root / "previews" / "crate" / "draft" / "turntable.png").exists()


def test_draft_paint_cuts_no_patterns(project: Project) -> None:
    """#222: a draft's smooth parts get no pattern cut into them (the build's do)."""
    from kiln.builder import field_of
    from kiln.mesher import dual_contour
    from kiln.paint import regions

    text = "name: ball\nparts:\n  - sphere: { at: [0, 0.3, 0], radius: 0.3 }\n    color: red\n    pattern: { type: stripes, color: blue, size: 0.05 }\n"
    model, _ = ok_model(project, text, "ball")
    field = field_of(model, 0.03)
    mesh = dual_contour(field, 0.03)
    full, quick = regions(mesh, model, field, False), regions(mesh, model, field, False, draft=True)
    assert full.pattern_groups and len(set(full.owner.tolist())) > 1
    assert not quick.pattern_groups and len(set(quick.owner.tolist())) == 1 and quick.mesh is mesh  # nothing cut


def test_draft_paint_keeps_a_cut_walls_colour(project: Project) -> None:
    """#222 review: in a draft each face takes its nearest part's paint, by signed distance: the wall of a cut is
    its solid's colour though a part the cut took away whole lies nearer."""
    from dataclasses import replace

    from kiln.builder import build_model

    text = "name: pit\nparts:\n  - sphere: { at: [0, 0.5, 0], radius: 0.5 }\n    color: red\n" \
           "  - sphere: { at: [0, 0.9, 0], radius: 0.08 }\n    color: blue\n" \
           "  - sphere: { at: [0, 0.95, 0], radius: 0.2 }\n    cut: true\n"
    model, style = ok_model(project, text, "pit")
    for m in (model, replace(model, draft=True)):
        built = build_model(m, style, None, {})
        used = {built.painted.groups[g].color_name for g in set(built.painted.face_group.tolist())}
        assert used == {"red"}, (m.draft, used)


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
    assert code == 0 and "description" not in result["models"][0]  # only with --verbose
    code, result = run_json(["status", "--verbose"], capsys)
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
    assert code == 0 and result["kiln"] == __version__ and "python" in result and "display" in result and "offscreen" in result


def test_skill_install(in_project: Project, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from kiln.cli import _skill_files

    shipped = _skill_files()
    stale = in_project.root / ".claude" / "skills" / "kiln" / "reference.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("the pre-0.14 reference")
    code, result = run_json(["skill", "install"], capsys)
    assert code == 0 and result["skill"] == ".claude/skills/kiln" and result["files"] == shipped
    target = in_project.root / ".claude" / "skills" / "kiln"
    assert target.is_dir() and not stale.exists() and "topics/parts.md" in shipped
    for name in shipped:
        assert (target / name).read_text() == files("kiln").joinpath("skill", *name.split("/")).read_text()
    code, result = run_json(["skill", "install", "--target", str(tmp_path / "elsewhere")], capsys)
    assert code == 0 and (tmp_path / "elsewhere").is_dir()


def test_json_after_the_command(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    from kiln.cli import main

    assert main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]


def test_closeup_by_part_number(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    from kiln.cli import main

    main(["--json", "new", "model", "crate", "--template", "empty"])
    capsys.readouterr()
    assert main(["--json", "preview", "crate", "--closeup", "0"]) == 0
    assert "0" in json.loads(capsys.readouterr().out)["outputs"]["closeup"]


def test_preview_views_pitch_and_size(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#96: a chosen set of views and pitches in one sheet, at a chosen tile size (flag or kiln.toml preview_size)."""
    from PIL import Image

    write_model(in_project, sphere_text("ball"), "ball")
    code, result = run_json(["preview", "ball", "--views", "front,34,side,back", "--pitch", "5,30", "--size", "120"], capsys)
    assert code == 0 and set(result["outputs"]) == {"views"}, result
    sheet = Image.open(in_project.root / result["outputs"]["views"])
    assert 4 * 120 < sheet.width < 4 * 120 + 200 and 2 * 120 < sheet.height < 2 * 120 + 200  # 4 x 2 tiles (title and gaps around)
    code, result = run_json(["preview", "ball", "--size", "100"], capsys)
    small = Image.open(in_project.root / result["outputs"]["turntable"]).size
    (in_project.root / "kiln.toml").write_text((in_project.root / "kiln.toml").read_text() + "preview_size = 150\n")
    code, result = run_json(["preview", "ball"], capsys)
    assert code == 0 and Image.open(in_project.root / result["outputs"]["turntable"]).width > small[0]
    for argv, text in ((["--views", "upwards"], "view 'upwards'"), (["--pitch", "95"], "between -89 and 89"), (["--size", "9"], "64-1024")):
        code, result = run_json(["preview", "ball", *argv], capsys)
        assert code == 1 and text in result["findings"][0]["message"], result


def test_preview_views_flags_on_terrains_and_config(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    land = "name: land\nterrain:\n  size: [8, 8]\n  cell: 0.5\n  chunk: 8\n  lod: []\n  splat:\n    - grass: { color: green }\n  shapes:\n    - hill: { at: [0, 0], radius: 3, height: 1 }\n"
    write_model(in_project, land, "land")
    for argv in (["--views", "front"], ["--pitch", "5"], ["--size", "200"], ["--draft"]):
        code, result = run_json(["preview", "land", *argv], capsys)
        assert code == 1 and "doesn't apply" in result["findings"][0]["message"], result
    code, result = run_json(["config", "set", "preview_size", "500"], capsys)
    assert code == 0, result
    code, result = run_json(["preview", "land"], capsys)  # a configured preview_size is harmless here
    assert code == 0, result
    code, result = run_json(["config", "set", "preview_size", "5000"], capsys)
    assert code == 1 and result["findings"][0]["where"] == "preview_size"
    code, result = run_json(["preview", "land", "--views", "nan"], capsys)
    assert code == 1


def test_pose_preview_views_size_and_frames(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#189, #201: --pose honours --views/--pitch/--size, --frame picks frames, 3/4 front + both sides by default, no
    stray views.png; frames out of range are refused before any sheet is written."""
    from conftest import arms_text, write_model
    from PIL import Image

    from kiln import preview as pv

    write_model(in_project, arms_text(), "thing")
    folder = in_project.preview_dir / "thing"
    rows: list[list[str]] = []
    real = pv.sheet
    monkey = pytest.MonkeyPatch()
    def recorded(title: str, sub: str, r: list, *a: object, **k: object) -> object:  # type: ignore[type-arg]
        rows.append([label for label, _ in r])
        return real(title, sub, r, *a, **k)  # type: ignore[arg-type]

    monkey.setattr(pv, "sheet", recorded)
    try:
        assert run_json(["preview", "thing", "--pose", "wave"], capsys)[0] == 0
        assert rows[-1] == ["3/4 front", "left side", "right side"]
        assert run_json(["preview", "thing", "--pose", "wave", "--pitch", "30"], capsys)[0] == 0
        assert rows[-1] == ["3/4 front +30", "left side +30", "right side +30"]
        code, _ = run_json(["preview", "thing", "--pose", "wave", "--views", "front", "--pitch", "10", "--size", "300", "--frame", "1"], capsys)
        assert code == 0 and rows[-1] == ["front +10"] and not (folder / "views.png").exists()
    finally:
        monkey.undo()
    one = Image.open(folder / "pose_wave.png")
    assert 300 <= one.width < 660  # one 300 px tile (sheets are at least 640 wide)
    (folder / "pose_wave.png").unlink()
    for bad in ("99", "1,99", "-1"):
        code, result = run_json(["preview", "thing", "--pose", "wave", "--frame", bad], capsys)
        assert code == 1 and "frames" in result["findings"][0]["message"] and not (folder / "pose_wave.png").exists()
    code, result = run_json(["preview", "thing", "--frame", "1"], capsys)
    assert code == 1 and "--pose" in result["findings"][0]["message"]


def test_lint_says_the_cell_size_and_why(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#223: lint names each meshed model's cell size and what set it (style or model resolution, size scaling,
    the max_cells cap)."""
    write_model(in_project, sphere_text("ball"), "ball")
    code, result = run_json(["lint", "ball"], capsys)
    assert code == 0
    cell = result["cells"]["ball"]
    assert cell["step"] == pytest.approx(0.03) and "style fast resolution 30 mm" in cell["why"]
    big = sphere_text("big").replace("radius: 0.3", "radius: 2").replace("at: [0, 0.3, 0]", "at: [0, 2, 0]")
    write_model(in_project, big.replace("parts:", "max_cells: 64\nparts:"), "big")
    code, result = run_json(["lint", "big"], capsys)
    why = result["cells"]["big"]["why"]
    assert "x sqrt(4 m, scale_with_size)" in why and "capped by max_cells 64 (model)" in why
    write_model(in_project, sphere_text("fine").replace("parts:", "resolution: 0.02\nparts:"), "fine")
    assert main(["lint", "fine"]) == 0
    assert "mm mesh cells (model resolution 20 mm)" in capsys.readouterr().out


def test_cell_size_reason_from_a_style_cap_a_stale_cache_and_build(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#223: a style's max_cells cap is named as the style's; a build cached before builds kept the reason still says
    it; kiln build's per-model line says it too."""
    import pickle

    (in_project.root / "styles" / "capped.style.toml").write_text('extends = "fast"\n\n[shape]\nmax_cells = 64\n')
    big = sphere_text("big").replace("radius: 0.3", "radius: 2").replace("at: [0, 0.3, 0]", "at: [0, 2, 0]")
    write_model(in_project, big.replace("parts:", "style: capped\nparts:"), "big")
    code, result = run_json(["lint", "big"], capsys)
    assert code == 0 and result["cells"]["big"]["capped"]
    assert "capped by max_cells 64 (style capped) across 4 m" in result["cells"]["big"]["why"]
    cached = list((in_project.root / ".kiln-cache").glob("big.*.pickle"))
    assert cached
    for path in cached:  # as cached by an older build
        built = pickle.loads(path.read_bytes())
        built.step_reason = ""
        path.write_bytes(pickle.dumps(built))
    code, result = run_json(["lint", "big"], capsys)
    assert "capped by max_cells 64 (style capped)" in result["cells"]["big"]["why"]
    assert main(["build", "big"]) == 0
    assert "mm mesh cells (style capped resolution 30 mm x sqrt(4 m, scale_with_size); capped by" in capsys.readouterr().out


def test_the_fast_lints_list_of_skipped_rules_is_the_built_checks_rules() -> None:
    """#186: every rule geometry_warnings can give is in BUILT_RULES (what --fast says it skipped), plus E009."""
    import inspect
    import re

    from kiln import lint

    given = set(re.findall(r'"([EW]\d{3})"', inspect.getsource(lint.geometry_warnings)))
    assert given and given | {"E009"} == set(lint.BUILT_RULES)


def test_preview_draft_under_a_big_budget(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#299: a hero budget above the draft mesh's face count (nothing to reduce) was E009 from the simplifier."""
    text = arms_text("hero", "soft").replace("name: hero\n", "name: hero\nbudget: 60000\n").replace("    blend: 0.04\n", "    blend: 0.04\n    density: 2\n")
    write_model(in_project, text, "hero")
    code, result = run_json(["preview", "hero", "--draft", "--views", "front", "--size", "64"], capsys)
    assert code == 0, result


def test_lint_and_build_report_the_same_findings(in_project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    """#210: build reports what lint reports (the same checks on the same cached mesh), E013 included."""
    write_model(in_project, sphere_text("good").replace("at: [0, 0.3, 0]", "at: [0, 1, 0]"), "good")  # W106
    write_model(in_project, arms_text("hero", "soft"), "hero")
    write_model(in_project, "name: crate\nparts:\n  - box: { at: [0, 0.2, 0], size: [0.4, 0.4, 0.4] }\n    color: red\n    hard: true\n"
                "    bevel: 0.02\n  - box: { at: [0, 0.4, 0], size: [0.3, 0.05, 0.3] }\n    color: blue\n    hard: true\n", "crate")  # (hard parts, coplanar contact)
    code, linted = run_json(["lint"], capsys)
    assert code == 0, linted
    code, built = run_json(["build"], capsys)
    key = lambda f: (f["rule"], f.get("path"), f.get("where"), f["message"])  # noqa: E731
    assert sorted(map(key, linted["findings"])) == sorted(map(key, built["findings"]))
