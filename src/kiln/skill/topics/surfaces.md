# Surfaces

Hard surfaces (exact polygons), hardware (rivets, bands, planks, bolts, slits, garments), patterns, decals, textures,
cloth folds, relief fur, soft colour borders.

## Hard surface

Smooth parts are sampled from the distance field and reduced to the budget: soft clay-toy shapes. **Hard** parts are
made as exact polygons instead: designed facets, crisp creases, octagonal wheels, planks, beams, armour plates, the
hand-built low-poly look (Kenney, KayKit). A part is hard when it asks (`sides`, `chamfer`, `bevel`, `blend: none` or
`hard: true`), or always with a style's `hard_surface = "always"` (low_poly), except the body of a soft-skinned
character (its joints bend by blending) and parts with `twist` or `noise`. Hard parts join each other exactly
(union, cut, intersect, in order); every later cut or intersect, of any shape, applies to them too. They sit in
smooth parts without blending. A box's `round` is a chamfer on a hard part. Round hard shapes get the style's
`hard_sides` (12 by default; low_poly 8) unless they say `sides`. When hard parts would take most of the budget
(LODs), bevels become chamfers, then go, then round shapes lose sides. Flat faces stay flat; in smooth styles bevel
bands shade round and designed edges stay crisp.

```yaml
  - box: { at: [0, 0.3, 0], size: [0.6, 0.6, 0.6] }      # a crate
    color: wood
    chamfer: 0.03
  - cylinder: { at: [0.7, 0.26, 0.9], radius: 0.26, height: 0.1, sides: 8, rotate: [0, 0, 90] }   # a wheel
    color: wood_dark
```

## Hardware

Written like a shape, each stands for several ordinary parts (hard by default); the part's other fields (colour,
material, id, mirror, ...) go to each.

| hardware | meaning |
|---|---|
| `rivets: { count: 8, along: [[x, y, z], ...], size: 0.03 }` | rivets evenly along a path (model space, ends included); or `around: { center, radius, axis: y }` in a ring |
| `band: { fit: body, at: [0, 0.12, 0], width: 0.05, thickness: 0.012, axis: y }` | an iron band round an earlier part's surface at `at` (or `radius:` instead of `fit`): barrels, doors, posts |
| `planks: { size: [1, 2, 0.08], count: 5, gap: 0.015, axis: x, jitter: 0.05, seed: 1 }` | boards side by side along `axis` with gaps, chamfered; `jitter` shortens each by up to that share of its length (with `at`, `rotate`) |
| `bolt: { at: [x, y, z], radius: 0.02, length: 0.02 }` | a hex bolt head along y (rotate it) |
| `slit: { at: [x, y, z], size: [0.3, 0.04, 0.3] }` | a cut: visor and arrow slits |
| `garment: { fit: [chest, spine], from_y, to_y, hem, openings }` | a fitted layer of clothing round earlier parts, open at the hem and neck (`making` has the full field list and the rigged-character setup) |

## Patterns

```yaml
    pattern: { type: stripes, color: gold, size: 0.06, width: 0.3, axis: y }
    # several: a list, painted in order (each over the last); frame: part = axes and `at` in the part's own frame
    # (they follow rotate/aim): pattern: [{ type: stripes, ..., frame: part }, { type: band, ..., frame: part }]
```

- `stripes`: bands across `axis`, one every `size` metres, `width` = fraction in the second colour.
- `band`: one band of thickness `size` centred at `at` (one number: metres along `axis`, in model space): belts, trims,
  hat bands. E.g. `{ type: band, color: brown, size: 0.06, at: 0.4, axis: y }` = a belt 0.4 m above the ground.
- `checker`: checks `size` metres across.
- `dots`: dots on a grid `size` metres apart, diameter `width` x size; `jitter` (0-1: up to half that of a cell each
  way) and `vary` (size +-) at random (`seed`); `offset: [x, y, z]` shifts a repeat (a 2nd dots pattern moves itself).
