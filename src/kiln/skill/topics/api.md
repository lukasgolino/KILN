# Api

Generator scripts with kiln.api: signatures, what each does, and worked examples.

## Generator scripts (`kiln.api`)

For walls with merlons, fences, stairs, rings of pillars, forests of trees, crowds, or a scene placing other models'
parts: write a short Python script with `kiln.api`, run it, and treat the resulting `.kiln.yaml` like any other model
(lint, preview). Keep the script next to the models (`models/<name>.py`) so it can be re-run.

```python
from kiln.api import model, part, write_model
legs = [part("capsule", "wood", from_=[x, 0, z], to=[x, 0.7, z], radius=0.03) for x in (-0.4, 0.4) for z in (-0.25, 0.25)]
top = part("box", "wood", at=[0, 0.72, 0], size=[1.0, 0.04, 0.6], round=0.01)
write_model("models/table.kiln.yaml", model("table", [top, *legs], cls="furniture"))
```

## Reference

| function | what it does |
|---|---|
| `part(shape, color=None, material="default", id=None, **params)` | one part as a dict. Shape parameters (`at`, `size`, `radius`, `rotate`, ...) go in the shape; part-level options (`blend`, `blend_to`, `cut`, `intersect`, `mirror`, `mirror_id`, `array`, `shell`, `twist`, `scale`, `noise`, `pattern`, `gradient`, `decal`, `texture`, `loose`, `hard`, `bevel`, `chamfer`, `segments`, `fit`, `keep`, `uv`, `attr`, `aim`) are sorted out to the part. `from_=` stands for `from` (a Python keyword). A cut keeps `color` / `material` (they paint its walls) |
| `transform(parts, rotate=(0,0,0), about=(0,0,0), translate=(0,0,0), cut_only=None)` | parts turned by `rotate` (Euler degrees, as a part's) about `about`, then moved: positions, each part's own rotation, tube and lock points and facing, `aim`, array centres, decal and texture centres and axes. Mirrored parts are written out as pairs first (a mirror is about the origin). `cut_only=[ids]`: its unscoped cuts cut only those (a placed group's holes don't cut the scene). A decal axis that no longer lies along x, y or z, or an array turned off its axis, is a ValueError |
| `offset(parts, dx=0, dy=0, dz=0)` | `transform(parts, translate=(dx, dy, dz))` |
| `surface_point(profile, y, angle, at=(0,0,0))` | the point on a lathe at height `y` (its own frame) and `angle` degrees round y (0 = +z, 90 = +x), and the outward normal there, in model space. A cone's profile: `[[radius, -h/2], [radius_top, h/2]]` |
| `ring(count, radius, y, make, start_angle=0)` | `make(x, y, z, angle_degrees)` called at `count` points on a circle; returns its parts |
| `crenellated_wall(length, height, thickness, color, material, merlon=0.5, gap=0.4, round_edges=0.03, noise=0)` | a wall along x, merlons on top |
| `fence(length, posts, height=1, color="wood", material="wood", rails=2)` | posts and rails |
| `stairs(steps, width, rise, run, color="stone", material="stone")` | a flight of steps |
| `tower(radius, height, color="stone", roof_color="red", material="stone")` | a round tower with a cone roof |
| `tree(height=3, crown=1, seed=1, bark="brown", leaves="green", blobs=4)` | a trunk and a lumpy crown |
| `model(name, parts, cls="prop", description="", **fields)` | the model dict (`rig=`, `skin=`, `animations=`, `variants=`, `style=`, `palette=`, ...) |
| `write_model(path, data)` / `dumps(data)` | write it as YAML (short lists inline) |

## A ring of tiles on a cone

```python
from kiln.api import part, surface_point
roof = part("cone", "red", at=[0, 2, 0], radius=1.0, radius_top=0, height=1.0)
tiles = []
for row, y in enumerate([-0.4, -0.2, 0.0]):
    for k in range(12):
        p, n = surface_point([[1.0, -0.5], [0.0, 0.5]], y, k * 30 + row * 15, at=[0, 2, 0])
        tip = [p[i] + n[i] * 0.03 for i in range(3)]
        tiles.append(part("cylinder", "crimson", radius=0.08, height=0.02, aim=[p, tip]))  # flat on the slope
```

`aim: [[base], [tip]]` stands a part's y axis on the line between the points: along the normal, it lies flat on the
surface. Placing another model's parts: read them (`yaml.safe_load(open("models/x.kiln.yaml"))["parts"]`), `transform`
them into place (with `cut_only` for their holes) and append.
