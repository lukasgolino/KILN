extends SceneTree
# Renders a model scene unshaded (its vertex colours or material colour as albedo, after the scene's own script ran)
# and prints the colour at the centre: `-s colour_probe.gd -- res://.../model.tscn`. Used by test_compat_colours.
func _init() -> void:
	var holder := Node3D.new()
	get_root().add_child(holder)
	var scene: Node3D = load(OS.get_cmdline_user_args()[0]).instantiate()
	holder.add_child(scene)
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
