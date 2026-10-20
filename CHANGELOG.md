# Changelog

All notable changes to KILN. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[SemVer](https://semver.org/) (any change to the notation, settings, manifest or meshes is at least a minor bump
before 1.0).

## [Unreleased]

## [0.2.0] - 2026-10-20

Smoother models: no more jagged seams, polygonal pupils, streaks or creases from decimation. Every built mesh
changes (same triangle budgets).

### Changed

- Colour borders and patterns are cut on the full-resolution mesh, then decimation keeps them: the mesh is pulled
  apart along the borders, simplified with the borders locked (thinned to within 0.15 grid steps where straight),
  and welded back. Before, edge collapses crossed borders: jagged seams (a cap on a head), polygonal pupils and
  shading streaks where parts blend.
- Patterns no longer refine the decimated mesh, so they cost far fewer triangles (the knight's band: ~7000 fewer).
- After decimation, slivers and tilted faces are evened out along the surface (borders and creases stay put).
- Normals: sharp edges are judged by the surface, not by the triangle (big decimated triangles stay smooth), and on
  a border each side uses its own faces' normals (no dark wedges beside a hoop or an eye).
- Needs fast-simplification >= 0.2.0 (border locking, collapse replay).

### Fixed

- Triangle budgets: the build loop also loosens border tolerance when borders alone exceed the budget.

## [0.1.0] - 2026-10-20

First release.

### Added

- Notation (`models/<name>.kiln.yaml`): shapes sphere, ellipsoid, box, cylinder, cone, capsule, tube, torus,
  lathe, extrude, wedge; `at`, `rotate`; part options id, color, material, blend, cut, intersect, mirror,
  mirror_id, array (row/ring), shell, twist, noise, pattern (stripes, band, checker, dots), decal; rig (pivot,
  parent, meta, separate), skin none/rigid/soft, animations (poses or cycles: walk, waddle, hop, bob, spin, swing,
  breathe, wave, chain), variants (colour swaps), lod, budget, imports (`source:` + `process:`); lathe profiles
  are smoothed unless `smooth: false`.
- Meshing: sparse sampling + dual contouring (sharp corners), decimation to the style's budget, surface projection;
  clean colour borders cut into the mesh; smooth or faceted normals.
- Styles: soft_toy, low_poly, toon, clay, diorama presets (materials incl. leather); project styles with `extends`; inspiration images.
- Output: glb (+ variants, LODs), Godot model scenes (style materials, toon, outlines, rim) and look kits,
  manifest.json, CREDITS.md; `--verify-godot`.
- Previews: turntable, closeup, animation filmstrip, line-up with a 1 m bar, gallery, vs inspiration, Godot engine
  renders.
- Lint: E000-E011, W101-W110; builds meet the triangle budget after painting (W110 when patterns alone exceed it).
- CLI (`kiln init/new/lint/build/preview/lineup/gallery/status/mark/style/config/import/credits/doctor/skill/mcp`),
  MCP server (`kiln[mcp]`), Python API for generator scripts, Claude skill.
- Demo project (toy airline + toy siege) and a Godot 4.7 showcase.

[Unreleased]: https://github.com/lukasgolino/KILN/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/lukasgolino/KILN/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lukasgolino/KILN/releases/tag/v0.1.0
