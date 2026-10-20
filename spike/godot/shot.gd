extends SceneTree
var vp: SubViewport
var n := 0
var style := ""
func place(name: String, pos: Vector3, yaw: float) -> void:
	var node: Node3D = load("res://models/%s/%s.glb" % [style, name]).instantiate()
	vp.add_child(node)
	node.position = pos
	node.rotation_degrees = Vector3(0, yaw, 0)
	if style == "toon":
		for m in node.find_children("*", "MeshInstance3D", true, false):
			for i in m.mesh.get_surface_count():
				var src: BaseMaterial3D = m.mesh.surface_get_material(i)
				var mat := ShaderMaterial.new()
				mat.shader = load("res://toon.gdshader")
				mat.set_shader_parameter("albedo", src.albedo_color)
				var outline := ShaderMaterial.new()
				outline.shader = load("res://outline.gdshader")
				mat.next_pass = outline
				m.set_surface_override_material(i, mat)
func _init() -> void:
	var args := OS.get_cmdline_user_args()
	style = args[0]
	vp = SubViewport.new()
	vp.size = Vector2i(1920, 1080)
	vp.msaa_3d = Viewport.MSAA_4X
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(vp)
	place("wall", Vector3(-3.0, 0, -2.2), 0)
	place("trebuchet", Vector3(1.3, 0, -2.0), -60)
	place("tree", Vector3(3.9, 0, -1.6), 0)
	var x := -3.0
	for name in ["seat", "passenger", "pilot", "knight", "archer", "barrel"]:
		place(name, Vector3(x, 0, 1.2), -10)
		x += 1.2
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(60, 60)
	ground.mesh = plane
	var gm := StandardMaterial3D.new()
	gm.albedo_color = Color("#a9c48f")
	gm.roughness = 0.95
	ground.material_override = gm
	vp.add_child(ground)
	var sun := DirectionalLight3D.new()
	sun.shadow_enabled = true
	sun.light_energy = 1.1
	sun.rotation_degrees = Vector3(-48, 30, 0)
	vp.add_child(sun)
	var env := Environment.new()
	var sky := Sky.new()
	var sm := ProceduralSkyMaterial.new()
	sm.sky_top_color = Color("#4f8fe0")
	sm.sky_horizon_color = Color("#bcd7f2")
	sm.ground_horizon_color = Color("#bcd7f2")
	sm.ground_bottom_color = Color("#9fb98a")
	sky.sky_material = sm
	env.background_mode = Environment.BG_SKY
	env.sky = sky
	env.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	env.ambient_light_energy = 0.9 if style != "toon" else 0.6
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.ssao_enabled = style != "toon"
	env.ssao_intensity = 1.5
	env.glow_enabled = style == "soft_toy"
	env.adjustment_enabled = true
	env.adjustment_saturation = 1.15
	var w := WorldEnvironment.new()
	w.environment = env
	vp.add_child(w)
	var cam := Camera3D.new()
	cam.fov = 42
	vp.add_child(cam)
	cam.look_at_from_position(Vector3(0.2, 3.2, 7.6), Vector3(0.2, 0.9, -0.4))
func _process(_d: float) -> bool:
	n += 1
	if n < 10:
		return false
	vp.get_texture().get_image().save_png(OS.get_cmdline_user_args()[1])
	print("SHOT_OK")
	quit(0)
	return true
