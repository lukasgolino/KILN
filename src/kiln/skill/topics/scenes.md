# Scenes

Other models placed in a model (`instances:`), assemblies of separate models (`mount:`), and checking that they fit.

## Instances and assemblies

Parts of one assembly built as separate models (a watch case, its caseback, its movement) share a frame: `mount: { to:
case, at: [x, y, z], rotate: [x, y, z] }` at the top of the part's model says where it sits on `to`; it skips the
ground checks (W106, W123), goes in the manifest (`mount`) for a game to snap it on, and `kiln preview case --with
lid,movement` shows them together. `kiln fit case movement` checks they fit.

Placing other models (a desk with its props, a tray of screws): `instances: [{ model: screw, at: [x, y, z], rotate:
[x, y, z], scale: 1, id: tray }]` at the top of the model. Each is that model's own build (its mesh at its own cell size
and budget: fine screws stay fine in a coarse scene), merged in after the scene is built. `at`/`rotate` are in the
scene's model space: `rotate` turns the instance about its own origin (its `origin:`, as its own glb), then `at`
places that origin (a flip is `rotate: [0, 180, 0]`; there is no mirror); `id` is the part it moves with
(default root; not mirrored). A scene `lod:` builds every instance at the same share of its triangles. Materials are
read in the scene's style; an instance's decals and textures come along. An instance whose model bakes maps, and every
instance in a scene that does, is a reference: a node `kiln_ref_<model>_<n>` that KILN's Godot scene fills with the
model's own scene (maps and all); a mapped scene's previews don't draw them. In an unskinned or rigid scene a model placed several
times is one mesh in the glb with a node per copy. A scene may be instances only (no `parts:`). Lint sees the scene with its
instances (its size, its pieces: an instance joining two parts makes them one), and holds the model's own parts to
its budget. `kiln build screw` rebuilds the models that place it. Missing models:
E011; templates, terrains, scatters and circles (a model placing itself round about) are errors.
