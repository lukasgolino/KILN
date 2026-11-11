# Setup

Start of every session, a new project, kiln.toml and the project layout.

## Start of every session

1. `kiln status` (or MCP `status`): what exists, what needs review. No `kiln.toml`? `kiln init <dir> --style <preset>`
   (inside a Godot project it writes `.gdignore` in the KILN folder, so Godot skips the sources, and sets `output_dir` to the
   Godot project's `assets/kiln` with `export = ["glb", "godot"]`; `kiln build` with Godot export refuses an output Godot ignores).
2. Read `BRIEF.md` (what the game needs, decisions) and `STYLE.md` (how it looks). They are the project's memory.
3. `kiln style show`: the style's notes (shape language, proportions) and numbers. Follow them.

New project: ask the owner (one batch, each with your recommended default):
- the game and the camera (how close does it get? that decides how much detail matters);
- the style: a preset (`kiln style list`: soft_toy = Dear Passengers / Fall Guys, low_poly, toon, clay, diorama) or
  inspirations. With inspirations, ask for 3-6 screenshots into `styles/<name>/inspiration/`, look at them, and write a
  style that `extends` the closest preset (`kiln docs styles`);
- the palette (the starter `palettes/main.pal.yaml`, or their colours);
- whether the game is in Godot (then `export = ["glb", "godot"]` and `output_dir` inside the Godot project).
Write the answers into BRIEF.md and STYLE.md.


## Project

```
kiln.toml            settings (kiln config show)
palettes/main.pal.yaml   colours (PAGAN format): models use their names
models/<name>.kiln.yaml  one model per file (name = file name)
styles/<name>.style.toml own styles; styles/<name>/inspiration/*.png|jpg reference images
decals/  imports/        images for decals and textures (or a textures/ folder: paths are relative to the project); imported .glb/.gltf files
BRIEF.md  STYLE.md       what the game needs; how it looks (+ changelog)
```

```toml
# kiln.toml
default_style = "soft_toy"     # kiln style list
default_palette = "main"
output_dir = "build"           # inside the Godot project when export has "godot"
preview_dir = "previews"
preview_size = 400             # optional: kiln preview tile size in pixels (64-1024; a hero face needs ~400+)
export = ["glb", "godot"]
style_version = 1
variant_glbs = true            # false: no .glb per variant; Godot gets <name>.<variant>.tscn recolouring the base glb
merge_rigid = false            # true: a rigid skin is one skinned mesh (one draw call; every vertex 100% on its part's bone;
                               #   separate parts stay nodes; hide a part by scaling its bone to 0); manifest merged_rigid
vertex_colors = false          # true: colours in the vertices, one surface per material preset (fewer draw calls)
atlas = false                  # true: one material per model from small palette textures (1 surface, +1 per decal or texture; normal_map models keep a material per colour)
atlas_ao = false               # true or a strength 0..1 (with atlas): ambient occlusion baked into the vertex colours (normal_map models too)
godot_bonemap = false          # true: humanoids get models/<name>.bonemap.tres in their glb's .import; Godot RENAMES
                               #   their bones to SkeletonProfileHumanoid's (see Humanoids)
[lint]
disable = ["W106"]
```
