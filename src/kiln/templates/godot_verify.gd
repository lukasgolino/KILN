# Run by `kiln build --verify-godot` (from a temp folder): loads every model KILN built and checks it against the
# manifest: the .glb and .tscn load, part nodes (or skeleton bones) exist, animations exist with the right loop
# flag, and every surface gets the style's material once the scene is ready.
extends SceneTree

var _manifest: Dictionary = {}
var _scenes: Array = []
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
	for name in _manifest["models"]:
		var entry: Dictionary = _manifest["models"][name]
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
	if _failures > 0:
		printerr("KILN_VERIFY_FAIL ", _failures, " problems")
		quit(1)
	else:
		print("KILN_VERIFY_OK ", _scenes.size(), " models")
		quit(0)
	return true


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
	var player: AnimationPlayer = node.find_child("AnimationPlayer", true, false)
	var animations: Dictionary = entry.get("animations", {})
	for anim in animations:
		if player == null or not player.has_animation(anim):
			fail("%s is missing animation %s" % [name, anim])
			continue
		var looping: bool = player.get_animation(anim).loop_mode != Animation.LOOP_NONE
		if looping != animations[anim]["loop"]:
			fail("%s animation %s loop is %s" % [name, anim, looping])
	var surfaces := 0
	for mesh_instance in node.find_children("*", "MeshInstance3D", true, false):
		if mesh_instance.mesh == null:
			continue
		for i in mesh_instance.mesh.get_surface_count():
			surfaces += 1
			if mesh_instance.get_surface_override_material(i) == null:
				fail("%s %s surface %d has no KILN material" % [name, mesh_instance.name, i])
	if surfaces == 0:
		fail("%s has no mesh surfaces" % name)
