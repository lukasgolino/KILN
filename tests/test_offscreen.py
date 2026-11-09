"""#160: engine renders never use the desktop display."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kiln import godot


def _linux(monkeypatch: pytest.MonkeyPatch, tools: tuple[str, ...] = ("xvfb-run", "xauth"), lavapipe: str | None = "/icd/lvp_icd.json") -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}" if name in tools else None)
    monkeypatch.setattr(godot, "_lavapipe", lambda: lavapipe)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("KILN_OFFSCREEN", raising=False)


def test_xvfb_without_the_desktop_display(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch)
    result = godot.offscreen_command(512)
    assert isinstance(result, godot.Offscreen)
    assert result.prefix == ["/usr/bin/xvfb-run", "-a", "-s", "-screen 0 512x512x24"] and result.godot_args == []
    assert "DISPLAY" not in result.env and "WAYLAND_DISPLAY" not in result.env
    assert result.env["LIBGL_ALWAYS_SOFTWARE"] == "1" and result.env["VK_ICD_FILENAMES"] == "/icd/lvp_icd.json"
    assert "lavapipe" in result.how


def test_no_lavapipe_uses_opengl_on_llvmpipe(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, lavapipe=None)
    result = godot.offscreen_command()
    assert isinstance(result, godot.Offscreen) and result.godot_args == ["--rendering-driver", "opengl3"]
    assert "VK_ICD_FILENAMES" not in result.env and "llvmpipe" in result.how


@pytest.mark.parametrize(("tools", "missing"), [((), "xvfb-run"), (("xvfb-run",), "xauth")])
def test_missing_tools_refuse_instead_of_a_window(monkeypatch: pytest.MonkeyPatch, tools: tuple[str, ...], missing: str) -> None:
    _linux(monkeypatch, tools)
    result = godot.offscreen_command()
    assert isinstance(result, str) and missing in result and "never opens a window" in result


def test_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, ())
    monkeypatch.setenv("KILN_OFFSCREEN", "'/opt/my tools/xvfb.sh' --quiet")
    result = godot.offscreen_command()
    assert isinstance(result, godot.Offscreen) and result.prefix == ["/opt/my tools/xvfb.sh", "--quiet"] and "DISPLAY" not in result.env
    monkeypatch.setenv("KILN_OFFSCREEN", "window")
    result = godot.offscreen_command()
    assert isinstance(result, godot.Offscreen) and result.prefix == [] and result.env["DISPLAY"] == ":0" and "KILN_OFFSCREEN=window" in result.how


def test_render_engine_refuses_without_launching(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _linux(monkeypatch, ())
    (tmp_path / "project.godot").write_text("config_version=5\n")
    launched: list[object] = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: launched.append(a))
    images, output = godot.render_engine("godot", tmp_path, "res://m.tscn", "res://l.tscn", [(0.0, 0.0)], 1.0, (0.0, 0.5, 0.0), 64, tmp_path / "out")
    assert images == [] and "xvfb-run" in output and launched == []


@pytest.mark.parametrize(("env", "expect"), [({}, "lavapipe"), ({"KILN_OFFSCREEN": "window"}, "current display")])
def test_doctor_says_how(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: dict[str, str], expect: str) -> None:
    from kiln.cli import main

    _linux(monkeypatch)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert main(["doctor"]) == 0
    assert expect in capsys.readouterr().out


def test_engine_preview_takes_views_pitch_size_and_framing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                            capsys: pytest.CaptureFixture[str]) -> None:  # fmt: skip
    """#162: --engine honours --views/--pitch/--size, frames like the software views, and composites on the tile colour."""
    import json

    from conftest import make_project, sphere_text, write_model
    from PIL import Image

    from kiln import cli
    from kiln import preview as pv

    (tmp_path / "project.godot").write_text("config_version=5\n")
    project = make_project(tmp_path / "art", 'default_style = "fast"\ndefault_palette = "main"\noutput_dir = "../assets/kiln"\n')
    write_model(project, sphere_text())
    out = tmp_path / "assets" / "kiln"
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(json.dumps({"models": {"thing": {"godot_scene": "res://assets/kiln/models/thing.tscn"}},
                                                   "looks": {"fast": "res://assets/kiln/looks/fast.tscn"}}))  # fmt: skip
    calls: dict[str, object] = {}

    def fake_render(godot_bin: str, root: Path, scene: str, look: str, views: list[tuple[float, float]], half: float,
                    centre: tuple[float, float, float], size: int, out_dir: Path) -> tuple[list[Path], str]:  # fmt: skip
        calls.update(views=views, half=half, centre=centre, size=size)
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(len(views)):
            paths.append(out_dir / f"engine_{i:02d}.png")
            Image.new("RGBA", (size, size), (0, 0, 0, 0)).save(paths[-1])
        return paths, "KILN_VIEWS_OK"

    monkeypatch.setattr("kiln.godot.render_engine", fake_render)
    monkeypatch.setattr("kiln.godot.find_godot_binary", lambda: "godot")
    monkeypatch.chdir(project.root)
    assert cli.main(["preview", "thing", "--engine", "--views", "front,back", "--pitch", "5,30", "--size", "128"]) == 0
    assert calls["views"] == [(0.0, 5.0), (180.0, 5.0), (0.0, 30.0), (180.0, 30.0)] and calls["size"] == 128
    from kiln.project import load_project

    built = cli._built(load_project(project.root), "thing")
    centre, half = pv.fit_of(built)
    assert calls["half"] == pytest.approx(half) and calls["centre"] == pytest.approx(tuple(float(c) for c in centre))
    sheet = Image.open(project.root / "previews" / "thing" / "engine.png").convert("RGBA")
    assert sheet.getpixel((20, 90)) == pv.TILE_BG  # the transparent render sits on the previews' tile colour


def test_engine_default_views_match_the_headings() -> None:
    from kiln import cli
    from kiln import preview as pv

    assert all(dict(pv.HEADINGS)[name] == yaw for name, yaw in cli.ENGINE_VIEWS)
