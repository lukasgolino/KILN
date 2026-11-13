# Headless smoke test of the retro room: run it for 30 frames, then check every pedestal holds a model (as many as
# the manifest has), the player stands on the floor, and every look key (1 / 2 / 3, Tab) swaps in a look kit with
# a WorldEnvironment and the Retro pass, freeing the previous one.
# Run: godot --headless --path examples/retro_room/godot -s res://tests/check_room.gd (after --import)
extends SceneTree

var _scene: Node
var _frames := 0
var _problems := 0
var _placed := 0


func _init() -> void:
	_scene = load("res://scenes/room.tscn").instantiate()
	root.add_child(_scene)


func _fail(message: String) -> void:
	printerr("CHECK_FAIL ", message)
	_problems += 1


func _key(keycode: Key) -> void:
	var event := InputEventKey.new()
	event.keycode = keycode
	event.physical_keycode = keycode
	event.pressed = true
	root.push_input(event)


func _check_kit(what: String, style: String) -> void:
	var kit: Node = _scene.look_kit
	if kit == null:
		_fail("%s: no look kit" % what)
		return
	if str(kit.get_meta("kiln_style", "")) != style:
		_fail("%s: look kit %s, expected %s" % [what, kit.get_meta("kiln_style", "?"), style])
	if kit.find_child("WorldEnvironment", false, false) == null:
		_fail("%s: look kit %s has no WorldEnvironment" % [what, style])
	if kit.find_child("Retro", false, false) == null:
		_fail("%s: look kit %s has no Retro pass" % [what, style])


func _process(_delta: float) -> bool:
	_frames += 1
	if _frames == 30:
		_check_room()
	if _frames < 32:  # the kits replaced in _check_room are freed at the end of frame 30
		return false
	_check_kits_freed()
	return true


func _check_room() -> void:
	var manifest = JSON.parse_string(FileAccess.get_file_as_string("res://assets/kiln/manifest.json"))
	var expected: int = mini(manifest["models"].size(), 9)

	for pedestal in _scene.pedestals:
		if pedestal.get_node_or_null("Model") != null:
			_placed += 1
	if _scene.pedestals.size() != 9:
		_fail("%d pedestals, expected 9" % _scene.pedestals.size())
	if _placed != expected:
		_fail("%d models on pedestals, the manifest has %d" % [_placed, expected])
	var player: CharacterBody3D = _scene.get_node_or_null("Player")
	if player == null:
		_fail("no player")
	elif not player.is_on_floor() or absf(player.position.y) > 0.05:
		_fail("the player isn't standing on the floor (y = %.3f)" % player.position.y)
	var kits: Dictionary = manifest.get("looks", {})
	var styles := ["retro_st", "retro_cga", "retro_mono"]
	for i in styles.size():
		if not kits.has(styles[i]):
			_fail("the manifest has no %s look kit" % styles[i])
			continue
		_key(KEY_1 + i)
		_check_kit("key %d" % (i + 1), styles[i])
	_key(KEY_1)
	for i in _scene.looks.size():  # Tab: st -> cga -> mono -> st
		_key(KEY_TAB)
		_check_kit("Tab %d" % (i + 1), _scene.looks[(i + 1) % _scene.looks.size()][0])


func _check_kits_freed() -> void:
	var kits_in_scene := 0
	for child in _scene.get_children():
		if child.has_meta("kiln_style"):
			kits_in_scene += 1
	if kits_in_scene != 1:
		_fail("%d look kits in the room, expected 1" % kits_in_scene)
	if _problems:
		quit(1)
	else:
		print("CHECK_OK %d models on 9 pedestals, %d look kits, player on the floor" % [
				_placed, _scene.looks.size()])
		quit(0)
