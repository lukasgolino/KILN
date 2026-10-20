---
name: kiln
description: Make and maintain smooth stylised 3D game models with KILN (Keyed Implicit Language & Notation) - characters, creatures, props, vehicles, siege engines, buildings, trees - written as text (shapes that blend like clay), previewed, rigged, animated and built into glTF/Godot. Also choosing or creating a game's 3D art style from inspirations (soft toy like Dear Passengers/Fall Guys, low poly, toon, clay, diorama). Use whenever a user or an orchestrating agent asks for a 3D model, a 3D asset, a character, a prop, a building, a 3D art style, or mentions kiln / kiln.toml / .kiln.yaml.
---

# KILN: 3D models as text

You can't draw or sculpt, but you can write. KILN turns text into game-ready 3D: every model is a list of simple
shapes (spheres, capsules, rounded boxes, cylinders, cones, tori, tubes, lathes, extrusions, wedges) that join
smoothly where you ask (`blend`), cut each other (`cut`), mirror and repeat. KILN meshes them, paints them from the
palette, rigs and animates them, and writes `.glb` files plus Godot scenes. You check your work by LOOKING at the
previews it renders. The notation is in [reference.md](reference.md); read it before writing a model.

The sibling tool PAGAN (pixel art) makes the 2D a 3D game still needs: UI, icons, signs, logos, shirt prints. KILN
puts PAGAN images on models as decals.

## 1. Start of every session

1. `kiln status` (or MCP `status`): what exists, what needs review. No `kiln.toml`? `kiln init <dir> --style <preset>`
   (inside a Godot project it writes `.gdignore`, so Godot skips the sources; point `output_dir` at a folder Godot sees).
2. Read `BRIEF.md` (what the game needs, decisions) and `STYLE.md` (how it looks). They are the project's memory.
3. `kiln style show`: the style's notes (shape language, proportions) and numbers. Follow them.

New project: ask the owner (one batch, each with your recommended default):
- the game and the camera (how close does it get? that decides how much detail matters);
- the style: a preset (`kiln style list`: soft_toy = Dear Passengers / Fall Guys, low_poly, toon, clay, diorama) or
  inspirations. With inspirations, ask for 3-6 screenshots into `styles/<name>/inspiration/`, look at them, and write a
  style that `extends` the closest preset (section 5);
- the palette (the starter `palettes/main.pal.yaml`, or their colours);
- whether the game is in Godot (then `export = ["glb", "godot"]` and `output_dir` inside the Godot project).
Write the answers into BRIEF.md and STYLE.md.

## 2. Making a model

1. **Plan on paper first, in metres.** Real sizes: a door is 2 m, a soldier 1.7 m (a toy-style bean 1-1.2 m), a
   chair seat 0.45 m high, a barrel 0.9 m. Sketch the parts as a list: shape, centre, size, colour. Models stand on
   y = 0, face +Z (their front), +X is their left.
2. **Scaffold:** `kiln new model <name> --template bean|prop|empty --class character|prop|building|...`.
3. **Write the parts** (reference.md). Big shapes first, details after. Rules of thumb:
   - Join body parts with `blend` (0.02-0.06 m in soft styles); give crisp seams (`blend: 0`, the default) to things
     that sit ON a surface: eyes, buttons, belts, trims.
   - Symmetric things: write the left one (+X) with `mirror: x`; if it must move separately (arms, legs) add
     `mirror_id: arm_r` so the copy is its own part.
   - Holes and openings: a `cut: true` part after the solid. Hollow things: `shell: <thickness>`.
   - Many regular repeats: `array` (in a row or a ring), or a generator script with `kiln.api` (section 6).
   - Every colour is a palette name. Materials are the style's presets (plastic, fabric, skin, leather, wood, stone,
     metal, gold, leaf, glass, rubber, paint, glow).
   - Big plain areas read better with geometry than patterns: planks, trims and shields as parts. Patterns cost
     triangles (W110); keep them for clothes and small props.
   - Things meant to float (flames, bees, sparks, rubble bits): `loose: true` on the part, so W103 stays meaningful.
   - Many similar models (8 soldier types, 5 trees): one `template: true` base and `extends: <base>` models that
     `remove:` and add parts (reference.md, Model families), instead of copies.
4. **Lint:** `kiln lint <name>`. Fix every error; read every warning (W101 a part is hidden, W102 too thin to mesh,
   W103 floating pieces, W106 not standing on the ground, W108 size wrong for the class).
5. **Look:** `kiln preview <name>` writes a turntable (8 sides x below / eye level / above). Open it and check:
   silhouette from every side, proportions, nothing floating, nothing poking through, the face reads, colours
   balanced. Then `--closeup <part>` for anything seen up close (faces, hands, hit zones). Iterate until it's right.
   You will misjudge proportions without looking: always look.
6. **Fit with the rest:** `kiln lineup` (same scale, one ground line, a 1 m bar) and `kiln preview <name> --vs`
   (beside the inspiration images). Does it look like it belongs in the same game?
7. **Report** to the owner with the preview images. When they approve: `kiln mark <name> --approved`, tick it in
   BRIEF.md, and `kiln build`.

## 3. Characters, rigs and animation

- **Characters for the soft styles:** bean/pear body (one capsule, radius 0.25-0.35), stubby limbs (capsules
  0.07-0.1 thick), big eyes (white sphere ~0.1 + black pupil ~0.04 pushed slightly forward), tiny or no mouth.
  Hats, helmets, hair: separate shapes on top, crisp seams. Heads on caricatures: an ellipsoid blended into the
  body with a big nose ellipsoid blended in. Keep hands simple (a sphere or mitten).
