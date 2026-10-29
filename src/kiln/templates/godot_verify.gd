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
	_manifest["_base"] = base
	var characters: Dictionary = {}
	if args.size() > 1:
		characters = JSON.parse_string(FileAccess.get_file_as_string(args[1]))
	for name in _manifest["models"]:
		var entry: Dictionary = _manifest["models"][name]
		if entry.has("scatter"):  # instances of other models: no glb of its own
			if entry.has("godot_scene"):
				var packed = load(entry["godot_scene"])
				if not (packed is PackedScene):
					fail("%s can't load %s" % [name, entry["godot_scene"]])
					continue
				var holder: Node = packed.instantiate()
				root.add_child(holder)
				_scenes.append([name, holder])
			continue
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
	if entry.has("scatter"):
		check_scatter(name, node, entry)
		return
	var skeleton: Skeleton3D = null
	for s in node.find_children("*", "Skeleton3D", true, false):
		skeleton = s
	for part in entry.get("parts", {}):
		var found := node.find_child(part, true, false) != null
		if not found and skeleton != null:
			found = skeleton.find_bone(part) >= 0
		if not found and skeleton != null and entry.has("godot_bonemap"):  # Godot renamed the bone to the profile's
			var profile: String = "Root" if part == "root" else entry.get("humanoid", {}).get(part, {}).get("godot", "")
			found = profile != "" and skeleton.find_bone(profile) >= 0
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
	if entry.has("terrain"):
		check_terrain(name, node, entry["terrain"])


# A terrain: its splat shader compiles (the dummy renderer parses shaders: a broken one has no uniforms), its LODs are
# instanced, and its HeightMapShape3D has the grid's size and puts the ground where KILN has it (rays at the probes).
func check_terrain(name: String, node: Node, terrain: Dictionary) -> void:
	var material = node.get("material")
	if not (material is ShaderMaterial) or material.shader == null or material.shader.get_shader_uniform_list().size() < 5:
		fail("%s splat shader doesn't compile" % name)
	for k in terrain["lod_distances"].size() + 1:
		if node.get_node_or_null("lod%d" % k) == null:
			fail("%s has no lod%d" % [name, k])
	if terrain.get("collision") == null:
		return
	var holder := node.get_node_or_null("Collision/Shape") as CollisionShape3D
	if holder == null or not (holder.shape is HeightMapShape3D):
		fail("%s has no HeightMapShape3D" % name)
		return
	var shape := holder.shape as HeightMapShape3D
	if shape.map_width != int(terrain["collision"]["samples"][0]) or shape.map_depth != int(terrain["collision"]["samples"][1]):
		fail("%s HeightMapShape3D is %dx%d, not %s" % [name, shape.map_width, shape.map_depth, terrain["collision"]["samples"]])
	var space := (node as Node3D).get_world_3d().direct_space_state
	for probe in terrain["probes"]:
		var at := Vector3(probe[0], probe[2], probe[1])
		var hit := space.intersect_ray(PhysicsRayQueryParameters3D.create(at + Vector3.UP * 100.0, at + Vector3.DOWN * 100.0))
		if hit.is_empty() or absf(hit["position"].y - at.y) > 0.02:
			fail("%s collision at (%s, %s) is %s, not %s" % [name, probe[0], probe[1], hit.get("position", "no hit"), probe[2]])


# The transform of `node` relative to `top` (outside the tree: its parents' transforms multiplied).
func relative(node: Node, top: Node) -> Transform3D:
	var t := Transform3D()
	var at := node
	while at != null and at != top:
		if at is Node3D:
			t = (at as Node3D).transform * t
		at = at.get_parent()
	return t


func near(a: Transform3D, b: Transform3D) -> bool:
	return a.origin.distance_to(b.origin) < 0.002 and (a.basis.x - b.basis.x).length() < 0.002 and (a.basis.y - b.basis.y).length() < 0.002 \
		and (a.basis.z - b.basis.z).length() < 0.002


