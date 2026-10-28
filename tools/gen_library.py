"""Writes KILN's template library (src/kiln/library/*.kiln.yaml): bodies, heads, helmets and armour that combine with
`extends: [body_..., head_..., helmet_..., armour_...]`. Run from the repo root: `python tools/gen_library.py`.

Every body uses the same standard joints (hips 0.86 m, neck 1.42 m, shoulders x 0.21, hips x 0.11), so any head sits
on any body; helmets and armour are shells fitted to the parts they cover (`fit:`), so they follow any head or body.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kiln.api import dumps, part

OUT = Path(__file__).resolve().parent.parent / "src" / "kiln" / "library"
Part = dict[str, Any]


def mirrored(p: Part, twin: str) -> Part:
    return {**p, "mirror": "x", "mirror_id": twin}


def cut(shape: str, target: str, **params: Any) -> Part:
    """A cut that only cuts the parts with id `target` (a helmet's opening, not the face under it)."""
    return {shape: params, "cut": target}


def template(name: str, description: str, parts: list[Part], **fields: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "description": description, "template": True, "palette": "people"}
    out.update(fields)
    out["parts"] = parts
    return out


# --- bodies ---------------------------------------------------------------------------------------------------------

RIG = {
    "hips": {"pivot": [0, 0.86, 0]}, "spine": {"pivot": [0, 0.98, 0]}, "chest": {"pivot": [0, 1.16, 0]},
    "upperarm_l": {"pivot": [0.21, 1.35, 0]}, "lowerarm_l": {"pivot": [0.3, 1.1, 0]},
    "hand_l": {"pivot": [0.345, 0.87, 0.01], "sockets": {"grip": [0.36, 0.8, 0.07]}},
    "upperleg_l": {"pivot": [0.11, 0.84, 0]}, "lowerleg_l": {"pivot": [0.12, 0.48, 0]}, "foot_l": {"pivot": [0.12, 0.12, 0]},
    "head": {"pivot": [0, 1.42, 0]},
}  # fmt: skip


def body(name: str, description: str, girth: float, tunic: str, trousers: str, sleeves: str, skirt: float, belly: float = 0.0,
         shoulders: float = 0.0) -> dict[str, Any]:  # fmt: skip
    g = girth
    chest = 0.2 * g + shoulders
    parts: list[Part] = [
        mirrored(part("capsule", trousers, "fabric", "upperleg_l", **{"from": [0.11, 0.84, 0], "to": [0.12, 0.48, 0]}, radius=0.08 * g ** 0.5,
                      blend=0.04), "upperleg_r"),  # fmt: skip
        mirrored(part("capsule", trousers, "fabric", "lowerleg_l", **{"from": [0.12, 0.48, 0], "to": [0.12, 0.16, 0]}, radius=0.066 * g ** 0.5,
                      blend=0.03), "lowerleg_r"),  # fmt: skip
        mirrored(part("capsule", "leather_dark", "leather", "lowerleg_l", **{"from": [0.12, 0.34, 0], "to": [0.12, 0.12, 0.01]},
                      radius=0.076 * g ** 0.5), "lowerleg_r"),  # fmt: skip
        mirrored(part("box", "leather_dark", "leather", "foot_l", at=[0.12, 0.05, 0.05], size=[0.13, 0.1, 0.25], round=0.045, blend=0.03), "foot_r"),
        *([] if belly else [part("capsule", tunic, "fabric", "spine", **{"from": [0, 0.94, 0], "to": [0, 1.1, 0]}, radius=0.19 * g, blend=0.04)]),
        part("cone", tunic, "fabric", "hips", at=[0, 0.86 - skirt / 2, 0], radius=0.23 * g + 0.02 * skirt, radius_top=0.19 * g, height=skirt + 0.06,
             blend=0.02),  # fmt: skip
        part("capsule", tunic, "fabric", "chest", **{"from": [0, 1.14, 0], "to": [0, 1.19, 0]}, radius=chest, blend=0.05),
        # the collar sits on the chest's top (inside a broad chest it would be hidden)
        part("torus", "cloth_linen", "fabric", "chest", at=[0, max(1.385, 1.18 + chest), 0], radius=0.085, thickness=0.03, blend=0.02),
        {"band": {"fit": "spine", "at": [0, 0.97, 0], "width": 0.07, "thickness": 0.014}, "id": "spine", "color": "leather", "material": "leather"},
        part("box", "gold", "gold", "spine", at=[0, 0.97, 0.19 * g + belly + 0.02], size=[0.08, 0.07, 0.03], hard=True, chamfer=0.008),
        mirrored(part("capsule", sleeves, "fabric", "upperarm_l", **{"from": [0.21, 1.35, 0], "to": [0.3, 1.1, 0]}, radius=0.07 * g ** 0.5 + shoulders / 3,
                      blend=0.04), "upperarm_r"),  # fmt: skip
        mirrored(part("capsule", "cloth_linen", "fabric", "lowerarm_l", **{"from": [0.3, 1.1, 0], "to": [0.345, 0.88, 0.01]}, radius=0.057 * g ** 0.5,
                      blend=0.03), "lowerarm_r"),  # fmt: skip
        mirrored(part("sphere", "leather_dark", "leather", "hand_l", at=[0.355, 0.8, 0.02], radius=0.062, blend=0.03), "hand_r"),
    ]
    if belly:  # in place of the spine capsule, which it would hide
        parts.insert(5, part("ellipsoid", tunic, "fabric", "spine", at=[0, 1.0, 0.04], radii=[0.21 * g, 0.2, 0.18 * g + belly], blend=0.06))
    return template(name, description, parts, **{"class": "character", "skeleton": "humanoid", "skin": "soft", "budget": 14000, "rig": RIG})


# --- heads ---------------------------------------------------------------------------------------------------------

def head(name: str, description: str, skin: str, hair: str, style: str, nose: float = 1.0, eyes: float = 1.0, brow_tilt: float = 0.0,
         beard: str = "", jaw: float = 1.0, mouth: str = "lip") -> dict[str, Any]:  # fmt: skip
    """`style`: short, bald, long, bun, tuft."""
    s = {"color": skin, "material": "skin"}
    parts: list[Part] = [
        part("ellipsoid", id="head", **s, at=[0, 1.63, 0], radii=[0.19, 0.21, 0.19], blend=0.04),
        # the neck reaches into the collar: without it the head only touches the body, and a slightly different grid
        # (a helmet changes the model's size) can mesh the head as a floating piece
        part("capsule", id="head", **s, **{"from": [0, 1.33, 0], "to": [0, 1.5, 0]}, radius=0.08, blend=0.01),
        *([part("ellipsoid", id="head", **s, at=[0, 1.535, 0.04], radii=[0.15 * jaw, 0.1, 0.14], blend=0.07)] if beard != "full" else []),
        part("ellipsoid", id="head", **s, at=[0, 1.6, 0.185], radii=[0.032 * nose, 0.045 * nose, 0.04 * nose], blend=0.02),
        {**part("ellipsoid", id="head", **s, at=[0.185, 1.61, 0], radii=[0.03, 0.05, 0.035], blend=0.02), "mirror": "x"},
    ]
    if eyes > 1.2:  # big round eyes: white sclera with a pupil
        parts.append({**part("sphere", "white", "default", "head", at=[0.07, 1.645, 0.155], radius=0.04 * eyes / 1.4), "mirror": "x"})
        parts.append({**part("sphere", "eye", "default", "head", at=[0.07, 1.645, 0.155 + 0.03 * eyes / 1.4], radius=0.018 * eyes / 1.4), "mirror": "x"})
    else:
        parts.append({**part("ellipsoid", "eye", "default", "head", at=[0.065, 1.645, 0.165], radii=[0.026 * eyes, 0.034 * eyes, 0.02]), "mirror": "x"})
    brow = hair if hair != "hair_grey" or style != "bald" else "hair_grey"
    parts.append({**part("capsule", brow, "default", "head", **{"from": [0.035, 1.7 - brow_tilt, 0.172], "to": [0.1, 1.705 + brow_tilt, 0.16]},
                         radius=0.012 if style != "bald" else 0.016), "mirror": "x"})  # fmt: skip
    if beard != "full":
        parts.append(part("capsule", mouth, "default", "head", **{"from": [-0.04, 1.525, 0.168], "to": [0.04, 1.525, 0.168]}, radius=0.012))
    # the hair is its own id, folded back into `head` (the same mesh as before it had one) unless a model opts in with
    # `rig: { hair: { parent: head, revealed: [helmet] } }`: then under a helmet it's its own piece, hidden until the
    # helmet comes off, and the helmet fits the skull (as KayKit's do)
    h = {"color": hair, "material": "default"}
    if style in ("short", "tuft", "bun", "long"):
        parts.append(part("ellipsoid", id="hair", **h, at=[0, 1.67, -0.03], radii=[0.2, 0.185, 0.2], blend=0.01))
    if style == "short":
        parts.append(part("ellipsoid", id="hair", **h, at=[0.04, 1.77, 0.12], radii=[0.12, 0.06, 0.08], blend=0.02))
    if style == "tuft":
        parts.append(part("cone", id="hair", **h, at=[0.0, 1.87, 0.02], radius=0.07, radius_top=0.0, height=0.12, rotate=[0, 0, 15], blend=0.03))
        parts.append(part("cone", id="hair", **h, at=[0.06, 1.85, 0.06], radius=0.05, radius_top=0.0, height=0.1, rotate=[0, 0, -25], blend=0.03))
    if style == "bun":
        parts.append(part("sphere", id="hair", **h, at=[0, 1.8, -0.15], radius=0.075, blend=0.03))
    if style == "long":
        parts.append(part("ellipsoid", id="hair", **h, at=[0, 1.5, -0.08], radii=[0.21, 0.24, 0.13], blend=0.05))
    if style == "bald":  # a fringe of hair round the back
        parts.append(part("torus", id="hair", **h, at=[0, 1.6, -0.03], radius=0.17, thickness=0.045, rotate=[-12, 0, 0], blend=0.02))
    if beard == "full":
        parts.append(part("ellipsoid", hair, "default", "head", at=[0, 1.48, 0.09], radii=[0.15, 0.12, 0.11], blend=0.04))
        parts.append(part("ellipsoid", hair, "default", "head", at=[0, 1.555, 0.18], radii=[0.08, 0.025, 0.03], blend=0.02))
    if beard == "moustache":
        parts.append({**part("capsule", hair, "default", "head", **{"from": [0.0, 1.56, 0.19], "to": [0.07, 1.54, 0.17]}, radius=0.018), "mirror": "x"})
    return template(name, description, parts, rig={"hair": HAIR})


HAIR = {"parent": "head", "fold": True}

# --- helmets (separate, fitted to whatever head they go on) -----------------------------------------------------------------

def helmet(name: str, description: str, parts: list[Part]) -> dict[str, Any]:
    return template(name, description, parts, rig={"helmet": {"parent": "head", "separate": True, "meta": {"detachable": True}}})


def dome(at: list[float], radius: float, thickness: float = 0.03, color: str = "steel") -> Part:
    return {**part("sphere", color, "metal", "helmet", at=at, radius=radius), "shell": {"thickness": thickness, "open": "-y"},
            "fit": {"to": "head", "gap": 0.018}}  # fmt: skip


HELMETS = [
    helmet("helmet_kettle", "a kettle hat: a fitted dome and a wide brim", [
        dome([0, 1.72, 0], 0.32),
        part("cylinder", "steel", "metal", "helmet", at=[0, 1.715, 0], radius=0.32, height=0.022, sides=16, hard=True),
    ]),
    helmet("helmet_nasal", "a nasal helm: a pointed dome to the brow and a nose bar", [
        dome([0, 1.66, 0], 0.34),
        part("cone", "steel", "metal", "helmet", at=[0, 1.86, -0.01], radius=0.12, radius_top=0.0, height=0.12, sides=8, hard=True),
        part("box", "steel", "metal", "helmet", at=[0, 1.6, 0.215], size=[0.035, 0.13, 0.025], hard=True, chamfer=0.006),
    ]),
    helmet("helmet_barbute", "a barbute: down to the jaw with a T-shaped face opening", [
        dome([0, 1.47, -0.02], 0.48),
        cut("box", "helmet", at=[0, 1.645, 0.2], size=[0.24, 0.055, 0.25]),
        cut("box", "helmet", at=[0, 1.55, 0.2], size=[0.1, 0.15, 0.25]),
    ]),
    helmet("helmet_great", "a great helm: a flat-topped steel pot with an eye slit and breaths", [
        # open at its centre: from the shoulders to above the tallest hair (head_goofy's tuft)
        {**part("cylinder", "steel", "metal", "helmet", at=[0, 1.45, 0], radius=0.26, height=1.0, sides=16), "hard": True,
         "shell": {"thickness": 0.025, "open": "-y"}},
        cut("box", "helmet", at=[0, 1.65, 0.2], size=[0.3, 0.035, 0.2]),
        {**cut("cylinder", "helmet", at=[0.09, 1.58, 0.25], radius=0.012, height=0.1, rotate=[90, 0, 0]), "array": {"count": 3, "step": [0, -0.05, 0]},
         "mirror": "x"},  # fmt: skip
        part("box", "gold", "gold", "helmet", at=[0, 1.6, 0.255], size=[0.03, 0.26, 0.02], hard=True),
        part("box", "gold", "gold", "helmet", at=[0, 1.7, 0.255], size=[0.26, 0.03, 0.02], hard=True),
    ]),
    helmet("helmet_sallet", "a sallet: a rounded dome with a flared tail and an eye slit", [
        dome([0, 1.6, -0.03], 0.38),
        cut("box", "helmet", at=[0, 1.645, 0.22], size=[0.3, 0.04, 0.2]),
        part("box", "steel", "metal", "helmet", at=[0, 1.55, -0.24], size=[0.36, 0.025, 0.2], rotate=[-30, 0, 0], hard=True, chamfer=0.006),
    ]),
    helmet("helmet_crown", "a crown: a gold band with points and jewels", [
        # a ring open at both ends (a shell is open on one side only: its bottom would cross the head), clear of the hair
        part("cylinder", "gold", "gold", "helmet", at=[0, 1.75, 0], radius=0.23, height=0.12, sides=16, hard=True),
        cut("cylinder", "helmet", at=[0, 1.75, 0], radius=0.205, height=0.3, sides=16),
        {**part("cone", "gold", "gold", "helmet", at=[0, 1.82, 0.22], radius=0.035, radius_top=0.0, height=0.08, sides=4), "hard": True,
         "array": {"count": 8, "around": "y", "center": [0, 0, 0]}},  # fmt: skip
        {**part("sphere", "cloth_red", "glass", "helmet", at=[0, 1.74, 0.235], radius=0.02, sides=6), "hard": True,
         "array": {"count": 4, "around": "y", "center": [0, 0, 0]}},  # fmt: skip
    ]),
]


# --- armour (fitted to the body parts they cover) -----------------------------------------------------------------------------

def shell(color: str, ident: str, to: str | list[str], shape: str, thickness: float = 0.045, gap: float = 0.025, material: str = "metal", **params: Any) -> Part:
    return {**part(shape, color, material, ident, **params), "shell": {"thickness": thickness, "open": "-y"}, "fit": {"to": to, "gap": gap}}


ARMOUR = [
    template("armour_breastplate", "a steel breastplate over the chest and belly", [
        shell("steel", "breastplate", ["chest", "spine", "upperarm_l", "upperarm_r"], "ellipsoid", at=[0, 0.98, 0.04], radii=[0.32, 0.5, 0.32]),
    ], rig={"breastplate": {"parent": "chest"}}),
    template("armour_pauldrons", "steel shoulder plates", [
        {**shell("steel", "pauldron_l", ["upperarm_l", "chest"], "sphere", at=[0.24, 1.28, 0], radius=0.15), "mirror": "x", "mirror_id": "pauldron_r"},
    ], rig={"pauldron_l": {"parent": "upperarm_l"}}),
    template("armour_gauntlets", "steel gauntlets over the hands and wrists", [
        {**shell("steel", "gauntlet_l", ["hand_l", "lowerarm_l"], "sphere", at=[0.35, 0.84, 0.02], radius=0.12), "mirror": "x", "mirror_id": "gauntlet_r"},
    ], rig={"gauntlet_l": {"parent": "hand_l"}}),
    template("armour_cape", "a cloak over the shoulders and back, with gold clasps", [
        {**shell("cloth_red", "cape", ["chest", "spine", "hips", "upperarm_l", "upperarm_r"], "box", thickness=0.025, gap=0.015, material="fabric",
                 at=[0, 1.1, -0.35], size=[0.9, 0.9, 0.7]), "shell": {"thickness": 0.025}},  # fmt: skip
        {**part("sphere", "gold", "gold", "cape", at=[0.15, 1.37, 0.12], radius=0.035), "mirror": "x"},
    ], rig={"cape": {"parent": "chest"}}),
    template("armour_hood", "a cloth hood with a face opening", [
        shell("cloth_brown", "hood", "head", "sphere", thickness=0.03, gap=0.015, material="fabric", at=[0, 1.48, -0.03], radius=0.45),
        cut("box", "hood", at=[0, 1.6, 0.25], size=[0.26, 0.34, 0.3]),
    ], rig={"hood": {"parent": "head"}}),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    models = [
        body("body_slim", "a slim humanoid body (standard joints) in a long green coat; extend with a head", 0.85, "cloth_green", "cloth_grey", "cloth_green", 0.3),
        body("body_stocky", "a stocky humanoid body (standard joints) in a tunic over trousers, belt, gloves and boots; extend with a head",
             1.0, "cloth_red", "cloth_brown", "cloth_red", 0.16),  # fmt: skip
        body("body_big", "a big humanoid body (standard joints) with a belly and broad shoulders, in blue; extend with a head",
             1.18, "cloth_blue", "cloth_brown", "cloth_blue", 0.12, belly=0.08, shoulders=0.03),  # fmt: skip
        head("head_young", "a young face with short brown hair", "skin_light", "hair_brown", "short"),
        head("head_old", "an old face: bald, grey fringe, big nose, moustache", "skin_mid", "hair_grey", "bald", nose=1.5, beard="moustache"),
        head("head_bearded", "a red full beard and short hair", "skin_light", "hair_red", "short", beard="full", jaw=1.1),
        head("head_stern", "a stern face: square jaw, angled brows, black hair", "skin_dark", "hair_black", "short", brow_tilt=-0.02, jaw=1.2,
             mouth="eye"),  # fmt: skip
        head("head_goofy", "a goofy face: big round eyes, big nose, a blond tuft", "skin_light", "hair_blond", "tuft", nose=1.6, eyes=1.6),
        head("head_female", "a woman's face with long black hair and a bun", "skin_mid", "hair_black", "long", nose=0.8, eyes=1.1),
        *HELMETS,
        *ARMOUR,
    ]
    for m in models:
        (OUT / f"{m['name']}.kiln.yaml").write_text(dumps(m), encoding="utf-8")
    print(f"wrote {len(models)} templates to {OUT}")


if __name__ == "__main__":
    main()
