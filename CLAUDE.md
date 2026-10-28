# CLAUDE.md

KILN (Keyed Implicit Language & Notation) is a standalone Python CLI/library that turns text models
(`.kiln.yaml`: signed-distance-field parts that blend like clay) into smooth stylised 3D game assets: meshes,
paint, rigs, animations, glTF and Godot scenes. It is PAGAN's 3D sibling (PAGAN = pixel art as text) and copies
PAGAN's workflow and conventions. The design is in the decisions log below and the notation in
`src/kiln/skill/reference.md`. Bugs and feature requests live in GitHub issues (label `later`: tracked, not planned
until requested), never in markdown files in the repo.

## Setup and commands

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
kiln --version
mypy          # strict
pytest        # GODOT=/path/to/godot for the Godot tests; a display (or xvfb) for engine renders
```

Demo: `cd examples/demo && kiln build --verify-godot` builds into `examples/godot/assets/kiln`;
`godot --path examples/godot` runs the showcase. Commit the regenerated output after changing demo models or
anything that changes output.

## Layout

- `src/kiln/`:
  - `sdf.py` shapes (distance functions), transforms, copies, noise, the combined `Field`;
  - `notation.py` `.kiln.yaml` parsing/validation -> `Model` (parts, rig, animations, variants, imports);
  - `style.py` style profiles (`styles/*.style.toml` presets: soft_toy, low_poly, toon, clay, diorama);
  - `project.py` `kiln.toml`, palettes (PAGAN format), loading models with their style;
  - `mesher.py` sparse sampling + dual contouring + decimation (fast-simplification) + surface projection;
  - `paint.py` part ownership with clean borders (triangle splitting), patterns (refined first), decals, normals;
  - `rig.py` skeleton from part ids, soft weights from the field, poses and procedural cycles, skinning maths;
  - `export.py` glTF writer (via `kiln.vendor.gltf.Document`); `vendor/` PAGAN pieces (palette, findings, YAML, colour, glTF); `gltf_check.py` reading/validation (incl. skins);
  - `builder.py` model -> `Built` with a pickle cache in `.kiln-cache/`; `importer.py` CC0 .glb/.gltf imports; `blender.py` optional .fbx/.blend/.obj -> glb via the `blender` binary;
  - `lint.py` E/W rules; `build.py` `kiln build` (glb, variants, LODs, Godot, manifest, credits, stale cleanup);
  - `render.py` vectorised software renderer; `preview.py` sheets (turntable, closeup, filmstrip, lineup, gallery, vs);
  - `godot.py` model scenes, look kits, headless verify, engine renders; `templates/` Godot scripts, init files;
  - `fonttext.py` font glyphs as SVG path data; `fillrule.py` nonzero fill (overlapping glyph contours joined);
  - `cli.py`, `mcp_server.py`, `api.py` (generator scripts), `skill/` (SKILL.md + reference.md).
- `examples/demo/` the demo project; `examples/godot/` the Godot project it builds into (showcase scene + CI check).
- `spike/` the throwaway spikes that justified the design (kept for reference; not part of the package).

## Conventions

- Python 3.11+, type hints everywhere (mypy strict), small modules, every feature lands with tests.
- Deterministic output: the same inputs give byte-identical files on one machine (tested). Across machines float
  libraries may differ, so CI checks build-twice equality, not equality with committed output.
- CLI: human output by default, `--json` for machines, non-zero exit on errors. Findings (rule id, file, line,
  `where`, a message that says how to fix it), collected rather than stopping at the first (PAGAN's `Finding`).
- Units: metres, +Y up, front +Z, models stand on y = 0. Colours from PAGAN palettes by name.
- Commit only when authorized (milestones), as plain git under our identity. NEVER add AI
  attribution. Push only when asked; ask before tags.
- Versioning as PAGAN: bump `version` in pyproject.toml, CHANGELOG entry (Keep a Changelog), tag `vX.Y.Z` for any
  change to the notation, settings, manifest/exporter output or meshes.
- Dependencies: numpy, Pillow, PyYAML, fast-simplification, fonttools (font text for extrudes; approved 2026-10-21) (PAGAN is vendored, not a dependency); extra `mcp`. Others only if needed:
  log why below.

## Decisions log

- 2026-10-20: KILN exists because PAGAN's voxel meshes didn't give the smooth "normal 3D" look (decided; PAGAN 3D
  frozen at v0.9.0). Free only: Claude (Max) writes text, KILN builds it; no paid generators (Tripo rejected).
- 2026-10-20: Signed distance fields with smooth unions: shapes an LLM can place well, joints that look sculpted.
  Spike v1/v2 (spike/) showed the Dear Passengers family is reachable; verdict: "much better, let's make that".
- 2026-10-20: No Blender in the core (optional at most). Meshing is dual contouring in numpy (sharp corners where
  shapes have them), decimation is fast-simplification (MIT, quadric), output via PAGAN's deterministic glb writer.
- 2026-10-20: Colour borders are cut into the mesh along where two parts' distances are equal (and along pattern
  zero lines, after local refinement): crisp borders without textures. Decals are the only textures.
- 2026-10-20: Soft skins weight each bone by a softmax of its parts' distances (temperature from the blend radius):
  blended joints bend where they blend. `separate: true` keeps detachables rigid.
- 2026-10-20: Previews use a vectorised software renderer (no GPU/display, ~0.15 s per view) that follows the
  style's look kit; `--engine` renders through Godot for the exact look.
- 2026-10-20: Godot scenes keep shaders and the material script as sub-resources inside the .tscn (no .gdshader/.gd
  files, whose .uid sidecars would make output non-deterministic, as found in PAGAN). Godot's text format writes
  Transform3D bases row-major.
- 2026-10-20: Styles are chosen per game ("we want to choose inspirations"); presets soft_toy, low_poly, toon,
  clay, diorama; project styles `extends` a preset; inspiration images in styles/<name>/inspiration/.
- 2026-10-20: Decimation keeps colour borders (after "weird artifacts, jagged edges"): paint groups and patterns
  are cut at full resolution, borders thinned (BORDER_TOLERANCE) and locked through fast-simplification's
  preserve_border, then welded via its collapse replay. The replay's own positions are wrong for some vertices
  (0.2.0), so only its index mapping is used. Afterwards bad faces (tilted > 25 degrees or slivers) are relaxed
  along the surface; crease vertices within one part stay. Border corners take per-side face-normal averages.
- 2026-10-20: LOOSE report items 1-16 (decided: fix them all). PAGAN is vendored into `kiln.vendor` (v0.9.0 copies of
  findings, yamlio, palette, color, gltf): a git dependency can't take a version range, and games pin their own PAGAN.
  Keep the palette format in step by hand. Families copy PAGAN's template/extends/remove. `separate` parts are their
  own pieces (`Field.only`: same part indices, only some adding parts form the surface). Godot checks run in a sandbox
  project (copy of output_dir + minimal project.godot with the host's renderer). Lint builds in a forkserver pool.
- 2026-10-20: Meshing order (found on LOOSE's 44 models): DC at full detail -> free decimation to PRESHAPE x budget
  (shape-driven; locked borders from full detail starved shapes: hexagonal wheels, flattened boots) -> cut colour
  regions -> alternate border thinning and border-locked decimation -> relax bad faces. Thin parts (< PROTECT x the
  budget's edge length) get their own region. Lint workers are limited by free memory (WORKER_MEMORY).
- 2026-10-21: CC0 parity (plan to match KayKit/Kenney; decided: do everything in there). Hard surface is a second, exact path:
  parts tessellated from their shape and combined with BSP CSG (csg.js algorithm) in pure Python, then coplanar
  fragments re-triangulated (holes bridged, straight points dropped only where every patch agrees) so it stays
  watertight. Hard parts aren't decimated; budget pressure lowers their detail (bevel -> chamfer -> none -> fewer sides).
- 2026-10-21: Cracks at colour borders came from split() cutting only the selected side of an edge (T-junctions); the
  neighbour is now split too. The smooth crease test uses half of sharp_angle (the field's normal on a crisp edge is
  the bisector) with a 15% inset sample.
- 2026-10-21: Kept parts (`keep`, or crisp parts < 2% of the model) are their own small meshes on a finer grid, sitting
  in the surface around them, so LODs never lose them. Hardware parts (rivets, band, planks, bolt, slit) expand into
  ordinary parts at parse time. Fitted shells (`fit`) are a wall around another part's distance field.
- 2026-10-21: Humanoids retarget CC0 clips (KayKit Rig_Medium) at build time: per joint, the clip's world-space change
  from its rest times the turn putting the KILN bone onto the clip's rest direction (so A-pose bodies play T-pose clips);
  hips move scaled by hip height. KayKit CC0 files are committed as test fixtures (tests/fixtures/kaykit, ~2 MB, approved).
- 2026-10-21: Attachments for CC0 characters fit a shell to the character's own mesh via an exact point-to-triangle
  distance over a cell grid (each triangle filed in every cell within one cell of it), exported in the bone's space.
- 2026-10-21: The template library lives in src/kiln/library (generated by tools/gen_library.py); `extends` takes a
  list; fitted shells are their own mesh pieces (meshed with what they wrap, the thin air gap tears both).
- 2026-10-21: LOOSE backlog 26-42. `origin` moves the glb root node (manifest stays model space + `origin`). UVs are
  projected per part in its local frame; TEXCOORD_0 unless the atlas/decals use it (then TEXCOORD_1). `attr` numbers
  go to custom `_NAME` attributes and the first to COLOR_0.a: Godot 4.7.2 drops custom attributes (verified).
  Polygon distance is tiled (exact; sign from the nearest edge/corner pseudo-normal, even-odd fallback for crossing
  outlines). Text is SVG `path:` on extrude, not fonts (fontTools would be a new dependency: needs approval). No glb
  quantization: Godot 4.7.2 doesn't support KHR_mesh_quantization or meshopt (checked).
- 2026-10-21: fonttools approved: extrude `text` + `font` (glyph outlines via SVGPathPen -> svgpath; no
  kerning/shaping). `effect:` (LOOSE #41, approved: "why not"): KILN only describes; `models/<name>.effect.json` holds
  every particle pre-rolled with Python's `random.Random(seed)` (stable across machines, unlike numpy streams) so the
  game's player and `preview --effect` match; closed-form motion with linear drag. LOOSE #35 (glb size) dropped.
- 2026-10-21: Scope (decided): KILN makes art and the data/glue a game needs to use it (glb, scenes, materials,
  manifest, effect JSON; small generated scripts like the .tscn material setup are fine). Game logic and runtime
  players stay in the game: no Godot effect player. `effect:` stays (LOOSE reskins on 0.7.0).
- 2026-10-21: Tracking moved to GitHub issues (decided): no PLAN.md / report / plan markdown files in the repo; label
  `later` = tracked, not planned until requested. 0.8.0 closes LOOSE report 44-58 (issues #1-#14).
- 2026-10-21: Hard CSG builds each BSP tree from the whole solid (a tree of only the polygons near the other solid
  misclassifies points: cracks, #2); only nearby polygons are clipped (~1.3x slower). The DC grid grows on any side
  the surface reaches (blends bulge out of part boxes, #11). merge_rigid (one skinned mesh for rigid skins, #9) is
  opt-in: games hide parts by node. Shared clips (#5) are an explicit carrier (`animations_only`) other models name
  (`animation_library`); Godot imports it as an AnimationLibrary. KILN writes Godot `.import` settings only for its
  palette textures and carriers, merging into what Godot wrote (idempotent builds, #14).
- 2026-10-21: #29: text extrudes fill nonzero (fonts' rule): when contours overlap, each outer contour minus its own
  holes becomes a thin prism, the prisms are unioned with the hard CSG and the union's top face gives the outlines
  (no polygon-clipping dependency). Non-overlapping outlines pass through unchanged; SVG `path:` stays even-odd.
  `font_axes` instances variable fonts with fontTools' instancer (overlaps kept, the fill handles them).
- 2026-10-25: #50: `union: per_bone` (model field, rigid skins only) meshes each bone's parts as their own piece (like
  `separate`), so rotated joints can't tear; a model field, not a kiln.toml one, because it changes the mesh (cache key)
  and non-merged rigid skins tear the same way. Opt-in: `whole` stays the default so existing meshes don't change.
- 2026-10-26: #25: dual contouring gives a cell one vertex per sheet (crossings paired around each cell face, the
  asymptotic decider on faces with four; a face both of whose cells would loop a sheet through it twice is read the
  other way), so walls and gaps thinner than a cell stay manifold. fast-simplification has no link-condition check:
  vertices it pinches are split per fan afterwards (`unpinch`; folded pockets that leaves are dropped) rather than
  locking areas and re-running (locked full-detail patches ate low budgets and cracked thin shells). Crossings are
  found on the surface (false position), not interpolated, and best-fit points may leave their cell by a step where
  they lie on the surface (sharp rims).
- 2026-10-28: #18: other engines get import notes only (`docs/engines.md`: Unity, Unreal, Bevy, three.js, Defold), no
  generated materials or prefabs: no game targets another engine yet, and generated setup would need that engine
  installed for a headless verify like `--verify-godot`. Outside Godot `atlas = true` is the recommended colour mode.
- 2026-10-28: #64: imported clips play on any skeleton through `skeleton: { map, root_motion }` (KILN bone -> clip joint,
  optional `child` aiming it). Humanoids run the same retarget with their table as the map (output byte-identical);
  they take no map. Without `root_motion` clips play in place (rotations only, the conservative default); an unmapped
  `root_motion` joint moves the bone mapped to its nearest mapped descendant. Mapped joints missing from a clip file
  are errors (a typo would leave a bone still), unlike humanoids' optional toes.
- 2026-10-28: #21: humanoid bone names for Godot are a `BoneMap` (SkeletonProfileHumanoid) in the glb's `.import`, not
  renamed glb bones (renaming for other engines only if one needs it). It is opt-in (`godot_bonemap`, kiln.toml: an
  import setting like the palette textures', no mesh change) because Godot then renames the imported bones and the
  skeleton node, breaking paths games already use. KILN edits only that key in `_subresources` (other settings and
  Godot's uid stay) and takes it out again when the flag goes off.
- 2026-10-28: #20: .fbx/.blend/.obj import through the `blender` binary as a subprocess (PATH or `BLENDER=`, any 4.x),
  not the `bpy` wheel (~300 MB, one Python per Blender release); imports only. Blender exports a glb that takes the
  normal glb path. `kiln import` writes it to `imports/<stem>.glb` so projects build without Blender; files named
  directly in a model convert into `.kiln-cache/blender/` keyed on source sha256 + Blender version + script version
  (4.2.3's glTF export is byte-stable run to run). Blender tests skip without it (CI).
