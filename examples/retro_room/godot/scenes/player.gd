# First-person walker: WASD, Shift runs, mouse look with the mouse captured (Esc frees it, a click takes it back).
extends CharacterBody3D

const WALK := 3.0
const RUN := 6.0
const ACCELERATION := 12.0
const SENSITIVITY := 0.0025
const SPAWN := Vector3(0, 0.05, 6.3)  # near the south wall, facing the grid (-z)

var gravity: float = ProjectSettings.get_setting("physics/3d/default_gravity")
var _pitch := 0.0

@onready var _camera: Camera3D = $Camera


func _ready() -> void:
	position = SPAWN
	Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		rotate_y(-event.relative.x * SENSITIVITY)
		_pitch = clampf(_pitch - event.relative.y * SENSITIVITY, -1.45, 1.45)
		_camera.rotation.x = _pitch
	elif event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif event is InputEventKey and event.pressed and event.physical_keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE


func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y -= gravity * delta
	var input := Vector2(
		float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A)),
		float(Input.is_physical_key_pressed(KEY_S)) - float(Input.is_physical_key_pressed(KEY_W)))
	var direction := (transform.basis * Vector3(input.x, 0, input.y)).normalized()
	var speed := RUN if Input.is_physical_key_pressed(KEY_SHIFT) else WALK
	var horizontal := Vector2(velocity.x, velocity.z).lerp(
		Vector2(direction.x, direction.z) * speed, clampf(ACCELERATION * delta, 0, 1))
	velocity.x = horizontal.x
	velocity.z = horizontal.y
	move_and_slide()
