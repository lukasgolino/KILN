"""#160: engine renders never use the desktop display."""

from __future__ import annotations

import shutil
import sys

import pytest

from kiln import godot


def _linux(monkeypatch: pytest.MonkeyPatch, which: str | None) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(shutil, "which", lambda name: which if name == "xvfb-run" else None)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.delenv("KILN_OFFSCREEN", raising=False)


def test_xvfb_without_the_desktop_display(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, "/usr/bin/xvfb-run")
    result = godot.offscreen_command(512)
    assert not isinstance(result, str)
    prefix, env = result
    assert prefix == ["/usr/bin/xvfb-run", "-a", "-s", "-screen 0 512x512x24"]
    assert "DISPLAY" not in env and "WAYLAND_DISPLAY" not in env
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1" and env["GALLIUM_DRIVER"] == "llvmpipe"


def test_no_xvfb_refuses_instead_of_a_window(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, None)
    result = godot.offscreen_command()
    assert isinstance(result, str) and "xvfb" in result and "never opens a window" in result


def test_override_wrapper_and_window_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    _linux(monkeypatch, None)
    monkeypatch.setenv("KILN_OFFSCREEN", "tools/xvfb.sh --quiet")
    result = godot.offscreen_command()
    assert not isinstance(result, str) and result[0] == ["tools/xvfb.sh", "--quiet"] and "DISPLAY" not in result[1]
    monkeypatch.setenv("KILN_OFFSCREEN", "window")
    result = godot.offscreen_command()
    assert not isinstance(result, str) and result[0] == [] and result[1]["DISPLAY"] == ":0"
