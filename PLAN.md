# KILN_PLAN.md — a PAGAN for smooth 3D game assets

> **To the agent reading this:** this is your brief for a new tool. Read it fully, then read PAGAN's
> `PLAN.md`, `CLAUDE.md` and `src/pagan/skill/` (in `lukasgolino/PAGAN`). KILN copies PAGAN's idea one-for-one:
> **Claude can't make art, but it can write text that a deterministic tool turns into art.** PAGAN does that for
> pixel art with palette-keyed grids. KILN does it for smooth 3D with **implicit surfaces**: parts described as
> shapes that blend into each other, the way clay does. The owner is busy: batch your questions, give each one a
> recommended default, and keep building on the defaults while you wait.
>
> **Name:** KILN = **K**eyed **I**mplicit **L**anguage & **N**otation. "Keyed" = palette-keyed colours, as in
> PAGAN. "Implicit" = implicit surfaces (signed distance fields), what every model is made of. A kiln is also where
> clay gets fired into its final finish. The owner may still rename it (§13).

---

## Status (2026-10-20): v0.1.0 built

M1-M7 and most of M8 are done; see CHANGELOG.md and CLAUDE.md's decisions log. Where the build differs from
this plan:
- **Previews:** KILN's own vectorised software renderer, so previews need no GPU or display. Godot renders on
  request with `--engine`. The plan had Godot only.
- **Patterns:** cut into the mesh along their zero lines, after local refinement, rather than baked into
  textures. Decals are the only textures.
- **LODs:** separate `.lod<N>.glb` files.
- **Not done:**
  - M7b humanoid retargeting (`rig: humanoid` mapping to SkeletonProfileHumanoid);
  - pack mirroring and search (`kiln pack add/search`): `kiln import` brings in local .glb/.gltf files;
  - the optional Blender extra (FBX/.blend imports).
- **Known limits:**
  - Very thin sharp rims (a cone roof overhanging its tower) can come out ragged at the default resolution.
  - The toon look kit is basic.
  - Cross-machine byte-identity is untested (CI checks build-twice equality).

## 0. Verdict

**Feasible, and free: Claude (Max subscription) writes the models; KILN, which is open source, builds them.**
No paid generators, no API keys, no GPU needed for the core. Build it as its own repo (`lukasgolino/KILN`).

### Evidence: spike, 2026-10-20

About 30 minutes of throwaway code:
- `scratchpad/kiln_spike/sdf.py` (≈100 lines: numpy + scikit-image marching cubes + trimesh glb export).
- Five assets written by hand as text: an airline seat, a caricature passenger, a bean pilot, a bean knight, a barrel.
- Rendered in Godot 4.7.2 with a hand-made soft-PBR environment.

Result:
- Recognisably the Dear Passengers family: smooth rounded shapes, googly eyes, saturated colours, soft shadows.
- Each asset was 5–11 primitives with smooth blends, about 20 lines of text.
- **Flaws seen** (all solvable, listed in §6):
  - jagged colour borders (per-vertex colour);
  - 60k–130k triangles (no decimation yet);
  - an over-bright ground;
  - a visor cut that hid the knight's eyes (a modelling mistake the preview caught at once, which is the loop working).

### Feasibility

