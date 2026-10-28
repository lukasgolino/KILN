# Using KILN output outside Godot

Everything KILN builds except the Godot scenes is plain glTF 2.0 plus JSON, so any engine with a glTF importer can use
it. Set `export = ["glb"]` (no `"godot"`) and point `output_dir` anywhere. The `.glb` files pass the Khronos glTF
Validator with no errors or warnings (with `atlas = true` it notes that images are URIs inside a GLB and that the
palettes aren't powers of two, both allowed).

These notes cover Unity, Unreal, Bevy, three.js and Defold. Engine importers change between versions: anything
marked *(check)* has to be checked in your version.

## What the files contain

| Thing | In the glTF | Notes |
| --- | --- | --- |
| Units, axes | metres, +Y up, front +Z (the glTF convention), standing on y = 0 | `origin:` moves the root node (the glb = model space minus `origin`); the manifest stays in model space and gives `origin` |
| Colours (default) | one material per colour and material preset: `baseColorFactor` (linear), `metallicFactor`, `roughnessFactor` | needs no setup: any PBR importer shows it. Material names are `<preset>_<colour>#rrggbb` |
| Glow | `emissiveFactor`, strength in `KHR_materials_emissive_strength` (optional extension) | importers without the extension show it at strength 1 |
| `vertex_colors = true` | `COLOR_0` (linear RGB) on white materials, one per preset (glowing and decal faces keep their own material) | the engine's material must multiply vertex colour into base colour, or everything is white |
| `atlas = true` | one material: `baseColorTexture` = `<name>.palette.png`, `metallicRoughnessTexture` = `<name>.material.png` (G roughness, B metallic), `emissiveTexture` = `<name>.glow.png` when something glows; UVs in `TEXCOORD_0` at each cell's centre | the PNGs are **referenced by URI**, not embedded: ship them next to the glb. Samplers are NEAREST, clamp, no mipmaps |
| `atlas_ao` | grey multiplier in `COLOR_0` | only shows where the material uses vertex colour |
| Decals | embedded PNG over the part's colour, own material, UVs in `TEXCOORD_0` | NEAREST sampler for images up to 256 px, else linear with mipmaps |
| `uv:` | projected UVs in `TEXCOORD_0`, or `TEXCOORD_1` when the atlas or a decal uses the first | manifest `uv.set` says which |
| `attr:` | float attributes `_<NAME>` (e.g. `_HEAT`); the first name (alphabetical) also in `COLOR_0` alpha (RGB white, or the colours with `vertex_colors`) | materials are opaque, so the alpha has no visual effect unless a material makes it opacity |
| Skins | `skin: soft`: one skinned mesh (`JOINTS_0`/`WEIGHTS_0`), `separate` parts as meshes on their bone nodes. `skin: rigid`: a node per part, each with its own mesh. `merge_rigid = true`: a rigid skin as one skinned mesh, every vertex 100% on its part's bone | soft skins have one extra unweighted joint, `kiln_skeleton`, on the root (Godot needs it; harmless elsewhere) |
| Animations | baked: translation, rotation and scale keys for every bone at the clip's fps, `LINEAR` or `STEP`; loops repeat the first pose at the end | loop clips are named `<name>-loop` (Godot's convention). Manifest `animations.<name>`: `gltf_name`, `loop`, `fps`, `duration` |
| Clip carriers | `animations_only` models hold the clips; models with `animation_library` have none in their glb | play the carrier's clips on the model (same bone names) |
| Part metadata | node `extras`: `kiln_part`, the part's `meta`, `kiln_revealed_by`; sockets are child nodes `<part>_<socket>` | the manifest has the same (and `aabb`, `node_path`); prefer it over extras |
| LODs, gibs, variants | separate glbs: `<name>.lod<N>.glb`, `<name>.gib.<part>.glb`, `<name>.<variant>.glb` (or swap tables / palette textures, see the reference) | LODs and gibs share the base glb's origin |
| Attachments (`fit_to`) | root node `<model>_on_<bone>` in that bone's space | parent it to the bone with an identity local transform |
| Effects | `models/<name>.effect.json`: every particle pre-rolled, plus the motion formula | engine-neutral; write a player in the game |

