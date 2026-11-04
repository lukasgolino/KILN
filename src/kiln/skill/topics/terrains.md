# Terrains

Terrains: height shapes, splats, chunked LOD meshes.

## Terrains

A model with `terrain:` instead of `parts:` is a heightfield (one height per x, z) with up to four splat layers of
palette colours: ground for a level. Only `name`, `description`, `tags`, `status`, `style_version`, `class` (default
`terrain`), `style`, `palette` and `lint` go with it. The map is centred on the origin (x and z from -size/2 to
+size/2), heights in metres. Design point: 256 x 256 m at 0.5 m cells (builds in ~2 s, ~120 MB).

```yaml
name: valley
terrain:
  size: [256, 256]           # metres [x, z] (or one number); a whole number of cells and of chunks
  cell: 0.5                  # grid spacing (m); up to 2048 x 2048 cells
  chunk: 32                  # mesh tile size (m): a whole number of cell x 2^(number of LODs), at most 250 cells
  lod: [64, 160]             # camera distances (m) where LOD 1, 2, ... take over (each halves the grid); [] = none
  skirt: 1.5                 # optional: how far chunk edges hang down (default: from the LODs' height error)
  collision: 1               # HeightMapShape3D sample every 1, 2, 4 or 8 cells; false = none
  seed: 3                    # noise seed; base: 0 (the height everything starts from)
  shapes:                    # applied in order to the running height H
    - noise: { scale: 70, height: 3, octaves: 5 }     # roughness: 0.5, ridged: false, seed: 0 (added to the terrain's)
    - hill: { at: [-70, -50], radius: 55, height: 22 }  # radius m or [x, z] (an oval), rotate: degrees
    - ridge: { points: [[-128, 90], [0, 100], [128, 80]], width: 35, height: 20 }   # a smooth curve through the points
    - plateau: { at: [70, -55], radius: 26, edge: 10, height: 14, blend: max, smooth: 3 }   # flat top, sloping rim
    - hill: { at: [40, 35], radius: 28, height: 5, blend: subtract }  # a hollow
    - path: { points: [[-128, 10], [0, 0], [128, 5]], width: 5, edge: 5, depth: 0.25 }  # smooth: 12 (m along it)
  splat:                     # 1-4 layers; the first is everywhere, each later one painted over where its rules hold
    - grass: { color: grass }
    - dirt: { color: dirt, path: { within: 3.5, fade: 1.5 }, noise: { scale: 6, cover: 0.85 } }
    - rock: { color: rock, slope: { above: 28, fade: 6 } }
    - sand: { color: sand, height: { below: -1.5, fade: 1 } }
```

Each shape has a weight p (1 at its core, a smooth falloff to 0 at its edge: a hill's radius, a ridge's `width` from
its line, a plateau's `edge` past its radius) and a `blend`: `add` (default; H += height x p), `subtract`, `max` /
`min` (raise / lower towards the level `height`; `smooth`: m of crease rounding) or `set` (to the level). Noise only
adds or subtracts (about +-height). A path flattens a band (`width`, banks `edge`) to the ground's own height smoothed
along it (`smooth` m), sunk by `depth`: roads that cut through hills and bridge dips. Layer rules multiply:
`slope: { above, below, fade }` degrees, `height: { above, below, fade }` metres, `path: { within, fade }` metres from a
path's centre line, `noise: { scale, cover (0-1), fade, seed }` patches; `strength` (0-1) caps the layer.

Output: `models/<name>.glb` (LOD 0) and `.lod<k>.glb`: a root node with `chunk_<ix>_<iz>` nodes at the chunks'
centres, each a regular grid mesh (POSITION, NORMAL, COLOR_0 = the blended colours, TEXCOORD_0 = the splat map) with a
skirt; `models/<name>.splat.png` (one pixel per grid point, top = -z; R, G, B = layers 2-4, layer 1 = the rest); with
"godot", `models/<name>.tscn`: the LOD glbs (each chunk shown between its LOD's distances, 4 m overlap), a splat shader
blending the palette colours (the style's toon bands if it has them) and a StaticBody3D with a HeightMapShape3D
(inline, scaled by the sample spacing). Godot imports the chunk glbs without its own LODs. Manifest: the usual fields
plus `terrain` (`size`, `cell`, `samples`, `chunk`, `chunks`, `lod_distances`, `skirt`, `height_range`, `splat`,
`layers` with `channel`, `collision` (`samples`, `spacing`), `probes`: [x, z, height] points `--verify-godot` checks
the collision at). `kiln preview <terrain>`: from above (splat colours, lit) and from four sides. Lint: W116 a layer
covers < 0.5% of the map, W117 a shape is off the map.

Tools (foliage scattering, props on the ground) read the heightfield in Python:
`kiln.terrain.load(project, "valley")` -> `Heightfield` with `height(x, z)`, `normal(x, z)`, `slope(x, z)` (degrees),
`splat(x, z)` (weights in `layer_names` order), `distance_to_path(x, z)`, `distance(points)` (y - height: the
heightfield as a distance field) and `bounds()`; arrays in, arrays out, bilinear between grid points.
