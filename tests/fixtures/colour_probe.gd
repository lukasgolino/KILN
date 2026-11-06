extends SceneTree
# Colour checks for test_compat_colours, run offscreen (tools/godot_window.sh):
#   -s colour_probe.gd -- pixel res://a.tscn [res://b.tscn ...]: the other scenes are instanced (their scripts run) and
#     hidden first, then a.tscn is rendered unshaded (vertex colours, else the material colour, as albedo after the
#     scene's own script ran) and the colour at the centre printed.
#   -s colour_probe.gd -- bytes res://scatter.tscn: the first vertex colour bytes of every MultiMesh's mesh (every LOD).
func _init() -> void:
	var args := OS.get_cmdline_user_args()
	var holder := Node3D.new()
	get_root().add_child(holder)
	for extra in args.slice(2):
		var other: Node3D = load(extra).instantiate()
		holder.add_child(other)
		other.visible = false
	var scene: Node3D = load(args[1]).instantiate()
	holder.add_child(scene)
	for i in 4:
		await process_frame
	if args[0] == "bytes":
		for node in scene.find_children("*", "MultiMeshInstance3D", true, false):
			var mesh := (node as MultiMeshInstance3D).multimesh.mesh
			for s in mesh.get_surface_count():
				var surface := RenderingServer.mesh_get_surface(mesh.get_rid(), s)
				var format: int = surface["format"]
				if format & Mesh.ARRAY_FORMAT_COLOR:
					var at := RenderingServer.mesh_surface_get_format_offset(format, surface["vertex_count"], Mesh.ARRAY_COLOR)
					var data: PackedByteArray = surface["attribute_data"]
					print("KILN_BYTES ", node.name, " ", data[at], ",", data[at + 1], ",", data[at + 2])
		quit()
		return
	for node in scene.find_children("*", "MeshInstance3D", true, false):
		var mesh_instance := node as MeshInstance3D
		for i in mesh_instance.mesh.get_surface_count():
			var flat := StandardMaterial3D.new()
			flat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
			var source := mesh_instance.mesh.surface_get_material(i) as BaseMaterial3D
			if mesh_instance.mesh.surface_get_format(i) & Mesh.ARRAY_FORMAT_COLOR:
				flat.vertex_color_use_as_albedo = true
			elif source != null:
				flat.albedo_color = source.albedo_color
			mesh_instance.set_surface_override_material(i, flat)
	var camera := Camera3D.new()
	camera.position = Vector3(0, 0.3, 1.2)
	holder.add_child(camera)
	camera.current = true
	for i in 4:
		await process_frame
	var image := get_root().get_texture().get_image()
	print("KILN_PROBE ", image.get_pixel(image.get_width() / 2, image.get_height() / 2).to_html(false))
	quit()
