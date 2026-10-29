# Changelog

All notable changes to KILN. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[SemVer](https://semver.org/) (any change to the notation, settings, manifest or meshes is at least a minor bump
before 1.0).

## [Unreleased]

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
  features) as GitHub issues at https://github.com/lukasgolino/KILN/issues: a minimal-repro draft, a duplicate
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

[Unreleased]: https://github.com/lukasgolino/KILN/compare/v0.12.0...HEAD
[0.12.0]: https://github.com/lukasgolino/KILN/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/lukasgolino/KILN/compare/v0.10.1...v0.11.0
[0.10.1]: https://github.com/lukasgolino/KILN/compare/v0.10.0...v0.10.1
[0.10.0]: https://github.com/lukasgolino/KILN/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/lukasgolino/KILN/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/lukasgolino/KILN/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/lukasgolino/KILN/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/lukasgolino/KILN/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/lukasgolino/KILN/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/lukasgolino/KILN/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/lukasgolino/KILN/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/lukasgolino/KILN/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/lukasgolino/KILN/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/lukasgolino/KILN/releases/tag/v0.1.0
