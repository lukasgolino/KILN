# Run by `kiln build --verify-godot` (from a temp folder): loads every model KILN built and checks it against the
# manifest: the .glb and .tscn load, part nodes (or skeleton bones) exist, animations exist with the right loop
# flag, and every surface gets the style's material once the scene is ready. Attachments fitted to a CC0 character
# (the characters are copied into the sandbox) hang on their bone through a BoneAttachment3D and must land where they
# were made.
extends SceneTree

var _manifest: Dictionary = {}
var _scenes: Array = []
var _attached: Array = []  # [model, character, attachment on its bone, the attachment alone]
var _frames := 0
var _failures := 0


func fail(message: String) -> void:
	printerr("KILN_VERIFY_FAIL ", message)
	_failures += 1


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	var path: String = args[0] if args.size() > 0 else "res://assets/kiln/manifest.json"
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY or typeof(parsed.get("models")) != TYPE_DICTIONARY:
		printerr("KILN_VERIFY_FAIL cannot read manifest ", path)
		quit(1)
		return
	_manifest = parsed
	var base := path.get_base_dir()
	var characters: Dictionary = {}
	if args.size() > 1:
		characters = JSON.parse_string(FileAccess.get_file_as_string(args[1]))
	for name in _manifest["models"]:
		var entry: Dictionary = _manifest["models"][name]
		if entry.get("animations_only", false):  # a clip carrier: imported as an AnimationLibrary
			check_library(name, base.path_join(entry["glb"]), entry.get("animations", {}))
			continue
		var glbs: Array = [entry["glb"]]
		for v in entry.get("variants", {}):
			if entry["variants"][v].has("glb"):
				glbs.append(entry["variants"][v]["glb"])
			if entry["variants"][v].has("godot_scene") and not (load(entry["variants"][v]["godot_scene"]) is PackedScene):
				fail("%s variant %s can't load %s" % [name, v, entry["variants"][v]["godot_scene"]])
		for lod in entry.get("lods", []):
			glbs.append(lod["glb"])
		for glb in glbs:
			var packed = load(base.path_join(glb))
			if packed == null or not (packed is PackedScene):
				fail("%s can't load %s" % [name, glb])
		if entry.has("godot_scene"):
			var scene = load(entry["godot_scene"])
			if scene == null or not (scene is PackedScene):
				fail("%s can't load %s" % [name, entry["godot_scene"]])
				continue
			var node: Node = scene.instantiate()
			root.add_child(node)
			_scenes.append([name, node])
		if entry.has("attach") and characters.has(name):
			attach(name, base.path_join(entry["glb"]), characters[name], entry["attach"]["bone"])
	for style in _manifest.get("looks", {}):
		var look = load(_manifest["looks"][style])
		if look == null or not (look is PackedScene):
			fail("look kit %s doesn't load" % style)
			continue
		var kit: Node = look.instantiate()
		if kit.find_child("WorldEnvironment", true, false) == null or kit.find_child("Sun", true, false) == null:
			fail("look kit %s has no WorldEnvironment or Sun" % style)
		kit.free()


func _process(_delta: float) -> bool:
	_frames += 1
	if _frames < 3:
		return false
	for pair in _scenes:
		check_model(pair[0], pair[1])
	for item in _attached:
		check_attached(item[0], item[1], item[2], item[3])
	if _failures > 0:
		printerr("KILN_VERIFY_FAIL ", _failures, " problems")
		quit(1)
	else:
		print("KILN_VERIFY_OK ", _scenes.size(), " models")
		quit(0)
	return true


func attach(name: String, glb: String, character_path: String, bone: String) -> void:
	var character_scene = load(character_path)
	var attachment_scene = load(glb)
	if not (character_scene is PackedScene) or not (attachment_scene is PackedScene):
		fail("%s: can't load %s or %s" % [name, character_path, glb])
		return
	var character: Node3D = character_scene.instantiate()
	var skeleton: Skeleton3D = null
	for s in character.find_children("*", "Skeleton3D", true, false):
		skeleton = s
	if skeleton == null or skeleton.find_bone(bone) < 0:
		fail("%s: %s has no skeleton bone %s" % [name, character_path, bone])
		character.free()
		return
	var holder := BoneAttachment3D.new()
	holder.bone_name = bone
	skeleton.add_child(holder)
	holder.add_child(attachment_scene.instantiate())
	var alone: Node3D = attachment_scene.instantiate()
	root.add_child(character)
	root.add_child(alone)
	_attached.append([name, character, holder, alone])


