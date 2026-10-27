# KILN notation reference

Units are **metres**. **+Y is up**, a model **faces +Z** (its front), **+X is its left**, and it **stands on y = 0**.
Angles are degrees. Colours are names (or keys) from the project palette (PAGAN's `.pal.yaml` format); `"#rrggbb"`
works but warns (W104).

## Project

```
kiln.toml            settings (kiln config show)
palettes/main.pal.yaml   colours (PAGAN format): models use their names
models/<name>.kiln.yaml  one model per file (name = file name)
styles/<name>.style.toml own styles; styles/<name>/inspiration/*.png|jpg reference images
decals/  imports/        images for decals; imported .glb/.gltf files
BRIEF.md  STYLE.md       what the game needs; how it looks (+ changelog)
```

```toml
# kiln.toml
default_style = "soft_toy"     # kiln style list
default_palette = "main"
output_dir = "build"           # inside the Godot project when export has "godot"
preview_dir = "previews"
export = ["glb", "godot"]
style_version = 1
variant_glbs = true            # false: no .glb per variant; Godot gets <name>.<variant>.tscn recolouring the base glb
merge_rigid = false            # true: a rigid skin is one skinned mesh (one draw call; every vertex 100% on its part's bone;
                               #   separate parts stay nodes; hide a part by scaling its bone to 0); manifest merged_rigid
vertex_colors = false          # true: colours in the vertices, one surface per material preset (fewer draw calls)
atlas = false                  # true: one material per model from small palette textures (1 surface, 2 with decals)
atlas_ao = false               # true or a strength 0..1 (with atlas): ambient occlusion baked into the vertex colours
[lint]
disable = ["W106"]
```

## Model file

```yaml
name: pilot                    # = file name (pilot.kiln.yaml)
description: bean crew member in a pilot cap
class: character               # size class: picks the triangle budget (style [budgets]) and size checks
tags: [crew]
status: draft                  # draft | approved
style_version: 1
style: soft_toy                # optional: else kiln.toml default_style
palette: main                  # optional: else default_palette
budget: 6000                   # optional: triangles (overrides the style's budget for the class)
lod: [2500, 800]               # optional: extra lower-detail .glb files
origin: center                 # optional: the .glb's origin: base (bottom centre of the box) | center (spinning debris) | [x, y, z]
                               #   (default: model space as written; manifest `origin` = that point, other manifest values stay model space)
node_prefix: Knight_           # optional: mesh nodes are Knight_<id> children of the part nodes (bones keep the ids;
                               # a soft skin's mesh is Knight_mesh); manifest parts get mesh_node
animation_library: soldier_anims # optional: play that clip carrier's animations (its glb has them; this one none)
animations_only: true          # optional: this model is a clip carrier for others' animation_library
parts: [...]                   # the shapes (below)
rig: {...}                     # optional: bones (below)
skin: soft                     # none (static) | rigid | soft; default rigid when there is a rig
union: whole                   # rigid skins: whole | per_bone (each bone its own closed surface: joints can't tear)
animations: {...}              # optional
variants:                      # optional: recoloured copies (<name>.<variant>.glb, or swap tables: variant_glbs)
  copilot: { swap: { red: green } }
lint: { disable: [W106] }
```

### Model families

A model can `extends: <base>` a `template: true` model in the same folder (templates are checked but not built):
soldiers sharing one body, trees sharing one trunk.

```yaml
# models/soldier.kiln.yaml
name: soldier
template: true
class: character
parts: [...]                   # body, arms, hat (id: hat)
rig: {...}
animations: {...}

# models/archer.kiln.yaml
name: archer
extends: soldier
remove: [hat]                  # base parts with these ids (or mirror_ids) are left out
parts: [...]                   # added after the base's parts
variants: { blue: { swap: { red: blue } } }
```

The base's parts come first, then the model's own; `rig`, `animations` and `variants` merge by name (the model's
win); every other field is inherited unless the model sets it, except its identity (name, description, tags, status,
style_version, template). Templates can extend templates.

Size classes in the built-in styles: prop, character, hero, creature, vehicle, machine, building, nature (and
`default` for anything else). Size sanity (W108, largest side): character 0.2-4 m, prop 0.02-6 m, building 1-200 m...

## Parts

Each part is one shape plus options. Parts are combined **in order**: each one joins (or cuts) what came before.

```yaml
parts:
  - capsule: { from: [0, 0.3, 0], to: [0, 0.75, 0], radius: 0.3 }   # the shape and its parameters
    id: body                   # optional: which bone/node it belongs to (default: root)
    color: red                 # palette colour name
    material: plastic          # a style material preset (default: default)
    blend: 0.04                # smooth join radius with what's before it (0 = crisp seam)
```

### Shapes

Every shape takes `at: [x, y, z]` (its centre; default [0, 0, 0]) and `rotate: [x, y, z]` (degrees, applied x
then y then z, about its centre).

| shape | parameters |
|---|---|
| `sphere` | `radius` |
| `ellipsoid` | `radii: [x, y, z]` |
| `box` | `size: [x, y, z]`, `round` (edge radius; size kept) |
| `cylinder` | `radius`, `height` (along y), `round`, `sides` (8: an octagonal prism, a flat side facing +z) |
| `cone` | `radius` (bottom), `radius_top` (0 = point), `height` (along y), `sides` (4: a pyramid) |
| `capsule` | `from: [x, y, z]`, `to: [x, y, z]`, `radius`, `radius_to` (taper) |
| `tube` | `points: [[x, y, z], ...]` (2+), `radius`, `radius_to`: ropes, branches, rails, tails |
| `torus` | `radius` (ring), `thickness` (tube radius); ring in the xz plane (rotate for others) |
| `lathe` | `profile: [[r, y], ...]` spun around y: vases, bottles, bells, caps, chess pieces, round towers. The profile is a closed outline in the (radius, height) plane: go up the outside and come back down the axis (points with r = 0), e.g. a cap `[[0, 1.06], [0.2, 1.02], [0.3, 0.9], [0.3, 0.8], [0, 0.8]]`. Corners are rounded (`smooth: true`, default); `smooth: false` keeps them sharp |
| `extrude` | `points: [[x, z], ...]` outline seen from above (3+ different points; repeats and a closing point are dropped), `height` (along y), `round`, `holes: [[[x, z], ...], ...]` (outlines cut through: letters O, A, B; `round` rounds their edges too; hard parts: hole edges stay sharp), `offset` (grow the outline by metres, < 0 shrinks: inset face plates). Or `path: "M 0 0 L 1 0 Q 1 1 0 1 Z"` (SVG path data: M L H V C S Q T A Z, absolute and relative; y runs down onto z, so `rotate: [90, 0, 0]` stands it up reading right from the front) with `path_scale` (metres per unit: 0.001 for a 1000-unit font em) and `path_tolerance` (0.002 m): every subpath is an outline, even-odd (counters are holes, separate shapes are islands). Or `text: "OPEN"` in `font: fonts/sign.ttf` (.ttf/.otf, relative to the project folder) with `text_size` (metres per em, 0.1), `text_align` (left, center, right: about x = 0), `letter_spacing` (metres), `line_spacing` (ems, 1.2; `\n` starts a line), `font_axes` (a variable font's instance: `{ wght: 900 }`; default: its default instance): first baseline at z = 0, glyphs toward -z; no kerning or shaping. Glyphs fill like fonts do (nonzero): overlapping contours join instead of cutting holes. Check the font's licence before shipping its shapes. Shields, signs, floor plans, stars, letters |
| `wedge` | `size: [x, y, z]`: a roof (ridge along x at the top) |

`sides` (3-64) also works on `lathe` and `torus`, and on `sphere`, `ellipsoid`, `capsule` and `tube` for hard parts.

For `capsule` and `tube`, the points are in the part's frame (moved by `at`, turned by `rotate`). Everything else in a
model (decal `at`, rig pivots, poses' offsets) is in model space.

### Part options

| option | meaning |
|---|---|
| `id` | bone/node name (lowercase). Parts sharing an id move together. No id = `root`. |
| `color` | palette colour name (required for adding parts) |
| `material` | style preset: default, plastic, paint, fabric, skin, leather, rubber, wood, stone, metal, gold, leaf, glass, glow |
| `blend` | smooth-union radius in metres with everything before it (cuts/intersects: smooth edge) |
| `cut: true` | remove this shape from everything before it (holes, slits, windows, eye sockets) |
| `intersect: true` | keep only what's inside this shape (trim) |
| `mirror: x` | also on the other side of 0 (x, y, z or a list); same id |
| `mirror_id: arm_r` | with `mirror: x`: the copy is a separate part with this id (rig entries are mirrored too) |
| `array: { count: 4, step: [1, 0, 0] }` | repeat in a row |
| `array: { count: 8, around: y, center: [0, 0, 0], angle: 360 }` | repeat in a ring (`around` may be any direction `[x, y, z]`: a ring on a tilted wheel) |
| `shell: 0.02` | hollow, walls this thick (centred on the surface) |
| `shell: { thickness: 0.02, open: -y }` | a wall inside the surface (the outside stays put), one side cut open at the shape's centre: helmets, bowls, pots, shields with a visible rim (`side: both` centres it) |
| `fit: head` or `fit: { to: head, gap: 0.01 }` | with `shell`: the wall wraps the parts with that id, `gap` away from them, wherever this part's own shape reaches (its shape is the coverage: a sphere around the head, `open: -y` and placed low enough to cover the cheeks). Helmets that sit on the head instead of perching on it; cut a face opening after it (before the head, so the cut doesn't take the face) |
| `twist: 90` | degrees per metre about the shape's y axis |
| `noise: { amount: 0.01, scale: 0.2, seed: 3 }` | lumpy surface (rocks, bark, clay): amount in metres, scale = bump size |
| `pattern: {...}` | a second colour painted on the part (below) |
| `decal: {...}` | an image on the part (below) |
| `loose: true` | this part may float free (flames, bees, sparks, rubble): W103 doesn't count it |
| `blend: none` | a hard part, joined crisply (below) |
| `hard: true` / `false` | make this part hard (exact polygons) or smooth, whatever the style says |
| `chamfer: 0.02` | hard parts: one flat band cut along every edge (box, wedge, cylinder, cone, extrude) |
| `bevel: 0.02` | hard parts: rounded edges in `segments: 1-4` flat bands (default 2); where an extrude outline is thinner than about twice the bevel (font serifs, hairlines) it flattens there to fit |
| `keep: true` | this detail survives every reduction (LODs) as its own small mesh, sitting in the surface around it. Crisp (`blend` 0) parts smaller than 2% of the model are kept anyway (rivets, pupils, studs); `keep: false` opts out |
| `aim: [[x, y, z], [x, y, z]]` | points the shape's own y axis from the first point to the second and puts it halfway (instead of `at`); a shape with a `height` that doesn't give one gets the distance. `{ from, to, roll: 30 }` spins it about that line; `rotate` turns it in its own frame first. Arrows, spears, struts, beams at any angle |
| `attr: { heat: 0.9 }` | named numbers a shader reads per vertex (heat, opacity, wind weight); faces of parts without it get 0. Each becomes a custom glTF attribute `_HEAT` (Blender, three.js; Godot 4.7 drops custom attributes), and the first name (alphabetical) also goes in COLOR_0's alpha (Godot: `COLOR.a`; white RGB unless `vertex_colors`). Manifest `attributes` |
| `uv: cylindrical` | texture coordinates projected from the part's shape, in its own frame (they follow `rotate`, mirror, arrays): `cylindrical` (u around, v along the axis over the part's box), `spherical`, `box` (per face, metres / the box's largest side), `along` (tubes and capsules: v = distance along the path, 0..1). `{ project, axis: y, scale: [1, 4] }`. Written to TEXCOORD_0 (Godot UV), or TEXCOORD_1 (UV2) when the atlas or a decal uses the first; manifest `uv: {set, parts}`. Other faces get (0, 0) |

Order matters: details that sit on a surface come **after** it. A part completely inside later parts shows nothing
(W101). A cut removes material from what came before it, and paint follows: a door placed after the cut that made its
archway is painted as the door, not as the wall. Parts thinner than about two mesh cells break up (W102): resolution comes from the style (soft_toy: 8 mm
for a ~1 m model, coarser for bigger models).

### Hard surface

Smooth parts are sampled from the distance field and reduced to the budget: soft clay-toy shapes. **Hard** parts are
made as exact polygons instead: designed facets, crisp creases, octagonal wheels, planks, beams, armour plates, the
hand-built low-poly look (Kenney, KayKit). A part is hard when it asks (`sides`, `chamfer`, `bevel`, `blend: none` or
`hard: true`), or always with a style's `hard_surface = "always"` (low_poly), except the body of a soft-skinned
character (its joints bend by blending) and parts with `twist` or `noise`. Hard parts join each other exactly
(union, cut, intersect, in order); every later cut or intersect, of any shape, applies to them too. They sit in
smooth parts without blending. A box's `round` is a chamfer on a hard part. Round hard shapes get the style's
`hard_sides` (12 by default; low_poly 8) unless they say `sides`. When hard parts would take most of the budget
(LODs), bevels become chamfers, then go, then round shapes lose sides. Flat faces stay flat; in smooth styles bevel
bands shade round and designed edges stay crisp.

```yaml
  - box: { at: [0, 0.3, 0], size: [0.6, 0.6, 0.6] }      # a crate
    color: wood
    chamfer: 0.03
  - cylinder: { at: [0.7, 0.26, 0.9], radius: 0.26, height: 0.1, sides: 8, rotate: [0, 0, 90] }   # a wheel
    color: wood_dark
```

### Hardware

Written like a shape, each stands for several ordinary parts (hard by default); the part's other fields (colour,
material, id, mirror, ...) go to each.

| hardware | meaning |
|---|---|
| `rivets: { count: 8, along: [[x, y, z], ...], size: 0.03 }` | rivets evenly along a path (model space, ends included); or `around: { center, radius, axis: y }` in a ring |
| `band: { fit: body, at: [0, 0.12, 0], width: 0.05, thickness: 0.012, axis: y }` | an iron band round an earlier part's surface at `at` (or `radius:` instead of `fit`): barrels, doors, posts |
| `planks: { size: [1, 2, 0.08], count: 5, gap: 0.015, axis: x, jitter: 0.05, seed: 1 }` | boards side by side along `axis` with gaps, chamfered; `jitter` shortens each by up to that share of its length (with `at`, `rotate`) |
| `bolt: { at: [x, y, z], radius: 0.02, length: 0.02 }` | a hex bolt head along y (rotate it) |
| `slit: { at: [x, y, z], size: [0.3, 0.04, 0.3] }` | a cut: visor and arrow slits |

### Patterns

```yaml
    pattern: { type: stripes, color: gold, size: 0.06, width: 0.3, axis: y }
    # several: a list, painted in order (each over the last); frame: part = axes and `at` in the part's own frame
    # (they follow rotate/aim): pattern: [{ type: stripes, ..., frame: part }, { type: band, ..., frame: part }]
```

- `stripes`: bands across `axis`, one every `size` metres, `width` = fraction in the second colour.
- `band`: one band of thickness `size` centred at `at` (one number: metres along `axis`, in model space): belts, trims,
  hat bands. E.g. `{ type: band, color: brown, size: 0.06, at: 0.4, axis: y }` = a belt 0.4 m above the ground.
- `checker`: checks `size` metres across.
- `dots`: dots on a grid `size` metres apart, diameter `width` x size.

### Decals

```yaml
    decal: { image: decals/logo.png, axis: z, at: [0, 0.6, 0.3], size: [0.2, 0.1] }
```

Projects an image (PNG with transparency, e.g. made with PAGAN) onto the faces of this part that face `axis`
(x, -x, y, -y, z, -z), centred at `at` (model space, on or near the surface), `size` = width, height in metres. It
shows on that side only (a flag needs a second decal with `axis: -z` for its back). Transparent pixels show the part's colour.
Small images (<= 256 px) are sampled crisp (pixel art).

## Rig and skin

```yaml
rig:
  leg_l: { pivot: [0.12, 0.26, 0] }                 # joint position; parent defaults to root
  arm_l: { pivot: [0.3, 0.6, 0], parent: root }
  head:  { pivot: [0, 0.8, 0], meta: { hitzone: head, seat: [0, 1.56, 0] } }
  helmet: { parent: head, meta: { detachable: true }, separate: true }
  arm:   { pivot: [0, 1.6, 0], sockets: { tip: [0, 3.9, -0.2], load: [0, 3.6, -0.5] } }
skin: soft
```

- Every part id is a bone/node. `pivot` is where it turns (hip, shoulder, hinge, axle); default: its box centre.
- A rig entry for `arm_l` also rigs its `mirror_id` twin (pivot mirrored; parent mapped to its twin if any).
- `skin: rigid`: each id is a separate mesh node that moves as one piece. By default all parts are one surface, cut
  where bones meet: fine while joints stay near their bind pose. `union: per_bone` makes each bone's parts their own
  closed surface; neighbouring bones overlap instead (a few hidden triangles), so turning a joint far (a ragdoll, an
  arm along the chest) never opens a hole. Blends between parts of different bones are then lost.
- `skin: soft`: one skinned mesh; weights come from each part's distance, so blended joints bend smoothly.
  `separate: true` makes a part its own closed, rigid mesh (detachable things): it may overlap the body (a helmet
  on a head) without fusing, and removing it leaves no hole. `under: { color: hair }` (with `separate: true`) paints
  the body where the part covers it (hair under a helmet; `material`, `gap`: how far from it still counts, 0.02 m),
  seen once it falls off. Check with `kiln preview <model> --detach`.
- `revealed: [arm_l]`: a part shown only once one of those is gone (a stump cap at the shoulder, under a
  detachable arm). It is its own piece (separate), hidden by KILN's .tscn scenes, `kiln_revealed_by` in its node's
  extras and `revealed_by` in the manifest's part: the game shows it when it removes the arm. Mirrored twins
  are revealed by the twins (`arm_r`). Previews (and `--vs`) leave it out like the game does; `--detach` shows it
  under the part taken off.
- `gib: true` (or `gib: [upperarm_l, lowerarm_l, hand_l]`): the part comes off as a piece of its own. Besides the model,
  `kiln build` writes `models/<name>.gib.<id>.glb`: that part (and, with `true`, every part hanging from it) meshed on
  its own, so it's closed where it met the body; static, at rest, in the model's frame (same origin as the model's glb),
  plain materials. Manifest: `gibs: { <id>: { glb, parts } }`. Mirrored twins get theirs. Pair it with a `revealed`
  stump cap on the body.
- `meta`: plain values or flat lists (points: `[x, y, z]`, model space) for game code: Godot node metadata
  (`get_meta("extras")`; on soft skins, bone metadata: `skeleton.get_bone_meta(i, "extras")`) and the manifest.
  Mirrored twins get the same meta (not mirrored).
- `sockets`: named points on the part (model space, as built): a muzzle, a hand slot, a trebuchet's load. Each is an
  empty child node `<id>_<name>` that moves with the part (Godot: a Node3D under a BoneAttachment3D on soft skins), and
  the manifest gives its position and its offset from the pivot. Mirrored twins get mirrored sockets.

## Template library

`kiln library` lists KILN's own templates: bodies (`body_slim`, `body_stocky`, `body_big`: standard joints, layered
clothes, gloves, boots, a `grip` socket per hand), heads (`head_young`, `head_old`, `head_bearded`, `head_stern`,
`head_goofy`, `head_female`), helmets (`helmet_kettle`, `helmet_nasal`, `helmet_barbute`, `helmet_great`,
`helmet_sallet`, `helmet_crown`: detachable, fitted to whatever head they go on) and armour (`armour_breastplate`,
`armour_pauldrons`, `armour_gauntlets`, `armour_cape`, `armour_hood`: shells fitted to the body). Combine them:

```yaml
name: sergeant
class: character
extends: [body_stocky, head_bearded, helmet_nasal, armour_cape]   # in order; a project template of the same name wins
variants: { blue: { swap: { cloth_red: cloth_blue } } }
animations:
  walk: { import: imports/Rig_Medium_MovementBasic.glb, clip: Walking_A }
```

or `kiln new model sergeant --extends body_stocky,head_bearded,helmet_nasal,armour_cape`. Their colours are the
library palette `people` (found without copying; copy it into palettes/ to change it). `extends` takes a list (bases
combine in order); `cut: <id>` cuts only that id (a helmet's face opening, not the face); `fit: { to: [ids] }` wraps
several parts. Fitted shells are their own meshes.

## Humanoids and clip libraries

`skeleton: humanoid` names a character's parts after the standard joints: `hips`, `spine`, `chest`, `head`,
`upperarm_l`, `lowerarm_l`, `hand_l`, `upperleg_l`, `lowerleg_l`, `foot_l` (and `_r`, usually by `mirror_id`;
optional `toes_l/_r`). Parents come from the standard hierarchy and pivots default to the joints (limbs at the end of
their longest capsule/cylinder/cone/tube nearest the parent, else of their box; hands, feet and toes where the limb
above them ends, on their own box: wrist, ankle; spine, chest, head at their bottom); give `rig:` pivots where that guess is off. Skin defaults to
soft. The manifest maps each joint to its KayKit, Mixamo and Godot SkeletonProfileHumanoid name.

Then any CC0 clip library on the same joints (KayKit Character Animations' `Rig_Medium_*.glb`: Idle_A, Walking_A,
Running_A, Death_A, Hit_A, Throw, Jump_*, ... ~80 clips) plays on the character, retargeted when it's built:

```yaml
animations:
  walk:  { import: imports/Rig_Medium_MovementBasic.glb, clip: Walking_A }
  death: { import: imports/Rig_Medium_General.glb, clip: Death_A, loop: false, fps: 30, speed: 1 }
```

Each bone points where the clip's bone points (the clip's rest pose may be a T-pose; yours can be anything), bone
lengths stay yours, and the hips move by the clip's motion scaled to your hip height. Check with `--pose <name>`.

Clips made for another body type (KayKit's are chibi: splayed arms, deep knee bends on an adult body) can be toned per
animation: `retarget: { keep: { upperarm: 0.35, lowerleg: 0.5 }, offset: { upperarm_l: [0, 0, 12] } }`. `keep` is the
share of each joint's turn away from rest it keeps (0 = held at rest, 1 = as the clip; a base name like `upperarm`
covers both sides; children follow), `offset` a fixed turn in degrees (model axes) added on top.

## Attachments for CC0 characters

A helmet, shield or banner made around a CC0 character (a KayKit Knight) instead of a KILN body:

```yaml
fit_to: { file: imports/Knight.glb, bone: head, meshes: [Knight_Head] }   # meshes: which ones to fit (default all)
parts:
  - sphere: { at: [0, 1.62, 0], radius: 0.8 }        # the coverage: where the helmet reaches
    shell: { thickness: 0.04, open: -y }
    fit: { to: target, gap: 0.015 }                   # wraps the character's own head, 1.5 cm off it
```

The model is made in the character file's space (its units); the glb is exported in the bone's space (root node
`<model>_on_<bone>`), so the game hangs it on that bone (Godot: a BoneAttachment3D); the manifest says `attach: { file,
bone }`. W113 warns when it sinks into the character. `kiln preview <model> --fit` shows it on the character and the
character without it.

## Effects

A burst (an explosion's debris, sparks, puffs of smoke) as other models thrown out over time. KILN doesn't play
effects: `kiln build` writes `models/<name>.effect.json` (manifest `effect`) with every particle already rolled from
the seed, so an engine-side player shows exactly what `kiln preview <model> --effect` shows.
The preview plays it in 8 evenly spaced frames; `--at 0,0.1,0.25,0.5,1` (seconds) gives a contact sheet at those
times instead (tune particle sizes there). Each piece's `fade` is drawn as ordered dithering (a reversed envelope shows
as pieces that appear instead of vanish) and a `floor` as a thin grid.

```yaml
effect:
  seed: 3                    # same seed, same particles
  duration: 1.2              # seconds (default: the last particle's end); loop: false
  emit:
    - model: spark           # another model in the project (its glb; `origin: center` so it spins about its middle)
      count: 12
      at: [0, 0.5, 0]        # spawn point, spread: 0.1 (a ball's radius)
      delay: [0, 0.2]        # seconds, a number or [lo, hi]; life: [0.5, 1.0]
      velocity: { min: [-0.5, 1, -0.5], max: [0.5, 2, 0.5] }   # m/s, or one [x, y, z]
      burst: [1, 2]          # m/s outward, any direction (added to velocity)
      gravity: 9.8           # m/s^2 down, or [x, y, z]; drag: 1.5 (1/s)
      spin: [-90, 90]        # degrees/s about a random axis
      scale: { 0: 0.2, 0.2: 1, 1: 0 }   # over life (0..1), linear between keys; or one number
      heat: { 0: 1, 1: 0 }   # for the game's shader (e.g. into the attr it reads)
      fade: { 0.8: 1, 1: 0 } # opacity for the game (1 = solid); previews dither it
      bounce: 0.3            # with a floor: vertical speed kept at a hit (0 = stops dead); friction: 0.6 (horizontal)
      settle: true           # with a floor: rest once slower than 0.2 m/s on it (no motion, no spin)
  floor: 0                   # optional: a height (effect frame) debris bounces on and settles on, instead of falling through
```

The JSON: `format`, `duration`, `loop`, `seed`, `motion` (the formula), `emitters` (model, `glb`, `godot_scene`,
`origin`, gravity vector, drag, envelopes as `[life fraction, value]` pairs) and `particles` (`emitter`, `delay`,
`life`, `at`, `velocity`, `axis`, `spin`; with a `floor`: `hits`, each `[age, position, velocity]` where the motion
starts again from that position and velocity, `[0, 0, 0]` = resting there without spin). Position at `age = t - delay`
(alive while 0 <= age <= life):
`at + g/k*age + (velocity - g/k)*(1 - exp(-k*age))/k` with drag k > 0, `at + velocity*age + g*age^2/2` with k = 0.
E011 when an emitted model doesn't exist.

## Animations

Names are letters, digits, `_` or `-`, any case (imported clips can keep their library names: `Idle_A`); two names
that differ only in case are an error.

```yaml
animations:
  wave:
    fps: 8
    loop: false                # default true (Godot loops it: glTF name "<name>-loop")
    interpolation: linear      # linear | step
    poses:                     # one per frame; a missing part = its rest pose
      - {}
      - { arm_r: { rotate: [0, 0, -120] } }
      - { arm_r: { rotate: [0, 0, -150] }, root: { offset: [0, 0.02, 0] } }
  walk: { fps: 12, cycle: { type: waddle, legs: [leg_l, leg_r], arms: [arm_l, arm_r] } }
  carry:                       # a cycle plus poses: poses repeat over the cycle's frames, and a part named in a
    fps: 12                    # pose follows the pose instead of the cycle (walking legs + arms holding a crate)
    cycle: { type: walk, legs: [leg_l, leg_r], arms: [] }
    poses: [{ arm_l: { rotate: [-70, 0, 0] }, arm_r: { rotate: [-70, 0, 0] } }]
```

Pose fields per part: `offset: [x, y, z]` (metres), `rotate: [x, y, z]` (degrees, about the pivot), `scale: s` or
`[x, y, z]` (squash and stretch). Signs: positive x tips the part's top towards the front (+Z), so a hanging leg or arm
swings backwards with positive x and forwards with negative x; a drawbridge hinged at its bottom lowers forwards with
positive x. About z: negative raises a right arm (-X side), positive raises a left arm. About y: positive turns
left (counter-clockwise seen from above).

Cycles (8 frames unless `frames:`):

| type | options (defaults) |
|---|---|
| `walk` | `legs` [leg_l, leg_r], `arms` [arm_l, arm_r], `body` root, `swing` 30, `arm_swing` 25, `bounce` 0.02 |
| `waddle` | as walk + `roll` 8 (side-to-side), `swing` 18 |
| `hop` | `part` root, `height` 0.2, `squash` 0.1 |
| `bob` | `part`, `amount` 0.05 |
| `spin` | `part`, `axis` y, `direction` 1 |
| `swing` | `part`, `axis` y, `angle` 20 |
| `breathe` | `part`, `amount` 0.03 |
| `wave` | `arms` (the last one waves), `raise` 150, `angle` 20 |
| `chain` | `parts` [ids in order from the root out; default: every id in file order], `axis` y, `angle` 15, `phase` 0.15: a travelling wave for flags, tails, tentacles, ropes |

## Imported models

```yaml
name: oak
class: nature
source: { file: imports/tree_oak.glb, licence: CC0-1.0, author: Kenney, url: https://kenney.nl }
process: { height: 4.0, recolor: auto, rotate: [0, 90, 0] }   # or scale: 1.0; recolor keep = file's colours
```

Static meshes only. Colours snap to the palette (OKLab nearest), the style's materials and budget apply, the model
stands on y = 0, and the build writes CREDITS.md. Files the model refers to (`Textures/colormap.png` in Kenney kits)
are copied with it by `kiln import`, keeping their folders; a missing one is an error, not a white model.

## Styles

```toml
# styles/sky_pirates.style.toml
description = "Chunky toy airships, warm sunset light"
extends = "soft_toy"           # soft_toy | low_poly | toon | clay | diorama | another project style
notes = """Shapes, proportions, colours, materials, lighting in words (agents follow this)."""

[shape]
smooth = true                  # false = faceted (flat normals)
sharp_angle = 50               # smooth styles: edges sharper than this stay crisp
resolution = 0.008             # metres per mesh cell for a ~1 m model (finer = rounder, slower)

[budgets]                      # triangles per class
character = 8000
default = 4000

[materials]                    # roughness, metallic (0..1), emission (glow strength), rim (soft edge light)
plastic = { roughness = 0.42 }

[look]                         # the Godot look kit and preview lighting
shader = "standard"            # standard | toon
toon_bands = 3
outline = 0.0                  # metres (toon outlines), 0 = none
outline_color = "#1a1420"
tonemapper = "filmic"          # linear | filmic | aces | agx
exposure = 1.0
saturation = 1.15
contrast = 1.0
ssao = true
glow = true
ambient = 0.9
sky_top = "#4f8fe0"
sky_horizon = "#bcd7f2"
ground = "#a9c48f"
sun_pitch = -48.0              # degrees (negative = from above)
sun_yaw = 30.0
sun_energy = 1.1
sun_color = "#fff6e8"
shadows = true
fog = 0.0
fog_color = "#c8d8e8"
rim_light = 0.0                # an added fresnel rim on every surface (Godot: a next pass; previews too): 0.5-1 reads on bright skies
rim_light_color = "#ffffff"
rim_light_power = 3.0          # higher: thinner rim
```

## Lint

Errors: E000 usage/config, E001 file/YAML, E002 unknown field, E003 bad value, E004 unknown colour, E005 unknown
material, E006 style problem, E007 rig problem, E008 animation problem, E009 nothing to mesh, E010 import file
problem, E011 decal image missing, E012 extends problem (no such model, not a template, a loop, unknown remove id),
E013 the built mesh has open edges (cracks), edges with more than two faces or sheets touching at a vertex (a KILN
bug; report it).

Warnings: W101 part has no visible surface, W102 part thinner than the mesh resolution, W103 separate pieces,
W104 colour not in the palette, W106 not standing on y = 0, W107 made under an older style_version, W108 size
unusual for the class, W109 animated part without a pivot, W110 well over the triangle budget (patterns cost
triangles: every stripe border is cut into the mesh; prefer few, large patterns, or model details as parts), W111 a
part lost when reducing to the triangle budget (raise `budget:`), W112 a LOD well above its target (from `kiln build`),
W113 a part pokes through a shell (eyes bigger than a visor slot, a head through a helmet: keep it inside or outside).
W114 (from `kiln build`) joints sit elsewhere than in the model's `animation_library`.
Disable in `kiln.toml` `[lint] disable` or per model `lint: { disable: [...] }`. Lint meshes models in parallel
(`KILN_JOBS` processes, default: every core) and caches them for build and previews.

## Commands

`kiln init [dir] --style soft_toy` · `kiln new model <name> --template bean|prop|empty --class C` ·
`kiln lint [models]` · `kiln preview <model> [--closeup ID|NUMBER] [--pose ANIM] [--vs] [--detach] [--fit] [--effect [--at T,T,...]] [--engine] [--variant V]` ·
`kiln lineup [models]` · `kiln gallery` · `kiln build [models] [--verify-godot]` (named models only: the others keep their last output) · `kiln status` ·
`kiln mark <models> --approved|--draft [--current]` · `kiln style list|show|new|bump` ·
`kiln config show|get|set` · `kiln import <file> --licence L` · `kiln credits` · `kiln doctor` ·
`kiln skill install` · `kiln mcp`. Every command takes `--json` (before or after the command). `--closeup` takes a part
id (`root` = parts without one) or a part's number in the file (`--closeup 3`).
`kiln preview <model> --vs <ref.glb|ref.gltf> [--ref-height METRES]`: the model against a reference mesh (a CC0
pack item, kept as it is: its own colours and normals) at one scale (same pixels per metre, both on y = 0, centred
on each other), in the style's lighting: `previews/<model>/vs_<ref>.png` with paired turntable rows (reference above
the model; from below, eye level, above), the top fifth (head region) close up, and the silhouette difference per
view, and both at gameplay distance (30 m and 60 m at a 60 degree vertical FOV on a 1080 px screen, the style's
outline if it has one, upscaled nearest; an orthographic render at that scale). `--ref-height` scales the reference to that height (default: its own units). Metrics (printed, and in `--json`
under `compare`): `iou` (mean silhouette IoU of 8 views: front, front-left, left, back-left at +10 degrees, front and
left at +50, top, below at -30; 1.0 = same outline), `iou_min`, `iou_views`, `triangle_ratio` (model / reference),
and for `model` and `reference`: `triangles`, `surfaces` (glTF primitives drawn = draw calls; for the model what
`kiln build` writes), `materials`, `colors` (distinct base colours on faces; a textured reference counts each face's
sampled colour), `facet_regularity` (share of surface area in triangles with an edge neighbour facing the same way
within 2 degrees: flat designed facets near 1, smooth or noisily decimated surfaces near 0), `open_edges` (cracks),
`size` (metres). For restyles (where proportions change on purpose):
`band_iou` (mean of `band_ious`: silhouette IoU per body band in 4 side views at 0 degrees, each band cropped, scaled to
one height and centred, so a big head on a short body still matches; `bands` = `humanoid` (`legs`/`torso`/`head` cut at
the hips and head joints: a `skeleton: humanoid` model against a reference with `head` and `hips` nodes) or `thirds`
(`bottom`/`middle`/`top`)), `mass` / `mass_ref` (visual mass: silhouette area / its bounding box, mean of the 8 views)
and `mass_ratio` (model / reference), `screen_px` (height in pixels at 30 m and 60 m, model and reference). All
deterministic. Without a path, `--vs` shows the style's inspiration images.

