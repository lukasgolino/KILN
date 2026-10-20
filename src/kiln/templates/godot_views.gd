# Run by `kiln preview --engine` (from a temp folder): renders a model scene under its look kit through Godot's real
# renderer, from several sides, into PNGs. Needs a display (not --headless).
# Args: scene, look kit, output folder, size, radius (m), centre y (m), then yaw:pitch pairs.
extends SceneTree

var _viewport: SubViewport
var _camera: Camera3D
var _views: Array = []
var _index := 0
var _wait := 0
var _out := ""
var _centre := Vector3.ZERO
var _distance := 1.0


func _init() -> void:
	var args := OS.get_cmdline_user_args()
	_out = args[2]
	var size := int(args[3])
	var radius := float(args[4])
	_centre = Vector3(0, float(args[5]), 0)
	_distance = radius * 4.0
	for pair in args.slice(6):
		var parts: PackedStringArray = pair.split(":")
		_views.append(Vector2(float(parts[0]), float(parts[1])))
	_viewport = SubViewport.new()
	_viewport.size = Vector2i(size, size)
	_viewport.msaa_3d = Viewport.MSAA_4X
	_viewport.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	root.add_child(_viewport)
	_viewport.add_child(load(args[1]).instantiate())
	_viewport.add_child(load(args[0]).instantiate())
	_camera = Camera3D.new()
	_camera.projection = Camera3D.PROJECTION_ORTHOGONAL
	_camera.size = radius * 2.2
	_camera.near = 0.01
	_camera.far = _distance * 3.0
	_viewport.add_child(_camera)
	_place(0)


func _place(i: int) -> void:
	var view: Vector2 = _views[i]
	var yaw := deg_to_rad(view.x)
	var pitch := deg_to_rad(view.y)
	var eye := _centre + _distance * Vector3(cos(pitch) * sin(yaw), sin(pitch), cos(pitch) * cos(yaw))
	var up := Vector3.UP if absf(view.y) < 89.0 else Vector3.FORWARD
	_camera.transform = Transform3D(Basis(), eye).looking_at(_centre, up)


func _process(_delta: float) -> bool:
	_wait += 1
	if _wait < 5:
		return false
	_viewport.get_texture().get_image().save_png("%s/engine_%02d.png" % [_out, _index])
	_index += 1
	_wait = 0
	if _index >= _views.size():
		print("KILN_VIEWS_OK ", _index)
		quit(0)
		return true
	_place(_index)
	return false
