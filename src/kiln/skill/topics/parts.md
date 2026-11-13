# Parts

Part notation: every shape and part option (blend, cut, mirror, array, shell, fit, on, folds, density, ...).

## Parts

Each part is one shape plus options. Parts are combined **in order**: each one joins (or cuts) what came before.
Hard surfaces, hardware (rivets, bands, planks, garments), patterns: `kiln docs surfaces`; decals and textures: `kiln docs textures`.

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
| `cylinder` | `radius`, `height` (along y), `round`, `sides` (8: an octagonal prism, a flat side facing +z; `radius` reaches its corners, its flats sit at radius x cos(180/sides)). `at` is its middle: half of it is below `at` (or place it by its ends with `aim`) |
| `cone` | `radius` (bottom), `radius_top` (0 = point), `height` (along y), `sides` (4: a pyramid). `at` is its middle, not its base: a tuft set `at` a surface is half buried. Stand it on a point with `aim: [[base], [tip]]` (y runs base to tip; without a `height`, the distance between them) |
| `capsule` | `from: [x, y, z]`, `to: [x, y, z]`, `radius`, `radius_to` (taper) |
| `tube` | `points: [[x, y, z], ...]` (2+; straight unless `smooth: true`), `radius`, `radius_to`: ropes, branches, rails, tails |
| `lock` | `points` (2+), `width`, `thickness`, `width_to`, `thickness_to`, `facing: [x, y, z]`, `smooth` (as tube): a flat blade along a path (fur and hair locks, feathers, leaves, petals); `width_to: 0` is a pointed tip; the flat sides look along `facing` |
| `torus` | `radius` (ring), `thickness` (tube radius); ring in the xz plane (rotate for others) |
| `lathe` | `profile: [[r, y], ...]` spun around y: vases, bottles, bells, caps, chess pieces, round towers. The profile is a closed outline in the (radius, height) plane: go up the outside and come back down the axis (points with r = 0), e.g. a cap `[[0, 1.06], [0.2, 1.02], [0.3, 0.9], [0.3, 0.8], [0, 0.8]]`. Corners are rounded (`smooth: true`, default); `smooth: false` keeps them sharp |
| `extrude` | `points: [[x, z], ...]` outline seen from above (3+ different points; repeats and a closing point are dropped), `height` (along y), `round`, `holes: [[[x, z], ...], ...]` (outlines cut through: letters O, A, B; `round` rounds their edges too; hard parts: hole edges stay sharp), `offset` (grow the outline by metres, < 0 shrinks: inset face plates). Or `path: "M 0 0 L 1 0 Q 1 1 0 1 Z"` (SVG path data: M L H V C S Q T A Z, absolute and relative; y runs down onto z, so `rotate: [90, 0, 0]` stands it up reading right from the front) with `path_scale` (metres per unit: 0.001 for a 1000-unit font em) and `path_tolerance` (0.002 m): every subpath is an outline, even-odd (counters are holes, separate shapes are islands). Or `text: "OPEN"` in `font: fonts/sign.ttf` (.ttf/.otf, relative to the project folder) with `text_size` (metres per em, 0.1), `text_align` (left, center, right: about x = 0), `letter_spacing` (metres), `line_spacing` (ems, 1.2; `\n` starts a line), `font_axes` (a variable font's instance: `{ wght: 900 }`; default: its default instance): first baseline at z = 0, glyphs toward -z; no kerning or shaping. Glyphs fill like fonts do (nonzero): overlapping contours join instead of cutting holes. Check the font's licence before shipping its shapes. Shields, signs, floor plans, stars, letters |
| `wedge` | `size: [x, y, z]`: a roof (ridge along x at the top) |

`sides` (3-64) also works on `lathe` and `torus`, and on `sphere`, `ellipsoid`, `capsule` and `tube` for hard parts.
`sides` makes a part hard (exact polygons: no blend, folds or pixel patterns on it).

For `capsule` and `tube`, the points are in the part's frame (moved by `at`, turned by `rotate`). Everything else in a
model (decal `at`, rig pivots, poses' offsets) is in model space.

### Part options

| option | meaning |
|---|---|
| `id` | bone/node name (lowercase). Parts sharing an id move together. No id = `root`. |
| `color` | palette colour name (required for adding parts) |
| `material` | style preset: default, plastic, paint, fabric, skin, leather, rubber, wood, stone, metal, gold, leaf, glass, glow |
| `emission: 0.6` | this part's glow strength over its preset's (eyes softer than a crystal). A glowing colour's strength is capped so it keeps its hue (its brightest channel x strength at most 0.75), so for bright colours a higher number changes nothing (a dark red can glow at 3, a pale pink tops out under 1); its lit colour is dimmed: the glow carries it |
| `blend` | smooth-union radius in metres with everything before it (cuts/intersects: smooth edge) |
| `color_blend` | metres its colour fades into blended neighbours' (`surfaces`) |
| `resolution: 0.004` | a finer mesh cell inside this part's box than the model's (a face, hands): the mesh there is split down to it and moved onto the surface, so lids, nostrils and a nose show on a coarse body; give it `density` too, or the budget reduces it away |
| `density: 3` | weight on the triangle budget (0.25-8, default 1): about 3x the share of the budget it would get, at the same total (a face); 0.5 coarser. Not past its full-resolution mesh; hard and kept parts ignore it |
| `cut: true` | remove this shape from everything before it (holes, slits, windows, eye sockets); an `id` or `mirror_id` on a cut only names it (it moves with nothing) |
| `cut: [case, lid]` | cuts only the parts with these ids (`cut: lid`: one); those parts are then meshed as their own surface (crisp against the rest), so the pad under a watch case or a tray's screws stay whole |
| `cut: true` + `color: black` | the walls the cut makes are painted (an inked groove, a clasp's lid line, panel lines; `material:` too); the surface round it keeps its colour. Not in `--draft` |
| `intersect: true` | keep only what's inside this shape (trim) |
| `mirror: x` | also on the other side of 0 (x, y, z or a list); same id |
| `mirror_id: arm_r` | with `mirror: x`: the copy is a separate part with this id (rig entries are mirrored too) |
| `array: { count: 4, step: [1, 0, 0] }` | repeat in a row |
| `array: { count: 8, around: y, center: [0, 0, 0], angle: 360 }` | repeat in a ring (`around` may be any direction `[x, y, z]`: a ring on a tilted wheel). The first copy is the part as written; the others turn about `around` through `center`, counter-clockwise seen from the tip of `around` (right-handed: +90 degrees about y takes +z to +x), and each copy is turned with the ring, not only moved (it faces outwards as the first does, also on a tilted axis). `angle` under 360 is an arc from the part as written to `angle`, both ends included (count - 1 gaps); negative runs clockwise. A fringe across the back only: write the first tuft at one end, e.g. at `[0.1, y, -0.1]` (the model's left is +x, its back -z), and give the arc's span: `angle: 90` ends at `[-0.1, y, -0.1]`. A full ring's count spreads evenly (no copy at 360) |
| `shell: 0.02` | hollow, walls this thick (centred on the surface) |
| `shell: { thickness: 0.02, open: -y }` | a wall inside the surface (the outside stays put), one side cut open at the shape's centre: helmets, bowls, pots, shields with a visible rim (`side: both` centres it) |
| `fit: head` or `fit: { to: head, gap: 0.01 }` | with `shell`: the wall wraps the parts with that id, `gap` away from them, wherever this part's own shape reaches (its shape is the coverage: a sphere around the head, `open: -y` and placed low enough to cover the cheeks). Helmets that sit on the head instead of perching on it; cut a face opening after it (before the head, so the cut doesn't take the face) |
| `twist: 90` | degrees per metre about the shape's y axis |
| `blend_to: torso` (or a list of ids) | with `blend`: melt only into those earlier parts, meet every other part crisply. If this part has `mirror_id`, its copy melts into the mirrored ids (name one side); with plain `mirror`, name both |
| `detail: true` | only in the model's baked normal map (`normal_map:`), never in the mesh: grooves between fur strands (a thin `cut: true` tube), wrinkles, knuckle creases, scratches, fine `noise` on a coarse, light mesh. Lint W121: no map, or thinner than two texels. A texel is about sqrt(2 x surface area) / map size (a 2.4 m character, about 4 m² of surface, at 2048: ~1.5 mm; small maps with many charts are coarser, and lint measures the real one): grooves read when about 4 texels wide or more; finer ones blur out (each texel is filtered), and deep narrow ones make bright specular lines: shallower and wider, or `normal_strength: 0.5` |
| `scale: [1, 1, 0.4]` | stretch the shape in its own frame (or one number); soft parts only |
| `noise: { amount: 0.01, scale: 0.2, seed: 3 }` | lumpy surface (rocks, bark, clay): amount in metres, scale = bump size. Colour borders with other parts follow the smooth shapes, so a patch on a noisy part keeps a clean edge |
| `folds: { count: 12, depth: 0.02, from_y, to_y }` | cloth folds round the part's own axis, deepest at the hem (`surfaces`) |
| `pattern: {...}` | a second colour painted on the part (`kiln docs surfaces`) |
| `gradient: { to: fur_light, steps: 3 }` | the part's colour going to `to` in `steps` bands (2-16, default 3), mixed in OKLab; `from:` replaces the part's colour at the start. `along: path` (the default for tube, capsule and lock: first point to last) or `x`/`y`/`z` (the default for other shapes: across the shape's own box, low to high). Patterns paint over it; variants recolour the mixed bands from the swapped ends |
| `decal: {...}` | an image on the part (`kiln docs textures`) |
| `texture: {...}` | an image tiled over the whole part, box, triplanar or cylindrical, crisp when small, palette-indexed or generated (`kiln docs textures`) |
| `loose: true` | this part may float free (flames, bees, sparks, rubble): W103 doesn't count it |
| `blend: none` | a hard part, joined crisply (`kiln docs surfaces`) |
| `hard: true` / `false` | make this part hard (exact polygons) or smooth, whatever the style says |
| `chamfer: 0.02` | hard parts: one flat band cut along every edge (box, wedge, cylinder, cone, extrude) |
| `bevel: 0.02` | hard parts: rounded edges in `segments: 1-4` flat bands (default 2); where an extrude outline is thinner than about twice the bevel (font serifs, hairlines) it flattens there to fit |
| `keep: true` | this detail survives every reduction (LODs) as its own small mesh, sitting in the surface around it. Crisp (`blend` 0) parts smaller than 2% of the model are kept anyway (rivets, pupils, studs); `keep: false` opts out |
| `aim: [[x, y, z], [x, y, z]]` | points the shape's own y axis from the first point to the second and puts it halfway (instead of `at`); a shape with a `height` that doesn't give one gets the distance. `{ from, to, roll: 30 }` spins it about that line; `rotate` turns it in its own frame first. Arrows, spears, struts, beams at any angle |
| `on: { part: body, near: [x, y, z] }` | instead of `at`: placed on the blended surface of earlier parts, its y axis along the normal there; `offset`, `roll`, `align: false` (`making`) |
| `attr: { heat: 0.9 }` | named numbers a shader reads per vertex (heat, opacity, wind weight); faces of parts without it get 0. Each becomes a custom glTF attribute `_HEAT` (Blender, three.js; Godot 4.7 drops custom attributes), and the first name (alphabetical) also goes in COLOR_0's alpha (Godot: `COLOR.a`; white RGB unless `vertex_colors`). Manifest `attributes` |
| `uv: cylindrical` | texture coordinates projected from the part's shape, in its own frame (they follow `rotate`, mirror, arrays): `cylindrical` (u around, v along the axis over the part's box), `spherical`, `box` (per face, metres / the box's largest side), `along` (tubes and capsules: v = distance along the path, 0..1). `{ project, axis: y, scale: [1, 4] }`. Written to TEXCOORD_0 (Godot UV), or TEXCOORD_1 (UV2) when the atlas or a decal uses the first; manifest `uv: {set, parts}`. Other faces get (0, 0) |

Order matters: details that sit on a surface come **after** it. A part completely inside later parts shows nothing
(W101). A cut removes material from what came before it, and paint follows: a door placed after the cut that made its
archway is painted as the door, not as the wall. Parts thinner than about two mesh cells break up (W102): resolution comes from the style (soft_toy: 8 mm
for a ~1 m model, coarser for bigger models: x sqrt(size), and at most 256 cells across). `kiln lint` and `kiln build`
print the cell size each model got and what set it (model or style resolution, the size scaling, a max_cells cap;
manifest `step`, lint `--json` `cells`); a long build's meshing line says it too. Finer detail on a hero: `resolution: 0.004` and `max_cells: 640` in the model
(lint W120 names the max_cells needed). Halving the cell size about doubles build time (`kiln docs build`); the budget still
decides the final triangles.

Posing a group (a hunched back, a head thrust forward) without retyping its parts: `transforms: [{ ids: [head, neck,
arm_l], rotate: [x, y, z], pivot: [x, y, z], move: [x, y, z] }]` at the top of the model turns the listed parts (arrays
keep their copies) about `pivot`, then moves them; their rig pivots and sockets go with them. Items apply in order.
A `mirror: x` part takes only turns about x and moves in y/z (anything else breaks its mirror: E003).

Placing other models (a desk with its props, a tray of screws): `instances: [{ model: screw, at: [x, y, z], rotate:
[x, y, z], scale: 1, id: tray }]` at the top of the model. Each is that model's own build (its mesh at its own cell size
and budget: fine screws stay fine in a coarse scene), merged in after the scene is built. `at`/`rotate` are in the
scene's model space and place the instance's origin (its `origin:`, as its own glb); `id` is the part it moves with
(default root; not mirrored). A scene `lod:` builds every instance at the same share of its triangles. Materials are
read in the scene's style; an instance's decals and textures come along (not when it is scaled); its animations, skin
and baked maps don't, and a scene with a normal map or relief can't take instances yet. Each copy is merged into the
scene's mesh (no shared mesh yet). `kiln build screw` rebuilds the models that place it. Missing models:
E011; templates, terrains, scatters and circles (a model placing itself round about) are errors.
