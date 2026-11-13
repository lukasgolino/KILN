# Headless smoke test of the retro room: run it for 30 frames, then check every pedestal holds a model (as many as
# the manifest has), the player stands on the floor, and every look key (1 / 2 / 3, Tab) swaps in a look kit with
# a WorldEnvironment and the Retro pass, freeing the previous one. Each model's size and place on its pedestal, and a
# walk: W held for a second moves the player forward and keeps it inside the walls. The dev panel (F1): pattern,
# lines, palette count, randomise, effect off / on and light bands reach the Retro pass and the models, a kit switch
# loads the new kit's settings, and Save preset writes the style and palette files.
# Run: godot --headless --path examples/retro_room/godot -s res://tests/check_room.gd (after --import)
extends SceneTree

var _scene: Node
var _frames := 0
var _problems := 0
var _placed := 0
var _walk_from := Vector3.ZERO


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
		_check_models()
		_hold_w(true)
	if _frames == 32:  # the kits replaced in _check_room are freed at the end of frame 30
		_check_kits_freed()
		_check_panel()
	if _frames < 90:
		return false
	_hold_w(false)
	_check_walk()
	if _problems:
		quit(1)
	else:
		print("CHECK_OK %d models on 9 pedestals (size and place checked), %d look kits, player on the floor, walks, dev panel" % [
				_placed, _scene.looks.size()])
		quit(0)
	return true


func _hold_w(down: bool) -> void:
	var player: Node3D = _scene.get_node("Player")
	if down:
		_walk_from = player.global_position
	var event := InputEventKey.new()
	event.physical_keycode = KEY_W
	event.keycode = KEY_W
	event.pressed = down
	Input.parse_input_event(event)


func _check_walk() -> void:
	var player: Node3D = _scene.get_node("Player")
	var moved := player.global_position - _walk_from
	if moved.z > -1.0:
		_fail("holding W for a second moved the player %.2f m forward, expected over 1 m" % -moved.z)
	var half: Vector3 = _scene.ROOM / 2.0
	if absf(player.global_position.x) > half.x or absf(player.global_position.z) > half.z:
		_fail("the player left the room: %s" % player.global_position)


func _model_box(model: Node3D) -> AABB:
	var box := AABB()
	var first := true
	for mesh_instance in model.find_children("*", "MeshInstance3D", true, false):
		var mi := mesh_instance as MeshInstance3D
		if mi.mesh == null:
			continue
		var local := mi.mesh.get_aabb()
		for i in 8:
			var corner: Vector3 = mi.global_transform * local.get_endpoint(i)
			if first:
				box = AABB(corner, Vector3.ZERO)
				first = false
			else:
				box = box.expand(corner)
	return box


func _check_models() -> void:
	var top: float = _scene.PEDESTAL.y
	for pedestal in _scene.pedestals:
		var model: Node3D = pedestal.get_node_or_null("Model")
		if model == null:
			continue
		var box := _model_box(model)
		var largest := maxf(box.size.x, maxf(box.size.y, box.size.z))
		var centre := box.get_center()
		var at: Vector3 = pedestal.global_position
		if absf(largest - _scene.MODEL_SIZE) > 0.1:
			_fail("%s is %.2f m at its largest, expected %.2f" % [pedestal.name, largest, _scene.MODEL_SIZE])
		if absf(box.position.y - top) > 0.06:
			_fail("%s: its model's bottom is at %.3f m, the pedestal top at %.2f" % [pedestal.name, box.position.y, top])
		if absf(centre.x - at.x) > _scene.PEDESTAL.x / 2 or absf(centre.z - at.z) > _scene.PEDESTAL.z / 2:
			_fail("%s: its model's centre %s is off the pedestal at %s" % [pedestal.name, centre, at])


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


func _retro() -> Node:
	return _scene.look_kit.get_node("Retro")


func _settings_say(what: String, key: String, expected) -> void:
	var got = _retro().get_settings()[key]
	var same: bool = is_equal_approx(float(got), float(expected)) if expected is float or expected is int else got == expected
	if not same:
		_fail("dev panel %s: Retro's %s is %s, expected %s" % [what, key, got, expected])


