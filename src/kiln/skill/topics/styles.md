# Styles

Styles and inspirations: presets, extends, the look kit; style notation.

## Styles and inspirations

A style (`styles/<name>.style.toml`, usually `extends = "soft_toy"` or another preset) decides: smooth or faceted
(`[shape]`), mesh resolution, triangle budgets per class, material presets (roughness, metal, glow, rim) and the
look kit (`[look]`: shader standard/toon (bands, softness, shadow colour, specular, banded shadows), outline
(metres or pixels, one colour or each part's darkened), tonemapper, exposure, saturation, contrast, SSAO, glow, sky,
sun, fog). The `notes` field holds the shape language and proportions in words: write it, and follow it.

From inspirations: look at the images; describe shapes (rounded? chunky? faceted?), proportions (head size, limb
thickness, eye size), colour (how saturated, how many per object), materials (glossy? matte?) and light (soft?
warm? outlines?). Pick the closest preset, `kiln style new <name> --extends <preset>`, override what differs, write
the notes, make one test model, compare with `kiln preview <model> --vs`, adjust, and get the owner's yes before
making more. Inspiration images are reference only: never copy another game's characters, and never model real
people.

Changing the look later: edit the style (and the palette): every model follows on the next build. If models
themselves must change, `kiln style bump -m "why"`; `kiln status` then flags older models for review.


## Styles

```toml
# styles/sky_pirates.style.toml
description = "Chunky toy airships, warm sunset light"
extends = "soft_toy"           # soft_toy | low_poly | toon | clay | diorama | another project style
notes = """Shapes, proportions, colours, materials, lighting in words (agents follow this)."""

[shape]
smooth = true                  # false = faceted (flat normals)
sharp_angle = 50               # smooth styles: edges sharper than this stay crisp
resolution = 0.008             # metres per mesh cell for a ~1 m model (finer = rounder, slower)
max_cells = 256                # mesh cells across a model at most (64-1024): bigger models get coarser cells past it
scale_with_size = true         # models over 1 m get resolution x sqrt(size); false: resolution as is

[budgets]                      # triangles per class
character = 8000
default = 4000

[materials]                    # roughness, metallic (0..1), emission (glow strength), rim (soft edge light)
plastic = { roughness = 0.42 }

[look]                         # the Godot look kit and preview lighting
shader = "standard"            # standard | toon
toon_bands = 3
toon_softness = 0.0            # toon: 0 = hard band steps; up to 1 = each edge blends over a whole band (0.2-0.4: soft cel)
toon_shadow_color = ""         # toon: "" = shadows only darken; "#rrggbb" or a palette colour = the sun's missing light in
                               # that colour (warm/cool shading; a light colour tints more; per model with its palette)
toon_specular = 0.0            # toon: one hard highlight blob, strength 0..1 (size grows and strength fades with roughness)
toon_shadows = "soft"          # toon: soft = Godot's received shadows; band = they drop into the darkest band (Godot only)
outline = 0.0                  # metres (toon outlines), 0 = none; pixels with outline_space = "pixels" (e.g. 2)
outline_color = "#1a1420"      # or "darken": each part's own colour, darkened
outline_space = "metres"       # metres: a shell that thins with distance; pixels: constant thickness on screen
tonemapper = "filmic"          # linear | filmic | aces | agx
exposure = 1.0
saturation = 1.15
contrast = 1.0
ssao = true
glow = true
ambient = 0.9
sky_top = "#4f8fe0"
sky_horizon = "#bcd7f2"
ground = "#a9c48f"
sun_pitch = -48.0              # degrees (negative = from above)
sun_yaw = 30.0
sun_energy = 1.1
sun_color = "#fff6e8"
shadows = true
fog = 0.0
fog_color = "#c8d8e8"
rim_light = 0.0                # an added fresnel rim on every surface (Godot: a next pass; previews too): 0.5-1 reads on bright skies
rim_light_color = "#ffffff"
rim_light_power = 3.0          # higher: thinner rim
```

Every toon key is off by default (today's plain cel look). Wind Waker / Sable-style: `toon_softness = 0.2`,
`toon_shadow_color` a cool mid tone, `toon_specular = 0.6` on glossy materials, `toon_shadows = "band"`,
`outline_space = "pixels"` with `outline = 2` and `outline_color = "darken"`. Previews follow every key except
`toon_shadows` (the software renderer has no cast shadows; `kiln preview --engine` shows them).
