# Changelog

All notable changes to KILN. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[SemVer](https://semver.org/) (any change to the notation, settings, manifest or meshes is at least a minor bump
before 1.0).

## [Unreleased]

## [0.7.1] - 2026-10-21

### Added

- The skill asks agents to report what got in their way (crashes, misleading messages, workarounds, missing
  features) as GitHub issues at https://github.com/lukasgolino/KILN/issues: a minimal-repro draft, a duplicate
  check, and filing only with the user's OK. `.github/ISSUE_TEMPLATE/agent-report.md` and the `agent-report` label.
  Run `kiln skill install` to update a project's copy of the skill.

### Fixed

- Hard-surface planar merge no longer crashes (`KeyError` in `_outline_points`) on a patch whose outline doesn't
  close (its edges only meet other patches' at T-points); such a patch keeps all its points (LOOSE #45).

## [0.7.0] - 2026-10-21

Effects and font text (LOOSE #41, #26).

### Added

- `effect:` on models (LOOSE #41): emitters throw other models out with velocity/burst, gravity, drag and spin, with
  scale/heat/fade envelopes over life. `kiln build` writes `models/<name>.effect.json` (manifest `effect`) with every
  particle rolled from the seed and the motion formula; `kiln preview <model> --effect` (MCP `preview` which=effect)
  plays it out. E011 when an emitted model doesn't exist.
- Extrude `text: "OPEN"` in `font: fonts/sign.ttf` (.ttf/.otf) with `text_size`, `text_align`, `letter_spacing`,
  `line_spacing` (LOOSE #26): glyph outlines from the font (counters are holes); no kerning or shaping.
- Dependency: fonttools.

### Changed

- Build cache keys include extrude outlines (a font file's edits rebuild); BUILDER_VERSION 12.

## [0.6.0] - 2026-10-21

LOOSE backlog: text outlines, holes, UVs, origins, per-vertex numbers, aim, pattern lists, rim light, bloom.

### Changed

- Extrude outlines measure only the edges that can be nearest to each point (tiles of points, bounded by their
  centre's nearest edge): same distances, several times faster on long outlines (LOOSE #31).
- W106 accepts a mesh up to 1.5 cells above the shapes' own bottom when that is on y = 0 (rounded extrudes at
  coarse resolution, LOOSE #33), and skips models with an explicit `origin`.

### Added

- `[look] rim_light`, `rim_light_color`, `rim_light_power` (LOOSE #34): a fresnel rim added to every surface,
  a blend-add next pass in Godot scenes (only written for styles that set it) and in previews.
- Previews bloom emissive materials when the style's look has `glow` (as Godot's environment glow does; LOOSE #42).
- `origin: base | center | [x, y, z]` on models (LOOSE #40): the exported glb's origin (the root node carries the
  shift; LODs share the full model's); manifest `origin`.
- `uv: cylindrical | spherical | box | along` on parts (LOOSE #39): projected texture coordinates in the part's
  own frame, TEXCOORD_0 (TEXCOORD_1 when the atlas or a decal uses the first); manifest `uv`. `kiln.api.part(uv=...)`.
- `aim: [from, to]` (or `{ from, to, roll }`) on every shape (LOOSE #29): its y axis along the line, halfway
  between the points, height = the distance when not given.
- `pattern:` takes a list (painted in order, each over the last) and `frame: part` (axes in the part's own
  frame, following rotate/aim) (LOOSE #30); ring arrays turn `around` any direction `[x, y, z]` (LOOSE #29).
- `attr: { name: number }` on parts (LOOSE #38): custom glTF attributes `_NAME` per vertex; the first name also in
  COLOR_0's alpha (what Godot imports); manifest `attributes`.
- `extrude: { path: "<SVG path data>" }` (LOOSE #26): subpaths flattened to outlines (curves within
  `path_tolerance`), even-odd counters and islands, `path_scale`; hard extrudes add islands and cut counters.
- `extrude` takes `holes` (outlines cut through, rounded with the rest; LOOSE #27) and `offset` (grow or shrink
  the outline; LOOSE #28).

## [0.5.0] - 2026-10-21

CC0 parity, second half: palette atlas (M9), humanoids and clip retargeting (M5), attachments for CC0 characters (M6),
the template library (M4).

### Added

- Palette atlas (M9): `atlas = true` (kiln.toml) gives every model one material: colours, roughness/metal, glow (and
  Godot rim light) live in small palette textures next to the glb (`<name>.palette.png`, `.material.png`, `.glow.png`,
  `.rim.png`), faces' UVs point at their colour's cell. 1 surface per mesh, 2 with a decal (the demo knight: 2 meshes,
  1 material, instead of 11 surfaces and 10 materials).
- Variants under `atlas` are texture swaps (`<name>.<variant>.palette.png`): same mesh, and the Godot variant scene is
  the base glb with the variant's palette. Manifest `atlas` (textures, cells with colour, preset, uv and pixel) and
  variant `palette`/`glow`.
- `atlas_ao = true`: ambient occlusion baked into the vertex colours (COLOR_0, a multiplier), from the distance field.
- `kiln build --verify-godot` checks that atlas models sample their palette texture.
- Humanoids (M5): `skeleton: humanoid` (parts named after standard joints; default parents, pivots and soft skin;
  manifest `humanoid` maps joints to KayKit, Mixamo and Godot SkeletonProfileHumanoid names) and imported
  animations `{ import: <clips.glb>, clip: <name>, fps, loop, speed }` retargeted at build time from CC0 clip libraries
  such as KayKit Character Animations (Rig_Medium); manifest animations name their `clip`.
- Attachments for CC0 characters (M6): `fit_to: { file, bone, meshes }` and `fit: { to: target, gap }` wrap a shell
  around the character's own mesh (an exact distance to its triangles); the glb is exported in the bone's space,
  manifest `attach`; W113 when it sinks into the character; `kiln preview --fit`.
- Template library (M4): 3 bodies, 6 heads, 6 helmets and 5 armour pieces in the package (`kiln library`, preview in
  docs/templates.png), combined with `extends: [a, b, ...]` (a list; project templates of the same name win) or
  `kiln new model <name> --extends a,b,c`; library palette `people`. `cut: <id>` cuts only that id; `fit` takes a list
  of ids; fitted shells are their own mesh pieces; templates may be partial (rig and fit names another template
  brings).

### Fixed

- `vertex_colors = true`: every surface carries COLOR_0, glow ones (which keep a material per colour) included, so
  rigged glowing models get vertex colours too (LOOSE 36).
- `kiln.api.part()` sorts `loose`, `hard`, `bevel`, `chamfer`, `segments`, `fit` and `keep` into the part (LOOSE 32, 43).

## [0.4.0] - 2026-10-21

Toward CC0 parity (CC0_PARITY_PLAN.md, from LOOSE_REPORT.md items 23-25).

### Added

- Hard surface (M2): parts made as exact polygons with designed facets and crisp creases, joined by exact CSG.
  A part is hard with `sides: N` (cylinder, cone, lathe, torus; sphere, ellipsoid, capsule, tube when hard),
  `chamfer`, `bevel` + `segments`, `blend: none` or `hard: true`; style `[shape] hard_surface = auto | always | never`
  and `hard_sides` (low_poly: always, 8). `sides` also shapes the smooth field (an octagonal prism). The demo trebuchet
  in low_poly is 908 triangles with octagonal wheels.
- `shell: { thickness, side: in | both, open: -y }`: a wall inside the surface with one side open, showing its rim.
- Rig `under: { color, material, gap }` on a `separate` part: paints what it covers (hair under a helmet).
- `fit: { to: <id>, gap }` on a shell part (M3): the wall wraps those parts' surface wherever the part's own shape
  reaches, so a helmet encloses the head down to the cheeks instead of perching on it.
- W113: a part pokes through another part's shell (eyes through a visor slot, a head through a helmet).
- `keep: true` (M8): the part is its own small mesh (on a finer grid if it's small) that every LOD keeps. Crisp parts
  under 2% of the model's size are kept anyway (rivets, pupils, studs; `keep: false` opts out).
- Hardware parts (M8): `rivets`, `band` (with `fit:` round an earlier part's surface), `planks`, `bolt`, `slit`;
  each expands into ordinary (hard) parts.
- `kiln preview <model> --detach` (and the MCP `preview` tool's `detach`): each separate part off in turn.
- E013: the built mesh has open edges (cracks).
- Reference comparison (M7): `kiln preview <model> --vs <ref.glb|ref.gltf> [--ref-height M]` renders the model and a
  reference mesh at one scale in paired turntable rows, head-region closeups and per-view silhouette differences, with
  metrics (printed and under `compare` in `--json`): silhouette IoU over 8 views, triangles and their ratio, surfaces,
  materials, colours, facet regularity and open edges of both. `--vs` without a path still shows the inspiration
  images. The MCP `preview` tool takes `reference` and `ref_height` with `which: "vs"`.
- Skill: a "match a reference" workflow (iterate until the metrics are inside the owner's thresholds).

### Fixed

- Cracks at colour borders (LOOSE 23: 36 open edges on a footman; the demo knight had 48): cutting a border split
  only one side of an edge, leaving T-junctions. Every demo model is now closed.
- Zero-volume fins (pairs of opposite faces) that decimation could leave on thin parts are removed.
- Smooth shading streaked across flat faces next to crisp edges (a cylinder's cap): the crease test compared the
  field's normal on the edge (the bisector) with the full `sharp_angle` instead of half of it.
- W102 and thin-part protection use a shell's wall thickness.
- The preview renderer crashed when a batch of triangles covered no pixel centre (close framings).

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

[Unreleased]: https://github.com/lukasgolino/KILN/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/lukasgolino/KILN/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/lukasgolino/KILN/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lukasgolino/KILN/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/lukasgolino/KILN/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lukasgolino/KILN/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lukasgolino/KILN/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lukasgolino/KILN/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lukasgolino/KILN/releases/tag/v0.1.0
