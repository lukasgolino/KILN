# Making

Making a model: plan in metres, scaffold, parts, lint, look, fit with the rest; the model file.

## Making a model

1. **Plan on paper first, in metres.** Real sizes: a door is 2 m, a soldier 1.7 m (a toy-style bean 1-1.2 m), a
   chair seat 0.45 m high, a barrel 0.9 m. Sketch the parts as a list: shape, centre, size, colour. Models stand on
   y = 0, face +Z (their front), +X is their left.
2. **Scaffold:** `kiln new model <name> --template bean|prop|empty --class character|prop|building|...`.
3. **Write the parts** (`kiln docs parts`; patterns, decals, hardware: `kiln docs surfaces`). Big shapes first, details after. Rules of thumb:
   - Join body parts with `blend` (0.02-0.06 m in soft styles); give crisp seams (`blend: 0`, the default) to things
     that sit ON a surface: eyes, buttons, belts, trims.
   - Symmetric things: write the left one (+X) with `mirror: x`; if it must move separately (arms, legs) add
     `mirror_id: arm_r` so the copy is its own part.
   - Holes and openings: a `cut: true` part after the solid. Hollow things: `shell: <thickness>`.
   - Many regular repeats: `array` (in a row or a ring), or a generator script with `kiln.api` (`kiln docs api`).
   - Before a model gets big, know what is slow (`kiln docs build`, "What things cost"): hundreds of parts, a
     `gradient` or `pattern` on each of many parts, many hard parts (more so with bevels and many sides).
     `kiln preview <name> --draft` while shapes are moving.
   - Every colour is a palette name. Materials are the style's presets (plastic, fabric, skin, leather, wood, stone,
     metal, gold, leaf, glass, clear, rubber, paint, glow). Toy styles' `metal` is part metallic: faces turned down or away
     take a little of the ground's warm colour. For cool cartoon steel pick a blue-grey and `plastic`, or add a preset
     with `metallic` 0.1-0.2 (`kiln docs styles`).
   - See-through (`clear`, or a preset with `alpha` < 1): blended parts share one surface, so a solid clear part
     blended into others shows a hole, not what is behind it. Give it its own surface: a `shell` (a bottle, a dome
     over a dial) or rig it `separate: true` (a window pane). Previews dither it; `atlas = true` draws it opaque (W131).
   - Mechanical props (flat faces, holes, bolts, panels): `hard: true` parts (with `bevel`). Smooth parts blend and
     then get reduced to the budget, so big flats come out dented and holes jagged; hard parts keep flats flat and
     edges straight. Smooth parts are for organic shapes (bodies, cloth, food, rocks).
   - Big plain areas read better with geometry than patterns: planks, trims and shields as parts. Patterns cost
     triangles (W110); keep them for clothes and small props.
   - Things meant to float (flames, bees, sparks, rubble bits): `loose: true` on the part, so W103 stays meaningful.
   - Many similar models (8 soldier types, 5 trees): one `template: true` base and `extends: <base>` models that
     `remove:` and add parts (Model families, below), instead of copies.
4. **Lint:** `kiln lint <name>`. Fix every error; read every warning (W101 a part is hidden, W102 too thin to mesh,
   W103 floating pieces, W106 not standing on the ground, W108 size wrong for the class).
5. **Look:** `kiln preview <name>` writes a turntable (8 sides x below / eye level / above). Open it and check:
   silhouette from every side, proportions, nothing floating, nothing poking through, the face reads, colours
   balanced. Then `--closeup <part>` for anything seen up close (faces, hands, hit zones), and `--detach` when the
   model has detachable (`separate`) parts: each one off, and what's under it. Iterate until it's right.
   You will misjudge proportions without looking: always look.
   For people, start from the template library (`kiln library`; `extends: [body_..., head_..., helmet_..., armour_...]`)
   and add or override parts, instead of building bodies and faces from scratch. To hide the head's hair under a
   helmet (its own piece, shown again when the helmet comes off): `rig: { hair: { parent: head, revealed: [helmet], fold: true } }`.
6. **Fit with the rest:** `kiln lineup` (same scale, one ground line, a 1 m bar) and `kiln preview <name> --vs`
   (beside the inspiration images). Does it look like it belongs in the same game?
