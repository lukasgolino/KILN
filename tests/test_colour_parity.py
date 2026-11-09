"""#161: `kiln preview` predicts the Godot render. A grid of palette colours x materials, rendered both ways from the
front; the mean OKLab distance at the spheres' centres stays small, in Forward+ and in Compatibility (where the look
kit's sun drops its shadows: godotengine/godot#90259 adds the ambient again per shadowed light)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kiln.godot import find_godot_binary
from kiln.style import FILMIC_WHITE

RENDER = pytest.mark.skipif(os.environ.get("KILN_ENGINE_RENDER") != "1" or find_godot_binary() is None or shutil.which("xvfb-run") is None,
                            reason="renders offscreen: KILN_ENGINE_RENDER=1, Godot and xvfb")  # fmt: skip
COLOURS = {"white": "#f4f4f0", "grey": "#8a93a3", "red": "#e8413c", "orange": "#f28c28", "gold": "#f2c14e", "green": "#4caf50",
           "blue": "#2f6fd0", "navy": "#2b3a67", "skin": "#f1b48c", "brown": "#6b4a2f"}  # fmt: skip
MATERIALS = ["default", "plastic", "fabric", "metal"]
TILE = 256


def oklab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    r, g, b = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    lms = np.cbrt([0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b, 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b,
                   0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b])  # fmt: skip
    m = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099], [0.0259040371, 0.7827717662, -0.8086757660]])
    return m @ lms


def test_filmic_is_godots_curve_at_the_look_kits_white() -> None:
    from kiln.render import _filmic

    def godot(x: float, white: float) -> float:  # Godot 4's tonemap_filmic (exposure bias 2 baked in)
        a, b, c, d, e, f = 0.22 * 4, 0.30 * 2, 0.10, 0.20, 0.01, 0.30

        def curve(v: float) -> float:
            return ((v * (a * v + c * b) + d * e) / (v * (a * v + b) + d * f)) - e / f

        return curve(x) / curve(white)

    for x in (0.05, 0.2, 0.5, 1.0, 2.0):
        assert float(_filmic(np.array(x))) == pytest.approx(godot(x, FILMIC_WHITE))


def _centres(sheet: Path) -> dict[tuple[str, str], np.ndarray]:
    from kiln.preview import TILE_BG

    image = np.asarray(Image.open(sheet).convert("RGB")).astype(float)
    ys, xs = np.nonzero((image == np.array(TILE_BG[:3])).all(axis=2))  # the first tile's corner, wherever the title wraps
    top, left = int(ys.min()), int(xs.min())
    tile = image[top : top + TILE, left : left + TILE]
    lo, hi = np.array([-1.225, 0.02, -0.1]), np.array([1.225, 0.97, 0.1])
    centre, half = (lo + hi) / 2, float(np.linalg.norm(hi - lo)) / 2 * 1.08
    scale = TILE / (2 * half)
    out = {}
    for j, material in enumerate(MATERIALS):
        for i, colour in enumerate(COLOURS):
            px, py = int(TILE / 2 + ((i - 4.5) * 0.25 - centre[0]) * scale), int(TILE / 2 - (0.12 + j * 0.25 - centre[1]) * scale)
            out[(material, colour)] = tile[py - 2 : py + 3, px - 2 : px + 3].reshape(-1, 3).mean(axis=0)
    return out


@RENDER
@pytest.mark.parametrize("renderer", ["forward_plus", "gl_compatibility"])
@pytest.mark.parametrize("style", ["soft_toy", pytest.param("toon", marks=pytest.mark.xfail(reason="#183: toon bands and outlines differ", strict=True))])
def test_engine_render_matches_the_preview(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, renderer: str, style: str) -> None:
    from kiln.cli import main

    (tmp_path / "project.godot").write_text(f'config_version=5\n[rendering]\nrenderer/rendering_method="{renderer}"\n')
    monkeypatch.chdir(tmp_path)
    assert main(["init", "art", "--style", style]) == 0
    art = tmp_path / "art"
    parts = [f"  - sphere: {{ at: [{(i - 4.5) * 0.25:.3f}, {0.12 + j * 0.25:.3f}, 0], radius: 0.1 }}\n    color: {c}\n    material: {m}"
             for j, m in enumerate(MATERIALS) for i, c in enumerate(COLOURS)]  # fmt: skip
    (art / "models" / "calib.kiln.yaml").write_text("name: calib\nclass: prop\nparts:\n" + "\n".join(parts) + "\n")
    monkeypatch.chdir(art)
    assert main(["build", "calib"]) == 0
    assert main(["preview", "calib", "--views", "front", "--pitch", "0", "--size", str(TILE)]) == 0
    assert main(["preview", "calib", "--engine", "--views", "front", "--pitch", "0", "--size", str(TILE)]) == 0
    soft, engine = _centres(art / "previews/calib/views.png"), _centres(art / "previews/calib/engine.png")
    gaps = [float(np.linalg.norm(oklab(engine[k]) - oklab(soft[k]))) for k in soft]
    assert np.mean(gaps) < 0.035, f"mean OKLab gap {np.mean(gaps):.3f}, worst {max(gaps):.3f}"
