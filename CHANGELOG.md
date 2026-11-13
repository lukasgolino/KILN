# Changelog

All notable changes to KILN. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions:
[SemVer](https://semver.org/) (any change to the notation, settings, manifest or meshes is at least a minor bump
before 1.0).

## [Unreleased]

### Added

- Lint W140: a part mirrored in one piece whose `blend_to` names one side of a mirror_id pair (#252).
- `kiln style check [style]`: each palette colour as the look lights it beside its hex, with its hue and lightness
  shift, and a swatch sheet (#336).
- `kiln examples [name]`: the worked example models (the demo's) ship with KILN and print from the CLI; the docs
  point there (#308).
- `kiln docs --search` knows engine words: emissive finds glow, metallic metal, transparent alpha and clear,
  instancing instances, and more (#164).
- `bevel` and `chamfer` on lathes: the outline's corners are rounded before it is spun (a bezel ring with a lip),
  as a hard part (#338).
- `bevel_edges: vertical | top | bottom | horizontal` picks the edges a bevel or chamfer rounds (a thin seat's corners
  only) (#345).
- Assemblies: `mount: { to, at, rotate }` on a model built to sit on another (a shared frame: no W106/W123 ground
  checks; `mount` in the manifest), and `kiln preview <model> --with <others>` to see them together (#181).
- `kiln fit <a> <b> [--at] [--rotate]`: does b fit a in their shared frame: overlap volume, how deep each goes into
  the other, the smallest gap (a movement in its case, a crystal under its lip) (#341).
- `base: [x, y, z]` places a cone or cylinder by its bottom centre (turned with it) instead of `at` (#332).
- `kiln.api.transform(parts, rotate, about, translate, cut_only)` (positions, rotations, aims, array centres, decal
  centres and axes; mirrors written out as pairs; scoped cuts), `kiln.api.surface_point()` on lathes and cones,
  `from_=` for capsules, and a reference with signatures in `kiln docs api` (#172, #206, #346).
- `kiln preview <model> --variants`: every variant side by side in one sheet, a row each (#330).
- Palette-indexed textures (`texture: { rows, key }`) and generated pixel art in palette colours (`generate: brushed |
  specks | scratches | grid | noise`), recoloured by variants (each such variant gets its own glb); lint W137: a
  pixel-art image off the palette on a model with variants. Decals and textures moved to `kiln docs textures` (#325).
- Patterns painted per texel into the base colour map (`paint: map`; by default pixel and dots patterns of a model
  that bakes maps), so trims cost no triangles; error E016 when a substantial part (15% of the model across, not a
  thin blade) vanishes to the budget (others stay W111) (#324).
- Lint W136: a band, pixel or stripes pattern that paints nothing on its part; the docs say a pixel band's `at` is
  from the part's own `at` (a lathe's origin) (#326).
- Motif prints: `texture: { motif: { images, count, scale, rotate, seed } }` scatters multicolour stamps over a
  seamless, seeded tile made in KILN (a floral shirt), tiled like any texture (#312).
- Material `grain` and `grain_size` in a style: a fine bumpy finish in the normals (rough cloth, felt) without
  geometry or triangles; a tiling noise normal map in KILN's Godot scenes, the same bumps in the previews (#329).
- Named textures: `textures: { print: {...} }` at the top of a model, `texture: print` on each part; and
  `project: triplanar` (box UVs in the glb; KILN's Godot scenes and the previews blend the three projections, so no
  seam at a sleeve's side) (#320).
- `kiln library <name>` prints a template's YAML; toy-proportioned templates `body_toy` and `head_toy` for
  soft_toy characters (#188).
- Garments: `collar: { style: band | open, height, depth, lapel }` (an open collar cuts a V and lays lapels on the
  chest), `placket: { width, buttons, button_color }` down the front, V openings (`shape: v`), and `length:` for a
  sleeve or trouser leg that runs along its limb and ends square and open (T-posed arms too) (#279).
- `folds:` on a capsule or a tube run round its own axis (trouser legs, sleeves), and `bunch: true` stacks rings
  along the axis (cloth bunched at an ankle); the compiled path has both (#315).
- An `idle` cycle: breathing, a slow sway, the head glancing to either side, arms and elbows settling. KILN ships
  KayKit's CC0 humanoid clips (26: idles, walks, runs, jumps, hits, deaths, throw, pick up): `kiln clips` lists
  them, `kiln clips add` copies them with their licence into `imports/kaykit-animations/` (#150).

### Fixed

- The MCP server's instructions point at `kiln://docs/{topic}` (not the gone `kiln://reference`); a test checks every
  `kiln://` URI it names is served (#159).
- CI: the godot job and its long steps have timeouts (a hung render once ran 4 hours); a test checks the committed
  demo says the package's version, so a release can't forget to rebuild it (#264, #254).
- W122 is quiet when a blend_to id has a soft part to melt into, though its crisp details (eyes, teeth) are kept
  apart (#152).
- `kiln build <deleted model>` says its last glb and scene stay until a full `kiln build` removes them (#182).
- `kiln new` writes the project palette's first colour where a template's colour isn't in the palette (#340).
- A look's `ambient` above 0.9 now brightens Godot too (the sky's `energy_multiplier`; Godot ignores
  `ambient_light_energy` while the sky gives all the ambient light): the skin and clay looks match their previews,
  and both join the colour-parity grid (#350).
- Reading a glb (references for `--vs`, imports): a skinned mesh ignores its node's transform, as glTF says; a model
  compared against its own skinned, vertex-coloured build matches (#227).
- See-through parts (`clear`, glass) are alpha-blended in software previews instead of dithered, so they read
  as in the engine (#342).
- Previews draw `tonemapper = "agx"` and `"aces"` with their own curves (close stand-ins), not as filmic (#337).
- Pose sheets: bigger tiles when there are few frames (one pose up to 450 px), and the style's background (`--bg`)
  as the other sheets have, so glows read on low-key looks (#322, #331).
- `preview --closeup` honours `--views` and `--pitch` (#309).
- `--frame-box`, `--at`, `--rotate` and `--pitch` take values starting with a minus (`--frame-box -0.25,...`) (#317).
- Hard flat faces keep their own normal to every corner when their flat is clearly the biggest there (only bevel
  bands blend), so long triangles across a flank no longer shade a diagonal crease; cavity shade on a sliver
  triangle (a fan across a flat where parts rest) is evened out over it instead of streaking (#335).
- Lint measures a scene with its instances placed (W108 size, W103 pieces joined by instances, the triangle line;
  W110 holds the model's own parts to its budget); a scene may be instances only, without `parts:`; the docs say
  `rotate` turns an instance about its origin before `at` (#333).
- `kiln.api.offset()` moves mirrored parts as written-out pairs, a lathe's part-level `at` (not a second one), array
  centres and decal centres (#172).
- Scatter LODs of a model with a normal map (or colour map) keep their own maps instead of LOD 0's on their own
  UVs (#259).
- A part that fails to read no longer drags in rig E007 for its id; the docs say `sides` makes a part hard (#327).
- `kiln.api.part(..., cut=True)` keeps `color` and `material` (they paint the cut's walls) (#344).
- A cut accepts `id` and `mirror_id` (they name it; shared option sets in generators work) instead of E003; a
  mirrored part's texture keeps its palette key (#153).
- No raw numpy RuntimeWarnings in `kiln` output (lint workers too); degenerate hard normals are guarded (#339).
- An instance's decals and textures come with it into the scene, turned with it (they were dropped); scaled
  instances still leave them out. Shared meshes and maps through instances: #353 (#295).
- Toon `outline_color = "darken"` previews take what Godot's outline takes: a glowing part's dimmed colour, vertex
  colours and shade, and the colour map (#290, #292).
- Godot variant scenes that recolour by the swap table cap and dim a recoloured glow as the glb does (standard and
  toon), instead of keeping the source colour's strength (#288).
- Small cut dots no longer vanish: the mesh refines down to the smallest dot, not the dot spacing (#283).
- A `band` or `stripes` pattern with `frame: part` on a hard part painted nothing: it is cut along its planes in the
  part's frame (#286).
- Docs: textures over 256 px are filtered smoothly with mipmaps, uncapped; a cylindrical texture's v = 0 is at its
  `at` (#321).
- `band: { fit: ... }` round a surface that isn't round (a belt round hips and belly) hugs it as a fitted shell
  instead of a cylinder sized to its farthest point (a flange at the back); `fit` takes a list of ids. Round ones
  (barrels, posts) keep their exact hard ring (#316).
- Lint W113 no longer flags intended overlaps with clothing: parts passing through a garment's hem, neck or
  openings or an open shell's open side, and body parts another garment wraps (an arm through an armhole, the chest
  under a sleeve) (#313).
- The `wave` cycle on an arm with a forearm (humanoids) holds the upper arm out to the side and waves the forearm
  from a bent elbow, whatever the rest pose, instead of raising the straight arm up by the head (#319).
- `frames:` written on an animation instead of inside its `cycle:` now says where it goes (E008); the docs show it
  inside the cycle (#318).

### Changed

- `kiln lint --fast` gives the warnings that need no mesh: W104, W109 and W121's missing map (#249).
- W103 counts pieces that touch as one (a smooth detail on a hard part, hard parts face to face, an instance),
  leaves out `separate: true` parts, and names the smallest floating piece and where it is (#173).
- Error wording: a model without `name:` takes its file's name; `- { shape: sphere, ... }` shows the right form; a
  part option written inside the shape (`bevel`, `scale`) and a shape field written beside it (`sides`) say where they
  go; W101 says "other parts" (not "later"); W120 is quiet on all-hard models (#168, #190, #177).
- Lint names parts as the model file has them: their `parts:` entry (before hardware expands), the kind written
  (`garment shirt`, not the box it became), the id and the line; per-part warnings (W101, W102, W111, W128) about
  more than three parts of one kind come as one line with the rest listed (#314, #235).
- Lint W102 says how wide the part is at its thinnest and offers `hard: true` / `sides:` (for shapes that can be
  exact) and `resolution:` besides making it thicker; W128 leads with `density` on the part and says how many
  triangles each fix costs (#304, #323).
- Under budget pressure hard parts lose their bevels a few at a time, the smallest first, after the chamfer step,
  instead of all at once; lint W139 says when bevels went and what budget keeps them (#334).
- UV charts in baked maps sit 8 texels apart as meant (they were 17: xatlas pads each side), so the maps hold more
  detail; lint W121 and W133 use the bake's real texel size instead of assuming a half-full map (#257).
- A model of hard parts only reports its hard part count instead of a mesh cell size in the lint and build
  summaries, and lint `--json` lists no `cells` entry for it (#243).
- The glow cap follows the look: divided by its `exposure`, and 1 (where it clips) instead of 0.75 under a linear
  tone curve; previews cap per material from its flat colour, as the glb does; lint W138 for an emission above its
  colour's cap (#290).
- Lint W123 (the mesh dips under the ground) names the part that dips, where, and by how much, on that part's line
  (#195).

## [0.25.0] - 2026-11-13

Iteration speed and the hero skin look (milestones 0.24 and 0.25; 0.24 was not released on its own). A colour or
relief edit rebuilds from cache in under a second and a large model's lint is about twice as fast; relief by colour,
new relief kinds and displacement; a part's own finer resolution; group posing; hand, foot and eye generators; colour
fades per vertex; shade paint per texel; a fill light in the look kit (on in skin); lint W133-W135. Builds of models
with relief, fades, shade paint or the skin style change (see Changed).

### Added

- `transforms:` turn and move a group of parts about a pivot (a hunched rest pose), rig pivots and sockets with
  them; a mirrored part refuses a turn that breaks its mirror (E003) (#305).
- A part's own `resolution:` (metres): the mesh inside its box is refined to that cell and moved onto the surface
  along its normals, so a face gets its lids, nostrils and nose on a body meshed coarsely, without the whole model's
  cells shrinking; pair it with `density` (#306).
- Relief kinds `scales` (a round lobe), `feathers` (one point and a rib) and `shingles` (a straight edge) next to
  `fur`; `flow: along` follows each part's own axis out from the body; `displace: true` moves the mesh out by the
  layer, so tufts break the silhouette (the normals stay, so the map isn't counted twice); a model's LODs stamp its
  full build's patches, so the pattern is the same at every level; lint W133: patches under four texels wide (#261).
- Relief picks its faces by painted colour (`on_colors: [fur]`; alone: every smooth part in those colours) and leaves
  ids bare (`except: [face, chest]`), so a bare chest or face that shares bones with the fur needs no extra bones
  (#301). The docs list `kind: fur` (#307); folds, relief and colour fades moved to `kiln docs surfaces`.
- `hand:` and `foot:` hardware: a soft hand (palm, curled tapered fingers, thumb, claws with their own colour) or
  foot (sole standing on `at`, toes, heel) as ordinary parts that blend into the arm or leg (#310).
- `eye:` hardware: a recessed eye (a socket cut into the face, a ball sunk in it, a thin rim lining the edge, flush
  with the surface, optionally glowing) instead of a torus and a flattened ellipsoid that stand proud (#328).
- `color_blend` without the baked maps: with `normal_map: 0` (or without `kiln-gen[bake]`) the fade goes in the
  vertex colours (COLOR_0, `vertex_colors = true`), previews too; lint W134 when the project doesn't export vertex
  colours (#262).
- A fill light in the look kit: `[look] fill_energy`, `fill_pitch`, `fill_yaw` (default: opposite the sun),
  `fill_color`; a second DirectionalLight3D without shadows in the look scene, and the same light in the previews
  (parity tested in both renderers). On in the `skin` preset (0.3) (#275).
- Lint W135: on a soft-skinned body, a limb fused to another branch at rest (an arm hanging into the belly, a leg
  into the other leg) away from its joint, with how far to move it (#255).
- `kiln build <models> --no-dependents`: the models that place them (instances) keep their last build (#343).

### Fixed

- Scatter-scene previews draw a placed relief (or colour-faded) model with its colour map, sampled at the corners,
  instead of flat paint. Gibs of a relief model keep their fur and fades on a quarter-size map of their own instead
  of flat colours (#349).
- Where three colours meet, a `color_blend` fade no longer flips its target at the bisector: both other colours
  mix in by their own distances, a third each at the corner (#262).
- A paint border across a smooth blend (a bare belly into fur) drew a thin shading line: each side took its own
  normal there, as at a real crease. Sides keep the surface's normal unless they turn more than 15 degrees from it.
  And relief layers that meet (an upper arm's and a forearm's) no longer each fade out toward the other: the fade runs
  to where the fur ends, so no bare band at the elbow (#302).
- Relief no longer draws stepped streaks where the surface faces along the flow (the top of a round shoulder under
  `flow: down`, the underside of a heel): there the flow can't lie in the surface, so the patches thin out and shrink
  as they do toward an edge, instead of all pointing one fixed way (#303).
- A lock's (and an ellipsoid's) distance ran short away from it, below the distance to its own box: the compiled
  path then skipped it by its box where the numpy path still blended it in, so the two disagreed near many locks
  (and numpy's answer depended on how points were batched). Outside its box such a part's distance is now never
  under the box's, in both paths. Models with many locks may mesh slightly differently (#238).
- `kiln preview --draft` on a model with part `density` and a budget above the draft mesh's face count stopped with
  E009 (the simplifier refuses a target it is already under); it now leaves the mesh as it is (#299).

### Changed

- Shade paint on a model with a base colour map (relief, `color_blend`) is painted per texel into the map, from
  the normal map's normals and each texel's occlusion, with the same strengths; its mapped faces carry no COLOR_0
  multiplier any more (no double shading). Fine grooves and relief now shade too (#266).
- The `skin` style's hero budget is 60k (was 20k): a close-up character with relief fur and a readable face (#311).
- `kiln lint` prints the static findings first (a `static checks:` line pointing at `--fast`), then builds the
  meshes for the rest; a long build ends with one line saying where its time went (`built in 156 s (meshing 12 s,
  ..., baking maps 112 s)`). Full lint stays the default (#186).

### Performance

- A base colour map is written in 0.7 s instead of 1.6 s at 2048, with half the memory: the padding grows only
  where it fills (the same bytes), float32 colours and an sRGB table (#349).
- Parts with `folds` use the compiled distance too (they took the numpy path for every field pass: about 2x on a
  model with one folded robe); the same values to 1e-9 (#281).
- Joined hard parts are kept in the build cache every 8 joins; a rebuild resumes at the last unchanged one, so moving a
  prop near the end of a scene joins again only from there (an 82-hard-part desk: 35 s cold, 9 s after moving one
  part), with the same result as joining from the first part. Hard parts lose bevels for the budget only when they
  need its smooth parts' share: that share now follows how much of the surface the smooth parts are (a movement's
  few small pins no longer cost 36 hard parts their bevels) (#214).
- A colour-only edit reuses the cached build, recoloured: part, pattern, relief and palette colours, as long as the
  same parts share colours (the paint borders don't move). A 2.4 m hero's colour tweak goes from a full rebuild
  (about 2.5 min) to seconds (#246).
- Normal and colour maps bake about 45% faster (a 2.4 m relief-furred hero with 2048 maps: 285 -> 156 s for the
  whole build): a texel is supersampled only where the surface turns away from the mesh (elsewhere its own normal is
  as good; the map changes by 0.006 degrees on average), the charts are packed again without being cut again when
  the atlas comes out too big, and a surface point already on the surface takes no second step. The bake has its own
  progress line, `baking maps`; it ran on under `skinning`, which then looked stuck on its last part (#300).

## [0.23.0] - 2026-11-12

Look and features. Relief layers (fur as patches in baked maps), colour that fades across part borders, shade
paint, part density, a skin style preset, garments, cloth folds, patterns (offsets, jittered dots, pixel motifs),
per-copy decals, glow that keeps its hue, see-through materials, painted and scoped cuts, aim and two-bone IK in
poses, gaits with bending knees and elbows, instances (models placed in a model), variant ramp swaps, and preview
framing; toon previews now match Godot (toon models are darker in Godot: see Fixed). Most meshes with colour
borders or decals change a little and every cached build is rebuilt once.

### Added

- `instances:` place other models in a model (a desk with its props), each its own build at its own detail, merged
  in after the scene is built (`at` in the scene's model space, at the instance's origin; LODs build each instance at
  the same share; a partial build rebuilds the models placing a rebuilt one). Shared meshes, instances' decals and
  maps, and scenes with normal maps: #295 (#171).
- Preview framing and light: `--tight` (each tile on what it shows), `--frame-box` (a region), `--fill` (a neutral
  light from the camera, previews only), `--bg auto|light|dark` (auto: dark for dark-sky styles), `kiln lineup
  --pitch`; `--closeup NUMBER` documented (a part's place in `parts:`) (#180, #203, #212).
- `cut: [ids]`: a cut names the parts it cuts. Those parts are meshed as their own surface, so the cut keeps to
  them in one model too (before, `cut: <id>` only held for separate or fitted parts: elsewhere it cut everything
  before it); they are split off only where the cut also reaches parts it doesn't name (#209).
- A cut can take `color` (and `material`): the walls it makes are painted, smooth and hard parts alike (inked
  grooves, panel lines) (#178).
- See-through materials: a preset's `alpha` (0.05-1; glTF BLEND, Godot transparency, the toon shader too, kept by
  variant recolours; previews dither it) and a `clear` preset in the built-in styles (`glass` stays opaque, so
  existing models don't change). Lint W131: see-through parts in an atlas project are drawn opaque (#175).
- Poses point parts at model-space points: `aim: [x, y, z]`, and two-bone IK `reach: [x, y, z]` (`pole:` for the
  middle joint) on an upper arm or thigh; `kiln preview --pose --json` gives each part's end per frame (`ends`)
  (#200); lint W132: `reach` on a part without exactly one child. The manifest's `start` poses now come from the
  solved frames (with the skeleton, as the glb).
- Variants swap whole palette ramps, shade for shade: `swap: { robes: golds }` (the palette's `ramps:`, same length;
  colour entries win over ramps; a shade two ramps share is swapped only when named). Lint W130 (and
  `kiln preview --variant`) names colours a variant leaves that go with one it swaps: the same ramp, or close in hue;
  `skin: skin` keeps one quietly (#205).
- `emission:` on a part: its own glow strength over its material preset's (#202).
- Decals: `per_copy: true` on an arrayed part puts the decal on every copy (sharing one texture in the glb), and
  `texel` (metres per image pixel) sizes a decal from its image instead of `size` (#211).
- `pixel` pattern: a pixel motif (`rows` of `#` and `.`, or a small PNG) tiled round a part's own axis in a band,
  `size` metres per cell, `repeat` times round or `auto` (about square cells): Greek keys, zigzags and checks round
  hat bands, hems and cuffs, cut into the mesh crisply, reading left to right like cylindrical textures. Smooth parts
  only (#198).
- Patterns: `offset: [x, y, z]` shifts stripes, checks and dots; dots take `jitter` (each dot moved up to half that
  of a cell each way) and `vary` (its size by up to that share), random per cell from `seed` (default: the pattern's
  place in the list), for speckles and scattered spots; with `frame: part`, mirror sides and array copies scatter
  alike. A second, third... `dots` pattern in a list without its own `offset` sits at its own place in the cell (they
  fell exactly under the first and never showed) (#194).
- `folds: { count, depth, from_y, to_y, sharp }` on a part: cloth folds round its own y axis, deepest at the hem and
  fading out higher up (robes, skirts, capes), as real shape (#204).
- `garment` hardware: a layer of clothing fitted to earlier parts (a shell `gap` off their surface between `from_y`
  and `to_y`, open at the hem and neck), with an optional thicker `hem` band and `openings` cut through it alone
  (mirrored with the garment). A fitted shell may now wrap an earlier fitted shell (a shirt over trousers) and parts of
  its own id (a sleeve on the arm's bone, which then moves with the arm) (#193).
- The `skin` style preset: stylised game skins with matte materials, colours that fade where parts blend, shade paint
  (darker crevices and undersides) and a soft look kit; fur as relief and face `density` in its notes and worked
  example (`kiln docs styles`) (#233).
- `[shape] color_blend` in a style: every smooth part that blends into a part of another colour (and doesn't set its
  own, and isn't made hard) fades its colour that far into its neighbours'; the baked colour map comes on for such
  models (not without `kiln-gen[bake]`). A part's `color_blend: 0` keeps its borders crisp from both sides. W127 only
  for a part's own color_blend (#262).
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

### Changed

- Docs (making): when to choose hard parts (mechanical props: flat faces, holes), and how toy metal picks up the
  ground's colour and how to get cool cartoon steel (#176).
- Glowing colours keep their hue: a glowing material's strength is capped per colour (its brightest channel x
  strength at most 0.75; past it Godot's tone curve bends the hue) and its lit base colour is dimmed (x 0.3), in the
  glb, the atlas (variants included) and the previews.
  A pale pink at glow 2 rendered white in Godot and previews; now it stays pink (#202).
- Decal cuts snap values within 1e-6 of a cut line onto it (no near-twin vertices beside a cut point); decal
  meshes may change slightly; cached builds are rebuilt once (#211).
- `kiln docs parts` split in two: `parts` (shapes and part options) and `surfaces` (hard surfaces, hardware, patterns,
  decals, textures). The topic had hit its size budget; the details cut to fit it are back (#270).

### Performance

- Hard parts join faster: a BSP node tests each polygon's box (made once, carried down the tree) against its plane
  in one numpy pass and splits only the polygons the plane crosses; output is the same polygon for polygon. The
  82-hard-part desk scene's hard pass 47 -> 28 s (#214).

### Fixed

- Toon: `kiln preview` and Godot agree (#183). The Godot toon shader took the sun at PI x its strength (Godot's
  `LIGHT_COLOR` carries a PI for PBR's divide), so toon bands came out washed and clipped (gold went yellow); they
  now light as the preview and the standard shader do. **Toon models are darker in Godot than before**: the
  palette as written. The preview's outlines are the inverted hull Godot draws (outward only, the set width), not
  a line twice as wide across each edge. Engine parity mean OKLab gap 0.16 -> 0.03.
- A decal on a part with a `gradient` or `pattern` also cut and marked other parts' faces painted in the same colours
  (their band and stripe colours are shared): it now keeps to the faces nearest its own part (#146).
- Colour borders along blends zigzagged at lower budgets (a sawtooth on a sleeve's edge from about 1200 triangles
  down): thinning a border to the budget left its vertices either side of it. Each vertex where two plain colours meet
  now goes back onto the exact border after reducing (along the surface, at most half an edge). And a decal that wraps
  round a side ended on whole triangles (a stepped edge): it is cut along where the surface turns away too, within
  its rectangle and on smooth surfaces (a hard part's flat faces: their own normal decides). Meshes with colour
  borders or decals change a little; cached builds are rebuilt once (#191).
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

[Unreleased]: https://github.com/lukasgolino/kiln/compare/v0.23.0...HEAD
[0.23.0]: https://github.com/lukasgolino/kiln/compare/v0.22.0...v0.23.0
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
