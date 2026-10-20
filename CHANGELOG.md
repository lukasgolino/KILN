# Changelog

All notable changes to KILN. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[SemVer](https://semver.org/) (any change to the notation, settings, manifest or meshes is at least a minor bump
before 1.0).

## [Unreleased]

## [0.3.0] - 2026-10-20

From the LOOSE! dogfooding report (LOOSE_REPORT.md, items 1-22).

### Added

- Model families: `template: true` models are bases; `extends: <base>` inherits parts (base first, minus
  `remove: [ids]`), rig, animations and variants (merged by name) and every other field except identity. E012.
- `loose: true` on a part: it may float (flames, bees, rubble) without W103.
- An animation can have a `cycle` and `poses` together: poses repeat over the cycle's frames and override it per part.
- Rig `meta` takes flat lists (points such as `seat: [0, 1.56, 0]`).
- Manifest parts: `aabb` (the part's box in model space, rest pose) and `node_path`.
- `variant_glbs = false` (kiln.toml): no glb per variant; each variant is a Godot scene recolouring the base glb, and
  every variant (with or without glbs) gets a `godot_scene` in the manifest.
- W111 (a part lost when reducing to the triangle budget) and W112 (a LOD well above its target, from `kiln build`).
- `kiln init` inside a Godot project writes `.gdignore`.
- Rig `sockets: { name: [x, y, z] }`: named points that become child nodes moving with the part (BoneAttachment3D
  markers in Godot), with position and offset in the manifest (report 22).
- Manifest animations: `start`, the parts the first frame moves (report 22).
- `vertex_colors = true` (kiln.toml): colours in the vertices, one surface per material preset: far fewer draw calls
  for crowds (report 19).
- Lint meshes models in parallel processes (`KILN_JOBS`, default every core).

### Changed

- KILN no longer depends on PAGAN: the palette format, findings, YAML loader, OKLab colours and glTF writer are
  vendored (`kiln.vendor`, from PAGAN v0.9.0), so a game can pin any PAGAN version next to KILN.
- `separate: true` parts are meshed on their own (a closed mesh, not fused into the body); they don't count for W103.
- W101 is judged on the full-detail mesh, not the decimated one.
- `--verify-godot` and `preview --engine` run in a throwaway Godot project holding a copy of the output, so nothing else
  in the game's project is imported or rewritten.
- glTF material names end in `#rrggbb` (the colour), which variant scenes recolour by.
- The .tscn style script shares its materials between instances (was: a copy per instance) and leaves surface
  overrides the game set before `add_child` alone (report 18).
- soft_toy materials reflect less: metal 0.35 metallic / 0.55 roughness, gold 0.5 / 0.45, skin roughness 0.8;
  low_poly gold 0.5 metallic (report 21).
- Meshing at tight budgets (characters with many colours, big models): each piece is first decimated freely to 3x the
  budget (triangles go where the shape needs them: wheels stay round), then colour borders are cut into it and kept.
  Borders are thinned and the mesh decimated in
  turns (a full-detail border can't be thinned until the surface around it is coarser), border tolerance follows the
  budget's triangle size, the simplifier runs again while it still helps (it stopped early on flat brims), and parts
  thinner than two budget-sized triangles keep their outline. Body pieces and `separate` parts are decimated
  together, each kept on its own surface. Rounder shapes than 0.2.0 at the same budget (LOOSE's peasant: boots,
  hands, ears and nose kept at 5000 triangles).
- Dual contouring stores only the cells on the surface (memory: was a 3x3 matrix per grid cell) and moves vertices
  whose triangles fold back to their cell's centre. Field evaluation is batched and skips parts out of reach.

### Fixed

- An `extrude` outline with repeated points (or closed on its first point) made the whole model NaN: repeats are
  dropped, fewer than 3 different points is E003, and a NaN shape is an error naming the part.
- Paint ownership ignored later cuts: a door in a cut archway was painted as the wall.
- Godot gave a soft skin's Skeleton3D the extras of its last bone (`hitzone: eye`): an unweighted last joint
  `kiln_skeleton` now carries the model's own (report 17).
- `kiln import` dropped textures in sub-folders (Kenney's `Textures/colormap.png`): they're copied with their folders,
  a missing one is an error, and the build cache keys on them.

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

[Unreleased]: https://github.com/lukasgolino/KILN/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/lukasgolino/KILN/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lukasgolino/KILN/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lukasgolino/KILN/releases/tag/v0.1.0
