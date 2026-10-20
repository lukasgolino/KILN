# LOOSE! dogfooding report (KILN v0.1.0)

Append-only. From the LOOSE! game (Godot 4.7.2, slapstick siege; ~/repos/loose, art in `art3d/`, branch `kiln`).
Each item: what happened, where, a generic proposal. Not fixed here; for KILN's own planning.

## 2026-10-20: first pass (40 text models + 4 CC0 imports, soft_toy-derived style)

### Bugs

1. **Zero-length polygon edge -> NaN field (silent).** `sdf.polygon_2d` (src/kiln/sdf.py:38) divides by `e @ e`; an
   `extrude` outline with two identical consecutive points (or first == last) makes every distance NaN. Effects:
   every later part W101, `W108 ... nan m across`, nothing meshes. Proposal: E003 in notation for repeated points
   (or drop zero-length edges), and treat any NaN in the field as an error.
2. **Paint ownership ignores later cuts.** `paint.regions` (src/kiln/paint.py:173-216) assigns faces by raw
   `field.part_distance`; a surface inside a volume an earlier part had cut away (doors in a cut archway, anything in
   a carved niche) gets that earlier part's colour. Proposal: for ownership use `max(d_part, -d_cut)` over the cuts
   that come after the part (the same order rule the field uses).
3. **Decimation erases thin parts at low budgets; lint then blames the model.** A 6 m model with thin rotated plates,
   wheels and a log at `budget: 6000`: plates/wheels removed, sliver triangles remain; lint reports W101 "no visible
   surface" for parts that are fine before decimation. Same file at 40000: correct. `lod: [3000]` silently produced
   12862-18428 triangles. Proposals: (a) protect small connected pieces / per-part minimum faces in
   `mesher.decimate_regions`; (b) run W101 on the undecimated mesh and add a separate warning "part lost all faces in
   decimation (budget too low)"; (c) warn when a LOD misses its target by > 25%.
4. **Import drops externally referenced textures in sub-folders.** `kiln import x.glb` copies the glb (and same-folder
   files for .gltf) but not `images[].uri` like `Textures/colormap.png` (every Kenney kit). Result: white model, no
   warning. Proposals: copy every referenced URI preserving relative paths; E010 when a referenced image is missing.
5. **Build cache ignores source/texture files.** `builder.cache_key` (src/kiln/builder.py:69) keys on the model; after
   fixing an import's texture the cached white mesh was served until the .kiln.yaml changed. Proposal: hash
   `source.file` and the images it references into the key.
6. **`--verify-godot` imports the whole host Godot project.** In LOOSE it rewrote an unrelated
   `assets/generated/fonts/*.png.import` (to `importer="skip"`). Proposal: verify in a temporary project that contains
   only `output_dir` (+ a minimal project.godot), or at least report files outside `output_dir` that changed.

### Friction / missing features

7. **pagan pin clash.** pyproject pins `pagan @ git+https://...@v0.9.0`; a game that pins another PAGAN tag (LOOSE:
   v0.8.0 over ssh) can't install both in one env or one requirements file. Proposals: depend on a version range
   (`pagan>=0.8,<0.10` via tags), or vendor the small pieces used (palette loader, glTF writer).
8. **`kiln init` inside a Godot project writes no `.gdignore`** (PAGAN does). Godot would import `imports/*.glb`,
   previews etc. Proposal: write it when a `project.godot` is found above.
9. **No per-part boxes in the manifest.** Parts carry pivot/parent/meta; games that do hit zones need a box per part
   (PAGAN's manifest has AABBs). Proposal: `parts.<id>.aabb` in rest pose, model space (faces owned by that bone /
   dominant weight), plus the Godot node path.
10. **Rig meta is scalars only** (E007 on `seat: [0, 1.56, 0]`). Proposal: allow flat lists of numbers (vectors), or
    a `sockets:` section (named points/frames on bones: seat, hand slots, muzzle).
11. **`separate: true` parts are meshed in the body's field,** so a helmet/grip that overlaps the body fuses with it
    and a detached part leaves a hole. Proposal: mesh each separate part in its own field (its own closed surface)
    and don't count it for W103.
12. **No model families.** PAGAN's `template`/`extends` (+ `remove`) would replace the generator script LOOSE uses for
    8 soldier types sharing one body.
13. **Cycles and explicit poses don't combine.** Want `cycle: walk` for legs + pose overrides for arms (carry, push,
    climb) or additive layers. Proposal: `cycle` + `poses` in one animation, poses override per part.
14. **Variants duplicate everything.** Each variant is a full glb with all animations (~410 KB per character here),
    LODs only exist for the base, only the base gets a `.tscn`; 6 team colours x 8 characters = 37 MB. Proposals: a
    `variant_glbs = false` mode (manifest `swap` table + material overrides in the .tscn), or variant scenes that
    reuse the base glb with swapped materials.
15. **Cold lint is slow** (4 min 41 s, 40 models). Lint and preview share the cache, which helps afterwards.
16. **W103 is noisy for intentionally loose parts** (flames, clappers, bees, rubble, detachables): per-part opt-out
    (`loose: true`) would be better than disabling W103 for the whole model.

### Good

- Review tooling is excellent: turntable (3 heights), `--closeup`, `--pose` filmstrips, `lineup` with a 1 m bar,
  `gallery`, `--engine`. The lineup made scale problems obvious immediately.
- Soft skins + separate rigid detachables, `mirror_id` rig mirroring, LODs, variants, look kit and `--verify-godot`
  all worked first time (44 models load in Godot with parts, animations, materials).
- KayKit imports restyle into the palette convincingly.
- `kiln.api.part` / `dumps` make generator scripts easy; errors say how to fix them.
