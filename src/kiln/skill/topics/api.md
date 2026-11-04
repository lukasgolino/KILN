# Api

Generator scripts with kiln.api.

## Generator scripts (`kiln.api`)

For walls with merlons, fences, stairs, rings of pillars, forests of trees, crowds: write a short Python script
with `kiln.api` (`part`, `crenellated_wall`, `fence`, `stairs`, `tower`, `tree`, `ring`, `offset`, `model`,
`write_model`), run it, and treat the resulting `.kiln.yaml` like any other model (lint, preview). Keep the script
next to the models (`models/<name>.py`) so it can be re-run.
