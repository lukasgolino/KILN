# Changelog

All notable changes to KILN. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[SemVer](https://semver.org/) (any change to the notation, settings, manifest or meshes is at least a minor bump
before 1.0).

## [Unreleased]

### Fixed

- The built-in walk on a humanoid (`skeleton: humanoid`) moved only the hips: its legs and arms default to
  upperleg/upperarm now, its knees and elbows bend (knees fold while the leg swings forward), its feet stay level,
  and the body rides so the planted foot stays on the ground. Listing `legs:` / `arms:` keeps the humanoid defaults
  off; other models bend what `knees:` / `elbows:` name. `wave` on a humanoid raises upperarm_r (it turned the whole
  model). A model without lower limbs and without the humanoid skeleton walks as before. Cached builds are rebuilt
  once (#150).
- `normal_map: 2048` wrote a 2140x2138 texture: the packer's atlas came out up to 10% over the size asked for and
  was written as it was. The map is now exactly the size asked for, square, with the charts and their padding
  inside it (packed again at a lower texel density until they fit). Texel density changes with it: about 20% lower
  at 256 and 512, where the old maps overshot most, and a few per cent higher from 1024 up. Cached builds with a
  normal map are rebuilt once (#151).

### Added

- The `skin` style preset: stylised game skins with matte materials, colours that fade where parts blend, shade paint
  (darker crevices and undersides) and a soft look kit; fur as relief and face `density` in its notes and worked
  example (`kiln docs styles`) (#233).
- `[shape] color_blend` in a style: every smooth part that blends (and doesn't set its own) fades its colour that far
  into its neighbours'; the baked colour map comes on for such models. W127 only for a part's own color_blend (#262).
- `skin_falloff` on a part (soft skins): the surface painted as its bone follows that bone alone away from its colour
  border (`0`), or fades over to it within that many metres; the border stays blended. A sleeve blended into the
  chest no longer smears down the torso when the arm moves. Without it, weights are as before. Lint W129 when it
  does nothing (a rigid skin, or a hard, kept, separate or cutting part) (#192).
- `run` and `sneak` cycles: a faster walk leaning forward, and a crouched walk (thighs forward, knees bent, the body
  lowered and leaning) (#150).
- `smooth: true` on tubes and locks: a centripetal Catmull-Rom curve through the points (8 straight pieces per span,
  3 for hard parts; through every point, no loops on uneven spacing; a closed path, first point = last, wraps
  round) instead of straight lines between them. A wave is five points,
  not thirteen. Without it the path is straight between points, as before (now documented) (#179).
- `on: { part, near }` on a part: placed on the blended surface of earlier parts (those ids, blends, fitted shells
  and earlier cuts included; detail parts not) where a walk from `near` along the field settles (start just outside
  the spot), its y axis along the surface normal, then `offset` along the normal and `roll` about it (`align: false`
  only moves it). Fur clumps, straps, scales and spikes no longer need the body's field worked out by hand;
  `mirror_id` twins and `mirror` follow; not with `array` or hardware parts (#149).
- Lint W128: a round soft part (sphere, ellipsoid, capsule, torus) that shows at least half of its surface on
  fewer than 48 triangles per copy reads as a polygon. A prop of many small parts shares one class budget; the
  warning gives the `density` and the `budget:` that would lift it to 48 (#167).
- `density` on a part: its weight on the triangle budget (0.25 to 8, default 1). Faces are classed by the density
  of the part they're on; each class gets what a plain reduction to the budget would give it, x its density, at the
  same total (a face at 3 gets about three times the share it had), reduced on its own with its border locked and
  welded back (no paint border, no shading crease). A class can't go past its full-resolution mesh: the shaping pass
  keeps the max density x its usual triangles. Hard and kept parts ignore it. Without `density` meshes are unchanged
  (#232).
- Shade paint: `shade: { cavity, top, under }` on a model, or `[shade]` in a style (the model's fields go over the
  style's): darker in crevices (`cavity` x the occlusion `atlas_ao` uses), the top keeps its colour while the rest
  darkens towards the bottom (`top`), the underside darker still (`under`). It is one grey multiplier per vertex corner in
  COLOR_0 in every colour mode (per-colour materials, vertex colours, the atlas, colour maps), shown by previews and
  Godot alike; manifest `shade` on the model. `top` is relative (vertex colours can't go above 1). With the atlas,
  `atlas_ao` is a cavity strength (with both, the larger). Off by default: output is unchanged without it (#231).
- `color_blend` on a part: its colour fades into its neighbours' over that distance either side of their border
  (mixed in OKLab, half and half on the border), instead of meeting in a crisp line. The fade is painted in the base
  colour map (`<name>.color.png`, which comes on for the model as it does for relief); the mesh is unchanged, and
  without `color_blend` so is all output. A border fades where the later part joins with a `blend` (a nose set on
  with a crisp seam stays sharp); hard and glowing parts and decals stay crisp; lint W127 says when a `color_blend`
  fades nothing. The demo cub's belly and muzzle use it (#230).
- Relief layers: fur as patches in the baked maps, not parts. `relief:` on a model scatters shallow, overlapping,
  flame-tipped patches over the parts it names (`on`, `length`, `width`, `lift`, `density`, `flow`, `tips`, `jitter`,
  `color`/`color_to`, `under`, `fade`, `seed`). They tilt the baked normal map and are painted into a new base colour
  map on the same UVs (`<name>.color.png`: each patch lighter toward its tip, the surface darker just under it), so a
  furry character is a handful of blended parts and builds in seconds, with nothing added to the mesh. Previews and
  the Godot scenes (standard and toon) show both maps; variants get their own colour map; the manifest has
  `color_map`. Patches stay on the parts a layer names (eyes, noses, hard and glowing parts next to them stay clean);
  lint W126 says when a layer has no surface to lie on. The demo has a cub (#229).
- A model can have a baked normal map and baked ambient occlusion together. In a project with `atlas = true`, a model
  with `normal_map:` is no longer a lint error: it keeps a material per colour (the palette atlas and the normal
  map both need the first UV set), carries its normal map, and gets `atlas_ao`'s occlusion in its vertex colours
  like the atlas models. Its variants recolour materials as they do without the atlas. Its manifest entry has
  `ao` and `ao_strength` and no `atlas` (#148).
- Lint W125: the mesh's UV charts don't fit the normal map (many separate pieces in a small map, where the padding
  between charts alone fills it). The packer now stops trying when the atlas stops shrinking and squeezes its
  smallest try into the map; the warning says by how much and what size to ask for.

## [0.22.0] - 2026-11-11

Speed and the iteration loop. Built output is the same as 0.21.0's except: the generator string in every glb and
the manifest; meshes of models with patterns or gradients, which can move by rounding (30 vertices of a 26k-triangle
character, see Performance). Mesh caches from earlier versions are rebuilt once.

### Added

- `kiln preview <model> --draft` (#222): a quick look while shapes and placement are still moving. Mesh cells 3 times
  coarser, each face in its nearest part's colour (no borders cut, no patterns on smooth parts), hard parts without
  bevels and made once, one reducing pass, no normal map or baked occlusion. A 536-part character: 14 s (its build:
  about 290 s); a 23-part one: 5 s; an 82-hard-part scene: 21 s (80 s). Sheets go to `previews/<model>/draft/`, each stamped
  DRAFT (`--json`: `draft: true`; its triangle count is not the build's); drafts have their own cache. Not with
  `--engine`, `--vs`, `--fit` or `--effect`, nor for terrains, scatters and imported models. The MCP `preview` tool
  takes `draft` too.
- Long builds say how far they are and roughly how long is left in each phase (meshing samples, painting, reducing
  passes, skinning), the heartbeat counting it down; a phase projected past 2 minutes says so at once with what would
  make it faster, and a model with 100 or more parts prints every phase line at once (#221).
- `kiln lint` and `kiln build` say each meshed model's cell size and what set it: the model's or the style's
  resolution, the size scaling (`scale_with_size`), a `max_cells` cap (#223). Long builds' meshing phase line says it
  too; `kiln lint --json` has it under `cells`.

### Changed

- Docs: `kiln docs build` has a "What things cost" section (measured build times for cell size, budget, normal map,
  noise, part count, gradients and patterns, hard parts); `kiln docs parts` says that the copy of a part with
  `mirror_id` melts into the mirrored ids of its `blend_to` (one side is enough there; a plain `mirror` part still
  names both) (#224).
- `kiln lint --fast` says in its summary which findings it didn't look for (those that need the built model: E009,
  E013 and most warnings; `--json`: `geometry: false`); the lint topic lists them and says how fast lint, plain lint
  and the build's lint relate (#186, #210).
- Build progress: joining hard parts is its own phase (`joining 82 hard parts`, then solids joined of the total over
  all pieces, cuts included, and time left, estimated for a cost that grows with the square of the count) instead of
  running under `meshing`; a detail level made again over budget says so. The meshing line counts the adding parts
  meshed there (not hard parts, not cuts), and a model of hard parts only no longer says `meshing ...` and
  `meshed at ...: 0 triangles` (#174).
- The vendored PAGAN pieces are Apache 2.0 like the rest of KILN (same author); the separate MIT file is gone.

### Performance

- Animation, variant and comment edits no longer rebuild the meshes (#185, #199): the mesh cache follows the fields a
  mesh, its paint and its skin come from, not the model's whole text. After an animation edit only the tracks are
  sampled again on the cached skeleton; variants, `description`, `tags`, `status`, comments and layout change nothing
  built. A 23-part soft-skinned character after a pose edit: `kiln build` in 4 s instead of 18, the glb identical to
  a full rebuild's. (Caches written by earlier versions are rebuilt once.)
- Joining hard parts is 2-3.5x faster on scenes of many hard parts (#214): a solid's BSP tree is made only where a clip
  reaches it, not whole for every join (joining a small part to a big solid reaches the few planes near the part),
  and planes a whole batch of polygons lies clear of are passed without a test per polygon. An 82-hard-part desk
  scene: 187 -> 54 s; the same desk modelled with 30 of its 110 parts smooth: 177 -> 80 s; a 94-part character with
  hard props: 55 -> 46 s; nothing to speak of on models of mostly smooth parts (the 536-part character stays at
  about 290 s). Output is
  byte-identical (the demo and five larger models): the same planes cut the same polygons. The joining phase's time
  left is now estimated as linear in the joins done.
- A look-only style edit no longer rebuilds the meshes (#174): the mesh cache follows a style's `[shape]` and
  the triangle budget that applies to the model (not the whole `[budgets]` table), not its `[look]`, `[materials]`,
  description or notes; the cached build is exported with the style as
  it is now. A 23-part character after an `exposure` or material edit: `kiln build` in 4 s instead of 18. (Caches
  written by earlier versions are rebuilt once.)
- Reducing is a little faster (#199): the nearest part of every vertex is found in one compiled pass instead of one
  pass per part (a 94-part character: 2.7 -> 0.3 s), and the colour-border simplifier does its fold test in plain
  floats instead of numpy on a handful of points (6 -> 1.8 s). The 536-part character's build: 310 -> about 290 s.
  Output is byte-identical (the demo and five larger models). What is left of "reducing" on models with hard parts is
  mostly the hard parts' union (#214); reduced meshes cached on geometry alone come with #185.
- Painting many-part models is about 3x faster (#154): small point sets (a split's new vertices, one part's
  distance at a few hundred points) run the compiled kernels on one thread (a parallel call cost ~3 ms however small),
  and the whole field is compiled at any size instead of looping every part in Python below 64 points. The 536-part
  character's lint: 838 -> 370 s; with a gradient on each of its 481 locks: 1231 -> 672 s (painting patterns 805 ->
  224 s). Meshes of models with patterns or gradients can move by rounding (the compiled and numpy distances agree to
  ~1e-15, which can flip a decimation choice): on a 26k-triangle character, 30 vertices moved; the demo is byte-identical.
- Distance fields with many `blend_to` parts no longer cost quadratically in their number (#220; since #116): a part out of reach is skipped without working out
  its targets' union (it can't change the field whatever that is), and the compiled kernel keeps that cache per chunk
  of points instead of allocating it per point. A 536-part character (478 fur locks, each melting into its own set of
  earlier parts) costs 7.6 us per point instead of 388, and its lint goes from over an hour to 14 minutes. Output is
  byte-identical.

### Fixed

- Thin parts the simplifier collapses away entirely (a ball with 120 thin locks at a low budget) no longer fail the
  build with "'list' argument must have no negative elements" (#144): they are dropped, and each is reported as W111.

## [0.21.0] - 2026-11-09

### Changed

- Licensed under the Apache License 2.0 instead of MIT (#225). Releases up to 0.20.0 stay
  available under MIT.
- `kiln preview --pose` (#189, #201): `--views`, `--pitch` and `--size` pick its views and tile size (they no longer also
  write a views sheet), `--frame N[,N...]` shows chosen frames (one up close), and the default rows are 3/4 front and
  both sides (a limb on -X showed in no side frame); `--pitch` alone tilts those; `--variant` now colours the pose
  sheet too (`pose_<anim>.<variant>.png`). Pose tiles stay 200 px unless `--size` is given. The MCP `preview` tool
  takes `frames` and `size`.

### Fixed

- W109 no longer fires for animated joints of a `skeleton: humanoid` model: the skeleton puts their pivots at the
  joints (#187).

## [0.20.0] - 2026-11-09

Textures tiled over whole parts, Godot renders that match the previews (and run offscreen), hard-part mirror and CSG
fixes, faster builds. Meshes change for models with hard parts wholly inside others and for every relaxed mesh (to
float rounding); look kits and previews change (colour parity); the rest is byte-identical apart from the generator
string.

### Added

- `texture: { image, project: box | cylindrical, size | texel, at, axis }` on a part (#184, #198): an image tiled over
  the whole part. Box: every face from the side it faces; cylindrical: wrapped round an axis by arc length, caps flat,
  vertices split along the seam. Exported with a repeating sampler (nearest for <= 256 px: pixel-art textures on
  smooth shapes), previewed the same; a decal on the part paints over it.

### Performance

- Relaxing after decimation re-tests only the faces next to a vertex that moved (#199): the same meshes (to float
  rounding; the demo is byte-identical), the pass ~3x faster.
- Hard-part detail levels that change nothing are skipped (#207). (Uniting hard parts pairwise, briefly in main,
  is reverted: on an 82-part scene it left 217 non-manifold edges where coplanar faces meet, #214.)

### Fixed

- Hard parts (#170): `mirror` on a hard part kept nothing (intersecting a solid with a half-space that wholly contains
  it returned no polygons), and a mirrored cut on a hard solid failed with numpy's "zero-size array ...". Union and subtract had the same early exit: a hard
  part wholly inside another kept its inner faces, a cut wholly inside one lost its cavity. A build error
  raised inside a library is now reported as an internal KILN error to report, with where it came from, not as numpy's
  message.

### Changed

- The repository is now `lukasgolino/kiln` (#158): move git pins and links to the new name (GitHub redirects the old
  URLs for now).
- The Godot render matches `kiln preview` (#161; mean OKLab gap 0.25 -> 0.02 on a palette x material grid, soft_toy):
  - look kits set `tonemap_white = 3`, so Godot's Filmic is exactly the previews' curve (Godot's default white made
    every colour paler);
  - on the Compatibility renderer the look kit's sun casts no shadows: Godot adds the ambient light again for each
    shadowed light there (godotengine/godot#90259), which made models several times too bright (`[look]
    compat_shadows = true` keeps them);
  - the preview's sky ambient is `ambient` as Godot applies it (it was scaled by 0.55): previews are a little brighter.
  Every look kit and every preview image changes. The toon look still differs (#183).
- `kiln preview --engine` takes `--views`, `--pitch` and `--size`, is framed exactly like the software views and sits on
  their tile colour (the look kit still lights it; its sky is no longer the backdrop), in the same sheet layout (#162).
  Default: four sides at 15 and 50 degrees. With `--engine`, those flags pick the engine's views.
- `kiln preview --engine` renders offscreen (#160): on Linux a private Xvfb display with Mesa's CPU drivers, the
  desktop's DISPLAY and WAYLAND_DISPLAY removed; without Xvfb it refuses instead of opening a window. `KILN_OFFSCREEN`
  sets a wrapper command (or `window` to opt in to the current display). `kiln doctor` reports how engine renders run
  (`offscreen` in `--json`) instead of whether a desktop display exists.
- `kiln init` inside a Godot project sets `output_dir` to the project's `assets/kiln` (relative) and `export = ["glb",
  "godot"]`, instead of keeping `build` under its own `.gdignore` and only saying so (#163).

## [0.19.0] - 2026-11-09

KILN is on PyPI as `kiln-gen` and in the MCP Registry as `io.github.lukasgolino/kiln` (#155). Output is
byte-identical apart from the generator string.

### Changed

- The distribution is `kiln-gen` (`kiln` on PyPI is another project): `pip install kiln-gen`; the command and the
  import stay `kiln`. Git pins must use the new name from this version on (`kiln-gen @ git+...@v0.19.0`).
- The MCP server is always installed (`mcp` is a dependency; the `mcp` extra is kept, empty), so
  `uvx kiln-gen mcp` runs it without an install.
- **Upgrading from a git-pinned `kiln`:** `pip uninstall kiln` first, then install `kiln-gen`. Both own the same
  `kiln/` files, so uninstalling `kiln` after installing `kiln-gen` deletes them.

### Added

- Tags publish to PyPI (Trusted Publishing) and `server.json` to the MCP Registry.

## [0.18.0] - 2026-11-08

Meshes change for models whose parts share pattern colours (several parts with the same `gradient`); everything
else, the demo included, is byte-identical apart from the generator string.

### Fixed

- Parts with the same `gradient` (or patterns of the same colours) paint only their own faces (#131): the bands'
  colour groups are shared between them, and a later part's bands cut and repainted the earlier parts' band faces
  by its own coordinate (wrong colours, stray cuts, cracks). Meshes of such models change.
- Decimation no longer leaves zero-volume pockets at thin parts' pointed tips (#131): two copies of a colour-border
  vertex at one place, each capping the same ring, read as non-manifold edges (E013). They are joined and the twin
  faces dropped.

## [0.17.0] - 2026-11-06

Fixes the open issues from game use: faster painting, Godot Compatibility colours, filtered normal maps, clean
colour edges on noisy parts, new lint warnings (W123, W124), preview views and sizes, a smaller MCP tool list.
Meshes change for models with `noise` next to another colour and for every baked normal map; Godot scenes of
models with vertex colours (or `atlas_ao`) gain the Compatibility re-encode; the demo's knight and wall use
`origin: ground`. Everything else is byte-identical apart from the generator string.

### Added

- `origin: ground` (#101): the exported mesh lifted (or lowered) onto y = 0 by its built lowest point, x and z as
  written; the manifest records the origin as for the other values.
- W123 (#101): the built mesh of a model standing on y = 0 dips under it by 2 mm (or a tenth of a cell) or more:
  blends and meshing push feet under the shapes' bottom, and W106 only fires past 1 cm. It points at
  `origin: ground`, which the demo's knight and wall now use (they dipped 4.5 and 7.1 mm).
- W124 (#98): a part shows only a sliver (97% or more of its own surface deeper inside other parts than their blend:
  clipped flat or nearly gone), naming the covering parts. W101 also names the parts that cover a hidden one. Hard,
  shell, separate and revealed parts are left out (hard parts are meshed as their tessellation, not their field).
- Long builds and lints are never silent for more than 10 s (#99): the current phase repeats itself every 10 s
  (`kiln: bigfoot: reducing to 15000 triangles (10 s)`), not only when the next one starts. Runs over 20 s without
  `kiln[fast]` installed point at it (a 50-part character: 20 s -> 9 s; cached: 1 s, shared with previews).
- `normal_strength` (#125): scales a baked normal map's tilt (0.5 softer, 0 flat, up to 4).
- `kiln preview --views front,34,side,back --pitch 5,30 --size 500` (#96): one sheet of the views asked for (names
  or degrees, a row per pitch) as `views.png`; `--size` sets the tile size of the turntable, closeups and views, and
  `preview_size` in kiln.toml its default. `--turntable` has a help line.

### Fixed

- Docs (#102): where a ring `array`'s arc starts and which way it runs, that copies turn with the ring, and that a
  `cone`'s (and `cylinder`'s) `at` is its middle, with `aim` to place it by its ends.
- Baked normal maps are filtered per texel (#125): four samples a quarter texel around its centre, each with a
  gradient step of half a texel, so detail finer than a texel blurs out instead of aliasing into streaks and speckle
  (sub-texel noise: tilt std 0.10 -> 0.04). Bakes take about 1.5x as long; every baked map changes. parts.md says
  which groove sizes read at which map size.
- Colour borders between a noisy part and its neighbours follow the parts' smooth shapes (#100): noise roughens the
  surface, not the edge of a blended patch on it (it came out saw-toothed). Meshes of models with `noise` next to
  another colour change.
- `kiln init` inside a Godot project names the `.gdignore` it wrote (in the KILN folder, not the Godot project's) and
  says the default `output_dir` is under it, with a path Godot sees (#97). `kiln build` with Godot export stops with
  E000 when `output_dir` is under a `.gdignore` in the Godot project (the scenes would never import).
- A palette with errors (e.g. a key of two characters, #126) reports only its own errors, naming the file and key;
  models using it are not parsed, instead of failing with one "unknown colour ... (none)" per part.
- Vertex colours (`vertex_colors = true`, and `atlas_ao`'s baked occlusion) render as in the previews in Godot's
  Compatibility renderer (#124): it decodes the colour attribute from sRGB once more, so they came out darker and
  more saturated. The generated scenes of models with COLOR_0 (and scatter scenes, for their LOD glbs) re-encode each
  mesh's colours once at load, only on Compatibility and not headless; the mesh carries the mark, so scenes sharing a
  glb don't encode it twice. Forward+ and Mobile, and scenes of models without vertex colours, are unchanged. An offscreen render
  test (`KILN_ENGINE_RENDER=1`, `tools/godot_window.sh`: Xvfb with Mesa's CPU drivers) compares vertex and material
  colours in both renderers.
- Painting no longer grows with the square of the paint groups (#123): each group's border takes one suffix minimum
  instead of a minimum over all later groups, and patterns and gradient bands evaluate and refine only their own
  part's faces, not the whole mesh. Output is byte-identical. A 120-tuft gradient test model paints in 30 s instead
  of 75 s; long paints print their progress (parts, colour groups) at most every 10 s.

### Changed

- The MCP tool list is a third smaller (#94): 15.1k -> 9.6k characters (~2.7k tokens) for 24 tools. No `title` on
  every schema, no generic output schemas, only annotation hints that differ from the spec's defaults, and one-line
  descriptions for the long ones (`docs` holds the detail). A test keeps it under 10.5k.
- README links the website at its own domain, https://kiln3d.dev/ (#128).
- CI: lint, types and tests on one Python run on every push. The full Python matrix and the Godot checks run on the
  PR once it leaves draft, and again only if a commit lands after that, as the last gate before merge.

## [0.16.1] - 2026-11-05

The 0.16.0 release as it was meant to be: the `v0.16.0` tag was pushed before #120 merged and sits on the commit
before it (0.15.0 code), so it doesn't hold what the 0.16.0 section below lists. Pin `v0.16.1`, not `v0.16.0`.

### Fixed

- Tags publish a GitHub release, with their CHANGELOG section as the notes (#121).

## [0.16.0] - 2026-11-05

### Added

- **Normal maps baked from the distance field** (#111, `kiln[bake]`: xatlas). A model with `normal_map: 1024` gets
  unique UVs (TEXCOORD_0; projected UVs move to TEXCOORD_1), tangents (TANGENT, so engines decode the map with the
  basis it was baked in) and a tangent-space normal map: each texel's normal is the field's gradient at the surface
  point under it. Fine shape detail then shows on a coarse, light mesh. Godot scenes read it (standard and toon looks),
  and `kiln preview` shades with it. Not with `atlas = true` yet (both need the first UV set).
- **`detail: true` parts**: only in the baked normal map, never in the mesh (fur strand grooves, wrinkles, creases).
  Lint W121: a detail part with no map, or thinner than two texels.

- **`gradient: { to: fur_light, steps: 3 }`** (#106): a part's colour (or `from`) going to `to` in `steps` bands mixed
  in OKLab, along the path of a tube, capsule or lock (root to tip), or `along: x|y|z` of other shapes. Patterns paint
  over it. Per-part random tones read as camouflage; a root-to-tip change reads as fur.
- **`blend_to: <id>`** (or a list of ids) (#107): with `blend`, a part melts only into the earlier parts with those ids
  and meets every other part crisply. Fur locks melt into the body and keep a groove between each other (one blend
  radius either melted neighbours into lumps or left each lock looking stuck on). Compiled kernel too.
- **`lock` shape** (#105): a flat blade along a path with an elliptical section, `width` x `thickness` tapering to
  `width_to` / `thickness_to` (`width_to: 0`: a pointed V tip), its flat sides looking along `facing`. For carved fur
  and hair locks, feathers, leaves and petals, which round tubes made look like candle drips.
- **`scale: [x, y, z]`** (or one number) on any soft part: a stretch in the part's own frame (the distance is a bound,
  as usual for stretched fields). Hard parts can't scale (an error, like twist and noise).
- **`kiln[fast]`: compiled distance evaluation** (#112, numba, optional). The whole field is evaluated in one compiled,
  multi-threaded pass per point (every shape but extrudes; mirror, copies, rotation, twist, shells, open sides, noise),
  with each part skipped per point where its box shows it can't change the result. A 422-part 2.4 m character, lint at
  12 mm: 154 s -> 67 s; a 48-part one at 4 mm: 114 s -> 72 s. Output agrees with the plain install to ~1e-15 m, not bit
  for bit: pin one or the other in a game. `KILN_JIT=0` turns it off. Lint's worker processes share the cores.

### Changed

- Previews (`kiln preview`, its sheets, `kiln gallery`, scatters) show the occlusion `atlas_ao` bakes in (#109), as
  Godot does; before, they under-represented the built look.
- Pattern refinement looks split edges up with sorted integer keys instead of a Python dict over every edge: patterned
  and gradient parts build several times faster (a 70-lock model: 46 s -> 30 s). Output is unchanged.
- **Many-part models need far less memory** (#110). Painting, part areas, nearest-part lookups and lint's shell check
  kept every part's distance over every vertex (parts x vertices: ~3.4 GB for 422 parts on a 1M-vertex mesh). They now
  keep a running minimum per paint group or point. Output is unchanged.

### Added

- `kiln build` and `kiln lint` end with the run's time and peak memory (`--json`: `seconds`, `peak_memory_gb`), and a
  model build that has run over 10 s says what it is doing on stderr (meshing, painting, reducing, skinning) (#108).

## [0.15.0] - 2026-11-05

### Added

- **Mesh detail is a setting** (#103). The grid was capped at 256 cells across a model, so a 2.4 m hero could not be
  meshed finer than ~10 mm whatever the style asked for. Now:
  - style `[shape] max_cells` (64-1024, default 256) and `scale_with_size` (default true: models over 1 m get
    resolution x sqrt(size); false: the resolution as is);
  - model `resolution:` (metres per cell for that model, used as is) and `max_cells:`, overriding the style;
  - lint **W120**: the cap, not the resolution asked for, set the cell size; it names the `max_cells` needed;
  - `kiln build` prints each model's triangles and mesh cell size, and the manifest has `step` per model.
  Defaults are unchanged: existing models build byte-identically.

### Changed

- Faster, leaner meshing at fine resolutions: field evaluations go in small spatially tight batches (most parts are
  skipped per batch), fine samples and normals are computed in chunks, and the fold repair after dual contouring only
  rechecks faces it moved. A 2.4 m, 48-part character: 33 s -> 28 s at the default 12.6 mm, 196 s -> 114 s at 4 mm
  (peak memory ~2.8 GB there, ~0.3 GB at the default). Output is unchanged.
- Lint and build size their worker pool for the biggest model's mesh grid (~36 bytes per cell), not a fixed 0.7 GB,
  so several fine-resolution models no longer run the machine out of memory.

## [0.14.0] - 2026-11-04

### Changed

- **The skill is split for agents that pay per token** (#85). `SKILL.md` is a 6 KB core (was 17 KB) that is loaded
  whenever the skill triggers; the rest of the old SKILL.md and all of `reference.md` (60 KB) moved, unchanged, into
  17 topic files (`skill/topics/*.md`). `kiln skill install` writes them and removes an installed `reference.md`.
  The MCP resource `kiln://reference` became `kiln://docs/{topic}`.
- **`--json` prints compact JSON** (one line, no indentation). Pipe through `python -m json.tool` to read it by eye.
- `kiln status` lists models grouped by state (one line per group); `-v` / `--verbose` (MCP: `verbose`) gives the
  old per-model listing with descriptions. `--json` leaves out descriptions unless `--verbose`.

### Added

- `kiln docs [topic...] [--search words]` (MCP tool `docs`): lists the topics with their size, prints one, or
  prints the few paragraphs that match. Budget tests keep `SKILL.md`, its description and each topic under a size.
- `ruff check` in CI (#91).

## [0.13.0] - 2026-10-29

Issues #15, #16, #18, #19, #20, #21, #23, #26, #27 and #64: terrains, foliage scattering, CC0 pack mirroring,
Blender imports, clips on any skeleton, an opt-in Godot BoneMap, a richer toon look kit, hair under helmets, engine
import notes and a cross-machine measurement. Everything new is opt-in: existing models build unchanged.

### Added

- Terrains (#15): a `terrain:` model of height shapes (hill, ridge, plateau, noise, path) blended in order, with up to
  4 palette-colour splat layers driven by slope, height, path distance and noise rules. `kiln build` writes chunked
  glbs (32 m chunks) with LODs and skirts, a splat map PNG and a Godot scene with a splat shader and an inline
  `HeightMapShape3D`. Design point 256 x 256 m at 0.5 m cells. `kiln.terrain.load` gives height, normal, slope and
  splat queries. Lint W116/W117, `kiln preview`, `--verify-godot` checks.
- Foliage scattering (#16): a `scatter:` model kind places models (and variants) over a terrain, a model's top
  surface or a flat area at build time (density, spacing, scale/yaw/tilt jitter, slope/height/noise/splat/path rules,
  tint jitter), pre-rolled with `random.Random(seed)` into `<name>.scatter.json` and a Godot scene of
  `MultiMeshInstance3D`s per entry, model and chunk. Lint E015/W118/W119, `kiln preview`, `--verify-godot` checks.
- CC0 packs (#19): `kiln pack list/add/search/import`. Recipes for Kenney, KayKit and Quaternius packs (archive sha256
  pinned, CC0 checked) mirror into a per-user cache (`~/.cache/kiln/packs`, `KILN_PACK_CACHE`); `search` uses names,
  tags and an index of triangles and size, with `--json` and a `--lineup` sheet. `pack import` records every copied
  file in `kiln.lock`; a changed hash or a non-CC0 entry fails the build (E014), a missing file warns (W115), and
  credits name the pack. Only `kiln pack add` uses the network. MCP: `pack_list`, `pack_search`, `pack_import`.
- Blender imports (#20): `.fbx`, `.blend` and `.obj` import through the `blender` binary (Blender 4.x on PATH or
  `BLENDER=`) as a subprocess, then take the glb path. `kiln import` writes `imports/<stem>.glb`; files named directly
  in a model convert into `.kiln-cache/blender/`. `kiln doctor` reports Blender.
- `godot_bonemap = true` in kiln.toml (#21, default false): humanoids get `models/<name>.bonemap.tres` (a `BoneMap` on
  `SkeletonProfileHumanoid`) set in their glb's `.import`, so Godot retargets humanoid clips onto them. Godot then
  renames the skeleton's bones and node, so game code naming them must change; turning it off restores the files.
- Toon look keys (#26): `toon_softness`, `toon_shadow_color`, `toon_specular`, `toon_shadows = "band"`,
  `outline_space = "pixels"` and `outline_color = "darken"`. Previews follow them (except banded cast shadows: the
  software renderer has none). Defaults are today's look. `--verify-godot` also fails on shader errors.
- Hair under helmets (#23): `rig: { hair: { parent: head, revealed: [helmet], fold: true } }` on a model makes the
  library heads' scalp hair its own piece, hidden until the helmet comes off, and fits the helmet to the skull. New rig
  key `fold`. Without it every library combo builds as before.
- Clips on any skeleton (#64): `skeleton: { map: {...}, root_motion: <joint> }` retargets imported clips onto
  non-humanoid skeletons (bone -> clip joint, optional `child` to aim). Unmapped bones follow their parent; unmapped
  joints are ignored; no `root_motion` means no root translation.
- `docs/engines.md`: notes for importing KILN output into Unity, Unreal, Bevy, three.js and Defold (#18).
- A non-failing CI workflow builds the demo on x86-64 Linux, arm64 Linux and arm64 macOS and reports the differences
  (#27; `tools/compare_builds.py`).

### Changed

- W113 skips a part hidden by the shell it pokes through (#23).

## [0.12.0] - 2026-10-28

Issues #66, #67, #70, #71 and #72: hard-surface and text fixes (E013 cracks and crowded edges, an E009 crash, a hang).

### Fixed

- Bevelled extrudes no longer crack where a bar is narrower than twice the bevel (text with overlapping contours, such
  as a heavy serif S, and plain `path:`/`points` outlines alike): rings that would fold have their insets lowered just
  around the fold (#66). Bevelled outlines that folded before change there; others are unchanged.
- Interlocked hard parts (chain links with small turns) no longer fail E013 with faces back to back: CSG slivers
  thinner than the weld whose outline folds over itself are dropped (#67).
- A hard part beside loose hard links no longer fails with E009 "max() iterable argument is empty": a flat patch
  with no outline is kept as it is (#70).
- Text glyphs drawn as one self-crossing contour (Cinzel's 3 and 8) are filled nonzero like overlapping contours, so
  they bevel without cracks (#71). Such glyphs change, bevelled or not.
- Glyphs whose serif bars abut their strokes (Cinzel's X) fill as one piece and bevel without hanging (#72).

## [0.11.0] - 2026-10-27

Issues #31, #57, #60 and #61: effect previews show fade, the floor and chosen times; fitted shells no longer grow walls
inside their target; two E013 (non-manifold) failures fixed.

### Added

- `kiln preview <model> --effect --at 0,0.1,0.25,0.5,1` (seconds) gives a contact sheet at those times instead of 8
  evenly spaced frames (MCP `preview`: `at`, with `which='effect'`). Effect previews draw each piece's `fade` as ordered
  dithering, and an effect with a `floor` gets the plane drawn as a thin grid (#31). Built output is unchanged.

### Fixed

- Two hard parts (a sphere and an aimed cone, a flared cone through a chamfered box) no longer fail E013 with two
  zero-area faces back to back: points the CSG leaves a hair off an edge two flat patches share now count as straight
  in both patches (#60). Hard-part meshes can change where this happened.
- Smooth models with blended parts of different colours no longer fail E013 with crowded edges at a colour border:
  vertices the simplifier puts exactly onto a border vertex are joined before projecting and relaxing (#61). Smooth
  meshes can change where this happened.
- Shells fitted to a CC0 mesh (`fit_to`, `fit: target`) no longer grow walls inside the target around its inner
  pieces: the target's distance is signed per connected piece (angle-weighted pseudo-normals, min over pieces) and
  points enclosed by a piece read inside (#57). Such shells change; cached ones rebuild.

## [0.10.1] - 2026-10-26

### Fixed

- Atlas palette textures (and clip carriers) get KILN's Godot `.import` settings whenever the output is inside a
  Godot project, not only with `export = ["godot"]`: a game that loads the glbs itself no longer gets VRAM-compressed,
  blurred palette cells (#56).

## [0.10.0] - 2026-10-26

Issues #22-#25 and #50: `union: per_bone` for rigid skins, manifold meshes on thin parts, clean shell and sharp rims,
template library fixes, adjustable baked AO, and attachments checked on their bone in Godot.

### Added

- `kiln build --verify-godot` hangs every attachment fitted to a CC0 character (`fit_to`) on its bone of a copy of that
  character (BoneAttachment3D) and checks it lands where it was made (#22).
- `atlas_ao` takes a strength 0..1 as well as `true` (0.65, unchanged): the darkest corner's colour is x (1 - strength);
  the manifest's `atlas` gives it as `ao_strength` (#24).
- `union: per_bone` on a rigid-skinned model (#50): each bone's parts are meshed as their own closed surface and
  neighbouring bones overlap instead of being cut where they meet, so turning a joint (animations, ragdolls) can't
  tear the mesh, with or without `merge_rigid`. Default `whole` (unchanged meshes). W103 counts the bones' pieces as
  joined where they touch. `per_bone` on a soft or static skin is E007.

### Fixed

- Template library (#23): heads have a neck reaching into the collar, so a helmet no longer leaves the head a separate
  piece (W103) on some grids; `helmet_great` reaches from the shoulders to above every hairstyle (hair poked through
  its top) and `helmet_crown` is a ring open at both ends (its closed bottom crossed the head); `body_big`'s collar sits
  on its chest instead of inside it and its hidden spine capsule is gone (W101).
- Thin soft parts and narrow gaps no longer pinch (#25): dual contouring gives a cell one vertex per sheet of the
  surface crossing it (both sides of a wall thinner than a cell used to share one: edges with four faces), and where
  decimation joins the two sides of a thin part the vertex is split back into one per side. E013 now also reports
  edges with more than two faces and points where two sheets touch, not only open edges.
- Smooth shells shade cleanly at their rims (#25): a crisp corner's normal is sampled just off its face, so it no
  longer picks up the rim's normal (dark wedges along helmet and bowl rims).
- Thin sharp rims (a cone roof overhanging its tower) reach their edge instead of coming out ragged (#25): crossing
  points are found on the surface rather than interpolated linearly, and a best-fit point just beyond its cell is
  kept where it lies on the surface.

## [0.9.0] - 2026-10-21

Issues #28-#37: font text that holds together (nonzero fill, variable fonts, thin bevels), effect floors, gib pieces,
mixed loadouts on shared clips, retarget adjustments, and preview fixes.

### Added

- `font_axes: { wght: 900 }` on text extrudes picks a variable font's instance (any axis), so no pre-instanced copy of the
  font is needed (#29).
- Effect `floor: y`: debris bounces (`bounce`, `friction` per emitter) and settles (`settle`) on it instead of falling
  through; every floor hit is rolled into the effect JSON (`hits`: age, position, velocity), so players and `preview
  --effect` match (#31).
- Imported (retargeted) animations take `retarget: { keep: { joint: share }, offset: { joint: [x, y, z] } }`: damp a
  joint's turn away from rest (base names cover both sides) and add a fixed turn, for clips made for another body
  type (#34).
- `gib: true | [ids]` on a rig entry: `kiln build` also writes `models/<name>.gib.<id>.glb`, the part (and what hangs
  from it) as one closed static piece in the model's frame, for parts that come off; manifest `gibs` (#35).

### Changed

- `animation_library` no longer needs exactly the same part ids: every id the carrier's clips move must be in the model,
  other ids may differ (mixed loadouts: helmet, hat, shield follow their parents) (#33).

### Fixed

- `bevel`/`chamfer` (and a shrinking `offset`) on an extrude whose outline has sections thinner than about twice the
  bevel (font serifs, hairlines) no longer cracks (E013): the inset is limited per vertex to what fits there (#28).
- E013 names the colour of a crack on a hex-coloured part instead of an empty name (#28).
- Text extrudes fill glyphs by the nonzero rule, like font renderers: overlapping contours (static instances of
  variable fonts, many hand-made fonts) join instead of being cut out, so letters no longer fall apart (W103), mesh
  slowly or crack with bevels. Fonts without overlaps give the same outlines as before; SVG `path:` stays even-odd (#29).
- `kiln build` removes decal textures Godot extracted from a glb (`models/<name>_decal<N>_<hex>.png` and its `.import`)
  once no glb embeds that image any more (the colour changed, or the model is gone) (#32).
- `kiln preview --vs` counts `surfaces` and `materials` as `kiln build` writes them, with `atlas` on too (#36).
- Previews (turntable, `--closeup`, `--pose`, lineup, gallery, `--vs`) leave out `revealed` parts, as the exported
  scenes do; `--detach` shows a part's cap once it's taken off (#37).

## [0.8.0] - 2026-10-21

LOOSE report 44-58, now GitHub issues #1-#14: shared clips, merged rigid skins, revealed parts, Godot import
settings, partial builds, and E013 crack fixes. Hard-surface and humanoid output changes (meshes, pivots).

### Added

- `revealed: [ids]` on a rig entry (#3): a part shown only once one of those parts is gone (stump caps). It is
  its own piece, hidden by KILN's .tscn scenes, marked `kiln_revealed_by` in the glb and `revealed_by` in the
  manifest; `--verify-godot` checks it starts hidden.
- `merge_rigid = true` in kiln.toml (#9): a rigid skin is exported as one skinned mesh, every vertex 100% on its
  part's bone (rigid look, one draw call instead of one per id); `separate` parts stay their own nodes. Hide a part by
  scaling its bone to 0. Manifest: `merged_rigid`.
- Shared clips (#5): `animations_only: true` makes a model a clip carrier; `animation_library: <carrier>` on another
  model plays its animations (same part ids: E008; joints over 1 cm away from the carrier's: W114) and its glb
  carries no clips. Manifest: `animation_library`, `animations_only`. With "godot" the carrier is imported as an
  AnimationLibrary (no `.tscn`); `--verify-godot` checks it.
- Godot import settings (#14): with "godot", palette atlas textures get `.import` settings (lossless, no mipmaps, no
  VRAM compression on first 3D use) and clip carriers the animation_library importer; what Godot adds later is kept.
  `--verify-godot` imports with them.
- `node_prefix: Knight_` on a model: mesh nodes are `Knight_<id>` children of their parts' nodes (a soft skin's mesh
  is `Knight_mesh`); bones and animations keep the part ids. Manifest: `node_prefix`, `mesh_node` per part (#7).
- Animation names may use capitals (`Idle_A`: imported clips keep their library names); names differing only in
  case are E008 (#4).
- `kiln build <models>` (MCP `build` models): builds only those; the other models keep what the last build wrote,
  so one broken model doesn't block the rest (#13).
- `kiln preview --vs <ref.glb>` metrics for restyles (#8): `band_iou`/`band_ious` (silhouette IoU per body band,
  each band normalised; head/torso/legs for humanoids against a rigged reference, else thirds), `mass`/`mass_ref`/
  `mass_ratio` (visual mass), `screen_px`; the sheet gains a row at 30 m and 60 m (60 degree FOV, 1080 px screen).

### Fixed

- Default `skeleton: humanoid` pivots sit on the joints: a capsule (cylinder, cone, tube) limb pivots at its axis
  end, not the top of its rounded box (upper legs were 8 cm above the hip, upper arms at the top of a shoulder ball);
  hands, feet and toes where the limb above them ends (wrist, ankle; feet were at the heel) (#6).
- Hard-surface CSG cracked (E013) where near-coplanar facets of several parts meet (a faceted skull, jaw and hair):
  each union, cut and intersect built its BSP trees from only the polygons near the other solid. The trees are now
  built from whole solids; only the nearby polygons are clipped (#2).
- Soft parts blended at one spot (a straw tuft of capsules) bulge out of their boxes by up to a quarter of the blend
  per join; where that left the sampling grid, the mesh had a hole (E013). The grid grows on any side the surface
  reaches (#11).
- Bands and stripes (model space) on hard parts are cut along their border planes on the exact faces, without
  refining the mesh first: three bands on a stepped hard lathe went from 30x the budget to its cuts (#12). A colour
  border through a vertex no longer leaves zero-area slivers there.
- E013 lists each crack with its place and parts (up to five), not one centroid of all of them (#10).
- Hard `lathe` parts take `shell:`, and `open: -y`/`+y` on a lathe cuts just its end wall (the profile sits anywhere
  on its axis; before, it cut at local y = 0): hollow hard helmets with a visible rim (#1). Hard parts no longer get
  W102 (thinner than the mesh resolution): they're exact polygons.

## [0.7.1] - 2026-10-21

### Added

- The skill asks agents to report what got in their way (crashes, misleading messages, workarounds, missing
  features) as GitHub issues at https://github.com/lukasgolino/kiln/issues: a minimal-repro draft, a duplicate
  check, and filing only once approved. `.github/ISSUE_TEMPLATE/agent-report.md` and the `agent-report` label.
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

Toward CC0 parity (from the LOOSE! dogfooding report, items 23-25).

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
- Skill: a "match a reference" workflow (iterate until the metrics are inside the agreed thresholds).

### Fixed

- Cracks at colour borders (LOOSE 23: 36 open edges on a footman; the demo knight had 48): cutting a border split
  only one side of an edge, leaving T-junctions. Every demo model is now closed.
- Zero-volume fins (pairs of opposite faces) that decimation could leave on thin parts are removed.
- Smooth shading streaked across flat faces next to crisp edges (a cylinder's cap): the crease test compared the
  field's normal on the edge (the bisector) with the full `sharp_angle` instead of half of it.
- W102 and thin-part protection use a shell's wall thickness.
- The preview renderer crashed when a batch of triangles covered no pixel centre (close framings).

## [0.3.0] - 2026-10-20

From the LOOSE! dogfooding report (items 1-22).

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

[Unreleased]: https://github.com/lukasgolino/kiln/compare/v0.22.0...HEAD
[0.22.0]: https://github.com/lukasgolino/kiln/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/lukasgolino/kiln/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/lukasgolino/kiln/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/lukasgolino/kiln/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/lukasgolino/kiln/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/lukasgolino/kiln/compare/v0.16.1...v0.17.0
[0.16.1]: https://github.com/lukasgolino/kiln/compare/v0.16.0...v0.16.1
[0.16.0]: https://github.com/lukasgolino/kiln/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/lukasgolino/kiln/compare/v0.14.0...v0.15.0
[0.14.0]: https://github.com/lukasgolino/kiln/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/lukasgolino/kiln/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/lukasgolino/kiln/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/lukasgolino/kiln/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/lukasgolino/kiln/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/lukasgolino/kiln/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/lukasgolino/kiln/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/lukasgolino/kiln/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/lukasgolino/kiln/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/lukasgolino/kiln/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lukasgolino/kiln/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/lukasgolino/kiln/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lukasgolino/kiln/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lukasgolino/kiln/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lukasgolino/kiln/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lukasgolino/kiln/releases/tag/v0.1.0
