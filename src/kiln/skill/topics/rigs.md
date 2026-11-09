# Rigs

Characters, rigs, skins and sockets; rig notation.

## Characters, rigs and animation

- **Characters for the soft styles:** bean/pear body (one capsule, radius 0.25-0.35), stubby limbs (capsules
  0.07-0.1 thick), big eyes (white sphere ~0.1 + black pupil ~0.04 pushed slightly forward), tiny or no mouth.
  Hats, helmets, hair: separate shapes on top, crisp seams. Heads on caricatures: an ellipsoid blended into the
  body with a big nose ellipsoid blended in. Keep hands simple (a sphere or mitten).
- **Rig** what moves: give it an `id`, then `rig: { id: { pivot: [joint], parent: id } }`. Pivots are the joint
  positions (hip, shoulder, hinge, axle). Without a pivot a part turns about its box centre (W109); `skeleton: humanoid` joints get theirs at the joint.
- **Skin:** `rigid` (each part moves as one piece: robots, machines, props, toys) or `soft` (one mesh that bends
  where parts blend: creatures, bean characters). `separate: true` keeps a part rigid inside a soft skin
  (detachable helmet). Rigid joints that turn far (ragdolls): `union: per_bone`, so no turn opens the mesh.
- **Animations:** explicit `poses` (one per frame, per part: offset/rotate/scale) or a `cycle` that writes the
  poses for you: walk, waddle, hop, bob, spin, swing, breathe, wave, chain (`kiln docs animations`). Both together: the cycle
  moves everything, and parts named in the poses follow the poses (walking while carrying).
- **CC0 clip libraries:** a `skeleton: humanoid` character plays imported clips
  (`walk: { import: imports/clips.glb, clip: Walking_A }`); any other skeleton (quadrupeds, birds) plays them through
  `skeleton: { map: { <part id>: <clip joint>, ... }, root_motion: <clip joint> }` (`kiln docs humanoids`, "Clips on any skeleton").
- **Cloth and flags:** split them into 3-4 segments along their length, each its own id parented to the previous one
  (pivots on the seams), crisp seams (`blend: 0`), `skin: soft`, and animate with `cycle: { type: chain, parts: [...] }`. Check every animation with
  `kiln preview <name> --pose <animation>`: the filmstrip shows each frame from 3/4 front and both sides; `--views`,
  `--pitch` and `--size` pick the views and tile size, `--frame 3` (or `0,4`) one frame up close.
- Gameplay data on parts: `rig: { helmet: { meta: { hitzone: head, detachable: true, socket: [0, 1.6, 0.1] } } }` ->
  node metadata in Godot and in the manifest, which also gives every part's box (`aabb`) for hit zones.
- Detachables (`separate: true`) are meshed on their own, so they may overlap the body and leave no hole when removed.
- Points the game needs on a part (a weapon's muzzle, a hand slot, a catapult's load, a seat): `sockets` in the rig
  entry; they become nodes that move with the part.


## Rig and skin

```yaml
rig:
  leg_l: { pivot: [0.12, 0.26, 0] }                 # joint position; parent defaults to root
  arm_l: { pivot: [0.3, 0.6, 0], parent: root }
  head:  { pivot: [0, 0.8, 0], meta: { hitzone: head, seat: [0, 1.56, 0] } }
  helmet: { parent: head, meta: { detachable: true }, separate: true }
  arm:   { pivot: [0, 1.6, 0], sockets: { tip: [0, 3.9, -0.2], load: [0, 3.6, -0.5] } }
skin: soft
```

- Every part id is a bone/node. `pivot` is where it turns (hip, shoulder, hinge, axle); default: its box centre.
- A rig entry for `arm_l` also rigs its `mirror_id` twin (pivot mirrored; parent mapped to its twin if any).
- `skin: rigid`: each id is a separate mesh node that moves as one piece. By default all parts are one surface, cut
  where bones meet: fine while joints stay near their bind pose. `union: per_bone` makes each bone's parts their own
  closed surface; neighbouring bones overlap instead (a few hidden triangles), so turning a joint far (a ragdoll, an
  arm along the chest) never opens a hole. Blends between parts of different bones are then lost.
- `skin: soft`: one skinned mesh; weights come from each part's distance, so blended joints bend smoothly.
  `separate: true` makes a part its own closed, rigid mesh (detachable things): it may overlap the body (a helmet
  on a head) without fusing, and removing it leaves no hole. `under: { color: hair }` (with `separate: true`) paints
  the body where the part covers it (hair under a helmet; `material`, `gap`: how far from it still counts, 0.02 m),
  seen once it falls off. Check with `kiln preview <model> --detach`.
- `revealed: [arm_l]`: a part shown only once one of those is gone (a stump cap at the shoulder, under a
  detachable arm). It is its own piece (separate), hidden by KILN's .tscn scenes, `kiln_revealed_by` in its node's
  extras and `revealed_by` in the manifest's part: the game shows it when it removes the arm. Mirrored twins
  are revealed by the twins (`arm_r`). Previews (and `--vs`) leave it out like the game does; `--detach` shows it
  under the part taken off.
- `fold: true` (with `parent`): while none of its `revealed` parts is in the model, the part folds into its parent:
  its parts take the parent's id (and blend with it) and the entry goes, as if it had no id of its own; with one
  there, it's an ordinary revealed part. Without `revealed` it always folds: the library heads rig their hair
  `hair: { parent: head, fold: true }` (one `head`, as before the hair had an id), and a model opts in to hiding it
  under a helmet with `hair: { parent: head, revealed: [helmet], fold: true }` (see Template library).
- `gib: true` (or `gib: [upperarm_l, lowerarm_l, hand_l]`): the part comes off as a piece of its own. Besides the model,
  `kiln build` writes `models/<name>.gib.<id>.glb`: that part (and, with `true`, every part hanging from it) meshed on
  its own, so it's closed where it met the body; static, at rest, in the model's frame (same origin as the model's glb),
  plain materials. Manifest: `gibs: { <id>: { glb, parts } }`. Mirrored twins get theirs. Pair it with a `revealed`
  stump cap on the body.
- `meta`: plain values or flat lists (points: `[x, y, z]`, model space) for game code: Godot node metadata
  (`get_meta("extras")`; on soft skins, bone metadata: `skeleton.get_bone_meta(i, "extras")`) and the manifest.
  Mirrored twins get the same meta (not mirrored).
- `sockets`: named points on the part (model space, as built): a muzzle, a hand slot, a trebuchet's load. Each is an
  empty child node `<id>_<name>` that moves with the part (Godot: a Node3D under a BoneAttachment3D on soft skins), and
  the manifest gives its position and its offset from the pivot. Mirrored twins get mirrored sockets.
