# First-person walker: WASD, Shift runs, mouse look with the mouse captured (Esc frees it, a click takes it back).
# While the dev panel is open (`frozen`) the mouse stays free and the view doesn't turn.
extends CharacterBody3D

const WALK := 3.0
const RUN := 6.0
const ACCELERATION := 12.0
const SENSITIVITY := 0.0025
const SPAWN := Vector3(0, 0.05, 6.3)  # near the south wall, facing the grid (-z)

var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")
var _pitch := 0.0
var _yaw := 0.0
var snap_pixels := false  # the dev panel's "snap turning to pixels": the view turns in steps of one low-res pixel
var snap_lines := 200.0  # the retro pass's lines (the step is one block's angle on screen)
var snap_aspect := 1.0  # the retro pass's pixel aspect (a block's width over its height)
var frozen := false  # the dev panel is open: the mouse is free and doesn't turn the view

@onready var _camera: Camera3D = $Camera


func _ready() -> void:
	position = SPAWN
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if frozen:
		return
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		_yaw -= event.relative.x * SENSITIVITY
		_pitch = clampf(_pitch - event.relative.y * SENSITIVITY, -1.45, 1.45)
		_turn()
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif event is InputEventKey and event.pressed and event.physical_keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


## Applies the mouse's yaw and pitch; with snap_pixels in whole steps of one low-res pixel's angle at the screen
## centre (the mouse still adds up smoothly), so the image steps cleanly instead of resampling every frame.
func _turn() -> void:
	var yaw := _yaw
	var pitch := _pitch
	if snap_pixels and snap_lines > 0.0:
		var half := tan(deg_to_rad(_camera.fov) / 2.0)
		var step := 2.0 * atan(half / snap_lines)
		yaw = snappedf(yaw, step * snap_aspect)
		pitch = snappedf(pitch, step)
	rotation.y = yaw
	_camera.rotation.x = pitch


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= gravity * delta
	var typing := get_viewport().gui_get_focus_owner() is LineEdit  # naming a preset in the dev panel
	var input := Vector2.ZERO if typing else Vector2(
		float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)),
		float(Input.is_physical_key_pressed(KEY_S)) - float(Input.is_physical_key_pressed(KEY_W)))
	var direction := (transform.basis * Vector3(input.x, 0, input.y)).normalized()
	var speed := RUN if Input.is_physical_key_pressed(KEY_SHIFT) else WALK
	var horizontal := Vector2(velocity.x, velocity.z).lerp(
		Vector2(direction.x, direction.z) * speed, clampf(ACCELERATION * delta, 0, 1))
	velocity.x = horizontal.x
	velocity.z = horizontal.y
	move_and_slide()
