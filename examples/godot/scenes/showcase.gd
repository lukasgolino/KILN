# The KILN demo: every model from the manifest in a row on a turntable, playing its animations, under the
# look kit of its style. Built by `kiln build` in examples/demo.
extends Node3D

const MANIFEST := "res://assets/kiln/manifest.json"
var models: Array[Node3D] = []


func _ready() -> void:
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	var looks: Dictionary = manifest.get("looks", {})
	if not looks.is_empty():
		add_child(load(looks.values()[0]).instantiate())
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


func _process(delta: float) -> void:
	for model in models:
		model.rotate_y(delta * 0.4)
