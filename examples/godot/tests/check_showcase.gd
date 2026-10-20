# Headless smoke test: run the showcase scene for a second and check every model from the manifest is in it,
# animating where it has animations. Run: godot --headless --path examples/godot -s res://tests/check_showcase.gd
extends SceneTree

var _scene: Node
var _frames := 0


func _init() -> void:
	_scene = load("res://scenes/showcase.tscn").instantiate()
	root.add_child(_scene)


func _process(_delta: float) -> bool:
	_frames += 1
	if _frames < 30:
		return false
	var manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/kiln/manifest.json"))
	var problems := 0
	for name in manifest["models"]:
		var model: Node = _scene.get_node_or_null(NodePath(name))
		if model == null:
			printerr("CHECK_FAIL ", name, " isn't in the showcase")
			problems += 1
			continue
		if not manifest["models"][name]["animations"].is_empty():
			var player: AnimationPlayer = model.find_child("AnimationPlayer", true, false)
			if player == null or not player.is_playing():
				printerr("CHECK_FAIL ", name, " isn't animating")
				problems += 1
	if problems:
		quit(1)
	else:
		print("CHECK_OK ", manifest["models"].size(), " models")
		quit(0)
	return true
