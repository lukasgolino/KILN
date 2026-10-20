"""The software renderer and the preview sheets."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import arms_text, built_of, sphere_text
from kiln import preview as pv
from kiln.export import Built
from kiln.project import Project
from kiln.render import View, camera_basis, posed, render


@pytest.fixture
def ball(project: Project) -> Built:
    return built_of(project, sphere_text())


@pytest.fixture
def hero(project: Project) -> Built:
    return built_of(project, arms_text("hero"), "hero")


def test_camera_basis_is_orthonormal() -> None:
    for view in (View(0, 0), View(30, 20), View(200, -30), View(0, 90), View(45, -90)):
        r, u, f = camera_basis(view)
        m = np.stack([r, u, f])
        np.testing.assert_allclose(m @ m.T, np.eye(3), atol=1e-12)
    r, u, f = camera_basis(View(0, 0))
    np.testing.assert_allclose(f, [0, 0, -1], atol=1e-12)  # looking at the front (+Z) from in front
    np.testing.assert_allclose(r, [1, 0, 0], atol=1e-12)
    np.testing.assert_allclose(u, [0, 1, 0], atol=1e-12)


def test_render_returns_an_rgba_image_with_the_model(ball: Built) -> None:
    image = render(ball, View(), 64)
    assert image.mode == "RGBA" and image.size == (64, 64)
    a = np.asarray(image)
    assert a[0, 0, 3] == 0  # transparent background
    assert a[32, 32, 3] == 255
    covered = (a[:, :, 3] > 0).mean()
    assert 0.15 < covered < 0.35  # a sphere framed by its box's bounding sphere
    centre = a[32, 32, :3].astype(int)
    assert centre[0] > centre[1] and centre[0] > centre[2]  # red


def test_render_background_and_swap(ball: Built) -> None:
    image = np.asarray(render(ball, View(), 32, swap={"#e8413c": "#2f6fd0"}, background=(10, 20, 30, 255)))
    assert tuple(image[0, 0]) == (10, 20, 30, 255)
    centre = image[16, 16, :3].astype(int)
    assert centre[2] > centre[0]


def test_render_is_deterministic(hero: Built) -> None:
    a = render(hero, View(40, 10), 48, track=0, frame=2)
    b = render(hero, View(40, 10), 48, track=0, frame=2)
    assert a.tobytes() == b.tobytes()


def test_toon_outline_draws_dark_edges(project: Project) -> None:
    (project.root / "styles" / "fast.style.toml").write_text(
        (project.root / "styles" / "fast.style.toml").read_text().replace('"soft_toy"', '"toon"')
    )
    built = built_of(project, sphere_text())
    a = np.asarray(render(built, View(), 64)).astype(int)
    dark = (a[:, :, 3] > 0) & (a[:, :, :3].sum(axis=2) < 120)
    assert dark.sum() > 20


def test_posed_moves_animated_parts(hero: Built) -> None:
    rest, _ = posed(hero, None, 0)
    hold = [t.name for t in hero.tracks].index("hold")
    moved, normals = posed(hero, hold, 1)
    assert rest.shape == moved.shape
    np.testing.assert_allclose(np.linalg.norm(normals, axis=2), 1.0, atol=1e-9)
    p = hero.painted
    arm = np.array([p.groups[g].bone == "arm_l" for g in p.face_group])
    body = np.array([p.groups[g].bone == "root" for g in p.face_group])
    assert not np.allclose(rest[arm], moved[arm])
    np.testing.assert_allclose(rest[body], moved[body], atol=1e-12)


def test_posed_soft_skin(project: Project) -> None:
    built = built_of(project, arms_text("hero", "soft"), "hero")
    rest, _ = posed(built, None, 0)
    moved, _ = posed(built, [t.name for t in built.tracks].index("hold"), 1)
    assert not np.allclose(rest, moved)
    far = rest[:, :, 1] < 0.1  # the bottom of the body: no arm influence
    np.testing.assert_allclose(rest[far], moved[far], atol=0.01)


def test_turntable_closeup_filmstrip(hero: Built) -> None:
    sheet = pv.turntable(hero, size=48)
    assert sheet.width >= 8 * 48 and sheet.height > 3 * 48
    close = pv.closeup(hero, "arm_l", size=48)
    assert close.height > 3 * 48
    strip = pv.filmstrip(hero, "wave", size=48)
    assert strip.width >= 4 * 48 and strip.height > 2 * 48
    with pytest.raises(KeyError):
        pv.closeup(hero, "tail", size=48)
    with pytest.raises(KeyError):
        pv.filmstrip(hero, "dance", size=48)


def test_closeup_of_a_static_model(project: Project) -> None:
    built = built_of(project, sphere_text() + "  - sphere: { at: [0, 0.6, 0], radius: 0.1 }\n    id: knob\n    color: white\n")
    assert built.skin == "none"
    assert pv.closeup(built, "knob", size=40).width > 0
    with pytest.raises(KeyError):
        pv.closeup(built, "tail", size=40)


def test_lineup_gallery_versus(tmp_path: Path, ball: Built, hero: Built) -> None:
    line = pv.lineup([ball, hero], height_px=120)
    assert line.width > 2 * 60 and line.height >= 120
    assert pv.lineup([]).width > 0
    gallery = pv.gallery([ball, hero], size=48)
    assert gallery.width >= 2 * 48
    inspiration = tmp_path / "styles" / "fast" / "inspiration"
    inspiration.mkdir(parents=True)
    Image.new("RGB", (80, 40), (200, 100, 50)).save(inspiration / "look.png")
    (inspiration / "notes.txt").write_text("not an image")
    images = pv.inspiration_images(tmp_path / "styles", "fast")
    assert images == [inspiration / "look.png"]
    vs = pv.versus(ball, images, size=48)
    assert vs.width >= 3 * 48
    assert pv.inspiration_images(tmp_path / "styles", "nope") == []
