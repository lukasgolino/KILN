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
   balanced. Then `--closeup <part>` for anything seen up close (faces, hands, hit zones), and `--detach` when the
   model has detachable (`separate`) parts: each one off, and what's under it. Iterate until it's right.
   You will misjudge proportions without looking: always look.
   For people, start from the template library (`kiln library`; `extends: [body_..., head_..., helmet_..., armour_...]`)
   and add or override parts, instead of building bodies and faces from scratch. A helmet hides the head's hair
   (its own `hair` piece, shown again when the helmet comes off).
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
  (detachable helmet). Rigid joints that turn far (ragdolls): `union: per_bone`, so no turn opens the mesh.
- **Animations:** explicit `poses` (one per frame, per part: offset/rotate/scale) or a `cycle` that writes the
  poses for you: walk, waddle, hop, bob, spin, swing, breathe, wave, chain (reference.md). Both together: the cycle
  moves everything, and parts named in the poses follow the poses (walking while carrying).
- **CC0 clip libraries:** a `skeleton: humanoid` character plays imported clips
  (`walk: { import: imports/clips.glb, clip: Walking_A }`); any other skeleton (quadrupeds, birds) plays them through
  `skeleton: { map: { <part id>: <clip joint>, ... }, root_motion: <clip joint> }` (reference.md, "Clips on any skeleton").
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
  and materials (and that attachments fitted to a CC0 character land on its bone).
- Many team colours: `variant_glbs = false` in kiln.toml keeps one glb per model; each variant becomes a Godot scene
  that recolours it (and a `swap` table in the manifest for other engines).
- Crowds (many instances): `vertex_colors = true` puts colours in the vertices, one surface per material preset,
  so a character costs 2-4 draw calls instead of one per colour.
- Crowds, best: `atlas = true` gives every model one material (colours and presets in a small palette texture): 1 draw
  call per mesh (2 with a decal), and team colours become a texture swap on one shared mesh. `atlas_ao = true` adds
  baked ambient occlusion (a number 0..1 sets its strength). Use it instead of `vertex_colors`.
- Warnings W111 (a part lost to the triangle budget) and W112 (a LOD well over its target) mean: raise the budget.
- Ground for a level: a model with `terrain:` instead of `parts:` (hills, ridges, plateaus, noise and paths combined in
  order; up to 4 splat layers of palette colours by slope, height, nearness to paths and noise; see reference.md,
  Terrains). It builds chunked LOD glbs, a splat map and a Godot scene with a HeightMapShape3D; `kiln preview <name>`
  shows it from above and four sides. Place things on it from Python with `kiln.terrain.load(project, name)`
  (`height`, `normal`, `slope`, `splat` at any x, z).
- `kiln preview <name> --engine` renders through Godot itself (needs a display): use it to confirm the look.
- `manifest.json` lists every model: glb, scene, size and bounds in metres, triangles, parts (pivot, parent, meta),
  animations (Godot names, loop, fps), variants, LODs, licences. That's the contract with game code.
- Not Godot: `export = ["glb"]`; the per-engine notes (Unity, Unreal, Bevy, three.js, Defold) are in KILN's
  `docs/engines.md` (https://github.com/lukasgolino/KILN/blob/main/docs/engines.md). Outside Godot `atlas = true` is
  usually the best colour mode; look kits, toon, outlines and rim light are Godot-only.

## 5. Styles and inspirations

A style (`styles/<name>.style.toml`, usually `extends = "soft_toy"` or another preset) decides: smooth or faceted
(`[shape]`), mesh resolution, triangle budgets per class, material presets (roughness, metal, glow, rim) and the
look kit (`[look]`: shader standard/toon (bands, softness, shadow colour, specular, banded shadows), outline
(metres or pixels, one colour or each part's darkened), tonemapper, exposure, saturation, contrast, SSAO, glow, sky,
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
authors. Never use assets whose licence forbids it (NC, ND, SA, Synty, anything "no AI"). An .fbx/.blend/.obj
imports the same way when Blender 4.x is installed (`BLENDER=/path/to/blender`): `kiln import` turns it into
`imports/<name>.glb` once, so prefer that over naming the .fbx in `source:` (every build would need Blender).

Shipped CC0 packs: `kiln pack list`; the owner mirrors one with `kiln pack add <pack>` (it downloads; ask first).
`kiln pack search knight --json` (MCP `pack_search`, `lineup: true` for a sheet of the hits) finds models by name and
tags with triangles and size; `kiln pack import <pack> <name> --height 1.8` (MCP `pack_import`) copies it into
`imports/<pack>/` and records it in `kiln.lock`, which the build checks (E014: a changed file, a non-CC0 licence).

**Match a reference** (make a KILN model that holds its own next to a CC0 asset, e.g. a KayKit barrel):
1. Put the reference in `imports/` and ask the owner for thresholds, with defaults: silhouette `iou` >= 0.9 (and
   `iou_min` >= 0.85), `triangle_ratio` <= 1.5, `surfaces` <= the reference's + 1, `colors` within +-2,
   `open_edges` 0, and for a faceted (low poly) target `facet_regularity` >= 0.7 (use a hard-surface style or parts).
2. `kiln preview <model> --vs imports/<ref>.glb --ref-height <the model's intended height> --json` (MCP: `preview`
   with `which: "vs"`, `reference`, `ref_height`). Read `compare` and LOOK at the sheet: the silhouette row shows red
   where the model sticks out and blue where it is missing, per view.
3. Change the model (proportions, part sizes, budget, `sides`, colours), lint, and repeat step 2 until every metric is
   inside the thresholds. Fix the worst view first (`iou_views`). Don't copy the reference's details one for one:
   match its size, outline, density and colour count; the design stays ours.
4. Report both renders (the vs sheet) and the final metrics against the thresholds; say which ones you couldn't meet
   and why.

## 8. Reporting

Keep reports short: what you made, the preview image paths, sizes/triangles if relevant, open questions with your
recommended default. Log owner decisions in BRIEF.md (`log_feedback` over MCP).

## 9. Help us improve KILN: report what got in your way

KILN is young, and it gets better mostly through reports from agents like you using it on real games. When
something gets in your way, please tell us in a GitHub issue at https://github.com/lukasgolino/KILN/issues. It
is the most useful thing you can do for the project. Whether you do is entirely up to you and your user.

Worth reporting: a crash or traceback; a wrong or misleading message or lint rule; output that looks or behaves
wrong; a workaround you had to invent; a feature you needed and didn't have; this skill or the reference
misleading you.

1. Note it as you go; don't interrupt the task for it.
2. At a natural break (the end of the task, your report), draft the issue: a one-line title; `kiln --version`;
   what you did (commands, a minimal source snippet); what you expected and what you got; the workaround, if
   any. End the body with "Reported by an agent using KILN." Keep it to a minimal repro: no game names, private
   asset content, paths or anything else from the user's project unless they OK it.
3. Look for an existing issue first: `gh issue list --repo lukasgolino/KILN --search "<keywords>"`; if one
   fits, offer a comment on it instead.
4. Show the user the draft and ask whether to file it. Issues are public and posted under their GitHub account,
   so **never file without their OK**. If they agree:
   `gh issue create --repo lukasgolino/KILN --title "..." --body-file <draft>`, or give them the link
   https://github.com/lukasgolino/KILN/issues/new?template=agent-report.md to file it themselves. If they
   decline, drop it.
