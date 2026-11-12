# Animations

Animation notation: poses, cycles, imported clips.

## Animations

Names are letters, digits, `_` or `-`, any case (imported clips can keep their library names: `Idle_A`); two names
that differ only in case are an error.

```yaml
animations:
  wave:
    fps: 8
    loop: false                # default true (Godot loops it: glTF name "<name>-loop")
    interpolation: linear      # linear | step
    poses:                     # one per frame; a missing part = its rest pose
      - {}
      - { arm_r: { rotate: [0, 0, -120] } }
      - { arm_r: { rotate: [0, 0, -150] }, root: { offset: [0, 0.02, 0] } }
  walk: { fps: 12, cycle: { type: waddle, legs: [leg_l, leg_r], arms: [arm_l, arm_r] } }
  carry:                       # a cycle plus poses: poses repeat over the cycle's frames, and a part named in a
    fps: 12                    # pose follows the pose instead of the cycle (walking legs + arms holding a crate)
    cycle: { type: walk, legs: [leg_l, leg_r], arms: [] }
    poses: [{ arm_l: { rotate: [-70, 0, 0] }, arm_r: { rotate: [-70, 0, 0] } }]
```

Pose fields per part: `offset: [x, y, z]` (metres), `rotate: [x, y, z]` (degrees, about the pivot), `scale: s` or
`[x, y, z]` (squash and stretch). Signs: positive x tips the part's top towards the front (+Z), so a hanging leg or arm
swings backwards with positive x and forwards with negative x; a drawbridge hinged at its bottom lowers forwards with
positive x. About z: negative raises a right arm (-X side), positive raises a left arm. About y: positive turns
left (counter-clockwise seen from above).

Point instead of turning: `aim: [x, y, z]` (a model-space point, metres) turns the part so it points there (from its
pivot to its only child's joint, else its own far end), the shortest way from where its parent leaves it.
`reach: [x, y, z]` on the upper of two parts (upper arm + forearm, thigh + shin) bends both so the lower one's end is
on the point (out of reach: straight toward it); `pole: [x, y, z]` picks where the middle joint goes (default: the way
the chain bends at rest; a straight leg's knee forward, other straight chains' joint back). One of rotate, aim and
reach per part; reach sets its child's turn. Raise a wand overhead: `arm_r: { reach: [-0.2, 2.1, 0.1] }`.
`kiln preview <m> --pose <anim> --json` lists each part's end per frame (`ends`) to check a pose without looking.

Cycles (8 frames unless `frames:`):

| type | options (defaults) |
|---|---|
| `walk` | `legs` [leg_l, leg_r] (a humanoid: upperleg_l/_r), `arms` [arm_l, arm_r] (upperarm_l/_r), `body` root, `swing` 30, `arm_swing` 25, `bounce` 0.02, `knee` 40, `knee_rest` 5, `elbow` 20, `lean` 0 (the `torso`, default spine, forward), `crouch` 0 (thighs forward, knees twice that) |
| `waddle` | as walk + `roll` 8 (side-to-side), `swing` 18, `knee` 20, `elbow` 15 |
| `run` | as walk: `swing` 45, `arm_swing` 40, `knee` 80, `knee_rest` 15, `elbow` 85, `lean` 10 |
| `sneak` | as walk: `swing` 20, `arm_swing` 10, `knee` 30, `elbow` 45, `lean` 15, `crouch` 15 |
| `hop` | `part` root, `height` 0.2, `squash` 0.1 |
| `bob` | `part`, `amount` 0.05 |
| `spin` | `part`, `axis` y, `direction` 1 |
| `swing` | `part`, `axis` y, `angle` 20 |
| `breathe` | `part`, `amount` 0.03 |
| `wave` | `arms` (the last one waves), `raise` 150, `angle` 20 |
| `chain` | `parts` [ids in order from the root out; default: every id in file order], `axis` y, `angle` 15, `phase` 0.15: a travelling wave for flags, tails, tentacles, ropes |

Gaits bend lower limbs on a humanoid (`skeleton: humanoid`: lowerleg/lowerarm; listing `legs:` / `arms:` drops these
defaults) or what `knees:` / `elbows:` name: knees fold by `knee` while the leg swings forward, plus `knee_rest`;
elbows hold `elbow`, more as the arm swings forward. Then the feet stay level and the body rides so the lower ankle
stays where it was at rest (no floating or sinking; `bounce` is unused). Each limb swings about its own axis square to
the front, so a T-posed arm swings rather than twists. A model without lower limbs walks as before.