# A scatter: every group's chunks (and the LODs the script adds) are MultiMeshes with their model's mesh and materials
# and exactly the instances of the scatter JSON (count, transform times the mesh's place in the model, tint colour).
func check_scatter(name: String, node: Node, entry: Dictionary) -> void:
	var base: String = _manifest.get("_base", "")
	var data = JSON.parse_string(FileAccess.get_file_as_string(base.path_join(entry["scatter"])))
	if typeof(data) != TYPE_DICTIONARY:
		fail("%s can't read %s" % [name, entry["scatter"]])
		return
	var checked := 0
	for group in data["groups"]:
		var holder := node.get_node_or_null(NodePath(group["node"]))
		if holder == null:
			fail("%s has no group %s" % [name, group["node"]])
			continue
		var source: Dictionary = _manifest["models"].get(group["model"], {})
		var origin := Vector3.ZERO
		if source.has("origin"):
			origin = Vector3(source["origin"][0], source["origin"][1], source["origin"][2])
		var model = load(group["godot_scene"])
		if not (model is PackedScene):
			fail("%s can't load %s" % [name, group["godot_scene"]])
			continue
		var made: Node = model.instantiate()
		var mesh_node: Node = null
		for found in made.find_children("*", "MeshInstance3D", true, false):
			if found.mesh != null and mesh_node == null:
				mesh_node = found
		if mesh_node == null:
			fail("%s: %s has no mesh" % [name, group["model"]])
			made.free()
			continue
		var frame := Transform3D(Basis(), origin) * relative(mesh_node, made)
		made.free()
		var lods: int = group["lod_distances"].size() + 1
		var tinted: bool = group.has("colors")
		for chunk in group["chunks"]:
			for lod in lods:
				var path: String = chunk["node"] if lod == 0 else "%s_lod%d" % [chunk["node"], lod]
				var mmi := holder.get_node_or_null(NodePath(path)) as MultiMeshInstance3D
				if mmi == null or mmi.multimesh == null:
					fail("%s %s has no MultiMeshInstance3D %s" % [name, group["node"], path])
					continue
				var mm := mmi.multimesh
				if mm.mesh == null or mm.mesh.get_surface_count() == 0:
					fail("%s %s/%s has no mesh" % [name, group["node"], path])
					continue
				for i in mm.mesh.get_surface_count():
					var material := mm.mesh.surface_get_material(i)
					if material == null:
						fail("%s %s/%s surface %d has no material" % [name, group["node"], path, i])
					elif tinted and material is BaseMaterial3D and not (material as BaseMaterial3D).vertex_color_use_as_albedo:
						fail("%s %s/%s surface %d ignores instance colours" % [name, group["node"], path, i])
				var far: float = group["visible"] if lod + 1 == lods else group["lod_distances"][lod]
				var near_end: float = 0.0 if lod == 0 else group["lod_distances"][lod - 1]
				if absf(mmi.visibility_range_end - far) > 0.001 or absf(mmi.visibility_range_begin - near_end) > 0.001:
					fail("%s %s/%s shows from %s to %s m, not %s to %s" % [name, group["node"], path, mmi.visibility_range_begin, mmi.visibility_range_end, near_end, far])
				if mm.instance_count != int(chunk["count"]):
					fail("%s %s/%s has %d instances, not %d" % [name, group["node"], path, mm.instance_count, chunk["count"]])
					continue
				if mm.use_colors != tinted:
					fail("%s %s/%s use_colors is %s" % [name, group["node"], path, mm.use_colors])
				# the buffer Godot holds (the dummy renderer keeps it, though get_instance_transform reads identity there):
				# per instance the 3 x 4 transform row by row, then RGBA with use_colors
				var buffer := mm.buffer
				var stride := 16 if tinted else 12
				if buffer.size() != stride * mm.instance_count:
					fail("%s %s/%s buffer holds %d floats, not %d" % [name, group["node"], path, buffer.size(), stride * mm.instance_count])
					continue
				for i in mm.instance_count:
					var t: Array = group["instances"][int(chunk["first"]) + i]
					var placed := Transform3D(Basis(Vector3(t[3], t[4], t[5]), Vector3(t[6], t[7], t[8]), Vector3(t[9], t[10], t[11])), Vector3(t[0], t[1], t[2]))
					var o := i * stride
					var got_t := Transform3D(Basis(Vector3(buffer[o], buffer[o + 4], buffer[o + 8]), Vector3(buffer[o + 1], buffer[o + 5], buffer[o + 9]),
						Vector3(buffer[o + 2], buffer[o + 6], buffer[o + 10])), Vector3(buffer[o + 3], buffer[o + 7], buffer[o + 11]))
					if not near(got_t, placed * frame):
						fail("%s %s/%s instance %d is at %s, not %s" % [name, group["node"], path, i, got_t, placed * frame])
						break
					if tinted:
						var c: Array = group["colors"][int(chunk["first"]) + i]
						var got := Color(buffer[o + 12], buffer[o + 13], buffer[o + 14], buffer[o + 15])
						if absf(got.r - c[0]) > 0.002 or absf(got.g - c[1]) > 0.002 or absf(got.b - c[2]) > 0.002:
							fail("%s %s/%s instance %d colour is %s, not %s" % [name, group["node"], path, i, got, c])
							break
					checked += 1
	if checked == 0 and data["groups"].size() > 0:
		fail("%s: no instances checked" % name)
