/**
 * The Naomi pool shader (docs/design/naomi-visual-brief.md §1): a single-pass
 * 2D signed-distance-field "pool" — ink-black blob on the white canvas, rim
 * displaced by FBM noise, interior advected along Bridson curl noise (stream
 * function ψ ramped to zero at the rim so the flow provably circulates
 * INSIDE the pool), quadratic Quilez smooth-minimum surface tension blending
 * the body with 0–4 transient satellite droplets that detach and re-merge.
 *
 * Stateless by contract: every frame is a pure function of the uniforms
 * (time, audio, physics) — no FBOs, no feedback, golden-frame testable.
 * Exported as GLSL ES 3.00 AND ES 1.00 variants sharing one body, so the
 * Tier 2 (WebGL1) fallback renders the identical design language.
 *
 * Monochrome discipline: ONLY brief inks appear — #0A0A0A base, #525252
 * currents at 8–14%, #EDEDED wet edge; background fully transparent so the
 * app's white canvas shows through. No bloom, no shadow, no color.
 */

// Shared GLSL body. `__FRAG_OUT__` is substituted per GLSL version.
const SHADER_BODY = /* glsl */ `
precision highp float;

uniform vec2  u_resolution;   // drawing buffer size, device px
uniform float u_poolRadiusPx; // device px per pool radius R=1
uniform float u_time;         // seconds; FROZEN under reduced motion
uniform vec4  u_audio;        // x env, y low band, z mid band, w high band
uniform float u_audioPulse;   // spectral-flux / word-boundary pulse 0..1
uniform vec4  u_flow;         // x flowSpeed, y rimFreq, z interiorFreq, w octaves
uniform vec4  u_shape;        // x rimAmp(effective), y smin k, z radiusBias, w restOffset
uniform vec4  u_pulseA;       // x breatheDepth, y bobDepth, z bobHz, w inwardBias
uniform vec4  u_pulseB;       // x ringDepth, y ringHz, z jitterAmp, w jitterHz
uniform vec2  u_droplet;      // x count (0..4), y burst seed
uniform float u_errorWeight;  // 0 normal .. 1 error state (2px rim, still pool)

// ---- Brief inks only (sRGB 0..1). Monochrome absolutism. ----
const vec3 INK      = vec3(0.039215687);  // #0A0A0A
const vec3 GREY_600 = vec3(0.321568627);  // #525252 interior currents
const vec3 GREY_200 = vec3(0.929411765);  // #EDEDED wet edge

// ---- Value noise + FBM (3–5 octaves; fractional last octave fades in) ----
float hash21(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash21(i);
  float b = hash21(i + vec2(1.0, 0.0));
  float c = hash21(i + vec2(0.0, 1.0));
  float d = hash21(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p, float octaves) {
  float value = 0.0;
  float amp = 0.5;
  float total = 0.0;
  for (int i = 0; i < 5; i++) {
    // Fractional octave weight keeps the field CONTINUOUS as the emotion
    // engine slides octaves between anchor states (never a visual pop).
    float w = clamp(octaves - float(i), 0.0, 1.0);
    value += amp * w * vnoise(p);
    total += amp * w;
    amp *= 0.5;
    p = p * 2.03 + vec2(19.7, 7.3);
  }
  return value / max(total, 1e-4);
}

// ---- SDF toolkit ----
float sdCircle(vec2 p, float r) { return length(p) - r; }

// Quilez quadratic polynomial smin — the liquid surface tension. k is the
// blend radius: high k = cohesive water, tiny k = tension breaks (agitated).
float smin(float a, float b, float k) {
  float h = max(k - abs(a - b), 0.0) / max(k, 1e-4);
  return min(a, b) - h * h * k * 0.25;
}

// Satellite droplet choreography: deterministic in (t, seed, index) — slow
// golden-angle orbits whose radial breathing carries them across the smin
// threshold, so they visibly detach and re-merge with the body.
vec2 dropletCenter(float fi, float t, float seed) {
  float ang = seed * 6.2831853 + fi * 2.3999632 + t * (0.22 + 0.06 * fi);
  float dist = 1.16 + 0.24 * sin(t * 0.55 + fi * 2.1 + seed * 9.0);
  return vec2(cos(ang), sin(ang)) * dist;
}
float dropletRadius(float fi, float t) {
  return 0.09 + 0.03 * sin(t * 0.9 + fi * 1.7);
}

// ---- The pool SDF: body + rim life + droplets ----
float poolDistance(vec2 p, float t) {
  // Body radius: bias × (breathe heartbeat + low-band audio swell).
  float breathe = u_pulseA.x * sin(t * 6.2831853 / 2.4); // 2400ms house beat
  float swell = 0.045 * u_audio.y;
  float r0 = u_shape.z * (1.0 + breathe + swell);
  vec2 pb = p;
  // Vertical bob (happy buoyancy) + rest offset (sad pool sits lower).
  pb.y -= u_pulseA.y * sin(t * 6.2831853 * u_pulseA.z) + u_shape.w;
  float d = sdCircle(pb, r0);

  // Laughter: concentric rings travelling outward at syllable rate.
  float ringPhase = 6.2831853 * (u_pulseB.y * t - length(pb) * 1.5);
  d -= u_pulseB.x * r0 * sin(ringPhase) * (0.5 + 0.5 * u_audioPulse);

  // Rim displacement: FBM along the rim direction (seamless — sampled on
  // the unit circle, never raw angle) with amplitude from emotion × audio.
  vec2 rimDir = pb / max(length(pb), 1e-4);
  float rim = fbm(rimDir * u_flow.y + vec2(0.0, t * (0.12 + 0.5 * u_flow.x)), u_flow.w);
  d += (rim - 0.5) * 2.0 * u_shape.x;

  // Agitation: irregular 8–12Hz micro-jitter, sharp higher harmonics.
  d += u_pulseB.z * (vnoise(rimDir * 7.0 + vec2(t * u_pulseB.w, 0.0)) - 0.5) * 2.0;

  // Droplets, blended with surface tension so necks form and snap.
  for (int i = 0; i < 4; i++) {
    float fi = float(i);
    if (fi < u_droplet.x - 0.5) {
      float dd = sdCircle(p - dropletCenter(fi, t, u_droplet.y), dropletRadius(fi, t));
      d = smin(d, dd, u_shape.y);
    }
  }
  return d;
}

// ---- Bridson curl-noise interior flow ----
// Stream function ψ = ramp(−d/d0)·fbm; the quintic ramp zeroes ψ at the rim
// so v = ∇×ψ is tangent there — water circulates inside its own boundary.
// WHY the un-displaced circle here: the ramp only needs the boundary
// location; skipping rim FBM keeps the finite-difference curl at 4 cheap
// evaluations without changing where the flow dies out.
float streamPsi(vec2 q, float t) {
  float dc = sdCircle(q, u_shape.z);
  float x = clamp(-dc / 0.35, 0.0, 1.0); // d0 = 0.35R noise length scale
  float r = x * x * x * (x * (x * 6.0 - 15.0) + 10.0); // quintic ramp
  return r * fbm(q * u_flow.z * 0.7 + vec2(0.0, t * (0.25 + u_flow.x)), min(u_flow.w, 3.0));
}
vec2 curlVelocity(vec2 q, float t) {
  float e = 1e-3; // brief: finite-difference curl, ε = 10⁻³
  float dpsidy = streamPsi(q + vec2(0.0, e), t) - streamPsi(q - vec2(0.0, e), t);
  float dpsidx = streamPsi(q + vec2(e, 0.0), t) - streamPsi(q - vec2(e, 0.0), t);
  return vec2(dpsidy, -dpsidx) / (2.0 * e); // v = (∂ψ/∂y, −∂ψ/∂x)
}

// ---- Interior shading: back-advected FBM → quantized grey bands ----
vec3 interiorColor(vec2 p, float t) {
  vec2 v = curlVelocity(p, t) * (2.2 * u_flow.x);
  v += u_pulseA.w * (-p); // thinking: slow radial-inward spiral bias
  vec2 q = p - v * 0.35;  // back-advection, τ = 0.35
  // Two curl layers at different scales/speeds = depth via motion parallax.
  float layerA = fbm(q * u_flow.z + vec2(0.0, t * 0.05), u_flow.w);
  float layerB = fbm(q * u_flow.z * 2.3 + vec2(1.7, -t * 0.035), u_flow.w);
  float currents = mix(layerA, layerB, 0.4);
  // Quantize into grey bands (the brief's shading language), softened so
  // band edges flow rather than crawl.
  float banded = mix(currents, floor(currents * 4.0) / 3.0, 0.55);
  // Currents render in #525252 at 8–14% mix; high band adds fine texture.
  float strength = (0.08 + 0.06 * clamp(u_audio.w + 0.4, 0.0, 1.0))
    * smoothstep(0.42, 0.85, banded);
  return mix(INK, GREY_600, strength);
}

// Premultiplied "over" compositing onto a transparent canvas.
void blendOver(inout vec4 acc, vec3 color, float alpha) {
  acc.rgb = color * alpha + acc.rgb * (1.0 - alpha);
  acc.a = alpha + acc.a * (1.0 - alpha);
}

void main() {
  float t = u_time;
  // Pool-local coordinates: |p| = 1 at the nominal rim.
  vec2 p = (gl_FragCoord.xy - 0.5 * u_resolution) / u_poolRadiusPx;
  float pixelLocal = 1.0 / u_poolRadiusPx; // one device pixel in R units

  float d = poolDistance(p, t);
  float aa = 1.25 * pixelLocal; // brief: anti-alias over 1.25 device px

  float fill = 1.0 - smoothstep(-aa, aa, d);
  // Meniscus rim line: 1.5px, thickening to 2px in the error state.
  float lineWidth = mix(1.5, 2.0, u_errorWeight) * pixelLocal;
  float meniscus = 1.0 - smoothstep(lineWidth - aa, lineWidth + aa, abs(d));
  // Faint wet edge just outside the rim, in #EDEDED on the white canvas.
  float wet = smoothstep(0.0, 0.015, d) * (1.0 - smoothstep(0.015, 0.12, d));

  vec4 acc = vec4(0.0);
  blendOver(acc, GREY_200, wet * 0.7);
  blendOver(acc, interiorColor(p, t), fill);
  blendOver(acc, INK, meniscus);
  __FRAG_OUT__ = acc;
}
`;

