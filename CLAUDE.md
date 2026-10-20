# CLAUDE.md

KILN (Keyed Implicit Language & Notation) is a standalone Python CLI/library that turns text models
(`.kiln.yaml`: signed-distance-field parts that blend like clay) into smooth stylised 3D game assets: meshes,
paint, rigs, animations, glTF and Godot scenes. It is PAGAN's 3D sibling (PAGAN = pixel art as text) and copies
PAGAN's workflow and conventions. Read [PLAN.md](PLAN.md) for the brief and design.

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
  - `builder.py` model -> `Built` with a pickle cache in `.kiln-cache/`; `importer.py` CC0 .glb/.gltf imports;
  - `lint.py` E/W rules; `build.py` `kiln build` (glb, variants, LODs, Godot, manifest, credits, stale cleanup);
  - `render.py` vectorised software renderer; `preview.py` sheets (turntable, closeup, filmstrip, lineup, gallery, vs);
  - `godot.py` model scenes, look kits, headless verify, engine renders; `templates/` Godot scripts, init files;
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
- Commit only when the owner authorizes (milestones), as plain git under the owner's identity. NEVER add AI
  attribution. Push only when asked; ask before tags.
- Versioning as PAGAN: bump `version` in pyproject.toml, CHANGELOG entry (Keep a Changelog), tag `vX.Y.Z` for any
  change to the notation, settings, manifest/exporter output or meshes.
- Dependencies: numpy, Pillow, PyYAML, fast-simplification (PAGAN is vendored, not a dependency); extra `mcp`. Others only if needed:
  log why below.

## Decisions log

- 2026-10-20: KILN exists because PAGAN's voxel meshes didn't give the smooth "normal 3D" look (owner; PAGAN 3D
  frozen at v0.9.0). Free only: Claude (Max) writes text, KILN builds it; no paid generators (owner rejected Tripo).
- 2026-10-20: Signed distance fields with smooth unions: shapes an LLM can place well, joints that look sculpted.
  Spike v1/v2 (spike/) showed the Dear Passengers family is reachable; owner: "much better, let's make that".
- 2026-10-20: No Blender in the core (owner: optional). Meshing is dual contouring in numpy (sharp corners where
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
- 2026-10-20: Styles are chosen per game (owner: "I want to choose inspirations"); presets soft_toy, low_poly, toon,
  clay, diorama; project styles `extends` a preset; inspiration images in styles/<name>/inspiration/.
- 2026-10-20: Decimation keeps colour borders (owner: "weird artifacts, jagged edges"): paint groups and patterns
  are cut at full resolution, borders thinned (BORDER_TOLERANCE) and locked through fast-simplification's
  preserve_border, then welded via its collapse replay. The replay's own positions are wrong for some vertices
  (0.2.0), so only its index mapping is used. Afterwards bad faces (tilted > 25 degrees or slivers) are relaxed
  along the surface; crease vertices within one part stay. Border corners take per-side face-normal averages.
- 2026-10-20: LOOSE report items 1-16 (owner: "fix them all"). PAGAN is vendored into `kiln.vendor` (v0.9.0 copies of
  findings, yamlio, palette, color, gltf): a git dependency can't take a version range, and games pin their own PAGAN.
  Keep the palette format in step by hand. Families copy PAGAN's template/extends/remove. `separate` parts are their
  own pieces (`Field.only`: same part indices, only some adding parts form the surface). Godot checks run in a sandbox
  project (copy of output_dir + minimal project.godot with the host's renderer). Lint builds in a forkserver pool.
- 2026-10-20: Meshing order (found on LOOSE's 44 models): DC at full detail -> free decimation to PRESHAPE x budget
  (shape-driven; locked borders from full detail starved shapes: hexagonal wheels, flattened boots) -> cut colour
  regions -> alternate border thinning and border-locked decimation -> relax bad faces. Thin parts (< PROTECT x the
  budget's edge length) get their own region. Lint workers are limited by free memory (WORKER_MEMORY).
