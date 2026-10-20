extends SceneTree
var vp: SubViewport
var n := 0
var players: Array = []
func _init() -> void:
	vp = SubViewport.new()
	vp.size = Vector2i(1200, 500)
	vp.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(vp)
	var anims := ["", "walk", "walk", "wave"]
	var times := [0.0, 0.17, 0.5, 0.25]
	for i in 4:
		var node: Node3D = load("res://models/test/pilot.glb").instantiate()
		vp.add_child(node)
		node.position = Vector3(-2.25 + i * 1.5, 0, 0)
		var p: AnimationPlayer = node.find_child("AnimationPlayer", true, false)
		if anims[i] != "" and p:
			p.play(anims[i])
			p.seek(times[i], true)
			p.pause()
		if i == 0: print("anims: ", p.get_animation_list() if p else "none")
	var sun := DirectionalLight3D.new()
	sun.shadow_enabled = true
	sun.rotation_degrees = Vector3(-45, 30, 0)
	vp.add_child(sun)
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color("#bcd7f2")
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("#bcd7f2")
	env.ambient_light_energy = 0.7
	env.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	var w := WorldEnvironment.new()
	w.environment = env
	vp.add_child(w)
	var cam := Camera3D.new()
	cam.fov = 40
	vp.add_child(cam)
	cam.look_at_from_position(Vector3(0, 1.4, 4.2), Vector3(0, 0.6, 0))
func _process(_d: float) -> bool:
	n += 1
	if n < 6:
		return false
	vp.get_texture().get_image().save_png(OS.get_cmdline_user_args()[0])
	quit(0)
	return true