func _check_panel() -> void:
	var panel: CanvasLayer = _scene.panel
	if panel == null:
		_fail("no dev panel")
		return
	_key(KEY_F1)
	if not panel.is_open() or not _scene.get_node("Player").frozen:
		_fail("F1 didn't open the dev panel (or the player still turns)")

	panel.pattern.select(3)
	panel.pattern.item_selected.emit(3)
	_settings_say("pattern", "pattern", "halftone")
	panel.lines.value = 321
	_settings_say("lines", "lines", 321.0)
	if panel.lines.get_meta("readout").text != "321":
		_fail("dev panel: the lines readout says %s" % panel.lines.get_meta("readout").text)
	panel.aspect.value = 1.5
	_settings_say("pixel aspect", "pixel_aspect", 1.5)
	panel.strength.value = 0.4
	_settings_say("strength", "strength", 0.4)

	panel.preset.select(2)  # CGA (item 0 is "custom")
	panel.preset.item_selected.emit(2)
	_settings_say("preset CGA", "palette", PackedColorArray([Color("#000000"), Color("#55ffff"), Color("#ff55ff"), Color("#ffffff")]))
	var plus: Button = panel.find_child("Plus", true, false)
	var minus: Button = panel.find_child("Minus", true, false)
	plus.pressed.emit()
	plus.pressed.emit()
	if _retro().get_settings()["palette"].size() != 6:
		_fail("dev panel: + + on 4 colours gave %d" % _retro().get_settings()["palette"].size())
	minus.pressed.emit()
	if _retro().get_settings()["palette"].size() != 5 or panel.swatches.get_child_count() != 5:
		_fail("dev panel: - gave %d colours, %d swatches" % [_retro().get_settings()["palette"].size(),
				panel.swatches.get_child_count()])
	var before: PackedColorArray = _retro().get_settings()["palette"]
	panel.find_child("RandomiseAll", true, false).pressed.emit()
	var after: PackedColorArray = _retro().get_settings()["palette"]
	if after.size() != 5 or after == before:
		_fail("dev panel: randomise all didn't change the palette")
	panel.randomise(0)
	if _retro().get_settings()["palette"][0] == after[0] or _retro().get_settings()["palette"].slice(1) != after.slice(1):
		_fail("dev panel: randomising swatch 0 didn't change only colour 0")

	panel.effect.button_pressed = false
	_settings_say("effect off", "enabled", false)
	panel.effect.button_pressed = true
	_settings_say("effect on", "enabled", true)
	if panel.space.disabled == _retro().has_method("set_space"):
		_fail("dev panel: the dither space toggle is %s, the kit %s set_space" % [
				"disabled" if panel.space.disabled else "enabled", "has" if _retro().has_method("set_space") else "lacks"])

	panel.bands_slider.value = 6
	var band_materials: Array = panel._band_materials()
	if band_materials.is_empty():
		_fail("dev panel: no model material has a bands parameter")
	for material in band_materials:
		if material.get_shader_parameter("bands") != 6:
			_fail("dev panel: a model material has bands %s, expected 6" % material.get_shader_parameter("bands"))
			break

	var saved: String = panel.save_preset("Check Room!")
	if saved != "check_room_":
		_fail("dev panel: preset name sanitised to %s, expected check_room_" % saved)
	if panel.sanitise("__-Neon") != "neon" or panel.sanitise("!!") != "custom":
		_fail("dev panel: names must start with a letter or digit (got %s, %s)" % [panel.sanitise("__-Neon"), panel.sanitise("!!")])
	var style_path := "user://presets/%s.style.toml" % saved
	var palette_path := "user://presets/%s.pal.yaml" % saved
	if not FileAccess.file_exists(style_path) or not FileAccess.file_exists(palette_path):
		_fail("dev panel: Save preset didn't write %s and %s" % [style_path, palette_path])
	else:
		var style := FileAccess.get_file_as_string(style_path)
		for key in ['extends = "retro_st"', "[look]", 'post_palette = "check_room_"', "post_lines = 321",
				"pixel_aspect = 1.5", 'dither = "halftone"', "dither_strength = 0.4", "toon_bands = 6"]:
			if not style.contains(key):
				_fail("dev panel: the saved style lacks %s:\n%s" % [key, style])
		var palette := FileAccess.get_file_as_string(palette_path)
		if not palette.begins_with("name: check_room_\n") or not palette.contains('"4": { hex: "#') or palette.contains('"5"'):
			_fail("dev panel: the saved palette isn't 5 PAGAN colours:\n%s" % palette)
		DirAccess.remove_absolute(style_path)
		DirAccess.remove_absolute(palette_path)

	_key(KEY_2)  # CGA: the panel shows that kit's own settings
	var cga: Dictionary = _retro().get_settings()
	if panel.lines.value != float(cga["lines"]) or panel.palette != cga["palette"] \
			or panel.patterns[panel.pattern.selected] != cga["pattern"]:
		_fail("dev panel: after key 2 it shows lines %s / %d colours, the CGA kit has %s / %d" % [
				panel.lines.value, panel.palette.size(), cga["lines"], cga["palette"].size()])
	if is_equal_approx(float(cga["lines"]), 321.0):
		_fail("dev panel: the CGA kit came up with the ST kit's tuned lines")
	_key(KEY_1)
	if is_equal_approx(float(_retro().get_settings()["lines"]), 321.0):
		_fail("dev panel: the ST kit came back with the tuned lines, expected its own")
	_key(KEY_F1)
	if panel.is_open() or _scene.get_node("Player").frozen:
		_fail("F1 didn't close the dev panel")
