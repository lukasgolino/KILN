# The retro room (#362): a closed room with the manifest's models on a 3x3 grid of pedestals, walked through in
# first person. 1 / 2 / 3 pick a look kit (Atari ST colour, CGA, ST mono), Tab cycles them; F1 opens the dev panel
# (scenes/dev_panel.gd) to tune the look live.
extends Node3D

const MANIFEST := "res://assets/kiln/manifest.json"
const ROOM := Vector3(14, 4, 14)  # inside size, metres; the floor is at y = 0
const WALL := 0.4  # wall, floor and ceiling thickness (outside the room)
const PEDESTAL := Vector3(1.4, 0.8, 1.4)
const SPACING := 4.0
const MODEL_SIZE := 1.1  # each model's largest dimension on its pedestal
const LOOKS := [  # [style, label], in key order
	["retro_st", "Atari ST colour"],
	["retro_cga", "CGA"],
	["retro_mono", "Atari ST mono"],
]
const HINT := "WASD walk · Shift run · mouse look · Esc frees the mouse\n1 / 2 / 3 or Tab: look · F1: tune the look"

const FLOOR_COLOUR := Color("#242449")
const WALL_COLOUR := Color("#b6b6db")
const CEILING_COLOUR := Color("#000000")
const PEDESTAL_COLOUR := Color("#6d6d92")  # floor dark, pedestals mid, walls light: they stay apart in 2-colour mono

var looks: Array = []  # [style, label, res path], the styles the manifest has a kit for
var look_index := -1
var look_kit: Node = null
var pedestals: Array[Node3D] = []
var panel: CanvasLayer = null

@onready var _label: Label = $Hud/Label


func _ready() -> void:
	var manifest = JSON.parse_string(FileAccess.get_file_as_string(MANIFEST))
	if manifest == null:
		push_error("no manifest at %s: run kiln build in ../art" % MANIFEST)
		manifest = {"models": {}, "looks": {}}
	var kits: Dictionary = manifest.get("looks", {})
	for look in LOOKS:
		if kits.has(look[0]):
			looks.append([look[0], look[1], kits[look[0]]])
	_build_room()
	_place_models(manifest["models"])
	panel = preload("res://scenes/dev_panel.gd").new()
	panel.name = "DevPanel"
	add_child(panel)
	var models: Array[Node] = []
	for pedestal in pedestals:
		var model := pedestal.get_node_or_null("Model")
		if model != null:
			models.append(model)
	panel.set_models(models)
	panel.toggled.connect(func(open: bool) -> void: $Player.frozen = open)
	show_look(0)


func _box(size: Vector3, centre: Vector3, colour: Color, node_name: String) -> StaticBody3D:
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = centre
	var mesh := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = size
	var material := StandardMaterial3D.new()
	material.albedo_color = colour
	material.roughness = 0.9
	box.material = material
	mesh.mesh = box
	body.add_child(mesh)
	var collider := CollisionShape3D.new()
	var shape := BoxShape3D.new()
	shape.size = size
	collider.shape = shape
	body.add_child(collider)
	add_child(body)
	return body


func _build_room() -> void:
	var outer := Vector3(ROOM.x + 2 * WALL, ROOM.y + 2 * WALL, ROOM.z + 2 * WALL)
	_box(Vector3(outer.x, WALL, outer.z), Vector3(0, -WALL / 2, 0), FLOOR_COLOUR, "Floor")
	_box(Vector3(outer.x, WALL, outer.z), Vector3(0, ROOM.y + WALL / 2, 0), CEILING_COLOUR, "Ceiling")
	_box(Vector3(outer.x, ROOM.y, WALL), Vector3(0, ROOM.y / 2, -(ROOM.z + WALL) / 2), WALL_COLOUR, "WallNorth")
	_box(Vector3(outer.x, ROOM.y, WALL), Vector3(0, ROOM.y / 2, (ROOM.z + WALL) / 2), WALL_COLOUR, "WallSouth")
	_box(Vector3(WALL, ROOM.y, ROOM.z), Vector3(-(ROOM.x + WALL) / 2, ROOM.y / 2, 0), WALL_COLOUR, "WallWest")
	_box(Vector3(WALL, ROOM.y, ROOM.z), Vector3((ROOM.x + WALL) / 2, ROOM.y / 2, 0), WALL_COLOUR, "WallEast")
	for row in 3:
		for column in 3:
			var at := Vector3((column - 1) * SPACING, 0, (row - 1) * SPACING)
			pedestals.append(_box(PEDESTAL, at + Vector3(0, PEDESTAL.y / 2, 0), PEDESTAL_COLOUR,
					"Pedestal%d" % pedestals.size()))
			# The look kit's sun can't get past the ceiling: a lamp over every pedestal instead.
			var lamp := OmniLight3D.new()
			lamp.name = "Lamp%d" % (pedestals.size() - 1)
			lamp.position = at + Vector3(0.6, ROOM.y - 0.6, 0.9)
			lamp.omni_range = 6.0
			lamp.light_energy = 1.6
			lamp.shadow_enabled = false
			add_child(lamp)


func _place_models(models: Dictionary) -> void:
	var names: Array = models.keys()
	names.sort()
	for i in mini(names.size(), pedestals.size()):
		var entry: Dictionary = models[names[i]]
		var model: Node3D = load(entry["godot_scene"]).instantiate()
		model.name = "Model"
		var size: Array = entry["size"]
		var largest: float = maxf(float(size[0]), maxf(float(size[1]), float(size[2])))
		if largest > 0:
			model.scale = Vector3.ONE * (MODEL_SIZE / largest)
		model.position = Vector3(0, PEDESTAL.y / 2, 0)  # the pedestal's top, in its frame
		model.set_meta("kiln_model", names[i])
		pedestals[i].add_child(model)
	if names.size() > pedestals.size():
		push_warning("%d models, %d pedestals: the rest aren't shown" % [names.size(), pedestals.size()])


func show_look(index: int) -> void:
	if looks.is_empty():
		_label.text = "no look kits in the manifest\n" + HINT
		return
	look_index = posmod(index, looks.size())
	if look_kit != null:
		look_kit.queue_free()
	look_kit = load(looks[look_index][2]).instantiate()
	var retro := look_kit.get_node_or_null("Retro")
	add_child(look_kit)
	if panel != null:
		panel.load_kit(retro)
	_label.text = "%s\n%s" % [looks[look_index][1], HINT]


func _unhandled_input(event: InputEvent) -> void:
	if not (event is InputEventKey and event.pressed and not event.echo):
		return
	match event.physical_keycode:
		KEY_1, KEY_2, KEY_3:
			var style: String = LOOKS[event.physical_keycode - KEY_1][0]
			for i in looks.size():
				if looks[i][0] == style:
					show_look(i)
		KEY_TAB:
			show_look(look_index + 1)
