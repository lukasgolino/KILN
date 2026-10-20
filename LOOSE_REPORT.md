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

## 2026-10-20: wiring KILN output into the game (LOOSE branch `kiln`)

### Bugs

17. **glTF extras of the last joint land on the Skeleton3D node.** Every skinned model's `Skeleton3D` carries
    `extras: {"hitzone": "eye", "kiln_part": "eye_r"}` (the soldier's last bone); the horse's carries eye_r's too.
    Harmless for LOOSE (it reads bones), wrong for anyone reading node meta.

### Friction / missing

18. **The `.tscn` style script works per instance.** `_ready()` duplicates every surface material and sets surface
    overrides on each instance: N soldiers = N x 9 unique materials (no material sharing/sorting), and it overwrites
    any override the game set before `add_child` (team colour swaps were lost). LOOSE loads the `.glb` instead and
    restyles each imported mesh once (shared materials). Proposal: bake the style into shared material resources
    (a `materials.tres` library or sub-resources in the `.tscn`) instead of a runtime script.
19. **One surface per palette colour = many draw calls.** A soldier body is 9 surfaces plus 2-3 rigid items:
    ~12 draw calls per soldier. 150-soldier bench: 2505 draw calls / 3256 objects (KILN) vs 1494 / 1652 (KayKit,
    texture atlas). Proposal: an export option with vertex colours and one material per preset (fabric, skin,
    metal...), so a body is 3-5 surfaces; the variant swap table then maps vertex colours (or a palette texture).
20. **No way to skip variant files** (follow-up to 14): LOOSE swaps colours from the manifest-style table at run
    time and excludes `<m>.<v>.glb`, `*.lod*.glb`, `*.tscn` from its export: 28 MB of the 37 MB output is unused.
    A `[build] variants = "manifest"` (swap table only) setting would avoid writing them.
21. **Material presets read too shiny under a sky.** `metal` (metallic 0.8, roughness 0.35) and `gold` (1.0/0.3)
    mirror the sky; `skin` at roughness 0.55 shows a pale horizon band across bald heads. LOOSE caps metal at
    0.35/0.55, gold 0.5/0.45 and raises skin to 0.8 roughness. Proposal: soft_toy presets closer to that, or a
    `reflections` knob in the style.
22. **Rigid machines need geometry the manifest doesn't give.** To swing the trebuchet arm and place its load the
    game needed the arm's built-in angle (rest = cocked, about -0.53 rad), pivot-to-tip lengths and the sling
    stone's position: all measured by hand from the source. Proposal: `sockets` (see 10) for tips/loads, and the
    angle a part is built at in the manifest when an animation's first frame isn't the rest.

## 2026-10-20: why LOOSE's owner prefers the CC0 packs (KayKit/Kenney), and what KILN would need to match them

Owner verdict after playing both branches: KILN version "completely broken": heads hollow and see-through when the
helmet falls off, helmets look like hats; CC0 version better. Evidence renders (Godot 4.7.2, same light/camera) were
made in the LOOSE session scratchpad (`kilngap/01_hollow_head.png`, `02_helmets.png`, `03_machines.png`,
`lineup_kiln.png`, `lineup_kaykit.png`).

### 23. Hollow head = item 11, still shipping in LOOSE (pinned v0.1.0)

- LOOSE's `assets/kiln` was built with KILN **v0.1.0** (`.venv-kiln` pin `5db55af`). In 0.1.0 `separate: true`
  parts are meshed in the body's union field: the helmet's brim disc (cylinder r 0.47, y 1.475..1.525) passes
  through the head sphere, so that band of head surface is interior to the union and never meshed; the brim faces
  go to the helmet bone. Detach the helmet and a ~1.6 m long open loop (y 1.4..1.6) is left in the head mesh: you see
  into the empty skull. Same for the knight's great helm (face/visor area missing) and the sword grip (hole through
  the hand). glTF check: footman body mesh 281 open edges in 0.1.0 vs 36 in a HEAD (0.3.0) rebuild; the HEAD
  rebuild's head is closed (render). Not a game bug.
- Fixed in 0.3.0 source (each separate part in its own field) but **untagged**: tag v0.3.0 so games can pin it.
- Residual in 0.3.0: ~36 open edges (cracks 1-5 cm) at colour borders near the bum/hips and the eyes. Weld check
  (no boundary edges on a closed SDF piece) should be a lint error, not left to the eye.
- Still missing for detachables: the surface *under* a separate part is generic (a bald sphere with the band of
  hair/forehead the helmet hid). CC0 packs model the head under the helmet on purpose (KayKit Knight_Head has hair).
  Proposal: `under: {color: hair, ...}` paint for the area a separate part covers, or a `revealed:` part list
  shown only when the detachable is gone.

### 24. Why KILN helmets read as hats (02_helmets.png)

- **Silhouette/fit**: KILN helmets perch on top of a sphere head (dome from the brow up, brim 1.6x head width),
  ears, hair and the whole jaw stay exposed. KayKit's helmet wraps the skull down to the cheeks/chin with a face
  opening, so it reads as armour enclosing a head. A brimmed kettle hat is historically right but at 640x360 a
  smooth dome + wide brim *is* the hat silhouette.
- **No hard-surface language**: SDF smooth-min + smooth normals give a uniform soft bowl with one big specular blob
  (plastic/tin, not forged steel). KayKit uses planar facets, crisp creases, a central ridge/crest, layered plates,
  chamfered edges, visible thickness at the rim and a gradient atlas that darkens recesses. KILN has no
  crease/bevel control per edge, no ridges/rivets/bands/visor slits as primitives, and the rim has no thickness read.
- **Broken construction at the face**: the great helm is a cylinder with a slot; the googly eyes (spheres larger than
  the slot) poke through the metal. Nothing stops a part penetrating another part's shell.
