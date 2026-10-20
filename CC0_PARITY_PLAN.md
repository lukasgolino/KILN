# CC0_PARITY_PLAN.md — make KILN output as good as KayKit/Kenney

## STATUS (2026-10-21) — read this first if you are continuing the work

Owner's instruction: do every milestone below, commit as you go, tag a release when it makes sense (0.4.0 or
smaller steps are fine). Never push without asking; never add AI attribution to commits. v0.3.0 is pushed and tagged.

| Milestone | State | Where |
|---|---|---|
| M1 watertight detachables | DONE | commit c311dbd (+ da39833): split() fixes T-junctions, drop_twins(), E013 lint, `under:` paint, `preview --detach`, tests/test_watertight.py |
| M2 hard surface | DONE | c311dbd: src/kiln/hard.py (BSP CSG, bevels, planar re-merge), builder hard_parts/build_hard, style hard_surface/hard_sides, tests/test_hard.py |
| M3 shells + no-penetration | DONE | da39833: `shell: {thickness, side, open}`, `fit: {to, gap}` (Geometry.fit in sdf.py), W113 (lint.penetrations), tests/test_shells.py |
| M8 keep + hardware | DONE | 2ce9d1b: `keep:` + auto-keep small crisp parts (builder.kept_parts/_kept), src/kiln/hardware.py (rivets, band, planks, bolt, slit), tests/test_hardware.py. Planar-aware decimation: QEM already does it; pinned by a test |
| M7 reference critic | DONE (merged) | branch m7-reference-compare (cd38b09), merged into main: `preview --vs ref.glb [--ref-height]`, metrics, MCP, skill workflow, tests/test_compare.py. Worktree /home/lgolino/repos/KILN/.claude/worktrees/m7-compare can be removed |
| M9 palette atlas | IN PROGRESS by a subagent (may be unfinished) | branch `m9-atlas`, worktree /home/lgolino/repos/KILN/.claude/worktrees/m9-atlas (uncommitted work may be there: check `git -C <dir> status`); spec: setting `atlas = true`, one material + palette PNG per model, ORM texture, variants = texture swaps, optional AO in COLOR_0, tests/test_atlas.py. If nothing usable exists, implement from section M9 |
| M5 humanoid rig + retargeting | TODO | KayKit files (CC0) at ~/repos/loose/assets/third_party/kaykit-animations/Rig_Medium_*.glb and kaykit-adventurers/Knight.glb; owner OK'd committing ~2 MB of them as test fixtures |
| M6 fit attachments to CC0 rigs | TODO | needs M3 fit (done) + a mesh SDF of the CC0 target (sample its surface, grid-hash nearest point, sign from normals) |
| M4 template library | TODO | needs `extends:` to find package templates (notation.resolve_extends only looks in models/); put them in src/kiln/library/ |

DONE: v0.4.0 tagged locally (M1-M3, M7, M8; not pushed). Next release (0.5.0) after M9, M5, M6, M4:
- Rebuild the demo output (`cd examples/demo && kiln build --verify-godot`) and commit examples/godot/assets: every
  mesh changed (crack fix, shading fix). Bump BUILDER_VERSION if meshing changes again (now 10).
- Bump version in pyproject.toml, move CHANGELOG [Unreleased] to [0.4.0] - date, add CLAUDE.md decision-log lines
  (hard surface via BSP CSG in pure Python; crease test uses half sharp_angle with a 15% inset; kept parts as own
  meshes; hardware expands at parse time), tag v0.4.0 locally, ask the owner before pushing.
- Then: rebuild ~/repos/kiln-website with the new tag (tools/build_site_assets.py --kiln-repo ~/repos/KILN; bump
  requirements.txt) and tell LOOSE's agent (via its KILN_LOG.md / LOOSE_REPORT.md) what's new.

