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
vertex_colors = false          # true: colours in the vertices, one surface per material preset (fewer draw calls)
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
parts: [...]                   # the shapes (below)
rig: {...}                     # optional: bones (below)
skin: soft                     # none (static) | rigid | soft; default rigid when there is a rig
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
| `cylinder` | `radius`, `height` (along y), `round` |
| `cone` | `radius` (bottom), `radius_top` (0 = point), `height` (along y) |
| `capsule` | `from: [x, y, z]`, `to: [x, y, z]`, `radius`, `radius_to` (taper) |
| `tube` | `points: [[x, y, z], ...]` (2+), `radius`, `radius_to`: ropes, branches, rails, tails |
| `torus` | `radius` (ring), `thickness` (tube radius); ring in the xz plane (rotate for others) |
| `lathe` | `profile: [[r, y], ...]` spun around y: vases, bottles, bells, caps, chess pieces, round towers. The profile is a closed outline in the (radius, height) plane: go up the outside and come back down the axis (points with r = 0), e.g. a cap `[[0, 1.06], [0.2, 1.02], [0.3, 0.9], [0.3, 0.8], [0, 0.8]]`. Corners are rounded (`smooth: true`, default); `smooth: false` keeps them sharp |
| `extrude` | `points: [[x, z], ...]` outline seen from above (3+ different points; repeats and a closing point are dropped), `height` (along y), `round`: shields, signs, floor plans, stars |
| `wedge` | `size: [x, y, z]`: a roof (ridge along x at the top) |

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
| `array: { count: 8, around: y, center: [0, 0, 0], angle: 360 }` | repeat in a ring |
| `shell: 0.02` | hollow, walls this thick |
| `twist: 90` | degrees per metre about the shape's y axis |
| `noise: { amount: 0.01, scale: 0.2, seed: 3 }` | lumpy surface (rocks, bark, clay): amount in metres, scale = bump size |
| `pattern: {...}` | a second colour painted on the part (below) |
| `decal: {...}` | an image on the part (below) |
| `loose: true` | this part may float free (flames, bees, sparks, rubble): W103 doesn't count it |

Order matters: details that sit on a surface come **after** it. A part completely inside later parts shows nothing
(W101). A cut removes material from what came before it, and paint follows: a door placed after the cut that made its
archway is painted as the door, not as the wall. Parts thinner than about two mesh cells break up (W102): resolution comes from the style (soft_toy: 8 mm
for a ~1 m model, coarser for bigger models).

### Patterns

```yaml
    pattern: { type: stripes, color: gold, size: 0.06, width: 0.3, axis: y }
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
- `skin: rigid`: each id is a separate mesh node that moves as one piece.
- `skin: soft`: one skinned mesh; weights come from each part's distance, so blended joints bend smoothly.
  `separate: true` makes a part its own closed, rigid mesh (detachable things): it may overlap the body (a helmet
  on a head) without fusing, and removing it leaves no hole.
- `meta`: plain values or flat lists (points: `[x, y, z]`, model space) for game code: Godot node metadata
  (`get_meta("extras")`; on soft skins, bone metadata: `skeleton.get_bone_meta(i, "extras")`) and the manifest.
  Mirrored twins get the same meta (not mirrored).
- `sockets`: named points on the part (model space, as built): a muzzle, a hand slot, a trebuchet's load. Each is an
  empty child node `<id>_<name>` that moves with the part (Godot: a Node3D under a BoneAttachment3D on soft skins), and
  the manifest gives its position and its offset from the pivot. Mirrored twins get mirrored sockets.

## Animations

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
```

## Lint

Errors: E000 usage/config, E001 file/YAML, E002 unknown field, E003 bad value, E004 unknown colour, E005 unknown
material, E006 style problem, E007 rig problem, E008 animation problem, E009 nothing to mesh, E010 import file
problem, E011 decal image missing, E012 extends problem (no such model, not a template, a loop, unknown remove id).

Warnings: W101 part has no visible surface, W102 part thinner than the mesh resolution, W103 separate pieces,
W104 colour not in the palette, W106 not standing on y = 0, W107 made under an older style_version, W108 size
unusual for the class, W109 animated part without a pivot, W110 well over the triangle budget (patterns cost
triangles: every stripe border is cut into the mesh; prefer few, large patterns, or model details as parts), W111 a
part lost when reducing to the triangle budget (raise `budget:`), W112 a LOD well above its target (from `kiln build`).
Disable in `kiln.toml` `[lint] disable` or per model `lint: { disable: [...] }`. Lint meshes models in parallel
(`KILN_JOBS` processes, default: every core) and caches them for build and previews.

## Commands

`kiln init [dir] --style soft_toy` · `kiln new model <name> --template bean|prop|empty --class C` ·
`kiln lint [models]` · `kiln preview <model> [--closeup ID|NUMBER] [--pose ANIM] [--vs] [--engine] [--variant V]` ·
`kiln lineup [models]` · `kiln gallery` · `kiln build [--verify-godot]` · `kiln status` ·
`kiln mark <models> --approved|--draft [--current]` · `kiln style list|show|new|bump` ·
`kiln config show|get|set` · `kiln import <file> --licence L` · `kiln credits` · `kiln doctor` ·
`kiln skill install` · `kiln mcp`. Every command takes `--json` (before or after the command). `--closeup` takes a part
id (`root` = parts without one) or a part's number in the file (`--closeup 3`).

## Build output

`<output_dir>/models/<name>.glb` (+ `.<variant>.glb`, `.lod<N>.glb`), with "godot": `models/<name>.tscn` (glb +
style materials) and `looks/<style>.tscn` (WorldEnvironment + Sun), `manifest.json`, `CREDITS.md` (imports).
Manifest per model: `glb`, `godot_scene`, `class`, `style`, `status`, `triangles`, `bounds` and `size` (metres),
`skin`, `parts` (parent, pivot, meta, separate, `node_path`: glTF node names from the root, `aabb`: the part's box
in model space, rest pose, for hit zones), `animations` (gltf_name, fps, frames, loop, interpolation, duration),
`variants` (`swap`, `glb` unless variant_glbs = false, `godot_scene`), `lods`, `colors`, `source` (imports);
parts also have `sockets`, animations a `start` (the parts their first frame moves, e.g. an arm built level but
cocked when the animation starts). With `vertex_colors = true`, a game loading the .glb itself must set
`vertex_color_use_as_albedo = true` on the imported materials (KILN's .tscn scenes do it); variants are then swap
tables for the game (or `variant_glbs = true`). KILN's .tscn scripts share their materials between instances and
leave any surface override the game set before `add_child` alone.
`kiln build --verify-godot` checks everything in a throwaway copy of the output (nothing else in the game's project is
imported or touched).

In Godot:

```gdscript
var pilot: Node3D = load("res://assets/kiln/models/pilot.tscn").instantiate()
add_child(pilot)
pilot.get_node("AnimationPlayer").play("walk")
add_child(load("res://assets/kiln/looks/soft_toy.tscn").instantiate())   # once per scene: the style's light
```
