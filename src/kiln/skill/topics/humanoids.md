# Humanoids

Humanoids, CC0 clip libraries, clips on any skeleton, attachments for CC0 characters.

## Humanoids and clip libraries

`skeleton: humanoid` names a character's parts after the standard joints: `hips`, `spine`, `chest`, `head`,
`upperarm_l`, `lowerarm_l`, `hand_l`, `upperleg_l`, `lowerleg_l`, `foot_l` (and `_r`, usually by `mirror_id`;
optional `toes_l/_r`). Parents come from the standard hierarchy and pivots default to the joints (limbs at the end of
their longest capsule/cylinder/cone/tube nearest the parent, else of their box; hands, feet and toes where the limb
above them ends, on their own box: wrist, ankle; spine, chest, head at their bottom); give `rig:` pivots where that guess is off. Skin defaults to
soft. The manifest maps each joint to its KayKit, Mixamo and Godot SkeletonProfileHumanoid name.

Then any CC0 clip library on the same joints (KayKit Character Animations' `Rig_Medium_*.glb`: Idle_A, Walking_A,
Running_A, Death_A, Hit_A, Throw, Jump_*, ... ~80 clips) plays on the character, retargeted when it's built. KILN
ships two of them (26 clips: idles, walks, runs, jumps, hits, deaths, throw, pick up): `kiln clips` lists them,
`kiln clips add` copies them into `imports/kaykit-animations/`:

```yaml
animations:
  idle:  { import: imports/kaykit-animations/Rig_Medium_General.glb, clip: Idle_A }
  walk:  { import: imports/kaykit-animations/Rig_Medium_MovementBasic.glb, clip: Walking_A }
  death: { import: imports/kaykit-animations/Rig_Medium_General.glb, clip: Death_A, loop: false, fps: 30, speed: 1 }
```

Each bone points where the clip's bone points (the clip's rest pose may be a T-pose; yours can be anything), bone
lengths stay yours, and the hips move by the clip's motion scaled to your hip height. Check with `--pose <name>`.

Clips made for another body type (KayKit's are chibi: splayed arms, deep knee bends on an adult body) can be toned per
animation: `retarget: { keep: { upperarm: 0.35, lowerleg: 0.5 }, offset: { upperarm_l: [0, 0, 12] } }`. `keep` is the
share of each joint's turn away from rest it keeps (0 = held at rest, 1 = as the clip; a base name like `upperarm`
covers both sides; children follow), `offset` a fixed turn in degrees (model axes) added on top.

`godot_bonemap = true` (kiln.toml, off by default; output inside a Godot project) writes `models/<name>.bonemap.tres`
for each humanoid with a skeleton in its glb (soft skins; rigid ones with `merge_rigid`), clip carriers included: a
`BoneMap` on `SkeletonProfileHumanoid` from the manifest's names (`root` -> `Root`, `hips` -> `Hips`, `upperleg_l` ->
`LeftUpperLeg`, ...), and points the glb's `.import` at it (`_subresources` -> `PATH:Skeleton3D` ->
`retarget/bone_map`; the rest of the sidecar stays). Godot then retargets on import: any humanoid clip made for the
profile (Mixamo, Godot's own retargeted libraries) plays on the character with no renaming in the game. The glb itself
doesn't change, but in Godot **the bones take the profile's names** (`Hips`, `LeftUpperLeg`; unmapped bones keep
theirs), the skeleton node becomes `%GeneralSkeleton`, and clip tracks follow: node paths, `find_bone("hips")` and
BoneAttachment3D names in game code must use the new names (manifest `humanoid` has them; the entry says
`godot_bonemap`). Use it for a new game or one sharing clips with other humanoids; leave it off where code already
names KILN's bones. Turning it off removes the files and the `.import` setting again (Godot reimports with KILN's
names).

### Clips on any skeleton (joint map)

A creature that isn't a humanoid (a quadruped, a bird) plays a clip library made for another armature through a
map from its part ids (bones) to the clip's joints:

```yaml
skin: rigid
rig: { body: { pivot: [0, 0.5, 0] }, neck: { pivot: [0, 0.55, 0.3], parent: body }, head: { parent: neck }, ... }
skeleton:
  map:
    body: Torso2
    neck: { joint: Neck1, child: head }        # child: the bone whose direction aims this one
    head: Head
    fl_up_l: { joint: FrontUpperLeg.L, child: fl_low_l }
    fl_low_l: FrontLowerLeg.L
    tail1: { joint: Tail1, child: tail2 }
    tail2: Tail4
  root_motion: Torso   # the clip joint whose movement moves the model
animations:
  walk: { import: imports/Horse.glb, clip: Walk, retarget: { keep: { tail1: 0.5 } } }
```

Each mapped bone turns by its joint's world-space turn from the clip's rest. A bone with a `child` (another mapped
bone below it in the rig) is first turned so it points where the clip's joint points to the child's joint (as each
humanoid limb is), so a creature built in its own rest pose plays the clip; without `child` it keeps its parent's
aim. Unmapped bones follow their parent (a saddle on the body); unmapped clip joints are ignored (IK and pole
bones). The map changes nothing else: parents, pivots and skin come from `rig` and `skin` as usual, so give the
creature a hierarchy (`parent:`) and a skin (`rigid` or `soft`). `retarget: { keep, offset }` works per mapped bone
(by id, or a base name for `_l`/`_r` pairs).

`root_motion` names the clip joint whose movement moves the model: its movement, scaled by the moving bone's rest
height over the joint's rest height (a joint at ground level: unscaled), moves the bone mapped to that joint, or,
when it isn't mapped (`Torso` above), the bone mapped to its nearest mapped joint below it (`body`: `Torso2`). Without
`root_motion` nothing moves: the clip plays in place, rotations only (the body's bob and travel are dropped).

`skeleton: humanoid` uses the standard table and takes no map (`skeleton: { ... }` is for every other skeleton).
Findings (E007): a map key that isn't a part id (or is `root`), a `child` that isn't a mapped bone below it; (E008)
a mapped joint or `root_motion` the clip file doesn't have (with the nearest names). Check with `--pose <animation>`.


## Attachments for CC0 characters

A helmet, shield or banner made around a CC0 character (a KayKit Knight) instead of a KILN body:

```yaml
fit_to: { file: imports/Knight.glb, bone: head, meshes: [Knight_Head] }   # meshes: which ones to fit (default all)
parts:
  - sphere: { at: [0, 1.62, 0], radius: 0.8 }        # the coverage: where the helmet reaches
    shell: { thickness: 0.04, open: -y }
    fit: { to: target, gap: 0.015 }                   # wraps the character's own head, 1.5 cm off it
```

The model is made in the character file's space (its units); the glb is exported in the bone's space (root node
`<model>_on_<bone>`), so the game hangs it on that bone (Godot: a BoneAttachment3D); the manifest says `attach: { file,
bone }`. W113 warns when it sinks into the character. `kiln preview <model> --fit` shows it on the character and the
character without it.