Known limits / notes for the next agent:
- Machine has ~6 GB RAM shared with other sessions: run test files selectively; full suite takes ~4 min.
- Tests: `.venv/bin/python -m pytest -q -p no:cacheprovider`; types: `.venv/bin/mypy` (strict, must be clean).
- Hard parts are not decimated; LOD/budget pressure lowers their detail level (bevel->chamfer->none->fewer sides).
- A few non-manifold "pinch" edges remain on thin soft parts (no holes); E013 only reports open edges.
- Smooth thin shells still shade a little noisily at their rims.


Source: LOOSE_REPORT.md items 23–25, Proposal and Verdict (2026-10-20). Evidence renders were made in the LOOSE session
scratchpad (`kilngap/01_hollow_head.png`, `02_helmets.png`, `03_machines.png`, `lineup_kiln.png`, `lineup_kaykit.png`).
Copy any you want kept into `docs/` before that scratchpad goes.

## 0. Goal and verdict

The LOOSE! owner played the same game twice: once with KILN models and once with CC0 packs (KayKit characters, Kenney
castle and siege engines). Verdict: the CC0 build is better, and the KILN build is "completely broken". The reasons:
- heads are hollow and see-through after a helmet falls off;
- helmets read as hats;
- every character is the same bean.

**Goal:** a game can pick KILN over CC0 packs for any asset class without losing quality, and use KILN to make custom
assets that sit seamlessly next to CC0 ones.

**Verdict on reachability:**

| Asset class | Reachable? | Needs |
|---|---|---|
| Rigid props, machines, buildings (siege engines, carts, barrels, gates, walls, tents, fences) | Yes. Already close to Kenney. | M1, M2, M3, M8 |
| Simple creatures, stylised nature | Yes | M1, M2, M7 |
| Attachments for CC0 characters (helmets, shields, weapons, banners) | Yes. Best near-term value. | M1–M3, M6 (`fit_to`) |
| Characters on par with KayKit | Only by shipping curated hand-made templates plus retargeted CC0 animation | M4, M5, M6 |

The SDF + smooth union + decimate pipeline inherently produces "soft clay toy". The CC0 look is "hand-built low poly
with a texture atlas": designed facets, crisp creases, layered silhouettes, painted faces, one material. Parity needs a
second, exact path (hard surface), not more tuning of the soft path.

**Recommended product direction:** a hybrid.
- CC0 bodies, heads and animation libraries stay.
- KILN makes custom attachments fitted to those rigs, plus props, machines and buildings.
- KILN adds its variant, LOD and hit-zone tooling over both.

## 1. Already done in 0.3.0 (untagged)

- `separate: true` parts are meshed on their own and closed, which fixes the hollow head (item 11/23).
- `vertex_colors = true`: one surface per material preset. This partly addresses draw calls (item 19).
- `sockets`, part `aabb` in the manifest, model families (`template` / `extends`), `variant_glbs = false`, softer
  soft_toy metals, the Godot sandbox for verification.

**Action (owner):** tag v0.3.0 so games can pin it. LOOSE is still on v0.1.0 and ships the hollow heads.

## 2. Milestones

Effort: S ≈ a day, M ≈ several days, L ≈ a week or more of agent work. Each milestone lands with tests, a CHANGELOG
entry, a minor version bump, and demo models in `examples/demo` that show it.

Order: M1 → M2 → M3 → M8 → M9 → M7 → M5 → M6 → M4.
- M1–M3 + M8 make props, machines and attachments match CC0.
- M9 brings draw calls down to CC0 levels for crowds.
- M7 gives agents a way to see the gap themselves.
- M5–M6 unlock the hybrid with CC0 characters.
- M4 is the long pole for full KILN characters.

### M1 — Watertight detachables (S)

Problem: open edges on closed pieces. 36 remain in 0.3.0, as 1–5 cm cracks at colour borders near the hips and eyes.
The surface under a separate part is generic: a bald sphere with the band the helmet hid.

- **E-level lint (E013):** a closed SDF piece (body or separate part) with boundary edges after build. Report the
  part, the number of edges and their location.
