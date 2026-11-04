# Effects

Effects: pre-rolled particle descriptions (effect.json).

## Effects

A burst (an explosion's debris, sparks, puffs of smoke) as other models thrown out over time. KILN doesn't play
effects: `kiln build` writes `models/<name>.effect.json` (manifest `effect`) with every particle already rolled from
the seed, so an engine-side player shows exactly what `kiln preview <model> --effect` shows.
The preview plays it in 8 evenly spaced frames; `--at 0,0.1,0.25,0.5,1` (seconds) gives a contact sheet at those
times instead (tune particle sizes there). Each piece's `fade` is drawn as ordered dithering (a reversed envelope shows
as pieces that appear instead of vanish) and a `floor` as a thin grid.

```yaml
effect:
  seed: 3                    # same seed, same particles
  duration: 1.2              # seconds (default: the last particle's end); loop: false
  emit:
    - model: spark           # another model in the project (its glb; `origin: center` so it spins about its middle)
      count: 12
      at: [0, 0.5, 0]        # spawn point, spread: 0.1 (a ball's radius)
      delay: [0, 0.2]        # seconds, a number or [lo, hi]; life: [0.5, 1.0]
      velocity: { min: [-0.5, 1, -0.5], max: [0.5, 2, 0.5] }   # m/s, or one [x, y, z]
      burst: [1, 2]          # m/s outward, any direction (added to velocity)
      gravity: 9.8           # m/s^2 down, or [x, y, z]; drag: 1.5 (1/s)
      spin: [-90, 90]        # degrees/s about a random axis
      scale: { 0: 0.2, 0.2: 1, 1: 0 }   # over life (0..1), linear between keys; or one number
      heat: { 0: 1, 1: 0 }   # for the game's shader (e.g. into the attr it reads)
      fade: { 0.8: 1, 1: 0 } # opacity for the game (1 = solid); previews dither it
      bounce: 0.3            # with a floor: vertical speed kept at a hit (0 = stops dead); friction: 0.6 (horizontal)
      settle: true           # with a floor: rest once slower than 0.2 m/s on it (no motion, no spin)
  floor: 0                   # optional: a height (effect frame) debris bounces on and settles on, instead of falling through
```

The JSON: `format`, `duration`, `loop`, `seed`, `motion` (the formula), `emitters` (model, `glb`, `godot_scene`,
`origin`, gravity vector, drag, envelopes as `[life fraction, value]` pairs) and `particles` (`emitter`, `delay`,
`life`, `at`, `velocity`, `axis`, `spin`; with a `floor`: `hits`, each `[age, position, velocity]` where the motion
starts again from that position and velocity, `[0, 0, 0]` = resting there without spin). Position at `age = t - delay`
(alive while 0 <= age <= life):
`at + g/k*age + (velocity - g/k)*(1 - exp(-k*age))/k` with drag k > 0, `at + velocity*age + g*age^2/2` with k = 0.
E011 when an emitted model doesn't exist.