- `pixel`: a pixel motif tiled round the part's own axis (a hat band, a hem, a cuff): `rows: ["#..#", ".##."]` (`.` or
  space bare, any other character painted; top row first) or `image: trims/key.png` (alpha over half painted, or with
  no transparency its dark pixels; up to 256x64). Each cell is `size` metres tall along `axis` (heights along the axis,
  not the slope: a shallow cone stretches them; a flat brim takes none), the band centred on `at` (from the part's
  centre: `frame: part` is the default here); `repeat` times round, or `auto` (the default: about square cells at the
  part's widest radius). It reads left to right seen from outside, like a cylindrical texture; a mirrored part reads
  mirrored. Near the axis (a cone's tip, a cap) columns too narrow aren't painted. One colour per pattern: list several
  for more. Smooth parts only (a hard part with one is an error). E.g. `{ type: pixel, color: gold, size: 0.02, at: -0.1,
  rows: [...] }`.

## Decals

```yaml
    decal: { image: decals/logo.png, axis: z, at: [0, 0.6, 0.3], size: [0.2, 0.1] }
```

Projects an image (PNG with transparency, e.g. made with PAGAN) onto the faces of this part that face `axis`
(x, -x, y, -y, z, -z), centred at `at` (model space, on or near the surface), `size` = width, height in metres. It
shows on that side only (a flag needs a second decal with `axis: -z` for its back). Transparent pixels show the part's colour.
Small images (<= 256 px) are sampled crisp (pixel art). `texel: 0.004` instead of `size`: metres per image pixel, so
props at different scales keep the same pixel size. On an arrayed part, `per_copy: true` puts the decal on every
copy, placed on each as written for the first (a badge on each of 12 links); the copies share one texture.

## Textures

```yaml
    texture: { image: textures/brushed.png, project: box, texel: 0.004 }                       # every face, from the side it faces
    texture: { image: textures/trim.png, project: cylindrical, at: [0, 0, 0], axis: y, size: [0.1, 0.05] }
```

Tiles an image over the whole part (a shirt print, pixel-art metal, a trim band), as one material. `box`: each face
takes it from the side it faces (its main normal direction, no blending), upright seen from there. `cylindrical`:
round `axis` through `at` (u = arc length: texels keep their size), caps taken flat; seam at -z for `axis: y`, -y
for x, -x for z (it shows unless the circumference is whole tiles). `at`: the part's centre by default. Cylindrical
can't follow `mirror`/`array` copies: use `mirror_id` or `box`. Tile: `size: [w, h]` metres or `texel:` metres per
pixel. It repeats; images <= 256 px are crisp (pixel art on smooth shapes). Clear pixels show the part's colour
(after swaps); its pattern colours paint over it; a `decal` replaces it there.

## Cloth folds: `folds`

Robes, skirts, capes and curtains: `folds: { count: 12, depth: 0.03, from_y: 0, to_y: 1.0, sharp: 0.5 }` on a smooth
part (a cone, a lathe, a cylinder; count 2-48, depth up to 0.1) runs `count` vertical folds round its own y axis,
`depth` metres deep at `from_y` (the hem) and fading out by `to_y` (where the cloth hangs from); `sharp` 0 gives
round waves, 1 narrow ridges between wide hollows. The hem comes out scalloped. Heights run along the part's own axis
(model heights for an upright part; each `array` copy folds round its own). A fold is never deeper than a quarter of
the fold spacing there (2 pi r / count), so near the axis and with many folds they get shallower. They are real
shape: they show in silhouette and in Godot without a normal map; keep `depth` at least two mesh cells. A shell's wall
folds with them; a fitted shell can't fold (fold the parts it wraps); hard parts can't; colour borders follow the
unfolded shapes (a belt doesn't wiggle).

## Relief: fur without parts

Fur, and any coat of small overlapping tufts, is a `relief:` layer on one smooth body, never hundreds of clump
parts: the patches live in the baked normal map and a base colour map, so they cost no parts, no cells and no
triangles (a 12-part cub with three layers builds in 30 s). Needs `kiln-gen[bake]`; turns on a 1024 map unless
`normal_map:` sets the size.

```yaml
relief:
  - on: [body, arm_l, arm_r, leg_l, leg_r]   # ids of the smooth parts it covers (a mirror twin by its own mirror_id)
    # or on_colors: [fur, fur_dark]: only faces painted in those colours (alone: on every smooth part; with on:, both);
    # except: [face, chest]: ids left bare. kind: fur (the only kind so far).
    length: 0.08      # metres, root to tip along the flow (default 0.09)
    width: 0.045      # metres across (0.05)
    lift: 0.007       # metres the tip stands off the surface (0.008): the depth of the shading
    density: 1.6      # 1 just covers the surface; more overlaps like roof tiles (1)
    flow: down        # down | up | [x, y, z]: the way the tips point (down)
    tips: 3           # pointed tips along a patch's lower edge (3)
    jitter: 0.3       # 0..1 variation of size and angle (0.3)
    color: bark       # optional root colour and tip colour; without them a patch has the colour of the surface
    color_to: wood
    under: 0.4        # 0..1: how much darker the surface is just below each tip (0.3)
    fade: 0.06        # metres over which patches thin out and shrink toward the edge of `on`: no hard bib (0.06)
    seed: 1
```

- Layers apply in order; give the body long patches, the head and hands shorter ones (`length` about a tenth of the
  part's size), a pale belly or muzzle its own short layer with `fade`.
- Model the body as a few big blended parts first; the silhouette stays the mesh's (relief does not move it).
- A patch is flat: on a thin limb lying across the flow it wraps badly; point `flow` along the limb there.
- Patches stay on the parts in `on`: eyes, a nose, claws and glowing or hard parts next to them stay clean.
  `normal_strength` scales the layer's shading with the rest of the map. `preview --draft` shows no relief.
- The model's colours are then in `<name>.color.png` on the normal map's UVs (one material per preset; a variant has
  its own map and glb). Manifest: `color_map` (`png`, `size`, `patches`). Example: `examples/demo/models/cub.kiln.yaml`.

## Soft colour borders: `color_blend`

A part's colour meets its neighbours' in a crisp border by default. `color_blend: 0.05` on a part (metres, 0 to
0.5) fades its colour into theirs over that distance either side of the border: a pale belly or muzzle melting into
the fur, a tan chest, a sunburnt nose.

```yaml
  - ellipsoid: { at: [0, 0.4, 0.13], radii: [0.17, 0.2, 0.12] }
    id: belly
    color: rope
    blend: 0.05
    color_blend: 0.04    # the wider of two neighbours' values is used on their border
```

- The fade is painted in the base colour map (the same map relief uses, `<name>.color.png`; it comes on with a 1024
  map unless `normal_map:` sets the size; needs `kiln-gen[bake]`; under `atlas = true` the model leaves the atlas).
  The mesh and its border don't change. `preview --draft` shows no fade.
- A border fades when one of its two parts asks and the later of them joins the other with a `blend`: a nose or an
  eye set on with a crisp seam (`blend: 0`) stays sharp next to a fading muzzle. The wider of the two values is used.
- Colours mix in OKLab, half and half on the border, toward what the neighbour looks like (its fur, if it has
  relief). A part's own pattern stripes and gradient bands stay crisp.
- Borders with hard parts, glowing materials and decals stay crisp. Lint W127: a `color_blend` that fades nothing.
- Where three colours meet, each point fades toward the nearest border only.
