# Dev panel (#369): F1 opens a column on the left to tune the look kit's Retro pass live (effect on/off, dither
# space, pattern, lines, pixel aspect, strength, palette) and the models' toon light bands, and to save the result as
# a KILN style + PAGAN palette in user://presets/. Switching kit (1 / 2 / 3, Tab) loads that kit's own settings.
extends CanvasLayer

signal toggled(open: bool)
signal snap_toggled(on: bool)

var patterns: Array = ["bayer4"]  # the kit's own list (its Retro script's PATTERNS), read in load_kit
var kit_style := "retro_st"  # the kit a saved preset extends

const MAX_COLOURS := 16
const KEYS := "0123456789abcdefghijklmnopqrstuvwxyz"
const PRESET_DIR := "user://presets/"
const PRESETS := [  # [label, colours]
	["Atari ST", ["#000000", "#242449", "#49496d", "#9292b6", "#ffffff", "#492400", "#924900", "#db9249",
			"#ffdbb6", "#004900", "#249224", "#92db49", "#002492", "#2492db", "#920000", "#ffdb00"]],
	["CGA", ["#000000", "#55ffff", "#ff55ff", "#ffffff"]],
	["mono", ["#000000", "#ffffff"]],
	["riso", ["#1b1f3b", "#f2e6c9"]],
	["LCD", ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"]],
	["blueprint", ["#0b3d91", "#e8f1ff"]],
	["neon", ["#000000", "#ff2e88", "#00e5ff", "#f9f871"]],
	["sunset", ["#1a1033", "#3b1f5c", "#6b2d6b", "#a83f63", "#e0605a", "#f59a5d", "#f7c873", "#fff3c4"]],
]

var retro: Node = null  # the look kit's Retro pass
var models: Array[Node] = []  # roots whose ShaderMaterials get the light bands
var palette := PackedColorArray()
var bands := 4

var effect: CheckButton
var space: OptionButton
var snap: CheckButton
var spaces: Array = ["screen"]  # the kit's own list (its Retro script's SPACES)
var space_hint: Label
var pattern: OptionButton
var lines: HSlider
var aspect: HSlider
var strength: HSlider
var bands_slider: HSlider
var preset: OptionButton
var count_label: Label
var swatches: GridContainer
var name_field: LineEdit
var save_status: Label

var _panel: PanelContainer


func _ready() -> void:
	layer = 120
	visible = false
	_build()


func is_open() -> bool:
	return visible


func set_open(open: bool) -> void:
	visible = open
	if open:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	else:
		var focus := get_viewport().gui_get_focus_owner()
		if focus != null:
			focus.release_focus()
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	toggled.emit(open)


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo and event.physical_keycode == KEY_F1:
		set_open(not visible)
		get_viewport().set_input_as_handled()


# --- building the column ---

func _build() -> void:
	_panel = PanelContainer.new()
	var box := StyleBoxFlat.new()
	box.bg_color = Color(0.05, 0.05, 0.08, 0.92)
	box.set_content_margin_all(10)
	_panel.add_theme_stylebox_override("panel", box)
	_panel.anchor_bottom = 1.0  # the left edge, under the HUD, down to the bottom: scrolls when it doesn't fit
	_panel.offset_left = 8
	_panel.offset_top = 108
	_panel.offset_right = 384
	_panel.offset_bottom = -8
	add_child(_panel)

	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_panel.add_child(scroll)
	var column := VBoxContainer.new()
	column.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	column.add_theme_constant_override("separation", 6)
	scroll.add_child(column)

	column.add_child(_heading("Look (F1 closes)"))
	effect = CheckButton.new()
	effect.text = "retro effect"
	effect.toggled.connect(func(on: bool) -> void:
		if retro != null:
			retro.set_enabled(on))
	column.add_child(_unfocused(effect))
	space = OptionButton.new()
	space.item_selected.connect(func(i: int) -> void:
		if retro != null and retro.has_method("set_space"):
			retro.set_space(spaces[i])
		_update_space_hint())
	column.add_child(_row("dither on", _unfocused(space)))
	snap = CheckButton.new()
	snap.text = "snap turning to pixels"
	snap.toggled.connect(func(on: bool) -> void: snap_toggled.emit(on))
	column.add_child(_unfocused(snap))
	space_hint = Label.new()
	space_hint.text = "world space reads best with the noise pattern"
	space_hint.add_theme_font_size_override("font_size", 12)
	space_hint.add_theme_color_override("font_color", Color("#f7c873"))
	space_hint.visible = false
	column.add_child(space_hint)

	pattern = OptionButton.new()
	pattern.item_selected.connect(func(i: int) -> void:
		if retro != null:
			retro.set_pattern(patterns[i])
		_update_space_hint())
	column.add_child(_row("pattern", _unfocused(pattern)))

	lines = _slider(column, "lines", 40, 480, 1, "%d", func(v: float) -> void:
		if retro != null:
			retro.set_lines(v))
	aspect = _slider(column, "pixel aspect", 0.5, 2.0, 0.01, "%.2f", func(v: float) -> void:
		if retro != null:
			retro.set_pixel_aspect(v))
	strength = _slider(column, "strength", 0.0, 1.0, 0.01, "%.2f", func(v: float) -> void:
		if retro != null:
			retro.set_strength(v))
	bands_slider = _slider(column, "light bands", 2, 8, 1, "%d", func(v: float) -> void:
		set_bands(int(v)))

	column.add_child(HSeparator.new())
	column.add_child(_heading("Palette"))
	preset = OptionButton.new()
	preset.add_item("custom")
	preset.set_item_disabled(0, true)
	for p in PRESETS:
		preset.add_item(p[0])
	preset.item_selected.connect(func(i: int) -> void:
		if i > 0:
			var colours := PackedColorArray()
			for hex in PRESETS[i - 1][1]:
				colours.append(Color(hex))
			set_palette(colours))
	column.add_child(_row("preset", _unfocused(preset)))

	var counts := HBoxContainer.new()
	var minus := _small_button("-", func() -> void:
		if palette.size() > 1:
			palette.resize(palette.size() - 1)
			set_palette(palette))
	var plus := _small_button("+", func() -> void:
		if palette.size() < MAX_COLOURS:
			palette.append(_random_colour())
			set_palette(palette))
	minus.name = "Minus"
	plus.name = "Plus"
	count_label = Label.new()
	count_label.custom_minimum_size.x = 90
	count_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	var randomise := _small_button("randomise all", randomise_all)
	randomise.name = "RandomiseAll"
	counts.add_child(minus)
	counts.add_child(count_label)
	counts.add_child(plus)
	counts.add_child(randomise)
	column.add_child(counts)

	swatches = GridContainer.new()
	swatches.columns = 4
	swatches.add_theme_constant_override("h_separation", 6)
	swatches.add_theme_constant_override("v_separation", 4)
	column.add_child(swatches)

	column.add_child(HSeparator.new())
	column.add_child(_heading("Save preset"))
	var save_row := HBoxContainer.new()
	name_field = LineEdit.new()
	name_field.placeholder_text = "name"
	name_field.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	name_field.text_submitted.connect(func(_t: String) -> void: save_preset(name_field.text))
	save_row.add_child(name_field)
	save_row.add_child(_small_button("save", func() -> void: save_preset(name_field.text)))
	column.add_child(save_row)
	save_status = Label.new()
	save_status.autowrap_mode = TextServer.AUTOWRAP_ARBITRARY
	save_status.custom_minimum_size.x = 340
	save_status.add_theme_font_size_override("font_size", 13)
	save_status.text = "into %s" % ProjectSettings.globalize_path(PRESET_DIR)
	column.add_child(save_status)


func _heading(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_color_override("font_color", Color("#f7c873"))
	return label


func _unfocused(control: Control) -> Control:  # keeps Tab and the number keys for switching kits
	control.focus_mode = Control.FOCUS_NONE
	return control


func _row(text: String, control: Control) -> HBoxContainer:
	var row := HBoxContainer.new()
	var label := Label.new()
	label.text = text
	label.custom_minimum_size.x = 100
	row.add_child(label)
	control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(control)
	return row


func _slider(column: VBoxContainer, text: String, low: float, high: float, step: float, shown: String,
		apply: Callable) -> HSlider:
	var slider := HSlider.new()
	slider.min_value = low
	slider.max_value = high
	slider.step = step
	slider.custom_minimum_size.x = 160
	var readout := Label.new()
	readout.custom_minimum_size.x = 48
	readout.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	slider.value_changed.connect(func(v: float) -> void:
		readout.text = shown % v
		apply.call(v))
	slider.changed.connect(func() -> void: readout.text = shown % slider.value)
	slider.set_meta("readout", readout)
	var row := _row(text, _unfocused(slider))
	row.add_child(readout)
	column.add_child(row)
	return slider


func _small_button(text: String, pressed: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.focus_mode = Control.FOCUS_NONE
	button.pressed.connect(pressed)
	return button


func _set_slider(slider: HSlider, value: float) -> void:
	slider.set_value_no_signal(value)
	var readout: Label = slider.get_meta("readout")
	readout.text = ("%d" if slider.step >= 1 else "%.2f") % slider.value


# --- the kit ---

## Points the panel at a new look kit's Retro pass and shows that kit's own settings.
func load_kit(kit_retro: Node) -> void:
	retro = kit_retro
	var settings: Dictionary = retro.get_settings() if retro != null else {}
	if retro != null:
		patterns = retro.get_script().get_script_constant_map().get("PATTERNS", patterns)
		kit_style = str(retro.get_parent().get_meta("kiln_style", kit_style))
	pattern.clear()
	for p in patterns:
		pattern.add_item(p)
	effect.set_pressed_no_signal(settings.get("enabled", true))
	effect.disabled = retro == null
	var has_space := retro != null and retro.has_method("set_space")
	space.disabled = not has_space
	space.tooltip_text = "" if has_space else "this kit's Retro pass has no set_space"
	if has_space:
		spaces = retro.get_script().get_script_constant_map().get("SPACES", spaces)
	space.clear()
	for s in spaces:
		space.add_item(s)
	if "world" in spaces and retro != null and retro.has_method("world_supported") and not retro.world_supported():
		space.set_item_disabled(spaces.find("world"), true)
		space.set_item_tooltip(spaces.find("world"), "world space needs the Forward+ renderer")
	space.select(maxi(spaces.find(str(settings.get("space", "screen"))), 0))
	_update_space_hint()
	pattern.select(maxi(patterns.find(str(settings.get("pattern", "bayer4"))), 0))
	_set_slider(lines, float(settings.get("lines", 200.0)))
	_set_slider(aspect, float(settings.get("pixel_aspect", 1.0)))
	_set_slider(strength, float(settings.get("strength", 1.0)))
	palette = settings.get("palette", PackedColorArray([Color.BLACK, Color.WHITE]))
	_show_palette()


## The models whose toon materials the light bands slider drives; reads the bands they have now.
func set_models(roots: Array[Node]) -> void:
	models = roots
	for material in _band_materials():
		bands = int(material.get_shader_parameter("bands"))
		break
	_set_slider(bands_slider, bands)


func _band_materials() -> Array[ShaderMaterial]:
	var found: Array[ShaderMaterial] = []
	for root in models:
		for node in root.find_children("*", "GeometryInstance3D", true, false):
			var candidates: Array[Material] = [(node as GeometryInstance3D).material_override]
			if node is MeshInstance3D:
				var mesh_instance := node as MeshInstance3D
				for i in mesh_instance.get_surface_override_material_count():
					candidates.append(mesh_instance.get_surface_override_material(i))
			for material in candidates:
				var shader_material := material as ShaderMaterial
				if shader_material != null and shader_material.shader != null and not found.has(shader_material) \
						and _has_uniform(shader_material.shader, "bands"):
					found.append(shader_material)
	return found


func _has_uniform(shader: Shader, uniform: String) -> bool:
	for entry in shader.get_shader_uniform_list():
		if entry["name"] == uniform:
			return true
	return false


func set_bands(value: int) -> void:
	bands = clampi(value, 2, 8)
	for material in _band_materials():
		material.set_shader_parameter("bands", bands)


# --- the palette ---

func set_palette(colours: PackedColorArray) -> void:
	palette = colours.slice(0, MAX_COLOURS)
	if retro != null:
		retro.set_palette(palette)
	_show_palette()


func randomise_all() -> void:
	for i in palette.size():
		palette[i] = _random_colour()
	set_palette(palette)


func randomise(index: int) -> void:
	palette[index] = _random_colour()
	set_palette(palette)


func _random_colour() -> Color:
	return Color(randf(), randf(), randf())


func _show_palette() -> void:
	count_label.text = "%d colours" % palette.size()
	preset.select(0)
	for i in PRESETS.size():
		if _same(palette, PRESETS[i][1]):
			preset.select(i + 1)
	for child in swatches.get_children():
		swatches.remove_child(child)
		child.queue_free()
	for i in palette.size():
		var cell := HBoxContainer.new()
		cell.add_theme_constant_override("separation", 1)
		var picker := ColorPickerButton.new()
		picker.color = palette[i]
		picker.edit_alpha = false
		picker.custom_minimum_size = Vector2(40, 26)
		picker.focus_mode = Control.FOCUS_NONE
		picker.color_changed.connect(func(colour: Color) -> void:
			palette[i] = Color(colour, 1.0)
			if retro != null:
				retro.set_palette(palette)
			preset.select(0))
		cell.add_child(picker)
		var again := _small_button("r", randomise.bind(i))
		again.tooltip_text = "randomise this colour"
		again.add_theme_font_size_override("font_size", 11)
		cell.add_child(again)
		swatches.add_child(cell)


func _same(colours: PackedColorArray, hexes: Array) -> bool:  # the same colours in any order (KILN sorts a kit's)
	if colours.size() != hexes.size():
		return false
	var mine: Array = []
	var theirs: Array = []
	for i in colours.size():
		mine.append(colours[i].to_html(false))
		theirs.append(Color(hexes[i]).to_html(false))
	mine.sort()
	theirs.sort()
	return mine == theirs


# --- saving ---

static func sanitise(text: String) -> String:
	var out := ""
	for c in text.strip_edges().to_lower():
		out += c if (c >= "a" and c <= "z") or (c >= "0" and c <= "9") or c == "_" or c == "-" else "_"
	out = out.lstrip("_-")  # palette and style names start with a letter or digit
	return out if out != "" else "custom"


static func _toml_float(value: float) -> String:
	var text := String.num(value, 4)
	return text if text.contains(".") else text + ".0"


## The style file: the current kit's style with this panel's [look] settings and the palette saved next to it.
func style_text(preset_name: String) -> String:
	var settings: Dictionary = retro.get_settings() if retro != null else {}
	return "\n".join([
		"description = \"%s: tuned in the retro room's dev panel\"" % preset_name,
		"extends = \"%s\"" % kit_style,
		"",
		"[look]",
		"post_palette = \"%s\"" % preset_name,
		"post_lines = %d" % roundi(float(settings.get("lines", lines.value))),
		"pixel_aspect = %s" % _toml_float(float(settings.get("pixel_aspect", aspect.value))),
		"dither = \"%s\"" % str(settings.get("pattern", patterns[pattern.selected])),
		"dither_strength = %s" % _toml_float(float(settings.get("strength", strength.value))),
		"dither_space = \"%s\"" % str(settings.get("space", "screen")),
		"toon_bands = %d" % bands,
		"",
	])


## The palette file, PAGAN format.
func palette_text(preset_name: String) -> String:
	var out := ["name: %s" % preset_name, "# Saved from the retro room's dev panel.", "colors:"]
	for i in palette.size():
		out.append("  \"%s\": { hex: \"#%s\", name: c%d }" % [KEYS[i], palette[i].to_html(false), i])
	out.append("")
	return "\n".join(out)


## Writes <name>.style.toml and <name>.pal.yaml into user://presets/ and copies the style to the clipboard.
## Returns the sanitised name ("" if a file couldn't be written).
func save_preset(raw_name: String) -> String:
	var preset_name := sanitise(raw_name)
	name_field.text = preset_name
	DirAccess.make_dir_recursive_absolute(PRESET_DIR)
	var style := style_text(preset_name)
	var written := [_write(PRESET_DIR + preset_name + ".style.toml", style),
			_write(PRESET_DIR + preset_name + ".pal.yaml", palette_text(preset_name))]
	var folder := ProjectSettings.globalize_path(PRESET_DIR)
	if false in written:
		save_status.text = "couldn't write into %s" % folder
		return ""
	DisplayServer.clipboard_set(style)
	save_status.text = "saved %s.style.toml + %s.pal.yaml in %s (style copied to the clipboard)" % [
			preset_name, preset_name, folder]
	print("dev panel: ", save_status.text)
	return preset_name


func _write(path: String, text: String) -> bool:
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		push_error("can't write %s: %s" % [path, error_string(FileAccess.get_open_error())])
		return false
	file.store_string(text)
	return true


func _update_space_hint() -> void:  # ordered patterns streak (moire) when fixed to the world; noise holds up
	if space_hint != null:
		space_hint.visible = spaces[space.selected] == "world" and patterns[pattern.selected] != "noise"
