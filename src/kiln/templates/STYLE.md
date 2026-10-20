# Style

How this game's models look, so every model fits. The style file (`kiln.toml` default_style, details in
`kiln style show`) holds the numbers; this file holds the words and the history.

## Look

- **Preset / style file:** $style
- **Shapes:** TODO (rounded? chunky? faceted?)
- **Proportions:** TODO (head to body, limb thickness, eye size)
- **Colours:** palette `main`; TODO (how many per model, accents)
- **Materials:** TODO (plastic? matte? metal accents?)
- **Lighting / look kit:** TODO (bright day? dusk? toon?)

## Rules

- Units are metres; models stand on y = 0 and face +Z.
- Every colour comes from the palette (names, not hexes).
- TODO

## Changelog

`kiln style bump --message "..."` adds an entry here and raises `style_version`; `kiln status` then lists models
made under an older style for review.

- v1: first version.