/** GLSL ES 3.00 fragment shader (Tier 1 — WebGL2). */
export const POOL_FRAGMENT_SHADER_ES300 =
  "#version 300 es\n" +
  SHADER_BODY.replace("__FRAG_OUT__", "fragColor").replace(
    "precision highp float;",
    "precision highp float;\nout vec4 fragColor;",
  );

/** GLSL ES 1.00 fragment shader (Tier 2 — WebGL1). Same body, gl_FragColor. */
export const POOL_FRAGMENT_SHADER_ES100 = SHADER_BODY.replace("__FRAG_OUT__", "gl_FragColor");

/** Full-screen triangle vertex shaders (one attribute; no index buffer). */
export const POOL_VERTEX_SHADER_ES300 =
  "#version 300 es\nin vec2 a_position;\nvoid main(){ gl_Position = vec4(a_position, 0.0, 1.0); }";
export const POOL_VERTEX_SHADER_ES100 =
  "attribute vec2 a_position;\nvoid main(){ gl_Position = vec4(a_position, 0.0, 1.0); }";

/** Clip-space full-screen triangle (covers the viewport with 3 vertices). */
export const FULLSCREEN_TRIANGLE_VERTICES = new Float32Array([-1, -1, 3, -1, -1, 3]);

/** Every uniform the renderer must locate — single source for both tiers. */
export const POOL_UNIFORM_NAMES = [
  "u_resolution",
  "u_poolRadiusPx",
  "u_time",
  "u_audio",
  "u_audioPulse",
  "u_flow",
  "u_shape",
  "u_pulseA",
  "u_pulseB",
  "u_droplet",
  "u_errorWeight",
] as const;

export type PoolUniformName = (typeof POOL_UNIFORM_NAMES)[number];
