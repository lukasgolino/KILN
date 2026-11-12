# Templates

The template library: bodies, heads, helmets, armour to extend.

## Template library

`kiln library` lists KILN's own templates: bodies (`body_slim`, `body_stocky`, `body_big`: standard joints, layered
clothes, gloves, boots, a `grip` socket per hand), heads (`head_young`, `head_old`, `head_bearded`, `head_stern`,
`head_goofy`, `head_female`), helmets (`helmet_kettle`, `helmet_nasal`, `helmet_barbute`, `helmet_great`,
`helmet_sallet`, `helmet_crown`: detachable, fitted to whatever head they go on) and armour (`armour_breastplate`,
`armour_pauldrons`, `armour_gauntlets`, `armour_cape`, `armour_hood`: shells fitted to the body). Combine them:

```yaml
name: sergeant
class: character
extends: [body_stocky, head_bearded, helmet_nasal, armour_cape]   # in order; a project template of the same name wins
variants: { blue: { swap: { cloth_red: cloth_blue } } }
animations:
  walk: { import: imports/Rig_Medium_MovementBasic.glb, clip: Walking_A }
```

or `kiln new model sergeant --extends body_stocky,head_bearded,helmet_nasal,armour_cape`. Their colours are the
library palette `people` (found without copying; copy it into palettes/ to change it). `extends` takes a list (bases
combine in order); `cut: <id>` (or `[ids]`) cuts only those ids (a helmet's face opening, not the face); `fit: { to: [ids] }` wraps
several parts. Fitted shells are their own meshes.

The heads' hair is the id `hair`, folded into `head` (`fold: true`, see Rig and skin), so helmets fit over it and
follow its lumps. To hide it under the helmet instead (as KayKit's helmets replace the hair), add to the model:

```yaml
rig:
  hair: { parent: head, revealed: [helmet], fold: true }   # hair hidden until the helmet (id helmet) comes off
```

The hair is then its own piece, hidden by the scenes and previews until the helmet comes off, and the helmet fits the
skull (`to: head`). Without a helmet it folds back into `head`. Leave it out for a crown (worn over the hair).
