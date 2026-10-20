shader_type spatial;
render_mode cull_front, unshaded;
uniform float width = 0.012;
void vertex() { VERTEX += NORMAL * width; }
void fragment() { ALBEDO = vec3(0.08, 0.06, 0.1); }