- **Weld colour borders after the pull-apart / decimate / weld cycle:** every border vertex is shared by both sides.
- **`kiln preview <model> --detach`:** one row per detachable, rendered with it hidden, and a close-up of the revealed
  area.
- **`under:` on a separate part:** paint for the area it covers, e.g. `under: { color: hair }`. Alternatively
  `revealed: [ids]`, parts shown only once the detachable is gone (a hair cap, a bruise).
- **Tests:**
  - every demo character's body and separate parts have 0 boundary edges;
  - a fixture whose helmet brim cuts through the head yields a closed head;
  - E013 fires on a deliberately cracked fixture.

### M2 — Hard-surface mode (L)

The biggest single step toward Kenney/KayKit.

- **`blend: none` per part:** exact CSG (union / cut / intersect) with no smoothing, and a crisp crease where the
  surfaces meet.
- **Polygonal primitives:** `sides: N` on cylinder, cone, lathe and torus (an octagonal wheel, a hexagonal beam);
  `box` stays 6-faced.
- **Bevel and chamfer per part:** `bevel: 0.02` (rounded edge band) or `chamfer: 0.02` (one flat cut), with
  `segments: 1..3`.
- **Exact polygon output for hard parts:** emit the polygons directly from the primitive or CSG instead of dual
  contouring + decimation. Hard and soft parts can mix in one model; the soft path stays for bodies.
- **Normals:** split normals on designed edges, facet normals inside a hard part, smooth inside soft parts.
- **Style:** `hard_surface = "auto" | "always" | "never"` on the style; low_poly defaults to always for props.
- **Tests:**
  - a box with `chamfer` = 26 faces;
  - a `sides: 8` cylinder = 8 side quads + caps;
  - a crease is kept at a CSG seam;
  - the trebuchet demo rebuilt hard is at most 2000 triangles (Kenney: 1518) and still reads as wood;
  - byte-identical rebuilds.

### M3 — Shells and no-penetration (M)