Godot-only (no glTF equivalent, skipped outside Godot): `models/*.tscn`, `looks/*.tscn`, `<name>.rim.png`, the
`.import` sidecars, toon bands, outlines, rim light, the look kit (sky, sun, tonemapper, SSAO, glow, fog, colour
grading), hiding `revealed_by` parts at start, and the `-loop` name handling. To approximate the look, read the style's
`.style.toml`: `[look]` has the sun direction (`sun_pitch`, `sun_yaw`), energy and colour, sky and ground colours,
ambient, tonemapper, exposure, saturation, `shader`/`toon_bands`, `outline`/`outline_color` and `rim_light*`;
`[materials]` the per-preset `rim`. Outlines are an inverted hull (back faces, pushed out along normals by `outline`
metres); rim is a fresnel term `pow(1 - dot(N, V), rim_light_power)` added to emission; toon is a quantised N·L
with `toon_bands` steps.

Things every engine has to do itself:
- Hide parts listed in `revealed_by` at start (stump caps) and show them when the named part comes off.
- Loop clips by the manifest's `loop`, not by the `-loop` name.
- Palette textures (`atlas = true`): point/nearest filtering, no mipmaps, no lossy or block compression, no
  resizing (they are 4 px per cell and not powers of two, e.g. 24x4). A cell bleeds into its neighbours otherwise.
- Convert manifest positions (pivots, sockets, `aabb`, `origin`, effect positions) the same way the importer
  converted the glb (axes, handedness, units).

Which colour mode to pick:
- Default (a material per colour): works everywhere unchanged; one draw call per colour.
- `atlas = true`: one standard textured PBR material per model; works in every engine below with only the texture
  settings above. The best choice outside Godot.
- `vertex_colors = true`: only where the engine's material reads vertex colours (three.js, Bevy out of the box;
  elsewhere a custom material).

## Unity

- Importer: glTFast (`com.unity.cloud.gltfast`) or UnityGLTF. Both convert to Unity's left-handed space by mirroring
  X; Y stays up, the model's front stays +Z (Unity's forward), 1 unit = 1 m. Mirror manifest X coordinates too.
- Vertex colours: glTFast's own shaders multiply `COLOR_0` into the base colour *(check)*; URP/Lit and Standard
  ignore vertex colours, so if materials are remapped to them, use a Shader Graph with a Vertex Color node.
- Palette textures: Filter Mode Point, Generate Mip Maps off, Compression None, Wrap Clamp, Non-Power of 2 None
  *(check what the importer set)*. Use Linear colour space: KILN's colours are linear.
- Animations: glTFast imports clips as legacy Animation or Mecanim clips depending on its import settings
  *(check)*. Rigid skins animate plain transforms, which both support. `humanoid` models: the manifest maps every
  joint to its Mixamo name, for building a Humanoid avatar.
- Custom `_NAME` attributes are not imported *(check)*; use `COLOR_0` alpha for the first `attr`.
- LODs: a `LODGroup` with the base glb as LOD 0 and `.lod<N>.glb` after it.
- Look: toon and outlines need a custom URP shader (or a renderer feature for outlines); the sun and sky from
  `[look]` go into a Directional Light and the Lighting settings, the tonemapper into a Volume's Tonemapping.

## Unreal

- Importer: Interchange (default in UE 5.x) or the glTF Importer plugin. Both convert Y-up metres to Z-up
  centimetres (scale x100). Check which way the model faces after import and rotate in the import options or in a
  parent actor *(check)*; convert manifest positions the same way.
- Unreal animates skeletal meshes. Use `skin: soft`, or `merge_rigid = true` for rigid skins, for anything with
  clips; a rigid skin without it imports as separate static meshes, and how its node animation comes through
  depends on the importer *(check)*. `separate` parts on soft skins sit on bone nodes: check they import, else
  attach them as components to bone sockets.
- Vertex colours: imported into the mesh's vertex colours, but the generated materials don't use them: make a material
  with a Vertex Color node into Base Color. Compare against `kiln preview` (sRGB/linear handling of vertex colours
  differs between importers *(check)*).