- **Rig** what moves: give it an `id`, then `rig: { id: { pivot: [joint], parent: id } }`. Pivots are the joint
  positions (hip, shoulder, hinge, axle). Without a pivot a part turns about its box centre (W109).
- **Skin:** `rigid` (each part moves as one piece: robots, machines, props, toys) or `soft` (one mesh that bends
  where parts blend: creatures, bean characters). `separate: true` keeps a part rigid inside a soft skin
  (detachable helmet).
- **Animations:** explicit `poses` (one per frame, per part: offset/rotate/scale) or a `cycle` that writes the
  poses for you: walk, waddle, hop, bob, spin, swing, breathe, wave, chain (reference.md). Both together: the cycle
  moves everything, and parts named in the poses follow the poses (walking while carrying).
- **Cloth and flags:** split them into 3-4 segments along their length, each its own id parented to the previous one
  (pivots on the seams), crisp seams (`blend: 0`), `skin: soft`, and animate with `cycle: { type: chain, parts: [...] }`. Check every animation with
  `kiln preview <name> --pose <animation>`: the filmstrip shows each frame from the front and the side.
- Gameplay data on parts: `rig: { helmet: { meta: { hitzone: head, detachable: true, socket: [0, 1.6, 0.1] } } }` ->
  node metadata in Godot and in the manifest, which also gives every part's box (`aabb`) for hit zones.
- Detachables (`separate: true`) are meshed on their own, so they may overlap the body and leave no hole when removed.
- Points the game needs on a part (a weapon's muzzle, a hand slot, a catapult's load, a seat): `sockets` in the rig
  entry; they become nodes that move with the part.

## 4. Building for the game

- `kiln build` writes `models/<name>.glb` (+ `<name>.<variant>.glb`, `<name>.lod1.glb`), and with "godot":
  `models/<name>.tscn` (the glb with the style's materials: toon bands, outlines, rim light) and
  `looks/<style>.tscn` (the look kit: sky, sun, tonemapper, SSAO, glow, grading). Tell the owner to instance the
  look kit once in each scene: half of the style is lighting.
- `kiln build --verify-godot` loads everything in headless Godot (in a throwaway copy) and checks parts, animations
  and materials.
- Many team colours: `variant_glbs = false` in kiln.toml keeps one glb per model; each variant becomes a Godot scene
  that recolours it (and a `swap` table in the manifest for other engines).
- Crowds (many instances): `vertex_colors = true` puts colours in the vertices, one surface per material preset,
  so a character costs 2-4 draw calls instead of one per colour.
- Warnings W111 (a part lost to the triangle budget) and W112 (a LOD well over its target) mean: raise the budget.
- `kiln preview <name> --engine` renders through Godot itself (needs a display): use it to confirm the look.
- `manifest.json` lists every model: glb, scene, size and bounds in metres, triangles, parts (pivot, parent, meta),
  animations (Godot names, loop, fps), variants, LODs, licences. That's the contract with game code.

## 5. Styles and inspirations

A style (`styles/<name>.style.toml`, usually `extends = "soft_toy"` or another preset) decides: smooth or faceted
(`[shape]`), mesh resolution, triangle budgets per class, material presets (roughness, metal, glow, rim) and the
look kit (`[look]`: shader standard/toon, outline, tonemapper, exposure, saturation, contrast, SSAO, glow, sky,
sun, fog). The `notes` field holds the shape language and proportions in words: write it, and follow it.

From inspirations: look at the images; describe shapes (rounded? chunky? faceted?), proportions (head size, limb
thickness, eye size), colour (how saturated, how many per object), materials (glossy? matte?) and light (soft?
warm? outlines?). Pick the closest preset, `kiln style new <name> --extends <preset>`, override what differs, write
the notes, make one test model, compare with `kiln preview <model> --vs`, adjust, and get the owner's yes before
making more. Inspiration images are reference only: never copy another game's characters, and never model real
people.

Changing the look later: edit the style (and the palette): every model follows on the next build. If models
themselves must change, `kiln style bump -m "why"`; `kiln status` then flags older models for review.

## 6. Generator scripts (`kiln.api`)

For walls with merlons, fences, stairs, rings of pillars, forests of trees, crowds: write a short Python script
with `kiln.api` (`part`, `crenellated_wall`, `fence`, `stairs`, `tower`, `tree`, `ring`, `offset`, `model`,
`write_model`), run it, and treat the resulting `.kiln.yaml` like any other model (lint, preview). Keep the script
next to the models (`models/<name>.py`) so it can be re-run.

## 7. Imported models (free CC0 packs)

For things text does badly (dense foliage, realistic rocks, detailed props), use free packs: Kenney, KayKit,
Quaternius (CC0), Poly Pizza (CC0/CC-BY). `kiln import <file.glb> --licence CC0-1.0 --author ... --url ...
--height 2.5` copies it into `imports/`, writes a model with `source:`; the build scales it, stands it on the
ground, snaps its colours to the palette and applies the style's materials. `kiln credits` and `CREDITS.md` list
authors. Never use assets whose licence forbids it (NC, ND, SA, Synty, anything "no AI").

## 8. Reporting

Keep reports short: what you made, the preview image paths, sizes/triangles if relevant, open questions with your
recommended default. Log owner decisions in BRIEF.md (`log_feedback` over MCP).