- **Detail lost by decimation**: rivets, bands, crest pieces are the first things W111 drops at LOD1/LOD2.

### 25. Broader gap vs KayKit/Kenney (lineups, 03_machines.png)

| | KayKit / Kenney | KILN 0.1-0.3 |
|---|---|---|
| Silhouette | designed proportions, overlapping layers (cape, belt, pauldrons, hood) | blobby capsules + spheres; one-layer bodies; every character is the same bean |
| Edges | intentional planar facets, chamfers, octagonal wheels | either soft SDF (soft_toy) or decimation-random facets (low_poly): no designed edge flow |
| Face | small painted features in the atlas, brows/beard/hair masses as shapes | big sphere eyes on a sphere head: one face for every character |
| Surface colour | one 1-material gradient atlas: 1 draw call, baked AO-ish shading in the texture | one surface per colour: footman 15 surfaces/11 materials, knight 20/14; no baked shading |
| Triangles | Kenney trebuchet 1518 tris, KayKit Knight 5800 | KILN trebuchet 7762 (5x) yet softer |
| Rig/anims | standard 23-joint humanoid (KayKit Rig_Medium), ~82 shared clips (walk, run, attack, hit, death, climb, cheer...) retargetable | per-model pose lists, 8-12 hand-written procedural cycles; no standard skeleton, no retargeting |
| Machines | planks, beams, iron bands, bolts, flags, contrasting materials | boxes and capsules in wood; reads closer to CC0 than the characters do |
| LODs | none (cheap base mesh) | yes (a KILN plus) |
| Detachables | separate authored meshes, closed, with modelled surface beneath | 0.1.0 holes (fixed 0.3.0); generic surface beneath |

KILN's advantages are real: text-diffable, consistent palette/scale, cheap variants, LODs, rig metadata/hit zones,
custom props on demand. The weakness is that SDF + smooth union + decimation inherently produces "soft clay toy",
and the CC0 look is "hand-built low poly with a texture atlas".

### Proposal: what KILN needs (priority order, effort S/M/L)

1. **Tag 0.3.0 + watertight lint** (S). Release the separate-part fix; E-level lint when a closed piece has open
   edges; check the area under each `separate` part (render with it hidden, part of `kiln preview --detach`).
2. **Hard-surface mode** (L). Per-part `blend: none` (exact CSG, no smoothing), polygonal primitives with explicit
   side counts (`sides: 8` cylinders/lathes), `bevel`/`chamfer` widths per part, crease-preserving export (split
   normals on designed edges, facet normals inside a part), and quad-dominant polygon output for those parts instead
   of dual-contour + decimation. This is the single biggest step toward Kenney/KayKit (planks, beams, wheels,
   helmets, armour plates).
3. **Shell/thickness + no-penetration** (M). `shell: {thickness}` for helmets/brims/shields with a visible rim; lint
   when one part's surface pokes through another's shell (eyes through visor).
4. **Template library for characters and armour** (M-L). Curated head/face templates (brow, nose, jaw masses; eyes
   as painted decals or flush insets, not spheres), helmet archetypes that fit a head template (kettle hat, nasal
   helm, barbute, great helm, sallet with cheek/neck guards) and armour pieces (pauldron, breastplate, gauntlet,
   belt, cape, hood) with sockets to snap on. LOOSE built every soldier from scratch in a generator script.
5. **Single palette-atlas output** (M). One material per model (or per preset class), UVs into a small gradient
   palette texture (KayKit-style), optional baked AO/cavity into vertex colour or the atlas. 1-2 draw calls per
   character instead of 15-20; recolouring = texture swap.
6. **Standard humanoid skeleton + clip retargeting** (L). `rig: humanoid` that names joints like KayKit Rig_Medium /
   Mixamo, auto-weights to it, and `animations: {import: <CC0 clip glb>}` retargeting so a KILN character gets the
   82 CC0 clips for free. Procedural cycles stay for creatures/machines.
7. **Reference-comparison critic loop** (M). `kiln preview --vs <ref.glb>` side by side at matched scale/camera, plus
   automated checks against a reference (silhouette IoU, triangle efficiency, colour count, facet regularity) so an
   agent iterates against a CC0 target instead of in a vacuum.
8. **Smarter decimation for small detail** (M). Protect named detail parts (rivets, crests, eyes) through LODs
   (W111 currently drops them at LOD1/2), and planar-aware decimation (preserve flat regions as few large faces).
9. **Hardware details as parts** (S-M). `rivets: {count, along: edge}`, `band`, `planks: {count, gap}`, `bolt`,
   `slit` cut primitives: the micro-detail CC0 packs use to read as metal or wood.

### Verdict

- **Can plausibly match CC0 (with 1-3, 9):** rigid props and machines (siege engines, carts, barrels, gates,
  walls, tents, fences), simple creatures, stylised nature. They are mostly boxes/cylinders with bevels; KILN is
  already near Kenney there and LODs/variants/hit-zone metadata are a plus.
- **Unlikely to match without hand-authored content:** characters. KayKit's quality comes from hand-made faces,
  layered clothing, texture-atlas painting and a big shared animation library. An SDF generator can approach it
  only with a curated template library (4) plus retargeting (6), i.e. effectively shipping hand-made parts.
- **Recommended hybrid for LOOSE-type games:** CC0 (KayKit) base bodies, heads and the shared animation library;
  KILN for custom attachments made to fit those rigs (helmets, shields, banners, weapons as separate closed meshes
  with sockets from the CC0 rig), custom props/machines/buildings, and recolour/variant/LOD/hit-zone tooling over
  both. That needs KILN to import a CC0 rig as the target for attachments (`fit_to: Knight.glb#head`).