## Build output

`<output_dir>/models/<name>.glb` (+ `.<variant>.glb`, `.lod<N>.glb`), with "godot": `models/<name>.tscn` (glb +
style materials) and `looks/<style>.tscn` (WorldEnvironment + Sun), `manifest.json`, `CREDITS.md` (imports).
Manifest per model: `glb`, `godot_scene`, `class`, `style`, `status`, `triangles`, `bounds` and `size` (metres),
`skin`, `parts` (parent, pivot, meta, separate, `node_path`: glTF node names from the root, `aabb`: the part's box
in model space, rest pose, for hit zones), `animations` (gltf_name, fps, frames, loop, interpolation, duration),
`variants` (`swap`, `glb` unless variant_glbs = false, `godot_scene`), `lods`, `colors`, `source` (imports), `effect`;
parts also have `sockets`, animations a `start` (the parts their first frame moves, e.g. an arm built level but
cocked when the animation starts). With `vertex_colors = true`, a game loading the .glb itself must set
`vertex_color_use_as_albedo = true` on the imported materials (KILN's .tscn scenes do it); variants are then swap
tables for the game (or `variant_glbs = true`). KILN's .tscn scripts share their materials between instances and
leave any surface override the game set before `add_child` alone.

**Palette atlas** (`atlas = true`; not with `vertex_colors`): every (colour, material preset) pair gets a 4x4-pixel
cell in `models/<name>.palette.png` (colours), `<name>.material.png` (glTF metallicRoughness: G = roughness,
B = metallic), `<name>.glow.png` (emission, only when a preset glows) and, with "godot", `<name>.rim.png` (Godot rim
light: R = rim, G = tint). The glb references them by URI (next to it) and every face's UVs sit on its cell's centre;
samplers are NEAREST without mipmaps. One material for the whole model: 1 surface per mesh (2 where a decal is), soft
or rigid skins alike (rigid parts are nodes sharing the material). A variant is a texture swap:
`<name>.<variant>.palette.png` (+ `.glow.png`), same cells, same mesh; its Godot scene is the base glb with the
variant's textures (variant glbs are still written unless `variant_glbs = false`). Manifest per model: `atlas`
(`palette`, `material`, `glow`, `rim`, `size`, `cell`, `cells`: `color`, `material`, `uv`, `pixel`; `ao`, `ao_strength`), variants
also `palette` (+ `glow`): to recolour at runtime, write other colours into a copy of the palette at the cells'
pixels. `atlas_ao = true` bakes ambient occlusion from the model's distance field (imported models: from the mesh's
dents) into COLOR_0 (a number sets its strength: the darkest corner is x (1 - strength); true = 0.65), a grey multiplier glTF viewers apply; in Godot only KILN's .tscn scenes use it
(`vertex_color_use_as_albedo`). Previews don't show it. When the output is inside a Godot project (with "godot" or
not), KILN writes the palette textures' `.import` settings (lossless, no mipmaps, no VRAM compression on first 3D use: 4x4 cells stay exact); settings Godot adds
later (uid, imported files) are kept.

