# Commands

Every command and its flags.

## Commands

`kiln init [dir] --style soft_toy` · `kiln new model <name> --template bean|prop|empty --class C` ·
`kiln lint [models]` · `kiln preview <model> [--closeup ID|NUMBER] [--pose ANIM [--frame N,N]] [--vs] [--detach] [--fit] [--effect [--at T,T,...]] [--engine] [--variant V] [--views front,34,side,back] [--pitch 5,30] [--size PX] [--draft] [--tight] [--frame-box X0,Y0,Z0,X1,Y1,Z1] [--fill] [--bg auto|light|dark]` ·
`kiln lineup [models] [--pitch DEG]` · `kiln gallery` · `kiln build [models] [--verify-godot] [--no-dependents]` (named models only, and the models placing them: the others keep their last output) · `kiln status` ·
`kiln mark <models> --approved|--draft [--current]` · `kiln style list|show|new|bump` ·
`kiln config show|get|set` · `kiln import <file> --licence L` (.glb/.gltf; .fbx/.blend/.obj with Blender 4.x) · `kiln pack list|add|search|import` · `kiln credits` · `kiln doctor` ·
`kiln docs [topic...] [--search words]` (these docs: list, print one, find paragraphs) · `kiln skill install` · `kiln mcp`. Every command takes `--json` (before or after the command). `--closeup` takes a part
id (`root` = parts without one) or a part's number in the file (`--closeup 3`).
Framing: `--tight` fits each tile to what it shows (flat props), `--frame-box` frames the sheets on a region (a scene's
corner; both: turntable and `--views` only), `lineup --pitch 60` looks down on flat props (no ground line past 10). `--fill` adds a neutral light from the
camera (previews only: the game has no such light), so faces seen from below read; `--bg auto` (turntable, views, closeups) is dark for dark skies.
`kiln preview <model> --vs <ref.glb|ref.gltf> [--ref-height METRES]`: the model against a reference mesh (a CC0
pack item, kept as it is: its own colours and normals) at one scale (same pixels per metre, both on y = 0, centred
on each other), in the style's lighting: `previews/<model>/vs_<ref>.png` with paired turntable rows (reference above
the model; from below, eye level, above), the top fifth (head region) close up, and the silhouette difference per
view, and both at gameplay distance (30 m and 60 m at a 60 degree vertical FOV on a 1080 px screen, the style's
outline if it has one, upscaled nearest; an orthographic render at that scale). `--ref-height` scales the reference to that height (default: its own units). Metrics (printed, and in `--json`
under `compare`): `iou` (mean silhouette IoU of 8 views: front, front-left, left, back-left at +10 degrees, front and
left at +50, top, below at -30; 1.0 = same outline), `iou_min`, `iou_views`, `triangle_ratio` (model / reference),
and for `model` and `reference`: `triangles`, `surfaces` (glTF primitives drawn = draw calls; for the model what
`kiln build` writes), `materials`, `colors` (distinct base colours on faces; a textured reference counts each face's
sampled colour), `facet_regularity` (share of surface area in triangles with an edge neighbour facing the same way
within 2 degrees: flat designed facets near 1, smooth or noisily decimated surfaces near 0), `open_edges` (cracks),
`size` (metres). For restyles (where proportions change on purpose):
`band_iou` (mean of `band_ious`: silhouette IoU per body band in 4 side views at 0 degrees, each band cropped, scaled to
one height and centred, so a big head on a short body still matches; `bands` = `humanoid` (`legs`/`torso`/`head` cut at
the hips and head joints: a `skeleton: humanoid` model against a reference with `head` and `hips` nodes) or `thirds`
(`bottom`/`middle`/`top`)), `mass` / `mass_ref` (visual mass: silhouette area / its bounding box, mean of the 8 views)
and `mass_ratio` (model / reference), `screen_px` (height in pixels at 30 m and 60 m, model and reference). All
deterministic. Without a path, `--vs` shows the style's inspiration images.
