# Imported

Imported models: CC0 packs, kiln import, matching a reference.

## Imported models (free CC0 packs)

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

**.fbx, .blend, .obj** (optional, needs Blender 4.x: `blender` on PATH or `BLENDER=/path/to/blender`; `kiln doctor`
shows which). Blender exports the file as a glb (+Y up, modifiers applied, skins, animations, the active vertex
colours, textures as they come), which then imports like any glb. Two ways in:

- `kiln import Knight.fbx --licence CC0-1.0 ...` converts once and writes `imports/Knight.glb` (the original isn't
  copied); the model names the glb, so the project builds anywhere without Blender. Preferred.
- `source.file`, an animation's `import:` and `fit_to.file` may name the .fbx/.blend/.obj directly: every load then
  needs Blender, and the glb is cached in `.kiln-cache/blender/<key>/<name>.glb` (key: the file's sha256, an .obj's
  .mtl and texture maps, the Blender version, the export script version), so only the first build runs it. Credits
  name the original file.

No Blender, or one older than 4: E010 (E008 for an animation `import:`) saying how to fix it; a failed conversion
shows the end of Blender's output. FBX clip names carry Blender's armature prefixes (a `Wave` action came out as
`Rig|Rig|Wave`); a wrong `clip:` lists the real names.

### CC0 packs (`kiln pack`)

KILN ships recipes for CC0 packs (`kiln pack list`): Kenney (`kenney-mini-dungeon`), KayKit (`kaykit-adventurers`,
`kaykit-furniture-bits`, `kaykit-city-builder-bits`, `kaykit-dungeon-remastered`) and Quaternius
(`quaternius-modular-scifi-megakit`). A recipe pins the archive's URL and sha256; mirroring checks both and that the
pack's licence file says CC0.

```sh
kiln pack add kaykit-adventurers          # the only command that downloads: into ~/.cache/kiln/packs/<pack>@<version>/
kiln pack search knight --json            # file name and tags (the pack's own + its folders); triangles, size, bytes
kiln pack search chair --pack kaykit-furniture-bits --lineup   # + previews/pack-search.png: the hits at one scale
kiln pack import kaykit-adventurers knight --height 1.8 --class character
```

Mirrors are per user, shared between games (`$XDG_CACHE_HOME/kiln/packs`; `KILN_PACK_CACHE` overrides). Search terms
must all match, ranked whole name > a word of the name > part of it > a tag. `kiln pack import <pack>[@version]
<path|name>` copies the model and the files it refers to into `imports/<pack>/`, writes the model (as `kiln import`:
`source:` with CC0-1.0, the pack's author and page) and records every copied file in `kiln.lock` (JSON: path ->
pack, version, url, sha256, licence, file in the pack). Commit `kiln.lock` and `imports/`; the cache stays out of the
repo. A recipe file works too: `kiln pack add my-pack.toml` (fields `name`, `version`, `url`, `sha256`, `licence` =
CC0-1.0 only, `author`, `homepage`, `strip` leading folders, `models` folder, `licence_file`, `textures` shared folder,
`tags`).

With a `kiln.lock`, lint and build check it (E014 errors fail the build): a listed file whose sha256 changed, an
entry whose licence isn't CC0-1.0, a model whose `source.licence` differs from its file's entry; a listed file that's
gone is W115. Files without an entry (local `kiln import`) aren't checked; no `kiln.lock`, no checks. CREDITS.md and
the manifest's `source` name the pack (`pack: kaykit-adventurers@1.0`) for locked files.
