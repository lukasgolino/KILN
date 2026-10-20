# Changelog

All notable changes to KILN. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[SemVer](https://semver.org/) (any change to the notation, settings, manifest or meshes is at least a minor bump
before 1.0).

## [Unreleased]

## [0.1.0] - 2026-10-20

First release.

### Added

- Notation (`models/<name>.kiln.yaml`): shapes sphere, ellipsoid, box, cylinder, cone, capsule, tube, torus,
  lathe, extrude, wedge; `at`, `rotate`; part options id, color, material, blend, cut, intersect, mirror,
  mirror_id, array (row/ring), shell, twist, noise, pattern (stripes, band, checker, dots), decal; rig (pivot,
  parent, meta, separate), skin none/rigid/soft, animations (poses or cycles: walk, waddle, hop, bob, spin, swing,
  breathe, wave), variants (colour swaps), lod, budget, imports (`source:` + `process:`).
- Meshing: sparse sampling + dual contouring (sharp corners), decimation to the style's budget, surface projection;
  clean colour borders cut into the mesh; smooth or faceted normals.
- Styles: soft_toy, low_poly, toon, clay, diorama presets; project styles with `extends`; inspiration images.
- Output: glb (+ variants, LODs), Godot model scenes (style materials, toon, outlines, rim) and look kits,
  manifest.json, CREDITS.md; `--verify-godot`.
- Previews: turntable, closeup, animation filmstrip, line-up with a 1 m bar, gallery, vs inspiration, Godot engine
  renders.
- Lint: E000-E011, W101-W109.
- CLI (`kiln init/new/lint/build/preview/lineup/gallery/status/mark/style/config/import/credits/doctor/skill/mcp`),
  MCP server (`kiln[mcp]`), Python API for generator scripts, Claude skill.
- Demo project (toy airline + toy siege) and a Godot 4.7 showcase.

[Unreleased]: https://github.com/lukasgolino/KILN/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lukasgolino/KILN/releases/tag/v0.1.0