**Shared clips**: `animations_only: true` makes a model a clip carrier (its animations are what counts; give it the
same rig as the models that use it); `animation_library: <carrier>` on another model plays the carrier's animations
(every part id its clips move must be in the model, E008 otherwise; other ids may differ, e.g. a helmet on one loadout:
they follow their parents, and tracks for carrier parts the model lacks are left out; shared joints more than 1 cm from
the carrier's: W114, since a clip's position tracks put bones where the carrier has them; same skeleton). That model's glb carries no clips; previews and the manifest's `animations` still
list them, plus `animation_library` (`model`, `glb`). Inside a Godot project the carrier's glb is imported as an
AnimationLibrary (no `.tscn`); add it to each model's AnimationPlayer.
`kiln build --verify-godot` checks everything in a throwaway copy of the output (nothing else in the game's project is
imported or touched). Attachments (`fit_to`) are hung on their bone of a copy of the character through a
BoneAttachment3D and must land where they were made.

In Godot:

```gdscript
var pilot: Node3D = load("res://assets/kiln/models/pilot.tscn").instantiate()
add_child(pilot)
pilot.get_node("AnimationPlayer").play("walk")
add_child(load("res://assets/kiln/looks/soft_toy.tscn").instantiate())   # once per scene: the style's light
```
