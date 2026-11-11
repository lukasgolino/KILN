# Lint

Lint rules: what each means and how to fix it.

## Lint

Errors: E000 usage/config, E001 file/YAML, E002 unknown field, E003 bad value, E004 unknown colour, E005 unknown
material, E006 style problem, E007 rig problem, E008 animation problem, E009 nothing to mesh, E010 import file
problem, E011 decal or texture image missing or unreadable, E012 extends problem (no such model, not a template, a loop, unknown remove id),
E013 the built mesh has open edges (cracks), edges with more than two faces or sheets touching at a vertex (a KILN
bug; report it), E014 `kiln.lock` problem (a pack-imported file changed, a licence that isn't CC0-1.0), E015 scatter problem
(an unknown or unsuitable model to place or stand on, too many instances).

Warnings: W101 part has no visible surface, W102 part thinner than the mesh resolution, W103 separate pieces,
W104 colour not in the palette, W106 not standing on y = 0, W107 made under an older style_version, W108 size
unusual for the class, W109 animated part without a pivot (not humanoid joints), W110 well over the triangle budget (patterns cost
triangles: every stripe border is cut into the mesh; prefer few, large patterns, or model details as parts), W111 a
part lost when reducing to the triangle budget (raise `budget:`), W112 a LOD well above its target (from `kiln build`),
W113 a part pokes through a shell (eyes bigger than a visor slot, a head through a helmet: keep it inside or outside).
W114 (from `kiln build`) joints sit elsewhere than in the model's `animation_library`. W115 `kiln.lock` lists a file
that isn't in the project. W116 a terrain's splat layer covers < 0.5% of the map, W117 a
terrain's height shape is off the map. W118 a scatter entry places more than 50 000 instances, W119 one places none.
W120 the grid cap (`max_cells`), not the resolution, set the mesh cell size: raise `max_cells` to what it says. W121 a `detail` part shows nowhere (no `normal_map`, or under two texels thick). W122 a
`blend_to` target is meshed apart from the part (hard, kept, separate, another bone's piece): they join crisply.
W123 the built mesh dips 2 mm (or a tenth of a cell) or more below y = 0 (blends push feet under the ground): `origin: ground` exports it
lifted onto y = 0. W124 a part shows only a sliver: 97% or more of its own surface is deeper inside other parts than
their blend (clipped flat, nearly gone; W101 is all of it), with the covering parts named; not for hard, shell or
separate parts. W125 the mesh's UV charts don't fit the `normal_map` size (many separate pieces in a small map: the
padding between charts alone fills it) and were squeezed in: use a bigger map. Partly floating details have no warning yet: check them in the previews.

`kiln lint --fast` runs only the checks that need no built model (YAML, fields, values, names, the rig's and
animations' structure): quick while writing. It can't give the findings that come from the built model, and its
summary lists them: E009 (nothing to mesh, a build failure), E013, W101-W104, W106, W108-W111, W113, W120-W125. That
includes some that read like text checks (W104 a colour outside the palette, W109 an animated part without a pivot).
A scatter's surface model is still built. Plain `kiln lint` builds each model named (all without names) for the full
list; `kiln build` runs that full lint first on every model, on the same cached meshes, so a model that passes plain
lint passes the build's lint. The build can still stop on what only exporting finds (a clip carrier's users, emitters,
the Godot export).

Disable in `kiln.toml` `[lint] disable` or per model `lint: { disable: [...] }`. Lint meshes models in parallel
(`KILN_JOBS` processes, default: every core) and caches them for build and previews: a model is meshed again when
its parts, paint, rig or skin, its palette, its style's `[shape]` or its triangle budget change. Not for an edit of
its animations (their tracks are made again in seconds), variants, description or comments, nor for a style's
`[look]` or `[materials]`: iterate on poses and looks freely. `pip install "kiln-gen[fast]"`
(numba) evaluates the shapes compiled, 2-3x faster on big models; the output then differs from the plain install in
the last digits, so a game pins one or the other.
