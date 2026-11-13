# The KILN demo: every model from the manifest in a row on a turntable, playing its animations, under the
# look kit of its style. Built by `kiln build` in examples/demo. L cycles the look kits (soft_toy, then the retro
# looks the demo's kiln.toml `looks` builds: Atari ST colour, CGA, ST mono).
extends Node3D

const MANIFEST := "res://assets/kiln/manifest.json"
var models: Array[Node3D] = []
var looks: Array = []  # res:// paths, the models' style first
var look_index := 0
var look_kit: Node = null


func _ready() -> void:
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	var kits: Dictionary = manifest.get("looks", {})
	var first_style := ""
	if not manifest["models"].is_empty():
		first_style = str(manifest["models"].values()[0].get("style", ""))
	if kits.has(first_style):
		looks.append(kits[first_style])
	var others: Array = kits.keys()
	others.sort()
	for style in others:
		if style != first_style:
			looks.append(kits[style])
	_show_look(0)
	var names: Array = manifest["models"].keys()
	names.sort()
	var x := 0.0
	for name in names:
		var entry: Dictionary = manifest["models"][name]
		var model: Node3D = load(entry["godot_scene"]).instantiate()
		model.name = name
		var size: Array = entry["size"]
		var spacing: float = maxf(1.6, maxf(float(size[0]), float(size[2])) + 0.6)
		model.position = Vector3(x + spacing / 2.0, 0, 0)
		x += spacing
		add_child(model)
		models.append(model)
		var player: AnimationPlayer = model.find_child("AnimationPlayer", true, false)
		if player != null and not entry["animations"].is_empty():
			var first: String = entry["animations"].keys()[0]
			player.play(first)
			if not entry["animations"][first]["loop"]:
				player.animation_finished.connect(func(_n): player.play(first))
	var ground := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	plane.size = Vector2(80, 80)
	ground.mesh = plane
	var material := StandardMaterial3D.new()
	material.albedo_color = Color("#a9c48f")
	material.roughness = 0.95
	ground.material_override = material
	add_child(ground)
	for model in models:  # centre the row on 0
		model.position.x -= x / 2.0
	var camera := Camera3D.new()
	camera.fov = 40
	add_child(camera)
	camera.look_at_from_position(Vector3(0, x * 0.32, x * 0.85), Vector3(0, 1.0, 0))


func _show_look(index: int) -> void:
	if looks.is_empty():
		return
	look_index = index % looks.size()
	if look_kit != null:
		look_kit.queue_free()
	look_kit = load(looks[look_index]).instantiate()
	add_child(look_kit)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.keycode == KEY_L:
		_show_look(look_index + 1)


func _process(delta: float) -> void:
	for model in models:
		model.rotate_y(delta * 0.4)
