# Curl-Noise for Procedural Fluid Flow — Bridson, Hourihan, Nordenstam (SIGGRAPH 2007)

**Citation:** Bridson, Robert (University of British Columbia); Hourihan, Jim (Tweak Films);
Nordenstam, Marcus (Double Negative). "Curl-Noise for Procedural Fluid Flow."
*ACM SIGGRAPH 2007 papers* (ACM Transactions on Graphics 26, 3). ACM, 2007.
**Links:** https://www.cs.ubc.ca/~rbridson/docs/bridson-siggraph2007-curlnoise.pdf · DOI: https://dl.acm.org/doi/10.1145/1275808.1276435
**Read:** full paper read verbatim (3 pages) on 2026-07-06.

## Claim (verbatim)

> "We offer an extremely simple approach to efficiently generating turbulent velocity fields
> based on Perlin noise, with a formula that is exactly incompressible (necessary for the
> characteristic look of everyday fluids), exactly respects solid boundaries ... and whose
> amplitude can be modulated in space as desired."

## Exact formulas

Velocity is the curl of a potential field ψ.

- **3D** (Eq. 1), ψ = (ψ1, ψ2, ψ3):
  `v(x,y,z) = ( ∂ψ3/∂y − ∂ψ2/∂z , ∂ψ1/∂z − ∂ψ3/∂x , ∂ψ2/∂x − ∂ψ1/∂y )`
- **2D** (Eq. 2), scalar ψ (the stream function; "its isocontours are the streamlines"):
  `v(x,y) = ( ∂ψ/∂y , −∂ψ/∂x )`
- **Divergence-free by identity:** `∇·∇× ≡ 0`, so `∇·v = 0` — "No sources or sinks
  ('gutters') are possible." (Plain Perlin-noise velocity fields have gutters where particles
  accumulate — the reason naive noise doesn't read as fluid.)
- Partial derivatives evaluated by **finite differences** with a very small displacement
  ("10⁻⁴ times smaller than the domain ... works fine in single precision").
- **Noise:** ψ = Perlin noise N(x); scale-relation: noise at length scale L gives "vortices of
  diameter approximately L and speeds up to approximately O(1/L)". Octave sums give
  turbulence "quite similar to *physical* turbulence" (Kolmogorov-style power-law falloff).
  Time-varying noise animates the field.
- **Modulation** (§2.3): modulate the *potential*, not the velocity —
  `v = ∇×(A(x) ψ(x))` stays divergence-free; `A(x)·v(x)` does not.
- **Boundaries** (§2.4, Eq. 3-4): ramp ψ to zero by distance to the boundary,
  `ψ_constrained(x) = ramp(d(x)/d0) ψ(x)` with the smooth quintic ramp
  `ramp(r) = 1 (r≥1); (15/8)r − (10/8)r³ + (3/8)r⁵ (|r|<1); −1 (r≤−1)`,
  making the boundary an isocontour of ψ so flow slips tangentially (inviscid `v·n = 0`),
  with `d0 = L` (the noise length scale). 3D variant Eq. 5 ramps only the tangential
  component of vector ψ.

## Relevance to Naomi

The exact tool for a *bounded* pool: set ψ = FBM noise ramped to zero at the pool rim →
interior motion is incompressible (reads as liquid, never as sliding texture) and provably
tangent to the rim — the water visibly *circulates inside its own edge*. Stateless closed-form
evaluation per pixel per frame: no simulation memory, deterministic, trivially parameterised
(noise frequency, octaves, gain, time speed = the emotion knobs).