| Part | Confidence | Why |
|---|---|---|
| Stylised characters (beans, mascots, caricatures, creatures) | **High** | Smooth-blended capsules/spheres/ellipsoids are what SDF does best (cf. Inigo Quilez's fully code-made characters). The spike's characters took minutes. |
| Props, furniture, vehicles, buildings | **High** | Rounded boxes, cylinders, revolve (lathe) and sweeps, cuts, mirrors and arrays cover most game props. Sharp-edged architecture needs a sharp-feature mesher (§6). |
| Many styles, chosen per game | **High** | The style lives in a **style profile** (§5.1): smoothness, bevels, facets, palette, materials, shader, lighting, proportions. The same notation renders as soft toy, faceted low-poly, toon or clay. |
| Rigging and animation | **Medium-high** | KILN built the parts, so it knows them: bones come from the part tree and skin weights from each part's distance field (§7). Poses as text, as in PAGAN. Complex organic motion (cloth, faces) is out of scope. |
| Detailed realism (photoreal faces, fabric, foliage clumps) | **Low: out of scope** | Use CC0 packs (Kenney, KayKit, Quaternius, Poly Haven), which are free, and unify them (§8). |
| Agent self-review | **High** | Godot renders the real build: turntables, line-ups, closeups, compared side by side with the owner's inspiration images. PAGAN already does Godot rendering. |
| Deterministic builds | **High** | Pure numpy, no generator, no network: same text in, same bytes out, as in PAGAN. |

### Spike v2, 2026-10-20 (`spike/`): go

The same `spike/models.kiln.yaml` (9 models, 4–12 parts each) built in two mesh styles and rendered in three looks
(`spike/shot_soft_toy.png`, `shot_low_poly.png`, `shot_toon.png`). The models are a seat, a passenger, a bean pilot,
a knight, an archer with a bow, a barrel, a trebuchet, a castle wall and a tree. Owner: "much better. Let's make that."

- **Fixed:**
  - clean colour borders (triangles split along the line where two parts meet);
  - triangle budgets (decimation, then vertices pulled back onto the surface);
  - linear glTF colours.
- **Budgets:** soft_toy characters ≈9k triangles, the trebuchet 15k, the wall 21k; low_poly 0.6–3k.
- **Build time:** about 40 s for all 9 (soft_toy), single process, unoptimised.
- **Known gaps:**
  - **Thin parts** (ropes, bowstrings) break up when thinner than about 2 field cells, badly in low_poly. Fix: build
    thin capsules/sweeps as exact meshes, or raise the resolution locally; lint "thinner than the style's resolution".
  - **Toon look** is overexposed. Its look kit needs tuning, not the meshes.
  - **Sharp hard-surface edges** are soft (marching cubes). Dual contouring in M2.
  - **Pale stone** reads white under this sky: a palette/look-kit issue, which `--vs-inspiration` reviews should catch.

### What changed from the first draft (2026-10-20)

- **Paid generators removed (owner):** no Tripo/Meshy. Everything comes from Claude-written text, CC0 packs, or the
  owner's own files.
- **Blender is not needed for the core.** Meshing, decimation, UVs, materials and glb export are done in Python, so
  KILN stays a `pip install` like PAGAN. Blender becomes an optional importer/cleaner for CC0 packs (M8).
- **Not one look:** Dear Passengers is one style profile, for LOOSE!. Every game picks or creates its own (§5.1).

### Why not inside PAGAN

PAGAN is pixel art and its 3D work is frozen (voxels). KILN shares PAGAN's palettes, colour code, findings, YAML
loader and glTF writer as a dependency (§3). Separate tags avoid churn, and a separate skill keeps triggering sharp.

### How PAGAN and KILN work together

PAGAN makes the 2D a 3D game still needs: UI, icons, decals and printed patterns (a Hawaiian shirt, an airline
logo, a sign), font sheets. KILN applies PAGAN images as **decals** and **pattern textures** on parts (§5.3).

---

## 1. The big picture

```
 owner ──talks──> agent (Claude + kiln skill / MCP)
                     │ writes text
                     ▼
   styles/<style>.style.toml    (the look: chosen from presets or made from inspiration images)
   models/<name>.kiln.yaml      (parts: shapes, blends, cuts, colours, rig, poses, LODs, metadata)
   palettes/*.pal.yaml          (PAGAN palette format)
                     │ kiln build (deterministic, pure Python)
                     ▼
   evaluate the distance field → mesh (sharp-feature aware) → part colours → decimate to budget → UVs/atlas
   → skin weights from parts → animations → glb (+ Godot .tscn/.tres, look kit) + manifest.json
                     │ kiln preview (Godot renders the real build with the style's lighting)
                     ▼
   agent looks at turntables / line-ups / "vs inspiration" sheets → edits text → owner approves
```

---

## 2. PAGAN → KILN concept map

| PAGAN | KILN |
|---|---|
| palette `*.pal.yaml` | same file format (KILN imports `pagan.palette`) |
| sprite grid / `.model.yaml` voxels | `models/<name>.kiln.yaml`: implicit parts |
| `[camera]`/`[light]`/STYLE.md | `styles/<name>.style.toml` + STYLE.md (the style profile) |
| render (deterministic) | mesh (deterministic) |
| poses, `rig:` | the same notation, plus real skinning |
| W/E lint rules | geometry, budget, scale, palette and style rules |
| preview / contact sheet / gallery / `--orbit` / `--closeup` | Godot turntables, line-ups, closeups, gallery, "vs inspiration" |
| BRIEF.md, `status`, `style_version`, `style bump`, `mark` | the same, one-for-one |
| manifest.json + Godot exporters + `--verify-godot` | the same contract |
| `pagan.api` for generator scripts | `kiln.api` (Python building blocks for repetitive things: fences, stairs, crowds of variants) |
| skill + MCP | the same |

---

## 3. Repository, reuse and dependencies

- New repo `lukasgolino/KILN`: MIT, Python ≥3.11, `src/` layout, mypy strict, pytest, CI with a Godot job.
- **Depends on `pagan`** (pinned tag) for:
  - `palette`, `color` (OKLab);
  - `findings`, `yamlio`;
  - `gltf` (the deterministic glb writer/validator built for PAGAN 0.8);
  - the Godot helpers (verify, SubViewport renders).
  Extract a shared package only if that coupling hurts.
- **Dependencies:** numpy, Pillow, PyYAML, pagan. Add only if needed, and log why:
  - **meshing:** write our own dual contouring / surface nets in numpy (deterministic, sharp features) rather than
    scikit-image's marching cubes (fine for the spike, but no sharp edges and it would be a heavy dependency);
  - **decimation:** quadric simplification. Write our own (deterministic, about 300 lines), or use
    `fast-simplification` (MIT) if it passes the byte-identical test.
- **No Blender, no GPU, no network** in the core. Optional extras: `kiln[blender]` (pack import/cleanup, M8) and
  `kiln[mcp]`.

---

## 4. Tech: from text to mesh

1. **Distance field.** Every part is a signed distance function (sphere, ellipsoid, capsule, rounded box, cylinder,
   cone, torus, revolve, sweep, extrude, text?), placed by transforms. Operations:
   - **union with a blend radius** (smooth union: clay-like joints);
   - **cut** (subtract) and **intersect**;
   - **shell** (hollow);
   - **mirror**, **array** (linear/radial);
   - **twist/bend/taper**;
   - **displace** (procedural noise for rocks, bark), **round** (soften edges).
   Evaluated with numpy on an adaptive grid (an octree around the surface, not a full cube) so big assets stay fast.
2. **Mesher:** dual contouring on that octree. It uses the analytic gradient for exact normals and keeps sharp edges
   where the style wants them (a crate's corners); surface nets where everything is soft. Resolution comes from the
   style profile and the asset's size class.
3. **Colour and materials:**
   - Each triangle belongs to the part nearest to it. Seams between parts get split *on the surface* (vertices on the
     iso-line between two parts), so colour borders are clean lines, not jagged vertex-colour steps (the spike's flaw).
   - Materials = style presets (roughness/metal/emission/sss-ish) × palette colours. Output either one glTF
     material per (preset, colour), or one **palette atlas** texture + UVs into its cells (one draw call; recolour the
     whole game by editing the palette). Default: atlas.
4. **Decals and patterns:** a part may carry `pattern:` (stripes, checker, dots, noise; all procedural, palette
   colours) or `decal:` (a PAGAN sprite projected along an axis). These need UVs: triplanar or projected UVs per
   part, baked into a small per-asset texture at the style's texel density.
5. **Decimation** to the size-class triangle budget, preserving part borders, sharp edges and the silhouette.
   LOD1/LOD2 from the same pass.
6. **Normals:** smooth (soft styles) or flat/faceted (low-poly styles), from the style profile.
7. **Export:** glb via PAGAN's deterministic writer: nodes per part (when rigged or when the game needs part nodes),
   skins, animations, extras/metadata.

---

## 5. Source formats (the KILN notation)

### 5.1 Style profile — `styles/<name>.style.toml` (+ STYLE.md)

A project uses one style (or a few: e.g. `characters` and `world`). KILN ships presets, and the agent can make new
ones from **inspiration images** the owner drops in `styles/<name>/inspiration/`. Claude reads images: it describes
the look, proposes a profile, then shows `kiln preview --vs-inspiration` sheets until the owner agrees.

```toml
# styles/soft_toy.style.toml : the Dear Passengers family (LOOSE! uses this)
[shape]
smooth = true              # smooth normals (false = faceted low-poly)
resolution = 0.008         # metres per field cell for a 1 m object (finer = rounder)
edge_round = 0.02          # default rounding of edges (m); 0 = sharp
blend = 0.04               # default blend radius between touching parts
[proportions]              # guidance the skill and lint use (W3xx), not hard rules
head_to_body = 0.6         # big heads
eyes = "large"             # googly, white sclera + black pupil
[materials]                # presets × palette colours
plastic = { roughness = 0.45 }
fabric  = { roughness = 0.85 }
metal   = { roughness = 0.35, metallic = 1.0 }
glow    = { emission = 2.0 }
[budgets]                  # triangles per size class
prop = 3000; character = 8000; building = 20000; hero = 20000
[look]                     # Godot look kit (§9.3): half the style is lighting
shader = "standard"        # standard (stylised PBR) | toon (ramp) | unshaded
outline = false
tonemapper = "filmic"; exposure = 1.1; ssao = true; glow = true; saturation = 1.15
sky = { top = "#4f8fe0", horizon = "#bcd7f2" }
sun = { pitch = -50, yaw = 35, energy = 1.3, shadows = true }
```

**Shipped presets** (each with a demo scene):
- `soft_toy`: Dear Passengers, Fall Guys.
- `low_poly`: faceted, flat colours, coarse resolution, flat normals (Kenney / Monument Valley family).
- `toon`: cel ramp + outlines (Zelda Wind Waker family).
- `clay`: matte, slightly lumpy displacement, soft light.
- `diorama`: tilt-shift, saturated, small worlds.

Inspiration is reference only: KILN never copies another game's assets or characters, and the skill refuses
likenesses of real people.

### 5.2 Model — `models/<name>.kiln.yaml`

```yaml
name: pilot
description: bean crew member, pilot uniform
class: character               # size class: budget, line-up group
style: soft_toy                # optional; project default otherwise
palette: crew                  # PAGAN palette; colours are keys or names
status: draft
units: m                       # +Y up, front +Z, origin at the feet (manifest-documented)

parts:
  - capsule: { from: [0, 0.3, 0], to: [0, 0.75, 0], radius: 0.3 }
    id: body
    color: red                 # palette key/name
    material: plastic
  - capsule: { from: [0.12, 0.05, 0], to: [0.12, 0.25, 0], radius: 0.1 }
    id: leg_l
    mirror: x                  # -> leg_r (mirrored ids get _l/_r)
    blend: 0.05                # smooth join with what's before it
  - sphere: { at: [0.1, 0.84, 0.23], radius: 0.1 }
    id: eye_l
    mirror: x
    color: white
    blend: 0                   # crisp seam
  - cylinder: { at: [0, 1.07, 0], radius: 0.25, height: 0.14, round: 0.03 }
    id: cap
    color: navy
  - box: { at: [0, 0.55, 0.29], size: [0.09, 0.22, 0.05], round: 0.015 }
    id: tie
    color: navy
    decal: { sprite: ui/airline_logo, axis: z }   # a PAGAN sprite, projected
  - box: { at: [0, 0.9, 0.3], size: [0.48, 0.12, 0.24] }
    cut: true                   # removes material (visor slit)

rig:                            # as PAGAN: pivots, parents, meta; plus skinning
  leg_l: { pivot: [0.12, 0.25, 0], parent: body }
  eye_l: { parent: body, meta: { hitzone: eye } }
  cap:   { parent: body, meta: { detachable: true } }
skin: soft                      # rigid (part = bone) | soft (blended weights from the field, §7)

animations:
  walk: { fps: 12, loop: true, cycle: { type: waddle, stride: 0.15 } }   # procedural cycle
  wave:                          # or explicit poses, as in PAGAN
    fps: 8
    poses: [ {}, { arm_r: { roll: -60 } }, { arm_r: { roll: -80 } } ]

variants:
  copilot: { swap: { red: green } }
lod: [8000, 3000, 800]
lint: { disable: [W301] }
```

Helpers for repetitive structures live in `kiln.api` (Python, as `pagan.api`): `fence(length, posts)`,
`stairs(steps)`, `crowd(base, n, seed)` (passenger variants), `castle_wall(length, crenels)`. The agent writes a
generator script, and the result is a plain `.kiln.yaml` the tool lints like any other.

### 5.3 Patterns and decals

`pattern: { type: stripes | checker | dots | flowers | noise, colors: [a, b], scale: 0.05, axis: y }` on any part.
`decal: { sprite: <PAGAN asset>, axis: z, size: 0.1 }`. PAGAN builds the sprite and KILN projects it. Baked into a
per-asset texture at `[texture] density`; models without patterns or decals need no texture at all, only the palette
atlas.

### 5.4 Project — `kiln.toml`

`default_style`, `default_palette`, `output_dir` (inside the Godot project), `export = ["glb", "godot"]`,
`[lint] disable`, `[sources]` (CC0 pack mirrors, M8), `style_version`, as in pagan.toml. Every setting is in a
registry with `kiln config show/get/set`, as in PAGAN.

---

## 6. Quality targets (from the spike's flaws)

| Spike flaw | Fix | Test |
|---|---|---|
| Jagged colour borders | Split triangles along the iso-line between parts' fields; one material/atlas cell per part colour | Every border edge lies on the part-boundary iso-line within ε |
| 60–130k triangles | Quadric decimation to the class budget, border/silhouette-preserving | Budget met; Hausdorff distance < 1% of size |
| Round-only edges | Dual contouring with gradient data + `round: 0` for sharp corners | A box exports as 12 triangles (+ bevel ring when rounded) |
| Lighting too bright | Look kit per style, previewed with exposure/histogram stats | Mean luminance and clipping % in the preview JSON |
| Modelling mistakes (hidden eyes) | Previews + lint: W3xx "part fully inside another" (as PAGAN's W013), "eye not visible from the front" | Fixture models |

---

## 7. Rigs, skinning, animation

- **Bones = rig entries** (part pivots and parents, as in PAGAN). `rig` children follow parents.
- **Skinning from the field:** a vertex's weight for bone *b* = softmax over the parts' distance values near it.
  Smoothly blended joints (a leg melting into a bean body) therefore bend smoothly: no auto-weight guesswork, because
  KILN knows which part every point came from. `skin: rigid` = one bone per part (props, robots, siege engines).
- **Animations:**
  - explicit poses (PAGAN's notation: offset, roll/pitch/yaw, about, show/hide, linear/step);
  - **procedural cycles** with a few parameters: `walk`, `waddle`, `hop`, `idle_breathe`, `bob`, `spin`, `swing`,
    `recoil`, so an agent gets good motion without keyframing.
- **Humanoids that should share animation libraries** (CC0 KayKit/Quaternius clips): `rig: humanoid` maps the parts
  to Godot's `SkeletonProfileHumanoid` bone names, so Godot's retargeting can use those libraries. Later (M7b).

---

## 8. CC0 packs (optional, free, unified)

For things text does badly (dense foliage, realistic rocks, detailed props) or to move faster:
- **Sources:**
  - `kiln pack add kenney/castle-kit` (mirrored once, offline index with thumbnails);
  - KayKit, Quaternius;
  - textures/HDRIs from ambientCG and Poly Haven.
- **Licences:** whitelist CC0 / CC-BY; lockfile with hash + licence + author; auto `CREDITS.md`.
- **Unify:** re-colour pack materials to the palette (OKLab nearest), apply style presets and the look kit, scale to
  the mannequin. Python only for glb packs. Blender optional (`kiln[blender]`) for FBX/blend packs.
- **Never:** Synty (EULA bans AI use), Objaverse-XL, Thingiverse, scraping Mixamo or itch.io.

---

## 9. Build, export, previews

### 9.1 Outputs

- `models/<name>.glb` (+ variants)
- `kiln_palette.png` (atlas)
- per-asset pattern textures
- Godot `.tscn` (materials applied) and shared material `.tres`
- the look kit
- `manifest.json`: nodes, pivots, AABBs in metres, meta, animations, LODs, triangles, licences
- `CREDITS.md`

Byte-identical rebuilds, stale-file cleanup and `--verify-godot`, as in PAGAN.

### 9.2 Previews (Godot, with the style's look kit)

- `turntable` (8 headings × 3 elevations);
- `lineup` (beside a 1 m mannequin and the class's approved assets: catches scale and style drift);
- `closeup <part>`;
- `pose <anim>` (filmstrip);
- `gallery`;
- `--vs-inspiration` (the asset beside the style's inspiration images);
- `--flaws` (seams, thin parts, hidden parts highlighted).

JSON: triangles, bounds, part visibility, luminance stats.

### 9.3 Look kit

`kiln_environment.tres` + `kiln_sun.tscn` (+ outline/toon shaders for those styles). The game instances it once.
Previews use it, so review = game.

---

## 10. Commands

`kiln init [--style soft_toy]` · `kiln new model <name> --class character` · `kiln lint` · `kiln build
[--verify-godot]` · `kiln preview <model> [--turntable|--lineup|--closeup P|--pose A|--vs-inspiration]` ·
`kiln gallery` · `kiln style new <name> --from-inspiration <dir>` · `kiln style show` · `kiln status` ·
`kiln mark` · `kiln style bump` · `kiln pack add/search` (M8) · `kiln credits` · `kiln config` · `kiln mcp` ·
`kiln skill install`. Every command takes `--json` and exits non-zero on error.

---

## 11. Milestones

### M0: Spike v2 — done 2026-10-20 (go). Was: go/no-go on quality

- Fix the spike's four flaws in throwaway code: clean seams, decimation, sharp edges, look kit.
- Make three looks from the **same** model text: soft_toy, low_poly, toon.
- Make the LOOSE! test set in soft_toy:
  - a knight;
  - a bean archer;
  - a trebuchet (hard-surface + rope);
  - a castle wall segment;
  - a tree (a CC0 pack or `displace` noise).
- One Godot shot per style. **Owner decides:** continue / adjust / stop.

### M1: Scaffolding

Repo, CI, config registry, findings, PAGAN dependency, notation loader (line-tracked), `kiln lint` (E-rules).

### M2: Field + mesher

SDF primitives and operations, octree evaluation, dual contouring, part ownership and seam splitting. Determinism
tests (byte-identical), a watertightness test, a performance target (a 1 m character < 2 s, a 10 m building < 10 s).

### M3: Materials, decimation, export

Presets × palette, atlas, quadric decimation + LODs, glb (via pagan.gltf), Godot `.tscn`/`.tres`, manifest,
`--verify-godot`.

### M4: Styles and previews

Style profiles + the five presets, look kit, Godot turntable/lineup/closeup/gallery, `--vs-inspiration`,
`style new --from-inspiration`.

### M5: Rigs and animation

Bones from rig, field skinning, poses, procedural cycles, glTF skins/animations, Godot verification.

### M6: Patterns and decals

Procedural patterns, PAGAN decals, UV projection + bake.

### M7: Skill, MCP, `kiln.api`, long-term management

Skill (workflow: brief → style → model → preview → fix → approve), reference, MCP server, `status`/`mark`/
`style bump`, `kiln.api` helpers.

### M7b: Humanoid retargeting

`rig: humanoid` → SkeletonProfileHumanoid; CC0 animation libraries.

### M8: CC0 packs

Mirror/index/search, licence lock, unify (Python for glb; `kiln[blender]` for FBX/blend).

### Later (don't start unless asked)

- Terrain (heightfield SDF + texture splats).
- Foliage scattering.
- Free local image-to-3D (only if a model with a UK-commercial-OK licence runs on 6 GB).
- Other engines.

---

## 12. Example project (tests keep it valid)

`examples/demo/`: the spike's five assets done properly, in two styles (soft_toy + low_poly), plus one CC0 pack
item unified into each. `examples/godot/` shows them under each look kit. CI: byte-identical build, Godot verify, a
headless scene check, renders under xvfb.

---

## 13. Questions for the owner (defaults used until answered)

1. **Name:** KILN (Keyed Implicit Language & Notation)? *(default: yes)*
2. **Spike v2 first** (2–3 days, §11 M0), with the go/no-go on its pictures? *(default: yes)*
3. **Shipped style presets:** soft_toy, low_poly, toon, clay, diorama? *(default: yes; soft_toy and low_poly first)*
4. **LOOSE!** = soft_toy (the Dear Passengers family), medieval? *(default: yes)*
5. **CC0 packs** as an optional source for foliage/rocks? *(default: yes, M8; text-only until then)*
6. **Repo:** `lukasgolino/KILN`, MIT, depends on `pagan`? *(default: yes)*

---

## 14. Risks

- **Quality ceiling of text-made shapes:** good for stylised and simple, weak for organic detail (hands with
  fingers, faces with expressions, foliage). Mitigations:
  - styles that suit it (big simple shapes are a choice, not a limitation);
  - CC0 packs for the rest;
  - M0 tests it on LOOSE!'s hardest assets.
- **Agent modelling skill:** Claude places primitives well but misjudges proportions without looking. Mitigations:
  - previews every iteration;
  - line-ups against the mannequin;
  - proportion guidance in the style;
  - lint for hidden or floating parts.
  (In the spike, the visor mistake showed up in the first render.)
- **Meshing/decimation effort:** dual contouring with sharp features and a deterministic quadric decimator are the
  two hard pieces (about 1–2 weeks). Fallbacks: marching cubes + `fast-simplification` if determinism holds.
- **Performance:** dense fields are O(n³). Mitigations: an octree around the surface, per-part bounding boxes,
  numpy vectorisation.
- **Skinning quality** at blended joints: field-based weights are novel. Test them on the bean walk cycle in M5
  before promising humanoids.
- **Style drift across a game:** one style file, one look kit, line-ups, `style_version` + `style bump`, as in PAGAN.
- **Legal:** none from generators (there are none). CC-BY credits are automatic. Inspiration images stay local
  reference and are never shipped or copied.
