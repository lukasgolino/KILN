// Signac paint (exploratory): the surface painted in dabs of pure pigment fixed to the world. Each dab is one palette
// colour for good; neighbouring dabs mix in the eye to the surface's colour (its own colour under a fixed sun, shadows
// leaning violet). Per pixel the target colour is split into the two palette colours whose mix matches it best,
// preferring contrasting pairs (paint_contrast); each dab takes one of them by its own random number, a few take the
// complementary colour (paint_accent). Where dabs shrink under a couple of pixels they fade to their mixed colour.
shader_type spatial;
render_mode unshaded, specular_disabled;

uniform vec4 albedo : source_color = vec4(1.0);
uniform bool use_vertex_color = true;

global uniform float paint_dab;  // dab spacing, metres
global uniform float paint_contrast;  // 0: nearest colours; higher: contrasting pairs (yellow + blue for green)
global uniform float paint_accent;  // share of complementary dabs (more in the shade)
global uniform float paint_shadow;  // shadows lean violet
global uniform float paint_light;  // 0 flat colour, 1 the fixed sun
global uniform float paint_lift;
global uniform float paint_value;  // keep both pigments near the target's value (Signac: same value, different hue)  // towards white
global uniform float paint_round;  // dab corner rounding
global uniform float paint_turn;  // random dab turn, radians
global uniform float paint_blend;  // fade small dabs to their mix (0 never)

const int N = 16;
const vec3 PAL[16] = vec3[16](  // sRGB: Signac's pure pigments and their tints with white
	vec3(0.992, 0.973, 0.925),  // white
	vec3(1.000, 0.851, 0.180),  // cadmium yellow
	vec3(1.000, 0.941, 0.604),  // yellow tint
	vec3(1.000, 0.541, 0.122),  // orange
	vec3(0.910, 0.263, 0.165),  // vermilion
	vec3(1.000, 0.690, 0.561),  // vermilion tint
	vec3(0.910, 0.353, 0.549),  // rose madder
	vec3(0.969, 0.702, 0.816),  // rose tint
	vec3(0.541, 0.310, 0.769),  // violet
	vec3(0.780, 0.651, 0.937),  // violet tint
	vec3(0.184, 0.247, 0.722),  // ultramarine
	vec3(0.247, 0.498, 0.851),  // cobalt
	vec3(0.612, 0.816, 0.961),  // cerulean tint
	vec3(0.122, 0.639, 0.478),  // emerald
	vec3(0.561, 0.878, 0.690),  // emerald tint
	vec3(0.718, 0.851, 0.290)   // yellow green
);

const vec3 LUMA = vec3(0.2126, 0.7152, 0.0722);

varying vec3 world_pos;
varying vec3 world_normal;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	world_normal = normalize((MODEL_MATRIX * vec4(NORMAL, 0.0)).xyz);
}

vec3 lin(vec3 c) {
	return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c));
}

vec4 hash4(vec2 p) {
	vec4 q = vec4(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)), dot(p, vec2(419.2, 371.9)), dot(p, vec2(87.3, 215.1)));
	return fract(sin(q) * 43758.5453);
}

// < 1 inside dab (h, k rolled per dab): a slightly irregular, rounded rectangle.
float dab_shape(vec2 d, vec4 h, vec4 k) {
	float a = 0.4 + (h.x - 0.5) * 2.0 * paint_turn;
	vec2 r = vec2(cos(a) * d.x + sin(a) * d.y, -sin(a) * d.x + cos(a) * d.y);
	r.x += (k.x - 0.5) * 0.3 * r.y;
	float half_len = 0.68 * (1.0 + 0.3 * h.y);
	float half_wid = 0.68 * (1.0 - 0.15 * h.y) * (1.0 + (k.y - 0.5) * 0.3 * r.x / half_len);
	vec2 u = abs(r) / vec2(half_len, max(half_wid, 0.05));
	float n = mix(16.0, 2.5, clamp(paint_round * (0.6 + 0.8 * k.z), 0.0, 1.0));
	return pow(pow(u.x, n) + pow(u.y, n), 1.0 / n);
}

