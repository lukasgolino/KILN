# Lint

Lint rules: what each means and how to fix it.

## Lint

Errors: E000 usage/config, E001 file/YAML, E002 unknown field, E003 bad value, E004 unknown colour, E005 unknown
material, E006 style problem, E007 rig problem, E008 animation problem, E009 nothing to mesh, E010 import file
problem, E011 decal image missing, E012 extends problem (no such model, not a template, a loop, unknown remove id),
E013 the built mesh has open edges (cracks), edges with more than two faces or sheets touching at a vertex (a KILN
bug; report it), E014 `kiln.lock` problem (a pack-imported file changed, a licence that isn't CC0-1.0), E015 scatter problem
(an unknown or unsuitable model to place or stand on, too many instances).

Warnings: W101 part has no visible surface, W102 part thinner than the mesh resolution, W103 separate pieces,
W104 colour not in the palette, W106 not standing on y = 0, W107 made under an older style_version, W108 size
unusual for the class, W109 animated part without a pivot, W110 well over the triangle budget (patterns cost
triangles: every stripe border is cut into the mesh; prefer few, large patterns, or model details as parts), W111 a
part lost when reducing to the triangle budget (raise `budget:`), W112 a LOD well above its target (from `kiln build`),
W113 a part pokes through a shell (eyes bigger than a visor slot, a head through a helmet: keep it inside or outside).
W114 (from `kiln build`) joints sit elsewhere than in the model's `animation_library`. W115 `kiln.lock` lists a file
that isn't in the project. W116 a terrain's splat layer covers < 0.5% of the map, W117 a
terrain's height shape is off the map. W118 a scatter entry places more than 50 000 instances, W119 one places none.
W120 the grid cap (`max_cells`), not the resolution, set the mesh cell size: raise `max_cells` to what it says. W121 a `detail` part shows nowhere (no `normal_map`, or under two texels thick). W122 a
`blend_to` target is meshed apart from the part (hard, kept, separate, another bone's piece): they join crisply.
Disable in `kiln.toml` `[lint] disable` or per model `lint: { disable: [...] }`. Lint meshes models in parallel
(`KILN_JOBS` processes, default: every core) and caches them for build and previews. `pip install "kiln[fast]"`
(numba) evaluates the shapes compiled, 2-3x faster on big models; the output then differs from the plain install in
the last digits, so a game pins one or the other.