# The meshes' box in `frame`'s space.
func bounds(meshes: Node, frame: Node3D) -> AABB:
	var box := AABB()
	var first := true
	for mesh_instance in meshes.find_children("*", "MeshInstance3D", true, false):
		if mesh_instance.mesh == null:
			continue
		var b: AABB = (frame.global_transform.affine_inverse() * mesh_instance.global_transform) * mesh_instance.mesh.get_aabb()
		box = b if first else box.merge(b)
		first = false
	return box


func check_attached(name: String, character: Node3D, holder: Node3D, alone: Node3D) -> void:
	# made in the character's space: the glb's root node undoes the bone, so on the bone it must be back where it was made
	var made := bounds(alone, alone.get_child(0))
	var landed := bounds(holder, character)
	var tolerance := 0.01 + 0.01 * made.size.length()
	if made.size == Vector3.ZERO or made.position.distance_to(landed.position) > tolerance or made.end.distance_to(landed.end) > tolerance:
		fail("%s on its bone lands at %s, made at %s (character space)" % [name, landed, made])


func check_library(name: String, glb: String, animations: Dictionary) -> void:
	var library = load(glb)
	if not (library is AnimationLibrary):
		fail("%s (animations_only) doesn't import as an AnimationLibrary: %s" % [name, glb])
		return
	for anim in animations:
		if not library.has_animation(anim):
			fail("%s library is missing animation %s" % [name, anim])
		elif (library.get_animation(anim).loop_mode != Animation.LOOP_NONE) != animations[anim]["loop"]:
			fail("%s library animation %s has the wrong loop" % [name, anim])


func check_model(name: String, node: Node) -> void:
	var entry: Dictionary = _manifest["models"][name]
	var skeleton: Skeleton3D = null
	for s in node.find_children("*", "Skeleton3D", true, false):
		skeleton = s
	for part in entry.get("parts", {}):
		var found := node.find_child(part, true, false) != null
		if not found and skeleton != null:
			found = skeleton.find_bone(part) >= 0
		if not found:
			fail("%s has no node or bone %s" % [name, part])
	for part in entry.get("parts", {}):
		if entry["parts"][part].has("revealed_by"):  # hidden until the game shows it
			var cap := node.find_child(entry.get("node_prefix", "") + part, true, false) as Node3D
			if cap == null or cap.is_visible_in_tree():
				fail("%s revealed part %s isn't hidden" % [name, part])
	var player: AnimationPlayer = node.find_child("AnimationPlayer", true, false)
	var animations: Dictionary = entry.get("animations", {})
	if entry.has("animation_library"):  # its clips are in the carrier's library (checked there)
		animations = {}
	for anim in animations:
		if player == null or not player.has_animation(anim):
			fail("%s is missing animation %s" % [name, anim])
			continue
		var looping: bool = player.get_animation(anim).loop_mode != Animation.LOOP_NONE
		if looping != animations[anim]["loop"]:
			fail("%s animation %s loop is %s" % [name, anim, looping])
	var surfaces := 0
	var textured := false
	for mesh_instance in node.find_children("*", "MeshInstance3D", true, false):
		if mesh_instance.mesh == null:
			continue
		for i in mesh_instance.mesh.get_surface_count():
			surfaces += 1
			var material = mesh_instance.get_surface_override_material(i)
			if material == null:
				fail("%s %s surface %d has no KILN material" % [name, mesh_instance.name, i])
			elif (material is BaseMaterial3D and material.albedo_texture != null) or (material is ShaderMaterial and material.get_shader_parameter("albedo_texture") != null):
				textured = true
	if surfaces == 0:
		fail("%s has no mesh surfaces" % name)
	if entry.has("atlas") and not textured:
		fail("%s has a palette atlas but no surface samples it" % name)