void fragment() {
	vec3 n = normalize(world_normal);
	vec3 an = abs(n);
	vec2 plane;
	float axis;
	if (an.x > an.y && an.x > an.z) {
		plane = world_pos.zy; axis = 1.0;
	} else if (an.y > an.z) {
		plane = world_pos.xz; axis = 2.0;
	} else {
		plane = world_pos.xy; axis = 3.0;
	}
	vec2 q = plane / max(paint_dab, 0.002) + axis * 37.0;
	float footprint = sqrt(length(dFdx(q)) * length(dFdy(q)));  // geometric mean: grazing surfaces keep their dabs longer  // dab cells per pixel

	// the colour to paint: the surface's own, under a fixed sun, shadows leaning violet, lifted
	vec3 base = albedo.rgb * (use_vertex_color ? COLOR.rgb : vec3(1.0));
	float sun = max(dot(n, normalize(vec3(0.45, 0.8, 0.35))), 0.0);
	vec3 target = base * mix(1.0, 0.35 + 0.85 * sun, paint_light);
	float luma = dot(target, vec3(0.2126, 0.7152, 0.0722));
	vec3 violet = vec3(0.25, 0.15, 0.85);
	violet *= luma / dot(violet, vec3(0.2126, 0.7152, 0.0722));
	float shade = clamp(1.0 - sun * 1.5, 0.0, 1.0) * paint_shadow;
	target = mix(target, violet, shade * 0.6);
	target = mix(target, vec3(1.0), paint_lift);

	// split it into two pigments whose mix matches it (linear light: how the eye averages)
	vec3 pal[16];
	for (int i = 0; i < N; i++) {
		pal[i] = lin(PAL[i]);
	}
	float best = 1e9;
	int bi = 0;
	int bj = 0;
	float bt = 0.0;
	for (int i = 0; i < N; i++) {
		for (int j = i + 1; j < N; j++) {
			vec3 s = pal[j] - pal[i];
			float t = clamp(dot(target - pal[i], s) / max(dot(s, s), 1e-6), 0.0, 1.0);
			vec3 e = sqrt(target) - sqrt(pal[i] + s * t);  // error near-perceptual (gamma 2): no dark + light for a mid
			vec3 hue = (PAL[j] - dot(PAL[j], vec3(0.333))) - (PAL[i] - dot(PAL[i], vec3(0.333)));  // chroma difference only
			float lt = sqrt(dot(target, LUMA));
			float li = sqrt(dot(pal[i], LUMA)) - lt;
			float lj = sqrt(dot(pal[j], LUMA)) - lt;
			float score = dot(e, e) + paint_value * (li * li * (1.0 - t) + lj * lj * t) - paint_contrast * 0.1 * dot(hue, hue) * t * (1.0 - t) * 4.0;
			if (score < best) {
				best = score; bi = i; bj = j; bt = t;
			}
		}
	}
	vec3 mixed = mix(pal[bi], pal[bj], bt);

	// which dab covers this pixel (dabs overlap their cells; a random one lies on top)
	vec2 base_cell = floor(q);
	float top = -1.0;
	vec4 dab = hash4(base_cell);
	vec4 dab_k = hash4(base_cell + vec2(57.0, 113.0));
	for (int y = -1; y <= 1; y++) {
		for (int x = -1; x <= 1; x++) {
			vec2 cell = base_cell + vec2(float(x), float(y));
			vec4 h = hash4(cell);
			vec4 k = hash4(cell + vec2(57.0, 113.0));
			vec2 centre = cell + 0.5 + (h.zw - 0.5) * 0.7;
			if (dab_shape(q - centre, h, k) < 1.0 && k.w > top) {
				top = k.w; dab = h; dab_k = k;
			}
		}
	}
	float u = fract(dab.z * 7.13 + dab.w * 3.71);
	vec3 colour = u < bt ? pal[bj] : pal[bi];
	if (fract(dab_k.w * 13.7) < paint_accent * (0.4 + shade)) {
		vec3 complement = vec3(max(max(target.r, target.g), target.b) + min(min(target.r, target.g), target.b)) - target;
		float near = 1e9;
		for (int i = 0; i < N; i++) {
			vec3 e = pal[i] - complement;
			if (dot(e, e) < near) {
				near = dot(e, e); colour = pal[i];
			}
		}
	}
	ALBEDO = mix(colour, mixed, smoothstep(0.5, 1.0, footprint) * paint_blend);
}
