shader_type spatial;
render_mode specular_disabled;
uniform vec4 albedo : source_color = vec4(1.0);
void fragment() { ALBEDO = albedo.rgb; }
void light() {
	float n = dot(NORMAL, LIGHT);
	float band = n > 0.35 ? 1.0 : (n > -0.1 ? 0.6 : 0.35);
	DIFFUSE_LIGHT += vec3(band) * ATTENUATION * LIGHT_COLOR;
}
