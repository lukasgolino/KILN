# Surfaces

Hard surfaces (exact polygons), hardware (rivets, bands, planks, bolts, slits, garments), patterns, decals, textures.

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
- `pixel`: a pixel motif tiled round the part's own axis (a hat band, a hem, a cuff): `rows: ["#..#", ".##."]` (`#`
  or any letter painted, `.` or space not; top row first) or `image: trims/key.png` (alpha over half painted; up to
  256x64), each cell `size` metres tall along `axis`, the band centred on `at` (from the part's centre: `frame: part` is
  the default here), the motif `repeat` times round (default 8: cells get wider on a wider part). One colour per
  pattern: list several for more. E.g. `{ type: pixel, color: gold, size: 0.02, at: -0.1, repeat: 16, rows: [...] }`.

## Decals

```yaml
    decal: { image: decals/logo.png, axis: z, at: [0, 0.6, 0.3], size: [0.2, 0.1] }
```

Projects an image (PNG with transparency, e.g. made with PAGAN) onto the faces of this part that face `axis`
(x, -x, y, -y, z, -z), centred at `at` (model space, on or near the surface), `size` = width, height in metres. It
shows on that side only (a flag needs a second decal with `axis: -z` for its back). Transparent pixels show the part's colour.
Small images (<= 256 px) are sampled crisp (pixel art).

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