- **`shell: { thickness }`** on any shape (generalising PAGAN's `shell`), for helmets, brims and shields, with a visible
  rim so they read as metal plate, not a solid lump.
- **Penetration lint (W113):** one part's surface pokes through another part's shell or outer surface (the great
  helm's eyes through the visor slot). Report the overlap volume and the location.
- **`fit: wrap`** on a shell part: the shell is offset from the parent's surface by `thickness + gap`, so a helmet
  wraps the skull down to the cheeks instead of perching.
- **Tests:**
  - the knight fixture flags W113 until the eyes are moved inside;
  - a shell helmet's rim thickness is measurable in the mesh.

### M4 — Character and armour template library (M–L)

Every LOOSE soldier was built from scratch in a generator script, and every face is two sphere eyes on a sphere.

- **Head and face templates** (`kiln new model --template head/<name>`): brow, nose and jaw masses, hair masses, ears.
  Eyes are painted decals or flush insets, not protruding spheres. At least 6 distinct faces (young, old, bearded,
  stern, goofy, female).
- **Body templates:** at least 3 builds (slim, stocky, big) with layered clothing (tunic over trousers, belt, boots,
  collar), each with sockets.
- **Helmet archetypes** that fit the head templates: kettle hat, nasal helm, barbute, great helm, sallet (with cheek
  and neck guards), a crown helm.
- **Armour pieces:** pauldron, breastplate, gauntlet, cape, hood. Each snaps to a socket and inherits the hard-surface
  (M2) and shell (M3) rules.
- **Library mechanics:** templates ship in the package (`kiln/templates/…`), are used through `extends`, and are
  versioned with the package. Previews of the whole library go in `docs/templates.png`.
- **Test:** a 6-character line-up built only from templates. Human review against `lineup_kaykit.png`: each reads as
  a different person at 20–60 m.

### M5 — Standard humanoid skeleton + clip retargeting (L)

This is PLAN.md's M7b, promoted.

- **`rig: humanoid`:** joints named like KayKit Rig_Medium, with a mapping to Mixamo and Godot SkeletonProfileHumanoid,
  auto-placed from the template's parts. Weights come from the field as now.
- **`animations: { import: <CC0 clip glb>, map: … }`:** retarget CC0 clip libraries (e.g. KayKit Character Animations,
  about 82 clips) onto KILN humanoids at build time. The procedural cycles stay for creatures and machines.
- **Godot output:** works with Godot's retargeting (a SkeletonProfile resource), so a game can share one
  AnimationLibrary between KILN and CC0 characters.
- **Tests:**
  - a KILN template character plays KayKit's Walking_A / Death_A without broken limbs (bone-length tolerance, a
    preview filmstrip);
  - the manifest lists the imported clips.

### M6 — Fit attachments to CC0 rigs (M)

The hybrid route, and the most valuable thing KILN can do for LOOSE now.

- **`fit_to: Knight.glb#head`** (or `#handslot.r`): import a CC0 rig and mesh as the target. The attachment is placed
  in that bone's space, wraps the target surface (M3 `fit: wrap`), and exports as a separate closed mesh with the
  bone name in the manifest.
- **Lint:** penetration (W113) and fit gap against the CC0 mesh.
- **Preview** on the CC0 character, with the attachment on and off.
- **Test:** a KILN great helm fitted to KayKit Knight's head bone, with no penetration, a closed mesh, and correct
  bone/socket placement in Godot `--verify-godot`.

### M7 — Reference-comparison critic loop (M)

So an agent iterates against a CC0 target instead of in a vacuum.

- **`kiln preview <model> --vs <ref.glb>`:** side by side at matched scale, camera and look kit (turntable plus
  close-ups).
- **Metrics in `--json`:** silhouette IoU from 8 views, triangle count ratio, surface and material count, colour
  count, facet regularity (normal clustering), open edges.
- **Skill update:** a "match a reference" workflow that iterates until the metrics are inside thresholds the user sets,
  then shows both renders.
- **Test:** the metrics are stable across runs; identical models give IoU 1.0.

### M8 — Detail-preserving decimation + hardware parts (M + S–M)

- **Protected parts:** `keep: true` (or an automatic rule for parts under 2% of the model's size) survives every LOD.
  Today W111 drops rivets, crests and eyes at LOD1 and LOD2.
- **Planar-aware decimation:** flat regions collapse to few large faces before curved ones lose detail.
- **Hardware primitives**, all hard-surface (M2) by default:
  - `rivets: { count, along: <edge or path>, size }`
  - `band: { at, width, thickness }` (iron bands on barrels and doors)
  - `planks: { count, gap, jitter }` (doors, decks, walls)
  - `bolt`
  - `slit: { width, length }` (visors, arrow slits)
- **Tests:**
  - a barrel with 2 bands and 8 rivets keeps them at LOD2;
  - a plank door has N separated planks with gaps.

### M9 — Single palette-atlas output (M)

0.3.0's `vertex_colors` cut surfaces to one per material preset. Go to KayKit's model:
- one material per model (or per preset class);
- UVs into a small gradient palette texture;
- optional baked AO / cavity into the atlas or the vertex colour.

Result: 1–2 draw calls per character instead of 15–20 in LOOSE. Recolouring a team becomes a palette-texture swap,
which also replaces per-variant scenes.
- **Test:** the footman demo has ≤ 2 surfaces; a recolour is a texture swap with no mesh change.

## 3. What to measure the result against

Re-run LOOSE's comparison once M1–M3 + M8 land, and again after M5–M6:
- the same cameras, CC0 on the left and KILN on the right;
- a helmet-off close-up;
- a siege engine line-up;
- 150 soldiers' draw calls.

The owner's bar is "as good as the CC0 build".

## 4. Non-goals

- Photoreal or PBR-textured output.
- Image-to-3D.
- Beating KayKit's hand-painted faces with pure SDF. Use templates (M4) or the hybrid (M6) instead.