7. **Report** to the owner with the preview images. When they approve: `kiln mark <name> --approved`, tick it in
   BRIEF.md, and `kiln build`.


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
resolution: 0.004              # optional: metres per mesh cell for this model, as is (not scaled by size): finer detail
normal_map: 1024               # optional: bake a normal map (256-4096 texels, the texture is exactly that size, square; needs kiln-gen[bake]; not with source:; under atlas = true the model keeps a material per colour): detail from the shapes, not triangles
normal_strength: 1             # optional: scales the map's tilt (0.5 softer grooves, 0 flat), up to 4 (steep slopes cap)
relief: [...]                  # optional: fur as patches in the baked maps, not parts (Relief, below)
shade: { cavity: 0.3, top: 0.12, under: 0.1 }  # optional: shade paint in the vertex colours, over the style's [shade] (kiln docs styles)
max_cells: 640                 # optional: mesh cells across at most (64-1024, style default 256); W120 says when it decides
lod: [2500, 800]               # optional: extra lower-detail .glb files
origin: center                 # optional: the .glb's origin: base (bottom centre of the box) | center (spinning debris) | ground
                               #   ([0, lowest point, 0]: the built mesh lifted onto y = 0, W123) | [x, y, z]
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
  copilot: { swap: { red: green } }   # palette colours; or whole ramps by name, shade for shade: { robes: golds } (colour entries win; a shade in two ramps only when named)
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

## On the surface: `on`

Clumps, straps, scales, spikes and tufts belong on the body's blended surface, which isn't any one part's shape.
`on` puts a part there instead of `at`:

```yaml
  - cone: { radius: 0.03, height: 0.12 }
    color: fur_dark
    on: { part: [body, head], near: [0.25, 0.8, 0.05], offset: -0.02, roll: 0 }
    mirror_id: tuft_r
    mirror: x
```

`near` is walked along the field onto the surface made by the earlier parts with those ids (blends and fitted shells
included; cuts listed before it apply; detail parts don't): start it just outside the spot, since from deep inside
the walk takes the field's way out, not the nearest point. The part's own y axis turns to the surface normal there (`rotate` turns it in its own frame first; `align:
false` keeps its turn and only moves it), `roll` spins it about the normal, `offset` moves it along the normal
(negative sinks it in: a cone's `at` is its middle). A part may sit on one placed this way before it; a `mirror_id`
twin is placed as its mirror image (`mirror: x` folds it as usual). A walk that doesn't settle on the surface is an
error (E003), as are `on` with `array` (the copies wouldn't follow the surface: a part per spot) and on hardware
parts (give them `at`). Hardware after a placed part sees it placed.

## Clothing: `garment`

A shirt, a robe or a jumper over a soft body, as its own layer (a hem, an open neck, a placket) rather than paint:

```yaml
  - garment: { fit: [chest, spine, upperarm_l, upperarm_r], from_y: 0.9, to_y: 1.42, gap: 0.008, thickness: 0.02, hem: 0.015,
               openings: [{ at: [0, 1.3, 0.2], size: [0.05, 0.2, 0.1] }] }
    id: shirt
    color: shirt_blue
```

It wraps the earlier parts with those ids: a shell `thickness` thick, `gap` off their surface, between `from_y` (the
hem) and `to_y` (default: their own extent); it is open where it ends horizontally (the hem, the neck, and the cuffs of
arms hanging down). A sleeve or a trouser leg takes `length: 0.6` instead (the share of its limb, a capsule or tube,
from the end nearest the body): it runs along the limb and ends square and open there, T-posed or not. List every part under it: an unlisted part pokes through.
`hem` adds a band twice that tall at the bottom, a little thicker. An earlier garment can be wrapped too (a shirt over
trousers: `fit: [chest, trousers]`). `openings` are boxes cut through the garment alone, so it needs an `id` of its
own; a mirrored garment (`mirror`, `mirror_id`) gets them mirrored. An opening with `shape: v` is a V, `size: [w, h,
d]` with w its width at the top (a V neck).

```yaml
  - garment: { fit: [chest], from_y: 1.0, to_y: 1.5, collar: { style: open, height: 0.035, depth: 0.16, lapel: 0.045 },
               placket: { width: 0.03, buttons: 4, button_color: black, to_y: 1.3 } }
    id: shirt
  - garment: { fit: [upperarm_l], length: 0.5, hem: 0 }   # a short sleeve
    id: upperarm_l
    mirror: x
    mirror_id: upperarm_r
```

`collar` is a band round the neck at the garment's top (`fit`: the part(s) it rounds, default `neck`, else `head`;
`height`); `style: open` cuts a V `depth` deep at the front and lays a lapel `lapel` wide along each side of it.
`placket` is a raised strip `width` wide down the front (`from_y`, `to_y`: default the garment's) with `buttons`
(`button_color`). They are fitted shells too, so they lie on the body's shape.

On a rigged, soft-skinned character a garment moves with the bone of its `id`: sleeves as their own garments with the
arm's id (`fit: [upperarm_l]`, `id: upperarm_l`, mirrored) move with the arms (and wholly with `skin_falloff: 0`);
the body garment with `id: chest`. Openings need a garment id that isn't a wrapped part's. Walls under two mesh cells
break up (lint W102): keep `thickness` at least twice the mesh step.

Cloth folds, relief fur and soft colour borders: `kiln docs surfaces`.
