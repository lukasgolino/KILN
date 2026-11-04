# Scatters

Scatters: foliage and props over a terrain or model.

## Scatters

A model with `scatter:` instead of `parts:` places other models many times over a surface: grass, flowers, rocks and
trees on a terrain, moss on a boulder, pebbles on a flat area. Only `name`, `description`, `tags`, `status`,
`style_version`, `class` (default `scatter`), `style`, `palette` and `lint` go with it. KILN rolls every instance at
build time (Python's `random.Random`, one stream per `place` entry: stable across machines, and editing one entry leaves
the others where they were).

```yaml
name: meadow
scatter:
  onto: valley               # a terrain, another model (its top surface, seen from above) or flat (needs size)
  size: [64, 64]             # optional: the area [x, z] in metres (or one number), centred on the origin;
                             # default: the whole terrain / the model's footprint
  seed: 7
  chunk: 32                  # instances are grouped in cells this size (one MultiMesh each: culling, LODs)
  place:                     # in order: later entries keep their distance from earlier ones (spacing)
    - model: tree            # a model, name.variant, or a list picked evenly: [flower, flower.pink]
      density: 0.003         # candidates per m^2 of area (seen from above), before rules and spacing
      spacing: 9             # at least this far (m) from every instance placed before (the larger spacing of the two)
      scale: [0.8, 1.3]      # a factor or [lo, hi]
      rotate: 360            # yaw jitter in degrees (360 = any way round, the default; 0 = none; or [lo, hi])
      tilt: 5                # a random lean up to this many degrees
      align: 0               # 0 upright .. 1 up along the surface's normal
      sink: 0.15             # metres into the surface (hides bases on slopes)
      tint: { color: sand, amount: 0.4, shade: 0.15 }  # or a number: shade only
      slope: { below: 22 }   # degrees, { above, below, fade } as terrain splats
      height: { above: 0 }   # metres
      noise: { scale: 20, cover: 0.6 }   # patches (clumps of flowers)
      splat: grass           # a terrain's layer (or a list): kept as often as their summed weight there
      path: { beyond: 6 }    # a terrain's paths: away from (beyond) or near (within) their centre lines, m
      lod: [70]              # camera distances where the model's lod1, lod2, ... take over (needs its lod: budgets)
      visible: 120           # hidden beyond this camera distance (m); 0 = always
```

How it places: `density` x the area candidates, uniform over the area; a candidate is dropped where there's no surface
(off a model, or under an overhang), else kept with the probability its rules give (multiplied; each a smooth ramp
over its `fade`), then dropped if it is closer than `spacing` to an instance placed before it (entries with spacing 0
skip that check). An instance stands its model's origin (its feet) on the surface, `sink` lower; it leans `align` of
the way to the surface's normal, then by a random `tilt`, turns by `rotate` about its up and is scaled. `tint` makes
an instance colour (linear RGB) that multiplies the model's colours: white leaning towards `color` by up to `amount`,
darkened by up to `shade`. Scatter models made of one mesh (no rig, no skin); keep their budgets small (grass ~100
triangles, trees ~1500 with a `lod:`).

The scatter's frame is the surface's: a terrain's map, a model's exported frame (its glb's: model space minus its
`origin`), or a flat area centred on the origin at y = 0. Put the scatter scene under the terrain or model.

Output: `models/<name>.scatter.json`: `format`, `seed`, `onto` (`kind`: flat, terrain or model; `model`), `area`
(`min`, `max` x, z), `chunk` and `groups`, one per entry and model (`node`, `place`, `model`, `variant`, `glb`, `lods`,
`godot_scene`, `count`, `lod_distances`, `visible`, `chunks` (`node`, `first`, `count`: ranges of `instances`),
`instances` (each `[x, y, z, ax, ay, az, bx, by, bz, cx, cy, cz]`: the model's origin and its x, y, z axes, scale
included) and, with a tint, `colors` (linear RGB per instance)). With "godot", `models/<name>.tscn`: a Node3D per group
holding a `MultiMeshInstance3D` per chunk (transforms and colours inline); its inline script gives each MultiMesh the
model's mesh with the materials the model's own scene sets up (the style's look; tinted groups let instance colours
through: `vertex_color_use_as_albedo`, the toon shader's COLOR), adds `<chunk>_lod<k>` copies with the model's LOD glbs
and sets the visibility ranges (2 m overlap). Manifest: `class`, `style`, `scatter` (the JSON), `onto`, `instances`
(per group), `godot_scene`; no `glb`. `--verify-godot` checks every chunk and LOD against the JSON (instance counts,
each transform times where the mesh sits in its model, colours, materials, distances). `kiln preview <scatter>`: from
above, from two sides and close up where the most instances are (the whole-area views draw every n-th instance of the
costliest groups beyond 200 000 triangles). Lint: E015 (an unknown or unsuitable model or variant, more `lod`
distances than the model has LODs, `splat`/`path` without a terrain, an unknown layer, more than 1 000 000 candidates
in an entry or 200 000 instances in a scatter), W118 an entry places more than 50 000 instances, W119 an entry places
none.