- Palette textures: Texture Group "2D Pixels (unfiltered)", Mip Gen Settings "NoMipmaps", a compression setting
  without block compression (e.g. "UserInterface2D (RGBA)"), sRGB on for the palette and off for `material.png`.
- `#` in material names may be replaced on import (asset names can't contain it); the colours are also in the
  manifest (`colors`, variant `swap`).
- LODs: import `.lod<N>.glb` into the Static Mesh / Skeletal Mesh editor's LOD slots ("Import LOD Level N").
- Look: toon, outlines and rim are a post-process or material function; the sun pitch/yaw go into a Directional
  Light, sky colours into a Sky Light or SkyAtmosphere.

## Bevy

- glTF's space is Bevy's (Y up, right-handed, metres), no conversion. Bevy's forward (`Transform::forward`) is -Z, so
  a KILN model faces Bevy's back: rotate it 180 degrees about Y, or aim it with the negated direction. Recent
  versions have a glTF loader setting to convert the coordinates *(check)*.
- Vertex colours: `StandardMaterial` multiplies the mesh's `COLOR_0` into the base colour, no setup.
- Custom attributes: register them with `GltfPlugin::add_custom_vertex_attribute("_HEAT", ...)` *(check)*.
- Extras: the `GltfExtras` component on each node's entity (`kiln_part`, `meta`).
- Animations: clips by name (`Gltf::named_animations`, names with `-loop`), played through an `AnimationPlayer`
  and `AnimationGraph` (API depends on the version); repeat by the manifest's `loop`.
- Palette textures: Bevy uses the glTF sampler (NEAREST, clamp) and doesn't generate mipmaps.
- LODs: `VisibilityRange` on each level's entity *(check)*.
- Look: toon/outline/rim need a custom material (`ExtendedMaterial`) or a crate; the tonemapper and exposure map to
  Bevy's `Tonemapping` and camera exposure.

## three.js / web

- `GLTFLoader`: no conversion (Y up, right-handed, metres). `Object3D.lookAt` turns +Z toward the target, so a KILN
  model faces what it looks at.
- Vertex colours: `COLOR_0` turns on `material.vertexColors` automatically.
- Custom attributes: kept, lower-cased: `geometry.attributes._heat`.
- Extras: `object.userData` (`kiln_part`, `meta`, `kiln_socket`).
- `KHR_materials_emissive_strength` is supported. URIs resolve relative to the glb's URL: serve the palette PNGs
  next to it. NEAREST samplers are applied as written.
- Animations: `AnimationMixer`; `clipAction(clip)` repeats by default; for clips with `loop: false` use
  `setLoop(THREE.LoopOnce)` and `clampWhenFinished = true`.
- LODs: `THREE.LOD` with `addLevel(object, distance)`.
- Look: `MeshToonMaterial` with a `gradientMap` of `toon_bands` texels (NearestFilter); `OutlineEffect` or an
  inverted hull for outlines; `renderer.toneMapping` for the tonemapper (ACES and AgX exist, Godot's filmic doesn't).

## Defold

- Model components load `.glb`/`.gltf` (Y up, right-handed; treat 1 unit as 1 m) *(check the minimum version)*.
- Every mesh is drawn with a Defold material (`.material` + shaders); glTF material factors aren't applied by the
  stock model material *(check)*, so the default colour mode needs per-colour Defold materials. Use `atlas = true` with a textured material and `<name>.palette.png` as its
  texture (UVs in `TEXCOORD_0`), or `vertex_colors = true` with a material whose vertex program passes the vertex
  colour through *(check that your version exposes the colour attribute)*.
- Palette textures: the material's sampler `filter_min`/`filter_mag` nearest, no mipmaps; a texture profile without
  compression for them.
- Animations: skinned models only (use `skin: soft` or `merge_rigid = true`); clips by name (with `-loop`) through
  `model.play_anim` *(check)*.
- No LOD system: switch the model's mesh by distance in a script, or skip LODs.
- Look: all in the material's shaders (toon, rim) and render script (outlines).
