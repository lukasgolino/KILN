# Textures

Decals (an image on one spot) and textures (an image tiled over a whole part): image files, named textures,
triplanar projection, motif prints, palette-indexed and generated pixel art that variants recolour.

## Decals

```yaml
    decal: { image: decals/logo.png, axis: z, at: [0, 0.6, 0.3], size: [0.2, 0.1] }
```

Projects an image (PNG with transparency, e.g. made with PAGAN) onto the faces of this part that face `axis`
(x, -x, y, -y, z, -z), centred at `at` (model space, on or near the surface), `size` = width, height in metres. It
shows on that side only (a flag needs a second decal with `axis: -z` for its back). Transparent pixels show the part's colour.
The image is upright and unmirrored seen from the side it faces: on a side axis (x, z) its top is +y; facing +y its
top points to -z (the back), facing -y to +z. A part turned 180 degrees with its decal still reads right only if the
decal's `axis` turns with it (write the axis it ends up facing).
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
pixel. It repeats; images up to 256 px on their longer side are crisp (nearest filtering, no mipmaps: pixel art on
smooth shapes); larger ones are filtered smoothly (linear, with mipmaps), at full size: no cap, so keep them as small
as the look needs. Cylindrical: v = 0 is at the part's `at` height, the image's bottom row toward low y. Clear pixels show the part's colour
(after swaps); its pattern colours paint over it; a `decal` replaces it there. `triplanar`: box UVs in the glb, but
KILN's Godot scenes (standard looks) and the previews blend the three projections by the surface's facing, so no seam
shows where box would switch sides (a sleeve's side).

A texture used on several parts is defined once at the top and named: `textures: { print: { image:
textures/print.png, project: triplanar, texel: 0.004 } }`, then `texture: print` on each part.

A busy multicolour print (flowers, leaves) made in KILN: `motif:` in place of `image` scatters stamps from a list of
PNGs (alpha, any colours) over one seamless tile, seeded: `texture: { motif: { images: [decals/flower.png,
decals/leaf.png], count: 14, scale: [0.12, 0.2], rotate: 180, seed: 2 }, project: triplanar, size: [0.14, 0.14] }`
(`scale`: a stamp's size as a share of the tile, up to 0.5 to wrap cleanly; `pixels`: the tile, 256). The tile is
written once to `.kiln-cache/motifs/`.

## Pixel art in palette colours

A texture written as rows of characters, each a palette colour (`.` or a space: the part's own colour shows), is
recoloured by variants like the parts around it; `generate:` makes one in palette colours (brushed metal, specks,
scratches, a grid, noise; `colors`: base, marks and an optional highlight; `pixels`: 32; `seed`).

```yaml
    texture: { rows: ["ab..", "ba.."], key: { a: red, b: gold }, project: box, texel: 0.01 }
    texture: { generate: brushed, colors: [steel, iron, white], pixels: 32, project: triplanar, texel: 0.004 }
```

A variant then gets its own glb (its texture in its colours). With variants, a pixel-art image (up to 256 px) whose
pixels aren't palette colours is lint W137: the variants can't swap them.
