# Retro room

A walkable demo of KILN's retro looks (#362): nine models on pedestals in a closed room, seen through the Atari ST
colour, CGA and Atari ST mono look kits.

- `art/`: the KILN project (models, palette, styles). `kiln build` writes into `godot/assets/kiln/`.
- `godot/`: the Godot 4.7 project. `scenes/room.gd` builds the room and puts the manifest's models (sorted by name)
  on a 3x3 grid of pedestals, each scaled to 1.1 m; `scenes/player.gd` is the first-person walker.

## Controls

| Key | |
|---|---|
| W A S D | walk |
| Shift | run |
| mouse | look (Esc frees the mouse, a click captures it again) |
| 1 / 2 / 3 | Atari ST colour / CGA / Atari ST mono |
| Tab | next look |

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
