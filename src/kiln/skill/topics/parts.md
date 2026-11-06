# Parts

Part notation: every shape, blend, cut, mirror, array, shell, patterns, decals, hardware.

## Parts

Each part is one shape plus options. Parts are combined **in order**: each one joins (or cuts) what came before.

```yaml
parts:
  - capsule: { from: [0, 0.3, 0], to: [0, 0.75, 0], radius: 0.3 }   # the shape and its parameters
    id: body                   # optional: which bone/node it belongs to (default: root)
    color: red                 # palette colour name
    material: plastic          # a style material preset (default: default)
    blend: 0.04                # smooth join radius with what's before it (0 = crisp seam)
```

### Shapes

Every shape takes `at: [x, y, z]` (its centre; default [0, 0, 0]) and `rotate: [x, y, z]` (degrees, applied x
then y then z, about its centre).

| shape | parameters |
|---|---|
| `sphere` | `radius` |
| `ellipsoid` | `radii: [x, y, z]` |
| `box` | `size: [x, y, z]`, `round` (edge radius; size kept) |
| `cylinder` | `radius`, `height` (along y), `round`, `sides` (8: an octagonal prism, a flat side facing +z) |
| `cone` | `radius` (bottom), `radius_top` (0 = point), `height` (along y), `sides` (4: a pyramid) |
| `capsule` | `from: [x, y, z]`, `to: [x, y, z]`, `radius`, `radius_to` (taper) |
| `tube` | `points: [[x, y, z], ...]` (2+), `radius`, `radius_to`: ropes, branches, rails, tails |
| `lock` | `points` (2+), `width`, `thickness`, `width_to`, `thickness_to`, `facing: [x, y, z]`: a flat blade along a path (fur and hair locks, feathers, leaves, petals); `width_to: 0` is a pointed tip; the flat sides look along `facing` |
| `torus` | `radius` (ring), `thickness` (tube radius); ring in the xz plane (rotate for others) |
| `lathe` | `profile: [[r, y], ...]` spun around y: vases, bottles, bells, caps, chess pieces, round towers. The profile is a closed outline in the (radius, height) plane: go up the outside and come back down the axis (points with r = 0), e.g. a cap `[[0, 1.06], [0.2, 1.02], [0.3, 0.9], [0.3, 0.8], [0, 0.8]]`. Corners are rounded (`smooth: true`, default); `smooth: false` keeps them sharp |
| `extrude` | `points: [[x, z], ...]` outline seen from above (3+ different points; repeats and a closing point are dropped), `height` (along y), `round`, `holes: [[[x, z], ...], ...]` (outlines cut through: letters O, A, B; `round` rounds their edges too; hard parts: hole edges stay sharp), `offset` (grow the outline by metres, < 0 shrinks: inset face plates). Or `path: "M 0 0 L 1 0 Q 1 1 0 1 Z"` (SVG path data: M L H V C S Q T A Z, absolute and relative; y runs down onto z, so `rotate: [90, 0, 0]` stands it up reading right from the front) with `path_scale` (metres per unit: 0.001 for a 1000-unit font em) and `path_tolerance` (0.002 m): every subpath is an outline, even-odd (counters are holes, separate shapes are islands). Or `text: "OPEN"` in `font: fonts/sign.ttf` (.ttf/.otf, relative to the project folder) with `text_size` (metres per em, 0.1), `text_align` (left, center, right: about x = 0), `letter_spacing` (metres), `line_spacing` (ems, 1.2; `\n` starts a line), `font_axes` (a variable font's instance: `{ wght: 900 }`; default: its default instance): first baseline at z = 0, glyphs toward -z; no kerning or shaping. Glyphs fill like fonts do (nonzero): overlapping contours join instead of cutting holes. Check the font's licence before shipping its shapes. Shields, signs, floor plans, stars, letters |
| `wedge` | `size: [x, y, z]`: a roof (ridge along x at the top) |

`sides` (3-64) also works on `lathe` and `torus`, and on `sphere`, `ellipsoid`, `capsule` and `tube` for hard parts.

For `capsule` and `tube`, the points are in the part's frame (moved by `at`, turned by `rotate`). Everything else in a
model (decal `at`, rig pivots, poses' offsets) is in model space.

### Part options

| option | meaning |
|---|---|
| `id` | bone/node name (lowercase). Parts sharing an id move together. No id = `root`. |
| `color` | palette colour name (required for adding parts) |
| `material` | style preset: default, plastic, paint, fabric, skin, leather, rubber, wood, stone, metal, gold, leaf, glass, glow |
| `blend` | smooth-union radius in metres with everything before it (cuts/intersects: smooth edge) |
| `cut: true` | remove this shape from everything before it (holes, slits, windows, eye sockets) |
| `intersect: true` | keep only what's inside this shape (trim) |
| `mirror: x` | also on the other side of 0 (x, y, z or a list); same id |
| `mirror_id: arm_r` | with `mirror: x`: the copy is a separate part with this id (rig entries are mirrored too) |
| `array: { count: 4, step: [1, 0, 0] }` | repeat in a row |
| `array: { count: 8, around: y, center: [0, 0, 0], angle: 360 }` | repeat in a ring (`around` may be any direction `[x, y, z]`: a ring on a tilted wheel) |
| `shell: 0.02` | hollow, walls this thick (centred on the surface) |
| `shell: { thickness: 0.02, open: -y }` | a wall inside the surface (the outside stays put), one side cut open at the shape's centre: helmets, bowls, pots, shields with a visible rim (`side: both` centres it) |
| `fit: head` or `fit: { to: head, gap: 0.01 }` | with `shell`: the wall wraps the parts with that id, `gap` away from them, wherever this part's own shape reaches (its shape is the coverage: a sphere around the head, `open: -y` and placed low enough to cover the cheeks). Helmets that sit on the head instead of perching on it; cut a face opening after it (before the head, so the cut doesn't take the face) |
| `twist: 90` | degrees per metre about the shape's y axis |
| `blend_to: torso` (or a list of ids) | with `blend`: melt only into those earlier parts, meet every other part crisply: fur locks that melt into the body but keep a groove between each other |
| `detail: true` | only in the model's baked normal map (`normal_map:`), never in the mesh: grooves between fur strands (a thin `cut: true` tube), wrinkles, knuckle creases, scratches, fine `noise` on a coarse, light mesh. Lint W121: no map, or thinner than two texels |
| `scale: [1, 1, 0.4]` | stretch the shape in its own frame (or one number); soft parts only |
| `noise: { amount: 0.01, scale: 0.2, seed: 3 }` | lumpy surface (rocks, bark, clay): amount in metres, scale = bump size. Colour borders with other parts follow the smooth shapes, so a patch on a noisy part keeps a clean edge |
| `pattern: {...}` | a second colour painted on the part (below) |
| `gradient: { to: fur_light, steps: 3 }` | the part's colour going to `to` in `steps` bands (2-16, default 3), mixed in OKLab; `from:` replaces the part's colour at the start. `along: path` (the default for tube, capsule and lock: first point to last) or `x`/`y`/`z` (the default for other shapes: across the shape's own box, low to high). Patterns paint over it; variants recolour the mixed bands from the swapped ends |
| `decal: {...}` | an image on the part (below) |
| `loose: true` | this part may float free (flames, bees, sparks, rubble): W103 doesn't count it |
| `blend: none` | a hard part, joined crisply (below) |
| `hard: true` / `false` | make this part hard (exact polygons) or smooth, whatever the style says |
| `chamfer: 0.02` | hard parts: one flat band cut along every edge (box, wedge, cylinder, cone, extrude) |
| `bevel: 0.02` | hard parts: rounded edges in `segments: 1-4` flat bands (default 2); where an extrude outline is thinner than about twice the bevel (font serifs, hairlines) it flattens there to fit |
| `keep: true` | this detail survives every reduction (LODs) as its own small mesh, sitting in the surface around it. Crisp (`blend` 0) parts smaller than 2% of the model are kept anyway (rivets, pupils, studs); `keep: false` opts out |
| `aim: [[x, y, z], [x, y, z]]` | points the shape's own y axis from the first point to the second and puts it halfway (instead of `at`); a shape with a `height` that doesn't give one gets the distance. `{ from, to, roll: 30 }` spins it about that line; `rotate` turns it in its own frame first. Arrows, spears, struts, beams at any angle |
| `attr: { heat: 0.9 }` | named numbers a shader reads per vertex (heat, opacity, wind weight); faces of parts without it get 0. Each becomes a custom glTF attribute `_HEAT` (Blender, three.js; Godot 4.7 drops custom attributes), and the first name (alphabetical) also goes in COLOR_0's alpha (Godot: `COLOR.a`; white RGB unless `vertex_colors`). Manifest `attributes` |
| `uv: cylindrical` | texture coordinates projected from the part's shape, in its own frame (they follow `rotate`, mirror, arrays): `cylindrical` (u around, v along the axis over the part's box), `spherical`, `box` (per face, metres / the box's largest side), `along` (tubes and capsules: v = distance along the path, 0..1). `{ project, axis: y, scale: [1, 4] }`. Written to TEXCOORD_0 (Godot UV), or TEXCOORD_1 (UV2) when the atlas or a decal uses the first; manifest `uv: {set, parts}`. Other faces get (0, 0) |

Order matters: details that sit on a surface come **after** it. A part completely inside later parts shows nothing
(W101). A cut removes material from what came before it, and paint follows: a door placed after the cut that made its
archway is painted as the door, not as the wall. Parts thinner than about two mesh cells break up (W102): resolution comes from the style (soft_toy: 8 mm
for a ~1 m model, coarser for bigger models: x sqrt(size), and at most 256 cells across). `kiln build` prints the cell
size each model got (manifest `step`). Finer detail on a hero: `resolution: 0.004` and `max_cells: 640` in the model
(lint W120 names the max_cells needed). Halving the cell size about triples build time and memory; the budget still
decides the final triangles.

### Hard surface

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

### Hardware

Written like a shape, each stands for several ordinary parts (hard by default); the part's other fields (colour,
material, id, mirror, ...) go to each.

| hardware | meaning |
|---|---|
| `rivets: { count: 8, along: [[x, y, z], ...], size: 0.03 }` | rivets evenly along a path (model space, ends included); or `around: { center, radius, axis: y }` in a ring |
| `band: { fit: body, at: [0, 0.12, 0], width: 0.05, thickness: 0.012, axis: y }` | an iron band round an earlier part's surface at `at` (or `radius:` instead of `fit`): barrels, doors, posts |
| `planks: { size: [1, 2, 0.08], count: 5, gap: 0.015, axis: x, jitter: 0.05, seed: 1 }` | boards side by side along `axis` with gaps, chamfered; `jitter` shortens each by up to that share of its length (with `at`, `rotate`) |
| `bolt: { at: [x, y, z], radius: 0.02, length: 0.02 }` | a hex bolt head along y (rotate it) |
| `slit: { at: [x, y, z], size: [0.3, 0.04, 0.3] }` | a cut: visor and arrow slits |

### Patterns

```yaml
    pattern: { type: stripes, color: gold, size: 0.06, width: 0.3, axis: y }
    # several: a list, painted in order (each over the last); frame: part = axes and `at` in the part's own frame
    # (they follow rotate/aim): pattern: [{ type: stripes, ..., frame: part }, { type: band, ..., frame: part }]
```

- `stripes`: bands across `axis`, one every `size` metres, `width` = fraction in the second colour.
- `band`: one band of thickness `size` centred at `at` (one number: metres along `axis`, in model space): belts, trims,
  hat bands. E.g. `{ type: band, color: brown, size: 0.06, at: 0.4, axis: y }` = a belt 0.4 m above the ground.
- `checker`: checks `size` metres across.
- `dots`: dots on a grid `size` metres apart, diameter `width` x size.

### Decals

```yaml
    decal: { image: decals/logo.png, axis: z, at: [0, 0.6, 0.3], size: [0.2, 0.1] }
```

Projects an image (PNG with transparency, e.g. made with PAGAN) onto the faces of this part that face `axis`
(x, -x, y, -y, z, -z), centred at `at` (model space, on or near the surface), `size` = width, height in metres. It
shows on that side only (a flag needs a second decal with `axis: -z` for its back). Transparent pixels show the part's colour.
Small images (<= 256 px) are sampled crisp (pixel art).
