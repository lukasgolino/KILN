---
name: kiln
description: Make and maintain smooth stylised 3D game models with KILN - characters, creatures, props, buildings, terrains, scatters - written as text (shapes that blend like clay), previewed, rigged, animated and built into glTF/Godot; also choosing a 3D art style from inspirations. Use whenever a user or an orchestrating agent asks for a 3D model, a 3D asset, a 3D art style, or mentions kiln / kiln.toml / .kiln.yaml.
---

# KILN: 3D models as text

KILN turns text into game-ready 3D: a model is a list of simple shapes (spheres, capsules, rounded boxes,
cylinders, cones, tori, tubes, lathes, extrusions, wedges) that join smoothly where you ask (`blend`), cut each
other (`cut`), mirror and repeat. KILN meshes, paints, rigs and animates them and writes `.glb` plus Godot scenes.
You check your work by LOOKING at the previews. This page is the core. Everything else is a topic:
**`kiln docs <topic>`** prints one, `kiln docs --search <words>` finds the paragraphs you need.

| Topic | When |
|---|---|
| `setup` | a new project, what to ask the owner, `kiln.toml` and the layout |
| `making` | the full model loop and the model file |
| `parts` | every shape and part field (read before writing parts) |
| `rigs`, `animations`, `humanoids`, `templates` | characters: rigs, skins, cycles, CC0 clips, the template library |
| `styles` | presets, inspirations, the look kit |
| `build` | glb, Godot scenes, look kits, colour modes, the manifest, what to report |
| `terrains`, `scatters`, `effects` | ground, foliage over it, particle effects |
| `imported`, `api` | CC0 packs and matching a reference; generator scripts (`kiln.api`) |
| `commands`, `lint` | every command and flag, every lint rule |
| `report` | filing what got in your way |

Units are **metres**, **+Y is up**, a model **faces +Z** (its front), **+X is its left**, and it **stands on
y = 0**. Angles are degrees. Colours are palette names.

## Every task

1. `kiln status` (MCP `status`): what exists, what needs review. No `kiln.toml`: `kiln docs setup`.
2. Read `BRIEF.md` (what the game needs, decisions) and `STYLE.md` (how it looks); `kiln style show` for the style's
   notes and numbers. Follow them. Ask the owner only what they don't answer, in one batch with defaults.
3. **Plan in metres** (a door 2 m, a soldier 1.7 m, a toy-style bean 1-1.2 m, a barrel 0.9 m): a list of parts,
   each a shape, centre, size and colour. Big shapes first, details after.
4. `kiln new model <name> --template bean|prop|empty --class character|prop|building|...`, then write the parts
   (`parts`). People: start from the template library (`kiln library`, `extends: [body_..., head_...]`).
   Many similar models: one `template: true` base and `extends:`. Regular repeats: `array` or `kiln.api`.
5. `kiln lint <name>`: fix every error, read every warning (W101 hidden part, W102 too thin, W103 floating,
   W106 not on the ground, W108 size wrong for the class).
6. **Look:** `kiln preview <name>` (turntable: 8 sides x below / eye level / above), `--closeup <part>` for faces
   and hit zones, `--pose <animation>` for animations, `kiln lineup` against the rest of the set. You will
   misjudge proportions without looking. Iterate until it's right.
7. Report to the owner with the preview paths (and triangles if relevant). On approval: `kiln mark <name>
   --approved`, tick it in BRIEF.md, `kiln build` (`build` for what to tell the game side).

**MCP:** with KILN tools (`status`, `write_model`, `preview`, `docs`...), use them instead of the CLI; same
workflow. **Orchestrators:** short reports: what you made, preview paths, open questions with defaults.

## Spend few tokens

- `kiln docs <topic>` instead of reading KILN's source or a whole reference. A question the topics don't answer
  is worth a report (`report`).
- Prefer `--json` and read only the fields you need; look at a preview once per change.
- One command that answers the question beats several probes: `kiln status`, `kiln style show`, `kiln library`.

## Rules of thumb

- Join body parts with `blend` (0.02-0.06 m in soft styles); crisp seams (`blend: 0`) for things ON a surface
  (eyes, buttons, trims). Symmetric: write the left (+X) one with `mirror: x` (+ `mirror_id` if it moves).
- Holes: a `cut: true` part after the solid; hollow: `shell:`. Floating on purpose: `loose: true`.
- Big plain areas read better as geometry (planks, trims) than patterns, which cost triangles (W110).
- Inspiration images are reference only: never copy another game's characters, never model real people.
- Free assets only with a licence that allows it (CC0, CC-BY; never NC, ND, SA, "no AI").
- KILN seems wrong (a crash, a misleading message)? Say so and offer to report it (`kiln docs report`).
