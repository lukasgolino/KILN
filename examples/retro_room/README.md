# Retro room

A walkable demo of KILN's retro looks (#362): nine models on pedestals in a closed room, seen through the Atari ST
colour, CGA and Atari ST mono look kits.

- `art/`: the KILN project (models, palette, styles). `kiln build` writes into `godot/assets/kiln/`.
- `godot/`: the Godot 4.7 project. `scenes/room.gd` builds the room and puts the manifest's models (sorted by name)
  on a 3x3 grid of pedestals, each scaled to 1.1 m; `scenes/player.gd` is the first-person walker; `scenes/dev_panel.gd` the F1 dev panel.

## Controls

| Key | |
|---|---|
| W A S D | walk |
| Shift | run |
| mouse | look (Esc frees the mouse, a click captures it again) |
| 1 / 2 / 3 | Atari ST colour / CGA / Atari ST mono |
| Tab | next look |
| F1 | dev panel: tune the look live (the mouse is free while it's open) |

## Dev panel (#369)

F1 opens a column on the left, above the retro pass, that drives the look kit's `Retro` node and the models:

- retro effect on / off (off: the plain render underneath); dither on: screen (fixed to the screen), view (fixed to
  view directions: steady while you turn) or world (fixed to surfaces; Forward+ only, best with `noise`);
- snap turning to pixels: the view turns in steps of one low-res pixel, so the image steps cleanly;
- pattern, lines (40-480), pixel aspect (0.5-2.0), strength (0-1), light bands (2-8: the toon `bands` of every model
  material);
- palette: presets (Atari ST, CGA, mono, riso, LCD, blueprint, neon, sunset), colour count - / + (1-16; + adds a random
  colour), a colour picker and a randomise button per swatch, randomise all;
- Save preset: writes `<name>.style.toml` (`extends = "retro_st"` with the panel's `[look]` values) and
  `<name>.pal.yaml` (PAGAN format) into `user://presets/` (the panel shows the folder) and copies the style to the
  clipboard. To use one, copy the style into `art/styles/` and the palette into `art/palettes/`.

Switching kit (1 / 2 / 3, Tab) starts from that kit's own settings; light bands stay as set.

## Build and run

From the repo root:

```sh
(cd examples/retro_room/art && ../../../.venv/bin/kiln build)    # the art
godot --headless --path examples/retro_room/godot --import       # import it
godot --path examples/retro_room/godot                           # play
godot --headless --path examples/retro_room/godot -s res://tests/check_room.gd   # smoke test: CHECK_OK / CHECK_FAIL
```

## Export

```sh
examples/retro_room/export.sh          # art, import, godot/build/RetroRoom.exe (Windows, PCK embedded)
examples/retro_room/export.sh v0.32.0  # also copies it to D:\cernbox\Documents\GMT\RetroRoom-<tag>-<hash>.exe
SKIP_ART=1 examples/retro_room/export.sh   # export whatever godot/assets/kiln holds, without rebuilding the art
```

Needs the Godot 4.7.2 export templates.
