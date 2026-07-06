# Smooth Minimum (smin) for SDF blending — Inigo Quilez

**Citation:** Quilez, Inigo. "smooth minimum." iquilezles.org articles (rewritten edition
introducing normalization, kernels, circular smooth-min and blend-function analysis; original
article 2013, rewrite announced 2024-03-08).
**Links:** https://iquilezles.org/articles/smin/ · announcement: https://x.com/iquilezles/status/1765935148091261277
**Fetched:** 2026-07-06.

## What it is

The standard technique for organic/liquid blending of signed distance fields: instead of the
hard union `min(a, b)`, a smooth union that merges surfaces when they come within a
tolerance `k` of each other — the visual signature of surface tension, metaballs, and
liquid droplets merging.

## Exact formulas (GLSL, as published)

Quadratic polynomial (recommended default; C1 continuous, "CD" family):

```glsl
float smin( float a, float b, float k ) {
  k *= 4.0;
  float h = max( k-abs(a-b), 0.0 )/k;
  return min(a,b) - h*h*k*(1.0/4.0);
}
```

Cubic polynomial (C2 continuous):

```glsl
float smin( float a, float b, float k ) {
  k *= 6.0;
  float h = max( k-abs(a-b), 0.0 )/k;
  return min(a,b) - h*h*h*k*(1.0/6.0);
}
```

Exponential ("DD" family, order-independent for n-ary blends):

```glsl
float smin( float a, float b, float k ) {
  k *= 1.0;
  float r = exp2(-a/k) + exp2(-b/k);
  return -k*log2(r);
}
```

Circular:

```glsl
float smin( float a, float b, float k ) {
  k *= 1.0/(1.0-sqrt(0.5));
  float h = max( k-abs(a-b), 0.0 )/k;
  return min(a,b) - k*0.5*(1.0+h-sqrt(1.0-h*(h-2.0)));
}
```

`k` is normalized so it is "the thickness of the blended area, in actual distance units" —
i.e. a physical surface-tension radius. The smooth-minimum provides a "smooth, non-binary
transition between the values of a and b" when shapes are within tolerance k.

## Applied prior art

Codrops, "How to Create a Liquid Raymarching Scene Using Three.js Shading Language"
(tympanus.net, 2024-07-15) — a production tutorial building exactly the audio-orb genre of
liquid metaball blob with smin blending: https://tympanus.net/codrops/2024/07/15/how-to-create-a-liquid-raymarching-scene-using-three-js-shading-language/

## Relevance to Naomi

`smin` is how the pool behaves like *water with surface tension*: satellite droplets that
detach and re-merge smoothly during laughter/agitation, and a rim that necks and rejoins
like a liquid, not like a mask. `k` is directly an emotion parameter: high k = cohesive,
rounded, calm/happy; low k = tense surface that breaks — agitated.
