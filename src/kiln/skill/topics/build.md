# Build

Building for the game: glb, Godot scenes, look kits, colour modes, the manifest, reporting.

## Building for the game

- `kiln build` writes `models/<name>.glb` (+ `<name>.<variant>.glb`, `<name>.lod1.glb`), and with "godot":
  `models/<name>.tscn` (the glb with the style's materials: toon bands, outlines, rim light) and
  `looks/<style>.tscn` (the look kit: sky, sun, tonemapper, SSAO, glow, grading). Tell the owner to instance the
  look kit once in each scene: half of the style is lighting.
- `kiln build --verify-godot` loads everything in headless Godot (in a throwaway copy) and checks parts, animations
  and materials (and that attachments fitted to a CC0 character land on its bone).
- Many team colours: `variant_glbs = false` in kiln.toml keeps one glb per model; each variant becomes a Godot scene
  that recolours it (and a `swap` table in the manifest for other engines; with `shade:` and `vertex_colors`, the
  vertex colours are shaded, so match them within a tolerance).
- Crowds (many instances): `vertex_colors = true` puts colours in the vertices, one surface per material preset,
  so a character costs 2-4 draw calls instead of one per colour.
- Crowds, best: `atlas = true` gives every model without a `normal_map` one material (colours and presets in a small palette texture): 1 draw
  call per mesh (+1 per decal or texture), and team colours become a texture swap on one shared mesh. `atlas_ao = true` adds
  baked ambient occlusion (a number 0..1 sets its strength). Use it instead of `vertex_colors`.
- Warnings W111 (a part lost to the triangle budget) and W112 (a LOD well over its target) mean: raise the budget.
- Ground for a level: a model with `terrain:` instead of `parts:` (hills, ridges, plateaus, noise and paths combined in
  order; up to 4 splat layers of palette colours by slope, height, nearness to paths and noise; see `kiln docs terrains`).
  It builds chunked LOD glbs, a splat map and a Godot scene with a HeightMapShape3D; `kiln preview <name>`
  shows it from above and four sides. Place things on it from Python with `kiln.terrain.load(project, name)`
  (`height`, `normal`, `slope`, `splat` at any x, z).
- Foliage and props over ground: a model with `scatter:` (`kiln docs scatters`) places other models (grass,
  flowers, rocks, trees; one mesh each, small budgets) over a terrain, another model's top or a flat area by density,
  spacing and rules (slope, height, noise patches, splat layers, paths), with random turn, scale, lean and tint. It
  builds `<name>.scatter.json` and a Godot scene of MultiMeshes (with LODs and a fade-out distance); `kiln preview
  <name>` shows it. Lint W118/W119: too many / no instances.
- `kiln preview <name> --engine` renders through Godot itself, offscreen (Linux: a private Xvfb with CPU drivers; never a window on the desktop; `KILN_OFFSCREEN` overrides): use it to confirm the look. It is framed like the software views on the same tile colour; with `--engine`, `--views`, `--pitch` and `--size` pick its views (default: four sides at 15 and 50 degrees).
- `manifest.json` lists every model: glb, scene, size and bounds in metres, triangles, parts (pivot, parent, meta),
  animations (Godot names, loop, fps), variants, LODs, licences. That's the contract with game code.
- Not Godot: `export = ["glb"]`; the per-engine notes (Unity, Unreal, Bevy, three.js, Defold) are in KILN's
  `docs/engines.md` (https://github.com/lukasgolino/kiln/blob/main/docs/engines.md). Outside Godot `atlas = true` is
  usually the best colour mode; look kits, toon, outlines and rim light are Godot-only.


## Build output

`<output_dir>/models/<name>.glb` (+ `.<variant>.glb`, `.lod<N>.glb`), with "godot": `models/<name>.tscn` (glb +
style materials) and `looks/<style>.tscn` (WorldEnvironment + Sun), `manifest.json`, `CREDITS.md` (imports).
Manifest per model: `glb`, `godot_scene`, `class`, `style`, `status`, `triangles`, `bounds` and `size` (metres),
`skin`, `parts` (parent, pivot, meta, separate, `node_path`: glTF node names from the root, `aabb`: the part's box
in model space, rest pose, for hit zones), `animations` (gltf_name, fps, frames, loop, interpolation, duration),
`variants` (`swap`, `glb` unless variant_glbs = false, `godot_scene`), `lods`, `colors`, `source` (imports), `effect`,
`humanoid` (each joint's KayKit, Mixamo, Godot name), `godot_bonemap` (with godot_bonemap = true: the BoneMap file);
parts also have `sockets`, animations a `start` (the parts their first frame moves, e.g. an arm built level but
cocked when the animation starts). With `vertex_colors = true`, a game loading the .glb itself must set
`vertex_color_use_as_albedo = true` on the imported materials (KILN's .tscn scenes do it), and on Godot's
Compatibility renderer, which decodes vertex colours from sRGB once more (darker, more saturated;
`vertex_color_is_srgb` changes nothing there), re-encode each mesh's colours once (`_encode_colours` in a KILN .tscn
does it, as do scatter scenes for LOD glbs; it also covers `atlas_ao`'s occlusion; LOD glbs a game loads itself need
it too); variants are then swap
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
(`vertex_color_use_as_albedo`). Previews (`kiln preview`, `kiln gallery`, scatters) show it too. When the output is inside a Godot project (with "godot" or
not), KILN writes the palette textures' `.import` settings (lossless, no mipmaps, no VRAM compression on first 3D use: 4x4 cells stay exact); settings Godot adds
later (uid, imported files) are kept. A model with `normal_map:` stays out of the atlas (both need the first UV set): a material per colour,
its normal map, and `atlas_ao`'s occlusion in COLOR_0 all the same (manifest: `ao`, `ao_strength` on the model, no `atlas`).

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

Other engines: everything but the `.tscn` files, `.import` sidecars and `<name>.rim.png` is plain glTF + JSON. Notes per
engine (axes, scale, vertex colours, palette texture filtering, skins, clips, LODs, approximating the look):
https://github.com/lukasgolino/kiln/blob/main/docs/engines.md

In Godot:

```gdscript
var pilot: Node3D = load("res://assets/kiln/models/pilot.tscn").instantiate()
add_child(pilot)
pilot.get_node("AnimationPlayer").play("walk")
add_child(load("res://assets/kiln/looks/soft_toy.tscn").instantiate())   # once per scene: the style's light
```


## Long builds

Builds say nothing for their first 10 s, then a line per phase (joining hard parts, meshing, painting, reducing,
skinning) at least every 10 s, with done/total and roughly how long is left:
`kiln: bigfoot: reducing: passes done 2/5, about 9 min left (662 s)`. A step projected past 2 minutes says
`a long build` at once with what would make it faster:

- joining hard parts: fewer hard parts, or fewer `sides` on round ones (the cell size makes no difference to this phase);
- meshing: a coarser `resolution` or fewer parts;
- painting: fewer gradient or pattern parts;
- reducing: a coarser resolution;
- skinning: `skin: rigid` or fewer parts.

A model with 100 or more parts prints every phase line at once.

`kiln preview <model> --draft` (with the turntable, `--views`, `--closeup`, `--pose`, `--detach`) is for iterating on
a slow model: mesh cells 3 times coarser, each face in its nearest part's colour (ragged colour edges, no patterns
on smooth parts, no `under:` paint beneath detachables), hard parts without bevels, one reducing pass, no normal map
or baked occlusion. A 536-part character that builds in 5 minutes drafts in 14 s; a 23-part one in 5 s. Sheets go to
`previews/<model>/draft/`, each stamped DRAFT; the draft has its own cache and never changes what `kiln build` or
the real previews use. Judge proportions, silhouette and placement on it. Don't judge the surface, the colour edges
(least of all next to cuts), the triangle count (a draft isn't reduced to the budget) or anything lint says: those
are the real preview's. Not for terrains, scatters or imported models, nor with `--engine`, `--vs`, `--fit`, `--effect`.

## What things cost

Build time, measured with KILN 0.22 on one 6-core machine with `kiln-gen[fast]`: read the ranking and the rough
size, not the seconds (without the `fast` extra everything meshed is 2-3 times slower). A 23-part soft-skinned
character at 6 mm cells builds in 16 s; the same model with one thing changed:

| Change | Build | Why |
|---|---|---|
| cells 12 mm instead of 6 | 8 s | fewer field samples and raw triangles; the budget decides the final count either way |
| cells 3 mm (with `max_cells` raised so they aren't capped) | 31 s | halving the cells about doubles the build, and takes more memory |
| 3 mm asked, `max_cells` left at 400 | 20 s | the cap gave 4.5 mm cells: lint W120 says when that happens |
| `budget` doubled (30k -> 60k triangles) | 22 s | more left to place and paint |
| `normal_map: 1024` | 35 s | the bake is a second pass over the surface |
| `noise` on every part | 17 s | one more term per sample: nearly free |
| `skin: rigid` instead of `soft` | 16 s | skinning is small at this size |

What grows with the model:

- **Parts**: about in step with their number. 23 parts 16 s, 94 parts 46 s, 536 parts (about 480 of them fur
  locks) 290 s.
  `blend_to` costs no more than `blend`. If a look needs hundreds of small parts, ask whether it is surface detail
  instead (`detail: true` parts in a `normal_map`, a `pattern`, a `texture`).
- **`gradient` and `pattern` parts**: each is painted on its own: about 0.6 s each on a big model (a gradient on
  every lock of that 536-part character added about 300 s). On a few parts, nothing to worry about.
- **Hard parts** (`hard`, `bevel`, `sides`): joined one by one as exact polygons, whatever the cell size, and the
  time follows their polygons more than their number: 82 mostly plain ones took 45 s of a 54 s build; 13 with many
  sides and bevels, 18 s. Bevels and more `sides` multiply the polygons, and a model over its budget joins them
  again with less detail. A model of hard parts only doesn't get faster with a coarser `resolution`.
- **Size**: a style's resolution gets coarser for models over 1 m (`scale_with_size`) and `max_cells` caps the grid,
  so a big scene costs like a small model unless you force fine cells on it.

What stays cheap after the first build: an edit of animations, variants, description or comments, or of the
style's `[look]` and `[materials]`, reuses the built meshes (seconds). While shapes are still moving,
`kiln preview <model> --draft` shows a slow model in seconds (above). `kiln lint --fast` checks the text without
building.

## Reporting

Keep reports short: what you made, the preview image paths, sizes/triangles if relevant, open questions with your
recommended default. Log owner decisions in BRIEF.md (`log_feedback` over MCP).
