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
extends = "soft_toy"           # soft_toy | low_poly | toon | clay | diorama | skin | another project style
notes = """Shapes, proportions, colours, materials, lighting in words (agents follow this)."""

[shape]
smooth = true                  # false = faceted (flat normals)
sharp_angle = 50               # smooth styles: edges sharper than this stay crisp
resolution = 0.008             # metres per mesh cell for a ~1 m model (finer = rounder, slower)
color_blend = 0.0              # metres: smooth parts blending into another colour fade into it (a part's own wins; 0 there: crisp)
max_cells = 256                # mesh cells across a model at most (64-1024): bigger models get coarser cells past it
scale_with_size = true         # models over 1 m get resolution x sqrt(size); false: resolution as is

[budgets]                      # triangles per class
character = 8000
default = 4000

[materials]                    # roughness, metallic (0..1), emission (glow strength, capped per colour: see parts), rim (soft edge light), alpha (0.05-1: see-through)
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
compat_shadows = false         # Godot's Compatibility renderer: the sun drops its shadows there, since that renderer adds the
                               # ambient again per shadowed light (godotengine/godot#90259: several times too bright); true keeps them
fog = 0.0
fog_color = "#c8d8e8"
rim_light = 0.0                # an added fresnel rim on every surface (Godot: a next pass; previews too): 0.5-1 reads on bright skies
rim_light_color = "#ffffff"
rim_light_power = 3.0          # higher: thinner rim

[shade]                        # shade paint baked into the vertex colours (off by default; each 0 to 0.9)
cavity = 0.25                  # crevices darker: x the field's occlusion (as atlas_ao)
top = 0.12                     # the top keeps its colour; sides darker by this, undersides too
under = 0.1                    # undersides darker still
```

**Shade paint** is the hand-painted look: dark crevices, tops at full colour, shaded sides and bellies, in any colour
mode. It is a grey multiplier per vertex corner in COLOR_0 (glTF multiplies it into the base colour; KILN's Godot scenes and the previews
use it), so it follows the mesh's resolution. A model with a base colour map (relief, `color_blend`) gets it per
texel in `<name>.color.png` instead, from the normal map's normals (relief tilts and grooves count) and the occlusion
at each texel, with the same strengths; its mapped faces then carry no COLOR_0. A model's `shade: { cavity: 0.3 }` goes over its style's fields. Vertex
colours can't go above 1, so `top` darkens everything that doesn't face up rather than lighten the top: pick base
colours for the lit top. Typical: `cavity` 0.2-0.4 for creatures and props with grooves, `top` 0.1-0.15, `under`
0.1. Without the atlas `atlas_ao` doesn't apply; `shade.cavity` is the same occlusion. Gibs get their own shade, from the piece's own shape (a
crevice where it was attached is open once it comes off). With `vertex_colors = true` and `variant_glbs = false`,
COLOR_0 holds the colours times the shade, so an engine recolouring from the manifest's `swap` table matches by
colour within a tolerance, or turns `variant_glbs` on (each variant its own shaded glb).

Every toon key is off by default (today's plain cel look). A painterly cel look: `toon_softness = 0.2`,
`toon_shadow_color` a cool mid tone, `toon_specular = 0.6` on glossy materials, `toon_shadows = "band"`,
`outline_space = "pixels"` with `outline = 2` and `outline_color = "darken"`. Previews follow every key except
`toon_shadows` (the software renderer has no cast shadows; `kiln preview --engine` shows them in Forward+ and Mobile
projects, and on Compatibility only with `compat_shadows = true`).

## The skin preset: stylised game skins

`default_style = "skin"` (or `extends = "skin"`) turns the painted game-skin look on without setting each option:
matte materials (no rim, no shine on skin, fur and cloth), `[shape] color_blend = 0.03` (every smooth part that blends
fades its colour into its neighbours'), `[shade]` on (cavity 0.3, top 0.12, under 0.1), larger budgets, and a soft
look kit (high ambient, warm sun). Fur goes on as relief, faces get `density`. A worked example (builds in ~25 s):

```yaml
name: critter
class: creature
parts:
  - ellipsoid: { at: [0, 0.45, 0], radii: [0.28, 0.4, 0.24] }
    id: body
    color: fur_brown
  - ellipsoid: { at: [0, 0.42, 0.14], radii: [0.18, 0.26, 0.13] }
    id: belly
    color: fur_light            # fades into the body: the style's color_blend
    blend: 0.06
  - sphere: { at: [0, 0.98, 0.02], radius: 0.2 }
    id: head
    color: fur_brown
    blend: 0.08
    density: 2                  # more of the budget on the face
  - ellipsoid: { at: [0, 0.94, 0.19], radii: [0.09, 0.07, 0.07] }
    id: snout
    color: fur_light
    blend: 0.04
relief:
  - { on: [body, head], length: 0.07, width: 0.035, lift: 0.006 }
```

Eyes, teeth and claws: a crisp seam (no `blend`) keeps them out of the fade, or `color_blend: 0` on the part (that
border stays crisp from both sides). The style's fade skips parts made hard (`hard_surface`, `bevel`, `blend: none`)
and parts blending only into their own colour (a one-colour prop bakes no map), and stays off when baking isn't
installed (`kiln-gen[bake]`).

